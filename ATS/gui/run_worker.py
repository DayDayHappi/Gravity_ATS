"""Qt worker-thread adapter around the toolkit-free TestService."""
from __future__ import annotations

import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ATS.application.models import RunRequest
from ATS.core.cancellation import CancellationToken
from ATS.core.events import Event


class _RunWorker(QObject):
    event_emitted = Signal(object)
    completed = Signal(object)
    crashed = Signal(str)

    def __init__(self, service, request: RunRequest, cancellation_token: CancellationToken) -> None:
        super().__init__()
        self.service = service
        self.request = request
        self.cancellation_token = cancellation_token

    @Slot()
    def execute(self) -> None:
        unsubscribe = None
        try:
            bus = getattr(self.service, "event_bus", None)
            if bus is not None:
                unsubscribe = bus.subscribe(self._forward_event)
            result = self.service.run(
                self.request,
                cancellation_token=self.cancellation_token,
            )
            self.completed.emit(result)
        except Exception:
            self.crashed.emit(traceback.format_exc())
        finally:
            if unsubscribe is not None:
                unsubscribe()

    def _forward_event(self, event: Event) -> None:
        self.event_emitted.emit(event)


class RunController(QObject):
    """Own at most one cooperative TestService worker thread for MainWindow."""

    event_received = Signal(object)
    run_finished = Signal(object)
    error = Signal(str)
    running_changed = Signal(bool)

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self._thread = None
        self._worker = None
        self._token = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, request: RunRequest) -> bool:
        if self._running or bool(getattr(self.service, "is_running", False)):
            return False

        token = CancellationToken()
        thread = QThread(self)
        worker = _RunWorker(self.service, request, token)
        worker.moveToThread(thread)

        self._token = token
        self._thread = thread
        self._worker = worker
        self._running = True

        thread.started.connect(worker.execute)
        worker.event_emitted.connect(self.event_received)
        worker.completed.connect(self._on_completed)
        worker.crashed.connect(self._on_crashed)
        worker.completed.connect(worker.deleteLater)
        worker.crashed.connect(worker.deleteLater)
        worker.completed.connect(thread.quit)
        worker.crashed.connect(thread.quit)
        thread.finished.connect(self._cleanup_thread)
        thread.finished.connect(thread.deleteLater)

        self.running_changed.emit(True)
        thread.start()
        return True

    def stop(self, reason: str = "GUI Stop") -> bool:
        requested = self._token.cancel(reason) if self._token is not None else False
        cancel = getattr(self.service, "cancel_current", None)
        service_requested = bool(cancel(reason)) if callable(cancel) else False
        return requested or service_requested

    def shutdown(self, timeout_ms: int = 10000) -> bool:
        """Request cooperative stop and report whether the worker fully exited."""
        thread = self._thread
        if thread is None or not thread.isRunning():
            return True
        self.stop("GUI closing")
        return bool(thread.wait(max(0, int(timeout_ms))))

    @Slot(object)
    def _on_completed(self, result) -> None:
        self.run_finished.emit(result)

    @Slot(str)
    def _on_crashed(self, detail: str) -> None:
        self.error.emit(detail)

    @Slot()
    def _cleanup_thread(self) -> None:
        self._worker = None
        self._thread = None
        self._token = None
        if self._running:
            self._running = False
            self.running_changed.emit(False)
