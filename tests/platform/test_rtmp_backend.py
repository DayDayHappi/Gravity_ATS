import socket
import threading

from ATS.platform.rtmp_backend import SocketRtmpServerBackend


def test_socket_backend_reports_ready_for_listening_port():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        backend = SocketRtmpServerBackend(port=port)
        assert backend.is_ready() is True
        backend.check_ready(timeout=0.1)
    finally:
        server.close()
