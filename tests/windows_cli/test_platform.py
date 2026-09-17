"""平台行为测试。Windows分支为模拟，不等于Windows原生验收。"""
import importlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest


def mod(name):
    return importlib.import_module('ATS.platform.' + name)


def port(device, vid=None, description='', hwid=''):
    return NS(device=device, vid=vid, pid=1, description=description,
              hwid=hwid, serial_number=None)


def test_windows_candidates_usb_priority_natural_order_no_bluetooth(monkeypatch):
    p = mod('ports')
    monkeypatch.setattr(p, 'IS_WINDOWS', True)
    monkeypatch.setattr(p, 'list_ports', lambda: [
        port('COM10', 0x403), port('COM3', description='Bluetooth'),
        port('COM1'), port('COM2', 0x403), port('COM4', hwid='BTHENUM\\x')])
    assert p.candidate_ports() == ['COM2', 'COM10', 'COM1']


def test_linux_preserves_usb_acm_candidates(monkeypatch):
    p = mod('ports')
    monkeypatch.setattr(p, 'IS_WINDOWS', False)
    monkeypatch.setattr(p.os, 'access', lambda *a: True)
    monkeypatch.setattr(p, 'list_ports', lambda: [
        port('/dev/ttyS0'), port('/dev/ttyUSB10', 1),
        port('/dev/ttyUSB2', 1), port('/dev/ttyACM0', 1)])
    assert p.candidate_ports() == ['/dev/ttyACM0', '/dev/ttyUSB2', '/dev/ttyUSB10']


def test_linux_excludes_inaccessible_port(monkeypatch):
    p = mod('ports')
    monkeypatch.setattr(p, 'IS_WINDOWS', False)
    monkeypatch.setattr(p, 'list_ports', lambda: [port('/dev/ttyUSB0', 1)])
    monkeypatch.setattr(p.os, 'access', lambda *a: False)
    assert p.candidate_ports() == []


def fake_tool(path, name, monkeypatch, windows=False):
    t = mod('tools')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'MZfake' if windows else b'#!/bin/sh\n')
    path.chmod(0o755)
    monkeypatch.setattr(t, 'run_capture', lambda argv, **kw: subprocess.CompletedProcess(
        argv, 0, name + ' version test\n', ''))
    return path


def test_tools_windows_default_does_not_run_linux_binary(tmp_path, monkeypatch):
    t = mod('tools')
    monkeypatch.setattr(t, 'IS_WINDOWS', True)
    linux = tmp_path / 'tools/ffmpeg/ffmpeg'
    linux.parent.mkdir(parents=True)
    linux.write_bytes(b'\x7fELF')
    exe = fake_tool(tmp_path / 'tools/ffmpeg/windows/ffmpeg.exe', 'ffmpeg', monkeypatch, True)
    assert t.resolve_tool('ffmpeg', 'tools/ffmpeg/ffmpeg', root=tmp_path) == str(exe)


def test_tools_relative_to_project_not_cwd(tmp_path, monkeypatch):
    t = mod('tools')
    monkeypatch.setattr(t, 'IS_WINDOWS', False)
    executable = fake_tool(tmp_path / 'tools/ffmpeg/ffprobe', 'ffprobe', monkeypatch)
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert t.resolve_tool('ffprobe', root=tmp_path) == str(executable)


def test_tools_explicit_missing_path_never_falls_back(tmp_path):
    t = mod('tools')
    with pytest.raises(t.ToolError, match='不存在|不可执行'):
        t.resolve_tool('ffmpeg', str(tmp_path / 'missing ffmpeg'), root=tmp_path)


def test_tools_windows_reject_explicit_elf(tmp_path, monkeypatch):
    t = mod('tools')
    monkeypatch.setattr(t, 'IS_WINDOWS', True)
    elf = tmp_path / 'ffmpeg'
    elf.write_bytes(b'\x7fELF')
    with pytest.raises(t.ToolError):
        t.resolve_tool('ffmpeg', str(elf), root=tmp_path)


@pytest.mark.parametrize('suffix', ['.cmd', '.bat', '.ps1'])
def test_tools_reject_shell_scripts(tmp_path, monkeypatch, suffix):
    t = mod('tools')
    p = fake_tool(tmp_path / ('ffmpeg' + suffix), 'ffmpeg', monkeypatch)
    with pytest.raises(t.ToolError):
        t.resolve_tool('ffmpeg', str(p), root=tmp_path)


def test_tools_reject_version_failure(tmp_path, monkeypatch):
    t = mod('tools')
    p = fake_tool(tmp_path / 'ffmpeg', 'ffmpeg', monkeypatch)
    monkeypatch.setattr(t, 'IS_WINDOWS', False)
    monkeypatch.setattr(t, 'run_capture', lambda *a, **k: NS(returncode=1, stdout='', stderr='bad architecture'))
    with pytest.raises(t.ToolError, match='bad architecture'):
        t.resolve_tool('ffmpeg', str(p), root=tmp_path)


