-- 003: engine instances and completion records (spec §10.1 instances/
-- addresses/activity; §10.2 service states; completions is the persistence
-- half of the M0' slice: records survive restarts).
CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine TEXT NOT NULL,
    engine_version TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL,
    model_path TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    pid INTEGER,
    state TEXT NOT NULL CHECK (state IN ('stopped','starting','loading','running','failed')),
    detail TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    stopped_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL REFERENCES instances(id),
    model_name TEXT NOT NULL,
    prompt_text TEXT NOT NULL DEFAULT '',
    output_text TEXT NOT NULL DEFAULT '',
    prompt_chars INTEGER NOT NULL,
    output_chars INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','error')),
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
