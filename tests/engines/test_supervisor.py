import signal
import socket
import sys
import time
from pathlib import Path

from ipostudio.engines import supervisor
from ipostudio.engines.repo import (
    active_instance,
    get_instance,
    last_completion,
    recent_instances,
    record_completion,
)
from ipostudio.engines.supervisor import (
    choose_port,
    engine_log_path,
    probe_health,
    start_instance,
    stop_instance,
)
from ipostudio.store.database import migrate, open_db

FAKE = Path(__file__).parent / "fake_llama_server.py"

def _db(tmp_path):
    conn = open_db(tmp_path / "app.db")
    migrate(conn)
    return conn

class _FakeProc:
    def __init__(self, exit_code=None):
        self.pid = 424242
        self.returncode = exit_code
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

def _spawned_kwargs(tmp_path, proc, probe):
    return {
        "engine": "llama.cpp", "model_name": "m", "model_path": "m.gguf",
        "host": "127.0.0.1", "port": 1, "log_path": tmp_path / "engine.log",
        "timeout_s": 1.0, "poll_interval": 0.01, "probe": probe,
        "spawn": lambda *a, **k: proc,
    }

def test_choose_port_skips_occupied_and_bounds_candidates():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy = sock.getsockname()[1]
        picked = choose_port("127.0.0.1", busy, candidates=3)
        assert picked is not None and picked != busy
        assert busy < picked < busy + 3
    assert choose_port("256.256.256.256", 1, candidates=1) is None

def test_probe_health_reports_down_without_listener():
    assert probe_health("127.0.0.1", 1, 0.2) == "down"

def test_probe_health_sees_real_503_as_loading(tmp_path):
    # ENG F11: the 503->"loading" mapping must hold over real HTTP, not just
    # injected lambdas — a regression here makes slow-loading models un-startable
    import subprocess

    port = choose_port("127.0.0.1", 18800)
    # the delay must comfortably exceed interpreter startup, or the first
    # successful probe could jump past the 503 window straight to "ok"
    proc = subprocess.Popen(
        [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
         "--load-delay", "3"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # the spawn races the fake server's own interpreter startup: an
        # immediate probe can hit the unbound port and read "down" on a slow
        # start (the suite's one real flake) — poll until the port answers
        # at all, bounded, then pin the observed mapping
        state = probe_health("127.0.0.1", port, 1.0)
        deadline = time.monotonic() + 5
        while state == "down" and time.monotonic() < deadline:
            time.sleep(0.05)
            state = probe_health("127.0.0.1", port, 1.0)
        assert state == "loading"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and probe_health(
            "127.0.0.1", port, 0.5
        ) != "ok":
            time.sleep(0.05)
        assert probe_health("127.0.0.1", port, 0.5) == "ok"
    finally:
        proc.terminate()
        proc.wait(timeout=10)

def test_start_instance_reaches_running(tmp_path):
    conn = _db(tmp_path)
    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    assert outcome.ok is True
    assert outcome.instance["state"] == "running"
    assert outcome.instance["pid"] == 424242
    conn.close()

def test_start_instance_records_loading_transition(tmp_path):
    conn = _db(tmp_path)
    sequence = iter(["loading", "loading", "ok"])
    outcome = start_instance(
        conn, ["engine"],
        **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: next(sequence))
    )
    assert outcome.ok is True
    assert get_instance(conn, outcome.instance["id"])["state"] == "running"
    conn.close()

def test_start_instance_engine_exit_marks_failed_with_log_tail(tmp_path):
    conn = _db(tmp_path)
    log = tmp_path / "engine.log"
    log.write_text("boom: bad model shape\n", encoding="utf-8")
    kwargs = _spawned_kwargs(tmp_path, _FakeProc(exit_code=1), lambda *a: "down")
    kwargs["log_path"] = log
    outcome = start_instance(conn, ["engine"], **kwargs)
    assert outcome.ok is False
    assert outcome.instance["state"] == "failed"
    assert "exited during startup" in outcome.instance["detail"]
    assert "bad model shape" in outcome.instance["detail"]
    conn.close()

def test_start_instance_timeout_marks_failed(tmp_path):
    conn = _db(tmp_path)
    proc = _FakeProc()
    outcome = start_instance(
        conn, ["engine"],
        **_spawned_kwargs(tmp_path, proc, lambda *a: "loading")
    )
    assert outcome.ok is False
    assert "was terminated" in outcome.instance["detail"]
    assert proc.terminated is True  # Codex orphan fold: no unmanaged engine
    conn.close()

def test_start_instance_spawn_failure_marks_failed(tmp_path):
    conn = _db(tmp_path)

    def _raising_spawn(*args, **kwargs):
        raise FileNotFoundError("missing engine")

    kwargs = _spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "down")
    kwargs["spawn"] = _raising_spawn
    outcome = start_instance(conn, ["missing-engine"], **kwargs)
    assert outcome.ok is False
    assert "cannot start engine" in outcome.instance["detail"]
    conn.close()

