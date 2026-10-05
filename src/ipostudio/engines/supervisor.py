"""Single-instance llama.cpp supervision for the core loop.

Spec §5.3 minimal slice; multi-instance, idle unload and auto-tune are P3.
State literals are the §10.2 service states, pinned by the 003 migration's
CHECK constraint.  The database row is the coordination point between
separate CLI processes: `start` spawns and exits (the engine is intentionally
orphaned — no platform-specific detach APIs, R1), later `stop`/`status` runs
trust the row plus a live health probe.

Known M0' limitation, symmetric on all three platforms: closing the terminal
that started the server may take the engine down with it; the durable
background service is P3 scope (ADR-004)."""

import json
import logging
import os
import signal
import socket
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ipostudio.logs import LOGGER_NAME, redact_text

logger = logging.getLogger(LOGGER_NAME)

SERVICE_STATES = ("stopped", "starting", "loading", "running", "failed")
ENGINE_LOG_FILE = "engine-llama-cpp.log"  # TODO-004 convention: per-process file

_INSTANCE_COLUMNS = (
    "id, engine, engine_version, model_name, model_path, host, port, pid, "
    "state, detail, started_at, stopped_at, created_at, updated_at"
)

@dataclass
class StartOutcome:
    instance: dict
    ok: bool

def engine_log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / ENGINE_LOG_FILE

def _now() -> str:
    # ENG F9: match SQLite datetime('now') formatting so one column never
    # mixes "2026-10-05 08:00:00" and ISO "2026-10-05T08:00:00+00:00"
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

def probe_health(host: str, port: int, timeout_s: float) -> str:
    """'ok' | 'loading' | 'down'.  llama-server answers 503 while the model
    loads and 200 once ready (documented engine behaviour)."""
    import urllib.error
    import urllib.request

    host_part = f"[{host}]" if ":" in host else host
    try:
        with urllib.request.urlopen(
            f"http://{host_part}:{port}/health", timeout=timeout_s
        ) as response:
            return "ok" if response.status == 200 else "down"
    # HTTPError subclasses OSError: this arm must come first
    except urllib.error.HTTPError as exc:
        return "loading" if exc.code == 503 else "down"
    except OSError:
        return "down"

