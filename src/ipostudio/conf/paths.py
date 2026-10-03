"""Resolve on-disk locations for data, config and database (ADR-003)."""

import os
from collections.abc import Mapping
from pathlib import Path

IPO_SUBDIRS: tuple[str, ...] = (
    "data",
    "logs",
    "downloads",
    "models",
    "media/images",
    "media/video",
    "media/audio",
    "backups",
    "skills",
)

# Environment variables consumed before the config file exists (spec §11.2 first rows).
BOOTSTRAP_ENV: frozenset[str] = frozenset({"IPO_DATA_DIR", "IPO_CONFIG", "IPO_DB_PATH"})


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def resolve_data_dir(env: Mapping[str, str] | None = None) -> Path:
    override = _env(env).get("IPO_DATA_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".ipostudio"


def resolve_config_path(env: Mapping[str, str] | None = None) -> Path:
    override = _env(env).get("IPO_CONFIG", "").strip()
    return Path(override).expanduser() if override else resolve_data_dir(env) / "settings.toml"


def resolve_db_path(env: Mapping[str, str] | None = None) -> Path:
    override = _env(env).get("IPO_DB_PATH", "").strip()
    return Path(override).expanduser() if override else resolve_data_dir(env) / "data" / "app.db"


def ensure_layout(data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    root = data_dir if data_dir is not None else resolve_data_dir(env)
    for sub in IPO_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
