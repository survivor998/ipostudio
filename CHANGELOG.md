# Changelog

## [Unreleased]

### Added
- `ipo models` / `ipo model --select` / `ipo model-info`: local GGUF catalog
  (scan, activate, details) backed by a new `models` table.
- `ipo server start/stop/restart/list/info/logs` and the `ipo
  start/status/stop/restart` shorthands: single-instance llama.cpp
  supervision with SQLite-persisted service states (stopped/starting/
  loading/running/failed), occupied-port avoidance, and per-process engine
  logs (`logs/engine-llama-cpp.log`).
- `ipo chat PROMPT`: one non-streaming completion against the running server
  via its OpenAI-compatible endpoint; every attempt (ok or error) is recorded
  in a new `completions` table and visible after restarts.
- Stop safety: `ipo server stop` proves port ownership against the engine's
  `/props` document before signaling; a foreign listener is refused with
  manual guidance, a silent port sends no signal, and a timed-out startup
  terminates its engine instead of orphaning it.
- `engines.llama_cpp_path` config key (empty = resolve `llama-server` from
  PATH).
- Config files are stamped with `config_version` on save so a downgrade
  degrades gracefully instead of rejecting a config this build wrote;
  conversation records are redacted for secret-shaped tokens at the
  persistence boundary.
- `ipo guide`/`ipo help` now document command arguments and subcommand
  options (server/config children included).
- First-run welcome card now points initialized users at `ipo models`.

## 0.1.0 (unreleased)
- Initial P1 foundation: package skeleton, config system (spec 11.2),
  rotating redacting logs, SQLite migration layer, `ipo` CLI
  (version/help/guide/doctor), three-platform CI matrix.
- CLI ergonomics: `ipo config` (path/get/set/list) over the existing config
  store, doctor summary line, first-run welcome card on bare `ipo`,
  did-you-mean command suggestions, NO_COLOR-aware presentation layer.
