"""Targeted phase-3 gaps for the CLI seams.

Pins the error-contract arms and interaction seams the flow tests never
reached: start validation boundaries (port/timeout), blank-prompt refusal,
chat against a non-running state, ghost-row/skip accounting on the models
table, the env-override warning, open_config_and_db's OSError/sqlite arms,
engine-log tailing/redaction, restart-when-stopped, the non-loopback warning,
the incomplete-shard start refusal, and `_human_size` boundaries.
"""

import json
import sys
from pathlib import Path

from click.testing import CliRunner

from ipostudio.cli.main import cli
from ipostudio.cli.models_cmd import _human_size

FAKE = Path(__file__).resolve().parents[1] / "engines" / "fake_llama_server.py"
GGUF = b"GGUF" + b"\x00" * 28


def _invoke(*args):
    return CliRunner().invoke(cli, list(args))


def _catalog_env(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    return tmp_path / "models"


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


def test_server_start_rejects_out_of_range_ports(tmp_path, monkeypatch):
    _catalog_env(tmp_path, monkeypatch)
    for bad in ("0", "70000", "-1"):
        result = _invoke("server", "start", "--port", bad)
        assert result.exit_code == 1, bad
        assert "1..65535" in result.stderr


def test_server_start_rejects_nonpositive_and_nan_timeouts(tmp_path, monkeypatch):
    _catalog_env(tmp_path, monkeypatch)
    for bad in ("0", "-5", "nan", "inf"):
        result = _invoke("server", "start", "--timeout", bad)
        assert result.exit_code == 1, bad
        assert "finite positive" in result.stderr


def test_chat_rejects_blank_prompt_and_blank_stdin(tmp_path, monkeypatch):
    _catalog_env(tmp_path, monkeypatch)
    blank = _invoke("chat", "   ")
    assert blank.exit_code == 1
    assert "empty prompt" in blank.stderr
    piped = CliRunner().invoke(cli, ["chat", "-"], input="  \n\t \n")
    assert piped.exit_code == 1
    assert "empty prompt" in piped.stderr


def test_chat_rejects_nonpositive_and_nonfinite_timeouts(tmp_path, monkeypatch):
    # `server start --timeout` is validated in _run_start; chat's own
    # --timeout must meet the same contract BEFORE any state is touched —
    # a negative value used to leak socket's "not valid JSON" misattribution,
    # and inf hung forever against a live server
    _catalog_env(tmp_path, monkeypatch)
    for bad in ("0", "-5", "nan", "inf"):
        result = _invoke("chat", "--timeout", bad, "hello")
        assert result.exit_code == 1, bad
        assert "finite positive" in result.stderr, bad
        assert "Traceback" not in result.stderr, bad


def test_chat_refuses_when_server_is_loading(tmp_path, monkeypatch):
    # chat must refuse a not-yet-ready instance instead of hanging on a
    # connection the engine cannot answer yet (state != running guard)
    _catalog_env(tmp_path, monkeypatch)
    from ipostudio.store.database import migrate, open_db

    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO instances (engine, model_name, model_path, host, port, "
        "pid, state, detail) VALUES ('llama.cpp', 'tiny-q4', 'tiny-q4.gguf', "
        "'127.0.0.1', 1, NULL, 'loading', '')"
    )
    conn.commit()
    conn.close()
    result = _invoke("chat", "hello")
    assert result.exit_code == 1
    assert "loading" in result.stderr
    assert "not ready" in result.stderr


def test_models_flags_ghost_row_and_counts_skipped(tmp_path, monkeypatch):
    # insert-only catalog: a deleted file stays as a ghost row labelled
    # "(missing)"; corrupt magic is counted in the skipped line — silence
    # must never be free (spec §13)
    root = _catalog_env(tmp_path, monkeypatch)
    (root / "broken.gguf").write_bytes(b"NOPE" + b"\x00" * 32)
    assert _invoke("models").exit_code == 0  # registers tiny-q4 (+ skipped 1)
    (root / "tiny-q4.gguf").unlink()
    result = _invoke("models")
    assert result.exit_code == 0
    assert "(missing)" in result.output
    assert "skipped 1" in result.output


def test_model_select_json_payload_and_env_override_warning(tmp_path, monkeypatch):
    root = _catalog_env(tmp_path, monkeypatch)
    (root / "other.gguf").write_bytes(GGUF + b"\x00" * 36)
    payload = json.loads(_invoke("model", "--select", "tiny-q4", "--json").output)
    assert payload["selected"] == "tiny-q4" and payload["saved"] is True
    # the shell override wins for new commands: the save must say so loudly
    # (human surface; --json returns before the warning — recorded as an
    # observation in the phase-3 report)
    monkeypatch.setenv("IPO_LOCAL_CHAT_MODEL", "other")
    (root / "third.gguf").write_bytes(GGUF + b"\x00" * 36)
    human = _invoke("model", "--select", "third")
    assert human.exit_code == 0, human.stderr
    assert "IPO_LOCAL_CHAT_MODEL" in human.stderr
    assert "overrides" in human.stderr


def test_open_config_and_db_error_arms_meet_the_contract(tmp_path, monkeypatch):
    # open_db_only's arms are pinned elsewhere; these are the SAME two arms
    # on open_config_and_db (the data-layer command seam, eb5191f/ENG F16)
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("IPO_DATA_DIR", str(blocker))
    blocked = _invoke("models")
    assert blocked.exit_code == 1
    assert "error:" in blocked.stderr
    assert "data directory" in blocked.stderr
    assert "Traceback" not in blocked.stderr

    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "not-a-db").mkdir()
    monkeypatch.setenv("IPO_DB_PATH", str(tmp_path / "not-a-db"))
    unavailable = _invoke("models")
    assert unavailable.exit_code == 1
    assert "database unavailable" in unavailable.stderr
    assert "doctor" in unavailable.stderr


