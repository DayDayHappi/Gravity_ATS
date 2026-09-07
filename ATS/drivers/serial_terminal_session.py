"""Cross-platform serial-terminal session independent of any GUI toolkit."""
from __future__ import annotations

import threading
from typing import Callable, Optional

from ..platform.serial_registry import SerialPortRegistry


class SerialTerminalSession:
    """Own one raw serial connection and stream decoded data to listeners."""

    def __init__(
        self,
        *,
        registry: Optional[SerialPortRegistry] = None,
        serial_factory=None,
        owner: str = "serial-terminal",
    ) -> None:
        self.registry = registry or SerialPortRegistry()
        self._serial_factory = serial_factory
        self.owner = owner
        self._serial = None
        self._port = ""
        self._reader = None
        self._stop = threading.Event()
        self._listeners: list[Callable[[str], None]] = []
        self._listeners_lock = threading.RLock()
        self._write_lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", True))

    @property
    def port(self) -> str:
        return self._port

    def add_listener(self, callback: Callable[[str], None]) -> None:
        with self._listeners_lock:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str], None]) -> None:
        with self._listeners_lock:
            self._listeners = [item for item in self._listeners if item is not callback]

    def open(self, port: str, baudrate: int, timeout: float = 0.1) -> None:
        if self.is_open:
            raise RuntimeError("serial terminal is already connected")
        if not self.registry.acquire(port, self.owner):
            raise RuntimeError(f"serial port {port} is already in use by {self.registry.owner(port)}")
        try:
            factory = self._serial_factory
            if factory is None:
                try:
                    import serial
                except ImportError as exc:
                    raise RuntimeError("pyserial is not installed") from exc
                factory = serial.Serial
            self._serial = factory(port, int(baudrate), timeout=timeout, write_timeout=2.0)
            self._port = str(port)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self._stop.clear()
            self._reader = threading.Thread(
                target=self._reader_loop,
                name="serial-terminal-reader",
                daemon=True,
            )
            self._reader.start()
        except Exception:
            self.registry.release(port, self.owner)
            self._serial = None
            self._port = ""
            raise

    def send(self, text: str) -> None:
        if not self.is_open:
            raise RuntimeError("serial terminal is not connected")
        payload = text if text.endswith("\n") else text + "\n"
        with self._write_lock:
            self._serial.write(payload.encode("utf-8"))
            self._serial.flush()

    def close(self) -> None:
        port = self._port
        self._stop.set()
        serial_obj = self._serial
        if serial_obj is not None:
            cancel_read = getattr(serial_obj, "cancel_read", None)
            if callable(cancel_read):
                try:
                    cancel_read()
                except Exception:
                    pass
            try:
                serial_obj.close()
            except Exception:
                pass
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=1.0)
        self._serial = None
        self._reader = None
        self._port = ""
        if port:
            self.registry.release(port, self.owner)
        if reader is not None and reader.is_alive():
            raise RuntimeError("serial terminal reader did not stop")

    def _reader_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data = self._serial.read(4096)
            except Exception:
                break
            if not data:
                continue
            text = data.decode("utf-8", errors="replace")
            with self._listeners_lock:
                listeners = tuple(self._listeners)
            for callback in listeners:
                try:
                    callback(text)
                except Exception:
                    pass
