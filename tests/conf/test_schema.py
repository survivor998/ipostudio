import pytest
from pydantic import ValidationError

from ipostudio.conf.schema import FLAT_KEYS, AppConfig

# Single source of truth for spec §11.2 default conformance: add a row when a
# key is added; the test derives from this table (CEO review: scattered
# verbatim assertions rot on every spec edit).
SPEC_DEFAULTS = {
    ("general", "server_mode"): "local",
    ("general", "inference_engine"): "llama.cpp",
    ("general", "server_host"): "127.0.0.1",
    ("general", "server_port"): 18080,
    ("general", "vllm_port"): 8081,
    ("general", "sglang_port"): 8082,
    ("general", "mlx_port"): 18010,
    ("general", "auto_start_server"): True,
    ("tuning", "server_ctx_size"): 8192,
    ("tuning", "server_parallel"): 1,
    ("tuning", "server_batch_size"): 256,
    ("tuning", "server_ubatch_size"): 64,
    ("tuning", "server_temp"): 0.2,
    ("tuning", "server_top_p"): 0.9,
    ("tuning", "server_top_k"): 40,
    ("tuning", "server_repeat_penalty"): 1.12,
    ("tuning", "server_cache_type_k"): "q8_0",
    ("tuning", "server_cache_type_v"): "q8_0",
    ("tuning", "server_auto_tune"): False,
    ("tuning", "server_auto_tune_min_ctx"): 4096,
    ("tuning", "server_idle_unload_minutes"): 0,
    ("tuning", "server_fallback_models"): [],
    ("tuning", "server_load_mode"): "auto",
    ("tuning", "server_flash_attn"): "auto",
    ("embedding", "embedding_port"): 18190,
    ("embedding", "embedding_pooling"): "last",
    ("gateway", "gateway_enabled"): True,
    ("gateway", "gateway_host"): "127.0.0.1",
    ("gateway", "gateway_port"): 10000,
    ("gateway", "gateway_api_key"): "",
    ("network", "proxy_mode"): "system",
    ("network", "proxy_url"): "",
    ("network", "proxy_allow_local_network"): True,
    ("downloads", "download_files"): 2,
    ("downloads", "download_parts"): 4,
    ("ui", "ui_lang"): "zh",
    ("ui", "ui_theme"): "system",
    ("ui", "ui_app_rail_layout"): "default",
    ("updates", "update_channel"): "stable",
    ("updates", "auto_update"): True,
}


def test_defaults_match_spec_11_2():
    cfg = AppConfig()
    for (family, key), expected in SPEC_DEFAULTS.items():
        assert getattr(getattr(cfg, family), key) == expected, f"{family}.{key}"


def test_unknown_key_rejected_in_every_family():
    with pytest.raises(ValidationError):
        AppConfig(general={"no_such_key": 1})
    with pytest.raises(ValidationError):
        AppConfig(tuning={"server_ctx_size": 8192, "mystery": True})


def test_enum_and_range_validation():
    with pytest.raises(ValidationError):
        AppConfig(general={"inference_engine": "tensorrt"})
    with pytest.raises(ValidationError):
        AppConfig(tuning={"server_ctx_size": 32})
    with pytest.raises(ValidationError):
        AppConfig(general={"server_port": 70000})
    with pytest.raises(ValidationError):
        AppConfig(ui={"ui_theme": "solarized"})
    with pytest.raises(ValidationError):
        AppConfig(network={"proxy_mode": "tor"})


def test_flat_keys_unique_and_cover_expected_fields():
    assert len(FLAT_KEYS) == len(set(FLAT_KEYS))
    for must in (
        "server_port", "server_ctx_size", "gateway_api_key", "embedding_pooling",
        "download_files", "ui_lang", "update_channel", "llama_cpp_extra_args",
        "server_fallback_models", "vllm_model_name",
    ):
        assert must in FLAT_KEYS
