from types import SimpleNamespace

from ATS.platform.serial_ports import PySerialPortProvider, SerialPortInfo


def test_provider_normalizes_windows_com_and_linux_devices():
    raw = [
        SimpleNamespace(device="COM3", description="Bluetooth", hwid="BTHENUM", vid=None, pid=None,
                        serial_number=None, manufacturer=None, product=None, interface=None, location=None),
        SimpleNamespace(device="COM10", description="USB Serial Port", hwid="USB VID:PID=0403:6015",
                        vid=0x0403, pid=0x6015, serial_number="DK0J1KSNA", manufacturer="FTDI",
                        product="USB Serial Port", interface=None, location="1-1"),
        SimpleNamespace(device="/dev/ttyUSB0", description="FTDI", hwid="USB", vid=0x0403, pid=0x6015,
                        serial_number="LINUX", manufacturer="FTDI", product="FTDI", interface=None,
                        location="2-1"),
    ]
    provider = PySerialPortProvider(enumerator=lambda: raw)

    ports = provider.list_ports()

    assert [p.device for p in ports] == ["/dev/ttyUSB0", "COM10", "COM3"]
    assert ports[1] == SerialPortInfo(
        device="COM10", description="USB Serial Port", hwid="USB VID:PID=0403:6015",
        vid=0x0403, pid=0x6015, serial_number="DK0J1KSNA", manufacturer="FTDI",
        product="USB Serial Port", interface="", location="1-1",
    )


def test_candidate_names_exclude_bluetooth_when_usb_exists():
    raw = [
        SimpleNamespace(device="COM3", description="Bluetooth link", hwid="BTHENUM", vid=None, pid=None,
                        serial_number=None, manufacturer=None, product=None, interface=None, location=None),
        SimpleNamespace(device="COM10", description="USB Serial Port", hwid="USB", vid=1, pid=2,
                        serial_number="x", manufacturer=None, product=None, interface=None, location=None),
    ]
    assert PySerialPortProvider(enumerator=lambda: raw).candidate_names() == ["COM10", "COM3"]
