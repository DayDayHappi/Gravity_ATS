import importlib
import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

from ATS.core import logger
from ATS.core.context import Context
from ATS.core.scenario import Scenario, Task
from ATS.core.runner import TestRunner as Runner
from ATS.core.scenario_manager import ScenarioManager
from ATS.modules.base import TestModule as Module, _REGISTRY
from ATS.core.result import TestResult as Result


@pytest.fixture(autouse=True)
def close_logs():
    yield
    logger.close()


@pytest.fixture
def cfg_dir(tmp_path):
    dest = tmp_path / '配置 目录'
    shutil.copytree(Path(__file__).resolve().parents[2] / 'ATS/config', dest)
    return dest


def put_module(cfg_dir, name, data):
    (cfg_dir / 'modules' / (name + '.yaml')).write_text(yaml.safe_dump(data), encoding='utf-8')


def test_cli_new_flags():
    from ATS.main import parse_args
    a = parse_args(['--no-preview', '--no-problem-prompt', '--input-dir', '中文 目录'])
    assert a.no_preview and a.no_problem_prompt
    assert a.input_dir == '中文 目录'
    assert parse_args(['--list-ports']).list_ports


def test_list_ports_does_not_open_hardware(monkeypatch, capsys):
    from ATS import main
    from ATS.platform import ports
    monkeypatch.setattr(ports, 'list_ports', lambda: [NS(device='COM10', description='USB Serial',
                                                       vid=0x403, pid=0x6015, serial_number='ABC')])
    assert main.main(['--list-ports']) == 0
    assert 'COM10' in capsys.readouterr().out


def test_local_only_dependency_check_does_not_require_pyserial(monkeypatch, cfg_dir):
    from ATS.main import check_dependencies
    monkeypatch.setitem(sys.modules, 'serial', None)
    assert check_dependencies({}, Scenario(tasks=[Task('video_integrity')]), str(cfg_dir))


def test_runner_reads_selected_config_directory(monkeypatch, cfg_dir):
    class Probe(Module):
        def run(self, ctx, console, params=None):
            return self._pass(str(self.config['marker']))
    Probe.name = 'probe_cli'
    monkeypatch.setitem(_REGISTRY, 'probe_cli', Probe)
    put_module(cfg_dir, 'probe_cli', {'marker': 'CUSTOM_DIRECTORY'})
    r = Runner({}, Context(), Scenario(name='s', tasks=[Task('probe_cli')]), config_dir=str(cfg_dir))
    assert r.run()[0].message == 'CUSTOM_DIRECTORY'


def test_setup_sees_effective_task_override(monkeypatch, cfg_dir):
    seen = []
    class Probe(Module):
        def setup(self, ctx, console):
            seen.append(self.config['marker'])
        def run(self, ctx, console, params=None):
            return self._pass()
    Probe.name = 'probe_cli'
    monkeypatch.setitem(_REGISTRY, 'probe_cli', Probe)
    put_module(cfg_dir, 'probe_cli', {'marker': 'default'})
    r = Runner({}, Context(), Scenario(name='s', tasks=[Task('probe_cli', override={'marker': 'override'})]),
               config_dir=str(cfg_dir))
    r.run()
    assert seen == ['override']
    assert yaml.safe_load((cfg_dir / 'modules/probe_cli.yaml').read_text())['marker'] == 'default'


def test_setup_failure_still_tears_down(monkeypatch):
    seen = []
    class Probe(Module):
        def setup(self, ctx, console):
            raise RuntimeError('half open')
        def teardown(self, ctx, console):
            seen.append('closed')
    r = Runner({}, Context(), Scenario(name='s'))
    r._run_module('probe_cli', Probe, {}, {}, 1, 0, 1)
    assert seen == ['closed']
    assert r.results[0].status == 'ERROR'


def test_interrupt_records_error_and_tears_down(monkeypatch):
    seen = []
    class Probe(Module):
        def run(self, ctx, console, params=None):
            raise KeyboardInterrupt
        def teardown(self, ctx, console):
            seen.append('closed')
    ctx = Context()
    r = Runner({}, ctx, Scenario(name='s'))
    with pytest.raises(KeyboardInterrupt):
        r._run_module('probe_cli', Probe, {}, {}, 2, 3, 4)
    assert seen == ['closed']
    assert len(r.results) == 1
    assert (r.results[0].status, r.results[0].cycle, r.results[0].rep) == ('ERROR', 2, 4)
    assert ctx.interrupted


