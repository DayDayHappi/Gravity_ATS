"""Desktop-window capability isolated from preview business behavior."""
from __future__ import annotations

import os
import sys


class DesktopEnvironment:
    def __init__(self, can_show_windows=None) -> None:
        self._override = can_show_windows

    @property
    def can_show_windows(self) -> bool:
        if self._override is not None:
            return bool(self._override)
        if os.name == "nt" or sys.platform == "darwin":
            return True
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
