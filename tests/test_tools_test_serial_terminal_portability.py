import ast
from pathlib import Path


def test_serial_terminal_has_no_unconditional_posix_only_imports():
    path = Path("ATS/tools/serial_terminal.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top_level = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            top_level.append(node.module or "")
    assert "termios" not in top_level
    assert "tty" not in top_level


def test_terminal_uses_platform_key_reader_adapter():
    text = Path("ATS/tools/serial_terminal.py").read_text(encoding="utf-8")
    assert "create_console_key_reader" in text
