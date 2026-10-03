from ipostudio.conf.paths import (
    BOOTSTRAP_ENV,
    IPO_SUBDIRS,
    ensure_layout,
    resolve_config_path,
    resolve_data_dir,
    resolve_db_path,
)


def test_default_data_dir_is_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # Windows 下 pathlib.Path.home() 优先 USERPROFILE
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert resolve_data_dir(env={}) == tmp_path / ".ipostudio"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path
    assert resolve_config_path() == tmp_path / "settings.toml"
    assert resolve_db_path() == tmp_path / "data" / "app.db"


def test_explicit_config_path_wins(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_CONFIG": str(tmp_path / "other.toml")}
    assert resolve_config_path(env=env) == tmp_path / "other.toml"


def test_ensure_layout_creates_all_subdirs_idempotently(tmp_path):
    first = ensure_layout(tmp_path)
    second = ensure_layout(tmp_path)
    assert first == second == tmp_path
    for sub in IPO_SUBDIRS:
        assert (tmp_path / sub).is_dir(), f"missing subdir: {sub}"


def test_bootstrap_env_contains_path_vars():
    assert BOOTSTRAP_ENV == frozenset({"IPO_DATA_DIR", "IPO_CONFIG", "IPO_DB_PATH"})
