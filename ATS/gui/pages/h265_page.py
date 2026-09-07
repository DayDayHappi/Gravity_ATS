"""Standalone H.265 integrity analysis page."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ATS.core.events import Event, EventType
from ATS.gui.requests import build_h265_request
from ATS.gui.widgets.log_view import BoundedLogView


class H265Page(QWidget):
    def __init__(self, service, controller, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.controller = controller
        self._owns_run = False
        self.explicit_files = []
        self._build_ui()
        self.controller.event_received.connect(self._handle_event)
        self.controller.run_finished.connect(self._handle_finished)
        self.controller.error.connect(self._handle_error)
        self.controller.running_changed.connect(self._set_running)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        directory_row = QHBoxLayout()
        self.directory = QLineEdit()
        self.browse_button = QPushButton("选择目录")
        directory_row.addWidget(self.directory, 1)
        directory_row.addWidget(self.browse_button)
        form.addRow("视频目录", directory_row)
        files_row = QHBoxLayout()
        self.files_display = QLineEdit()
        self.files_display.setReadOnly(True)
        self.files_display.setPlaceholderText("selection=explicit 时选择一个或多个文件")
        self.files_button = QPushButton("选择文件")
        files_row.addWidget(self.files_display, 1)
        files_row.addWidget(self.files_button)
        form.addRow("Explicit Files", files_row)
        self.selection = QComboBox()
        for value in ("all", "latest", "latest_unchecked", "explicit"):
            self.selection.addItem(value, value)
        form.addRow("Selection", self.selection)
        self.recursive = QCheckBox("递归扫描子目录")
        form.addRow("扫描", self.recursive)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(0.1, 1000.0)
        self.fps.setValue(30.0)
        self.fps.setDecimals(3)
        self.gop = QSpinBox()
        self.gop.setRange(1, 10000)
        self.gop.setValue(30)
        form.addRow("Expected FPS", self.fps)
        form.addRow("Expected GOP", self.gop)
        analysis = QHBoxLayout()
        self.decode = QCheckBox("Decode（主判据，固定启用）")
        self.decode.setChecked(True)
        self.decode.setEnabled(False)
        self.decode.setToolTip("全文件 Decode 是现有 H265 PASS/FAIL 主判据，不能由表现层关闭")
        self.showinfo = QCheckBox("Showinfo")
        self.showinfo.setChecked(True)
        self.trace = QCheckBox("Trace Headers")
        self.trace.setChecked(True)
        analysis.addWidget(self.decode)
        analysis.addWidget(self.showinfo)
        analysis.addWidget(self.trace)
        analysis.addStretch(1)
        form.addRow("分析阶段", analysis)
        layout.addLayout(form)

        actions = QHBoxLayout()
        self.status_label = QLabel("IDLE")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        actions.addWidget(QLabel("状态:"))
        actions.addWidget(self.status_label)
        actions.addStretch(1)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)

        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["文件/用例", "状态", "Message", "Detail"])
        self.results.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.results, 2)
        self.log_view = BoundedLogView(max_blocks=8000)
        layout.addWidget(self.log_view, 3)
        self.browse_button.clicked.connect(self.choose_directory)
        self.files_button.clicked.connect(self.choose_files)
        self.start_button.clicked.connect(self.start_run)
        self.stop_button.clicked.connect(self.stop_run)

    @Slot()
    def choose_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 H265 目录", self.directory.text())
        if path:
            self.directory.setText(path)

    @Slot()
    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择 H265 文件",
            self.directory.text(),
            "H265/HEVC (*.h265 *.hevc);;All Files (*)",
        )
        if files:
            self.explicit_files = [str(path) for path in files]
            self.files_display.setText("; ".join(self.explicit_files))
            self.directory.setText(str(Path(files[0]).parent))
            index = self.selection.findData("explicit")
            if index >= 0:
                self.selection.setCurrentIndex(index)

    @Slot()
    def start_run(self) -> None:
        selection = str(self.selection.currentData())
        directory = self.directory.text().strip()
        if selection == "explicit" and not self.explicit_files:
            QMessageBox.warning(self, "Gravity ATS", "请选择至少一个 H265 文件")
            return
        if not directory:
            QMessageBox.warning(self, "Gravity ATS", "请选择 H265 视频目录")
            return
        request = build_h265_request(
            directory=directory,
            selection=selection,
            recursive=self.recursive.isChecked(),
            fps=self.fps.value(),
            gop=self.gop.value(),
            decode=self.decode.isChecked(),
            showinfo=self.showinfo.isChecked(),
            trace_headers=self.trace.isChecked(),
            explicit_files=self.explicit_files,
        )
        self.results.setRowCount(0)
        self.log_view.clear()
        self._owns_run = self.controller.start(request)
        self._set_running(self.controller.is_running)
        if not self._owns_run:
            QMessageBox.information(self, "Gravity ATS", "已有测试正在运行")

    @Slot()
    def stop_run(self) -> None:
        if self._owns_run:
            self.status_label.setText("CANCELLING")
            self.stop_button.setEnabled(False)
            self.controller.stop("operator stopped H265 analysis")

    @Slot(object)
    def _handle_event(self, event: Event) -> None:
        if not self._owns_run:
            return
        if event.type is EventType.LOG:
            self.log_view.enqueue(f"[{event.level or 'INFO'}] {event.message}")
        elif event.type is EventType.RESULT_PRODUCED and event.result is not None:
            result = event.result
            row = self.results.rowCount()
            self.results.insertRow(row)
            for column, value in enumerate((result.name, result.status, result.message, result.detail)):
                self.results.setItem(row, column, QTableWidgetItem(str(value)))
        elif event.type is EventType.RUN_FINISHED:
            self.status_label.setText(event.status or "ERROR")
        elif event.type is EventType.RUN_STARTED:
            self.status_label.setText("RUNNING")

    @Slot(object)
    def _handle_finished(self, result) -> None:
        if self._owns_run:
            status = getattr(result, "status", "ERROR")
            self.status_label.setText(getattr(status, "value", str(status)))
            self._owns_run = False

    @Slot(str)
    def _handle_error(self, detail: str) -> None:
        if self._owns_run:
            self.log_view.enqueue("[ERROR] GUI Worker 异常\n" + detail)
            self.status_label.setText("ERROR")
            self._owns_run = False

    @Slot(bool)
    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running and self._owns_run)
        self.browse_button.setEnabled(not running)
        self.files_button.setEnabled(not running)
