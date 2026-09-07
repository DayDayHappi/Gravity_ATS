import ast
from pathlib import Path


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append((node.module or ""))
    return names


def test_gui_does_not_import_concrete_modules_runner_or_serial_console():
    gui = Path("ATS/gui")
    assert gui.is_dir()
    forbidden = ("ATS.modules", "ATS.core.runner", "ATS.core.serial_console", "..modules", "..core.runner", "..core.serial_console")
    violations = []
    for path in gui.rglob("*.py"):
        for name in imported_modules(path):
            if any(token in name for token in forbidden):
                violations.append((str(path), name))
    assert violations == []
