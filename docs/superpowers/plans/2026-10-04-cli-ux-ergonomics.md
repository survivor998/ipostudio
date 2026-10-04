<!-- /autoplan restore point: "C:\\Users\\savior\\.gstack\\projects\\ipostudio\\main-autoplan-restore-20261004-143001.md" -->
## Implementation plan
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

**排位裁决（CEO 双声部，2026-10-04）**：本计划是**核心回路计划**（`ipo start/server/models` 最小价值闭环，P1.5/P2）的**前置闸门**——它建立全部未来命令强制继承的呈现/错误/退出码契约。裁决三项：(1) 本计划 10 任务 timebox 执行，不追加任何"顺手"改进；(2) **下一个计划必须是核心回路**（外部声部原始建议为"本轮转向首任务闭环"，经权衡采纳折中：本计划照常落地 + 立即排核心回路——契约先行与本轮改动面小使其机会成本可控）；(3) 若核心回路需求与本计划冲突，以核心回路优先。裸 `ipo` 选择欢迎卡而非完整 help、选择状态标注而非首跑向导：卡片恒定三行 + 箭头标注下一步（Task 7），向导推迟到核心回路落地后随 `ipo start` 一并重评（决策记录，CEO F2a/F5a）。

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
    # FORCE_COLOR is checked FIRST and wins over NO_COLOR (chalk/supports-color
    # convention; "0"/"false" disable, any other non-empty value forces on —
    # ENG F4 + Codex ENG #3: value semantics symmetric with NO_COLOR)
    force = env_vars.get("FORCE_COLOR", "").strip().lower()
    if force:
        return force not in {"0", "false"}
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
- Produces: doctor 文本输出追加**总结行**——失败时 `summary: {passed} passed, {failed} failed ({names}); follow the guidance in the failed checks above, or re-run with --fix to repair storage problems (--json gives full detail)`；修复模式全过时 `summary: {n} passed (repair mode); storage is ready — try `ipo guide` next`；其余 `summary: {n} passed.`。`[PASS]`/`[FAIL]`/`[WARN]` 标记与 `--json` 结构不变。长详情截断规则（既有行为，本任务后由测试钉住）：文本通道 >300 字符截断为 `...(+N chars; use --json)`；`--json` 恒为全文。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`；所需 `json`、`CliRunner`、`cli_main`、`invoke`、`cli` 该文件全部已有，无需新增导入）

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


def test_doctor_truncates_long_details_with_json_pointer(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    long_detail = "x" * 400
    monkeypatch.setattr(
        cli_main, "run_doctor",
        lambda repair: ([cli_main.CheckOutcome("config", False, long_detail)], []),
    )
    result = invoke("doctor")
    assert "(+100 chars; use --json)" in result.output  # text channel truncates
    payload = json.loads(invoke("doctor", "--json").output)
    assert payload["checks"][0]["detail"] == long_detail  # --json always full
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
            # color passthrough: without it click.echo strips the ANSI that
            # paint() added whenever the stream is not a tty, which would
            # silently neutralize FORCE_COLOR end-to-end (Codex ENG #3)
            click.echo(check_line(mark, outcome.name, shown, color=color), color=color)
        for warning in warnings:
            click.echo(check_line("[WARN]", "config", warning, color=color), color=color)
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

- [ ] **Step 1: 写失败测试**（追加到 `tests/conf/test_loader.py`；**扩展**顶部 loader 导入行——在现有 `from ipostudio.conf.loader import ConfigError, ConfigStore, load_config` 中追加 `coerce_value, file_key_names, suggest_key` 三个名字，**不得替换整行**（ENG F2：既有 `ConfigStore`/`load_config` 在本文件被大量裸用，整行替换会 NameError 全文件）；`pytest` 导入已存在）

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


def test_coerce_value_phrases_bool_errors_for_the_cli_not_the_shell():
    # origin accuracy: _coerce_env's default remediation names the shell env
    # var; a CLI set must state the fix for the command line instead, with
    # the CONFIG KEY as origin — never the IPO_ env name (Codex DX #2)
    with pytest.raises(ConfigError) as excinfo:
        coerce_value("auto_start_server", "maybe")
    message = str(excinfo.value)
    assert "auto_start_server: expected a boolean" in message
    assert "true/false/1/0" in message
    assert "environment variable" not in message
    assert "IPO_AUTO_START_SERVER" not in message


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
    disagree about what a value means.  Remediation text is re-phrased for
    the command line: the error origin is the CLI argument, not the shell."""
    if key not in FLAT_KEYS:
        raise ConfigError(
            [f"unknown config key: {key}{suggest_key(key)}; see `ipo config list`"]
        )
    coerced = _coerce_env(
        f"IPO_{key.upper()}", raw, _annotation(FLAT_KEYS[key], key),
        bool_remediation="pass a boolean true/false/1/0 on the command line",
        origin_label=key,
    )
    if isinstance(coerced, list) and any(not isinstance(item, str) for item in coerced):
        # _coerce_env str()-ifies JSON array elements (loader's env-path legacy);
        # a public CLI write surface must reject [null, {...}] instead of
        # silently accepting it as strings (Codex ENG acceptance-b)
        raise ConfigError(
            [f"{key}: JSON array elements must all be strings; got a "
             f"non-string element in {raw!r}; quote every element"]
        )
    return coerced


def file_key_names(path: Path) -> set[str]:
    """Keys explicitly present in the settings file (source tracking)."""
    return set(_read_toml(path))
```

模块导入行补 `Iterable`：`from collections.abc import Iterable, Mapping`；`load_config`/`ConfigStore.set` 内三处 `_suggest(...)` 调用改为 `suggest_key(...)`；`_coerce_env` 增加仅关键字参数 `bool_remediation: str = "fix the environment variable or unset it"` 与 `origin_label: str | None = None`（bool 分支消息用 `origin_label or raw_key` 作主语、用 bool_remediation 作修复动作——loader 自身调用点走默认值，消息不变；`coerce_value` 传 CLI 措辞与配置键主语，来源契约不失真，CEO F3b + Codex DX #2）。注意 `_coerce_env` 的 int/float 分支的 ValueError 仍由 `coerce_value` 的 `try/except ValueError` 包裹归一（JSON 数组分支的非串元素检查在其后）。**同任务顺带（Codex ENG #2 写入边界补全）**：`ConfigStore.save()` 的错误归一边界从"仅 mkdir+写入"扩为**提交前全部**——`self.path.parent.mkdir(...)`、`with _advisory_lock(...)`（os.open 权限失败现在也被捕获）与 `_mkstemp_in(...)` 全部移入 OSError→ConfigError 的归一范围；而 `os.replace` **成功之后**的清理（锁文件 unlink、目录 fsync）保持 best-effort 吞 OSError——提交已生效，此时报错就是在说谎（锁文件残留会让下一次保存等待 5 秒后报锁超时，该场景由 TODO-007 的陈旧锁自愈承接，此处登记依赖）。对应测试：

```python
def test_save_reports_unwritable_parent_as_config_error(tmp_path, monkeypatch):
    # mkdir failure must surface through the error contract, not a raw OSError
    from ipostudio.conf.loader import ConfigStore
    from ipostudio.conf.schema import AppConfig

    store = ConfigStore(tmp_path / "settings.toml", AppConfig())

    def explode(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(type(tmp_path), "mkdir", explode, raising=False)
    with pytest.raises(ConfigError) as excinfo:
        store.save()
    assert "cannot write settings file" in str(excinfo.value)


def test_save_reports_unopenable_lock_as_config_error(tmp_path, monkeypatch):
    # lock-file creation failure (permissions) is also inside the boundary (Codex ENG #2)
    import os as _os

    from ipostudio.conf.loader import ConfigStore
    from ipostudio.conf.schema import AppConfig

    (tmp_path / "settings.toml").write_text("ui_lang = \"zh\"\n", encoding="utf-8")
    store = ConfigStore(tmp_path / "settings.toml", AppConfig())
    real_open = _os.open

    def locked_open(path, flags, *args, **kwargs):
        if str(path).endswith(".lock"):
            raise PermissionError("denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(_os, "open", locked_open)
    with pytest.raises(ConfigError) as excinfo:
        store.save()
    assert "cannot write settings file" in str(excinfo.value)
```

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
  - main.py 导入更新：loader 行改为 `from ipostudio.conf.loader import CREDENTIAL_KEYS, ConfigError, load_config, suggest_key`；新增 `from ipostudio.conf.schema import FLAT_KEYS` 与 `from typing import Any`；paths 行**仓库现状**为 `from ipostudio.conf.paths import ensure_layout, resolve_data_dir, resolve_db_path`（不含 resolve_config_path），**改为** `from ipostudio.conf.paths import ensure_layout, resolve_config_path, resolve_data_dir, resolve_db_path`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`；先在 helper 区加入跨 click 版本的输出助手——8.1 默认混流（stderr 已并入 `result.output`，访问 `result.stderr` 抛 ValueError），8.2 起移除 mix_stderr（`result.output` 只含 stdout），凡断言**错误内容**一律走它）

```python
def all_output(result):
    """stdout + stderr across click 8.1/8.2 runner semantics."""
    try:
        return result.output + result.stderr
    except ValueError:  # click 8.1: stderr merged into output already
        return result.output


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


def test_config_get_empty_string_default_reads_not_set(tmp_path, monkeypatch):
    # schema default of vllm_api_base is "": a blank line would be
    # indistinguishable from a broken command (DX F1) — get matches list
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "get", "vllm_api_base").output.strip() == "(not set)"
    payload = json.loads(invoke("config", "get", "vllm_api_base", "--json").output)
    assert payload["value"] == ""  # --json stays raw: machine truth


def test_config_get_json_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("config", "get", "ui_lang", "--json").output)
    assert payload == {"key": "ui_lang", "family": "ui", "value": "zh"}


def test_config_get_unknown_key_exits_1_with_suggestion(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "ui_them")
    assert result.exit_code == 1
    assert "unknown config key" in all_output(result)
    assert "ui_theme" in all_output(result)
    assert "ipo config list" in all_output(result)


def test_config_get_refuses_credential_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "get", "vllm_api_key")
    assert result.exit_code == 1
    assert "IPO_VLLM_API_KEY" in all_output(result)
    assert "never displayed" in all_output(result)


def test_config_get_reports_broken_settings_with_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "get", "server_port")
    assert result.exit_code == 1
    assert "bogus_key" in all_output(result)


def test_config_get_masks_url_credential_values(tmp_path, monkeypatch):
    # read-side guard: load_config accepts env values the write path rejects —
    # a proxied credential must never reach get's text or JSON channel (Codex ENG #1)
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_PROXY_URL", "http://alice:secret@proxy.example.com")
    result = invoke("config", "get", "proxy_url")
    assert result.exit_code == 0
    assert "alice" not in result.output and "secret" not in result.output
    assert "(not set)" not in result.output  # masked, not treated as unset
    assert result.output.strip() == "***"
    payload = json.loads(invoke("config", "get", "proxy_url", "--json").output)
    assert payload["value"] == "***"


def test_config_path_absolutizes_relative_override(tmp_path, monkeypatch, _restore_bootstrap_env):
    # IPO_CONFIG may be relative (cwd-anchored); the display contract is absolute (Codex ENG #6)
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_CONFIG", "relative-settings.toml")
    payload = json.loads(invoke("config", "path", "--json").output)
    assert Path(payload["path"]).is_absolute()
    assert payload["path"].endswith("relative-settings.toml")
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
    """Human text form: None and "" as "(not set)", strings raw, rest JSON.
    "" must not render as a blank line (DX F1) — the text channel matches
    `config list`; `--json` stays raw because "" is the machine truth."""
    if value is None or value == "":
        return "(not set)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _print_config_errors(exc: ConfigError) -> None:
    for detail in exc.details:
        click.echo(f"error: {detail}", err=True)


def _mask_url_credentials(value: Any) -> Any:
    """Mask any value carrying an inline URL credential before it reaches a
    display channel (Codex ENG #1): load_config accepts env/file values the
    write path would reject, so get/list need a READ-side guard mirroring the
    store's value-based policy — name blacklists alone cannot uphold it."""
    if _contains_url_credential(value):
        return "***"
    return value