def test_manager_preserves_results_when_later_config_raises(monkeypatch, cfg_dir):
    class Probe(Module):
        def run(self, ctx, console, params=None):
            return self._pass('first completed')
    Probe.name = 'probe_cli'
    monkeypatch.setitem(_REGISTRY, 'probe_cli', Probe)
    monkeypatch.setitem(_REGISTRY, 'missing_cli', Probe)
    put_module(cfg_dir, 'probe_cli', {})
    manager = ScenarioManager(str(cfg_dir))
    monkeypatch.setattr(manager, 'load', lambda n: Scenario(name='s', tasks=[Task('probe_cli'), Task('missing_cli')]))
    with pytest.raises(Exception, match='配置文件不存在'):
        manager.run('s', system_cfg={})
    assert len(manager.results) == 1
    assert manager.results[0].message == 'first completed'


def test_manager_no_preview_override_and_config_context(monkeypatch, cfg_dir):
    from ATS.core.scenario import PREPARE_ACTIONS
    seen = []
    def prepare(ctx, system_cfg):
        seen.append((ctx.preview_enabled, ctx.config_dir))
    monkeypatch.setitem(PREPARE_ACTIONS, 'check_cli', prepare)
    manager = ScenarioManager(str(cfg_dir))
    manager.preview_cfg = {'enabled': True}
    monkeypatch.setattr(manager, 'load', lambda n: Scenario(name='s', prepare=['check_cli']))
    manager.run('s', system_cfg={}, no_preview=True)
    assert seen == [(False, str(cfg_dir))]


def test_ftp_prepare_uses_config_dir(monkeypatch, cfg_dir):
    from ATS.modules import ftp
    put_module(cfg_dir, 'ftp', {'port': 2121, 'user': 'marker'})
    ctx = Context()
    ctx.config_dir = str(cfg_dir)
    ctx.evb_ip = '192.0.2.2'
    ctx.ftp_server_started = True
    monkeypatch.setattr(ftp, 'ensure_ftp', lambda *a, **kw: object())
    ftp.start_ftp(ctx, None)
    assert ctx.ftp_cfg == {'port': 2121, 'user': 'marker'}


def test_preview_prepare_uses_selected_configs(monkeypatch, cfg_dir):
    from ATS.core.scenario_manager import _action_preview_start
    from ATS.drivers import preview_manager as pm, rtmp_server as rs
    put_module(cfg_dir, 'preview', {'retry_interval': 17, 'url': 'rtmp://192.0.2.1/custom/cam'})
    put_module(cfg_dir, 'rtmp', {'stream_url': 'rtmp://{pc_ip}/other/key'})
    seen = []
    class Preview:
        def __init__(self, cfg):
            seen.append(cfg)
        def start(self, url):
            seen.append(url)
    monkeypatch.setattr(pm, 'PreviewManager', Preview)
    monkeypatch.setattr(rs.RtmpServer, 'check_ready', lambda *a, **k: None)
    ctx = Context()
    ctx.preview_enabled = True
    ctx.config_dir = str(cfg_dir)
    ctx.system_config = {'pc': {'ip': '192.0.2.1'}}
    _action_preview_start(ctx, {})
    assert seen[0]['retry_interval'] == 17
    assert seen[1] == 'rtmp://192.0.2.1/custom/cam'


def test_terminal_import_does_not_import_unix_only_modules():
    code = '''
import builtins
original = builtins.__import__
def guarded(name, *a, **kw):
    if name in ('termios', 'tty'):
        raise ImportError('Windows does not have ' + name)
    return original(name, *a, **kw)
builtins.__import__ = guarded
import ATS.tools.serial_terminal
'''
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


class FakeSerial:
    def __init__(self):
        self.writes = []
        self.closed = False
    def reset_input_buffer(self): pass
    def reset_output_buffer(self): pass
    def read(self, size):
        time.sleep(.01)
        return b''
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def flush(self): pass
    def close(self): self.closed = True


def test_terminal_keeps_tab_backspace_enter_exit(monkeypatch):
    from ATS.tools import serial_terminal as t
    from ATS.platform import console_input
    device = FakeSerial()
    chars = iter('ab\bc\t\rexit\r')
    class Keys:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, timeout=.1): return next(chars, '')
    monkeypatch.setattr(t, 'serial', NS(Serial=lambda *a, **k: device))
    monkeypatch.setattr(t, 'KeyboardInput', Keys)
    assert t.run_terminal('COM10', 2000000) == 0
    assert device.writes == [b'ac\n']
    assert device.closed


