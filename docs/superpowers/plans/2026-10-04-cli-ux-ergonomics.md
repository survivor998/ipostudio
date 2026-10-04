# CLI 人体工学（first-touch UX）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `ipo` 现有全部功能补齐人体工学 CLI UI：统一终端呈现层（颜色 + NO_COLOR/管道降级）、doctor 总结行、裸 `ipo` 首次上手欢迎卡、命令拼写纠错建议，以及规格 §9.12 要求但尚未有界面的 `ipo config` 配置交互面（path/get/set/list）——使首次接触者无需读文档即可正确使用。

**Architecture:** 新增 `src/ipostudio/cli/ui.py` 呈现基础层：所有面向人的输出经由它，`--json` 机器可读输出永不染色；颜色经 click 样式原语实现（Windows/POSIX 终端能力由 click 处理，本层零平台分支）。doctor 改走该层并追加总结行与修复后引导。`config` 命令族是既有 `ConfigStore`/loader 的 CLI 皮：校验、建议、跨进程锁、原子写全部复用数据层，本计划不新建持久化逻辑。裸 `ipo` 欢迎卡与未知命令建议由组回调与 `click.Group` 子类承载。

**Tech Stack:** Python ≥3.11；click>=8.1 的 `style`/`echo`（不新增运行时依赖）；标准库 `difflib`（近邻建议，与 loader 现有键建议同源）；测试 `pytest` + `click.testing.CliRunner`。

**Spec:** `Functional Specification v1.0.md` §9.11（CLI 命令表、失败非零退出）、§9.12（已知配置列表/读取/写入/路径查询、环境体检）；`docs/design/requirements-addendum.md` R1（三平台一级支持）；`docs/design/architecture.md` ADR-003（配置优先级 env > file > default）；`docs/superpowers/plans/2026-10-03-core-foundation.md` 的 DX 审查 CLI 约定（错误消息契约 = 问题 + 出处 + 修复动作；`--json` 为机器可读通道）。

## Global Constraints

- **三平台一级（R1）**：不得引入 POSIX-only 假设；不得在 `src/` 出现 `os.name`/`sys.platform` 分支（`tests/test_platform_hygiene.py` 守卫）；颜色能力交给 click（其自身处理 Windows 终端），本计划代码只做平台无关判断（isatty / NO_COLOR / TERM）。
- **机器可读契约**：一切 `--json` 输出保持字节干净——永不携带 ANSI 转义、永不改字段名；`--json` 是唯一的机器通道（DX 审查约定）。
- **退出码契约**：成功 0；检查/运行失败 1（doctor、config）；用法错误 2（click UsageError，含未知命令）。
- **错误消息契约**：每条错误 = 问题 + 出处（文件/环境变量）+ 修复动作；近邻建议沿用 loader 的 difflib 口径（cutoff 0.6）。
- **命名强制**：CLI 名 `ipo`；环境变量前缀 `IPO_`；配置键 = spec 键去前缀的小写蛇形（ADR-003）。
- **凭据不落盘、不上屏**：`CREDENTIAL_KEYS`（vllm/embedding/gateway api key）永不由 `config set` 写入文件（既有 store 策略），也永不被 `config get/list` 回显明文（本计划新增的不变量）。
- **NO_COLOR 语义**：按 no-color.org——变量存在且非空字符串（无论值是什么）即禁色；空字符串不禁；`TERM=dumb` 亦禁色。
- **冷启动保护（TODO-008 在案）**：`cli/main.py` 模块级只允许既有导入 + `cli/ui.py`、`conf` 公共符号；不得新增重量级模块级导入。
- **洁净室**：文案与实现独立措辞，不得复制第三方 CLI 的提示原文；内部命名独立设计。
- 所有命令在仓库根 `D:\project\ipostudio` 执行；提交信息英文 conventional（`feat:`/`test:`/`docs:`/`refactor:`），逐任务提交。
- 现有 117 项测试全绿是基线：每任务收尾必须 `python -m pytest -q`（或最小相关子集 + 最终全量）通过后再提交。

**任务顺序说明**：欢迎卡（Task 7）引导用户执行 `ipo config list`，故 config 命令族（Task 4–6）先于欢迎卡落地，避免引导指向不存在的命令。

---

### Task 1: 终端呈现基础层 `cli/ui.py`

**Files:**
- Create: `src/ipostudio/cli/ui.py`
- Test: `tests/cli/test_ui.py`（新建）

**Interfaces:**
- Consumes: `click.style`。
- Produces（后续任务与全部未来命令共用）:
  - `use_color(env: Mapping[str, str] | None = None, stream: TextIO | None = None) -> bool` — 默认读 `os.environ`/`sys.stdout`；`NO_COLOR` 非空或 `TERM=dumb` 或流非 tty 或流为 None（pythonw）→ False。
  - `paint(text: str, fg: str | None, *, color: bool) -> str` — `color=False` 或 `fg=None` 时原样返回。
  - `check_line(mark: str, name: str, detail: str, *, color: bool = False) -> str` — 已知标记（`[PASS]`/`[FAIL]`/`[WARN]`）按绿/红/黄染色，未知标记不染色；格式恒为 `{mark} {name}: {detail}`。

- [ ] **Step 1: 写失败测试**

