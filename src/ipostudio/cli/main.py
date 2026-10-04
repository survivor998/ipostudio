"""`ipo` command line entrypoint (spec §9.11 skeleton + §9.12 doctor)."""

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from ipostudio import __version__
from ipostudio.cli.ui import check_line, use_color
from ipostudio.conf.loader import (
    CREDENTIAL_KEYS,
    ConfigError,
    ConfigStore,
    _contains_url_credential,
    coerce_value,
    load_config,
    suggest_key,
)
from ipostudio.conf.paths import (
    ensure_layout,
    resolve_config_path,
    resolve_data_dir,
    resolve_db_path,
)
from ipostudio.conf.schema import FLAT_KEYS
from ipostudio.logs import log_file_path
from ipostudio.store.database import migrate, open_db

GUIDE_BRIEF = {
    "zh": "ipostudio 命令行工具：本地模型、推理服务与应用的统一入口（当前为基础版本）。",
    "en": "ipostudio CLI: unified entry for local models, inference services and apps (foundation release).",
}


@dataclass
class CheckOutcome:
    name: str
    ok: bool
    detail: str


def _force_utf8_streams() -> None:
    """Non-tty streams default to the locale codec (cp936 etc. on Windows),
    which can crash or mojibake CJK output; pin redirected output to UTF-8
    (requirement R1). Interactive consoles already use UTF-8 via the OS API."""
    for stream in (sys.stdout, sys.stderr):
        # pythonw.exe leaves the streams as None; skip them (AttributeError
        # here would kill every command before its own error handling).
        if stream is not None and not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def collect_command_docs() -> list[dict]:
    docs = []
    for name, command in sorted(cli.commands.items()):
        docs.append(
            {
                "name": name,
                "help": command.help or "",
                "options": [
                    {"flag": option.opts[0] if option.opts else "", "help": option.help or ""}
                    for option in command.params
                ],
            }
        )
    return docs


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Docs: docs/ in the repository, or run `ipo guide`.",
)
@click.version_option(__version__, prog_name="ipo")
@click.option("--config", "config_path", type=click.Path(), default=None,
              help="path to settings.toml (overrides IPO_CONFIG)")
@click.option("--data-dir", "data_dir", type=click.Path(), default=None,
              help="data directory (overrides IPO_DATA_DIR)")
def cli(config_path: str | None, data_dir: str | None) -> None:
    """ipostudio command line interface."""
    _force_utf8_streams()
    # CLI flags translate to the bootstrap env vars before any config load;
    # the env vars remain the underlying mechanism (escape-hatch parity).
    if config_path:
        os.environ["IPO_CONFIG"] = config_path
    if data_dir:
        os.environ["IPO_DATA_DIR"] = data_dir


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def version(as_json: bool) -> None:
    """Show the ipostudio version."""
    if as_json:
        click.echo(json.dumps({"name": "ipostudio", "version": __version__}))
    else:
        click.echo(f"ipostudio {__version__}")


def _render_docs(docs: list[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(docs, ensure_ascii=False, indent=2)
    if fmt == "markdown":
        lines = ["# ipo command reference", ""]
        for doc in docs:
            lines += [f"## {doc['name']}", "", doc["help"] or "(no description)", ""]
            for option in doc["options"]:
                lines.append(f"- `{option['flag']}`: {option['help']}")
            lines.append("")
        return "\n".join(lines)
    lines = []
    for doc in docs:
        flags = " ".join(f"[{o['flag']}]" for o in doc["options"])
        lines.append(f"ipo {doc['name']} {flags}".rstrip())
        if doc["help"]:
            lines.append(f"    {doc['help']}")
    return "\n".join(lines)


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["text", "markdown", "json"]), default="text")
@click.option("--json", "as_json", is_flag=True, help="shorthand for --format json")
def help(fmt: str, as_json: bool) -> None:
    """List available ipo commands."""
    if as_json:
        fmt = "json"
    click.echo(_render_docs(collect_command_docs(), fmt))


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["text", "markdown", "json"]), default="text")
@click.option("--json", "as_json", is_flag=True, help="shorthand for --format json")
@click.option("--lang", type=click.Choice(["zh", "en"]), default=None,
              help="manual language (default: ui_lang config)")
def guide(fmt: str, as_json: bool, lang: str | None) -> None:
    """Show the full ipo manual."""
    if as_json:
        fmt = "json"
    if lang is None:
        try:
            lang = load_config().ui.ui_lang
        except ConfigError:
            lang = "zh"  # broken config must not break the manual
    if fmt == "json":
        click.echo(json.dumps(collect_command_docs(), ensure_ascii=False, indent=2))
        return
    click.echo(GUIDE_BRIEF[lang])
    click.echo(_render_docs(collect_command_docs(), fmt))


