from ATS.application.events import EventBus
from ATS.application.models import RunRequest, RunStatus
from ATS.application.service import TestService
from ATS.core.events import EventType
from ATS.core.result import TestResult


class Scenario:
    name = "normal"
    tasks = []


class Manager:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def load(self, name):
        return Scenario()

    def run(self, *args, **kwargs):
        return [TestResult(name="ok", module="ok", status="PASS")]


def make_service(bus, dependency_checker=lambda *_: []):
    return TestService(
        event_bus=bus,
        scenario_manager_factory=Manager,
        system_loader=lambda _: {"runner": {}, "report": {"junit": False, "html": False}},
        dependency_checker=dependency_checker,
        reporter=lambda *_args, **_kwargs: {"json": "result.json"},
    )


def test_service_emits_started_and_finished_with_same_run_id(tmp_path):
    events = []
    bus = EventBus()
    bus.subscribe(events.append)

    result = make_service(bus).run(RunRequest(config_dir=str(tmp_path), output_dir=str(tmp_path)))

    assert result.status is RunStatus.PASSED
    lifecycle = [e for e in events if e.type in (EventType.RUN_STARTED, EventType.RUN_FINISHED)]
    assert [e.type for e in lifecycle] == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert lifecycle[0].run_id == lifecycle[1].run_id == result.run_id
    assert lifecycle[1].status == RunStatus.PASSED.value


def test_environment_error_emits_run_failed_then_run_finished(tmp_path):
    events = []
    bus = EventBus()
    bus.subscribe(events.append)

    result = make_service(bus, dependency_checker=lambda *_: ["missing"]).run(
        RunRequest(config_dir=str(tmp_path), output_dir=str(tmp_path))
    )

    assert result.status is RunStatus.ERROR
    lifecycle = [e for e in events if e.type in (
        EventType.RUN_STARTED, EventType.RUN_FAILED, EventType.RUN_FINISHED
    )]
    assert [e.type for e in lifecycle] == [
        EventType.RUN_STARTED, EventType.RUN_FAILED, EventType.RUN_FINISHED
    ]
    assert all(e.run_id == result.run_id for e in lifecycle)
