"""Primary scenario execution page."""
from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ATS.application.models import RunRequest
from ATS.core.events import Event, EventType
from ATS.gui.state import GuiRunState
from ATS.gui.widgets.log_view import BoundedLogView


class TestPage(QWidget):
    """Run existing YAML scenarios through TestService in a worker thread."""

    run_result_available = Signal(object)

    def __init__(self, service, controller, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.controller = controller
        self.state = GuiRunState(())
        self._owns_run = False
        self._task_rows = {}
        self._build_ui()
        self._connect_signals()
        self.refresh_sources()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        settings = QGroupBox("测试请求")
        form = QFormLayout(settings)
        self.scenario_combo = QComboBox()
        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        for baud in (2_000_000, 250_000, 115_200, 921_600):
            self.baud_combo.addItem(str(baud), baud)
        self.noninteractive_wifi = QCheckBox("使用 system.yaml 默认 WiFi，不弹出交互")
        form.addRow("Scenario", self.scenario_combo)
        form.addRow("串口", self.port_combo)
        form.addRow("波特率", self.baud_combo)
        form.addRow("WiFi", self.noninteractive_wifi)
        layout.addWidget(settings)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("刷新")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        status = QHBoxLayout()
        self.run_status_label = QLabel("IDLE")
        self.cycle_label = QLabel("0")
        self.module_label = QLabel("-")
        status.addWidget(QLabel("运行状态:"))
        status.addWidget(self.run_status_label)
        status.addSpacing(24)
        status.addWidget(QLabel("Cycle:"))
        status.addWidget(self.cycle_label)
        status.addSpacing(24)
        status.addWidget(QLabel("Current Module:"))
        status.addWidget(self.module_label)
        status.addStretch(1)
        layout.addLayout(status)

        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["Module", "Repeat", "Duration", "Status"])
        self.task_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.task_table, 2)

        self.result_table = QTableWidget(0, 4)
        self.result_table.setHorizontalHeaderLabels(["Result", "Module", "Status", "Message"])
        self.result_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.result_table, 2)

        self.log_view = BoundedLogView(max_blocks=8000)
        layout.addWidget(self.log_view, 3)

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_sources)
        self.scenario_combo.currentTextChanged.connect(self._load_scenario)
        self.start_button.clicked.connect(self.start_run)
        self.stop_button.clicked.connect(self.stop_run)
        self.controller.event_received.connect(self._handle_event)
        self.controller.run_finished.connect(self._handle_finished)
        self.controller.error.connect(self._handle_worker_error)
        self.controller.running_changed.connect(self._set_running)

    @Slot()
    def refresh_sources(self) -> None:
        selected_scenario = self.scenario_combo.currentText()
        self.scenario_combo.blockSignals(True)
        self.scenario_combo.clear()
        try:
            scenarios = list(self.service.list_scenarios())
        except Exception as exc:
            scenarios = []
            self.log_view.enqueue(f"[ERROR] 场景发现失败: {exc}")
        self.scenario_combo.addItems(scenarios)
        if selected_scenario in scenarios:
            self.scenario_combo.setCurrentText(selected_scenario)
        self.scenario_combo.blockSignals(False)

        selected_port = self.port_combo.currentData()
        self.port_combo.clear()
        self.port_combo.addItem("自动探测", "auto")
        try:
            for port in self.service.list_serial_ports():
                label = getattr(port, "display_name", getattr(port, "device", str(port)))
                device = getattr(port, "device", str(port))
                self.port_combo.addItem(label, device)
        except Exception as exc:
            self.log_view.enqueue(f"[WARN] 串口枚举失败: {exc}")
        index = self.port_combo.findData(selected_port)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        self._load_scenario(self.scenario_combo.currentText())

    @Slot(str)
    def _load_scenario(self, name: str) -> None:
        self.task_table.setRowCount(0)
        self._task_rows.clear()
        if not name:
            self.state.reset(())
            return
        try:
            description = self.service.describe_scenario(name)
        except Exception as exc:
            self.log_view.enqueue(f"[ERROR] 场景读取失败: {exc}")
            return
        modules = [task.module for task in description.tasks]
        self.state.reset(modules)
        for row, task in enumerate(description.tasks):
            self.task_table.insertRow(row)
            self.task_table.setItem(row, 0, QTableWidgetItem(task.module))
            self.task_table.setItem(row, 1, QTableWidgetItem(str(task.repeat)))
            self.task_table.setItem(row, 2, QTableWidgetItem("" if task.duration is None else str(task.duration)))
            self.task_table.setItem(row, 3, QTableWidgetItem("WAITING"))
            self._task_rows.setdefault(task.module, []).append(row)

    @Slot()
    def start_run(self) -> None:
        scenario = self.scenario_combo.currentText().strip()
        if not scenario:
            QMessageBox.warning(self, "Gravity ATS", "没有可执行的 Scenario")
            return
        try:
            baud = int(self.baud_combo.currentText().strip())
        except ValueError:
            QMessageBox.warning(self, "Gravity ATS", "波特率必须是整数")
            return
        port = str(self.port_combo.currentData() or "auto")
        request = RunRequest(
            scenario=scenario,
            system_overrides={"serial.port": port, "serial.baudrate": baud},
            no_interactive_wifi=self.noninteractive_wifi.isChecked(),
        )
        self._load_scenario(scenario)
        self.result_table.setRowCount(0)
        self.log_view.clear()
        self._owns_run = self.controller.start(request)
        self._set_running(self.controller.is_running)
        if not self._owns_run:
            QMessageBox.information(self, "Gravity ATS", "已有测试正在运行")

    @Slot()
    def stop_run(self) -> None:
        if self._owns_run:
            self.stop_button.setEnabled(False)
            self.run_status_label.setText("CANCELLING")
            self.controller.stop("operator clicked Stop")

    @Slot(object)
    def _handle_event(self, event: Event) -> None:
        if not self._owns_run:
            return
        self.state.apply(event)
        self.run_status_label.setText(self.state.run_status)
        self.cycle_label.setText(str(self.state.current_cycle))
        self.module_label.setText(self.state.current_module or "-")
        if event.type is EventType.TASK_STARTED:
            self._set_module_status(event.module, "RUNNING")
        elif event.type is EventType.TASK_FINISHED:
            self._set_module_status(event.module, event.status or "ERROR")
        elif event.type is EventType.RESULT_PRODUCED and event.result is not None:
            self._append_result(event.result)
        elif event.type is EventType.LOG:
            self.log_view.enqueue(f"[{event.level or 'INFO'}] {event.message}")

    def _set_module_status(self, module: str, status: str) -> None:
        rows = self._task_rows.get(module, [])
        for row in rows:
            self.task_table.setItem(row, 3, QTableWidgetItem(status))

    def _append_result(self, result) -> None:
        row = self.result_table.rowCount()
        self.result_table.insertRow(row)
        for column, value in enumerate((result.name, result.module, result.status, result.message)):
            self.result_table.setItem(row, column, QTableWidgetItem(str(value)))

    @Slot(object)
    def _handle_finished(self, result) -> None:
        if not self._owns_run:
            return
        self.run_status_label.setText(getattr(getattr(result, "status", ""), "value", str(getattr(result, "status", ""))))
        self.run_result_available.emit(result)
        self._owns_run = False

    @Slot(str)
    def _handle_worker_error(self, detail: str) -> None:
        if self._owns_run:
            self.log_view.enqueue("[ERROR] GUI Worker 异常\n" + detail)
            self._owns_run = False

    @Slot(bool)
    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.refresh_button.setEnabled(not running)
        self.scenario_combo.setEnabled(not running)
        self.port_combo.setEnabled(not running)
        self.baud_combo.setEnabled(not running)
        self.stop_button.setEnabled(running and self._owns_run)
