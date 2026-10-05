"""Repository functions for the models table (ADR-002: SQL stays auditable,
no ORM)."""

import sqlite3
from pathlib import Path

from ipostudio.catalog.scan import ModelFile

_UPSERT = """
INSERT INTO models (name, path, format, size_bytes, parts, category, source, updated_at)
VALUES (?, ?, ?, ?, ?, 'chat', 'scan', datetime('now'))
ON CONFLICT(path) DO UPDATE SET
    name = excluded.name,
    size_bytes = excluded.size_bytes,
    parts = excluded.parts,
    updated_at = datetime('now')
"""

_COLUMNS = (
    "id, name, path, format, size_bytes, parts, category, source, first_seen, updated_at"
)

def upsert_models(conn: sqlite3.Connection, files: list[ModelFile]) -> None:
    with conn:
        conn.executemany(
            _UPSERT,
            [(f.name, str(f.path), f.format, f.size_bytes, f.parts) for f in files],
        )

def list_models(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM models ORDER BY name, path").fetchall()
    return [dict(row) for row in rows]

def find_model(conn: sqlite3.Connection, ident: str) -> list[dict]:
    """Resolve a user-typed identifier to catalog rows: exact name, then
    exact path, then path-suffix match.  All candidates come back so the
    caller can distinguish missing from ambiguous."""
    def query(where: str, param: str) -> list[dict]:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM models WHERE {where} ORDER BY name, path",
            (param,),
        ).fetchall()
        return [dict(row) for row in rows]

    exact_name = query("name = ?", ident)
    if exact_name:
        return exact_name
    exact_path = query("path = ?", ident)
    if not exact_path:
        # separator-normalized exact path: a user can type the SAME stored
        # path with forward slashes (shells, configs, copy-paste), and the
        # byte-exact SQL arm above must not turn that into a false "no local
        # model matches".  Both sides go through as_posix() (R1-clean
        # normalization; os.path is out of bounds in src/).
        normalized = ident.replace("\\", "/").strip("/")
        if normalized:
            exact_path = [
                row for row in list_models(conn)
                if Path(row["path"]).as_posix() == normalized
            ]
    if exact_path:
        return exact_path
    # Component-aware suffix match, computed in Python: user-supplied % and _
    # can never act as wildcards, and a bare directory name ("nested") matches
    # .../nested/beta.gguf because the ident equals one of the path parts.
    # The catalog is capped at MAX_SCAN_ENTRIES, so a full scan stays bounded.
    needle = ident.replace("\\", "/").strip("/")
    if not needle:
        return []
    matches = []
    for row in list_models(conn):
        posix = Path(row["path"]).as_posix()
        if needle in Path(row["path"]).parts or posix.endswith("/" + needle):
            matches.append(row)
    return matches