def test_start_fail_write_loses_race_to_concurrent_stop(tmp_path):
    # Fail-writes are expect-guarded: a concurrent stop that already retired
    # the row to `stopped` must win, and the startup's failure write must
    # neither flip it to `failed` nor resurrect it.  The stop is injected
    # inside `spawn` so the row is deterministically `stopped` when the
    # failure path fires (state-machine pre-seeding, not sleep timing).
    conn = _db(tmp_path)

    def retiring_spawn(*args, **kwargs):
        stop_instance(conn, identify=lambda *a, **k: "absent")
        raise FileNotFoundError("missing engine")

    kwargs = _spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "down")
    kwargs["spawn"] = retiring_spawn
    outcome = start_instance(conn, ["missing-engine"], **kwargs)
    assert outcome.ok is False
    row = get_instance(conn, outcome.instance["id"])
    assert row["state"] == "stopped"  # the concurrent stop stays retired
    assert row["detail"] == ""  # the lost fail-write left the row untouched
    conn.close()

def test_start_instance_with_real_fake_engine_end_to_end(tmp_path):
    conn = _db(tmp_path)
    port = choose_port("127.0.0.1", 18300)
    assert port is not None
    argv = [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
            "--model", "fake.gguf"]
    stopped = None
    try:
        outcome = start_instance(
            conn, argv, engine="llama.cpp", model_name="fake", model_path="fake.gguf",
            host="127.0.0.1", port=port, log_path=tmp_path / "logs" / "engine.log",
            timeout_s=20, poll_interval=0.05,
        )
        assert outcome.ok is True
        assert outcome.instance["state"] == "running"
        assert probe_health("127.0.0.1", port, 1.0) == "ok"
        # ENG F12: the recorded engine build must be non-empty (argv[0] is
        # sys.executable, whose --version really runs)
        assert get_instance(conn, outcome.instance["id"])["engine_version"]
    finally:
        stopped = stop_instance(conn, grace_s=10, poll_interval=0.05)
    assert stopped is not None
    assert stopped["state"] == "stopped"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and probe_health("127.0.0.1", port, 0.5) != "down":
        time.sleep(0.05)
    assert probe_health("127.0.0.1", port, 0.5) == "down"
    conn.close()

def test_stop_instance_without_active_returns_none(tmp_path):
    conn = _db(tmp_path)
    assert stop_instance(conn) is None
    conn.close()

def test_stop_sends_no_signal_when_identity_absent(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    stopped = stop_instance(conn, identify=lambda *a, **k: "absent")
    assert stopped["state"] == "stopped"
    assert kills == []  # Codex fold: no blind kill on an unproven identity
    assert "no stop signal was sent" in stopped["detail"]
    conn.close()

def test_stop_refuses_signal_when_identity_foreign(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    stopped = stop_instance(conn, identify=lambda *a, **k: "foreign")
    assert kills == []  # a foreign document on the port must never be killed
    assert stopped["state"] == "running"  # refusal leaves the row honest
    assert "different model document" in stopped["detail"]
    conn.close()

def test_stop_signals_once_identity_confirms(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append(sig))
    stopped = stop_instance(conn, identify=lambda *a, **k: "owned")
    assert stopped["state"] == "stopped"
    assert kills == [signal.SIGTERM]
    conn.close()

def test_probe_identity_matches_escaped_windows_paths():
    # regression (Task 5 e2e finding): the /props body JSON-escapes the
    # backslashes of Windows paths, so matching the RAW body text classified
    # every owned Windows port as foreign and stop could never kill the
    # engine it started.  The check must see the DECODED document — on every
    # platform (R1), hence this deterministic loopback fixture.
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    win_path = "C:\\models\\tiny-q4.gguf"
    body = json.dumps({"model_path": win_path}).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            assert supervisor.probe_identity(host, port, win_path, 2.0) == "owned"
            assert supervisor.probe_identity(host, port, "C:\\other.gguf", 2.0) == "foreign"
        finally:
            httpd.shutdown()
        thread.join(timeout=5)

def test_concurrent_stop_cancels_start(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append(sig))
    proc = _FakeProc()
    raced = {"done": False}

    def racing_probe(*a):
        if not raced["done"]:
            raced["done"] = True
            stop_instance(conn, identify=lambda *a, **k: "absent")
        return "loading"

    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, proc, racing_probe)
    )
    assert outcome.ok is False
    assert proc.terminated is True  # the loser of the race cleans up
    row = get_instance(conn, outcome.instance["id"])
    assert row["state"] == "stopped"  # and never resurrects the row
    conn.close()

