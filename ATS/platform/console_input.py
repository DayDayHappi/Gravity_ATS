"""Cross-platform single-key console input used by the CLI serial terminal."""
from __future__ import annotations

import os
import sys


class _BaseKeyReader:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read_key(self) -> str:
        raise NotImplementedError


class _PosixKeyReader(_BaseKeyReader):
    def __init__(self, stream) -> None:
        self.stream = stream
        self._fd = None
        self._old_settings = None

    def __enter__(self):
        import termios
        import tty

        self._fd = self.stream.fileno()
        self._old_settings = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fd is not None and self._old_settings is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
        return False

    def read_key(self) -> str:
        return self.stream.read(1)


class _WindowsKeyReader(_BaseKeyReader):
    def read_key(self) -> str:
        import msvcrt

        value = msvcrt.getwch()
        if value in ("\x00", "\xe0"):
            # Consume the scan code for function/navigation keys.
            msvcrt.getwch()
            return ""
        return value


class _StreamKeyReader(_BaseKeyReader):
    """Fallback for redirected stdin where cbreak/getwch is unavailable."""

    def __init__(self, stream) -> None:
        self.stream = stream

    def read_key(self) -> str:
        return self.stream.read(1)


def create_console_key_reader(platform_name: str = None, stream=None):
    """Return a context-managed key reader without leaking OS imports upward."""
    stream = stream or sys.stdin
    name = (platform_name or ("windows" if os.name == "nt" else "posix")).lower()
    if not getattr(stream, "isatty", lambda: False)():
        return _StreamKeyReader(stream)
    if name.startswith("win"):
        return _WindowsKeyReader()
    return _PosixKeyReader(stream)
