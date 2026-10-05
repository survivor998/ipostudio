"""Translate config tuning into llama-server argv (its documented public CLI).

Sampling parameters (temp/top_p/top_k/repeat_penalty) are REQUEST-time, not
server flags — `ipo chat` sends them per completion.  `--flash-attn auto`
and load_mode auto/gpu omit their flags so engine defaults stand."""

from pathlib import Path

from ipostudio.conf.schema import ServerTuning


def build_server_argv(
    engine: Path,
    model_path: Path,
    host: str,
    port: int,
    tuning: ServerTuning,
    extra_args: list[str],
) -> list[str]:
    argv = [
        str(engine),
        "--model", str(model_path),
        "--host", host,
        "--port", str(port),
        "--ctx-size", str(tuning.server_ctx_size),
        "--parallel", str(tuning.server_parallel),
        "--batch-size", str(tuning.server_batch_size),
        "--ubatch-size", str(tuning.server_ubatch_size),
        "--cache-type-k", tuning.server_cache_type_k,
        "--cache-type-v", tuning.server_cache_type_v,
    ]
    if tuning.server_gpu_layers is not None:
        argv += ["--n-gpu-layers", str(tuning.server_gpu_layers)]
    elif tuning.server_load_mode == "cpu":
        argv += ["--n-gpu-layers", "0"]  # explicit CPU pinning
    if tuning.server_flash_attn in ("on", "off"):
        argv += ["--flash-attn", tuning.server_flash_attn]
    # Managed flags must not be overridable via extras: the engine honors
    # the last occurrence, so an extra --port/--host/--model would desync
    # the recorded instance row from reality (Codex ENG fold)
    managed = {"--model", "-m", "--host", "--port"}
    for arg in extra_args:
        flag = str(arg).split("=", 1)[0]
        if flag in managed:
            raise ValueError(
                f"llama_cpp_extra_args contains managed flag {flag!r}; manage "
                f"it via its config key (server_host / server_port / model "
                f"selection) instead"
            )
    argv += [str(arg) for arg in extra_args]
    return argv
