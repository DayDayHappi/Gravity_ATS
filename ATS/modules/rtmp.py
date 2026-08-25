"""RTMP 推流模块：EVB 推流 + PC 端 ffprobe 实时探测 + RTMP 持续 heartbeat 检测。

流程：
- setup: 确定 pc_ip（自动检测或配置，复用 drivers/preview_manager._detect_pc_ip），
         创建 RtmpReceiver（ffprobe）
- run: 检查 nginx-rtmp 就绪 -> ``rtmp_video_start <url>`` (exec_async，不依赖哨兵) ->
       等推流上线 -> ffprobe 实时探测流（★ 主判据） ->
       RTMPMonitor 持续检测 heartbeat（[RTMP] f_index，超时则 FAIL）-> ``rtmp_video_stop``
- teardown: 移除 monitor listener（兜底）

画面观察（ffplay）已由 ADR-010 抽离到 ``drivers/preview_manager.py``，属 Scenario 生命
周期（prepare 的 preview_start / cleanup 的 preview_stop），本模块不再管理播放窗口。

只依赖 WiFi（推流需网络），不依赖 FTP。

推流命令用 exec_async 而非 exec_sync：photo/video 后固件 FTP 常陷入
"service go wrong" 崩溃循环刷屏，会打乱 exec_sync 的哨兵定界导致必败。
exec_async 不依赖哨兵，真正成败判据交给 PC 端 ffprobe 是否探测到流。

持续运行检测：用板端 ``[RTMP] f_index`` 日志作 heartbeat（代表编码+发送仍在进行），
由独立的 RTMPMonitor 订阅串口原始数据、周期性检查超时，捕捉"推流中途异常停止"
（如 ImuThread 崩溃导致画面卡住），避免干等剩余时长误判 PASS。

★ 关键时序：ffprobe 探测必须在 ``rtmp_video_stop`` **之前**——探测的是实时流，
stop 后流断开探测必失败。这与 MediaMTX 时代"先 stop 再 verify 存盘文件"相反。
"""
import time

from .base import TestModule, register
from ..core import logger
from ..core.result import Timer, TestResult
from ..drivers.preview_manager import _detect_pc_ip
from ..drivers.rtmp_receiver import RtmpReceiver
from ..drivers.rtmp_server import RtmpServer, RtmpServerError
from .rtmp_monitor import RTMPMonitor, TIMEOUT


