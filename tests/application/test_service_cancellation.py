from ATS.application.events import EventBus
from ATS.application.models import RunRequest, RunStatus
from ATS.application.service import TestService
from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.core.events import EventType
from ATS.core.result import TestResult


class Scenario:
    name = "normal"
    tasks = []


class CancellingManager:
    def __init__(self, **kwargs):
        self.last_results = [TestResult(name="before-stop", module="dummy", status="PASS")]

    def load(self, name):
        return Scenario()

    def run(self, *args, **kwargs):
        raise OperationCancelled("operator stop")


def test_service_returns_cancelled_partial_result_and_final_event(tmp_path):
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    service = TestService(
        event_bus=bus,
        scenario_manager_factory=CancellingManager,
        system_loader=lambda _: {"runner": {}, "report": {"junit": False, "html": False}},
        dependency_checker=lambda *_: [],
        reporter=lambda results, *_a, **_k: {"json": f"partial-{len(results)}.json"},
    )
    token = CancellationToken()

    result = service.run(RunRequest(config_dir=str(tmp_path), output_dir=str(tmp_path)), token)

    assert result.status is RunStatus.CANCELLED
    assert [item.name for item in result.results] == ["before-stop"]
    assert result.report_paths["json"] == "partial-1.json"
    assert [e.type for e in events if e.type in (EventType.RUN_STARTED, EventType.RUN_FINISHED)] == [
        EventType.RUN_STARTED, EventType.RUN_FINISHED
    ]
    assert events[-1].status == RunStatus.CANCELLED.value
