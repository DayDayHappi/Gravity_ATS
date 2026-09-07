"""Application, configuration, runtime-tool, and user-data path resolution."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


class ResourceLocator:
    """Resolve project resources independently of the process current directory."""

    def __init__(
        self,
        app_root: Optional[os.PathLike | str] = None,
        user_data_root: Optional[os.PathLike | str] = None,
        frozen: Optional[bool] = None,
    ) -> None:
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        if app_root is None:
            if self.frozen:
                app_root = Path(sys.executable).resolve().parent
            else:
                app_root = Path(__file__).resolve().parents[2]
        self.app_root = Path(app_root).expanduser().resolve()
        self.user_data_root = Path(user_data_root).expanduser().resolve() if user_data_root else self._default_user_data_root()

    def _default_user_data_root(self) -> Path:
        if os.name == "nt":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        return (base / "GravityATS").resolve()

    @property
    def config_dir(self) -> Path:
        if self.frozen:
            override = self.user_data_root / "config"
            if (
                (override / "system.yaml").is_file()
                and (override / "modules").is_dir()
                and (override / "scenarios").is_dir()
            ):
                return override
        candidates = (self.app_root / "ATS" / "config", self.app_root / "config")
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]

    @property
    def runtime_dir(self) -> Path:
        return self.app_root / "runtime"

    def resolve_config_dir(self, override: Optional[os.PathLike | str] = None) -> Path:
        if not override:
            return self.config_dir
        path = Path(override).expanduser()
        return path.resolve() if path.is_absolute() else (self.app_root / path).resolve()

    def resolve_output_root(self, configured: os.PathLike | str, kind: str) -> Path:
        """Resolve logs/reports under app root in source mode and user data when frozen."""
        path = Path(configured or kind).expanduser()
        if path.is_absolute():
            return path.resolve()
        base = self.user_data_root if self.frozen else self.app_root
        return (base / path).resolve()

    def resolve_path(self, value: os.PathLike | str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.app_root / path).resolve()

    @staticmethod
    def _tool_names(name: str):
        raw = Path(name).name
        stem = raw[:-4] if raw.lower().endswith(".exe") else raw
        # Search both variants so a Windows runtime layout can be inspected on Linux too.
        return (raw, stem, stem + ".exe")

    def find_tool(self, name: str, preferred: Optional[os.PathLike | str] = None) -> str:
        """Find an executable in preferred location, bundled runtime, legacy tools, or PATH."""
        candidates = []
        if preferred:
            preferred_path = Path(preferred).expanduser()
            if not preferred_path.is_absolute():
                preferred_path = self.app_root / preferred_path
            candidates.append(preferred_path)
            if preferred_path.suffix.lower() != ".exe":
                candidates.append(preferred_path.with_name(preferred_path.name + ".exe"))

        for directory in (
            self.runtime_dir / "ffmpeg",
            self.runtime_dir,
            self.app_root / "tools" / "ffmpeg",
        ):
            for tool_name in self._tool_names(name):
                candidates.append(directory / tool_name)

        seen = set()
        for candidate in candidates:
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return str(candidate.resolve())

        for tool_name in self._tool_names(name):
            found = shutil.which(tool_name)
            if found:
                return str(Path(found).resolve())
        return ""

    def ensure_user_directories(self) -> dict[str, Path]:
        paths = {
            "user_data": self.user_data_root,
            "logs": self.user_data_root / "logs",
            "reports": self.user_data_root / "reports",
            "config_overrides": self.user_data_root / "config",
        }
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)
        return paths
