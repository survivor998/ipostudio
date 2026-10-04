## Implementation plan
# P1 核心基础（core-foundation）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 ipostudio 的可安装 Python 包骨架：数据目录布局、完整核心配置系统（规格 §11.1–11.2）、脱敏轮转日志（§5.23）、SQLite 迁移层，以及 `ipo version/help/guide/doctor` CLI（§9.11/9.12 的地基部分）。

**Architecture:** 依据 `docs/design/architecture.md`（ADR-002/003/006/008）。src-layout 单包 `ipostudio`，分层 `conf/`（paths→schema→loader）、`logs.py`、`store/`（sqlite3+WAL+版本化迁移）、`cli/`（click）。无后台进程、无网络——本计划全部可离线测试。

**Tech Stack:** Python ≥3.11；依赖仅 `pydantic>=2.7`（MIT）、`click>=8.1`（BSD）、`tomli-w>=1.0`（MIT，TOML 写出；读取用标准库 `tomllib`）；测试 `pytest`（MIT）；Lint `ruff`（MIT）。

**Spec:** `D:\project\ipostudio\Functional Specification v1.0.md`（重点 §1.2、§5.23 日志、§5.26、§9.11–9.12、§11.1–11.2、§12、§15）与需求附录 `docs/design/requirements-addendum.md`（R1 三平台支持、R2 文档格式——R2 实现落在 P11/P13，本计划仅继承约束）；架构决策 `docs/design/architecture.md`（含 ADR-009/010）；子项目拆分 `docs/design/roadmap.md`。

## Global Constraints

- **三平台支持（需求附录 R1，用户指令 2026-10-03）**：Windows/Linux/macOS 均为一级目标。本计划全部代码与测试不得含 POSIX-only 假设：路径一律 `pathlib`、文件读写显式 `encoding="utf-8"`、原子写用 `os.replace`（三平台原子语义）；Task 9 的 CI 三平台矩阵是支持的执行机制。
- **文档格式（需求附录 R2，用户指令 2026-10-03）**：OOXML/ODF 解析落 P11/P13（ADR-009 `docparse` 注册表）；本计划不引入文档解析，但不得做出与 R2 冲突的设计（如硬编码 §7.3 扩展名清单于本包内——该清单归 P13 的格式注册表所有）。
- 规格强制接口名：CLI 名 `ipo`；环境变量前缀 `IPO_`（§1.2）。其余一切内部命名独立设计（洁净室约束，见 architecture.md §0）。
- 配置默认值逐字取自规格 §11.2：`SERVER_PORT=18080`、`VLLM_PORT=8081`、`SGLANG_PORT=8082`、`MLX_PORT=18010`、`SERVER_CTX_SIZE=8192`、`SERVER_PARALLEL=1`、`SERVER_BATCH_SIZE=256`、`SERVER_UBATCH_SIZE=64`、`SERVER_TEMP=0.2`、`SERVER_TOP_P=0.9`、`SERVER_TOP_K=40`、`SERVER_REPEAT_PENALTY=1.12`、`SERVER_CACHE_TYPE_K/V=q8_0`、`SERVER_AUTO_TUNE=off`、`SERVER_AUTO_TUNE_MIN_CTX=4096`、`SERVER_IDLE_UNLOAD_MINUTES=0`、`SERVER_FALLBACK_MODELS=空有序列表`、`SERVER_LOAD_MODE=auto`、`SERVER_FLASH_ATTN=auto`、`EMBEDDING_PORT=18190`、`EMBEDDING_POOLING=last`、`GATEWAY_ENABLED=on/HOST=回环/PORT=10000/API_KEY=空`、`PROXY_MODE=system/URL=空/ALLOW_LOCAL_NETWORK=on`、下载 `2 文件/4 连接`、`UI_LANG=中文`、`UI_THEME=系统`、`UPDATE_CHANNEL=稳定`、`AUTO_UPDATE=开`、`AUTO_START_SERVER=开`。
- 配置系统行为（§11.1）：GUI/CLI 语义一致；已知枚举与范围校验；**未知键拒绝**；配置保存必须原子写。
- 日志（§5.23/§15）：轮转约 2 MB；凭据脱敏；崩溃后磁盘记录仍可被 CLI 读取。
- CLI（§9.11）：失败非零退出；`--json` 输出机器可读。
- **许可证状态（用户 2026-10-03 裁决）**：仓库暂私有、无 LICENSE；不得发布到公共分发包索引；公开前 TODO-006 选定。
- **前向兼容范围限定（Eng 审查）**：`config_version` 机制只保证"未知**键**不致命"；未来版本对既有**枚举/字段形状**的演进仍会使旧代码加载失败——升级公告必须区分二者；旧代码写新版本文件时以脏键合并写为安全边界（未识别键原样保留）。
- **CLI 约定（DX 审查，后续所有命令继承）**：机器可读输出一律用 `--json` 标志（`--format` 仅用于 markdown/text **导出**关切）；组级 `--version`、`--config PATH`、`--data-dir PATH` 为通用逃生口（转译为对应 `IPO_*` 环境变量）；错误信息契约 = 问题 + 出处（文件/环境变量）+ 修复动作（+ 建议，如 difflib 近邻键）。
- 平台：Windows（Git Bash）/macOS/Linux 三平台路径均用 `pathlib`；不得写入硬编码 `C:\` 路径。
- 所有测试命令在仓库根 `D:\project\ipostudio` 执行。
- 提交信息用英文 conventional 风格（`feat:`/`test:`/`chore:`），逐步提交，禁止一次性全量提交（洁净室可审计性要求）。

---

### Task 1: 仓库脚手架与包骨架

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`（见 Step 5.5）
- Create: `CHANGELOG.md`（见 Step 5.8）
- Create: `TODOS.md`（延后项登记簿，见 Step 3.5）
（注：不创建 LICENSE——用户裁决暂不开源，公开前经 TODO-006 选定，见 Step 6.5）
- Consumed（已存在于仓库根，随首次提交入库，不由本任务创建）: `CLAUDE.md`
- Create: `src/ipostudio/__init__.py`
- Create: `tests/__init__.py`（空）
- Create: `tests/test_package.py`

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: `ipostudio.__version__: str`（模块级常量，后续 CLI 与网关 `/` 信息端点使用）；pytest 可发现的 `tests/` 目录；`TODOS.md` 延后项登记簿（本审查与后续计划共用）。

- [ ] **Step 1: 初始化 git 仓库**

```bash
cd "D:\project\ipostudio"
git init
```

- [ ] **Step 2: 写 `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ipostudio"
description = "Local-first AI workstation (clean-room implementation)"
requires-python = ">=3.11"
dynamic = ["version"]
dependencies = [
    "click>=8.1",
    "pydantic>=2.7",
    "tomli-w>=1.0",
    "tzdata>=2024.1; sys_platform == 'win32'",
]

[project.scripts]
ipo = "ipostudio.cli.main:cli"

[project.optional-dependencies]
dev = ["pytest>=7.4", "ruff>=0.4"]

[tool.hatch.version]
path = "src/ipostudio/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/ipostudio"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = "-q"

[tool.ruff]
line-length = 100
src = ["src", "tests"]
```

（说明：`dynamic = ["version"]` + `[tool.hatch.version]` 使 `__init__.py` 的 `__version__` 成为唯一版本源，`pyproject` 不再手写版本号；`tzdata` 带 `sys_platform == 'win32'` 标记——Windows 无系统 tz 数据库，P8 调度器的 `zoneinfo` 依赖它（ADR-010），现在引入避免后续跨平台缺口。`[project.scripts]` 声明的 `ipo` 入点在 Task 7 才有目标模块，Task 8 才安装——声明先行的顺序无害。）

- [ ] **Step 3: 写 `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
*.egg-info/
build/
dist/
.venv/
```

- [ ] **Step 3.5: 写 `TODOS.md`（延后项登记簿）**

```markdown
# TODOS

## TODO-001: `ipo completion` shell 补全
- **What:** 为 `ipo` 提供 bash/zsh/fish 补全生成命令。
- **Why:** 降低长命令的记忆成本；click 原生支持，成本低。
- **Pros:** 开箱即用的 CLI 体验提升。
- **Cons:** 又一个需测试与维护的命令。
- **Context:** 2026-10-03 CEO 审查（决策 #5）延后：真实便利但非 P1 目标，宜在 P2 开始前实现（时序约束，非优先级）。click 8 内置 `shell_completion` 模块即可实现。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** P1 Task 7（CLI 骨架）

## TODO-002: CLI 崩溃兜底与 --debug 语义（P21 前）
- **What:** 未预期异常的友好输出（exit 1 + 指引），`--debug` 显示完整回溯。
- **Why:** 当前 doctor 只捕获已知异常类，未知异常裸奔 traceback。
- **Pros:** 诊断体验一致。
- **Cons:** 又一层包装需测试。
- **Context:** 2026-10-03 DX 审查延后；P1 已知路径均有捕获。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** P1 Task 7

## TODO-003: P1 落地后运行 /devex-review 回旋镖
- **What:** 实现完成后实测 TTHW 与计划对照（目标 Competitive 2-5 分钟）。
- **Why:** DX 目标目前是估算，未测量。
- **Context:** 2026-10-03 DX 审查（Pass 8）。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** P1 完成

## TODO-004: 多进程日志文件所有权（P3 前实现）
- **What:** 长驻进程（引擎监管、网关）使用按进程命名的日志文件（如 `ipostudio-gateway.log`），短命 CLI 继续共用 `ipostudio.log`；`ipo logs` 聚合读取。
- **Why:** `RotatingFileHandler` 非多进程安全：并发轮转 Windows 下损坏/丢文件。这是 P3 第二个长驻进程落地前的硬前提（Eng 双声部共识）。
- **决策（Eng 阶段已定，ADR-006 修订）**：按进程分文件，不做单写者进程（复杂度不匹配 P1-P3 阶段）。
- **Effort:** human: S / CC: S
- **Priority:** P1（优先级），时序 P3 前
- **Depends on:** P1 Task 5

## TODO-006: 选定开源许可证（公开仓库前必须）
- **What:** 在 Apache-2.0（审查推荐）与 MIT 之间选定并提交 LICENSE 全文；同步 pyproject 元数据。
- **Why:** 用户 2026-10-03 裁决：仓库暂私有、暂不选许可证；公开发布/分发前的硬前提（洁净室 IP 姿态要求严谨）。
- **Context:** 最终审批门 B2 裁决记录。
- **Effort:** human: S / CC: S
- **Priority:** P1（公开前阻塞项）
- **Depends on:** 用户择日决定

## TODO-005: wheel 构建与仓库外安装冒烟（M0 期间）
- **What:** `python -m build` 产 wheel，在仓库外 venv 安装并跑 `ipo doctor --json`（验证 SQL 迁移资源打包）。
- **Why:** editable 安装掩盖打包缺陷（Eng Codex #11）；发布可信度前提。
- **Context:** 2026-10-03 Eng 审查延后至 M0（与分发渠道决策同期）。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** M0
```

- [ ] **Step 4: 写包标识 `src/ipostudio/__init__.py`**

```python
"""ipostudio: local-first AI workstation (independent clean-room implementation)."""

__version__ = "0.1.0"
```

- [ ] **Step 5: 写失败测试 `tests/test_package.py`**

```python
import ipostudio


def test_version_is_semver_string():
    parts = ipostudio.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)
```

- [ ] **Step 6: 安装开发依赖并运行测试验证通过**

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_package.py -v
```

Expected: `1 passed`（src-layout 由 `pythonpath=["src"]` 提供）。

- [ ] **Step 5.5: 写 `README.md`（开发者前门，DX 审查 HIGH 发现）**

```markdown
# ipostudio

Local-first AI workstation: models, inference, multimodal apps, agents and
memory in one tool. Clean-room implementation against the functional spec.

Status: P1 foundation (install/config/logging/storage/CLI skeleton). The first
end-to-end model workflow lands at milestone M0' / P1.5 vertical slice (see
docs/design/roadmap.md).

## Requirements
- Python >= 3.11 (Windows / Linux / macOS)

## Install (development)
    python -m venv .venv
    # Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
    python -m pip install -e ".[dev]"

## Run the tests
    python -m pytest -v

## Quickstart
    ipo version
    ipo doctor          # read-only health check
    ipo doctor --fix    # create data layout + initialize storage
    ipo guide           # full command manual (markdown/text/json)

## Configuration
Settings live at ~/.ipostudio/settings.toml (override with IPO_DATA_DIR or
`ipo --data-dir/--config`). Every key can be overridden via IPO_<KEY> env vars.
See `ipo guide` and docs/design/architecture.md (ADR-003).

## Docs
docs/design/ — architecture decisions, roadmap, requirement addenda.
```

- [ ] **Step 5.8: 写 `CHANGELOG.md`**

```markdown
# Changelog

## 0.1.0 (unreleased)
- Initial P1 foundation: package skeleton, config system (spec 11.2),
  rotating redacting logs, SQLite migration layer, `ipo` CLI
  (version/help/guide/doctor), three-platform CI matrix.
```

- [ ] **Step 6.5: 许可证——本任务不创建 LICENSE（用户 2026-10-03 裁决）**

仓库暂不公开、暂不选择开源许可证；公开前必须解决（TODO-006，候选 Apache-2.0（推荐：显式专利授权）/MIT）。在此之前：仓库保持私有，不发布分发包到公共索引。

- [ ] **Step 7: 提交**

```bash
git add pyproject.toml .gitignore README.md CHANGELOG.md CLAUDE.md TODOS.md src/ tests/
git commit -m "chore: project scaffold with src-layout package skeleton"
```

---

### Task 2: 数据目录布局解析

**Files:**
- Create: `src/ipostudio/conf/__init__.py`（空）
- Create: `src/ipostudio/conf/paths.py`
- Test: `tests/conf/__init__.py`（空）、`tests/conf/test_paths.py`

**Interfaces:**
- Consumes: `ipostudio.__version__`（无实际依赖）。
- Produces（后续所有任务与 P2+ 依赖）:
  - `resolve_data_dir(env: Mapping[str, str] | None = None) -> Path` — 环境变量 `IPO_DATA_DIR` 优先，默认 `~/.ipostudio`（仅解析，不创建）。
  - `resolve_config_path(env=None) -> Path` — `IPO_CONFIG` 优先，默认 `<data>/settings.toml`。
  - `resolve_db_path(env=None) -> Path` — `IPO_DB_PATH` 优先，默认 `<data>/data/app.db`。
  - `ensure_layout(data_dir: Path | None = None, env=None) -> Path` — 幂等创建子目录，返回数据目录。
  - 常量 `IPO_SUBDIRS: tuple[str, ...]`、`BOOTSTRAP_ENV: frozenset[str] = {"IPO_DATA_DIR", "IPO_CONFIG", "IPO_DB_PATH"}`（配置加载器据此跳过引导变量）。

- [ ] **Step 1: 写失败测试 `tests/conf/test_paths.py`**

```python
from pathlib import Path

