import subprocess
import sys
import time

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.platform.processes import ProcessController


def test_process_controller_starts_without_shell_and_reaps_process():
    controller = ProcessController(platform_name="linux")
    proc = controller.start([sys.executable, "-c", "print('ok')"], stdout=subprocess.PIPE, text=True)
    stdout, _ = proc.communicate(timeout=3)
    assert stdout.strip() == "ok"
    assert proc.returncode == 0


def test_process_controller_cancellation_terminates_child_fast():
    controller = ProcessController(platform_name="linux")
    token = CancellationToken()
    proc = controller.start([sys.executable, "-c", "import time; time.sleep(30)"])
    import threading
    threading.Timer(0.15, lambda: token.cancel("stop child")).start()
    started = time.monotonic()
    try:
        controller.wait(proc, timeout=30, cancellation_token=token)
        raise AssertionError("cancellation did not raise")
    except OperationCancelled:
        pass
    assert time.monotonic() - started < 2.0
    assert proc.poll() is not None


def test_windows_start_kwargs_are_confined_to_controller():
    controller = ProcessController(platform_name="windows")
    kwargs = controller.creation_kwargs(new_process_group=True, show_window=True)
    assert kwargs.get("creationflags", 0) != 0
    assert "start_new_session" not in kwargs
