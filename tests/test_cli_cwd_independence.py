import os
import subprocess
import sys
from pathlib import Path


def test_cli_discovers_scenarios_from_arbitrary_cwd(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "ATS.main", "--list-scenarios"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert "normal" in completed.stdout
    assert "release_smoke" in completed.stdout
