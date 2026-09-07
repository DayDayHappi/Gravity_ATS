from pathlib import Path

from ATS.application.models import RunRequest, RunStatus
from ATS.application.service import TestService
from ATS.core.result import TestResult
from ATS.core.scenario_manager import ScenarioError


class Scenario:
    name = "normal"
    tasks = []


class FailingManager:
    def __init__(self, **kwargs):
        self.last_results = [TestResult(name="before-error", module="dummy", status="PASS")]

    def load(self, name):
        return Scenario()

    def run(self, *args, **kwargs):
        raise ScenarioError("runtime environment failed")


def test_runtime_scenario_error_preserves_partial_results_and_reports(tmp_path):
    calls = []

    def reporter(results, out_dir, **kwargs):
        calls.append((list(results), out_dir, kwargs))
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        result_path = Path(out_dir) / "result.json"
        result_path.write_text("{}", encoding="utf-8")
        return {"json": str(result_path)}

    service = TestService(
        scenario_manager_factory=FailingManager,
        system_loader=lambda _: {"runner": {}, "report": {"junit": True, "html": True}},
        dependency_checker=lambda *_: [],
        reporter=reporter,
    )

    result = service.run(RunRequest(config_dir=str(tmp_path), output_dir=str(tmp_path / "out")))

    assert result.status is RunStatus.ERROR
    assert [item.name for item in result.results] == ["before-error"]
    assert result.report_dir
    assert result.report_paths["json"].endswith("result.json")
    assert len(calls) == 1
