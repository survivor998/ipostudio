"""CLI-wide plumbing shared by main and the command modules."""

import sqlite3
import sys

import click

from ipostudio.cli.ui import use_color
from ipostudio.conf.loader import ConfigError, load_config, suggest_key
from ipostudio.conf.paths import resolve_db_path
from ipostudio.conf.schema import AppConfig
from ipostudio.store.database import migrate, open_db


class _SuggestingGroup(click.Group):
    """Turn unknown-command errors into actionable ones and keep every
    click-rendered surface under the presentation color gate.  The UsageError
    contract (exit code 2) is preserved — only the message improves."""

    def make_context(self, info_name, args, parent=None, **extra):
        # eager --help exits during parsing, before any callback runs: the
        # color gate must be applied at context construction (DX F6)
        extra.setdefault("color", use_color())
        return super().make_context(info_name, args, parent=parent, **extra)

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            name = args[0] if args else ""
            hint = suggest_key(name, pool=self.commands)
            # ctx=ctx keeps click's usage block on the rewritten error (ENG F6)
            raise click.UsageError(
                f"unknown command {name!r}{hint}; run `ipo --help` to list commands",
                ctx=ctx,
            ) from exc


def open_config_and_db() -> tuple[sqlite3.Connection, AppConfig]:
    """Shared entry for commands that need effective config plus a migrated
    database.  Any failure prints a structured stderr line and exits 1."""
    try:
        cfg = load_config()
        conn = open_db(resolve_db_path())
        migrate(conn)
    except ConfigError as exc:
        for detail in exc.details:
            click.echo(f"error: {detail}", err=True)
        sys.exit(1)
    except sqlite3.Error as exc:
        click.echo(
            f"error: database unavailable ({exc}); run `ipo doctor --fix` and retry",
            err=True,
        )
        sys.exit(1)
    except OSError as exc:
        # ENG F16: an unreadable data dir (permissions) must meet the same
        # error contract, not a traceback
        click.echo(
            f"error: cannot access the data directory ({exc}); check "
            f"permissions, then run `ipo doctor --fix`",
            err=True,
        )
        sys.exit(1)
    return conn, cfg


def open_db_only() -> sqlite3.Connection:
    """Migrated database without loading settings.toml (Codex recovery fold):
    stop/status/list/info must work even when the config file is broken —
    a user must always be able to stop what they started."""
    try:
        conn = open_db(resolve_db_path())
        migrate(conn)
    except sqlite3.Error as exc:
        click.echo(
            f"error: database unavailable ({exc}); run `ipo doctor --fix` and retry",
            err=True,
        )
        sys.exit(1)
    except OSError as exc:
        # ENG F16: an unreadable data dir (permissions) must meet the same
        # error contract, not a traceback — these are exactly the recovery
        # surfaces where a raw crash costs the user the most
        click.echo(
            f"error: cannot access the data directory ({exc}); check "
            f"permissions, then run `ipo doctor --fix`",
            err=True,
        )
        sys.exit(1)
    return conn


def _fail(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    sys.exit(1)
