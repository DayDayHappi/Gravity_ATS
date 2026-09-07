"""Toolkit-free projection of structured ATS events into GUI display state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

from ATS.core.events import Event, EventType
from ATS.core.result import TestResult


_DISPLAY_TERMINAL_STATES = {"PASS", "FAIL", "SKIP", "ERROR", "CANCELLED"}


@dataclass
class GuiRunState:
    """Mutable read model consumed by Qt widgets.

    The reducer only accepts :class:`~ATS.core.events.Event`; it never reads
    ``run.log`` or reaches into ``Runner``/``Module`` internals.
    """

    modules: Iterable[str] = field(default_factory=tuple)
    run_id: str = ""
    scenario: str = ""
    run_status: str = "IDLE"
    current_cycle: int = 0
    current_module: str = ""
    current_repeat: int = 0
    repeat_total: int = 0
    module_status: Dict[str, str] = field(default_factory=dict)
    results: List[TestResult] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.module_status = {str(name): "WAITING" for name in self.modules}

    def reset(self, modules: Iterable[str] = ()) -> None:
        """Reset one run while preserving no hidden engine state."""
        self.run_id = ""
        self.scenario = ""
        self.run_status = "IDLE"
        self.current_cycle = 0
        self.current_module = ""
        self.current_repeat = 0
        self.repeat_total = 0
        self.module_status = {str(name): "WAITING" for name in modules}
        self.results.clear()
        self.logs.clear()

    def apply(self, event: Event) -> None:
        """Apply one immutable engine event to the presentation read model."""
        if event.type is EventType.RUN_STARTED:
            self.run_id = event.run_id
            self.scenario = event.scenario
            self.run_status = "RUNNING"
            return
        if event.type is EventType.CYCLE_STARTED:
            self.current_cycle = event.cycle
            return
        if event.type is EventType.TASK_STARTED:
            self.current_module = event.module
            self.current_repeat = event.repeat
            self.repeat_total = event.repeat_total
            if event.module:
                self.module_status[event.module] = "RUNNING"
            return
        if event.type is EventType.RESULT_PRODUCED:
            if isinstance(event.result, TestResult):
                self.results.append(event.result)
            return
        if event.type is EventType.TASK_FINISHED:
            if event.module:
                status = event.status or "ERROR"
                self.module_status[event.module] = (
                    status if status in _DISPLAY_TERMINAL_STATES else "ERROR"
                )
            return
        if event.type is EventType.LOG:
            level = event.level or "INFO"
            self.logs.append(f"[{level}] {event.message}")
            return
        if event.type is EventType.RUN_FAILED:
            self.run_status = "ERROR"
            return
        if event.type is EventType.RUN_FINISHED:
            self.run_status = event.status or "ERROR"
