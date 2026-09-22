"""恢复协调器（RecoveryCoordinator，ADR-016）。

职责边界（红线）：
- 消费健康状态、决定异常后怎么办、协调恢复流程。
- **不负责**健康判据本身、不负责上下电二进制协议、不负责 photo/video/rtmp 业务逻辑。
- 不认识具体硬件（不 import power_commands 帧、不知道 115200 波特率），只调用
  RecoveryBackend 的统一接口。
- 只复用现有 prepare action 做环境重新收敛，不复制第二套 WiFi/FTP 逻辑。

状态机：``IDLE → REQUESTED → RECOVERING → RECONCILING → HEALTHY``；恢复失败进 ``FAILED``。
必须有 ``recovery_in_progress`` 互斥，同一时间只允许一个恢复流程。

恢复事件独立留痕（``ctx.recovery_history``），不能被 PASS 覆盖。
"""
import time
import threading

from ..core import logger
from ..core.scenario import PREPARE_ACTIONS
from .recovery_backends.base import (
    RecoveryBackendUnavailable, create_backend,
)

# Coordinator 状态
IDLE = "IDLE"
REQUESTED = "REQUESTED"
RECOVERING = "RECOVERING"
RECONCILING = "RECONCILING"
HEALTHY = "HEALTHY"
FAILED = "FAILED"


class RecoveryOutcome:
    """一次恢复流程的结论（Runner 据此决定 retry / abort / continue）。"""

    def __init__(self, action, success, backend=None, attempts=0, message=""):
        self.action = action            # "retry_current_task" | "abort_scenario" | "continue"
        self.success = success
        self.backend = backend
        self.attempts = attempts
        self.message = message

    def __repr__(self):
        return (f"<RecoveryOutcome action={self.action} success={self.success} "
                f"attempts={self.attempts}>")


