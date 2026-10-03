"""Typed schema for every core config key in spec §11.2 plus foundation log keys.

File/env key naming rule (ADR-003): config key = lower snake case of the spec key
without the ``IPO_`` prefix; environment form = ``IPO_`` + upper(config key).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CacheType = Literal["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneralConfig(_Strict):
    # Forward-compatibility marker: files written by a NEWER build (higher
    # config_version) get warn-and-ignore for unknown keys so rollback after
    # auto-update does not brick the config (CEO review consensus).
    config_version: int = Field(default=1, ge=1)
    server_mode: Literal["local", "remote"] = "local"
    inference_engine: Literal["llama.cpp", "vllm", "sglang", "mlx"] = "llama.cpp"
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=18080, ge=1, le=65535)
    vllm_port: int = Field(default=8081, ge=1, le=65535)
    sglang_port: int = Field(default=8082, ge=1, le=65535)
    mlx_port: int = Field(default=18010, ge=1, le=65535)
    local_model_path: str | None = None
    local_model_name: str | None = None
    local_chat_model: str | None = None
    model_dirs: list[str] = Field(default_factory=list)
    auto_start_server: bool = True
    vllm_api_base: str = ""
    vllm_api_key: str = ""
    vllm_model_name: str = ""


class ServerTuning(_Strict):
    server_ctx_size: int = Field(default=8192, ge=128)
    server_parallel: int = Field(default=1, ge=1)
    server_batch_size: int = Field(default=256, ge=1)
    server_ubatch_size: int = Field(default=64, ge=1)
    server_temp: float = Field(default=0.2, ge=0.0, le=2.0)
    server_top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    server_top_k: int = Field(default=40, ge=0)
    server_repeat_penalty: float = Field(default=1.12, ge=1.0, le=2.0)
    server_gpu_layers: int | None = Field(default=None, ge=0)
    server_cache_type_k: CacheType = "q8_0"
    server_cache_type_v: CacheType = "q8_0"
    server_auto_tune: bool = False
    server_auto_tune_min_ctx: int = Field(default=4096, ge=0)
    server_idle_unload_minutes: int = Field(default=0, ge=0)
    server_fallback_models: list[str] = Field(default_factory=list)
    server_load_mode: Literal["auto", "cpu", "gpu"] = "auto"
    server_flash_attn: Literal["auto", "on", "off"] = "auto"


class EngineExtras(_Strict):
    llama_cpp_extra_args: list[str] = Field(default_factory=list)
    vllm_extra_args: list[str] = Field(default_factory=list)
    sglang_extra_args: list[str] = Field(default_factory=list)
    mlx_extra_args: list[str] = Field(default_factory=list)


class EmbeddingConfig(_Strict):
    embedding_port: int = Field(default=18190, ge=1, le=65535)
    embedding_pooling: Literal["last", "mean"] = "last"
    embedding_model: str = ""
    embedding_base: str = ""
    embedding_api_key: str = ""


class GatewayConfig(_Strict):
    gateway_enabled: bool = True
    gateway_host: str = "127.0.0.1"
    gateway_port: int = Field(default=10000, ge=1, le=65535)
    gateway_api_key: str = ""


class NetworkConfig(_Strict):
    proxy_mode: Literal["system", "manual", "direct"] = "system"
    proxy_url: str = ""
    proxy_allow_local_network: bool = True


class DownloadsConfig(_Strict):
    download_files: int = Field(default=2, ge=1, le=16)
    download_parts: int = Field(default=4, ge=1, le=16)


class UiConfig(_Strict):
    ui_lang: Literal["zh", "en"] = "zh"
    ui_theme: Literal["light", "dark", "system"] = "system"
    ui_app_rail_layout: str = "default"


class UpdateConfig(_Strict):
    update_channel: Literal["stable", "beta"] = "stable"
    auto_update: bool = True


class LogConfig(_Strict):
    """Foundation-owned keys (spec §5.23/§15 behaviour; key names are our own design)."""

    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_json: bool = False
    log_max_bytes: int = Field(default=2_000_000, ge=64_000)
    log_backups: int = Field(default=5, ge=1, le=50)


class AppConfig(_Strict):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    tuning: ServerTuning = Field(default_factory=ServerTuning)
    engines: EngineExtras = Field(default_factory=EngineExtras)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    downloads: DownloadsConfig = Field(default_factory=DownloadsConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    updates: UpdateConfig = Field(default_factory=UpdateConfig)
    logs: LogConfig = Field(default_factory=LogConfig)


FAMILIES: dict[str, type[BaseModel]] = {
    "general": GeneralConfig,
    "tuning": ServerTuning,
    "engines": EngineExtras,
    "embedding": EmbeddingConfig,
    "gateway": GatewayConfig,
    "network": NetworkConfig,
    "downloads": DownloadsConfig,
    "ui": UiConfig,
    "updates": UpdateConfig,
    "logs": LogConfig,
}


def _build_flat_keys() -> dict[str, str]:
    flat: dict[str, str] = {}
    for family, model in FAMILIES.items():
        for field_name in model.model_fields:
            if field_name in flat:
                raise RuntimeError(f"duplicate config key across families: {field_name}")
            flat[field_name] = family
    return flat


FLAT_KEYS: dict[str, str] = _build_flat_keys()
