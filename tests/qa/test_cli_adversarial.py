"""QA-C adversarial/edge-case tests: CLI entry and end-to-end behavior.

Domain: src/ipostudio/cli/main.py, src/ipostudio/__main__.py and their
interplay with src/ipostudio/conf/paths.py.  All probes exercise real
behavior: in-process CliRunner runs plus real `python -m ipostudio`
subprocesses for stream-encoding and true entry-point checks.  No mocks,
no network.  Findings are logged to .gstack/qa-reports/qa-log-cli.md.
"""

import ctypes
import json
import os
import re
import subprocess
import sys
from ctypes import wintypes

import pytest
from click.testing import CliRunner

from ipostudio import __version__
from ipostudio.cli.main import cli
from ipostudio.conf.paths import ensure_layout
from ipostudio.store.database import migrate, open_db

BOOTSTRAP_KEYS = ("IPO_CONFIG", "IPO_DATA_DIR", "IPO_DB_PATH")
SUBPROCESS_TIMEOUT = 30


@pytest.fixture(autouse=True)
def _restore_bootstrap_env():
    """The `ipo` group callback translates --config/--data-dir into os.environ
    and deliberately never restores it; keep that leak out of the test process."""
    saved = {key: os.environ.get(key) for key in BOOTSTRAP_KEYS}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


def _clean_env(extra_env=None):
    """Real subprocess env without IPO_* leakage from the test process shell."""
    env = {k: v for k, v in os.environ.items() if k not in BOOTSTRAP_KEYS}
    env.update(extra_env or {})
    return env


def run_module(*args, extra_env=None, timeout=SUBPROCESS_TIMEOUT):
    """Run `python -m ipostudio ...` in a real subprocess (true entry point)."""
    return subprocess.run(
        [sys.executable, "-m", "ipostudio", *args],
        capture_output=True,
        env=_clean_env(extra_env),
        timeout=timeout,
        check=False,
    )


