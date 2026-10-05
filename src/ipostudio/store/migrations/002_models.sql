-- 002: model catalog rows for locally scanned model files (spec §10.1:
-- models, origin, category and integrity; F02 local-management slice).
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    parts INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL DEFAULT 'chat',
    source TEXT NOT NULL DEFAULT 'scan',
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
