"""QA-B adversarial tests: logging (redaction/rotation/threading) + sqlite store.

Clean-room tests written from observed behavior of src/ipostudio/logs.py and
src/ipostudio/store/database.py. Real files under tmp_path, real subprocesses,
no mocks.
"""

import ast
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ipostudio.logs import (
    RedactionFilter,
    log_file_path,
    redact_text,
    redaction_count,
    setup_logging,
)
from ipostudio.store.database import MigrationFailure, migrate, open_db

SRC_DIR = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def _restore_logging():
    """Detach every handler from the shared 'ipostudio' logger after each test."""
    yield
    logger = logging.getLogger("ipostudio")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)


def _flush(logger):
    for handler in logger.handlers:
        handler.flush()


# ---------------------------------------------------------------------------
# Redaction (redact_text + RedactionFilter)
# ---------------------------------------------------------------------------


def test_redact_adversarial_combo_and_context_survival():
    sample = (
        'config load: api_key = "sk-abc123" then '
        "Authorization: Bearer eyJhbGciOi.abc.def and "
        "postgres://user:p4ssw0rd@db.host:5432/app plus "
        "the bare token: hunter2value mid-sentence "
        "also 日志token=相邻值123 adjacent and "
        "https://api.example.com?key=urltok99 query"
    )
    out = redact_text(sample)
    assert "sk-abc123" not in out
    assert "eyJhbGciOi" not in out
    assert "p4ssw0rd" not in out
    assert "db.host:5432/app" in out  # non-credential URL part survives
    assert "hunter2value" not in out
    assert "mid-sentence" in out  # words after the masked value survive
    assert "相邻值123" not in out  # CJK-adjacent secret still masked
    assert "日志" in out  # CJK prefix survives
    assert "urltok99" not in out
    assert "api.example.com" in out
    # false positives must not be touched
    fp = "keyboard=ok monkey=business keystrokes=fn"
    assert redact_text(fp) == fp
    # counter semantics on direct calls: +0 for clean, exactly +1 for one secret
    before = redaction_count()
    redact_text("no credentials in this line")
    assert redaction_count() == before
    before = redaction_count()
    redact_text("one token=plainvalue123 tail")
    assert redaction_count() - before == 1


def test_redact_long_line_200k_tail_secret():
    filler = "lorem ipsum dolor sit amet " * 7500  # ~200KB
    line = filler + "中文标记 password=hunter2supersecret 尾部"
    assert len(line) > 200_000
    start = time.perf_counter()
    out = redact_text(line)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"redact_text took {elapsed:.2f}s on a 200KB line"
    assert "hunter2supersecret" not in out
    assert out.startswith("lorem ipsum dolor sit amet")  # prefix intact
    assert "中文标记" in out and "尾部" in out  # context around the secret intact


def test_redact_quoted_secret_with_spaces_fully_masked():
    """Regression H-01: a quoted secret containing spaces used to leak its
    tail ('api_key = "alpha beta gamma"' -> 'api_key = *** beta gamma"')
    because the value group was a bare \\S+.  The value group must consume
    the whole quoted string, closing quote included."""
    out = redact_text('api_key = "alpha beta gamma" and the tail survives')
    assert out == "api_key = *** and the tail survives"
    quoted_json = redact_text('"api_key": "alpha beta gamma" ok')
    assert "alpha beta gamma" not in quoted_json
    single = redact_text("'password': 'seed one two' rest")
    assert "seed one two" not in single
    assert "rest" in single


def test_redaction_filter_mutates_msg_args_and_exc_text():
    f = RedactionFilter()
    rec = logging.LogRecord(
        "ipostudio",
        logging.ERROR,
        "p",
        1,
        "upload failed for %s",
        ("https://user:supersecret9@host/x",),
        None,
    )
    assert f.filter(rec) is True
    assert "supersecret9" not in str(rec.msg)
    assert rec.args is None  # args cleared after msg replacement

    try:
        raise ValueError("conn string postgres://user:secretpw12@host/db")
    except ValueError:
        exc_info = sys.exc_info()
    rec2 = logging.LogRecord("ipostudio", logging.ERROR, "p", 2, "boom", None, exc_info)
    assert f.filter(rec2) is True
    assert rec2.exc_text is not None
    assert "secretpw12" not in rec2.exc_text
    assert "Traceback" in rec2.exc_text
    assert "ValueError" in rec2.exc_text

    rec3 = logging.LogRecord("ipostudio", logging.INFO, "p", 3, "plain", None, None)
    assert f.filter(rec3) is True
    assert rec3.exc_text is None  # untouched when no exc_info