def test_serial_console_open_reset_failure_closes_device(monkeypatch):
    from ATS.core import serial_console as s
    device = FakeSerial()
    def broken(): raise OSError('device removed')
    device.reset_input_buffer = broken
    monkeypatch.setattr(s, 'serial', NS(Serial=lambda *a, **k: device))
    c = s.SerialConsole('COM10')
    with pytest.raises(s.SerialError):
        c.open()
    assert device.closed


def test_serial_candidate_adapter_is_used(monkeypatch):
    from ATS.core import serial_console as s
    from ATS.platform import ports
    monkeypatch.setattr(ports, 'candidate_ports', lambda: ['COM10'])
    assert s._list_candidate_ports() == ['COM10']


def test_context_cleanup_releases_all_owned_resources():
    seen = []
    ctx = Context()
    ctx.ftp_client = NS(close=lambda: seen.append('ftp'))
    ctx.preview_manager = NS(stop=lambda: seen.append('preview'))
    ctx.console = NS(close=lambda: seen.append('serial'))
    ctx.cleanup()
    assert set(seen) == {'ftp', 'preview', 'serial'}
    assert ctx.as_dict() == {}


def test_cli_input_override_preserves_other_nested_scenario_settings():
    manager = ScenarioManager()
    sc = Scenario(tasks=[Task('video_integrity', override={'input': {'recursive': True, 'patterns': ['*.hevc']}})])
    manager._apply_module_overrides(sc, {'video_integrity': {'input': {'source': 'directory', 'directory': 'new'}}})
    assert sc.tasks[0].override['input'] == {'recursive': True, 'patterns': ['*.hevc'],
                                           'source': 'directory', 'directory': 'new'}


def test_main_interrupt_during_dependency_check_always_closes_logs(monkeypatch, cfg_dir, tmp_path):
    from ATS import main
    monkeypatch.chdir(tmp_path)
    def interrupted(*a, **kw): raise KeyboardInterrupt
    monkeypatch.setattr(main, 'check_dependencies', interrupted)
    assert main.main(['--config-dir', str(cfg_dir), '--scenario', 'video_integrity', '--dry-run']) == 130
    assert logger._SERIAL_FP is None and logger._RUN_FP is None


def test_main_interrupt_returns_130_with_partial_report(monkeypatch, cfg_dir, tmp_path):
    from ATS import main
    class Interrupt(Module):
        def run(self, ctx, console, params=None):
            raise KeyboardInterrupt
    Interrupt.name = 'interrupt_cli'
    monkeypatch.setitem(_REGISTRY, 'interrupt_cli', Interrupt)
    put_module(cfg_dir, 'interrupt_cli', {})
    (cfg_dir / 'scenarios/interrupt_cli.yaml').write_text(yaml.safe_dump({'scenario': {
        'name': 'interrupt_cli', 'prepare': [], 'tasks': [{'module': 'interrupt_cli'}], 'cleanup': []}}))
    monkeypatch.setattr(main, 'check_dependencies', lambda *a: True)
    monkeypatch.chdir(tmp_path)
    assert main.main(['--config-dir', str(cfg_dir), '--scenario', 'interrupt_cli', '--no-problem-prompt']) == 130
    reports = list(tmp_path.rglob('result.json'))
    assert len(reports) == 1
    data = json.loads(reports[0].read_text())
    assert data['results'][0]['status'] == 'ERROR'
    assert data['results'][0]['rep'] == 1
    assert logger._RUN_FP is None


def test_context_finishes_other_closes_before_reraising_keyboardinterrupt():
    ctx = Context()
    seen = []
    def interrupted(): raise KeyboardInterrupt
    ctx.preview_manager = NS(stop=interrupted)
    ctx.ftp_client = NS(close=lambda: seen.append('ftp'))
    ctx.console = NS(close=lambda: seen.append('serial'))
    with pytest.raises(KeyboardInterrupt): ctx.cleanup()
    assert seen == ['ftp', 'serial']
    assert ctx.as_dict() == {}


def test_manager_interrupt_in_cleanup_does_not_skip_remaining_actions(monkeypatch):
    from ATS.core.scenario import CLEANUP_ACTIONS
    seen = []
    def interrupted(*args): raise KeyboardInterrupt
    monkeypatch.setitem(CLEANUP_ACTIONS, 'interrupt_cleanup_cli', interrupted)
    monkeypatch.setitem(CLEANUP_ACTIONS, 'last_cleanup_cli', lambda *args: seen.append('closed'))
    manager = ScenarioManager()
    monkeypatch.setattr(manager, 'load', lambda name: Scenario(name=name, cleanup=['interrupt_cleanup_cli', 'last_cleanup_cli']))
    manager.run('s', system_cfg={})
    assert seen == ['closed']
    assert manager.interrupted