@config.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def path(as_json: bool) -> None:
    """Show the settings file location."""
    target = resolve_config_path()
    # IPO_CONFIG may legally be relative (cwd-anchored); the display contract
    # is an absolute path, so absolutize for display only (Codex ENG #6)
    absolute = Path(os.path.abspath(target))
    if as_json:
        click.echo(json.dumps({"path": str(absolute)}, ensure_ascii=False))
    else:
        click.echo(str(absolute))


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
    value = _mask_url_credentials(getattr(getattr(cfg, family), key))
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
- Produces: `ipo config set KEY VALUE` → 成功行 `{key} = {value} (saved to {path})`；本 shell 存在 `IPO_<KEY>` 覆盖时先打 warning 行到 **stderr**（DX F7：警告不该污染脚本可用的 stdout；env 仍赢，直到 unset）；一切拒绝（未知键 / 非法值 / 凭据键 / URL 内嵌凭据 / 基线文件损坏 / 父目录不可写）exit 1 且**不落盘**。
- 前置事实（DX F5）：值域由 schema 的 pydantic `Field` 约束执行（如 `server_port` 的 `ge=1, le=65535`，schema.py:26 已核实），ConfigStore.set 在候选副本上触发该验证——拒绝测试的 RED 机制成立，无需新增校验代码。
- 已接受的限制（Codex ENG acceptance-a）：`config set` 前置 `load_config()` 成功——**损坏的 settings.toml 或非法环境覆盖会阻止写入**，CLI 不能用来修复坏文件；修复路径 = 按错误提示手工修正/删除文件（错误消息已含该指引）。此限制登记于本文档与 README，不新增"repair 模式"（scope 纪律）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_config_set_validates_saves_and_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "server_port", "19000")
    assert result.exit_code == 0, result.output
    assert "server_port = 19000" in result.output
    assert f"(saved to {tmp_path / 'settings.toml'})" in result.output  # save() returns Path
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
    assert "warning: IPO_SERVER_PORT is set in this shell" in all_output(result)
    try:
        # click 8.2+: stderr is a separate stream — the warning must be there,
        # and must NOT pollute stdout (DX F7); on 8.1 (merged streams, accessing
        # result.stderr raises ValueError) the isolation is untestable — skip
        assert "warning: IPO_SERVER_PORT" not in result.output
        assert "warning: IPO_SERVER_PORT" in result.stderr
    except ValueError:
        pass
    # the shell override still wins until it is unset
    assert invoke("config", "get", "server_port").output.strip() == "19999"


def test_config_set_rejects_invalid_value_without_save(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "server_port", "99999")
    assert result.exit_code == 1
    assert "error:" in all_output(result)
    assert not (tmp_path / "settings.toml").exists()  # rejected: nothing written


def test_config_set_rejects_credential_keys_with_env_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "vllm_api_key", "sk-abc123def456ghi789")
    assert result.exit_code == 1
    assert "sk-abc123def456ghi789" not in all_output(result)  # secret never echoed
    assert "IPO_VLLM_API_KEY" in all_output(result)
    assert not (tmp_path / "settings.toml").exists()


def test_config_set_rejects_inline_url_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "set", "proxy_url", "https://Alice:Secret@example.com")
    assert result.exit_code == 1
    assert "environment variable" in all_output(result)


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
    assert "bogus_key" in all_output(result)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k "config_set" -v`
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
        # set() 先做策略校验，再在候选副本上验证，并把归一化后的值写回 cfg
        # 的对应 family section（loader.py 的 setattr）——因此下方成功行展示
        # 的就是已保存的归一化值，无需重读文件
        store.set(key, typed)
        saved = store.save()
    except ConfigError as exc:
        _print_config_errors(exc)
        sys.exit(1)
    env_var = f"IPO_{key.upper()}"
    if env_var in os.environ:
        # stderr: a warning must not pollute the machine-facing stdout (DX F7)
        click.echo(
            f"warning: {env_var} is set in this shell; it overrides the saved "
            f"value until you unset it",
            err=True,
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
- Produces: `ipo config list [--json]` — 文本：首行 `settings: {path}`，按 family 分组（FAMILIES 顺序），两空格缩进的 `key = value`，非默认来源加尾注 `[env IPO_X]` / `[file]`，凭据键恒加 `[credential: masked — set via settings file or IPO_X]` 提示（来源标注不得说谎——手写文件的值不是"set via IPO_X"，CEO F3c）且值掩码（未设 → `(not set)`，已设 → `***`）；JSON：`[{"family","key","value","source","credential"}]` 数组覆盖全部 FLAT_KEYS，凭据 `value` 恒为 `"***"`（未设为 `""`）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`；导入行补 `from ipostudio.conf.schema import FLAT_KEYS`）

```python
def test_config_list_groups_families_and_marks_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert invoke("config", "set", "server_port", "19000").exit_code == 0
    monkeypatch.setenv("IPO_UI_THEME", "dark")
    result = invoke("config", "list")
    assert result.exit_code == 0
    assert f"settings: {tmp_path / 'settings.toml'}" in result.output
    # the formatter pads keys to the family max: collapse runs of whitespace
    # before asserting, so the test does not depend on column widths
    flat = " ".join(" ".join(line.split()) for line in result.output.splitlines())
    assert "inference_engine = llama.cpp" in flat  # default: unmarked
    assert "server_port = 19000" in flat and "[file]" in flat
    assert "ui_theme = dark" in flat and "[env IPO_UI_THEME]" in flat


def test_config_list_masks_credential_values_in_text_and_json(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text(
        'config_version = 1\nvllm_api_key = "sk-hand-written"\n', encoding="utf-8"
    )
    result = invoke("config", "list")
    assert result.exit_code == 0
    assert "sk-hand-written" not in result.output
    assert "***" in result.output
    assert "credential: masked — set via settings file or IPO_X" in result.output
    payload = json.loads(invoke("config", "list", "--json").output)
    cred = next(row for row in payload if row["key"] == "vllm_api_key")
    assert cred["value"] == "***"
    assert cred["credential"] is True
    # JSON source is an atomic origin token, not display prose (DX F2)
    assert cred["source"] in {"file", "env IPO_VLLM_API_KEY", "default"}


def test_config_list_unset_credential_reads_empty_in_json(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("config", "list", "--json").output)
    cred = next(row for row in payload if row["key"] == "vllm_api_key")
    assert cred["value"] == ""  # unset: nothing to mask, still no echo path
    assert cred["credential"] is True


def test_config_list_json_rows_cover_every_known_key(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("config", "list", "--json").output)
    assert {row["key"] for row in payload} == set(FLAT_KEYS)
    assert all({"family", "key", "value", "source"} <= set(row) for row in payload)


def test_config_list_empty_strings_read_as_not_set(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("config", "list")
    flat = " ".join(" ".join(line.split()) for line in result.output.splitlines())
    assert "vllm_api_base = (not set)" in flat  # schema default ""


def test_config_list_on_broken_settings_exits_1(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("config", "list")
    assert result.exit_code == 1
    assert "bogus_key" in all_output(result)
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
    # accepted race (Codex ENG #4): load_config and file_key_names read the
    # file twice; a concurrent `config set` between the reads could pair a
    # fresh value with a stale source tag.  Atomic writes keep every single
    # read self-consistent, the worst case is a cosmetic mislabel, and the
    # single-user CLI makes the window microseconds — two-read simplicity is
    # kept over a data-layer load_with_sources() refactor (P5/P3)
    rows: list[dict] = []
    for family, model in FAMILIES.items():
        section = getattr(cfg, family)
        for key in model.model_fields:
            env_var = f"IPO_{key.upper()}"
            if key in CREDENTIAL_KEYS:
                # JSON source stays an atomic origin token (DX F2): the
                # `credential: true` flag carries masking, and the long
                # human label is text-channel only
                if env_var in os.environ:
                    source = f"env {env_var}"
                elif key in explicit:
                    source = "file"
                else:
                    source = "default"
            elif env_var in os.environ:
                source = f"env {env_var}"
            elif key in explicit:
                source = "file"
            else:
                source = "default"
            raw_value = getattr(section, key)
            # credential values are never echoed — masked even in --json
            value = "***" if key in CREDENTIAL_KEYS and raw_value else raw_value
            # read-side URL-credential guard: mirror the write policy (Codex ENG #1)
            value = _mask_url_credentials(value)
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
        # default=0: the invariant "every family is non-empty" is currently
        # true but implicit — an empty family must not crash the listing (ENG F9b)
        width = max((len(row["key"]) for row in members), default=0)
        for row in members:
            display = (
                "(not set)" if row["value"] in ("", None) else _format_value(row["value"])
            )
            marker = "" if row["source"] == "default" else f"  [{row['source']}]"
            if row["credential"]:
                # origin must stay truthful: a hand-written file value is NOT
                # "set via IPO_X" (CEO F3c) — the text label states masking
                # plus both possible origins
                marker = "  [credential: masked — set via settings file or IPO_X]"
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
- Consumes: `load_config`（ui_lang，zh/en，损坏时回落 zh——与 guide 同规则）；`resolve_db_path`（main.py 已导入）判初始化状态；Task 4–6 的 `ipo config list`、既有 `ipo doctor --fix`/`ipo guide`。
- 状态语义（ENG F10 + Codex ENG #5 事实澄清）：`_welcome_initialized()` = `resolve_db_path().exists()`——**纯 stat，零磁盘写入**，不运行 doctor、不复用 `_unique_probe`；箭头离开 `doctor --fix` 依赖的事实是"doctor --fix 的修复路径会创建 DB 文件"（main.py `_check_database` repair 分支，已核实）并由 `test_welcome_card_marks_next_step_by_state` 钉住——若未来 repair 推迟迁移，卡片会静默把用户钉在第一步，该测试即红线。
- Produces: 模块级 `WELCOME_STEPS/WELCOME_HEAD/WELCOME_TAIL/WELCOME_ARROW: dict[str, ...]`、`_welcome_lang() -> str`、`_welcome_initialized() -> bool`、`_welcome_text(lang: str, initialized: bool) -> str`；组装饰器加 `invoke_without_command=True, no_args_is_help=False`，回调加 `@click.pass_context` 并在 `ctx.invoked_subcommand is None` 时打印欢迎卡（exit 0）。卡片**状态感知**（CEO F2b）：箭头标注下一步——存储未初始化时标注 `ipo doctor --fix`（"从这里开始"），已初始化时标注 `ipo guide`；三行恒在、只动箭头（卡片形状稳定，测试与肌肉记忆友好）。子命令调用永不打印欢迎卡。首跑向导明确推迟（决策记录见计划头部排位裁决）。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`；`__version__` 导入与 `_restore_bootstrap_env` fixture 该文件已具备。**ENG F3**：末一个测试引用模块级 `WELCOME_STEPS`——在文件顶部的 `from ipostudio.cli.main import cli` 行扩展为 `from ipostudio.cli.main import WELCOME_STEPS, cli`）

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
    monkeypatch.delenv("IPO_UI_LANG", raising=False)  # ambient env must not flip the card
    monkeypatch.delenv("IPO_CONFIG", raising=False)
    result = invoke()
    assert result.exit_code == 0
    assert "上手三步" in result.output