def choose_port(host: str, base_port: int, candidates: int = 20) -> int | None:
    """First bindable port at/after base_port (§5.3: an occupied configured
    port is replaced by a free one whose actual address is displayed; §15
    caps candidate scans at about 20).  The socket family follows the host
    literal so an IPv6 loopback configuration probes IPv6 binds (Codex
    address-family fold); the range is capped at 65536 so a configured port
    of 65535 cannot raise OverflowError on bind (Codex boundary fold)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for port in range(max(base_port, 1), min(base_port + candidates, 65536)):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return None

def _get(conn: sqlite3.Connection, instance_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances WHERE id = ?", (instance_id,)
    ).fetchone()
    return dict(row)

def _touch(
    conn: sqlite3.Connection, instance_id: int, *, expect=None, **fields
) -> bool:
    """Conditional row update.  `expect` restricts the write to rows still
    in one of the given states (Codex race fold): a concurrent `stop` can
    retire a `starting` row and the still-running startup then loses every
    subsequent transition instead of resurrecting the row."""
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = [*fields.values(), _now(), instance_id]
    if expect is None:
        cur = conn.execute(
            f"UPDATE instances SET {assignments}, updated_at = ? WHERE id = ?",
            values,
        )
    else:
        states = ", ".join("?" for _ in expect)
        cur = conn.execute(
            f"UPDATE instances SET {assignments}, updated_at = ? "
            f"WHERE id = ? AND state IN ({states})",
            [*values, *expect],
        )
    conn.commit()
    return cur.rowcount > 0

def _tail(path: Path, lines: int = 15) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(engine log not readable)"
    picked = content.splitlines()[-lines:]
    return redact_text(" | ".join(picked))[:1500]

def _fail_row(
    conn: sqlite3.Connection, instance_id: int, detail: str, *, expect=None
) -> None:
    _touch(conn, instance_id, state="failed", detail=detail[:2000], expect=expect)

def _engine_version(engine: str) -> str:
    """Best-effort `--version` probe: the instance row records WHICH engine
    build served, so argv-compatibility failures are diagnosable later (CEO
    review).  Never fatal — an engine without --version records ""."""
    try:
        proc = subprocess.run(
            [engine, "--version"], capture_output=True, text=True, timeout=5,
            check=False,  # a failing --version still yields data, not an error (ruff PLW1510)
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return first[0][:200] if first else ""

def start_instance(
    conn: sqlite3.Connection,
    argv: list[str],
    *,
    engine: str,
    model_name: str,
    model_path: str,
    host: str,
    port: int,
    log_path: Path,
    timeout_s: float,
    poll_interval: float = 0.5,
    probe=probe_health,
    spawn=subprocess.Popen,
) -> StartOutcome:
    engine_version = _engine_version(argv[0])
    conn.execute(
        "INSERT INTO instances (engine, engine_version, model_name, model_path, "
        "host, port, pid, state, detail) VALUES (?, ?, ?, ?, ?, ?, NULL, "
        "'starting', '')",
        (engine, engine_version, model_name, model_path, host, port),
    )
    conn.commit()
    instance_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def outcome(ok: bool) -> StartOutcome:
        return StartOutcome(_get(conn, instance_id), ok)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_handle = log_path.open("ab")
    except OSError as exc:
        logger.warning("server start failed: cannot open engine log %s: %s",
                       log_path, exc)
        _fail_row(conn, instance_id, f"cannot open engine log {log_path}: {exc}",
                  expect=("starting", "loading"))
        return outcome(False)
    try:
        try:
            proc = spawn(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
            )
        except OSError as exc:
            logger.warning("server start failed: cannot start engine %s: %s",
                           argv[0], exc)
            _fail_row(conn, instance_id, f"cannot start engine {argv[0]}: {exc}",
                      expect=("starting", "loading"))
            return outcome(False)
        _touch(conn, instance_id, pid=proc.pid)
        deadline = time.monotonic() + timeout_s
        observed = "starting"
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    logger.warning(
                        "server start failed: engine exited during startup "
                        "with code %s (instance %s)", proc.returncode, instance_id,
                    )
                    _fail_row(
                        conn, instance_id,
                        f"engine exited during startup with code {proc.returncode}; "
                        f"last log lines: {_tail(log_path)}",
                        expect=("starting", "loading"),
                    )
                    return outcome(False)
                health = probe(host, port, 1.5)
                if health == "ok":
                    # expect=: a concurrent stop must win the race (Codex
                    # fold) — if it retired the row, do not resurrect it
                    if not _touch(conn, instance_id, state="running",
                                  detail="", started_at=_now(),
                                  expect=("starting", "loading")):
                        proc.terminate()
                        return outcome(False)
                    logger.info(
                        "server started: engine=%s model=%s at %s:%s "
                        "(pid %s, instance %s)",
                        engine, model_name, host, port, proc.pid, instance_id,
                    )
                    return outcome(True)
                if health == "loading" and observed != "loading":
                    observed = "loading"
                    if not _touch(conn, instance_id, state="loading",
                                  expect=("starting",)):
                        proc.terminate()
                        return outcome(False)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.warning("server start interrupted (Ctrl+C), instance %s",
                           instance_id)
            proc.terminate()
            _fail_row(conn, instance_id, "startup wait interrupted (Ctrl+C)",
                      expect=("starting", "loading"))
            return outcome(False)
        # Codex orphan fold: a timed-out engine must never outlive a failed
        # start unmanaged — the old flow marked the row failed and left the
        # process running, and `ipo server stop` (active states only) could
        # never reach it
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _signal(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        logger.warning(
            "server start failed: health not ready within %gs; engine "
            "terminated (instance %s)", timeout_s, instance_id,
        )
        _fail_row(
            conn, instance_id,
            f"health check did not report ready within {timeout_s:g}s; the "
            f"engine process was terminated — inspect `ipo server logs`, then "
            f"start again (raise --timeout if the model needs longer to load)",
            expect=("starting", "loading"),
        )
        return outcome(False)
    finally:
        log_handle.close()

def _document_names_model(node: object, model_path: str) -> bool:
    """True when the model path appears inside any string value of the
    decoded /props document.  Matching DECODED strings — never the raw body
    text — is the cross-platform form: JSON escapes the backslashes of
    Windows paths, so a raw-substring check classified every owned Windows
    port as foreign and `ipo server stop` could never stop the engine it
    started (R1; found by the Task 5 end-to-end suite)."""
    if isinstance(node, str):
        return model_path in node
    if isinstance(node, dict):
        return any(
            _document_names_model(value, model_path) for value in node.values()
        )
    if isinstance(node, list):
        return any(_document_names_model(item, model_path) for item in node)
    return False

def probe_identity(
    host: str, port: int, model_path: str, timeout_s: float
) -> str:
    """'owned' | 'foreign' | 'absent' (Codex stop fold).  A health status
    alone cannot prove PID ownership — any 200/503 on the port would
    authorize a kill.  llama-server documents GET /props with the served
    model, so the guard requires the recorded model path to appear in that
    document before any signal is sent.  Residual risk (the recorded PID
    recycled while the port still serves this model) stays with TODO-016."""
    import urllib.error
    import urllib.request

    host_part = f"[{host}]" if ":" in host else host
    try:
        with urllib.request.urlopen(
            f"http://{host_part}:{port}/props", timeout=timeout_s
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return "absent"
    except OSError:
        return "absent"
    try:
        document = json.loads(body)
    except ValueError:
        return "foreign"  # not a props document: ownership stays unproven
    return "owned" if _document_names_model(document, model_path) else "foreign"

def stop_instance(
    conn: sqlite3.Connection,
    *,
    grace_s: float = 10.0,
    poll_interval: float = 0.25,
    probe=probe_health,
    identify=probe_identity,
) -> dict | None:
    """Stop the most recent active instance.  Kill guard (Codex fold): a
    signal is only issued while the recorded port answers /props naming the
    recorded model; a foreign document refuses the stop with manual
    guidance; a silent port sends no signal at all (a blind kill could hit a
    recycled PID).  State writes are conditional on the row still being
    active, so a concurrent start cannot resurrect a stopped row.
    os.kill is the cross-platform API: POSIX sends SIGTERM, Windows maps it
    to TerminateProcess (no graceful shutdown there — ADR-010 backlog)."""
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances "
        "WHERE state IN ('starting','loading','running') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    instance = dict(row)
    pid = instance["pid"]
    detail = instance["detail"]
    if pid is not None:
        identity = identify(instance["host"], instance["port"],
                            instance["model_path"], 2.0)
        if identity == "owned":
            logger.info("server stop: signaling pid %s (instance %s)",
                        pid, instance["id"])
            _signal(pid, signal.SIGTERM)
            deadline = time.monotonic() + grace_s
            # grace wait keys on the health probe going down (the process
            # stopped serving), not on /props: a graceful engine may stop
            # answering before its port closes, and an injected identity
            # that stays "owned" must not turn one stop into two signals
            while time.monotonic() < deadline:
                if probe(instance["host"], instance["port"], 1.0) == "down":
                    break
                time.sleep(poll_interval)
            else:
                _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        elif identity == "foreign":
            logger.warning(
                "server stop refused: port answers with a different model "
                "document (instance %s, pid %s)", instance["id"], pid,
            )
            _touch(
                conn, instance["id"],
                detail=(detail + "; " if detail else "") + (
                    "port answers with a different model document — verify "
                    f"PID {pid} manually before any manual termination"
                ),
                expect=("starting", "loading", "running"),
            )
            return _get(conn, instance["id"])
        else:  # absent: nothing serves the recorded port
            detail = (detail + "; " if detail else "") + (
                "port not answering; no stop signal was sent (identity "
                f"unprovable) — if a process remains, check PID {pid} manually"
            )
    _touch(
        conn, instance["id"], state="stopped", stopped_at=_now(),
        detail=detail, expect=("starting", "loading", "running"),
    )
    logger.info("server stopped: instance %s (model %s)",
                instance["id"], instance["model_name"])
    return _get(conn, instance["id"])

def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except OSError:
        pass  # already gone — the conditional state write is what matters
