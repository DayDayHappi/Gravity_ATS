"""RTMP server readiness abstraction independent of nginx deployment details."""
from __future__ import annotations

import socket
import time
from typing import Protocol


class RtmpBackendError(RuntimeError):
    pass


class RtmpServerBackend(Protocol):
    def check_ready(self, timeout: float = 8.0, cancellation_token=None) -> None:
        ...


class SocketRtmpServerBackend:
    """Treat a listening TCP endpoint as the RTMP server readiness contract."""

    def __init__(self, host: str = "127.0.0.1", port: int = 1935) -> None:
        self.host = host
        self.port = int(port)

    def is_ready(self) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                return sock.connect_ex((self.host, self.port)) == 0
        except OSError:
            return False

    def check_ready(self, timeout: float = 8.0, cancellation_token=None) -> None:
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if self.is_ready():
                return
            wait_time = min(0.1, max(0.0, deadline - time.monotonic()))
            if cancellation_token is None:
                time.sleep(wait_time)
            elif cancellation_token.wait(wait_time):
                cancellation_token.raise_if_cancelled()
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if not self.is_ready():
            raise RtmpBackendError(
                f"RTMP server is not ready at {self.host}:{self.port}; start the configured backend"
            )
