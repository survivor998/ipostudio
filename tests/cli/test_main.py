import json
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from ipostudio import __version__
from ipostudio.cli import main as cli_main
from ipostudio.cli.main import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


def all_output(result):
    """stdout + stderr across click 8.1/8.2 runner semantics."""
    try:
        return result.output + result.stderr
    except ValueError:  # click 8.1: stderr merged into output already
        return result.output


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


def test_doctor_text_output_has_summary_line(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "summary: 4 passed." in result.output


def test_doctor_failure_summary_names_failed_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("doctor")
    assert result.exit_code == 1
    assert "summary: 3 passed, 1 failed (config)" in result.output


def test_doctor_fix_success_suggests_guide_next(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor", "--fix")
    assert result.exit_code == 0
    assert "summary: 4 passed (repair mode)" in result.output
    assert "ipo guide" in result.output


def test_doctor_color_wiring_reaches_check_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: True)
    result = CliRunner().invoke(cli, ["doctor"], color=True)
    assert result.exit_code == 0
    assert "\x1b[32m[PASS]" in result.output


def test_doctor_json_output_stays_unstyled(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: True)
    result = CliRunner().invoke(cli, ["doctor", "--json"], color=True)
    assert result.exit_code == 0
    assert "\x1b[" not in result.output  # --json is machine-readable: never styled
    json.loads(result.output)


def test_doctor_truncates_long_details_with_json_pointer(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    long_detail = "x" * 400
    monkeypatch.setattr(
        cli_main, "run_doctor",
        lambda repair: ([cli_main.CheckOutcome("config", False, long_detail)], []),
    )
    result = invoke("doctor")
    assert "(+100 chars; use --json)" in result.output  # text channel truncates
    payload = json.loads(invoke("doctor", "--json").output)
    assert payload["checks"][0]["detail"] == long_detail  # --json always full


def test_doctor_force_color_survives_a_real_pipe(tmp_path):
    # CliRunner(color=True) forces color for every echo, so the runner cannot
    # discriminate click.echo's color passthrough; only a real pipe — where a
    # missing `color=color` silently strips painted ANSI — pins it (Codex ENG #3).
    import subprocess

    env = dict(os.environ, IPO_DATA_DIR=str(tmp_path), FORCE_COLOR="1")
    env.pop("NO_COLOR", None)
    proc = subprocess.run(
        [sys.executable, "-m", "ipostudio", "doctor"],
        env=env, capture_output=True, timeout=60,
        check=False,  # returncode is asserted below, not raised (ruff PLW1510)
    )
    assert proc.returncode == 0, proc.stderr
    assert b"\x1b[32m[PASS]" in proc.stdout  # ANSI survived the pipe


def test_config_path_prints_resolved_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "path")
    assert result.exit_code == 0
    assert str(tmp_path / "settings.toml") in result.output
    payload = json.loads(invoke("config", "path", "--json").output)
    assert payload == {"path": str(tmp_path / "settings.toml")}


def test_config_get_reports_effective_value_with_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "get", "server_port").output.strip() == "18080"
    monkeypatch.setenv("IPO_SERVER_PORT", "19000")
    assert invoke("config", "get", "server_port").output.strip() == "19000"


def test_config_get_optional_unset_key_reads_not_set(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "get", "local_model_path").output.strip() == "(not set)"


def test_config_get_empty_string_default_reads_not_set(tmp_path, monkeypatch):
    # schema default of vllm_api_base is "": a blank line would be
    # indistinguishable from a broken command (DX F1) — get matches list
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "get", "vllm_api_base").output.strip() == "(not set)"
    payload = json.loads(invoke("config", "get", "vllm_api_base", "--json").output)
    assert payload["value"] == ""  # --json stays raw: machine truth


def test_config_get_json_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("config", "get", "ui_lang", "--json").output)
    assert payload == {"key": "ui_lang", "family": "ui", "value": "zh"}


def test_config_get_unknown_key_exits_1_with_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "ui_them")
    assert result.exit_code == 1
    assert "unknown config key" in all_output(result)
    assert "ui_theme" in all_output(result)
    assert "ipo config list" in all_output(result)


