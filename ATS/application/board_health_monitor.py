"""板卡健康监测器（BoardHealthMonitor，ADR-016）。

职责边界（红线）：
- 只判断 EVB 是否健康，输出 ``HealthEvent`` / 维护 ``HEALTHY / SUSPECTED /
  UNRESPONSIVE`` 状态机。
- **不认识 PowerSwitch**，不决定是否重启、不决定 Task 重跑、不恢复 WiFi/FTP、不改 Scenario。
- 监听 EVB 串口活动（通过 ``SerialConsole.add_listener`` 订阅，读线程回调）时
  **禁止阻塞**：listener 内不得 sleep / exec_sync / exec_async / PowerSwitch / FTP / 网络 IO。

状态机（ADR-016）：
``HEALTHY →（超过 inactivity_timeout 无串口活动）→ SUSPECTED →（主动健康确认连续失败）→ UNRESPONSIVE``。

「无串口输出」不直接等价「整板死机」：``UNRESPONSIVE`` 只表示 ATS 无法通过当前
EVB 控制链路取得有效响应，不推断根因。主动 probe 必须在安全点执行（无并发命令
事务时），由 Runner 控制流在 checkpoint 调用 ``probe()``，Monitor 线程只观察。
"""
import time
import threading

from ..core import logger
from . import runtime_control

# 健康状态常量
HEALTHY = "HEALTHY"
SUSPECTED = "SUSPECTED"
UNRESPONSIVE = "UNRESPONSIVE"


class HealthEvent:
    """健康状态事件（Monitor 输出，Coordinator 输入）。"""

    def __init__(self, state, reason, at_monotonic=None, clock=None):
        self.state = state
        self.reason = reason
        self.at_monotonic = at_monotonic if at_monotonic is not None else time.monotonic()
        self.clock = clock or time.strftime("%H:%M:%S")

    def to_dict(self):
        return {
            "state": self.state,
            "reason": self.reason,
            "clock": self.clock,
        }


