# src/ipostudio/cli/ui.py
"""Terminal presentation helpers shared by every human-facing ipo command.

Contract (inherited by all future commands): machine-readable streams
(`--json`) are never styled — helpers apply to human lines only, and every
helper collapses to plain text when stdout is redirected, NO_COLOR is set
(no-color.org: any non-empty value), or TERM=dumb.  ANSI capability on each
platform is click's job, so no platform branching lives here (R1).
"""

import os
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TextIO

import click

_MARK_COLORS: dict[str, str] = {"[PASS]": "green", "[FAIL]": "red", "[WARN]": "yellow"}

_UTC_NAIVE_FORMAT = "%Y-%m-%d %H:%M:%S"  # SQLite datetime('now') shape (ENG F9)


def use_color(env: Mapping[str, str] | None = None, stream: TextIO | None = None) -> bool:
    """ANSI color only for an interactive stream that did not opt out."""
    env_vars = os.environ if env is None else env
    # FORCE_COLOR is checked FIRST and wins over NO_COLOR (chalk/supports-color
    # convention; "0"/"false" disable, any other non-empty value forces on —
    # ENG F4 + Codex ENG #3: value semantics symmetric with NO_COLOR)
    force = env_vars.get("FORCE_COLOR", "").strip().lower()
    if force:
        return force not in {"0", "false"}
    if env_vars.get("NO_COLOR", ""):
        return False
    if env_vars.get("TERM", "") == "dumb":
        return False
    target = sys.stdout if stream is None else stream
    # pythonw.exe leaves sys.stdout as None; presenters degrade silently.
    return target is not None and bool(target.isatty())


def paint(text: str, fg: str | None, *, color: bool) -> str:
    if not color or fg is None:
        return text
    return click.style(text, fg=fg)


def check_line(mark: str, name: str, detail: str, *, color: bool = False) -> str:
    """One doctor-style line: colored mark, check name, detail."""
    return f"{paint(mark, _MARK_COLORS.get(mark), color=color)} {name}: {detail}"


def local_time(stored: str) -> str:
    """Render a stored UTC timestamp in the user's local time.

    Storage is deliberately UTC (SQLite ``datetime('now')``, ENG F9); humans
    read local — best practice is to convert at the presentation layer, so
    every human-facing timestamp goes through this helper while ``--json``
    keeps the raw stored strings (machine-readable contract unchanged).
    Malformed values render unchanged so diagnostics are never lost.
    """
    try:
        moment = datetime.strptime(stored, _UTC_NAIVE_FORMAT).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return stored
    return moment.astimezone().strftime(_UTC_NAIVE_FORMAT)
