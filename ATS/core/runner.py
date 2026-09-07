"""Scenario task scheduler with repeat/loop, events, and cooperative cancellation."""
from __future__ import annotations

import datetime as _dt
import time

from . import logger
from .cancellation import CancellationToken, OperationCancelled
from .config import load_module_config
from .events import Event, EventType
from .result import CANCELLED, ERROR, FAILED, PASSED, SKIPPED, TestResult


class RunnerError(Exception):
    pass


class TestRunner:
    """Execute a Scenario in declaration order without knowing module internals."""

    __test__ = False

    def __init__(
        self,
        system_cfg,
        ctx,
        scenario,
        event_sink=None,
        cancellation_token: CancellationToken | None = None,
        config_dir: str | None = None,
    ):
        self.system_cfg = system_cfg
        self.ctx = ctx
        self.scenario = scenario
        self.event_sink = event_sink
        self.run_id = getattr(ctx, "run_id", "") or ""
        self.console = getattr(ctx, "console", None)
        self.cancellation_token = (
            cancellation_token
            or getattr(ctx, "cancellation_token", None)
            or CancellationToken()
        )
        self.config_dir = config_dir
        self.results: list[TestResult] = []
        self.module_status: dict[str, str] = {}
        runner_cfg = system_cfg.get("runner", {}) or {}
        self.retry = max(1, int(runner_cfg.get("retry_on_fail", 1)))
        self.fail_fast = bool(runner_cfg.get("fail_fast", True))

    def run(self) -> list[TestResult]:
        import importlib

        importlib.import_module("ATS.modules")
        loop = self.scenario.loop
        cycle = 0
        deadline = None
        if loop.enable and loop.duration:
            deadline = time.monotonic() + float(loop.duration)

        try:
            while True:
                self.cancellation_token.raise_if_cancelled()
                cycle += 1
                before = len(self.results)
                self._emit(EventType.CYCLE_STARTED, cycle=cycle)
                logger.step(f"===== Scenario [{self.scenario.name}] cycle {cycle} 开始 =====")
                try:
                    self._run_tasks(cycle)
                except OperationCancelled:
                    logger.warn(f"Scenario [{self.scenario.name}] cycle {cycle} 已取消")
                    self._emit(EventType.CYCLE_FINISHED, cycle=cycle, status=CANCELLED)
                    raise
                cycle_results = self.results[before:]
                cycle_status = FAILED if any(
                    result.status in (FAILED, ERROR) for result in cycle_results
                ) else PASSED
                logger.step(f"===== Scenario [{self.scenario.name}] cycle {cycle} 结束 =====")
                self._emit(EventType.CYCLE_FINISHED, cycle=cycle, status=cycle_status)

                self.cancellation_token.raise_if_cancelled()
                if not loop.enable:
                    break
                if loop.count is not None and cycle >= int(loop.count):
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                if loop.count is None and loop.duration is None:
                    logger.info(f"loop 无限循环，cycle {cycle} 完成，继续...（STOP/Ctrl+C 中断）")
        except KeyboardInterrupt as exc:
            self.cancellation_token.cancel("keyboard interrupt")
            raise OperationCancelled("keyboard interrupt") from exc
        return self.results

    def _run_tasks(self, cycle: int) -> None:
        from ..modules.base import get_module_cls

        self.module_status = {}
        for task in self.scenario.tasks:
            self.cancellation_token.raise_if_cancelled()
            cls = get_module_cls(task.module)
            if cls is None:
                self._record(TestResult(
                    name=task.module,
                    module=task.module,
                    status=ERROR,
                    message="模块未注册",
                ), cycle)
                self.module_status[task.module] = ERROR
                continue

            deps = getattr(cls, "depends", []) or []
            blocked = [dep for dep in deps if self.module_status.get(dep) in (FAILED, ERROR)]
            if blocked:
                self._record(TestResult(
                    name=task.module,
                    module=task.module,
                    status=SKIPPED,
                    message=f"依赖模块未通过: {blocked}",
                ), cycle)
                self.module_status[task.module] = SKIPPED
                continue

            module_defaults = load_module_config(task.module, self.config_dir)
            params = dict(task.override or {})
            duration_key = getattr(cls, "duration_key", None)
            if task.duration is not None and duration_key:
                params[duration_key] = task.duration

            repeat_total = max(1, int(task.repeat or 1))
            for rep_index in range(repeat_total):
                self.cancellation_token.raise_if_cancelled()
                self._emit(
                    EventType.TASK_STARTED,
                    cycle=cycle,
                    module=task.module,
                    repeat=rep_index + 1,
                    repeat_total=repeat_total,
                )
                task_status = ERROR
                try:
                    self._run_module(
                        task.module,
                        cls,
                        module_defaults,
                        params,
                        cycle,
                        rep_index,
                        repeat_total,
                    )
                    task_status = self.module_status.get(task.module, ERROR)
                except OperationCancelled:
                    task_status = CANCELLED
                    self.module_status[task.module] = CANCELLED
                    raise
                finally:
                    self._emit(
                        EventType.TASK_FINISHED,
                        cycle=cycle,
                        module=task.module,
                        repeat=rep_index + 1,
                        repeat_total=repeat_total,
                        status=task_status,
                    )

    def _run_module(self, name, cls, config, params, cycle, rep_index, repeat_total) -> None:
        label = name if repeat_total <= 1 else f"{name}[{rep_index + 1}/{repeat_total}]"
        mod_start = time.monotonic()
        logger.step(f">>> 模块 [{label}] 开始执行 (cycle {cycle})")
        module = cls(config)
        result = None
        setup_ok = False
        cancelled = False
        try:
            self.cancellation_token.raise_if_cancelled()
            try:
                module.setup(self.ctx, self.console)
                setup_ok = True
            except OperationCancelled:
                cancelled = True
                self.module_status[name] = CANCELLED
                raise
            except Exception as exc:
                logger.error(f"[{label}] setup 异常: {exc}")
                self._record(TestResult(
                    name=name,
                    module=name,
                    status=ERROR,
                    message=f"setup 异常: {exc}",
                ), cycle)
                self.module_status[name] = ERROR
                return

            last_err = None
            for attempt in range(1, self.retry + 1):
                self.cancellation_token.raise_if_cancelled()
                try:
                    logger.step(
                        f"    - 执行模块: {label}"
                        + (f" (尝试 {attempt})" if attempt > 1 else "")
                    )
                    result = module.run(self.ctx, self.console, params=params)
                    if self._overall_pass(result):
                        break
                except OperationCancelled:
                    cancelled = True
                    self.module_status[name] = CANCELLED
                    raise
                except Exception as exc:
                    last_err = exc
                    logger.warn(f"[{label}] 第 {attempt} 次执行异常: {exc}")
                    result = TestResult(
                        name=name,
                        module=name,
                        status=ERROR,
                        message=f"执行异常: {exc}",
                    )
                if attempt < self.retry:
                    logger.info(f"[{label}] 失败，重试中...")

            self._record_results(name, result, last_err, cycle)
            if isinstance(result, list):
                # Preserve baseline behavior: any PASS/SKIP makes the module non-blocking.
                status = PASSED if any(
                    item.status in (PASSED, SKIPPED) for item in result
                ) else FAILED
            elif result is not None:
                status = result.status
            else:
                status = FAILED
            self.module_status[name] = status
        finally:
            try:
                module.teardown(self.ctx, self.console)
            except Exception as exc:
                logger.warn(f"[{label}] teardown 异常: {exc}")
            elapsed = time.monotonic() - mod_start
            status = CANCELLED if cancelled else self.module_status.get(name, "?")
            logger.step(f"<<< 模块 [{label}] 结束，耗时 {elapsed:.1f}s（结果 {status}）")

    def _record_results(self, name, result, last_err, cycle) -> None:
        if result is None:
            self._record(TestResult(
                name=name,
                module=name,
                status=FAILED,
                message="模块未返回结果",
            ), cycle)
            return
        if isinstance(result, list):
            for item in result:
                self._record(item, cycle)
        else:
            self._record(result, cycle)

    def _record(self, result: TestResult, cycle: int = 0) -> None:
        result.timestamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not result.scenario:
            result.scenario = self.scenario.name
        if not result.cycle:
            result.cycle = cycle
        self.results.append(result)
        logger.result_line(result.status, result.name, result.elapsed_ms, result.message)
        self._emit(
            EventType.RESULT_PRODUCED,
            cycle=result.cycle,
            module=result.module,
            status=result.status,
            message=result.message,
            result=result,
        )
        for artifact in getattr(result, "artifacts", []):
            self._emit(
                EventType.ARTIFACT_PRODUCED,
                cycle=result.cycle,
                module=result.module,
                status=result.status,
                message=getattr(artifact, "label", ""),
                data=artifact.to_dict() if hasattr(artifact, "to_dict") else dict(artifact),
            )

    def _emit(self, event_type: EventType, **kwargs) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink.emit(Event(
                type=event_type,
                run_id=self.run_id,
                scenario=self.scenario.name,
                **kwargs,
            ))
        except Exception:
            pass

    @staticmethod
    def _overall_pass(result) -> bool:
        if result is None:
            return False
        if isinstance(result, list):
            return bool(result) and any(
                item.status in (PASSED, SKIPPED) for item in result
            )
        return result.status in (PASSED, SKIPPED)
