from types import SimpleNamespace

import pytest

from ATS.core.cancellation import OperationCancelled
from ATS.core.scenario_manager import _action_preclean


class Console:
    def __init__(self):
        self.calls = []

    def exec_sync(self, command, **kwargs):
        self.calls.append((command, kwargs))
        raise OperationCancelled("stop preclean")

    def exec_async(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return None


def test_preclean_propagates_cancellation_after_best_effort_video_stop():
    console = Console()
    ctx = SimpleNamespace(console=console)

    with pytest.raises(OperationCancelled):
        _action_preclean(ctx, {})

    assert [command for command, _ in console.calls] == ["cd /", "dfs_video_stop"]
    stop_kwargs = console.calls[-1][1]
    assert stop_kwargs["honor_cancellation"] is False
    assert stop_kwargs["result_timeout"] <= 3.0
