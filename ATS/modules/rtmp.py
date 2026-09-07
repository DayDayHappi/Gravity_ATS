"""RTMP test module: DUT publish + ffprobe verdict + heartbeat continuity."""
from __future__ import annotations

import time

from .base import TestModule, register
from .rtmp_monitor import RTMPMonitor, TIMEOUT
from ..core import logger
from ..core.cancellation import OperationCancelled, token_from
from ..core.result import TestResult, Timer
from ..drivers.preview_manager import _detect_pc_ip
from ..drivers.rtmp_receiver import RtmpReceiver
from ..drivers.rtmp_server import RtmpServer, RtmpServerError


@register("rtmp")
class RtmpModule(TestModule):
    """Run one RTMP publishing test without owning the preview window."""

    depends = []
    duration_key = "stream_duration"

    def __init__(self, config):
        super().__init__(config)
        self._receiver = None
        self._server = None
        self._monitor = None
        self._monitor_cb = None

    def setup(self, ctx, console):
        evb_ip = getattr(ctx, "evb_ip", None)
        sys_pc = (getattr(ctx, "system_config", None) or {}).get("pc", {}) or {}
        pc_ip = sys_pc.get("ip", "auto") or self.config.get("pc_ip", "auto")
        if pc_ip in ("auto", "", None):
            pc_ip = _detect_pc_ip(evb_ip) if evb_ip else ""
            if pc_ip:
                logger.info(f"自动检测到 PC IP: {pc_ip}")
        if not pc_ip:
            logger.warn("未能确定 PC IP，RTMP 推流可能失败")
        ctx.pc_ip = pc_ip

        services = getattr(ctx, "platform_services", None)
        self._receiver = RtmpReceiver(
            ffprobe_path=self.config.get("ffprobe_path", "ffprobe"),
            resource_locator=getattr(services, "resources", None) if services else None,
            process_controller=getattr(services, "processes", None) if services else None,
            cancellation_token=getattr(ctx, "cancellation_token", None),
        )
        self._server = RtmpServer(
            port=1935,
            backend=getattr(services, "rtmp_backend", None) if services else None,
        )

    def run(self, ctx, console, params=None):
        self.config = self._merge(params)
        pc_ip = getattr(ctx, "pc_ip", "")
        if not pc_ip:
            return self._fail("无法确定 PC IP，RTMP 推流目标未知")
        token = token_from(ctx)
        try:
            try:
                self._server.check_ready(cancellation_token=token)
            except TypeError:
                # 兼容旧的 RTMP server backend / 测试替身：Phase 4 为
                # ``check_ready`` 增加了可选取消参数，但第三方实现可能仍
                # 只有无参签名。生产内置 backend 会走上面的可取消路径。
                self._server.check_ready()
        except RtmpServerError as exc:
            return self._fail(f"RTMP 服务端未就绪: {exc}")

        timer = Timer().start()
        url = self.config.get("stream_url", "rtmp://{pc_ip}/live/cam").format(pc_ip=pc_ip)
        duration = int(self.config.get("stream_duration", 600))
        heartbeat_timeout = float(self.config.get("heartbeat_timeout", 30.0))
        monitor = None
        monitor_status = None
        stream_started = False
        info = None
        logger.step(f"  RTMP 推流测试: {url} / {duration}s")

        try:
            console.exec_async(
                f"rtmp_video_start {url}",
                expect=r"publish ready|Push Start",
                result_timeout=8.0,
            )
            # Even if the start marker is missed, the DUT may have started; cleanup must stop it.
            stream_started = True
            logger.info("推流命令已下发，等待 EVB 建连上线...")
            self._wait(token, 3.0)

            info = self._receiver.probe(url, attempts=5, interval=3.0)
            if info.get("ok") and duration > 0:
                monitor = RTMPMonitor(timeout=heartbeat_timeout)
                monitor.start()
                self._monitor = monitor
                self._monitor_cb = monitor.update
                console.add_listener(self._monitor_cb)
                logger.info(
                    f"推流保持 {duration}s（持续 heartbeat 检测，阈值 {heartbeat_timeout:.0f}s）..."
                )
                waited = 0.0
                next_progress = 30.0
                while waited < duration:
                    step = min(1.0, duration - waited)
                    self._wait(token, step)
                    waited += step
                    if monitor.check_timeout():
                        logger.error(
                            f"RTMP heartbeat 超时（>{heartbeat_timeout:.0f}s 无 [RTMP] f_index），"
                            "推流异常停止，提前结束等待"
                        )
                        break
                    if waited >= next_progress:
                        logger.info(f"  推流已保持 {int(waited)}/{duration}s ...")
                        next_progress += 30.0
                monitor_status = monitor.get_status()
            elif not info.get("ok"):
                logger.info("推流探测失败，跳过保持阶段，直接停止推流...")

            if not info.get("ok"):
                result = self._fail(
                    f"推流验证失败: {info.get('reason', '未知')}",
                    detail=str(info),
                )
            elif monitor_status is not None and monitor_status["status"] == TIMEOUT:
                result = TestResult(
                    name="rtmp",
                    module="rtmp",
                    status="FAIL",
                    message="RTMP 推流中途异常停止（heartbeat timeout）",
                    detail=self._fmt_monitor_detail(monitor_status),
                )
            else:
                message = f"推流验证通过: {info['reason']}"
                detail = ""
                if monitor_status is not None:
                    message += f"，持续 {monitor_status['duration']:.0f}s 稳定"
                    detail = self._fmt_monitor_detail(monitor_status)
                result = TestResult(
                    name="rtmp", module="rtmp", status="PASS",
                    message=message, detail=detail,
                )
            result.elapsed_ms = timer.elapsed_ms()
            return result
        finally:
            if self._monitor_cb is not None:
                try:
                    console.remove_listener(self._monitor_cb)
                except Exception:
                    pass
                self._monitor_cb = None
            if monitor is not None:
                monitor.stop()
            self._monitor = None
            if stream_started:
                try:
                    console.exec_async(
                        "rtmp_video_stop",
                        expect=r"Push Stop|Stop requested",
                        result_timeout=8.0,
                        honor_cancellation=False,
                    )
                except Exception as exc:
                    logger.warn(f"RTMP STOP 清理异常(可忽略): {exc}")

    @staticmethod
    def _wait(token, seconds: float) -> None:
        if token is None:
            time.sleep(seconds)
        elif token.wait(seconds):
            token.raise_if_cancelled()

    @staticmethod
    def _fmt_monitor_detail(status: dict) -> str:
        return "\n".join([
            "RTMP Monitor Result:",
            f"Status: {status['status']}",
            f"Reason: {status['reason']}",
            f"Start Time: {status['start_time']}",
            f"Last Frame Time: {status['last_frame_time']}",
            f"Timeout: {status['timeout']:.0f}s",
            f"Duration: {status['duration']:.1f}s",
            f"Frame Count: {status['frame_count']}",
        ])

    def teardown(self, ctx, console):
        if self._monitor_cb is not None:
            try:
                console.remove_listener(self._monitor_cb)
            except Exception:
                pass
            self._monitor_cb = None
        if self._monitor is not None:
            self._monitor.stop()
            self._monitor = None
        if self._receiver:
            self._receiver.stop()
            self._receiver = None
        self._server = None
