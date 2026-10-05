"""Targeted phase-3 gaps for the engine surface.

Pins the branches the core-loop suites never reached: port-boundary and
address-family selection, health/identity probe arms against non-HTTP,
non-503 and non-JSON responders, the log-open failure and Ctrl+C arms of
`start_instance`, the NULL-pid stop path, redaction/truncation at the
persistence boundary, and the HTTP-500 / bad-JSON arms of the chat client.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from click.testing import CliRunner

from ipostudio.cli.main import cli
from ipostudio.engines import supervisor
from ipostudio.engines.openai_client import ChatError, chat_completion
from ipostudio.engines.repo import get_instance, last_completion, record_completion
from ipostudio.engines.supervisor import (
    choose_port,
    probe_health,
    probe_identity,
    start_instance,
    stop_instance,
)
from ipostudio.store.database import migrate, open_db


def _db(tmp_path):
    conn = open_db(tmp_path / "app.db")
    migrate(conn)
    return conn


class _FakeProc:
    def __init__(self):
        self.pid = 424242
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


class _Exiter:
    """A process object that is already dead: the startup loop must see the
    nonzero exit on its first poll and take the engine-exit failure path."""

    pid = 424242
    returncode = 1

    def poll(self):
        return self.returncode

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return self.returncode


def _spawned_kwargs(tmp_path, proc, probe):
    return {
        "engine": "llama.cpp", "model_name": "m", "model_path": "m.gguf",
        "host": "127.0.0.1", "port": 1, "log_path": tmp_path / "engine.log",
        "timeout_s": 1.0, "poll_interval": 0.01, "probe": probe,
        "spawn": lambda *a, **k: proc,
    }


def _http_server(handler):
    """ThreadingHTTPServer on an ephemeral port; returns (server, thread)."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_choose_port_survives_the_65535_boundary_and_zero_base():
    # a configured port of 65535 used to risk OverflowError on bind (Codex
    # boundary fold): the candidate range must cap at 65536 and never raise
    assert choose_port("127.0.0.1", 65535, candidates=20) in (65535, None)
    assert choose_port("127.0.0.1", 0, candidates=2) in (1, 2)


def test_choose_port_probes_ipv6_loopback():
    picked = choose_port("::1", 19600, candidates=5)
    assert picked is not None and picked >= 19600  # AF_INET6 family branch
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
        sock.bind(("::1", picked))  # the picked port was genuinely bindable


def test_probe_health_against_non_http_listener_is_down():
    # a port that accepts and slams the connection shut must read "down",
    # not crash the probe (RemoteDisconnected is an OSError subclass)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        threading.Thread(target=lambda: sock.accept()[0].close(), daemon=True).start()
        assert probe_health("127.0.0.1", port, 1.0) == "down"


def test_probe_targets_loopback_for_the_unspecified_address():
    # 0.0.0.0 is a bind wildcard, never a destination: the probe must connect
    # to loopback or a `--host 0.0.0.0` start can never pass its own health
    # check on Windows (connect refused with a WSAEADDRNOTAVAIL-class error)
    class Ok(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server, thread = _http_server(Ok)
    try:
        _host, port = server.server_address
        assert probe_health("0.0.0.0", port, 1.0) == "ok"
    finally:
        server.shutdown()
    thread.join(timeout=5)


def test_probe_health_non_503_http_error_is_down():
    class NotFound(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass

    server, thread = _http_server(NotFound)
    try:
        host, port = server.server_address
        assert probe_health(host, port, 1.0) == "down"
    finally:
        server.shutdown()
    thread.join(timeout=5)


def test_probe_identity_garbage_body_is_foreign_and_404_is_absent():
    # a 200 body that is not a props document proves nothing (foreign); an
    # HTTP error on /props means nothing serves THIS model (absent)
    class SplitResponder(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/props":
                self.send_response(200)
                self.send_header("Content-Length", "5")
                self.end_headers()
                self.wfile.write(b"not json")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    server, thread = _http_server(SplitResponder)
    try:
        host, port = server.server_address
        assert probe_identity(host, port, "m.gguf", 1.0) == "foreign"
        assert probe_identity(host, port + 1, "m.gguf", 1.0) == "absent"
    finally:
        server.shutdown()
    thread.join(timeout=5)


def test_start_instance_log_open_failure_marks_failed(tmp_path):
    # the engine log path is blocked by a regular file: start must land a
    # failed row carrying the reason, never a traceback
    conn = _db(tmp_path)
    blocker = tmp_path / "blocked.log"
    blocker.write_bytes(b"x")
    kwargs = _spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "down")
    kwargs["log_path"] = blocker / "engine.log"  # parent is a file -> OSError
    outcome = start_instance(conn, ["engine"], **kwargs)
    assert outcome.ok is False
    assert outcome.instance["state"] == "failed"
    assert "cannot open engine log" in outcome.instance["detail"]
    conn.close()


def test_start_instance_keyboard_interrupt_marks_failed_and_terminates(tmp_path):
    conn = _db(tmp_path)
    proc = _FakeProc()

    def interrupted_probe(*a):
        raise KeyboardInterrupt

    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, proc, interrupted_probe)
    )
    assert outcome.ok is False
    assert proc.terminated is True  # the engine never outlives a failed start
    row = get_instance(conn, outcome.instance["id"])
    assert row["state"] == "failed"
    assert "interrupted" in row["detail"]
    conn.close()


