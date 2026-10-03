"""`ipo` command line entrypoint (spec §9.11 skeleton + §9.12 doctor)."""

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import click

from ipostudio import __version__
from ipostudio.conf.loader import ConfigError, load_config
from ipostudio.conf.paths import ensure_layout, resolve_data_dir, resolve_db_path
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
        if not stream.isatty() and hasattr(stream, "reconfigure"):
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
            version = _count_migrations(conn)
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
    return CheckOutcome("database", True, f"schema at migration count {version}")


def _count_migrations(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]


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


def _contained(check, repair: bool) -> CheckOutcome:
    """Every check failure still returns a structured outcome, so `--json`
    never dies mid-report (eng review)."""
    try:
        return check(repair)
    except Exception as exc:  # noqa: BLE001 - diagnostic command must not crash
        return CheckOutcome("unexpected", False, f"{check.__name__}: {exc!r}; "
                          f"this is a bug in ipo doctor; report it with --json output")


def run_doctor(repair: bool = False) -> tuple[list[CheckOutcome], list[str]]:
    config_outcome, warnings = _check_config()
    outcomes = [
        config_outcome,
        _contained(_check_data_dir, repair),
        _contained(_check_database, repair),
        _contained(_check_logs, repair),
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
        for outcome in outcomes:
            mark = "[PASS]" if outcome.ok else "[FAIL]"
            # long multi-error details are truncated for the terminal with a
            # visible count; `--json` always carries the full text
            shown = outcome.detail
            if len(shown) > 300:
                shown = shown[:300] + f" ...(+{len(outcome.detail) - 300} chars; use --json)"
            click.echo(f"{mark} {outcome.name}: {shown}")
        for warning in warnings:
            click.echo(f"[WARN] config: {warning}")
    if failed:
        sys.exit(1)
