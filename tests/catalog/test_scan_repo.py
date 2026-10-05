from pathlib import Path

from ipostudio.catalog.repo import find_model, list_models, upsert_models
from ipostudio.catalog.scan import (
    MAX_SCAN_ENTRIES,
    ModelFile,
    looks_like_gguf,
    model_scan_roots,
    scan_model_files,
)
from ipostudio.store.database import migrate, open_db

GGUF_HEAD = b"GGUF" + b"\x00" * 28  # magic + version/tensor-count shape

def _make_db(tmp_path):
    conn = open_db(tmp_path / "app.db")
    migrate(conn)
    return conn

def _write_gguf(path, size=64, head=GGUF_HEAD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + b"\x00" * max(size - len(head), 0))

def test_scan_finds_single_gguf_and_skips_other_extensions(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "tiny-q4.gguf", size=64)
    (root / "notes.txt").write_text("not a model")
    files, skipped, truncated = scan_model_files([root])
    assert skipped == 0 and truncated is False
    assert [f.name for f in files] == ["tiny-q4"]
    assert files[0].format == "gguf" and files[0].parts == 1
    assert files[0].size_bytes == 64

def test_scan_rejects_non_gguf_magic_as_incomplete(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "corrupt.gguf", head=b"NOPE")
    files, skipped, _ = scan_model_files([root])
    assert files == [] and skipped == 1

def test_scan_groups_multipart_shards_into_one_model(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "big-00001-of-00003.gguf", size=100)
    _write_gguf(root / "big-00002-of-00003.gguf", size=100)
    _write_gguf(root / "big-00003-of-00003.gguf", size=100)
    files, skipped, _ = scan_model_files([root])
    assert skipped == 0
    assert len(files) == 1
    assert files[0].name == "big" and files[0].parts == 3
    assert files[0].size_bytes == 300
    assert files[0].path.name == "big-00001-of-00003.gguf"

def test_scan_keeps_prefix_colliding_shard_families(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "llama-00001-of-00002.gguf")
    _write_gguf(root / "llama-00002-of-00002.gguf")
    _write_gguf(root / "llama-instruct-00001-of-00002.gguf")
    _write_gguf(root / "llama-instruct-00002-of-00002.gguf")
    files, skipped, _ = scan_model_files([root])
    assert skipped == 0
    assert sorted(f.name for f in files) == ["llama", "llama-instruct"]
    assert all(f.parts == 2 for f in files)

def test_scan_skips_incomplete_shard_sets_and_orphan_shards(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "half-00002-of-00002.gguf")  # first shard missing
    _write_gguf(root / "set-00001-of-00002.gguf")   # second shard missing
    files, skipped, _ = scan_model_files([root])
    assert files == [] and skipped == 2

def test_scan_bounds_depth_and_skips_hidden_entries(tmp_path):
    root = tmp_path / "models"
    deep = root / "a" / "b" / "c" / "d"
    _write_gguf(deep / "reachable.gguf")
    _write_gguf(deep / "e" / "too-deep.gguf")
    _write_gguf(root / ".hidden" / "secret.gguf")
    names = [f.name for f in scan_model_files([root])[0]]
    assert "reachable" in names
    assert "too-deep" not in names and "secret" not in names

def test_scan_truncates_at_entry_cap_with_flag(tmp_path):
    root = tmp_path / "models"
    for index in range(MAX_SCAN_ENTRIES + 10):
        _write_gguf(root / f"m{index:04}.gguf")
    files, _skipped, truncated = scan_model_files([root])
    assert truncated is True
    assert len(files) <= MAX_SCAN_ENTRIES

def test_missing_roots_are_silent(tmp_path):
    files, skipped, truncated = scan_model_files([tmp_path / "nope"])
    assert files == [] and skipped == 0 and truncated is False

def test_model_scan_roots_dedupes_and_appends_default(tmp_path):
    roots = model_scan_roots(["~/m", "~/m"], tmp_path)
    assert roots == [Path("~/m").expanduser().resolve(), (tmp_path / "models").resolve()]

def test_scan_roots_resolve_relative_dirs_across_cwd(tmp_path, monkeypatch):
    root = tmp_path / "relmodels"
    root.mkdir()
    _write_gguf(root / "m.gguf", size=10)
    monkeypatch.chdir(tmp_path)
    files, _skipped, _truncated = scan_model_files(model_scan_roots(["relmodels"], tmp_path))
    assert files and files[0].path.is_absolute()  # Codex path-stability fold

def test_non_contiguous_shard_set_is_rejected(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    _write_gguf(root / "x-00001-of-00002.gguf", size=10)
    _write_gguf(root / "x-00003-of-00002.gguf", size=10)
    files, skipped, _truncated = scan_model_files([root])
    assert files == [] and skipped == 2  # Codex contiguity fold

def test_visit_budget_bounds_non_gguf_directories(tmp_path, monkeypatch):
    import ipostudio.catalog.scan as scan_module

    root = tmp_path / "models"
    root.mkdir()
    for index in range(50):
        (root / f"note-{index:03d}.txt").write_bytes(b"x")
    monkeypatch.setattr(scan_module, "MAX_SCAN_VISITED", 10)
    files, _skipped, truncated = scan_model_files([root])
    assert files == [] and truncated is True  # Codex budget fold

def test_looks_like_gguf_tolerates_unreadable_file(tmp_path):
    assert looks_like_gguf(tmp_path / "absent.gguf") is False

def test_upsert_is_idempotent_by_path_and_updates_size(tmp_path):
    conn = _make_db(tmp_path)
    target = tmp_path / "m.gguf"
    upsert_models(conn, [ModelFile("m", target, 10, "gguf", 1)])
    upsert_models(conn, [ModelFile("m", target, 20, "gguf", 1)])
    rows = list_models(conn)
    assert len(rows) == 1 and rows[0]["size_bytes"] == 20
    conn.close()

def test_find_model_exact_name_then_path_then_suffix(tmp_path):
    conn = _make_db(tmp_path)
    upsert_models(
        conn,
        [
            ModelFile("alpha", tmp_path / "alpha.gguf", 1, "gguf", 1),
            ModelFile("beta", tmp_path / "nested" / "beta.gguf", 1, "gguf", 1),
        ],
    )
    assert find_model(conn, "alpha")[0]["name"] == "alpha"
    assert find_model(conn, str(tmp_path / "alpha.gguf"))[0]["name"] == "alpha"
    assert find_model(conn, "nested")[0]["name"] == "beta"
    assert find_model(conn, "gamma") == []
    conn.close()
