"""Load settings.toml and apply IPO_* environment overrides (ADR-003).

Precedence: environment variable > TOML file > schema default.
TOML files are flat (no sections): ``server_port = 18080``.
Environment lists are comma-separated; the literal ``none`` clears optional fields.

Error-message contract (DX review): every ConfigError detail names the offending
key, the controlling file/env var, and a remediation clause. Files written by a
newer build (higher config_version) drop unknown keys with a warning instead of
failing, so rollback after auto-update never bricks the config.
"""

import difflib
import os
import re
import tomllib
import types
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Self, Union, get_args, get_origin

import tomli_w
from pydantic import ValidationError

from ipostudio.conf.paths import BOOTSTRAP_ENV, resolve_config_path
from ipostudio.conf.schema import FAMILIES, FLAT_KEYS, AppConfig
from ipostudio.logs import redact_unambiguous

_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """Raised for unreadable, unknown or invalid configuration input."""

    def __init__(self, details: list[str]) -> None:
        # Details echo raw input values and doctor/CLI print them to stdout
        # and --json -- outside the logging redactor.  Mask unambiguous secret
        # shapes here, at the single construction surface, without letting the
        # generic key=value family corrupt prose diagnostics.
        self.details = [redact_unambiguous(detail) for detail in details]
        super().__init__("; ".join(self.details))


def _annotation(family: str, key: str) -> Any:
    return FAMILIES[family].model_fields[key].annotation


def _is_optional(ann: Any) -> bool:
    # PEP 604 unions (``str | None`` as written in schema.py) have origin
    # ``types.UnionType`` on CPython 3.10+; typing.Union covers Optional[...] form.
    return get_origin(ann) in (Union, types.UnionType) and type(None) in get_args(ann)


def _strip_optional(ann: Any) -> Any:
    if _is_optional(ann):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def suggest_key(key: str, pool: Iterable[str] | None = None) -> str:
    close = difflib.get_close_matches(
        key, pool if pool is not None else FLAT_KEYS, n=1, cutoff=0.6
    )
    return f"; did you mean {close[0]!r}?" if close else ""


def _coerce_env(
    raw_key: str,
    raw_value: str,
    ann: Any,
    *,
    bool_remediation: str = "fix the environment variable or unset it",
    origin_label: str | None = None,
) -> Any:
    if _is_optional(ann) and raw_value.strip().lower() in {"", "none", "null"}:
        return None
    ann = _strip_optional(ann)
    origin = get_origin(ann)
    if ann is bool:
        lowered = raw_value.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
        # origin_label/bool_remediation let the CLI re-point this error at the
        # command line (config key as subject); loader's own call sites take
        # the defaults and keep the byte-identical env-var message
        raise ConfigError(
            [(f"{origin_label or raw_key}: expected a boolean (true/false/1/0), "
             f"got {raw_value!r}; {bool_remediation}")]
        )
    if ann is int:
        return int(raw_value.strip())
    if ann is float:
        return float(raw_value.strip())
    if origin is list:
        # unambiguous encoding first: a JSON array keeps commas inside values
        # (engine extra args) intact; bare comma-split stays as legacy form.
        text = raw_value.strip()
        if text.startswith("["):
            import json

            return [str(item) for item in json.loads(text)]
        return [part.strip() for part in raw_value.split(",") if part.strip()]
    # shell-transplanted values carry stray padding; every scalar branch
    # strips, and so does the string branch (QA-A-02)
    return raw_value.strip()


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(
            [(f"cannot read settings file {path}: {exc}; "
             f"check file permissions, then re-run or delete the file to regenerate defaults")]
        ) from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            [(f"settings file is not valid UTF-8 TOML ({path}): {exc}; "
             f"fix or delete the offending line, or restore the file from a backup")]
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError([f"settings file must be a table ({path})"])
    return data


_SCHEMA_CONFIG_VERSION = 1


def coerce_value(key: str, raw: str) -> Any:
    """Turn a CLI-provided string into the typed value for `key`.

    Same coercion rules as IPO_* environment variables (one code path:
    `_coerce_env`), so `ipo config set` and the env override can never
    disagree about what a value means.  Remediation text is re-phrased for
    the command line: the error origin is the CLI argument, not the shell."""
    if key not in FLAT_KEYS:
        raise ConfigError(
            [f"unknown config key: {key}{suggest_key(key)}; see `ipo config list`"]
        )
    try:
        coerced = _coerce_env(
            f"IPO_{key.upper()}", raw, _annotation(FLAT_KEYS[key], key),
            bool_remediation="pass a boolean true/false/1/0 on the command line",
            origin_label=key,
        )
    except ValueError as exc:
        # int/float/JSON-array coercion failures surface as ConfigError too:
        # the CLI write surface has the same single error contract as
        # load_config, with the config key as subject (never the IPO_ name)
        raise ConfigError(
            [(f"{key}: cannot convert {raw!r} ({exc}); pass a JSON array of "
              f"strings, e.g. [\"a\", \"b\"]")]
        ) from exc
    if isinstance(coerced, list) and any(not isinstance(item, str) for item in coerced):
        # _coerce_env str()-ifies JSON array elements (loader's env-path legacy);
        # a public CLI write surface must reject [null, {...}] instead of
        # silently accepting it as strings (Codex ENG acceptance-b)
        raise ConfigError(
            [(f"{key}: JSON array elements must all be strings; got a "
              f"non-string element in {raw!r}; quote every element")]
        )
    return coerced


