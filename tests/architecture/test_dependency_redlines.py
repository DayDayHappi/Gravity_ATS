import ast
from pathlib import Path


def imports_in(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            values.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            values.append(node.module or "")
    return values


def test_engine_and_platform_never_import_gui_or_pyside():
    violations = []
    for root in ("ATS/core", "ATS/modules", "ATS/drivers", "ATS/application", "ATS/platform"):
        for path in Path(root).rglob("*.py"):
            for name in imports_in(path):
                if "PySide6" in name or name.startswith("ATS.gui") or name.startswith("gui"):
                    violations.append((str(path), name))
    assert violations == []


def test_os_detection_is_confined_to_platform_layer():
    violations = []
    for root in ("ATS/core", "ATS/modules", "ATS/drivers", "ATS/application"):
        for path in Path(root).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "os.name" in text or "platform.system" in text or "sys.platform" in text:
                violations.append(str(path))
    assert violations == []


def test_subprocesses_never_use_shell_true():
    violations = []
    for path in Path("ATS").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is True):
                    violations.append((str(path), node.lineno))
    assert violations == []


def test_preview_manager_has_no_bash_or_posix_process_group_calls():
    text = Path("ATS/drivers/preview_manager.py").read_text(encoding="utf-8")
    for forbidden in ("bash", "killpg", "setsid", "DISPLAY", "gnome-terminal", "xterm"):
        assert forbidden not in text


def test_engine_layers_do_not_read_from_stdin_directly():
    violations = []
    for root in ("ATS/core", "ATS/modules", "ATS/drivers"):
        for path in Path(root).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "input"):
                    violations.append((str(path), node.lineno))
    assert violations == []


def test_engine_layers_do_not_import_application_layer():
    violations = []
    for root in ("ATS/core", "ATS/modules", "ATS/drivers"):
        for path in Path(root).rglob("*.py"):
            for name in imports_in(path):
                if name.startswith("ATS.application") or name.startswith("..application"):
                    violations.append((str(path), name))
            text = path.read_text(encoding="utf-8")
            if "application.interaction" in text:
                violations.append((str(path), "application.interaction"))
    assert violations == []
