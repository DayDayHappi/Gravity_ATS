"""PreviewManager：PC 端 ffplay 画面观察器（单例，Scenario 生命周期）。

职责边界（ADR-010）：
- 画面观察是**观察能力**，不是测试能力；播放器生命周期属于 **Scenario 生命周期**，
  不属于 Task 生命周期。
- 播放器只负责「把 RTMP 实时流播出来供人工观察（延时/首帧/卡顿/推流恢复）」，**不参与
  判据**（判据由 ffprobe 实时探测 + RTMP heartbeat 给出）。
- 与 ``RtmpReceiver``/``RtmpServer`` 同级，都是「PC 端本地进程/服务管理器」，故落位
  ``drivers/``，不新增 ``core/`` 或 ``services/`` 目录。

关键适配（stress 多轮 start/stop 推流的现实）：nginx-rtmp 在 EVB 停止推流
（``rtmp_video_stop``）时会断开该 stream 的观看连接，单次 ffplay 进程会在流断后退出、
且下一轮 ``rtmp_video_start`` 时不会自动重连。因此 ``start()`` 内部用 Python 重连
worker 线程：ffplay 退出后 sleep + 重试，直到 ``stop()`` 终止 worker 及子进程。

进程管理走平台抽象层（``ProcessController`` + ``ResourceLocator`` 构造注入），
Windows 用 ``CREATE_NEW_PROCESS_GROUP`` + taskkill 整树回收、ffplay 直启带窗口；
Linux 用 ``start_new_session`` + ``killpg`` 整组回收。ffplay 查找走 ``find_tool()``
（自动处理 ``.exe`` 后缀 + bundled 目录 + PATH）。

无 ffplay / Linux 无 DISPLAY 时跳过（无人值守/SSH 常见，不影响判据）。
"""
import os
import subprocess
import threading

from ..core import logger
from ..platform.processes import ProcessController
from ..platform.resources import ResourceLocator


def _detect_pc_ip(target_ip: str) -> str:
    """通过"连接 target_ip"获取本机与 target_ip 通信的接口 IP。

    不会真正发数据，仅让 OS 选路并返回本端地址。供 preview 与 rtmp 两处复用。
    """
    if not target_ip:
        return ""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target_ip, 1935))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ""


class PreviewManager:
    """RTMP 画面观察器：管理 ffplay 重连 worker 的生命周期（start/stop/restart/is_running）。

    整个 Scenario 生命周期只应有一个实例（由 ``prepare_action("preview_start")`` 创建并
    写入 ``ctx.preview_manager``，``cleanup_action("preview_stop")`` 回收），不得在每个
    task/loop 轮次新建——避免 stress 多轮累积窗口与资源泄漏。

    构造注入 ``process_controller`` / ``resource_locator``，测试可传 mock。
    """

    def __init__(self, config: dict = None, *,
                 process_controller: ProcessController = None,
                 resource_locator: ResourceLocator = None):
        self.config = config or {}
        self._processes = process_controller or ProcessController()
        self._resources = resource_locator or ResourceLocator()
        self._ffplay_path = self._resources.find_tool(
            "ffplay", self.config.get("ffplay_path", "ffplay"))
        self._retry = max(0.05, float(self.config.get("retry_interval", 3.0)))
        self._required = bool(self.config.get("preview_required", False))
        # ffplay 窗口初始尺寸（-x/-y 是窗口尺寸，非视频缩放；0/空 = 不传，跟随原始分辨率）
        self._window_w = int(self.config.get("window_width", 0) or 0)
        self._window_h = int(self.config.get("window_height", 0) or 0)

        self._url = None
        self._stop_event = None      # worker 停止信号（threading.Event，替代取消令牌）
        self._thread = None          # 重连 worker 线程
        self._current_process = None  # 当前 ffplay 子进程（供 stop 立即回收）
        self._lock = threading.RLock()
        self._log_handle = None      # preview.log 句柄

    # ------------------------------------------------------------------
    # 生命周期接口
    # ------------------------------------------------------------------

    def start(self, url: str) -> bool:
        """启动画面观察（幂等：已在运行则直接返回 True）。

        启动重连 worker 线程跑 ffplay，直到 ``stop()`` 终止。返回是否成功启动
        （无 ffplay / Linux 无 DISPLAY 时为 False，不影响判据）。
        """
        if self.is_running():
            logger.info("PreviewManager 已在运行，跳过重复启动")
            return True
        if not self._ffplay_path:
            logger.warn("未找到 ffplay，跳过画面观察（判据仍由 ffprobe + heartbeat 给出）")
            return False
        if not self._can_show():
            logger.info("当前会话不能显示画面窗口，跳过画面观察（无人值守/SSH 常见）")
            return False

        self._url = url
        self._stop_event = threading.Event()
        self._open_log()
        self._thread = threading.Thread(
            target=self._worker, name="rtmp-preview-reconnect", daemon=True)
        self._thread.start()
        logger.info("画面观察重连 worker 已启动")
        return True

    def stop(self):
        """关闭画面观察：终止 worker 及当前 ffplay 子进程，清空状态。幂等。"""
        evt = self._stop_event
        if evt is None:
            return
        evt.set()
        with self._lock:
            proc = self._current_process
        if proc is not None:
            self._processes.terminate(proc)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        self._stop_event = None
        with self._lock:
            self._current_process = None
        self._close_log()

    def restart(self, url: str = None) -> bool:
        """重新连接 RTMP：先 stop 再 start（应用场景：板端重新推流）。"""
        self.stop()
        return self.start(url or self._url)

    def is_running(self) -> bool:
        """worker 线程是否存活。"""
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # 启动实现
    # ------------------------------------------------------------------

    def _can_show(self) -> bool:
        """Windows 交互会话默认可显示；Linux 需有 DISPLAY（SSH/无人值守跳过）。"""
        if self._processes.is_windows:
            return True
        return bool(os.environ.get("DISPLAY"))

    def _argv(self):
        argv = [
            self._ffplay_path,
            "-rtmp_live", "live",
            "-rtmp_buffer", "0",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-framedrop",
            "-sync", "ext",
        ]
        if self._window_w > 0:
            argv += ["-x", str(self._window_w)]
        if self._window_h > 0:
            argv += ["-y", str(self._window_h)]
        argv.append(self._url)
        return argv

    def _worker(self):
        """重连 worker：循环启动 ffplay，退出后 sleep 重试，直到 stop 信号。"""
        evt = self._stop_event
        while not evt.is_set():
            proc = None
            try:
                proc = self._processes.start(
                    self._argv(),
                    stdout=subprocess.DEVNULL,
                    stderr=self._log_handle or subprocess.DEVNULL,
                    show_window=self._processes.is_windows,
                )
                with self._lock:
                    self._current_process = proc
                proc.wait()
                if not evt.is_set():
                    level = logger.error if self._required else logger.warn
                    level("preview stopped unexpectedly（画面观察意外退出），准备自动重连")
            except Exception as exc:
                if not evt.is_set():
                    logger.warn(f"画面观察进程异常: {exc}")
            finally:
                if proc is not None and proc.poll() is None:
                    self._processes.terminate(proc)
                with self._lock:
                    if self._current_process is proc:
                        self._current_process = None
            evt.wait(self._retry)

    def _open_log(self):
        directory = logger.log_dir()
        if not directory:
            return
        try:
            self._log_handle = open(os.path.join(directory, "preview.log"), "ab")
        except OSError:
            self._log_handle = None

    def _close_log(self):
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