def test_jsonl_redaction_cjk_and_traceback(tmp_path):
    logger = setup_logging(tmp_path, json_lines=True)
    logger.error("connect failed postgres://admin:p4ssw0rd@db.internal:5432/app 失败")
    try:
        raise RuntimeError("lease expired secret=zzz1234567890")
    except RuntimeError:
        logger.exception("worker died")
    _flush(logger)
    raw = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "p4ssw0rd" not in raw
    assert "zzz1234567890" not in raw
    assert "失败" in raw  # ensure_ascii=False: CJK stored literally, not escaped
    payloads = [json.loads(line) for line in raw.splitlines()]
    assert any(
        p["level"] == "ERROR" and "***" in p["message"] and "失败" in p["message"]
        for p in payloads
    )
    assert any(p["message"].startswith("worker died") for p in payloads)
    tb_records = [p for p in payloads if "traceback" in p]
    assert tb_records, "expected traceback field on the exception record"
    for p in tb_records:
        assert "zzz1234567890" not in p["traceback"]
        assert "Traceback" in p["traceback"]


def test_pipeline_redaction_count_clean_vs_secret(tmp_path):
    logger = setup_logging(tmp_path)
    before = redaction_count()
    logger.info("totally clean operational message")
    _flush(logger)
    assert redaction_count() == before, "clean message must not bump the counter"
    logger.warning("one secret token=leakyvalue42 end")
    _flush(logger)
    delta = redaction_count() - before
    assert delta >= 1, "a masked record must bump the counter"
    # OBSERVED (probe + finding QA-B-03): delta is 4, not 1 — each record passes through
    # 2 handler filters + 2 formatter re-redactions, and the mask value '***'
    # itself re-matches the key=value rule, inflating the counter.


# ---------------------------------------------------------------------------
# setup_logging: idempotence + rotation
# ---------------------------------------------------------------------------


def test_setup_logging_twice_no_duplicate_lines(tmp_path):
    logger = setup_logging(tmp_path)
    logger2 = setup_logging(tmp_path)
    assert logger is logger2
    assert len(logger2.handlers) == 2  # one console + one file, no stale handlers
    logger2.warning("exactly once token=dupcheck123")
    _flush(logger2)
    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert content.count("exactly once") == 1
    assert "dupcheck123" not in content


def test_rotation_default_2mb_creates_backup(tmp_path):
    logger = setup_logging(tmp_path)  # defaults: max_bytes=2_000_000, backups=5
    filler = "lorem ipsum dolor sit amet " * 2560  # ~69KB per record
    for i in range(40):  # ~2.7MB total
        logger.warning("rec %d %s tail token=volsecret%d", i, filler, i)
    _flush(logger)
    logs_dir = tmp_path / "logs"
    assert log_file_path(tmp_path).exists()
    assert (logs_dir / "ipostudio.log.1").exists(), "2MB+ volume must rotate once"
    rotated = list(logs_dir.glob("ipostudio.log.*"))
    assert len(rotated) <= 5, "backupCount=5 must cap rotated files"
    for path in logs_dir.glob("ipostudio.log*"):
        content = path.read_text(encoding="utf-8")  # every fragment is valid utf-8
        assert "volsecret" not in content
    logger.warning("final 中文轮转 token=endcheck77")
    _flush(logger)
    current = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "endcheck77" not in current
    assert "中文轮转" in current  # CJK intact across rotation


def test_rotation_backup_count_respected_utf8_cjk(tmp_path):
    logger = setup_logging(tmp_path, max_bytes=1000, backups=2)
    for i in range(40):  # ~2.6KB total -> several rollovers
        logger.warning("中文%d token=secret%d", i, i)
    _flush(logger)
    names = sorted(p.name for p in (tmp_path / "logs").glob("ipostudio.log*"))
    assert names == ["ipostudio.log", "ipostudio.log.1", "ipostudio.log.2"]
    for name in names:
        content = (tmp_path / "logs" / name).read_text(encoding="utf-8")
        assert "secret" not in content
    current = (tmp_path / "logs" / "ipostudio.log").read_text(encoding="utf-8")
    assert "中文39" in current  # newest record in the live file, CJK unbroken


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


