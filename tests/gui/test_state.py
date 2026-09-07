from ATS.application.models import RunStatus
from ATS.core.events import Event, EventType
from ATS.core.result import TestResult
from ATS.gui.state import GuiRunState


def test_gui_state_is_driven_only_by_structured_events():
    state = GuiRunState(["photo", "video"])
    state.apply(Event(type=EventType.RUN_STARTED, run_id="r", scenario="normal"))
    state.apply(Event(type=EventType.CYCLE_STARTED, run_id="r", cycle=2))
    state.apply(Event(type=EventType.TASK_STARTED, run_id="r", cycle=2, module="photo", repeat=1, repeat_total=2))
    result = TestResult(name="photo[auto]", module="photo", status="PASS")
    state.apply(Event(type=EventType.RESULT_PRODUCED, run_id="r", result=result, module="photo", status="PASS"))
    state.apply(Event(type=EventType.TASK_FINISHED, run_id="r", module="photo", status="PASS"))
    state.apply(Event(type=EventType.LOG, run_id="r", level="INFO", message="structured log"))
    state.apply(Event(type=EventType.RUN_FINISHED, run_id="r", status=RunStatus.PASSED.value))

    assert state.current_cycle == 2
    assert state.current_module == "photo"
    assert state.module_status["photo"] == "PASS"
    assert state.results == [result]
    assert state.logs[-1] == "[INFO] structured log"
    assert state.run_status == RunStatus.PASSED.value
