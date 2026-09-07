"""Pure builders that translate presentation input into Application requests."""
from __future__ import annotations

from ATS.application.models import RunRequest


def build_h265_request(
    *,
    directory: str,
    selection: str = "all",
    recursive: bool = False,
    fps: float = 30.0,
    gop: int = 30,
    decode: bool = True,
    showinfo: bool = True,
    trace_headers: bool = True,
    explicit_files=None,
    output_dir: str = None,
) -> RunRequest:
    """Build a standalone H.265 run using runtime overrides only."""
    return RunRequest(
        scenario="video_integrity",
        module_overrides={
            "video_integrity": {
                "input": {
                    "source": "directory",
                    "directory": str(directory),
                    "selection": str(selection),
                    "explicit_files": [str(path) for path in (explicit_files or [])],
                    "recursive": bool(recursive),
                },
                "analysis": {
                    "decode_check": True,
                    "locate_on_error": bool(showinfo),
                    "trace_headers_on_error": bool(trace_headers),
                },
                "hevc": {
                    "expected_fps": float(fps),
                    "expected_gop_size": int(gop),
                },
            }
        },
        output_dir=output_dir,
        no_interactive_wifi=True,
    )
