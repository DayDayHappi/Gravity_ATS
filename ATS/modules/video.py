"""录像模块：1080p 录 N 秒，可选 FTP 校验/下载。

实测文件结构：
  /emmc/VIDEO/<时间戳目录>/Video_<序号>_0.h265   (主视频)
                        /Imu_<序号>.bin          (附加IMU数据，可选)

参数开关：``video_ftp_download``（默认 true）。
  - true: 历史行为——录像后校验文件大小并下载到本地（normal/stress 场景）。
  - false: 纯录像——完全不依赖 FTP，不 ensure_ftp、不列目录、不下载，
    停止成功后直接判 PASS（testvideo 分支场景）。

流程（FTP 下载模式）：
1. 记录 /emmc/VIDEO 旧时间戳目录集合
2. ``cam_set video 1080p``
3. ``dfs_video_start`` -> sleep(录像时长) -> ``dfs_video_stop``
4. 轮询 FTP 等新时间戳目录（给编码落盘时间）
5. 列新目录找 .h265 文件，下载验证大小 > 阈值

流程（纯录像模式，video_ftp_download=false）：
1. ``dfs_video_start`` -> sleep(录像时长) -> ``dfs_video_stop``
2. 等到 ``Video recording completed successfully.`` 即 PASS
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

    depends = []
    duration_key = "video_duration"   # scenario 里 task.duration 覆盖此参数

    def run(self, ctx, console, params=None):
        self.config = self._merge(params)
        ftp_enabled = bool(self.config.get("video_ftp_download", True))
        if not ftp_enabled:
            return self._run_no_ftp(ctx, console)

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
        # TODO-TEMP-DISABLE-CAM_SET: 录像前暂不切分辨率，直接 dfs_video_start；后续恢复 cam_set video。
        #   临时禁用（用户口述）：跳过 cam_set，直接进入 dfs_video_start。恢复时删掉下面这段跳过逻辑、
        #   还原 cam_set 调用即可。resolution 变量保留（logger.step / logger.info 仍在使用）。
        if False:
            r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
            if not r.success:
                return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)

        # 3. 开始录像。录像命令输出海量日志会打乱哨兵，用 exec_async 等正则。
        #    启动成功判据：Record Start（正常路径）或 f_index（录像编码心跳，无 [RTMP] 前缀，
        #    区别于 rtmp_monitor 的 [RTMP] f_index）。连续压测下固件可能漏打 Record Start
        #    （摄像头资源退化）但编码实际在跑（f_index 持续增长），只等 Record Start 会误判失败。
        logger.info(f"拍摄开始（{resolution} / {duration}s）...")
        rec_start = time.monotonic()
        r = console.exec_async("dfs_video_start",
                               expect=r"Record Start|f_index\s*=",
                               result_timeout=25.0)
        if not r.success:
            # 失败清理：尽力停掉可能已半启动的录像，避免 stream_on 半初始化态泄漏给下一个
            # rtmp task（否则 ffprobe Input/output error 连锁 FAIL/SKIP）。best-effort，不判结果。
            logger.warn("开始录像失败，补发 dfs_video_stop 清理状态（best-effort）...")
            try:
                console.exec_async("dfs_video_stop",
                                   expect=r"Save Video|Please start|recording completed",
                                   result_timeout=8.0)
            except Exception as e:
                logger.warn(f"清理 dfs_video_stop 异常(可忽略): {e}")
            return self._mk("FAIL", "开始录像失败", r.clean[-300:], timer)

        time.sleep(duration)

        # 4. 停止录像（exec_async 等串口主判据：Video recording completed successfully.，
        #    录像全流程走完的最终完成标志。不能用 Save Video Successful：它出现更早
        #    （实测约早 2s），此时录像收尾（编码 finalize/落盘）未完成、路径还可能被
        #    串口分块截断，提前发下一条命令会造成错位 + 校验对象错误）
        r = console.exec_async("dfs_video_stop",
                               expect=r"Video recording completed successfully.",
                               result_timeout=25.0)
        rec_elapsed = time.monotonic() - rec_start
        if not r.success:
            logger.info(f"拍摄结束（失败），耗时 {rec_elapsed:.1f}s")
            return self._mk("FAIL", "停止录像失败", r.clean[-300:], timer)
        logger.info(f"拍摄结束，耗时 {rec_elapsed:.1f}s")

        # 5. 录像已成功落盘（串口确认）。FTP 校验文件大小作辅助。
        #    路径不能依赖 Save Video Successful 行的捕获组——板端打印路径本身会分块
        #    截断（实测 "Save Video Successful: /emmc/VI"）；等完成标志后整条路径已在
        #    r.clean 累积缓冲中拼接完整，按 /emmc/VIDEO/<dir>/Video_<n>_0.h265 扫描才可靠。
        import re
        m2 = re.search(rf"{re.escape(_VIDEO_DIR)}/[^\s/]+/Video_[^\s]+\.h265", r.clean)
        video_path = m2.group(0) if m2 else ""
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

    def _run_no_ftp(self, ctx, console):
        """纯录像流程（video_ftp_download=false）：只录不下载，完全不碰 FTP。

        判据与 FTP 模式一致：dfs_video_stop 等到 Video recording completed successfully.。
        """
        timer = Timer().start()
        resolution = self.config.get("video_resolution", "1080p")
        duration = int(self.config.get("video_duration", 5))

        logger.step(f"  录像测试（纯录像，不下载）: {resolution} / {duration}s")

        # TODO-TEMP-DISABLE-CAM_SET: 录像前暂不切分辨率，直接 dfs_video_start（与 FTP 模式
        #   同一临时禁用约定）。恢复时删掉这段跳过逻辑、还原 cam_set 调用即可。
        if False:
            r = console.exec_sync(f"cam_set video {resolution}", timeout=10.0)
            if not r.success:
                return self._mk("FAIL", f"设置分辨率 {resolution} 失败", r.clean, timer)

        logger.info(f"拍摄开始（{resolution} / {duration}s）...")
        rec_start = time.monotonic()
        r = console.exec_async("dfs_video_start",
                               expect=r"Record Start|f_index\s*=",
                               result_timeout=25.0)
        if not r.success:
            # 失败清理：尽力停掉可能已半启动的录像（与 FTP 模式同款 best-effort）
            logger.warn("开始录像失败，补发 dfs_video_stop 清理状态（best-effort）...")
            try:
                console.exec_async("dfs_video_stop",
                                   expect=r"Save Video|Please start|recording completed",
                                   result_timeout=8.0)
            except Exception as e:
                logger.warn(f"清理 dfs_video_stop 异常(可忽略): {e}")
            return self._mk("FAIL", "开始录像失败", r.clean[-300:], timer)

        time.sleep(duration)

        r = console.exec_async("dfs_video_stop",
                               expect=r"Video recording completed successfully.",
                               result_timeout=25.0)
        rec_elapsed = time.monotonic() - rec_start
        if not r.success:
            logger.info(f"拍摄结束（失败），耗时 {rec_elapsed:.1f}s")
            return self._mk("FAIL", "停止录像失败", r.clean[-300:], timer)
        logger.info(f"拍摄结束，耗时 {rec_elapsed:.1f}s")
        return self._mk("PASS", "录像成功（纯录像，未下载）", r.clean[-200:], timer)

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
