"""QA-A adversarial/edge-case tests for ipostudio.conf (paths, schema, loader).

Clean-room tests written from observed behavior of src/ipostudio/conf/.
Focus: concurrency, crash atomicity, stale locks, env coercion edge cases,
malformed TOML, forward compatibility, credential scrubbing, read-only files.

All subprocesses are real ``sys.executable`` processes with hard timeouts
(Windows-safe: no fork, no POSIX-only APIs).
"""

import os
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from ipostudio.conf.loader import CREDENTIAL_KEYS, FLAT_KEYS, ConfigError, ConfigStore, load_config
from ipostudio.conf.paths import (
    IPO_SUBDIRS,
    ensure_layout,
    resolve_config_path,
    resolve_data_dir,
    resolve_db_path,
)

HOME_ROOT = Path.home() / ".ipostudio"

CHILD_SET_AND_SAVE = """\
import sys
from pathlib import Path
from ipostudio.conf.loader import ConfigStore, load_config

key, value, cfg_path = sys.argv[1], sys.argv[2], sys.argv[3]
config = load_config({"IPO_CONFIG": cfg_path})
store = ConfigStore(Path(cfg_path), config)
store.set(key, value)
store.save()
"""

CHILD_SAVE_LOOP = """\
import sys
from pathlib import Path
from ipostudio.conf.loader import ConfigStore, load_config

cfg_path = sys.argv[1]
config = load_config({"IPO_CONFIG": cfg_path})
store = ConfigStore(Path(cfg_path), config)
i = 0
while True:
    store.set("server_host", f"10.0.0.{i % 250 + 1}")
    store.save()
    i += 1
"""

CHILD_CRASH_BEFORE_REPLACE = """\
import os, sys
from pathlib import Path

# Simulate a writer killed between mkstemp and os.replace: a staged temp file
# is left behind, config.toml itself is never touched.
tmp = Path(sys.argv[1]) / ".settings-crashed.tmp"
tmp.write_bytes(b"partial write, process died before os.replace")
os._exit(1)
"""


def base_env(cfg_path: Path) -> dict[str, str]:
    return {"IPO_CONFIG": str(cfg_path)}


def make_store(cfg_path: Path) -> ConfigStore:
    config = load_config({"IPO_CONFIG": str(cfg_path)})
    return ConfigStore(cfg_path, config)


def child_env() -> dict[str, str]:
    env = os.environ.copy()
    src = Path(__file__).resolve().parents[2] / "src"
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    return env


# ---------------------------------------------------------------------------
# 1-2: IPO_ env override edge cases
# ---------------------------------------------------------------------------


def test_env_coercion_whitespace_empty_and_none_semantics(tmp_path):
    """Whitespace-padded numeric/bool words coerce; '' / none / null clear
    optional keys to None; '' on a plain str key stays ''; '' on an int key
    is a cannot-convert error; a float-looking int value is rejected."""
    cfg = tmp_path / "settings.toml"
    env = base_env(cfg) | {
        "IPO_SERVER_PORT": " 18080 ",  # padded int
        "IPO_AUTO_START_SERVER": "ON",  # case-insensitive bool
        "IPO_LOCAL_MODEL_PATH": " none ",  # optional cleared by word
        "IPO_VLLM_API_BASE": "",  # non-optional str keeps empty
    }
    config = load_config(env)
    assert config.general.server_port == 18080
    assert config.general.auto_start_server is True
    assert config.general.local_model_path is None
    assert config.general.vllm_api_base == ""

    # null (padded, any case) also clears an optional key
    config_null = load_config(base_env(cfg) | {"IPO_LOCAL_MODEL_PATH": " NuLL "})
    assert config_null.general.local_model_path is None

    with pytest.raises(ConfigError) as empty_int:
        load_config(base_env(cfg) | {"IPO_SERVER_PORT": ""})
    assert "IPO_SERVER_PORT" in empty_int.value.details[0]
    assert "cannot convert" in empty_int.value.details[0]

    with pytest.raises(ConfigError) as float_int:
        load_config(base_env(cfg) | {"IPO_SERVER_CTX_SIZE": "8192.0"})
    assert "cannot convert" in str(float_int.value)

    # QA-A-02 regression: string env values are whitespace-stripped like the
    # numeric/bool branches, so shell padding no longer leaks into values nor
    # breaks Literal fields
    padded = load_config(base_env(cfg) | {"IPO_SERVER_HOST": " 0.0.0.0 "})
    assert padded.general.server_host == "0.0.0.0"
    themed = load_config(base_env(cfg) | {"IPO_UI_THEME": " dark "})
    assert themed.ui.ui_theme == "dark"


