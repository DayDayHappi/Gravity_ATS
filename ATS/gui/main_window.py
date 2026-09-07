"""Gravity ATS engineering desktop main window."""
from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ATS.gui.interaction import QtInteractionProvider
from ATS.gui.pages.environment_page import EnvironmentPage
from ATS.gui.pages.h265_page import H265Page
from ATS.gui.pages.report_page import ReportPage
from ATS.gui.pages.serial_terminal_page import SerialTerminalPage
from ATS.gui.pages.scenario_page import TestPage
from ATS.gui.run_worker import RunController


class MainWindow(QMainWindow):
    """Compose presentation pages around one shared TestService controller."""

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Gravity ATS")
        self.resize(1280, 820)
        self.interaction_provider = QtInteractionProvider(self)
        if hasattr(service, "interaction_provider"):
            service.interaction_provider = self.interaction_provider
        self.controller = RunController(service, self)
        self.tabs = QTabWidget(self)
        self.setCentralWidget(self.tabs)
        self.test_page = TestPage(service, self.controller, self)
        self.environment_page = EnvironmentPage(service, self)
        self.serial_terminal_page = SerialTerminalPage(service, self)
        self.h265_page = H265Page(service, self.controller, self)
        self.report_page = ReportPage(service, self)
        self.tabs.addTab(self.test_page, "测试")
        self.tabs.addTab(self.environment_page, "环境")
        self.tabs.addTab(self.serial_terminal_page, "串口终端")
        self.tabs.addTab(self.h265_page, "H265 完整性")
        self.tabs.addTab(self.report_page, "报告")
        self.controller.running_changed.connect(self.serial_terminal_page.set_test_running)
        self.controller.run_finished.connect(self._on_run_finished)
        self.controller.error.connect(self._on_controller_error)
        self.test_page.run_result_available.connect(self.report_page.show_run_result)
        self.statusBar().showMessage("Ready")
        if self.environment_page.has_failures:
            self.tabs.setCurrentWidget(self.environment_page)
            self.statusBar().showMessage("Environment check has failures")

    @Slot(object)
    def _on_run_finished(self, result) -> None:
        status = getattr(result, "status", "")
        text = getattr(status, "value", str(status))
        self.statusBar().showMessage(f"Run finished: {text}")
        self.report_page.show_run_result(result)

    @Slot(str)
    def _on_controller_error(self, _detail: str) -> None:
        self.statusBar().showMessage("Run worker error")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.serial_terminal_page.close_session()
        if not self.controller.shutdown():
            self.statusBar().showMessage("Stopping active test; close again after cleanup finishes")
            event.ignore()
            return
        event.accept()