@register("rtmp")
class RtmpModule(TestModule):
    """RTMP 推流测试。"""

    depends = []
    duration_key = "stream_duration"   # scenario 里 task.duration 覆盖此参数

    def __init__(self, config):
        super().__init__(config)
        self._receiver = None
        self._server = None
        self._monitor = None           # RTMP 持续 heartbeat 检测器
        self._monitor_cb = None        # 已注册到 console 的 listener 回调（用于 teardown 兜底移除）

    def setup(self, ctx, console):
        evb_ip = getattr(ctx, "evb_ip", None)
        # pc_ip 解析顺序：system.pc.ip -> rtmp.yaml.pc_ip -> auto 探测
        sys_pc = (getattr(ctx, "system_config", None) or {}).get("pc", {}) or {}
        pc_ip = sys_pc.get("ip", "auto") or self.config.get("pc_ip", "auto")
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

    def run(self, ctx, console, params=None):
        self.config = self._merge(params)
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
        duration = int(self.config.get("stream_duration", 600))

        logger.step(f"  RTMP 推流测试: {url} / {duration}s")

        # 3. EVB 开始推流（先于探测启动）。
        # 用 exec_async：只发命令、不发哨兵，直接等业务状态字符串（DUT 侧开始推流）。
        # expect 匹配 "publish ready / Push Start" 表示 DUT 侧 RTMP 已上线，不再用
        # 命令回显（"rtmp_video_start"）当匹配——命令回显 ≠ 业务成功。但 exec_async
        # 的匹配结果仍不作为 RTMP 最终判据，最终判据是 PC 端 ffprobe 探测到流。
        # 即便 exec_async 没匹配到也不立即 FAIL，留给 ffprobe 兜底。
        # 注：必须先推流后探测——ffprobe 连无流的源会立即 I/O error。
        console.exec_async(
            f"rtmp_video_start {url}",
            expect=r"publish ready|Push Start",
            result_timeout=8.0,
        )

        # 4. 等推流上线（给 EVB 建连 + 首帧时间）
        logger.info("推流命令已下发，等待 EVB 建连上线...")
        time.sleep(3.0)

        # 5. ffprobe 实时探测 RTMP 流（★ 主判据，带重试防上线时间不准）。
        #    ★ 必须在 rtmp_video_stop 之前探测——探测的是实时流。
        info = self._receiver.probe(url, attempts=5, interval=3.0)

        # 6. 探测到流后，保持推流 stream_duration 秒，同时用 RTMPMonitor 持续检测
        #    heartbeat（[RTMP] f_index）。仅探测成功才保持推流，失败则尽快 stop。
        #    超时无 heartbeat（板端推流异常停止）则提前 FAIL，不再干等剩余时长。
        monitor = None
        heartbeat_timeout = float(self.config.get("heartbeat_timeout", 30.0))
        if info.get("ok") and duration > 0:
            monitor = RTMPMonitor(timeout=heartbeat_timeout)
            monitor.start()
            self._monitor = monitor
            self._monitor_cb = monitor.update
            console.add_listener(self._monitor_cb)
            logger.info(
                f"推流保持 {duration}s（持续 heartbeat 检测，阈值 {heartbeat_timeout:.0f}s）..."
            )
            waited = 0
            check_step = 1.0         # 每 1s 检查一次 heartbeat
            progress_step = 30       # 每 30s 打印一次进度
            next_progress = progress_step
            try:
                while waited < duration:
                    time.sleep(check_step)
                    waited += check_step
                    if monitor.check_timeout():
                        logger.error(
                            f"RTMP heartbeat 超时（>{heartbeat_timeout:.0f}s 无 [RTMP] f_index），"
                            f"推流异常停止，提前结束等待"
                        )
                        break
                    if waited >= next_progress:
                        logger.info(f"  推流已保持 {int(waited)}/{duration}s ...")
                        next_progress += progress_step
            finally:
                console.remove_listener(self._monitor_cb)
                self._monitor_cb = None
                monitor.stop()
        elif not info.get("ok"):
            logger.info("推流探测失败，跳过保持阶段，直接停止推流...")

        # 7. 停止推流（exec_async 只发命令不发哨兵，等业务状态字符串）
        console.exec_async(
            "rtmp_video_stop",
            expect=r"Push Stop|Stop requested",
            result_timeout=8.0,
        )

        # 8. 判据：ffprobe 探测到流（主判据）+ RTMP 持续 heartbeat 无超时
        if not info.get("ok"):
            res = self._fail(f"推流验证失败: {info.get('reason', '未知')}",
                             detail=str(info))
        elif monitor is not None and monitor.get_status()["status"] == TIMEOUT:
            res = TestResult(
                name="rtmp", module="rtmp", status="FAIL",
                message="RTMP 推流中途异常停止（heartbeat timeout）",
                detail=self._fmt_monitor_detail(monitor.get_status()),
            )
        else:
            msg = f"推流验证通过: {info['reason']}"
            detail = ""
            if monitor is not None:
                st = monitor.get_status()
                msg += f"，持续 {st['duration']:.0f}s 稳定"
                detail = self._fmt_monitor_detail(st)
            res = TestResult(name="rtmp", module="rtmp", status="PASS",
                             message=msg, detail=detail)
        res.elapsed_ms = timer.elapsed_ms()
        return res

    @staticmethod
    def _fmt_monitor_detail(st: dict) -> str:
        """把 RTMPMonitor 状态格式化为多行文本，写入 TestResult.detail 供 report 展示。"""
        return "\n".join([
            "RTMP Monitor Result:",
            f"Status: {st['status']}",
            f"Reason: {st['reason']}",
            f"Start Time: {st['start_time']}",
            f"Last Frame Time: {st['last_frame_time']}",
            f"Timeout: {st['timeout']:.0f}s",
            f"Duration: {st['duration']:.1f}s",
            f"Frame Count: {st['frame_count']}",
        ])

    def teardown(self, ctx, console):
        # 兜底移除 monitor listener（正常路径已在 run() 的 finally 移除；异常路径在此兜底）。
        if self._monitor_cb is not None:
            try:
                console.remove_listener(self._monitor_cb)
            except Exception:
                pass
            self._monitor_cb = None
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        # receiver 无常驻进程，但保留 stop 调用统一
        if self._receiver:
            self._receiver.stop()
            self._receiver = None
        # server 不由脚本启停，无操作
        self._server = None
