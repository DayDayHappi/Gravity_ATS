import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.core.context import Context
from ATS.core.result import Response
from ATS.modules.video import VideoModule


class FakeFtp:
    def close(self):
        pass

    def _list_entries(self, _path):
        return []


class FakeConsole:
    def __init__(self):
        self.commands = []

    def exec_async(self, cmd, expect, result_timeout, **kwargs):
        self.commands.append((cmd, {"result_timeout": result_timeout, **kwargs}))
        if cmd == "dfs_video_start":
            return Response(success=True, clean="f_index = 0")
        return Response(success=True, clean="Video recording completed successfully.")


def test_video_cancel_sends_best_effort_stop_before_propagating(monkeypatch, tmp_path):
    token = CancellationToken()
    ctx = Context()
    ctx.ftp_client = FakeFtp()
    ctx.cancellation_token = token
    console = FakeConsole()
    monkeypatch.setattr("ATS.modules.ftp.ensure_ftp", lambda *_a, **_k: FakeFtp())
    monkeypatch.setattr("ATS.core.logger.log_dir", lambda: str(tmp_path))

    def cancel_on_wait(timeout):
        token.cancel("stop video")
        return True

    monkeypatch.setattr(token, "wait", cancel_on_wait)

    with pytest.raises(OperationCancelled):
        VideoModule({"video_duration": 180}).run(ctx, console)

    assert [cmd for cmd, _ in console.commands] == ["dfs_video_start", "dfs_video_stop"]
    assert console.commands[-1][1]["honor_cancellation"] is False
    assert console.commands[-1][1]["result_timeout"] <= 3.0
