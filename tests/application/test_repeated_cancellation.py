import threading
import time

from ATS.application.models import RunRequest, RunStatus
from ATS.application.service import TestService
from ATS.core.cancellation import OperationCancelled


class Scenario:
    name = "stress"
    tasks = []


class WaitingManager:
    def __init__(self, **_kwargs):
        self.last_results = []

    def load(self, _name):
        return Scenario()

    def run(self, *args, **kwargs):
        token = kwargs["cancellation_token"]
        while not token.wait(0.01):
            pass
        token.raise_if_cancelled()


def test_service_can_start_and_stop_twenty_times_without_worker_leak(tmp_path):
    service = TestService(
        scenario_manager_factory=WaitingManager,
        system_loader=lambda _: {"runner": {}, "report": {"junit": False, "html": False}},
        dependency_checker=lambda *_args: [],
        reporter=lambda *_args, **_kwargs: {},
    )
    results = []
    baseline_threads = {thread.ident for thread in threading.enumerate()}

    for _ in range(20):
        thread = threading.Thread(
            target=lambda: results.append(service.run(RunRequest(
                scenario="stress", config_dir=str(tmp_path), output_dir=str(tmp_path)
            )))
        )
        thread.start()
        deadline = time.monotonic() + 2
        while not service.is_running and time.monotonic() < deadline:
            time.sleep(0.005)
        assert service.cancel_current("repeat stop") is True
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert service.is_running is False

    assert len(results) == 20
    assert all(result.status is RunStatus.CANCELLED for result in results)
    assert {thread.ident for thread in threading.enumerate()} == baseline_threads
