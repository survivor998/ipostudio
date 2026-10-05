# ipostudio

Local-first AI workstation: models, inference, multimodal apps, agents and
memory in one tool. Clean-room implementation against the functional spec.

Status: P1 foundation (install/config/logging/storage/CLI skeleton). The first
end-to-end model workflow lands at milestone M0' / P1.5 vertical slice (see
docs/design/roadmap.md).

## Requirements
- Python >= 3.11 (Windows / Linux / macOS)

## Install (development)
    python -m venv .venv
    # Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
    python -m pip install -e ".[dev]"

## Run the tests
    python -m pytest -v

## Quickstart
    ipo                        # first-run welcome card
    ipo doctor --fix           # initialize storage + verify the environment
    ipo config list            # browse every setting (env > file > default)
    ipo config set ui_theme dark
    ipo guide                  # full command manual (markdown/text/json)

## Configuration
Settings live at ~/.ipostudio/settings.toml (override with IPO_DATA_DIR or
`ipo --data-dir/--config`). Every key can be overridden via IPO_<KEY> env vars;
read values with `ipo config get KEY`, write them with `ipo config set KEY VALUE`
(validation, atomic write, 'none' clears an optional key). Examples:

    ipo config set server_port 19000          # integer
    ipo config set auto_start_server off      # boolean: on/off/true/false
    ipo config set model_dirs '["D:/models", "/data/models"]'   # list (JSON)
    ipo config set local_model_path none      # clear an optional key

A value that starts with a dash needs click's `--` separator before it (e.g.
`ipo config set vllm_api_base -- -stage-endpoint`); if a shell environment
already overrides a key, saving still works but the env value wins until you
unset it (the command warns on stderr).

Saving scrubs any hand-written credential keys from the file — pass API keys
via the environment instead, e.g. IPO_VLLM_API_KEY. Resetting a non-optional
key to its default: remove the line from settings.toml (`ipo config path`).
See `ipo guide` and docs/design/architecture.md (ADR-003).

## Core loop quickstart

The minimal loop: scan a local model, activate it, start the llama.cpp
server, complete one prompt — records persist across restarts.

1. Install llama.cpp and put `llama-server` on your PATH (official releases:
   <https://github.com/ggml-org/llama.cpp/releases>; Homebrew:
   `brew install llama.cpp`; on Windows grab `llama-server-<edition>-win-x64.zip`
   from the same releases page, or `winget install ggml.llama.cpp`). Or point
   the `llama_cpp_path` setting at the executable:
   `ipo config set llama_cpp_path "C:\llama\llama-server.exe"`. On Linux,
   unpack the release build for your architecture onto your `PATH`
   (e.g. `~/.local/bin`).
2. Download any small instruct GGUF (e.g. Qwen2.5-0.5B-Instruct or
   Llama-3.2-1B-Instruct from Hugging Face or ModelScope — with
   `pip install huggingface_hub` a single `huggingface-cli download
   <repo-id> --include *.gguf --local-dir .` fetches one) and drop it into
   `<data-dir>\models` (default `~/.ipostudio/models`; `ipo doctor --fix`
   creates the directory if it does not exist yet), or register another
   directory: `ipo config set model_dirs -- '["D:/models"]'`.
3. Run the loop:

    ipo doctor --fix          # one-time: create the data layout
    ipo models                # scan and list local .gguf models
    ipo model --select NAME   # activate one as the default chat model
    ipo server start          # launch llama-server (picks a free port)
    ipo chat "hello"          # one completion through the running server
    ipo status                # state, address, live health
    ipo server info           # instance + last completion record
    ipo server stop           # stop (idempotent)

Notes: completion records and instance history live in SQLite and survive
restarts (`ipo server info`, `ipo server list`). Closing the terminal that
started the server may stop the engine (durable background service comes
with the engine-supervision plan). Model downloading and engine installation
stay manual until the model-management plan lands its downloader. Use a
recent llama.cpp release: `server_flash_attn: on/off` needs a build whose
`llama-server` accepts valued `--flash-attn` (the default `auto` omits the
flag and works everywhere). Chat records are redacted for secret-shaped
tokens (Bearer / `sk-`…) at the persistence boundary and stay in the local
SQLite file; retention controls arrive with the model-management plan. The
engine writes its own stdout/stderr verbatim to `logs/engine-llama-cpp.log`
— display is redacted, but treat that file as raw engine output.
`ipo server stop` proves port ownership against the engine's `/props`
document before signaling and refuses a foreign listener. Shorthand
semantics: `ipo start --model NAME` persists the selection; `ipo server
start/restart --model NAME` overrides for that command only; `ipo start` is
a no-op success when a server is already running, while `ipo server start`
reports the conflict as an error.

## Terminal output
Human output is colored only on interactive terminals; it degrades to plain
text when piped, when NO_COLOR is set (any non-empty value), or TERM=dumb.
FORCE_COLOR forces color on for pagers/CI with VT support. `--json` output is
always machine-readable and never styled.

## Exit codes
0 success; 1 check/runtime failure (doctor, config); 2 usage error.

## Docs
docs/design/ — architecture decisions, roadmap, requirement addenda.
