import os
from pathlib import Path

from ATS.platform.resources import ResourceLocator


def test_resource_locator_finds_config_and_runtime_from_arbitrary_cwd(tmp_path, monkeypatch):
    app = tmp_path / "app"
    (app / "ATS" / "config").mkdir(parents=True)
    tool = app / "runtime" / "ffmpeg" / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    tool.parent.mkdir(parents=True)
    tool.write_text("binary", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    locator = ResourceLocator(app_root=app, user_data_root=tmp_path / "user", frozen=False)

    assert locator.config_dir == app / "ATS" / "config"
    assert Path(locator.find_tool("ffprobe")) == tool
    assert locator.resolve_output_root("logs", "logs") == app / "logs"


def test_frozen_output_goes_to_user_data_and_preserves_absolute_override(tmp_path):
    app = tmp_path / "Program Files" / "Gravity ATS"
    user = tmp_path / "LocalAppData" / "GravityATS"
    locator = ResourceLocator(app_root=app, user_data_root=user, frozen=True)

    assert locator.resolve_output_root("logs", "logs") == user / "logs"
    absolute = tmp_path / "chosen reports"
    assert locator.resolve_output_root(str(absolute), "reports") == absolute


def test_find_tool_accepts_windows_suffix_even_when_preferred_omits_it(tmp_path):
    app = tmp_path / "app"
    exe = app / "tools" / "ffmpeg" / "ffmpeg.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    locator = ResourceLocator(app_root=app, frozen=False)
    assert Path(locator.find_tool("ffmpeg", "tools/ffmpeg/ffmpeg")) == exe


def test_frozen_locator_prefers_complete_user_config_override(tmp_path):
    app = tmp_path / "Program Files" / "GravityATS"
    bundled = app / "ATS" / "config"
    bundled.mkdir(parents=True)
    (bundled / "system.yaml").write_text("serial: {}", encoding="utf-8")
    user = tmp_path / "LocalAppData" / "GravityATS"
    override = user / "config"
    override.mkdir(parents=True)
    (override / "modules").mkdir()
    (override / "scenarios").mkdir()
    (override / "system.yaml").write_text("serial: {}", encoding="utf-8")

    locator = ResourceLocator(app_root=app, user_data_root=user, frozen=True)

    assert locator.config_dir == override


def test_frozen_locator_ignores_empty_user_config_directory(tmp_path):
    app = tmp_path / "Program Files" / "GravityATS"
    bundled = app / "ATS" / "config"
    bundled.mkdir(parents=True)
    (bundled / "system.yaml").write_text("serial: {}", encoding="utf-8")
    user = tmp_path / "LocalAppData" / "GravityATS"
    (user / "config").mkdir(parents=True)

    locator = ResourceLocator(app_root=app, user_data_root=user, frozen=True)

    assert locator.config_dir == bundled