def test_json_surfaces_stay_pure_when_the_data_layer_is_unavailable(tmp_path, monkeypatch):
    # --json consumers parse stdout as one document: a data-layer failure
    # must exit 1 via stderr with an EMPTY stdout, never a partial document
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    monkeypatch.setenv("IPO_DATA_DIR", str(blocker))
    for args in (["models", "--json"], ["server", "list", "--json"]):
        result = _invoke(*args)
        assert result.exit_code == 1, args
        assert result.stdout == "", args
        assert "error:" in result.stderr, args


def test_server_logs_missing_file_tail_and_redaction(tmp_path, monkeypatch):
    _catalog_env(tmp_path, monkeypatch)
    empty = _invoke("server", "logs")
    assert empty.exit_code == 0
    assert "no engine log yet" in empty.output

    listing = _invoke("server", "list")
    assert listing.exit_code == 0
    assert "no server instances yet" in listing.output

    from ipostudio.engines.supervisor import engine_log_path

    log = engine_log_path(tmp_path)
    log.parent.mkdir(parents=True, exist_ok=True)  # app logging may own it already
    lines = [f"line-{index:02d}" for index in range(30)]
    lines += ["api_key=supersecretvalue123", "你好 engine", ""]
    log.write_text("\n".join(lines), encoding="utf-8")
    tailed = _invoke("server", "logs", "--lines", "3")
    assert "line-29" in tailed.output and "line-26" not in tailed.output
    full = _invoke("server", "logs")
    assert "你好 engine" in full.output  # utf-8 log survives rendering
    assert "supersecretvalue123" not in full.output  # redacted on display


def test_restart_shorthand_boots_when_nothing_runs(tmp_path, monkeypatch):
    # restart with no active instance: stop_instance returns None and the
    # flow must proceed straight into a successful start (not crash on None)
    _catalog_env(tmp_path, monkeypatch)
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    result = _invoke("restart", "--timeout", "20")
    assert result.exit_code == 0, result.stderr
    assert "running" in _invoke("status").output
    stopped = _invoke("stop")
    assert stopped.exit_code == 0
    assert "stopped" in stopped.output


def test_start_with_non_loopback_host_warns_about_exposure(tmp_path, monkeypatch):
    _catalog_env(tmp_path, monkeypatch)
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    import socket

    # pick a real bindable non-loopback address deterministically: 0.0.0.0
    with socket.socket() as probe:
        probe.bind(("0.0.0.0", 0))
    started = _invoke("server", "start", "--host", "0.0.0.0", "--timeout", "20")
    assert started.exit_code == 0, started.stderr
    assert "UNAUTHENTICATED" in started.stderr
    assert "loopback" in started.stderr
    _invoke("server", "stop")


