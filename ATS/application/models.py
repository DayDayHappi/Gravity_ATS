"""Stable request/result contracts for invoking the ATS engine."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional

from ..core.result import TestResult


class RunStatus(str, Enum):
    """Terminal state of one Application-level run."""

    PASSED = "PASS"
    FAILED = "FAIL"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    DRY_RUN = "DRY_RUN"


@dataclass(frozen=True)
class RunRequest:
    """Description of one test execution without presentation-layer objects."""

    scenario: str = "normal"
    config_dir: Optional[str] = None
    system_overrides: Mapping[str, Any] = field(default_factory=dict)
    module_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    output_dir: Optional[str] = None
    verbose: bool = False
    no_interactive_wifi: bool = False
    dry_run: bool = False
    execution_options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "system_overrides", copy.deepcopy(dict(self.system_overrides)))
        object.__setattr__(self, "module_overrides", copy.deepcopy(dict(self.module_overrides)))
        object.__setattr__(self, "execution_options", copy.deepcopy(dict(self.execution_options)))


@dataclass
class RunResult:
    """Application-level result with reports, artifacts, and CLI-compatible exit semantics."""

    run_id: str
    scenario: str
    status: RunStatus
    results: List[TestResult] = field(default_factory=list)
    report_paths: Dict[str, str] = field(default_factory=dict)
    log_dir: str = ""
    report_dir: str = ""
    problem_root: str = ""
    started_at: str = ""
    finished_at: str = ""
    error: str = ""

    @property
    def exit_code(self) -> int:
        """Map to the existing 0/1/2 CLI contract.

        Cancellation is a non-successful completed run and therefore maps to 1;
        callers that need the distinction use ``status``.
        """
        if self.status in (RunStatus.PASSED, RunStatus.DRY_RUN):
            return 0
        if self.status in (RunStatus.FAILED, RunStatus.CANCELLED):
            return 1
        return 2

    @property
    def passed(self) -> bool:
        return self.status is RunStatus.PASSED

    @classmethod
    def from_results(
        cls,
        *,
        run_id: str,
        scenario: str,
        results: List[TestResult],
        **kwargs: Any,
    ) -> "RunResult":
        failed = any(r.status in ("FAIL", "ERROR") for r in results)
        return cls(
            run_id=run_id,
            scenario=scenario,
            status=RunStatus.FAILED if failed else RunStatus.PASSED,
            results=list(results),
            **kwargs,
        )


@dataclass(frozen=True)
class TaskDescriptor:
    module: str
    repeat: int = 1
    duration: Optional[float] = None


@dataclass(frozen=True)
class ScenarioDescriptor:
    name: str
    prepare: tuple[str, ...] = ()
    tasks: tuple[TaskDescriptor, ...] = ()
    cleanup: tuple[str, ...] = ()
    loop_enabled: bool = False
    loop_count: Optional[int] = None
    loop_duration: Optional[float] = None
