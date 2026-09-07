"""Bounded, batched log display that keeps the GUI responsive."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit


class BoundedLogView(QPlainTextEdit):
    """Read-only log view with bounded history and batched UI updates."""

    def __init__(self, parent=None, *, max_blocks: int = 5000) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(max(100, int(max_blocks)))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._pending = deque(maxlen=max(500, int(max_blocks)))
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._flush_pending)

    def enqueue(self, text: str) -> None:
        if text is None:
            return
        normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
        self._pending.extend(normalized.splitlines() or [""])
        if not self._timer.isActive():
            self._timer.start()

    def clear(self) -> None:
        self._pending.clear()
        super().clear()

    def _flush_pending(self) -> None:
        count = 0
        while self._pending and count < 200:
            self.appendPlainText(self._pending.popleft())
            count += 1
        if not self._pending:
            self._timer.stop()
