"""RTMP 服务端就绪探测：检查本机 nginx-rtmp 是否已启动并监听 1935。

为什么需要服务端：RTMP 推流测试拓扑是「EVB 推流到 PC + PC 用 ffprobe/ffplay 验证」，
两端都指向 PC 的 1935 端口。PC 上必须有一个 RTMP 服务端接收 EVB 推流(publish)并
把它中转出来供 ffprobe 探测 / ffplay 播放。本项目用 **nginx-rtmp** 做这个服务端。

启停策略（与 MediaMTX 时代的区别）：nginx-rtmp 通常作为系统服务运行（由用户或
systemd 启动），脚本**不 subprocess 启停 nginx**——否则会和 systemd/sudo 冲突。
脚本只做「就绪检查」：确认 1935 端口在监听即认为服务端就绪，未就绪报错提示用户
手动启动（`systemctl start nginx` 或 `nginx` 命令）。

流程：
1. ``check_ready()``：轮询 1935 端口是否进入 LISTEN，未就绪抛 RtmpServerError。

nginx-rtmp 配置要求：``application live { live on; record off; }``，故推流地址
``rtmp://<pc_ip>/live/cam`` 中 ``live`` 是 application 名、``cam`` 是 stream key。
"""
import time
import socket

from ..core import logger


class RtmpServerError(Exception):
    pass


class RtmpServer:
    """PC 端 nginx-rtmp 服务端就绪探测（不启停 nginx）。

    一次实例对应一次推流测试：check_ready -> (EVB 推流 + ffprobe/ffplay 验证)。
    nginx 进程的启停由用户/系统负责，本类不持有也不管理子进程。
    """

    def __init__(self, port=1935):
        self.port = port

    def check_ready(self, timeout: float = 8.0) -> None:
        """检查 nginx-rtmp 是否已启动并监听 1935。

        Args:
            timeout: 轮询端口监听的最长秒数。

        Raises:
            RtmpServerError: 1935 端口未监听（nginx-rtmp 未启动）。
        """
        logger.info(f"检查 RTMP 服务端 (nginx-rtmp) 是否监听 :{self.port}")
        if not self._wait_port_ready(timeout):
            raise RtmpServerError(
                f"nginx-rtmp 服务端未就绪: {self.port} 端口未监听。"
                f"请手动启动 nginx-rtmp（systemctl start nginx 或 nginx 命令），"
                f"并确认配置了 application live（监听 1935）。")
        logger.info(f"nginx-rtmp 就绪，RTMP 监听 :{self.port}")

    def _wait_port_ready(self, timeout: float) -> bool:
        """轮询本机端口是否进入 LISTEN。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
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