def _check_config() -> tuple[CheckOutcome, list[str]]:
    warnings: list[str] = []
    try:
        load_config(warnings=warnings)
        outcome = CheckOutcome("config", True, "settings parsed with strict key validation")
    except ConfigError as exc:
        outcome = CheckOutcome("config", False, "; ".join(exc.details))
    return outcome, warnings


def _unique_probe(directory: Path) -> bool:
    """Write-verify with an exclusively-created unique temp file.

    Never touches or deletes pre-existing files (eng review: a fixed probe name
    would overwrite then delete a user file of the same name)."""
    import tempfile

    try:
        fd, name = tempfile.mkstemp(prefix=".doctor-probe-", dir=directory)
        os.close(fd)
        os.unlink(name)
        return True
    except OSError:
        return False


def _check_data_dir(repair: bool) -> CheckOutcome:
    data_dir = resolve_data_dir()
    if repair:
        ensure_layout(data_dir)  # idempotent; also repairs partial layouts
    if not data_dir.exists():
        return CheckOutcome(
            "data-dir", True,
            f"not created yet ({data_dir}); run with --fix or start the app",
        )
    if not _unique_probe(data_dir):
        return CheckOutcome(
            "data-dir", False,
            f"data directory not writable ({data_dir}); check permissions "
            f"(synced/roaming profiles and antivirus locks are common causes)",
        )
    return CheckOutcome("data-dir", True, str(data_dir))


def _check_database(repair: bool) -> CheckOutcome:
    db_path = resolve_db_path()
    if repair:
        try:
            conn = open_db(db_path)
            try:
                migrate(conn)  # repairs BOTH fresh and outdated databases
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return CheckOutcome(
                "database", False,
                f"migration failed: {exc} (database {db_path}); the failed "
                f"migration was rolled back; fix the reported cause and re-run",
            )
        return CheckOutcome("database", True, f"schema up to date at {db_path}")
    if not db_path.exists():
        return CheckOutcome(
            "database", True,
            f"not initialized yet ({db_path}); run with --fix or start the app",
        )
    if db_path.is_dir():
        # A directory cannot be a database, but how sqlite fails on one is
        # platform-dependent (Windows: CANTOPEN; POSIX: open(dir, O_RDONLY)
        # succeeds and the header read yields an IOERR-class error that the
        # code-based classification below would report as a hard failure).
        # Route it to the same guided PASS on every platform (first CI run).
        return CheckOutcome(
            "database", True,
            f"cannot inspect read-only ({db_path} is a directory, not a "
            f"database file); check IPO_DB_PATH or run `ipo doctor --fix` "
            f"for a writable check",
        )
    try:
        # read-only inspection: default doctor must not touch an existing
        # database (no WAL pragma, no migration). --fix repairs explicitly.
        from urllib.parse import quote

        quoted = quote(str(db_path))
        if db_path.with_name(db_path.name + "-wal").exists():
            # A sidecar means a writer may be live: read through the WAL with
            # plain mode=ro. The side files belong to that database, never to
            # this check (deleting a -wal could destroy uncheckpointed commits).
            uri = f"file:{quoted}?mode=ro"
        else:
            # No sidecar => no WAL frames exist, so immutable=1 is exact and
            # creates ZERO side files: every database open_db() makes is
            # persistently WAL, and a plain ro connection still creates
            # -wal/-shm for the wal-index, then cannot remove them on close
            # (read-only connections never checkpoint).  A sidecar appearing
            # between the exists() check and connect is at worst a stale best-
            # effort read: immutable readers never write anything.
            uri = f"file:{quoted}?mode=ro&immutable=1"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            version, registry, tables = _inspect_schema(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # Classify by result code, never message text: CANTOPEN's Python
        # message is "unable to open database file", which contains neither
        # 'readonly' nor 'cantopen'.  & 0xFF folds extended codes
        # (SQLITE_CANTOPEN_ISDIR, SQLITE_READONLY_DIRECTORY, ...) onto their
        # primary code.  These are exactly the "cannot open here" cases the
        # plan degrades to a guided PASS; anything else is a real failure.
        primary = getattr(exc, "sqlite_errorcode", 0) & 0xFF
        if primary in (sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_READONLY):
            return CheckOutcome(
                "database", True,
                f"cannot inspect read-only ({exc}) at {db_path}; likely a "
                f"synced/locked directory; run `ipo doctor --fix` for a "
                f"writable check",
            )
        return CheckOutcome(
            "database", False,
            f"sqlite failure reading {db_path}: {exc}; run `ipo doctor --fix` "
            f"or check the file is not locked by another ipostudio process",
        )
    if not registry:
        if tables == 0:
            # Same guidance as a missing database: the file exists but no
            # schema was ever applied, which doctor --fix (or starting the
            # app) repairs.
            return CheckOutcome(
                "database", True,
                f"not initialized yet ({db_path}); run with --fix or start the app",
            )
        return CheckOutcome(
            "database", False,
            f"database has tables but no migration registry ({db_path}); it "
            f"may be corrupted or not an ipostudio database; inspect it "
            f"manually before running `ipo doctor --fix`",
        )
    if version == 0:
        # Registry exists but nothing was ever applied (crash between
        # registry creation and the first migration): --fix repairs.
        return CheckOutcome(
            "database", True,
            f"not initialized yet ({db_path}); run with --fix or start the app",
        )
    return CheckOutcome(
        "database", True, f"schema at migration count {version} ({db_path})"
    )


def _inspect_schema(conn: sqlite3.Connection) -> tuple[int, bool, int]:
    """Return (migration count, registry present, user table count).

    An existing-but-empty database (0-byte file: what a crashed cold open
    leaves behind) is valid sqlite with no tables; consult sqlite_master
    instead of crashing on 'no such table: _migrations' (H-04).  The table
    count separates "truly empty" from "has tables but no registry", which is
    a corrupted or foreign database and must not get the guided PASS
    (cross-model review finding)."""
    tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0]
    registry = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type = 'table' AND name = '_migrations'"
    ).fetchone()[0]
    if not registry:
        return 0, False, tables
    version = conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
    return version, True, tables


