"""Dependency validation shared by CLI and GUI."""
from __future__ import annotations

from typing import List

from ..core.config import load_module_config
from ..drivers.rtmp_receiver import RtmpReceiver
from ..platform.resources import ResourceLocator


def find_missing_dependencies(system_cfg, scenario, config_dir, resource_locator=None) -> List[str]:
    missing: List[str] = []
    try:
        import serial  # noqa: F401
    except ImportError:
        # Standalone H265 does not require serial; board scenarios do.
        if getattr(scenario, "prepare", None):
            missing.append("pyserial (pip install pyserial)")

    if any(task.module == "rtmp" for task in scenario.tasks):
        rtmp_cfg = load_module_config("rtmp", config_dir)
        missing.extend(RtmpReceiver.check_tools(
            rtmp_cfg.get("ffprobe_path", "ffprobe"),
            resource_locator=resource_locator or ResourceLocator(),
        ))
    return missing
