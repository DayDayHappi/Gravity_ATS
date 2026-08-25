"""PreviewManager：PC 端 ffplay 画面观察器（单例，Scenario 生命周期）。

职责边界（ADR-010）：
- 画面观察是**观察能力**，不是测试能力；播放器生命周期属于 **Scenario 生命周期**，
  不属于 Task 生命周期。
- 播放器只负责「把 RTMP 实时流播出来供人工观察（延时/首帧/卡顿/推流恢复）」，**不参与
  判据**（判据由 ffprobe 实时探测 + RTMP heartbeat 给出）。
- 与 ``RtmpReceiver``/``RtmpServer`` 同级，都是「PC 端本地进程/服务管理器」，故落位
  ``drivers/``，不新增 ``core/`` 或 ``services/`` 目录。

关键适配（stress 多轮 start/stop 推流的现实）：nginx-rtmp 在 EVB 停止推流
（``rtmp_video_stop``）时会断开该 stream 的观看连接，单次 ffplay 进程会在流断后退出、
且下一轮 ``rtmp_video_start`` 时不会自动重连。因此 ``start()`` 内部用**重连 wrapper**：
ffplay 退出后 sleep + 重试，直到 ``stop()`` 终止 wrapper 及子进程。这与 ``restart()``
落地方式一致——由 PreviewManager 自动重连，不依赖外部显式调用。

启动方式沿用既有已验证逻辑（从 ``modules/rtmp.py`` 迁移）：
- 有 DISPLAY + 终端模拟器（gnome-terminal/xterm 等）时，在独立终端窗口跑 wrapper；
- 否则回退 subprocess 直启 bash wrapper（``setsid`` 成新会话，便于 ``killpg`` 整组回收）；
- 无 DISPLAY 或无 ffplay 则跳过（无人值守/SSH 常见，不影响判据）。
"""
import os
import signal
import subprocess

from ..core import logger