def test_engine_exit_detail_is_redacted_and_tolerates_bad_utf8(tmp_path):
    # the log tail is third-party text landing in the failure detail: it must
    # pass through redact_text (secrets never persist) and errors="replace"
    conn = _db(tmp_path)
    log = tmp_path / "engine.log"
    log.write_bytes(
        b"api_key=supersecretvalue123\n"
        b"Bearer abcd1234efgh5678\n"
        b"boom: \xff\xfe invalid utf8 tail\n"
    )
    kwargs = _spawned_kwargs(tmp_path, _Exiter(), lambda *a: "down")
    kwargs["log_path"] = log
    outcome = start_instance(conn, ["engine"], **kwargs)
    assert outcome.ok is False
    detail = outcome.instance["detail"]
    assert "supersecretvalue123" not in detail
    assert "abcd1234efgh5678" not in detail
    assert "invalid utf8" in detail  # replacement chars, never a crash
    conn.close()


def test_stop_instance_with_null_pid_marks_stopped_without_signal(tmp_path, monkeypatch):
    # a row can be active with no pid yet (spawn crashed first): stop must
    # retire it honestly without probing or signaling anything
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO instances (engine, model_name, model_path, host, port, "
        "pid, state, detail) VALUES ('llama.cpp', 'm', 'm.gguf', '127.0.0.1', "
        "1, NULL, 'loading', '')"
    )
    conn.commit()
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append(sig))
    stopped = stop_instance(conn)
    assert stopped is not None and stopped["state"] == "stopped"
    assert kills == []  # no pid -> no probe, no signal
    conn.close()


def test_record_completion_redacts_and_truncates_at_2000(tmp_path):
    # redaction happens at the persistence boundary, and every stored text
    # column is capped at 2000 chars regardless of input size
    conn = _db(tmp_path)
    conn.execute(
        "INSERT INTO instances (engine, model_name, model_path, host, port, "
        "pid, state, detail) VALUES ('llama.cpp', 'm', 'm.gguf', '127.0.0.1', "
        "1, 9, 'running', '')"
    )
    conn.commit()
    secret = "Bearer abcd1234efgh5678"
    record_completion(
        conn, instance_id=1, model_name="m",
        prompt_text=f"{secret} {'x' * 3000}",
        output_text="y" * 3000,
        prompt_chars=3100, output_chars=3000, duration_ms=5, status="ok",
        detail="failed after api_key=supersecretvalue123",
    )
    stored = last_completion(conn)
    assert len(stored["prompt_text"]) == 2000
    assert len(stored["output_text"]) == 2000
    assert secret not in stored["prompt_text"]
    assert "supersecretvalue123" not in stored["detail"]
    conn.close()


