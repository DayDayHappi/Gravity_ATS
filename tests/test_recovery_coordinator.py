"""RecoveryCoordinator 单元测试（ADR-016，NEW-P1-02 固化，unittest 风格）。

覆盖：backend 不可用/未知、policy 字段 fail-closed、restore 未知 action、
recover 成功/异常、restore 失败、max_attempts 耗尽、Context 失效。
"""
import unittest

import ATS.core.scenario_manager  # noqa: F401  注册 prepare/cleanup 动作
from ATS.application.board_health_monitor import BoardHealthMonitor, UNRESPONSIVE
from ATS.application.recovery_backends.base import RecoveryBackendUnavailable
from ATS.application.recovery_coordinator import RecoveryCoordinator
from ATS.core.context import Context


class _FakePS:
    port = "/dev/ttyUSB1"
    def reboot(self):
        pass


class _GoodConsole:
    def wait_for_ready(self):
        return True
    def wait_for_ready_since(self, cursor):
        return True
    def health_check(self):
        return True
    def snapshot_rx_cursor(self):
        return 1


def _mk_ctx(power_switch=None, console=None):
    ctx = Context()
    ctx.scenario_name = "t"
    ctx.system_config = {}
    ctx.power_switch = power_switch
    ctx.console = console
    return ctx


def _mk_coord(ctx, **policy):
    base = {"enabled": True, "backend": "power_cycle", "max_attempts": 2,
            "after_recovery": "retry_current_task", "on_exhausted": "abort_scenario",
            "restore": ["board_ready"]}
    base.update(policy)
    monitor = BoardHealthMonitor({"inactivity_timeout": 999})
    return RecoveryCoordinator(policy=base, ctx=ctx, console=ctx.console, monitor=monitor)


class RecoveryCoordinatorTest(unittest.TestCase):

    def test_backend_unavailable_fail_closed(self):
        ctx = _mk_ctx(power_switch=None)
        coord = _mk_coord(ctx)
        with self.assertRaises(RecoveryBackendUnavailable):
            coord.validate()

    def test_unknown_backend_fail_closed(self):
        ctx = _mk_ctx(power_switch=_FakePS())
        coord = _mk_coord(ctx, backend="nonexistent")
        with self.assertRaises(RecoveryBackendUnavailable):
            coord.validate()

    def test_invalid_policy_fail_closed(self):
        # max_attempts 必须 >=1 的整数；after_recovery/on_exhausted 必须是已支持枚举
        for bad in ({"max_attempts": 0}, {"max_attempts": -1},
                    {"after_recovery": "retry_task"},
                    {"on_exhausted": "abort_scenaro"}):
            ctx = _mk_ctx(power_switch=_FakePS())
            coord = _mk_coord(ctx, **bad)
            with self.assertRaises(ValueError):
                coord.validate()

    def test_unknown_restore_action_fail_closed(self):
        ctx = _mk_ctx(power_switch=_FakePS())
        coord = _mk_coord(ctx, restore=["wifi_conect"])
        with self.assertRaises(ValueError):
            coord.validate()

    def test_recover_success_retry_current_task(self):
        ctx = _mk_ctx(power_switch=_FakePS(), console=_GoodConsole())
        coord = _mk_coord(ctx)
        coord.validate()
        out = coord.handle_unresponsive(1, "video", 1, UNRESPONSIVE, "hang")
        self.assertTrue(out.success)
        self.assertEqual(out.action, "retry_current_task")
        self.assertEqual(len(ctx.recovery_history), 1)
        self.assertEqual(ctx.recovery_history[0]["recovery_result"], "ok")

    def test_recover_exception_returns_abort(self):
        class _BoomPS:
            port = "/dev/ttyUSB1"
            def reboot(self):
                raise RuntimeError("reboot failed")
        ctx = _mk_ctx(power_switch=_BoomPS(), console=_GoodConsole())
        coord = _mk_coord(ctx)
        coord.validate()
        out = coord.handle_unresponsive(1, "video", 1, UNRESPONSIVE, "hang")
        self.assertFalse(out.success)
        self.assertEqual(out.action, "abort_scenario")
        self.assertTrue(ctx.recovery_history[0]["recovery_result"].startswith("failed"))

    def test_restore_failure_returns_abort(self):
        class _BadReadyConsole(_GoodConsole):
            def wait_for_ready_since(self, cursor):
                raise RuntimeError("no ready")
            def wait_for_ready(self):
                raise RuntimeError("no ready")
        ctx = _mk_ctx(power_switch=_FakePS(), console=_BadReadyConsole())
        coord = _mk_coord(ctx, restore=["board_ready"])
        coord.validate()
        out = coord.handle_unresponsive(1, "video", 1, UNRESPONSIVE, "hang")
        self.assertFalse(out.success)
        self.assertEqual(out.action, "abort_scenario")
        self.assertTrue(ctx.recovery_history[0]["restore_result"].startswith("restore failed"))

    def test_exhausted_aborts(self):
        ctx = _mk_ctx(power_switch=_FakePS(), console=_GoodConsole())
        coord = _mk_coord(ctx, max_attempts=1)
        coord.validate()
        coord.handle_unresponsive(1, "video", 1, UNRESPONSIVE, "hang")
        out = coord.handle_unresponsive(2, "photo", 1, UNRESPONSIVE, "hang")
        self.assertEqual(out.action, "abort_scenario")
        self.assertFalse(out.success)
        self.assertEqual(ctx.recovery_history[-1]["recovery_result"], "exhausted")

    def test_context_invalidation(self):
        ctx = _mk_ctx(power_switch=_FakePS(), console=_GoodConsole())
        ctx.ftp_server_started = True
        ctx.ftp_client = object()
        ctx.evb_ip = "1.1.1.1"
        ctx.wifi_ready = True
        ctx.skip_wifi = True
        coord = _mk_coord(ctx)
        coord.validate()
        coord.handle_unresponsive(1, "photo", 1, UNRESPONSIVE, "hang")
        self.assertIsNone(ctx.ftp_server_started)
        self.assertIsNone(ctx.ftp_client)
        self.assertIsNone(ctx.evb_ip)
        self.assertIsNone(ctx.wifi_ready)
        self.assertIsNone(ctx.skip_wifi)
        self.assertEqual(ctx.system_config, {})
        self.assertIsNotNone(ctx.power_switch)


if __name__ == "__main__":
    unittest.main()
