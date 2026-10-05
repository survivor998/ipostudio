"""Repository functions for instances and completions (ADR-002).

Dependency direction: SERVICE_STATES and the row primitives live in
supervisor.py; this module adds the query/insert surface and never gets
imported by the supervisor (no cycle)."""

import logging
import sqlite3

from ipostudio.engines.supervisor import SERVICE_STATES
from ipostudio.logs import LOGGER_NAME, redact_text

logger = logging.getLogger(LOGGER_NAME)

__all__ = [
    "SERVICE_STATES",
    "active_instance",
    "get_instance",
    "last_completion",
    "recent_instances",
    "record_completion",
]

_INSTANCE_COLUMNS = (
    "id, engine, engine_version, model_name, model_path, host, port, pid, "
    "state, detail, started_at, stopped_at, created_at, updated_at"
)

def get_instance(conn: sqlite3.Connection, instance_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances WHERE id = ?", (instance_id,)
    ).fetchone()
    return dict(row) if row else None

def active_instance(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances "
        "WHERE state IN ('starting','loading','running') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None

def recent_instances(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]

def record_completion(
    conn: sqlite3.Connection,
    *,
    instance_id: int,
    model_name: str,
    prompt_text: str = "",
    output_text: str = "",
    prompt_chars: int,
    output_chars: int,
    duration_ms: int,
    status: str,
    detail: str = "",
) -> None:
    """Persist one completion attempt.  Secret-shaped substrings are
    redacted HERE, at the persistence boundary — display-time redaction
    cannot unsave what was already written (Codex trust fold)."""
    with conn:
        conn.execute(
            "INSERT INTO completions (instance_id, model_name, prompt_text, "
            "output_text, prompt_chars, output_chars, duration_ms, status, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (instance_id, model_name, redact_text(prompt_text)[:2000],
             redact_text(output_text)[:2000], prompt_chars, output_chars,
             duration_ms, status, redact_text(detail)[:2000]),
        )
    logger.info(
        "completion recorded: instance=%s model=%s status=%s chars=%s in %sms",
        instance_id, model_name, status, output_chars, duration_ms,
    )

def last_completion(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id, instance_id, model_name, prompt_text, output_text, "
        "prompt_chars, output_chars, duration_ms, status, detail, created_at "
        "FROM completions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
