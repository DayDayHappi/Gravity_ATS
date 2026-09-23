"""测试编排器：按 Scenario 的 Task 列表调度模块执行，支持 repeat/loop。

职责边界：
- **Runner**：什么时候执行（调度）——不关心模块怎么测，只按 Task 列表驱动。
- **Module**：怎么测（能力）。
- **Scenario**：怎么组合测试（流程/循环次数/持续时间）。

职责：
1. 按 ``scenario.tasks`` 声明顺序执行（顺序即流程，不再拓扑排序）。
2. 每个 Task 支持 ``repeat``（重复次数，Runner 循环驱动，模块内不写 for）。
3. 外层 ``loop`` 支持整轮循环（count 次数 / duration 时长 / 无限）。
4. 参数合并：module 默认(config/modules/*.yaml) + task.override + task.duration(经 duration_key)。
5. fail-fast：依赖模块 FAIL/ERROR 则本模块 SKIP（SKIP 不阻断依赖）。
6. 收集所有 TestResult，交 reporter 输出。
"""
import datetime as _dt
import time

from . import logger
from .config import load_module_config
from .result import TestResult, PASSED, FAILED, SKIPPED, ERROR


class RunnerError(Exception):
    pass


class ScenarioAbort(Exception):
    """ADR-016 P0-04/P0-07：Scenario 级中止信号。

    由 Runner 在恢复策略 on_exhausted=abort_scenario 或 monitor-only 确认
    UNRESPONSIVE 时抛出，``TestRunner.run()`` 外层捕获后退出整个 while loop，
    ScenarioManager finally 仍正常 cleanup。
    """