```python
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


def test_use_color_tolerates_none_stream(monkeypatch):
    # pythonw.exe: sys.stdout/sys.stderr are None; helpers degrade, never raise
    monkeypatch.setattr(sys, "stdout", None)
    assert ui.use_color() is False


def test_paint_passes_text_through_without_color():
    assert ui.paint("[PASS]", "green", color=False) == "[PASS]"
    assert ui.paint("[PASS]", None, color=True) == "[PASS]"


def test_paint_wraps_ansi_when_enabled():
    assert ui.paint("[PASS]", "green", color=True) == "\x1b[32m[PASS]\x1b[0m"


def test_check_line_formats_and_colors_known_marks():
    assert ui.check_line("[PASS]", "config", "ok", color=False) == "[PASS] config: ok"
    assert ui.check_line("[FAIL]", "db", "x", color=True).startswith("\x1b[31m[FAIL]\x1b[0m db: x")
    assert ui.check_line("[OTHER]", "db", "x", color=True) == "[OTHER] db: x"  # unknown mark: plain
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_ui.py -v`
Expected: FAIL — `ImportError: cannot import name 'ui'`（模块尚不存在）。

- [ ] **Step 3: 最小实现**

```python
# src/ipostudio/cli/ui.py
"""Terminal presentation helpers shared by every human-facing ipo command.

Contract (inherited by all future commands): machine-readable streams
(`--json`) are never styled — helpers apply to human lines only, and every
helper collapses to plain text when stdout is redirected, NO_COLOR is set
(no-color.org: any non-empty value), or TERM=dumb.  ANSI capability on each
platform is click's job, so no platform branching lives here (R1).
"""

import os
import sys
from collections.abc import Mapping
from typing import TextIO

import click

_MARK_COLORS: dict[str, str] = {"[PASS]": "green", "[FAIL]": "red", "[WARN]": "yellow"}


def use_color(env: Mapping[str, str] | None = None, stream: TextIO | None = None) -> bool:
    """ANSI color only for an interactive stream that did not opt out."""
    env_vars = os.environ if env is None else env
    if env_vars.get("NO_COLOR", ""):
        return False
    if env_vars.get("TERM", "") == "dumb":
        return False
    target = sys.stdout if stream is None else stream
    # pythonw.exe leaves sys.stdout as None; presenters degrade silently.
    return target is not None and bool(target.isatty())


def paint(text: str, fg: str | None, *, color: bool) -> str:
    if not color or fg is None:
        return text
    return click.style(text, fg=fg)


def check_line(mark: str, name: str, detail: str, *, color: bool = False) -> str:
    """One doctor-style line: colored mark, check name, detail."""
    return f"{paint(mark, _MARK_COLORS.get(mark), color=color)} {name}: {detail}"
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_ui.py -v`
Expected: PASS（8 项）。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`
Expected: 全绿。

```bash
git add src/ipostudio/cli/ui.py tests/cli/test_ui.py
git commit -m "feat: add terminal presentation helpers with NO_COLOR and tty degradation"
```

---

### Task 2: doctor 接入呈现层 + 总结行 + 修复后引导

**Files:**
- Modify: `src/ipostudio/cli/main.py`（doctor 命令文本分支，约 386–398 行）
- Test: `tests/cli/test_main.py`（追加）

**Interfaces:**
- Consumes: `ui.check_line`、`ui.use_color`（Task 1）；既有 `run_doctor`/`CheckOutcome` 不变。
- Produces: doctor 文本输出追加**总结行**——失败时 `summary: {passed} passed, {failed} failed ({names}); follow the guidance in the failed checks above, or re-run with --fix to repair storage problems (--json gives full detail)`；修复模式全过时 `summary: {n} passed (repair mode); storage is ready — try `ipo guide` next`；其余 `summary: {n} passed.`。`[PASS]`/`[FAIL]`/`[WARN]` 标记与 `--json` 结构不变。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_doctor_text_output_has_summary_line(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "summary: 4 passed." in result.output


def test_doctor_failure_summary_names_failed_checks(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("doctor")
    assert result.exit_code == 1
    assert "summary: 3 passed, 1 failed (config)" in result.output


def test_doctor_fix_success_suggests_guide_next(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor", "--fix")
    assert result.exit_code == 0
    assert "summary: 4 passed (repair mode)" in result.output
    assert "ipo guide" in result.output


def test_doctor_color_wiring_reaches_check_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: True)
    result = CliRunner().invoke(cli, ["doctor"], color=True)
    assert result.exit_code == 0
    assert "\x1b[32m[PASS]" in result.output


def test_doctor_json_output_stays_unstyled(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: True)
    result = CliRunner().invoke(cli, ["doctor", "--json"], color=True)
    assert result.exit_code == 0
    assert "\x1b[" not in result.output  # --json is machine-readable: never styled
    json.loads(result.output)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k summary -v`
Expected: FAIL — 输出中无 `summary:`。

- [ ] **Step 3: 实现**

`src/ipostudio/cli/main.py` 顶部导入追加：

```python
from ipostudio.cli.ui import check_line, use_color
```

doctor 命令的 `else:`（文本）分支整体替换为：

```python
    else:
        color = use_color()
        for outcome in outcomes:
            mark = "[PASS]" if outcome.ok else "[FAIL]"
            # long multi-error details are truncated for the terminal with a
            # visible count; `--json` always carries the full text
            shown = outcome.detail
            if len(shown) > 300:
                shown = shown[:300] + f" ...(+{len(outcome.detail) - 300} chars; use --json)"
            click.echo(check_line(mark, outcome.name, shown, color=color))
        for warning in warnings:
            click.echo(check_line("[WARN]", "config", warning, color=color))
        passed = len(outcomes) - len(failed)
        if failed:
            names = ", ".join(outcome.name for outcome in failed)
            click.echo(
                f"summary: {passed} passed, {len(failed)} failed ({names}); follow the "
                f"guidance in the failed checks above, or re-run with --fix to repair "
                f"storage problems (--json gives full detail)"
            )
        elif repair:
            click.echo(
                f"summary: {passed} passed (repair mode); storage is ready — "
                f"try `ipo guide` next"
            )
        else:
            click.echo(f"summary: {passed} passed.")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_main.py tests/cli/test_ui.py -v`
