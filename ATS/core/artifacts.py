"""Generic test artifact model shared by modules, reports, and presentations."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Artifact:
    kind: str
    path: str
    label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", copy.deepcopy(dict(self.metadata)))

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "label": self.label,
            "metadata": copy.deepcopy(dict(self.metadata)),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Artifact":
        return cls(
            kind=str(value.get("kind", "artifact")),
            path=str(value.get("path", "")),
            label=str(value.get("label", "")),
            metadata=dict(value.get("metadata", {}) or {}),
        )