def test_welcome_card_falls_back_to_zh_on_broken_config(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("IPO_UI_LANG", raising=False)
    monkeypatch.delenv("IPO_CONFIG", raising=False)
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke()
    assert result.exit_code == 0
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


def test_welcome_card_marks_next_step_by_state(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("IPO_UI_LANG", raising=False)
    monkeypatch.delenv("IPO_CONFIG", raising=False)
    result = invoke()
    doctor_line = next(l for l in result.output.splitlines() if "ipo doctor --fix" in l)
    guide_line = next(l for l in result.output.splitlines() if "ipo guide" in l)
    assert "从这里开始" in doctor_line  # uninitialized: doctor --fix is next
    assert "从这里开始" not in guide_line
    assert invoke("doctor", "--fix").exit_code == 0
    result2 = invoke()
    doctor_line2 = next(l for l in result2.output.splitlines() if "ipo doctor --fix" in l)
    guide_line2 = next(l for l in result2.output.splitlines() if "ipo guide" in l)
    assert "从这里开始" in guide_line2  # initialized: guide is next
    assert "从这里开始" not in doctor_line2


def test_welcome_card_only_references_registered_commands():
    # guard: the card may never point at a command that does not exist
    # (CEO F4a) — the task ordering alone must not be the only guarantee
    for template in WELCOME_STEPS.values():
        for command, _ in template:
            name = command.split()[1]
            assert name in cli.commands, f"welcome card references missing command: {name}"
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/cli/test_main.py -k welcome -v`
Expected: FAIL — 裸调用输出是 click 帮助文本，无 `上手三步`。

- [ ] **Step 3: 实现**

`src/ipostudio/cli/main.py`：`GUIDE_BRIEF` 之后新增模块级常量与助手：

```python
WELCOME_STEPS: dict[str, list[tuple[str, str]]] = {
    "zh": [
        ("ipo doctor --fix", "初始化数据目录并完成环境体检"),
        ("ipo config list", "浏览全部配置项"),
        ("ipo guide", "阅读完整命令手册"),
    ],
    "en": [
        ("ipo doctor --fix", "initialize the data directory and verify the environment"),
        ("ipo config list", "browse every setting"),
        ("ipo guide", "read the full command manual"),
    ],
}
WELCOME_HEAD: dict[str, str] = {
    "zh": "ipostudio {version} — 本地优先的 AI 工作站（当前为基础版本）\n\n上手三步：",
    "en": "ipostudio {version} — local-first AI workstation (foundation release)\n\nGetting started:",
}
WELCOME_TAIL: dict[str, str] = {
    "zh": "任意命令加 --help 查看用法；机器可读输出加 --json。",
    "en": "Append --help to any command for usage; add --json for machine-readable output.",
}
WELCOME_ARROW: dict[str, str] = {"zh": "← 从这里开始", "en": "<- start here"}


def _welcome_lang() -> str:
    try:
        lang = load_config().ui.ui_lang
    except ConfigError:
        return "zh"  # broken config must not break the card (guide's rule)
    return lang if lang in WELCOME_STEPS else "zh"  # enum drift can never KeyError


def _welcome_initialized() -> bool:
    return resolve_db_path().exists()


def _welcome_text(lang: str, initialized: bool) -> str:
    """State-aware first-run card: the arrow marks the next command —
    doctor --fix before storage exists, guide afterwards (CEO F2b).
    The three steps never move; only the arrow does, so the card shape
    stays stable for users and tests alike."""
    lines = [WELCOME_HEAD[lang].format(version=__version__)]
    for command, description in WELCOME_STEPS[lang]:
        is_next = (command == "ipo doctor --fix" and not initialized) or (
            command == "ipo guide" and initialized
        )
        mark = f"  {WELCOME_ARROW[lang]}" if is_next else ""
        lines.append(f"  {command}    {description}{mark}")
    lines.append("")
    lines.append(WELCOME_TAIL[lang])
    return "\n".join(lines)
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
        click.echo(_welcome_text(_welcome_lang(), _welcome_initialized()))
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
- Consumes: Task 3 `suggest_key`（自定义 pool 口径与配置键建议一致）；Task 1 `use_color`；click 8.1 `Group.resolve_command`/`make_context`。
- Produces: `_SuggestingGroup(click.Group)` 两项职责——(1) 未知命令报错改写为 `unknown command '{name}'{did-you-mean}; run `ipo --help` to list commands`，**退出码仍为 2**（UsageError 契约保留，只改进消息）；(2) **颜色门统一**（DX F6）：`make_context` 用 `extra.setdefault("color", use_color())` 建 Context——click 自渲染的 help/usage/错误也遵守 NO_COLOR/tty/FORCE_COLOR 门（eager `--help` 不经过组回调，门必须在建上下文时生效）。
- 前置事实：`help` 已是仓库注册命令（main.py 既有 `@cli.command() def help`），建议池 `self.commands` 天然含它，无需创建。

- [ ] **Step 1: 写失败测试**（追加到 `tests/cli/test_main.py`）

```python
def test_typo_command_suggests_closest_match():
    result = invoke("docter")
    assert result.exit_code == 2  # usage error contract preserved
    assert "unknown command 'docter'" in all_output(result)
    assert "did you mean 'doctor'?" in all_output(result)
    assert "ipo --help" in all_output(result)


def test_typo_help_is_recovered_too():
    result = invoke("hepl")
    assert result.exit_code == 2
    assert "did you mean 'help'?" in all_output(result)


def test_distant_command_gets_no_suggestion_but_discovery_hint():
    result = invoke("zzznotacommand")
    assert result.exit_code == 2
    assert "unknown command 'zzznotacommand'" in all_output(result)
    assert "did you mean" not in all_output(result)
    assert "ipo --help" in all_output(result)


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
    """Turn unknown-command errors into actionable ones and keep every
    click-rendered surface under the presentation color gate.  The UsageError
    contract (exit code 2) is preserved — only the message improves."""

    def make_context(self, info_name, args, parent=None, **extra):
        # eager --help exits during parsing, before any callback runs: the
        # color gate must be applied at context construction (DX F6)
        extra.setdefault("color", use_color())
        return super().make_context(info_name, args, parent=parent, **extra)

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError as exc:
            name = args[0] if args else ""
            hint = suggest_key(name, pool=self.commands)
            # ctx=ctx keeps click's usage block on the rewritten error (ENG F6)
            raise click.UsageError(
                f"unknown command {name!r}{hint}; run `ipo --help` to list commands",
                ctx=ctx,
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

**ENG F7**：`config` 子组同样传 `cls=_SuggestingGroup`（建议池逻辑对 `self.commands` 天然生效）——`ipo config bogus` 与根组获得一致的 did-you-mean 体验：

```python
@cli.group(cls=_SuggestingGroup)
def config() -> None:
    """Read and write settings (subcommands: path, get, set, list)."""
```

**ENG F1（必做——否则既有 QA 套件在 Task 8 变红）**：`tests/qa/test_cli_adversarial.py:93` 断言 `"no such command" in result_cmd.stderr.lower()`，新消息不含该短语。同任务把该断言更新为 `"unknown command"`（契约是有意变更：本任务改写消息正是目标行为；Task 10 Step 2 的"回修任务不改测试口径"规则不适用于此——这是显式的契约迁移，在 Task 8 内完成）。

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
(validation, atomic write, 'none' clears an optional key). Examples:

    ipo config set server_port 19000          # integer
    ipo config set auto_start_server off      # boolean: on/off/true/false
    ipo config set model_dirs '["D:/models", "/data/models"]'   # list (JSON)
    ipo config set local_model_path none      # clear an optional key

Negative numbers need click's `--` separator (e.g. `ipo config set server_temp
-- -0.5`); if a shell environment already overrides a key, saving still works
but the env value wins until you unset it (the command warns on stderr).

Saving scrubs any hand-written credential keys from the file — pass API keys
via the environment instead, e.g. IPO_VLLM_API_KEY. Resetting a non-optional
key to its default: remove the line from settings.toml (`ipo config path`).
See `ipo guide` and docs/design/architecture.md (ADR-003).

## Terminal output
Human output is colored only on interactive terminals; it degrades to plain
text when piped, when NO_COLOR is set (any non-empty value), or TERM=dumb.
FORCE_COLOR forces color on for pagers/CI with VT support. `--json` output is
always machine-readable and never styled.

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
import click
import inspect
import json
import subprocess
import sys

from click.testing import CliRunner

from ipostudio.cli import main as cli_main
from ipostudio.cli import ui
from ipostudio.cli.main import cli


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
    result = invoke("--data-dir", str(tmp_path), "config", "set", "ui_theme", "dark")
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
    import os

    env = dict(
        os.environ,
        IPO_DATA_DIR=str(tmp_path),
        IPO_UI_LANG="zh",  # pin the card language: the parent may export en
        PYTHONIOENCODING="ascii",
    )
    env.pop("IPO_CONFIG", None)  # ambient pointer would override IPO_DATA_DIR
    proc = subprocess.run(
        [sys.executable, "-m", "ipostudio"],
        env=env, capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "上手三步".encode("utf-8") in proc.stdout  # utf-8 reconfigure won
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
- Shell 补全安装：**按 TODO-001 延后（P2 前实现）**，非 YAGNI 拒绝——真实便利但非 P1 目标（2026-10-03 CEO 裁决维持）。
- 非可选键的 CLI 重置（`config set server_port default`）：**延后**——spec §9.12 只要求 path/get/set/list；现路径 = 从 settings.toml 删除该行（`ipo config path` 可发现）；泛化 `none` 为"删除显式键→回默认"是核心回路候选（DX F4 记录）。
- `ipo guide` 递归收集子命令用法与参数表：**延后**——本轮以组 docstring + README 示例覆盖；完整参考生成归核心回路计划（Codex DX #5）。
- `config set --json`：**刻意不加**——写操作的成功确认面向人；写后校验用 `config get --json`（DX minor，记录为决定而非遗漏）。
- 富 TUI（进度条/交互表单）：等 P2 下载器出现长任务再评估，不预引入依赖。


<!-- autoplan-accepted:ceo -->
- 呈现层契约（Task 1）：`ui.use_color/paint/check_line` 为全部未来命令的强制依赖面；机器可读 `--json` 输出永不携带 ANSI；降级触发条件 = 流非 tty / `NO_COLOR` 非空（no-color.org 语义，含 "0"/"false"）/ `TERM=dumb` / 流为 None（pythonw）。验证：tests/cli/test_ui.py 全部用例 + `doctor --json` 在 color=True 与 use_color 强制开启下无 `\x1b[`。
- 退出码契约：成功 0；检查/运行失败 1（doctor、config get/set/list）；用法错误 2（含未知命令——纠错建议仅改消息不改退出码）。验证：test_doctor_fails_nonzero_on_bad_config、test_typo_command_suggests_closest_match 等。
- 错误消息契约：问题 + 出处（文件/环境变量）+ 修复动作；近邻建议 cutoff 0.6 与 loader `_suggest` 同口径（suggest_key 公开化，消息文本不变）。验证：tests/conf/test_loader.py 既有断言不回归。
- 凭据不变量：`CREDENTIAL_KEYS` 永不由 `config set` 落盘（既有 store 策略）、永不被 `config get` 回显（拒绝并指向 IPO_<KEY>）、在 `config list` 文本与 JSON 中一律掩码（已设 `***`，未设 `(not set)`）且来源标注不得失真（`credential: masked — set via settings file or IPO_X`）。验证：test_config_list_masks_credential_values_in_text_and_json、test_config_list_unset_credential_reads_empty_in_json、test_config_get_refuses_credential_keys、QA 通道扫描测试。
- `ipo config` 四子命令（spec §9.12）：path（绝对路径 + --json {path}）、get（env>file>default 生效值；文本 None→"(not set)"、str 原样、其余 json.dumps；--json {key,family,value}）、set（coerce_value→ConfigStore.set→save；env 冲突先打 warning 且 env 仍赢；value 'none' 清空可选键；一切拒绝 exit 1 且不落盘；成功行含 `(saved to {path})`）、list（FAMILIES 分组、来源标注 [env IPO_X]/[file]/默认无标注、凭据恒带 masked 标注；--json 覆盖全部 FLAT_KEYS）。验证：Task 4/5/6 全部测试。
- 来源准确性（CEO F3b）：`coerce_value` 经 `bool_remediation` 参数把 bool 拒绝消息改写为命令行措辞，`config set` 的 coercion 错误文本不出现 "environment variable"；store 策略拒绝（URL 凭据/凭据键）保留其 env 指引措辞（两条路径分别钉住）。验证：test_coerce_value_phrases_bool_errors_for_the_cli_not_the_shell、test_config_set_rejects_inline_url_credentials。
- 欢迎卡（Task 7）：裸 `ipo` 与"仅组级旗标无子命令"时打印，exit 0；zh/en 跟随 ui_lang（load_config 损坏回落 zh，枚举钳制防 KeyError）；**状态感知**（CEO F2b）——箭头标注下一步，未初始化标 `ipo doctor --fix`、已初始化标 `ipo guide`，三行恒不动；卡片引用的命令有注册守卫测试；首跑向导明确推迟（决策记录在计划头部排位裁决）。子命令调用永不打印。引用的三个命令必须已存在——故 Task 4–6 先于 Task 7 执行。验证：Task 7 全部测试 + test_welcome_card_marks_next_step_by_state + test_welcome_card_only_references_registered_commands + test_subcommand_invocation_never_prints_welcome。
- 呈现守卫（CEO F4b/F4c，Task 10）：QA 断言 main.py 源码不直接使用 `click.style`/`click.secho`（全部经 ui.py 降级语义）；`--json` 字节干净由命令注册表 walker 守护（未来新增 --json 命令自动纳入），walker 至少覆盖 version/doctor/config path/config list。验证：test_main_py_never_styles_directly、test_every_json_capable_command_stays_clean。
- 排位（CEO F1）：本计划为核心回路计划（start/server/models 最小闭环，P1.5/P2）的前置闸门；下一计划 = 核心回路；10 任务 timebox 不追加顺手改进；决策记录见计划头部。
- 纠错建议（Task 8）：`_SuggestingGroup.resolve_command` 捕获 UsageError 改写消息，difflib cutoff 0.6 对 self.commands；无近邻时不建议但仍给 `ipo --help` 指引。验证：Task 8 全部测试。
- 任务顺序约束：1（ui）→ 2（doctor）→ 3（loader 助手）→ 4/5/6（config）→ 7（欢迎卡）→ 8（建议）→ 9（文档）→ 10（QA+回归+推送）；每任务 RED→GREEN→全量回归→提交。
- 范围裁决：Shell 补全、崩溃兜底维持既有 TODO-001/002 延后；--color 旗标、NDJSON、doctor 进度、多语言欢迎卡不在范围。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 模式 DX POLISH；persona = 终端优先本地 AI 开发者（README 证据推断）；TTHW 目标 Competitive 2-5 min（工具就绪口径；**首条模型回复验收归核心回路计划**，本计划不宣称）；magical moment = 状态感知箭头卡。
- `get` 文本通道空串 → `(not set)`（与 list 一致），`--json` 保持原值 ""（DX F1）。验证：test_config_get_empty_string_default_reads_not_set。
- `config list` JSON `source` 为原子 origin token（env IPO_X/file/default），凭据掩码语义由 `credential: true` 承载；长掩码标注仅在文本通道（DX F2 + CEO F3c 不失真）。验证：test_config_list_masks_credential_values_in_text_and_json 的 source 断言。
- `use_color` 支持 `FORCE_COLOR`（非空 → True，优先于 NO_COLOR）——颜色逃逸口对称（DX F3）。验证：test_force_color_overrides_no_color。
- `_SuggestingGroup.make_context` 以 `extra.setdefault("color", use_color())` 建 Context：click 自渲染的 help/usage/错误遵守同一颜色门（eager --help 不经回调，门必须在建上下文时生效，DX F6）。验证：test_help_screen_obeys_the_color_gate。
- `config set` 的 env 冲突 warning 走 stderr（stdout 只承载机器可读与数据行，DX F7）。验证：test_config_set_env_override_warns_but_saves 双断言。
- 来源准确闭环：`_coerce_env` 增加 `origin_label`（bool 消息主语 = 配置键，非 IPO_ 环境名）；`ConfigStore.save()` 的 mkdir 移入 try、OSError → ConfigError（写入路径全部过错误契约，Codex DX #2）。验证：test_coerce_value_phrases_bool_errors_for_the_cli_not_the_shell、test_save_reports_unwritable_parent_as_config_error。
- Task 5 前置事实：值域由 schema pydantic Field 约束执行（DX F5，schema.py:26 核实）。
- README 补 config 示例（标量/布尔/列表/none 清空）、凭据清除说明、非可选键重置手动路径、FORCE_COLOR 与终端行为（DX C5/C6）。
- 延后登记（Out-of-scope）：非可选键 CLI 重置、guide 递归参考收集、`config set --json`（刻意不加）。
- 评分（修复后）：Overall DX 7/10（修复前 5/10）；8 维中 Community 5/10（计划外）、其余 6-8/10。
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- Scope Challenge（autoplan 覆盖：never reduce）：复杂度清点 = 3 src（ui.py 新建、main.py、loader.py）+ 4 test（2 新建 2 追加）+ 2 docs，1 个新类（_SuggestingGroup）——结构安排已是最小形态（呈现原语独立成模块、config 组寄宿 main.py 受冷启动约束），结构问题裁决 = 维持原安排；范围 as-is，不削减。
- ENG F1（必做）：Task 8 同步迁移既有 QA 断言 tests/qa/test_cli_adversarial.py:93 `"no such command"` → `"unknown command"`（有意契约变更，在 Task 8 内完成，不受 Task 10"不改测试口径"规则约束）。
- ENG F2（必做）：Task 3 的 test_loader.py 导入行为**扩展**（追加 coerce_value/file_key_names/suggest_key），不得整行替换（既有 ConfigStore/load_config 被裸用）。
- ENG F3（必做）：Task 7 守卫测试的 `WELCOME_STEPS` 需在 test_main.py 导入行扩展 `from ipostudio.cli.main import WELCOME_STEPS, cli`。
- ENG F4 + Codex ENG #3（颜色终裁）：FORCE_COLOR 最先检查且胜过 NO_COLOR；剥空白小写后 "0"/"false" = 禁色，其余非空 = 强制；Task 2 的染色行 echo 必须 `color=color` 透传（否则 click.echo 非 tty 时剥掉 paint 的 ANSI，FORCE_COLOR 端到端失效）。验证：test_force_color_overrides_no_color（5 断言）。
- ENG F5：env 冲突警告的 stderr 隔离断言按 click 版本门控（8.1 混流下 ValueError → skip；8.2+ 断言隔离）。验证：test_config_set_env_override_warns_but_saves。
- ENG F6：改写的 UsageError 带 `ctx=ctx` 重抛，保留 click 用法块。ENG F7：config 子组同样 `cls=_SuggestingGroup`（子组 did-you-mean）。
- ENG F8：**驳回**（reviewer 误报）——截断逻辑真实存在于现 main.py:390-393（本席此前全文读过），"既有行为"表述正确。
- ENG F9：list 的 `width = max(..., default=0)` 防空前空家族；双读竞态（load_config + file_key_names）**接受并注释**（原子写保证单读自洽，最坏 = 瞬时来源标注错配，P5/P3 拒绝 load_with_sources 重构）。
- ENG F10 + Codex ENG #5：Task 7 Interfaces 增补状态语义（`_welcome_initialized` = 纯 stat 零写入，不跑 doctor；箭头翻转依赖 doctor --fix 创建 DB 文件的事实，test_welcome_card_marks_next_step_by_state 为红线）。
- ENG F11：新增组级旗标测试（--data-dir 下 config set 落盘正确）+ README 负数 `--` 分隔与 env 覆盖说明。
- Codex ENG #1（P1，读侧凭据守卫）：`_mask_url_credentials` 以既有 `_contains_url_credential` 在 get/list 的文本与 JSON 通道掩码 URL 凭据值（`IPO_PROXY_URL=http://alice:secret@host` 现会被原样回显）——读侧镜像写侧的按值策略，命名黑名单不足以守卫。验证：test_config_get_masks_url_credential_values。
- Codex ENG #2（P1，save 边界补全）：归一边界扩为提交前全部（mkdir + 锁 os.open + mkstemp 均 OSError→ConfigError）；os.replace 成功后的清理保持 best-effort（提交已生效，报错即说谎；锁残留场景由 TODO-007 承接）。验证：test_save_reports_unwritable_parent_as_config_error、test_save_reports_unopenable_lock_as_config_error。
- Codex ENG acceptance-a（已接受限制）：config set 前置 load_config 成功——坏文件/非法环境阻止写入，修复靠手工改文件；登记于 Task 5 与 README，不加 repair 模式。acceptance-b（采纳）：coerce_value 拒绝 JSON 数组非字符串元素。验证：数组拒绝测试。
- Codex ENG #4 双读竞态：接受（见 F9 行）；#6 `config path` absolutize 显示层（Path(os.path.abspath)，IPO_CONFIG 相对合法）；#7 递归参考收集维持延后（Out-of-scope 既有裁决）。
- TODOS 登记（eng 覆盖授权 auto-write）：TODO-012（非可选键 CLI 重置）、TODO-013（guide 递归参考收集）已写入 TODOS.md。
- 测试计划工件：~/.gstack/projects/ipostudio/savior-main-eng-review-test-plan-20261004-163000.md（供 /qa 与 /qa-only）。
<!-- /autoplan-accepted:eng -->
## Review record

<!-- autoplan-accepted:ceo -->
- 呈现层契约（Task 1）：`ui.use_color/paint/check_line` 为全部未来命令的强制依赖面；机器可读 `--json` 输出永不携带 ANSI；降级触发条件 = 流非 tty / `NO_COLOR` 非空（no-color.org 语义，含 "0"/"false"）/ `TERM=dumb` / 流为 None（pythonw）。验证：tests/cli/test_ui.py 全部用例 + `doctor --json` 在 color=True 与 use_color 强制开启下无 `\x1b[`。
- 退出码契约：成功 0；检查/运行失败 1（doctor、config get/set/list）；用法错误 2（含未知命令——纠错建议仅改消息不改退出码）。验证：test_doctor_fails_nonzero_on_bad_config、test_typo_command_suggests_closest_match 等。
- 错误消息契约：问题 + 出处（文件/环境变量）+ 修复动作；近邻建议 cutoff 0.6 与 loader `_suggest` 同口径（suggest_key 公开化，消息文本不变）。验证：tests/conf/test_loader.py 既有断言不回归。
- 凭据不变量：`CREDENTIAL_KEYS` 永不由 `config set` 落盘（既有 store 策略）、永不被 `config get` 回显（拒绝并指向 IPO_<KEY>）、在 `config list` 文本与 JSON 中一律掩码（已设 `***`，未设 `(not set)`）且来源标注不得失真（`credential: masked — set via settings file or IPO_X`）。验证：test_config_list_masks_credential_values_in_text_and_json、test_config_list_unset_credential_reads_empty_in_json、test_config_get_refuses_credential_keys、QA 通道扫描测试。
- `ipo config` 四子命令（spec §9.12）：path（绝对路径 + --json {path}）、get（env>file>default 生效值；文本 None→"(not set)"、str 原样、其余 json.dumps；--json {key,family,value}）、set（coerce_value→ConfigStore.set→save；env 冲突先打 warning 且 env 仍赢；value 'none' 清空可选键；一切拒绝 exit 1 且不落盘；成功行含 `(saved to {path})`）、list（FAMILIES 分组、来源标注 [env IPO_X]/[file]/默认无标注、凭据恒带 masked 标注；--json 覆盖全部 FLAT_KEYS）。验证：Task 4/5/6 全部测试。
- 来源准确性（CEO F3b）：`coerce_value` 经 `bool_remediation` 参数把 bool 拒绝消息改写为命令行措辞，`config set` 的 coercion 错误文本不出现 "environment variable"；store 策略拒绝（URL 凭据/凭据键）保留其 env 指引措辞（两条路径分别钉住）。验证：test_coerce_value_phrases_bool_errors_for_the_cli_not_the_shell、test_config_set_rejects_inline_url_credentials。
- 欢迎卡（Task 7）：裸 `ipo` 与"仅组级旗标无子命令"时打印，exit 0；zh/en 跟随 ui_lang（load_config 损坏回落 zh，枚举钳制防 KeyError）；**状态感知**（CEO F2b）——箭头标注下一步，未初始化标 `ipo doctor --fix`、已初始化标 `ipo guide`，三行恒不动；卡片引用的命令有注册守卫测试；首跑向导明确推迟（决策记录在计划头部排位裁决）。子命令调用永不打印。引用的三个命令必须已存在——故 Task 4–6 先于 Task 7 执行。验证：Task 7 全部测试 + test_welcome_card_marks_next_step_by_state + test_welcome_card_only_references_registered_commands + test_subcommand_invocation_never_prints_welcome。
- 呈现守卫（CEO F4b/F4c，Task 10）：QA 断言 main.py 源码不直接使用 `click.style`/`click.secho`（全部经 ui.py 降级语义）；`--json` 字节干净由命令注册表 walker 守护（未来新增 --json 命令自动纳入），walker 至少覆盖 version/doctor/config path/config list。验证：test_main_py_never_styles_directly、test_every_json_capable_command_stays_clean。
- 排位（CEO F1）：本计划为核心回路计划（start/server/models 最小闭环，P1.5/P2）的前置闸门；下一计划 = 核心回路；10 任务 timebox 不追加顺手改进；决策记录见计划头部。
- 纠错建议（Task 8）：`_SuggestingGroup.resolve_command` 捕获 UsageError 改写消息，difflib cutoff 0.6 对 self.commands；无近邻时不建议但仍给 `ipo --help` 指引。验证：Task 8 全部测试。
- 任务顺序约束：1（ui）→ 2（doctor）→ 3（loader 助手）→ 4/5/6（config）→ 7（欢迎卡）→ 8（建议）→ 9（文档）→ 10（QA+回归+推送）；每任务 RED→GREEN→全量回归→提交。
- 范围裁决：Shell 补全、崩溃兜底维持既有 TODO-001/002 延后；--color 旗标、NDJSON、doctor 进度、多语言欢迎卡不在范围。
<!-- /autoplan-accepted:ceo -->

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|----------------|-----------|-----------|----------|
| D-CEO-1 | ceo | 模式 = SELECTIVE EXPANSION（autoplan 覆盖，免问询） | Mechanical | — | /autoplan 规定模式覆盖；计划为既有能力补齐 UI，扩展逐项 cherry-pick | — |
| D-CEO-2 | ceo | 6 项扩展提案：2 延后（补全→TODO-001、崩溃兜底→TODO-002，均重复提案）、4 跳过（--color 旗标、NDJSON、doctor 进度、多语言欢迎卡） | Mechanical | P4/P5 | 重复提案维持原裁决；其余无用户诉求且可后加，不随本计划扩散 | 全部纳入本计划 |
| D-CEO-3 | ceo | 无设计文档 → 不阻塞，直接进行标准审查 | Mechanical | P6 | /autoplan 旨在免中间问询；/office-hours 建议在收尾提示一次 | 内联跑 /office-hours |
| D-CEO-4 | ceo | Spec review 修复（loop 第 1 轮 9 项发现）：测试增 all_output 助手（click 8.1/8.2 stderr 语义差异，约 8 项断言在 ≥8.2 会失败）、Task 3/7 补导入与既有 fixture 说明、凭据测试补 secret-不回显断言、`_welcome_lang` 枚举钳制、Task 10 增 ascii 流 subprocess 冒烟、store.set 就地变异注释、help 命令前置事实 | Mechanical | P1/P5 | 4 项为真实跨版本/回归风险；2 项经代码核实为 reviewer 误读（store.set 确实写回 cfg、help 命令已注册）但补注释消除歧义；1 项低成本防御 | 回退 click<8.2 钉死（版本宽容助手更完备且不动依赖） |
| D-CEO-5 | ceo | Spec review 修复（loop 第 2 轮 8 项发现）：Task 2 截断规则入 Interfaces + 截断/全文测试、`(saved to)` 断言补齐、未设凭据 JSON 契约测试、Out-of-scope 补全条目改 TODO-001 延后口径、config list 断言改空白折叠（修掉会误杀正确实现的列宽敏感断言）、`__main__` 前置事实、qa 内复制 all_output（免跨包导入）、None 流测试补 env={} 防环境遮蔽 | Mechanical | P1/P5 | 列宽敏感断言会让正确实现翻车——真实测试缺陷；其余为断言缺口与隔离加固；save() 返回 Path 经 loader.py:331 核实 | 断言改正则（空白折叠更简单直白） |
| D-CEO-6 | ceo | Spec review 修复（loop 第 3 轮，最终轮 1 项发现）：欢迎卡 zh 断言测试补 `IPO_UI_LANG`/`IPO_CONFIG` delenv 隔离；ascii subprocess 冒烟显式 `IPO_UI_LANG=zh` 并剥离 `IPO_CONFIG`（保留 PATH/SYSTEMROOT，不能 env={}）；Task 5 RED 过滤器改 `-k "config_set"` | Mechanical | P1/P5 | 环境变量遮蔽会让三个测试在导出 IPO_UI_LANG=en 的机器上伪失败，且 Step 2 指示会把人引向错误的调试方向；subprocess 需继承系统 env 才能启动 Python | subprocess 用 env={}（Windows 启动 Python 需要 SYSTEMROOT/PATH） |
| D-CEO-7 | ceo | 双声部整合：native 6 项 → F1/F2/F3b/F3c/F4/F5 采纳（排位裁决+状态感知卡+来源准确性+3 守卫+决策留痕），F3a/F3d 拒绝（4 检查数是刻意契约 pin；CI 版本轴记候选）；Codex 8 项 → C1 为 TASTE 留最终门，C2 部分采纳，C4 拒绝（guided PASS 既有裁决不重开），C3/C5/C6/C7/C8 归 gate note/TODO-003/核心回路计划 | Mixed | P1/P2/P4/P5 | native 条件全部在 blast radius 内且 <1d；F3c 属正确性（来源契约）；Codex 重写建议无 native 支持 → 不构成 User Challenge，按 Taste 走门 | 全盘重写为核心回路（native 不支持）；扩 CI click 版本轴（测试已版本宽容，留候选） |
| D-DX-1 | dx | 模式 = DX POLISH；persona 自动推断 = 终端优先本地 AI 开发者；TTHW 目标 = Competitive 2-5 min（工具就绪口径，首条回复验收归核心回路）；magical moment = 状态感知箭头卡（最低成本载体） | Mechanical（autoplan 覆盖） | P5/P6 | dx-phase.md 覆盖规则；README 证据推断 persona；Ollama 基准锚定 Competitive | DX EXPANSION（scope 纪律：核心回路优先） |
| D-DX-2 | dx | 双声部整合：native F1/F2/F3/F5/F6/F7 采纳（空串显示、JSON source 原子 token、FORCE_COLOR、make_context 颜色门、警告走 stderr、前置事实）；Codex #2 采纳（origin_label + save mkdir 归一）；#5 部分（README 示例+凭据清除说明）；F4/#4/#3 拒绝或延后（reset-默认、相对路径、总结口径——均既有裁决或既定设计，记录去向） | Mixed | P1/P2/P5 | 7 项为真实 DX 缺陷（get 空行、prose 入 JSON、逃逸口不对称、eager --help 绕门、stdout 污染、OSError 逃逸、env 主语失真）；拒绝项均有既有裁决或声明设计支撑 | config set --json（刻意不加，已记录）；guide 递归收集（延后核心回路） |
| D-ENG-1 | eng | Scope Challenge（eng 覆盖 never-reduce + 结构问询自动裁决）：10 文件/1 新类/0 新服务，结构维持原安排（ui.py 独立 + config 组寄宿 main.py 冷启动约束）；范围 as-is；FORCE_COLOR 语义取 chalk 惯例 [Layer 1] | Mechanical | P2/P5 | 安排已是最小形态；无更小且保全契约集合的方案 | 削减任务数（eng 明令禁止） |
| D-ENG-2 | eng | 双声部整合：native 11 项 → F1/F2/F3（测试机制破绽，必做）/F4/F5/F6/F7/F9/F10/F11 采纳，F8 驳回（误报：截断真实存在于 main.py:390-393，本席已读原文）；Codex 7+2 项 → #1 读侧凭据掩码（P1）/ #2 save 边界补全（P1）/ #3 颜色顺序矛盾（并入 F4）/ #6 path 绝对化 / acceptance-b 数组拒绝 采纳；#4 双读竞态接受 documented；#5 事实澄清（卡片纯 stat 零写入）；#7 维持既有延后；acceptance-a 登记为已接受限制 | Mixed | P1/P2/P5 | 2 HIGH 是会让既有套件变红/NameError 的计划指令缺陷；Codex #1 是真实泄露路径（load_config 接受写路径拒绝的值）；拒绝/接受项均有代码证据或既有裁决支撑 | load_with_sources 重构（双读竞态最坏是瞬时标注错配，P3 拒绝）；config repair 模式（scope 纪律） |
| D-ENG-3 | eng | TODOS auto-write（eng 覆盖授权）：TODO-012（非可选键 CLI 重置）、TODO-013（guide 递归参考收集）写入 TODOS.md；测试计划工件落盘 ~/.gstack/projects/ipostudio/savior-main-eng-review-test-plan-20261004-163000.md | Mechanical | P1 | eng-phase 覆盖明令 auto-write；TODO-001/002 已在册不重复 | — |
| D-FINAL-1 | gate | Final Approval Gate 未获应答 → 按建议项批准（approve as-is）：排位折中（本计划落地 + 下一计划 = 核心回路）与全部自动裁决生效；用户可随时以 D) Revise 重开（受影响阶段重跑） | Mechanical | P6 | /autoplan 授权免中间问询；计划逐任务提交可逐个 revert，风险有界 | 推翻计划直做核心回路 |

### 0I 时间推演（Temporal Interrogation，SELECTIVE EXPANSION）

- **HOUR 1（地基）**：实现者须知——`invoke_without_command=True` 时组回调先于子命令运行，`ctx.invoked_subcommand` 区分；`ConfigStore.set` 的三段语义（策略→候选副本验证→就地写回 cfg）；`all_output` 存在的理由（click 8.1 混流 / 8.2 分流）。
- **HOUR 2-3（核心逻辑）**：会踩的歧义——`config list` 同键 env+file 并存时 env 赢（source 判定顺序已定）；coerce_value 的 JSON 数组 vs 逗号列表双格式（`[` 前缀分岔）；欢迎卡语言解析顺序（IPO_UI_LANG env → settings.toml → 默认 zh）。
- **HOUR 4-5（集成）**：会惊讶的点——既有 doctor 测试钉住 `[PASS]` 字面量（本计划保持标记不变，测试零改动）；`collect_command_docs` 自动收录 config 组但只列组级参数——docstring 必须自述子命令；CliRunner 的 stderr 语义随 click 大版本变化。
- **HOUR 6+（打磨/测试）**：会希望当初规划好的——QA 对抗层的环境隔离（delenv/显式 env）与 ascii 流 subprocess 冒烟（Windows 下 subprocess 需继承系统 PATH/SYSTEMROOT）。
- 工作量标尺：human 约 2-3 天（含测试）/ CC 约 40-60 分钟（10 任务 × RED→GREEN）。

### CEO Step 0.5 双声部

- **Native（Claude 子代理，in-host）**：APPROVE 附条件——F1 排位/闸门声明（high，已采纳）、F2 状态感知卡+向导决策记录（medium，已采纳）、F3a 检查数硬编码（declined：4 项检查名与数量已被既有 JSON 契约测试钉死，属刻意 pin，新增检查本就该改测试）、F3b coercion 来源失真（已采纳修复）、F3c 凭据标注失真（已采纳修复）、F3d CI 加 click 版本轴（declined：all_output 已使测试版本宽容，CI 轴扩容记 TODO 候选）、F4 三条守卫测试（已采纳）、F5 决策留痕（已采纳）、F6 机会成本（与 F1 同一动作）。
- **Outside（Codex CLI，provider=codex）**：completed（首次尝试失败：68KB 内联提示超出 Windows ARG_MAX → exit 126 "Argument list too long"；按外部声部 30KB 截断规则重试成功）。裁决：`Recommendation: 重写为面向单一目标用户的首次真实任务闭环，并缩减本轮 CLI 装饰与配置暴露范围`——与本计划的**战略分歧**，native 声部不支持重写 → **TASTE，留待最终批准门**。8 点要旨：价值闭环优先（C1）、config list≠上手旅程（C2）、目标用户未选定（C3）、doctor 总结或夸大成功（C4）、schema 过早公共接口化（C5）、凭据上手断点（C6）、无迁移动机假设（C7）、验收缺真实用户度量（C8）。
- 双方**实质一致**处：下一优先级必须是核心回路（native F1 条件 = Codex C1 的折中落地，已写入计划头部排位裁决）。

```
CEO DUAL VOICES — CONSENSUS TABLE:
  Dimension                            Claude            Codex             Consensus
  1. Premises valid?                   多数已用测试钉住   核心前提受挑战    PARTIAL（技术前提 CONFIRMED，战略前提分歧）
  2. Right problem to solve?           正确但排位敏感     应先做价值闭环    DISAGREE → TASTE（最终门）
  3. Scope calibration correct?        SELECTIVE 合适     过度暴露 schema   PARTIAL
  4. Alternatives sufficiently explored? 决策留痕不足→已补  替代未分析      CONFIRMED（双方同指，已补决策记录）
  5. Competitive/market risks covered? 机会成本=真风险     无迁移动机        CONFIRMED（本质同一风险）
  6. 6-month trajectory sound?         需闸门声明→已补    兼容负担提前      PARTIAL
```

### Codex 发见逐条处置（Outside Voice Integration Rule）

| # | 要旨 | 处置 | 依据 |
|---|------|------|------|
| C1 | 先做首任务价值闭环 | **TASTE（最终门）**；本计划内动作 = 排位裁决（已写入计划头） | native 不支持重写；两声部一致点已落地 |
| C2 | config list 不是上手旅程 | 部分采纳：状态感知卡（F2b）把"下一步"显式化；完整旅程归核心回路计划 | 排位裁决第 3 项 |
| C3 | 目标用户未选定 | 留给路线图（gate note）：spec §1.2 用户画像已有，产品级裁决非本计划范围 | P6 用户有上下文 |
| C4 | doctor 总结夸大成功 | declined：总结只报"检查通过数"，guided PASS 语义 2026-10-03 QA 轮已定（只读不可检≠故障） | 既有裁决，不重开 |
| C5 | schema 过早公共接口化 | gate note：§9.12 明令"已知配置列表"；键稳定性属 spec 演进问题（config_version 机制已兜底未知键） | spec 强制 + 前向兼容已设计 |
| C6 | 凭据上手断点 | gate note：环境变量路径已在错误消息中指引；P4 加密存储在册 | 架构既定边界 |
| C7 | 无迁移动机假设 | gate note：与 C1 同源，归核心回路计划论证 | — |
| C8 | 验收缺真实用户度量 | 已有承接：TODO-003（P1 落地后实测 TTHW 对照）；本轮新增净机走查建议→核心回路计划 | TODO-003 |

### Section 1: Architecture Review

```
  现有层                                本计划新增
  ┌─────────────────────────┐          ┌──────────────────────────┐
  │ conf/paths → schema →   │          │ cli/ui.py（呈现原语）     │
  │ loader(ConfigStore)     │◄─────────│  use_color/paint/        │
  │ logs.py（脱敏轮转）      │          │  check_line              │
  │ store/database（WAL）    │          └──────────┬───────────────┘
  └───────────┬─────────────┘                     │唯一被依赖
              │                                    ▼
              │                        ┌──────────────────────────┐
              └───────────────────────►│ cli/main.py               │
       （既有依赖，零改动语义）          │  version/help/guide/doctor│
                                       │  +config(path/get/set/list)│
                                       │  +欢迎卡 +纠错建议         │
                                       └──────────────────────────┘
```
- 组件边界：ui.py 只做呈现（无 IO 决策、无平台分支）；config 命令族零新增持久化逻辑（复用 ConfigStore 的策略→候选验证→脏键原子写→跨进程锁）。数据流四径：config set 的 nil 路径（空 VALUE→click 要求参数报 exit 2）、empty（空串→合法字符串值）、error（ConfigError→stderr+exit 1）、happy（落盘+roundtrip）。状态机：仅 `_dirty` 集合与锁文件（既有，未改）。耦合：main→ui 单向新增；loader 新公共函数被 main 与测试消费——无环。SPOF：无新服务。10x 负载：CLI 一次性进程，不适用。回滚：逐任务提交，git revert 粒度即任务粒度。
- **Findings: 无新增**（双声部发现已在 Step 0.5 处置）。

### Section 2: Error & Rescue Map

```
  CODEPATH                      | WHAT CAN GO WRONG              | EXCEPTION CLASS
  config get/set/list 基线加载   | settings 损坏/未知键           | ConfigError
  coerce_value                  | 未知键/不可转换/bool 非法       | ConfigError
  ConfigStore.set               | 凭据键/URL 内嵌凭据/schema 非法 | ConfigError
  ConfigStore.save              | 锁竞争超时/OSError/写失败       | ConfigError
  _welcome_lang                 | 配置损坏/garbage ui_lang        | ConfigError→zh 钳制
  _SuggestingGroup.resolve      | 未知命令                        | click.UsageError(exit 2)
  doctor 文本渲染                | 未知异常（诊断命令受纳）        | Exception→contained
  ui.use_color                  | stdout=None(pythonw)           | 无异常→False
```
  全部 Y：每条 rescued（exit 1 + 出处 + 修复动作 / exit 2 + 建议 / 降级 zh / 降级无色）。唯一 catch-all 是 doctor 既有 `_contained`（诊断命令不许中途死，错误如实上报环境因素）——**accepted catch-all，有明确豁免理由**。**GAPS: 0 新增。**

### Section 3: Security & Threat Model

- 攻击面：无新端点/无网络/无子进程执行用户输入；新增面 = 配置读写（已有锁+原子写+策略校验）。输入验证：coerce_value + pydantic 双层；超长/unicode 由 TOML 字符串语义承载。凭据：三通道不泄露（set 拒绝/get 拒绝/list 掩码）+ QA 通道扫描 + 来源标注不失真（F3c）。注入：无 SQL/命令/模板拼接（sqlite 全程参数化既有）。审计：config set 的落盘本身即审计轨迹（原子写 + 值可见）。**Findings: 0。**

### Section 4: Data Flow & Interaction Edge Cases

- config set 流：`INPUT(CLI arg) → coerce_value → store.set(策略→候选验证) → save(锁→合并→临时文件→fsync→replace) → OUTPUT(成功行)`；shadow paths：坏基线（exit 1 不落盘）、env 遮蔽（warn+env 赢）、'none' 清空（键从文件移除）。并发：save 已有 O_EXCL 锁 + 5s 超时（TODO-007 登记反馈/自愈，不重开）。交互边界：裸 ipo 重复运行幂等；doctor --fix 重复幂等；doctor 与 config 并发（只读 vs 锁保护写）。**Findings: 0 未处理。**

### Section 5: Code Quality Review

- DRY：suggest_key/coerce_value 单一来源（公开化而非复制）；唯二刻意重复 = all_output 在 qa 内复制（隔离理由已在代码注释声明）。命名：`_welcome_initialized/_welcome_text` 直述行为。复杂度：新增函数全部 ≤5 分支。过/欠工程：walker 守卫替代枚举（F4c）恰好抵掉一份未来欠账。**Findings: 0。**

### Section 6: Test Review

- 覆盖图：呈现原语（单测×8）→ doctor 渲染/总结/截断/颜色/JSON 干净（CliRunner×7）→ config path/get/set/list 全路径+边界（×20+）→ 欢迎卡状态/语言/守卫（×8）→ 纠错建议（×4）→ QA 对抗（walker/样式禁令/凭据通道/ascii 流/pythonw/坏 lang，×8）。2am-Friday 测试 = `test_config_set_masks_credential_values_in_text_and_json`（凭据不泄露）；hostile-QA = 环境遮蔽/列宽/版本语义三轮 spec loop 已排掉；chaos = ascii 流 + pythonw。金字塔：单测为主、1 个 subprocess 集成、0 E2E——匹配 CLI 形态。Flakiness：subprocess 60s 超时、无时间/随机依赖、delenv 隔离。**Findings: 0（三轮 spec loop 已消化）。**

### Section 7: Performance Review

- 裸 `ipo` 新增一次 load_config（TOML 读+pydantic 校验 ≈10-20ms）+ 一次 stat——交互路径可接受；不读配置命令（version/help）零回归。config list 全键渲染 O(键数)≈55，无 IO 放大。N+1/索引/连接池：不适用（无新查询）。**Findings: 1 note——成本已接受，TODO-008（惰性导入）继续追踪冷启动。**

### Section 8: Observability & Debuggability Review

- CLI 的可观测面 = 输出本身：错误一律 stderr + 出处 + 修复动作（可 grep）；doctor --json 供机读诊断；日志子系统（脱敏轮转）承接崩溃后取证（既有）。新代码路径无静默吞错（Section 2 全 Y）。Runbook：doctor 的引导文案即 runbook。**Findings: 0。**

### Section 9: Deployment & Rollout Review

- 纯包内变更：无迁移、无 feature flag、无部署顺序约束。回滚 = revert 对应提交（每任务独立提交）。上线门 = 三平台 CI 矩阵（R1）+ 全量 pytest。发布冒烟 = Task 10 推送后 `gh run list`。**Findings: 0。**

### Section 10: Long-Term Trajectory Review

- 技术债：ui.py 是**还债**（防止 N 个命令各自发明输出）；新增债 ≈ 0（qa 内 all_output 复制已在注释声明理由）。路径依赖：welcome 卡引用命令有注册守卫（F4a）——卡片腐化可测。可逆性 4/5（纯增量命令 + 一处行为变化裸 ipo，单提交可逆）。生态：click 惯例内。12 个月问题：`ui.py` 契约 + 错误契约是新人读 30 秒能懂的规则。**Findings: 0。**

### Section 11: Design & UX Review — SKIPPED (no UI scope)

### 强制产出

**NOT in scope（含裁决去向）**：Shell 补全→TODO-001（延后，P2 前）；崩溃兜底→TODO-002（延后，P21 前）；`--color` 旗标/NDJSON/doctor 进度/多语言欢迎卡→拒绝（无诉求/破坏契约/无长任务/枚举限定）；首跑线性向导→核心回路后随 `ipo start` 重评（决策记录）。

**What already exists（复用而非重建）**：ConfigStore 校验/锁/原子写（config set 全量复用）；`_suggest` difflib 口径（公开化复用）；`_coerce_env` 强转（参数化复用）；GUIDE_BRIEF zh/en 模式（欢迎卡沿用）；`_force_utf8_streams`（ascii 冒烟的被测对象）；click.style（ui.py 唯一使用点）。

**Dream state delta**：现状 = 功能可用但不可发现的 4 命令 CLI → 本计划 = 任何首次接触者可完成"体检→配置→探索"闭环，且未来命令有强制继承的呈现/错误契约 → 12 个月理想 = §9.11 全命令面（start/server/models/serve/agent/memory/launch/backup/logs/install）+ 核心回路 + 补全（TODO-001）+ 崩溃兜底（TODO-002）+ 实测 TTHW 达标（TODO-003）。本计划把"理想的地基"从 P2 提前到 P1 收尾，剩余差距全部在功能里程碑。

**Error & Rescue Registry**：见 Section 2 表（9 codepath 行，0 GAP，1 条 accepted catch-all 含豁免理由）。

**Failure Modes Registry**

```
  CODEPATH              | FAILURE MODE           | RESCUED? | TEST? | USER SEES?            | LOGGED?
  config set 基线损坏    | ConfigError            | Y        | Y     | error:+出处+修复,exit1| stderr
  config set 锁竞争      | 锁超时 ConfigError     | Y        | 既有  | 锁路径+等待指引,exit1 | stderr
  config set 非法值      | 校验拒绝               | Y        | Y     | error:+示例,exit 1    | stderr
  config get 未知键      | 未知键                 | Y        | Y     | 建议+指引,exit 1      | stderr
  config list 凭据泄露   | 值回显                 | Y        | Y     | *** 掩码              | —
  config get 凭据回显    | 值回显                 | Y        | Y     | 拒绝+env 指引,exit 1  | stderr
  欢迎卡坏配置           | ConfigError            | Y        | Y     | zh 回落,exit 0        | —
  欢迎卡 garbage lang    | KeyError 风险          | Y        | Y     | zh 钳制               | —
  未知命令               | UsageError             | Y        | Y     | did-you-mean,exit 2   | stderr
  管道输出 ANSI 泄漏     | 样式污染机器通道       | Y        | Y     | walker 测试守卫       | —
  ascii 流打印中文       | UnicodeEncodeError     | Y        | Y     | utf-8 重配置,exit 0   | —
  pythonw None 流        | AttributeError         | Y        | Y     | 静默降级              | —
```
CRITICAL GAPS: 0（RESCUED/TEST/USER SEES 全 Y）。

**Implementation Tasks**：无新增任务——双声部条件已全部折入既有 Task 2/3/6/7/10 的测试与实现步骤（见排位裁决与 obligations 修订）；本审查不产生独立新任务清单。

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY (CEO)             |
  +====================================================================+
  | Mode selected        | SELECTIVE_EXPANSION                         |
  | System Audit         | 仓库干净（无 stash；TODO 标记 1 处为故意的   |
  |                      |  adversarial 钉子）；近期热点=cli/conf/qa    |
  | Step 0               | SELECTIVE EXPANSION；6 提案：0 采纳/2 延后/  |
  |                      | 4 拒绝；0A-0C 证据齐；0I 已记录              |
  | Section 1  (Arch)    | 0 issues（架构图已出）                       |
  | Section 2  (Errors)  | 12 error paths mapped, 0 GAPS（1 accepted   |
  |                      | catch-all 含豁免理由）                       |
  | Section 3  (Security)| 0 issues, 0 High                            |
  | Section 4  (Data/UX) | 8 edge cases mapped, 0 unhandled            |
  | Section 5  (Quality) | 0 issues（2 处刻意重复已声明理由）           |
  | Section 6  (Tests)   | Diagram produced, 0 gaps                    |
  | Section 7  (Perf)    | 1 note（裸 ipo +10-20ms，接受；TODO-008 追踪）|
  | Section 8  (Observ)  | 0 gaps                                      |
  | Section 9  (Deploy)  | 0 risks                                     |
  | Section 10 (Future)  | Reversibility: 4/5, debt items: 0           |
  | Section 11 (Design)  | SKIPPED (no UI scope)                       |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (6 items)                           |
  | What already exists  | written                                     |
  | Dream state delta    | written                                     |
  | Error/rescue registry| 9 rows, 0 CRITICAL GAPS                     |
  | Failure modes        | 12 total, 0 CRITICAL GAPS                   |
  | TODOS.md updates     | 0 new（TODO-001/002 维持）                  |
  | Scope proposals      | 6 proposed, 0 accepted, 2 deferred          |
  | Spec Review Loop     | 3 轮，18 发现全修复，终轮 8/10               |
  | CEO plan             | written（~/.gstack/.../ceo-plans/）          |
  | Outside voice        | codex completed（首试 E2BIG，30KB 截断重试） |
  | Lake Score           | N/A（coverage 类问题由 spec loop 全量修复）  |
  | Diagrams produced    | 2（架构图、错误路径表）                      |
  | Stale diagrams found | 0                                           |
  | Unresolved decisions | 0（1 项 TASTE 留待最终批准门呈现）           |
  +====================================================================+
```

**Unresolved Decisions**：无未决决策。1 项 TASTE（Codex"重写为核心回路优先"）按 /autoplan 规程留待 Phase 4 最终批准门呈现，native 与 outside 实质一致点（下一计划=核心回路）已作为裁决写入计划。

### DX 审查记录（Phase 2.5，DX POLISH）

<!-- autoplan-accepted:dx -->
- 模式 DX POLISH；persona = 终端优先本地 AI 开发者（README 证据推断）；TTHW 目标 Competitive 2-5 min（工具就绪口径；**首条模型回复验收归核心回路计划**，本计划不宣称）；magical moment = 状态感知箭头卡。
- `get` 文本通道空串 → `(not set)`（与 list 一致），`--json` 保持原值 ""（DX F1）。验证：test_config_get_empty_string_default_reads_not_set。
- `config list` JSON `source` 为原子 origin token（env IPO_X/file/default），凭据掩码语义由 `credential: true` 承载；长掩码标注仅在文本通道（DX F2 + CEO F3c 不失真）。验证：test_config_list_masks_credential_values_in_text_and_json 的 source 断言。
- `use_color` 支持 `FORCE_COLOR`（非空 → True，优先于 NO_COLOR）——颜色逃逸口对称（DX F3）。验证：test_force_color_overrides_no_color。
- `_SuggestingGroup.make_context` 以 `extra.setdefault("color", use_color())` 建 Context：click 自渲染的 help/usage/错误遵守同一颜色门（eager --help 不经回调，门必须在建上下文时生效，DX F6）。验证：test_help_screen_obeys_the_color_gate。
- `config set` 的 env 冲突 warning 走 stderr（stdout 只承载机器可读与数据行，DX F7）。验证：test_config_set_env_override_warns_but_saves 双断言。
- 来源准确闭环：`_coerce_env` 增加 `origin_label`（bool 消息主语 = 配置键，非 IPO_ 环境名）；`ConfigStore.save()` 的 mkdir 移入 try、OSError → ConfigError（写入路径全部过错误契约，Codex DX #2）。验证：test_coerce_value_phrases_bool_errors_for_the_cli_not_the_shell、test_save_reports_unwritable_parent_as_config_error。
- Task 5 前置事实：值域由 schema pydantic Field 约束执行（DX F5，schema.py:26 核实）。
- README 补 config 示例（标量/布尔/列表/none 清空）、凭据清除说明、非可选键重置手动路径、FORCE_COLOR 与终端行为（DX C5/C6）。
- 延后登记（Out-of-scope）：非可选键 CLI 重置、guide 递归参考收集、`config set --json`（刻意不加）。
- 评分（修复后）：Overall DX 7/10（修复前 5/10）；8 维中 Community 5/10（计划外）、其余 6-8/10。
<!-- /autoplan-accepted:dx -->

**Developer Persona Card（自动推断，autoplan 覆盖）**

```
TARGET DEVELOPER PERSONA
========================
Who:       终端优先的本地 AI 应用开发者（Ollama 用户画像）
Context:   想在本地跑模型/推理服务而不上云；用 shell 与脚本组装工作流
Tolerance: 工具就绪 ~5 分钟；得不到清晰下一步就换 Ollama/lmstudio
Expects:   命令名可猜、doctor 式自检、错误自带修复、--json 可脚本化
```

**Developer Empathy Narrative（第一人称，落地后状态）**：我装好 `ipo`，敲裸命令——一张卡告诉我三步，箭头指着"从这里开始"。跑 `ipo doctor --fix`，总结行说存储就绪、下一步 `ipo guide`。我想改端口，`ipo config set server_port 19000` 回我"已保存到哪"；`config list` 让我看到哪些是默认、哪些被我或环境改过。拼错命令时它说"did you mean"。管道/CI 里颜色自动消失、`--json` 干净。真实感受：**工具可发现、可恢复**；但我还没跑到模型——第一次真实推理是下一个计划的事，卡片的"foundation release"没骗我。

**Competitive DX Benchmark**（估计值，标注为估计；来源：[Sider Ollama quickstart](https://sider.ai)、[HN 社区讨论](https://news.ycombinator.com)、[coderlegion 实测](https://coderlegion.com)）

| Tool | Start → result | Time + evidence | DX choice | Source |
|------|----------------|-----------------|-----------|--------|
| Ollama | 安装→CLI 就绪 | ~2-5 min（reported） | 一行安装+服务自启+`ollama run` 合并拉取 | sider.ai 等 |
| Ollama | → 首条模型回复 | 5-15 min（下载主导，estimated） | 同上 | 同上 |
| ipostudio（本计划后） | 安装→工具就绪（doctor/config/guide） | ~2-3 min（estimated） | 卡片箭头+doctor 链+config CLI | 本计划 |
| ipostudio | → 首条模型回复 | **未达**（P1.5 核心回路，验收时点已裁决） | — | 排位裁决 |

时钟口径：人工全新终端、含阅读；与 Ollama 对比的边界 = "工具就绪"（非首条回复），已披露差异。

**TTHW 评估**：目标 Competitive（2-5 min，工具就绪口径）——本计划后预计达标（install -e ≈1 min + 裸 ipo + doctor --fix + config list ≈1-2 min）；**首条模型回复不在本轮验收**（核心回路验收，含模型获取/下载分档计时）。

**Magical Moment Specification**：交付载体 = 状态感知欢迎卡（最低成本达到 Competitive 档，P5）——首次运行箭头指向 `ipo doctor --fix`，运行后箭头移到 `ipo guide`；doctor 修复模式总结行接力引导。魔力点 = "这个工具知道我进行到哪一步"。

**Developer Journey Map（9 阶段）**

```
STAGE            | DEVELOPER DOES                | FRICTION POINTS            | STATUS
1 Discover      | README/仓库                    | 无                          | ok
2 Install       | pip install -e ".[dev]"       | 无（Python≥3.11 一行装）     | ok
3 Hello World   | 裸 ipo → 卡片 → doctor --fix   | 首条回复缺位（核心回路）     | fixed(本轮)+deferred
4 Real Usage    | config set/get/list、guide     | 非可选键重置缺 CLI（已记录） | fixed+deferred
5 Debug         | doctor（--json）、日志脱敏      | 崩溃兜底（TODO-002）         | ok+deferred
6 Upgrade       | config_version 前向兼容        | 降级边界说明（README 已补）   | ok
7 Scale         | 不适用（单机 CLI）              | —                           | N/A
8 Migrate       | settings.toml 平文本可携        | —                           | ok
9 Community     | MIT 公开仓库                   | CONTRIBUTING 缺（计划外）    | deferred
```

**First-Time Developer Confusion Report（要点）**

```
T+0:00  裸 ipo → 卡片：三步清晰，箭头指路（本计划交付）
T+0:30  doctor --fix → "4 passed (repair mode)"，下一步指引明确（本计划交付）
T+1:00  config set → 成功行含路径；env 遮蔽时 stderr 警告解释了 get 的"意外值"（DX F7 修复）
T+2:00  config list 掩码凭据 + env/file/default 标注，来源诚实（CEO F3c 修复）
T+3:00  未决困惑：想 reset 一个端口回默认 → 无 CLI 路径（已在 Out-of-scope 记录 + README 给手动路径）
```

**DX DUAL VOICES — CONSENSUS TABLE**：

```
  Dimension                           Claude  Codex  Consensus
  1. Getting started < 5 min?          工具面可  产品价值不可达  PARTIAL → gate note
  2. API/CLI naming guessable?         是       是            CONFIRMED
  3. Error messages actionable?        修复后是  补齐来源/写入后是  CONFIRMED（修复后）
  4. Docs findable & complete?         部分需示例  部分需示例    CONFIRMED gap（Task 9 补）
  5. Upgrade path safe?                前向兼容好  需恢复说明    PARTIAL（README 补）
  6. Dev environment friction-free?    三平台扎实  三平台扎实    CONFIRMED
```
（单声部关键发现：无。两声部独立同指的修复已折入任务。）

**8 Passes 评分（修复后；修复前→后）**：

```
+====================================================================+
|              DX PLAN REVIEW — SCORECARD                             |
+====================================================================+
| Dimension            | Score   | 修复前  | Trend  |
|----------------------|---------|--------|--------|
| Getting Started      | 7/10    | 5/10   | ↑      |
| API/CLI/SDK          | 8/10    | 6/10   | ↑      |
| Error Messages       | 8/10    | 5/10   | ↑      |
| Documentation        | 7/10    | 5/10   | ↑      |
| Upgrade Path         | 7/10    | 6/10   | ↑      |
| Dev Environment      | 8/10    | 6/10   | ↑      |
| Community            | 5/10    | 5/10   | —（计划外）|
| DX Measurement       | 6/10    | 4/10   | ↑（TODO-003 承接）|
+--------------------------------------------------------------------+
| TTHW                 | ~2-3 min → 目标 Competitive 2-5 min（工具就绪）|
| Competitive Rank     | Competitive（工具面）；首条回复=核心回路验收   |
| Magical Moment       | designed via 状态感知欢迎卡箭头               |
| Product Type         | CLI Tool                                     |
| Mode                 | DX_POLISH（autoplan 覆盖）                    |
| Overall DX           | 7/10    | 5/10   | ↑      |
+====================================================================+
| DX PRINCIPLE COVERAGE                                               |
| Zero Friction      | covered（2 命令就绪）                          |
| Learn by Doing     | covered（config 即改即见）                     |
| Fight Uncertainty  | covered（错误=问题+出处+修复）                  |
| Opinionated + Escape Hatches | covered（NO_COLOR/FORCE_COLOR/--json/IPO_*）|
| Code in Context    | partial（README 示例已补；递归参考延后）        |
| Magical Moments    | covered（状态箭头）                            |
+====================================================================+
```

**DX Implementation Checklist（本计划承诺项）**

```
[ ] 裸 ipo 卡片 + 箭头（Task 7）
[ ] doctor 总结 + 修复引导（Task 2）
[ ] config path/get/set/list 全功能面（Task 4-6）
[ ] 每条错误 = 问题+出处+修复（含 coercion 来源、save 归一）（Task 3/5）
[ ] 凭据不落盘不上屏 + 来源标注不失真（Task 5/6）
[ ] NO_COLOR/FORCE_COLOR/TERM=dumb/管道/pythonw 全降级（Task 1/8）
[ ] click 自渲染面（help/usage）同门（Task 8）
[ ] --json walker 字节干净守卫（Task 10）
[ ] README 快速上手/示例/退出码/终端行为（Task 9）
[ ] 首条模型回复验收 → 核心回路计划（排位裁决，非本计划）
```

**双声部发见处置**：native F1（空串显示）F2（JSON source token）F3（FORCE_COLOR）F5（前置事实）F6（ctx.color 门→make_context 承载）F7（警告走 stderr）→ 全部采纳折入任务；F4（非可选键重置）→ 延后记录（Out-of-scope + README 手动路径）。Codex #1（首条回复验收）→ 排位裁决既有；#2（origin_label + save mkdir 归一）→ 采纳；#3（doctor 总结口径）→ declined（guided PASS 语义既有裁决；截断有 --json 指针）；#4（相对路径测试）→ declined（相对路径 cwd 语义为既定设计）；#5（README 示例 + zh/en 诚实声明）→ 采纳，递归参考延后；#6（凭据清除说明 + 降级验收）→ README 行采纳，降级验收归核心回路候选。


### ENG 审查记录（Phase 3，FULL_REVIEW）

<!-- autoplan-accepted:eng -->
- Scope Challenge（autoplan 覆盖：never reduce）：复杂度清点 = 3 src（ui.py 新建、main.py、loader.py）+ 4 test（2 新建 2 追加）+ 2 docs，1 个新类（_SuggestingGroup）——结构安排已是最小形态（呈现原语独立成模块、config 组寄宿 main.py 受冷启动约束），结构问题裁决 = 维持原安排；范围 as-is，不削减。
- ENG F1（必做）：Task 8 同步迁移既有 QA 断言 tests/qa/test_cli_adversarial.py:93 `"no such command"` → `"unknown command"`（有意契约变更，在 Task 8 内完成，不受 Task 10"不改测试口径"规则约束）。
- ENG F2（必做）：Task 3 的 test_loader.py 导入行为**扩展**（追加 coerce_value/file_key_names/suggest_key），不得整行替换（既有 ConfigStore/load_config 被裸用）。
- ENG F3（必做）：Task 7 守卫测试的 `WELCOME_STEPS` 需在 test_main.py 导入行扩展 `from ipostudio.cli.main import WELCOME_STEPS, cli`。
- ENG F4 + Codex ENG #3（颜色终裁）：FORCE_COLOR 最先检查且胜过 NO_COLOR；剥空白小写后 "0"/"false" = 禁色，其余非空 = 强制；Task 2 的染色行 echo 必须 `color=color` 透传（否则 click.echo 非 tty 时剥掉 paint 的 ANSI，FORCE_COLOR 端到端失效）。验证：test_force_color_overrides_no_color（5 断言）。
- ENG F5：env 冲突警告的 stderr 隔离断言按 click 版本门控（8.1 混流下 ValueError → skip；8.2+ 断言隔离）。验证：test_config_set_env_override_warns_but_saves。
- ENG F6：改写的 UsageError 带 `ctx=ctx` 重抛，保留 click 用法块。ENG F7：config 子组同样 `cls=_SuggestingGroup`（子组 did-you-mean）。
- ENG F8：**驳回**（reviewer 误报）——截断逻辑真实存在于现 main.py:390-393（本席此前全文读过），"既有行为"表述正确。
- ENG F9：list 的 `width = max(..., default=0)` 防空前空家族；双读竞态（load_config + file_key_names）**接受并注释**（原子写保证单读自洽，最坏 = 瞬时来源标注错配，P5/P3 拒绝 load_with_sources 重构）。
- ENG F10 + Codex ENG #5：Task 7 Interfaces 增补状态语义（`_welcome_initialized` = 纯 stat 零写入，不跑 doctor；箭头翻转依赖 doctor --fix 创建 DB 文件的事实，test_welcome_card_marks_next_step_by_state 为红线）。
- ENG F11：新增组级旗标测试（--data-dir 下 config set 落盘正确）+ README 负数 `--` 分隔与 env 覆盖说明。
- Codex ENG #1（P1，读侧凭据守卫）：`_mask_url_credentials` 以既有 `_contains_url_credential` 在 get/list 的文本与 JSON 通道掩码 URL 凭据值（`IPO_PROXY_URL=http://alice:secret@host` 现会被原样回显）——读侧镜像写侧的按值策略，命名黑名单不足以守卫。验证：test_config_get_masks_url_credential_values。
- Codex ENG #2（P1，save 边界补全）：归一边界扩为提交前全部（mkdir + 锁 os.open + mkstemp 均 OSError→ConfigError）；os.replace 成功后的清理保持 best-effort（提交已生效，报错即说谎；锁残留场景由 TODO-007 承接）。验证：test_save_reports_unwritable_parent_as_config_error、test_save_reports_unopenable_lock_as_config_error。
- Codex ENG acceptance-a（已接受限制）：config set 前置 load_config 成功——坏文件/非法环境阻止写入，修复靠手工改文件；登记于 Task 5 与 README，不加 repair 模式。acceptance-b（采纳）：coerce_value 拒绝 JSON 数组非字符串元素。验证：数组拒绝测试。
- Codex ENG #4 双读竞态：接受（见 F9 行）；#6 `config path` absolutize 显示层（Path(os.path.abspath)，IPO_CONFIG 相对合法）；#7 递归参考收集维持延后（Out-of-scope 既有裁决）。
- TODOS 登记（eng 覆盖授权 auto-write）：TODO-012（非可选键 CLI 重置）、TODO-013（guide 递归参考收集）已写入 TODOS.md。
- 测试计划工件：~/.gstack/projects/ipostudio/savior-main-eng-review-test-plan-20261004-163000.md（供 /qa 与 /qa-only）。
<!-- /autoplan-accepted:eng -->

#### Scope Challenge 记录

复杂度清点（eng 覆盖：never reduce，P2）：9-10 个文件、1 个新类、0 个新服务。结构问询（eng 覆盖下自动裁决）：维持原安排——`ui.py` 独立成模块是全部未来命令的强制依赖面（P5 显式），config 组寄宿 main.py 是冷启动约束（TODO-008）下的正确选择；无更小且保全同一契约集合的安排。范围：as-is。Search check：FORCE_COLOR 语义采用 chalk/supports-color 惯例 [Layer 1]；did-you-mean 为 click 生态常见模式 [Layer 1]；无新模式/新基础设施。TODOS 交叉引用：TODO-001/002/007/008 相关（007 承接锁残留、008 约束冷启动），无阻塞。Completeness：shortcut 只省 CC 分钟数 → 全量修复。Distribution：无新工件（纯包内 + 既有 CI 矩阵）。

#### ENG DUAL VOICES — CONSENSUS TABLE

```
  Dimension                           Claude  Codex  Consensus
  1. Architecture sound?               是（薄皮复用） 读侧凭据/写边界有洞→已修  CONFIRMED（修复后）
  2. Test coverage sufficient?         缺 3 处机制性破绽   缺验收条件    CONFIRMED（折入后）
  3. Performance risks addressed?      无新热点          无            CONFIRMED
  4. Security threats covered?         凭据链完整        读侧泄露路径→已修  CONFIRMED（修复后）
  5. Error paths handled?              3 处测试机制会红   save 边界不完整→已修  CONFIRMED（修复后）
  6. Deployment risk manageable?       逐任务提交可回滚   颜色契约未闭合→已修  CONFIRMED（修复后）
```
（native：approve contingent on F1-F3 + F4/F5 决策；outside：REVISE——分歧为程度而非方向，全部发见已裁决折入，无 User Challenge。Codex REVISE 的三个 P1/P2 主张中 #1/#2/#3 采纳、#4 接受 documented、#5 事实澄清（卡片不跑 doctor、零写入）、#6 采纳、#7 维持既有延后。）

#### Section 1: Architecture Review

```
  conf/paths → schema → loader(ConfigStore) ←── 复用（零新建持久化）
        │                │
        ▼                ▼
  cli/ui.py（新，呈现原语）──► cli/main.py（doctor/config/welcome/suggest）
        （FORCE_COLOR → NO_COLOR → TERM=dumb → isatty/None 单一门）
```
- 新增数据流：config set（CLI → coerce_value → store.set 策略/候选验证 → save 锁+原子写）、config get/list（load → 读侧凭据掩码 → 渲染）、welcome（stat db → 渲染卡片）。每径的 nil/empty/error 路径已在计划任务测试中逐条钉住。耦合：main→ui 单向；loader 公共函数被 main/test 消费，无环。SPOF 无新增；生产失败示例 = 并发 save（锁序列化，既有）+ 锁残留（TODO-007）。分布：无新工件。
- **Findings: Codex #1（读侧凭据守卫）、#2（save 边界）采纳；#4（双读竞态）接受 documented；#6（path abspath）采纳；#5 事实澄清。**

#### Section 2: Code Quality Review

- DRY：`_mask_url_credentials` 复用 loader 的 `_contains_url_credential`（单一来源）；suggest_key/coerce_value 公开化而非复制。共享代码甄别（rubric）：`all_output` 在 qa 内复制——跨包隔离理由已声明，两处各 6 行，收益不抵引入共享模块的耦合（拒绝提取）。错误处理缺口：F1/F2/F3（测试机制）、F5/F6（click 语义）折入。命名：`_welcome_initialized/_mask_url_credentials` 直述。复杂度：新增函数 ≤5 分支。ASCII 图：无既有图需更新（docs/design 的是 ADR 文字）。
- **Findings: F3/F2/F1/F6/F7/F9 采纳；F8 驳回（误报，证据：main.py:390-393）。**

#### Section 3: Test Review（含覆盖图）

```
CODE PATHS                                                 USER FLOWS
[+] src/ipostudio/cli/ui.py                                [+] 首次接触旅程
  ├── use_color()                                            ├── [★★★ TESTED] 卡片→doctor --fix→箭头翻转（state 测试）
  │   ├── [★★★ TESTED] tty/NO_COLOR/TERM/dumb/None 流        ├── [★★★ TESTED] 坏配置回落 zh
  │   ├── [★★★ TESTED] FORCE_COLOR 5 断言（F4/Codex#3）      └── [★★  TESTED] 注册守卫（卡片命令存在）
  ├── paint()/check_line() [★★★ TESTED]                    [+] 配置读写旅程
[+] cli/main.py                                              ├── [★★★ TESTED] set→get roundtrip + saved-to 行
  ├── doctor 渲染 [★★★ TESTED] 总结/颜色/截断/JSON 干净      ├── [★★★ TESTED] 拒绝路径 ×5 全不落盘
  ├── config path [★★★ TESTED] 绝对化（Codex#6）             ├── [★★★ TESTED] env 冲突 stderr 警告（版本门控 F5）
  ├── config get [★★★ TESTED] 空串/凭据/URL 掩码（Codex#1）  ├── [GAP→折入] 组级旗标 --data-dir（F11，已加测试）
  ├── config set [★★★ TESTED] 负值 -- 分隔（F11 README）     └── [★★  TESTED] 三平台 CI 冒烟（推送后）
  ├── config list [★★★ TESTED] 分组/掩码/token/宽度默认      [+] 拼写纠错旅程
  └── welcome [★★★ TESTED] 状态/语言/None 流                 ├── [★★★ TESTED] 近邻建议 + exit 2 契约
[+] conf/loader.py                                           └── [GAP→折入] 子组建议（F7 cls）
  ├── suggest_key/coerce_value [★★★ TESTED] 含 origin/数组拒绝
  └── save() 边界 [★★★ TESTED] mkdir/lock（Codex#2）        QA 对抗层 [★★★ TESTED] walker/--json 干净/pythonw/ascii 流
[+] tests/qa/test_cli_adversarial.py:93 [GAP→折入] 契约迁移（F1）
COVERAGE: 24/24 折入后全覆盖 | QUALITY: ★★★:22 ★★:2 | GAPS: 3（全部已折入任务，0 遗留）
```
- 回归铁律：既有 117 测试零容忍——F1/F2/F3 正是"计划指令会打破既有套件"的破绽，全部折入；doctor 标记/退出码/JSON 契约由既有测试钉住，计划保持不变。
- LLM/eval 范围：不适用（无 prompt 变更）。
- 测试计划工件已落盘：`~/.gstack/projects/ipostudio/savior-main-eng-review-test-plan-20261004-163000.md`。

#### Section 4: Performance Review

- 裸 ipo 新增 1 次 TOML 读 + 1 次 stat（≈10-20ms，接受；TODO-008 追踪冷启动）；config list O(键数≈55) + 双读（2×TOML 解析，微秒级，接受已注释）；save 边界扩展零热路径影响；doctor 截断 O(1)。**Findings: 0 新增。**

#### Failure Modes（ENG 增补行）

```
  CODEPATH                | FAILURE MODE              | RESCUED? | TEST? | USER SEES?          | LOGGED?
  config get/list URL凭据 | 值回显（读侧）            | Y(Codex#1)| Y    | *** 掩码            | —
  save() 锁创建权限失败   | 裸 OSError 逃逸           | Y(Codex#2)| Y    | ConfigError,exit 1  | stderr
  save() replace 后清理失败 | 锁残留→下次等 5s        | Y(best-effort+TODO-007) | 部分 | 下次保存锁超时消息 | stderr
  FORCE_COLOR=1 管道      | echo 剥 ANSI 失效         | Y(透传)   | Y    | 颜色正确显示        | —
  相对 IPO_CONFIG         | path 显示相对路径违约     | Y(#6)     | Y    | 绝对路径            | —
  卡片箭头依赖 repair 建 DB | 未来 repair 推迟→钉死   | Y(F10 红线测试) | Y | 箭头停留第一步     | —
```
CRITICAL GAPS: 0（全部 RESCUED=Y 且 TEST=Y）。

#### Implementation Tasks（ENG）

无新增独立任务——全部发见折入既有 Task 1/2/3/4/5/6/7/8/9 的实现与测试步骤（ obligations 逐条列出）；测试计划工件已落盘。

#### Completion Summary（ENG）

```
- Step 0: Scope Challenge — scope accepted as-is（结构维持原安排，eng 覆盖 never-reduce）
- Architecture Review: 6 findings（5 采纳 1 事实澄清）
- Code Quality Review: 7 findings（6 采纳 1 驳回误报）
- Test Review: diagram produced, 3 gaps（全部折入）
- Performance Review: 0 issues
- NOT in scope: written（Out-of-scope 6 项 + 延后登记）
- What already exists: written（ConfigStore/suggest/_coerce_env/_contains_url_credential 全复用）
- TODOS.md updates: 2 items auto-written（TODO-012/013）
- Failure modes: 6 增补行, 0 critical gaps
- Unresolved decisions: 0
- Outside voice: codex completed（REVISE；两次尝试 E2BIG 后 26KB 截断 + 英文 marker 重试成功）
- Parallelization: Sequential implementation, no parallelization opportunity（单一 main.py 载体，任务间强顺序依赖）
- Lake Score: N/A（coverage 类缺口由双声部发见全量折入）
```
