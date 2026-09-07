"""Cooperative cancellation primitives shared by the engine and drivers."""
from __future__ import annotations

import threading
from typing import Callable, Dict, Optional


class OperationCancelled(Exception):
    """Raised at a safe point after a cancellation request."""


class CancellationToken:
    """Thread-safe, idempotent cancellation token with wake-up callbacks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.RLock()
        self._reason = ""
        self._callbacks: Dict[int, Callable[[], None]] = {}
        self._next_callback_id = 1

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def cancel(self, reason: str = "cancelled") -> bool:
        """Request cancellation once; return ``True`` only for the first call."""
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = reason or "cancelled"
            callbacks = tuple(self._callbacks.values())
            self._callbacks.clear()
            self._event.set()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass
        return True

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait until cancelled or timeout; return whether cancellation occurred."""
        return self._event.wait(timeout)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelled(self.reason or "cancelled")

    def register(self, callback: Callable[[], None]):
        """Run callback on cancellation and return an unregister function."""
        if not callable(callback):
            raise TypeError("callback must be callable")
        invoke_now = False
        with self._lock:
            if self._event.is_set():
                invoke_now = True
                callback_id = 0
            else:
                callback_id = self._next_callback_id
                self._next_callback_id += 1
                self._callbacks[callback_id] = callback
        if invoke_now:
            try:
                callback()
            except Exception:
                pass

        def unregister() -> None:
            if callback_id:
                with self._lock:
                    self._callbacks.pop(callback_id, None)

        return unregister


def token_from(context) -> Optional[CancellationToken]:
    """Return a token from a Context-like object, or ``None``."""
    return getattr(context, "cancellation_token", None) if context is not None else None


def wait_or_cancel(context, seconds: float) -> None:
    """Sleep cooperatively and raise if cancellation was requested."""
    token = token_from(context)
    if token is None:
        import time

        time.sleep(max(0.0, seconds))
        return
    if token.wait(max(0.0, seconds)):
        token.raise_if_cancelled()
