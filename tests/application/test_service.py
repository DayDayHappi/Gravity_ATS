from pathlib import Path

from ATS.application.models import RunRequest, RunStatus
from ATS.application.service import TestService
from ATS.core.result import TestResult


class FakeScenario:
    name = "normal"
    tasks = []


class FakeManager:
    def __init__(self, config_dir=None, **kwargs):
        self.config_dir = config_dir
        self.kwargs = kwargs

    def load(self, name):
        assert name == "normal"
        return FakeScenario()

    def run(self, scenario_name, **kwargs):
        assert scenario_name == "normal"
        assert kwargs["module_overrides"] == {"video": {"video_duration": 1}}
        return [TestResult(name="ok", module="dummy", status="PASS")]


def test_service_runs_without_tty_and_returns_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("stdin used")))
    generated = {}

    def reporter(results, out_dir, junit=True, html=True):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        path = Path(out_dir) / "result.json"
        path.write_text("{}", encoding="utf-8")
        generated["out_dir"] = out_dir
        return {"json": str(path)}

    service = TestService(
        scenario_manager_factory=FakeManager,
        system_loader=lambda _config_dir: {"runner": {}, "report": {"junit": True, "html": True}},
        dependency_checker=lambda *_: [],
        reporter=reporter,
    )
    request = RunRequest(
        scenario="normal",
        config_dir=str(tmp_path / "config"),
        output_dir=str(tmp_path / "reports"),
        module_overrides={"video": {"video_duration": 1}},
        no_interactive_wifi=True,
    )

    result = service.run(request)

    assert result.status is RunStatus.PASSED
    assert result.exit_code == 0
    assert result.results[0].status == "PASS"
    assert result.report_paths["json"].endswith("result.json")
    assert generated["out_dir"] == result.report_dir


def test_service_converts_environment_failure_to_error_result(tmp_path):
    service = TestService(
        scenario_manager_factory=FakeManager,
        system_loader=lambda _config_dir: {"runner": {}, "report": {"junit": True, "html": True}},
        dependency_checker=lambda *_: ["missing tool"],
        reporter=lambda *_args, **_kwargs: {},
    )

    result = service.run(RunRequest(config_dir=str(tmp_path)))

    assert result.status is RunStatus.ERROR
    assert result.exit_code == 2
    assert "missing tool" in result.error
