"""单次录像：显式选择完整 size 命令，再录像与 FTP 辅助验证。

协议定义：ATS/drivers/video_commands.py（命令、判据、实测 size 映射）。
测试编排：Scenario 的多个 video task + repeat/duration；模块不做 size 循环。
保留最终完成标志、完整路径扫描、f_index 启动兜底和 TT ERROR 标注。
下载文件仍放在本次日志 videos/ 下，使用组合与板端时间戳目录区分。
"""
import math
import os
import re
import time

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, Timer
from .tt_error_monitor import TTErrorMonitor
from ..drivers import video_commands as commands

_VIDEO_DIR = "/emmc/VIDEO"


@register("video")
class VideoModule(TestModule):
    """录像测试。"""

    depends = []
    duration_key = "video_duration"   # scenario 里 task.duration 覆盖此参数

    def __init__(self, config):
        super().__init__(config)
        self._console = None           # 录像窗口内用于摘除 listener（run() 时赋值）
        self._tt_monitor = None        # TT ERROR 检测器
        self._tt_monitor_cb = None     # TT ERROR listener 回调（用于 teardown 兜底移除）
        self._profile = None
        self._duration = None
        self._recording_active = False

    def run(self, ctx, console, params=None):
        self._console = console
        self._profile = None
        self._duration = None
        self._recording_active = False
        self._tt_monitor = None
        try:
            return self._run_once(ctx, console, params)
        finally:
            # 连续切 size 不能把半启动录像和 listener 泄漏给下一次；也覆盖 Ctrl+C。
            try:
                if self._recording_active:
                    self._stop_after_error(console)
            finally:
                self._detach_tt_listener()

    def _run_once(self, ctx, console, params=None):
        # 不把运行时覆盖写回默认配置，实例复用/重试不会继承上一个 size。
        cfg = self._merge(params)
        timer = Timer().start()
        try:
            self._profile = commands.resolve_video_profile(
                cfg.get("video_resolution", commands.DEFAULT_VIDEO_PROFILE))
            value = cfg.get("video_duration", 5)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError("video_duration 必须是大于 0 的有限数字（秒）")
            duration = float(value)
            self._duration = duration
            min_kb = int(cfg.get("video_min_size_kb", 100))
        except (ValueError, TypeError, OverflowError) as exc:
            return self._mk("ERROR", f"录像配置错误：{exc}", "未下发录像命令", timer)
        profile = self._profile
        resolution = profile.key
        ftp = getattr(ctx, "ftp_client", None)
        if ftp is None:
            return self._mk("SKIP", "FTP 客户端不可用，跳过录像", "", timer)

        # 确保 FTP 可用（固件 FTP 在重负载后会崩溃）
        from .ftp import ensure_ftp
        ftp = ensure_ftp(ctx, console)
        if ftp is None:
            return self._mk("FAIL", "FTP 不可用且恢复失败，跳过录像", "", timer)

        tmp_dir = os.path.join(logger.log_dir() or "logs", "videos")
        os.makedirs(tmp_dir, exist_ok=True)

        logger.step(f"  录像测试: {resolution} / {duration:g}s / "
                    f"预期 {profile.width}x{profile.height} {profile.orientation}")
        logger.info(f"录像 size 设置命令: {profile.command}")

        # 1. 旧目录
        before = set(self._list_video_dirs(ftp))

        # 2. 设置分辨率
        r = console.exec_sync(profile.command, timeout=commands.VIDEO_SET_TIMEOUT)
        if not r.success or re.search(commands.VIDEO_SET_ERROR, r.clean or ""):
            return self._mk("FAIL", f"设置录像组合 {resolution} 失败", r.clean, timer)

        # TT ERROR 检测（录像窗口）：命中不判 FAIL，仅在结果 detail 标注（cycle/rep 由 runner 填）。
        self._tt_monitor = TTErrorMonitor()
        self._tt_monitor_cb = self._tt_monitor.update
        console.add_listener(self._tt_monitor_cb)

        # 3. 开始录像。启动成功判据保持 Record Start 或编码心跳 f_index。
        logger.info(f"拍摄开始（{resolution} / {duration}s）...")
        rec_start = time.monotonic()
        self._recording_active = True  # 发起后即使超时，也可能已半启动。
        r = console.exec_async(commands.VIDEO_START_COMMAND,
                               expect=commands.VIDEO_START_EXPECT,
                               result_timeout=commands.VIDEO_START_TIMEOUT)
        if not r.success:
            self._stop_after_error(console)
            return self._mk("FAIL", "开始录像失败", r.clean[-300:], timer)

        time.sleep(duration)

        # 4. 等录像全流程的最终完成标志，不把 Save Video Successful 当成完成。
        r = console.exec_async(commands.VIDEO_STOP_COMMAND,
                               expect=commands.VIDEO_STOP_EXPECT,
                               result_timeout=commands.VIDEO_STOP_TIMEOUT)
        if r.success:
            self._recording_active = False
        rec_elapsed = time.monotonic() - rec_start
        if not r.success:
            logger.info(f"拍摄结束（失败），耗时 {rec_elapsed:.1f}s")
            return self._mk("FAIL", "停止录像失败", r.clean[-300:], timer)
        logger.info(f"拍摄结束，耗时 {rec_elapsed:.1f}s")

        # 5. 完成后从累积缓冲扫描完整视频路径，FTP 校验维持辅助性质。
        m2 = re.search(rf"{re.escape(_VIDEO_DIR)}/[^\s/]+/Video_[^\s]+\.h265", r.clean)
        video_path = m2.group(0) if m2 else ""
        msg_base = "录像成功"
        if video_path:
            msg_base += f"，文件 {video_path}"

        from .ftp import ensure_ftp
        ftp2 = ensure_ftp(ctx, console, force=True)
        if ftp2 is None or not video_path:
            return self._mk("PASS", f"{msg_base}（未校验大小）", r.clean[-200:], timer)

        sz = ftp2.size(video_path)
        if sz < 0:
            time.sleep(1.5)
            sz = ftp2.size(video_path)
        if sz < 0:
            return self._mk("PASS", f"{msg_base}（大小校验跳过）", r.clean[-200:], timer)
        if sz < min_kb * 1024:
            return self._mk("FAIL", f"文件过小 {sz//1024}KB < {min_kb}KB", video_path, timer)

        # 下载录像到本地（断点续传，FTP 卡死后自动从断点继续）
        fname = video_path.rsplit("/", 1)[-1]
        # 同名 Video_1_0.h265 可出现在不同板端目录；不能误当作已下载而续传旧 size。
        remote_dir = video_path.rsplit("/", 2)[-2]
        safe_dir = re.sub(r"[^A-Za-z0-9_.-]", "_", remote_dir)
        local = os.path.join(tmp_dir, f"{profile.key}_{safe_dir}_{fname}")
        logger.info(f"FTP 开始下载视频: {video_path} ({sz//1024}KB) -> {local}")
        dl_start = time.monotonic()
        if ftp2.download(video_path, local, timeout=20, retries=6):
            dl_elapsed = time.monotonic() - dl_start
            logger.info(f"FTP 下载完成，耗时 {dl_elapsed:.1f}s")
            msg = f"{msg_base}，{sz//1024}KB | 已下载到 {local}"
        else:
            dl_elapsed = time.monotonic() - dl_start
            logger.info(f"FTP 下载未完成，耗时 {dl_elapsed:.1f}s")
            local_sz = os.path.getsize(local) if os.path.exists(local) else 0
            msg = f"{msg_base}，{sz//1024}KB | 下载不完整({local_sz//1024}KB/{sz//1024}KB)"
        return self._mk("PASS", msg, video_path, timer)

    def _list_video_dirs(self, ftp):
        try:
            entries = ftp._list_entries(_VIDEO_DIR)
            return [name for name, is_dir, _ in entries if is_dir]
        except Exception:
            return []

    def _wait_new_dir(self, ftp, before, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            now = set(self._list_video_dirs(ftp))
            new = now - before
            if new:
                return next(iter(new))
            time.sleep(0.5)
        return None

    def _mk(self, status, msg, detail, timer):
        self._detach_tt_listener()
        detail = self._attach_tt_hits(detail or "")
        profile = getattr(self, "_profile", None)
        name = "video"
        if profile is not None:
            name = f"video[{profile.key}]"
            metadata = (
                f"录像组合: {profile.key}\n"
                f"设置命令: {profile.command}\n"
                f"预期 size: {profile.width}x{profile.height} ({profile.orientation})\n"
                "尺寸来源: 用户手测映射；不是本次视频实测值"
            )
            if self._duration is not None:
                metadata += f"\n配置录像时长: {self._duration:g}s"
            detail = metadata + ("\n" + detail if detail else "")
        return TestResult(name=name, module="video", status=status,
                          message=msg, detail=detail, elapsed_ms=timer.elapsed_ms())

    def _detach_tt_listener(self):
        cb = getattr(self, "_tt_monitor_cb", None)
        if cb is not None:
            try:
                self._console.remove_listener(cb)
            except Exception:
                pass
            self._tt_monitor_cb = None

    def _stop_after_error(self, console):
        """尽力收尾，不覆盖原失败结果；不把清理成功当作本次录像成功。"""
        logger.warn(f"录像异常，补发 {commands.VIDEO_STOP_COMMAND} 清理状态（best-effort）...")
        try:
            console.exec_async(commands.VIDEO_STOP_COMMAND,
                               expect=commands.VIDEO_CLEANUP_EXPECT,
                               result_timeout=commands.VIDEO_CLEANUP_TIMEOUT)
        except Exception as exc:
            logger.warn(f"清理录像状态异常(可忽略): {exc}")
        finally:
            self._recording_active = False

    def _attach_tt_hits(self, detail):
        """把 TT ERROR 命中信息追加到 detail（命中不改变 status）。"""
        mon = self._tt_monitor
        hits = mon.get_hits() if mon else []
        if not hits:
            return detail
        block = "\n".join(
            [f"TT ERROR 命中 {len(hits)} 次："]
            + [f"第{i}次: {h}" for i, h in enumerate(hits, 1)]
        )
        return (detail + "\n" + block) if detail else block

    def teardown(self, ctx, console):
        self._detach_tt_listener()
        self._tt_monitor = None