class TestRunner:
    """按场景 Task 列表执行模块的编排器。"""

    def __init__(self, system_cfg, ctx, scenario):
        self.system_cfg = system_cfg
        self.ctx = ctx
        self.scenario = scenario
        self.console = getattr(ctx, "console", None)
        self.results: list = []           # 所有 TestResult
        self.module_status: dict = {}     # module name -> PASS/FAIL/SKIP/ERROR（本 cycle）
        runner_cfg = system_cfg.get("runner", {}) or {}
        self.retry = int(runner_cfg.get("retry_on_fail", 1))
        self.fail_fast = bool(runner_cfg.get("fail_fast", True))

    def run(self) -> list:
        """执行场景的全部 cycle，返回 TestResult 列表。"""
        from ..modules.base import get_module_cls
        import importlib
        importlib.import_module("ATS.modules")  # 触发模块注册

        loop = self.scenario.loop
        cycle = 0
        deadline = None
        if loop.enable and loop.duration:
            deadline = time.monotonic() + float(loop.duration)

        try:
            while True:
                cycle += 1
                logger.step(f"===== Scenario [{self.scenario.name}] cycle {cycle} 开始 =====")
                self._run_tasks(cycle)
                logger.step(f"===== Scenario [{self.scenario.name}] cycle {cycle} 结束 =====")

                if not loop.enable:
                    break
                if loop.count is not None and cycle >= int(loop.count):
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if loop.count is None and loop.duration is None:
                    logger.info(f"loop 无限循环，cycle {cycle} 完成，继续...（Ctrl+C 中断）")
        except ScenarioAbort:
            # P0-04：abort_scenario 中止整个 Scenario（退出 while loop），不再进下一 cycle
            logger.error("Scenario 已中止（abort_scenario / monitor-only UNRESPONSIVE），停止后续 cycle")
        except KeyboardInterrupt:
            logger.warn("用户中断循环")
        return self.results

    def _run_tasks(self, cycle: int):
        """执行一轮 tasks（按声明顺序）。"""
        from ..modules.base import get_module_cls
        self.module_status = {}   # 每 cycle 独立判定 fail-fast

        for task in self.scenario.tasks:
            cls = get_module_cls(task.module)
            if cls is None:
                self._record(TestResult(
                    name=task.module, module=task.module, status=ERROR,
                    message="模块未注册"), cycle)
                self.module_status[task.module] = ERROR
                continue

            # fail-fast：依赖模块 FAIL/ERROR 则跳过；SKIP 不阻断
            deps = getattr(cls, "depends", []) or []
            blocked = [d for d in deps if self.module_status.get(d) in (FAILED, ERROR)]
            if blocked:
                self._record(TestResult(
                    name=task.module, module=task.module, status=SKIPPED,
                    message=f"依赖模块未通过: {blocked}"), cycle)
                self.module_status[task.module] = SKIPPED
                continue

            # 参数合并：module 默认 + task.override + task.duration(经 duration_key)
            module_defaults = load_module_config(task.module)
            params = dict(task.override or {})
            dk = getattr(cls, "duration_key", None)
            if task.duration is not None and dk:
                params[dk] = task.duration

            repeat_total = max(1, int(task.repeat or 1))
            for rep in range(repeat_total):
                # ADR-016：每次 _run_module 的 Outcome 都必须处理，直到
                # success / continue / abort_scenario（P1-01：retry 二次 Outcome 不再丢弃）。
                outcome = self._run_module(task.module, cls, module_defaults, params,
                                           cycle, rep, repeat_total)
                while True:
                    if outcome is None:
                        break
                    if outcome.action == "abort_scenario":
                        # NEW-P0-01：恢复失败/耗尽必须生成 framework FAIL/ERROR，
                        # 保证最终退出码非 0（结果一致性）。
                        if not outcome.success:
                            self._record_framework_recovery_error(outcome, cycle)
                        logger.error("恢复策略 on_exhausted/abort_scenario，中止整个 Scenario")
                        raise ScenarioAbort("abort_scenario")
                    if outcome.action == "retry_current_task":
                        logger.info(f"恢复策略 retry_current_task：重跑模块 {task.module}")
                        outcome = self._run_module(task.module, cls, module_defaults,
                                                   params, cycle, rep, repeat_total)
                        continue   # 二次 Outcome 继续进入本循环处理（P1-01）
                    if outcome.action == "continue":
                        # NEW-P0-03：恢复成功，不重跑当前 Task，继续下一个 Task。
                        # 设计文档 §24：continue 必须 success==True，失败则 abort。
                        if not outcome.success:
                            logger.error("continue 但恢复失败，记录错误并中止")
                            self._record_framework_recovery_error(outcome, cycle)
                            raise ScenarioAbort("continue with failed recovery")
                        logger.info("恢复策略 after_recovery=continue：恢复成功，继续下一个 Task")
                        break
                    # NEW-P0-02 兜底：未知 Outcome.action fail-closed，禁止静默 break 继续
                    logger.error(f"未知 RecoveryOutcome.action: {outcome.action!r}，"
                                 f"fail-closed 中止 Scenario")
                    self._record_framework_recovery_error(outcome, cycle)
                    raise ScenarioAbort(f"unknown recovery action: {outcome.action!r}")

    def _record_framework_recovery_error(self, outcome, cycle):
        """NEW-P0-01：恢复失败的 Outcome 转成 framework 级 TestResult（board_recovery ERROR）。

        Coordinator 不感知报告结构，此处由 Runner 负责「RecoveryOutcome → framework
        TestResult」，保证恢复失败/耗尽最终能影响退出码（不被 PASS 覆盖）。
        """
        msg = (f"恢复失败：backend={outcome.backend}, attempts={outcome.attempts}, "
               f"reason={outcome.message}")
        self._record(TestResult(
            name="board_recovery", module="board_recovery", status=ERROR,
            message=msg), cycle)
        self.module_status["board_recovery"] = ERROR

    def _run_module(self, name, cls, config, params, cycle, rep_index, repeat_total):
        """执行单次模块：实例化 -> setup -> run(带重试) -> teardown -> recovery checkpoint。

        Returns:
            RecoveryOutcome（ADR-016）或 None（无 recovery / 未触发）。
        """
        label = name if repeat_total <= 1 else f"{name}[{rep_index + 1}/{repeat_total}]"
        mod_start = time.monotonic()
        logger.step(f">>> 模块 [{label}] 开始执行 (cycle {cycle})")
        outcome = None
        try:
            module = cls(config)

            try:
                module.setup(self.ctx, self.console)
            except Exception as e:
                logger.error(f"[{label}] setup 异常: {e}")
                self._record(TestResult(
                    name=name, module=name, status=ERROR,
                    message=f"setup 异常: {e}"), cycle, rep_index)
                self.module_status[name] = ERROR
                return None

            result = None
            last_err = None
            for attempt in range(1, self.retry + 1):
                try:
                    logger.step(f"    - 执行模块: {label}"
                                + (f" (尝试 {attempt})" if attempt > 1 else ""))
                    result = module.run(self.ctx, self.console, params=params)
                    if self._overall_pass(result):
                        break
                except Exception as e:
                    last_err = e
                    logger.warn(f"[{label}] 第 {attempt} 次执行异常: {e}")
                    result = TestResult(name=name, module=name, status=ERROR,
                                        message=f"执行异常: {e}")
                if attempt < self.retry:
                    logger.info(f"[{label}] 失败，重试中...")

            try:
                module.teardown(self.ctx, self.console)
            except Exception as e:
                logger.warn(f"[{label}] teardown 异常: {e}")

            self._record_results(name, result, last_err, cycle, rep_index)
            if isinstance(result, list):
                st = PASSED if any(r.status in (PASSED, SKIPPED) for r in result) else FAILED
            elif result is not None:
                st = result.status
            else:
                st = FAILED
            self.module_status[name] = st

            # ADR-016 recovery checkpoint：模块完成后检查板卡健康
            outcome = self._recovery_checkpoint(cycle, name, rep_index)
        finally:
            elapsed = time.monotonic() - mod_start
            status = self.module_status.get(name, "?")
            logger.step(f"<<< 模块 [{label}] 结束，耗时 {elapsed:.1f}s（结果 {status}）")
        return outcome

    def _recovery_checkpoint(self, cycle, task, rep_index):
        """ADR-016 Runner 接入点：Task 完成后检查健康，SUSPECTED 在同一次安全点
        完成 confirm_failures 次主动确认（P0-03），UNRESPONSIVE 交给 Coordinator；
        monitor-only 且 UNRESPONSIVE 时抛 ScenarioAbort（P0-07）。Runner 不认识具体硬件。

        Returns:
            RecoveryOutcome；无 monitor/recovery 配置或状态健康时返回 None。
        """
        monitor = getattr(self.ctx, "board_health_monitor", None)
        if monitor is None:
            return None

        state = monitor.current_state()

        # SUSPECTED：在安全点（无并发命令事务）一次性完成 confirm_failures 次确认（P0-03）
        if state == "SUSPECTED":
            logger.warn(f"板卡疑似无响应（SUSPECTED），在安全点执行 {monitor.confirm_failures} 次主动健康确认...")
            final_state = monitor.confirm_health(self.console)
            if final_state == "HEALTHY":
                logger.info("健康确认通过，继续测试")
                return None
            state = final_state   # UNRESPONSIVE

        # UNRESPONSIVE：交给 Coordinator 或 monitor-only 语义（P0-07）
        if state == "UNRESPONSIVE":
            coord = getattr(self.ctx, "recovery_coordinator", None)
            reason = monitor.get_status().get("reason", "")
            if coord is None:
                # P0-07：monitor-only，确认 UNRESPONSIVE 后必须形成可见失败 + abort
                logger.error(f"板卡无响应（UNRESPONSIVE: {reason}），recovery 未启用，"
                             f"记录 board_health 失败并中止 Scenario（不 PowerCycle）")
                self._record(TestResult(
                    name="board_health", module="board_health", status=FAILED,
                    message=f"板卡确认无响应: {reason}"), cycle, rep_index)
                self.module_status["board_health"] = FAILED
                raise ScenarioAbort("monitor-only UNRESPONSIVE")
            return coord.handle_unresponsive(
                cycle, task, rep_index + 1, state, reason)

        return None

    def _record_results(self, name, result, last_err, cycle, rep_index):
        """把模块返回的结果（单条或多条）记录进 self.results 并打印。"""
        if result is None:
            self._record(TestResult(name=name, module=name, status=FAILED,
                                    message="模块未返回结果"), cycle, rep_index)
            return
        if isinstance(result, list):
            for r in result:
                self._record(r, cycle, rep_index)
        else:
            self._record(result, cycle, rep_index)

    def _record(self, r: TestResult, cycle: int = 0, rep_index: int = -1):
        r.timestamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not r.scenario:
            r.scenario = self.scenario.name
        if not r.cycle:
            r.cycle = cycle
        if rep_index >= 0 and not r.rep:
            r.rep = rep_index + 1   # 1-based repeat 序号
        self.results.append(r)
        logger.result_line(r.status, r.name, r.elapsed_ms, r.message)

    def _overall_pass(self, result) -> bool:
        """判断模块返回结果是否整体通过。SKIP 视为通过（主动跳过不算失败）。"""
        if result is None:
            return False
        if isinstance(result, list):
            if not result:
                return False
            return any(r.status in (PASSED, SKIPPED) for r in result)
        return result.status in (PASSED, SKIPPED)