Expected: PASS（新旧全过——`[PASS]`/`[FAIL]` 标记未变，既有断言不受影响）。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/cli/main.py tests/cli/test_main.py
git commit -m "feat: colorize doctor output and add a check summary line"
```

---

### Task 3: loader 公共助手（建议 / 强转 / 文件键清单）

**Files:**
- Modify: `src/ipostudio/conf/loader.py`
- Test: `tests/conf/test_loader.py`（追加）

**Interfaces:**
- Consumes: 既有私有 `_suggest`、`_coerce_env`、`_annotation`、`_read_toml`、`FLAT_KEYS`。
- Produces（Task 4–6、Task 8 及未来 GUI 共用）:
  - `suggest_key(key: str, pool: Iterable[str] | None = None) -> str` — 命中返回 `"; did you mean 'x'?"`，未命中 `""`（原 `_suggest` 公开化，消息不变）。
  - `coerce_value(key: str, raw: str) -> Any` — 校验 key ∈ FLAT_KEYS（未知键抛 ConfigError 带建议），按 schema 注解把 CLI 字符串转成类型化值（bool 词 / int / float / 去空白字符串 / JSON 数组或逗号列表 / `none` 清空 Optional）；ValueError 归一为 ConfigError 并附示例。
  - `file_key_names(path: Path) -> set[str]` — settings 文件中显式出现的键（缺失文件 → 空集；不可读/坏 TOML → ConfigError 原样上抛）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/conf/test_loader.py`）

```python
def test_suggest_key_returns_did_you_mean_for_close_matches():
    assert suggest_key("server_prot") == "; did you mean 'server_port'?"


def test_suggest_key_accepts_custom_pool():
    assert suggest_key("hepl", pool={"help", "guide"}) == "; did you mean 'help'?"


def test_suggest_key_empty_for_distant_names():
    assert suggest_key("zzzzzz") == ""


def test_coerce_value_parses_scalars_lists_and_none():
    assert coerce_value("server_port", "19000") == 19000
    assert coerce_value("auto_start_server", "on") is True
    assert coerce_value("server_temp", "0.5") == 0.5
    assert coerce_value("ui_lang", "  en ") == "en"  # shell-transplanted padding
    assert coerce_value("model_dirs", '["a", "b"]') == ["a", "b"]  # JSON keeps commas
    assert coerce_value("model_dirs", "a, b") == ["a", "b"]  # legacy comma form
    assert coerce_value("local_model_path", "none") is None  # optional clearing


def test_coerce_value_rejects_unknown_key_with_suggestion():
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("nope_key", "1")
    assert "unknown config key" in str(excinfo.value)


def test_coerce_value_reports_undeclarable_values_as_config_error():
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("model_dirs", "[broken")
    assert "cannot convert" in str(excinfo.value)
    assert '["a", "b"]' in str(excinfo.value)  # remediation carries an example


def test_file_key_names_reports_explicit_keys(tmp_path):
    settings = tmp_path / "settings.toml"
    settings.write_text('ui_lang = "en"\n', encoding="utf-8")
    assert file_key_names(settings) == {"ui_lang"}
    assert file_key_names(tmp_path / "missing.toml") == set()
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/conf/test_loader.py -k "suggest_key or coerce_value or file_key_names" -v`
Expected: FAIL — `ImportError: cannot import name 'suggest_key'`。

- [ ] **Step 3: 实现**（`src/ipostudio/conf/loader.py`）

把既有 `_suggest` 公开化并替换其全部调用点（消息不变，纯改名）：

```python
def suggest_key(key: str, pool: Iterable[str] | None = None) -> str:
    close = difflib.get_close_matches(
        key, pool if pool is not None else FLAT_KEYS, n=1, cutoff=0.6
    )
    return f"; did you mean {close[0]!r}?" if close else ""
```

在 `load_config` 之前新增：

```python
def coerce_value(key: str, raw: str) -> Any:
    """Turn a CLI-provided string into the typed value for `key`.

    Same coercion rules as IPO_* environment variables (one code path:
    `_coerce_env`), so `ipo config set` and the env override can never
    disagree about what a value means."""
    if key not in FLAT_KEYS:
        raise ConfigError(
            [f"unknown config key: {key}{suggest_key(key)}; see `ipo config list`"]
        )
    try:
        return _coerce_env(f"IPO_{key.upper()}", raw, _annotation(FLAT_KEYS[key], key))
    except ValueError as exc:
        raise ConfigError(
            [f"{key}: cannot convert {raw!r} ({exc}); examples: booleans "
             f"true/false, integers 8080, floats 0.5, lists [\"a\", \"b\"] or a, b, "
             f"and 'none' to clear an optional key"]
        ) from exc


def file_key_names(path: Path) -> set[str]:
    """Keys explicitly present in the settings file (source tracking)."""
    return set(_read_toml(path))
```

