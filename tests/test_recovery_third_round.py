"""第三轮验收修复单元测试（ADR-016 NEW-P0-03/04 + NEW-P1-03）。

覆盖：
- NEW-P0-03：Runner 正确支持 after_recovery=continue 语义。
- NEW-P0-04：PowerSwitch.reboot_checked 严格校验 OFF/ON 回帧。
- NEW-P1-03：ScenarioManager.validate_scenario 供 dry-run 复用的公开入口。
"""
import types
import unittest

import ATS.core.runner as rmod
import ATS.drivers.power_switch as ps_mod
from ATS.application.recovery_coordinator import RecoveryOutcome
from ATS.core.context import Context
from ATS.core.runner import TestRunner
from ATS.core.scenario import LoopConfig, Scenario, Task
from ATS.core.scenario_manager import ScenarioError, ScenarioManager
from ATS.drivers import power_commands as pc
from ATS.modules.base import TestModule, register

rmod.load_module_config = lambda name: {}


class _FakeSerial:
    def __init__(self, **kw):
        self.timeout = 0.5
        self.is_open = True
        self.queue = []
    def reset_input_buffer(self):
        pass
    def write(self, b):
        pass
    def flush(self):
        pass
    def read(self, n):
        if self.queue:
            return self.queue.pop(0)
        return b""
    def close(self):
        pass


def _mk_power_switch():
    ps = ps_mod.PowerSwitch("/dev/ttyUSB1", 115200, reboot_delay=0.01)
    ps._ser = _FakeSerial()
    return ps


class RebootCheckedTest(unittest.TestCase):

    def test_off_on_legal_succeeds(self):
        ps = _mk_power_switch()
        ps._ser.queue = [pc.POWER_STATE_OFF, pc.POWER_STATE_ON]
        ps.reboot_checked()   # 不抛即通过

    def test_off_empty_raises(self):
        ps = _mk_power_switch()
        ps._ser.queue = [b"", b""]
        with self.assertRaises(ps_mod.PowerSwitchError):
            ps.reboot_checked()

    def test_on_empty_raises(self):
        ps = _mk_power_switch()
        ps._ser.queue = [pc.POWER_STATE_OFF, b"", b""]
        with self.assertRaises(ps_mod.PowerSwitchError):
            ps.reboot_checked()

    def test_on_invalid_frame_raises(self):
        ps = _mk_power_switch()
        ps._ser.queue = [pc.POWER_STATE_OFF, bytes([0x00, 0x00, 0x00, 0x00])]
        with self.assertRaises(ps_mod.PowerSwitchError):
            ps.reboot_checked()


class ContinueActionTest(unittest.TestCase):

    def test_continue_does_not_abort(self):
        @register("_c1")
        class _M1(TestModule):
            depends = []
            def run(self, ctx, console, params=None):
                return self._pass("ok")
        @register("_c2")
        class _M2(TestModule):
            depends = []
            def run(self, ctx, console, params=None):
                return self._pass("ok")

        sc = Scenario(name="t", tasks=[Task(module="_c1"), Task(module="_c2")],
                      loop=LoopConfig(enable=False))
        ctx = Context()
        ctx.system_config = {"runner": {}}
        calls = {"n": 0}
        orig = rmod.TestRunner._run_module
        def fake(self, name, cls, config, params, cycle, rep, repeat_total):
            calls["n"] += 1
            if calls["n"] == 1:
                return RecoveryOutcome("continue", True, backend="power_cycle", attempts=1)
            return None
        rmod.TestRunner._run_module = fake
        try:
            runner = TestRunner({"runner": {}}, ctx, sc)
            runner.run()
            self.assertFalse(any(r.name == "board_recovery" for r in runner.results))
            self.assertEqual(calls["n"], 2)
        finally:
            rmod.TestRunner._run_module = orig


class ValidateScenarioTest(unittest.TestCase):

    def test_public_validate_raises_on_bad_contract(self):
        mgr = ScenarioManager()
        bad = Scenario(name="bad", tasks=[Task(module="photo")], loop=LoopConfig(),
                       health_monitor={"enabled": True}, recovery={},
                       prepare=["serial_init"], cleanup=["close_serial"])
        with self.assertRaises(ScenarioError):
            mgr.validate_scenario(bad)

    def test_public_validate_passes_on_valid(self):
        mgr = ScenarioManager()
        sc = mgr.load("recovery_validation")
        mgr.validate_scenario(sc)   # 不抛即通过


if __name__ == "__main__":
    unittest.main()
