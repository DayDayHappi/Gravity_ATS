"""Thread-safe event bus used by Application and presentation layers."""
from __future__ import annotations

import threading
from typing import Callable, List

from ..core.events import Event

EventListener = Callable[[Event], None]


class EventBus:
    """Fan out structured events while isolating listener failures."""

    def __init__(self) -> None:
        self._listeners: List[EventListener] = []
        self._lock = threading.RLock()

    def subscribe(self, listener: EventListener):
        if not callable(listener):
            raise TypeError("listener must be callable")
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            self.unsubscribe(listener)

        return unsubscribe

    def unsubscribe(self, listener: EventListener) -> None:
        with self._lock:
            self._listeners = [item for item in self._listeners if item is not listener]

    def emit(self, event: Event) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # An observer is never allowed to fail the ATS run.
                continue
