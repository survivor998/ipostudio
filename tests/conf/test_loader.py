import os
import subprocess
import sys
from pathlib import Path

import pytest

from ipostudio.conf import loader
from ipostudio.conf.loader import (
    ConfigError,
    ConfigStore,
    coerce_value,
    file_key_names,
    load_config,
    suggest_key,
)


def write_settings(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_yields_defaults(tmp_path):
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert cfg.general.server_port == 18080


def test_toml_values_load_and_env_overrides(tmp_path):
    write_settings(tmp_path, 'server_port = 19000\nui_lang = "en"\n')
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path), "IPO_SERVER_PORT": "18111"})
    assert cfg.general.server_port == 18111
    assert cfg.ui.ui_lang == "en"


def test_env_coercion_bool_int_list(tmp_path):
    env = {
        "IPO_DATA_DIR": str(tmp_path),
        "IPO_AUTO_START_SERVER": "false",
        "IPO_SERVER_TOP_K": "7",
        "IPO_SERVER_TEMP": "0.5",
        "IPO_MODEL_DIRS": "/a, /b",
        "IPO_SERVER_FALLBACK_MODELS": "m1,m2",
        "IPO_LOCAL_MODEL_PATH": "none",
    }
    cfg = load_config(env=env)
    assert cfg.general.auto_start_server is False
    assert cfg.tuning.server_top_k == 7
    assert cfg.tuning.server_temp == 0.5
    assert cfg.general.model_dirs == ["/a", "/b"]
    assert cfg.tuning.server_fallback_models == ["m1", "m2"]
    assert cfg.general.local_model_path is None


def test_unknown_toml_key_rejected(tmp_path):
    write_settings(tmp_path, "definitely_not_a_key = 1\n")
    with pytest.raises(ConfigError) as err:
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert any("definitely_not_a_key" in line for line in err.value.details)


def test_unknown_env_key_rejected_but_bootstrap_ok(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_NO_SUCH_THING": "1"}
    with pytest.raises(ConfigError) as err:
        load_config(env=env)
    assert any("IPO_NO_SUCH_THING" in line for line in err.value.details)
    # bootstrap variables themselves never raise
    assert load_config(env={"IPO_DATA_DIR": str(tmp_path), "IPO_CONFIG": "x.toml"}) is not None


def test_invalid_value_reports_field_location(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_SERVER_CTX_SIZE": "32"}
    with pytest.raises(ConfigError) as err:
        load_config(env=env)
    assert any("server_ctx_size" in line for line in err.value.details)


def test_broken_toml_rejected(tmp_path):
    write_settings(tmp_path, "not [valid toml\n")
    with pytest.raises(ConfigError):
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})


def test_store_save_is_atomic_and_roundtrips(tmp_path):
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("server_port", 18222)
    saved = store.save()
    assert saved == tmp_path / "settings.toml"
    again = load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert again.general.server_port == 18222
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_store_only_writes_dirty_keys_and_never_credentials(tmp_path):
    write_settings(tmp_path, "server_port = 19000\n")
    write_settings(tmp_path, "server_port = 19000\ngateway_api_key = \"sk-old-file-key\"\n")
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("gateway_port", 10001)
    store.save()
    body = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "server_port = 19000" in body          # untouched key preserved
    assert "gateway_port = 10001" in body          # dirty key written
    assert "sk-old-file-key" not in body           # credentials dropped even if previously in file


def test_store_set_validates_and_rejects_without_mutation(tmp_path):
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    for attempt in (lambda: store.set("server_port", 70000),          # out of range
                    lambda: store.set("gateway_api_key", "sk-x"),     # credential key
                    lambda: store.set("no_such_key", 1),              # unknown key
                    lambda: store.set("proxy_url", "http://u:p@h")):  # URL credential
        with pytest.raises(ConfigError):
            attempt()
    assert store.config.general.server_port == 18080           # memory untouched
    assert store.config.gateway.gateway_api_key == ""          # secret never landed
    assert store.set("server_port", "18222") is None           # str input normalized
    assert store.config.general.server_port == 18222
    assert isinstance(store.config.general.server_port, int)


