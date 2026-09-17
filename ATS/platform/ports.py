"""主机串口枚举；USB 优先，不替代 SerialConsole 的 EVB 指纹探测。"""
import os
import re

IS_WINDOWS = os.name == "nt"


def list_ports():
    """只枚举，不打开/探测串口。保留 pyserial 的 ListPortInfo 元信息。"""
    try:
        from serial.tools.list_ports import comports
    except ImportError as exc:
        raise RuntimeError("缺少 pyserial；请安装 ATS/requirements-cli.txt") from exc
    return list(comports())


def _natural_key(device):
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", device)]


def candidate_ports():
    """Windows 排除蓝牙自动探测；Linux 保留原 USB/ACM 范围和权限检查。

    手动 --port 由上层直接打开，不经过本筛选，因此不限制显式端口。
    """
    entries = {}
    for item in list_ports():
        device = item.device
        metadata = " ".join(str(getattr(item, k, "") or "")
                            for k in ("description", "hwid")).lower()
        if IS_WINDOWS:
            if "bluetooth" in metadata or "bthenum" in metadata or "蓝牙" in metadata:
                continue
            if not re.fullmatch(r"COM\d+", device, re.I):
                continue
        elif not (device.startswith(("/dev/ttyUSB", "/dev/ttyACM"))
                  and os.access(device, os.R_OK | os.W_OK)):
            continue
        usb = getattr(item, "vid", None) is not None or "usb" in metadata
        entries[device] = (0 if usb else 1, _natural_key(device))
    return sorted(entries, key=entries.get)