class RecoveryCoordinator:
    """协调「检测 → 确认 → 恢复决策 → 恢复执行 → 环境重新收敛 → 流程恢复/终止」。"""

    def __init__(self, policy: dict = None, ctx=None, console=None, monitor=None):
        self.policy = policy or {}
        self.ctx = ctx
        self.console = console
        self.monitor = monitor

        self.enabled = bool(self.policy.get("enabled", False))
        self.backend_name = self.policy.get("backend", "power_cycle")
        self.max_attempts = int(self.policy.get("max_attempts", 2))
        self.after_recovery = self.policy.get("after_recovery", "retry_current_task")
        self.on_exhausted = self.policy.get("on_exhausted", "abort_scenario")
        self.restore = list(self.policy.get("restore", []) or [])

        self._state = IDLE
        self._lock = threading.Lock()
        self._in_progress = False
        self._attempts = 0
        self._backend = None
        self._last_outcome = None

    # ---------- 状态查询 ----------

    @property
    def in_progress(self) -> bool:
        with self._lock:
            return self._in_progress

    @property
    def attempts(self) -> int:
        with self._lock:
            return self._attempts

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def _record(self, cycle, task, rep, health_state, reason, backend,
                attempt, recovery_result, restore_result):
        """追加一条恢复历史到 ctx.recovery_history（不能被 PASS 覆盖）。"""
        if self.ctx is None:
            return
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scenario": getattr(self.ctx, "scenario_name", "") or "",
            "cycle": cycle,
            "task": task,
            "rep": rep,
            "health_state": health_state,
            "reason": reason,
            "backend": backend,
            "attempt": attempt,
            "recovery_result": recovery_result,
            "restore_result": restore_result,
        }
        if not hasattr(self.ctx, "recovery_history") or self.ctx.recovery_history is None:
            self.ctx.recovery_history = []
        self.ctx.recovery_history.append(entry)
        logger.log_recovery(
            f"recovery_history | {entry}"
        )

    # ---------- 恢复流程入口（Runner checkpoint 调用） ----------

    def handle_unresponsive(self, cycle, task, rep, health_state, reason) -> RecoveryOutcome:
        """处理 UNRESPONSIVE：决策 + 恢复 + 环境收敛，返回给 Runner 的结论。

        幂等/互斥：``recovery_in_progress`` 期间重复调用直接返回 ``continue``，
        防止多个 health event 并发触发多次 reboot。
        """
        with self._lock:
            if self._in_progress:
                return RecoveryOutcome("continue", False, attempts=self._attempts,
                                       message="恢复流程进行中")
            self._in_progress = True
            self._state = REQUESTED

        try:
            return self._recover(cycle, task, rep, health_state, reason)
        finally:
            with self._lock:
                self._in_progress = False

    def _recover(self, cycle, task, rep, health_state, reason) -> RecoveryOutcome:
        # 1. 后端可用性检查（禁止静默 fallback）
        backend = self._resolve_backend()
        if backend is None:
            msg = (f"恢复后端不可用: backend={self.backend_name} 未注册或 power_switch "
                   f"未启用/探测失败（RecoveryBackendUnavailable）")
            logger.log_recovery(msg)
            logger.error(msg)
            self._state = FAILED
            self._record(cycle, task, rep, health_state, reason, self.backend_name,
                         self._attempts + 1, "backend_unavailable", "")
            return RecoveryOutcome(self.on_exhausted, False, backend=self.backend_name,
                                   attempts=self._attempts, message=msg)

        # 2. 次数上限：超过 max_attempts → on_exhausted（禁止无限重启）
        if self._attempts >= self.max_attempts:
            msg = (f"恢复次数已达上限 max_attempts={self.max_attempts}，"
                   f"执行 on_exhausted={self.on_exhausted}")
            logger.log_recovery(msg)
            logger.error(msg)
            self._state = FAILED
            self._record(cycle, task, rep, health_state, reason, backend.name,
                         self._attempts, "exhausted", "")
            return RecoveryOutcome(self.on_exhausted, False, backend=backend.name,
                                   attempts=self._attempts, message=msg)

        self._attempts += 1
        attempt = self._attempts
        logger.log_recovery(
            f"recovery start | cycle={cycle} task={task} rep={rep} "
            f"state={health_state} reason={reason} backend={backend.name} "
            f"attempt={attempt}/{self.max_attempts}"
        )
        logger.warn(f"板卡无响应，开始恢复（backend={backend.name}，第 {attempt} 次）")

        # 3. 记录 fresh-ready 游标（P0-06：PowerCycle 前记录，board_ready 只认新 RX）
        self._snapshot_recovery_cursor()

        # 4. 失效板端运行状态（PowerCycle 前）
        self._invalidate_board_state()

        # 5. 执行恢复
        self._state = RECOVERING
        try:
            backend.recover(self.ctx)
            recovery_result = "ok"
        except Exception as e:
            logger.log_recovery(f"recovery failed | {e}")
            logger.error(f"恢复执行失败: {e}")
            self._state = FAILED
            self._record(cycle, task, rep, health_state, reason, backend.name,
                         attempt, f"failed: {e}", "")
            return RecoveryOutcome(self.on_exhausted, False, backend=backend.name,
                                   attempts=self._attempts, message=f"恢复执行失败: {e}")

        # 6. 环境重新收敛（board_ready + 声明式 restore 列表）
        self._state = RECONCILING
        restore_result = self._restore_environment()
        ok = restore_result == "ok"

        if ok:
            self._state = HEALTHY
            if self.monitor is not None:
                self.monitor.mark_healthy()
        else:
            self._state = FAILED

        self._record(cycle, task, rep, health_state, reason, backend.name,
                     attempt, recovery_result, restore_result)

        if ok:
            logger.log_recovery(f"recovery ok | backend={backend.name} attempt={attempt}")
            return RecoveryOutcome(self.after_recovery, True, backend=backend.name,
                                   attempts=self._attempts, message="恢复成功")
        logger.log_recovery(f"recovery restore failed | {restore_result}")
        return RecoveryOutcome(self.on_exhausted, False, backend=backend.name,
                               attempts=self._attempts, message=restore_result)

    # ---------- 内部 ----------

    def _resolve_backend(self):
        if self._backend is None:
            self._backend = create_backend(self.backend_name)
        if self._backend is None:
            return None
        # available() 检查（power_cycle 后端要求 ctx.power_switch 就绪）
        if not self._backend.available(self.ctx):
            return None
        return self._backend

    def validate(self):
        """前置校验（P1-02/P1-04/NEW-P0-02）：正式 tasks 前调用，fail-closed。

        - policy 字段完整校验：max_attempts >= 1；after_recovery / on_exhausted
          必须为已支持枚举值（NEW-P0-02，防拼写错误导致恢复失败后继续执行）。
        - backend 未注册 / 不可用（如 power_switch 未启用）→ 抛
          ``RecoveryBackendUnavailable``，禁止静默降级。
        - restore 列表里存在未注册的 prepare action → 抛 ValueError，
          禁止恢复不完整仍判 ok。
        """
        # 1. policy 字段校验（NEW-P0-02）
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError(
                f"recovery.max_attempts 必须为 >=1 的整数，实际 {self.max_attempts!r}"
            )
        if self.after_recovery not in ("retry_current_task", "continue"):
            raise ValueError(
                f"recovery.after_recovery 只支持 retry_current_task/continue，"
                f"实际 {self.after_recovery!r}"
            )
        if self.on_exhausted not in ("abort_scenario",):
            raise ValueError(
                f"recovery.on_exhausted 只支持 abort_scenario，实际 {self.on_exhausted!r}"
            )

        # 2. backend 前置校验（P1-02）
        backend = self._resolve_backend()
        if backend is None:
            raise RecoveryBackendUnavailable(
                f"recovery.backend={self.backend_name!r} 不可用：后端未注册或 "
                f"power_switch 未启用/探测失败（禁止静默 fallback）"
            )

        # 3. restore action 前置校验（P1-04）
        for name in self.restore:
            if name == "board_ready":
                continue
            if PREPARE_ACTIONS.get(name) is None:
                raise ValueError(
                    f"recovery.restore 含未注册动作 {name!r}（已注册: "
                    f"{sorted(PREPARE_ACTIONS.keys())}）"
                )
        return True

    def _invalidate_board_state(self):
        """失效板端运行状态（调用 Context 局部失效，不清 system_config/console 等）。"""
        if self.ctx is not None:
            try:
                self.ctx.invalidate_board_runtime_state()
            except Exception as e:
                logger.warn(f"失效板端运行状态异常(可忽略): {e}")

    def _snapshot_recovery_cursor(self):
        """PowerCycle 前记录串口 RX 游标（P0-06），供 board_ready 做 fresh-ready。"""
        console = getattr(self.ctx, "console", None) if self.ctx is not None else None
        if console is not None and hasattr(console, "snapshot_rx_cursor"):
            try:
                cursor = console.snapshot_rx_cursor()
                self.ctx.recovery_cursor = cursor
                logger.log_recovery(f"fresh-ready cursor 已记录: {cursor}")
            except Exception as e:
                logger.warn(f"记录 fresh-ready 游标异常(可忽略): {e}")

    def _restore_environment(self) -> str:
        """复用现有 prepare action 重新收敛环境（board_ready 必做，restore 按声明）。

        fail-closed（P1-04）：未知 restore action 直接判 restore failed，不得
        静默跳过后返回 ok。
        """
        system_cfg = getattr(self.ctx, "system_config", None) or {}
        actions = ["board_ready"] + [a for a in self.restore if a != "board_ready"]
        for name in actions:
            fn = PREPARE_ACTIONS.get(name)
            if fn is None:
                logger.log_recovery(f"restore 未知动作，恢复失败: {name}")
                logger.error(f"恢复失败：restore 含未注册动作 {name!r}")
                return f"restore failed: unknown action {name!r}"
            try:
                logger.log_recovery(f"restore action: {name}")
                fn(self.ctx, system_cfg)
            except Exception as e:
                logger.log_recovery(f"restore 失败 action={name}: {e}")
                logger.error(f"环境重新收敛失败({name}): {e}")
                return f"restore failed at {name}: {e}"
        return "ok"
