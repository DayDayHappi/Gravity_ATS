from ATS.application.events import EventBus
from ATS.core.context import Context
from ATS.core.events import EventType
from ATS.core.result import TestResult
from ATS.core.scenario import LoopConfig, Scenario, Task
from ATS.core.runner import TestRunner
from ATS.modules import base


class DummyModule(base.TestModule):
    name = "event_dummy"
    depends = []

    def run(self, ctx, console, params=None):
        return TestResult(name="event_dummy", module="event_dummy", status="PASS")


def test_runner_emits_strict_cycle_repeat_task_result_lifecycle(monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "event_dummy", DummyModule)
    monkeypatch.setattr("ATS.core.runner.load_module_config", lambda *_args, **_kwargs: {})
    events = []
    bus = EventBus()
    bus.subscribe(events.append)
    scenario = Scenario(
        name="event_scenario",
        tasks=[Task(module="event_dummy", repeat=2)],
        loop=LoopConfig(enable=True, count=2),
    )
    ctx = Context()
    ctx.run_id = "run-1"

    results = TestRunner({}, ctx, scenario, event_sink=bus).run()

    assert len(results) == 4
    non_log = [e for e in events if e.type is not EventType.LOG]
    assert [e.type for e in non_log] == [
        EventType.CYCLE_STARTED,
        EventType.TASK_STARTED, EventType.RESULT_PRODUCED, EventType.TASK_FINISHED,
        EventType.TASK_STARTED, EventType.RESULT_PRODUCED, EventType.TASK_FINISHED,
        EventType.CYCLE_FINISHED,
        EventType.CYCLE_STARTED,
        EventType.TASK_STARTED, EventType.RESULT_PRODUCED, EventType.TASK_FINISHED,
        EventType.TASK_STARTED, EventType.RESULT_PRODUCED, EventType.TASK_FINISHED,
        EventType.CYCLE_FINISHED,
    ]
    task_starts = [e for e in non_log if e.type is EventType.TASK_STARTED]
    assert [(e.cycle, e.repeat, e.repeat_total) for e in task_starts] == [
        (1, 1, 2), (1, 2, 2), (2, 1, 2), (2, 2, 2)
    ]
    produced = [e for e in non_log if e.type is EventType.RESULT_PRODUCED]
    assert all(e.run_id == "run-1" and isinstance(e.result, TestResult) for e in produced)
