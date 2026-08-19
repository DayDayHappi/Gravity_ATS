"""FTP 客户端封装。

封装标准库 ``ftplib``，连接 EVB 上的 FTP 服务，用于：
- 列目录（拍照前后对比找新增文件）
- 下载（从板子复制照片/视频到本地，二进制 retrbinary 保证字节完整）
- 上传（验证双向通路）

所有操作带重试：网络抖动/服务未完全就绪时重连重试，避免偶发失败误判。

连接模型：板子端 FTP 服务空闲约 3s 会断开会话，故不缓存/复用旧连接；每次
下载前都重新 connect()（新 socket -> 重新登录 -> cwd 根目录）。该 FTP 只支持
主动模式（PORT）：每次传输由 ftplib 重新 makeport() 起一个新数据端口，让
服务器主动连回，天然避免旧端口 TIME_WAIT 复用失败。
"""
import os
import time
import threading
from ftplib import FTP, error_perm, error_temp, error_proto

from ..core import logger


class FtpError(Exception):
    """FTP 操作异常。"""


class FtpClient:
    """EVB FTP 服务的客户端封装。

    连接参数默认对齐手册：端口 21，用户 loogg/loogg。
    """

    def __init__(self, host, port=21, user="loogg", password="loogg",
                 retry=3, interval=1.0, pasv=False, timeout=10):
        """EVB FTP（RT-Thread）默认用主动模式：该服务不支持 PASV（502）。
        主动模式需 PC 防火墙放行入站数据端口（或临时关闭防火墙）。
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.retry = retry
        self.interval = interval
        self.pasv = pasv
        self.timeout = timeout
        self._ftp = None

    # ---------- 连接 ----------

    def connect(self) -> None:
        """连接并登录 FTP，失败按 retry 重试。

        每次调用都是与上一次完全独立的新连接：新 socket -> connect(读欢迎信息，
        ftplib 内部 getresp() 已读净，不留缓冲) -> USER/PASS 登录 -> 主动模式 ->
        cwd 根目录（恢复工作目录到已知基线，后续按绝对路径操作）。
        板子 FTP 会话空闲一段时间会被服务端断开，调用方不应假设旧连接仍然存活，
        需要时直接调用本方法重连，而不是复用/探测旧连接。
        """
        last_err = None
        # 若已存在旧连接（同一对象复用），先关闭避免泄漏旧 socket。
        self._safe_close()
        for attempt in range(1, self.retry + 1):
            try:
                ftp = FTP()
                ftp.connect(self.host, self.port, timeout=self.timeout)
                ftp.login(self.user, self.password)
                ftp.set_pasv(self.pasv)
                try:
                    ftp.cwd("/")
                except Exception:
                    pass
                self._ftp = ftp
                logger.debug(f"FTP 已连接 {self.host}:{self.port} (尝试 {attempt})")
                return
            except Exception as e:
                last_err = e
                logger.debug(f"FTP 连接失败(尝试 {attempt}/{self.retry}): {e}")
                self._safe_close()
                time.sleep(self.interval)
        raise FtpError(f"FTP 连接失败（重试 {self.retry} 次）: {last_err}")

    def _ensure(self):
        if self._ftp is None:
            raise FtpError("FTP 未连接，请先 connect()")

    def _safe_close(self):
        if self._ftp is not None:
            try:
                self._ftp.close()
            except Exception:
                pass
            self._ftp = None

    def close(self):
        self._safe_close()

    # ---------- 操作（带重试） ----------

    def _with_retry(self, op_name, fn):
        """对易错操作做重试：失败先重连再重试。"""
        self._ensure()
        last_err = None
        for attempt in range(1, self.retry + 1):
            try:
                return fn()
            except (error_temp, error_proto, EOFError, OSError) as e:
                # 临时性错误：重连重试
                last_err = e
                logger.debug(f"FTP {op_name} 失败(尝试 {attempt}): {e}，重连...")
                try:
                    self.connect()
                except FtpError:
                    time.sleep(self.interval)
            except error_perm as e:
                # 权限/永久错误：不重试
                raise FtpError(f"FTP {op_name} 权限错误: {e}")
        raise FtpError(f"FTP {op_name} 失败（重试 {self.retry} 次）: {last_err}")

    def list_dir(self, path="") -> list:
        """列目录，返回所有项（文件+子目录）的名称列表。

        该 FTP 服务不支持 NLST，用 LIST 解析。path 为空列当前目录。
        返回纯名称列表（不含详情）。
        """
        entries = self._list_entries(path)
        return [name for name, _is_dir, _size in entries]

    def list_files(self, path="") -> list:
        """列目录，仅返回文件名（排除子目录）。

        依赖 LIST 输出中的目录标记（``<DIR>`` 或 ``d`` 开头）。
        """
        entries = self._list_entries(path)
        return [name for name, is_dir, _size in entries if not is_dir]

    def list_files_detail(self, path="") -> list:
        """列目录，返回 [(name, size), ...] 仅文件。供需要大小的调用方使用。"""
        entries = self._list_entries(path)
        return [(name, size) for name, is_dir, size in entries if not is_dir]

    def _list_entries(self, path="") -> list:
        """用 LIST 命令解析目录，返回 [(name, is_dir, size), ...]。

        该 FTP 服务 ``LIST <path>`` 会忽略路径参数，必须先 CWD 到目标目录
        再用无参 LIST 才能列对。这里 CWD->LIST->CWD回原目录。
        """
        def _do():
            self._ensure()
            orig = None
            try:
                orig = self._ftp.pwd()
            except Exception:
                pass
            entries = []
            try:
                if path:
                    try:
                        self._ftp.cwd(path)
                    except Exception:
                        return entries
                def _collect(line):
                    parsed = self._parse_list_line(line)
                    if parsed:
                        entries.append(parsed)
                self._ftp.retrlines("LIST", _collect)
            finally:
                if orig:
                    try:
                        self._ftp.cwd(orig)
                    except Exception:
                        pass
            return entries
        try:
            return self._with_retry("list", _do)
        except FtpError:
            return []

    @staticmethod
    def _parse_list_line(line: str):
        """解析一行 LIST 输出，返回 (name, is_dir, size) 或 None。"""
        line = line.strip()
        if not line or line in (".", ".."):
            return None
        # Unix 风格: 权限位开头
        if len(line) > 30 and line[0] in "-d":
            parts = line.split(None, 8)
            if len(parts) < 9:
                return None
            perm = parts[0]
            is_dir = perm[0] == "d"
            size = int(parts[4]) if parts[4].isdigit() else 0
            name = parts[8].split()[0] if parts[8:] else ""
            # 去可能的 "-> link" 等
            name = name.split(" -> ")[0]
            if name in (".", ".."):
                return None
            return (name, is_dir, size)
        # RT-Thread 风格: "name <DIR>" 或 "name size"
        if "<DIR>" in line:
            name = line.replace("<DIR>", "").strip().split()[0]
            return (name, True, 0)
        parts = line.rsplit(None, 1)
        if len(parts) == 2 and parts[1].isdigit():
            return (parts[0], False, int(parts[1]))
        # 仅名称
        name = line.split()[0] if line.split() else ""
        return (name, False, 0) if name else None

    def size(self, remote_path: str) -> int:
        """获取远程文件大小。该FTP不支持SIZE命令，用LIST父目录解析。"""
        try:
            self._ensure()
            remote_path = remote_path.rstrip("/")
            parent = remote_path.rsplit("/", 1)[0] or "/"
            base = remote_path.rsplit("/", 1)[-1]
            for name, is_dir, sz in self._list_entries(parent):
                if name == base and not is_dir:
                    return sz
            return -1
        except Exception:
            return -1

    def download(self, remote_path: str, local_path: str, timeout: float = 30.0,
                 retries: int = 5) -> bool:
        """从板子复制文件到本地（二进制下载，支持断点续传）。

        板子 FTP 会话空闲超过约 3s 会被服务端断开，不能假设调用前的旧连接
        还活着。每次下载开始时都先重新 connect()（全新独立的控制连接：新
        socket -> 重新登录 -> cwd 根目录），基于这条新连接查大小、发起传输；
        续传重试同样重新 connect()，不复用可能已死的旧连接。数据连接（主动
        模式 PORT）由 ftplib 在每次实际传输时自动重新协商，天然使用新端口。

        固件 FTP 传大文件易卡死。用全局 socket 超时使卡死的 recv 抛异常（不无限阻塞），
        失败后用 REST 命令断点续传（从已下载位置继续，不从头）。多次续传可下完大文件。

        Args:
            remote_path: 板子上的文件路径。
            local_path: 本地保存路径。
            timeout: 单次 socket 操作超时秒数（卡死即中断续传）。
            retries: 断点续传最大尝试次数。

        Returns:
            True 下载成功（本地 >= 远端）；False 失败/不完整（保留部分文件）。
        """
        import socket as _socket
        old_timeout = _socket.getdefaulttimeout()
        _socket.setdefaulttimeout(timeout)
        try:
            # 独立于此前任何操作，先建一条全新连接用于本次下载
            try:
                self.connect()
            except FtpError as e:
                logger.warn(f"下载前建连失败: {e}")
                return False
            total = self.size(remote_path)
            for attempt in range(1, retries + 1):
                if self._ftp is None:
                    try:
                        self.connect()
                    except FtpError as e:
                        logger.warn(f"下载前重连失败(尝试{attempt}/{retries}): {e}")
                        continue
                # 已下载字节数（续传起点）
                offset = os.path.getsize(local_path) if os.path.exists(local_path) else 0
                if total > 0 and offset >= total:
                    return True  # 已下完
                try:
                    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                    # 追加模式，REST 设置服务器偏移
                    mode = "ab" if offset > 0 else "wb"
                    with open(local_path, mode) as f:
                        # retrbinary 的 rest 参数让服务器从 offset 开始传
                        self._ftp.retrbinary(f"RETR {remote_path}", f.write, rest=offset if offset > 0 else None)
                    # 检查完整性
                    local_sz = os.path.getsize(local_path)
                    if total <= 0 or local_sz >= total:
                        return True
                    logger.warn(f"下载提前结束({local_sz//1024}KB/{total//1024}KB)，续传 {attempt}/{retries}")
                except Exception as e:
                    logger.warn(f"下载异常(尝试{attempt}/{retries})，已传"
                                f"{os.path.getsize(local_path)//1024 if os.path.exists(local_path) else 0}KB: {e}")
                # 连接已不可用，重连（全新会话）后续传
                self._safe_close()
                try:
                    self.connect()
                except FtpError:
                    pass
            # 最终检查
            local_sz = os.path.getsize(local_path) if os.path.exists(local_path) else 0
            return total > 0 and local_sz >= total
        finally:
            _socket.setdefaulttimeout(old_timeout)

    def upload(self, local_path: str, remote_path: str) -> bool:
        """从本地上传文件到板子。

        注意：EVB 的 RT-Thread FTP 服务实测不支持 STOR（502），上传会失败。
        保留接口供支持上传的 FTP 服务使用；当前固件下返回 False。
        """
        if not os.path.isfile(local_path):
            return False

        def _do():
            self._ensure()
            with open(local_path, "rb") as f:
                self._ftp.storbinary(f"STOR {remote_path}", f)
            return True
        try:
            return self._with_retry("upload", _do)
        except FtpError as e:
            logger.warn(f"上传失败 {local_path}（该FTP可能不支持STOR）: {e}")
            return False
