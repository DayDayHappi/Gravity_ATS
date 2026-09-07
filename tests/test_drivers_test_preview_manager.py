import threading
import time

from ATS.drivers.preview_manager import PreviewManager


class FakeProcess:
    _pid = 100

    def __init__(self):
        type(self)._pid += 1
        self.pid = type(self)._pid
        self.returncode = None
        self.exit = threading.Event()

    def poll(self):
        return self.returncode


class FakeController:
    def __init__(self):
        self.started = []
        self.terminated = []

    def start(self, argv, **kwargs):
        proc = FakeProcess()
        self.started.append((argv, proc))
        return proc

    def wait(self, proc, timeout=None, cancellation_token=None):
        while proc.poll() is None:
            if cancellation_token and cancellation_token.wait(0.01):
                self.terminate(proc)
                cancellation_token.raise_if_cancelled()
            if proc.exit.wait(0.01):
                proc.returncode = 0
        return proc.returncode

    def terminate(self, proc, grace=2.0):
        self.terminated.append(proc.pid)
        proc.returncode = -15
        proc.exit.set()


class FakeLocator:
    def find_tool(self, name, preferred=None):
        return f"/runtime/{name}"


class Desktop:
    can_show_windows = True


def test_preview_reconnects_in_python_and_stop_reaps_current_process():
    controller = FakeController()
    manager = PreviewManager(
        {"retry_interval": 0.01},
        process_controller=controller,
        resource_locator=FakeLocator(),
        desktop_environment=Desktop(),
    )
    assert manager.start("rtmp://127.0.0.1/live/cam") is True
    deadline = time.monotonic() + 1
    while not controller.started and time.monotonic() < deadline:
        time.sleep(0.01)
    first = controller.started[0][1]
    first.returncode = 1
    first.exit.set()
    while len(controller.started) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    manager.stop()

    assert len(controller.started) >= 2
    assert manager.is_running() is False
    assert controller.terminated
    source = __import__("inspect").getsource(PreviewManager)
    assert "bash" not in source
    assert "killpg" not in source


class StubbornThread:
    def __init__(self):
        self.join_calls = []

    def is_alive(self):
        return True

    def join(self, timeout=None):
        self.join_calls.append(timeout)


def test_preview_stop_does_not_discard_live_worker_state(tmp_path):
    import io
    from ATS.core.cancellation import CancellationToken

    controller = FakeController()
    manager = PreviewManager(
        {},
        process_controller=controller,
        resource_locator=FakeLocator(),
        desktop_environment=Desktop(),
    )
    thread = StubbornThread()
    token = CancellationToken()
    log_handle = io.BytesIO()
    process = FakeProcess()
    manager._thread = thread
    manager._token = token
    manager._log_handle = log_handle
    manager._current_process = process

    stopped = manager.stop(timeout=0.01)

    assert stopped is False
    assert manager._thread is thread
    assert manager._token is token
    assert log_handle.closed is False
    assert token.is_cancelled is True
    assert controller.terminated == [process.pid]
