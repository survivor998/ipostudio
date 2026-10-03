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
    ipo version
    ipo doctor          # read-only health check
    ipo doctor --fix    # create data layout + initialize storage
    ipo guide           # full command manual (markdown/text/json)

## Configuration
Settings live at ~/.ipostudio/settings.toml (override with IPO_DATA_DIR or
`ipo --data-dir/--config`). Every key can be overridden via IPO_<KEY> env vars.
See `ipo guide` and docs/design/architecture.md (ADR-003).

## Docs
docs/design/ — architecture decisions, roadmap, requirement addenda.
