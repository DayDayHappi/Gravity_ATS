"""Structured environment checks consumed by CLI, GUI, and installers."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class EnvironmentCheck:
    name: str
    status: CheckStatus
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)


class EnvironmentInspector:
    """Inspect runtime prerequisites without changing system configuration."""

    def __init__(self, platform_services) -> None:
        self.services = platform_services

    def inspect(self):
        checks = []
        try:
            import serial  # noqa: F401
            checks.append(EnvironmentCheck("Serial API", CheckStatus.PASS, "pyserial available"))
        except ImportError:
            checks.append(EnvironmentCheck("Serial API", CheckStatus.FAIL, "pyserial is not installed"))

        try:
            ports = self.services.serial_ports.list_ports()
            if ports:
                checks.append(EnvironmentCheck(
                    "Serial Ports", CheckStatus.PASS,
                    f"{len(ports)} port(s): " + ", ".join(port.display_name for port in ports),
                    {"ports": [port.device for port in ports]},
                ))
            else:
                checks.append(EnvironmentCheck("Serial Ports", CheckStatus.WARN, "No serial ports detected"))
        except Exception as exc:
            checks.append(EnvironmentCheck("Serial Ports", CheckStatus.FAIL, str(exc)))

        config_dir = Path(self.services.resources.config_dir)
        checks.append(EnvironmentCheck(
            "Config",
            CheckStatus.PASS if config_dir.is_dir() else CheckStatus.FAIL,
            str(config_dir),
        ))

        for label, tool in (("FFmpeg", "ffmpeg"), ("FFprobe", "ffprobe"), ("FFplay", "ffplay")):
            path = self.services.resources.find_tool(tool)
            checks.append(EnvironmentCheck(
                label,
                CheckStatus.PASS if path else (CheckStatus.WARN if tool == "ffplay" else CheckStatus.FAIL),
                path or f"{tool} not found",
            ))

        log_root = self.services.resources.resolve_output_root("logs", "logs")
        try:
            Path(log_root).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=log_root, prefix="ats_write_", delete=True):
                pass
            checks.append(EnvironmentCheck("Logs writable", CheckStatus.PASS, str(log_root)))
        except OSError as exc:
            checks.append(EnvironmentCheck("Logs writable", CheckStatus.FAIL, str(exc)))

        try:
            ready = bool(self.services.rtmp_backend.is_ready())
            checks.append(EnvironmentCheck(
                "RTMP:1935",
                CheckStatus.PASS if ready else CheckStatus.WARN,
                "listening" if ready else "not listening",
            ))
        except Exception as exc:
            checks.append(EnvironmentCheck("RTMP:1935", CheckStatus.WARN, str(exc)))

        if getattr(self.services.processes, "is_windows", False):
            checks.append(EnvironmentCheck(
                "FTP Active/Firewall",
                CheckStatus.WARN,
                "EVB uses active FTP; allow inbound Python/Gravity ATS traffic in Windows Defender Firewall",
            ))
        else:
            checks.append(EnvironmentCheck(
                "FTP Active/Firewall",
                CheckStatus.WARN,
                "EVB uses active FTP; ensure inbound high ports are allowed",
            ))
        return checks
