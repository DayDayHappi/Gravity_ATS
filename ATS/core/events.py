"""Toolkit-free structured event contracts produced by the ATS engine."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Protocol


class EventType(str, Enum):
    RUN_STARTED = "RunStarted"
    RUN_FINISHED = "RunFinished"
    RUN_FAILED = "RunFailed"
    CYCLE_STARTED = "CycleStarted"
    CYCLE_FINISHED = "CycleFinished"
    TASK_STARTED = "TaskStarted"
    TASK_FINISHED = "TaskFinished"
    RESULT_PRODUCED = "ResultProduced"
    LOG = "LogEvent"
    TASK_PROGRESS = "TaskProgress"
    ARTIFACT_PRODUCED = "ArtifactProduced"
    ENVIRONMENT_STATUS_CHANGED = "EnvironmentStatusChanged"
    SERIAL_DATA = "SerialData"


@dataclass(frozen=True)
class Event:
    """One immutable lifecycle or observation event."""

    type: EventType
    run_id: str
    timestamp: str = field(default_factory=lambda: dt.datetime.now().isoformat(timespec="milliseconds"))
    scenario: str = ""
    cycle: int = 0
    module: str = ""
    repeat: int = 0
    repeat_total: int = 0
    status: str = ""
    message: str = ""
    level: str = ""
    result: Optional[Any] = None
    data: Mapping[str, Any] = field(default_factory=dict)


class EventSink(Protocol):
    def emit(self, event: Event) -> None:
        """Observe an event. Implementations must not own test control flow."""
