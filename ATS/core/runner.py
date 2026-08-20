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
                self._run_module(task.module, cls, module_defaults, params,
                                 cycle, rep, repeat_total)

    def _run_module(self, name, cls, config, params, cycle, rep_index, repeat_total):
        """执行单次模块：实例化 -> setup -> run(带重试) -> teardown。"""
        label = name if repeat_total <= 1 else f"{name}[{rep_index + 1}/{repeat_total}]"
        mod_start = time.monotonic()
        logger.step(f">>> 模块 [{label}] 开始执行 (cycle {cycle})")
        try:
            module = cls(config)

            try:
                module.setup(self.ctx, self.console)
            except Exception as e:
                logger.error(f"[{label}] setup 异常: {e}")
                self._record(TestResult(
                    name=name, module=name, status=ERROR,
                    message=f"setup 异常: {e}"), cycle)
                self.module_status[name] = ERROR
                return

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

            self._record_results(name, result, last_err, cycle)
            if isinstance(result, list):
                st = PASSED if any(r.status in (PASSED, SKIPPED) for r in result) else FAILED
            elif result is not None:
                st = result.status
            else:
                st = FAILED
            self.module_status[name] = st
        finally:
            elapsed = time.monotonic() - mod_start
            status = self.module_status.get(name, "?")
            logger.step(f"<<< 模块 [{label}] 结束，耗时 {elapsed:.1f}s（结果 {status}）")

    def _record_results(self, name, result, last_err, cycle):
        """把模块返回的结果（单条或多条）记录进 self.results 并打印。"""
        if result is None:
            self._record(TestResult(name=name, module=name, status=FAILED,
                                    message="模块未返回结果"), cycle)
            return
        if isinstance(result, list):
            for r in result:
                self._record(r, cycle)
        else:
            self._record(result, cycle)

    def _record(self, r: TestResult, cycle: int = 0):
        r.timestamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not r.scenario:
            r.scenario = self.scenario.name
        if not r.cycle:
            r.cycle = cycle
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
