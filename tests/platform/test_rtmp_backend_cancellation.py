import threading
import time

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.platform.rtmp_backend import SocketRtmpServerBackend


def test_rtmp_readiness_wait_is_cancellable(monkeypatch):
    backend = SocketRtmpServerBackend()
    monkeypatch.setattr(backend, "is_ready", lambda: False)
    token = CancellationToken()
    threading.Timer(0.05, lambda: token.cancel("stop readiness")).start()
    started = time.monotonic()

    with pytest.raises(OperationCancelled):
        backend.check_ready(timeout=8.0, cancellation_token=token)

    assert time.monotonic() - started < 0.5