class BoardHealthMonitor:
    """EVB 整板控制链路健康监测器（Scenario 生命周期能力，非 Task）。

    用法::

        mon = BoardHealthMonitor(config)
        mon.start()
        console.add_listener(mon.on_rx)        # 订阅串口原始数据（读线程回调，极轻量）
        ...
        # Runner 在 checkpoint 调用：
        state = mon.current_state()
        if state == SUSPECTED:
            ok = mon.probe(console)            # 主动健康确认（安全点）
        console.remove_listener(mon.on_rx)
        mon.stop()
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.check_interval = float(cfg.get("check_interval", 2.0))
        self.inactivity_timeout = float(cfg.get("inactivity_timeout", 60.0))
        self.confirm_failures = int(cfg.get("confirm_failures", 3))
        self.confirm_interval = float(cfg.get("confirm_interval", 3.0))

        self._lock = threading.Lock()
        self._started = False
        self._state = HEALTHY
        self._reason = ""
        self._last_rx_monotonic = 0.0      # 最后有效 RX 时间（monotonic）
        self._last_rx_clock = ""
        self._rx_count = 0
        self._consecutive_probe_failures = 0
        self._events = []                  # HealthEvent 列表（留痕）

    # ---------- 生命周期 ----------

    def start(self):
        with self._lock:
            self._started = True
            self._state = HEALTHY
            self._reason = ""
            self._consecutive_probe_failures = 0
            now = time.monotonic()
            self._last_rx_monotonic = now
            self._last_rx_clock = time.strftime("%H:%M:%S")
            runtime_control.clear_recovery()
            self._events = []

    def stop(self):
        with self._lock:
            self._started = False

    # ---------- 串口监听（读线程回调，禁止阻塞） ----------

    def on_rx(self, text):
        """串口原始数据回调（读线程调用）。只更新 last_rx 时间戳，极轻量。"""
        if not text:
            return
        now = time.monotonic()
        with self._lock:
            if not self._started:
                return
            self._last_rx_monotonic = now
            self._last_rx_clock = time.strftime("%H:%M:%S")
            self._rx_count += 1

    # ---------- 状态查询（Runner checkpoint 调用） ----------

    def current_state(self) -> str:
        """返回当前状态；SUSPECTED 由「超时检测」动态推进（基于 last_rx 距今）。"""
        with self._lock:
            if not self._started:
                return HEALTHY
            # 已 UNRESPONSIVE 保持；否则按超时推进 HEALTHY -> SUSPECTED
            if self._state != UNRESPONSIVE:
                if (time.monotonic() - self._last_rx_monotonic) > self.inactivity_timeout:
                    self._state = SUSPECTED
                    self._reason = (
                        f"超过 {self.inactivity_timeout:g}s 无串口活动"
                        f"（last_rx={self._last_rx_clock}）"
                    )
                    runtime_control.request_recovery()
                    self._record_event(SUSPECTED, self._reason)
            return self._state

    def is_unresponsive(self) -> bool:
        return self.current_state() == UNRESPONSIVE

    # ---------- 主动健康确认（安全点执行，Monitor 线程不调） ----------

    def probe(self, console) -> bool:
        """主动健康确认：``console.health_check()``（echo EVBTEST_HELLO → 有效响应）。

        必须在安全点（无并发命令事务）由 Runner 调用，Monitor 线程不执行。
        成功回到 HEALTHY；连续失败达 ``confirm_failures`` 进入 UNRESPONSIVE。

        Returns:
            True 表示本次 probe 成功（板可响应）。
        """
        if console is None:
            return False
        try:
            ok = console.health_check()
        except Exception as e:
            logger.warn(f"板卡健康确认异常: {e}")
            ok = False

        with self._lock:
            if ok:
                self._state = HEALTHY
                self._reason = "健康确认通过"
                self._consecutive_probe_failures = 0
                # 成功 probe 视为一次有效活动，刷新 last_rx，避免立即重新 SUSPECTED
                now = time.monotonic()
                self._last_rx_monotonic = now
                self._last_rx_clock = time.strftime("%H:%M:%S")
                runtime_control.clear_recovery()
                self._record_event(HEALTHY, self._reason)
            else:
                self._consecutive_probe_failures += 1
                self._reason = (
                    f"健康确认失败 {self._consecutive_probe_failures}/{self.confirm_failures}"
                )
                if self._consecutive_probe_failures >= self.confirm_failures:
                    self._state = UNRESPONSIVE
                    self._reason = (
                        f"主动健康确认连续失败 {self._consecutive_probe_failures} 次"
                    )
                    runtime_control.request_recovery()
                    self._record_event(UNRESPONSIVE, self._reason)
                else:
                    self._record_event(SUSPECTED, self._reason)
        return ok

    def mark_healthy(self):
        """恢复完成后由 Coordinator 调用，回到 HEALTHY 并清零失败计数。"""
        with self._lock:
            self._state = HEALTHY
            self._reason = "恢复完成，重新确认健康"
            self._consecutive_probe_failures = 0
            now = time.monotonic()
            self._last_rx_monotonic = now
            self._last_rx_clock = time.strftime("%H:%M:%S")
            runtime_control.clear_recovery()
            self._record_event(HEALTHY, self._reason)

    # ---------- 证据与状态导出 ----------

    def _record_event(self, state, reason):
        self._events.append(HealthEvent(state, reason, time.monotonic(), time.strftime("%H:%M:%S")))

    def get_status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "reason": self._reason,
                "last_rx_clock": self._last_rx_clock,
                "rx_count": self._rx_count,
                "consecutive_probe_failures": self._consecutive_probe_failures,
                "inactivity_timeout": self.inactivity_timeout,
            }

    def pop_events(self) -> list:
        """取走并清空已记录的健康事件（供 report 留痕）。"""
        with self._lock:
            evs = [e.to_dict() for e in self._events]
            self._events = []
            return evs