def test_stop_instance_escalates_to_kill_after_grace(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []

    def _kill(pid, sig):
        kills.append(sig)

    monkeypatch.setattr(supervisor.os, "kill", _kill)

    def always_up(*args):
        return "ok" if len(kills) < 2 else "down"

    stop_instance(
        conn, grace_s=0.05, poll_interval=0.01,
        probe=always_up, identify=lambda *a, **k: "owned",
    )
    assert len(kills) == 2  # SIGTERM then the SIGKILL-equivalent escalation
    conn.close()

def test_active_instance_prefers_latest(tmp_path):
    conn = _db(tmp_path)
    first = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    ).instance
    second = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    ).instance
    assert active_instance(conn)["id"] == second["id"]
    stop_instance(conn, identify=lambda *a, **k: "owned")
    # stop is latest-first: the older row must still be active here
    # (Codex determinism fold: the old assertion expected None wrongly)
    assert active_instance(conn)["id"] == first["id"]
    stop_instance(conn, identify=lambda *a, **k: "owned")
    assert active_instance(conn) is None
    assert [row["id"] for row in recent_instances(conn)] == [second["id"], first["id"]]
    conn.close()

def test_completion_records_roundtrip(tmp_path):
    conn = _db(tmp_path)
    instance = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    ).instance
    record_completion(
        conn, instance_id=instance["id"], model_name="m",
        prompt_chars=5, output_chars=7, duration_ms=12, status="ok",
    )
    record_completion(
        conn, instance_id=instance["id"], model_name="m",
        prompt_chars=1, output_chars=0, duration_ms=3, status="error",
        detail="boom",
    )
    latest = last_completion(conn)
    assert latest["status"] == "error" and latest["detail"] == "boom"
    # restart-visible: a fresh connection sees the same rows (M0' slice proof)
    conn.close()
    fresh = open_db(tmp_path / "app.db")
    assert last_completion(fresh)["status"] == "error"
    fresh.close()

def test_service_states_match_migration_check(tmp_path):
    conn = _db(tmp_path)
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'instances'"
    ).fetchone()[0]
    for state in supervisor.SERVICE_STATES:
        assert f"'{state}'" in sql
    conn.close()

def test_engine_log_path_is_per_process_named(tmp_path):
    assert engine_log_path(tmp_path) == tmp_path / "logs" / "engine-llama-cpp.log"


def test_lifecycle_and_completions_are_recorded_in_the_app_log(tmp_path, monkeypatch):
    """Phase-1 E2E finding: the app log (ADR-006) was never wired, so server
    lifecycle events existed only as terminal lines.  With the log installed,
    start/stop/completion seams must leave records in it."""
    from ipostudio.logs import log_file_path, setup_logging

    setup_logging(tmp_path, console=False)
    conn = _db(tmp_path)
    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    assert outcome.ok is True
    record_completion(
        conn, instance_id=outcome.instance["id"], model_name="m",
        prompt_chars=1, output_chars=1, duration_ms=2, status="ok",
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append(sig))
    stopped = stop_instance(
        conn, identify=lambda *a, **k: "owned", probe=lambda *a, **k: "down"
    )
    assert stopped is not None and stopped["state"] == "stopped"
    conn.close()

    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "server started" in content
    assert "completion recorded" in content
    assert "server stopped" in content