from ipostudio.conf.paths import (
    BOOTSTRAP_ENV,
    IPO_SUBDIRS,
    ensure_layout,
    resolve_config_path,
    resolve_data_dir,
    resolve_db_path,
)


def test_default_data_dir_is_under_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))  # Windows 下 pathlib.Path.home() 优先 USERPROFILE
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert resolve_data_dir(env={}) == tmp_path / ".ipostudio"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path
    assert resolve_config_path() == tmp_path / "settings.toml"
    assert resolve_db_path() == tmp_path / "data" / "app.db"


def test_explicit_config_path_wins(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_CONFIG": str(tmp_path / "other.toml")}
    assert resolve_config_path(env=env) == tmp_path / "other.toml"


def test_ensure_layout_creates_all_subdirs_idempotently(tmp_path):
    first = ensure_layout(tmp_path)
    second = ensure_layout(tmp_path)
    assert first == second == tmp_path
    for sub in IPO_SUBDIRS:
        assert (tmp_path / sub).is_dir(), f"missing subdir: {sub}"


def test_bootstrap_env_contains_path_vars():
    assert BOOTSTRAP_ENV == frozenset({"IPO_DATA_DIR", "IPO_CONFIG", "IPO_DB_PATH"})
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/conf/test_paths.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'ipostudio.conf'`。

- [ ] **Step 3: 实现 `src/ipostudio/conf/paths.py`**

```python
"""Resolve on-disk locations for data, config and database (ADR-003)."""

import os
from collections.abc import Mapping
from pathlib import Path

IPO_SUBDIRS: tuple[str, ...] = (
    "data",
    "logs",
    "downloads",
    "models",
    "media/images",
    "media/video",
    "media/audio",
    "backups",
    "skills",
)

# Environment variables consumed before the config file exists (spec §11.2 first rows).
BOOTSTRAP_ENV: frozenset[str] = frozenset({"IPO_DATA_DIR", "IPO_CONFIG", "IPO_DB_PATH"})


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def resolve_data_dir(env: Mapping[str, str] | None = None) -> Path:
    override = _env(env).get("IPO_DATA_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".ipostudio"


def resolve_config_path(env: Mapping[str, str] | None = None) -> Path:
    override = _env(env).get("IPO_CONFIG", "").strip()
    return Path(override).expanduser() if override else resolve_data_dir(env) / "settings.toml"


def resolve_db_path(env: Mapping[str, str] | None = None) -> Path:
    override = _env(env).get("IPO_DB_PATH", "").strip()
    return Path(override).expanduser() if override else resolve_data_dir(env) / "data" / "app.db"


def ensure_layout(data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    root = data_dir if data_dir is not None else resolve_data_dir(env)
    for sub in IPO_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
```

并创建空的 `src/ipostudio/conf/__init__.py` 与 `tests/conf/__init__.py`。

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/conf/test_paths.py -v`
Expected: `5 passed`。

- [ ] **Step 5: 提交**

```bash
git add src/ipostudio/conf/ tests/conf/
git commit -m "feat: data directory layout and bootstrap path resolution"
```

---

### Task 3: 核心配置模式（§11.2 全部键）

**Files:**
- Create: `src/ipostudio/conf/schema.py`
- Test: `tests/conf/test_schema.py`

**Interfaces:**
- Consumes: 无。
- Produces（Task 4 加载器与 P3/P4 等后续计划依赖）:
  - `AppConfig`（pydantic 聚合模型）及族模型 `GeneralConfig / ServerTuning / EngineExtras / EmbeddingConfig / GatewayConfig / NetworkConfig / DownloadsConfig / UiConfig / UpdateConfig / LogConfig`——字段名 = 规格 §11.2 键的小写蛇形形式（如 `server_ctx_size`），**全部 `extra="forbid"`**。
  - `FAMILIES: dict[str, type[BaseModel]]`（族名→模型）；`FLAT_KEYS: dict[str, str]`（字段名→族名，全局唯一性由构建时断言保证）。
  - 注意：规格表中 `IPO_DATA_DIR/IPO_DB_PATH/IPO_DOWNLOAD_FILES/IPO_DOWNLOAD_PARTS` 以环境变量形式给出；对应**配置键**为引导变量（Task 2）与 `download_files/download_parts`。

- [ ] **Step 1: 写失败测试 `tests/conf/test_schema.py`**

```python
import pytest
from pydantic import ValidationError

from ipostudio.conf.schema import FLAT_KEYS, AppConfig


# Single source of truth for spec §11.2 default conformance: add a row when a
# key is added; the test derives from this table (CEO review: scattered
# verbatim assertions rot on every spec edit).
SPEC_DEFAULTS = {
    ("general", "server_mode"): "local",
    ("general", "inference_engine"): "llama.cpp",
    ("general", "server_host"): "127.0.0.1",
    ("general", "server_port"): 18080,
    ("general", "vllm_port"): 8081,
    ("general", "sglang_port"): 8082,
    ("general", "mlx_port"): 18010,
    ("general", "auto_start_server"): True,
    ("tuning", "server_ctx_size"): 8192,
    ("tuning", "server_parallel"): 1,
    ("tuning", "server_batch_size"): 256,
    ("tuning", "server_ubatch_size"): 64,
    ("tuning", "server_temp"): 0.2,
    ("tuning", "server_top_p"): 0.9,
    ("tuning", "server_top_k"): 40,
    ("tuning", "server_repeat_penalty"): 1.12,
    ("tuning", "server_cache_type_k"): "q8_0",
    ("tuning", "server_cache_type_v"): "q8_0",
    ("tuning", "server_auto_tune"): False,
    ("tuning", "server_auto_tune_min_ctx"): 4096,
    ("tuning", "server_idle_unload_minutes"): 0,
    ("tuning", "server_fallback_models"): [],
    ("tuning", "server_load_mode"): "auto",
    ("tuning", "server_flash_attn"): "auto",
    ("embedding", "embedding_port"): 18190,
    ("embedding", "embedding_pooling"): "last",
    ("gateway", "gateway_enabled"): True,
    ("gateway", "gateway_host"): "127.0.0.1",
    ("gateway", "gateway_port"): 10000,
    ("gateway", "gateway_api_key"): "",
    ("network", "proxy_mode"): "system",
    ("network", "proxy_url"): "",
    ("network", "proxy_allow_local_network"): True,
    ("downloads", "download_files"): 2,
    ("downloads", "download_parts"): 4,
    ("ui", "ui_lang"): "zh",
    ("ui", "ui_theme"): "system",
    ("ui", "ui_app_rail_layout"): "default",
    ("updates", "update_channel"): "stable",
    ("updates", "auto_update"): True,
}


def test_defaults_match_spec_11_2():
    cfg = AppConfig()
    for (family, key), expected in SPEC_DEFAULTS.items():
        assert getattr(getattr(cfg, family), key) == expected, f"{family}.{key}"


def test_unknown_key_rejected_in_every_family():
    with pytest.raises(ValidationError):
        AppConfig(general={"no_such_key": 1})
    with pytest.raises(ValidationError):
        AppConfig(tuning={"server_ctx_size": 8192, "mystery": True})


def test_enum_and_range_validation():
    with pytest.raises(ValidationError):
        AppConfig(general={"inference_engine": "tensorrt"})
    with pytest.raises(ValidationError):
        AppConfig(tuning={"server_ctx_size": 32})
    with pytest.raises(ValidationError):
        AppConfig(general={"server_port": 70000})
    with pytest.raises(ValidationError):
        AppConfig(ui={"ui_theme": "solarized"})
    with pytest.raises(ValidationError):
        AppConfig(network={"proxy_mode": "tor"})


def test_flat_keys_unique_and_cover_expected_fields():
    assert len(FLAT_KEYS) == len(set(FLAT_KEYS))
    for must in (
        "server_port", "server_ctx_size", "gateway_api_key", "embedding_pooling",
        "download_files", "ui_lang", "update_channel", "llama_cpp_extra_args",
        "server_fallback_models", "vllm_model_name",
    ):
        assert must in FLAT_KEYS
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/conf/test_schema.py -v`
Expected: FAIL，`No module named 'ipostudio.conf.schema'`。

- [ ] **Step 3: 实现 `src/ipostudio/conf/schema.py`**

```python
"""Typed schema for every core config key in spec §11.2 plus foundation log keys.

File/env key naming rule (ADR-003): config key = lower snake case of the spec key
without the ``IPO_`` prefix; environment form = ``IPO_`` + upper(config key).
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CacheType = Literal["f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GeneralConfig(_Strict):
    # Forward-compatibility marker: files written by a NEWER build (higher
    # config_version) get warn-and-ignore for unknown keys so rollback after
    # auto-update does not brick the config (CEO review consensus).
    config_version: int = Field(default=1, ge=1)
    server_mode: Literal["local", "remote"] = "local"
    inference_engine: Literal["llama.cpp", "vllm", "sglang", "mlx"] = "llama.cpp"
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=18080, ge=1, le=65535)
    vllm_port: int = Field(default=8081, ge=1, le=65535)
    sglang_port: int = Field(default=8082, ge=1, le=65535)
    mlx_port: int = Field(default=18010, ge=1, le=65535)
    local_model_path: Optional[str] = None
    local_model_name: Optional[str] = None
    local_chat_model: Optional[str] = None
    model_dirs: list[str] = Field(default_factory=list)
    auto_start_server: bool = True
    vllm_api_base: str = ""
    vllm_api_key: str = ""
    vllm_model_name: str = ""


class ServerTuning(_Strict):
    server_ctx_size: int = Field(default=8192, ge=128)
    server_parallel: int = Field(default=1, ge=1)
    server_batch_size: int = Field(default=256, ge=1)
    server_ubatch_size: int = Field(default=64, ge=1)
    server_temp: float = Field(default=0.2, ge=0.0, le=2.0)
    server_top_p: float = Field(default=0.9, ge=0.0, le=1.0)
    server_top_k: int = Field(default=40, ge=0)
    server_repeat_penalty: float = Field(default=1.12, ge=1.0, le=2.0)
    server_gpu_layers: Optional[int] = Field(default=None, ge=0)
    server_cache_type_k: CacheType = "q8_0"
    server_cache_type_v: CacheType = "q8_0"
    server_auto_tune: bool = False
    server_auto_tune_min_ctx: int = Field(default=4096, ge=0)
    server_idle_unload_minutes: int = Field(default=0, ge=0)
    server_fallback_models: list[str] = Field(default_factory=list)
    server_load_mode: Literal["auto", "cpu", "gpu"] = "auto"
    server_flash_attn: Literal["auto", "on", "off"] = "auto"


class EngineExtras(_Strict):
    llama_cpp_extra_args: list[str] = Field(default_factory=list)
    vllm_extra_args: list[str] = Field(default_factory=list)
    sglang_extra_args: list[str] = Field(default_factory=list)
    mlx_extra_args: list[str] = Field(default_factory=list)


class EmbeddingConfig(_Strict):
    embedding_port: int = Field(default=18190, ge=1, le=65535)
    embedding_pooling: Literal["last", "mean"] = "last"
    embedding_model: str = ""
    embedding_base: str = ""
    embedding_api_key: str = ""


class GatewayConfig(_Strict):
    gateway_enabled: bool = True
    gateway_host: str = "127.0.0.1"
    gateway_port: int = Field(default=10000, ge=1, le=65535)
    gateway_api_key: str = ""


class NetworkConfig(_Strict):
    proxy_mode: Literal["system", "manual", "direct"] = "system"
    proxy_url: str = ""
    proxy_allow_local_network: bool = True


class DownloadsConfig(_Strict):
    download_files: int = Field(default=2, ge=1, le=16)
    download_parts: int = Field(default=4, ge=1, le=16)


class UiConfig(_Strict):
    ui_lang: Literal["zh", "en"] = "zh"
    ui_theme: Literal["light", "dark", "system"] = "system"
    ui_app_rail_layout: str = "default"


class UpdateConfig(_Strict):
    update_channel: Literal["stable", "beta"] = "stable"
    auto_update: bool = True


class LogConfig(_Strict):
    """Foundation-owned keys (spec §5.23/§15 behaviour; key names are our own design)."""

    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_json: bool = False
    log_max_bytes: int = Field(default=2_000_000, ge=64_000)
    log_backups: int = Field(default=5, ge=1, le=50)


class AppConfig(_Strict):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    tuning: ServerTuning = Field(default_factory=ServerTuning)
    engines: EngineExtras = Field(default_factory=EngineExtras)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    downloads: DownloadsConfig = Field(default_factory=DownloadsConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    updates: UpdateConfig = Field(default_factory=UpdateConfig)
    logs: LogConfig = Field(default_factory=LogConfig)


FAMILIES: dict[str, type[BaseModel]] = {
    "general": GeneralConfig,
    "tuning": ServerTuning,
    "engines": EngineExtras,
    "embedding": EmbeddingConfig,
    "gateway": GatewayConfig,
    "network": NetworkConfig,
    "downloads": DownloadsConfig,
    "ui": UiConfig,
    "updates": UpdateConfig,
    "logs": LogConfig,
}


def _build_flat_keys() -> dict[str, str]:
    flat: dict[str, str] = {}
    for family, model in FAMILIES.items():
        for field_name in model.model_fields:
            if field_name in flat:
                raise RuntimeError(f"duplicate config key across families: {field_name}")
            flat[field_name] = family
    return flat


FLAT_KEYS: dict[str, str] = _build_flat_keys()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/conf/test_schema.py -v`
Expected: `4 passed`。

- [ ] **Step 5: 提交**

```bash
git add src/ipostudio/conf/schema.py tests/conf/test_schema.py
git commit -m "feat: typed config schema for all spec 11.2 core keys with strict unknown-key rejection"
```

---

### Task 4: 配置加载器（TOML + `IPO_` 环境覆盖 + 原子保存）

**Files:**
- Create: `src/ipostudio/conf/loader.py`
- Test: `tests/conf/test_loader.py`

**Interfaces:**
- Consumes: `paths.resolve_config_path`、`paths.BOOTSTRAP_ENV`、`schema.FAMILIES/FLAT_KEYS/AppConfig`。
- Produces（CLI doctor、P2+ 全部计划依赖）:
  - `class ConfigError(Exception)` — 属性 `.details: list[str]`（人类可读的键级错误行）。
  - `load_config(env: Mapping[str, str] | None = None) -> AppConfig` — 读 TOML → 应用 `IPO_*` 覆盖 → 分组校验；文件不存在时返回纯默认+环境覆盖结果。
  - `class ConfigStore` — `__init__(self, path: Path, config: AppConfig)`；`save(self) -> Path`（扁平 TOML、临时文件+`os.replace` 原子写、跳过 `None` 值）。P4 的 `serve --port` 写回、P8 调度器等经此保存。

- [ ] **Step 1: 写失败测试 `tests/conf/test_loader.py`**

```python
from pathlib import Path

import pytest

from ipostudio.conf.loader import ConfigError, ConfigStore, load_config


def write_settings(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_file_yields_defaults(tmp_path):
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert cfg.general.server_port == 18080


def test_toml_values_load_and_env_overrides(tmp_path):
    write_settings(tmp_path, 'server_port = 19000\nui_lang = "en"\n')
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path), "IPO_SERVER_PORT": "18111"})
    assert cfg.general.server_port == 18111
    assert cfg.ui.ui_lang == "en"


def test_env_coercion_bool_int_list(tmp_path):
    env = {
        "IPO_DATA_DIR": str(tmp_path),
        "IPO_AUTO_START_SERVER": "false",
        "IPO_SERVER_TOP_K": "7",
        "IPO_SERVER_TEMP": "0.5",
        "IPO_MODEL_DIRS": "/a, /b",
        "IPO_SERVER_FALLBACK_MODELS": "m1,m2",
        "IPO_LOCAL_MODEL_PATH": "none",
    }
    cfg = load_config(env=env)
    assert cfg.general.auto_start_server is False
    assert cfg.tuning.server_top_k == 7
    assert cfg.tuning.server_temp == 0.5
    assert cfg.general.model_dirs == ["/a", "/b"]
    assert cfg.tuning.server_fallback_models == ["m1", "m2"]
    assert cfg.general.local_model_path is None


def test_unknown_toml_key_rejected(tmp_path):
    write_settings(tmp_path, "definitely_not_a_key = 1\n")
    with pytest.raises(ConfigError) as err:
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert any("definitely_not_a_key" in line for line in err.value.details)


def test_unknown_env_key_rejected_but_bootstrap_ok(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_NO_SUCH_THING": "1"}
    with pytest.raises(ConfigError) as err:
        load_config(env=env)
    assert any("IPO_NO_SUCH_THING" in line for line in err.value.details)
    # bootstrap variables themselves never raise
    assert load_config(env={"IPO_DATA_DIR": str(tmp_path), "IPO_CONFIG": "x.toml"}) is not None


def test_invalid_value_reports_field_location(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_SERVER_CTX_SIZE": "32"}
    with pytest.raises(ConfigError) as err:
        load_config(env=env)
    assert any("server_ctx_size" in line for line in err.value.details)


def test_broken_toml_rejected(tmp_path):
    write_settings(tmp_path, "not [valid toml\n")
    with pytest.raises(ConfigError):
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})


def test_store_save_is_atomic_and_roundtrips(tmp_path):
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("server_port", 18222)
    saved = store.save()
    assert saved == tmp_path / "settings.toml"
    again = load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    assert again.general.server_port == 18222
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_store_only_writes_dirty_keys_and_never_credentials(tmp_path):
    write_settings(tmp_path, "server_port = 19000\n")
    write_settings(tmp_path, "server_port = 19000\ngateway_api_key = \"sk-old-file-key\"\n")
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("gateway_port", 10001)
    store.save()
    body = (tmp_path / "settings.toml").read_text(encoding="utf-8")
    assert "server_port = 19000" in body          # untouched key preserved
    assert "gateway_port = 10001" in body          # dirty key written
    assert "sk-old-file-key" not in body           # credentials dropped even if previously in file


def test_store_set_validates_and_rejects_without_mutation(tmp_path):
    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    for attempt in (lambda: store.set("server_port", 70000),          # out of range
                    lambda: store.set("gateway_api_key", "sk-x"),     # credential key
                    lambda: store.set("no_such_key", 1),              # unknown key
                    lambda: store.set("proxy_url", "http://u:p@h")):  # URL credential
        with pytest.raises(ConfigError):
            attempt()
    assert store.config.general.server_port == 18080           # memory untouched
    assert store.config.gateway.gateway_api_key == ""          # secret never landed
    assert store.set("server_port", "18222") is None           # str input normalized
    assert store.config.general.server_port == 18222
    assert isinstance(store.config.general.server_port, int)


def test_newer_config_version_unknown_keys_ignored_with_warning(tmp_path):
    write_settings(tmp_path, "config_version = 99\nfuture_key_xyz = 1\n")
    warnings: list[str] = []
    cfg = load_config(env={"IPO_DATA_DIR": str(tmp_path)}, warnings=warnings)
    assert cfg.general.config_version == 99
    assert any("future_key_xyz" in w for w in warnings)
    assert not hasattr(cfg.general, "future_key_xyz")


def test_unknown_key_error_names_file_and_suggests_fix(tmp_path):
    write_settings(tmp_path, "server_prot = 18111\n")  # typo of server_port
    with pytest.raises(ConfigError) as err:
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})
    joined = "\n".join(err.value.details)
    assert "server_prot" in joined
    assert "server_port" in joined          # difflib suggestion
    assert "settings.toml" in joined        # controlling file named
    assert "remove" in joined.lower() or "fix" in joined.lower()  # remedy clause


def test_unreadable_or_non_utf8_config_is_configerror(tmp_path):
    bad = tmp_path / "settings.toml"
    bad.write_bytes(b"\xff\xfe not utf8")
    with pytest.raises(ConfigError):
        load_config(env={"IPO_DATA_DIR": str(tmp_path)})


def test_env_lists_accept_json_array_encoding(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path),
           "IPO_MODEL_DIRS": '["/a,comma/dir", "/b"]'}
    cfg = load_config(env=env)
    assert cfg.general.model_dirs == ["/a,comma/dir", "/b"]  # comma inside value kept


def test_env_sourced_error_names_env_var_not_file(tmp_path):
    env = {"IPO_DATA_DIR": str(tmp_path), "IPO_SERVER_PORT": "70000"}
    with pytest.raises(ConfigError) as err:
        load_config(env=env)
    joined = "\n".join(err.value.details)
    assert "IPO_SERVER_PORT" in joined


def test_save_failure_cleans_temp_and_raises_configerror(tmp_path, monkeypatch):
    import tomli_w as tomli_w_module

    store = ConfigStore(tmp_path / "settings.toml", load_config(env={"IPO_DATA_DIR": str(tmp_path)}))
    store.set("server_port", 18222)

    def exploding_dump(data, handle):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(tomli_w_module, "dump", exploding_dump)
    with pytest.raises(ConfigError):
        store.save()
    leftovers = list(tmp_path.glob(".settings-*.tmp")) + list(tmp_path.glob("*.lock"))
    assert leftovers == []  # temp AND lock cleaned on failure
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/conf/test_loader.py -v`
Expected: FAIL，`No module named 'ipostudio.conf.loader'`。

- [ ] **Step 3: 实现 `src/ipostudio/conf/loader.py`**

```python
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
from collections.abc import Mapping
from pathlib import Path
from typing import Any, get_args, get_origin, Union

import tomli_w
from pydantic import ValidationError

from ipostudio.conf.paths import BOOTSTRAP_ENV, resolve_config_path
from ipostudio.conf.schema import FAMILIES, FLAT_KEYS, AppConfig

_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


class ConfigError(Exception):
    """Raised for unreadable, unknown or invalid configuration input."""

    def __init__(self, details: list[str]) -> None:
        self.details = details
        super().__init__("; ".join(details))


def _annotation(family: str, key: str) -> Any:
    return FAMILIES[family].model_fields[key].annotation


def _is_optional(ann: Any) -> bool:
    return get_origin(ann) is Union and type(None) in get_args(ann)


def _strip_optional(ann: Any) -> Any:
    if _is_optional(ann):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _suggest(key: str) -> str:
    close = difflib.get_close_matches(key, FLAT_KEYS, n=1, cutoff=0.6)
    return f"; did you mean {close[0]!r}?" if close else ""


def _coerce_env(raw_key: str, raw_value: str, ann: Any) -> Any:
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
        raise ConfigError(
            [f"{raw_key}: expected a boolean (true/false/1/0), got {raw_value!r}; "
             f"fix the environment variable or unset it"]
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
    return raw_value


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(
            [f"cannot read settings file {path}: {exc}; "
             f"check file permissions, then re-run or delete the file to regenerate defaults"]
        ) from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            [f"settings file is not valid UTF-8 TOML ({path}): {exc}; "
             f"fix or delete the offending line, or restore the file from a backup"]
        ) from exc
    if not isinstance(data, dict):
        raise ConfigError([f"settings file must be a table ({path})"])
    return data


_SCHEMA_CONFIG_VERSION = 1


def load_config(
    env: Mapping[str, str] | None = None,
    warnings: list[str] | None = None,
) -> AppConfig:
    """Load settings; ``warnings`` (if given) receives non-fatal notices."""
    env = os.environ if env is None else env
    config_path = resolve_config_path(env)
    flat: dict[str, Any] = _read_toml(config_path)
    file_version = flat.get("config_version", _SCHEMA_CONFIG_VERSION)
    from_newer_build = (
        isinstance(file_version, int) and file_version > _SCHEMA_CONFIG_VERSION
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
                f"unknown environment key: {raw_key}{_suggest(key)}; "
                f"unset it or correct the spelling in your shell"
            )
            continue
        try:
            flat[key] = _coerce_env(raw_key, raw_value, _annotation(FLAT_KEYS[key], key))
            origin[key] = raw_key
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
                f"(config_version={file_version}); it will be preserved by nothing "
                f"and re-recognised after you upgrade back"
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
                f"unknown config key: {key} (in {config_path}){_suggest(key)}; "
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
            raise ConfigError([f"unknown config key: {key}{_suggest(key)}; "
                               f"check the spelling against `ipo guide`"])
        if key in CREDENTIAL_KEYS:
            raise ConfigError(
                [f"{key} is credential-shaped and never persisted; "
                 f"pass it via the environment (IPO_{key.upper()}) until the "
                 f"encrypted secret store lands (P4)"]
            )
        if isinstance(value, str) and _URL_CREDENTIAL_PATTERN.search(value):
            raise ConfigError(
                [f"{key}: value contains an inline URL credential "
                 f"(user:password@host); move the credential to an "
                 f"IPO_-prefixed environment variable instead"]
            )
        family = FLAT_KEYS[key]
        section = getattr(self.config, family)
        candidate = section.model_dump()
        candidate[key] = value
        try:
            validated = FAMILIES[family].model_validate(candidate)
        except ValidationError as exc:
            raise ConfigError(
                [f"{family}.{key}: {exc.errors()[0]['msg']}; "
                 f"choose a value matching the documented range/type"]
            ) from exc
        setattr(section, key, getattr(validated, key))  # normalized value
        self._dirty.add((family, key))

    def save(self) -> Path:
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
                os.replace(temp_name, self.path)
            except OSError as exc:
                Path(temp_name).unlink(missing_ok=True)
                raise ConfigError(
                    [f"cannot write settings file {self.path}: {exc}; "
                     f"check permissions and whether another process holds the "
                     f"file open, then retry"]
                ) from exc
        self._dirty.clear()
        return self.path


def _mkstemp_in(directory: Path) -> tuple[int, str]:
    import tempfile

    return tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)


class _advisory_lock:
    """Portable cross-process mutex via O_CREAT|O_EXCL lock file with timeout."""

    def __init__(self, path: Path, timeout_seconds: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout_seconds
        self.held = False

    def __enter__(self) -> "_advisory_lock":
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
                        [f"settings file is locked by another process "
                         f"({self.path}); wait for it to finish or remove a "
                         f"stale lock after confirming no ipostudio process runs"]
                    )
                time.sleep(0.05)

    def __exit__(self, *exc: object) -> None:
        if self.held:
            os.close(self.fd)
            self.path.unlink(missing_ok=True)
            self.held = False
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/conf/test_loader.py -v`
Expected: `16 passed`。

- [ ] **Step 5: 提交**

```bash
git add src/ipostudio/conf/loader.py tests/conf/test_loader.py
git commit -m "feat: config loader with TOML merge, IPO_ env overrides and atomic save"
```

---

### Task 5: 日志系统（轮转 + 脱敏 + JSONL）

**Files:**
- Create: `src/ipostudio/logs.py`
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: `paths.resolve_data_dir/ensure_layout`（仅 CLI/运行时组合时使用；本模块自身只接收目录参数）。
- Produces:
  - `setup_logging(data_dir: Path, *, level: str = "info", json_lines: bool = False, max_bytes: int = 2_000_000, backups: int = 5) -> logging.Logger` — 配置名为 `"ipostudio"` 的日志器（控制台 + `logs/ipostudio.log` 轮转文件），幂等（重复调用先清理既有 handler）。
  - `redact_text(text: str) -> str` — 对 `key=value`/`key: value` 形式的敏感键、`Bearer <token>`、`sk-` 前缀长令牌打码。
  - `redaction_count() -> int` — 进程内累计打码次数（规格 §5.20"记录拦截数量"同款行为，供诊断输出）。
  - `log_file_path(data_dir: Path) -> Path` — CLI `ipo logs`（P21）与崩溃后读取（§5.23）用。
  - `RedactionFilter`（`logging.Filter` 子类）。

- [ ] **Step 1: 写失败测试 `tests/test_logs.py`**

```python
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/test_logs.py -v`
Expected: FAIL，`No module named 'ipostudio.logs'`。

- [ ] **Step 3: 实现 `src/ipostudio/logs.py`**

```python
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
_SECRET_KEY_VALUE = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])"
    r"((?:[a-z0-9_-]*token)|(?:api[_-]?key)|(?:[a-z0-9_-]*secret)|"
    r"(?:[a-z0-9_-]*password)|(?:authorization)|(?:credential)|key)"
    r"(?![A-Za-z0-9_-])(\s*[=:]\s*)(\S+)"
)
# credentials embedded in URLs: http://user:password@host
_URL_CREDENTIAL = re.compile(r"(?i)(://)([^/\s:@]+):([^/\s@]+)(@)")
_BEARER = re.compile(r"(?i)\bbearer\s+(\S+)")
_LONG_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_MASK = "***"

_masked_total = 0


def redaction_count() -> int:
    return _masked_total


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
) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    console = logging.StreamHandler()
    file_handler = RotatingFileHandler(
        log_file_path(data_dir), maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
    )
    formatter = (
        _JsonLineFormatter()
        if json_lines
        else _PlainTextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    for handler in (console, file_handler):
        handler.setFormatter(formatter)
        handler.addFilter(RedactionFilter())
        logger.addHandler(handler)
    return logger
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/test_logs.py -v`
Expected: `6 passed`。

- [ ] **Step 5: 提交**

```bash
git add src/ipostudio/logs.py tests/test_logs.py
git commit -m "feat: rotating redacting logger with JSONL mode"
```

---

### Task 6: 数据库层（WAL + 版本化迁移）

**Files:**
- Create: `src/ipostudio/store/__init__.py`（空）
- Create: `src/ipostudio/store/database.py`
- Create: `src/ipostudio/store/migrations/001_init.sql`
- Test: `tests/store/__init__.py`（空）、`tests/store/test_database.py`

**Interfaces:**
- Consumes: 无。
- Produces（P2 起所有领域计划依赖）:
  - `open_db(path: Path) -> sqlite3.Connection` — `journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`row_factory=sqlite3.Row`。
  - `migrate(conn: sqlite3.Connection) -> list[str]` — 按文件名序应用未执行的迁移，返回本次应用的迁移名列表；幂等。
  - `current_version(conn) -> int` — 已应用迁移数（即最高序号版本）。
  - 迁移登记表 `_migrations(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, applied_at TEXT NOT NULL)`——由 `migrate()` 引导创建，属于运行时内部结构（规格不约束物理表名）。
  - `app_meta` 键值表的既有消费者：本计划测试用作探针；P2 模型目录仓库层用 `app_meta` 存 CLI 侧状态（如最近选择模型）——非 YAGNI。

- [ ] **Step 1: 写失败测试 `tests/store/test_database.py`**

```python
import sqlite3

import pytest

from ipostudio.store.database import MigrationFailure, current_version, migrate, open_db


def test_open_db_enables_wal_and_row_factory(tmp_path):
    conn = open_db(tmp_path / "app.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_migrate_is_idempotent_and_records_names(tmp_path):
    conn = open_db(tmp_path / "app.db")
    applied_first = migrate(conn)
    applied_second = migrate(conn)
    assert applied_first == ["001_init.sql"]  # migration identity = package filename
    assert applied_second == []
    assert current_version(conn) == 1
    names = [row["name"] for row in conn.execute("SELECT name FROM _migrations ORDER BY id")]
    assert names == ["001_init.sql"]
    # app_meta usable
    conn.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES ('probe', '1')")
    conn.commit()
    assert conn.execute("SELECT value FROM app_meta WHERE key='probe'").fetchone()[0] == "1"
    conn.close()


def test_failed_migration_rolls_back_and_stays_unregistered(tmp_path, monkeypatch):
    import ipostudio.store.database as db

    broken = [("001_init.sql", db.migration_files()[0][1]),
              ("002_broken.sql", "INSERT INTO no_such_table VALUES (1);")]
    monkeypatch.setattr(db, "migration_files", lambda: broken)
    conn = open_db(tmp_path / "app.db")
    with pytest.raises(MigrationFailure) as err:
        migrate(conn)
    assert err.value.name == "002_broken.sql"
    names = [row["name"] for row in conn.execute("SELECT name FROM _migrations")]
    assert names == ["001_init.sql"]      # failed migration not registered
    assert migrate(conn) == []            # connection reusable after rollback
    conn.close()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/store/test_database.py -v`
Expected: FAIL，`No module named 'ipostudio.store'`。

- [ ] **Step 3: 写迁移 `src/ipostudio/store/migrations/001_init.sql`**

```sql
-- 001_init: internal key-value storage for CLI/runtime state.
-- (_migrations is bootstrapped by migrate() itself, not by this script.)
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

- [ ] **Step 4: 实现 `src/ipostudio/store/database.py`**

```python
"""SQLite connection defaults and forward-only versioned migrations (ADR-002)."""

import sqlite3
from importlib import resources
from pathlib import Path

_MIGRATIONS_PACKAGE = "ipostudio.store.migrations"


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migration_files() -> list[tuple[str, str]]:
    entries = resources.files(_MIGRATIONS_PACKAGE).iterdir()
    named = sorted(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in entries
        if entry.name.endswith(".sql")
    )
    return named


class MigrationFailure(sqlite3.Error):
    """A migration script failed; its transaction was rolled back."""

    def __init__(self, name: str, cause: Exception) -> None:
        super().__init__(f"migration {name} failed and was rolled back: {cause}")
        self.name = name


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations atomically and race-safe.

    - BEGIN IMMEDIATE takes the write lock BEFORE re-reading the registry, so
      two processes starting migrations concurrently serialize instead of both
      applying the same script (eng review consensus).
    - executescript() force-commits pending transactions, so atomicity of
      "apply script + register it" requires BEGIN/COMMIT inside the script text.
    - On failure the open transaction is rolled back explicitly and re-raised
      as MigrationFailure; _migrations stays clean and a retry is safe.
    - Authoring rules: migration files must end with `;` + newline, must not
      contain their own BEGIN/COMMIT, and must not end with a `--` comment.
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _migrations ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT UNIQUE NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied: list[str] = []
    for name, script in migration_files():
        conn.executescript("BEGIN IMMEDIATE;\n")
        try:
            registered = conn.execute(
                "SELECT 1 FROM _migrations WHERE name = ?", (name,)
            ).fetchone()
            if registered:
                conn.execute("COMMIT")
                continue
            # name is a package-controlled ASCII filename; repr() is a safe SQL literal.
            conn.executescript(script)
            conn.execute("INSERT INTO _migrations(name) VALUES (?)", (name,))
            conn.execute("COMMIT")
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationFailure(name, exc) from exc
        applied.append(name)
    return applied


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]
```

同时创建空 `src/ipostudio/store/__init__.py`，并在 `migrations/` 旁放置空 `src/ipostudio/store/migrations/__init__.py`（`importlib.resources` 打包发现需要包标记）。

- [ ] **Step 5: 运行测试验证通过**

Run: `python -m pytest tests/store/test_database.py -v`
Expected: `3 passed`。

- [ ] **Step 6: 提交**

```bash
git add src/ipostudio/store/ tests/store/
git commit -m "feat: sqlite WAL connection defaults and versioned migration runner"
```

---

### Task 7: CLI 骨架（`ipo version/help/guide/doctor`）

**Files:**
- Create: `src/ipostudio/cli/__init__.py`（空）
- Create: `src/ipostudio/cli/main.py`
- Test: `tests/cli/__init__.py`（空）、`tests/cli/test_main.py`

**Interfaces:**
- Consumes: `ipostudio.__version__`、`conf.paths.ensure_layout/resolve_data_dir`、`conf.loader.load_config/ConfigError`、`logs.log_file_path`、`store.database.open_db/migrate`。
- Produces:
  - click 组 `cli`（console_script `ipo` 的目标）。
  - `collect_command_docs() -> list[dict]`（`main.py` 内，供 `help`/`guide` 共用；每项 `{"name", "help", "options": [{"flag", "help"}]}`）。
  - 命令：`version [--json]`、`help [--format text|markdown|json]`、`guide [--format text|markdown|json] [--lang zh|en]`、`doctor [--json]`。
  - 退出码约定：成功 0；click 用法错误 2；doctor 检查失败 1（运行失败的通用约定，后续计划沿用）。

- [ ] **Step 1: 写失败测试 `tests/cli/test_main.py`**

```python
import json

from click.testing import CliRunner

from ipostudio import __version__
from ipostudio.cli.main import cli


def invoke(*args):
    return CliRunner().invoke(cli, list(args))


def test_version_text_and_json():
    result = invoke("version")
    assert result.exit_code == 0
    assert __version__ in result.output
    payload = json.loads(invoke("version", "--json").output)
    assert payload == {"name": "ipostudio", "version": __version__}


def test_help_lists_commands_in_all_formats():
    for fmt in ("text", "markdown", "json"):
        result = invoke("help", "--format", fmt)
        assert result.exit_code == 0
    docs = json.loads(invoke("help", "--format", "json").output)
    names = {d["name"] for d in docs}
    assert {"version", "help", "guide", "doctor"} <= names


def test_guide_mentions_every_command_and_langs():
    result_zh = invoke("guide")
    assert result_zh.exit_code == 0
    result_en = invoke("guide", "--lang", "en")
    assert result_en.exit_code == 0
    docs = json.loads(invoke("guide", "--format", "json").output)
    assert {d["name"] for d in docs} >= {"version", "help", "guide", "doctor"}


def test_guide_lang_defaults_from_ui_lang_config(monkeypatch, tmp_path):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IPO_UI_LANG", "en")
    result = invoke("guide")  # no --lang: follows ui_lang config
    assert result.exit_code == 0
    assert "unified entry" in result.output  # English brief, not Chinese


def test_group_version_flag():
    result = invoke("--version")
    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_passes_on_fresh_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor")
    assert result.exit_code == 0
    assert "[PASS]" in result.output
    assert not (tmp_path / "data" / "app.db").exists()  # read-only by default


def test_doctor_fix_initializes_database(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = invoke("doctor", "--fix")
    assert result.exit_code == 0
    assert (tmp_path / "data" / "app.db").exists()


def test_doctor_fix_migrates_existing_outdated_database(tmp_path, monkeypatch):
    import sqlite3 as sq

    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    db = tmp_path / "data" / "app.db"
    db.parent.mkdir(parents=True)
    conn = sq.connect(db)  # pre-existing DB with NO migrations applied
    conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.commit()
    conn.close()
    result = invoke("doctor", "--fix")
    assert result.exit_code == 0
    conn = sq.connect(db)
    names = [r[0] for r in conn.execute("SELECT name FROM _migrations")]
    conn.close()
    assert names == ["001_init.sql"]  # existing DB was migrated, not skipped


def test_doctor_fails_nonzero_on_bad_config(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("bogus_key = 1\n", encoding="utf-8")
    result = invoke("doctor")
    assert result.exit_code == 1
    assert "[FAIL]" in result.output
    assert "bogus_key" in result.output


def test_doctor_json_structure(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    payload = json.loads(invoke("doctor", "--json").output)
    assert payload["ok"] is True
    names = {c["name"] for c in payload["checks"]}
    assert {"config", "data-dir", "database", "logs"} <= names
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: FAIL，`No module named 'ipostudio.cli'`。

- [ ] **Step 3: 实现 `src/ipostudio/cli/main.py`**

```python
"""`ipo` command line entrypoint (spec §9.11 skeleton + §9.12 doctor)."""

import json
import os
import sqlite3
import sys
from dataclasses import dataclass

import click

from ipostudio import __version__
from ipostudio.conf.loader import ConfigError, load_config
from ipostudio.conf.paths import ensure_layout, resolve_data_dir, resolve_db_path
from ipostudio.logs import log_file_path
from ipostudio.store.database import migrate, open_db

GUIDE_BRIEF = {
    "zh": "ipostudio 命令行工具：本地模型、推理服务与应用的统一入口（当前为基础版本）。",
    "en": "ipostudio CLI: unified entry for local models, inference services and apps (foundation release).",
}


@dataclass
class CheckOutcome:
    name: str
    ok: bool
    detail: str


def _force_utf8_streams() -> None:
    """Non-tty streams default to the locale codec (cp936 etc. on Windows),
    which can crash or mojibake CJK output; pin redirected output to UTF-8
    (requirement R1). Interactive consoles already use UTF-8 via the OS API."""
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def collect_command_docs() -> list[dict]:
    docs = []
    for name, command in sorted(cli.commands.items()):
        docs.append(
            {
                "name": name,
                "help": command.help or "",
                "options": [
                    {"flag": option.opts[0] if option.opts else "", "help": option.help or ""}
                    for option in command.params
                ],
            }
        )
    return docs


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog="Docs: docs/ in the repository, or run `ipo guide`.",
)
@click.version_option(__version__, prog_name="ipo")
@click.option("--config", "config_path", type=click.Path(), default=None,
              help="path to settings.toml (overrides IPO_CONFIG)")
@click.option("--data-dir", "data_dir", type=click.Path(), default=None,
              help="data directory (overrides IPO_DATA_DIR)")
def cli(config_path: str | None, data_dir: str | None) -> None:
    """ipostudio command line interface."""
    _force_utf8_streams()
    # CLI flags translate to the bootstrap env vars before any config load;
    # the env vars remain the underlying mechanism (escape-hatch parity).
    if config_path:
        os.environ["IPO_CONFIG"] = config_path
    if data_dir:
        os.environ["IPO_DATA_DIR"] = data_dir


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def version(as_json: bool) -> None:
    """Show the ipostudio version."""
    if as_json:
        click.echo(json.dumps({"name": "ipostudio", "version": __version__}))
    else:
        click.echo(f"ipostudio {__version__}")


def _render_docs(docs: list[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(docs, ensure_ascii=False, indent=2)
    if fmt == "markdown":
        lines = ["# ipo command reference", ""]
        for doc in docs:
            lines += [f"## {doc['name']}", "", doc["help"] or "(no description)", ""]
            for option in doc["options"]:
                lines.append(f"- `{option['flag']}`: {option['help']}")
            lines.append("")
        return "\n".join(lines)
    lines = []
    for doc in docs:
        flags = " ".join(f"[{o['flag']}]" for o in doc["options"])
        lines.append(f"ipo {doc['name']} {flags}".rstrip())
        if doc["help"]:
            lines.append(f"    {doc['help']}")
    return "\n".join(lines)


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["text", "markdown", "json"]), default="text")
@click.option("--json", "as_json", is_flag=True, help="shorthand for --format json")
def help(fmt: str, as_json: bool) -> None:
    """List available ipo commands."""
    if as_json:
        fmt = "json"
    click.echo(_render_docs(collect_command_docs(), fmt))


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["text", "markdown", "json"]), default="text")
@click.option("--json", "as_json", is_flag=True, help="shorthand for --format json")
@click.option("--lang", type=click.Choice(["zh", "en"]), default=None,
              help="manual language (default: ui_lang config)")
def guide(fmt: str, as_json: bool, lang: str | None) -> None:
    """Show the full ipo manual."""
    if as_json:
        fmt = "json"
    if lang is None:
        try:
            lang = load_config().ui.ui_lang
        except ConfigError:
            lang = "zh"  # broken config must not break the manual
    if fmt == "json":
        click.echo(json.dumps(collect_command_docs(), ensure_ascii=False, indent=2))
        return
    click.echo(GUIDE_BRIEF[lang])
    click.echo(_render_docs(collect_command_docs(), fmt))


def _check_config() -> tuple[CheckOutcome, list[str]]:
    warnings: list[str] = []
    try:
        load_config(warnings=warnings)
        outcome = CheckOutcome("config", True, "settings parsed with strict key validation")
    except ConfigError as exc:
        outcome = CheckOutcome("config", False, "; ".join(exc.details))
    return outcome, warnings


def _unique_probe(directory: Path) -> bool:
    """Write-verify with an exclusively-created unique temp file.

    Never touches or deletes pre-existing files (eng review: a fixed probe name
    would overwrite then delete a user file of the same name)."""
    import tempfile

    try:
        fd, name = tempfile.mkstemp(prefix=".doctor-probe-", dir=directory)
        os.close(fd)
        os.unlink(name)
        return True
    except OSError:
        return False


def _check_data_dir(repair: bool) -> CheckOutcome:
    data_dir = resolve_data_dir()
    if repair:
        ensure_layout(data_dir)  # idempotent; also repairs partial layouts
    if not data_dir.exists():
        return CheckOutcome(
            "data-dir", True,
            f"not created yet ({data_dir}); run with --fix or start the app",
        )
    if not _unique_probe(data_dir):
        return CheckOutcome(
            "data-dir", False,
            f"data directory not writable ({data_dir}); check permissions "
            f"(synced/roaming profiles and antivirus locks are common causes)",
        )
    return CheckOutcome("data-dir", True, str(data_dir))


def _check_database(repair: bool) -> CheckOutcome:
    db_path = resolve_db_path()
    if repair:
        try:
            conn = open_db(db_path)
            try:
                migrate(conn)  # repairs BOTH fresh and outdated databases
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return CheckOutcome(
                "database", False,
                f"migration failed: {exc}; the failed migration was rolled "
                f"back; fix the reported cause and re-run",
            )
        return CheckOutcome("database", True, f"schema up to date at {db_path}")
    if not db_path.exists():
        return CheckOutcome(
            "database", True,
            f"not initialized yet ({db_path}); run with --fix or start the app",
        )
    try:
        # read-only inspection: default doctor must not touch an existing
        # database (no WAL pragma, no migration). --fix repairs explicitly.
        from urllib.parse import quote

        conn = sqlite3.connect(f"file:{quote(str(db_path))}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            version = _count_migrations(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        if "readonly" in str(exc).lower() or "cantopen" in str(exc).lower():
            return CheckOutcome(
                "database", True,
                f"cannot inspect read-only ({exc}); likely a synced/locked "
                f"directory; run `ipo doctor --fix` for a writable check",
            )
        return CheckOutcome(
            "database", False,
            f"sqlite failure: {exc}; run `ipo doctor --fix` or check the file "
            f"is not locked by another ipostudio process",
        )
    return CheckOutcome("database", True, f"schema at migration count {version}")


def _count_migrations(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM _migrations").fetchone()[0]


def _check_logs(repair: bool) -> CheckOutcome:
    path = log_file_path(resolve_data_dir())
    if repair:
        path.parent.mkdir(parents=True, exist_ok=True)
    if not path.parent.exists():
        return CheckOutcome(
            "logs", True,
            f"log directory not created yet ({path.parent}); run with --fix or start the app",
        )
    if not _unique_probe(path.parent):
        return CheckOutcome(
            "logs", False,
            f"log directory not writable ({path.parent}); check permissions, then re-run",
        )
    return CheckOutcome("logs", True, str(path))


def _contained(check, repair: bool) -> CheckOutcome:
    """Every check failure still returns a structured outcome, so `--json`
    never dies mid-report (eng review)."""
    try:
        return check(repair)
    except Exception as exc:  # noqa: BLE001 - diagnostic command must not crash
        return CheckOutcome("unexpected", False, f"{check.__name__}: {exc!r}; "
                          f"this is a bug in ipo doctor; report it with --json output")


def run_doctor(repair: bool = False) -> tuple[list[CheckOutcome], list[str]]:
    config_outcome, warnings = _check_config()
    outcomes = [
        config_outcome,
        _contained(_check_data_dir, repair),
        _contained(_check_database, repair),
        _contained(_check_logs, repair),
    ]
    return outcomes, warnings


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
@click.option("--fix", "repair", is_flag=True, help="repair: create layout and apply migrations")
def doctor(as_json: bool, repair: bool) -> None:
    """Verify config, data dir, database and logs (read-only; --fix repairs)."""
    outcomes, warnings = run_doctor(repair)
    failed = [o for o in outcomes if not o.ok]
    if as_json:
        click.echo(
            json.dumps(
                {
                    "ok": not failed,
                    "checks": [
                        {"name": o.name, "ok": o.ok, "detail": o.detail} for o in outcomes
                    ],
                    "warnings": warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for outcome in outcomes:
            mark = "[PASS]" if outcome.ok else "[FAIL]"
            # long multi-error details are truncated for the terminal with a
            # visible count; `--json` always carries the full text
            shown = outcome.detail
            if len(shown) > 300:
                shown = shown[:300] + f" ...(+{len(outcome.detail) - 300} chars; use --json)"
            click.echo(f"{mark} {outcome.name}: {shown}")
        for warning in warnings:
            click.echo(f"[WARN] config: {warning}")
    if failed:
        sys.exit(1)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `python -m pytest tests/cli/test_main.py -v`
Expected: `10 passed`。

- [ ] **Step 5: 提交**

```bash
git add src/ipostudio/cli/ tests/cli/
git commit -m "feat: ipo CLI skeleton with version, help, guide and doctor"
```

---

### Task 8: 安装打包与端到端冒烟

**Files:**
- Create: `src/ipostudio/__main__.py`
- Create: `tests/cli/test_smoke.py`
- Modify: 无（`pyproject.toml` 已在 Task 1 声明 `ipo` 入点）

**Interfaces:**
- Consumes: `[project.scripts] ipo`、`python -m ipostudio`、Task 7 的 `cli`。
- Produces: 包级模块入口 `python -m ipostudio`；可安装分发（`pip install -e .` 后 `ipo` 全局可用）；`tests/cli/test_smoke.py` 作为后续计划的安装回归。

- [ ] **Step 1: 写失败测试 `tests/cli/test_smoke.py`**

```python
import json
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def run_module(args: list[str], data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC), "IPO_DATA_DIR": str(data_dir)}
    return subprocess.run(
        [sys.executable, "-m", "ipostudio", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",  # CLI pins non-tty output to UTF-8 (requirement R1)
        env=env,
        timeout=60,
    )


def test_module_entry_version_json(tmp_path):
    proc = run_module(["version", "--json"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["name"] == "ipostudio"


def test_module_entry_doctor_json(tmp_path):
    proc = run_module(["doctor", "--json"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


def test_module_entry_guide_cjk_roundtrip(tmp_path):
    proc = run_module(["guide", "--lang", "zh"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "命令行" in proc.stdout  # UTF-8 survives Windows pipes (R1)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `python -m pytest tests/cli/test_smoke.py -v`
Expected: FAIL，`No module named 'ipostudio.__main__'; 'ipostudio' is a package and cannot be directly executed`。

- [ ] **Step 3: 写包级入口 `src/ipostudio/__main__.py`**

```python
"""Allow `python -m ipostudio` as an alias of the `ipo` console script."""

from ipostudio.cli.main import cli

if __name__ == "__main__":
    cli()
```

Run: `python -m pytest tests/cli/test_smoke.py -v`
Expected: `3 passed`。

- [ ] **Step 4: 安装为可编辑包并验证 `ipo` 命令**

```bash
python -m pip install -e .
ipo version
ipo version --json
ipo doctor
```

Expected: 三条命令输出正常，`ipo doctor` 退出码 0。

- [ ] **Step 5: 运行全部测试**

Run: `python -m pytest -v`
Expected: 全部通过（累计 48 项；Task 9 平台卫生守卫后 49 项）。

- [ ] **Step 6: Lint 收口**

Run: `python -m ruff check src tests`
Expected: 无错误（有则修复后重跑）。

- [ ] **Step 7: 提交**

```bash
git add src/ipostudio/__main__.py tests/cli/test_smoke.py
git commit -m "test: package module entry and end-to-end smoke tests"
```

---

### Task 9: CI 三平台矩阵（需求附录 R1 的执行机制）

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `tests/test_platform_hygiene.py`

**Interfaces:**
- Consumes: Task 1–8 的全部测试与 lint。
- Produces: push/PR 触发的 `ubuntu-latest`/`windows-latest`/`macos-latest` × Python `3.11/3.12` 测试矩阵；本地平台卫生守卫（R1 补偿机制：远端建立前的静态防护）。

- [ ] **Step 1: 写平台卫生守卫 `tests/test_platform_hygiene.py`**

```python
"""Static guard for requirement R1: no POSIX-only constructs in src/.

The three-platform CI is the real gate once a remote exists; this test is the
local compensating guard until then (CEO review consensus, ADR-010).
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

BANNED_PATTERNS = (
    "os.path.",          # use pathlib everywhere (plan Global Constraints)
    "if os.name ==",
    "sys.platform ==",
)


def test_no_posix_only_constructs_in_src():
    violations = []
    for py in SRC.rglob("*.py"):
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in BANNED_PATTERNS:
                if pattern in line:
                    violations.append(f"{py.name}:{lineno}: {pattern.strip()}")
    assert not violations, "platform-hygiene violations:\n" + "\n".join(violations)
```

Run: `python -m pytest tests/test_platform_hygiene.py -v`
Expected: `1 passed`。

- [ ] **Step 1.5: 写工作流 `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  push:
  pull_request:

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ["3.11", "3.12"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install
        run: python -m pip install -e ".[dev]"
      - name: Tests
        run: python -m pytest -v
      - name: Lint
        run: python -m ruff check src tests
```

（说明：`fail-fast: false` 保证能看到每个平台的完整失败清单。**验收口径（无远端时的本地等价）**：本仓库当前无 git 远端，"三平台全绿"在远端建立并首次 push 前不可执行；因此 P1 的验收 = 本地 `python -m pytest -v` 全绿（49 项，含平台卫生守卫）+ `python -m ruff check` 干净 + 工作流文件存在且语法有效（YAML 语法错误会在 push 后 workflow 解析阶段立即暴露）。CI 门禁在远端存在之日起自动生效，成为后续所有计划的合并门槛。远端/push 的建立属用户操作，不入本计划任务。）

- [ ] **Step 2: 提交**

```bash
git add .github/workflows/ci.yml tests/test_platform_hygiene.py
git commit -m "ci: three-platform test matrix and local platform-hygiene guard (requirement R1)"
```

---

---

## 完成定义（P1 验收对照）

- `pip install -e .` 后 `ipo version/help/guide/doctor` 可用，doctor 失败时退出码 1（规格 §9.11"失败非零退出"、§9.12"环境体检"）。
- 规格表 §11.2 的每个键：有默认值、有类型/枚举/范围校验、可经 `IPO_<KEY>` 覆盖、未知键（文件或环境）被拒绝并报出键名（§11.1）。
- 日志：轮转 ~2MB、凭据打码、JSONL 可选、文件落盘可离线读取（§5.23/§15，对应 T73 精神的可自动化子集）。
- SQLite：WAL + 迁移幂等且"应用+登记"原子（为 P2+ 提供地基）。
- 三平台（附录 R1）：本地全量测试与 lint 通过 + `.github/workflows/ci.yml` 就位；CI 门禁自远端建立起生效（见 Task 9 验收口径）。
- 洁净室检查：无任何第三方项目源码片段；命名除规格强制接口（`ipo`、`IPO_*`）外均为本项目独立设计。

## 已知延后项（显式记录，非遗漏）

- 云端凭据（`vllm_api_key` 等）目前为明文配置字段；加密落盘在 P4（密钥管理）与 P18（备份凭据剔除）统一解决（§14.4）。
- 配置跨进程 2 秒可见窗口的文件监听在 P4 网关计划实现（本计划仅提供原子写保证）（§11.1）。
- §11.1"配置与实际地址区分"：配置值与运行时实际绑定地址的分离展示，落 P3（引擎实例）与 P4（网关状态端点）。
- §11.1"明确即时或重启生效"：逐键生效时机标注，落 P4（随网关配置监听一并实现）。
- §9.12 其余扩展兼容命令（已知配置列表/读/写、模型列表、流式对话、服务器强停等）按路线图统一落 P21（`ipo serve/logs/models` 同期）。
- `ipo serve/logs/models` 等命令按路线图在 P2/P4/P21 落地。

<!-- autoplan-accepted:ceo -->
- 需求附录 R1（三平台支持）为本计划硬约束：全部代码/测试无 POSIX-only 假设；Task 7 UTF-8 流强化与 Task 8 CJK 往返测试必须落地；验证 = 本地 `python -m pytest -v` 全绿（49 项，含平台卫生守卫）+ ruff 干净 + 工作流就位；CI 门禁自远端建立起生效（见 Task 9 说明）。
- 需求附录 R2（文档格式）本计划仅继承约束（不含 docparse 实现）；P11/P13 计划必须实现 docparse 解析器注册表（ADR-009），传统二进制格式明确提示转换。
- 版本号单一来源：`src/ipostudio/__init__.py` 的 `__version__`，pyproject 用 hatch dynamic version；不得恢复双写。
- CLAUDE.md（技能路由规则）随 Task 1 首次提交入库。
- 规格 §11.2 全部键的默认值/校验/覆盖行为保持原计划要求不变（用户指令未触及）。
- 前向兼容：`config_version` 键 + "更高版本文件的未知键忽略、同版本拒绝"策略 + 测试（双声部共识，Task 3/4）。
- 秘密边界：`ConfigStore` 永不持久化 `*_api_key` 字段（Task 4 `CREDENTIAL_KEYS` + 测试）；P4 引入加密秘密库。
- 日志脱敏覆盖 traceback（两个 formatter 全格式重打码 + 泄漏测试，Task 5）。
- doctor 默认只读（不建目录、不迁移），`--fix` 显式修复 + 测试（Task 7）。
- ConfigStore 只写脏键并合并重读文件，多入口并发不互相覆盖、环境覆盖不落盘 + 测试（Task 4）。
- LICENSE（Apache-2.0，最终门可改 MIT）随 Task 1 入库。
- CI 增加 Python 3.11/3.12 版本维度；本地平台卫生守卫测试（`os.path.` 等禁用模式）作为 R1 补偿机制（Task 9）。
- 默认值一致性测试改为表驱动单一来源 `SPEC_DEFAULTS`（Task 3）。
- 迁移作者规则：SQL 迁移文件不得以无换行的 `--` 注释结尾（Task 6 注释 + 此处义务）。
- 三平台机器验证 = P2 入口条件（非 P1 已完成项）；P1 验收为本地等价口径 + 卫生守卫。
<!-- /autoplan-accepted:ceo -->


<!-- autoplan-accepted:dx -->
- README.md（先决条件/venv/安装/测试/快速开始/配置说明/M0 状态区分）与 CHANGELOG.md（0.1.0 unreleased）随 Task 1 入库。
- 错误信息契约（全 P1 表面 + 后续命令继承）：问题 + 出处（文件路径/环境变量名）+ 修复动作；未知键附 difflib 近邻建议；doctor 文本输出截断时显示 (+N)，`--json` 恒为全文；click 组 epilog 指向文档。
- `config_version` 回滚路径修复：新版本文件的未知键在分组前剔除（修复 KeyError），经 `load_config(env, warnings)` 收集告警，doctor 以 `[WARN]` 展示；有测试。
- `_read_toml` 捕获 `OSError` 与 `UnicodeDecodeError` 并给出修复指引；有测试（非 UTF-8 字节）。
- `ConfigStore.set(key, value)` 扁平签名；写入前经 schema 验证（失败回滚属性）；凭据键 `set()` 抛 ConfigError 指引环境变量；`save()` 从合并结果中剔除凭据键（含文件既有值）；临时文件按进程唯一（mkstemp）。
- doctor 默认严格只读：不 mkdir、不对既有库设 WAL、不创建日志文件（ro-uri 只读连接、临时探针即删）；data-dir 检查默认常驻（修复测试矛盾）；`--fix` 显式修复。
- 迁移标识 = 包内文件名（含 `.sql`）；测试对齐 `001_init.sql`。
- CLI 约定入 Global Constraints：`--json` 统一、组级 `--version/--config/--data-dir`、`guide --lang` 默认取 `ui_lang` 配置（坏配置回退 zh）。
- TODO-002（CLI 崩溃兜底 + --debug）、TODO-003（P1 后 /devex-review 回旋镖实测 TTHW）登记 TODOS.md。
- 残余风险记录：`_migrations` 含包内不存在的迁移名（新库旧码场景）时的守护检查归 P2 首个新迁移之前实现（current_version 已提供计数基础）。
<!-- /autoplan-accepted:dx -->


<!-- autoplan-accepted:eng -->
- 脱敏正则重写：左边界改 `(?<![A-Za-z0-9_-])`，键形覆盖 `[\w-]*token/password/secret`、`api[_-]?key`、`authorization`、`credential`、裸 `key`（URL `?key=`）；新增 URL 内嵌凭据模式；JSON 字段值经 kv 规则覆盖；新增形态测试（access_token=/AUTH_TOKEN:/gateway_api_key=/JSON/URL）。
- `migrate()`：BEGIN IMMEDIATE 后重读登记（并发迁移串行化）；失败显式 rollback 并抛 `MigrationFailure`（携迁移名），`_migrations` 保持干净、连接可复用；作者规则补全（以 `;`+换行结尾、不得自带 BEGIN/COMMIT、不得以无换行注释结尾）；坏迁移测试。
- `ConfigStore`：凭据键与 URL 内嵌凭据检查移到 `set()` 最前（拒绝后内存零变更）；候选模型验证成功才落值（规范化类型）；错误统一 `ConfigError`；`save()` 全程持跨进程 advisory lock（O_CREAT|O_EXCL，5s 超时，finally 清理）；失败清理临时文件并抛 ConfigError；测试覆盖（无变更拒绝/JSON 列表/环境变量归因/失败清理）。
- 环境列表支持 JSON 数组编码（逗号保留于值内）。
- doctor：探针改独占创建的唯一临时文件（不再覆盖/删除既有同名文件）；`--fix` 修复既有过时数据库（open_db+migrate）与部分目录布局；ro 打开失败（同步/锁定目录）降级为带指引的 PASS 注记；URI 路径 quote；每检查异常受纳（`--json` 永不中途死）；新增 fix-migrates-existing 测试。
- 多进程日志所有权决策：按进程分文件（ADR-006 修订 + TODO-004）。
- wheel 仓库外安装冒烟延后 M0（TODO-005）。
- 前向兼容范围限定与混合版本写策略入 Global Constraints。
- 计数修正：Task 8 累计 48 项，Task 9 卫生守卫后 49 项。
- 最终门裁决（2026-10-03）：UC-1 批准——路线图插入 P1.5 垂直切片（最小可用闭环前置，见 roadmap M0′/M0 修订）；许可证暂不选择（仓库私有期），Task 1 不创建 LICENSE，公开前经 TODO-006 选定。
<!-- /autoplan-accepted:eng -->
## Review record

<!-- autoplan-accepted:ceo -->
- 需求附录 R1（三平台支持）为本计划硬约束：全部代码/测试无 POSIX-only 假设；Task 7 UTF-8 流强化与 Task 8 CJK 往返测试必须落地；验证 = 本地 `python -m pytest -v` 全绿（49 项，含平台卫生守卫）+ ruff 干净 + 工作流就位；CI 门禁自远端建立起生效（见 Task 9 说明）。
- 需求附录 R2（文档格式）本计划仅继承约束（不含 docparse 实现）；P11/P13 计划必须实现 docparse 解析器注册表（ADR-009），传统二进制格式明确提示转换。
- 版本号单一来源：`src/ipostudio/__init__.py` 的 `__version__`，pyproject 用 hatch dynamic version；不得恢复双写。
- CLAUDE.md（技能路由规则）随 Task 1 首次提交入库。
- 规格 §11.2 全部键的默认值/校验/覆盖行为保持原计划要求不变（用户指令未触及）。
- 前向兼容：`config_version` 键 + "更高版本文件的未知键忽略、同版本拒绝"策略 + 测试（双声部共识，Task 3/4）。
- 秘密边界：`ConfigStore` 永不持久化 `*_api_key` 字段（Task 4 `CREDENTIAL_KEYS` + 测试）；P4 引入加密秘密库。
- 日志脱敏覆盖 traceback（两个 formatter 全格式重打码 + 泄漏测试，Task 5）。
- doctor 默认只读（不建目录、不迁移），`--fix` 显式修复 + 测试（Task 7）。
- ConfigStore 只写脏键并合并重读文件，多入口并发不互相覆盖、环境覆盖不落盘 + 测试（Task 4）。
- LICENSE（Apache-2.0，最终门可改 MIT）随 Task 1 入库。
- CI 增加 Python 3.11/3.12 版本维度；本地平台卫生守卫测试（`os.path.` 等禁用模式）作为 R1 补偿机制（Task 9）。
- 默认值一致性测试改为表驱动单一来源 `SPEC_DEFAULTS`（Task 3）。
- 迁移作者规则：SQL 迁移文件不得以无换行的 `--` 注释结尾（Task 6 注释 + 此处义务）。
- 三平台机器验证 = P2 入口条件（非 P1 已完成项）；P1 验收为本地等价口径 + 卫生守卫。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- README.md（先决条件/venv/安装/测试/快速开始/配置说明/M0 状态区分）与 CHANGELOG.md（0.1.0 unreleased）随 Task 1 入库。
- 错误信息契约（全 P1 表面 + 后续命令继承）：问题 + 出处（文件路径/环境变量名）+ 修复动作；未知键附 difflib 近邻建议；doctor 文本输出截断时显示 (+N)，`--json` 恒为全文；click 组 epilog 指向文档。
- `config_version` 回滚路径修复：新版本文件的未知键在分组前剔除（修复 KeyError），经 `load_config(env, warnings)` 收集告警，doctor 以 `[WARN]` 展示；有测试。
- `_read_toml` 捕获 `OSError` 与 `UnicodeDecodeError` 并给出修复指引；有测试（非 UTF-8 字节）。
- `ConfigStore.set(key, value)` 扁平签名；写入前经 schema 验证（失败回滚属性）；凭据键 `set()` 抛 ConfigError 指引环境变量；`save()` 从合并结果中剔除凭据键（含文件既有值）；临时文件按进程唯一（mkstemp）。
- doctor 默认严格只读：不 mkdir、不对既有库设 WAL、不创建日志文件（ro-uri 只读连接、临时探针即删）；data-dir 检查默认常驻（修复测试矛盾）；`--fix` 显式修复。
- 迁移标识 = 包内文件名（含 `.sql`）；测试对齐 `001_init.sql`。
- CLI 约定入 Global Constraints：`--json` 统一、组级 `--version/--config/--data-dir`、`guide --lang` 默认取 `ui_lang` 配置（坏配置回退 zh）。
- TODO-002（CLI 崩溃兜底 + --debug）、TODO-003（P1 后 /devex-review 回旋镖实测 TTHW）登记 TODOS.md。
- 残余风险记录：`_migrations` 含包内不存在的迁移名（新库旧码场景）时的守护检查归 P2 首个新迁移之前实现（current_version 已提供计数基础）。
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- 脱敏正则重写：左边界改 `(?<![A-Za-z0-9_-])`，键形覆盖 `[\w-]*token/password/secret`、`api[_-]?key`、`authorization`、`credential`、裸 `key`（URL `?key=`）；新增 URL 内嵌凭据模式；JSON 字段值经 kv 规则覆盖；新增形态测试（access_token=/AUTH_TOKEN:/gateway_api_key=/JSON/URL）。
- `migrate()`：BEGIN IMMEDIATE 后重读登记（并发迁移串行化）；失败显式 rollback 并抛 `MigrationFailure`（携迁移名），`_migrations` 保持干净、连接可复用；作者规则补全（以 `;`+换行结尾、不得自带 BEGIN/COMMIT、不得以无换行注释结尾）；坏迁移测试。
- `ConfigStore`：凭据键与 URL 内嵌凭据检查移到 `set()` 最前（拒绝后内存零变更）；候选模型验证成功才落值（规范化类型）；错误统一 `ConfigError`；`save()` 全程持跨进程 advisory lock（O_CREAT|O_EXCL，5s 超时，finally 清理）；失败清理临时文件并抛 ConfigError；测试覆盖（无变更拒绝/JSON 列表/环境变量归因/失败清理）。
- 环境列表支持 JSON 数组编码（逗号保留于值内）。
- doctor：探针改独占创建的唯一临时文件（不再覆盖/删除既有同名文件）；`--fix` 修复既有过时数据库（open_db+migrate）与部分目录布局；ro 打开失败（同步/锁定目录）降级为带指引的 PASS 注记；URI 路径 quote；每检查异常受纳（`--json` 永不中途死）；新增 fix-migrates-existing 测试。
- 多进程日志所有权决策：按进程分文件（ADR-006 修订 + TODO-004）。
- wheel 仓库外安装冒烟延后 M0（TODO-005）。
- 前向兼容范围限定与混合版本写策略入 Global Constraints。
- 计数修正：Task 8 累计 48 项，Task 9 卫生守卫后 49 项。
- 最终门裁决（2026-10-03）：UC-1 批准——路线图插入 P1.5 垂直切片（最小可用闭环前置，见 roadmap M0′/M0 修订）；许可证暂不选择（仓库私有期），Task 1 不创建 LICENSE，公开前经 TODO-006 选定。
<!-- /autoplan-accepted:eng -->



## Decision Audit Trail

<!-- AUTONOMOUS DECISION LOG -->
| # | Phase | Decision | Classification | Principle | Rationale | Rejected |
|---|-------|----------|-----------|-----------|----------|----------|
| 1 | CEO | 接受 R1 三平台支持进 P1（Task 9 CI 矩阵、UTF-8 强化、tzdata） | User directive | P1/P2 | 用户 2026-10-03 指令；爆炸半径内 <1 天 CC | 仅文档声明不做执行机制 |
| 2 | CEO | 接受 R2 文档格式：附录 + ADR-009，实现落 P11/P13 | User directive | P1/P2 | 用户指令；本阶段锁需求与架构，不提前实现 | 在 P1 提前引入解析库（YAGNI） |
| 3 | CEO | 版本单一来源（hatch dynamic） | Mechanical | P5 | 消除双写漂移 | 保留 pyproject 静态版本 |
| 4 | CEO | CLAUDE.md 路由规则随 Task 1 入库 | User directive | — | routing-instruction 门用户选 A；未建仓故并入首次提交 | 单独 pre-init 提交 |
| 5 | CEO | shell 补全延后 TODOS.md | Taste | P2 边界 | 真实便利、非本计划目标 | 现在实现 |
| 6 | CEO | config_version 前向兼容策略（回滚不炸配置） | Mechanical（双声部共识） | P1 | AUTO_UPDATE 默认开+beta 通道使回滚成为常态场景 | 保持纯拒绝（回滚即 doctor FAIL） |
| 7 | CEO | 凭据字段永不落盘（env-only 至 P4 秘密库） | Mechanical（安全） | P1 | 防止明文进入持久契约与用户自制备份 | 保持明文写盘 |
| 8 | CEO | 日志脱敏覆盖 traceback | Mechanical（安全） | P1 | 异常串是最可能泄漏路径（URL/argv） | 仅过滤消息正文 |
| 9 | CEO | doctor 默认只读 + --fix | Taste | P5 | 诊断命令不应悄然变更被诊断系统 | 保持隐式修复 |
| 10 | CEO | ConfigStore 脏键合并写 | Mechanical | P1/P2 | 多入口并发写互相覆盖（丢更新） | 整快照覆盖 |
| 11 | CEO | LICENSE(Apache-2.0) 入 Task 1 | Taste（最终门可改 MIT） | P1 | 洁净室卖点下 IP 姿态须最严谨 | 无 LICENSE |
| 12 | CEO | CI 加 3.11 维度 + 平台卫生守卫测试 | Mechanical | P1 | 声称 >=3.11 却只测 3.12 | 单版本 |
| 13 | CEO | 默认值测试表驱动单源 | Mechanical | P5 | 散布逐字断言随规格演进腐烂 | 保留长断言列表 |
| 14 | CEO | M0 走通骨架里程碑 + P2 入口切片 | Taste（附加性标注） | P1/P2 | 双声部共识：最致命风险未被前置验证 | 维持纯顺序路线图 |
| 15 | DX | README/CHANGELOG 入 Task 1 | Mechanical（双声部共识 HIGH） | P1/P5 | 前门缺失是 TTHW 最大乘数 | 维持无 README |
| 16 | DX | 错误信息契约（问题+出处+修复+建议） | Mechanical（双声部共识 HIGH） | P1 | 6 个错误点现在改便宜，P2+ 改昂贵 | 仅报键名 |
| 17 | DX | doctor 严格只读 + data-dir 常驻检查 | Mechanical（双声部共识，阻断级） | P1 | 修复自引入的测试矛盾与只读违约 | 维持会 mkdir 的实现 |
| 18 | DX | config_version 未知键分组前剔除（KeyError 修复） | Mechanical（Codex HIGH） | P1 | 承诺的回滚路径原会崩溃 | 仅跳过报错 |
| 19 | DX | ConfigStore 扁平 set + 前置验证 + 凭据剔除/拒绝 + 唯一临时文件 | Mechanical（Codex HIGH） | P1 | 防止"保存成功但下次加载炸"与凭据复写 | 保持无验证写入 |
| 20 | DX | --json 统一 + 组级 --version/--config/--data-dir + guide --lang 取配置 | Taste | P5/P2 | 约定现在定，P2-P21 全部继承 | 各命令各风格 |
| 21 | DX | 迁移名含 .sql 对齐 | Mechanical（Codex） | P1 | 测试与实现不一致即阻断 | 只改测试 |
| 22 | Eng | 脱敏正则左边界重写 + URL/JSON 形态 | Mechanical（双声部共识，安全） | P1 | \b 对下划线前缀键永不命中 | 保留旧正则 |
| 23 | Eng | migrate 并发安全 + 失败回滚 | Mechanical（双声部共识） | P1 | 半事务与重复迁移会腐蚀后续全部域表 | 仅加 try/except |
| 24 | Eng | ConfigStore 锁 + 拒绝零变更 + 统一错误面 | Mechanical（双声部共识） | P1 | 丢更新/内存残留秘密/三种异常类型 | 只修其中一项 |
| 25 | Eng | doctor --fix 修既有库 + 唯一探针 + 受纳 | Mechanical（双声部共识） | P1 | 修复承诺不成立 + 会删用户同名文件 | 仅文档说明 |
| 26 | Eng | 多进程日志=按进程分文件 | Taste（Codex 要求 P1 定） | P5 | 决策现在定，P3 实现前提明确 | 单写者进程（过度设计） |
| 27 | Eng | env 列表 JSON 编码 + 环境归因 + URI quote | Mechanical | P1 | 含逗号参数会被撕碎；错误指向错误出处 | 维持逗号拆分 |
| 28 | Gate | UC-1 批准：P1.5 垂直切片前移（最小闭环前置） | User decision（最终门） | P1/P2 | 用户明确批准双声部建议 | 维持纯顺序（被否决） |
| 29 | Gate | 许可证暂不选择：不创建 LICENSE，TODO-006 挂公开前 | User decision（最终门） | P1 | 用户裁决仓库暂私有 | 按 Apache-2.0 写入（被否决） |

### CEO 阶段审查记录（2026-10-03，SELECTIVE EXPANSION）

**0I 时间轴质询**：H1 需知——src-layout+`pythonpath=["src"]`（免安装跑单测）、hatch dynamic version 单源；H2-3 歧义——`_coerce_env` 的 Optional/none 语义、TOML 扁平无节、`sorted(env)` 错误行序；H4-5 意外——CliRunner 与 `_force_utf8_streams` 交互（isatty 守卫）、Windows `Path.home()` 读 USERPROFILE、数据目录出现 WAL 伴生文件属正常；H6+ 早知——无远端时的本地等价验收、迁移作者规则、网关进程复用 `setup_logging` 的幂等清理。

**CEO 双声部共识表**：

```
维度                          Claude            Codex             共识
1 前提有效？                  部分（配置冻结/   部分（验证前提     部分成立：前向兼容与
                              引擎名录未论证）   未落实）          验证机制前提需补（已补）
2 解对问题？                  是，但未前置致命  挑战：用户价值     方向可接受+需前置价值
                              风险的学习        验证缺失          验证（M0/切片已加）
3 范围标定？                  范围对、验收口径  P1 范围可、验收    范围合适；验收口径已
                              过度              声明过度          降为本地等价（已修）
4 备选充分探索？              3 处缺口          外部转换未实测     少数备选已补记/挂 P13 义务
5 竞争/市场风险？             护城河未定义      首发工作流未定义   需定义楔子功能→用户挑战
6 六个月轨迹？                顺序悔恨风险      安装验证太晚       M0 里程碑+切片（已加）
CONFIRMED = 双声部均完成（Claude 原生 + Codex 外部，provider=codex host=claude，
完成标记经一次英文重述后过官方校验器）
```

**分节结论**（无发现处说明审查了什么）：
1 架构：发现 2 项（多进程并发写丢更新→脏键合并写；ADR 可逆性缺失→已补记）；2 错误与救援：见登记簿，3 处 GAP 全部补救援；3 安全：发现 3 项（traceback 绕过脱敏、凭据明文持久化、doctor 突变状态）全部修复；4 数据流边界：配置文件 nil/空/损坏/未知键/新版本五路径均有测试；5 代码质量：默认值断言腐烂风险→表驱动；6 测试：新增 4 测试（脏键/凭据不落盘/新版本忽略/traceback 脱敏/doctor --fix/卫生守卫=实际 +6，总 37→38 含卫生守卫）；7 性能：P1 无热路径，无发现；8 可观测：redaction_count 已有，traceback 取证补齐；9 部署：CI 版本维度补齐；R1 验证分期；10 长期轨迹：可逆性评分 4/5（配置/路径可迁、SQLite 单库可导出），M0 债务上限；11 设计：SKIPPED（无 UI 范围）。

**Error & Rescue 登记簿**（实现就绪深度）：

```
方法/路径                     | 可能出错                 | 异常类            | 救援? | 动作                     | 用户所见
load_config                   | TOML 语法坏              | ConfigError       | Y    | 键级错误行               | doctor FAIL+键名
load_config                   | 同版本未知键             | ConfigError       | Y    | 拒绝并列键名             | 明确拒绝（§11.1）
load_config                   | 新版本未知键（回滚）     | -                 | Y    | 忽略                     | 正常启动
_coerce_env                   | 布尔/数值无法转换        | ValueError→ConfigError | Y | 键级错误行               | doctor FAIL
ConfigStore.save              | 目标目录只读             | OSError           | Y    | 上抛（调用方 doctor 捕获）| FAIL+原因
setup_logging                 | 日志目录不可写           | OSError           | N←GAP(已修) | doctor 预检 logs 可写 | 提前 FAIL
migrate                       | 脚本中途崩溃             | sqlite3.Error     | Y    | BEGIN/COMMIT 原子回滚    | 下次重试
redact_text                   | 非模式化高熵秘密         | -                 | N    | 文档声明残余风险         | 文档
doctor(_check_database)       | db 损坏                  | sqlite3.Error     | Y    | FAIL+原因                | 可诊断
```

**失效模式登记簿**：

```
路径                 | 失效模式            | 救援? | 测试? | 用户所见   | 记录?
load_config          | 损坏 TOML           | Y     | Y     | 错误行     | Y
ConfigStore.save     | 并发丢更新          | Y     | Y     | 无感       | Y
ConfigStore.save     | 凭据落盘            | Y     | Y     | 无感       | Y
setup_logging        | traceback 泄密      | Y     | Y     | 打码日志   | Y
migrate              | 半应用迁移          | Y     | Y*    | 无感       | Y (*原子性由脚本结构保证)
doctor               | 诊断即变更          | Y     | Y     | 显式 --fix | Y
CLI 输出             | Windows 管道编码    | Y     | Y     | 正常 CJK   | -
```
CRITICAL GAP：0。

**NOT in scope**（含理由）：shell 补全（TODOS.md TODO-001）；云端凭据加密存储（P4 秘密库，义务已登记）；配置 2s 跨进程监听、逐键生效标注、地址区分（P3/P4，已记录）；§9.12 扩展命令全集（P21）；文档格式解析实现（P11/P13，仅约束继承）；阶段重排/楔子功能定义（→用户挑战，未批不动）。

**What already exists**：`CLAUDE.md`（路由规则，入库）；`docs/design/*`（架构/路线图/附录，本次审查的设计输入）；其余为全新实现（洁净室绿地）。

**Dream state delta**：现状（空仓库+三份设计文档）→ 本计划后（可安装包 + 配置/日志/存储/CLI 地基 + CI 矩阵 + 平台守卫，M0 前一切基建就绪）→ 12 个月理想（规格 26 域全交付的本地优先工作台）。本计划是理想形态的承重地基，不产生直接用户价值（已由 M0/P2 切片对冲顺序风险）。

**Implementation Tasks（CEO 阶段）**：
- [ ] **T1 (P1, human: ~2h / CC: ~15min)** — conf — config_version 前向兼容与凭据不落盘（Task 3/4 修正项）
  - Surfaced by: CEO 双声部共识（Claude F3 / Codex #5#6）
  - Files: src/ipostudio/conf/{schema,loader}.py, tests/conf/test_loader.py
  - Verify: `python -m pytest tests/conf -v`
- [ ] **T2 (P1, human: ~1h / CC: ~10min)** — logs/cli — traceback 脱敏 + doctor 只读化（Task 5/7 修正项）
  - Surfaced by: CEO F6/F8 + Codex #5
  - Files: src/ipostudio/logs.py, src/ipostudio/cli/main.py, tests/test_logs.py, tests/cli/test_main.py
  - Verify: `python -m pytest tests/test_logs.py tests/cli -v`
- [ ] **T3 (P1, human: ~1h / CC: ~10min)** — build — LICENSE + CI 版本矩阵 + 平台卫生守卫（Task 1/9 修正项）
  - Surfaced by: CEO F11 + 版本矩阵发现
  - Files: LICENSE, .github/workflows/ci.yml, tests/test_platform_hygiene.py
  - Verify: `python -m pytest tests/test_platform_hygiene.py -v`

**完成摘要（CEO）**：模式 SELECTIVE_EXPANSION；系统审计=空仓库绿地+三份设计文档；提案 5、接受 4、延后 1；规范审查 2 轮 8→9/10（13 发现全修）；双声部 CONFIRMED（12+7 发现，交叉 4 组）；未解决决策=2 项用户挑战 + 1 项许可证选择（见最终门）；Lake Score 4/4（覆盖类决策全选完整选项）。

### DX 阶段审查记录（2026-10-03，DX POLISH，CLI Tool）

**Persona（0A，文档推断）**：本地模型高级用户兼开发者——终端里管理 GGUF、把网关接进编码工具；对安装的耐心以分钟计；期望 pip 装完即 `ipo doctor` 全绿。

**共情叙事（0B）**：我克隆了仓库。pyproject 说要 Python 3.11+，我先建了 venv。`pip install -e ".[dev]"` 一次过。`ipo version` 出来了——好。`ipo doctor`：config PASS、data-dir 说"not created yet"、database 说"not initialized"、logs 同样——没有红色，没有惊吓，每行都告诉我下一步（--fix）。我改了一个端口写进 settings.toml，手滑打成 `server_prot`——doctor 直接告诉我"did you mean 'server_port'?"和该删哪一行。我顺手 `IPO_SERVER_PORT=99999 ipo doctor`，它说超范围并让我修 shell。前 5 分钟我知道了：这工具坏了会说话。（0G 角色扮演验证同此路径，T+3:00 成功。）

**竞争基准（0C）**：Ollama（mac/win/linux 一键安装 + `ollama run`，约 2 分钟，reported）、LM Studio（GUI 安装器，约 3 分钟，reported）、Jan（桌面安装器，约 3 分钟，reported）；ipostudio P1 = 源码安装 3 步约 3 分钟（estimated，无分发轮子）。**目标档位：Competitive（2-5 分钟）**；Champion（<2 分钟）待 PyPI/安装器分发（M0 后评估）。说明：P1 的"hello world"是 doctor 全绿；模型级 hello world 在 M0（roadmap 已注明区分）。

**魔法时刻（0D）**：`ipo doctor` 全绿 + 每行带下一步——最低成本载体已在计划内（现有能力，DX POLISH 边界内）。

**开发者旅程图（0F/9 段）**：

```
阶段          | 开发者做什么                    | 摩擦点                     | 状态
1 Discover   | 读 README                      | 无 README（HIGH）          | fixed（Task 1 Step 5.5）
2 Evaluate   | 读 LICENSE/CHANGELOG/docs 树    | 缺 CHANGELOG               | fixed（Step 5.8）
3 Install    | venv + pip install -e ".[dev]" | venv 指引缺失              | fixed（README）
4 Hello World| ipo version → ipo doctor       | —                          | ok（3 步 ~3 分钟）
5 Real Usage | ipo guide / 配置覆盖           | guide 无选项值/示例/配置参考 | partial（collect_command_docs 补默认值与选项元数据——记 P2 改进项）
6 Debug      | doctor FAIL 行 + 错误契约       | 无修复指引（HIGH）          | fixed（契约全文落地）
7 Upgrade    | config_version 回滚 + CHANGELOG | 回滚 KeyError（HIGH）       | fixed（分组前剔除+告警）
8 Extend     | 加配置键（SPEC_DEFAULTS 表驱动） | —                          | ok
9 Contribute | TODOS.md 范本 + 测试即文档      | —                          | ok
```

**首次开发者困惑报告（0G）**：见共情叙事路径；两个预测困惑（guide 混语言正文、--json/--format 并存）已分别以 ui_lang 默认与约定统一处理。

**Passes 1-8（修复后评分）**：1 起步 8（README+3 步；无分发轮子扣分）；2 API/CLI 8（约定统一、逃生口齐、写入前验证）；3 错误 8（契约+建议+截断计数；无文档站扣分）；4 文档 7（README/guide/计划自证；无教程库）；5 升级 8（config_version+回滚+CHANGELOG；DB 新库旧码守护记 P2 义务）；6 环境 8（CI 3×2、卫生守卫、免安装跑测试）；7 社区 5（LICENSE+TODOS 范本；无 CONTRIBUTING/渠道——预发布阶段延后）；8 度量 5（TODO-003 回旋镖已立；无插桩）。

**DX Scorecard**：

```
+====================================================================+
|              DX PLAN REVIEW — SCORECARD                             |
+====================================================================+
| Dimension            | Score | Prior | Trend |
|----------------------|-------|-------|-------|
| Getting Started      |  8/10 |  5    | ↑     |
| API/CLI/SDK          |  8/10 |  6    | ↑     |
| Error Messages       |  8/10 |  4    | ↑     |
| Documentation        |  7/10 |  5    | ↑     |
| Upgrade Path         |  8/10 |  6    | ↑     |
| Dev Environment      |  8/10 |  7    | ↑     |
| Community            |  5/10 |  4    | ↑     |
| DX Measurement       |  5/10 |  3    | ↑     |
+--------------------------------------------------------------------+
| TTHW                 | ~3 min (est.) | target 2-5 min | Competitive |
| Competitive Rank     | Competitive                                   |
| Magical Moment       | designed via `ipo doctor` all-PASS            |
| Product Type         | CLI Tool (foundation phase)                   |
| Mode                 | DX POLISH                                     |
| Overall DX           | 7/10                                          |
+--------------------------------------------------------------------+
| Zero Friction covered | Learn by Doing covered | Fight Uncertainty covered |
| Opinionated+Escape covered | Code in Context partial(guide) | Magical Moments covered |
+====================================================================+
```

**DX 双声部共识表**：

```
维度                          Claude            Codex             共识
1 起步 <5 分钟？              是（3 步）但缺 README  6 步估算/无快速开始  共识：README 必补（已补）
2 API/CLI 命名可猜？           是；--json/--format 分裂  一致性不足        共识：约定统一（已统一）
3 错误信息可行动？             无修复指引（HIGH）    结构化失败缺失（HIGH） 共识：契约落地（已落地）
4 文档可发现？                 guide 自证良好       guide 不答首用问题   部分共识：选项值/示例记 P2 改进
5 升级无惧？                  config_version 强    回滚路径会崩（HIGH）  共识：KeyError 修复（已修）
6 开发环境无摩擦？             CI/免安装佳          wheel 冒烟缺失      部分共识：分发测试记 M0 后
CONFIRMED = 双声部均完成（Claude 原生 10 发现 + Codex 外部 7 发现，交叉 4 组）
```

**NOT in scope（DX）**：PyPI/安装器分发与 wheel 冒烟（M0 后评估）；guide 选项值/示例/配置参考全文（P2 改进项，collect_command_docs 扩展）；CONTRIBUTING.md 与社区渠道（公开发布前）；文档站与搜索（DOCS_BASE 占位）；TTHW 插桩（TODO-003 手动回旋镖替代）。

**What already exists（DX）**：`collect_command_docs()` 单源命令参考（三格式导出）；TODOS.md 范本结构；CLAUDE.md 路由；docs/design 树。

**Implementation Tasks（DX 阶段）**：
- [ ] **T4 (P1, human: ~2h / CC: ~15min)** — conf — 错误契约 + config_version 告警通道 + 只读读取防护（Task 4 重写项）
  - Surfaced by: DX 双声部（Claude F3 / Codex #1#3）
  - Files: src/ipostudio/conf/loader.py, tests/conf/test_loader.py
  - Verify: `python -m pytest tests/conf/test_loader.py -v`（13 passed）
- [ ] **T5 (P1, human: ~2h / CC: ~15min)** — cli — doctor 严格只读 + 组级选项 + guide 配置语言（Task 7 重写项）
  - Surfaced by: DX 双声部（Claude F1 / Codex #2）
  - Files: src/ipostudio/cli/main.py, tests/cli/test_main.py
  - Verify: `python -m pytest tests/cli/test_main.py -v`（9 passed）
- [ ] **T6 (P1, human: ~1h / CC: ~10min)** — build — README + CHANGELOG + 约定行 + 迁移名对齐（Task 1/6）
  - Surfaced by: DX 双声部（Claude F2/F10 / Codex #4#7）
  - Files: README.md, CHANGELOG.md, tests/store/test_database.py
  - Verify: `python -m pytest tests/store -v` + README 存在

### Eng 阶段审查记录（2026-10-03，SELECTIVE_EXPANSION·Eng 最后运行）

**Scope Challenge**：绿地计划——全部子问题无既有代码可复用（What already exists = 标准库+四个许可证兼容依赖）；最小变更即 9 任务本身；复杂度检查：15 个新文件、4 个新类 → 触发结构门 → 自动决策：**Original arrangement**（更小编排必须裁掉已批准的安全/DX 修正，违背 P2）；TODOS 交叉引用完成（TODO-001~005）。

**ENG 双声部共识表**：

```
维度                          Claude            Codex             共识
1 架构健全？                  是；分层干净       是；多进程缺口     共识：单进程健全；多进程风险已登记（锁+日志决策）
2 测试覆盖充分？              7 个 2am 缺口      并发/故障边界缺失  共识：补 7+ 测试（已补：形态/迁移回滚/fix-migrate/清理/归因/JSON）
3 性能风险已处理？            P1 无热路径        同                共识：无发现（10x 风险均在多进程延后项）
4 安全威胁已覆盖？            脱敏正则缺陷(M1)   边界只 3 键(#5)    共识：正则重写 + URL 凭据扫描（已修）
5 错误路径已处理？            迁移无回滚(M3)     set 先改后拒(#4)   共识：全部修复（回滚/锁/统一错误面）
6 部署风险可控？              CI/无远端已分期    wheel 未验证(#11)  共识：wheel 冒烟延后 M0（TODO-005）
CONFIRMED = 双声部均完成（Claude 原生 6M+7L+INFO / Codex 外部 7H+4M，交叉 6 组）
```

**Section 1 架构**（依赖图）：

```
                    ┌────────────────────────────┐
                    │  ipo (click)  cli/main.py  │← __main__.py / console_script
                    └──────┬──────────┬──────────┘
                           │          │
                ┌──────────▼──┐   ┌───▼─────────────────┐
                │ conf/loader │──▶│ store/database+migr │
                │ (锁/验证)   │   │ (BEGIN IMMEDIATE)   │
                └──┬─────▲────┘   └──────────┬──────────┘
                   │     │                   │
             ┌─────▼─────┴────┐        ┌─────▼─────┐
             │ conf/schema    │        │ 001..NNN  │
             │ (extra=forbid) │        │  .sql     │
             └─────▲──────────┘        └───────────┘
                   │        ┌──────────────┐
             ┌─────┴────────│ logs.py      │（双层脱敏+traceback）
             │ conf/paths   │（唯一被 CLI/加载/日志共用的地基）
             └──────────────┴──────────────┘
耦合：领域零横向依赖；cli→conf/store/logs 单向；无环。
```

单点故障：settings.toml（原子写+锁缓解）；app.db（WAL+busy_timeout+迁移锁）。生产失败场景每路径一个：坏 TOML→doctor FAIL 带修复句；锁超时→ConfigError 指引；迁移失败→回滚+MigrationFailure；并发写→advisory lock 串行。部署：CI 3×2 矩阵；wheel 冒烟 M0。

**Section 2 代码质量**：DRY——`_suggest`/`_unique_probe`/`_advisory_lock` 均单点；命名按行为（`from_newer_build`、`_contained`）；复杂度热点 `load_config` 分支 ~8 → 已按职责分段（读取/环境/未知键/分组）注释化；无过度抽象（未提前建 config-watcher）。发现 0 项新增（双声部所列均已修复）。

**Section 3 测试审查**（覆盖图）：

```
CODE PATHS                                              USER FLOWS
[+] conf/paths.py                                        [+] 安装→doctor 全绿（README 快速开始）
  ├── [★★★ TESTED] 默认/覆盖/幂等 (5)                     ├── [★★★ TESTED] smoke×3 + doctor 全链
  └── [★★  TESTED]  无 .resolve()（INFO 已记）             └── [GAP→E2E] 真实 wheel 仓库外安装（TODO-005, M0）
[+] conf/schema.py
  ├── [★★★ TESTED] 表驱动默认值/枚举/未知键 (4)
[+] conf/loader.py
  ├── [★★★ TESTED] 缺省/覆盖/强制转换/坏TOML/非UTF8 (8)
  ├── [★★★ TESTED] 新版本告警+剔除/建议/归因/JSON列表 (5)
  └── [★★★ TESTED] store: 往返/脏键+凭据剔除/零变更拒绝/失败清理 (4)
[+] logs.py
  ├── [★★★ TESTED] 形态矩阵/轮转/JSONL/回溯泄密/幂等 (6)
[+] store/database.py
  ├── [★★★ TESTED] WAL/幂等原子/坏迁移回滚 (3)
[+] cli/main.py
  ├── [★★★ TESTED] version/help/guide(语言)/组旗标/doctor 四态 (10)
[+] 平台卫生守卫 (1)
COVERAGE: 43 计划内测试全映射（48+1=49 计数一致）；GAPS: 2（wheel E2E→M0；组级 --config 端到端→P2 补）
LLM/EVAL: 无（P1 无模型调用）
```

**测试计划工件**：已写 `<gstack project dir>/eng-review-test-plan-<ts>.md`（见下）。

**Section 4 性能**：无 N+1（单文件读）；内存峰值 = settings 全量字典（<100 键）+ 单条日志缓冲；缓存不适用；慢路径 = doctor ro 打开（同步目录降级路径已护）；busy_timeout 5s/锁 5s 上限防挂死。无发现。

**失效模式登记簿（Eng 汇总，含此前阶段）**：CEO 表 + 本阶段新增：

```
路径                     | 失效模式              | 救援? | 测试? | 用户所见        | 记录?
redact 覆盖不足          | 下划线/URL 形态漏脱敏  | Y     | Y     | 打码日志        | Y
migrate 并发双跑         | 重复应用              | Y     | Y*    | 无感            | Y (*BEGIN IMMEDIATE 结构保证+单进程测试)
migrate 中途失败         | 半事务残留            | Y     | Y     | MigrationFailure | Y
ConfigStore 并发 save    | 丢更新                | Y     | Y     | 锁等待/超时报错  | Y
set 拒绝后内存残留        | 秘书驻内存            | Y     | Y     | 无感            | Y
doctor 探针覆盖既有文件   | 删除用户文件          | Y     | Y     | 无感            | Y
--fix 不修既有库         | 升级路径断裂          | Y     | Y     | 修复生效        | Y
save 失败临时残留        | 磁盘垃圾              | Y     | Y     | 无感            | Y
多进程日志轮转竞态       | 丢日志/损坏           | TODO-004(P3前) | - | 延后登记      | Y
```
CRITICAL GAP：0（全部有救援+测试或显式延后登记）。

**NOT in scope（Eng）**：wheel 构建与仓库外安装（M0/TODO-005）；多进程日志实现（P3/TODO-004，决策已定）；单写者日志进程（否决）；组级 --config/--data-dir 端到端测试（P2 首个消费者计划补）；`platform.system()` 类卫生守卫盲区（CI 为真门禁，守卫如实标注为补偿控制）。

**What already exists**：Python 标准库（tomllib/sqlite3/logging/tempfile/difflib/urllib）；依赖 pydantic/click/tomli-w（复用阶梯第 3-4 级）；无本项目既有代码。

**Dream state delta / 完成摘要（Eng）**：模式 SELECTIVE_EXPANSION（autoplan 覆盖：范围不缩减 P2）；系统审计=绿地；双声部 CONFIRMED（6M+7L+INFO 原生 / 7H+4M 外部，交叉 6 组全修）；自动决策 6 项（#22-27）；未解决决策 = 沿袭 CEO 2 项用户挑战 + 1 项许可证选择（最终门）；Lake Score 6/6；产生测试 49；测试计划工件已写盘。

**Implementation Tasks（Eng 阶段）**：
- [ ] **T7 (P1, human: ~3h / CC: ~20min)** — logs/store — 脱敏形态矩阵 + 迁移并发/回滚（Task 5/6 修正项）
  - Surfaced by: Eng 双声部 M1/M3/Codex#3#6
  - Files: src/ipostudio/logs.py, src/ipostudio/store/database.py, 对应测试
  - Verify: `python -m pytest tests/test_logs.py tests/store -v`（6+3 passed）
- [ ] **T8 (P1, human: ~3h / CC: ~20min)** — conf/cli — 存储锁与零变更拒绝 + doctor 修复既有态（Task 4/7 修正项）
  - Surfaced by: Eng 双声部 M2/M4/M6/Codex#1#8
  - Files: src/ipostudio/conf/loader.py, src/ipostudio/cli/main.py, 对应测试
  - Verify: `python -m pytest tests/conf tests/cli -v`（16+10 passed）

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/autoplan` (plan-ceo-review) | Scope & strategy | 1 | ISSUES OPEN | 5 proposals, 4 accepted, 1 deferred; spec-loop 2 轮 8→9/10（13 发现全修）|
| Outside Review | codex via /autoplan | Independent 2nd opinion | 3 (ceo/dx/eng) | completed | ceo 7 concerns / dx 7 / eng 11；完成标记经一次英文重述后过官方校验器 |
| Eng Review | `/autoplan` (plan-eng-review) | Architecture & tests (required) | 1 | ISSUES OPEN | 双声部 24 发现（6M+7L 原生 / 7H+4M 外部），交叉 6 组全修，CRITICAL GAP 0 |
| Design Review | — | UI/UX gaps | 0 | skipped | 无 UI 范围（Phase 0 检测）|
| DX Review | `/autoplan` (plan-devex-review) | Developer experience gaps | 1 | ISSUES OPEN | 双声部 17 发现（10 原生 / 7 外部），交叉 4 组全修；评分 5-6 → 7/10 |

- **OUTSIDE COVERAGE:** provider=codex, host=claude；phases ceo/dx/eng 均 completed（validator PASS）；design skipped（无 UI 范围）。codex 完成标记一次因中文"因为"未过校验器，经一次 resume 英文重述后通过——内容未变。
- **CROSS-MODEL:** Claude(原生) × Codex(外部) 在三阶段共 10 组交叉发现全部收敛并修复；无未决技术分歧。
- **VERDICT:** **APPROVED**（用户 2026-10-03 批准计划及其修改，暂不执行）。CEO + DX + ENG 技术发现全部清偿（CRITICAL GAP 0）；用户挑战与许可证均已裁决并入（P1.5 前置 / LICENSE 延迟 TODO-006）。

**UNRESOLVED DECISIONS:**（无）

NO UNRESOLVED DECISIONS

