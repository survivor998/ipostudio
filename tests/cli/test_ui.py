# tests/cli/test_ui.py
"""Presentation layer: color gating must be platform-neutral and degrade
silently (piped output, NO_COLOR, dumb terminals, pythonw None-streams)."""
import sys

from ipostudio.cli import ui


class _FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_use_color_follows_interactivity():
    assert ui.use_color(env={}, stream=_FakeStream(True)) is True
    assert ui.use_color(env={}, stream=_FakeStream(False)) is False


def test_no_color_non_empty_value_disables_color():
    # no-color.org: present and not an empty string, regardless of the value
    for value in ("1", "0", "false", " ", "whatever"):
        assert ui.use_color(env={"NO_COLOR": value}, stream=_FakeStream(True)) is False


def test_no_color_empty_string_keeps_color():
    assert ui.use_color(env={"NO_COLOR": ""}, stream=_FakeStream(True)) is True


def test_dumb_term_disables_color():
    assert ui.use_color(env={"TERM": "dumb"}, stream=_FakeStream(True)) is False


def test_force_color_overrides_no_color():
    # FORCE_COLOR wins over everything (chalk convention, ENG F4 + Codex ENG #3):
    # stripped "0"/"false" = disable, any other non-empty = force on
    assert ui.use_color(env={"NO_COLOR": "1", "FORCE_COLOR": "1"}, stream=_FakeStream(True)) is True
    assert ui.use_color(env={"FORCE_COLOR": "1"}, stream=_FakeStream(False)) is True
    assert ui.use_color(env={"FORCE_COLOR": "0"}, stream=_FakeStream(True)) is False
    assert ui.use_color(env={"NO_COLOR": "1", "FORCE_COLOR": "false"}, stream=_FakeStream(True)) is False
    assert ui.use_color(env={"NO_COLOR": "1", "FORCE_COLOR": " "}, stream=_FakeStream(True)) is False


def test_use_color_tolerates_none_stream(monkeypatch):
    # pythonw.exe: sys.stdout/sys.stderr are None; helpers degrade, never raise.
    # env={} isolates the None-stream branch from ambient NO_COLOR/TERM.
    monkeypatch.setattr(sys, "stdout", None)
    assert ui.use_color(env={}) is False


def test_paint_passes_text_through_without_color():
    assert ui.paint("[PASS]", "green", color=False) == "[PASS]"
    assert ui.paint("[PASS]", None, color=True) == "[PASS]"


def test_paint_wraps_ansi_when_enabled():
    assert ui.paint("[PASS]", "green", color=True) == "\x1b[32m[PASS]\x1b[0m"


def test_check_line_formats_and_colors_known_marks():
    assert ui.check_line("[PASS]", "config", "ok", color=False) == "[PASS] config: ok"
    assert ui.check_line("[FAIL]", "db", "x", color=True).startswith("\x1b[31m[FAIL]\x1b[0m db: x")
    assert ui.check_line("[OTHER]", "db", "x", color=True) == "[OTHER] db: x"  # unknown mark: plain