def test_server_start_refuses_incomplete_shard_family(tmp_path, monkeypatch):
    # insert-only catalog revalidation (Codex stale-row fold): a family that
    # lost a shard AFTER registration must refuse the start with a rescan
    # hint, never surface as a mid-load engine crash
    root = _catalog_env(tmp_path, monkeypatch)
    (root / "shardset-00001-of-00002.gguf").write_bytes(GGUF + b"\x00" * 36)
    (root / "shardset-00002-of-00002.gguf").write_bytes(GGUF + b"\x00" * 36)
    assert _invoke("model", "--select", "shardset").exit_code == 0
    (root / "shardset-00002-of-00002.gguf").unlink()
    _patch_fake_engine(monkeypatch)
    started = _invoke("server", "start", "--timeout", "20")
    assert started.exit_code == 1
    assert "incomplete on disk" in started.stderr
    assert "shard is missing" in started.stderr


def test_human_size_boundaries():
    assert _human_size(0) == "0 B"
    assert _human_size(1023) == "1023 B"
    assert _human_size(1024) == "1.0 KiB"
    assert _human_size(1024**2) == "1.0 MiB"
    assert _human_size(1024**3) == "1.0 GiB"
    assert _human_size(1024**4) == "1.0 TiB"  # the ladder's terminal unit


def test_gbk_piped_streams_render_new_tables_as_valid_utf8(tmp_path):
    # the locale-codec trap on the NEW table surfaces: `models` (name column)
    # and `server list` (model column) must emit UTF-8 through a real
    # subprocess with GBK-forced streams, like doctor already does
    import os
    import subprocess

    root = tmp_path / "models"
    root.mkdir()
    (root / "模型-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    from ipostudio.store.database import migrate, open_db

    (tmp_path / "data").mkdir()
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    conn.execute(
        "INSERT INTO instances (engine, model_name, model_path, host, port, "
        "pid, state, detail) VALUES ('llama.cpp', '模型-q4', '模型-q4.gguf', "
        "'127.0.0.1', 1, 7, 'running', '')"
    )
    conn.commit()
    conn.close()

    env = {k: v for k, v in os.environ.items() if not k.startswith("IPO_")}
    env["PYTHONIOENCODING"] = "gbk"
    env["IPO_DATA_DIR"] = str(tmp_path)
    from ipostudio.engines.supervisor import engine_log_path

    engine_log = engine_log_path(tmp_path)
    engine_log.parent.mkdir(parents=True, exist_ok=True)  # logs/ may not exist yet
    engine_log.write_text(
        "你好 engine log\napi_key=supersecretvalue123\n", encoding="utf-8"
    )
    # the two TABLE surfaces carry the model name through the pipe ...
    for args in (["models"], ["server", "list"]):
        done = subprocess.run(
            [sys.executable, "-m", "ipostudio", *args],
            capture_output=True, env=env, timeout=60, check=False,
        )
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        text = done.stdout.decode("utf-8")  # GBK bytes would break this decode
        assert "模型-q4" in text, args
    # ... and the engine-log tail renders CJK + redaction through the pipe too
    done = subprocess.run(
        [sys.executable, "-m", "ipostudio", "server", "logs"],
        capture_output=True, env=env, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    logs_text = done.stdout.decode("utf-8")  # GBK bytes would break this decode
    assert "你好 engine log" in logs_text
    assert "supersecretvalue123" not in logs_text  # redacted on display


def test_managed_flag_in_extras_fails_through_both_shorthands(tmp_path, monkeypatch):
    # eb5191f claim: the managed-flag _fail lives in _run_start, so BOTH
    # shorthands share the contract — verify it end to end with the real
    # argv builder (only the engine lookup is patched; stubbing the builder
    # would bypass the ValueError under test)
    _catalog_env(tmp_path, monkeypatch)
    from ipostudio.cli import server_cmd

    monkeypatch.setattr(
        server_cmd, "resolve_engine",
        lambda configured: (Path(sys.executable), None),
    )
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    runner = CliRunner()
    assert runner.invoke(
        cli, ["config", "set", "llama_cpp_extra_args", '["--port=1"]']
    ).exit_code == 0
    restarted = _invoke("restart")
    assert restarted.exit_code == 1
    assert "managed flag" in restarted.stderr
    assert "Traceback" not in restarted.stderr
    started = _invoke("start")
    assert started.exit_code == 1
    assert "managed flag" in started.stderr
    # the contract must hold BEFORE any process/state change: nothing runs
    listing = json.loads(_invoke("server", "list", "--json").output)
    assert all(row["state"] != "running" for row in listing["instances"])
