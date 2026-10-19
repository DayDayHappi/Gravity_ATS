"""BoardHealthMonitor 单元测试（ADR-016，NEW-P1-02 固化）。

用标准库 unittest（工程无 pytest 依赖），``python3 -m unittest`` 即可运行。

覆盖：watchdog 超时推进、RX 不误判、confirm_health 确认流程、参数 fail-closed、
stop 后 watchdog 不再推进。
"""
import time
import unittest

from ATS.application import runtime_control
from ATS.application.board_health_monitor import (
    BoardHealthMonitor, HEALTHY, SUSPECTED, UNRESPONSIVE,
)


class _GoodConsole:
    def health_check(self):
        return True


class _BadConsole:
    def health_check(self):
        return False


def _fast_cfg(**kw):
    base = {"check_interval": 0.02, "inactivity_timeout": 0.05,
            "confirm_failures": 3, "confirm_interval": 0.0}
    base.update(kw)
    return base


class BoardHealthMonitorTest(unittest.TestCase):

    def test_watchdog_timeout_enters_suspected(self):
        m = BoardHealthMonitor(_fast_cfg())
        m.start()
        try:
            time.sleep(0.15)   # 超过 inactivity_timeout
            self.assertEqual(m.current_state(), SUSPECTED)
            self.assertTrue(runtime_control.is_recovery_requested())
        finally:
            m.stop()

    def test_rx_keeps_healthy(self):
        m = BoardHealthMonitor(_fast_cfg(inactivity_timeout=0.1))
        m.start()
        try:
            for _ in range(5):
                m.on_rx("some serial data\n")
                time.sleep(0.03)
            self.assertEqual(m.current_state(), HEALTHY)
        finally:
            m.stop()

    def test_confirm_health_first_success_returns_healthy(self):
        m = BoardHealthMonitor(_fast_cfg(confirm_failures=3))
        m.start()
        try:
            m._state = SUSPECTED
            self.assertEqual(m.confirm_health(_GoodConsole()), HEALTHY)
        finally:
            m.stop()

    def test_confirm_health_nth_success_returns_healthy(self):
        class _FlakyConsole:
            def __init__(self):
                self.calls = 0
            def health_check(self):
                self.calls += 1
                return self.calls >= 2
        c = _FlakyConsole()
        m = BoardHealthMonitor(_fast_cfg(confirm_failures=3))
        m.start()
        try:
            m._state = SUSPECTED
            self.assertEqual(m.confirm_health(c), HEALTHY)
            self.assertEqual(c.calls, 2)
        finally:
            m.stop()

    def test_confirm_health_all_fail_returns_unresponsive(self):
        m = BoardHealthMonitor(_fast_cfg(confirm_failures=3))
        m.start()
        try:
            m._state = SUSPECTED
            self.assertEqual(m.confirm_health(_BadConsole()), UNRESPONSIVE)
            self.assertEqual(m.current_state(), UNRESPONSIVE)
        finally:
            m.stop()

    def test_invalid_params_fail_closed(self):
        for bad in ({"check_interval": 0}, {"inactivity_timeout": -1},
                    {"confirm_failures": 0}, {"confirm_interval": -1}):
            with self.assertRaises(ValueError):
                BoardHealthMonitor(bad)

    def test_stop_halts_watchdog(self):
        m = BoardHealthMonitor(_fast_cfg(inactivity_timeout=0.05))
        m.start()
        m.stop()
        time.sleep(0.1)
        # stop 后 watchdog 不再推进（仍是 HEALTHY，不会变 SUSPECTED）
        self.assertEqual(m.current_state(), HEALTHY)


if __name__ == "__main__":
    unittest.main()
