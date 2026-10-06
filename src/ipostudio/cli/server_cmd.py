"""`ipo server` management (spec §9.11).

start spawns the engine and exits; the SQLite instance row is the
coordination point for later stop/status processes (supervisor docstring has
the process model).  Contract: `server info`/`server list` are informational
and exit 0 even when nothing runs — the QA --json walker invokes them on a
fresh data directory and requires exit 0."""

import json
import math
from pathlib import Path

import click

from ipostudio.catalog.repo import find_model, upsert_models
from ipostudio.catalog.scan import (
    model_scan_roots,
    scan_model_files,
    shard_family_complete,
)
from ipostudio.cli.base import (
    _fail,
    _SuggestingGroup,
    open_config_and_db,
    open_db_only,
)
from ipostudio.cli.models_cmd import activate_model
from ipostudio.cli.ui import local_time
from ipostudio.conf.loader import ConfigError
from ipostudio.conf.paths import resolve_data_dir
from ipostudio.engines.discovery import resolve_engine
from ipostudio.engines.llama_server import build_server_argv
from ipostudio.engines.repo import (
    active_instance,
    last_completion,
    recent_instances,
)
from ipostudio.engines.supervisor import (
    choose_port,
    engine_log_path,
    probe_health,
    start_instance,
    stop_instance,
)
from ipostudio.logs import redact_text

DEFAULT_TIMEOUT_S = 600.0  # spec §15: local inference budget

def _resolve_model(conn, cfg, wanted: str | None) -> dict:
    # ENG F10: one scan-and-upsert helper serves both `ipo models` and the
    # server path, so the two surfaces always see the same catalog view
    from ipostudio.cli.models_cmd import _refresh

    _refresh(conn, cfg)
    target = wanted or cfg.general.local_chat_model
    if not target:
        _fail(
            "no model selected; run `ipo model --select NAME` "
            "(catalog: `ipo models`)"
        )
    matches = find_model(conn, target)
    if not matches:
        _fail(f"no local model matches {target!r}; run `ipo models`")
    if len(matches) > 1:
        _fail(f"ambiguous model match for {target!r}; use a full name or path")
    model = matches[0]
    # ENG F3: the catalog is insert-only until P2 pruning — a deleted file
    # must fail here with a rescan hint, not surface as an engine crash
    if not Path(model["path"]).exists():
        _fail(
            f"model file no longer exists: {model['path']}; it may have been "
            f"moved or deleted — re-run `ipo models` to refresh the catalog"
        )
    # insert-only catalog: a family that lost a shard after registration
    # would crash the engine mid-load — revalidate before launch (Codex
    # stale-row fold)
    if not shard_family_complete(Path(model["path"])):
        _fail(
            f"model {model['name']!r} is incomplete on disk (a shard is "
            f"missing); re-run `ipo models` and re-register the full set"
        )
    return model

def _warn_reserved_tuning(cfg) -> None:
    """Spec §1.3 rule 3: reserved capability must be labelled, never silent."""
    if cfg.tuning.server_auto_tune:
        click.echo(
            "warning: server_auto_tune is on but automatic planning is not "
            "implemented yet; using your configured values as-is",
            err=True,
        )
    if cfg.tuning.server_idle_unload_minutes:
        click.echo(
            "warning: server_idle_unload_minutes is set but idle unloading is "
            "not implemented yet; the server stays up",
            err=True,
        )
    if cfg.tuning.server_fallback_models:
        click.echo(
            "warning: server_fallback_models is set but fallback is not "
            "implemented yet; the list is ignored",
            err=True,
        )