def test_store_set_rejects_url_credential_nested_in_containers(tmp_path):
    """The URL-credential invariant is on VALUES, not key names: any string
    anywhere inside a config value (list/tuple elements, dict values) must be
    rejected, not just top-level strings (final review finding)."""
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    for value in (
        ["--proxy", "http://user:secret@host"],            # flat list (reported leak)
        ("--proxy", "http://user:secret@host"),            # tuple
        [["--connect-timeout", "http://user:secret@host"]],  # nested list
        {"proxy": "http://user:secret@host"},              # dict values
    ):
        with pytest.raises(ConfigError) as err:
            store.set("llama_cpp_extra_args", value)
        assert any("inline URL credential" in line for line in err.value.details)
    assert store.config.engines.llama_cpp_extra_args == []  # memory unchanged
    assert store._dirty == set()  # rejected calls never mark keys dirty


def test_newer_config_version_unknown_keys_ignored_with_warning(tmp_path):
    write_settings(tmp_path, "config_version = 99\nfuture_key_xyz = 1\n")
    warnings: list[str] = []
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path)}, warnings=warnings)
    assert cfg.general.config_version == 99
    assert any("future_key_xyz" in w for w in warnings)
    # the warning must match save() reality: the dirty-key merge re-serializes
    # the raw file, so unknown keys ARE kept in the file on save (final review)
    assert any("kept in the file" in w and "ignored" in w for w in warnings)
    assert not any("preserved by nothing" in w for w in warnings)
    assert not hasattr(cfg.general, "future_key_xyz")


def test_unknown_key_error_names_file_and_suggests_fix(tmp_path):
    write_settings(tmp_path, "server_prot = 18111\n")  # typo of server_port
    with pytest.raises(ConfigError) as err:
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    joined = "\n".join(err.value.details)
    assert "server_prot" in joined
    assert "server_port" in joined          # difflib suggestion
    assert "settings.toml" in joined        # controlling file named
    assert "remove" in joined.lower() or "fix" in joined.lower()  # remedy clause


def test_unreadable_or_non_utf8_config_is_configerror(tmp_path):
    bad = tmp_path / "settings.toml"
    bad.write_bytes(b"\xff\xfe not utf8")
    with pytest.raises(ConfigError):
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})


def test_env_lists_accept_json_array_encoding(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path),
           "IPO_MODEL_DIRS": '["/a,comma/dir", "/b"]'}
    cfg = load_config(env=env)
    assert cfg.general.model_dirs == ["/a,comma/dir", "/b"]  # comma inside value kept


