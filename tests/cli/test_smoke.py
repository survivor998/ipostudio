import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def run_module(args: list[str], data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC), "IPO_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-m", "ipostudio", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",  # CLI pins non-tty output to UTF-8 (requirement R1)
        env=env,
        timeout=60,
        check=False,  # returncode is asserted per-test; do not raise here
    )


def test_module_entry_version_json(tmp_path):
    proc = run_module(["version", "--json"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["name"] == "ipostudio"


def test_module_entry_doctor_json(tmp_path):
    proc = run_module(["doctor", "--json"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


def test_module_entry_guide_cjk_roundtrip(tmp_path):
    proc = run_module(["guide", "--lang", "zh"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "命令行" in proc.stdout  # UTF-8 survives Windows pipes (R1)