def _run_start(conn, cfg, model_name: str | None, host: str | None,
               port: int | None, timeout_s: float) -> None:
    """Shared by `ipo server start`, `ipo start` and `ipo restart`."""
    if port is not None and not 1 <= port <= 65535:
        _fail(f"--port must be within 1..65535, got {port}")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        _fail("--timeout must be a finite positive number of seconds")
    if cfg.general.server_mode != "local":
        _fail(
            f"server_mode is {cfg.general.server_mode!r}; remote operation "
            f"arrives with the gateway plan — switch back with "
            f"`ipo config set server_mode local`"
        )
    if cfg.general.inference_engine != "llama.cpp":
        _fail(
            f"inference_engine is {cfg.general.inference_engine!r}; only "
            f"llama.cpp is supported in this build (vllm/sglang/mlx arrive "
            f"with the engine-supervision plan) — switch back with "
            f"`ipo config set inference_engine llama.cpp`"
        )
    _warn_reserved_tuning(cfg)
    running = active_instance(conn)
    if running is not None:
        _fail(
            f"server already {running['state']} at "
            f"http://{running['host']}:{running['port']} "
            f"(model {running['model_name']}); use `ipo server restart` "
            f"to swap models"
        )
    engine_path, problem = resolve_engine(cfg.engines.llama_cpp_path)
    if engine_path is None:
        _fail(problem)
    model = _resolve_model(conn, cfg, model_name)
    host = host or cfg.general.server_host
    port_given = port is not None
    if port is None:
        port = choose_port(host, cfg.general.server_port)
        if port is None:
            _fail(
                f"no free port in {cfg.general.server_port}.."
                f"{cfg.general.server_port + 19} on {host}"
            )
    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo(
            f"warning: binding {host} exposes the engine's UNAUTHENTICATED "
            f"completions endpoint to your network; keep server_host on "
            f"loopback unless you accept that",
            err=True,
        )
    try:
        argv = build_server_argv(
            engine_path, Path(model["path"]), host, port, cfg.tuning,
            cfg.engines.llama_cpp_extra_args,
        )
    except ValueError as exc:
        # managed-flag rejection must meet the error contract at the command
        # seam too: start/start-shorthand and both restarts share this path
        _fail(str(exc))
    log_path = engine_log_path(resolve_data_dir())
    outcome = start_instance(
        conn, argv, engine="llama.cpp", model_name=model["name"],
        model_path=model["path"], host=host, port=port, log_path=log_path,
        timeout_s=timeout_s,
    )
    instance = outcome.instance
    if not outcome.ok:
        detail = instance["detail"]
        if port_given:
            detail += (
                f" (you passed --port {port}; verify that port is free "
                f"on {host})"
            )
        _fail(detail)
    click.echo(
        f"server running: http://{host}:{port} (model {model['name']}, "
        f"pid {instance['pid']}, log {log_path})"
    )
    click.echo("note: closing the terminal that started the server may stop it "
               "(durable background service arrives with the engine plan)")
    click.echo('try `ipo chat "hello"` or `ipo status`')

@click.group("server", cls=_SuggestingGroup)
def server() -> None:
    """Manage the local inference server (subcommands: start, stop, restart,
    list, info, logs)."""

@server.command("start")
@click.option("--model", "model_name", default=None, metavar="NAME",
              help="model to serve (default: the active chat model)")
@click.option("--host", default=None, help="override the configured server_host")
@click.option("--port", type=int, default=None,
              help="exact port to bind (no avoidance is applied; default: the "
                   "configured server_port with occupied-port avoidance)")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True, help="seconds to wait for engine readiness")
def server_start(model_name: str | None, host: str | None, port: int | None,
                 timeout_s: float) -> None:
    """Start the llama.cpp server for the active (or named) model."""
    conn, cfg = open_config_and_db()
    try:
        _run_start(conn, cfg, model_name, host, port, timeout_s)
    finally:
        conn.close()

@server.command("stop")
def server_stop() -> None:
    """Stop the running server instance (idempotent)."""
    conn = open_db_only()
    try:
        stopped = stop_instance(conn)
    finally:
        conn.close()
    if stopped is None:
        click.echo("no running server instance")
        return
    if stopped["state"] != "stopped":
        # identity guard refused the kill — never claim success (Codex fold)
        _fail(f"stop refused: {stopped['detail']}")
    click.echo(
        f"server stopped (model {stopped['model_name']}, "
        f"was http://{stopped['host']}:{stopped['port']})"
    )
    if stopped["detail"]:
        click.echo(f"note: {stopped['detail']}")

@server.command("restart")
@click.option("--model", "model_name", default=None, metavar="NAME")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True)
def server_restart(model_name: str | None, timeout_s: float) -> None:
    """Stop then start the server (applies a new --model or config)."""
    conn, cfg = open_config_and_db()
    try:
        # precheck BEFORE stopping (Codex DX fold): a bad request must not
        # cost the user a running server; --model stays temporary here —
        # `ipo restart` is the persisting shorthand.  The precheck runs
        # unconditionally: with no --model the start below still resolves the
        # persisted selection, so a deleted active-model file must refuse
        # while the old server is up, never after the stop (insert-only
        # catalog: only the file check can catch the deletion)
        engine_path, problem = resolve_engine(cfg.engines.llama_cpp_path)
        if engine_path is None:
            _fail(problem)
        _resolve_model(conn, cfg, model_name)  # resolve-only precheck
        stopped = stop_instance(conn)
        if stopped is not None and stopped["state"] != "stopped":
            # identity guard refused the kill (Codex fold): report the
            # refusal — the detail carries the manual-PID guidance — instead
            # of walking into _run_start's circular "already running" hint
            _fail(f"stop refused: {stopped['detail']}")
        _run_start(conn, cfg, model_name, None, None, timeout_s)
    finally:
        conn.close()

