# tests/cli/test_timestamp_display.py
"""Phase-1 E2E finding: the database stores UTC (SQLite ``datetime('now')``,
ENG F9) but ``ipo server info`` and ``ipo model-info`` rendered those naive
strings unlabeled — a user at 19:26 local read "last completion ... 11:26:03".
Best practice (store UTC, convert at the presentation layer): the human
surface renders local time; ``--json`` keeps the raw stored strings so the
machine-readable contract is unchanged.

Note: on a UTC machine the conversion is the identity, so these tests also
pass against the old rendering there; on any offset zone they pin the fix."""

import json

from click.testing import CliRunner

from ipostudio.cli.main import cli
from ipostudio.cli.ui import local_time

GGUF = b"GGUF" + b"\x00" * 28
STORED = "2026-10-05 11:26:03"


def _invoke(*args):
    return CliRunner().invoke(cli, list(args))


def test_server_info_renders_completion_time_as_local(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    from ipostudio.store.database import migrate, open_db

    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO instances (engine, engine_version, model_name, model_path, "
        "host, port, pid, state, detail) VALUES "
        "('llama.cpp', '', 'm', 'm.gguf', '127.0.0.1', 1, NULL, 'stopped', '')"
    )
    conn.execute(
        "INSERT INTO completions (instance_id, model_name, prompt_text, "
        "output_text, prompt_chars, output_chars, duration_ms, status, detail) "
        "VALUES (1, 'm', 'p', 'a', 1, 1, 3, 'ok', '')"
    )
    conn.execute("UPDATE completions SET created_at = ?", (STORED,))
    conn.commit()
    conn.close()

    result = _invoke("server", "info")
    assert result.exit_code == 0
    assert f"last completion: ok (1 chars in 3 ms, {local_time(STORED)})" in (
        result.output
    )


def test_model_info_renders_first_seen_as_local(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    assert _invoke("models").exit_code == 0
    from ipostudio.store.database import migrate, open_db

    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    conn.execute("UPDATE models SET first_seen = ?", (STORED,))
    conn.commit()
    conn.close()

    result = _invoke("model-info", "tiny-q4")
    assert result.exit_code == 0
    assert f"seen:     {local_time(STORED)}" in result.output


def test_server_info_json_keeps_raw_stored_timestamps(tmp_path, monkeypatch):
    """The machine-readable contract stays byte-stable: raw UTC strings."""
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    from ipostudio.store.database import migrate, open_db

    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO instances (engine, engine_version, model_name, model_path, "
        "host, port, pid, state, detail) VALUES "
        "('llama.cpp', '', 'm', 'm.gguf', '127.0.0.1', 1, NULL, 'stopped', '')"
    )
    conn.execute(
        "INSERT INTO completions (instance_id, model_name, prompt_text, "
        "output_text, prompt_chars, output_chars, duration_ms, status, detail) "
        "VALUES (1, 'm', 'p', 'a', 1, 1, 3, 'ok', '')"
    )
    conn.execute("UPDATE completions SET created_at = ?", (STORED,))
    conn.commit()
    conn.close()

    result = _invoke("server", "info", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["last_completion"]["created_at"] == STORED