模块导入行补 `Iterable`：`from collections.abc import Iterable, Mapping`；`load_config`/`ConfigStore.set` 内三处 `_suggest(...)` 调用改为 `suggest_key(...)`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/conf -v`
Expected: PASS（新旧全过；消息文本未变）。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/conf/loader.py tests/conf/test_loader.py
git commit -m "refactor: expose config key suggestion, coercion and file-key helpers"
```

---

### Task 4: `ipo config` 命令组 + `path` + `get`

**Files:**
- Modify: `src/ipostudio/cli/main.py`（新命令组；放在 doctor 命令之后）
- Test: `tests/cli/test_main.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 `suggest_key`；既有 `load_config`、`resolve_config_path`、`FLAT_KEYS`、`CREDENTIAL_KEYS`、`ConfigError`。
- Produces:
  - `config` 命令组，docstring 明确列出四个子命令（`collect_command_docs`/`ipo guide` 依赖 docstring 呈现）。
  - `ipo config path [--json]` → 文本输出绝对路径；JSON `{"path": "..."}`。
  - `ipo config get KEY [--json]` → 文本：字符串原样、None → `(not set)`、其余 `json.dumps`；JSON `{"key","family","value"}`；未知键 exit 1 + 建议；凭据键拒绝显示（exit 1，指向 `IPO_<KEY>`）；配置文件损坏 exit 1（复用 ConfigError 详情）。
  - 模块级助手 `_format_value(value: Any) -> str`、`_print_config_errors(exc: ConfigError) -> None`（Task 5/6 复用）。
  - main.py 导入更新：`from ipostudio.conf.loader import CREDENTIAL_KEYS, ConfigError, load_config, suggest_key`、`from ipostudio.conf.schema import FLAT_KEYS`、`from typing import Any`；paths 导入行补 `resolve_config_path`（现为 `from ipostudio.conf.paths import ensure_layout, resolve_config_path, resolve_data_dir, resolve_db_path`）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_config_path_prints_resolved_settings_file(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "path")
    assert result.exit_code == 0
    assert str(tmp_path / "settings.toml") in result.output
    payload = json.loads(invoke("config", "path", "--json").output)
    assert payload == {"path": str(tmp_path / "settings.toml")}


def test_config_get_reports_effective_value_with_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "get", "server_port").output.strip() == "18080"
    monkeypatch.setenv("IPO_SERVER_PORT", "19000")
    assert invoke("config", "get", "server_port").output.strip() == "19000"


def test_config_get_optional_unset_key_reads_not_set(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "get", "local_model_path").output.strip() == "(not set)"


def test_config_get_json_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("config", "get", "ui_lang", "--json").output)
    assert payload == {"key": "ui_lang", "family": "ui", "value": "zh"}


def test_config_get_unknown_key_exits_1_with_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "ui_them")
    assert result.exit_code == 1
    assert "unknown config key" in result.output
    assert "ui_theme" in result.output
    assert "ipo config list" in result.output


def test_config_get_refuses_credential_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "vllm_api_key")
    assert result.exit_code == 1
    assert "IPO_VLLM_API_KEY" in result.output
    assert "never displayed" in result.output


def test_config_get_reports_broken_settings_with_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "get", "server_port")
    assert result.exit_code == 1
    assert "bogus_key" in result.output
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k config -v`
Expected: FAIL — `No such command 'config'`（exit 2）。

- [ ] **Step 3: 实现**（`src/ipostudio/cli/main.py`，doctor 命令之后追加）

```python
@cli.group()
def config() -> None:
    """Read and write settings (subcommands: path, get, set, list)."""


def _format_value(value: Any) -> str:
    """Human text form: strings raw, None as "(not set)", the rest JSON."""
    if value is None:
        return "(not set)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _print_config_errors(exc: ConfigError) -> None:
    for detail in exc.details:
        click.echo(f"error: {detail}", err=True)


@config.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def path(as_json: bool) -> None:
    """Show the settings file location."""
    target = resolve_config_path()
    if as_json:
        click.echo(json.dumps({"path": str(target)}, ensure_ascii=False))
    else:
        click.echo(str(target))


@config.command()
@click.argument("key")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def get(key: str, as_json: bool) -> None:
    """Show one setting's effective value (env > file > default)."""
    if key in CREDENTIAL_KEYS:
        click.echo(
            f"error: {key} is credential-shaped and never displayed; read it "
            f"from the environment (IPO_{key.upper()}) instead",
            err=True,
        )
        sys.exit(1)
    try:
        cfg = load_config()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    family = FLAT_KEYS.get(key)
    if family is None:
        click.echo(
            f"error: unknown config key: {key}{suggest_key(key)}; see `ipo config list`",
            err=True,
        )
        sys.exit(1)
    value = getattr(getattr(cfg, family), key)
    if as_json:
        click.echo(
            json.dumps({"key": key, "family": family, "value": value}, ensure_ascii=False)
        )
    else:
        click.echo(_format_value(value))
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: PASS。

- [ ] **Step 5: guide 覆盖抽查**

Run: `python -c "from ipostudio.cli.main import collect_command_docs; docs = collect_command_docs(); print(next(d['help'] for d in docs if d['name'] == 'config'))"`
Expected: 打印 `Read and write settings (subcommands: path, get, set, list).`。

- [ ] **Step 6: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/cli/main.py tests/cli/test_main.py
git commit -m "feat: add ipo config path/get for reading settings"
```

---

### Task 5: `ipo config set`（校验落盘 + env 冲突提醒）

