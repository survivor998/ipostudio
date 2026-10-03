import json

from click.testing import CliRunner

from ipostudio import __version__
from ipostudio.cli.main import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


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


def test_doctor_json_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("doctor", "--json").output)
    assert payload["ok"] is True
    names = {c["name"] for c in payload["checks"]}
    assert {"config", "data-dir", "database", "logs"} <= names
