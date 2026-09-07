from types import SimpleNamespace

import pytest

from ATS.core.cancellation import OperationCancelled
from ATS.core.scenario_manager import _action_serial_init
from ATS.platform.serial_registry import SerialPortRegistry


class Console:
    instance = None

    def __init__(self, **_kwargs):
        self.closed = False
        Console.instance = self

    def open(self):
        pass

    def wait_for_ready(self):
        raise OperationCancelled("stop during ready")

    def health_check(self):
        return True

    def close(self):
        self.closed = True


def test_serial_init_closes_local_console_and_releases_lease_when_cancelled(monkeypatch):
    registry = SerialPortRegistry()
    services = SimpleNamespace(serial_registry=registry)
    ctx = SimpleNamespace(
        platform_services=services,
        run_id="run-1",
        cancellation_token=None,
    )
    monkeypatch.setattr("ATS.core.scenario_manager.SerialConsole", Console)

    with pytest.raises(OperationCancelled):
        _action_serial_init(ctx, {"serial": {"port": "COM10", "baudrate": 2_000_000}})

    assert Console.instance.closed is True
    assert registry.owner("COM10") is None
