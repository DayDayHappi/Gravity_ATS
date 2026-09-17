"""保留板端协议/下载时机的回归，以及真实本地 FFmpeg 的 CLI 集成测试。"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ATS.core import logger
from ATS.core.context import Context
from ATS.core.result import Response


@pytest.fixture(autouse=True)
def logs(tmp_path):
    logger.init_logger(str(tmp_path / '日志'))
    yield
    logger.close()


def test_ftp_failed_login_closes_unpublished_socket(monkeypatch):
    from ATS.drivers import ftp_client as f
    closed = []
    class FTP:
        def connect(self, *a, **kw): pass
        def login(self, *a): raise OSError('login failed')
        def close(self): closed.append(True)
    monkeypatch.setattr(f, 'FTP', FTP)
    with pytest.raises(f.FtpError):
        f.FtpClient('192.0.2.2', retry=2, interval=0).connect()
    assert len(closed) == 2


def test_ftp_interrupted_login_closes_unpublished_socket(monkeypatch):
    from ATS.drivers import ftp_client as f
    closed = []
    class FTP:
        def connect(self, *a, **kw): pass
        def login(self, *a): raise KeyboardInterrupt
        def close(self): closed.append(True)
    monkeypatch.setattr(f, 'FTP', FTP)
    with pytest.raises(KeyboardInterrupt):
        f.FtpClient('192.0.2.2', retry=1).connect()
    assert len(closed) == 1


def test_ftp_active_mode_and_new_connection_preserved(monkeypatch):
    from ATS.drivers import ftp_client as f
    sessions = []
    class FTP:
        def __init__(self):
            self.passive = None
            self.closed = False
            sessions.append(self)
        def connect(self, *a, **kw): pass
        def login(self, *a): pass
        def set_pasv(self, flag): self.passive = flag
        def cwd(self, path): assert path == '/'
        def close(self): self.closed = True
    monkeypatch.setattr(f, 'FTP', FTP)
    client = f.FtpClient('192.0.2.2')
    client.connect()
    client.connect()
    assert len(sessions) == 2 and sessions[0].closed
    assert sessions[1].passive is False
    client.close()
    assert sessions[1].closed


@pytest.mark.parametrize('key,command', [
    ('sd1080p_0', 'cam_set video sd1080p 0'),
    ('sd1080p_1', 'cam_set video sd1080p 1'),
    ('sd1080p_2', 'cam_set video sd1080p 2'),
    ('hd1080p_1', 'cam_set video hd1080p 1'),
    ('hd1080p_2', 'cam_set video hd1080p 2'),
    ('3k_2', 'cam_set video 3k 2'),
    ('720p_0', 'cam_set video 720p 0'),
    ('720p_1', 'cam_set video 720p 1'),
    ('720p_2', 'cam_set video 720p 2'),
    ('480p_0', 'cam_set video 480p 0'),
    ('480p_2', 'cam_set video 480p 2'),
])
def test_full_video_profiles_unchanged(key, command):
    from ATS.drivers.video_commands import resolve_video_profile
    assert resolve_video_profile(key).command == command


@pytest.mark.parametrize('key', ['1080p', '3k', '480p_1'])
def test_ambiguous_and_blocked_profiles_still_rejected(key):
    from ATS.drivers.video_commands import resolve_video_profile, VideoProfileError
    with pytest.raises(VideoProfileError): resolve_video_profile(key)


def serial_link(monkeypatch):
    from ATS.core import serial_console as s
    monkeypatch.setattr(s, 'serial', NS())
    monkeypatch.setattr(s, 'time', NS(sleep=lambda _: None, monotonic=time.monotonic))
    c = s.SerialConsole('COM10')
    chunks = []
    pending = bytearray()
    class Link:
        def write(self, data):
            chunks.append(data)
            pending.extend(data)
            while b'\n' in pending:
                i = pending.index(b'\n')
                line = bytes(pending[:i]).decode()
                del pending[:i+1]
                if line.startswith('echo '):
                    token = re.search(r'"([^"]+)"', line).group(1)
                    c._buffer.append('\n' + token + '\n')
                elif line == 'dfs_capture_start':
                    c._buffer.append('Capture completed successfully.\n')
                else:
                    c._buffer.append('mode configured\n')
            return len(data)
        def flush(self): pass
    c._ser = Link()
    return c, chunks


def test_sync_keeps_quoted_newline_sentinel_and_32_byte_chunks(monkeypatch):
    c, chunks = serial_link(monkeypatch)
    result = c.exec_sync('cam_set video sd1080p 0', timeout=.1)
    sent = b''.join(chunks)
    assert result.success
    assert b'\necho "__EVBTEST_END_' in sent and b';' not in sent
    assert max(map(len, chunks)) <= 32
    assert c.baudrate == 2000000


def test_async_keeps_business_completion_without_sentinel(monkeypatch):
    c, chunks = serial_link(monkeypatch)
    result = c.exec_async('dfs_capture_start', expect='Capture completed successfully.', result_timeout=.1)
    assert result.success
    assert b''.join(chunks) == b'dfs_capture_start\n'


class CaptureConsole:
    def __init__(self, set_ok=True):
        self.commands = []
        self.listeners = set()
        self.set_ok = set_ok
    def add_listener(self, cb): self.listeners.add(cb)
    def remove_listener(self, cb): self.listeners.discard(cb)
    def exec_sync(self, cmd, **kw):
        self.commands.append(cmd)
        return Response(success=self.set_ok, clean='' if self.set_ok else 'Usage error')
    def exec_async(self, cmd, **kw):
        self.commands.append(cmd)
        return Response(success=True, clean='/emmc/VIDEO/20260916_000001/Video_1_0.h265\nVideo recording completed successfully.')


def test_video_download_still_happens_per_recording_with_board_posix_path(monkeypatch):
    from ATS.modules import video, ftp
    downloaded = []
    class Client:
        def _list_entries(self, path): return []
        def size(self, path): return 200 * 1024
        def download(self, remote, local, **kwargs):
            downloaded.append((remote, local))
            Path(local).write_bytes(b'video' * 40960)
            return True
    client = Client()
    monkeypatch.setattr(ftp, 'ensure_ftp', lambda *a, **kw: client)
    monkeypatch.setattr(video, 'time', NS(sleep=lambda _: None, monotonic=time.monotonic))
    ctx = Context()
    ctx.ftp_client = client
    c = CaptureConsole()
    m = video.VideoModule({'video_resolution': '3k_2', 'video_duration': 1})
    result = m.run(ctx, c)
    assert result.status == 'PASS'
    assert c.commands == ['cam_set video 3k 2', 'dfs_video_start', 'dfs_video_stop']
    assert downloaded[0][0] == '/emmc/VIDEO/20260916_000001/Video_1_0.h265'
    assert Path(downloaded[0][1]).name.startswith('3k_2_20260916_000001_')
    assert not c.listeners


def test_video_does_not_record_after_size_setup_failure(monkeypatch):
    from ATS.modules import video, ftp
    client = NS(_list_entries=lambda path: [])
    monkeypatch.setattr(ftp, 'ensure_ftp', lambda *a, **kw: client)
    ctx = Context()
    ctx.ftp_client = client
    c = CaptureConsole(set_ok=False)
    m = video.VideoModule({'video_resolution': 'sd1080p_0', 'video_duration': 1})
    assert m.run(ctx, c).status == 'FAIL'
    assert c.commands == ['cam_set video sd1080p 0']


def test_integrity_manifest_all_unchecked_still_deduplicates(tmp_path):
    from ATS.modules.video_integrity import VideoIntegrityModule
    directory = tmp_path / '视频'
    directory.mkdir()
    for name in ('a.h265', 'b.h265'):
        (directory/name).write_bytes(b'not decoded in selection test')
    cfg = {'source': 'directory', 'directory': str(directory), 'selection': 'all_unchecked'}
    m = VideoIntegrityModule({'input': cfg})
    files, error = m._select_files(cfg)
    assert len(files) == 2 and error is None
    m._record_checked(files, cfg)
    assert m._select_files(cfg)[0] == []
    (directory/'a.h265').write_bytes(b'changed')
    assert len(m._select_files(cfg)[0]) == 1


def test_cli_module_listing_has_no_qt_dependency():
    code = '''
import builtins
old = builtins.__import__
def no_qt(name, *a, **kw):
    if name.startswith(('PySide', 'PyQt', 'qtpy')):
        raise ImportError('No UI allowed')
    return old(name, *a, **kw)
builtins.__import__ = no_qt
from ATS.main import main
raise SystemExit(main(['--list-modules']))
'''
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'video_integrity' in result.stdout


@pytest.fixture
def actual_video(tmp_path):
    from ATS.platform.tools import resolve_tool, ToolError
    try:
        executable = resolve_tool('ffmpeg')
    except ToolError as exc:
        pytest.skip('真实FFmpeg集成测试缺少工具: ' + str(exc))
    directory = tmp_path / '中文 视频 目录'
    directory.mkdir()
    video = directory / '正常 样本.h265'
    result = subprocess.run([executable, '-hide_banner', '-v', 'error', '-f', 'lavfi',
                             '-i', 'testsrc2=size=128x96:rate=10', '-t', '1', '-c:v', 'libx265',
                             '-preset', 'ultrafast', '-x265-params', 'pools=1:frame-threads=1:log-level=error',
                             '-an', '-f', 'hevc', str(video)], capture_output=True, timeout=20)
    if result.returncode:
        pytest.skip('样本生成要求带libx265的ffmpeg: ' + result.stderr.decode('utf-8', 'replace')[:300])
    return directory


def run_actual_cli(input_dir, tmp_path):
    script = Path(__file__).resolve().parents[2] / 'ATS/main.py'
    return subprocess.run([sys.executable, '-X', 'utf8', str(script), '--scenario', 'video_integrity',
                           '--input-dir', str(input_dir), '--no-preview', '--no-problem-prompt'],
                          cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', timeout=30)


def test_real_ffmpeg_local_cli_from_different_cwd_writes_reports(actual_video, tmp_path):
    out = run_actual_cli(actual_video, tmp_path)
    assert out.returncode == 0, out.stdout + out.stderr
    data = json.loads(next(tmp_path.rglob('result.json')).read_text(encoding='utf-8'))
    assert data['summary']['passed'] == 1
    assert list(tmp_path.rglob('junit.xml')) and list(tmp_path.rglob('report.html'))
    assert all(p.stat().st_size == 0 for p in tmp_path.rglob('serial.log'))


def test_real_ffmpeg_invalid_h265_does_not_pass(actual_video, tmp_path):
    for fp in actual_video.iterdir(): fp.unlink()
    (actual_video/'损坏 样本.h265').write_bytes(b'not HEVC data')
    out = run_actual_cli(actual_video, tmp_path)
    assert out.returncode == 1, out.stdout + out.stderr
    data = json.loads(next(tmp_path.rglob('result.json')).read_text(encoding='utf-8'))
    assert data['summary']['failed'] == 1
    assert list(tmp_path.rglob('decode.log'))