def _check_logs(repair: bool) -> CheckOutcome:
    path = log_file_path(resolve_data_dir())
    if repair:
        path.parent.mkdir(parents=True, exist_ok=True)
    if not path.parent.exists():
        return CheckOutcome(
            "logs", True,
            f"log directory not created yet ({path.parent}); run with --fix or start the app",
        )
    if not _unique_probe(path.parent):
        return CheckOutcome(
            "logs", False,
            f"log directory not writable ({path.parent}); check permissions, then re-run",
        )
    return CheckOutcome("logs", True, str(path))


def _contained(name: str, check, repair: bool) -> CheckOutcome:
    """Every check failure still returns a structured outcome, so `--json`
    never dies mid-report (eng review)."""
    try:
        return check(repair)
    except Exception as exc:  # noqa: BLE001 - diagnostic command must not crash
        # Keep the canonical check name (the JSON contract is exactly these
        # four) and attribute honestly: an unexpected crash during a check is
        # usually environmental (permissions, path shape), not a doctor bug.
        return CheckOutcome(
            name, False,
            f"unexpected error during the {name} check: {exc!r}; this is "
            f"often environmental rather than a bug in ipo doctor; re-run "
            f"and report with --json output if it persists",
        )


def run_doctor(repair: bool = False) -> tuple[list[CheckOutcome], list[str]]:
    warnings: list[str] = []

    def _config_outcome(_repair: bool) -> CheckOutcome:
        nonlocal warnings
        outcome, warnings = _check_config()
        return outcome

    outcomes = [
        # the config check is contained like every other check: a non-
        # ConfigError crash from load_config must not kill doctor mid-report
        _contained("config", _config_outcome, repair),
        _contained("data-dir", _check_data_dir, repair),
        _contained("database", _check_database, repair),
        _contained("logs", _check_logs, repair),
    ]
    return outcomes, warnings


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
@click.option("--fix", "repair", is_flag=True, help="repair: create layout and apply migrations")
def doctor(as_json: bool, repair: bool) -> None:
    """Verify config, data dir, database and logs (read-only; --fix repairs)."""
    outcomes, warnings = run_doctor(repair)
    failed = [o for o in outcomes if not o.ok]
    if as_json:
        click.echo(
            json.dumps(
                {
                    "ok": not failed,
                    "checks": [
                        {"name": o.name, "ok": o.ok, "detail": o.detail} for o in outcomes
                    ],
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        color = use_color()
        for outcome in outcomes:
            mark = "[PASS]" if outcome.ok else "[FAIL]"
            # long multi-error details are truncated for the terminal with a
            # visible count; `--json` always carries the full text
            shown = outcome.detail
            if len(shown) > 300:
                shown = shown[:300] + f" ...(+{len(outcome.detail) - 300} chars; use --json)"
            # color passthrough: without it click.echo strips the ANSI that
            # paint() added whenever the stream is not a tty, which would
            # silently neutralize FORCE_COLOR end-to-end (Codex ENG #3)
            click.echo(check_line(mark, outcome.name, shown, color=color), color=color)
        for warning in warnings:
            click.echo(check_line("[WARN]", "config", warning, color=color), color=color)
        passed = len(outcomes) - len(failed)
        if failed:
            names = ", ".join(outcome.name for outcome in failed)
            click.echo(
                f"summary: {passed} passed, {len(failed)} failed ({names}); follow the "
                f"guidance in the failed checks above, or re-run with --fix to repair "
                f"storage problems (--json gives full detail)"
            )
        elif repair:
            click.echo(
                f"summary: {passed} passed (repair mode); storage is ready — "
                f"try `ipo guide` next"
            )
        else:
            click.echo(f"summary: {passed} passed.")
    if failed:
        sys.exit(1)


@cli.group()
def config() -> None:
    """Read and write settings (subcommands: path, get, set, list)."""


def _format_value(value: Any) -> str:
    """Human text form: None and "" as "(not set)", strings raw, rest JSON.
    "" must not render as a blank line (DX F1) — the text channel matches
    `config list`; `--json` stays raw because "" is the machine truth."""
    if value is None or value == "":
        return "(not set)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _print_config_errors(exc: ConfigError) -> None:
    for detail in exc.details:
        click.echo(f"error: {detail}", err=True)


def _mask_url_credentials(value: Any) -> Any:
    """Mask any value carrying an inline URL credential before it reaches a
    display channel (Codex ENG #1): load_config accepts env/file values the
    write path would reject, so get/list need a READ-side guard mirroring the
    store's value-based policy — name blacklists alone cannot uphold it."""
    if _contains_url_credential(value):
        return "***"
    return value


@config.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def path(as_json: bool) -> None:
    """Show the settings file location."""
    target = resolve_config_path()
    # IPO_CONFIG may legally be relative (cwd-anchored); the display contract
    # is an absolute path, so absolutize for display only (Codex ENG #6).
    # .absolute() is cwd-anchored absolutization with NO symlink resolution —
    # resolving would rewrite the displayed path on symlinked temp dirs
    # (macOS /var -> /private/var) and break path-pinning tests; the
    # platform-hygiene guard keeps legacy path helpers out of src/, hence
    # the pathlib form.
    absolute = target.absolute()
    if as_json:
        click.echo(json.dumps({"path": str(absolute)}, ensure_ascii=False))
    else:
        click.echo(str(absolute))


@config.command()
@click.argument("key")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def get(key: str, as_json: bool) -> None:
    """Show one setting's effective value (env > file > default)."""
    if key in CREDENTIAL_KEYS:
        click.echo(
            f"error: {key} is credential-shaped and never displayed; read it "
            f"from the environment (IPO_{key.upper()}) instead",
            err=True,
        )
        sys.exit(1)
    try:
        cfg = load_config()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    family = FLAT_KEYS.get(key)
    if family is None:
        click.echo(
            f"error: unknown config key: {key}{suggest_key(key)}; see `ipo config list`",
            err=True,
        )
        sys.exit(1)
    value = _mask_url_credentials(getattr(getattr(cfg, family), key))
    if as_json:
        click.echo(
            json.dumps({"key": key, "family": family, "value": value}, ensure_ascii=False)
        )
    else:
        click.echo(_format_value(value))


@config.command(name="set")
@click.argument("key")
@click.argument("value")
def set_value(key: str, value: str) -> None:
    """Validate and persist one setting; VALUE 'none' clears an optional key."""
    try:
        typed = coerce_value(key, value)
        cfg = load_config()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    store = ConfigStore(resolve_config_path(), cfg)
    try:
        # set() 先做策略校验，再在候选副本上验证，并把归一化后的值写回 cfg
        # 的对应 family section（loader.py 的 setattr）——因此下方成功行展示
        # 的就是已保存的归一化值，无需重读文件
        store.set(key, typed)
        saved = store.save()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    env_var = f"IPO_{key.upper()}"
    if env_var in os.environ:
        # stderr: a warning must not pollute the machine-facing stdout (DX F7)
        click.echo(
            f"warning: {env_var} is set in this shell; it overrides the saved "
            f"value until you unset it",
            err=True,
        )
    current = getattr(getattr(cfg, FLAT_KEYS[key]), key)
    click.echo(f"{key} = {_format_value(current)} (saved to {saved})")
