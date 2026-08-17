"""RTMP 推流模块：EVB 推流 + PC 端 ffprobe 实时探测 + 可选 ffplay 画面确认。

流程：
- setup: 确定 pc_ip（自动检测或配置），创建 RtmpReceiver（ffprobe）+ ffplay 句柄
- run: 前置压制 FTP 崩溃刷屏 -> 检查 nginx-rtmp 就绪 -> ``rtmp_video_start <url>``
       (exec_async，不依赖哨兵) -> 等推流上线 -> 可选起 ffplay 看画面 ->
       ffprobe 实时探测流（★ 主判据）-> ``rtmp_video_stop`` -> 停 ffplay
- teardown: 停止 ffplay 进程（兜底）

只依赖 WiFi（推流需网络），不依赖 FTP。

推流命令用 exec_async 而非 exec_sync：photo/video 后固件 FTP 常陷入
"service go wrong" 崩溃循环刷屏，会打乱 exec_sync 的哨兵定界导致必败。
exec_async 不依赖哨兵，真正成败判据交给 PC 端 ffprobe 是否探测到流。

★ 关键时序：ffprobe 探测必须在 ``rtmp_video_stop`` **之前**——探测的是实时流，
stop 后流断开探测必失败。这与 MediaMTX 时代"先 stop 再 verify 存盘文件"相反。
"""
import os
import time
import signal
import subprocess

from .base import TestModule, register
from ..core import logger
from ..core.result import Timer
from ..drivers.rtmp_receiver import RtmpReceiver
from ..drivers.rtmp_server import RtmpServer, RtmpServerError


def _detect_pc_ip(target_ip: str) -> str:
    """通过"连接 target_ip"获取本机与 target_ip 通信的接口 IP。

    不会真正发数据，仅让 OS 选路并返回本端地址。
    """
    if not target_ip:
        return ""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target_ip, 1935))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ""


def _find_ffplay(preferred=None) -> str:
    """查找 ffplay 可执行文件。顺序：preferred -> PATH -> 常见绝对路径。"""
    import shutil
    if preferred and (shutil.which(preferred) or os.path.isfile(preferred)):
        return preferred
    p = shutil.which("ffplay")
    if p:
        return p
    for cand in ("/usr/bin/ffplay", "/usr/local/bin/ffplay",
                 os.path.expanduser("~/bin/ffplay")):
        if os.path.isfile(cand):
            return cand
    return ""


# 终端模拟器候选：用于在独立终端窗口跑 ffplay 画面确认
_TERMINAL_CANDIDATES = [
    "gnome-terminal", "xterm", "konsole", "xfce4-terminal",
    "terminator", "mate-terminal", "lxterminal",
]


def _find_terminal() -> str:
    """查找可用的终端模拟器，返回其路径或空串。"""
    import shutil
    for t in _TERMINAL_CANDIDATES:
        p = shutil.which(t)
        if p:
            return p
    return ""


