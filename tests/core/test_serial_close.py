import threading
import time

from ATS.core.serial_console import SerialConsole


class BlockingSerial:
    def __init__(self):
        self.is_open = True
        self.released = threading.Event()
        self.cancel_read_called = False
        self.closed = False

    def blocking_read(self):
        self.released.wait(5)

    def cancel_read(self):
        self.cancel_read_called = True
        self.released.set()

    def close(self):
        self.closed = True
        self.is_open = False
        self.released.set()


def test_serial_close_unblocks_reader_before_joining():
    fake = BlockingSerial()
    console = SerialConsole.__new__(SerialConsole)
    console._ser = fake
    console._stop_event = threading.Event()
    console._cond = threading.Condition(threading.Lock())
    console._reader_thread = threading.Thread(target=fake.blocking_read, daemon=True)
    console._reader_thread.start()

    started = time.monotonic()
    console.close()

    assert time.monotonic() - started < 0.5
    assert fake.cancel_read_called is True
    assert fake.closed is True
    assert not console._reader_thread.is_alive()
