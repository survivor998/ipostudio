import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from ipostudio.cli.main import cli
from ipostudio.engines.openai_client import ChatError
from ipostudio.engines.repo import last_completion
from ipostudio.engines.supervisor import (
    choose_port,
    start_instance,
    stop_instance,
)
from ipostudio.store.database import migrate, open_db

FAKE = Path(__file__).resolve().parents[1] / "engines" / "fake_llama_server.py"
GGUF = b"GGUF" + b"\x00" * 28

@pytest.fixture
def running_service(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    assert runner.invoke(cli, ["model", "--select", "tiny-q4"]).exit_code == 0
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    port = choose_port("127.0.0.1", 18700)
    argv = [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
            "--model", "tiny-q4.gguf"]  # /props identity surface (Codex fold)
    outcome = start_instance(
        conn, argv, engine="llama.cpp", model_name="tiny-q4",
        model_path="tiny-q4.gguf", host="127.0.0.1", port=port,
        log_path=tmp_path / "logs" / "engine.log", timeout_s=20,
        poll_interval=0.05,
    )
    assert outcome.ok, outcome.instance["detail"]
    yield tmp_path, conn
    stop_instance(conn)
    conn.close()

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_chat_completes_against_running_server(running_service):
    _tmp, conn = running_service
    result = _invoke("chat", "hello")
    assert result.exit_code == 0, result.stderr
    assert "echo:hello" in result.output
    record = last_completion(conn)
    assert record is not None and record["status"] == "ok"
    assert record["prompt_chars"] == len("hello")
    # the exchange itself is stored (truncated), not just counters
    assert record["prompt_text"] == "hello"
    assert record["output_text"] == "echo:hello"

def test_chat_persists_null_content_as_error(running_service, monkeypatch):
    _tmp, conn = running_service
    from ipostudio.cli import chat_cmd

    monkeypatch.setattr(
        chat_cmd, "chat_completion",
        lambda *a, **k: {"choices": [{"message": {"content": None}}]},
    )
    result = _invoke("chat", "hello")
    assert result.exit_code == 1  # not a TypeError crash (Codex shape fold)
    assert "must be a string" in result.stderr
    assert last_completion(conn)["status"] == "error"

def test_chat_redacts_secret_shapes_before_persist(running_service):
    _tmp, conn = running_service
    secret = "Bearer sk-abc123def456ghi789jkl012"
    result = _invoke("chat", f"analyze this: {secret}")
    assert result.exit_code == 0, result.stderr
    stored = last_completion(conn)
    assert secret not in (stored["prompt_text"] or "")
    assert secret not in (stored["output_text"] or "")

def test_chat_record_survives_reconnect(running_service):
    tmp_path, conn = running_service
    assert _invoke("chat", "again").exit_code == 0
    instance_id = last_completion(conn)["instance_id"]
    # a SECOND connection sees the row; the fixture-owned connection stays
    # open for the teardown's stop_instance (Codex determinism fold)
    fresh = open_db(tmp_path / "data" / "app.db")
    record = last_completion(fresh)
    assert record["instance_id"] == instance_id
    fresh.close()

def test_chat_reaches_loopback_engine_when_the_row_records_the_wildcard_host(
    tmp_path, monkeypatch,
):
    # ba4e590 cross-effect fold: `server start --host 0.0.0.0` now SUCCEEDS on
    # Windows (the supervisor probes translate the wildcard to loopback) and
    # the instance row keeps the configured host — chat must apply the same
    # translate-only-the-connect-target rule, or the documented-supported
    # wildcard start leaves an engine that `ipo chat` can never reach
    # (connect-to-0.0.0.0 is refused on Windows, WSAEADDRNOTAVAIL class).
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    assert runner.invoke(cli, ["model", "--select", "tiny-q4"]).exit_code == 0
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    port = choose_port("127.0.0.1", 18900)
    argv = [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
            "--model", "tiny-q4.gguf"]
    outcome = start_instance(
        conn, argv, engine="llama.cpp", model_name="tiny-q4",
        model_path="tiny-q4.gguf", host="0.0.0.0", port=port,
        log_path=tmp_path / "logs" / "engine.log", timeout_s=20,
        poll_interval=0.05,
    )
    assert outcome.ok, outcome.instance["detail"]
    assert outcome.instance["host"] == "0.0.0.0"  # row keeps the configured host
    try:
        result = runner.invoke(cli, ["chat", "hello"])
        assert result.exit_code == 0, result.stderr
        assert "echo:hello" in result.output
        assert last_completion(conn)["status"] == "ok"
    finally:
        stop_instance(conn)
        conn.close()


def test_chat_without_server_guides_start(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("chat", "hello")
    assert result.exit_code == 1
    assert "ipo server start" in result.stderr

def test_chat_error_is_recorded_and_reported(running_service, monkeypatch):
    _tmp, conn = running_service
    from ipostudio.cli import chat_cmd

    def _explode(*args, **kwargs):
        raise ChatError("server returned HTTP 500: boom")

    monkeypatch.setattr(chat_cmd, "chat_completion", _explode)
    result = _invoke("chat", "hello")
    assert result.exit_code == 1
    assert "boom" in result.stderr
    record = last_completion(conn)
    assert record["status"] == "error"
    assert "boom" in record["detail"]

def test_chat_stdin_prompt(running_service):
    result = CliRunner().invoke(cli, ["chat", "-"], input="piped prompt\n")
    assert result.exit_code == 0, result.stderr
    assert "echo:piped prompt" in result.output
