import logging
import logging.handlers

from ipostudio.logs import (
    log_file_path,
    redact_text,
    redaction_count,
    setup_logging,
)


def test_redact_text_masks_common_secret_shapes():
    sample = (
        'request failed: api_key=sk-abc123def456ghi789 header '
        'Authorization: Bearer eyJhbGc.iOiJIUzI1.NiIsInR5cCI6 mode=proxy'
    )
    out = redact_text(sample)
    assert "sk-abc123def456ghi789" not in out
    assert "eyJhbGc.iOiJIUzI1.NiIsInR5cCI6" not in out
    assert "mode=proxy" in out
    assert redaction_count() >= 2


def test_redact_covers_underscore_json_url_and_bare_key_forms():
    # every shape named by the eng dual-voice consensus
    sample = (
        'access_token=tok1 AUTH_TOKEN: tok2 gateway_api_key=tok3 '
        '"api_key": "tok4" https://api.example.com?key=tok5 '
        'http://user:secret@host/pa th'
    )
    out = redact_text(sample)
    for leaked in ("tok1", "tok2", "tok3", "tok4", "tok5", "user:secret"):
        assert leaked not in out, leaked
    assert "/pa th" in out or "/pa" in out  # non-secret URL path survives


def test_setup_logging_writes_file_and_rotates(tmp_path):
    logger = setup_logging(tmp_path, level="debug", max_bytes=512, backups=2)
    for i in range(40):
        logger.warning("line %d with token=secretpassword123", i)
    handlers = [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert handlers, "expected a rotating file handler"
    assert log_file_path(tmp_path).exists()
    rotated = list((tmp_path / "logs").glob("ipostudio.log.*"))
    assert rotated, "expected at least one rotated file"
    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "secretpassword123" not in content
    assert "***" in content


def test_json_lines_formatter(tmp_path):
    import json

    logger = setup_logging(tmp_path, json_lines=True)
    logger.error("plain failure")
    lines = log_file_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert lines, "log file should not be empty"
    record = json.loads(lines[-1])
    assert record["level"] == "ERROR"
    assert record["message"] == "plain failure"


def test_traceback_secrets_are_redacted(tmp_path):
    logger = setup_logging(tmp_path)
    try:
        raise RuntimeError("auth failed for https://api.example.com?key=sk-topsecret99887766")
    except RuntimeError:
        logger.exception("engine bootstrap failed")
    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "sk-topsecret99887766" not in content
    assert "Traceback" in content  # forensics preserved, secret scrubbed


def test_setup_logging_is_idempotent(tmp_path):
    first = setup_logging(tmp_path)
    second = setup_logging(tmp_path)
    assert first is second
    assert len(second.handlers) == 2  # one console + one file