def file_key_names(path: Path) -> set[str]:
    """Keys explicitly present in the settings file (source tracking)."""
    return set(_read_toml(path))


def load_config(
    env: Mapping[str, str] | None = None,
    warnings: list[str] | None = None,
) -> AppConfig:
    """Load settings; ``warnings`` (if given) receives non-fatal notices."""
    env = os.environ if env is None else env
    config_path = resolve_config_path(env)
    flat: dict[str, Any] = _read_toml(config_path)
    file_version = flat.get("config_version", _SCHEMA_CONFIG_VERSION)
    # (int, float), not int: TOML 2.0 parses a bare "2.0" as float, and the
    # int-only gate let a float version fall through to fatal unknown-key
    # handling instead of the warn-and-keep rollback path (H-06).  Pydantic
    # would coerce 2.0 -> 2 anyway, so the gate was the only thing treating
    # it as "same build".
    from_newer_build = (
        isinstance(file_version, (int, float)) and file_version > _SCHEMA_CONFIG_VERSION
    )

    details: list[str] = []
    origin: dict[str, str] = {}  # key -> env var name or the file path (error attribution)
    for raw_key, raw_value in sorted(env.items()):
        if not raw_key.startswith("IPO_") or raw_key in BOOTSTRAP_ENV:
            continue
        key = raw_key[len("IPO_"):].lower()
        if key not in FLAT_KEYS:
            # env vars come from the CURRENT shell, not a newer file: always fatal
            details.append(
                f"unknown environment key: {raw_key}{suggest_key(key)}; "
                f"unset it or correct the spelling in your shell"
            )
            continue
        try:
            flat[key] = _coerce_env(raw_key, raw_value, _annotation(FLAT_KEYS[key], key))
            origin[key] = raw_key
        except ConfigError as exc:
            # _coerce_env's bool branch reports through ConfigError with a
            # ready-made detail; accumulate it like the ValueError branch so
            # one bad variable no longer hides the others (QA-A-01)
            details.extend(exc.details)
        except ValueError as exc:
            details.append(
                f"{raw_key}: cannot convert {raw_value!r} ({exc}); "
                f"fix the value in your shell environment"
            )

    for key in flat:
        origin.setdefault(key, str(config_path))

    unknown = [key for key in flat if key not in FLAT_KEYS]
    if from_newer_build:
        for key in unknown:
            warnings_append = (
                f"ignored key {key!r} written by a newer ipostudio "
                f"(config_version={file_version}); it is kept in the file on "
                f"save and ignored until you upgrade back"
            )
            if warnings is not None:
                warnings.append(warnings_append)
            else:
                import logging

                logging.getLogger("ipostudio").warning(warnings_append)
        for key in unknown:  # drop before grouping; grouping indexes FLAT_KEYS
            del flat[key]
    else:
        for key in unknown:
            details.append(
                f"unknown config key: {key} (in {config_path}){suggest_key(key)}; "
                f"remove the line, fix the spelling, or upgrade ipostudio"
            )
    if details:
        raise ConfigError(details)

    grouped: dict[str, dict[str, Any]] = {}
    for key, value in flat.items():
        grouped.setdefault(FLAT_KEYS[key], {})[key] = value
    try:
        return AppConfig(**grouped)
    except ValidationError as exc:
        raise ConfigError(
            [
                f"{'.'.join(str(part) for part in error['loc'][:2])} "
                f"(from {origin.get(str(error['loc'][1]) if len(error['loc']) > 1 else '?', str(config_path))}): "
                f"{error['msg']}; fix the value at its origin or remove it to use the default"
                for error in exc.errors()
            ]
        ) from exc


# Credential-shaped keys are never written to disk by ConfigStore: they are
# env-only until the P4 encrypted secret store lands (architecture.md secrets
# boundary; CEO review consensus). Hand-written file values still load for
# local experimentation, but save() scrubs them.
CREDENTIAL_KEYS = frozenset({"vllm_api_key", "embedding_api_key", "gateway_api_key"})


# any string value containing an inline URL credential is rejected regardless
# of key name (proxy_url, engine extra args, future keys) — eng review: the
# three-key name blacklist alone cannot uphold "credentials never on disk".
_URL_CREDENTIAL_PATTERN = re.compile(r"(?i)://[^/\s:@]+:[^/\s@]+@")