@server.command("list")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
@click.option("--limit", type=int, default=20, show_default=True)
def server_list(as_json: bool, limit: int) -> None:
    """List recent server instances with their states."""
    conn = open_db_only()
    try:
        rows = recent_instances(conn, limit)
    finally:
        conn.close()
    if as_json:
        click.echo(json.dumps({"count": len(rows), "instances": rows},
                              ensure_ascii=False, indent=2))
        return
    if not rows:
        click.echo("no server instances yet (start one with `ipo server start`)")
        return
    click.echo("ID  STATE      MODEL             ADDRESS               PID")
    for row in rows:
        address = f"{row['host']}:{row['port']}"
        pid = row["pid"] if row["pid"] is not None else "-"
        click.echo(
            f"{row['id']:<3} {row['state']:<10} {row['model_name']:<17} "
            f"{address:<21} {pid}"
        )

@server.command("info")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def server_info(as_json: bool) -> None:
    """Show the current instance, live health and last completion."""
    conn = open_db_only()
    try:
        instance = active_instance(conn)
        completion = last_completion(conn)
        health = None
        if instance is not None:
            health = probe_health(instance["host"], instance["port"], 2.0)
    finally:
        conn.close()
    if as_json:
        click.echo(
            json.dumps(
                {"instance": instance, "health": health,
                 "last_completion": completion},
                ensure_ascii=False, indent=2,
            )
        )
        return
    if instance is None:
        click.echo("server: stopped (start with `ipo server start`)")
        if completion is not None:
            _print_completion(completion)
        return
    click.echo(
        f"server: {instance['state']} at http://{instance['host']}:"
        f"{instance['port']} (model {instance['model_name']}, "
        f"pid {instance['pid']})"
    )
    click.echo(f"health: {health}")
    if instance["state"] == "running" and health != "ok":
        click.echo(
            "not responding — the engine may have exited; see `ipo server logs` "
            "or stop it with `ipo server stop`"
        )
    if instance["detail"]:
        click.echo(f"detail: {instance['detail']}")
    if completion is not None:
        _print_completion(completion)

def _print_completion(completion: dict) -> None:
    # created_at is stored UTC (ENG F9); humans read local time — the
    # presentation layer converts (store UTC, localize on display)
    created = local_time(completion["created_at"])
    click.echo(
        f"last completion: {completion['status']} "
        f"({completion['output_chars']} chars in {completion['duration_ms']} ms, "
        f"{created})"
    )
    # the stored exchange is the recall value of the record (CEO review):
    # what was asked and what the model answered, truncated for the terminal
    prompt = completion.get("prompt_text") or ""
    output = completion.get("output_text") or ""
    if prompt:
        click.echo(f"  prompt: {prompt[:120]}{'…' if len(prompt) > 120 else ''}")
    if output:
        click.echo(f"  answer: {output[:200]}{'…' if len(output) > 200 else ''}")

@server.command("logs")
@click.option("--lines", type=int, default=50, show_default=True,
              help="tail length")
def server_logs(lines: int) -> None:
    """Show the tail of the engine log file."""
    path = engine_log_path(resolve_data_dir())
    if not path.exists():
        click.echo("no engine log yet (start the server first)")
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    tail = content.splitlines()[-lines:] if lines > 0 else content.splitlines()
    for line in tail:
        # engine output is third-party text: the redaction layer applies on
        # display just as it does on failure-detail tails (ENG F5)
        click.echo(redact_text(line))


@click.command("start")
@click.option("--server", "as_server", is_flag=True, default=True,
              help="start the inference server (the default action; the flag "
                   "exists for spec §9.11 option parity and is accepted but "
                   "always on)")
@click.option("--model", "model_name", default=None, metavar="NAME",
              help="activate this model, then start the server")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True)
@click.option("--cloud", "cloud", is_flag=True, default=False,
              help="reserved: cloud providers arrive with the gateway plan")
@click.option("--app-path", "app_path", default=None,
              help="reserved: the desktop shell arrives with the P20 plan")
