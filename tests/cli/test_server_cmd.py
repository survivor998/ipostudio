import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from ipostudio.cli.main import cli

FAKE = Path(__file__).resolve().parents[1] / "engines" / "fake_llama_server.py"
GGUF = b"GGUF" + b"\x00" * 28

@pytest.fixture
def service_env(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set", "server_port", "18400"])
    assert result.exit_code == 0, result.output
    return tmp_path

def _patch_fake_engine(monkeypatch):
    from ipostudio.cli import server_cmd

    monkeypatch.setattr(
        server_cmd, "resolve_engine",
        lambda configured: (Path(sys.executable), None),
    )

    def _fake_argv(engine, model_path, host, port, tuning, extra_args):
        return [sys.executable, str(FAKE), "--host", host, "--port", str(port),
                "--model", str(model_path)]

    monkeypatch.setattr(server_cmd, "build_server_argv", _fake_argv)

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_server_start_reports_missing_engine_honestly(service_env):
    # deterministic on every machine: a configured path that does not exist
    # is reported without depending on whether the dev box has llama-server
    runner = CliRunner()
    ghost = service_env / "ghost-engine"
    assert runner.invoke(
        cli, ["config", "set", "llama_cpp_path", str(ghost)]
    ).exit_code == 0
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("server", "start")
    assert started.exit_code == 1
    assert "does not exist" in started.stderr
    assert "llama_cpp_path" in started.stderr

def test_server_start_without_model_guides_selection(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    started = _invoke("server", "start")
    assert started.exit_code == 1
    assert "ipo model --select" in started.stderr

def test_server_start_reaches_running_and_stop_works(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("server", "start", "--timeout", "20")
    assert started.exit_code == 0, started.stderr
    assert "server running" in started.output
    assert "http://127.0.0.1:18400" in started.output
    info = _invoke("server", "info")
    assert info.exit_code == 0
    assert "running" in info.output
    stopped = _invoke("server", "stop")
    assert stopped.exit_code == 0
    assert "stopped" in stopped.output
    again = _invoke("server", "stop")
    assert again.exit_code == 0  # idempotent
    assert "no running server" in again.output

def test_server_start_twice_refuses_with_restart_hint(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("server", "start", "--timeout", "20").exit_code == 0
    try:
        second = _invoke("server", "start", "--timeout", "20")
        assert second.exit_code == 1
        assert "already" in second.stderr
        assert "ipo server restart" in second.stderr
    finally:
        _invoke("server", "stop")

def test_server_start_avoids_occupied_configured_port(service_env, monkeypatch):
    import socket

    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 18400))
        sock.listen(1)
        started = _invoke("server", "start", "--timeout", "20")
        assert started.exit_code == 0, started.stderr
        assert "http://127.0.0.1:1840" in started.output  # moved off 18400
    _invoke("server", "stop")

def test_server_info_and_list_report_state(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("server", "start", "--timeout", "20").exit_code == 0
    try:
        info = _invoke("server", "info", "--json")
        assert info.exit_code == 0
        payload = json.loads(info.output)
        assert payload["instance"]["state"] == "running"
        assert payload["instance"]["model_name"] == "tiny-q4"
        listing = _invoke("server", "list", "--json")
        rows = json.loads(listing.output)
        assert rows["count"] >= 1
        logs = _invoke("server", "logs")
        assert logs.exit_code == 0
    finally:
        _invoke("server", "stop")

def test_server_info_empty_is_a_valid_state(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("server", "info", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["instance"] is None
    text = _invoke("server", "info")
    assert "stopped" in text.output

def test_explicit_port_is_not_replaced(service_env, monkeypatch):
    import socket

    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 18555))
        sock.listen(1)
        started = _invoke("server", "start", "--port", "18555", "--timeout", "5")
        assert started.exit_code == 1
        assert "exited during startup" in started.stderr
    _invoke("server", "stop")

def test_reserved_tuning_warns_on_stderr(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    runner = CliRunner()
    assert runner.invoke(
        cli, ["config", "set", "server_auto_tune", "true"]
    ).exit_code == 0
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("server", "start", "--timeout", "20")
    assert started.exit_code == 0, started.stderr
    # spec §1.3 rule 3 (ruling #10): reserved capability is labelled, never silent
    assert "server_auto_tune" in started.stderr
    assert "not implemented yet" in started.stderr
    _invoke("server", "stop")

def test_remote_mode_and_non_llama_engine_are_honest(service_env):
    runner = CliRunner()
    assert runner.invoke(cli, ["config", "set", "server_mode", "remote"]).exit_code == 0
    blocked = _invoke("server", "start")
    assert blocked.exit_code == 1
    assert "remote" in blocked.stderr
    assert runner.invoke(cli, ["config", "set", "server_mode", "local"]).exit_code == 0
    assert runner.invoke(
        cli, ["config", "set", "inference_engine", "vllm"]
    ).exit_code == 0
    blocked = _invoke("server", "start")
    assert blocked.exit_code == 1
    assert "llama.cpp" in blocked.stderr


def test_start_shorthand_boots_the_default_service(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("start")
    assert started.exit_code == 0, started.stderr
    assert "server running" in started.output
    _invoke("stop")

def test_start_shorthand_honors_auto_start_off(service_env):
    runner = CliRunner()
    assert runner.invoke(
        cli, ["config", "set", "auto_start_server", "false"]
    ).exit_code == 0
    result = _invoke("start")
    assert result.exit_code == 0
    assert "auto_start_server is off" in result.output

def test_start_shorthand_is_idempotent_when_running(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("start").exit_code == 0
    again = _invoke("start")
    assert again.exit_code == 0
    assert "already running" in again.output
    _invoke("stop")

def test_start_selects_model_then_boots(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    started = _invoke("start", "--model", "tiny-q4")
    assert started.exit_code == 0, started.stderr
    active = _invoke("config", "get", "local_chat_model")
    assert "tiny-q4" in active.output
    _invoke("stop")

def test_reserved_flags_fail_with_plan_pointers(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    cloud = _invoke("start", "--cloud")
    assert cloud.exit_code == 1
    assert "reserved" in cloud.stderr and "gateway" in cloud.stderr
    app = _invoke("start", "--app-path", "D:/apps/demo")
    assert app.exit_code == 1
    assert "reserved" in app.stderr

def test_status_json_stays_clean_when_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("status", "--json")
    assert result.exit_code == 0
    assert "\x1b[" not in result.output
    payload = json.loads(result.output)
    assert payload["state"] == "stopped"

def test_stop_and_restart_shorthands(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("start").exit_code == 0
    assert _invoke("restart").exit_code == 0
    assert "running" in _invoke("status").output
    stopped = _invoke("stop")
    assert stopped.exit_code == 0
    assert "stopped" in stopped.output
