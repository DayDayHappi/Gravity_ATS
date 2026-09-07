from pathlib import Path


def test_test_and_h265_pages_refresh_controls_after_claiming_run():
    for path in (
        Path("ATS/gui/pages/scenario_page.py"),
        Path("ATS/gui/pages/h265_page.py"),
    ):
        text = path.read_text(encoding="utf-8")
        assignment = "self._owns_run = self.controller.start(request)"
        refresh = "self._set_running(self.controller.is_running)"
        assert assignment in text
        assert refresh in text
        assert text.index(refresh, text.index(assignment)) > text.index(assignment)


def test_window_refuses_close_while_worker_is_still_running():
    text = Path("ATS/gui/main_window.py").read_text(encoding="utf-8")
    assert "if not self.controller.shutdown" in text
    assert "event.ignore()" in text


def test_controller_shutdown_is_cooperative_and_reports_success():
    text = Path("ATS/gui/run_worker.py").read_text(encoding="utf-8")
    assert "def shutdown(self, timeout_ms: int = 10000) -> bool:" in text
    assert ".terminate(" not in text
    assert "return bool(thread.wait" in text or "return not thread.isRunning()" in text
    assert "worker.completed.connect(worker.deleteLater)" in text
    assert "worker.crashed.connect(worker.deleteLater)" in text