def test_config_get_refuses_credential_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "vllm_api_key")
    assert result.exit_code == 1
    assert "IPO_VLLM_API_KEY" in all_output(result)
    assert "never displayed" in all_output(result)


def test_config_get_reports_broken_settings_with_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "get", "server_port")
    assert result.exit_code == 1
    assert "bogus_key" in all_output(result)


def test_config_get_masks_url_credential_values(tmp_path, monkeypatch):
    # read-side guard: load_config accepts env values the write path rejects —
    # a proxied credential must never reach get's text or JSON channel (Codex ENG #1)
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_PROXY_URL", "http://alice:secret@proxy.example.com")
    result = invoke("config", "get", "proxy_url")
    assert result.exit_code == 0
    assert "alice" not in result.output and "secret" not in result.output
    assert "(not set)" not in result.output  # masked, not treated as unset
    assert result.output.strip() == "***"
    payload = json.loads(invoke("config", "get", "proxy_url", "--json").output)
    assert payload["value"] == "***"


def test_config_path_absolutizes_relative_override(tmp_path, monkeypatch, _restore_bootstrap_env):
    # IPO_CONFIG may be relative (cwd-anchored); the display contract is absolute (Codex ENG #6)
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_CONFIG", "relative-settings.toml")
    payload = json.loads(invoke("config", "path", "--json").output)
    assert Path(payload["path"]).is_absolute()
    assert payload["path"].endswith("relative-settings.toml")


def test_config_set_validates_saves_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 0, result.output
    assert "server_port = 19000" in result.output
    assert f"(saved to {tmp_path / 'settings.toml'})" in result.output  # save() returns Path
    saved = json.loads(invoke("config", "get", "server_port", "--json").output)
    assert saved["value"] == 19000
    raw = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "server_port = 19000" in raw


def test_config_set_string_value_persists_raw_text(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "ui_theme", "dark")
    assert result.exit_code == 0, result.output
    assert invoke("config", "get", "ui_theme").output.strip() == "dark"


def test_config_set_env_override_warns_but_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_SERVER_PORT", "19999")
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 0, result.output
    assert "warning: IPO_SERVER_PORT is set in this shell" in all_output(result)
    try:
        # click 8.2+: stderr is a separate stream — the warning must be there,
        # and must NOT pollute stdout (DX F7); on 8.1 (merged streams, accessing
        # result.stderr raises ValueError) the isolation is untestable — skip
        # (click 8.2+ deviation: Result.output MIXES both streams, so the
        # stdout-only channel is Result.stdout — the DX F7 instrument here)
        assert "warning: IPO_SERVER_PORT" not in result.stdout
        assert "warning: IPO_SERVER_PORT" in result.stderr
    except ValueError:
        pass
    # the shell override still wins until it is unset
    assert invoke("config", "get", "server_port").output.strip() == "19999"


def test_config_set_rejects_invalid_value_without_save(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "server_port", "99999")
    assert result.exit_code == 1
    assert "error:" in all_output(result)
    assert not (tmp_path / "settings.toml").exists()  # rejected: nothing written


def test_config_set_rejects_credential_keys_with_env_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "vllm_api_key", "sk-abc123def456ghi789")
    assert result.exit_code == 1
    assert "sk-abc123def456ghi789" not in all_output(result)  # secret never echoed
    assert "IPO_VLLM_API_KEY" in all_output(result)
    assert not (tmp_path / "settings.toml").exists()


def test_config_set_rejects_inline_url_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "proxy_url", "https://Alice:Secret@example.com")
    assert result.exit_code == 1
    assert "environment variable" in all_output(result)


def test_config_set_none_clears_optional_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "set", "local_model_path", "abc").exit_code == 0
    result = invoke("config", "set", "local_model_path", "none")
    assert result.exit_code == 0, result.output
    raw = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "local_model_path" not in raw  # cleared, not written as null


def test_config_set_on_broken_baseline_reports_and_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 1
    assert "bogus_key" in all_output(result)
