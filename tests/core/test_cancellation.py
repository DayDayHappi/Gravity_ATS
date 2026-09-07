import threading
import time

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled


def test_cancel_is_idempotent_wakes_waiters_and_runs_callbacks_once():
    token = CancellationToken()
    calls = []
    woke = []
    token.register(lambda: calls.append("called"))
    thread = threading.Thread(target=lambda: woke.append(token.wait(5)))
    thread.start()

    token.cancel("operator stop")
    token.cancel("ignored second reason")
    thread.join(timeout=1)

    assert token.is_cancelled is True
    assert token.reason == "operator stop"
    assert calls == ["called"]
    assert woke == [True]


def test_raise_if_cancelled_uses_distinct_exception():
    token = CancellationToken()
    token.cancel("stop")
    with pytest.raises(OperationCancelled, match="stop"):
        token.raise_if_cancelled()
