"""Scenario 生命周期内的可选 ffplay 观察器（ADR-010 / ADR-012）。

直接启动 ffplay；Python 线程负责断流后的重连，Windows 不需要 Bash/DISPLAY，
Ubuntu 有 DISPLAY/WAYLAND_DISPLAY 才启动。每次最多持有一个直接子进程，
不再用独立终端模拟器包装；ffplay 画面窗口仍保留原有低延时参数。
不参与 ffprobe/heartbeat 主判据，不启停外部 nginx。
"""
import math
import os
import subprocess
import threading

from ..core import logger
from ..platform.tools import resolve_tool, ToolError
from ..platform.processes import spawn, terminate_process

IS_WINDOWS = os.name == "nt"


def _detect_pc_ip(target_ip: str) -> str:
    """交由 OS 为 EVB 地址选路；只获取本端地址，不发送应用数据。"""
    if not target_ip:
        return ""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target_ip, 1935))
            return s.getsockname()[0]
    except OSError:
        return ""


def _find_ffplay(preferred=None) -> str:
    try:
        return resolve_tool("ffplay", preferred)
    except ToolError as exc:
        logger.debug(str(exc))
        return ""


class PreviewManager:
    """单实例、多次 start/stop 安全；重连间隙 is_running() 仍为 True。"""

    def __init__(self, config=None):
        self.config = config or {}
        self._ffplay_path = _find_ffplay(self.config.get("ffplay_path"))
        self._retry = float(self.config.get("retry_interval", 3.0))
        if not math.isfinite(self._retry) or self._retry <= 0:
            raise ValueError("preview.retry_interval 必须为大于0的有限秒数")
        self._required = bool(self.config.get("preview_required", False))
        self._url = None
        self._proc = None
        self._worker = None
        self._stop_event = threading.Event()
        self._process_lock = threading.Lock()
        self._log_handle = None

    def _argv(self, url):
        return [self._ffplay_path, "-rtmp_live", "live", "-rtmp_buffer", "0",
                "-fflags", "nobuffer", "-flags", "low_delay", "-framedrop", "-sync", "ext", url]

    def start(self, url):
        if self.is_running():
            logger.info("PreviewManager 已在运行，跳过重复启动")
            return True
        if self._worker is not None and self._worker.is_alive():
            self.stop()
            if self._worker.is_alive():
                logger.error("旧预览监督线程尚未退出，拒绝重复启动")
                return False
        if not self._ffplay_path:
            logger.warn("未找到可运行的 ffplay，跳过观察（RTMP 自动判据不受影响）")
            return False
        if not IS_WINDOWS and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            logger.info("无图形显示环境，跳过 ffplay 观察")
            return False
        if not isinstance(url, str) or not url:
            logger.warn("预览 URL 为空，跳过观察")
            return False
        self._url = url
        self._stop_event.clear()
        self._close_log()
        log_dir = logger.log_dir()
        if log_dir:
            try:
                self._log_handle = open(os.path.join(log_dir, "preview.log"), "ab")
            except OSError as exc:
                logger.warn(f"无法打开 preview.log: {exc}")
        try:
            with self._process_lock:
                self._proc = self._launch()
            self._worker = threading.Thread(target=self._supervise, name="ats-preview", daemon=True)
            self._worker.start()
            logger.info(f"ffplay 观察已启动: {self._ffplay_path}")
            return True
        except BaseException as exc:
            self._stop_event.set()
            terminate_process(self._proc)
            self._close_log()
            if not isinstance(exc, Exception):
                raise
            logger.warn(f"预览启动失败（不影响主判据）: {exc}")
            return False

    def _launch(self):
        return spawn(self._argv(self._url), stdout=subprocess.DEVNULL,
                     stderr=self._log_handle if self._log_handle is not None else subprocess.DEVNULL)

    def _supervise(self):
        try:
            while not self._stop_event.is_set():
                with self._process_lock:
                    proc = self._proc
                if proc is not None and proc.poll() is None:
                    self._stop_event.wait(.1)
                    continue
                if self._stop_event.is_set():
                    break
                logger.info(f"ffplay 已退出，{self._retry:g}s 后重连")
                if self._stop_event.wait(self._retry):
                    break
                with self._process_lock:
                    if self._stop_event.is_set():
                        break
                    self._proc = self._launch()
        except Exception as exc:
            message = f"预览监督失败: {exc}"
            (logger.error if self._required else logger.warn)(message)
        finally:
            self._stop_event.set()
            if not terminate_process(self._proc):
                logger.error("预览子进程未能回收，请检查 preview.log")
            self._close_log()

    def stop(self):
        self._stop_event.set()
        with self._process_lock:
            proc = self._proc
        if not terminate_process(proc):
            logger.error("预览子进程停止超时")
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=7.0)
            if worker.is_alive():
                logger.error("预览监督线程尚未退出")
                return
        self._close_log()

    def restart(self, url=None):
        self.stop()
        return self.start(url or self._url)

    def is_running(self):
        return bool(self._worker is not None and self._worker.is_alive()
                    and not self._stop_event.is_set())

    def _close_log(self):
        handle, self._log_handle = self._log_handle, None
        if handle is not None:
            handle.close()
