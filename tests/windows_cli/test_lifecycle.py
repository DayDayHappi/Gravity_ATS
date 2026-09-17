import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from ATS.core import logger
from ATS.core.context import Context
from ATS.core.result import Response


@pytest.fixture(autouse=True)
def logs(tmp_path):
    logger.init_logger(str(tmp_path / '日志'))
    yield
    logger.close()


def test_receiver_explicit_invalid_tool_must_not_fall_back(tmp_path):
    from ATS.drivers.rtmp_receiver import RtmpReceiver
    missing = str(tmp_path / 'missing' / 'ffprobe.exe')
    assert RtmpReceiver.check_tools(missing)


def test_h265_explicit_invalid_tool_must_not_fall_back(tmp_path):
    from ATS.drivers.h265_validator import H265Validator
    v = H265Validator({'ffmpeg_path': str(tmp_path / 'missing' / 'ffmpeg.exe')})
    assert not v.tool_available()


def test_receiver_uses_managed_capture_and_preserves_probe_argv(monkeypatch):
    from ATS.drivers import rtmp_receiver as r
    seen = []
    def capture(argv, timeout):
        seen.append(argv)
        return NS(returncode=0, stdout='{"streams":[{"codec_name":"h264","width":1920,"height":1080}]}', stderr='')
    monkeypatch.setattr(r, '_find_ffprobe', lambda *a: sys.executable)
    monkeypatch.setattr(r, 'run_capture', capture)
    receiver = r.RtmpReceiver()
    info = receiver.probe('rtmp://192.0.2.1/live/中文 key', attempts=1)
    assert info['ok'] and info['width'] == 1920
    assert seen[0][seen[0].index('-i') + 1] == 'rtmp://192.0.2.1/live/中文 key'
    assert '-rw_timeout' in seen[0]


def test_h265_spawn_timeout_reaps_process(monkeypatch, tmp_path):
    from ATS.drivers import h265_validator as h
    from ATS.platform import processes
    children = []
    def save(*a, **k):
        child = processes.spawn(*a, **k)
        children.append(child)
        return child
    monkeypatch.setattr(h, 'spawn', save)
    v = h.H265Validator()
    rc, timed = v._spawn([sys.executable, '-c', 'import time; time.sleep(30)'], .1, str(tmp_path/'out.log'))
    assert timed and rc != 0
    assert children[0].poll() is not None


def test_h265_spawn_interrupt_reaps_process(monkeypatch, tmp_path):
    from ATS.drivers import h265_validator as h
    from ATS.platform import processes
    children = []
    def save(*a, **k):
        child = processes.spawn(*a, **k)
        original = child.wait
        count = [0]
        def interrupted_wait(*args, **kw):
            count[0] += 1
            if count[0] == 1:
                raise KeyboardInterrupt
            return original(*args, **kw)
        child.wait = interrupted_wait
        children.append(child)
        return child
    monkeypatch.setattr(h, 'spawn', save)
    v = h.H265Validator()
    with pytest.raises(KeyboardInterrupt):
        v._spawn([sys.executable, '-c', 'import time; time.sleep(30)'], 3, str(tmp_path/'out.log'))
    assert children[0].poll() is not None
    (tmp_path/'out.log').unlink()


def test_h265_spawn_reads_complete_large_utf8_log(tmp_path):
    from ATS.drivers.h265_validator import H265Validator
    lines = []
    v = H265Validator()
    rc, timed = v._spawn([sys.executable, '-X', 'utf8', '-c',
                         "import sys; [sys.stderr.write('中文_%d\\n'%i) for i in range(20000)]"],
                        5, str(tmp_path/'日志 文件.log'), collector=lines.append)
    assert not timed and rc == 0
    assert len(lines) == 20000 and '中文_19999' in lines[-1]


@pytest.mark.parametrize('method, required', [
    ('_run_decode', ['-v', 'error', '-err_detect', 'explode']),
    ('_run_showinfo', ['-threads', '1', '-vf', 'showinfo']),
    ('_run_trace', ['-c:v', 'copy', '-bsf:v', 'trace_headers'])])
def test_h265_analysis_commands_remain_unchanged(monkeypatch, method, required):
    from ATS.drivers.h265_validator import H265Validator
    v = H265Validator()
    seen = []
    monkeypatch.setattr(v, '_spawn', lambda argv, *a: (seen.append(argv) or (0, False)))
    getattr(v, method)('中文 文件.h265', 'out.log', 10)
    assert all(value in seen[0] for value in required)
    assert seen[0][seen[0].index('-i') + 1] == '中文 文件.h265'


class Console:
    def __init__(self, interrupt_start=False, stop_ok=True):
        self.listeners = set()
        self.commands = []
        self.interrupt_start = interrupt_start
        self.stop_ok = stop_ok
    def add_listener(self, cb): self.listeners.add(cb)
    def remove_listener(self, cb): self.listeners.discard(cb)
    def exec_sync(self, cmd, **kw):
        self.commands.append(cmd)
        return Response(success=True)
    def exec_async(self, cmd, **kw):
        self.commands.append(cmd)
        if cmd.startswith('rtmp_video_start') and self.interrupt_start:
            raise KeyboardInterrupt
        return Response(success=self.stop_ok if 'stop' in cmd else True, error='timeout' if not self.stop_ok else None)


