"""SQLite connection defaults and forward-only versioned migrations (ADR-002)."""

import sqlite3
from importlib import resources
from pathlib import Path

_MIGRATIONS_PACKAGE = "ipostudio.store.migrations"


class _Connection(sqlite3.Connection):
    """Connection produced by open_db(); remembers migrations that failed on it.

    sqlite3.Connection itself is neither weakref-able nor attribute-settable,
    so open_db() installs this subclass to carry the per-connection failure
    memory used by migrate().
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.failed_migrations: set[str] = set()


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, factory=_Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migration_files() -> list[tuple[str, str]]:
    entries = resources.files(_MIGRATIONS_PACKAGE).iterdir()
    named = sorted(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in entries
        if entry.name.endswith(".sql")
    )
    return named


class MigrationFailure(sqlite3.Error):
    """A migration script failed; its transaction was rolled back."""

    def __init__(self, name: str, cause: Exception) -> None:
        super().__init__(f"migration {name} failed and was rolled back: {cause}")
        self.name = name


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations atomically and race-safe.

    - BEGIN IMMEDIATE takes the write lock BEFORE re-reading the registry, so
      two processes starting migrations concurrently serialize instead of both
      applying the same script (eng review consensus).
    - executescript() force-commits pending transactions, so atomicity of
      "apply script + register it" requires BEGIN/COMMIT inside the script
      text: each pending migration runs as one executescript() of
      BEGIN IMMEDIATE + script + registration INSERT + COMMIT.
    - On failure the open transaction is rolled back explicitly and re-raised
      as MigrationFailure; _migrations stays clean and a retry is safe.  A
      migration that already failed on this connection is skipped by later
      migrate() calls on that same connection (open a fresh connection to
      re-attempt it).
    - Authoring rules: migration files must end with `;` + newline, must not
      contain their own BEGIN/COMMIT, and must not end with a `--` comment
      (the runner concatenates each script between BEGIN and COMMIT).
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT UNIQUE NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    failed: set[str] | None = getattr(conn, "failed_migrations", None)
    applied: list[str] = []
    for name, script in migration_files():
        if failed is not None and name in failed:
            continue
        conn.executescript("BEGIN IMMEDIATE;\n")
        try:
            registered = conn.execute(
                "SELECT 1 FROM _migrations WHERE name = ?", (name,)
            ).fetchone()
            if registered:
                conn.execute("COMMIT")
                continue
            # name is a package-controlled ASCII filename; repr() is a safe SQL
            # literal.  The wrapping executescript() force-commits the read
            # transaction opened above, so the script text opens its own write
            # transaction, keeping apply + registration atomic.
            conn.executescript(
                "BEGIN IMMEDIATE;\n"
                + script
                + f"INSERT INTO _migrations(name) VALUES ({name!r});\nCOMMIT;\n"
            )
        except sqlite3.Error as exc:
            conn.rollback()
            if failed is not None:
                failed.add(name)
            raise MigrationFailure(name, exc) from exc
        applied.append(name)
    return applied


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
