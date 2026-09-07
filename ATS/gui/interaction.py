"""Qt implementation of the toolkit-free InteractionProvider contract."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

from ATS.application.interaction import InteractionProvider


@dataclass
class _PromptRequest:
    kind: str
    prompt: str
    options: tuple = ()
    default: object = None
    secret: bool = False
    completed: threading.Event = field(default_factory=threading.Event)
    result: object = None


class QtInteractionProvider(QObject, InteractionProvider):
    """Marshal worker-thread prompts to the GUI thread and wait for a reply."""

    requested = Signal(object)

    def __init__(self, parent=None) -> None:
        QObject.__init__(self, parent)
        self.requested.connect(self._handle_request)

    def confirm(self, prompt: str, default: bool = True) -> bool:
        request = _PromptRequest("confirm", prompt, default=bool(default))
        return bool(self._execute(request))

    def choose(self, prompt: str, options, default_index: int = 0):
        values = tuple(options)
        if not values:
            raise ValueError("options must not be empty")
        index = min(max(int(default_index), 0), len(values) - 1)
        request = _PromptRequest("choose", prompt, options=values, default=index)
        return self._execute(request)

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        request = _PromptRequest("text", prompt, default=str(default), secret=bool(secret))
        return str(self._execute(request) or "")

    def _execute(self, request: _PromptRequest):
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            self._handle_request(request)
        else:
            self.requested.emit(request)
            request.completed.wait()
        return request.result

    @Slot(object)
    def _handle_request(self, request: _PromptRequest) -> None:
        try:
            if request.kind == "confirm":
                buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                default_button = (
                    QMessageBox.StandardButton.Yes
                    if request.default else QMessageBox.StandardButton.No
                )
                answer = QMessageBox.question(
                    self.parent(), "Gravity ATS", request.prompt, buttons, default_button
                )
                request.result = answer == QMessageBox.StandardButton.Yes
            elif request.kind == "choose":
                labels = [str(item) for item in request.options]
                text, accepted = QInputDialog.getItem(
                    self.parent(), "Gravity ATS", request.prompt,
                    labels, int(request.default), False,
                )
                request.result = request.options[labels.index(text)] if accepted else request.options[int(request.default)]
            elif request.kind == "text":
                mode = QLineEdit.EchoMode.Password if request.secret else QLineEdit.EchoMode.Normal
                value, accepted = QInputDialog.getText(
                    self.parent(), "Gravity ATS", request.prompt, mode, str(request.default)
                )
                request.result = value if accepted else request.default
        finally:
            request.completed.set()