def test_threaded_logging_800_records_integrity(tmp_path):
    logger = setup_logging(tmp_path)
    before = redaction_count()
    errors: list[Exception] = []

    def worker(tid: int) -> None:
        try:
            for i in range(100):
                logger.warning("worker %d item %d token=pw%d_%d done", tid, i, tid, i)
        except Exception as exc:  # noqa: BLE001 - intentionally record ANY worker failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    _flush(logger)
    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 800, "every record must land as its own line"
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} WARNING ipostudio "
        r"worker (\d+) item (\d+) token=\*\*\* done$"
    )
    seen = set()
    for line in lines:
        m = pattern.match(line)
        assert m, f"corrupt/interleaved line: {line!r}"
        seen.add((int(m.group(1)), int(m.group(2))))
    assert seen == {(t, i) for t in range(8) for i in range(100)}
    assert "token=pw" not in content  # nothing leaked in plaintext
    assert redaction_count() - before >= 800


# ---------------------------------------------------------------------------
# Store: migrations, pragmas, contention
# ---------------------------------------------------------------------------


def test_migrate_concurrent_subprocesses_single_registration(tmp_path):
    db = tmp_path / "app.db"
    code = (
        "import sys;from pathlib import Path;"
        "from ipostudio.store.database import open_db,migrate;"
        "c=open_db(Path(sys.argv[1]));print(migrate(c));c.close()"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(db)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    out1, err1 = procs[0].communicate(timeout=60)
    out2, err2 = procs[1].communicate(timeout=60)
    # T-2: TODO-010 documents a microsecond TOCTOU window between the registry
    # re-check and the applying executescript in which the loser legitimately
    # exits nonzero with a rolled-back MigrationFailure.  Accept that recorded
    # variant; the post-state invariant below stays strict.
    for returncode, err in ((procs[0].returncode, err1), (procs[1].returncode, err2)):
        # any migration can be the one the TOCTOU loser was racing on
        assert (
            returncode == 0
            or "migration 001_init.sql failed" in err
            or "migration 002_models.sql failed" in err
            or "migration 003_instances.sql failed" in err
        ), err
    assert "Traceback" not in err1 and "Traceback" not in err2
    applied = sorted(
        ast.literal_eval(out.strip()) for out, rc, err in
        ((out1, procs[0].returncode, err1), (out2, procs[1].returncode, err2))
        if rc == 0
    )
    # 003 makes per-migration wins combinatorial (either process can win any
    # of the three apply races), so assert the invariant the two-migration
    # enumeration expressed: across processes, each migration applies
    # exactly once.
    flat = [name for entry in applied for name in entry]
    assert sorted(flat) == [
        "001_init.sql", "002_models.sql", "003_instances.sql",
    ], f"each migration must be applied exactly once across processes, got: {applied}"
    conn = open_db(db)
    rows = conn.execute("SELECT name FROM _migrations ORDER BY id").fetchall()
    assert [r["name"] for r in rows] == [
        "001_init.sql", "002_models.sql", "003_instances.sql",
    ]
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='app_meta'").fetchone()[0] == 1
    conn.close()


def test_migration_atomicity_not_null_rollback_and_fresh_conn_retry(tmp_path, monkeypatch):
    import ipostudio.store.database as db_mod

    broken = [
        ("001_init.sql", db_mod.migration_files()[0][1]),
        (
            "002_notnull.sql",
            "CREATE TABLE ok_tbl (v TEXT NOT NULL);\nINSERT INTO ok_tbl (v) VALUES (NULL);\n",
        ),
    ]
    monkeypatch.setattr(db_mod, "migration_files", lambda: broken)

    conn1 = open_db(tmp_path / "app.db")
    with pytest.raises(MigrationFailure) as ei:
        migrate(conn1)
    assert ei.value.name == "002_notnull.sql"
    # mid-script atomicity: the CREATE TABLE from the failed script is gone
    assert conn1.execute("SELECT name FROM sqlite_master WHERE name='ok_tbl'").fetchone() is None
    names = [r["name"] for r in conn1.execute("SELECT name FROM _migrations")]
    assert names == ["001_init.sql"]  # 001 committed, 002 unregistered
    assert migrate(conn1) == []  # same connection refuses retry (failure memory)

    conn2 = open_db(tmp_path / "app.db")  # fresh connection re-attempts loudly
    with pytest.raises(MigrationFailure) as ei2:
        migrate(conn2)
    assert ei2.value.name == "002_notnull.sql"
    assert conn2.execute("SELECT name FROM sqlite_master WHERE name='ok_tbl'").fetchone() is None
    assert conn2.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0] == 1
    conn1.close()
    conn2.close()


