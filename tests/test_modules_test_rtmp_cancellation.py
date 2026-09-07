import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.core.context import Context
from ATS.core.result import Response
from ATS.modules.rtmp import RtmpModule


class Console:
    def __init__(self):
        self.commands = []
        self.listeners = []

    def exec_async(self, cmd, expect, result_timeout, **kwargs):
        self.commands.append((cmd, kwargs))
        return Response(success=True, clean="Push Stop")

    def add_listener(self, cb):
        self.listeners.append(cb)

    def remove_listener(self, cb):
        if cb in self.listeners:
            self.listeners.remove(cb)


class Server:
    def check_ready(self):
        pass


class Receiver:
    def probe(self, *args, **kwargs):
        raise OperationCancelled("stop probe")

    def stop(self):
        pass


def test_rtmp_cancel_during_probe_always_stops_stream_and_clears_listener(monkeypatch):
    token = CancellationToken()
    ctx = Context()
    ctx.pc_ip = "127.0.0.1"
    ctx.cancellation_token = token
    console = Console()
    module = RtmpModule({"stream_duration": 600, "stream_url": "rtmp://{pc_ip}/live/cam"})
    module._server = Server()
    module._receiver = Receiver()
    monkeypatch.setattr(token, "wait", lambda timeout: False)

    with pytest.raises(OperationCancelled):
        module.run(ctx, console)

    assert [cmd for cmd, _ in console.commands] == [
        "rtmp_video_start rtmp://127.0.0.1/live/cam",
        "rtmp_video_stop",
    ]
    assert console.commands[-1][1]["honor_cancellation"] is False
    assert console.listeners == []
