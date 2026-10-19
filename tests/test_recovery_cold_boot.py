"""第四轮（冷启动/串口生命周期）修复单元测试（ADR-016 NEW-P0-05/06）。

覆盖：
- TC-BOOT-001 冷启动顺序（power_switch_init < serial_init < health_monitor_start）。
- TC-BOOT-002 power_switch.enabled=false 且 recovery=power_cycle → validate 失败。
- TC-RCV-SER-002 SerialConsole.reconnect 保持对象身份 + listener + buffer seq 单调。
- TC-RCV-SER-006 restore 顺序（serial_reconnect < board_ready）。
"""
import types
import unittest

import ATS.core.serial_console as sc_mod
from ATS.application.board_health_monitor import BoardHealthMonitor
from ATS.application.recovery_coordinator import RecoveryCoordinator
from ATS.core.context import Context
from ATS.core.scenario import LoopConfig, Scenario, Task
from ATS.core.scenario_manager import ScenarioError, ScenarioManager
from ATS.core.serial_console import SerialConsole


class _FakeSerialPort:
    def __init__(self, port, baud, **kw):
        self.port = port
        self.is_open = True
    def reset_input_buffer(self):
        pass
    def reset_output_buffer(self):
        pass
    def read(self, n):
        return b""
    def close(self):
        self.is_open = False


class _FakePS:
    port = "/dev/ttyUSB1"
    def reboot_checked(self):
        pass


def _mk_scenario(prepare, cleanup=None, hm=True, rc=True):
    return Scenario(
        name="t", tasks=[Task(module="photo")], loop=LoopConfig(),
        health_monitor={"enabled": hm},
        recovery={"enabled": rc, "backend": "power_cycle", "max_attempts": 2,
                  "after_recovery": "retry_current_task", "on_exhausted": "abort_scenario",
                  "restore": ["serial_reconnect", "board_ready"]},
        prepare=prepare, cleanup=cleanup or ["health_monitor_stop", "close_serial"],
    )


class ColdBootContractTest(unittest.TestCase):

    def test_correct_order_passes(self):
        mgr = ScenarioManager()
        sc = _mk_scenario(["power_switch_init", "serial_init", "health_monitor_start"])
        mgr.validate_scenario(sc, {"power_switch": {"enabled": True}})   # 不抛

    def test_power_switch_after_serial_init_fails(self):
        mgr = ScenarioManager()
        sc = _mk_scenario(["serial_init", "power_switch_init", "health_monitor_start"])
        with self.assertRaises(ScenarioError):
            mgr.validate_scenario(sc, {"power_switch": {"enabled": True}})

    def test_power_switch_disabled_fails(self):
        mgr = ScenarioManager()
        sc = _mk_scenario(["power_switch_init", "serial_init", "health_monitor_start"])
        with self.assertRaises(ScenarioError):
            mgr.validate_scenario(sc, {"power_switch": {"enabled": False}})


class RestoreOrderTest(unittest.TestCase):

    def test_serial_reconnect_before_board_ready(self):
        ctx = Context()
        ctx.system_config = {}
        ctx.power_switch = _FakePS()
        ctx.scenario_name = "t"
        mon = BoardHealthMonitor({"inactivity_timeout": 999})
        coord = RecoveryCoordinator(
            policy={"enabled": True, "backend": "power_cycle", "max_attempts": 2,
                    "after_recovery": "retry_current_task",
                    "on_exhausted": "abort_scenario",
                    "restore": ["serial_reconnect", "board_ready"]},
            ctx=ctx, console=None, monitor=mon)
        coord.validate()   # 不抛

    def test_reversed_order_fails(self):
        ctx = Context()
        ctx.system_config = {}
        ctx.power_switch = _FakePS()
        ctx.scenario_name = "t"
        mon = BoardHealthMonitor({"inactivity_timeout": 999})
        coord = RecoveryCoordinator(
            policy={"enabled": True, "backend": "power_cycle", "max_attempts": 2,
                    "after_recovery": "retry_current_task",
                    "on_exhausted": "abort_scenario",
                    "restore": ["board_ready", "serial_reconnect"]},
            ctx=ctx, console=None, monitor=mon)
        with self.assertRaises(ValueError):
            coord.validate()


class SerialReconnectTest(unittest.TestCase):

    def setUp(self):
        fake = types.ModuleType("serial")
        fake.Serial = _FakeSerialPort
        self._orig_serial = sc_mod.serial
        sc_mod.serial = fake

    def tearDown(self):
        sc_mod.serial = self._orig_serial

    def test_reconnect_preserves_identity_listeners_seq(self):
        c = SerialConsole("/dev/ttyUSB0", 2000000)
        c.open()
        cid = id(c)
        seq_before = c._buffer_seq
        c.add_listener(lambda t: None)
        n_listeners = len(c._listeners)

        c.reconnect("/dev/ttyUSB1", 2000000)

        self.assertEqual(id(c), cid)          # 对象身份不变
        self.assertEqual(c.port, "/dev/ttyUSB1")
        self.assertTrue(c._ser is not None and c._ser.is_open)
        self.assertGreaterEqual(c._buffer_seq, seq_before)  # seq 单调
        self.assertEqual(len(c._listeners), n_listeners)    # listener 不清空
        c.close()


class SerialReconnectActionBug006Test(unittest.TestCase):
    """BUG-006：serial_reconnect 探测前必须 close 旧句柄，原端口未消失时直接重连。"""

    def test_old_port_still_present_reconnects_without_detect(self):
        import ATS.core.scenario_manager as sm
        from ATS.core.context import Context

        # fake console：记录 close/reconnect 调用，port=/dev/ttyUSB2
        class FakeConsole:
            def __init__(self):
                self.port = "/dev/ttyUSB2"
                self.closed = False
                self.reconnected_port = None
            def close(self):
                self.closed = True
            def reconnect(self, port=None, baudrate=None):
                self.reconnected_port = port
                self.port = port

        # fake _list_candidate_ports：原端口仍在
        orig_list = sm._list_candidate_ports if hasattr(sm, "_list_candidate_ports") else None
        import ATS.core.serial_console as sc
        orig_sc_list = sc._list_candidate_ports
        sc._list_candidate_ports = lambda: ["/dev/ttyUSB2"]

        ctx = Context()
        ctx.console = FakeConsole()
        ctx.power_switch = None
        system_cfg = {"serial": {"port": "auto", "baudrate": 2000000}}

        try:
            sm._action_serial_reconnect(ctx, system_cfg)
            self.assertTrue(ctx.console.closed, "必须先 close 旧句柄")
            self.assertEqual(ctx.console.reconnected_port, "/dev/ttyUSB2",
                             "原端口未消失时直接 reconnect 原端口")
        finally:
            sc._list_candidate_ports = orig_sc_list


if __name__ == "__main__":
    unittest.main()
