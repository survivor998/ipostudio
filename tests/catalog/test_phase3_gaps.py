"""Targeted phase-3 gaps for the catalog surface (scan + repo).

Existing suites pin the happy scan/skip/upsert flows; these guards target the
untested branches: `shard_family_complete` (the server-start revalidation has
zero direct tests), the root-is-a-file skip accounting, degenerate shard
totals, hidden candidate FILES, and `find_model`'s wildcard/slash handling.
"""

import os

from ipostudio.catalog.repo import find_model, list_models, upsert_models
from ipostudio.catalog.scan import (
    ModelFile,
    model_scan_roots,
    scan_model_files,
    shard_family_complete,
)
from ipostudio.store.database import migrate, open_db

GGUF_HEAD = b"GGUF" + b"\x00" * 28


def _make_db(tmp_path):
    conn = open_db(tmp_path / "app.db")
    migrate(conn)
    return conn


def _write_gguf(path, size=64):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(GGUF_HEAD + b"\x00" * max(size - len(GGUF_HEAD), 0))


def test_configured_root_that_is_a_file_counts_as_skipped(tmp_path):
    # ENG F8 branch: a configured root that exists but is not a directory is
    # accounted in `skipped` — silence must never be free
    blocker = tmp_path / "models"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    files, skipped, truncated = scan_model_files([blocker])
    assert files == [] and skipped == 1 and truncated is False


def test_shard_family_complete_non_shard_paths(tmp_path):
    plain = tmp_path / "solo.gguf"
    assert shard_family_complete(plain) is False  # missing file
    _write_gguf(plain)
    assert shard_family_complete(plain) is True
    # a single-part shard family (00001-of-00001) counts as its own complete set
    family = tmp_path / "one-00001-of-00001.gguf"
    _write_gguf(family)
    assert shard_family_complete(family) is True


def test_shard_family_complete_prefix_collision_and_missing_parent(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "llama-00001-of-00002.gguf")
    _write_gguf(root / "llama-00002-of-00002.gguf")
    _write_gguf(root / "llama-instruct-00001-of-00002.gguf")
    # the prefix-collision guard must not let the llama-instruct family count
    # toward llama's completeness, nor llama toward llama-instruct's
    assert shard_family_complete(root / "llama-00001-of-00002.gguf") is True
    assert shard_family_complete(root / "llama-instruct-00001-of-00002.gguf") is False
    # an unreadable/absent parent directory is not "complete"
    assert shard_family_complete(tmp_path / "void" / "x-00001-of-00001.gguf") is False


def test_scan_degenerate_zero_total_shard_is_skipped(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "x-00001-of-00000.gguf")
    files, skipped, _truncated = scan_model_files([root])
    assert files == [] and skipped == 1


def test_scan_ignores_hidden_candidate_files(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / ".secret.gguf")
    _write_gguf(root / "visible.gguf")
    names = [f.name for f in scan_model_files([root])[0]]
    assert names == ["visible"]


def test_scan_upsert_find_roundtrip_with_unicode_name(tmp_path):
    # CJK + special characters must survive scan -> sqlite -> resolve
    root = tmp_path / "models"
    _write_gguf(root / "模型-q4.gguf")
    files, skipped, _truncated = scan_model_files([root])
    assert skipped == 0 and files[0].name == "模型-q4"
    conn = _make_db(tmp_path)
    upsert_models(conn, files)
    rows = list_models(conn)
    assert rows[0]["name"] == "模型-q4"
    assert find_model(conn, "模型-q4")[0]["path"] == str(files[0].path)
    conn.close()


def test_find_model_sql_wildcards_stay_literal(tmp_path):
    # `%` and `_` are SQL wildcards: the Python-side suffix matcher must treat
    # user input literally (repo.py comment pins this; no test held it)
    conn = _make_db(tmp_path)
    upsert_models(
        conn,
        [
            ModelFile("al_pha", tmp_path / "al_pha.gguf", 1, "gguf", 1),
            ModelFile("pct%", tmp_path / "pct%.gguf", 1, "gguf", 1),
            ModelFile("beta", tmp_path / "nested" / "beta.gguf", 1, "gguf", 1),
        ],
    )
    assert find_model(conn, "al_pha")[0]["name"] == "al_pha"
    assert find_model(conn, "alpha") == []  # `_` must not act as a wildcard
    assert find_model(conn, "pct%")[0]["name"] == "pct%"
    assert find_model(conn, "p%") == []  # `%` must not act as a wildcard
    # user-supplied separators: a backslash ident normalizes to the stored path
    ident = (tmp_path / "nested" / "beta.gguf")
    assert find_model(conn, ident.as_posix())[0]["name"] == "beta"
    conn.close()


def test_scan_roots_dedupe_is_identity_based_not_string_based(tmp_path):
    # "." vs the absolute tmp path must collapse to one root after resolve()
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        roots = model_scan_roots([".", str(tmp_path)], tmp_path)
        assert roots == [tmp_path.resolve(), (tmp_path / "models").resolve()]
    finally:
        os.chdir(cwd)