@register("rtmp")
class RtmpModule(TestModule):
    """RTMP 推流测试。"""

    depends = ["wifi_join"]

    def __init__(self, config):
        super().__init__(config)
        self._receiver = None
        self._server = None
        self._ffplay_proc = None
        self._ffplay_path = None
        self._ffplay_log = None        # ffplay stderr 日志文件句柄（仅 subprocess 直启方式用）
        self._ffplay_in_terminal = False  # 是否用独立终端窗口启动 ffplay
        self._ffplay_active = False    # 本次是否成功启动了 ffplay（终端或直启）

    def setup(self, ctx, console):
        evb_ip = getattr(ctx, "evb_ip", None)
        pc_ip = self.config.get("pc_ip", "auto")
        if pc_ip in ("auto", "", None):
            pc_ip = _detect_pc_ip(evb_ip) if evb_ip else ""
            if pc_ip:
                logger.info(f"自动检测到 PC IP: {pc_ip}")
        if not pc_ip:
            logger.warn("未能确定 PC IP，RTMP 推流可能失败")
        ctx.pc_ip = pc_ip

        # ffprobe 实时探测器（★ 主判据：探测到视频流编码/分辨率即 PASS）
        self._receiver = RtmpReceiver(
            ffprobe_path=self.config.get("ffprobe_path", "ffprobe"),
        )
        # RTMP 服务端（nginx-rtmp）：仅检查就绪，nginx 由用户/系统手动启动。
        self._server = RtmpServer(port=1935)
        # ffplay 画面确认（可选）：无 DISPLAY 时自动跳过
        self._ffplay_path = _find_ffplay(self.config.get("ffplay_path", "ffplay"))

    def run(self, ctx, console):
        pc_ip = getattr(ctx, "pc_ip", "")
        if not pc_ip:
            return self._fail("无法确定 PC IP，RTMP 推流目标未知")

        # 1. 检查 nginx-rtmp 服务端就绪（1935 监听）。未启动直接 FAIL 提示手动启动。
        try:
            self._server.check_ready()
        except RtmpServerError as e:
            return self._fail(f"RTMP 服务端未就绪: {e}")

        # 2. 不再发 ftp_server 前置压制：rtmp 不依赖 FTP，且主动重发 ftp_server 会
        # 再次触发固件 FTP 崩溃循环（每次重启新建 ftp 线程、旧线程 suspend 不回收），
        # 线程堆积吃满 CPU，反而拖慢编码与推流（见 devBugLog 记录）。推流命令用
        # exec_async 不依赖哨兵，刷屏不影响成败判据（判据是 PC 端 ffprobe）。

        timer = Timer().start()
        url = self.config.get("stream_url", "rtmp://{pc_ip}/live/cam").format(pc_ip=pc_ip)
        duration = int(self.config.get("stream_duration", 10))

        logger.step(f"  RTMP 推流测试: {url} / {duration}s")

        # 3. EVB 开始推流（先于探测启动）。
        # 用 exec_async：发命令后直接等推流相关输出，不依赖被 FTP 刷屏打乱的
        # 哨兵定界。expect 用宽松正则仅用于尽快返回，不作为成败判据——真正判据
        # 是 PC 端 ffprobe 探测到流。即便 exec_async 没匹配到也不立即 FAIL，留给
        # ffprobe 兜底。注：必须先推流后探测——ffprobe 连无流的源会立即 I/O error。
        console.exec_async(
            f"rtmp_video_start {url}",
            expect=r"rtmp_video_start|RTMP|push|start",
            result_timeout=8.0,
        )

        # 4. 等推流上线（给 EVB 建连 + 首帧时间）
        time.sleep(3.0)

        # 5. 画面确认：优先在独立终端窗口跑 ffplay（窗口生命周期独立，用户可从容看画面）。
        # 有 DISPLAY + 终端模拟器时开新终端；否则回退 subprocess 直启（teardown killpg）。
        # 无 DISPLAY 或无 ffplay 则跳过。
        self._ffplay_active = False
        if os.environ.get("DISPLAY") and self._ffplay_path:
            terminal = _find_terminal()
            if terminal:
                self._ffplay_in_terminal = True
                self._ffplay_active = self._launch_ffplay_terminal(url, terminal)
            else:
                self._ffplay_in_terminal = False
                self._ffplay_active = self._launch_ffplay_direct(url)
        else:
            if not os.environ.get("DISPLAY"):
                logger.info("无 DISPLAY 环境变量，跳过 ffplay 画面确认（无人值守/SSH 常见）")
            elif not self._ffplay_path:
                logger.warn("未找到 ffplay，跳过画面确认（判据仍由 ffprobe 给出）")

        # 6. ffprobe 实时探测 RTMP 流（★ 主判据，带重试防上线时间不准）。
        #    ★ 必须在 rtmp_video_stop 之前探测——探测的是实时流。
        info = self._receiver.probe(url, attempts=5, interval=3.0)

        # 6.5 延长 ffplay 展示窗口：探测到流后、stop 前多停留几秒供人眼确认。
        #     大分辨率首帧解码慢，延长展示让窗口有足够时间出画面。
        #     仅当流已探测到且 ffplay 已启动时才停留（失败则尽快 stop 清理）。
        try:
            show = float(self.config.get("ffplay_show_duration", 5))
        except (TypeError, ValueError):
            show = 5.0
        if info.get("ok") and show > 0 and self._ffplay_active:
            logger.info(f"ffplay 展示窗口保持 {show:.0f}s 供人眼确认画面...")
            time.sleep(show)

        # 7. 停止推流（exec_async 容忍刷屏）
        console.exec_async(
            "rtmp_video_stop",
            expect=r"rtmp_video_stop|stop|RTMP",
            result_timeout=8.0,
        )

        # 8. 判据：ffprobe 探测到流
        if info.get("ok"):
            res = self._pass(f"推流验证通过: {info['reason']}")
        else:
            res = self._fail(f"推流验证失败: {info.get('reason', '未知')}",
                             detail=str(info))
        res.elapsed_ms = timer.elapsed_ms()
        return res

    def _launch_ffplay_terminal(self, url, terminal) -> bool:
        """在独立终端窗口启动 ffplay 播放画面。

        用终端模拟器（gnome-terminal 等）开一个新窗口，在其中运行 ffplay。窗口生命周期
        独立于脚本（脚本不管理其退出），ffplay 耐心等关键帧出画面（不设 -rw_timeout，
        慢流/大分辨率首帧慢时也能等到），流断开后 ffplay 自动退出，read 等回车关闭窗口。
        """
        ffplay_abs = os.path.abspath(self._ffplay_path)
        script = (
            f'echo "RTMP 画面确认: {url}"; '
            f'"{ffplay_abs}" -x 480 -y 360 "{url}"; '
            f'echo; echo "== ffplay 已退出，按回车关闭窗口 =="; read'
        )
        try:
            self._ffplay_proc = subprocess.Popen(
                [terminal, "--", "bash", "-c", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info(f"已在独立终端窗口启动 ffplay 画面确认 ({terminal})")
            return True
        except Exception as e:
            logger.warn(f"终端启动 ffplay 失败(可忽略，不影响判据): {e}")
            self._ffplay_proc = None
            return False

    def _launch_ffplay_direct(self, url) -> bool:
        """回退方式：subprocess 直启 ffplay（无独立终端），stderr 落日志文件。"""
        try:
            ffplay_err = subprocess.DEVNULL
            log_dir = logger.log_dir()
            if log_dir:
                self._ffplay_log = open(os.path.join(log_dir, "ffplay.log"), "wb")
                ffplay_err = self._ffplay_log
            self._ffplay_proc = subprocess.Popen(
                [self._ffplay_path, "-rw_timeout", "3000000", "-x", "480", "-y", "360", url],
                stdout=subprocess.DEVNULL, stderr=ffplay_err,
                preexec_fn=os.setsid,
            )
            logger.info(f"ffplay 画面确认已启动 (pid={self._ffplay_proc.pid})")
            return True
        except Exception as e:
            logger.warn(f"ffplay 启动失败(可忽略，不影响判据): {e}")
            self._ffplay_proc = None
            return False

    def teardown(self, ctx, console):
        # 停 ffplay：仅 subprocess 直启方式才需要 killpg（进程组 kill，防 SDL 残留）。
        # 独立终端窗口方式不杀（窗口生命周期独立，ffplay 流断后自退，用户自己关窗口）。
        if (not self._ffplay_in_terminal
                and self._ffplay_proc and self._ffplay_proc.poll() is None):
            try:
                os.killpg(os.getpgid(self._ffplay_proc.pid), signal.SIGTERM)
                self._ffplay_proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(self._ffplay_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self._ffplay_proc = None
        self._ffplay_in_terminal = False
        self._ffplay_active = False
        # 关闭 ffplay stderr 日志句柄（子进程被 kill 后安全关闭）
        if self._ffplay_log:
            try:
                self._ffplay_log.close()
            except Exception:
                pass
            self._ffplay_log = None
        # receiver 无常驻进程，但保留 stop 调用统一
        if self._receiver:
            self._receiver.stop()
            self._receiver = None
        # server 不由脚本启停，无操作
        self._server = None