def _contains_url_credential(value: Any) -> bool:
    """The invariant is on VALUES, not key names: every string reachable in a
    config value — top-level, list/tuple elements (engine extra args), dict
    values — is scanned for an inline URL credential."""
    if isinstance(value, str):
        return _URL_CREDENTIAL_PATTERN.search(value) is not None
    if isinstance(value, (list, tuple)):
        return any(_contains_url_credential(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_url_credential(item) for item in value.values())
    return False


class ConfigStore:
    """Validating, locked, dirty-key atomic writer for the active settings file.

    - ``set(key, value)`` checks policy (credential keys, URL-embedded
      credentials) FIRST, then validates the value on a candidate copy and only
      then mutates self.config — rejected calls leave memory byte-identical.
    - All rejections raise ConfigError (single error surface for callers).
    - save() holds a cross-process advisory lock around read-merge-replace so
      concurrent writers serialize instead of losing each other's keys.
    - Only explicitly set keys are written; credential keys are scrubbed from
      the merged output; environment overrides are never baked into the file.
    - The temp file is unique per process and removed on failure.
    """

    def __init__(self, path: Path, config: AppConfig) -> None:
        self.path = path
        self.config = config
        self._dirty: set[tuple[str, str]] = set()

    def set(self, key: str, value: Any) -> None:
        if key not in FLAT_KEYS:
            raise ConfigError([(f"unknown config key: {key}{suggest_key(key)}; "
                               f"check the spelling against `ipo guide`")])
        if key in CREDENTIAL_KEYS:
            raise ConfigError(
                [(f"{key} is credential-shaped and never persisted; "
                 f"pass it via the environment (IPO_{key.upper()}) until the "
                 f"encrypted secret store lands (P4)")]
            )
        if _contains_url_credential(value):
            raise ConfigError(
                [(f"{key}: value contains an inline URL credential "
                 f"(user:password@host); move the credential to an "
                 f"IPO_-prefixed environment variable instead")]
            )
        family = FLAT_KEYS[key]
        section = getattr(self.config, family)
        candidate = section.model_dump()
        candidate[key] = value
        try:
            validated = FAMILIES[family].model_validate(candidate)
        except ValidationError as exc:
            raise ConfigError(
                [(f"{family}.{key}: {exc.errors()[0]['msg']}; "
                 f"choose a value matching the documented range/type")]
            ) from exc
        setattr(section, key, getattr(validated, key))  # normalized value
        self._dirty.add((family, key))

    def save(self) -> Path:
        # Codex ENG #2: the OSError->ConfigError boundary covers ALL pre-commit
        # steps -- mkdir, the advisory-lock open and the mkstemp -- not just the
        # write itself, so permission failures surface through the error
        # contract instead of a raw OSError.
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_suffix(self.path.suffix + ".lock")
            with _advisory_lock(lock_path):
                merged: dict[str, Any] = dict(_read_toml(self.path))
                for key in CREDENTIAL_KEYS:
                    merged.pop(key, None)
                for family, key in self._dirty:
                    value = getattr(getattr(self.config, family), key)
                    if value is None:
                        merged.pop(key, None)
                    else:
                        merged[key] = value
                fd, temp_name = _mkstemp_in(self.path.parent)
                try:
                    with os.fdopen(fd, "wb") as handle:
                        tomli_w.dump(merged, handle)
                        # durable atomic save: the data must reach the disk before
                        # the rename, or power loss can persist os.replace with an
                        # empty/truncated settings file (H-02).  fsync is
                        # best-effort: some filesystems reject it outright, and
                        # handle.flush() has already handed the data to the OS.
                        handle.flush()
                        try:
                            os.fsync(handle.fileno())
                        except OSError:
                            pass
                    os.replace(temp_name, self.path)
                except BaseException:
                    # a failure from the dump (TypeError on a bad value) or the
                    # write must not litter the data directory with temp files;
                    # OSErrors re-raised here hit the boundary below
                    Path(temp_name).unlink(missing_ok=True)
                    raise
                _fsync_directory(self.path.parent)
        except OSError as exc:
            raise ConfigError(
                [(f"cannot write settings file {self.path}: {exc}; "
                 f"check permissions and whether another process holds the "
                 f"file open, then retry")]
            ) from exc
        self._dirty.clear()
        return self.path


def _mkstemp_in(directory: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory-entry durability after os.replace (POSIX: the
    rename itself can still be lost to power loss otherwise).  Windows offers
    no directory fsync -- os.open on a directory raises there, which the
    except swallows, so no platform branching is needed.  A failure never
    fails the save: the data itself was already fsynced before the rename."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class _advisory_lock:
    """Portable cross-process mutex via O_CREAT|O_EXCL lock file with timeout."""

    def __init__(self, path: Path, timeout_seconds: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout_seconds
        self.held = False

    def __enter__(self) -> Self:
        import time

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self.held = True
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise ConfigError(
                        [(f"settings file is locked by another process "
                         f"({self.path}); wait for it to finish or remove a "
                         f"stale lock after confirming no ipostudio process runs")]
                    )
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        if self.held:
            self.held = False
            # lock release is post-commit cleanup (save() has already landed
            # the file by the time __exit__ runs): a failure here must never
            # be reported as a save failure, so stay best-effort.  Lock-file
            # residue is TODO-007's stale-lock self-healing territory.
            try:
                os.close(self.fd)
            except OSError:
                pass
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
