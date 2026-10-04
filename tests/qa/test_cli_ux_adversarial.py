"""Adversarial cases for the CLI UX layer: machine-readability of --json,
pythonw robustness, welcome-card resilience and credential non-disclosure."""
import inspect
import json
import os
import subprocess
import sys

import click
import pytest
from click.testing import CliRunner

from ipostudio.cli import main as cli_main
from ipostudio.cli import ui
from ipostudio.cli.main import cli
from ipostudio.conf.paths import BOOTSTRAP_ENV

BOOTSTRAP_KEYS = tuple(sorted(BOOTSTRAP_ENV))  # review M-1: track the source of truth


@pytest.fixture
def _restore_bootstrap_env():
    """The `ipo` group callback translates --config/--data-dir into os.environ
    and deliberately never restores it; keep that leak out of the test process.
    Module-scoped copy of tests/qa/test_cli_adversarial.py's reviewed fixture:
    this package has no conftest.py, so each module carries its own."""
    saved = {key: os.environ.get(key) for key in BOOTSTRAP_KEYS}
    yield
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def all_output(result):
    """Duplicate of tests.cli.test_main.all_output — the QA module stays
    import-isolated from the regular suite (no cross-package coupling)."""
    try:
        return result.output + result.stderr
    except ValueError:  # click 8.1: stderr merged into output already
        return result.output


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


def _takes_json(command) -> bool:
    return any("--json" in getattr(p, "opts", ()) for p in command.params)


def _has_required_args(command) -> bool:
    return any(getattr(p, "required", False) for p in command.params)


def _json_invocations():
    """Every command surface that accepts --json and needs no extra args
    (config get needs KEY, so it keeps its own dedicated tests)."""
    for name, command in cli.commands.items():
        if isinstance(command, click.Group):
            for sub_name, sub in command.commands.items():
                if _takes_json(sub) and not _has_required_args(sub):
                    yield [name, sub_name, "--json"]
        elif _takes_json(command) and not _has_required_args(command):
            yield [name, "--json"]


def test_every_json_capable_command_stays_clean(tmp_path, monkeypatch):
    # walker over the live command registry: a future --json command is
    # covered automatically instead of trusting an enumerated list (CEO F4c)
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: True)
    cases = sorted(_json_invocations())
    assert {"version --json", "doctor --json", "config path --json", "config list --json"} <= {
        " ".join(args) for args in cases
    }
    for args in cases:
        result = CliRunner().invoke(cli, args, color=True)
        assert result.exit_code == 0, (args, result.output)
        assert "\x1b[" not in result.output, args  # byte-clean
        json.loads(result.output)  # and parseable


def test_main_py_never_styles_directly():
    # all human-facing styling routes through cli/ui.py, so the NO_COLOR and
    # tty degradation contract cannot be bypassed by a future command (F4b)
    source = inspect.getsource(cli_main)
    assert "click.style" not in source
    assert "click.secho" not in source


def test_ui_helpers_tolerate_none_streams(monkeypatch):
    # pythonw.exe: streams are None; every presenter degrades, never raises.
    # env={} isolates the None-stream branch from ambient NO_COLOR/TERM.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert ui.use_color(env={}) is False


def test_welcome_card_stays_plain_and_never_crashes(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(cli, [], color=True)
    assert result.exit_code == 0
    assert "\x1b[" not in result.output  # the card is prose, never styled


def test_help_screen_obeys_the_color_gate(tmp_path, monkeypatch):
    # click renders help/usage itself; the ctx.color gate (DX F6) must make
    # click's own output obey the same NO_COLOR/tty contract as our lines
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: False)
    result = CliRunner().invoke(cli, ["--help"], color=True)
    assert result.exit_code == 0
    assert "\x1b[" not in result.output


def test_welcome_card_survives_garbage_ui_lang(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_UI_LANG", "fr")  # not in the zh/en enum
    result = invoke()
    assert result.exit_code == 0  # fallback, not a crash
    assert "上手三步" in result.output


def test_config_list_never_discloses_credentials_on_any_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text(
        'config_version = 1\nvllm_api_key = "sk-hand-written"\n', encoding="utf-8"
    )
    text = CliRunner().invoke(cli, ["config", "list"], color=True).output
    payload = json.dumps(json.loads(invoke("config", "list", "--json").output),
                         ensure_ascii=False)
    for artifact in (text, payload):
        assert "sk-hand-written" not in artifact
        assert "***" in artifact


def test_config_set_group_flags_reach_the_store(tmp_path, monkeypatch, _restore_bootstrap_env):
    # the group-level --data-dir/--config flags are the documented README path;
    # only IPO_ env vars were exercised so far (ENG F11)
    settings = tmp_path / "custom" / "settings.toml"
    settings.parent.mkdir(parents=True)
    # --data-dir points at the pre-created directory: the settings file lands
    # at <data-dir>/settings.toml (the layout resolve_config_path pins)
    result = invoke("--data-dir", str(settings.parent), "config", "set", "ui_theme", "dark")
    assert result.exit_code == 0, result.output
    assert settings.exists()  # written under the --data-dir layout, not the real home


def test_config_set_masks_credential_values_in_success_line(tmp_path, monkeypatch):
    # store.set rejects credential keys — but if policy ever loosens (P4 store),
    # the success line must still not echo the secret; pin the current behavior.
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "vllm_api_key", "sk-abc123def456ghi789")
    assert result.exit_code == 1
    assert "sk-abc123def456ghi789" not in all_output(result)  # secret never echoed
    assert "IPO_VLLM_API_KEY" in all_output(result)  # remediation, not the secret


def test_config_get_json_never_carries_credential_values(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "vllm_api_key", "--json")
    assert result.exit_code == 1  # refused outright: no value channel exists
    assert "\x1b[" not in all_output(result)


def test_welcome_survives_ascii_forced_streams(tmp_path):
    # A redirected stream with a locale/ascii codec is exactly what
    # _force_utf8_streams() exists to survive (R1): regress it to a hard fail.
    # Precondition: src/ipostudio/__main__.py exists and is smoke-covered by
    # tests/test_package.py — `python -m ipostudio` reaches the click group.
    env = dict(
        os.environ,
        IPO_DATA_DIR=str(tmp_path),
        IPO_UI_LANG="zh",  # pin the card language: the parent may export en
        PYTHONIOENCODING="ascii",
    )
    env.pop("IPO_CONFIG", None)  # ambient pointer would override IPO_DATA_DIR
    proc = subprocess.run(
        [sys.executable, "-m", "ipostudio"],
        env=env, capture_output=True, timeout=60, check=False,  # ruff PLW1510
    )
    assert proc.returncode == 0, proc.stderr
    assert "上手三步".encode() in proc.stdout  # utf-8 reconfigure won
