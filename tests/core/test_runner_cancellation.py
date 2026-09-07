import pytest

from ATS.application.events import EventBus
from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.core.context import Context
from ATS.core.events import EventType
from ATS.core.runner import TestRunner
from ATS.core.scenario import Scenario, Task
from ATS.modules import base


class CancellingModule(base.TestModule):
    name = "cancelling_dummy"
    depends = []
    runs = 0
    teardowns = 0

    def run(self, ctx, console, params=None):
        type(self).runs += 1
        ctx.cancellation_token.cancel("test stop")
        ctx.cancellation_token.raise_if_cancelled()

    def teardown(self, ctx, console):
        type(self).teardowns += 1


def test_runner_stops_repeats_and_still_tears_down_on_cancel(monkeypatch):
    CancellingModule.runs = 0
    CancellingModule.teardowns = 0
    monkeypatch.setitem(base._REGISTRY, "cancelling_dummy", CancellingModule)
    monkeypatch.setattr("ATS.core.runner.load_module_config", lambda *_a, **_k: {})
    token = CancellationToken()
    ctx = Context()
    ctx.cancellation_token = token
    ctx.run_id = "cancel-run"
    events = []
    bus = EventBus()
    bus.subscribe(events.append)

    runner = TestRunner({}, ctx, Scenario(name="s", tasks=[Task("cancelling_dummy", repeat=3)]),
                        event_sink=bus, cancellation_token=token)
    with pytest.raises(OperationCancelled):
        runner.run()

    assert CancellingModule.runs == 1
    assert CancellingModule.teardowns == 1
    task_finished = [e for e in events if e.type is EventType.TASK_FINISHED]
    assert len(task_finished) == 1
    assert task_finished[0].status == "CANCELLED"
