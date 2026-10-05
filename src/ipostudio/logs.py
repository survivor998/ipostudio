"""Rotating, redacting, optionally JSONL logging (ADR-006, spec §5.23/§15)."""

import json
import logging
import re
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "ipostudio"
LOG_FILE_NAME = "ipostudio.log"

# Left boundary (?<![A-Za-z0-9_-]) instead of \b: \b never fires between
# "access_" and "token" because _ is a word char, so access_token= would slip
# through unmasked (eng review M1). "key" alone is included for ?key= URLs.
# Two extensions over the brief's draft, required by its own consensus tests:
# - the api-key alternative carries the same [a-z0-9_-]* token-start prefix as
#   token/secret/password, so gateway_api_key= matches as one token (the left
#   boundary rightly forbids starting mid-word after "_");
# - the separator tolerates the closing quote (single or double) of
#   JSON/Python-style keys ("api_key": or 'password':).
# The value group takes a quoted string before the bare-token fallback.
# It must be ESCAPE-AWARE (\\" inside a JSON-serialized value is not a closing
# quote: {"api_key": "abc\\"def"} used to leak def"}, the exact leak class
# H-01 closed), LINE-LOCAL (the class excludes \\n, so an unterminated quote
# in a multi-line traceback falls back to the bare token instead of swallowing
# every line up to the next quote), and it consumes a glued non-space tail
# after the closing quote ("abc"def masks whole) so masking is never weaker
# than the old bare \\S+ fallback.
_SECRET_KEY_VALUE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])"
    r"((?:[a-z0-9_-]*token)|(?:[a-z0-9_-]*api[_-]?key)|(?:[a-z0-9_-]*secret)|"
    r"(?:[a-z0-9_-]*password)|(?:authorization)|(?:credential)|key)"
    r"(?![A-Za-z0-9_-])(\s*"
    r"['\"]?\s*[=:]\s*)"
    r'("(?:[^"\\\n]|\\.)*"[^\s]*|\'(?:[^\'\\\n]|\\.)*\'[^\s]*|\S+)'
)
# credentials embedded in URLs: http://user:password@host
_URL_CREDENTIAL = re.compile(r"(?i)(://)([^/\s:@]+):([^/\s@]+)(@)")
_BEARER = re.compile(r"(?i)\bbearer\s+(\S+)")
_LONG_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_MASK = "***"

_masked_total = 0


def redaction_count() -> int:
    return _masked_total


def redact_unambiguous(text: str) -> str:
    """Mask only unambiguous secret shapes (Bearer tokens, ``sk-`` tokens,
    URL-embedded credentials) -- for error output that bypasses the logging
    pipeline.  The generic ``key=value`` family fires on prose like
    ``unknown environment key: IPO_X`` and would corrupt diagnostics there."""
    text = _BEARER.sub(lambda m: f"{m.group(0).split()[0]} {_MASK}", text)
    text = _LONG_TOKEN.sub(_MASK, text)
    return _URL_CREDENTIAL.sub(
        lambda m: f"{m.group(1)}{_MASK}:{_MASK}{m.group(4)}", text
    )


def redact_text(text: str) -> str:
    """Mask credential-looking values; returns the scrubbed text.

    Order matters: bearer tokens and ``sk-`` tokens are masked first so the
    generic ``key=value`` rule cannot swallow the word ``Bearer`` as a value
    and leave the actual token exposed.
    """
    global _masked_total
    hits = [0]

    def _kv(match: re.Match[str]) -> str:
        hits[0] += 1
        return f"{match.group(1)}{match.group(2)}{_MASK}"

    def _bearer(match: re.Match[str]) -> str:
        hits[0] += 1
        return f"{match.group(0).split()[0]} {_MASK}"

    def _token(match: re.Match[str]) -> str:
        hits[0] += 1
        return _MASK

    text = _BEARER.sub(_bearer, text)
    text = _LONG_TOKEN.sub(_token, text)
    text = _URL_CREDENTIAL.sub(lambda m: (hits.__setitem__(0, hits[0] + 1), f"{m.group(1)}{_MASK}:{_MASK}@")[1], text)
    text = _SECRET_KEY_VALUE.sub(_kv, text)
    _masked_total += hits[0]
    return text


class RedactionFilter(logging.Filter):
    """Mask credentials in the message AND in the exc_info traceback.

    Tracebacks are the likeliest leak path (exception strings carry URLs and
    subprocess argv); filtering record.msg alone leaves them untouched
    (CEO review consensus), so both formatters re-redact the fully formatted
    output (which appends exc_text) as a second layer.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        masked = redact_text(message)
        if masked != message:
            record.msg = masked
            record.args = None
        if record.exc_info:
            record.exc_text = redact_text(self.format_exception(record.exc_info))
        return True

    @staticmethod
    def format_exception(exc_info) -> str:
        import traceback

        return "".join(traceback.format_exception(*exc_info))


class _PlainTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        if record.exc_info:
            payload["traceback"] = redact_text(
                "".join(__import__("traceback").format_exception(*record.exc_info))
            )
        return json.dumps(payload, ensure_ascii=False)


def log_file_path(data_dir: Path) -> Path:
    return data_dir / "logs" / LOG_FILE_NAME


def setup_logging(
    data_dir: Path,
    *,
    level: str = "info",
    json_lines: bool = False,
    max_bytes: int = 2_000_000,
    backups: int = 5,
    console: bool = True,
) -> logging.Logger:
    """Install the "ipostudio" logger with a rotating, redacting file handler.

    ``console=False`` serves the CLI wiring (ADR-006 / TODO-004: short-lived
    commands share ``ipostudio.log`` file-only): records must never duplicate
    the command's own stdout/stderr error contract on the terminal.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file_path(data_dir), maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    formatter = (
        _JsonLineFormatter()
        if json_lines
        else _PlainTextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handlers: list[logging.Handler] = [file_handler]
    if console:
        handlers.insert(0, logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RedactionFilter())
        logger.addHandler(handler)
    return logger