def _build_wal_db(db):
    """Create a real WAL database exactly the way the app does and clean-close
    it (which checkpoints and removes the -wal/-shm side files)."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = open_db(db)
    try:
        migrate(conn)
    finally:
        conn.close()


def _migration_count(detail):
    m = re.search(r"migration count (\d+)", detail)
    assert m, detail
    return int(m.group(1))


# ---------------------------------------------------------------- exit codes


def test_usage_errors_exit_2_and_version_exit_0():
    result_flag = invoke("--no-such-flag")
    assert result_flag.exit_code == 2
    assert "no such option" in result_flag.stderr.lower()

    result_cmd = invoke("definitely-not-a-command")
    assert result_cmd.exit_code == 2
    assert "no such command" in result_cmd.stderr.lower()

    result_arg = invoke("version", "unexpected-arg")
    assert result_arg.exit_code == 2

    ok = invoke("version")
    assert ok.exit_code == 0
    assert __version__ in ok.output


def test_subprocess_m_entry_version_and_help_contract():
    ver_flag = run_module("--version")
    assert ver_flag.returncode == 0
    assert ver_flag.stdout.decode("utf-8").strip() == f"ipo, version {__version__}"

    ver_cmd = run_module("version")
    assert ver_cmd.returncode == 0
    assert ver_cmd.stdout.decode("utf-8").strip() == f"ipostudio {__version__}"

    helptext = run_module("--help")
    assert helptext.returncode == 0
    text = helptext.stdout.decode("utf-8")
    for name in ("version", "help", "guide", "doctor"):
        assert name in text


# ---------------------------------------------------------------- doctor happy


def test_doctor_fresh_layout_happy_path_subprocess_json(tmp_path):
    ensure_layout(tmp_path)
    proc = run_module("doctor", "--json", extra_env={"IPO_DATA_DIR": str(tmp_path)})
    assert proc.returncode == 0
    assert proc.stderr == b""  # no stderr noise on the happy path
    payload = json.loads(proc.stdout.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["warnings"] == []
    checks = {c["name"]: c for c in payload["checks"]}
    assert set(checks) == {"config", "data-dir", "database", "logs"}
    assert all(c["ok"] for c in checks.values())
    assert checks["data-dir"]["detail"] == str(tmp_path)
    assert "not initialized yet" in checks["database"]["detail"]
    assert str(tmp_path / "data" / "app.db") in checks["database"]["detail"]


# ---------------------------------------------------------------- doctor db states


def test_doctor_closed_wal_db_immutable_readonly_no_side_files(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    _build_wal_db(db)
    assert not any(p.name.endswith(("-wal", "-shm")) for p in db.parent.iterdir())
    before = {p.name for p in db.parent.iterdir()}
    result = invoke("doctor", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    check = next(c for c in payload["checks"] if c["name"] == "database")
    assert check["ok"] is True
    assert _migration_count(check["detail"]) >= 1  # immutable=1 ro open worked
    assert {p.name for p in db.parent.iterdir()} == before  # doctor created nothing


def test_doctor_live_wal_sidecar_readonly_and_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    db.parent.mkdir(parents=True)
    conn = open_db(db)  # stays open: a live writer keeps -wal/-shm on disk
    try:
        migrate(conn)
        conn.commit()
        assert (db.parent / "app.db-wal").exists()
        result = invoke("doctor", "--json")
        assert result.exit_code == 0
        payload = json.loads(result.output)
        check = next(c for c in payload["checks"] if c["name"] == "database")
        assert check["ok"] is True
        # frames read THROUGH the live WAL, not the bare main file
        assert _migration_count(check["detail"]) >= 1
        assert (db.parent / "app.db-wal").exists()  # doctor never deletes side files
        assert (db.parent / "app.db-shm").exists()
    finally:
        conn.close()


def test_doctor_garbage_db_guided_failure_exit_1(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_DB_PATH", str(tmp_path / "broken.db"))
    (tmp_path / "broken.db").write_bytes(b"this is definitely not a sqlite database" * 8)
    result = invoke("doctor", "--json")
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    check = next(c for c in payload["checks"] if c["name"] == "database")
    assert check["ok"] is False
    assert "sqlite failure reading" in check["detail"]
    assert str(tmp_path / "broken.db") in check["detail"]
    assert "doctor --fix" in check["detail"]  # guided remediation
    text = invoke("doctor")
    assert text.exit_code == 1
    assert "Traceback" not in text.output


@pytest.mark.skipif(
    sys.platform != "win32", reason="CreateFileW exclusive-lock probe is Windows-only"
)
def test_doctor_exclusively_locked_db_structured_no_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    _build_wal_db(db)
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    generic_read, open_existing, file_attr_normal = 0x80000000, 3, 0x80
    handle = kernel32.CreateFileW(
        str(db), generic_read, 0, None, open_existing, file_attr_normal, None
    )
    if handle in (None, ctypes.c_void_p(-1).value):
        pytest.fail("could not open an exclusive handle (test premise broken)")
    try:
        result = invoke("doctor", "--json")
        assert result.exit_code in (0, 1)  # guided PASS or clean FAIL, never a crash
        payload = json.loads(result.output)
        names = {c["name"] for c in payload["checks"]}
        assert names == {"config", "data-dir", "database", "logs"}
        check = next(c for c in payload["checks"] if c["name"] == "database")
        assert str(db) in check["detail"]  # path origin present in either branch
        text = invoke("doctor")
        assert text.exit_code == result.exit_code
        assert "Traceback" not in text.output
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------- redirects


def test_data_dir_flag_redirect_and_db_path_env_honored(tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()  # exists -> data-dir check probes it and reports the exact path
    db_elsewhere = tmp_path / "custom" / "my.db"
    monkeypatch.setenv("IPO_DB_PATH", str(db_elsewhere))
    result = invoke("--data-dir", str(other), "doctor", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    checks = {c["name"]: c for c in payload["checks"]}
    assert checks["data-dir"]["detail"] == str(other)  # redirected, not ~/.ipostudio
    assert ".ipostudio" not in json.dumps(payload)
    assert "not initialized yet" in checks["database"]["detail"]
    assert str(db_elsewhere) in checks["database"]["detail"]  # IPO_DB_PATH honored


def test_config_flag_missing_file_clean_and_directory_config_contained(
    tmp_path, monkeypatch
):
    missing = tmp_path / "nope" / "settings.toml"
    result = invoke("--config", str(missing), "version")
    assert result.exit_code == 0  # missing file: silent fallback to defaults
    assert __version__ in result.output
    doctor = invoke("--config", str(missing), "doctor", "--json")
    assert doctor.exit_code == 0
    payload = json.loads(doctor.output)
    config = next(c for c in payload["checks"] if c["name"] == "config")
    assert config["ok"] is True

    # a directory is unreadable: clean ConfigError containment, and a garbage db
    # fails at the same time -- one structured report must carry BOTH failures
    monkeypatch.setenv("IPO_DB_PATH", str(tmp_path / "junk.db"))
    (tmp_path / "junk.db").write_bytes(b"garbage" * 64)
    directory = tmp_path / "adir"
    directory.mkdir()
    broken = invoke("--config", str(directory), "doctor", "--json")
    assert broken.exit_code == 1
    payload2 = json.loads(broken.output)
    assert payload2["ok"] is False
    assert {c["name"] for c in payload2["checks"]} == {
        "config", "data-dir", "database", "logs",
    }
    cfg = next(c for c in payload2["checks"] if c["name"] == "config")
    db = next(c for c in payload2["checks"] if c["name"] == "database")
    assert cfg["ok"] is False
    assert "cannot read settings file" in cfg["detail"]
    assert db["ok"] is False
    assert "Traceback" not in broken.output


# ---------------------------------------------------------------- streams


def test_gbk_piped_streams_emit_valid_utf8(tmp_path):
    env = {"PYTHONIOENCODING": "gbk", "IPO_DATA_DIR": str(tmp_path)}
    ver = run_module("version", extra_env=env)
    assert ver.returncode == 0
    assert ver.stdout.decode("utf-8").strip() == f"ipostudio {__version__}"

    guide = run_module("guide", extra_env=env)  # zh brief emits CJK
    assert guide.returncode == 0
    text = guide.stdout.decode("utf-8")  # GBK bytes would break this decode
    assert "命令行工具" in text


# ---------------------------------------------------------------- logs / concurrency


def test_doctor_logs_check_tolerates_large_rotated_files(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    logs = tmp_path / "logs"
    logs.mkdir()
    chunk = b"2026-10-03 INFO ipostudio filler line for rotation pressure\n" * 1000
    (logs / "ipostudio.log").write_bytes(chunk * 40)  # ~2.4 MB
    (logs / "ipostudio.log.1").write_bytes(chunk)
    (logs / "ipostudio.log.2").write_bytes(chunk)
    result = invoke("doctor", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    check = next(c for c in payload["checks"] if c["name"] == "logs")
    assert check["ok"] is True
    assert check["detail"] == str(logs / "ipostudio.log")


def test_concurrent_doctors_same_data_dir(tmp_path):
    ensure_layout(tmp_path)
    _build_wal_db(tmp_path / "data" / "app.db")
    env = _clean_env({"IPO_DATA_DIR": str(tmp_path)})
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", "ipostudio", "doctor", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        for _ in range(2)
    ]
    results = []
    try:
        for proc in procs:
            out, err = proc.communicate(timeout=SUBPROCESS_TIMEOUT)
            results.append((proc.returncode, out, err))
    except subprocess.TimeoutExpired:
        for proc in procs:
            proc.kill()
        raise
    for returncode, out, err in results:
        assert returncode == 0
        payload = json.loads(out.decode("utf-8"))
        assert payload["ok"] is True
        dbcheck = next(c for c in payload["checks"] if c["name"] == "database")
        assert dbcheck["ok"] is True
        assert "schema at migration count" in dbcheck["detail"]


def test_doctor_database_success_detail_names_db_path(tmp_path, monkeypatch):
    """Regression QA-C-03: the plain-success database detail used to omit the
    db path while every other outcome (fail, degraded, repair) named it."""
    db = tmp_path / "app.db"
    monkeypatch.setenv("IPO_DB_PATH", str(db))
    conn = open_db(db)
    migrate(conn)
    conn.close()
    result = invoke("doctor", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    check = next(c for c in payload["checks"] if c["name"] == "database")
    assert check["ok"] is True
    assert str(db) in check["detail"]


def test_doctor_zero_byte_db_guided_pass(tmp_path, monkeypatch):
    """Regression H-04: a 0-byte app.db is a valid empty sqlite database
    (exactly what a crashed cold open leaves); doctor must give it the same
    guided PASS as a missing db, not a hard FAIL on 'no such table'."""
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "app.db").write_bytes(b"")
    result = invoke("doctor", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    check = next(c for c in payload["checks"] if c["name"] == "database")
    assert check["ok"] is True
    assert "not initialized" in check["detail"]


def test_doctor_fix_with_blocking_data_dir_keeps_check_names(tmp_path, monkeypatch):
    """Regression H-05: an environmental OSError during --fix (IPO_DATA_DIR
    is a file) used to rename every affected check to 'unexpected' with a
    false 'bug in ipo doctor' attribution, breaking the exactly-4-check-names
    JSON contract."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("IPO_DATA_DIR", str(blocker))
    result = invoke("doctor", "--fix", "--json")
    payload = json.loads(result.output)
    assert {c["name"] for c in payload["checks"]} == {
        "config", "data-dir", "database", "logs",
    }
    assert payload["ok"] is False
