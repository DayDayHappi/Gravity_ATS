from types import SimpleNamespace

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.core.result import Response
from ATS.modules.video import VideoModule


class Ftp:
    def _list_entries(self, _path):
        return []


class Console:
    def __init__(self):
        self.calls = []

    def exec_async(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command == "dfs_video_start":
            raise OperationCancelled("stop during video start")
        return Response(success=True, clean="Please start")


def test_video_cancellation_during_start_still_sends_best_effort_stop(monkeypatch):
    ftp = Ftp()
    monkeypatch.setattr("ATS.modules.ftp.ensure_ftp", lambda *_args, **_kwargs: ftp)
    console = Console()
    token = CancellationToken()
    ctx = SimpleNamespace(ftp_client=ftp, cancellation_token=token)

    with pytest.raises(OperationCancelled):
        VideoModule({"video_duration": 180}).run(ctx, console)

    stop_calls = [kwargs for command, kwargs in console.calls if command == "dfs_video_stop"]
    assert len(stop_calls) == 1
    assert stop_calls[0]["honor_cancellation"] is False
    assert stop_calls[0]["result_timeout"] <= 3.0
