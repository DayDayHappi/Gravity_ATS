"""Unified Application service for CLI, GUI, and future APIs."""
from __future__ import annotations

import datetime as dt
import os
import uuid
import threading
from typing import Callable, Iterable, Optional

from .dependencies import find_missing_dependencies
from .events import EventBus
from .interaction import InteractionProvider, NonInteractiveInteractionProvider
from .models import RunRequest, RunResult, RunStatus, ScenarioDescriptor, TaskDescriptor
from ..core import logger
from ..core.config import CONFIG_DIR, ConfigError, apply_overrides, load_system
from ..core.events import Event, EventType
from ..core.cancellation import CancellationToken, OperationCancelled
from ..core.reporter import generate as generate_report
from ..core.scenario_manager import ScenarioError, ScenarioManager
from ..platform.resources import ResourceLocator
from ..platform.services import PlatformServices, create_platform_services


def resolve_output_roots(system_cfg: dict, scenario_name: str, output_dir: Optional[str] = None,
                         resource_locator: ResourceLocator = None):
    report_cfg = system_cfg.get("report", {}) or {}
    locator = resource_locator or ResourceLocator()
    log_base = str(locator.resolve_output_root(report_cfg.get("log_dir", "logs"), "logs"))
    report_value = output_dir if output_dir is not None else report_cfg.get("output_dir", "reports")
    report_base = str(locator.resolve_output_root(report_value, "reports"))
    date = dt.datetime.now().strftime("%Y%m%d")
    log_root = os.path.join(log_base, scenario_name, date)
    problem_root = os.path.join(log_base, scenario_name, "problem")
    if scenario_name != "normal" and output_dir is None:
        report_root = os.path.join(log_base, scenario_name, "report", date)
    else:
        report_root = os.path.join(report_base, date)
    return log_root, report_root, problem_root


