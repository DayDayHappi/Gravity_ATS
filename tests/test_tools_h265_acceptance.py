from pathlib import Path

from ATS.application.models import RunStatus
from ATS.tools.h265_acceptance import build_request, expectation_met


def test_h265_acceptance_builds_explicit_single_file_request(tmp_path):
    source = tmp_path / "中文 path" / "broken file.h265"
    source.parent.mkdir()
    source.write_bytes(b"x")

    request = build_request(str(source))

    override = request.module_overrides["video_integrity"]["input"]
    assert override["source"] == "directory"
    assert override["directory"] == str(source.parent)
    assert override["selection"] == "explicit"
    assert override["explicit_files"] == [source.name]


def test_h265_acceptance_treats_expected_failure_as_successful_evidence():
    assert expectation_met(RunStatus.PASSED, "PASS") is True
    assert expectation_met(RunStatus.FAILED, "FAIL") is True
    assert expectation_met(RunStatus.ERROR, "FAIL") is False