def test_process_capture_preserves_unicode_spaces_and_shell_literals(tmp_path):
    p = mod('processes')
    value = '中文 路径 & $(echo surprise);'
    result = p.run_capture([sys.executable, '-X', 'utf8', '-c', 'import sys; print(sys.argv[1])', value], timeout=5)
    assert result.returncode == 0
    assert result.stdout.strip() == value


def test_process_timeout_reaps_actual_child(monkeypatch):
    p = mod('processes')
    children = []
    original = p.spawn
    def save(*a, **k):
        proc = original(*a, **k)
        children.append(proc)
        return proc
    monkeypatch.setattr(p, 'spawn', save)
    with pytest.raises(subprocess.TimeoutExpired):
        p.run_capture([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=.1)
    assert children[0].poll() is not None


def test_process_interrupt_reaps_child(monkeypatch):
    p = mod('processes')
    child = Mock()
    child.communicate.side_effect = KeyboardInterrupt
    child.poll.side_effect = [None, None, 0, 0]
    monkeypatch.setattr(p, 'spawn', lambda *a, **k: child)
    with pytest.raises(KeyboardInterrupt):
        p.run_capture(['ffprobe', '-version'], timeout=1)
    assert child.terminate.called or child.kill.called
    assert child.wait.called


def test_windows_spawn_has_no_posix_or_shell_options(monkeypatch):
    p = mod('processes')
    monkeypatch.setattr(p, 'IS_WINDOWS', True)
    seen = {}
    def popen(argv, **kw):
        seen.update(kw)
        return Mock()
    monkeypatch.setattr(p.subprocess, 'Popen', popen)
    p.spawn(['ffprobe.exe', '-version'])
    assert seen['shell'] is False
    assert seen['stdin'] == subprocess.DEVNULL
    assert seen['creationflags'] & 0x200
    assert 'preexec_fn' not in seen
    assert 'start_new_session' not in seen


def test_posix_spawn_isolates_signal_session(monkeypatch):
    p = mod('processes')
    monkeypatch.setattr(p, 'IS_WINDOWS', False)
    seen = {}
    monkeypatch.setattr(p.subprocess, 'Popen', lambda argv, **kw: seen.update(kw))
    p.spawn(['ffprobe', '-version'])
    assert seen['start_new_session'] is True
    assert 'preexec_fn' not in seen


def test_keyboard_windows_tab_enter_backspace_extended(monkeypatch):
    p = mod('console_input')
    monkeypatch.setattr(p, 'IS_WINDOWS', True)
    chars = iter(['\t', '\r', '\b', '\xe0', 'H', '中', '\x03'])
    monkeypatch.setitem(sys.modules, 'msvcrt', NS(kbhit=lambda: True, getwch=lambda: next(chars)))
    stream = NS(isatty=lambda: True)
    with p.KeyboardInput(stream) as kb:
        assert kb.read() == '\t'
        assert kb.read() == '\r'
        assert kb.read() == '\b'
        assert kb.read() is None  # Windows arrow key is swallowed, not sent to EVB.
        assert kb.read() == '中'
        assert kb.read() == '\x03'


def test_keyboard_windows_poll_timeout(monkeypatch):
    p = mod('console_input')
    monkeypatch.setattr(p, 'IS_WINDOWS', True)
    monkeypatch.setitem(sys.modules, 'msvcrt', NS(kbhit=lambda: False))
    with p.KeyboardInput(NS(isatty=lambda: True)) as kb:
        assert kb.read(timeout=0) is None


def test_keyboard_non_tty_rejected_cleanly():
    p = mod('console_input')
    with pytest.raises(OSError, match='终端|TTY'):
        with p.KeyboardInput(NS(isatty=lambda: False)):
            pass


@pytest.mark.skipif(os.name == 'nt', reason='POSIX PTY test; Windows uses msvcrt branch tests')
def test_posix_keyboard_handles_pasted_unicode_without_stalling_and_restores_tty():
    import termios
    p = mod('console_input')
    master, slave = os.openpty()
    original = termios.tcgetattr(slave)
    stream = os.fdopen(os.dup(slave), 'r', encoding='utf-8')
    try:
        with p.KeyboardInput(stream) as kb:
            text = '中文\tabc\n'
            os.write(master, text.encode())
            received = [kb.read(timeout=.1) for _ in text]
            assert received == list(text)
        assert termios.tcgetattr(slave) == original
    finally:
        stream.close()
        os.close(master)
        os.close(slave)
