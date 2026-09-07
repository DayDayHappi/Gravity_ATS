from ATS.gui.requests import build_h265_request


def test_h265_request_uses_runtime_override_not_yaml_rewrite(tmp_path):
    request = build_h265_request(
        directory=str(tmp_path / "中文 path"),
        selection="all",
        recursive=True,
        fps=30.0,
        gop=30,
        decode=True,
        showinfo=False,
        trace_headers=True,
    )

    assert request.scenario == "video_integrity"
    override = request.module_overrides["video_integrity"]
    assert override["input"]["directory"].endswith("中文 path")
    assert override["input"]["recursive"] is True
    assert override["analysis"]["locate_on_error"] is False
    assert override["analysis"]["trace_headers_on_error"] is True
    assert override["hevc"] == {"expected_fps": 30.0, "expected_gop_size": 30}


def test_h265_full_decode_remains_mandatory_even_if_presentation_requests_false(tmp_path):
    request = build_h265_request(directory=str(tmp_path), decode=False)
    analysis = request.module_overrides["video_integrity"]["analysis"]
    assert analysis["decode_check"] is True


def test_h265_explicit_selection_passes_absolute_files_through_runtime_override(tmp_path):
    first = tmp_path / "中文 A.h265"
    second = tmp_path / "B file.hevc"
    request = build_h265_request(
        directory=str(tmp_path),
        selection="explicit",
        explicit_files=[str(first), str(second)],
    )
    input_override = request.module_overrides["video_integrity"]["input"]
    assert input_override["selection"] == "explicit"
    assert input_override["explicit_files"] == [str(first), str(second)]
