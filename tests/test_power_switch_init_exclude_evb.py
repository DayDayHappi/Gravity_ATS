"""power_switch_init 排除 EVB 串口端口 + 冷启动先下电再上电（P0，2026-09-30）单元测试。"""
import types
import unittest

import ATS.core.scenario_manager as sm
import ATS.drivers.power_switch as ps
from ATS.core.context import Context
from ATS.core.scenario_manager import ScenarioError


class PowerSwitchInitExcludeEvbTest(unittest.TestCase):

    def setUp(self):
        self._orig_accessible = ps._accessible_ports
        self._orig_detect = ps.detect_power_switch

    def tearDown(self):
        ps._accessible_ports = self._orig_accessible
        ps.detect_power_switch = self._orig_detect

    def _patch(self, ports, detect_cb):
        ps._accessible_ports = lambda: list(ports)
        ps.detect_power_switch = detect_cb

    def test_excludes_console_port(self):
        captured = {}
        def fake_detect(candidate_ports=None, **kw):
            captured["candidates"] = candidate_ports
            return None
        self._patch(["/dev/ttyUSB2", "/dev/ttyUSB5"], fake_detect)

        class FakeConsole:
            port = "/dev/ttyUSB2"
        ctx = Context()
        ctx.console = FakeConsole()
        ctx.recovery = {}
        system_cfg = {"power_switch": {"enabled": True, "port": "auto"},
                      "serial": {"port": "auto"}}

        sm._action_power_switch_init(ctx, system_cfg)
        self.assertEqual(captured["candidates"], ["/dev/ttyUSB5"])

    def test_cold_boot_console_none_no_impact(self):
        captured = {}
        def fake_detect(candidate_ports=None, **kw):
            captured["candidates"] = candidate_ports
            return None
        self._patch(["/dev/ttyUSB1"], fake_detect)

        ctx = Context()
        ctx.console = None   # 冷启动
        ctx.recovery = {}
        sm._action_power_switch_init(ctx, {"power_switch": {"enabled": True, "port": "auto"},
                                           "serial": {"port": "auto"}})
        self.assertEqual(captured["candidates"], ["/dev/ttyUSB1"])

    def test_explicit_serial_port_excluded(self):
        detected = {}
        def fake_detect(candidate_ports=None, **kw):
            detected["called"] = True
            return None
        self._patch(["/dev/ttyUSB2"], fake_detect)

        ctx = Context()
        ctx.console = None
        ctx.recovery = {}
        sm._action_power_switch_init(ctx, {"power_switch": {"enabled": True, "port": "auto"},
                                           "serial": {"port": "/dev/ttyUSB2"}})
        self.assertFalse(detected.get("called", False))


class PowerSwitchInitColdBootRebootCheckedTest(unittest.TestCase):
    """冷启动语义：识别控制器后 reboot_checked（先下电再上电），而非 power_on。"""

    def setUp(self):
        self._orig_accessible = ps._accessible_ports
        self._orig_detect = ps.detect_power_switch

    def tearDown(self):
        ps._accessible_ports = self._orig_accessible
        ps.detect_power_switch = self._orig_detect

    def _patch(self, ports, detect_cb):
        ps._accessible_ports = lambda: list(ports)
        ps.detect_power_switch = detect_cb

    def test_cold_boot_uses_reboot_checked(self):
        calls = {"reboot_checked": 0, "power_on": 0, "delay": None}
        class FakePS:
            port = "/dev/ttyUSB1"
            def reboot_checked(self, delay=None):
                calls["reboot_checked"] += 1
                calls["delay"] = delay
            def power_on(self):
                calls["power_on"] += 1
        self._patch(["/dev/ttyUSB1"], lambda **kw: FakePS())

        ctx = Context()
        ctx.console = None
        ctx.recovery = {}
        sm._action_power_switch_init(ctx, {"power_switch": {"enabled": True, "port": "auto",
                                                            "reboot_delay": 3.0},
                                           "serial": {"port": "auto"}})
        self.assertEqual(calls["reboot_checked"], 1)
        self.assertEqual(calls["power_on"], 0)
        self.assertEqual(calls["delay"], 3.0)

    def test_required_fail_closed_on_reboot_error(self):
        class FakePS:
            port = "/dev/ttyUSB1"
            def reboot_checked(self, delay=None):
                raise ps.PowerSwitchError("下电回帧非法")
        self._patch(["/dev/ttyUSB1"], lambda **kw: FakePS())

        ctx = Context()
        ctx.console = None
        ctx.recovery = {"enabled": True, "backend": "power_cycle"}
        with self.assertRaises(ScenarioError):
            sm._action_power_switch_init(ctx, {"power_switch": {"enabled": True, "port": "auto"},
                                               "serial": {"port": "auto"}})

    def test_non_required_warns_and_continues(self):
        class FakePS:
            port = "/dev/ttyUSB1"
            def reboot_checked(self, delay=None):
                raise ps.PowerSwitchError("下电回帧非法")
        self._patch(["/dev/ttyUSB1"], lambda **kw: FakePS())

        ctx = Context()
        ctx.console = None
        ctx.recovery = {}
        sm._action_power_switch_init(ctx, {"power_switch": {"enabled": True, "port": "auto"},
                                           "serial": {"port": "auto"}})
        self.assertIsNotNone(ctx.power_switch)


if __name__ == "__main__":
    unittest.main()
