from pathlib import Path

import pytest

from ipostudio.conf.loader import ConfigError, ConfigStore, load_config


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


def test_newer_config_version_unknown_keys_ignored_with_warning(tmp_path):
    write_settings(tmp_path, "config_version = 99\nfuture_key_xyz = 1\n")
    warnings: list[str] = []
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path)}, warnings=warnings)
    assert cfg.general.config_version == 99
    assert any("future_key_xyz" in w for w in warnings)
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