def test_chat_completion_http_500_raises_chat_error():
    class Erroring(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = b'{"error": "sk-abcdef1234567890 exploded"}'
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server, thread = _http_server(Erroring)
    try:
        host, port = server.server_address
        with pytest.raises(ChatError) as excinfo:
            chat_completion(
                host, port, model="m", prompt="hi", temperature=0.2, top_p=0.9,
                top_k=40, repeat_penalty=1.1, timeout_s=5,
            )
    finally:
        server.shutdown()
    thread.join(timeout=5)
    message = str(excinfo.value)
    assert "HTTP 500" in message
    assert "server logs" in message  # remediation clause
    assert "sk-abcdef1234567890" not in message  # error detail is redacted


def test_chat_completion_non_json_200_raises_chat_error():
    class Garbage(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"not json")

        def log_message(self, *args):
            pass

    server, thread = _http_server(Garbage)
    try:
        host, port = server.server_address
        with pytest.raises(ChatError) as excinfo:
            chat_completion(
                host, port, model="m", prompt="hi", temperature=0.2, top_p=0.9,
                top_k=40, repeat_penalty=1.1, timeout_s=5,
            )
    finally:
        server.shutdown()
    thread.join(timeout=5)
    assert "not valid JSON" in str(excinfo.value)


def test_chat_completion_brackets_ipv6_hosts():
    # an IPv6 host literal must become [::1] in the URL (host_part branch)
    class V6(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    class Echo(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            payload = json.dumps({
                "choices": [
                    {"message": {"content": "echo:" + body["messages"][0]["content"]}}
                ]
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = V6(("::1", 0), Echo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]  # AF_INET6 address is a 4-tuple
        payload = chat_completion(
            "::1", port, model="m", prompt="hi", temperature=0.2, top_p=0.9,
            top_k=40, repeat_penalty=1.1, timeout_s=5,
        )
        assert payload["choices"][0]["message"]["content"] == "echo:hi"
    finally:
        server.shutdown()
    thread.join(timeout=5)


def test_probe_health_silent_listener_times_out_as_down():
    # the third down-arm: a listener that accepts and never answers must
    # read "down" within the probe timeout, not hang the startup loop
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        held = []

        def accept_and_hold():
            try:
                held.append(sock.accept()[0])
            except OSError:
                pass

        threading.Thread(target=accept_and_hold, daemon=True).start()
        started = time.monotonic()
        assert probe_health("127.0.0.1", port, 0.3) == "down"
        assert time.monotonic() - started < 5
    for conn in held:
        conn.close()


def test_chat_completion_silent_server_times_out_as_chat_error():
    # a hung engine must surface as a ChatError naming the reach problem —
    # never an unhandled socket.timeout traceback from the chat command
    class Silent(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            time.sleep(1.5)  # outlives the client timeout below

        def log_message(self, *args):
            pass

    server, thread = _http_server(Silent)
    try:
        host, port = server.server_address
        started = time.monotonic()
        with pytest.raises(ChatError) as excinfo:
            chat_completion(
                host, port, model="m", prompt="hi", temperature=0.2, top_p=0.9,
                top_k=40, repeat_penalty=1.1, timeout_s=0.3,
            )
        assert time.monotonic() - started < 5
    finally:
        server.shutdown()
    thread.join(timeout=5)
    assert "cannot reach" in str(excinfo.value)


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_chat_completion_rejects_nonpositive_and_nonfinite_timeouts(bad):
    # an invalid timeout is caller error at the library seam: it must raise
    # the user-safe ChatError, not leak socket's ValueError ("Timeout value
    # out of range") or, worse, misattribute it to "not valid JSON" / hang
    # forever (inf passes settimeout and never comes back)
    with pytest.raises(ChatError) as excinfo:
        chat_completion(
            "127.0.0.1", 1, model="m", prompt="hi", temperature=0.2, top_p=0.9,
            top_k=40, repeat_penalty=1.1, timeout_s=bad,
        )
    assert "finite positive" in str(excinfo.value)


def test_stop_shorthand_reports_refusal_on_foreign_identity(tmp_path, monkeypatch):
    # CLI seam (eb5191f): a refused stop must meet the error contract
    # (exit 1, problem + guidance on stderr) instead of claiming success
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    from ipostudio.cli import server_cmd

    monkeypatch.setattr(
        server_cmd, "stop_instance",
        lambda conn, **k: {
            "state": "running", "model_name": "m", "host": "127.0.0.1",
            "port": 1,
            "detail": "port answers with a different model document",
        },
    )
    result = CliRunner().invoke(cli, ["server", "stop"])
    assert result.exit_code == 1
    assert "stop refused" in result.stderr
    assert "different model document" in result.stderr
