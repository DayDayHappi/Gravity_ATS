"""Toolkit-free report loading model for GUI and future APIs."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..core.artifacts import Artifact


@dataclass(frozen=True)
class ReportResult:
    name: str
    module: str
    status: str
    elapsed_ms: int = 0
    message: str = ""
    detail: str = ""
    scenario: str = ""
    cycle: int = 0
    artifacts: tuple[Artifact, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReportDocument:
    path: Path
    summary: Mapping[str, Any]
    scenario_stats: Mapping[str, Any]
    results: tuple[ReportResult, ...]
    generated_at: str = ""

    @classmethod
    def load(cls, path) -> "ReportDocument":
        source = Path(path).expanduser().resolve()
        with source.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        results = []
        for raw in data.get("results", []):
            results.append(ReportResult(
                name=str(raw.get("name", "")),
                module=str(raw.get("module", "")),
                status=str(raw.get("status", "")),
                elapsed_ms=int(raw.get("elapsed_ms", 0) or 0),
                message=str(raw.get("message", "")),
                detail=str(raw.get("detail", "")),
                scenario=str(raw.get("scenario", "")),
                cycle=int(raw.get("cycle", 0) or 0),
                artifacts=tuple(Artifact.from_dict(item) for item in raw.get("artifacts", []) or []),
            ))
        return cls(
            path=source,
            summary=dict(data.get("summary", {}) or {}),
            scenario_stats=dict(data.get("scenario_stats", {}) or {}),
            results=tuple(results),
            generated_at=str(data.get("generated_at", "")),
        )
