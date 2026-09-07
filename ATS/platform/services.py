"""Composition root for platform infrastructure."""
from __future__ import annotations

from dataclasses import dataclass

from .desktop import DesktopEnvironment
from .processes import ProcessController
from .resources import ResourceLocator
from .rtmp_backend import SocketRtmpServerBackend
from .serial_ports import PySerialPortProvider
from .serial_registry import SerialPortRegistry


@dataclass
class PlatformServices:
    resources: ResourceLocator
    serial_ports: PySerialPortProvider
    processes: ProcessController
    rtmp_backend: SocketRtmpServerBackend
    desktop: DesktopEnvironment
    serial_registry: SerialPortRegistry


def create_platform_services(resource_locator: ResourceLocator | None = None) -> PlatformServices:
    locator = resource_locator or ResourceLocator()
    return PlatformServices(
        resources=locator,
        serial_ports=PySerialPortProvider(),
        processes=ProcessController(),
        rtmp_backend=SocketRtmpServerBackend(),
        desktop=DesktopEnvironment(),
        serial_registry=SerialPortRegistry(),
    )
