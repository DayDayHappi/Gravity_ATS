"""Platform-specific infrastructure kept outside ATS business modules.

CLI 最小裁剪版（feature/windows-cli）：只保留串口枚举、单键控制台输入、
子进程生命周期、工具查找四块能力。GUI / 服务编排 / 取消令牌相关能力不引入，
详见 docs/02_design/windows_cli_port_plan.md。
"""

from .resources import ResourceLocator
from .serial_ports import PySerialPortProvider, SerialPortInfo
from .processes import ProcessController
from .console_input import create_console_key_reader

__all__ = [
    "ResourceLocator",
    "PySerialPortProvider",
    "SerialPortInfo",
    "ProcessController",
    "create_console_key_reader",
]