def test_env_sourced_error_names_env_var_not_file(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_SERVER_PORT": "70000"}
    with pytest.raises(ConfigError) as err:
        load_config(env=env)
    joined = "\n".join(err.value.details)
    assert "IPO_SERVER_PORT" in joined


def test_save_failure_cleans_temp_and_raises_configerror(tmp_path, monkeypatch):
    import tomli_w as tomli_w_module

    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("server_port", 18222)

    def exploding_dump(data, handle):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(tomli_w_module, "dump", exploding_dump)
    with pytest.raises(ConfigError):
        store.save()
    leftovers = list(tmp_path.glob(".settings-*.tmp")) + list(tmp_path.glob("*.lock"))
    assert leftovers == []  # temp AND lock cleaned on failure


# ---------------------------------------------------------------------------
# Lock-protocol behavior (review fix round 1): contention, timeout and
# cross-process merge. These are characterization tests: they pin the EXISTING
# advisory-lock protocol (O_CREAT|O_EXCL lock file, timeout, release-on-exit)
# and are expected to pass against the committed implementation.
# ---------------------------------------------------------------------------

_SUBPROCESS_MERGE_CHILD = """\
import sys
from pathlib import Path

from ipostudio.conf.loader import ConfigStore, load_config

data_dir = Path(sys.argv[1])
config = load_config(env={"IPO_DATA_DIR": str(data_dir)})
store = ConfigStore(data_dir / "settings.toml", config)
store.set("gateway_port", 10001)
store.save()
print("CHILD_SAVED")
"""

_SUBPROCESS_CONTENTION_CHILD = """\
import sys
from pathlib import Path

from ipostudio.conf import loader
from ipostudio.conf.loader import ConfigError, ConfigStore, load_config


class _FastLock(loader._advisory_lock):
    def __init__(self, path, timeout_seconds=0.5):
        super().__init__(path, timeout_seconds)


loader._advisory_lock = _FastLock

data_dir = Path(sys.argv[1])
config = load_config(env={"IPO_DATA_DIR": str(data_dir)})
store = ConfigStore(data_dir / "settings.toml", config)
store.set("server_port", 18333)
try:
    store.save()
except ConfigError as exc:
    print("CONFIG_ERROR")
    print(exc)
    raise SystemExit(3)
print("CHILD_SAVED")
"""


def _patch_fast_lock(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    """Shrink the advisory-lock timeout so timeout-path tests stay fast."""

    class _FastAdvisoryLock(loader._advisory_lock):
        def __init__(self, path, timeout_seconds=seconds):
            super().__init__(path, timeout_seconds)

    monkeypatch.setattr(loader, "_advisory_lock", _FastAdvisoryLock)


def _run_child(script: str, data_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run a snippet in a real second process with ipostudio importable."""
    src_dir = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": str(src_dir)}
    return subprocess.run(
        [sys.executable, "-c", script, str(data_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
        check=False,
    )


def test_interleaved_stores_merge_both_dirty_keys(tmp_path):
    config_path = tmp_path / "settings.toml"
    store_a = ConfigStore(config_path, load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store_b = ConfigStore(config_path, load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store_a.set("server_port", 18222)
    store_b.set("gateway_port", 10001)
    store_a.save()
    store_b.save()  # must re-read and merge, not overwrite store_a's key
    reloaded = load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert reloaded.general.server_port == 18222
    assert reloaded.gateway.gateway_port == 10001
    leftovers = list(tmp_path.glob("*.lock")) + list(tmp_path.glob("*.tmp"))
    assert leftovers == []  # lock released on the success path, no temp leaked


def test_subprocess_writer_merges_with_parent_save(tmp_path):
    config_path = tmp_path / "settings.toml"
    parent = ConfigStore(config_path, load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    parent.set("server_port", 18222)
    parent.save()
    result = _run_child(_SUBPROCESS_MERGE_CHILD, tmp_path)
    assert result.returncode == 0, f"child failed:\n{result.stdout}\n{result.stderr}"
    reloaded = load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert reloaded.general.server_port == 18222       # parent's key survives
    assert reloaded.gateway.gateway_port == 10001      # child's key merged in
    leftovers = list(tmp_path.glob("*.lock")) + list(tmp_path.glob("*.tmp"))
    assert leftovers == []  # cross-process save releases the lock cleanly


def test_lock_timeout_raises_configerror_naming_lock_path(tmp_path, monkeypatch):
    _patch_fast_lock(monkeypatch, 0.1)
    config_path = tmp_path / "settings.toml"
    lock_path = tmp_path / "settings.toml.lock"
    lock_path.write_bytes(b"")  # a foreign holder owns the advisory lock
    store = ConfigStore(config_path, load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("server_port", 18222)
    try:
        with pytest.raises(ConfigError) as err:
            store.save()
        assert lock_path.exists()  # a waited-on foreign lock is never stolen
    finally:
        lock_path.unlink(missing_ok=True)  # the test must not leak its own lock
    assert "settings.toml.lock" in str(err.value)
    assert list(tmp_path.glob(".settings-*.tmp")) == []  # nothing written pre-lock
    # once the foreign lock is gone, the same store saves without residue
    store.save()
    assert load_config(env={"IPO_DATA_DIR": str(tmp_path)}).general.server_port == 18222
    assert list(tmp_path.glob("*.lock")) == []


def test_subprocess_writer_hits_held_lock_and_times_out(tmp_path):
    lock_path = tmp_path / "settings.toml.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)  # parent holds it
    try:
        result = _run_child(_SUBPROCESS_CONTENTION_CHILD, tmp_path)
        assert result.returncode == 3, (
            f"child did not time out:\n{result.stdout}\n{result.stderr}"
        )
        assert "CONFIG_ERROR" in result.stdout
        assert "settings.toml.lock" in result.stdout  # error names the lock path
        assert lock_path.exists()  # child never removes a lock it does not own
    finally:
        os.close(fd)
        lock_path.unlink(missing_ok=True)  # parent releases; nothing leaks


def test_suggest_key_returns_did_you_mean_for_close_matches():
    assert suggest_key("server_prot") == "; did you mean 'server_port'?"


def test_suggest_key_accepts_custom_pool():
    assert suggest_key("hepl", pool={"help", "guide"}) == "; did you mean 'help'?"


def test_suggest_key_empty_for_distant_names():
    assert suggest_key("zzzzzz") == ""


def test_coerce_value_parses_scalars_lists_and_none():
    assert coerce_value("server_port", "19000") == 19000
    assert coerce_value("auto_start_server", "on") is True
    assert coerce_value("server_temp", "0.5") == 0.5
    assert coerce_value("ui_lang", "  en ") == "en"  # shell-transplanted padding
    assert coerce_value("model_dirs", '["a", "b"]') == ["a", "b"]  # JSON keeps commas
    assert coerce_value("model_dirs", "a, b") == ["a", "b"]  # legacy comma form
    assert coerce_value("local_model_path", "none") is None  # optional clearing


def test_coerce_value_rejects_unknown_key_with_suggestion():
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("nope_key", "1")
    assert "unknown config key" in str(excinfo.value)


def test_coerce_value_phrases_bool_errors_for_the_cli_not_the_shell():
    # origin accuracy: _coerce_env's default remediation names the shell env
    # var; a CLI set must state the fix for the command line instead, with
    # the CONFIG KEY as origin — never the IPO_ env name (Codex DX #2)
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("auto_start_server", "maybe")
    message = str(excinfo.value)
    assert "auto_start_server: expected a boolean" in message
    assert "true/false/1/0" in message
    assert "environment variable" not in message
    assert "IPO_AUTO_START_SERVER" not in message


def test_coerce_value_reports_undeclarable_values_as_config_error():
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("model_dirs", "[broken")
    assert "cannot convert" in str(excinfo.value)
    assert '["a", "b"]' in str(excinfo.value)  # remediation carries an example


def test_coerce_value_rejects_non_string_json_array_elements():
    # Codex ENG acceptance-b: a public CLI write surface must reject
    # [null, {...}] instead of silently stringifying it (["None", "{'x': 1}"])
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("model_dirs", '[null, {"x": 1}]')
    message = str(excinfo.value)
    assert "JSON array elements must all be strings" in message
    assert "model_dirs" in message


def test_file_key_names_reports_explicit_keys(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text('ui_lang = "en"\n', encoding="utf-8")
    assert file_key_names(settings) == {"ui_lang"}
    assert file_key_names(tmp_path / "missing.toml") == set()


def test_save_stamps_config_version_for_downgrade_tolerance(tmp_path, monkeypatch):
    import tomllib

    from ipostudio.conf.loader import ConfigStore
    from ipostudio.conf.paths import resolve_config_path

    monkeypatch.setenv("IPO_CONFIG", str(tmp_path / "settings.toml"))
    store = ConfigStore(resolve_config_path(), load_config())
    store.set("server_port", 18765)
    store.save()
    raw = tomllib.loads(resolve_config_path().read_text(encoding="utf-8"))
    assert raw["config_version"] == loader._SCHEMA_CONFIG_VERSION  # Codex fold


def test_save_reports_unwritable_parent_as_config_error(tmp_path, monkeypatch):
    # mkdir failure must surface through the error contract, not a raw OSError
    from ipostudio.conf.loader import ConfigStore
    from ipostudio.conf.schema import AppConfig

    store = ConfigStore(tmp_path / "settings.toml", AppConfig())

    def explode(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(type(tmp_path), "mkdir", explode, raising=False)
    with pytest.raises(ConfigError) as excinfo:
        store.save()
    assert "cannot write settings file" in str(excinfo.value)


def test_save_reports_unopenable_lock_as_config_error(tmp_path, monkeypatch):
    # lock-file creation failure (permissions) is also inside the boundary (Codex ENG #2)
    import os as _os

    from ipostudio.conf.loader import ConfigStore
    from ipostudio.conf.schema import AppConfig

    (tmp_path / "settings.toml").write_text("ui_lang = \"zh\"\n", encoding="utf-8")
    store = ConfigStore(tmp_path / "settings.toml", AppConfig())
    real_open = _os.open

    def locked_open(path, flags, *args, **kwargs):
        if str(path).endswith(".lock"):
            raise PermissionError("denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(_os, "open", locked_open)
    with pytest.raises(ConfigError) as excinfo:
        store.save()
    assert "cannot write settings file" in str(excinfo.value)
