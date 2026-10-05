import sqlite3

import pytest

from ipostudio.store.database import MigrationFailure, current_version, migrate, open_db


def test_open_db_enables_wal_and_row_factory(tmp_path):
    conn = open_db(tmp_path / "app.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_migrate_is_idempotent_and_records_names(tmp_path):
    conn = open_db(tmp_path / "app.db")
    applied_first = migrate(conn)
    applied_second = migrate(conn)
    assert applied_first == ["001_init.sql", "002_models.sql"]  # identity = package filename
    assert applied_second == []
    assert current_version(conn) == 2
    names = [row["name"] for row in conn.execute("SELECT name FROM _migrations ORDER BY id")]
    assert names == ["001_init.sql", "002_models.sql"]
    # app_meta usable
    conn.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES ('probe', '1')")
    conn.commit()
    assert conn.execute("SELECT value FROM app_meta WHERE key='probe'").fetchone()[0] == "1"
    conn.close()


def test_failed_migration_rolls_back_and_stays_unregistered(tmp_path, monkeypatch):
    import ipostudio.store.database as db

    broken = [("001_init.sql", db.migration_files()[0][1]),
              ("002_broken.sql", "INSERT INTO no_such_table VALUES (1);")]
    monkeypatch.setattr(db, "migration_files", lambda: broken)
    conn = open_db(tmp_path / "app.db")
    with pytest.raises(MigrationFailure) as err:
        migrate(conn)
    assert err.value.name == "002_broken.sql"
    names = [row["name"] for row in conn.execute("SELECT name FROM _migrations")]
    assert names == ["001_init.sql"]      # failed migration not registered
    assert migrate(conn) == []            # connection reusable after rollback
    conn.close()
