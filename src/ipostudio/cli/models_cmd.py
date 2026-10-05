"""`ipo models` / `ipo model` / `ipo model-info` (spec §9.11 local slice).

`model --select` and `model-info` refresh the scan before resolving, so a
model dropped into a directory is selectable without running `ipo models`
first (ruling #12)."""

import json
import os
import sqlite3
from pathlib import Path

import click

from ipostudio.catalog.repo import find_model, list_models, upsert_models
from ipostudio.catalog.scan import MAX_SCAN_ENTRIES, model_scan_roots, scan_model_files
from ipostudio.cli.base import _fail, open_config_and_db
from ipostudio.conf.loader import ConfigError, ConfigStore
from ipostudio.conf.paths import resolve_config_path, resolve_data_dir


def _refresh(conn: sqlite3.Connection, cfg) -> tuple[list[dict], int, bool, list]:
    roots = model_scan_roots(cfg.general.model_dirs, resolve_data_dir())
    files, skipped, truncated = scan_model_files(roots)
    upsert_models(conn, files)
    return list_models(conn), skipped, truncated, roots


def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


@click.command("models")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def models(as_json: bool) -> None:
    """List local models found in the configured model directories."""
    conn, cfg = open_config_and_db()
    try:
        rows, skipped, truncated, roots = _refresh(conn, cfg)
    finally:
        conn.close()
    active = cfg.general.local_chat_model
    for row in rows:
        row["active"] = row["name"] == active
        # insert-only catalog until P2 pruning: surface ghost rows instead of
        # hiding them (Codex stale-row fold; TODO-021 owns removal)
        row["missing"] = not Path(row["path"]).exists()
    if as_json:
        click.echo(
            json.dumps(
                {
                    "count": len(rows),
                    "skipped": skipped,
                    "truncated": truncated,
                    "roots": [str(root) for root in roots],
                    "models": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not rows:
        click.echo("no models found.")
        click.echo(f"searched: {', '.join(str(root) for root in roots)}")
        click.echo(
            "place a .gguf model file in one of these directories (or register "
            "another directory with `ipo config set model_dirs -- '[\"D:/models\"]'`)"
        )
        return
    width = max(len(row["name"]) for row in rows) + 1
    click.echo(f"{'NAME':<{width}}  SIZE  PARTS  FORMAT  PATH")
    for row in rows:
        mark = "*" if row["active"] else " "
        path_text = row["path"] + ("  (missing)" if row["missing"] else "")
        click.echo(
            f"{mark + row['name']:<{width}}  {_human_size(row['size_bytes']):>8}  "
            f"{row['parts']:>5}  {row['format']:<6}  {path_text}"
        )
    if truncated:
        click.echo(
            f"listing truncated at {MAX_SCAN_ENTRIES} entries; register a narrower "
            f"model_dirs entry to see the rest"
        )
    if skipped:
        click.echo(f"skipped {skipped} incomplete or unreadable candidate(s)")


def activate_model(conn: sqlite3.Connection, ident: str, cfg) -> str:
    """Resolve `ident` against the catalog and persist it as the active chat
    model.  Raises LookupError (nothing matches) or ValueError (ambiguous)
    with user-safe messages; returns the activated name."""
    matches = find_model(conn, ident)
    if not matches:
        raise LookupError(
            f"no local model matches {ident!r}; run `ipo models` for the catalog"
        )
    if len(matches) > 1:
        paths = ", ".join(sorted({match["path"] for match in matches})[:5])
        raise ValueError(
            f"ambiguous match for {ident!r}: {paths}; use a full name or path"
        )
    name = matches[0]["name"]
    # ENG F2: selection by unique path must not round-trip into an ambiguous
    # name — if the bare name still matches several rows, `server start`
    # would brick.  Path-addressable activation lands with P2 pruning.
    if len(find_model(conn, name)) > 1:
        # the ident itself was unique — the NAME is not; say so precisely so
        # the user is not sent in a circle (Codex DX dead-loop fold)
        raise ValueError(
            f"several catalog rows share the name {name!r} (same file name in "
            f"different directories); until catalog pruning lands (P2), "
            f"activate by a name unique in the catalog — or remove the "
            f"duplicate file and re-run `ipo models`"
        )
    store = ConfigStore(resolve_config_path(), cfg)
    store.set("local_chat_model", name)
    store.save()
    return name


@click.command("model")
@click.option("--select", "select_name", default=None, metavar="NAME",
              help="activate a local model as the default chat model")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def model(select_name: str | None, as_json: bool) -> None:
    """Show or set the active chat model."""
    if select_name is None:
        conn, cfg = open_config_and_db()
        conn.close()
        active = cfg.general.local_chat_model
        if as_json:
            click.echo(json.dumps({"active": active}, ensure_ascii=False))
        else:
            shown = active if active else "(not set)"
            click.echo(f"active chat model: {shown}")
            if not active:
                click.echo("set one with `ipo model --select NAME` (see `ipo models`)")
        return
    conn, cfg = open_config_and_db()
    try:
        _refresh(conn, cfg)
        name = activate_model(conn, select_name, cfg)
    except (LookupError, ValueError, ConfigError) as exc:
        _fail(str(exc))  # Codex boundary fold: lock/permission failures are
        # ConfigError, not LookupError — without this arm they traceback
    finally:
        conn.close()
    if as_json:  # Codex JSON-contract fold: selection is machine-readable too
        click.echo(json.dumps(
            {"selected": name, "saved": True,
             "apply_with": "ipo server restart"},
            ensure_ascii=False,
        ))
        return
    click.echo(f"active chat model: {name} (saved)")
    override = os.environ.get("IPO_LOCAL_CHAT_MODEL", "").strip()
    if override and override != name:
        click.echo(
            f"warning: IPO_LOCAL_CHAT_MODEL={override!r} is set in this shell; "
            f"it overrides the saved value for new commands",
            err=True,
        )
    click.echo("if a server is running, apply the change with `ipo server restart`")


@click.command("model-info")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def model_info(name: str, as_json: bool) -> None:
    """Show details for one local model (NAME from `ipo models`)."""
    conn, cfg = open_config_and_db()
    try:
        _refresh(conn, cfg)
        matches = find_model(conn, name)
    finally:
        conn.close()
    if not matches:
        _fail(f"no local model matches {name!r}; run `ipo models`")
    if len(matches) > 1:
        _fail(f"ambiguous match for {name!r}; use a full name or path")
    row = matches[0]
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    click.echo(f"name:     {row['name']}")
    click.echo(f"path:     {row['path']}")
    click.echo(f"size:     {_human_size(row['size_bytes'])} ({row['size_bytes']} bytes)")
    click.echo(f"format:   {row['format']} ({row['parts']} part(s))")
    click.echo(f"category: {row['category']}")
    click.echo(f"source:   {row['source']}")
    click.echo(f"seen:     {row['first_seen']}")