**Files:**
- Modify: `src/ipostudio/cli/main.py`（config 组内新增子命令）
- Test: `tests/cli/test_main.py`（追加）

**Interfaces:**
- Consumes: Task 3 `coerce_value`；既有 `ConfigStore`（策略校验 → 候选副本验证 → 脏键原子写，跨进程锁）、`resolve_config_path`、`FLAT_KEYS`、`_format_value`、`_print_config_errors`。
- Produces: `ipo config set KEY VALUE` → 成功行 `{key} = {value} (saved to {path})`；本 shell 存在 `IPO_<KEY>` 覆盖时先打 warning 行（env 仍赢，直到 unset）；一切拒绝（未知键 / 非法值 / 凭据键 / URL 内嵌凭据 / 基线文件损坏）exit 1 且**不落盘**。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_config_set_validates_saves_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 0, result.output
    assert "server_port = 19000" in result.output
    saved = json.loads(invoke("config", "get", "server_port", "--json").output)
    assert saved["value"] == 19000
    raw = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "server_port = 19000" in raw


def test_config_set_string_value_persists_raw_text(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "ui_theme", "dark")
    assert result.exit_code == 0, result.output
    assert invoke("config", "get", "ui_theme").output.strip() == "dark"


def test_config_set_env_override_warns_but_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_SERVER_PORT", "19999")
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 0, result.output
    assert "warning: IPO_SERVER_PORT is set in this shell" in result.output
    # the shell override still wins until it is unset
    assert invoke("config", "get", "server_port").output.strip() == "19999"


def test_config_set_rejects_invalid_value_without_save(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "server_port", "99999")
    assert result.exit_code == 1
    assert "error:" in result.output
    assert not (tmp_path / "settings.toml").exists()  # rejected: nothing written


def test_config_set_rejects_credential_keys_with_env_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "vllm_api_key", "sk-abc123def456ghi789")
    assert result.exit_code == 1
    assert "IPO_VLLM_API_KEY" in result.output
    assert not (tmp_path / "settings.toml").exists()


def test_config_set_rejects_inline_url_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "proxy_url", "https://Alice:Secret@example.com")
    assert result.exit_code == 1
    assert "environment variable" in result.output


def test_config_set_none_clears_optional_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "set", "local_model_path", "abc").exit_code == 0
    result = invoke("config", "set", "local_model_path", "none")
    assert result.exit_code == 0, result.output
    raw = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "local_model_path" not in raw  # cleared, not written as null


def test_config_set_on_broken_baseline_reports_and_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 1
    assert "bogus_key" in result.output
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k "set" -v`
Expected: FAIL — `No such command 'set'`。

- [ ] **Step 3: 实现**（config 组内追加；main.py 导入更新为 `from ipostudio.conf.loader import CREDENTIAL_KEYS, ConfigError, ConfigStore, coerce_value, load_config, suggest_key`）

```python
@config.command(name="set")
@click.argument("key")
@click.argument("value")
def set_value(key: str, value: str) -> None:
    """Validate and persist one setting; VALUE 'none' clears an optional key."""
    try:
        typed = coerce_value(key, value)
        cfg = load_config()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    store = ConfigStore(resolve_config_path(), cfg)
    try:
        store.set(key, typed)  # policy first, then candidate-copy validation
        saved = store.save()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    env_var = f"IPO_{key.upper()}"
    if env_var in os.environ:
        click.echo(
            f"warning: {env_var} is set in this shell; it overrides the saved "
            f"value until you unset it"
        )
    current = getattr(getattr(cfg, FLAT_KEYS[key]), key)
    click.echo(f"{key} = {_format_value(current)} (saved to {saved})")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: PASS。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/cli/main.py tests/cli/test_main.py
git commit -m "feat: add ipo config set with validation and env-conflict warning"
```

---

### Task 6: `ipo config list`（值 + 来源 + 凭据提示）

**Files:**
- Modify: `src/ipostudio/cli/main.py`（config 组内新增子命令）
- Test: `tests/cli/test_main.py`（追加）

**Interfaces:**
- Consumes: Task 3 `file_key_names`；既有 `FAMILIES`、`FLAT_KEYS`、`CREDENTIAL_KEYS`、`_format_value`、`_print_config_errors`。
- Produces: `ipo config list [--json]` — 文本：首行 `settings: {path}`，按 family 分组（FAMILIES 顺序），两空格缩进的 `key = value`，非默认来源加尾注 `[env IPO_X]` / `[file]`，凭据键恒加 `[credential: set via IPO_X]` 且值掩码（未设 → `(not set)`，已设 → `***`）；JSON：`[{"family","key","value","source","credential"}]` 数组覆盖全部 FLAT_KEYS，凭据 `value` 恒为 `"***"`（未设为 `""`）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`；导入行补 `from ipostudio.conf.schema import FLAT_KEYS`）