def _detect_pc_ip(target_ip: str) -> str:
    """通过"连接 target_ip"获取本机与 target_ip 通信的接口 IP。

    不会真正发数据，仅让 OS 选路并返回本端地址。供 preview 与 rtmp 两处复用。
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


# 终端模拟器候选：用于在独立终端窗口跑 ffplay 画面观察
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


class PreviewManager:
    """RTMP 画面观察器：管理 ffplay 重连 wrapper 的生命周期（start/stop/restart/is_running）。

    整个 Scenario 生命周期只应有一个实例（由 ``prepare_action("preview_start")`` 创建并
    写入 ``ctx.preview_manager``，``cleanup_action("preview_stop")`` 回收），不得在每个
    task/loop 轮次新建——避免 stress 多轮累积窗口与资源泄漏。
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self._ffplay_path = _find_ffplay(self.config.get("ffplay_path", "ffplay"))
        self._retry = float(self.config.get("retry_interval", 3.0))
        self._required = bool(self.config.get("preview_required", False))

        self._url = None
        self._wrapper_proc = None   # 重连 wrapper 进程（终端模拟器 或 bash -c）
        self._in_terminal = False   # 是否走独立终端窗口模式
        self._active = False        # 本次是否成功启动（用于终端模式下 gnome-terminal 立即返回的兜底）
        self._log_handle = None     # 直启模式 stderr 日志句柄

    # ------------------------------------------------------------------
    # 生命周期接口
    # ------------------------------------------------------------------

    def start(self, url: str) -> bool:
        """启动画面观察（幂等：已在运行则直接返回 True）。

        用重连 wrapper 跑 ffplay，直到 ``stop()`` 终止。返回是否成功启动
        （无 DISPLAY / 无 ffplay 时为 False，不影响判据）。
        """
        if self.is_running():
            logger.info("PreviewManager 已在运行，跳过重复启动")
            return True
        self._url = url

        if not self._ffplay_path:
            logger.warn("未找到 ffplay，跳过画面观察（判据仍由 ffprobe + heartbeat 给出）")
            return False
        if not os.environ.get("DISPLAY"):
            logger.info("无 DISPLAY 环境变量，跳过画面观察（无人值守/SSH 常见）")
            return False

        terminal = _find_terminal()
        if terminal:
            return self._launch_terminal(url, terminal)
        return self._launch_direct(url)

    def stop(self):
        """关闭画面观察：终止重连 wrapper 及子进程，清空状态。幂等。"""
        if not self._active:
            self._wrapper_proc = None
            return
        self._report_unexpected_exit()
        self._terminate_wrapper()
        self._active = False
        self._wrapper_proc = None
        self._in_terminal = False
        self._close_log()

    def restart(self, url: str = None) -> bool:
        """重新连接 RTMP：先 stop 再 start（应用场景：板端重新推流）。"""
        self.stop()
        return self.start(url or self._url)

    def is_running(self) -> bool:
        """是否在运行。

        直启模式以 ``wrapper.poll() is None`` 为准；终端模式下部分终端模拟器
        （如 gnome-terminal）启动后立即返回，故以 ``_active`` 兜底判断。
        """
        if not self._active:
            return False
        if self._in_terminal:
            return True
        return self._wrapper_proc is not None and self._wrapper_proc.poll() is None

    # ------------------------------------------------------------------
    # 启动实现
    # ------------------------------------------------------------------

    def _wrapper_script(self, url: str) -> str:
        """生成重连 wrapper 的 bash 脚本：ffplay 退出后 sleep 重连，直到被 stop 终止。"""
        ffplay_abs = os.path.abspath(self._ffplay_path)
        return (
            f'echo "RTMP 画面观察: {url}"; '
            f'while true; do '
            f'  "{ffplay_abs}" -rtmp_live live -rtmp_buffer 0 -fflags nobuffer '
            f'-flags low_delay -framedrop -sync ext "{url}"; '
            f'  echo; echo "== ffplay 已退出，{self._retry:g}s 后重连 =="; '
            f'  sleep {self._retry}; '
            f'done'
        )

    def _launch_terminal(self, url: str, terminal: str) -> bool:
        """独立终端窗口模式：终端模拟器里跑重连 wrapper。"""
        script = self._wrapper_script(url)
        try:
            self._wrapper_proc = subprocess.Popen(
                [terminal, "--", "bash", "-c", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._in_terminal = True
            self._active = True
            logger.info(f"已在独立终端窗口启动画面观察 ({terminal})")
            return True
        except Exception as e:
            logger.warn(f"终端启动画面观察失败(可忽略，不影响判据): {e}")
            self._wrapper_proc = None
            return False

    def _launch_direct(self, url: str) -> bool:
        """直启模式：subprocess 直启 bash wrapper（setsid 便于 killpg 整组回收）。"""
        script = self._wrapper_script(url)
        err = subprocess.DEVNULL
        log_dir = logger.log_dir()
        if log_dir:
            try:
                self._log_handle = open(os.path.join(log_dir, "preview.log"), "wb")
                err = self._log_handle
            except Exception:
                self._log_handle = None
        try:
            self._wrapper_proc = subprocess.Popen(
                ["bash", "-c", script],
                stdout=subprocess.DEVNULL,
                stderr=err,
                preexec_fn=os.setsid,
            )
            self._in_terminal = False
            self._active = True
            logger.info(f"画面观察已启动 (pid={self._wrapper_proc.pid})")
            return True
        except Exception as e:
            logger.warn(f"画面观察启动失败(可忽略，不影响判据): {e}")
            self._wrapper_proc = None
            self._close_log()
            return False

    # ------------------------------------------------------------------
    # 停止与异常处理
    # ------------------------------------------------------------------

    def _terminate_wrapper(self):
        """终止重连 wrapper 及其子进程（进程组 kill，防 ffplay 残留）。"""
        if self._wrapper_proc is None:
            return
        try:
            pgid = os.getpgid(self._wrapper_proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                self._wrapper_proc.wait(timeout=3)
            except Exception:
                pass
        except Exception:
            pass
        # 兜底：SIGKILL 确保回收
        if self._wrapper_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._wrapper_proc.pid), signal.SIGKILL)
                self._wrapper_proc.wait(timeout=3)
            except Exception:
                pass

    def _report_unexpected_exit(self):
        """若曾启动但已意外退出（如用户手动关闭窗口），按 preview_required 决定影响级别。"""
        if self._in_terminal:
            # 终端模式下无法精确探测 wrapper 是否仍存活，跳过（记录见 devlog）
            return
        if self._wrapper_proc is not None and self._wrapper_proc.poll() is not None:
            msg = "preview stopped unexpectedly（画面观察意外退出）"
            if self._required:
                logger.error(f"{msg}（preview_required=true）")
            else:
                logger.warn(f"{msg}（不影响判据）")

    def _close_log(self):
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
