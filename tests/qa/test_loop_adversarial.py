"""Adversarial guards for the core value loop surface.

Inherited contracts: byte-clean --json (the cli-ux walker auto-covers the new
listers — this module adds the loop-specific misbehavior checks), honest
missing-engine reporting (ADR-010), state-literal pinning (§10.2), and the
credential non-disclosure channel scan over the new commands."""

import inspect
import json

from click.testing import CliRunner

from ipostudio.cli import chat_cmd, models_cmd, server_cmd
from ipostudio.cli.main import cli

GGUF = b"GGUF" + b"\x00" * 28

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_new_cli_modules_never_style_directly():
    for module in (models_cmd, server_cmd, chat_cmd):
        source = inspect.getsource(module)
        assert "click.style" not in source
        assert "click.secho" not in source

def test_state_literals_are_pinned_in_one_place():
    from ipostudio.engines.repo import SERVICE_STATES as repo_states
    from ipostudio.engines.supervisor import SERVICE_STATES

    assert SERVICE_STATES == ("stopped", "starting", "loading", "running", "failed")
    assert repo_states is SERVICE_STATES

def test_engine_log_name_follows_per_process_convention():
    from ipostudio.engines.supervisor import ENGINE_LOG_FILE

    assert ENGINE_LOG_FILE.startswith("engine-")
    assert ENGINE_LOG_FILE.endswith(".log")

def test_missing_engine_never_fakes_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "m.gguf").write_bytes(GGUF + b"\x00" * 36)
    # deterministic on every machine: the configured engine path is missing,
    # so the start fails regardless of whether llama-server is on PATH
    ghost = tmp_path / "ghost-engine"
    assert CliRunner().invoke(
        cli, ["config", "set", "llama_cpp_path", str(ghost)]
    ).exit_code == 0
    assert _invoke("model", "--select", "m").exit_code == 0
    result = _invoke("server", "start")
    assert result.exit_code == 1
    assert "does not exist" in result.stderr
    assert "llama_cpp_path" in result.stderr
    # and nothing was recorded as running
    listing = json.loads(_invoke("server", "list", "--json").output)
    assert all(row["state"] != "running" for row in listing["instances"])

def test_configured_engine_path_that_vanishes_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "m.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    runner.invoke(cli, ["model", "--select", "m"])
    ghost = tmp_path / "ghost-engine"
    runner.invoke(cli, ["config", "set", "llama_cpp_path", str(ghost)])
    result = _invoke("server", "start")
    assert result.exit_code == 1
    assert "llama_cpp_path" in result.stderr

def test_chat_channel_scan_shows_no_secret_shapes(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    for args in (["chat", "hi"], ["status"], ["server", "info"]):
        result = _invoke(*args)
        combined = result.output + (result.stderr or "")
        assert "sk-" not in combined
        assert "Bearer " not in combined

def test_guide_still_mentions_every_top_level_command(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("guide")
    assert result.exit_code == 0
    for name in ("models", "model", "model-info", "server", "start",
                 "status", "stop", "restart", "chat"):
        assert name in result.output