```python
def test_config_list_groups_families_and_marks_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "set", "server_port", "19000").exit_code == 0
    monkeypatch.setenv("IPO_UI_THEME", "dark")
    result = invoke("config", "list")
    assert result.exit_code == 0
    assert f"settings: {tmp_path / 'settings.toml'}" in result.output
    assert "inference_engine = llama.cpp" in result.output  # default: unmarked
    assert "server_port = 19000" in result.output and "[file]" in result.output
    assert "ui_theme = dark" in result.output and "[env IPO_UI_THEME]" in result.output


def test_config_list_masks_credential_values_in_text_and_json(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text(
        'config_version = 1\nvllm_api_key = "sk-hand-written"\n', encoding="utf-8"
    )
    result = invoke("config", "list")
    assert result.exit_code == 0
    assert "sk-hand-written" not in result.output
    assert "***" in result.output
    assert "credential: set via IPO_VLLM_API_KEY" in result.output
    payload = json.loads(invoke("config", "list", "--json").output)
    cred = next(row for row in payload if row["key"] == "vllm_api_key")
    assert cred["value"] == "***"
    assert cred["credential"] is True


def test_config_list_json_rows_cover_every_known_key(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("config", "list", "--json").output)
    assert {row["key"] for row in payload} == set(FLAT_KEYS)
    assert all({"family", "key", "value", "source"} <= set(row) for row in payload)


def test_config_list_empty_strings_read_as_not_set(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "list")
    assert "vllm_api_base = (not set)" in result.output  # schema default ""


def test_config_list_on_broken_settings_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "list")
    assert result.exit_code == 1
    assert "bogus_key" in result.output
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k list -v`
Expected: FAIL — `No such command 'list'`。

- [ ] **Step 3: 实现**（config 组内追加；main.py 导入更新为 `from ipostudio.conf.loader import CREDENTIAL_KEYS, ConfigError, ConfigStore, coerce_value, file_key_names, load_config, suggest_key` 与 `from ipostudio.conf.schema import FAMILIES, FLAT_KEYS`）

```python
@config.command(name="list")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def list_keys(as_json: bool) -> None:
    """List every known setting with its effective value and origin."""
    try:
        cfg = load_config()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    config_path = resolve_config_path()
    try:
        explicit = file_key_names(config_path)
    except ConfigError:
        explicit = set()  # file vanished mid-run: source markers degrade to defaults
    rows: list[dict] = []
    for family, model in FAMILIES.items():
        section = getattr(cfg, family)
        for key in model.model_fields:
            env_var = f"IPO_{key.upper()}"
            if key in CREDENTIAL_KEYS:
                source = f"credential: set via {env_var}"
            elif env_var in os.environ:
                source = f"env {env_var}"
            elif key in explicit:
                source = "file"
            else:
                source = "default"
            raw_value = getattr(section, key)
            # credential values are never echoed — masked even in --json
            value = "***" if key in CREDENTIAL_KEYS and raw_value else raw_value
            rows.append(
                {
                    "family": family,
                    "key": key,
                    "value": value,
                    "source": source,
                    "credential": key in CREDENTIAL_KEYS,
                }
            )
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    click.echo(f"settings: {config_path}")
    for family in FAMILIES:
        members = [row for row in rows if row["family"] == family]
        click.echo(family)
        width = max(len(row["key"]) for row in members)
        for row in members:
            display = (
                "(not set)" if row["value"] in ("", None) else _format_value(row["value"])
            )
            marker = "" if row["source"] == "default" else f"  [{row['source']}]"
            click.echo(f"  {row['key']:<{width}} = {display}{marker}")
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: PASS。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/cli/main.py tests/cli/test_main.py
git commit -m "feat: add ipo config list with value origin tracking"
```

---

### Task 7: 裸 `ipo` 首次上手欢迎卡

**Files:**
- Modify: `src/ipostudio/cli/main.py`（组装饰器 + 组回调 + 模块级常量）
- Test: `tests/cli/test_main.py`（追加）

