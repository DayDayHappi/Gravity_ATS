"""Cross-platform serial-port discovery based on pyserial metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str = ""
    hwid: str = ""
    vid: Optional[int] = None
    pid: Optional[int] = None
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    product: Optional[str] = None
    interface: str = ""
    location: Optional[str] = None

    @property
    def is_bluetooth(self) -> bool:
        text = f"{self.description} {self.hwid}".lower()
        return "bluetooth" in text or "bthenum" in text or "蓝牙" in text

    @property
    def is_usb(self) -> bool:
        return self.vid is not None or "usb" in f"{self.description} {self.hwid}".lower()

    @property
    def display_name(self) -> str:
        parts = [self.device]
        if self.description:
            parts.append(self.description)
        if self.vid is not None and self.pid is not None:
            parts.append(f"VID:PID={self.vid:04X}:{self.pid:04X}")
        if self.serial_number:
            parts.append(f"SN={self.serial_number}")
        return " — ".join(parts)


class PySerialPortProvider:
    """Normalize ``serial.tools.list_ports`` output for Linux and Windows."""

    def __init__(self, enumerator: Optional[Callable[[], Iterable[object]]] = None) -> None:
        self._enumerator = enumerator

    def _raw_ports(self):
        if self._enumerator is not None:
            return list(self._enumerator())
        try:
            from serial.tools import list_ports
        except ImportError as exc:
            raise RuntimeError("pyserial is not installed") from exc
        return list(list_ports.comports())

    def list_ports(self) -> List[SerialPortInfo]:
        ports = [
            SerialPortInfo(
                device=str(getattr(port, "device", "") or ""),
                description=str(getattr(port, "description", "") or ""),
                hwid=str(getattr(port, "hwid", "") or ""),
                vid=getattr(port, "vid", None),
                pid=getattr(port, "pid", None),
                serial_number=getattr(port, "serial_number", None),
                manufacturer=getattr(port, "manufacturer", None),
                product=getattr(port, "product", None),
                interface=str(getattr(port, "interface", "") or ""),
                location=getattr(port, "location", None),
            )
            for port in self._raw_ports()
            if getattr(port, "device", None)
        ]

        def rank(port: SerialPortInfo):
            if port.is_bluetooth:
                category = 2
            elif port.is_usb:
                category = 0
            else:
                category = 1
            return category, port.device

        return sorted(ports, key=rank)

    def candidate_names(self) -> List[str]:
        return [port.device for port in self.list_ports()]
