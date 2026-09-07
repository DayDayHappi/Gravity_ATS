"""Structured report browser with generic artifact presentation."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ATS.application.reports import ReportDocument


class ReportPage(QWidget):
    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.document = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.browse_button = QPushButton("选择 result.json")
        self.latest_button = QPushButton("加载最新")
        self.load_button = QPushButton("加载")
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)
        path_row.addWidget(self.latest_button)
        path_row.addWidget(self.load_button)
        layout.addLayout(path_row)
        self.summary = QLabel("尚未加载报告")
        layout.addWidget(self.summary)
        self.results = QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(["Name", "Module", "Status", "Cycle", "Elapsed", "Message"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.currentCellChanged.connect(self._show_artifacts)
        layout.addWidget(self.results, 3)
        layout.addWidget(QLabel("Artifacts"))
        self.artifacts = QListWidget()
        self.artifacts.itemDoubleClicked.connect(self._open_artifact)
        layout.addWidget(self.artifacts, 1)
        actions = QHBoxLayout()
        self.open_report_dir_button = QPushButton("打开报告目录")
        self.open_log_dir_button = QPushButton("打开日志目录")
        actions.addWidget(self.open_report_dir_button)
        actions.addWidget(self.open_log_dir_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.browse_button.clicked.connect(self.choose_report)
        self.latest_button.clicked.connect(self.load_latest)
        self.load_button.clicked.connect(self.load_path)
        self.open_report_dir_button.clicked.connect(self.open_report_directory)
        self.open_log_dir_button.clicked.connect(self.open_log_directory)
        self._last_log_dir = ""

    @Slot()
    def choose_report(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择报告", self.path_edit.text(), "JSON (*.json)")
        if path:
            self.path_edit.setText(path)
            self.load_path()

    @Slot()
    def load_latest(self) -> None:
        roots = []
        locator = getattr(self.service, "resource_locator", None)
        if locator is not None:
            roots.extend([Path(locator.app_root) / "reports", Path(locator.user_data_root) / "reports"])
        candidates = []
        for root in roots:
            if root.is_dir():
                candidates.extend(root.rglob("result.json"))
        if not candidates:
            QMessageBox.information(self, "Gravity ATS", "未找到 result.json")
            return
        newest = max(candidates, key=lambda item: item.stat().st_mtime)
        self.path_edit.setText(str(newest))
        self.load_path()

    @Slot()
    def load_path(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            return
        try:
            self._display_document(ReportDocument.load(path))
        except Exception as exc:
            QMessageBox.critical(self, "Gravity ATS", f"报告加载失败: {exc}")

    def show_run_result(self, result) -> None:
        self._last_log_dir = str(getattr(result, "log_dir", "") or "")
        path = (getattr(result, "report_paths", {}) or {}).get("json", "")
        if path and Path(path).is_file():
            self.path_edit.setText(str(path))
            self.load_path()

    def _display_document(self, document: ReportDocument) -> None:
        self.document = document
        summary = document.summary
        self.summary.setText(
            f"Total {summary.get('total', 0)} | PASS {summary.get('passed', 0)} | "
            f"FAIL {summary.get('failed', 0)} | ERROR {summary.get('errored', 0)} | "
            f"SKIP {summary.get('skipped', 0)} | Pass Rate {summary.get('pass_rate', 0)}%"
        )
        self.results.setRowCount(0)
        for row, result in enumerate(document.results):
            self.results.insertRow(row)
            values = (
                result.name,
                result.module,
                result.status,
                result.cycle,
                result.elapsed_ms,
                result.message,
            )
            for column, value in enumerate(values):
                self.results.setItem(row, column, QTableWidgetItem(str(value)))
        if document.results:
            self.results.selectRow(0)

    @Slot(int, int, int, int)
    def _show_artifacts(self, current_row: int, _current_column: int, _previous_row: int, _previous_column: int) -> None:
        self.artifacts.clear()
        if self.document is None or current_row < 0 or current_row >= len(self.document.results):
            return
        for artifact in self.document.results[current_row].artifacts:
            label = artifact.label or Path(artifact.path).name or artifact.kind
            item = QListWidgetItem(f"[{artifact.kind}] {label} — {artifact.path}")
            item.setData(32, artifact.path)
            self.artifacts.addItem(item)

    @Slot(QListWidgetItem)
    def _open_artifact(self, item: QListWidgetItem) -> None:
        path = item.data(32)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).expanduser().resolve())))

    @Slot()
    def open_report_directory(self) -> None:
        if self.document is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.document.path.parent)))

    @Slot()
    def open_log_directory(self) -> None:
        if self._last_log_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._last_log_dir).resolve())))
