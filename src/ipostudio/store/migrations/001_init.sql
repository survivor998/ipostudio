-- 001_init: internal key-value storage for CLI/runtime state.
-- (_migrations is bootstrapped by migrate() itself, not by this script.)
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
