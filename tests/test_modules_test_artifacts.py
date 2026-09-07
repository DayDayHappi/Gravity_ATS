from pathlib import Path
from types import SimpleNamespace

from ATS.core.result import Response
from ATS.drivers.h265_validator import H265ValidationResult
from ATS.modules.photo import PhotoModule
from ATS.modules.video import VideoModule
from ATS.modules.video_integrity import VideoIntegrityModule


class PhotoFtp:
    def list_files(self, _path):
        return ["Image_1.jpg"]

    def download(self, _remote, local, **_kwargs):
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(b"\xff\xd8\xff" + b"0" * 2048)
        return True


def test_photo_result_exposes_downloaded_file_as_generic_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr("ATS.modules.photo.logger.log_dir", lambda: str(tmp_path))
    monkeypatch.setattr("ATS.modules.ftp.ensure_ftp", lambda *_args, **_kwargs: PhotoFtp())
    console = SimpleNamespace(
        exec_sync=lambda *_args, **_kwargs: Response(success=True),
        exec_async=lambda *_args, **_kwargs: Response(
            success=True,
            clean="Save Photo Successful: /emmc/PIC/20260907_100000/\nCapture completed successfully.",
        ),
    )
    module = PhotoModule({"photo_min_size_kb": 1, "photo_settle_delay": 0})

    result = module._test_one(
        SimpleNamespace(), console, PhotoFtp(), "auto", 0, 1, 1,
        str(tmp_path / "photos"),
    )

    assert [(artifact.kind, Path(artifact.path).name) for artifact in result.artifacts] == [
        ("photo", "auto_20260907_100000_Image_1.jpg")
    ]


class VideoFtp:
    def _list_entries(self, _path):
        return []

    def size(self, _path):
        return 4096

    def download(self, _remote, local, **_kwargs):
        Path(local).parent.mkdir(parents=True, exist_ok=True)
        Path(local).write_bytes(b"v" * 4096)
        return True


def test_video_result_exposes_downloaded_file_as_generic_artifact(tmp_path, monkeypatch):
    ftp = VideoFtp()
    monkeypatch.setattr("ATS.modules.video.logger.log_dir", lambda: str(tmp_path))
    monkeypatch.setattr("ATS.modules.ftp.ensure_ftp", lambda *_args, **_kwargs: ftp)
    responses = iter([
        Response(success=True, clean="Record Start"),
        Response(
            success=True,
            clean="Save Video Successful: /emmc/VIDEO/20260907/Video_1_0.h265\nVideo recording completed successfully.",
        ),
    ])
    console = SimpleNamespace(exec_async=lambda *_args, **_kwargs: next(responses))
    module = VideoModule({"video_duration": 0, "video_min_size_kb": 1})

    result = module.run(SimpleNamespace(ftp_client=ftp), console)

    assert result.status == "PASS"
    assert [(artifact.kind, Path(artifact.path).name) for artifact in result.artifacts] == [
        ("video", "Video_1_0.h265")
    ]


def test_h265_aggregate_exposes_sources_and_diagnostics_as_artifacts(tmp_path):
    source = tmp_path / "异常 视频.h265"
    source.write_bytes(b"x")
    diagnostic = tmp_path / "diagnostic.txt"
    diagnostic.write_text("failure", encoding="utf-8")
    validation = H265ValidationResult(
        file_path=str(source),
        ok=False,
        error_type="DECODE_ERROR",
        reason="decode failure",
        diagnostic_logs=[str(diagnostic)],
    )
    module = VideoIntegrityModule({})

    result = module._aggregate([
        {"file": str(source), "name": source.name, "res": validation, "status": "FAIL"}
    ], [str(source)])

    assert {artifact.kind for artifact in result.artifacts} == {"video-source", "diagnostic"}
