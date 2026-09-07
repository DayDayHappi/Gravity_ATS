from ATS.application.models import RunResult, RunStatus


def test_cli_constructs_run_request_and_uses_service_exit_code(monkeypatch, tmp_path):
    import ATS.main as cli

    captured = {}

    class FakeService:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def run(self, request):
            captured["request"] = request
            return RunResult(run_id="r", scenario=request.scenario, status=RunStatus.FAILED)

    monkeypatch.setattr(cli, "TestService", FakeService)
    monkeypatch.setattr(cli, "_record_test_problem", lambda *_args, **_kwargs: None)

    rc = cli.main([
        "--scenario", "normal",
        "--port", "COM10",
        "--baudrate", "2000000",
        "--output-dir", str(tmp_path),
        "--no-interactive-wifi",
    ])

    assert rc == 1
    request = captured["request"]
    assert request.scenario == "normal"
    assert request.system_overrides["serial.port"] == "COM10"
    assert request.system_overrides["serial.baudrate"] == 2_000_000
    assert request.no_interactive_wifi is True


def test_cli_does_not_prompt_for_problem_when_no_execution_report(monkeypatch, tmp_path):
    import ATS.main as cli

    prompted = []

    class FakeService:
        def __init__(self, **kwargs):
            pass

        def run(self, request):
            return RunResult(
                run_id="r",
                scenario=request.scenario,
                status=RunStatus.ERROR,
                problem_root=str(tmp_path / "problem"),
                report_dir="",
                error="missing dependency",
            )

    monkeypatch.setattr(cli, "TestService", FakeService)
    monkeypatch.setattr(cli, "_record_test_problem", lambda *_a, **_k: prompted.append(True))

    assert cli.main(["--scenario", "normal"]) == 2
    assert prompted == []
