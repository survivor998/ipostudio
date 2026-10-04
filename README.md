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

## Terminal output
Human output is colored only on interactive terminals; it degrades to plain
text when piped, when NO_COLOR is set (any non-empty value), or TERM=dumb.
FORCE_COLOR forces color on for pagers/CI with VT support. `--json` output is
always machine-readable and never styled.

## Exit codes
0 success; 1 check/runtime failure (doctor, config); 2 usage error.

## Docs
docs/design/ — architecture decisions, roadmap, requirement addenda.
