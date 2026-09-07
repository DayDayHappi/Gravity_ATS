import pytest

pytest.importorskip("PySide6")
from ATS.gui.main_window import MainWindow


class Port:
    device = "COM10"
    display_name = "COM10 — USB Serial"


class Description:
    name = "normal"
    tasks = []


class Services:
    class Registry:
        pass
    serial_registry = Registry()


class Service:
    platform_services = Services()
    resource_locator = type("R", (), {"app_root": __import__("pathlib").Path.cwd(), "user_data_root": __import__("pathlib").Path.cwd()})()
    is_running = False

    def list_scenarios(self):
        return ["normal", "video_integrity"]

    def list_serial_ports(self):
        return [Port()]

    def describe_scenario(self, name):
        return Description()

    def inspect_environment(self):
        return []

    def cancel_current(self, reason="stop"):
        return False


def test_main_window_exposes_engineering_pages(qtbot):
    window = MainWindow(Service())
    qtbot.addWidget(window)
    names = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert names == ["测试", "环境", "串口终端", "H265 完整性", "报告"]
    assert window.test_page.start_button.isEnabled()
    assert window.test_page.port_combo.itemData(1) == "COM10"


class BlockingService(Service):
    def __init__(self):
        import threading
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.is_running = False

    def run(self, request, cancellation_token=None):
        from ATS.application.models import RunResult, RunStatus
        self.is_running = True
        self.started.set()
        if cancellation_token is not None:
            while not cancellation_token.wait(0.01):
                pass
        else:
            self.cancelled.wait(2)
        self.is_running = False
        return RunResult(run_id="qt", scenario=request.scenario, status=RunStatus.CANCELLED)

    def cancel_current(self, reason="stop"):
        self.cancelled.set()
        return True


def test_test_page_enables_stop_after_start_claims_shared_controller(qtbot):
    service = BlockingService()
    window = MainWindow(service)
    qtbot.addWidget(window)

    window.test_page.start_button.click()

    qtbot.waitUntil(service.started.is_set, timeout=3000)
    assert window.test_page.stop_button.isEnabled()
    assert not window.test_page.start_button.isEnabled()
    window.test_page.stop_button.click()
    qtbot.waitUntil(lambda: not window.controller.is_running, timeout=3000)


def test_h265_page_enables_stop_after_start_claims_shared_controller(qtbot, tmp_path):
    service = BlockingService()
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.h265_page.directory.setText(str(tmp_path))

    window.h265_page.start_button.click()

    qtbot.waitUntil(service.started.is_set, timeout=3000)
    assert window.h265_page.stop_button.isEnabled()
    assert not window.h265_page.start_button.isEnabled()
    window.h265_page.stop_button.click()
    qtbot.waitUntil(lambda: not window.controller.is_running, timeout=3000)


def test_h265_decode_primary_verdict_control_is_fixed_enabled(qtbot):
    window = MainWindow(Service())
    qtbot.addWidget(window)
    assert window.h265_page.decode.isChecked()
    assert not window.h265_page.decode.isEnabled()
    assert "主判据" in window.h265_page.decode.toolTip()


def test_h265_page_exposes_explicit_file_selection(qtbot):
    window = MainWindow(Service())
    qtbot.addWidget(window)
    assert window.h265_page.selection.findData("explicit") >= 0
    assert window.h265_page.files_button.text() == "选择文件"
