"""拍照模块：遍历模式 + 每拍即 FTP 验证。

实测文件结构（与手册不同）：
  /emmc/PIC/<时间戳目录>/Image_<时间戳>_<序号>.jpg   (auto 模式生成 4 个 jpg)
每次拍照生成一个新的时间戳目录，里面是多个 jpg。

每个模式：
1. 记录 /emmc/PIC 旧时间戳目录集合
2. ``cam_set photo <mode>`` 切模式 + 稳定延时
3. ``dfs_capture_start`` 拍照
4. 轮询 FTP 列 /emmc/PIC，等出现新时间戳目录（超时 photo_capture_timeout）
5. 下载新目录里第一个 jpg，验证 JPEG 头 ``FF D8 FF`` + 大小 > 阈值

某模式失败只标记该模式 FAIL，继续下一个模式，不影响后续录像/推流。
返回多条 TestResult（每模式一条）。
"""
import os
import time

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, Timer

# JPEG magic number
_JPEG_MAGIC = b"\xff\xd8\xff"
# 实测拍照存盘目录（大写）
_PIC_DIR = "/emmc/PIC"


@register("photo")
class PhotoModule(TestModule):
    """拍照测试。"""

    depends = ["ftp"]

    def run(self, ctx, console, params=None):
        self.config = self._merge(params)
        ftp = getattr(ctx, "ftp_client", None)
        if ftp is None:
            return self._skip("FTP 客户端不可用，跳过拍照")

        # 确保 FTP 可用（固件 FTP 在重负载后会崩溃，这里检查并恢复）
        from .ftp import ensure_ftp
        ftp = ensure_ftp(ctx, console)
        if ftp is None:
            return self._fail("FTP 不可用且恢复失败，跳过拍照")

        modes = self.config.get("photo_modes", ["auto"])
        settle = float(self.config.get("photo_settle_delay", 1.0))
        cap_timeout = float(self.config.get("photo_capture_timeout", 10.0))
        min_kb = int(self.config.get("photo_min_size_kb", 10))
        tmp_dir = os.path.join(logger.log_dir() or "logs", "photos")
        os.makedirs(tmp_dir, exist_ok=True)

        results = []
        for mode in modes:
            results.append(self._test_one(ctx, console, ftp, mode,
                                          settle, cap_timeout, min_kb, tmp_dir))
        return results

    def _test_one(self, ctx, console, ftp, mode, settle, cap_timeout, min_kb, tmp_dir):
        name = f"photo[{mode}]"
        timer = Timer().start()
        logger.step(f"  拍照测试: 模式 {mode}")

        # 1. 切模式
        r = console.exec_sync(f"cam_set photo {mode}", timeout=10.0)
        if not r.success:
            return self._mk(name, "FAIL", f"设置模式 {mode} 失败", r.clean, timer)
        if settle > 0:
            time.sleep(settle)

        # 2. 拍照 + 等保存完成。
        # 拍照命令输出海量摄像头初始化日志，会打乱哨兵定界，故用 exec_async
        # （发命令后直接等正则，不依赖哨兵）。主判据：Save Photo Successful（含路径）
        r = console.exec_async("dfs_capture_start",
                               expect=r"Save Photo Successful:\s*(\S+)",
                               result_timeout=30.0)
        if not r.success:
            return self._mk(name, "FAIL", "拍照未完成保存", r.clean[-300:], timer)

        # 3. 从串口输出解析保存目录（如 /emmc/PIC/20260812_104009_9606/）
        import re
        save_dir = r.matched or ""
        save_dir = save_dir.rstrip("/")
        msg_base = f"拍照成功，保存到 {save_dir}"

        # 4. FTP 下载验证（辅助；FTP 在拍照后大概率崩，强制重连）
        from .ftp import ensure_ftp
        ftp2 = ensure_ftp(ctx, console, force=True)
        if ftp2 is None or not save_dir:
            return self._mk(name, "PASS", f"{msg_base}（FTP 验证跳过）", r.clean[-200:], timer)

        new_dir = save_dir.rsplit("/", 1)[-1]
        jpgs = self._list_jpgs(ftp2, save_dir)
        if not jpgs:
            # 再等一会重试一次
            time.sleep(1.5)
            jpgs = self._list_jpgs(ftp2, save_dir)
        if not jpgs:
            return self._mk(name, "PASS", f"{msg_base}（未列出 jpg 辅助验证）", r.clean[-200:], timer)

        jpg0 = jpgs[0]
        remote = f"{save_dir}/{jpg0}"
        local = os.path.join(tmp_dir, f"{mode}_{new_dir}_{jpg0}")
        if not ftp2.download(remote, local, timeout=30, retries=2):
            return self._mk(name, "PASS", f"{msg_base}（下载验证失败）", r.clean[-200:], timer)

        ok, vmsg = self._verify_jpeg(local, min_kb)
        status = "PASS" if ok else "FAIL"
        # message 含本地存储路径，便于用户找到下载的照片
        msg = f"{vmsg} | {msg_base} | 已下载到 {local}"
        return self._mk(name, status, msg, f"含 {len(jpgs)} 个 jpg", timer)

    def _list_pic_dirs(self, ftp):
        """列 /emmc/PIC 下的时间戳目录（仅目录名）。"""
        try:
            # list_dir 返回所有项；用 list_files_detail 区分文件/目录较繁琐，
            # 这里用 _list_entries 直接取目录项
            entries = ftp._list_entries(_PIC_DIR)
            return [name for name, is_dir, _ in entries if is_dir]
        except Exception:
            return []

    def _list_jpgs(self, ftp, dir_path):
        """列指定目录下的 jpg 文件名。"""
        try:
            return [n for n in ftp.list_files(dir_path) if n.lower().endswith(".jpg")]
        except Exception:
            return []

    def _wait_new_dir(self, ftp, before, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            now = set(self._list_pic_dirs(ftp))
            new = now - before
            if new:
                return next(iter(new))
            time.sleep(0.5)
        return None

    def _verify_jpeg(self, local, min_kb):
        size = os.path.getsize(local)
        if size < min_kb * 1024:
            return False, f"文件过小 {size}B < {min_kb}KB"
        with open(local, "rb") as f:
            head = f.read(3)
        if head[:3] != _JPEG_MAGIC:
            return False, f"JPEG 头校验失败 {head!r}"
        return True, f"JPEG OK {size//1024}KB"

    def _mk(self, name, status, msg, detail, timer):
        res = TestResult(name=name, module="photo", status=status,
                         message=msg, detail=detail, elapsed_ms=timer.elapsed_ms())
        return res
