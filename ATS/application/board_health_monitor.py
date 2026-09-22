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
EVB 控制链路取得有效响应，不推断根因。

持续监测（P0-01/P0-02 修复）：内置轻量 watchdog 线程，每 ``check_interval`` 秒
只比较 ``time.monotonic() - last_rx``；超过 ``inactivity_timeout`` 时置 SUSPECTED
并 ``runtime_control.request_recovery()``。watchdog 线程**禁止** exec_sync/exec_async/
health_check/PowerSwitch/FTP/网络 IO——主动健康 probe 仍由 Runner 在安全点执行。
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
        self._validate_params()

        self._lock = threading.Lock()
        self._started = False
        self._state = HEALTHY
        self._reason = ""
        self._last_rx_monotonic = 0.0      # 最后有效 RX 时间（monotonic）
        self._last_rx_clock = ""
        self._rx_count = 0
        self._consecutive_probe_failures = 0
        self._events = []                  # HealthEvent 列表（留痕）
        self._watchdog = None
        self._stop_watchdog = threading.Event()

    def _validate_params(self):
        """参数合法性校验（P1-06）：非法配置 fail-closed。"""
        if self.check_interval <= 0:
            raise ValueError(f"board_health.check_interval 必须 > 0，实际 {self.check_interval}")
        if self.inactivity_timeout <= 0:
            raise ValueError(f"board_health.inactivity_timeout 必须 > 0，实际 {self.inactivity_timeout}")
        if self.confirm_failures < 1:
            raise ValueError(f"board_health.confirm_failures 必须 >= 1，实际 {self.confirm_failures}")
        if self.confirm_interval < 0:
            raise ValueError(f"board_health.confirm_interval 必须 >= 0，实际 {self.confirm_interval}")

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
        # 启动 watchdog 线程（P0-01：持续监测，长 Task 中途死机能及时发现）
        self._stop_watchdog.clear()
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="board-health-watchdog", daemon=True
        )
        self._watchdog.start()

    def stop(self):
        self._stop_watchdog.set()
        with self._lock:
            self._started = False
        if self._watchdog is not None:
            self._watchdog.join(timeout=2.0)
            self._watchdog = None
        # NEW-P2-01：Scenario 生命周期收尾兜底，清除恢复请求
        runtime_control.clear_recovery()

    # ---------- watchdog（持续监测线程，禁止阻塞/IO） ----------

    def _watchdog_loop(self):
        """轻量 watchdog：每 check_interval 秒比较 last_rx 距今，超时置 SUSPECTED。

        用 ``_stop_watchdog.wait(check_interval)``（NEW-P2-01）：stop() 的 set() 能
        立即唤醒，避免长 check_interval 下 join 超时残留。

        禁止 exec_sync/exec_async/health_check/PowerSwitch/FTP/网络 IO。
        锁内只改 state/reason/event，logger 移出锁外（避免 reader 回调等待文件 IO）。
        """
        while not self._stop_watchdog.wait(self.check_interval):
            with self._lock:
                if not self._started or self._state != HEALTHY:
                    # 已 SUSPECTED/UNRESPONSIVE 时不重复推进，等待 Runner 安全点确认
                    continue
                if (time.monotonic() - self._last_rx_monotonic) > self.inactivity_timeout:
                    self._state = SUSPECTED
                    self._reason = (
                        f"超过 {self.inactivity_timeout:g}s 无串口活动"
                        f"（last_rx={self._last_rx_clock}）"
                    )
                    runtime_control.request_recovery()
                    self._record_event_locked(SUSPECTED, self._reason)
                    should_log = True
                else:
                    should_log = False
            if should_log:
                logger.warn(f"板卡疑似无响应（SUSPECTED）: {self._reason}")

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
        """返回当前状态。watchdog 已负责持续推进 HEALTHY -> SUSPECTED，
        本方法不再做超时推进（避免与 watchdog 重复），仅返回当前状态。"""
        with self._lock:
            if not self._started:
                return HEALTHY
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
                now = time.monotonic()
                self._last_rx_monotonic = now
                self._last_rx_clock = time.strftime("%H:%M:%S")
                runtime_control.clear_recovery()
                self._record_event_locked(HEALTHY, self._reason)
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
                    self._record_event_locked(UNRESPONSIVE, self._reason)
                else:
                    self._record_event_locked(SUSPECTED, self._reason)
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
            self._record_event_locked(HEALTHY, self._reason)

    # ---------- 完整确认流程（P0-03，安全点由 Runner 调用） ----------

    def confirm_health(self, console):
        """在同一安全点一次性完成 ``confirm_failures`` 次主动健康确认（P0-03）。

        规则（ADR-016 / 验收报告 §6）：
        - 任一次 probe 成功 → 回 HEALTHY、清零失败计数、返回 HEALTHY（继续测试）。
        - 连续失败达 ``confirm_failures`` → UNRESPONSIVE，返回 UNRESPONSIVE。
        - 每次 probe 间 sleep ``confirm_interval``（P1-06：时间参数真正接线）。

        必须在安全点（无并发命令事务）由 Runner 调用；Monitor 线程/wdog 不执行。

        Returns:
            最终状态字符串（HEALTHY / UNRESPONSIVE）。
        """
        if console is None:
            # 无 console 无法确认，直接判 UNRESPONSIVE
            with self._lock:
                self._state = UNRESPONSIVE
                self._reason = "无 console，无法健康确认"
                runtime_control.request_recovery()
                self._record_event_locked(UNRESPONSIVE, self._reason)
            return UNRESPONSIVE

        # 从头开始一次完整确认流程（清零历史失败计数，避免跨 checkpoint 累计）
        with self._lock:
            self._consecutive_probe_failures = 0

        for i in range(self.confirm_failures):
            self.probe(console)
            state = self.current_state()
            if state == HEALTHY:
                return HEALTHY
            if state == UNRESPONSIVE:
                return UNRESPONSIVE
            # 未达阈值：sleep confirm_interval 后继续下一次 probe
            if self.confirm_interval > 0 and i < self.confirm_failures - 1:
                time.sleep(self.confirm_interval)
        return self.current_state()

    # ---------- 证据与状态导出 ----------

    def _record_event(self, state, reason):
        with self._lock:
            self._record_event_locked(state, reason)

    def _record_event_locked(self, state, reason):
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