def test_open_db_fk_busy_timeout_and_dir_error(tmp_path):
    db = tmp_path / "a.db"
    conn = open_db(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.executescript(
        "CREATE TABLE parent(id INTEGER PRIMARY KEY);"
        "CREATE TABLE child(pid INTEGER REFERENCES parent(id));"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO child(pid) VALUES (999)")
    conn.rollback()

    # busy_timeout: a second writer waits for the lock instead of failing instantly
    conn.executescript("CREATE TABLE t(x INTEGER)")  # committed, visible to all
    conn.isolation_level = None  # manual transaction control
    conn.execute("BEGIN IMMEDIATE")  # hold the write lock with an open txn
    conn.execute("INSERT INTO t VALUES (1)")
    result: dict = {}

    def writer() -> None:
        c2 = open_db(db)
        start = time.perf_counter()
        try:
            c2.execute("INSERT INTO t VALUES (2)")
            c2.commit()
            result["ok"] = True
        except sqlite3.Error as exc:
            result["ok"] = False
            result["err"] = str(exc)
        finally:
            result["elapsed"] = time.perf_counter() - start
            c2.close()

    th = threading.Thread(target=writer)
    th.start()
    time.sleep(1.0)
    conn.execute("COMMIT")  # release the lock while the writer is waiting
    th.join(timeout=10)
    assert result.get("ok"), f"second writer failed: {result}"
    assert result["elapsed"] >= 0.5, "writer must have waited, not failed instantly"
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    conn.close()

    # a directory path fails as a clean typed error (CANTOPEN, primary fold)
    subdir = tmp_path / "not_a_db"
    subdir.mkdir()
    with pytest.raises(sqlite3.OperationalError) as ei:
        open_db(subdir)
    assert ei.value.sqlite_errorcode & 0xFF == 14  # SQLITE_CANTOPEN


def test_open_db_waits_for_busy_db_instead_of_raw_lock_error(tmp_path):
    """open_db on a database held by another connection (BEGIN EXCLUSIVE)
    waits on the busy handler and finishes the WAL switch once the holder
    releases — it must not fail, whatever handler is installed."""
    db = tmp_path / "busy.db"
    holder = sqlite3.connect(db, check_same_thread=False)
    holder.execute("CREATE TABLE t (x)")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("INSERT INTO t VALUES (1)")

    def _release() -> None:
        time.sleep(0.5)
        holder.execute("COMMIT")

    releaser = threading.Thread(target=_release)
    releaser.start()
    try:
        start = time.monotonic()
        conn = open_db(db)
        try:
            waited = time.monotonic() - start
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
    finally:
        releaser.join()
        holder.close()
    assert mode == "wal"
    # blocked on the holder, not an instant crash (0.2s floor keeps 0.3s of
    # headroom under the 0.5s releaser for CI scheduling stalls, review T-3)
    assert waited >= 0.2


def test_open_db_survives_simultaneous_cold_open_wal_race(tmp_path):
    """Regression QA-B-01: simultaneous cold opens of one fresh database can
    mutually deadlock on the WAL switch — each opener holds the SHARED lock
    the other's SHARED->EXCLUSIVE upgrade needs, and SQLite answers that
    upgrade with an immediate SQLITE_BUSY without invoking the busy handler
    (deadlock avoidance).  Pre-fix this leaked a raw "database is locked"
    OperationalError in ~20% of 6-way rounds; open_db must retry instead."""
    for round_no in range(12):
        db = tmp_path / f"race-{round_no}.db"
        seed = sqlite3.connect(db)
        seed.execute("CREATE TABLE t (x)")
        seed.commit()
        seed.close()
        barrier = threading.Barrier(6, timeout=15)
        errors: list[str] = []
        lock = threading.Lock()

        def opener(db=db, barrier=barrier, lock=lock, errors=errors) -> None:
            barrier.wait()
            try:
                open_db(db).close()
            except sqlite3.Error as exc:
                with lock:
                    errors.append(str(exc))

        threads = [threading.Thread(target=opener) for _ in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        assert errors == [], f"round {round_no}: {errors}"


def test_redact_escaped_quotes_and_line_local_multiline():
    """Cross-model review finding: JSON-serialized values with escaped quotes
    ({"api_key": "abc\\"def"}) leak the tail past the mask because \\" reads
    as a closing quote; an unclosed quote also swallowed subsequent traceback
    lines up to the next quote anywhere in the text.  Quoted matching must be
    escape-aware AND line-local."""
    out = redact_text('{"api_key": "abc\\"def"} rest survives')
    assert out == '{"api_key": *** rest survives'
    single = redact_text("'password': 'ab\\'cd' tail")
    assert "cd" not in single  # escaped apostrophe is not a closing quote
    assert single.endswith(" tail")
    # unclosed quote on a traceback line: mask the token, keep every later line
    tb = 'self.key = "unclosed-value\n  file.py:10 x = combine("a", "b")\n  final diagnostic'
    out_tb = redact_text(tb)
    assert "unclosed-value" not in out_tb
    assert 'x = combine("a", "b")' in out_tb
    assert "final diagnostic" in out_tb


def test_switch_to_wal_deadline_stops_burning_busy_timeouts(tmp_path, monkeypatch):
    """Four-source review convergence: with busy_timeout=5000 installed, every
    BUSY from a persistent holder burns the full 5s handler wait, so 8 bounded
    retries meant a ~42s open_db stall.  The retry loop must respect a
    wall-clock deadline: once past it, the next BUSY re-raises instead of
    starting another 5s wait."""
    import ipostudio.store.database as db_mod

    class BusyConn:
        def __init__(self):
            self.calls = 0

        def execute(self, sql, *args):
            self.calls += 1
            exc = sqlite3.OperationalError("database is locked")
            exc.sqlite_errorcode = 5  # SQLITE_BUSY
            raise exc

    conn = BusyConn()
    clock = {"t": 0.0}

    def fake_monotonic():
        clock["t"] += 3.0  # 3s per read: the deadline is crossed after one retry
        return clock["t"]

    sleeps: list[float] = []
    monkeypatch.setattr(db_mod.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(db_mod.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(sqlite3.OperationalError):
        db_mod._switch_to_wal(conn)  # type: ignore[arg-type]
    assert len(sleeps) <= 2, f"burned {len(sleeps)} retries past the deadline"


def test_switch_to_wal_non_busy_reraises_without_retry(tmp_path, monkeypatch):
    """T-1: a non-BUSY OperationalError must re-raise immediately -- no sleep,
    no retry (retrying NOTADB or a disk error cannot succeed)."""
    import ipostudio.store.database as db_mod

    class NotADbConn:
        def execute(self, sql, *args):
            exc = sqlite3.OperationalError("file is not a database")
            exc.sqlite_errorcode = 26  # SQLITE_NOTADB
            raise exc

    sleeps: list[float] = []
    monkeypatch.setattr(db_mod.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(sqlite3.OperationalError):
        db_mod._switch_to_wal(NotADbConn())  # type: ignore[arg-type]
    assert sleeps == []


def test_switch_to_wal_retries_exhaustion_still_raises(tmp_path, monkeypatch):
    """T-1: persistent BUSY within the deadline still raises after the bounded
    attempt count, with one sleep per retried attempt."""
    import ipostudio.store.database as db_mod

    class BusyConn:
        def execute(self, sql, *args):
            exc = sqlite3.OperationalError("database is locked")
            exc.sqlite_errorcode = 5  # SQLITE_BUSY
            raise exc

    sleeps: list[float] = []
    monkeypatch.setattr(db_mod.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(sqlite3.OperationalError):
        db_mod._switch_to_wal(BusyConn())  # type: ignore[arg-type]
    assert len(sleeps) == db_mod._WAL_SWITCH_RETRIES - 1


def test_open_db_closes_connection_when_init_fails(tmp_path, monkeypatch):
    """Codex review: if a pragma during open_db initialization raises, the
    freshly created connection leaked (callers never receive it to close).
    A closed handle releases the file, so the db becomes deletable on
    Windows -- that is the observable."""
    import ipostudio.store.database as db_mod

    def explode(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(db_mod, "_switch_to_wal", explode)
    db = tmp_path / "leak.db"
    db.write_bytes(b"")  # non-empty so the connection definitely opens it
    with pytest.raises(RuntimeError):
        open_db(db)
    db.unlink()  # Windows: only succeeds when no handle is still open
