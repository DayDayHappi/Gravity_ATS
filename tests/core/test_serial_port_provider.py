from ATS.core import serial_console


class Provider:
    def candidate_names(self):
        return ["COM3", "COM10"]


def test_detect_port_uses_cross_platform_provider_and_fingerprint(monkeypatch):
    monkeypatch.setattr(serial_console, "serial", object())
    probes = []

    def probe(port, baudrate, detect_timeout):
        probes.append((port, baudrate))
        return port == "COM10" and baudrate == 2_000_000

    monkeypatch.setattr(serial_console, "_probe_port_baud", probe)

    port, baud = serial_console.detect_port(
        baudrate=2_000_000,
        baud_candidates=[2_000_000, 115200],
        interactive=False,
        port_provider=Provider(),
    )

    assert (port, baud) == ("COM10", 2_000_000)
    assert ("COM3", 2_000_000) in probes


class ChoiceProvider:
    def __init__(self):
        self.calls = []

    def choose(self, prompt, options, default_index=0):
        self.calls.append((prompt, list(options), default_index))
        return options[1]


def test_detect_port_routes_multiple_match_choice_through_interaction_provider(monkeypatch):
    monkeypatch.setattr(serial_console, "serial", object())
    monkeypatch.setattr(
        serial_console,
        "_probe_port_baud",
        lambda port, baudrate, detect_timeout: baudrate == 2_000_000,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("core read stdin")),
    )
    provider = ChoiceProvider()

    selected = serial_console.detect_port(
        baudrate=2_000_000,
        baud_candidates=[2_000_000],
        interactive=True,
        port_provider=Provider(),
        interaction_provider=provider,
    )

    assert selected == ("COM10", 2_000_000)
    assert provider.calls == [
        ("请选择 EVB 串口", [("COM3", 2_000_000), ("COM10", 2_000_000)], 0)
    ]


def test_detect_port_multiple_matches_is_deterministic_without_provider(monkeypatch):
    monkeypatch.setattr(serial_console, "serial", object())
    monkeypatch.setattr(
        serial_console,
        "_probe_port_baud",
        lambda port, baudrate, detect_timeout: baudrate == 2_000_000,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("core read stdin")),
    )

    assert serial_console.detect_port(
        baudrate=2_000_000,
        baud_candidates=[2_000_000],
        interactive=True,
        port_provider=Provider(),
    ) == ("COM3", 2_000_000)


def test_health_check_propagates_cancellation(monkeypatch):
    monkeypatch.setattr(serial_console, "serial", object())
    console = serial_console.SerialConsole("COM10")

    def cancelled(*_args, **_kwargs):
        from ATS.core.cancellation import OperationCancelled
        raise OperationCancelled("stop during health check")

    monkeypatch.setattr(console, "exec_sync", cancelled)

    import pytest
    from ATS.core.cancellation import OperationCancelled
    with pytest.raises(OperationCancelled):
        console.health_check()
