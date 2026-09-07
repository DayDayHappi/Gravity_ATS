import time

from ATS.drivers.serial_terminal_session import SerialTerminalSession
from ATS.platform.serial_registry import SerialPortRegistry


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.writes = []
        self.read_data = [b"msh />", b""]

    def read(self, _size):
        if self.read_data:
            return self.read_data.pop(0)
        time.sleep(0.01)
        return b""

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass


def test_terminal_session_reserves_port_streams_data_and_releases():
    registry = SerialPortRegistry()
    fake = FakeSerial()
    received = []
    session = SerialTerminalSession(
        registry=registry,
        serial_factory=lambda *a, **k: fake,
        owner="terminal-test",
    )
    session.add_listener(received.append)

    session.open("COM10", 2_000_000)
    session.send("echo hi")
    deadline = time.monotonic() + 1
    while not received and time.monotonic() < deadline:
        time.sleep(0.01)
    session.close()

    assert fake.writes == [b"echo hi\n"]
    assert received == ["msh />"]
    assert registry.owner("COM10") is None


class BlockingTerminalSerial(FakeSerial):
    def __init__(self):
        super().__init__()
        self.release = __import__('threading').Event()
        self.cancel_read_called = False
        self.read_data = []

    def read(self, _size):
        self.release.wait(5)
        return b""

    def cancel_read(self):
        self.cancel_read_called = True
        self.release.set()

    def close(self):
        super().close()
        self.release.set()


def test_terminal_close_unblocks_reader_before_join():
    import time
    registry = SerialPortRegistry()
    fake = BlockingTerminalSerial()
    session = SerialTerminalSession(
        registry=registry,
        serial_factory=lambda *a, **k: fake,
        owner="terminal-blocking",
    )
    session.open("COM10", 2_000_000)

    started = time.monotonic()
    session.close()

    assert time.monotonic() - started < 0.5
    assert fake.cancel_read_called is True
    assert session._reader is None
    assert registry.owner("COM10") is None
