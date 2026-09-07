"""Cross-platform child-process lifecycle and process-tree cleanup."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Optional, Sequence

from ..core.cancellation import CancellationToken, OperationCancelled


class ProcessController:
    """Own all operating-system branches for launching and terminating processes."""

    def __init__(self, platform_name: Optional[str] = None) -> None:
        if platform_name is None:
            platform_name = "windows" if os.name == "nt" else "posix"
        self.platform_name = platform_name.lower()

    @property
    def is_windows(self) -> bool:
        return self.platform_name.startswith("win")

    def creation_kwargs(self, *, new_process_group: bool = True, show_window: bool = False) -> dict:
        if self.is_windows:
            flags = 0
            if new_process_group:
                flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            if not show_window:
                flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            return {"creationflags": flags}
        return {"start_new_session": bool(new_process_group)}

    def start(self, argv: Sequence[str], *, new_process_group: bool = True,
              show_window: bool = False, **kwargs):
        if isinstance(argv, (str, bytes)):
            raise TypeError("argv must be a sequence; shell strings are not allowed")
        options = self.creation_kwargs(
            new_process_group=new_process_group,
            show_window=show_window,
        )
        options.update(kwargs)
        options["shell"] = False
        return subprocess.Popen(list(argv), **options)

    def wait(self, proc, timeout: Optional[float] = None,
             cancellation_token: Optional[CancellationToken] = None) -> int:
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        while proc.poll() is None:
            if cancellation_token is not None and cancellation_token.is_cancelled:
                self.terminate(proc)
                cancellation_token.raise_if_cancelled()
            if deadline is not None and time.monotonic() >= deadline:
                self.terminate(proc)
                raise subprocess.TimeoutExpired(getattr(proc, "args", []), timeout)
            try:
                remaining = 0.1 if deadline is None else max(0.0, min(0.1, deadline - time.monotonic()))
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
        return int(proc.returncode or 0)

    def run_capture(self, argv: Sequence[str], *, timeout: Optional[float] = None,
                    cancellation_token: Optional[CancellationToken] = None,
                    text: bool = True, **kwargs) -> subprocess.CompletedProcess:
        """Run a bounded command while allowing cooperative cancellation."""
        proc = self.start(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, **kwargs
        )
        deadline = None if timeout is None else time.monotonic() + float(timeout)
        try:
            while True:
                if cancellation_token is not None and cancellation_token.is_cancelled:
                    self.terminate(proc)
                    cancellation_token.raise_if_cancelled()
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    self.terminate(proc)
                    raise subprocess.TimeoutExpired(list(argv), timeout)
                try:
                    stdout, stderr = proc.communicate(
                        timeout=0.1 if remaining is None else min(0.1, max(0.01, remaining))
                    )
                    return subprocess.CompletedProcess(list(argv), proc.returncode, stdout, stderr)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if proc.poll() is None:
                self.terminate(proc)

    def terminate(self, proc, grace: float = 2.0) -> None:
        if proc is None or proc.poll() is not None:
            return
        if self.is_windows:
            # taskkill /T is the standard no-extra-dependency process-tree fallback.
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(0.5, grace),
                    check=False,
                )
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
        try:
            proc.wait(timeout=grace)
            return
        except Exception:
            pass
        if self.is_windows:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=max(0.5, grace),
                    check=False,
                )
            except Exception:
                pass
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            proc.wait(timeout=grace)
        except Exception:
            pass