def test_env_errors_accumulate_attribute_and_short_circuit(tmp_path):
    """Multiple bad env vars accumulate details naming the env var; unknown
    env keys are always fatal; env coercion errors (bool or numeric) and
    file-side unknown keys accumulate instead of discarding each other;
    origin attribution names env var vs file."""
    cfg = tmp_path / "settings.toml"
    with pytest.raises(ConfigError) as multi:
        load_config(
            base_env(cfg)
            | {
                "IPO_SERVER_PORT": "notanint",
                "IPO_VLLM_PORT": "alsobad",
                "IPO_DOWNLOADS": "4",  # family name, not a key: unknown
                "IPO_UNKNOWN_THING": "1",
            }
        )
    details = multi.value.details
    assert any("IPO_SERVER_PORT" in d and "cannot convert" in d for d in details)
    assert any("IPO_VLLM_PORT" in d and "cannot convert" in d for d in details)
    assert any("unknown environment key: IPO_DOWNLOADS" in d for d in details)
    assert any("unknown environment key: IPO_UNKNOWN_THING" in d for d in details)

    # QA-A-01 regression: an invalid bool used to raise immediately, dropping
    # the already-accumulated IPO_SERVER_PORT detail — it now accumulates
    with pytest.raises(ConfigError) as short:
        load_config(
            base_env(cfg) | {"IPO_SERVER_PORT": "notanint", "IPO_AUTO_START_SERVER": "maybe"}
        )
    assert len(short.value.details) == 2
    assert "expected a boolean" in short.value.details[0]
    assert "IPO_SERVER_PORT" in short.value.details[1]

    # ...and file-side unknown keys still surface alongside env coercion
    # errors instead of being skipped by an early raise
    cfg.write_text("bogus_key = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError) as mixed:
        load_config(base_env(cfg) | {"IPO_AUTO_START_SERVER": "maybe"})
    assert any("expected a boolean" in d for d in mixed.value.details)
    assert any("bogus_key" in d for d in mixed.value.details)
    cfg.write_text("", encoding="utf-8")

    # origin attribution: env-sourced range failure names the env var,
    # file-sourced one names the file path
    with pytest.raises(ConfigError) as from_env:
        load_config(base_env(cfg) | {"IPO_SERVER_PORT": "99999"})
    assert "from IPO_SERVER_PORT" in str(from_env.value)

    cfg.write_text("server_port = 99999\n", encoding="utf-8")
    with pytest.raises(ConfigError) as from_file:
        load_config(base_env(cfg))
    assert f"from {cfg}" in str(from_file.value)


# ---------------------------------------------------------------------------
# 3: malformed TOML
# ---------------------------------------------------------------------------


def test_malformed_toml_syntax_bom_nonutf8_and_crlf(tmp_path):
    """Syntax errors, a UTF-8 BOM and non-UTF-8 bytes all raise ConfigError
    naming the file; a CRLF-only file loads fine."""
    cfg = tmp_path / "settings.toml"

    cfg.write_bytes(b'server_port = "unclosed\n')
    with pytest.raises(ConfigError) as syntax:
        load_config(base_env(cfg))
    assert "not valid UTF-8 TOML" in str(syntax.value)
    assert str(cfg) in str(syntax.value)

    cfg.write_bytes(b"\xef\xbb\xbfserver_port = 18080\n")  # UTF-8 BOM
    with pytest.raises(ConfigError) as bom:
        load_config(base_env(cfg))
    assert "not valid UTF-8 TOML" in str(bom.value)

    cfg.write_bytes(b"\xff\xfe\x00garbage")  # not valid UTF-8
    with pytest.raises(ConfigError) as encoding:
        load_config(base_env(cfg))
    assert "not valid UTF-8 TOML" in str(encoding.value)

    cfg.write_bytes(b'server_port = 18080\r\nserver_host = "with-crlf"\r\n')
    config = load_config(base_env(cfg))
    assert config.general.server_port == 18080
    assert config.general.server_host == "with-crlf"


# ---------------------------------------------------------------------------
# 4: config_version forward compatibility
# ---------------------------------------------------------------------------


def test_newer_config_version_warns_drops_unknown_but_keeps_them_on_save(tmp_path):
    """config_version=2 file: unknown keys warn with the 'kept in the file on
    save' wording, are dropped from the model, and survive a save; known keys
    still apply and still validate."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text(
        "config_version = 2\nfuture_key = 'from-the-future'\nserver_port = 19999\n",
        encoding="utf-8",
    )
    warnings: list[str] = []
    config = load_config(base_env(cfg), warnings)
    assert config.general.server_port == 19999
    assert config.general.config_version == 2
    assert any("future_key" in w and "kept in the file on save" in w and "2" in w for w in warnings)

    store = ConfigStore(cfg, config)
    store.set("ui_theme", "dark")
    store.save()
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data["future_key"] == "from-the-future"  # preserved on disk
    assert data["config_version"] == 2  # version marker preserved
    assert data["ui_theme"] == "dark"  # dirty key merged in

    # a known key with a bad value still errors even under a newer version
    cfg.write_text("config_version = 2\nserver_port = 99999\n", encoding="utf-8")
    with pytest.raises(ConfigError) as bad:
        load_config(base_env(cfg))
    assert "server_port" in str(bad.value)


# ---------------------------------------------------------------------------
# 5: FLAT_KEYS roundtrip
# ---------------------------------------------------------------------------

ROUNDTRIP_VALUES: dict[str, object] = {
    # general (vllm_api_key skipped: credential)
    "config_version": 1,
    "server_mode": "remote",
    "inference_engine": "vllm",
    "server_host": "192.168.1.50",
    "server_port": 12345,
    "vllm_port": 12346,
    "sglang_port": 12347,
    "mlx_port": 12348,
    "local_model_path": "D:/models/qwen",
    "local_model_name": "qwen2.5-7b",
    "local_chat_model": "chat-qwen",
    "model_dirs": ["D:/models", "C:/ai"],
    "auto_start_server": False,
    "vllm_api_base": "http://127.0.0.1:12346",
    "vllm_model_name": "vllm-model",
    # tuning
    "server_ctx_size": 4096,
    "server_parallel": 2,
    "server_batch_size": 512,
    "server_ubatch_size": 128,
    "server_temp": 0.7,
    "server_top_p": 0.95,
    "server_top_k": 80,
    "server_repeat_penalty": 1.3,
    "server_gpu_layers": 16,
    "server_cache_type_k": "f16",
    "server_cache_type_v": "q4_0",
    "server_auto_tune": True,
    "server_auto_tune_min_ctx": 2048,
    "server_idle_unload_minutes": 30,
    "server_fallback_models": ["fallback-a"],
    "server_load_mode": "gpu",
    "server_flash_attn": "on",
    # engines
    "llama_cpp_extra_args": ["--n-gpu-layers", "16"],
    "vllm_extra_args": ["--max-model-len", "4096"],
    "sglang_extra_args": ["--chunked-prefill-size", "512"],
    "mlx_extra_args": [],
    # embedding (embedding_api_key skipped: credential)
    "embedding_port": 18200,
    "embedding_pooling": "mean",
    "embedding_model": "bge-m3",
    "embedding_base": "http://127.0.0.1:18200",
    # gateway (gateway_api_key skipped: credential)
    "gateway_enabled": False,
    "gateway_host": "127.0.0.1",
    "gateway_port": 10001,
    # network
    "proxy_mode": "manual",
    "proxy_url": "http://proxy.lan:8080",
    "proxy_allow_local_network": False,
    # downloads
    "download_files": 8,
    "download_parts": 2,
    # ui
    "ui_lang": "en",
    "ui_theme": "dark",
    "ui_app_rail_layout": "rail",
    # updates
    "update_channel": "beta",
    "auto_update": False,
    # logs
    "log_level": "debug",
    "log_json": True,
    "log_max_bytes": 100_000,
    "log_backups": 10,
}


def test_flat_keys_full_roundtrip_preserves_values_and_types(tmp_path):
    """Set every settable FLAT_KEYS entry (60 - 3 credentials = 57), save,
    reload into a fresh store, and compare the whole config for equality —
    catches coercion drift on floats, bools, Nones and lists."""
    assert len(FLAT_KEYS) == 60
    assert len(ROUNDTRIP_VALUES) == len(FLAT_KEYS) - len(CREDENTIAL_KEYS)
    assert not (set(ROUNDTRIP_VALUES) & CREDENTIAL_KEYS)

    cfg = tmp_path / "settings.toml"
    store = make_store(cfg)
    for key, value in ROUNDTRIP_VALUES.items():
        store.set(key, value)
    store.save()

    text = cfg.read_text(encoding="utf-8")
    assert "vllm_api_key" not in text
    assert "embedding_api_key" not in text
    assert "gateway_api_key" not in text
    data = tomllib.loads(text)
    assert set(data) == set(ROUNDTRIP_VALUES)  # every key materialized in the file

    reloaded = make_store(cfg)
    assert reloaded.config == store.config

    # an optional key set to None is removed from the file, not written
    store.set("local_model_path", None)
    store.save()
    data2 = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert "local_model_path" not in data2
    final = load_config(base_env(cfg))
    assert final.general.local_model_path is None
    assert final == store.config  # store's memory was mutated to None by set()


# ---------------------------------------------------------------------------
# 6: credential policy
# ---------------------------------------------------------------------------


def test_set_rejects_credentials_url_credentials_and_scrubs_handwritten(tmp_path):
    """set() refuses the 3 credential keys and any string value with an inline
    URL credential (top-level or inside a list), leaving memory untouched;
    hand-written credential values load but are scrubbed by save()."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text('vllm_api_key = "sk-hand-written"\n', encoding="utf-8")
    store = make_store(cfg)
    # hand-written credential still loads into the model (documented behavior)
    assert store.config.general.vllm_api_key == "sk-hand-written"

    for key in ("vllm_api_key", "embedding_api_key", "gateway_api_key"):
        with pytest.raises(ConfigError) as cred:
            store.set(key, "whatever")
        assert "never persisted" in str(cred.value)

    with pytest.raises(ConfigError) as url_top:
        store.set("proxy_url", "http://user:pass@proxy.lan:8080")
    assert "inline URL credential" in str(url_top.value)

    with pytest.raises(ConfigError) as url_list:
        store.set("llama_cpp_extra_args", ["--host", "https://Alice:Secret@host.example/x"])
    assert "inline URL credential" in str(url_list.value)

    with pytest.raises(ConfigError) as url_case:
        store.set("proxy_url", "HTTP://U:P@HOST")
    assert "inline URL credential" in str(url_case.value)

    # rejected sets left memory byte-identical: only the good value lands
    store.set("proxy_url", "http://proxy.lan:8080")  # user@host without password is fine
    store.set("server_port", 12345)
    store.save()
    text = cfg.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    assert data["proxy_url"] == "http://proxy.lan:8080"
    assert data["server_port"] == 12345
    assert "vllm_api_key" not in data  # hand-written credential scrubbed
    assert "user:pass@" not in text and "Alice:Secret@" not in text
    assert store.config.general.vllm_api_key == "sk-hand-written"  # memory untouched by save


# ---------------------------------------------------------------------------
# 7-8: lock and crash atomicity
# ---------------------------------------------------------------------------


def test_stale_lock_file_fails_save_within_documented_timeout(tmp_path):
    """A pre-existing (stale) lock must make save() raise ConfigError within
    the documented 5s window, name the lock path, and never hang forever;
    the foreign lock file must survive the failed save."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text('server_host = "original"\n', encoding="utf-8")
    lock = cfg.with_suffix(cfg.suffix + ".lock")
    lock.write_bytes(b"stale lock from a dead process")
    store = make_store(cfg)
    store.set("server_port", 12345)

    start = time.perf_counter()
    with pytest.raises(ConfigError) as locked:
        store.save()
    elapsed = time.perf_counter() - start

    assert 4.0 <= elapsed <= 8.0, f"stale-lock timeout took {elapsed:.2f}s"
    assert "locked by another process" in str(locked.value)
    assert str(lock) in str(locked.value)
    assert lock.exists()  # save must not delete a lock it does not own
    assert tomllib.loads(cfg.read_text(encoding="utf-8")) == {"server_host": "original"}


def test_crashed_save_leaves_tmp_that_next_load_and_save_ignore(tmp_path):
    """A subprocess killed between mkstemp and os.replace leaves a .tmp file:
    the next load and the next save both succeed and the file stays valid."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text('server_host = "survivor"\n', encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", CHILD_CRASH_BEFORE_REPLACE, str(tmp_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
        env=child_env(),
        check=False,
    )
    assert proc.returncode == 1  # died via os._exit(1) as designed
    crashed_tmp = tmp_path / ".settings-crashed.tmp"
    assert crashed_tmp.exists()

    config = load_config(base_env(cfg))  # leftover tmp does not break load
    assert config.general.server_host == "survivor"

    store = ConfigStore(cfg, config)
    store.set("server_port", 12346)
    store.save()  # must not be confused by the foreign tmp file

    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert data == {"server_host": "survivor", "server_port": 12346}
    # save leaves no NEW temps behind (its own was renamed into place);
    # the crashed one is untouched by the loader
    leftovers = sorted(p.name for p in tmp_path.glob(".settings-*.tmp"))
    assert leftovers == [".settings-crashed.tmp"]


# ---------------------------------------------------------------------------
# 9-10: real multi-process behavior
# ---------------------------------------------------------------------------


def test_multiprocess_concurrent_saves_keep_every_key(tmp_path):
    """Six real subprocesses each set a distinct key and save on the same
    store: the advisory lock serializes them, all keys survive, and the file
    stays valid TOML."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text('server_host = "base"\n', encoding="utf-8")
    jobs = [
        ("server_host", "10.1.0.1"),
        ("local_model_name", "model-child-a"),
        ("embedding_model", "emb-child"),
        ("gateway_host", "10.1.0.3"),
        ("vllm_model_name", "vllm-child"),
        ("ui_app_rail_layout", "rail-child"),
    ]
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD_SET_AND_SAVE, key, value, str(cfg)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=child_env(),
        )
        for key, value in jobs
    ]
    for proc, (key, _) in zip(procs, jobs):
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 0, f"child for {key} failed rc={proc.returncode}\n{out}\n{err}"

    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    for key, value in jobs:
        assert data.get(key) == value, f"key {key} lost by concurrent writers"
    config = load_config(base_env(cfg))
    for key, value in jobs:
        assert getattr(getattr(config, FLAT_KEYS[key]), key) == value


def test_kill_during_save_loop_leaves_config_loadable(tmp_path):
    """Hard-killing a process in the middle of a save loop must never leave an
    unreadable config.toml; if the kill stranded the advisory lock, removing
    it (documented remediation) restores normal saves."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text('server_host = "10.0.0.1"\n', encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-c", CHILD_SAVE_LOOP, str(cfg)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=child_env(),
    )
    try:
        time.sleep(0.6)
        proc.kill()
        proc.communicate(timeout=15)
    finally:
        if proc.poll() is None:  # pragma: no cover - only if kill failed
            proc.kill()
            proc.communicate(timeout=15)

    # file must be valid TOML and loadable no matter where the kill landed
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "server_host" in data
    config = load_config(base_env(cfg))
    assert config.general.server_host.startswith("10.0.0.")

    lock = cfg.with_suffix(cfg.suffix + ".lock")
    if lock.exists():  # kill landed while the lock was held: stale-lock case
        lock.unlink()  # documented remediation for a confirmed-dead process
    store = ConfigStore(cfg, config)
    store.set("server_port", 12399)
    store.save()
    assert tomllib.loads(cfg.read_text(encoding="utf-8"))["server_port"] == 12399


