from pathlib import Path

from ATS.core.config import load_scenario
from ATS.core.scenario_manager import ScenarioManager


def test_release_smoke_matches_phase7_contract():
    scenario = ScenarioManager().load("release_smoke")
    assert scenario.loop.enable is True
    assert scenario.loop.count == 3
    assert [(task.module, task.repeat, task.duration) for task in scenario.tasks] == [
        ("photo", 2, None),
        ("video", 1, 20),
        ("rtmp", 1, 20),
    ]


def test_pyinstaller_spec_bundles_config_and_optional_runtime_in_onedir():
    text = Path("packaging/gravity_ats.spec").read_text(encoding="utf-8")
    assert '"ATS/config"' in text or "'ATS/config'" in text
    assert '"runtime"' in text or "'runtime'" in text
    assert "COLLECT(" in text
    assert "ATS.gui.main" in text or "ATS/gui/main.py" in text
    assert "collect_submodules" in text
    assert 'collect_submodules("ATS.modules")' in text or "collect_submodules('ATS.modules')" in text


def test_inno_installer_keeps_user_data_outside_install_tree():
    text = Path("packaging/GravityATS.iss").read_text(encoding="utf-8")
    assert "{localappdata}" in text.lower()
    assert "UninstallDelete" not in text
    assert "GravityATS.exe" in text


def test_windows_acceptance_script_covers_required_commands():
    text = Path("scripts/windows_acceptance.ps1").read_text(encoding="utf-8")
    for required in (
        "--list-scenarios",
        "--list-modules",
        "--dry-run",
        "--scenario normal",
        "--scenario release_smoke",
        "COM10",
        "result.json",
    ):
        assert required in text


def test_gitignore_keeps_project_runtime_tools_ignored_but_allows_ats_tool_sources():
    text = Path(".gitignore").read_text(encoding="utf-8")
    lines = {line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")}
    assert "/tools/" in lines
    assert "tools/" not in lines


def test_installer_seeds_user_config_without_overwriting_or_uninstalling_it():
    text = Path("packaging/GravityATS.iss").read_text(encoding="utf-8").lower()
    assert 'destdir: "{localappdata}\\gravityats\\config"' in text
    assert "onlyifdoesntexist" in text
    assert "uninsneveruninstall" in text
