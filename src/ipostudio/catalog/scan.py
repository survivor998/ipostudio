"""Local GGUF discovery for the model catalog (spec §5.2 local management).

Core-loop slice: single- and multi-part GGUF files under the configured
roots.  safetensors directories, remote references and category correction
arrive with P2.  The walker bounds depth and entry count so a mis-pointed
MODEL_DIR entry cannot stall the CLI; incomplete sets (bad GGUF magic,
missing shards) are skipped with a count instead of registered as models
(spec §13: incomplete weights must not present as valid)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

GGUF_MAGIC = b"GGUF"
GGUF_SUFFIX = ".gguf"
_SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$")
MAX_SCAN_DEPTH = 4
MAX_SCAN_ENTRIES = 500
MAX_SCAN_VISITED = 20000  # every visited entry counts, not only GGUF candidates

def shard_family_complete(path: Path) -> bool:
    """True when `path`'s shard family (if any) is fully present on disk.
    The catalog is insert-only until P2 pruning, so the server path
    re-validates the recorded file set before launch (Codex stale-row
    fold)."""
    match = _SHARD.search(path.name)
    if match is None:
        return path.exists()
    total = int(match.group(2))
    base = path.name[: match.start()]
    indexes: set[int] = set()
    try:
        for entry in os.scandir(path.parent):
            found = _SHARD.search(entry.name)
            if found is not None and entry.name[: found.start()] == base:
                indexes.add(int(found.group(1)))
    except OSError:
        return False
    return indexes == set(range(1, total + 1))

@dataclass(frozen=True)
class ModelFile:
    name: str
    path: Path
    size_bytes: int
    format: str
    parts: int

def model_scan_roots(model_dirs: list[str], data_dir: Path) -> list[Path]:
    """Configured dirs plus the default <data>/models root, deduplicated
    (architecture.md data layout: the data-dir models/ folder is always a
    scan root; MODEL_DIRS adds more).  Identities are persisted absolute
    (`resolve()`), so scanning from directory A and starting from directory
    B address the same rows (Codex path-stability fold)."""
    roots: list[Path] = []
    for raw in [*model_dirs, str(data_dir / "models")]:
        path = Path(raw).expanduser().resolve()
        if path not in roots:
            roots.append(path)
    return roots

def looks_like_gguf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(GGUF_MAGIC)) == GGUF_MAGIC
    except OSError:
        return False

def _iter_files(root: Path, unreadable: list, visited: list):
    """Bounded recursive walk: depth <= MAX_SCAN_DEPTH; hidden entries and
    symlinked directories are never descended.  os.scandir with
    follow_symlinks=False keeps this 3.11-compatible (pathlib's
    follow_symlinks kwarg on is_dir/is_file is 3.12+) and R1-clean.
    Entries are streamed (never materialized: a mis-pointed directory with
    a million non-GGUF files must not exhaust memory — Codex budget fold)
    and EVERY visited entry counts toward the shared `visited[0]` budget.
    Unreadable directories are appended to `unreadable` so the skip count
    stays honest (spec §13/§12.3: silence must be counted, never free)."""
    def walk(directory: Path, depth: int):
        if depth > MAX_SCAN_DEPTH:
            unreadable.append(directory)  # ENG F8: depth refusal is accounted
            return
        try:
            scanner = os.scandir(directory)
        except OSError:
            unreadable.append(directory)
            return
        with scanner:
            for entry in scanner:
                if visited[0] >= MAX_SCAN_VISITED:
                    return
                visited[0] += 1
                yield entry
                if entry.name.startswith("."):
                    continue  # never descend into hidden directories
                if entry.is_dir(follow_symlinks=False):
                    yield from walk(Path(entry.path), depth + 1)

    yield from walk(root, 0)

def _collect_candidates(roots: list[Path]) -> tuple[list[Path], bool, int]:
    candidates: list[Path] = []
    truncated = False
    unreadable: list = []
    visited = [0]  # shared across roots: the budget is global, not per-root
    for root in roots:
        if not root.is_dir():
            if root.exists():
                unreadable.append(root)  # ENG F8: configured root is a file
            continue
        for entry in _iter_files(root, unreadable, visited):
            if not entry.name.endswith(GGUF_SUFFIX) or entry.name.startswith("."):
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            if len(candidates) >= MAX_SCAN_ENTRIES:
                return candidates, True, len(unreadable)
            candidates.append(Path(entry.path))
    return candidates, truncated or visited[0] >= MAX_SCAN_VISITED, len(unreadable)

def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None

def scan_model_files(roots: list[Path]) -> tuple[list[ModelFile], int, bool]:
    """Return (models, skipped, truncated).  `skipped` counts unreadable
    directories as well as rejected files, so silence is never free.
    Multi-part shards collapse into one ModelFile named after the shared
    stem, sized as the shard sum, with `path` pointing at the first shard
    (what llama-server consumes)."""
    candidates, truncated, unreadable = _collect_candidates(roots)
    models: list[ModelFile] = []
    skipped = unreadable
    handled: set[Path] = set()
    for path in sorted(candidates):
        if path in handled:
            continue
        handled.add(path)
        match = _SHARD.search(path.name)
        if match is None:
            size = _file_size(path)
            if size is None or not looks_like_gguf(path):
                skipped += 1
                continue
            models.append(ModelFile(path.stem, path, size, "gguf", 1))
            continue
        index, total = match.group(1), match.group(2)
        base = path.name[: match.start()]
        # prefix-collision guard (ENG F1): a candidate belongs to this family
        # only when its OWN shard match derives the same base — otherwise
        # `llama-...` would swallow `llama-instruct-...` and silently drop it
        shards = [
            candidate
            for candidate in candidates
            if candidate.parent == path.parent
            and (m2 := _SHARD.search(candidate.name)) is not None
            and candidate.name[: m2.start()] == base
        ]
        handled.update(shards)
        # equal count is not completeness: {1, 3}-of-00002 must not pass
        # (Codex contiguity fold)
        indexes = sorted(
            int(_SHARD.search(shard.name).group(1)) for shard in shards
        )
        if (
            index != "00001"
            or len(shards) != int(total)
            or indexes != list(range(1, int(total) + 1))
        ):
            # every rejected FILE counts (plan test: a non-contiguous 2-shard
            # family is skipped == 2), not one per family — silence stays free
            # of uncounted bytes (Codex contiguity fold)
            skipped += len(shards)
            continue
        sizes = [_file_size(shard) for shard in shards]
        if any(size is None for size in sizes) or not all(
            looks_like_gguf(shard) for shard in shards
        ):
            # same per-FILE invariant as the contiguity arm above: a family
            # rejected for bad magic or a missing size counts every shard
            skipped += len(shards)
            continue
        models.append(ModelFile(base, path, sum(sizes), "gguf", len(shards)))
    return models, skipped, truncated
