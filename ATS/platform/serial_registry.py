"""In-process serial-port ownership registry shared by test and terminal flows."""
from __future__ import annotations

import threading
from contextlib import contextmanager


class SerialPortRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._owners: dict[str, str] = {}

    def acquire(self, port: str, owner: str) -> bool:
        key = str(port).upper()
        with self._lock:
            current = self._owners.get(key)
            if current is not None and current != owner:
                return False
            self._owners[key] = owner
            return True

    def release(self, port: str, owner: str) -> None:
        key = str(port).upper()
        with self._lock:
            if self._owners.get(key) == owner:
                self._owners.pop(key, None)

    def owner(self, port: str):
        with self._lock:
            return self._owners.get(str(port).upper())

    @contextmanager
    def lease(self, port: str, owner: str):
        if not self.acquire(port, owner):
            raise RuntimeError(f"serial port {port} is already in use")
        try:
            yield
        finally:
            self.release(port, owner)
