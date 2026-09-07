from pathlib import Path

import pytest

from ATS.core.cancellation import OperationCancelled
from ATS.drivers.h265_validator import H265Validator


class CancellingProcesses:
    def run_capture(self, *args, **kwargs):
        raise OperationCancelled("stop in capability probe")


def test_trace_capability_probe_propagates_cancellation():
    validator = H265Validator(
        {"ffmpeg_path": "ffmpeg"},
        process_controller=CancellingProcesses(),
    )
    validator.ffmpeg = "ffmpeg"
    with pytest.raises(OperationCancelled):
        validator._trace_available()


class ShowinfoCancels(H265Validator):
    def tool_available(self):
        return True

    def _run_decode(self, *args, **kwargs):
        return 1, False, ["Could not find ref with POC 16"]

    def _run_showinfo(self, *args, **kwargs):
        raise OperationCancelled("stop in showinfo")


def test_showinfo_stage_propagates_cancellation(tmp_path):
    source = tmp_path / "bad.h265"
    source.write_bytes(b"x")
    validator = ShowinfoCancels({
        "analysis": {"locate_on_error": True, "trace_headers_on_error": False},
        "input": {"patterns": ["*.h265"]},
    })
    with pytest.raises(OperationCancelled):
        validator.validate(str(source), str(tmp_path / "work"))


class TraceCancels(H265Validator):
    def tool_available(self):
        return True

    def _run_decode(self, *args, **kwargs):
        return 1, False, ["Could not find ref with POC 16"]

    def _trace_available(self):
        return True

    def _run_trace(self, *args, **kwargs):
        raise OperationCancelled("stop in trace")


def test_trace_stage_propagates_cancellation(tmp_path):
    source = tmp_path / "bad.h265"
    source.write_bytes(b"x")
    validator = TraceCancels({
        "analysis": {"locate_on_error": False, "trace_headers_on_error": True},
        "input": {"patterns": ["*.h265"]},
    })
    with pytest.raises(OperationCancelled):
        validator.validate(str(source), str(tmp_path / "work"))
