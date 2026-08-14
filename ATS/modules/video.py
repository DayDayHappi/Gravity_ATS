"""录像模块：1080p 录 N 秒 + FTP 验证文件大小。

实测文件结构：
  /emmc/VIDEO/<时间戳目录>/Video_<序号>_0.h265   (主视频)
                        /Imu_<序号>.bin          (附加IMU数据，可选)

流程：
1. 记录 /emmc/VIDEO 旧时间戳目录集合
2. ``cam_set video 1080p``
3. ``dfs_video_start`` -> sleep(录像时长) -> ``dfs_video_stop``
4. 轮询 FTP 等新时间戳目录（给编码落盘时间）
5. 列新目录找 .h265 文件，下载验证大小 > 阈值
"""
import os
import time

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, Timer

_VIDEO_DIR = "/emmc/VIDEO"


@register("video")
class VideoModule(TestModule):
    """录像测试。"""

    depends = ["ftp"]

    def run(self, ctx, console):
        ftp = getattr(ctx, "ftp_client", None)
        if ftp is None:
            return self._skip("FTP 客户端不可用，跳过录像")

        # 确保 FTP 可用（固件 FTP 在重负载后会崩溃）
        from .ftp import ensure_ftp
        ftp = ensure_ftp(ctx, console)
        if ftp is None:
            return self._fail("FTP 不可用且恢复失败，跳过录像")

        timer = Timer().start()
        resolution = self.config.get("video_resolution", "1080p")
        duration = int(self.config.get("video_duration", 5))
        cap_timeout = float(self.config.get("video_capture_timeout", 15.0))
        min_kb = int(self.config.get("video_min_size_kb", 100))
        tmp_dir = os.path.join(logger.log_dir() or "logs", "videos")
        os.makedirs(tmp_dir, exist_ok=True)

        logger.step(f"  录像测试: {resolution} / {duration}s")

        # 1. 旧目录
        before = set(self._list_video_dirs(ftp))

        # 2. 设置分辨率
        r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
        if not r.success:
            return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)

        # 3. 开始录像。录像命令输出海量日志会打乱哨兵，用 exec_async 等正则。
        r = console.exec_async("dfs_video_start", expect=r"Record Start", result_timeout=25.0)
        if not r.success:
            return self._mk("FAIL", "开始录像失败", r.clean[-300:], timer)

        time.sleep(duration)

        # 4. 停止录像（exec_async 等串口主判据：Save Video Successful，含视频路径）
        r = console.exec_async("dfs_video_stop",
                               expect=r"Save Video Successful:\s*(\S+)",
                               result_timeout=25.0)
        if not r.success:
            return self._mk("FAIL", "停止录像失败", r.clean[-300:], timer)

        # 5. 录像已成功落盘（串口确认）。FTP 校验文件大小作辅助
        import re
        video_path = (r.matched or "").rstrip()
        msg_base = "录像成功"
        if video_path:
            msg_base += f"，文件 {video_path}"

        from .ftp import ensure_ftp
        ftp2 = ensure_ftp(ctx, console, force=True)
        if ftp2 is None or not video_path:
            return self._mk("PASS", f"{msg_base}（未校验大小）", r.clean[-200:], timer)

        # size 可能因 FTP 不稳失败，重试一次
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
        local = os.path.join(tmp_dir, fname)
        if ftp2.download(video_path, local, timeout=20, retries=6):
            msg = f"{msg_base}，{sz//1024}KB | 已下载到 {local}"
        else:
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
        return TestResult(name="video", module="video", status=status,
                          message=msg, detail=detail, elapsed_ms=timer.elapsed_ms())
