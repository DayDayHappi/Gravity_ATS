from ATS.application.models import RunRequest, RunResult, RunStatus
from ATS.core.result import TestResult


def test_run_request_owns_override_copies():
    system = {"serial.port": "COM10"}
    modules = {"video": {"video_duration": 20}}

    request = RunRequest(system_overrides=system, module_overrides=modules)
    system["serial.port"] = "COM11"
    modules["video"]["video_duration"] = 99

    assert request.system_overrides == {"serial.port": "COM10"}
    assert request.module_overrides == {"video": {"video_duration": 20}}


def test_run_result_exit_code_preserves_cli_semantics():
    assert RunResult(run_id="1", scenario="normal", status=RunStatus.PASSED).exit_code == 0
    assert RunResult(run_id="2", scenario="normal", status=RunStatus.DRY_RUN).exit_code == 0
    assert RunResult(run_id="3", scenario="normal", status=RunStatus.FAILED).exit_code == 1
    assert RunResult(run_id="4", scenario="normal", status=RunStatus.CANCELLED).exit_code == 1
    assert RunResult(run_id="5", scenario="normal", status=RunStatus.ERROR).exit_code == 2


def test_run_result_derives_failed_status_from_test_results():
    results = [TestResult(name="x", module="x", status="FAIL")]
    run = RunResult.from_results(run_id="r", scenario="normal", results=results)
    assert run.status is RunStatus.FAILED
    assert run.exit_code == 1
