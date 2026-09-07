import json
from pathlib import Path

from ATS.core.result import Response
from ATS.tools.windows_probe import probe_serial, write_probe_json


class Console:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False

    def open(self):
        pass

    def wait_for_ready(self):
        return True

    def health_check(self):
        return True

    def exec_sync(self, *args, **kwargs):
        return Response(success=True, matched="ATS_WIN_SYNC_OK")

    def exec_async(self, *args, **kwargs):
        return Response(success=True, matched="ATS_WIN_ASYNC_OK")

    def close(self):
        self.closed = True


def test_serial_probe_exercises_ready_health_sync_and_async():
    created = []

    def factory(**kwargs):
        console = Console(**kwargs)
        created.append(console)
        return console

    result = probe_serial("COM10", 2_000_000, console_factory=factory)

    assert result["ok"] is True
    assert result["port"] == "COM10"
    assert result["baudrate"] == 2_000_000
    assert result["ready"] is True
    assert result["health_check"] is True
    assert result["exec_sync"] is True
    assert result["exec_async"] is True
    assert created[0].closed is True


def test_probe_json_is_utf8_and_machine_readable(tmp_path):
    path = tmp_path / "串口 probe.json"
    write_probe_json(path, {"ok": True, "port": "COM10"})
    assert json.loads(path.read_text(encoding="utf-8"))["port"] == "COM10"


def test_serial_probe_waits_for_standalone_async_result_not_command_echo():
    calls = {}

    class CapturingConsole(Console):
        def exec_sync(self, command, **kwargs):
            calls["sync"] = (command, kwargs)
            return super().exec_sync(command, **kwargs)

        def exec_async(self, command, **kwargs):
            calls["async"] = (command, kwargs)
            return super().exec_async(command, **kwargs)

    result = probe_serial("COM10", 2_000_000, console_factory=CapturingConsole)

    assert result["ok"] is True
    assert calls["sync"][1]["expect"] == r"(?m)^[ \t]*ATS_WIN_SYNC_OK[ \t]*$"
    assert calls["async"][1]["expect"] == r"(?m)^[ \t]*ATS_WIN_ASYNC_OK[ \t]*$"
