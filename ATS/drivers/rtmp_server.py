"""RTMP 服务端：PC 上用 MediaMTX 接收 EVB 推流并中转给 ffmpeg 拉流。

为什么需要服务端：RTMP 推流测试拓扑是「EVB 推流到 PC + PC 用 ffmpeg 拉流」，两端
都指向 PC 的 1935 端口。必须在 PC 上起一个 RTMP 服务端接收 EVB 推流(publish)并
把它中转出来供 ffmpeg 拉流(play)。MediaMTX 是单文件预编译二进制，解压即用、无需
编译/依赖，适合离线环境。

流程：
1. ``start()``：subprocess 启动 MediaMTX（最小化配置，只开 RTMP），等 1935 就绪。
2. ``stop()``：终止 MediaMTX 进程。

为什么用最小化配置(只开 rtmp)：MediaMTX 默认配置同时开 RTSP/HLS/WebRTC/SRT/MoQ
等协议，多协议冲突会导致推流端 Broken pipe、拉流端 I/O error。只开 RTMP 后稳定。

MediaMTX 路径规则：默认 ``paths: all_others`` 接受任意路径，故
``rtmp://<pc_ip>/live/cam1`` 直接可用，无需为 ``live`` 单独配 application。

依赖：项目内置 ``tools/mediamtx/mediamtx`` 二进制 + ``tools/mediamtx/mediamtx_min.yml``。
"""
import os
import time
import socket
import subprocess

from ..core import logger


def _find_mediamtx(preferred=None) -> str:
    """查找 MediaMTX 可执行文件。优先配置指定，其次项目内置，再次 PATH。"""
    if preferred and os.path.isfile(preferred):
        return preferred
    # 项目内置默认路径（基于运行时 cwd = 项目根）
    builtin = os.path.join("tools", "mediamtx", "mediamtx")
    if os.path.isfile(builtin):
        return builtin
    if preferred and os.path.isfile(preferred):
        return preferred
    import shutil
    p = shutil.which("mediamtx")
    if p:
        return p
    return ""


class RtmpServerError(Exception):
    pass


class RtmpServer:
    """PC 端 RTMP 服务端（MediaMTX）封装。

    一次实例对应一次推流测试：start -> (EVB 推流 + ffmpeg 拉流) -> stop。
    """

    def __init__(self, mediamtx_path=None, config_path=None, port=1935):
        self.mediamtx_path = mediamtx_path or _find_mediamtx()
        # 配置文件默认取与二进制同目录的最小化配置
        self.config_path = config_path or os.path.join("tools", "mediamtx", "mediamtx_min.yml")
        self.port = port
        self._proc = None

    @property
    def available(self) -> bool:
        """MediaMTX 二进制与配置是否就绪。"""
        return bool(self.mediamtx_path and os.path.isfile(self.mediamtx_path)
                    and os.path.isfile(self.config_path))

    def start(self, ready_timeout: float = 8.0):
        """启动 MediaMTX，等 1935 端口就绪。

        Args:
            ready_timeout: 等端口监听的最长秒数。

        Raises:
            RtmpServerError: 二进制缺失或端口未就绪。
        """
        if not self.available:
            raise RtmpServerError(
                f"MediaMTX 不可用: 二进制={self.mediamtx_path!r} 配置={self.config_path!r}")
        if self._proc is not None and self._proc.poll() is None:
            logger.warn("MediaMTX 已在运行，先停止")
            self.stop()

        cmd = [self.mediamtx_path, self.config_path]
        logger.info(f"启动 RTMP 服务端 MediaMTX: {' '.join(cmd)}")
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise RtmpServerError(f"MediaMTX 启动失败: {e}")

        # 等 1935 端口就绪
        if not self._wait_port_ready(ready_timeout):
            # 端口没起来，收集 stderr 辅助排查
            err = ""
            if self._proc.stderr:
                try:
                    err = self._proc.stderr.read(500).decode("utf-8", "ignore")
                except Exception:
                    pass
            self.stop()
            raise RtmpServerError(
                f"MediaMTX 启动后 {self.port} 端口未就绪，stderr: {err!r}")
        logger.info(f"MediaMTX 就绪，RTMP 监听 :{self.port}")

    def _wait_port_ready(self, timeout: float) -> bool:
        """轮询本机端口是否进入 LISTEN。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            # 进程已退出则不必再等
            if self._proc and self._proc.poll() is not None:
                return False
            if self._is_port_listening():
                return True
            time.sleep(0.2)
        return self._is_port_listening()

    def _is_port_listening(self) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                # 连本机端口，连得上说明在监听
                return s.connect_ex(("127.0.0.1", self.port)) == 0
        except Exception:
            return False

    def stop(self):
        """终止 MediaMTX 进程。"""
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
