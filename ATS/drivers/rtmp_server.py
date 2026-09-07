"""RTMP server readiness driver backed by a platform-neutral backend contract."""
from __future__ import annotations

from ..core import logger
from ..platform.rtmp_backend import RtmpBackendError, SocketRtmpServerBackend


class RtmpServerError(Exception):
    pass


class RtmpServer:
    def __init__(self, port=1935, backend=None):
        self.port = int(port)
        self.backend = backend or SocketRtmpServerBackend(port=self.port)

    def check_ready(self, timeout: float = 8.0, cancellation_token=None) -> None:
        logger.info(f"检查 RTMP Server 是否监听 :{self.port}")
        try:
            try:
                self.backend.check_ready(timeout, cancellation_token=cancellation_token)
            except TypeError:
                # Backward-compatible custom backends may implement the original
                # readiness-only signature.
                self.backend.check_ready(timeout)
        except RtmpBackendError as exc:
            raise RtmpServerError(str(exc)) from exc
        logger.info(f"RTMP Server 就绪，监听 :{self.port}")
