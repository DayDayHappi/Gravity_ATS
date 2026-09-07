"""Cross-platform raw serial terminal page."""
from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ATS.core.ansi import strip as strip_ansi
from ATS.drivers.serial_terminal_session import SerialTerminalSession
from ATS.gui.widgets.log_view import BoundedLogView


class SerialTerminalPage(QWidget):
    serial_received = Signal(str)

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        registry = getattr(getattr(service, "platform_services", None), "serial_registry", None)
        self.session = SerialTerminalSession(registry=registry)
        self._test_running = False
        self._build_ui()
        self.serial_received.connect(self._append_received)
        self.session.add_listener(self.serial_received.emit)
        self.refresh_ports()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        for baud in (2_000_000, 250_000, 115_200, 921_600):
            self.baud_combo.addItem(str(baud), baud)
        self.refresh_button = QPushButton("刷新串口")
        self.connect_button = QPushButton("连接")
        self.ansi_checkbox = QCheckBox("剥离 ANSI")
        self.ansi_checkbox.setChecked(True)
        top.addWidget(self.port_combo, 2)
        top.addWidget(self.baud_combo)
        top.addWidget(self.refresh_button)
        top.addWidget(self.connect_button)
        top.addWidget(self.ansi_checkbox)
        layout.addLayout(top)
        self.output = BoundedLogView(max_blocks=10000)
        layout.addWidget(self.output)
        send = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("输入 msh 命令，回车发送")
        self.send_button = QPushButton("发送")
        self.clear_button = QPushButton("清屏")
        send.addWidget(self.input, 1)
        send.addWidget(self.send_button)
        send.addWidget(self.clear_button)
        layout.addLayout(send)
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.send_button.clicked.connect(self.send_command)
        self.input.returnPressed.connect(self.send_command)
        self.clear_button.clicked.connect(self.output.clear)

    @Slot()
    def refresh_ports(self) -> None:
        current = self.port_combo.currentData()
        self.port_combo.clear()
        try:
            ports = self.service.list_serial_ports()
        except Exception as exc:
            self.output.enqueue(f"[ERROR] 串口枚举失败: {exc}")
            return
        for port in ports:
            self.port_combo.addItem(
                getattr(port, "display_name", port.device),
                getattr(port, "device", str(port)),
            )
        index = self.port_combo.findData(current)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)

    @Slot()
    def toggle_connection(self) -> None:
        if self.session.is_open:
            self.close_session()
            return
        if self._test_running:
            QMessageBox.information(self, "Gravity ATS", "测试正在占用串口，终端不可连接")
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "Gravity ATS", "没有可用串口")
            return
        try:
            self.session.open(str(port), int(self.baud_combo.currentText()))
        except Exception as exc:
            QMessageBox.critical(self, "Gravity ATS", f"连接失败: {exc}")
            return
        self.connect_button.setText("断开")
        self.output.enqueue(f"[INFO] 已连接 {port} @ {self.baud_combo.currentText()}")
        self._update_controls()

    @Slot()
    def send_command(self) -> None:
        text = self.input.text()
        if not text:
            return
        try:
            self.session.send(text)
            self.output.enqueue(f"TX> {text}")
            self.input.clear()
        except Exception as exc:
            QMessageBox.warning(self, "Gravity ATS", str(exc))

    @Slot(str)
    def _append_received(self, text: str) -> None:
        value = strip_ansi(text) if self.ansi_checkbox.isChecked() else text
        self.output.enqueue(value)

    @Slot(bool)
    def set_test_running(self, running: bool) -> None:
        self._test_running = bool(running)
        if running and self.session.is_open:
            self.output.enqueue("[WARN] 测试即将占用串口，终端连接已释放")
            self.close_session()
        self._update_controls()

    def close_session(self) -> None:
        self.session.close()
        self.connect_button.setText("连接")
        self._update_controls()

    def _update_controls(self) -> None:
        connected = self.session.is_open
        self.connect_button.setEnabled(connected or (not self._test_running and self.port_combo.count() > 0))
        self.port_combo.setEnabled(not connected and not self._test_running)
        self.baud_combo.setEnabled(not connected and not self._test_running)
        self.refresh_button.setEnabled(not connected and not self._test_running)
        self.input.setEnabled(connected)
        self.send_button.setEnabled(connected)
