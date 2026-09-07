"""Environment readiness page."""
from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class EnvironmentPage(QWidget):
    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.checks = []
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("重新检查")
        actions.addStretch(1)
        actions.addWidget(self.refresh_button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["检查项", "状态", "说明"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.refresh_button.clicked.connect(self.refresh)
        self.refresh()

    @property
    def has_failures(self) -> bool:
        return any(getattr(getattr(check, "status", None), "value", "") == "FAIL" for check in self.checks)

    @Slot()
    def refresh(self) -> None:
        self.table.setRowCount(0)
        try:
            self.checks = list(self.service.inspect_environment())
        except Exception as exc:
            self.checks = []
            self.table.insertRow(0)
            self.table.setItem(0, 0, QTableWidgetItem("Environment Inspector"))
            self.table.setItem(0, 1, QTableWidgetItem("FAIL"))
            self.table.setItem(0, 2, QTableWidgetItem(str(exc)))
            return
        for row, check in enumerate(self.checks):
            self.table.insertRow(row)
            status = getattr(check.status, "value", str(check.status))
            self.table.setItem(row, 0, QTableWidgetItem(str(check.name)))
            self.table.setItem(row, 1, QTableWidgetItem(status))
            self.table.setItem(row, 2, QTableWidgetItem(str(check.message)))