# ---------------------------------------------------------------------------
# 11: read-only destination
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="read-only attribute semantics are Windows")
def test_readonly_config_file_save_fails_clean(tmp_path):
    """A read-only config file makes os.replace fail: save() must map that to
    a clean ConfigError, leave the original bytes untouched, and remove the
    staged temp file."""
    cfg = tmp_path / "settings.toml"
    cfg.write_text('server_host = "readonly-target"\n', encoding="utf-8")
    original_bytes = cfg.read_bytes()
    store = make_store(cfg)
    store.set("server_port", 12355)
    os.chmod(cfg, stat.S_IREAD)
    try:
        with pytest.raises(ConfigError) as denied:
            store.save()
        assert "cannot write settings file" in str(denied.value)
        assert cfg.read_bytes() == original_bytes  # no partial write
        assert not list(tmp_path.glob(".settings-*.tmp"))  # temp cleaned up
        assert not (tmp_path / "settings.toml.lock").exists()  # lock released
    finally:
        os.chmod(cfg, stat.S_IWRITE)


# ---------------------------------------------------------------------------
# 12: paths.py edge cases
# ---------------------------------------------------------------------------


def test_paths_whitespace_overrides_fallback_and_layout(tmp_path):
    """Empty/whitespace IPO_DATA_DIR/IPO_CONFIG/IPO_DB_PATH fall back to the
    ~/.ipostudio defaults; ensure_layout creates (and re-creates) nested dirs;
    bootstrap vars never leak into config keys."""
    for var in ("IPO_DATA_DIR", "IPO_CONFIG", "IPO_DB_PATH"):
        assert resolve_data_dir({var: "   \t " if var == "IPO_DATA_DIR" else ""}) == HOME_ROOT
    assert resolve_data_dir({}) == HOME_ROOT
    assert resolve_config_path({}) == HOME_ROOT / "settings.toml"
    assert resolve_db_path({"IPO_DB_PATH": " \t "}) == HOME_ROOT / "data" / "app.db"
    assert resolve_config_path({"IPO_DATA_DIR": str(tmp_path)}) == tmp_path / "settings.toml"

    root = tmp_path / "layout"
    assert ensure_layout(root) == root
    for sub in IPO_SUBDIRS:
        assert (root / sub).is_dir(), f"missing subdir {sub}"
    assert any(("/" in sub) for sub in IPO_SUBDIRS)  # nested entries exist...
    assert (root / "media" / "images").is_dir()  # ...and are fully materialized
    ensure_layout(root)  # second run is a no-op, not an error
    for sub in IPO_SUBDIRS:
        assert (root / sub).is_dir()

    via_env = ensure_layout(env={"IPO_DATA_DIR": str(tmp_path / "envroot")})
    assert (via_env / "logs").is_dir()

    # bootstrap vars are excluded from the override loop: no unknown-key error
    cfg = tmp_path / "settings.toml"
    cfg.write_text('server_host = "bootstrap-ok"\n', encoding="utf-8")
    config = load_config({"IPO_CONFIG": str(cfg), "IPO_DATA_DIR": str(tmp_path)})
    assert config.general.server_host == "bootstrap-ok"
