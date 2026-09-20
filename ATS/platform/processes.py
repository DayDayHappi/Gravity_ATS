"""Cross-platform child-process lifecycle and process-tree cleanup (CLI minimal).

裁剪版（feature/windows-cli，方案甲）：不引入 ``core.cancellation``，只保留
``start`` / ``terminate`` / ``creation_kwargs``。超时打断由调用方用
``subprocess`` 自带 ``timeout`` 或 ``Popen.wait(timeout=...)`` 处理。
"""
from __future__ import annotations

import os
import signal
import subprocess
from typing import Optional, Sequence


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

    def terminate(self, proc, grace: float = 2.0) -> None:
        """Terminate a process tree and reap it without leaving zombies."""
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
