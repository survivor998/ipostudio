# tests/cli/test_logging_wiring.py
"""Phase-1 E2E finding: ``setup_logging`` (ADR-006: rotation, redaction,
JSONL) existed and was fully tested, but NO runtime code path ever called it —
the product's own log file ``<data>/logs/ipostudio.log`` was never created,
so doctor's logs check pointed at a file that could not exist and the
redaction/rotation machinery was dead code in production.

Contract pinned here (ADR-006 / TODO-004: the short-lived CLI shares
``ipostudio.log``): every command that engages the data layer installs
file-only logging; a broken log location must never take the command down."""

from click.testing import CliRunner

from ipostudio.cli.main import cli


def _invoke(*args):
    return CliRunner().invoke(cli, list(args))


def test_data_command_creates_the_app_log(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("status")
    assert result.exit_code == 0
    assert (tmp_path / "logs" / "ipostudio.log").exists()


def test_unwritable_app_log_never_breaks_the_command(tmp_path, monkeypatch):
    # a DIRECTORY sitting where the log file belongs is the portable way to
    # make handler creation raise OSError (PermissionError on Windows,
    # IsADirectoryError on POSIX) — the command must still work
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "ipostudio.log").mkdir()
    result = _invoke("status")
    assert result.exit_code == 0
    assert "server" in result.output