**Interfaces:**
- Consumes: `load_config`（ui_lang，zh/en，损坏时回落 zh——与 guide 同规则）；Task 4–6 的 `ipo config list`、既有 `ipo doctor --fix`/`ipo guide`。
- Produces: 模块级 `WELCOME: dict[str, str]`（zh/en 模板，含 `{version}` 槽位）与 `_welcome_lang() -> str`；组装饰器加 `invoke_without_command=True, no_args_is_help=False`，回调加 `@click.pass_context` 并在 `ctx.invoked_subcommand is None` 时打印欢迎卡（exit 0）。子命令调用永不打印欢迎卡。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_bare_invocation_prints_welcome_card(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke()
    assert result.exit_code == 0
    assert __version__ in result.output
    assert "ipo doctor --fix" in result.output
    assert "ipo config list" in result.output
    assert "ipo guide" in result.output


def test_welcome_card_follows_ui_lang_config(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_UI_LANG", "en")
    result = invoke()
    assert result.exit_code == 0
    assert "Getting started" in result.output


def test_welcome_card_defaults_to_zh_brief(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke()
    assert result.exit_code == 0
    assert "上手三步" in result.output


def test_welcome_card_falls_back_to_zh_on_broken_config(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke()
    assert result.exit_code == 0  # broken config must not break the card
    assert "上手三步" in result.output


def test_global_flags_without_subcommand_still_show_welcome(
    tmp_path, monkeypatch, _restore_bootstrap_env
):
    result = invoke("--data-dir", str(tmp_path))
    assert result.exit_code == 0
    assert "ipo guide" in result.output


def test_subcommand_invocation_never_prints_welcome(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("version")
    assert result.exit_code == 0
    assert "上手三步" not in result.output
    assert "Getting started" not in result.output
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k welcome -v`
Expected: FAIL — 裸调用输出是 click 帮助文本，无 `上手三步`。

- [ ] **Step 3: 实现**

`src/ipostudio/cli/main.py`：`GUIDE_BRIEF` 之后新增模块级常量与助手：

```python
WELCOME: dict[str, str] = {
    "zh": (
        "ipostudio {version} — 本地优先的 AI 工作站（当前为基础版本）\n"
        "\n"
        "上手三步：\n"
        "  ipo doctor --fix    初始化数据目录并完成环境体检\n"
        "  ipo config list     浏览全部配置项\n"
        "  ipo guide           阅读完整命令手册\n"
        "\n"
        "任意命令加 --help 查看用法；机器可读输出加 --json。"
    ),
    "en": (
        "ipostudio {version} — local-first AI workstation (foundation release)\n"
        "\n"
        "Getting started:\n"
        "  ipo doctor --fix    initialize the data directory and verify the environment\n"
        "  ipo config list     browse every setting\n"
        "  ipo guide           read the full command manual\n"
        "\n"
        "Append --help to any command for usage; add --json for machine-readable output."
    ),
}


def _welcome_lang() -> str:
    try:
        return load_config().ui.ui_lang
    except ConfigError:
        return "zh"  # broken config must not break the card (guide's rule)
```

组装饰器与回调改为：

```python
@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    no_args_is_help=False,
    epilog="Docs: docs/ in the repository, or run `ipo guide`.",
)
@click.version_option(__version__, prog_name="ipo")
@click.option("--config", "config_path", type=click.Path(), default=None,
              help="path to settings.toml (overrides IPO_CONFIG)")
@click.option("--data-dir", "data_dir", type=click.Path(), default=None,
              help="data directory (overrides IPO_DATA_DIR)")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, data_dir: str | None) -> None:
    """ipostudio command line interface."""
    _force_utf8_streams()
    # CLI flags translate to the bootstrap env vars before any config load;
    # the env vars remain the underlying mechanism (escape-hatch parity).
    if config_path:
        os.environ["IPO_CONFIG"] = config_path
    if data_dir:
        os.environ["IPO_DATA_DIR"] = data_dir
    if ctx.invoked_subcommand is None:
        click.echo(WELCOME[_welcome_lang()].format(version=__version__))
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: PASS（`--version`/`--help` 由 eager 选项处理，回调不执行，行为不变）。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/cli/main.py tests/cli/test_main.py
git commit -m "feat: show a first-run welcome card on bare ipo"
```

---

### Task 8: 未知命令近邻建议

**Files:**
- Modify: `src/ipostudio/cli/main.py`（新增 `_SuggestingGroup`，组装饰器加 `cls=`）
- Test: `tests/cli/test_main.py`（追加）

**Interfaces:**
- Consumes: Task 3 `suggest_key`（自定义 pool 口径与配置键建议一致）；click 8.1 `Group.resolve_command`。
- Produces: `_SuggestingGroup(click.Group)` — 未知命令报错改写为 `unknown command '{name}'{did-you-mean}; run `ipo --help` to list commands`；**退出码仍为 2**（UsageError 契约保留，只改进消息）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_typo_command_suggests_closest_match():
    result = invoke("docter")
    assert result.exit_code == 2  # usage error contract preserved
    assert "unknown command 'docter'" in result.output
    assert "did you mean 'doctor'?" in result.output
    assert "ipo --help" in result.output


def test_typo_help_is_recovered_too():
    result = invoke("hepl")
    assert result.exit_code == 2
    assert "did you mean 'help'?" in result.output


def test_distant_command_gets_no_suggestion_but_discovery_hint():
    result = invoke("zzznotacommand")
    assert result.exit_code == 2
    assert "unknown command 'zzznotacommand'" in result.output
    assert "did you mean" not in result.output
    assert "ipo --help" in result.output


def test_valid_commands_still_resolve():
    assert invoke("version").exit_code == 0
    assert invoke("help").exit_code == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k "typo or distant" -v`
Expected: FAIL — 输出是 click 原生 `No such command 'docter'.`，无建议。

- [ ] **Step 3: 实现**（`cli` 组定义之前插入）

```python
class _SuggestingGroup(click.Group):
    """Turn unknown-command errors into actionable ones: a near-miss name
    gets a did-you-mean hint, every miss gets the discovery command.  The
    UsageError contract (exit code 2) is preserved — only the message improves."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            name = args[0] if args else ""
            hint = suggest_key(name, pool=self.commands)
            raise click.UsageError(
                f"unknown command {name!r}{hint}; run `ipo --help` to list commands"
            ) from exc
```

组装饰器第一行改为：

```python
@click.group(
    cls=_SuggestingGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
    no_args_is_help=False,
    epilog="Docs: docs/ in the repository, or run `ipo guide`.",
)
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: PASS。

- [ ] **Step 5: 回归 + 提交**

Run: `python -m pytest -q && python -m ruff check src tests`

```bash
git add src/ipostudio/cli/main.py tests/cli/test_main.py
git commit -m "feat: suggest near-miss commands on typos"
```

---

### Task 9: 文档同步（README / CHANGELOG）

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 2/4/5/6/7/8 的成行为（文案以实现为准：`ipo config` 四子命令、总结行、欢迎卡、纠错建议、NO_COLOR）。
- Produces: 面向新用户的 README 上手路径与退出码说明；CHANGELOG 0.1.0 条目更新。

- [ ] **Step 1: 更新 README.md**（替换 Quickstart 与 Configuration 两节，追加 Terminal output 与 Exit codes 小节）

```markdown
## Quickstart
    ipo                        # first-run welcome card
    ipo doctor --fix           # initialize storage + verify the environment
    ipo config list            # browse every setting (env > file > default)
    ipo config set ui_theme dark
    ipo guide                  # full command manual (markdown/text/json)

## Configuration
Settings live at ~/.ipostudio/settings.toml (override with IPO_DATA_DIR or
`ipo --data-dir/--config`). Every key can be overridden via IPO_<KEY> env vars;
read values with `ipo config get KEY`, write them with `ipo config set KEY VALUE`
(validation, atomic write, 'none' clears an optional key). Credential-shaped
keys (API keys) are never persisted or displayed — pass them via the
environment, e.g. IPO_VLLM_API_KEY. See `ipo guide` and
docs/design/architecture.md (ADR-003).

## Terminal output
Human output is colored only on interactive terminals; it degrades to plain
text when piped, when NO_COLOR is set (any non-empty value), or TERM=dumb.
`--json` output is always machine-readable and never styled.

## Exit codes
0 success; 1 check/runtime failure (doctor, config); 2 usage error.
```

- [ ] **Step 2: 更新 CHANGELOG.md**（0.1.0 条目末尾追加一行）

```markdown
- CLI ergonomics: `ipo config` (path/get/set/list) over the existing config
  store, doctor summary line, first-run welcome card on bare `ipo`,
  did-you-mean command suggestions, NO_COLOR-aware presentation layer.
```

- [ ] **Step 3: 冒烟验证**

Run: `python -m pytest tests/cli -q && python -m ruff check src tests`
Expected: PASS（文档改动不碰代码，冒烟即可）。

- [ ] **Step 4: 提交**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document config commands and terminal behaviour in README"
```

---

### Task 10: 对抗用例收尾 + 全量回归 + 推送

**Files:**
- Create: `tests/qa/test_cli_ux_adversarial.py`
- Test: 全量套件

**Interfaces:**
- Consumes: Task 1 `ui`（None 流语义）、Task 4–8 全部成行为。
- Produces: 守卫四条不变量的回归网——`--json` 字节干净、pythonw None 流安全、欢迎卡无样式/坏配置不崩、凭据值永不上屏（含 JSON 通道）。

- [ ] **Step 1: 写对抗测试**

```python
# tests/qa/test_cli_ux_adversarial.py
"""Adversarial cases for the CLI UX layer: machine-readability of --json,
pythonw robustness, welcome-card resilience and credential non-disclosure."""
import json
import sys

from click.testing import CliRunner

from ipostudio.cli import main as cli_main
from ipostudio.cli import ui
from ipostudio.cli.main import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


def test_json_outputs_never_carry_ansi_escapes(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli_main, "use_color", lambda: True)
    cases = (
        ["doctor", "--json"],
        ["version", "--json"],
        ["config", "path", "--json"],
        ["config", "get", "ui_lang", "--json"],
        ["config", "list", "--json"],
    )
    for args in cases:
        result = CliRunner().invoke(cli, args, color=True)
        assert result.exit_code == 0, (args, result.output)
        assert "\x1b[" not in result.output, args  # byte-clean
        json.loads(result.output)  # and parseable


def test_ui_helpers_tolerate_none_streams(monkeypatch):
    # pythonw.exe: streams are None; every presenter degrades, never raises
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert ui.use_color() is False


def test_welcome_card_stays_plain_and_never_crashes(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = CliRunner().invoke(cli, [], color=True)
    assert result.exit_code == 0
    assert "\x1b[" not in result.output  # the card is prose, never styled


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


def test_config_set_masks_credential_values_in_success_line(tmp_path, monkeypatch):
    # store.set rejects credential keys — but if policy ever loosens (P4 store),
    # the success line must still not echo the secret; pin the current behavior.
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "vllm_api_key", "sk-abc123def456ghi789")
    assert result.exit_code == 1
    assert "IPO_VLLM_API_KEY" in result.output  # remediation, not the secret
```

另补一条凭据 JSON 通道守卫（同一文件内）：

```python
def test_config_get_json_never_carries_credential_values(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "vllm_api_key", "--json")
    assert result.exit_code == 1  # refused outright: no value channel exists
    assert "\x1b[" not in result.output
```

- [ ] **Step 2: 运行确认通过/失败归因**

Run: `python -m pytest tests/qa/test_cli_ux_adversarial.py -v`
Expected: PASS（这些都是对已实现行为的守卫；若 RED，说明前序任务实现有漏——回修对应任务而非改测试口径）。

- [ ] **Step 3: 全量回归**

Run: `python -m pytest -q`
Expected: 全绿（既有 117 + 新增 ~50）。

Run: `python -m ruff check src tests`
Expected: 无告警。

- [ ] **Step 4: 提交**

```bash
git add tests/qa/test_cli_ux_adversarial.py
git commit -m "test: add cli ux adversarial suite"
```

- [ ] **Step 5: 推送并确认 CI**

```bash
git push
gh run list --limit 1
```
Expected: 三平台矩阵全绿（Windows 上欢迎卡中文字符由 `_force_utf8_streams` 的 UTF-8 重配置覆盖；CI 捕获流为非 tty，走同一机制）。

---

## Out of scope（后续计划承载）

- §9.11 其余命令（start/server/models/serve/agent/...）：属 P1.5/P2 功能里程碑；本计划的 `ui.py` 助手与错误/退出码契约是它们的强制依赖面。
- 全局崩溃兜底（未捕获异常 → 友好提示 + 日志路径）：等命令面扩大后统一设计。
- Shell 补全安装（`--install-completion` 风格）：click 8 无开箱支持，YAGNI。
- 富 TUI（进度条/交互表单）：等 P2 下载器出现长任务再评估，不预引入依赖。