class TestService:
    """Coordinate configuration, existing engine execution, events, and reports."""

    __test__ = False

    def __init__(
        self,
        *,
        interaction_provider: Optional[InteractionProvider] = None,
        event_bus: Optional[EventBus] = None,
        scenario_manager_factory=ScenarioManager,
        system_loader: Callable[[str], dict] = load_system,
        dependency_checker: Callable[[dict, object, str], Iterable[str]] = find_missing_dependencies,
        reporter: Callable = generate_report,
        resource_locator: ResourceLocator = None,
        platform_services: PlatformServices = None,
    ) -> None:
        self.interaction_provider = interaction_provider or NonInteractiveInteractionProvider()
        self.event_bus = event_bus or EventBus()
        self._manager_factory = scenario_manager_factory
        self._system_loader = system_loader
        self._dependency_checker = dependency_checker
        self.resource_locator = resource_locator or ResourceLocator()
        self.platform_services = platform_services or create_platform_services(self.resource_locator)
        self._reporter = reporter
        self._state_lock = threading.RLock()
        self._active_token = None

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._active_token is not None

    def cancel_current(self, reason: str = "operator stop") -> bool:
        with self._state_lock:
            token = self._active_token
        return token.cancel(reason) if token is not None else False

    def list_scenarios(self):
        from ..core.config import list_scenarios
        return list_scenarios(str(self.resource_locator.config_dir))

    def list_serial_ports(self):
        return self.platform_services.serial_ports.list_ports()

    def describe_scenario(self, name: str) -> ScenarioDescriptor:
        manager = self._manager_factory(
            config_dir=str(self.resource_locator.config_dir),
            interaction_provider=self.interaction_provider,
        )
        scenario = manager.load(name)
        return ScenarioDescriptor(
            name=scenario.name,
            prepare=tuple(scenario.prepare),
            tasks=tuple(TaskDescriptor(task.module, task.repeat, task.duration) for task in scenario.tasks),
            cleanup=tuple(scenario.cleanup),
            loop_enabled=bool(scenario.loop.enable),
            loop_count=scenario.loop.count,
            loop_duration=scenario.loop.duration,
        )

    def inspect_environment(self):
        from .environment import EnvironmentInspector
        return EnvironmentInspector(self.platform_services).inspect()

    def run(self, request: RunRequest, cancellation_token: CancellationToken = None) -> RunResult:
        started = dt.datetime.now()
        run_id = started.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        config_dir = str(self.resource_locator.resolve_config_dir(request.config_dir))
        final = RunResult(
            run_id=run_id,
            scenario=request.scenario,
            status=RunStatus.ERROR,
            started_at=started.isoformat(timespec="seconds"),
        )
        logger_started = False
        log_callback = None
        manager = None
        system_cfg = None
        report_root = ""
        problem_root = ""
        execution_started = False
        report_attempted = False
        token = cancellation_token or CancellationToken()
        with self._state_lock:
            if self._active_token is not None:
                final.error = "TestService already has an active run"
                self._emit(EventType.RUN_STARTED, final)
                self._emit(EventType.RUN_FAILED, final, message=final.error)
                self._emit(EventType.RUN_FINISHED, final)
                return final
            self._active_token = token
        self._emit(EventType.RUN_STARTED, final)
        try:
            token.raise_if_cancelled()
            system_cfg = apply_overrides(self._system_loader(config_dir), dict(request.system_overrides))
            log_root, report_root, problem_root = resolve_output_roots(
                system_cfg, request.scenario, request.output_dir, self.resource_locator
            )
            logger.init_logger(log_root, verbose=request.verbose, run_ts=run_id)
            logger_started = True
            final.log_dir = logger.log_dir()
            final.problem_root = problem_root

            def forward_log(level, message, _timestamp):
                self.event_bus.emit(Event(
                    type=EventType.LOG,
                    run_id=run_id,
                    scenario=request.scenario,
                    level=level,
                    message=message,
                ))

            log_callback = forward_log
            logger.add_listener(log_callback)
            logger.info(f"VX100 EVB 自动化测试启动，运行时间戳: {run_id}")
            logger.info(f"日志目录: {log_root}  报告目录: {report_root}")

            manager = self._manager_factory(
                config_dir=config_dir,
                interaction_provider=self.interaction_provider,
                event_sink=self.event_bus,
                run_id=run_id,
            )
            scenario = manager.load(request.scenario)
            final.scenario = scenario.name
            logger.info(f"场景 [{scenario.name}] 任务: {[t.module for t in scenario.tasks]}")

            try:
                missing = list(self._dependency_checker(
                    system_cfg, scenario, config_dir, self.resource_locator
                ))
            except TypeError:
                # Backward-compatible custom checkers used by tests/integrators.
                missing = list(self._dependency_checker(system_cfg, scenario, config_dir))
            if missing:
                final.error = "缺少依赖: " + "; ".join(missing)
                for item in missing:
                    logger.error(f"缺少依赖: {item}")
                self._emit(EventType.RUN_FAILED, final, message=final.error)
            elif request.dry_run:
                self._validate_registered_modules(scenario)
                logger.info("dry-run: 配置与依赖校验通过，不执行测试")
                final.status = RunStatus.DRY_RUN
            else:
                execution_started = True
                results = manager.run(
                    request.scenario,
                    no_interactive_wifi=request.no_interactive_wifi,
                    module_overrides=dict(request.module_overrides),
                    system_cfg=system_cfg,
                    cancellation_token=token,
                    platform_services=self.platform_services,
                )
                out_dir = os.path.join(report_root, run_id)
                report_cfg = system_cfg.get("report", {}) or {}
                final.results = list(results)
                report_attempted = True
                paths = self._reporter(
                    results,
                    out_dir,
                    junit=report_cfg.get("junit", True),
                    html=report_cfg.get("html", True),
                )
                final = RunResult.from_results(
                    run_id=run_id,
                    scenario=scenario.name,
                    results=results,
                    report_paths=paths,
                    log_dir=logger.log_dir(),
                    report_dir=out_dir,
                    problem_root=problem_root,
                    started_at=final.started_at,
                )
        except OperationCancelled as exc:
            partial = list(getattr(manager, "last_results", []) or [])
            final.status = RunStatus.CANCELLED
            final.error = str(exc)
            final.results = partial
            if logger_started and report_root:
                out_dir = os.path.join(report_root, run_id)
                report_cfg = (system_cfg or {}).get("report", {}) or {}
                try:
                    final.report_paths = self._reporter(
                        partial, out_dir,
                        junit=report_cfg.get("junit", True),
                        html=report_cfg.get("html", True),
                    )
                    final.report_dir = out_dir
                except Exception as report_exc:
                    logger.warn(f"取消后的部分报告生成失败: {report_exc}")
            if logger_started:
                logger.warn(f"测试已取消: {exc}")
        except (ConfigError, ScenarioError) as exc:
            final.error = str(exc)
            if execution_started:
                partial = list(getattr(manager, "last_results", []) or [])
                final.results = partial
                if logger_started and report_root and not report_attempted:
                    self._attach_reports(final, partial, report_root, run_id, system_cfg)
            if logger_started:
                logger.error(f"测试中止: {exc}")
            self._emit(EventType.RUN_FAILED, final, message=final.error)
        except Exception as exc:
            final.error = str(exc)
            if execution_started:
                partial = list(getattr(manager, "last_results", []) or final.results or [])
                final.results = partial
                if logger_started and report_root and not report_attempted:
                    self._attach_reports(final, partial, report_root, run_id, system_cfg)
            if logger_started:
                logger.error(f"测试执行异常: {exc}")
            self._emit(EventType.RUN_FAILED, final, message=final.error)
        finally:
            final.finished_at = dt.datetime.now().isoformat(timespec="seconds")
            self._emit(EventType.RUN_FINISHED, final)
            if log_callback is not None:
                logger.remove_listener(log_callback)
            if logger_started:
                logger.close()
            with self._state_lock:
                if self._active_token is token:
                    self._active_token = None
        return final


    def _attach_reports(self, final, results, report_root, run_id, system_cfg) -> None:
        """Attach best-effort partial reports after an execution-time failure."""
        out_dir = os.path.join(report_root, run_id)
        report_cfg = (system_cfg or {}).get("report", {}) or {}
        try:
            final.report_paths = self._reporter(
                list(results),
                out_dir,
                junit=report_cfg.get("junit", True),
                html=report_cfg.get("html", True),
            )
            final.report_dir = out_dir
        except Exception as report_exc:
            logger.warn(f"异常后的部分报告生成失败: {report_exc}")

    def _emit(self, event_type: EventType, run: RunResult, message: str = "") -> None:
        self.event_bus.emit(Event(
            type=event_type,
            run_id=run.run_id,
            scenario=run.scenario,
            status=run.status.value,
            message=message,
            data={"exit_code": run.exit_code},
        ))

    @staticmethod
    def _validate_registered_modules(scenario) -> None:
        import importlib

        importlib.import_module("ATS.modules")
        from ..modules.base import get_module_cls

        missing = [task.module for task in scenario.tasks if get_module_cls(task.module) is None]
        if missing:
            raise ScenarioError(f"未注册模块: {missing}")
