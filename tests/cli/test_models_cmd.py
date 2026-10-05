import json

import pytest
from click.testing import CliRunner

from ipostudio.catalog.repo import upsert_models
from ipostudio.catalog.scan import model_scan_roots, scan_model_files
from ipostudio.cli.main import cli
from ipostudio.store.database import migrate, open_db

GGUF = b"GGUF" + b"\x00" * 28

@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    root = tmp_path / "models"
    root.mkdir()  # Codex determinism fold: write_bytes never creates parents
    (root / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    (root / "other-f16.gguf").write_bytes(GGUF + b"\x00" * 36)
    return tmp_path, root

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_models_lists_scanned_files(catalog):
    result = _invoke("models")
    assert result.exit_code == 0
    assert "tiny-q4" in result.output and "other-f16" in result.output
    assert "FORMAT" in result.output

def test_models_empty_state_guides_the_user(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("models")
    assert result.exit_code == 0
    assert "no models found" in result.output
    assert str(tmp_path / "models") in result.output
    assert "ipo config set model_dirs" in result.output

def test_models_json_is_clean_and_parseable(catalog):
    result = _invoke("models", "--json")
    assert result.exit_code == 0
    assert "\x1b[" not in result.output
    payload = json.loads(result.output)
    assert payload["count"] == 2 and payload["truncated"] is False
    assert {m["name"] for m in payload["models"]} == {"tiny-q4", "other-f16"}

def test_models_reports_broken_config_with_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("nonsense_key = 1\n", encoding="utf-8")
    result = _invoke("models", "--json")
    assert result.exit_code == 1
    assert "nonsense_key" in result.stderr

def test_model_without_select_shows_active_or_unset(catalog):
    unset = _invoke("model")
    assert unset.exit_code == 0
    assert "(not set)" in unset.output
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    selected = _invoke("model")
    assert selected.exit_code == 0
    assert "tiny-q4" in selected.output

def test_model_json_reports_null_active_on_fresh_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("model", "--json")
    assert result.exit_code == 0  # walker contract: no-arg invocation passes
    assert json.loads(result.output) == {"active": None}

def test_model_select_persists_config_and_hints_restart(catalog):
    result = _invoke("model", "--select", "tiny-q4")
    assert result.exit_code == 0
    assert "ipo server restart" in result.output
    stored = _invoke("config", "get", "local_chat_model")
    assert "tiny-q4" in stored.output

def test_model_select_reports_missing_with_hint(catalog):
    result = _invoke("model", "--select", "nope")
    assert result.exit_code == 1
    assert "no local model matches" in result.stderr
    assert "ipo models" in result.stderr

def test_model_select_reports_ambiguous_suffix(catalog):
    _tmp, root = catalog
    (root / "a").mkdir()
    (root / "a" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    (root / "b").mkdir()
    (root / "b" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    result = _invoke("model", "--select", "dup.gguf")
    assert result.exit_code == 1
    assert "ambiguous" in result.stderr

def test_model_info_reports_one_model(catalog):
    info = _invoke("model-info", "tiny-q4")
    assert info.exit_code == 0
    assert "tiny-q4.gguf" in info.output
    payload = json.loads(_invoke("model-info", "tiny-q4", "--json").output)
    assert payload["name"] == "tiny-q4" and payload["format"] == "gguf"

def test_model_info_requires_name(catalog):
    result = _invoke("model-info")
    assert result.exit_code == 2  # required argument (click usage error)

def test_activate_model_persists_and_resolves(catalog):
    tmp_path, _root = catalog
    from ipostudio.cli.models_cmd import activate_model
    from ipostudio.conf.loader import load_config

    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    files, _skipped, _truncated = scan_model_files(model_scan_roots([], tmp_path))
    upsert_models(conn, files)
    assert activate_model(conn, "tiny-q4", load_config()) == "tiny-q4"
    assert load_config().general.local_chat_model == "tiny-q4"
    with pytest.raises(LookupError):
        activate_model(conn, "absent", load_config())
    conn.close()

def test_activate_model_refuses_ambiguous_name_from_unique_path(catalog):
    tmp_path, _root = catalog
    from ipostudio.cli.models_cmd import activate_model
    from ipostudio.conf.loader import load_config

    models_root = tmp_path / "models"
    (models_root / "a").mkdir()
    (models_root / "a" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    (models_root / "b").mkdir()
    (models_root / "b" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    files, _skipped, _truncated = scan_model_files(model_scan_roots([], tmp_path))
    upsert_models(conn, files)
    with pytest.raises(ValueError):
        activate_model(conn, str(models_root / "a" / "dup.gguf"), load_config())
    conn.close()

def test_activate_model_raises_on_ambiguity(catalog):
    tmp_path, _root = catalog
    from ipostudio.cli.models_cmd import activate_model
    from ipostudio.conf.loader import load_config

    models_root = tmp_path / "models"
    (models_root / "a").mkdir()
    (models_root / "a" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    (models_root / "b").mkdir()
    (models_root / "b" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    files, _skipped, _truncated = scan_model_files(model_scan_roots([], tmp_path))
    upsert_models(conn, files)
    with pytest.raises(ValueError):
        activate_model(conn, "dup.gguf", load_config())
    conn.close()
