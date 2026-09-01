"""下载模块：从板端 FTP 下载文件到本地，不做任何业务测试。

配合「纯录像」场景（``video_ftp_download=false``，只录不下载）使用：拍摄脚本走完后，
用户手动 ``--scenario download`` 把板端文件按需下载到电脑。

参数接口（config/modules/download.yaml + scenario override）：

- ``sources``: 下载来源列表，可含多组（视频/照片/其他），每组 {label, dir, pattern}。
- ``latest_n``: 每个来源取最新的 N 个时间戳子目录。
- ``download_dest``: 本地下载根目录（其下 ``downloads/<日期>/<label>/<子目录>/<文件>``）。
- ``download_timeout`` / ``download_retries``: 单文件下载 socket 超时 / 断点续传重试。

下载逻辑（每个 source 一次）：

1. 列 ``source.dir`` 下所有子目录（时间戳目录）。
2. 按目录名降序（时间戳目录名形如 ``YYYYMMDD_HHMMSS[_序号]``，字典序=时间序），
   取前 ``latest_n`` 个。
3. 对每个子目录列匹配 ``pattern`` 的文件，逐个 ``FtpClient.download()`` 下载。
4. 单文件失败不中断整体，按 source 汇总成功数/失败数/总大小。

不删除板端文件（``DELE`` 不用）。模块内遍历 sources/子目录/文件由配置驱动
（与 photo 遍历 photo_modes 同款模式，非业务循环），符合模块红线。
"""
import os
import fnmatch
import datetime as _dt

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, Timer


@register("download")
class DownloadModule(TestModule):
    """仅下载模块（不做测试）。"""

    depends = []

    def run(self, ctx, console, params=None):
        self.config = self._merge(params)
        ftp = getattr(ctx, "ftp_client", None)
        if ftp is None:
            return self._skip("FTP 客户端不可用，跳过下载")

        # 每次下载前重建连接（板子 FTP 服务端 3s 空闲即断会话；下载内部也会重连）
        from .ftp import ensure_ftp
        ftp = ensure_ftp(ctx, console)
        if ftp is None:
            return self._fail("FTP 不可用且恢复失败，跳过下载")

        sources = self.config.get("sources") or []
        if not sources:
            return self._fail("未配置 sources，无下载来源")

        latest_n = int(self.config.get("latest_n", 20))
        dest_root = self.config.get("download_dest", "downloads")
        timeout = float(self.config.get("download_timeout", 30))
        retries = int(self.config.get("download_retries", 5))
        date = _dt.datetime.now().strftime("%Y%m%d")

        results = []
        for src in sources:
            results.append(self._download_source(
                ctx, ftp, src, latest_n, dest_root, date, timeout, retries))
        return results

    # ---------- 内部 ----------

    def _download_source(self, ctx, ftp, src, latest_n, dest_root, date,
                         timeout, retries):
        """下载单个来源（一组 label/dir/pattern），返回一条 TestResult。"""
        label = src.get("label", "files") if isinstance(src, dict) else str(src)
        name = f"download[{label}]"
        timer = Timer().start()
        remote_dir = (src.get("dir") if isinstance(src, dict) else "") or ""
        pattern = (src.get("pattern", "*") if isinstance(src, dict) else "*") or "*"

        if not remote_dir:
            return self._mk(name, "FAIL", f"来源 {label} 缺 dir", "", timer)

        logger.step(f"  下载来源 {label}: {remote_dir} (pattern={pattern}, 最新 {latest_n} 个目录)")

        # 1. 列根目录下的时间戳子目录
        subdirs = self._list_subdirs(ftp, remote_dir)
        if not subdirs:
            return self._mk(name, "PASS", f"{label}: {remote_dir} 下无子目录", "", timer)

        # 2. 目录名降序（时间戳字典序=时间序），取前 N（latest_n<=0 视为全取）
        subdirs_sorted = sorted(subdirs, reverse=True)
        picked = subdirs_sorted[:latest_n] if latest_n > 0 else subdirs_sorted
        logger.info(f"{label}: {remote_dir} 目录总数 {len(subdirs_sorted)}，"
                    f"实际取最新 {len(picked)} 个")

        # 3. 逐个子目录下载匹配 pattern 的文件；单文件失败不中断整体。
        #    逐文件打印成功/失败，带远端/本地大小（来自 ftp.download() 的 out 回传），
        #    便于确认是否有残缺文件静默入库。
        ok = 0
        fail = 0
        total_bytes = 0
        for sub in picked:
            remote_sub = f"{remote_dir.rstrip('/')}/{sub}"
            for fname in self._list_files(ftp, remote_sub, pattern):
                remote_path = f"{remote_sub}/{fname}"
                local_path = os.path.join(dest_root, date, label, sub, fname)
                info = {}
                logger.info(f"下载 {remote_path} -> {local_path}")
                if ftp.download(remote_path, local_path, timeout=timeout,
                                retries=retries, out=info):
                    ok += 1
                    local_sz = info.get("local_size") or os.path.getsize(local_path)
                    total_bytes += local_sz
                    remote_sz = info.get("remote_size", -1) or -1
                    remote_s = f"{remote_sz//1024}KB" if remote_sz > 0 else "未知"
                    resumed_s = "（续传）" if info.get("resumed") else ""
                    logger.info(f"  成功 {fname}: 远端 {remote_s} / "
                                f"本地 {local_sz//1024}KB{resumed_s}")
                else:
                    fail += 1
                    local_sz = (info.get("local_size")
                                or (os.path.getsize(local_path) if os.path.exists(local_path) else 0))
                    remote_sz = info.get("remote_size", -1) or -1
                    remote_s = f"{remote_sz//1024}KB" if remote_sz > 0 else "未知"
                    logger.warn(f"  失败 {fname}: 远端 {remote_s} / 本地 {local_sz//1024}KB")

        total_kb = total_bytes // 1024
        # 单个文件失败不判整体失败；全部失败才 FAIL
        status = "FAIL" if ok == 0 and fail > 0 else "PASS"
        msg = (f"{label}: 目录 {len(picked)}/{len(subdirs_sorted)} 个，"
               f"下载 {ok} 个文件 / 共 {total_kb}KB / 失败 {fail} 个 "
               f"-> {os.path.join(dest_root, date, label)}")
        detail = (f"{remote_dir} 目录总数 {len(subdirs_sorted)}，实际取最新 {len(picked)} 个；"
                  f"成功 {ok} 个 / 失败 {fail} 个 / 共 {total_kb}KB")
        return self._mk(name, status, msg, detail, timer)

    def _list_subdirs(self, ftp, path):
        """列指定目录下的子目录名（复用 FtpClient._list_entries 的 is_dir 标记）。"""
        try:
            return [n for n, is_dir, _ in ftp._list_entries(path) if is_dir]
        except Exception:
            return []

    def _list_files(self, ftp, path, pattern):
        """列指定目录下匹配 pattern 的文件名（fnmatch）。"""
        try:
            names = [n for n, is_dir, _ in ftp._list_entries(path) if not is_dir]
            return [n for n in names if fnmatch.fnmatch(n, pattern)]
        except Exception:
            return []

    def _mk(self, name, status, msg, detail, timer):
        return TestResult(name=name, module="download", status=status,
                          message=msg, detail=detail, elapsed_ms=timer.elapsed_ms())