def start(as_server: bool, model_name: str | None, timeout_s: float,
          cloud: bool, app_path: str | None) -> None:
    """Start the app's default services (spec §9.11)."""
    if cloud or app_path:
        reserved = " --cloud" if cloud else ""
        reserved += " --app-path" if app_path else ""
        _fail(
            f"{reserved.strip()} is reserved for a later milestone (gateway "
            f"plan / desktop shell plan) and is not available in this build; "
            f"see `ipo guide`"
        )
    conn, cfg = open_config_and_db()
    try:
        if model_name is not None:
            # ENG F7: an explicit selection is honored even when the gates
            # below skip the start — the user asked for the activation
            files, _skipped, _truncated = scan_model_files(
                model_scan_roots(cfg.general.model_dirs, resolve_data_dir())
            )
            upsert_models(conn, files)
            try:
                activate_model(conn, model_name, cfg)
            except (LookupError, ValueError, ConfigError) as exc:
                _fail(str(exc))
        running = active_instance(conn)
        if running is not None:
            click.echo(
                f"server already running at http://{running['host']}:"
                f"{running['port']} (model {running['model_name']}); "
                f"`ipo server restart` applies the new selection"
            )
            return
        if not cfg.general.auto_start_server:
            click.echo(
                "auto_start_server is off; nothing to start "
                "(enable with `ipo config set auto_start_server true`)"
            )
            return
        _run_start(conn, cfg, None, None, None, timeout_s)
    finally:
        conn.close()

@click.command("status")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def status(as_json: bool) -> None:
    """Show the default service status (exit 0 even when stopped)."""
    conn = open_db_only()
    try:
        instance = active_instance(conn)
        health = None
        if instance is not None:
            health = probe_health(instance["host"], instance["port"], 2.0)
    finally:
        conn.close()
    state = instance["state"] if instance is not None else "stopped"
    if as_json:
        click.echo(
            json.dumps(
                {"state": state, "instance": instance, "health": health},
                ensure_ascii=False, indent=2,
            )
        )
        return
    if instance is None:
        click.echo("server: stopped (start with `ipo start` or `ipo server start`)")
        return
    click.echo(
        f"server: {state} at http://{instance['host']}:{instance['port']} "
        f"(model {instance['model_name']}); health: {health}"
    )
    if instance["state"] == "running" and health != "ok":
        click.echo(
            "not responding — the engine may have exited; see `ipo server logs` "
            "or stop it with `ipo server stop`"
        )

@click.command("stop")
def stop() -> None:
    """Stop the default service (idempotent)."""
    conn = open_db_only()
    try:
        stopped = stop_instance(conn)
    finally:
        conn.close()
    if stopped is None:
        click.echo("no running server instance")
        return
    if stopped["state"] != "stopped":
        _fail(f"stop refused: {stopped['detail']}")
    click.echo(f"server stopped (model {stopped['model_name']})")
    if stopped["detail"]:
        click.echo(f"note: {stopped['detail']}")

@click.command("restart")
@click.option("--model", "model_name", default=None, metavar="NAME")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True)
def restart(model_name: str | None, timeout_s: float) -> None:
    """Restart the default service (applies config and model changes)."""
    conn, cfg = open_config_and_db()
    try:
        # precheck BEFORE stopping: a typo'd model or missing engine must
        # never cost the user a running server (Codex DX fold); the
        # selection persists, matching `ipo start --model` semantics
        engine_path, problem = resolve_engine(cfg.engines.llama_cpp_path)
        if engine_path is None:
            _fail(problem)
        # resolve-only model precheck through the same disk-aware path
        # `ipo server restart` uses: with the insert-only catalog a moved or
        # deleted model file must fail here — before a healthy server is
        # stopped — never as a start failure after the stop.  The selection
        # is not persisted until the precheck below has passed.
        _resolve_model(conn, cfg, model_name)
        if model_name is not None:
            try:
                activate_model(conn, model_name, cfg)
            except (LookupError, ValueError, ConfigError) as exc:
                _fail(str(exc))
            model_name = None  # selection persisted; start resolves it
        stopped = stop_instance(conn)
        if stopped is not None and stopped["state"] != "stopped":
            # identity guard refused the kill: report the refusal (the detail
            # carries the manual-PID guidance) instead of walking into
            # _run_start's circular "already running" hint — same handling as
            # `server restart` above
            _fail(f"stop refused: {stopped['detail']}")
        _run_start(conn, cfg, model_name, None, None, timeout_s)
    finally:
        conn.close()