def rtmp_module(monkeypatch):
    from ATS.modules import rtmp
    m = rtmp.RtmpModule({'stream_duration': 0})
    m._server = NS(check_ready=lambda: None)
    m._receiver = NS(probe=lambda *a, **k: {'ok': True, 'reason': 'h264 1920x1080'}, stop=lambda: None)
    monkeypatch.setattr(rtmp, 'time', NS(sleep=lambda n: None, monotonic=time.monotonic))
    ctx = Context()
    ctx.pc_ip = '192.0.2.1'
    return m, ctx


def test_rtmp_interrupt_stops_before_next_task_and_detaches_listeners(monkeypatch):
    m, ctx = rtmp_module(monkeypatch)
    c = Console(interrupt_start=True)
    with pytest.raises(KeyboardInterrupt):
        m.run(ctx, c)
    assert 'rtmp_video_stop' in c.commands
    assert not c.listeners


def test_rtmp_probe_exception_stops_and_detaches(monkeypatch):
    m, ctx = rtmp_module(monkeypatch)
    def fail(*a, **kw): raise OSError('probe removed')
    m._receiver.probe = fail
    c = Console()
    with pytest.raises(OSError): m.run(ctx, c)
    assert 'rtmp_video_stop' in c.commands
    assert not c.listeners


def test_rtmp_no_stop_ack_is_visible_in_result_without_changing_probe_criterion(monkeypatch):
    m, ctx = rtmp_module(monkeypatch)
    c = Console(stop_ok=False)
    result = m.run(ctx, c)
    assert result.status == 'PASS'
    assert '未确认' in result.detail
    assert not c.listeners


def test_video_cleanup_no_ack_is_logged(capsys):
    from ATS.modules.video import VideoModule
    m = VideoModule({})
    m._recording_active = True
    m._stop_after_error(Console(stop_ok=False))
    assert '未确认' in capsys.readouterr().out


def test_scenario_stop_no_ack_is_logged(capsys):
    from ATS.core.scenario_manager import _action_stop_stream
    ctx = Context()
    ctx.console = Console(stop_ok=False)
    _action_stop_stream(ctx, {})
    assert '未确认' in capsys.readouterr().out


def prepare_preview(monkeypatch, tmp_path, exit_first=False):
    from ATS.drivers import preview_manager as p
    from ATS.platform import processes
    monkeypatch.setattr(p, 'IS_WINDOWS', True)
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(p, '_find_ffplay', lambda *a: sys.executable)
    children = []
    def command(self, url):
        code = 'pass' if exit_first and not children else 'import time; time.sleep(30)'
        return [sys.executable, '-c', code]
    monkeypatch.setattr(p.PreviewManager, '_argv', command)
    def save(argv, **kwargs):
        assert 'bash' not in argv
        child = processes.spawn(argv, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(p, 'spawn', save)
    return p.PreviewManager({'retry_interval': .03}), children


def wait_for(predicate, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate(): return
        time.sleep(.01)
    assert predicate(), 'condition timed out'


def test_windows_preview_without_display_is_singleton_and_stops_owned_child(monkeypatch, tmp_path):
    m, children = prepare_preview(monkeypatch, tmp_path)
    try:
        assert m.start('rtmp://test/key')
        assert m.start('rtmp://test/key')
        wait_for(lambda: len(children) == 1)
        assert m.is_running()
    finally:
        m.stop()
    assert len(children) == 1 and children[0].poll() is not None
    assert not m.is_running()


def test_preview_reconnect_without_accumulating_windows(monkeypatch, tmp_path):
    m, children = prepare_preview(monkeypatch, tmp_path, exit_first=True)
    try:
        assert m.start('rtmp://test/key')
        wait_for(lambda: len(children) >= 2)
        assert len([p for p in children if p.poll() is None]) <= 1
    finally:
        m.stop()
    assert all(p.poll() is not None for p in children)
    assert not m.is_running()


def test_linux_headless_preview_skips_without_side_effect(monkeypatch):
    from ATS.drivers import preview_manager as p
    monkeypatch.setattr(p, 'IS_WINDOWS', False)
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    m = p.PreviewManager({})
    assert m.start('rtmp://test/key') is False
    assert not m.is_running()


def test_h265_collector_failure_does_not_abort_remaining_diagnostics(tmp_path):
    from ATS.drivers.h265_validator import H265Validator
    seen = []
    def collect(line):
        if 'bad' in line:
            raise ValueError('malformed diagnostic record')
        seen.append(line)
    v = H265Validator()
    rc, timed = v._spawn([sys.executable, '-c', "import sys; sys.stderr.write('bad\\ngood\\n')"],
                        5, str(tmp_path/'diagnostic.log'), collect)
    assert rc == 0 and not timed
    assert seen == ['good\n']
