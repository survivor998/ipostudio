import json
import os
import sys

import pytest
from click.testing import CliRunner

from ipostudio import __version__
from ipostudio.cli import main as cli_main
from ipostudio.cli.main import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


@pytest.fixture
def _restore_bootstrap_env():
    """The group callback translates --config/--data-dir into os.environ and
    deliberately never restores it; keep that leak out of the test process."""
    saved = {key: os.environ.get(key) for key in ("IPO_CONFIG", "IPO_DATA_DIR")}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_version_text_and_json():
    result = invoke("version")
    assert result.exit_code == 0
    assert __version__ in result.output
    payload = json.loads(invoke("version", "--json").output)
    assert payload == {"name": "ipostudio", "version": __version__}


def test_help_lists_commands_in_all_formats():
    for fmt in ("text", "markdown", "json"):
        result = invoke("help", "--format", fmt)
        assert result.exit_code == 0
    docs = json.loads(invoke("help", "--format", "json").output)
    names = {d["name"] for d in docs}
    assert {"version", "help", "guide", "doctor"} <= names


def test_guide_mentions_every_command_and_langs():
    result_zh = invoke("guide")
    assert result_zh.exit_code == 0
    result_en = invoke("guide", "--lang", "en")
    assert result_en.exit_code == 0
    docs = json.loads(invoke("guide", "--format", "json").output)
    assert {d["name"] for d in docs} >= {"version", "help", "guide", "doctor"}


def test_guide_lang_defaults_from_ui_lang_config(monkeypatch, tmp_path):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_UI_LANG", "en")
    result = invoke("guide")  # no --lang: follows ui_lang config
    assert result.exit_code == 0
    assert "unified entry" in result.output  # English brief, not Chinese


def test_group_version_flag():
    result = invoke("--version")
    assert result.exit_code == 0
    assert __version__ in result.output


def test_group_data_dir_flag_reaches_doctor(tmp_path, _restore_bootstrap_env):
    # Global Constraints (CLI 约定): group-level --data-dir is the universal
    # escape hatch, translated to IPO_DATA_DIR before any config load.
    result = invoke("--data-dir", str(tmp_path), "doctor", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    data_dir = next(c for c in payload["checks"] if c["name"] == "data-dir")
    assert data_dir["ok"] is True
    assert data_dir["detail"] == str(tmp_path)  # doctor probed THIS directory


def test_group_config_flag_is_read_before_config_load(tmp_path, _restore_bootstrap_env):
    # The flag must override IPO_CONFIG semantics before the first config
    # read: a value from the pointed-at file becomes observable behaviour.
    settings = tmp_path / "custom-settings.toml"
    settings.write_text('ui_lang = "en"\n', encoding="utf-8")
    result = invoke("--config", str(settings), "guide")  # no --lang: follows config
    assert result.exit_code == 0, result.output
    assert "unified entry" in result.output  # English brief from the --config file


def test_doctor_passes_on_fresh_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "[PASS]" in result.output
    assert not (tmp_path / "data" / "app.db").exists()  # read-only by default


def test_doctor_fix_initializes_database(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor", "--fix")
    assert result.exit_code == 0
    assert (tmp_path / "data" / "app.db").exists()


def test_doctor_fix_migrates_existing_outdated_database(tmp_path, monkeypatch):
    import sqlite3 as sq

    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    db.parent.mkdir(parents=True)
    conn = sq.connect(db)  # pre-existing DB with NO migrations applied
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    result = invoke("doctor", "--fix")
    assert result.exit_code == 0
    conn = sq.connect(db)
    names = [r[0] for r in conn.execute("SELECT name FROM _migrations")]
    conn.close()
    assert names == ["001_init.sql"]  # existing DB was migrated, not skipped


def test_doctor_fails_nonzero_on_bad_config(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("doctor")
    assert result.exit_code == 1
    assert "[FAIL]" in result.output
    assert "bogus_key" in result.output


def test_doctor_config_check_contained_on_unexpected_error(tmp_path, monkeypatch):
    # 每检查异常受纳: a non-ConfigError crash from load_config must be captured
    # as a structured check result, never kill doctor mid-report (--json too).
    # H-05: the contained outcome keeps the canonical "config" name (the JSON
    # contract is exactly these four checks) instead of renaming to
    # "unexpected", and attributes honestly instead of "a bug in ipo doctor".
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))

    def explode(*args, **kwargs):
        raise RuntimeError("config subsystem exploded")

    monkeypatch.setattr("ipostudio.cli.main.load_config", explode)
    result = invoke("doctor", "--json")
    assert result.exit_code == 1  # reported failure, not a crash
    payload = json.loads(result.output)  # report still complete
    assert {c["name"] for c in payload["checks"]} == {
        "config", "data-dir", "database", "logs",
    }
    config_check = next(
        c for c in payload["checks"] if c["name"] == "config"
    )
    assert config_check["ok"] is False
    assert "RuntimeError" in config_check["detail"]
    assert "unexpected error during the config check" in config_check["detail"]


def test_force_utf8_streams_tolerates_none_streams(monkeypatch):
    # pythonw.exe has sys.stdout/sys.stderr set to None; every command must
    # still run instead of dying with AttributeError on stream.isatty().
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    cli_main._force_utf8_streams()  # must not raise


def test_doctor_json_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("doctor", "--json").output)
    assert payload["ok"] is True
    names = {c["name"] for c in payload["checks"]}
    assert {"config", "data-dir", "database", "logs"} <= names


def _make_wal_db(db_path):
    """Create a real WAL database exactly the way the app does (open_db pins
    journal_mode=WAL) and clean-close it, which removes the side files."""
    from ipostudio.store.database import migrate, open_db

    conn = open_db(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()


def test_doctor_readonly_inspection_leaves_no_wal_side_files(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    _make_wal_db(db)  # clean close: no -wal/-shm exist from here on
    before = {p.name for p in db.parent.iterdir()}
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "schema at migration count" in result.output  # inspection succeeded
    after = {p.name for p in db.parent.iterdir()}
    assert after - before == set(), f"doctor created files: {after - before}"
    assert not any(name.endswith(("-wal", "-shm")) for name in after)


def test_doctor_readonly_keeps_existing_wal_sidecar(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    _make_wal_db(db)
    (db.parent / "app.db-wal").write_bytes(b"")  # simulate a live-writer sidecar
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "[PASS]" in result.output
    assert (db.parent / "app.db-wal").exists()  # doctor never deletes side files


def test_doctor_cantopen_degrades_to_guided_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_DB_PATH", str(tmp_path))  # a DIRECTORY, not a database
    result = invoke("doctor")
    assert result.exit_code == 0  # degraded PASS, not FAIL
    assert "[FAIL]" not in result.output
    assert "cannot inspect read-only" in result.output
    assert str(tmp_path) in result.output  # origin path in the note
    assert "doctor --fix" in result.output  # with guidance


def test_doctor_fix_failure_detail_names_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "junk.db"
    db.write_text("this is not a sqlite database", encoding="utf-8")
    monkeypatch.setenv("IPO_DB_PATH", str(db))
    result = invoke("doctor", "--fix")
    assert result.exit_code == 1
    assert "[FAIL] database" in result.output
    assert str(db) in result.output  # error contract: origin path in detail


def test_doctor_readonly_failure_detail_names_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "junk.db"
    db.write_text("this is not a sqlite database", encoding="utf-8")
    monkeypatch.setenv("IPO_DB_PATH", str(db))
    result = invoke("doctor")
    assert result.exit_code == 1
    assert "[FAIL] database" in result.output
    assert str(db) in result.output  # error contract: origin path in detail
