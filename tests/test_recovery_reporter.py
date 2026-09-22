"""Reporter 单元测试（ADR-016，NEW-P1-02 固化，unittest 风格）。"""
import json
import os
import tempfile
import unittest

from ATS.core.reporter import write_html, write_json
from ATS.core.result import TestResult


def _events():
    return [{
        "timestamp": "2026-09-22 10:00:00", "scenario": "stress", "cycle": 10,
        "task": "video", "rep": 1, "health_state": "UNRESPONSIVE",
        "reason": "hang", "backend": "power_cycle", "attempt": 1,
        "recovery_result": "ok", "restore_result": "ok",
    }]


class ReporterTest(unittest.TestCase):

    def test_json_contains_recovery_events(self):
        tmp = tempfile.mkdtemp()
        results = [TestResult(name="x", module="x", status="PASS")]
        p = write_json(results, tmp, _events())
        data = json.load(open(p, encoding="utf-8"))
        self.assertEqual(data["recovery_events"], _events())

    def test_html_shows_recovery_events(self):
        tmp = tempfile.mkdtemp()
        results = [TestResult(name="x", module="x", status="PASS")]
        p = write_html(results, tmp, _events())
        html = open(p, encoding="utf-8").read()
        self.assertIn("Recovery Events", html)
        self.assertIn("power_cycle", html)
        self.assertIn("UNRESPONSIVE", html)

    def test_html_no_recovery_block_when_empty(self):
        tmp = tempfile.mkdtemp()
        results = [TestResult(name="x", module="x", status="PASS")]
        p = write_html(results, tmp, [])
        html = open(p, encoding="utf-8").read()
        self.assertNotIn("Recovery Events", html)


if __name__ == "__main__":
    unittest.main()
