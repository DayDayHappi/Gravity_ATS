"""Scenario-lifetime RTMP preview with a Python reconnect worker."""
from __future__ import annotations

import os
import subprocess
import threading

from ..core import logger
from ..core.cancellation import CancellationToken, OperationCancelled
from ..platform.desktop import DesktopEnvironment
from ..platform.processes import ProcessController
from ..platform.resources import ResourceLocator


def _detect_pc_ip(target_ip: str) -> str:
    if not target_ip:
        return ""
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((target_ip, 1935))
            return sock.getsockname()[0]
    except Exception:
        return ""


class PreviewManager:
    """Manage one reconnecting ffplay observation process for a Scenario."""

    def __init__(
        self,
        config: dict | None = None,
        *,
        process_controller: ProcessController | None = None,
        resource_locator: ResourceLocator | None = None,
        desktop_environment: DesktopEnvironment | None = None,
    ) -> None:
        self.config = config or {}
        self._processes = process_controller or ProcessController()
        self._resources = resource_locator or ResourceLocator()
        self._desktop = desktop_environment or DesktopEnvironment()
        self._ffplay_path = self._resources.find_tool(
            "ffplay", self.config.get("ffplay_path", "ffplay")
        )
        self._retry = max(0.05, float(self.config.get("retry_interval", 3.0)))
        self._required = bool(self.config.get("preview_required", False))
        self._url = ""
        self._thread = None
        self._token = None
        self._current_process = None
        self._lock = threading.RLock()
        self._log_handle = None

    def start(self, url: str) -> bool:
        if self.is_running():
            logger.info("PreviewManager 已在运行，跳过重复启动")
            return True
        self._finalize_stopped_state()
        if not self._ffplay_path:
            logger.warn("未找到 ffplay，跳过画面观察（不影响 RTMP 判据）")
            return False
        if not self._desktop.can_show_windows:
            logger.info("当前会话不能显示桌面窗口，跳过画面观察")
            return False
        self._url = url
        self._token = CancellationToken()
        self._open_log()
        self._thread = threading.Thread(
            target=self._worker,
            name="rtmp-preview-reconnect",
            daemon=True,
        )
        self._thread.start()
        logger.info("画面观察重连 worker 已启动")
        return True

    def stop(self, timeout: float = 3.0) -> bool:
        """Request STOP and return only after the reconnect worker has exited.

        If the worker does not exit within ``timeout``, keep its token/thread/log
        state intact so callers can report and retry cleanup instead of losing
        the only handles to a live worker.
        """
        token = self._token
        if token is None:
            return self._finalize_stopped_state()
        token.cancel("preview stop")
        with self._lock:
            proc = self._current_process
        if proc is not None:
            self._processes.terminate(proc)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, float(timeout)))
        if thread is not None and thread.is_alive():
            logger.error("PreviewManager STOP 超时，重连 worker 仍在运行")
            return False
        return self._finalize_stopped_state()

    def restart(self, url: str | None = None) -> bool:
        target = url or self._url
        if not self.stop():
            return False
        return self.start(target)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _finalize_stopped_state(self) -> bool:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return False
        with self._lock:
            self._current_process = None
        self._thread = None
        self._token = None
        self._close_log()
        return True

    def _argv(self):
        return [
            self._ffplay_path,
            "-rtmp_live", "live",
            "-rtmp_buffer", "0",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-framedrop",
            "-sync", "ext",
            self._url,
        ]

    def _worker(self) -> None:
        token = self._token
        while token is not None and not token.is_cancelled:
            proc = None
            try:
                proc = self._processes.start(
                    self._argv(),
                    stdout=subprocess.DEVNULL,
                    stderr=self._log_handle or subprocess.DEVNULL,
                    show_window=True,
                )
                with self._lock:
                    self._current_process = proc
                self._processes.wait(proc, cancellation_token=token)
                if not token.is_cancelled:
                    level = logger.error if self._required else logger.warn
                    level("preview stopped unexpectedly，准备自动重连")
            except OperationCancelled:
                break
            except Exception as exc:
                if not token.is_cancelled:
                    logger.warn(f"画面观察进程异常: {exc}")
            finally:
                if proc is not None and proc.poll() is None:
                    self._processes.terminate(proc)
                with self._lock:
                    if self._current_process is proc:
                        self._current_process = None
            if token.wait(self._retry):
                break

    def _open_log(self) -> None:
        directory = logger.log_dir()
        if not directory:
            return
        try:
            self._log_handle = open(os.path.join(directory, "preview.log"), "ab")
        except OSError:
            self._log_handle = None

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
