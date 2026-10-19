"""Runner 恢复流程单元测试（ADR-016，NEW-P1-02 固化，unittest 风格）。

覆盖：monitor-only UNRESPONSIVE、recovery failure → board_recovery ERROR、
retry 二次 Outcome、未知 action fail-closed。
"""
import unittest

import ATS.core.runner as rmod
from ATS.application.board_health_monitor import UNRESPONSIVE
from ATS.application.recovery_coordinator import RecoveryOutcome
from ATS.core.context import Context
from ATS.core.runner import ScenarioAbort, TestRunner
from ATS.core.scenario import LoopConfig, Scenario, Task
from ATS.modules.base import TestModule, register

rmod.load_module_config = lambda name: {}


def _make_scenario(module_name, loop_count=5, loop_enable=True):
    return Scenario(
        name="t",
        tasks=[Task(module=module_name, repeat=1)],
        loop=LoopConfig(enable=loop_enable, count=loop_count),
    )


def _register_mock(name):
    @register(name)
    class _Mock(TestModule):
        depends = []
        def run(self, ctx, console, params=None):
            return self._pass("ok")
    return _Mock


class _UnrespMonitor:
    confirm_failures = 3
    def current_state(self):
        return UNRESPONSIVE
    def get_status(self):
        return {"reason": "test hang"}
    def confirm_health(self, console):
        return UNRESPONSIVE


class RecoveryRunnerTest(unittest.TestCase):

    def test_monitor_only_unresponsive_aborts(self):
        _register_mock("_r1")
        sc = _make_scenario("_r1")
        ctx = Context()
        ctx.system_config = {"runner": {}}
        ctx.console = None
        ctx.board_health_monitor = _UnrespMonitor()
        ctx.recovery_coordinator = None
        runner = TestRunner({"runner": {}}, ctx, sc)
        runner.retry = 1
        try:
            runner.run()
        except ScenarioAbort:
            pass
        self.assertTrue(any(r.name == "board_health" and r.status == "FAIL"
                            for r in runner.results))

    def test_recovery_failure_records_board_recovery_error(self):
        _register_mock("_r2")
        sc = _make_scenario("_r2", loop_enable=False)
        ctx = Context()
        ctx.system_config = {"runner": {}}
        ctx.console = None
        orig = rmod.TestRunner._run_module
        def fake(self, name, cls, config, params, cycle, rep, repeat_total):
            return RecoveryOutcome("abort_scenario", False, backend="power_cycle",
                                   attempts=2, message="restore failed at board_ready")
        rmod.TestRunner._run_module = fake
        try:
            runner = TestRunner({"runner": {}}, ctx, sc)
            runner.run()
            self.assertTrue(any(r.name == "board_recovery" and r.status == "ERROR"
                                for r in runner.results))
        finally:
            rmod.TestRunner._run_module = orig

    def test_retry_second_outcome_abort_handled(self):
        _register_mock("_r3")
        sc = _make_scenario("_r3", loop_enable=False)
        ctx = Context()
        ctx.system_config = {"runner": {}}
        ctx.console = None
        calls = {"n": 0}
        orig = rmod.TestRunner._run_module
        def fake(self, name, cls, config, params, cycle, rep, repeat_total):
            calls["n"] += 1
            if calls["n"] == 1:
                return RecoveryOutcome("retry_current_task", True)
            return RecoveryOutcome("abort_scenario", False)
        rmod.TestRunner._run_module = fake
        try:
            runner = TestRunner({"runner": {}}, ctx, sc)
            runner.run()
            self.assertEqual(calls["n"], 2)
        finally:
            rmod.TestRunner._run_module = orig

    def test_unknown_action_fail_closed(self):
        _register_mock("_r4")
        sc = _make_scenario("_r4", loop_enable=False)
        ctx = Context()
        ctx.system_config = {"runner": {}}
        ctx.console = None
        orig = rmod.TestRunner._run_module
        def fake(self, name, cls, config, params, cycle, rep, repeat_total):
            return RecoveryOutcome("bogus_action", False)
        rmod.TestRunner._run_module = fake
        try:
            runner = TestRunner({"runner": {}}, ctx, sc)
            runner.run()
            self.assertTrue(any(r.name == "board_recovery" and r.status == "ERROR"
                                for r in runner.results))
        finally:
            rmod.TestRunner._run_module = orig


if __name__ == "__main__":
    unittest.main()
