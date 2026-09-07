from pathlib import Path

from ATS.application.environment import CheckStatus, EnvironmentInspector


class Resources:
    def __init__(self, root):
        self.config_dir = root / "ATS" / "config"
        self.config_dir.mkdir(parents=True)
        self.user_data_root = root / "user"

    def find_tool(self, name, preferred=None):
        return f"/runtime/{name}" if name != "ffplay" else ""

    def resolve_output_root(self, configured, kind):
        return self.user_data_root / configured


class Ports:
    def list_ports(self):
        return [type("P", (), {"display_name": "COM10 — USB", "device": "COM10"})()]


class Backend:
    def is_ready(self):
        return True


class Processes:
    is_windows = True


class Services:
    def __init__(self, root):
        self.resources = Resources(root)
        self.serial_ports = Ports()
        self.rtmp_backend = Backend()
        self.processes = Processes()


def test_environment_inspector_returns_structured_checks(tmp_path):
    checks = EnvironmentInspector(Services(tmp_path)).inspect()
    by_name = {check.name: check for check in checks}

    assert by_name["Config"].status is CheckStatus.PASS
    assert by_name["Serial Ports"].status is CheckStatus.PASS
    assert by_name["FFmpeg"].status is CheckStatus.PASS
    assert by_name["FFplay"].status is CheckStatus.WARN
    assert by_name["RTMP:1935"].status is CheckStatus.PASS
    assert by_name["FTP Active/Firewall"].status is CheckStatus.WARN
