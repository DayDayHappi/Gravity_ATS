import sys
import time

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.drivers.h265_validator import H265Validator


def test_h265_spawn_terminates_process_on_cancel(tmp_path):
    token = CancellationToken()
    validator = H265Validator({"ffmpeg_path": sys.executable}, cancellation_token=token)
    token.register(lambda: None)

    import threading
    threading.Timer(0.15, lambda: token.cancel("stop ffmpeg")).start()
    started = time.monotonic()
    with pytest.raises(OperationCancelled):
        validator._spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=30,
            log_path=str(tmp_path / "proc.log"),
        )
    assert time.monotonic() - started < 2.0
