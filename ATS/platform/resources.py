"""Cross-platform tool lookup (ffprobe / ffmpeg / ffplay).

CLI 最小裁剪版：只保留 ``find_tool`` 能力（自动处理 ``.exe`` 后缀 + bundled 目录
+ PATH），不引入 config / user-data / 服务编排相关能力。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional


class ResourceLocator:
    """Resolve executable tools independently of the process current directory."""

    def __init__(
        self,
        app_root: Optional[os.PathLike | str] = None,
        frozen: Optional[bool] = None,
    ) -> None:
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        if app_root is None:
            if self.frozen:
                app_root = Path(sys.executable).resolve().parent
            else:
                app_root = Path(__file__).resolve().parents[2]
        self.app_root = Path(app_root).expanduser().resolve()

    @property
    def runtime_dir(self) -> Path:
        return self.app_root / "runtime"

    @staticmethod
    def _tool_names(name: str):
        raw = Path(name).name
        stem = raw[:-4] if raw.lower().endswith(".exe") else raw
        # Search both variants so a Windows runtime layout can be inspected on Linux too.
        return (raw, stem, stem + ".exe")

    def find_tool(self, name: str, preferred: Optional[os.PathLike | str] = None) -> str:
        """Find an executable in preferred location, bundled tools, or PATH."""
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
