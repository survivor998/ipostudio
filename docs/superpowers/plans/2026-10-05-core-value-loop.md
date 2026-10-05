# Core Value Loop Implementation Plan（`ipo start/server/models` 最小闭环）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真实产品命令打通最小价值闭环——扫描本地 GGUF 模型（`ipo models`）→ 激活（`ipo model --select`）→ 启动 llama.cpp 服务（`ipo server start`）→ 一次补全（`ipo chat`）→ 记录落 SQLite 与日志 → 重启可查（`ipo status` / `ipo server info`）。

**目标用户（Codex CEO 折叠）：** 熟悉终端、能自行安装 llama.cpp 并下载模型权重的本地 LLM 熟手；新手路径（引擎安装/模型下载引导）由 P2 下载器承接，本计划不以新人为验收对象。`ipo chat` 在本计划中定位为冒烟/诊断探针（单轮、非流式），交互式对话体验随 P6 流式与 NDJSON 事件落地（TODO-018）。

**Architecture:** 引擎监督采用"CLI 进程即起即走 + SQLite 行即协调点"（ADR-004 的最小形态）：`ipo server start` spawn 引擎子进程后退出，引擎成为孤儿进程继续服务；后续 stop/status 在新进程里读数据库行 + 实时健康探测。状态机字面量取规格 §10.2 服务态，由数据库 CHECK 约束钉死。模型目录扫描与引擎发现均为纯函数层，CLI 只做编排。

**Tech Stack:** Python ≥3.11 标准库（urllib/socket/sqlite3/subprocess/shutil）+ 既有 click 8 / pydantic v2 基座；**零新增运行时依赖**。

**Spec:** `Functional Specification v1.0.md` §5.2（F02 本地管理切片）、§5.3（F03 最小切片）、§9.11（`start`/`status/stop/restart`/`server`/`models`/`model`/`model-info`）、§9.12（CLI 对话）、§10.1/§10.2（持久化与服务状态）、§11.2（配置键）、§12.1/§13（错误与空态）、§15（端口/超时）；设计依据 `docs/design/architecture.md`（ADR-002/003/004/006/008/010）、`docs/design/roadmap.md`（M0′/M0、P1.5）、`docs/design/requirements-addendum.md`（R1）。

## Implementation plan

---

---

## 排位与范围裁决（计划作者裁决，评审管线可攻击）

承接 2026-10-04 CLI-UX 计划头部的排位裁决：本计划即**核心回路计划**（P1.5/P2 混合切片），是全部后续计划的下一个执行对象；它强制继承 CLI-UX 计划建立的呈现/错误/退出码契约。本计划自身的范围裁决：

1. **无下载命令、无引擎自动安装**。P1.5 原案允许一次性脚本做装引擎/下模型；本计划升级为产品命令后，这两个动作保持**手动**（README 给出三平台安装与 GGUF 放置指引），可续传下载器（ADR-005、T02/T03/T04）完整留给 P2，不造会被 P2 重写的一次性下载面。
2. **单实例**。T05（双模型独立地址）/T06（停一个其他继续）按路线图留 P3；但 `instances` 表为每实例一行，不预设多实例障碍。
3. **`ipo chat` 非流式**（§9.12 授权 CLI 对话；流式/NDJSON 事件流留 P6/P7）。命令名为本计划自主设计（规格 1.3/9.12：扩展命令语法后续自定，不保留来源项目旧名）。
4. **doctor 不加第五项检查**。缺引擎/缺模型报告由 `ipo models` 空态与 `ipo server start` 错误承载（ADR-010"缺引擎明确报告"）；doctor 四项 JSON 契约不动。
5. **引擎 detach = 孤儿进程**。不用任何平台专属 detach API（R1）；M0′ 已知限制三平台对称：关闭启动它的终端可能连带引擎退出，常驻后台服务是 P3 范围。
6. **stop 的所有权守卫**：仅在"记录的端口仍以健康文档应答"时才发 kill 信号（PID 重用与端口被占时盲杀是真实风险）；进程身份加固（create_time 比对）记 TODOS 留 P3。
7. **`ipo model-info NAME` 的 NAME 必填**。可选参 + 无激活模型会让 QA 的 `--json` 注册表 walker 在全新数据目录上拿到 exit 1；必填参让 walker 按既有规则跳过，JSON 洁净由专属测试钉。
8. **`--select` 不自动重启运行中的服务**（副作用最小化），输出指引 `ipo server restart`。
9. **欢迎卡三步更新为 doctor --fix / models / guide**（状态感知箭头：未初始化→doctor，已初始化→models）；完整首跑向导继续推迟（继承 CLI-UX 排位裁决第 3 项）。
10. **auto_tune / idle_unload / fallback_models 非默认值时 stderr 明确"尚未实现"警告**（规格 1.3 规则 3：预留能力明确标注），行为退回用户配置值。
11. **显式 `--port` 不做端口避让**（用户点名即如实执行，占用则引擎绑定失败并如实报告）；仅**配置的** `server_port` 被占时按 §5.3 选择可用端口并展示实际地址。
12. **`ipo model --select` / `ipo model-info` 先刷新扫描再解析**——用户放入模型文件后无需先跑 `ipo models` 即可直接选。
13. 本计划 8 任务 timebox；评审与执行中的"顺手"改进一律记 TODOS 不实施（继承排位裁决）。
14. **M0 债务上限的诚实标注（CEO 评审 #3）**：原 M0′ 案是 ≤2 天一次性探针；本计划按 2026-10-04 排位裁决升级为真实产品命令，工程面大于探针——这是用户裁决的形态变更，不是 debt-cap 违约，但计划承认其信息增益低于探针（真实引擎/真实用户两项高风险未知仍被推迟），故 Task 8 的 roadmap 回写以真机冒烟为 P2 入口最终标准（见 Task 8 回写门），且 supervisor/completions/instances 按 P3/P6 演进已在 ADR-011 登记为脚手架件。

## Global Constraints（每个任务隐式继承）

- **洁净室 IP 约束**：不得复制、改写、翻译、转写、结构性重构或近似复现任何第三方项目的源代码；不得通过修改变量名/函数名/调整代码顺序/拆分合并函数/语言翻译/同义改写等方式规避；不得保留第三方识别性注释、错误消息、内部名称、魔法数字。实现依据仅限：本规格正文、公共协议（HTTP/OpenAI Chat Completions/llama-server 公开命令行）、公开标准与许可证兼容依赖。llama-server 的命令行旗标与 `/health`、`/v1/chat/completions` 行为按其**公开文档**对待。
- 命名：CLI `ipo`、环境前缀 `IPO_`（规格 §1.2）。除规格强制名外一切内部命名独立设计。
- **R1**：Windows/Linux/macOS 三平台一级支持；`src/` 内禁止 `os.name` / `sys.platform` 分支与 `os.path.` 调用（`tests/test_platform_hygiene.py` 为守卫）；一律用 pathlib / `shutil.which` / `subprocess.Popen` / `os.kill` 等跨平台 API。平台行为差异（如 Windows `os.kill` = TerminateProcess 硬杀）只允许出现在注释与文档中，不允许出现分支代码。测试代码允许 `sys.platform`（守卫只扫 src/），但本计划测试同样不需要。
- R2（docparse）本计划不涉及（P11/P13 落地）。
- Python ≥3.11（可用 `datetime.UTC`；`Path.is_dir(follow_symlinks=)` 是 3.12+ 参数，目录遍历用 `os.scandir` 的 `entry.is_dir(follow_symlinks=False)`）；pydantic v2；click ≥8.1；SQLite WAL 沿用 `store/database.py`，**不新增运行时依赖**。
- 退出码：成功 0；click 用法错误 2；运行失败 1（规格 §9.11"失败非零退出"）。
- 错误契约（继承 CLI-UX 计划）：每条错误 = 问题 + 来源 + 修复指引；错误走 stderr；stdout 保持机器可解析。
- `--json` 字节干净（无 ANSI、可 `json.loads`）；QA walker（`tests/qa/test_cli_ux_adversarial.py`）会**自动**把新增的无必选参 `--json` 命令纳入覆盖——新命令在全新数据目录上无参调用必须 exit 0。
- 凭据永不落盘、永不明文回显（本计划引擎面无密钥，但不得引入任何凭据回显路径）；交换内容在**持久化边界**经 `redact_text` 脱敏后才入 `completions` 表（Codex 三声部信任折叠：展示期脱敏无法追回已落盘内容），QA 以真实形状密钥样本断言库内无泄漏。
- 服务状态字面量 = 规格 §10.2 五态的英文本位设计：`stopped` / `starting` / `loading` / `running` / `failed`，由 `003_instances.sql` 的 CHECK 约束钉死；下载态字面量本计划不涉及（P2）。
- 端口候选扫描上限约 20（规格 §15"网关端口最多约 20 候选"同理适用）；本地推理超时默认 600 秒（规格 §15"本地 600 秒"）。
- 多进程日志（TODO-004 / ADR-006 修订）：引擎子进程 stdout/stderr 重定向到按进程命名的日志文件 `logs/engine-llama-cpp.log`，**不**经 `RotatingFileHandler`。
- TDD 红绿循环：每任务先写失败测试再实现；每任务结束跑全量测试 + ruff 再提交。
- 解释器：**只用 `.venv/Scripts/python.exe`**（系统 python 缺 tomli_w，bare `python` 采集即炸）；venv 内 click 实际为 **8.5.0**；测试基线 **191 passed** + ruff 全绿。
- click 8.5 事实：`CliRunner` 下 `Result.output` 混合 stdout+stderr（对 stderr 敏感的断言用 `.stdout` / `.stderr`，或沿用 `tests/cli/test_main.py` 的 `all_output` 助手思路）；`make_context` 的 `extra["color"]` 是 runner 路径上唯一的色彩权威（`_SuggestingGroup` 已接管）。
- 测试里不得产生仓库内垃圾文件：所有测试文件句柄/日志路径一律落在 `tmp_path` 下。

## 基线事实（勘察已核实，执行者无需重查）

- 现有命令：`version` / `help` / `guide` / `doctor` / `config(path|get|set|list)`；`cli/main.py` 709 行，`_SuggestingGroup` 在 main.py:126-147。
- 现有 help/guide 测试均为**子集断言**（`<=` / `>=`），新增命令不破坏它们。
- 迁移仅有 `store/migrations/001_init.sql`（`app_meta` KV 表）；`migrate()` 的编写规则：以 `;`+换行结尾、脚本内不得自带 BEGIN/COMMIT、不得以 `--` 注释结尾。
- 配置 schema：`conf/schema.py` 全族已注册；`EngineExtras`（engines 族）现仅含四个 `*_extra_args`。**新增配置键必须同步三处**：schema.py、`tests/conf/test_schema.py` 的 `SPEC_DEFAULTS`、`tests/qa/test_conf_adversarial.py` 的 `ROUNDTRIP_VALUES` + `assert len(FLAT_KEYS) == 60` 改 61（tests/qa/test_conf_adversarial.py:330）。
- `tests/cli/test_main.py` 钉死欢迎卡内容：:557（欢迎卡用例）断言卡内含 `ipo config list`；已初始化箭头指向 `ipo guide`（:607-618 `test_welcome_card_marks_next_step_by_state`）；:621 的注册守卫测试从 `WELCOME_STEPS` 泛化推导，更新卡后自动通过。**:366 的 `ipo config list` 是 config-get 未知键错误文案断言，与欢迎卡无关，不得改动。**
- R1 守卫禁字面量：`"os.path."`、`"if os.name =="`、`"sys.platform =="`（tests/test_platform_hygiene.py:11-15）。
- Windows `shutil.which("llama-server")` 只会命中带 PATHEXT 扩展名的文件（`llama-server.exe`），POSIX 只命中裸名——涉及 PATH 探测的测试必须**两种文件名都创建**。
- Windows `os.kill(pid, SIGTERM)` = TerminateProcess（硬杀、无优雅期）；POSIX 为 SIGTERM。`signal.SIGKILL` 仅 POSIX 存在——跨平台取值用 `getattr(signal, "SIGKILL", signal.SIGTERM)`（值适配，非分支）。
- `urllib.error.HTTPError` 是 `OSError` 的子类——except 顺序必须 HTTPError 在前。
- 打包：hatchling `packages = ["src/ipostudio"]`，新子包自动收入 wheel。
- ruff：line-length 100，`src = ["src","tests"]`，默认规则集（含 pyflakes F401 未用导入）；每任务以 `.venv/Scripts/python.exe -m ruff check src tests` 全绿收口——**测试文件的 import 也必须全部被使用**。

## 文件结构（本计划完成后）

```
src/ipostudio/
  catalog/                    # 模型目录（ADR-008；P2 将扩展搜索/下载/收藏）
    __init__.py               # 新建（空）
    scan.py                   # 新建：GGUF 发现（纯函数）
    repo.py                   # 新建：models 表仓库函数
  engines/                    # 引擎监管（ADR-008；P3 将扩展多实例/自动规划）
    __init__.py               # 新建（空）
    discovery.py              # 新建：定位 llama-server（纯函数）
    llama_server.py           # 新建：配置 → llama-server argv（纯函数）
    supervisor.py             # 新建：spawn/健康/停止 + 实例行状态机
    repo.py                   # 新建：instances/completions 表仓库函数
    openai_client.py          # 新建：/v1/chat/completions 最小客户端
  cli/
    base.py                   # 新建：_SuggestingGroup（自 main 迁入）+ open_config_and_db + _fail
    models_cmd.py             # 新建：models / model / model-info
    server_cmd.py             # 新建：server 组 + start/status/stop/restart
    chat_cmd.py               # 新建：chat
    main.py                   # 修改：迁出 _SuggestingGroup、注册新命令、欢迎卡三步更新
  conf/schema.py              # 修改：engines 族新增 llama_cpp_path
store/migrations/
  002_models.sql              # 新建
  003_instances.sql           # 新建
tests/
  catalog/__init__.py         # 新建（空）
  catalog/test_scan_repo.py   # 新建
  engines/__init__.py         # 新建（空）
  engines/fake_llama_server.py# 新建：假引擎（架构 §5 认可的测试替身）
  engines/test_llama_server.py# 新建（discovery + argv + 替身契约）
  engines/test_supervisor.py  # 新建
  engines/test_openai_client.py # 新建
  cli/test_models_cmd.py      # 新建
  cli/test_server_cmd.py      # 新建
  cli/test_chat_cmd.py        # 新建
  cli/test_main.py            # 修改：欢迎卡断言（Task 6）
  qa/test_conf_adversarial.py # 修改：FLAT_KEYS 61 + ROUNDTRIP（Task 3）
  qa/test_cli_ux_adversarial.py # 修改：样式守卫扩到 cli 包 + walker 子集分阶段扩充（Task 2/6/8）
  qa/test_loop_adversarial.py # 新建（Task 8）
docs/design/roadmap.md        # 修改：M0′ 切片结论回写（Task 8）
README.md / CHANGELOG.md / TODOS.md  # 修改（Task 8）
```

任务顺序约束：1（catalog 数据层）→ 2（models CLI）→ 3（引擎发现+argv+配置键）→ 4（监督器）→ 5（server CLI）→ 6（start/status/stop/restart+欢迎卡）→ 7（chat）→ 8（文档+QA+推送）。2 依赖 1；4 依赖 3；5、6、7 依赖 4。2/5/6/7/8 都会触碰 `tests/qa/test_cli_ux_adversarial.py`——按任务顺序的增量改法已在各任务写明，勿提前合并。

---

### Task 1: 模型目录数据层（migration 002 + catalog/scan.py + catalog/repo.py）

**Files:**
- Create: `src/ipostudio/store/migrations/002_models.sql`
- Create: `src/ipostudio/catalog/__init__.py`（空文件）
- Create: `src/ipostudio/catalog/scan.py`
- Create: `src/ipostudio/catalog/repo.py`
- Create: `tests/catalog/__init__.py`（空文件）
- Test: `tests/catalog/test_scan_repo.py`

**Interfaces:**
- Consumes: `store/database.py` 的 `open_db` / `migrate`（既有）。
- Produces（Task 2/5/6 依赖，签名逐字）:
  - `ModelFile(name: str, path: Path, size_bytes: int, format: str, parts: int)` — frozen dataclass。
  - `model_scan_roots(model_dirs: list[str], data_dir: Path) -> list[Path]`
  - `scan_model_files(roots: list[Path]) -> tuple[list[ModelFile], int, bool]` — (模型, 跳过数, 是否截断)。
  - `shard_family_complete(path: Path) -> bool` — 记录文件的分片族（若有）在盘上完整；server 启动前复核 insert-only 目录的陈旧行（Codex 陈旧行折叠）。
  - `looks_like_gguf(path: Path) -> bool`
  - `MAX_SCAN_DEPTH = 4`、`MAX_SCAN_ENTRIES = 500`、`MAX_SCAN_VISITED = 20000`（模块常量；访问预算计入全部遍历条目，非仅 GGUF 候选——Codex 预算折叠）。
  - `upsert_models(conn: sqlite3.Connection, files: list[ModelFile]) -> None`
  - `list_models(conn: sqlite3.Connection) -> list[dict]`
  - `find_model(conn: sqlite3.Connection, ident: str) -> list[dict]` — 精确名 → 精确路径 → 路径后缀匹配，**返回全部候选**（0/1/多由调用方裁决）。

- [ ] **Step 1: 写失败测试**

`tests/catalog/test_scan_repo.py` 全文：

```python
from pathlib import Path

from ipostudio.catalog.repo import find_model, list_models, upsert_models
from ipostudio.catalog.scan import (
    MAX_SCAN_ENTRIES,
    ModelFile,
    looks_like_gguf,
    model_scan_roots,
    scan_model_files,
)
from ipostudio.store.database import migrate, open_db

GGUF_HEAD = b"GGUF" + b"\x00" * 28  # magic + version/tensor-count shape

def _make_db(tmp_path):
    conn = open_db(tmp_path / "app.db")
    migrate(conn)
    return conn

def _write_gguf(path, size=64, head=GGUF_HEAD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + b"\x00" * max(size - len(head), 0))

def test_scan_finds_single_gguf_and_skips_other_extensions(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "tiny-q4.gguf", size=64)
    (root / "notes.txt").write_text("not a model")
    files, skipped, truncated = scan_model_files([root])
    assert skipped == 0 and truncated is False
    assert [f.name for f in files] == ["tiny-q4"]
    assert files[0].format == "gguf" and files[0].parts == 1
    assert files[0].size_bytes == 64

def test_scan_rejects_non_gguf_magic_as_incomplete(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "corrupt.gguf", head=b"NOPE")
    files, skipped, _ = scan_model_files([root])
    assert files == [] and skipped == 1

def test_scan_groups_multipart_shards_into_one_model(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "big-00001-of-00003.gguf", size=100)
    _write_gguf(root / "big-00002-of-00003.gguf", size=100)
    _write_gguf(root / "big-00003-of-00003.gguf", size=100)
    files, skipped, _ = scan_model_files([root])
    assert skipped == 0
    assert len(files) == 1
    assert files[0].name == "big" and files[0].parts == 3
    assert files[0].size_bytes == 300
    assert files[0].path.name == "big-00001-of-00003.gguf"

def test_scan_keeps_prefix_colliding_shard_families(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "llama-00001-of-00002.gguf")
    _write_gguf(root / "llama-00002-of-00002.gguf")
    _write_gguf(root / "llama-instruct-00001-of-00002.gguf")
    _write_gguf(root / "llama-instruct-00002-of-00002.gguf")
    files, skipped, _ = scan_model_files([root])
    assert skipped == 0
    assert sorted(f.name for f in files) == ["llama", "llama-instruct"]
    assert all(f.parts == 2 for f in files)

def test_scan_skips_incomplete_shard_sets_and_orphan_shards(tmp_path):
    root = tmp_path / "models"
    _write_gguf(root / "half-00002-of-00002.gguf")  # first shard missing
    _write_gguf(root / "set-00001-of-00002.gguf")   # second shard missing
    files, skipped, _ = scan_model_files([root])
    assert files == [] and skipped == 2

def test_scan_bounds_depth_and_skips_hidden_entries(tmp_path):
    root = tmp_path / "models"
    deep = root / "a" / "b" / "c" / "d"
    _write_gguf(deep / "reachable.gguf")
    _write_gguf(deep / "e" / "too-deep.gguf")
    _write_gguf(root / ".hidden" / "secret.gguf")
    names = [f.name for f in scan_model_files([root])[0]]
    assert "reachable" in names
    assert "too-deep" not in names and "secret" not in names

def test_scan_truncates_at_entry_cap_with_flag(tmp_path):
    root = tmp_path / "models"
    for index in range(MAX_SCAN_ENTRIES + 10):
        _write_gguf(root / f"m{index:04}.gguf")
    files, _skipped, truncated = scan_model_files([root])
    assert truncated is True
    assert len(files) <= MAX_SCAN_ENTRIES

def test_missing_roots_are_silent(tmp_path):
    files, skipped, truncated = scan_model_files([tmp_path / "nope"])
    assert files == [] and skipped == 0 and truncated is False

def test_model_scan_roots_dedupes_and_appends_default(tmp_path):
    roots = model_scan_roots(["~/m", "~/m"], tmp_path)
    assert roots == [Path("~/m").expanduser().resolve(), (tmp_path / "models").resolve()]

def test_scan_roots_resolve_relative_dirs_across_cwd(tmp_path, monkeypatch):
    root = tmp_path / "relmodels"
    root.mkdir()
    _write_gguf(root / "m.gguf", size=10)
    monkeypatch.chdir(tmp_path)
    files, _skipped, _truncated = scan_model_files(model_scan_roots(["relmodels"], tmp_path))
    assert files and files[0].path.is_absolute()  # Codex path-stability fold

def test_non_contiguous_shard_set_is_rejected(tmp_path):
    root = tmp_path / "models"
    root.mkdir()
    _write_gguf(root / "x-00001-of-00002.gguf", size=10)
    _write_gguf(root / "x-00003-of-00002.gguf", size=10)
    files, skipped, _truncated = scan_model_files([root])
    assert files == [] and skipped == 2  # Codex contiguity fold

def test_visit_budget_bounds_non_gguf_directories(tmp_path, monkeypatch):
    import ipostudio.catalog.scan as scan_module

    root = tmp_path / "models"
    root.mkdir()
    for index in range(50):
        (root / f"note-{index:03d}.txt").write_bytes(b"x")
    monkeypatch.setattr(scan_module, "MAX_SCAN_VISITED", 10)
    files, _skipped, truncated = scan_model_files([root])
    assert files == [] and truncated is True  # Codex budget fold

def test_looks_like_gguf_tolerates_unreadable_file(tmp_path):
    assert looks_like_gguf(tmp_path / "absent.gguf") is False

def test_upsert_is_idempotent_by_path_and_updates_size(tmp_path):
    conn = _make_db(tmp_path)
    target = tmp_path / "m.gguf"
    upsert_models(conn, [ModelFile("m", target, 10, "gguf", 1)])
    upsert_models(conn, [ModelFile("m", target, 20, "gguf", 1)])
    rows = list_models(conn)
    assert len(rows) == 1 and rows[0]["size_bytes"] == 20
    conn.close()

def test_find_model_exact_name_then_path_then_suffix(tmp_path):
    conn = _make_db(tmp_path)
    upsert_models(
        conn,
        [
            ModelFile("alpha", tmp_path / "alpha.gguf", 1, "gguf", 1),
            ModelFile("beta", tmp_path / "nested" / "beta.gguf", 1, "gguf", 1),
        ],
    )
    assert find_model(conn, "alpha")[0]["name"] == "alpha"
    assert find_model(conn, str(tmp_path / "alpha.gguf"))[0]["name"] == "alpha"
    assert find_model(conn, "nested")[0]["name"] == "beta"
    assert find_model(conn, "gamma") == []
    conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/catalog/test_scan_repo.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'ipostudio.catalog'`

- [ ] **Step 3: 写迁移与实现**

`src/ipostudio/store/migrations/002_models.sql` 全文：

```sql
-- 002: model catalog rows for locally scanned model files (spec §10.1:
-- models, origin, category and integrity; F02 local-management slice).
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    parts INTEGER NOT NULL DEFAULT 1,
    category TEXT NOT NULL DEFAULT 'chat',
    source TEXT NOT NULL DEFAULT 'scan',
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`src/ipostudio/catalog/scan.py` 全文：

```python
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
    \"\"\"True when `path`'s shard family (if any) is fully present on disk.
    The catalog is insert-only until P2 pruning, so the server path
    re-validates the recorded file set before launch (Codex stale-row
    fold).\"\"\"
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
            skipped += 1  # orphan shard, incomplete, or non-contiguous set
            continue
        sizes = [_file_size(shard) for shard in shards]
        if any(size is None for size in sizes) or not all(
            looks_like_gguf(shard) for shard in shards
        ):
            skipped += 1
            continue
        models.append(ModelFile(base, path, sum(sizes), "gguf", len(shards)))
    return models, skipped, truncated
```

`src/ipostudio/catalog/repo.py` 全文：

```python
"""Repository functions for the models table (ADR-002: SQL stays auditable,
no ORM)."""

import sqlite3
from pathlib import Path

from ipostudio.catalog.scan import ModelFile

_UPSERT = """
INSERT INTO models (name, path, format, size_bytes, parts, category, source, updated_at)
VALUES (?, ?, ?, ?, ?, 'chat', 'scan', datetime('now'))
ON CONFLICT(path) DO UPDATE SET
    name = excluded.name,
    size_bytes = excluded.size_bytes,
    parts = excluded.parts,
    updated_at = datetime('now')
"""

_COLUMNS = (
    "id, name, path, format, size_bytes, parts, category, source, first_seen, updated_at"
)

def upsert_models(conn: sqlite3.Connection, files: list[ModelFile]) -> None:
    with conn:
        conn.executemany(
            _UPSERT,
            [(f.name, str(f.path), f.format, f.size_bytes, f.parts) for f in files],
        )

def list_models(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(f"SELECT {_COLUMNS} FROM models ORDER BY name, path").fetchall()
    return [dict(row) for row in rows]

def find_model(conn: sqlite3.Connection, ident: str) -> list[dict]:
    """Resolve a user-typed identifier to catalog rows: exact name, then
    exact path, then path-suffix match.  All candidates come back so the
    caller can distinguish missing from ambiguous."""
    def query(where: str, param: str) -> list[dict]:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM models WHERE {where} ORDER BY name, path",
            (param,),
        ).fetchall()
        return [dict(row) for row in rows]

    exact_name = query("name = ?", ident)
    if exact_name:
        return exact_name
    exact_path = query("path = ?", ident)
    if exact_path:
        return exact_path
    # Component-aware suffix match, computed in Python: user-supplied % and _
    # can never act as wildcards, and a bare directory name ("nested") matches
    # .../nested/beta.gguf because the ident equals one of the path parts.
    # The catalog is capped at MAX_SCAN_ENTRIES, so a full scan stays bounded.
    needle = ident.replace("\\", "/").strip("/")
    if not needle:
        return []
    matches = []
    for row in list_models(conn):
        posix = Path(row["path"]).as_posix()
        if needle in Path(row["path"]).parts or posix.endswith("/" + needle):
            matches.append(row)
    return matches
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/catalog/test_scan_repo.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 202 passed（191 基线 + 11 新）, ruff 全绿

```bash
git add src/ipostudio/catalog src/ipostudio/store/migrations/002_models.sql tests/catalog
git commit -m "feat: scan local gguf models into a catalog table"
```

---

### Task 2: `ipo models` / `ipo model --select` / `ipo model-info` + cli/base.py 拆分

**Files:**
- Create: `src/ipostudio/cli/base.py`
- Create: `src/ipostudio/cli/models_cmd.py`
- Modify: `src/ipostudio/cli/main.py`（迁出 `_SuggestingGroup`，注册三个新命令）
- Modify: `tests/qa/test_cli_ux_adversarial.py`（样式守卫从单文件扩到整个 cli 包；walker 子集加 `models --json`、`model --json`）
- Test: `tests/cli/test_models_cmd.py`（新建）

**Interfaces:**
- Consumes: Task 1 全部 Produces；既有 `load_config` / `ConfigStore` / `ConfigError` / `resolve_config_path` / `resolve_data_dir` / `resolve_db_path` / `open_db` / `migrate` / `suggest_key`。
- Produces（Task 5/6/7 依赖）:
  - `src/ipostudio/cli/base.py`：
    - `_SuggestingGroup`（自 main.py 原样迁入；main.py 以 `from ipostudio.cli.base import _SuggestingGroup` 继续引用）。
    - `open_config_and_db() -> tuple[sqlite3.Connection, AppConfig]` — load_config + open_db + migrate 的公共入口；失败打印结构化 stderr 并 exit 1。
    - `_fail(message: str) -> None` — stderr `error: {message}` + exit 1。
  - `models_cmd.py` 模块级函数 `activate_model(conn, ident: str, cfg) -> str` — 解析并持久化 `local_chat_model`，返回激活名；无匹配抛 `LookupError`、歧义抛 `ValueError`（消息已用户安全；Task 6 的 `ipo start --model` 复用）。

- [ ] **Step 1: 写失败测试**

`tests/cli/test_models_cmd.py` 全文：

```python
import json

import pytest
from click.testing import CliRunner

from ipostudio.catalog.repo import upsert_models
from ipostudio.catalog.scan import model_scan_roots, scan_model_files
from ipostudio.cli.main import cli
from ipostudio.store.database import migrate, open_db

GGUF = b"GGUF" + b"\x00" * 28

@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    root = tmp_path / "models"
    root.mkdir()  # Codex determinism fold: write_bytes never creates parents
    (root / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    (root / "other-f16.gguf").write_bytes(GGUF + b"\x00" * 36)
    return tmp_path, root

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_models_lists_scanned_files(catalog):
    result = _invoke("models")
    assert result.exit_code == 0
    assert "tiny-q4" in result.output and "other-f16" in result.output
    assert "FORMAT" in result.output

def test_models_empty_state_guides_the_user(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("models")
    assert result.exit_code == 0
    assert "no models found" in result.output
    assert str(tmp_path / "models") in result.output
    assert "ipo config set model_dirs" in result.output

def test_models_json_is_clean_and_parseable(catalog):
    result = _invoke("models", "--json")
    assert result.exit_code == 0
    assert "\x1b[" not in result.output
    payload = json.loads(result.output)
    assert payload["count"] == 2 and payload["truncated"] is False
    assert {m["name"] for m in payload["models"]} == {"tiny-q4", "other-f16"}

def test_models_reports_broken_config_with_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "settings.toml").write_text("nonsense_key = 1\n", encoding="utf-8")
    result = _invoke("models", "--json")
    assert result.exit_code == 1
    assert "nonsense_key" in result.stderr

def test_model_without_select_shows_active_or_unset(catalog):
    unset = _invoke("model")
    assert unset.exit_code == 0
    assert "(not set)" in unset.output
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    selected = _invoke("model")
    assert selected.exit_code == 0
    assert "tiny-q4" in selected.output

def test_model_json_reports_null_active_on_fresh_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("model", "--json")
    assert result.exit_code == 0  # walker contract: no-arg invocation passes
    assert json.loads(result.output) == {"active": None}

def test_model_select_persists_config_and_hints_restart(catalog):
    result = _invoke("model", "--select", "tiny-q4")
    assert result.exit_code == 0
    assert "ipo server restart" in result.output
    stored = _invoke("config", "get", "local_chat_model")
    assert "tiny-q4" in stored.output

def test_model_select_reports_missing_with_hint(catalog):
    result = _invoke("model", "--select", "nope")
    assert result.exit_code == 1
    assert "no local model matches" in result.stderr
    assert "ipo models" in result.stderr

def test_model_select_reports_ambiguous_suffix(catalog):
    _tmp, root = catalog
    (root / "a").mkdir()
    (root / "a" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    (root / "b").mkdir()
    (root / "b" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    result = _invoke("model", "--select", "dup.gguf")
    assert result.exit_code == 1
    assert "ambiguous" in result.stderr

def test_model_info_reports_one_model(catalog):
    info = _invoke("model-info", "tiny-q4")
    assert info.exit_code == 0
    assert "tiny-q4.gguf" in info.output
    payload = json.loads(_invoke("model-info", "tiny-q4", "--json").output)
    assert payload["name"] == "tiny-q4" and payload["format"] == "gguf"

def test_model_info_requires_name(catalog):
    result = _invoke("model-info")
    assert result.exit_code == 2  # required argument (click usage error)

def test_activate_model_persists_and_resolves(catalog):
    tmp_path, _root = catalog
    from ipostudio.cli.models_cmd import activate_model
    from ipostudio.conf.loader import load_config

    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    files, _skipped, _truncated = scan_model_files(model_scan_roots([], tmp_path))
    upsert_models(conn, files)
    assert activate_model(conn, "tiny-q4", load_config()) == "tiny-q4"
    assert load_config().general.local_chat_model == "tiny-q4"
    with pytest.raises(LookupError):
        activate_model(conn, "absent", load_config())
    conn.close()

def test_activate_model_refuses_ambiguous_name_from_unique_path(catalog):
    tmp_path, _root = catalog
    from ipostudio.cli.models_cmd import activate_model
    from ipostudio.conf.loader import load_config

    models_root = tmp_path / "models"
    (models_root / "a").mkdir()
    (models_root / "a" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    (models_root / "b").mkdir()
    (models_root / "b" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    files, _skipped, _truncated = scan_model_files(model_scan_roots([], tmp_path))
    upsert_models(conn, files)
    with pytest.raises(ValueError):
        activate_model(conn, str(models_root / "a" / "dup.gguf"), load_config())
    conn.close()

def test_activate_model_raises_on_ambiguity(catalog):
    tmp_path, _root = catalog
    from ipostudio.cli.models_cmd import activate_model
    from ipostudio.conf.loader import load_config

    models_root = tmp_path / "models"
    (models_root / "a").mkdir()
    (models_root / "a" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    (models_root / "b").mkdir()
    (models_root / "b" / "dup.gguf").write_bytes(GGUF + b"\x00" * 36)
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    files, _skipped, _truncated = scan_model_files(model_scan_roots([], tmp_path))
    upsert_models(conn, files)
    with pytest.raises(ValueError):
        activate_model(conn, "dup.gguf", load_config())
    conn.close()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/cli/test_models_cmd.py -v`
Expected: FAIL —— unknown command 'models'（`CliRunner` 经 `_SuggestingGroup` 改写为 unknown command），或 `ModuleNotFoundError: ipostudio.cli.models_cmd`（activate 测试）

- [ ] **Step 3: 实现**

`src/ipostudio/cli/base.py` 全文（`_SuggestingGroup` 自 `main.py:126-147` **原样迁移**，仅 import 面随新家调整）：

```python
"""CLI-wide plumbing shared by main and the command modules."""

import sqlite3
import sys

import click

from ipostudio.cli.ui import use_color
from ipostudio.conf.loader import ConfigError, load_config, suggest_key
from ipostudio.conf.paths import resolve_db_path
from ipostudio.conf.schema import AppConfig
from ipostudio.store.database import migrate, open_db

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

def open_config_and_db() -> tuple[sqlite3.Connection, AppConfig]:
    """Shared entry for commands that need effective config plus a migrated
    database.  Any failure prints a structured stderr line and exits 1."""
    try:
        cfg = load_config()
        conn = open_db(resolve_db_path())
        migrate(conn)
    except ConfigError as exc:
        for detail in exc.details:
            click.echo(f"error: {detail}", err=True)
        sys.exit(1)
    except sqlite3.Error as exc:
        click.echo(
            f"error: database unavailable ({exc}); run `ipo doctor --fix` and retry",
            err=True,
        )
        sys.exit(1)
    except OSError as exc:
        # ENG F16: an unreadable data dir (permissions) must meet the same
        # error contract, not a traceback
        click.echo(
            f"error: cannot access the data directory ({exc}); check "
            f"permissions, then run `ipo doctor --fix`",
            err=True,
        )
        sys.exit(1)
    return conn, cfg

def open_db_only() -> sqlite3.Connection:
    """Migrated database without loading settings.toml (Codex recovery fold):
    stop/status/list/info must work even when the config file is broken —
    a user must always be able to stop what they started."""
    conn = open_db(resolve_db_path())
    migrate(conn)
    return conn

def _fail(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    sys.exit(1)
```

`src/ipostudio/cli/models_cmd.py` 全文：

```python
"""`ipo models` / `ipo model` / `ipo model-info` (spec §9.11 local slice).

`model --select` and `model-info` refresh the scan before resolving, so a
model dropped into a directory is selectable without running `ipo models`
first (ruling #12)."""

import json
import os
import sqlite3
from pathlib import Path

import click

from ipostudio.catalog.repo import find_model, list_models, upsert_models
from ipostudio.catalog.scan import MAX_SCAN_ENTRIES, model_scan_roots, scan_model_files
from ipostudio.cli.base import _fail, open_config_and_db
from ipostudio.conf.loader import ConfigError, ConfigStore
from ipostudio.conf.paths import resolve_config_path, resolve_data_dir

def _refresh(conn: sqlite3.Connection, cfg) -> tuple[list[dict], int, bool, list]:
    roots = model_scan_roots(cfg.general.model_dirs, resolve_data_dir())
    files, skipped, truncated = scan_model_files(roots)
    upsert_models(conn, files)
    return list_models(conn), skipped, truncated, roots

def _human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"

@click.command("models")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def models(as_json: bool) -> None:
    """List local models found in the configured model directories."""
    conn, cfg = open_config_and_db()
    try:
        rows, skipped, truncated, roots = _refresh(conn, cfg)
    finally:
        conn.close()
    active = cfg.general.local_chat_model
    for row in rows:
        row["active"] = row["name"] == active
        # insert-only catalog until P2 pruning: surface ghost rows instead of
        # hiding them (Codex stale-row fold; TODO-021 owns removal)
        row["missing"] = not Path(row["path"]).exists()
    if as_json:
        click.echo(
            json.dumps(
                {
                    "count": len(rows),
                    "skipped": skipped,
                    "truncated": truncated,
                    "roots": [str(root) for root in roots],
                    "models": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not rows:
        click.echo("no models found.")
        click.echo(f"searched: {', '.join(str(root) for root in roots)}")
        click.echo(
            "place a .gguf model file in one of these directories (or register "
            "another directory with `ipo config set model_dirs -- '[\"D:/models\"]'`)"
        )
        return
    width = max(len(row["name"]) for row in rows) + 1
    click.echo(f"{'NAME':<{width}}  SIZE  PARTS  FORMAT  PATH")
    for row in rows:
        mark = "*" if row["active"] else " "
        path_text = row["path"] + ("  (missing)" if row["missing"] else "")
        click.echo(
            f"{mark + row['name']:<{width}}  {_human_size(row['size_bytes']):>8}  "
            f"{row['parts']:>5}  {row['format']:<6}  {path_text}"
        )
    if truncated:
        click.echo(
            f"listing truncated at {MAX_SCAN_ENTRIES} entries; register a narrower "
            f"model_dirs entry to see the rest"
        )
    if skipped:
        click.echo(f"skipped {skipped} incomplete or unreadable candidate(s)")

def activate_model(conn: sqlite3.Connection, ident: str, cfg) -> str:
    """Resolve `ident` against the catalog and persist it as the active chat
    model.  Raises LookupError (nothing matches) or ValueError (ambiguous)
    with user-safe messages; returns the activated name."""
    matches = find_model(conn, ident)
    if not matches:
        raise LookupError(
            f"no local model matches {ident!r}; run `ipo models` for the catalog"
        )
    if len(matches) > 1:
        paths = ", ".join(sorted({match["path"] for match in matches})[:5])
        raise ValueError(
            f"ambiguous match for {ident!r}: {paths}; use a full name or path"
        )
    name = matches[0]["name"]
    # ENG F2: selection by unique path must not round-trip into an ambiguous
    # name — if the bare name still matches several rows, `server start`
    # would brick.  Path-addressable activation lands with P2 pruning.
    if len(find_model(conn, name)) > 1:
        # the ident itself was unique — the NAME is not; say so precisely so
        # the user is not sent in a circle (Codex DX dead-loop fold)
        raise ValueError(
            f"several catalog rows share the name {name!r} (same file name in "
            f"different directories); until catalog pruning lands (P2), "
            f"activate by a name unique in the catalog — or remove the "
            f"duplicate file and re-run `ipo models`"
        )
    store = ConfigStore(resolve_config_path(), cfg)
    store.set("local_chat_model", name)
    store.save()
    return name

@click.command("model")
@click.option("--select", "select_name", default=None, metavar="NAME",
              help="activate a local model as the default chat model")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def model(select_name: str | None, as_json: bool) -> None:
    """Show or set the active chat model."""
    if select_name is None:
        conn, cfg = open_config_and_db()
        conn.close()
        active = cfg.general.local_chat_model
        if as_json:
            click.echo(json.dumps({"active": active}, ensure_ascii=False))
        else:
            shown = active if active else "(not set)"
            click.echo(f"active chat model: {shown}")
            if not active:
                click.echo("set one with `ipo model --select NAME` (see `ipo models`)")
        return
    conn, cfg = open_config_and_db()
    try:
        _refresh(conn, cfg)
        name = activate_model(conn, select_name, cfg)
    except (LookupError, ValueError, ConfigError) as exc:
        _fail(str(exc))  # Codex boundary fold: lock/permission failures are
        # ConfigError, not LookupError — without this arm they traceback
    finally:
        conn.close()
    if as_json:  # Codex JSON-contract fold: selection is machine-readable too
        click.echo(json.dumps(
            {"selected": name, "saved": True,
             "apply_with": "ipo server restart"},
            ensure_ascii=False,
        ))
        return
    click.echo(f"active chat model: {name} (saved)")
    override = os.environ.get("IPO_LOCAL_CHAT_MODEL", "").strip()
    if override and override != name:
        click.echo(
            f"warning: IPO_LOCAL_CHAT_MODEL={override!r} is set in this shell; "
            f"it overrides the saved value for new commands",
            err=True,
        )
    click.echo("if a server is running, apply the change with `ipo server restart`")

@click.command("model-info")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def model_info(name: str, as_json: bool) -> None:
    """Show details for one local model (NAME from `ipo models`)."""
    conn, cfg = open_config_and_db()
    try:
        _refresh(conn, cfg)
        matches = find_model(conn, name)
    finally:
        conn.close()
    if not matches:
        _fail(f"no local model matches {name!r}; run `ipo models`")
    if len(matches) > 1:
        _fail(f"ambiguous match for {name!r}; use a full name or path")
    row = matches[0]
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    click.echo(f"name:     {row['name']}")
    click.echo(f"path:     {row['path']}")
    click.echo(f"size:     {_human_size(row['size_bytes'])} ({row['size_bytes']} bytes)")
    click.echo(f"format:   {row['format']} ({row['parts']} part(s))")
    click.echo(f"category: {row['category']}")
    click.echo(f"source:   {row['source']}")
    click.echo(f"seen:     {row['first_seen']}")
```

`src/ipostudio/cli/main.py` 的修改（两处）：

1. 删除 `class _SuggestingGroup`（main.py:126-147），在 import 区加：
```python
from ipostudio.cli.base import _SuggestingGroup
```
（main.py 其余 `use_color` / `suggest_key` 等 import 保持不变，doctor 与 config get 仍在使用。）
2. 文件末尾注册新命令：
```python
from ipostudio.cli.models_cmd import model, model_info, models

cli.add_command(models)
cli.add_command(model)
cli.add_command(model_info)
```

3. `collect_command_docs` 升级（Codex DX 折叠：现有收集器把 `click.Argument` 当选项输出 `flag:""`，且不递归命令组——`server start --model`、`config set` 等子命令面在 guide/help 中缺失；注意 Argument 的 `.help` 恒为 `None`，现有 `option.help or ""` 并不崩溃，缺口是**完整性**而非崩溃）：

```python
def collect_command_docs() -> list[dict]:
    def doc_for(command: click.Command) -> dict:
        options: list[dict] = []
        arguments: list[dict] = []
        for param in command.params:
            if isinstance(param, click.Argument):
                arguments.append(
                    {"name": (param.name or "").upper(),
                     "required": param.required}
                )
            else:
                options.append(
                    {"flag": param.opts[0] if param.opts else "",
                     "help": param.help or ""}
                )
        doc: dict = {
            "name": command.name,
            "help": command.help or "",
            "options": options,
            "arguments": arguments,
        }
        if isinstance(command, click.Group):
            doc["commands"] = [
                doc_for(sub) for _, sub in sorted(command.commands.items())
            ]
        return doc

    return [doc_for(command) for _, command in sorted(cli.commands.items())]
```

`_render_docs` 同步：markdown/text 分支输出 `arguments`（`<NAME>` 形态）与嵌套 `commands`（二级条目/缩进行）；`json` 分支自然携带新键。执行时更新 `tests/cli/test_main.py` 的 guide 断言（新增 server/config 子命令行与 `model-info`/`chat` 的 `<NAME>` 参数行），walker `--json` 洁净守卫保持绿。

`tests/qa/test_cli_ux_adversarial.py` 的修改：

1. `test_main_py_never_styles_directly` 改为包级守卫（函数名同步改为 `test_cli_package_never_styles_directly`；文件顶部若无 `from pathlib import Path` 则补上）：

```python
def test_cli_package_never_styles_directly():
    # all human-facing styling routes through cli/ui.py, so the NO_COLOR and
    # tty degradation contract cannot be bypassed by any module in the
    # package (models/server/chat land in their own files from the core loop)
    cli_dir = Path(inspect.getsourcefile(cli_main)).parent
    offenders = []
    for py in sorted(cli_dir.glob("*.py")):
        if py.name == "ui.py":
            continue  # the sanctioned styling boundary itself (Codex fold:
            # the guard as written flagged its own exempt module)
        source = py.read_text(encoding="utf-8")
        if "click.style" in source or "click.secho" in source:
            offenders.append(py.name)
    assert offenders == []
```

2. walker 子集断言扩为：

```python
    assert {"version --json", "doctor --json", "config path --json", "config list --json",
            "models --json", "model --json"} <= {
        " ".join(args) for args in cases
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/cli/test_models_cmd.py tests/qa -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿

```bash
git add src/ipostudio/cli tests/cli/test_models_cmd.py tests/qa/test_cli_ux_adversarial.py
git commit -m "feat: add ipo models, model --select and model-info commands"
```

---

### Task 3: 引擎发现 + llama-server argv 构建 + `llama_cpp_path` 配置键 + 假引擎替身

**Files:**
- Create: `src/ipostudio/engines/__init__.py`（空文件）
- Create: `src/ipostudio/engines/discovery.py`
- Create: `src/ipostudio/engines/llama_server.py`
- Modify: `src/ipostudio/conf/schema.py`（engines 族新增 `llama_cpp_path`）
- Modify: `src/ipostudio/conf/loader.py`（save() 盖 `config_version` 版本戳，防降级拒绝——Codex DX 折叠）
- Create: `tests/engines/__init__.py`（空文件）
- Modify: `tests/conf/test_loader.py`（save 版本戳测试）
- Create: `tests/engines/fake_llama_server.py`
- Modify: `tests/conf/test_schema.py`（SPEC_DEFAULTS 加一行）
- Modify: `tests/qa/test_conf_adversarial.py`（ROUNDTRIP_VALUES + 行数 60→61）
- Test: `tests/engines/test_llama_server.py`

**Interfaces:**
- Consumes: `conf/schema.py` 的 `ServerTuning`。
- Produces（Task 4/5/6/7 依赖，签名逐字）:
  - `discovery.ENGINE_COMMAND = "llama-server"`
  - `resolve_engine(configured: str) -> tuple[Path | None, str | None]` — (路径, 问题)；路径非空 ⇒ 问题为 None。
  - `build_server_argv(engine: Path, model_path: Path, host: str, port: int, tuning: ServerTuning, extra_args: list[str]) -> list[str]`
  - `tests/engines/fake_llama_server.py`：必认 `--host/--port/--model`（`parse_known_args` 忽略多余旗标），另支持 `--load-delay SECONDS`（期间 /health 回 503）与 `--exit-immediately`（stderr 一行后 exit 1）；GET `/props` 回 `{"model_path": <--model 值>}`（stop 身份守卫的替身面——Codex 折叠）。

- [ ] **Step 1: 写失败测试**

`tests/engines/test_llama_server.py` 全文：

```python
import sys
from pathlib import Path

from ipostudio.conf.schema import ServerTuning
from ipostudio.engines.discovery import ENGINE_COMMAND, resolve_engine
from ipostudio.engines.llama_server import build_server_argv

def test_resolve_engine_configured_path_wins(tmp_path):
    engine = tmp_path / "llama-server.exe"
    engine.write_bytes(b"\x01")
    path, problem = resolve_engine(str(engine))
    assert (path, problem) == (engine, None)

def test_resolve_engine_configured_but_missing_is_a_problem(tmp_path):
    path, problem = resolve_engine(str(tmp_path / "gone"))
    assert path is None
    assert "does not exist" in problem
    assert "llama_cpp_path" in problem

def test_resolve_engine_reports_missing_from_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    path, problem = resolve_engine("")
    assert path is None
    assert ENGINE_COMMAND in problem
    assert "install" in problem.lower()

def test_resolve_engine_finds_command_on_path(tmp_path, monkeypatch):
    # Windows' which() only matches PATHEXT names, POSIX only the bare name:
    # create both and accept either (R1: no platform branches, also in tests)
    for name in ("llama-server", "llama-server.exe"):
        candidate = tmp_path / name
        candidate.write_bytes(b"\x01")
        candidate.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    path, problem = resolve_engine("")
    assert problem is None
    assert path is not None and path.name in ("llama-server", "llama-server.exe")

TUNING = ServerTuning()

def test_argv_carries_core_flags():
    argv = build_server_argv(
        Path("engine"), Path("m.gguf"), "127.0.0.1", 18080, TUNING, []
    )
    assert argv[:8] == ["engine", "--model", "m.gguf", "--host", "127.0.0.1",
                        "--port", "18080", "--ctx-size"]
    assert "8192" in argv and "--parallel" in argv
    assert "--cache-type-k" in argv and "q8_0" in argv

def test_argv_omits_auto_flags_and_appends_extras():
    argv = build_server_argv(
        Path("engine"), Path("m.gguf"), "h", 1, TUNING, ["--verbose", "--special", "v"]
    )
    assert "--flash-attn" not in argv  # auto -> engine default
    assert "--n-gpu-layers" not in argv
    assert argv[-3:] == ["--verbose", "--special", "v"]

def test_argv_flash_attn_on_and_explicit_gpu_layers():
    tuning = ServerTuning(server_flash_attn="on", server_gpu_layers=16)
    argv = build_server_argv(Path("e"), Path("m"), "h", 1, tuning, [])
    assert "--flash-attn" in argv and "on" in argv
    assert argv[argv.index("--n-gpu-layers") + 1] == "16"

def test_argv_cpu_mode_pins_zero_layers_only_without_explicit_count():
    cpu = build_server_argv(
        Path("e"), Path("m"), "h", 1, ServerTuning(server_load_mode="cpu"), []
    )
    assert cpu[cpu.index("--n-gpu-layers") + 1] == "0"
    both = build_server_argv(
        Path("e"), Path("m"), "h", 1,
        ServerTuning(server_load_mode="cpu", server_gpu_layers=5), [],
    )
    assert both.count("--n-gpu-layers") == 1
    assert both[both.index("--n-gpu-layers") + 1] == "5"

def test_fake_engine_double_speaks_health_and_chat(tmp_path):
    """The fake engine is a subprocess contract: it must answer the two
    endpoints the core loop uses, on a port it is told to take."""
    import json
    import socket
    import subprocess
    import time
    import urllib.request

    fake = Path(__file__).parent / "fake_llama_server.py"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, str(fake), "--host", "127.0.0.1", "--port", str(port),
         "--model", "fake"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=1
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        body = json.dumps(
            {"model": "fake", "messages": [{"role": "user", "content": "hi"}]}
        ).encode()
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode())
        assert payload["choices"][0]["message"]["content"] == "echo:hi"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
```

`tests/conf/test_schema.py` 的 `SPEC_DEFAULTS` 中 engines 位置补一行（放在 `server_load_mode` 行之后即可，键序无关）：

```python
    ("engines", "llama_cpp_path"): "",
```

`tests/qa/test_conf_adversarial.py`：`ROUNDTRIP_VALUES` 的 engines 段补 `"llama_cpp_path": "engines/llama-server"`（置于 `llama_cpp_extra_args` 之前），并把 `assert len(FLAT_KEYS) == 60` 改为 `== 61`（docstring 里的 "60 - 3 credentials = 57" 同步改 "61 - 3 = 58"）。

`src/ipostudio/conf/loader.py` 的 `save()`：在 `for family, key in self._dirty:` 合并循环之后、`fd, temp_name = _mkstemp_in(self.path.parent)` 之前插入（Codex DX 降级折叠——save 不盖版本戳时，旧版本读不到 `config_version` 会按当前旧值解释，把本工具自己写出的新键判为未知键并**拒绝加载**，用户回退即坏档；盖戳后旧版本按设计走"更高版本容忍+警告丢弃"路径）：

```python
                # Stamp the writing schema version: after a downgrade the
                # older build reads a HIGHER file version and drops
                # unknown keys with a warning, instead of rejecting a
                # config this build itself wrote.
                merged["config_version"] = _SCHEMA_CONFIG_VERSION
```

`tests/conf/test_loader.py` 追加：

```python
def test_save_stamps_config_version_for_downgrade_tolerance(tmp_path):
    import tomllib

    from ipostudio.conf.loader import ConfigStore
    from ipostudio.conf.paths import resolve_config_path

    store = ConfigStore(resolve_config_path(), load_config())
    store.set("general.server_port", 18765)
    store.save()
    raw = tomllib.loads(resolve_config_path().read_text(encoding="utf-8"))
    assert raw["config_version"] == _SCHEMA_CONFIG_VERSION  # Codex fold
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/engines/test_llama_server.py tests/conf/test_schema.py tests/qa/test_conf_adversarial.py -v`
Expected: FAIL —— `No module named 'ipostudio.engines'`；SPEC_DEFAULTS 缺行断言失败；行数 61 断言失败

- [ ] **Step 3: 实现**

`src/ipostudio/conf/schema.py` 的 `EngineExtras` 改为：

```python
class EngineExtras(_Strict):
    llama_cpp_path: str = ""  # empty: resolve `llama-server` from PATH
    llama_cpp_extra_args: list[str] = Field(default_factory=list)
    vllm_extra_args: list[str] = Field(default_factory=list)
    sglang_extra_args: list[str] = Field(default_factory=list)
    mlx_extra_args: list[str] = Field(default_factory=list)
```

`src/ipostudio/engines/discovery.py` 全文：

```python
"""Locate the llama.cpp server executable.

ADR-010: a missing engine is reported honestly and never faked.  PATH lookup
uses shutil.which, which honors PATHEXT — `llama-server.exe` is found on
Windows without any platform branch (R1)."""

import shutil
from pathlib import Path

ENGINE_COMMAND = "llama-server"

def resolve_engine(configured: str) -> tuple[Path | None, str | None]:
    """Return (path, problem).  A configured path wins when it exists; an
    empty setting falls back to PATH.  A configured path that does not exist
    is a hard problem — silently ignoring user configuration would start the
    wrong engine or quietly shadow it."""
    if configured.strip():
        path = Path(configured.strip()).expanduser()
        if path.exists():
            return path, None
        return None, (
            f"configured engines.llama_cpp_path does not exist: {path}; "
            f"fix it with `ipo config set llama_cpp_path ...` or clear it "
            f"with `ipo config set llama_cpp_path \"\"` (empty falls back to PATH)"
        )
    found = shutil.which(ENGINE_COMMAND)
    if found:
        return Path(found), None
    return None, (
        f"llama.cpp server executable {ENGINE_COMMAND!r} not found on PATH; "
        f"install llama.cpp for your platform (see README quickstart) or set "
        f"the engines.llama_cpp_path config key"
    )
```

`src/ipostudio/engines/llama_server.py` 全文：

```python
"""Translate config tuning into llama-server argv (its documented public CLI).

Sampling parameters (temp/top_p/top_k/repeat_penalty) are REQUEST-time, not
server flags — `ipo chat` sends them per completion.  `--flash-attn auto`
and load_mode auto/gpu omit their flags so engine defaults stand."""

from pathlib import Path

from ipostudio.conf.schema import ServerTuning

def build_server_argv(
    engine: Path,
    model_path: Path,
    host: str,
    port: int,
    tuning: ServerTuning,
    extra_args: list[str],
) -> list[str]:
    argv = [
        str(engine),
        "--model", str(model_path),
        "--host", host,
        "--port", str(port),
        "--ctx-size", str(tuning.server_ctx_size),
        "--parallel", str(tuning.server_parallel),
        "--batch-size", str(tuning.server_batch_size),
        "--ubatch-size", str(tuning.server_ubatch_size),
        "--cache-type-k", tuning.server_cache_type_k,
        "--cache-type-v", tuning.server_cache_type_v,
    ]
    if tuning.server_gpu_layers is not None:
        argv += ["--n-gpu-layers", str(tuning.server_gpu_layers)]
    elif tuning.server_load_mode == "cpu":
        argv += ["--n-gpu-layers", "0"]  # explicit CPU pinning
    if tuning.server_flash_attn in ("on", "off"):
        argv += ["--flash-attn", tuning.server_flash_attn]
    # Managed flags must not be overridable via extras: the engine honors
    # the last occurrence, so an extra --port/--host/--model would desync
    # the recorded instance row from reality (Codex ENG fold)
    managed = {"--model", "-m", "--host", "--port"}
    for arg in extra_args:
        flag = str(arg).split("=", 1)[0]
        if flag in managed:
            raise ValueError(
                f"llama_cpp_extra_args contains managed flag {flag!r}; manage "
                f"it via its config key (server_host / server_port / model "
                f"selection) instead"
            )
    argv += [str(arg) for arg in extra_args]
    return argv
```

`tests/engines/fake_llama_server.py` 全文（测试替身，架构 §5 认可）：

```python
"""Test double for llama-server (architecture.md §5: fake executables stand
in for real engines; no weights required).  Speaks the two endpoints the
core loop uses: GET /health and POST /v1/chat/completions."""

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--load-delay", type=float, default=0.0)
    parser.add_argument("--exit-immediately", action="store_true")
    args, _unknown = parser.parse_known_args()
    if args.exit_immediately:
        print("boom: simulated engine failure", file=sys.stderr)
        sys.exit(1)
    ready_at = time.monotonic() + args.load_delay

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/props":
                # stop-identity guard surface: names the served model so
                # `ipo server stop` can prove port ownership (Codex fold);
                # llama-server documents /props with the model path
                self._send(200, {"model_path": args.model})
            elif self.path == "/health":
                if time.monotonic() < ready_at:
                    self._send(503, {"error": {"message": "Loading model"}})
                else:
                    self._send(200, {"status": "ok"})
            else:
                self._send(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            prompt = ""
            for message in body.get("messages", []):
                if message.get("role") == "user":
                    prompt = message.get("content", "")
            self._send(
                200,
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "model": body.get("model", args.model),
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": f"echo:{prompt}"},
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            )

        def _send(self, code: int, payload: dict) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:  # keep the engine log quiet
            pass

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.serve_forever()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/engines tests/conf tests/qa -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿

```bash
git add src/ipostudio/engines src/ipostudio/conf/schema.py tests/engines tests/conf/test_schema.py tests/qa/test_conf_adversarial.py
git commit -m "feat: locate llama-server and translate config into engine argv"
```

---

### Task 4: 实例监督器（migration 003 + engines/repo.py + engines/supervisor.py）

**Files:**
- Create: `src/ipostudio/store/migrations/003_instances.sql`
- Create: `src/ipostudio/engines/repo.py`
- Create: `src/ipostudio/engines/supervisor.py`
- Test: `tests/engines/test_supervisor.py`

**Interfaces:**
- Consumes: Task 3 全部 Produces；`store/database.py`；`logs.py` 的 `redact_text`。
- Produces（Task 5/6/7 依赖，签名逐字）:
  - `supervisor.SERVICE_STATES = ("stopped", "starting", "loading", "running", "failed")`
  - `supervisor.ENGINE_LOG_FILE = "engine-llama-cpp.log"`、`engine_log_path(data_dir: Path) -> Path`
  - `probe_health(host: str, port: int, timeout_s: float) -> str` → `"ok" | "loading" | "down"`
  - `choose_port(host: str, base_port: int, candidates: int = 20) -> int | None`
  - `start_instance(conn, argv: list[str], *, engine: str, model_name: str, model_path: str, host: str, port: int, log_path: Path, timeout_s: float, poll_interval: float = 0.5, probe=probe_health, spawn=subprocess.Popen) -> StartOutcome`；`StartOutcome(instance: dict, ok: bool)`（dataclass）。
  - `probe_identity(host: str, port: int, model_path: str, timeout_s: float) -> str` → `"owned" | "foreign" | "absent"`（stop 身份守卫，Codex 折叠）。
  - `stop_instance(conn, *, grace_s: float = 10.0, poll_interval: float = 0.25, probe=probe_health, identify=probe_identity) -> dict | None`（身份证明才发信号；foreign 拒绝并如实留行；absent 不发信号；状态写为条件更新——Codex 折叠）
  - `repo.py`：`active_instance(conn) -> dict | None`、`recent_instances(conn, limit: int = 20) -> list[dict]`、`record_completion(conn, *, instance_id: int, model_name: str, prompt_chars: int, output_chars: int, duration_ms: int, status: str, detail: str = "") -> None`、`last_completion(conn) -> dict | None`；`SERVICE_STATES` 从 supervisor 导入再导出（单一事实源）。

**依赖方向（锁定）**：行读写与 `SERVICE_STATES` 定义在 `supervisor.py`（自带 `_get`/`_touch` 私有读写与 stop 的内联查询）；`repo.py` 导入 supervisor 的 `SERVICE_STATES` 并提供查询/插入面；**supervisor 不 import repo**（避免环）。

- [ ] **Step 1: 写失败测试**

`tests/engines/test_supervisor.py` 全文：

```python
import socket
import sys
import time
from pathlib import Path

from ipostudio.engines import supervisor
from ipostudio.engines.repo import (
    active_instance,
    get_instance,
    last_completion,
    recent_instances,
    record_completion,
)
from ipostudio.engines.supervisor import (
    choose_port,
    engine_log_path,
    probe_health,
    start_instance,
    stop_instance,
)
from ipostudio.store.database import migrate, open_db

FAKE = Path(__file__).parent / "fake_llama_server.py"

def _db(tmp_path):
    conn = open_db(tmp_path / "app.db")
    migrate(conn)
    return conn

class _FakeProc:
    def __init__(self, exit_code=None):
        self.pid = 424242
        self.returncode = exit_code
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

def _spawned_kwargs(tmp_path, proc, probe):
    return dict(
        engine="llama.cpp", model_name="m", model_path="m.gguf",
        host="127.0.0.1", port=1, log_path=tmp_path / "engine.log",
        timeout_s=1.0, poll_interval=0.01, probe=probe, spawn=lambda *a, **k: proc,
    )

def test_choose_port_skips_occupied_and_bounds_candidates():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy = sock.getsockname()[1]
        picked = choose_port("127.0.0.1", busy, candidates=3)
        assert picked is not None and picked != busy
        assert busy < picked < busy + 3
    assert choose_port("256.256.256.256", 1, candidates=1) is None

def test_probe_health_reports_down_without_listener():
    assert probe_health("127.0.0.1", 1, 0.2) == "down"

def test_probe_health_sees_real_503_as_loading(tmp_path):
    # ENG F11: the 503->"loading" mapping must hold over real HTTP, not just
    # injected lambdas — a regression here makes slow-loading models un-startable
    import subprocess

    port = choose_port("127.0.0.1", 18800)
    proc = subprocess.Popen(
        [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
         "--load-delay", "1.5"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert probe_health("127.0.0.1", port, 1.0) == "loading"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and probe_health(
            "127.0.0.1", port, 0.5
        ) != "ok":
            time.sleep(0.05)
        assert probe_health("127.0.0.1", port, 0.5) == "ok"
    finally:
        proc.terminate()
        proc.wait(timeout=10)

def test_start_instance_reaches_running(tmp_path):
    conn = _db(tmp_path)
    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    assert outcome.ok is True
    assert outcome.instance["state"] == "running"
    assert outcome.instance["pid"] == 424242
    conn.close()

def test_start_instance_records_loading_transition(tmp_path):
    conn = _db(tmp_path)
    sequence = iter(["loading", "loading", "ok"])
    outcome = start_instance(
        conn, ["engine"],
        **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: next(sequence))
    )
    assert outcome.ok is True
    assert get_instance(conn, outcome.instance["id"])["state"] == "running"
    conn.close()

def test_start_instance_engine_exit_marks_failed_with_log_tail(tmp_path):
    conn = _db(tmp_path)
    log = tmp_path / "engine.log"
    log.write_text("boom: bad model shape\n", encoding="utf-8")
    kwargs = _spawned_kwargs(tmp_path, _FakeProc(exit_code=1), lambda *a: "down")
    kwargs["log_path"] = log
    outcome = start_instance(conn, ["engine"], **kwargs)
    assert outcome.ok is False
    assert outcome.instance["state"] == "failed"
    assert "exited during startup" in outcome.instance["detail"]
    assert "bad model shape" in outcome.instance["detail"]
    conn.close()

def test_start_instance_timeout_marks_failed(tmp_path):
    conn = _db(tmp_path)
    proc = _FakeProc()
    outcome = start_instance(
        conn, ["engine"],
        **_spawned_kwargs(tmp_path, proc, lambda *a: "loading")
    )
    assert outcome.ok is False
    assert "was terminated" in outcome.instance["detail"]
    assert proc.terminated is True  # Codex orphan fold: no unmanaged engine
    conn.close()

def test_start_instance_spawn_failure_marks_failed(tmp_path):
    conn = _db(tmp_path)

    def _raising_spawn(*args, **kwargs):
        raise FileNotFoundError("missing engine")

    kwargs = _spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "down")
    kwargs["spawn"] = _raising_spawn
    outcome = start_instance(conn, ["missing-engine"], **kwargs)
    assert outcome.ok is False
    assert "cannot start engine" in outcome.instance["detail"]
    conn.close()

def test_start_instance_with_real_fake_engine_end_to_end(tmp_path):
    conn = _db(tmp_path)
    port = choose_port("127.0.0.1", 18300)
    assert port is not None
    argv = [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
            "--model", "fake"]
    stopped = None
    try:
        outcome = start_instance(
            conn, argv, engine="llama.cpp", model_name="fake", model_path="fake.gguf",
            host="127.0.0.1", port=port, log_path=tmp_path / "logs" / "engine.log",
            timeout_s=20, poll_interval=0.05,
        )
        assert outcome.ok is True
        assert outcome.instance["state"] == "running"
        assert probe_health("127.0.0.1", port, 1.0) == "ok"
        # ENG F12: the recorded engine build must be non-empty (argv[0] is
        # sys.executable, whose --version really runs)
        assert get_instance(conn, outcome.instance["id"])["engine_version"]
    finally:
        stopped = stop_instance(conn, grace_s=10, poll_interval=0.05)
    assert stopped is not None
    assert stopped["state"] == "stopped"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and probe_health("127.0.0.1", port, 0.5) != "down":
        time.sleep(0.05)
    assert probe_health("127.0.0.1", port, 0.5) == "down"
    conn.close()

def test_stop_instance_without_active_returns_none(tmp_path):
    conn = _db(tmp_path)
    assert stop_instance(conn) is None
    conn.close()

def test_stop_sends_no_signal_when_identity_absent(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    stopped = stop_instance(conn, identify=lambda *a, **k: "absent")
    assert stopped["state"] == "stopped"
    assert kills == []  # Codex fold: no blind kill on an unproven identity
    assert "no stop signal was sent" in stopped["detail"]
    conn.close()

def test_stop_refuses_signal_when_identity_foreign(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append((pid, sig)))
    stopped = stop_instance(conn, identify=lambda *a, **k: "foreign")
    assert kills == []  # a foreign document on the port must never be killed
    assert stopped["state"] == "running"  # refusal leaves the row honest
    assert "different model document" in stopped["detail"]
    conn.close()

def test_stop_signals_once_identity_confirms(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append(sig))
    stopped = stop_instance(conn, identify=lambda *a, **k: "owned")
    assert stopped["state"] == "stopped"
    assert kills == [signal.SIGTERM]
    conn.close()

def test_concurrent_stop_cancels_start(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    kills = []
    monkeypatch.setattr(supervisor.os, "kill", lambda pid, sig: kills.append(sig))
    proc = _FakeProc()
    raced = {"done": False}

    def racing_probe(*a):
        if not raced["done"]:
            raced["done"] = True
            stop_instance(conn, identify=lambda *a, **k: "absent")
        return "loading"

    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, proc, racing_probe)
    )
    assert outcome.ok is False
    assert proc.terminated is True  # the loser of the race cleans up
    row = get_instance(conn, outcome.instance["id"])
    assert row["state"] == "stopped"  # and never resurrects the row
    conn.close()

def test_stop_instance_escalates_to_kill_after_grace(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    outcome = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    )
    kills = []

    def _kill(pid, sig):
        kills.append(sig)

    monkeypatch.setattr(supervisor.os, "kill", _kill)

    def always_up(*args):
        return "ok" if len(kills) < 2 else "down"

    stop_instance(
        conn, grace_s=0.05, poll_interval=0.01,
        probe=always_up, identify=lambda *a, **k: "owned",
    )
    assert len(kills) == 2  # SIGTERM then the SIGKILL-equivalent escalation
    conn.close()

def test_active_instance_prefers_latest(tmp_path):
    conn = _db(tmp_path)
    first = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    ).instance
    second = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    ).instance
    assert active_instance(conn)["id"] == second["id"]
    stop_instance(conn, identify=lambda *a, **k: "owned")
    # stop is latest-first: the older row must still be active here
    # (Codex determinism fold: the old assertion expected None wrongly)
    assert active_instance(conn)["id"] == first["id"]
    stop_instance(conn, identify=lambda *a, **k: "owned")
    assert active_instance(conn) is None
    assert [row["id"] for row in recent_instances(conn)] == [second["id"], first["id"]]
    conn.close()

def test_completion_records_roundtrip(tmp_path):
    conn = _db(tmp_path)
    instance = start_instance(
        conn, ["engine"], **_spawned_kwargs(tmp_path, _FakeProc(), lambda *a: "ok")
    ).instance
    record_completion(
        conn, instance_id=instance["id"], model_name="m",
        prompt_chars=5, output_chars=7, duration_ms=12, status="ok",
    )
    record_completion(
        conn, instance_id=instance["id"], model_name="m",
        prompt_chars=1, output_chars=0, duration_ms=3, status="error",
        detail="boom",
    )
    latest = last_completion(conn)
    assert latest["status"] == "error" and latest["detail"] == "boom"
    # restart-visible: a fresh connection sees the same rows (M0' slice proof)
    conn.close()
    fresh = open_db(tmp_path / "app.db")
    assert last_completion(fresh)["status"] == "error"
    fresh.close()

def test_service_states_match_migration_check(tmp_path):
    conn = _db(tmp_path)
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'instances'"
    ).fetchone()[0]
    for state in supervisor.SERVICE_STATES:
        assert f"'{state}'" in sql
    conn.close()

def test_engine_log_path_is_per_process_named(tmp_path):
    assert engine_log_path(tmp_path) == tmp_path / "logs" / "engine-llama-cpp.log"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/engines/test_supervisor.py -v`
Expected: FAIL —— `cannot import name 'choose_port'`（或 `No module named 'ipostudio.engines.repo'`）

- [ ] **Step 3: 写迁移与实现**

`src/ipostudio/store/migrations/003_instances.sql` 全文：

```sql
-- 003: engine instances and completion records (spec §10.1 instances/
-- addresses/activity; §10.2 service states; completions is the persistence
-- half of the M0' slice: records survive restarts).
CREATE TABLE IF NOT EXISTS instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine TEXT NOT NULL,
    engine_version TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL,
    model_path TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    pid INTEGER,
    state TEXT NOT NULL CHECK (state IN ('stopped','starting','loading','running','failed')),
    detail TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    stopped_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER NOT NULL REFERENCES instances(id),
    model_name TEXT NOT NULL,
    prompt_text TEXT NOT NULL DEFAULT '',
    output_text TEXT NOT NULL DEFAULT '',
    prompt_chars INTEGER NOT NULL,
    output_chars INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','error')),
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

`src/ipostudio/engines/supervisor.py` 全文：

```python
"""Single-instance llama.cpp supervision for the core loop.

Spec §5.3 minimal slice; multi-instance, idle unload and auto-tune are P3.
State literals are the §10.2 service states, pinned by the 003 migration's
CHECK constraint.  The database row is the coordination point between
separate CLI processes: `start` spawns and exits (the engine is intentionally
orphaned — no platform-specific detach APIs, R1), later `stop`/`status` runs
trust the row plus a live health probe.

Known M0' limitation, symmetric on all three platforms: closing the terminal
that started the server may take the engine down with it; the durable
background service is P3 scope (ADR-004)."""

import os
import signal
import socket
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ipostudio.logs import redact_text

SERVICE_STATES = ("stopped", "starting", "loading", "running", "failed")
ENGINE_LOG_FILE = "engine-llama-cpp.log"  # TODO-004 convention: per-process file

_INSTANCE_COLUMNS = (
    "id, engine, engine_version, model_name, model_path, host, port, pid, "
    "state, detail, started_at, stopped_at, created_at, updated_at"
)

@dataclass
class StartOutcome:
    instance: dict
    ok: bool

def engine_log_path(data_dir: Path) -> Path:
    return data_dir / "logs" / ENGINE_LOG_FILE

def _now() -> str:
    # ENG F9: match SQLite datetime('now') formatting so one column never
    # mixes "2026-10-05 08:00:00" and ISO "2026-10-05T08:00:00+00:00"
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

def probe_health(host: str, port: int, timeout_s: float) -> str:
    """'ok' | 'loading' | 'down'.  llama-server answers 503 while the model
    loads and 200 once ready (documented engine behaviour)."""
    import urllib.error
    import urllib.request

    host_part = f"[{host}]" if ":" in host else host
    try:
        with urllib.request.urlopen(
            f"http://{host_part}:{port}/health", timeout=timeout_s
        ) as response:
            return "ok" if response.status == 200 else "down"
    # HTTPError subclasses OSError: this arm must come first
    except urllib.error.HTTPError as exc:
        return "loading" if exc.code == 503 else "down"
    except OSError:
        return "down"

def choose_port(host: str, base_port: int, candidates: int = 20) -> int | None:
    """First bindable port at/after base_port (§5.3: an occupied configured
    port is replaced by a free one whose actual address is displayed; §15
    caps candidate scans at about 20).  The socket family follows the host
    literal so an IPv6 loopback configuration probes IPv6 binds (Codex
    address-family fold); the range is capped at 65536 so a configured port
    of 65535 cannot raise OverflowError on bind (Codex boundary fold)."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    for port in range(max(base_port, 1), min(base_port + candidates, 65536)):
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    return None

def _get(conn: sqlite3.Connection, instance_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances WHERE id = ?", (instance_id,)
    ).fetchone()
    return dict(row)

def _touch(
    conn: sqlite3.Connection, instance_id: int, *, expect=None, **fields
) -> bool:
    """Conditional row update.  `expect` restricts the write to rows still
    in one of the given states (Codex race fold): a concurrent `stop` can
    retire a `starting` row and the still-running startup then loses every
    subsequent transition instead of resurrecting the row."""
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = [*fields.values(), _now(), instance_id]
    if expect is None:
        cur = conn.execute(
            f"UPDATE instances SET {assignments}, updated_at = ? WHERE id = ?",
            values,
        )
    else:
        states = ", ".join("?" for _ in expect)
        cur = conn.execute(
            f"UPDATE instances SET {assignments}, updated_at = ? "
            f"WHERE id = ? AND state IN ({states})",
            [*values, *expect],
        )
    conn.commit()
    return cur.rowcount > 0

def _tail(path: Path, lines: int = 15) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(engine log not readable)"
    picked = content.splitlines()[-lines:]
    return redact_text(" | ".join(picked))[:1500]

def _fail_row(
    conn: sqlite3.Connection, instance_id: int, detail: str, *, expect=None
) -> None:
    _touch(conn, instance_id, state="failed", detail=detail[:2000], expect=expect)

def _engine_version(engine: str) -> str:
    """Best-effort `--version` probe: the instance row records WHICH engine
    build served, so argv-compatibility failures are diagnosable later (CEO
    review).  Never fatal — an engine without --version records ""."""
    try:
        proc = subprocess.run(
            [engine, "--version"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return first[0][:200] if first else ""

def start_instance(
    conn: sqlite3.Connection,
    argv: list[str],
    *,
    engine: str,
    model_name: str,
    model_path: str,
    host: str,
    port: int,
    log_path: Path,
    timeout_s: float,
    poll_interval: float = 0.5,
    probe=probe_health,
    spawn=subprocess.Popen,
) -> StartOutcome:
    engine_version = _engine_version(argv[0])
    conn.execute(
        "INSERT INTO instances (engine, engine_version, model_name, model_path, "
        "host, port, pid, state, detail) VALUES (?, ?, ?, ?, ?, ?, NULL, "
        "'starting', '')",
        (engine, engine_version, model_name, model_path, host, port),
    )
    conn.commit()
    instance_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def outcome(ok: bool) -> StartOutcome:
        return StartOutcome(_get(conn, instance_id), ok)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_handle = log_path.open("ab")
    except OSError as exc:
        _fail_row(conn, instance_id, f"cannot open engine log {log_path}: {exc}")
        return outcome(False)
    try:
        try:
            proc = spawn(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
            )
        except OSError as exc:
            _fail_row(conn, instance_id, f"cannot start engine {argv[0]}: {exc}")
            return outcome(False)
        _touch(conn, instance_id, pid=proc.pid)
        deadline = time.monotonic() + timeout_s
        observed = "starting"
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    _fail_row(
                        conn, instance_id,
                        f"engine exited during startup with code {proc.returncode}; "
                        f"last log lines: {_tail(log_path)}",
                    )
                    return outcome(False)
                health = probe(host, port, 1.5)
                if health == "ok":
                    # expect=: a concurrent stop must win the race (Codex
                    # fold) — if it retired the row, do not resurrect it
                    if not _touch(conn, instance_id, state="running",
                                  detail="", started_at=_now(),
                                  expect=("starting", "loading")):
                        proc.terminate()
                        return outcome(False)
                    return outcome(True)
                if health == "loading" and observed != "loading":
                    observed = "loading"
                    if not _touch(conn, instance_id, state="loading",
                                  expect=("starting",)):
                        proc.terminate()
                        return outcome(False)
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            proc.terminate()
            _fail_row(conn, instance_id, "startup wait interrupted (Ctrl+C)",
                      expect=("starting", "loading"))
            return outcome(False)
        # Codex orphan fold: a timed-out engine must never outlive a failed
        # start unmanaged — the old flow marked the row failed and left the
        # process running, and `ipo server stop` (active states only) could
        # never reach it
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _signal(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        _fail_row(
            conn, instance_id,
            f"health check did not report ready within {timeout_s:g}s; the "
            f"engine process was terminated — inspect `ipo server logs`, then "
            f"start again (raise --timeout if the model needs longer to load)",
            expect=("starting", "loading"),
        )
        return outcome(False)
    finally:
        log_handle.close()

def probe_identity(
    host: str, port: int, model_path: str, timeout_s: float
) -> str:
    """'owned' | 'foreign' | 'absent' (Codex stop fold).  A health status
    alone cannot prove PID ownership — any 200/503 on the port would
    authorize a kill.  llama-server documents GET /props with the served
    model, so the guard requires the recorded model path to appear in that
    document before any signal is sent.  Residual risk (the recorded PID
    recycled while the port still serves this model) stays with TODO-016."""
    import urllib.error
    import urllib.request

    host_part = f"[{host}]" if ":" in host else host
    try:
        with urllib.request.urlopen(
            f"http://{host_part}:{port}/props", timeout=timeout_s
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError:
        return "absent"
    except OSError:
        return "absent"
    return "owned" if model_path in body else "foreign"

def stop_instance(
    conn: sqlite3.Connection,
    *,
    grace_s: float = 10.0,
    poll_interval: float = 0.25,
    probe=probe_health,
    identify=probe_identity,
) -> dict | None:
    """Stop the most recent active instance.  Kill guard (Codex fold): a
    signal is only issued while the recorded port answers /props naming the
    recorded model; a foreign document refuses the stop with manual
    guidance; a silent port sends no signal at all (a blind kill could hit a
    recycled PID).  State writes are conditional on the row still being
    active, so a concurrent start cannot resurrect a stopped row.
    os.kill is the cross-platform API: POSIX sends SIGTERM, Windows maps it
    to TerminateProcess (no graceful shutdown there — ADR-010 backlog)."""
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances "
        "WHERE state IN ('starting','loading','running') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    instance = dict(row)
    pid = instance["pid"]
    detail = instance["detail"]
    if pid is not None:
        identity = identify(instance["host"], instance["port"],
                            instance["model_path"], 2.0)
        if identity == "owned":
            _signal(pid, signal.SIGTERM)
            deadline = time.monotonic() + grace_s
            while time.monotonic() < deadline:
                if identify(instance["host"], instance["port"],
                            instance["model_path"], 1.0) == "absent":
                    break
                time.sleep(poll_interval)
            else:
                _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        elif identity == "foreign":
            _touch(
                conn, instance["id"],
                detail=(detail + "; " if detail else "") + (
                    "port answers with a different model document — verify "
                    f"PID {pid} manually before any manual termination"
                ),
                expect=("starting", "loading", "running"),
            )
            return _get(conn, instance["id"])
        else:  # absent: nothing serves the recorded port
            detail = (detail + "; " if detail else "") + (
                "port not answering; no stop signal was sent (identity "
                f"unprovable) — if a process remains, check PID {pid} manually"
            )
    _touch(
        conn, instance["id"], state="stopped", stopped_at=_now(),
        detail=detail, expect=("starting", "loading", "running"),
    )
    return _get(conn, instance["id"])

def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except OSError:
        pass  # already gone — the conditional state write is what matters
```

`src/ipostudio/engines/repo.py` 全文：

```python
"""Repository functions for instances and completions (ADR-002).

Dependency direction: SERVICE_STATES and the row primitives live in
supervisor.py; this module adds the query/insert surface and never gets
imported by the supervisor (no cycle)."""

import sqlite3

from ipostudio.engines.supervisor import SERVICE_STATES
from ipostudio.logs import redact_text

__all__ = [
    "SERVICE_STATES",
    "active_instance",
    "get_instance",
    "last_completion",
    "recent_instances",
    "record_completion",
]

_INSTANCE_COLUMNS = (
    "id, engine, engine_version, model_name, model_path, host, port, pid, "
    "state, detail, started_at, stopped_at, created_at, updated_at"
)

def get_instance(conn: sqlite3.Connection, instance_id: int) -> dict | None:
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances WHERE id = ?", (instance_id,)
    ).fetchone()
    return dict(row) if row else None

def active_instance(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances "
        "WHERE state IN ('starting','loading','running') ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None

def recent_instances(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_INSTANCE_COLUMNS} FROM instances ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]

def record_completion(
    conn: sqlite3.Connection,
    *,
    instance_id: int,
    model_name: str,
    prompt_text: str = "",
    output_text: str = "",
    prompt_chars: int,
    output_chars: int,
    duration_ms: int,
    status: str,
    detail: str = "",
) -> None:
    """Persist one completion attempt.  Secret-shaped substrings are
    redacted HERE, at the persistence boundary — display-time redaction
    cannot unsave what was already written (Codex trust fold)."""
    with conn:
        conn.execute(
            "INSERT INTO completions (instance_id, model_name, prompt_text, "
            "output_text, prompt_chars, output_chars, duration_ms, status, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (instance_id, model_name, redact_text(prompt_text)[:2000],
             redact_text(output_text)[:2000], prompt_chars, output_chars,
             duration_ms, status, redact_text(detail)[:2000]),
        )

def last_completion(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id, instance_id, model_name, prompt_text, output_text, "
        "prompt_chars, output_chars, duration_ms, status, detail, created_at "
        "FROM completions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
```

（注：`get_instance` 在 repo 与 supervisor 的 `_get` 语义相同——repo 版是公开查询面，supervisor 内部用 `_get`；二者并存是依赖方向锁定的代价，评审如认为应合并，按"repo 导入 supervisor 私有名不可取"原则保持现状。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/engines/test_supervisor.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿

```bash
git add src/ipostudio/engines src/ipostudio/store/migrations/003_instances.sql tests/engines/test_supervisor.py
git commit -m "feat: supervise a llama.cpp instance with sqlite-backed state"
```

---

### Task 5: `ipo server` 组（start/stop/restart/list/info/logs）

**Files:**
- Create: `src/ipostudio/cli/server_cmd.py`
- Modify: `src/ipostudio/cli/main.py`（注册 `server` 组）
- Test: `tests/cli/test_server_cmd.py`（新建）

**Interfaces:**
- Consumes: Task 1/3/4 全部 Produces；`cli/base.py` 的 `_SuggestingGroup` / `open_config_and_db` / `_fail`。
- Produces（Task 6/7 依赖）:
  - `server_cmd._run_start(conn, cfg, model_name: str | None, host: str | None, port: int | None, timeout_s: float) -> None` — 失败路径自行 exit 1；成功打印运行地址。Task 6 的 `ipo start` / `ipo restart` 直接复用。
  - `server_cmd.DEFAULT_TIMEOUT_S = 600.0`。

- [ ] **Step 1: 写失败测试**

`tests/cli/test_server_cmd.py` 全文：

```python
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from ipostudio.cli.main import cli

FAKE = Path(__file__).resolve().parents[1] / "engines" / "fake_llama_server.py"
GGUF = b"GGUF" + b"\x00" * 28

@pytest.fixture
def service_env(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    result = runner.invoke(cli, ["config", "set", "server_port", "18400"])
    assert result.exit_code == 0, result.output
    return tmp_path

def _patch_fake_engine(monkeypatch):
    from ipostudio.cli import server_cmd

    monkeypatch.setattr(
        server_cmd, "resolve_engine",
        lambda configured: (Path(sys.executable), None),
    )

    def _fake_argv(engine, model_path, host, port, tuning, extra_args):
        return [sys.executable, str(FAKE), "--host", host, "--port", str(port),
                "--model", str(model_path)]

    monkeypatch.setattr(server_cmd, "build_server_argv", _fake_argv)

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_server_start_reports_missing_engine_honestly(service_env):
    # deterministic on every machine: a configured path that does not exist
    # is reported without depending on whether the dev box has llama-server
    runner = CliRunner()
    ghost = service_env / "ghost-engine"
    assert runner.invoke(
        cli, ["config", "set", "llama_cpp_path", str(ghost)]
    ).exit_code == 0
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("server", "start")
    assert started.exit_code == 1
    assert "does not exist" in started.stderr
    assert "llama_cpp_path" in started.stderr

def test_server_start_without_model_guides_selection(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    started = _invoke("server", "start")
    assert started.exit_code == 1
    assert "ipo model --select" in started.stderr

def test_server_start_reaches_running_and_stop_works(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("server", "start", "--timeout", "20")
    assert started.exit_code == 0, started.stderr
    assert "server running" in started.output
    assert "http://127.0.0.1:18400" in started.output
    info = _invoke("server", "info")
    assert info.exit_code == 0
    assert "running" in info.output
    stopped = _invoke("server", "stop")
    assert stopped.exit_code == 0
    assert "stopped" in stopped.output
    again = _invoke("server", "stop")
    assert again.exit_code == 0  # idempotent
    assert "no running server" in again.output

def test_server_start_twice_refuses_with_restart_hint(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("server", "start", "--timeout", "20").exit_code == 0
    try:
        second = _invoke("server", "start", "--timeout", "20")
        assert second.exit_code == 1
        assert "already" in second.stderr
        assert "ipo server restart" in second.stderr
    finally:
        _invoke("server", "stop")

def test_server_start_avoids_occupied_configured_port(service_env, monkeypatch):
    import socket

    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 18400))
        sock.listen(1)
        started = _invoke("server", "start", "--timeout", "20")
        assert started.exit_code == 0, started.stderr
        assert "http://127.0.0.1:1840" in started.output  # moved off 18400
    _invoke("server", "stop")

def test_server_info_and_list_report_state(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("server", "start", "--timeout", "20").exit_code == 0
    try:
        info = _invoke("server", "info", "--json")
        assert info.exit_code == 0
        payload = json.loads(info.output)
        assert payload["instance"]["state"] == "running"
        assert payload["instance"]["model_name"] == "tiny-q4"
        listing = _invoke("server", "list", "--json")
        rows = json.loads(listing.output)
        assert rows["count"] >= 1
        logs = _invoke("server", "logs")
        assert logs.exit_code == 0
    finally:
        _invoke("server", "stop")

def test_server_info_empty_is_a_valid_state(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("server", "info", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["instance"] is None
    text = _invoke("server", "info")
    assert "stopped" in text.output

def test_explicit_port_is_not_replaced(service_env, monkeypatch):
    import socket

    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 18555))
        sock.listen(1)
        started = _invoke("server", "start", "--port", "18555", "--timeout", "5")
        assert started.exit_code == 1
        assert "exited during startup" in started.stderr
    _invoke("server", "stop")

def test_reserved_tuning_warns_on_stderr(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    runner = CliRunner()
    assert runner.invoke(
        cli, ["config", "set", "server_auto_tune", "true"]
    ).exit_code == 0
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("server", "start", "--timeout", "20")
    assert started.exit_code == 0, started.stderr
    # spec §1.3 rule 3 (ruling #10): reserved capability is labelled, never silent
    assert "server_auto_tune" in started.stderr
    assert "not implemented yet" in started.stderr
    _invoke("server", "stop")

def test_remote_mode_and_non_llama_engine_are_honest(service_env):
    runner = CliRunner()
    assert runner.invoke(cli, ["config", "set", "server_mode", "remote"]).exit_code == 0
    blocked = _invoke("server", "start")
    assert blocked.exit_code == 1
    assert "remote" in blocked.stderr
    assert runner.invoke(cli, ["config", "set", "server_mode", "local"]).exit_code == 0
    assert runner.invoke(
        cli, ["config", "set", "inference_engine", "vllm"]
    ).exit_code == 0
    blocked = _invoke("server", "start")
    assert blocked.exit_code == 1
    assert "llama.cpp" in blocked.stderr
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/cli/test_server_cmd.py -v`
Expected: FAIL —— unknown command 'server'

- [ ] **Step 3: 实现**

`src/ipostudio/cli/server_cmd.py` 全文：

```python
"""`ipo server` management (spec §9.11).

start spawns the engine and exits; the SQLite instance row is the
coordination point for later stop/status processes (supervisor docstring has
the process model).  Contract: `server info`/`server list` are informational
and exit 0 even when nothing runs — the QA --json walker invokes them on a
fresh data directory and requires exit 0."""

import json
import math
from pathlib import Path

import click

from ipostudio.catalog.repo import find_model
from ipostudio.catalog.scan import shard_family_complete
from ipostudio.cli.base import (
    _SuggestingGroup,
    _fail,
    open_config_and_db,
    open_db_only,
)
from ipostudio.conf.paths import resolve_data_dir
from ipostudio.engines.discovery import resolve_engine
from ipostudio.engines.llama_server import build_server_argv
from ipostudio.engines.repo import (
    active_instance,
    last_completion,
    recent_instances,
)
from ipostudio.engines.supervisor import (
    choose_port,
    engine_log_path,
    probe_health,
    start_instance,
    stop_instance,
)
from ipostudio.logs import redact_text

DEFAULT_TIMEOUT_S = 600.0  # spec §15: local inference budget

def _resolve_model(conn, cfg, wanted: str | None) -> dict:
    # ENG F10: one scan-and-upsert helper serves both `ipo models` and the
    # server path, so the two surfaces always see the same catalog view
    from ipostudio.cli.models_cmd import _refresh

    _refresh(conn, cfg)
    target = wanted or cfg.general.local_chat_model
    if not target:
        _fail(
            "no model selected; run `ipo model --select NAME` "
            "(catalog: `ipo models`)"
        )
    matches = find_model(conn, target)
    if not matches:
        _fail(f"no local model matches {target!r}; run `ipo models`")
    if len(matches) > 1:
        _fail(f"ambiguous model match for {target!r}; use a full name or path")
    model = matches[0]
    # ENG F3: the catalog is insert-only until P2 pruning — a deleted file
    # must fail here with a rescan hint, not surface as an engine crash
    if not Path(model["path"]).exists():
        _fail(
            f"model file no longer exists: {model['path']}; it may have been "
            f"moved or deleted — re-run `ipo models` to refresh the catalog"
        )
    # insert-only catalog: a family that lost a shard after registration
    # would crash the engine mid-load — revalidate before launch (Codex
    # stale-row fold)
    if not shard_family_complete(Path(model["path"])):
        _fail(
            f"model {model['name']!r} is incomplete on disk (a shard is "
            f"missing); re-run `ipo models` and re-register the full set"
        )
    return model

def _warn_reserved_tuning(cfg) -> None:
    """Spec §1.3 rule 3: reserved capability must be labelled, never silent."""
    if cfg.tuning.server_auto_tune:
        click.echo(
            "warning: server_auto_tune is on but automatic planning is not "
            "implemented yet; using your configured values as-is",
            err=True,
        )
    if cfg.tuning.server_idle_unload_minutes:
        click.echo(
            "warning: server_idle_unload_minutes is set but idle unloading is "
            "not implemented yet; the server stays up",
            err=True,
        )
    if cfg.tuning.server_fallback_models:
        click.echo(
            "warning: server_fallback_models is set but fallback is not "
            "implemented yet; the list is ignored",
            err=True,
        )

def _run_start(conn, cfg, model_name: str | None, host: str | None,
               port: int | None, timeout_s: float) -> None:
    """Shared by `ipo server start`, `ipo start` and `ipo restart`."""
    if port is not None and not 1 <= port <= 65535:
        _fail(f"--port must be within 1..65535, got {port}")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        _fail("--timeout must be a finite positive number of seconds")
    if cfg.general.server_mode != "local":
        _fail(
            f"server_mode is {cfg.general.server_mode!r}; remote operation "
            f"arrives with the gateway plan — switch back with "
            f"`ipo config set server_mode local`"
        )
    if cfg.general.inference_engine != "llama.cpp":
        _fail(
            f"inference_engine is {cfg.general.inference_engine!r}; only "
            f"llama.cpp is supported in this build (vllm/sglang/mlx arrive "
            f"with the engine-supervision plan) — switch back with "
            f"`ipo config set inference_engine llama.cpp`"
        )
    _warn_reserved_tuning(cfg)
    running = active_instance(conn)
    if running is not None:
        _fail(
            f"server already {running['state']} at "
            f"http://{running['host']}:{running['port']} "
            f"(model {running['model_name']}); use `ipo server restart` "
            f"to swap models"
        )
    engine_path, problem = resolve_engine(cfg.engines.llama_cpp_path)
    if engine_path is None:
        _fail(problem)
    model = _resolve_model(conn, cfg, model_name)
    host = host or cfg.general.server_host
    port_given = port is not None
    if port is None:
        port = choose_port(host, cfg.general.server_port)
        if port is None:
            _fail(
                f"no free port in {cfg.general.server_port}.."
                f"{cfg.general.server_port + 19} on {host}"
            )
    if host not in ("127.0.0.1", "localhost", "::1"):
        click.echo(
            f"warning: binding {host} exposes the engine's UNAUTHENTICATED "
            f"completions endpoint to your network; keep server_host on "
            f"loopback unless you accept that",
            err=True,
        )
    argv = build_server_argv(
        engine_path, Path(model["path"]), host, port, cfg.tuning,
        cfg.engines.llama_cpp_extra_args,
    )
    log_path = engine_log_path(resolve_data_dir())
    outcome = start_instance(
        conn, argv, engine="llama.cpp", model_name=model["name"],
        model_path=model["path"], host=host, port=port, log_path=log_path,
        timeout_s=timeout_s,
    )
    instance = outcome.instance
    if not outcome.ok:
        detail = instance["detail"]
        if port_given:
            detail += (
                f" (you passed --port {port}; verify that port is free "
                f"on {host})"
            )
        _fail(detail)
    click.echo(
        f"server running: http://{host}:{port} (model {model['name']}, "
        f"pid {instance['pid']}, log {log_path})"
    )
    click.echo("note: closing the terminal that started the server may stop it "
               "(durable background service arrives with the engine plan)")
    click.echo('try `ipo chat "hello"` or `ipo status`')

@click.group("server", cls=_SuggestingGroup)
def server() -> None:
    """Manage the local inference server (subcommands: start, stop, restart,
    list, info, logs)."""

@server.command("start")
@click.option("--model", "model_name", default=None, metavar="NAME",
              help="model to serve (default: the active chat model)")
@click.option("--host", default=None, help="override the configured server_host")
@click.option("--port", type=int, default=None,
              help="exact port to bind (no avoidance is applied; default: the "
                   "configured server_port with occupied-port avoidance)")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True, help="seconds to wait for engine readiness")
def server_start(model_name: str | None, host: str | None, port: int | None,
                 timeout_s: float) -> None:
    """Start the llama.cpp server for the active (or named) model."""
    conn, cfg = open_config_and_db()
    try:
        _run_start(conn, cfg, model_name, host, port, timeout_s)
    finally:
        conn.close()

@server.command("stop")
def server_stop() -> None:
    """Stop the running server instance (idempotent)."""
    conn = open_db_only()
    try:
        stopped = stop_instance(conn)
    finally:
        conn.close()
    if stopped is None:
        click.echo("no running server instance")
        return
    if stopped["state"] != "stopped":
        # identity guard refused the kill — never claim success (Codex fold)
        _fail(f"stop refused: {stopped['detail']}")
    click.echo(
        f"server stopped (model {stopped['model_name']}, "
        f"was http://{stopped['host']}:{stopped['port']})"
    )
    if stopped["detail"]:
        click.echo(f"note: {stopped['detail']}")

@server.command("restart")
@click.option("--model", "model_name", default=None, metavar="NAME")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True)
def server_restart(model_name: str | None, timeout_s: float) -> None:
    """Stop then start the server (applies a new --model or config)."""
    conn, cfg = open_config_and_db()
    try:
        # precheck BEFORE stopping (Codex DX fold): a bad request must not
        # cost the user a running server; --model stays temporary here —
        # `ipo restart` is the persisting shorthand
        engine_path, problem = resolve_engine(cfg.engines.llama_cpp_path)
        if engine_path is None:
            _fail(problem)
        if model_name is not None:
            _resolve_model(conn, cfg, model_name)  # resolve-only precheck
        stop_instance(conn)
        _run_start(conn, cfg, model_name, None, None, timeout_s)
    finally:
        conn.close()

@server.command("list")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
@click.option("--limit", type=int, default=20, show_default=True)
def server_list(as_json: bool, limit: int) -> None:
    """List recent server instances with their states."""
    conn = open_db_only()
    try:
        rows = recent_instances(conn, limit)
    finally:
        conn.close()
    if as_json:
        click.echo(json.dumps({"count": len(rows), "instances": rows},
                              ensure_ascii=False, indent=2))
        return
    if not rows:
        click.echo("no server instances yet (start one with `ipo server start`)")
        return
    click.echo("ID  STATE      MODEL             ADDRESS               PID")
    for row in rows:
        address = f"{row['host']}:{row['port']}"
        pid = row["pid"] if row["pid"] is not None else "-"
        click.echo(
            f"{row['id']:<3} {row['state']:<10} {row['model_name']:<17} "
            f"{address:<21} {pid}"
        )

@server.command("info")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def server_info(as_json: bool) -> None:
    """Show the current instance, live health and last completion."""
    conn = open_db_only()
    try:
        instance = active_instance(conn)
        completion = last_completion(conn)
        health = None
        if instance is not None:
            health = probe_health(instance["host"], instance["port"], 2.0)
    finally:
        conn.close()
    if as_json:
        click.echo(
            json.dumps(
                {"instance": instance, "health": health,
                 "last_completion": completion},
                ensure_ascii=False, indent=2,
            )
        )
        return
    if instance is None:
        click.echo("server: stopped (start with `ipo server start`)")
        if completion is not None:
            _print_completion(completion)
        return
    click.echo(
        f"server: {instance['state']} at http://{instance['host']}:"
        f"{instance['port']} (model {instance['model_name']}, "
        f"pid {instance['pid']})"
    )
    click.echo(f"health: {health}")
    if instance["state"] == "running" and health != "ok":
        click.echo(
            "not responding — the engine may have exited; see `ipo server logs` "
            "or stop it with `ipo server stop`"
        )
    if instance["detail"]:
        click.echo(f"detail: {instance['detail']}")
    if completion is not None:
        _print_completion(completion)

def _print_completion(completion: dict) -> None:
    click.echo(
        f"last completion: {completion['status']} "
        f"({completion['output_chars']} chars in {completion['duration_ms']} ms, "
        f"{completion['created_at']})"
    )
    # the stored exchange is the recall value of the record (CEO review):
    # what was asked and what the model answered, truncated for the terminal
    prompt = completion.get("prompt_text") or ""
    output = completion.get("output_text") or ""
    if prompt:
        click.echo(f"  prompt: {prompt[:120]}{'…' if len(prompt) > 120 else ''}")
    if output:
        click.echo(f"  answer: {output[:200]}{'…' if len(output) > 200 else ''}")

@server.command("logs")
@click.option("--lines", type=int, default=50, show_default=True,
              help="tail length")
def server_logs(lines: int) -> None:
    """Show the tail of the engine log file."""
    path = engine_log_path(resolve_data_dir())
    if not path.exists():
        click.echo("no engine log yet (start the server first)")
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    tail = content.splitlines()[-lines:] if lines > 0 else content.splitlines()
    for line in tail:
        # engine output is third-party text: the redaction layer applies on
        # display just as it does on failure-detail tails (ENG F5)
        click.echo(redact_text(line))
```

`src/ipostudio/cli/main.py` 注册（追加到 Task 2 的注册块）：

```python
from ipostudio.cli.server_cmd import server

cli.add_command(server)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/cli/test_server_cmd.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿

```bash
git add src/ipostudio/cli/server_cmd.py src/ipostudio/cli/main.py tests/cli/test_server_cmd.py
git commit -m "feat: add ipo server lifecycle commands"
```

---

### Task 6: `ipo start` + `ipo status/stop/restart` 简写 + 欢迎卡回路化

**Files:**
- Modify: `src/ipostudio/cli/server_cmd.py`（新增四个顶层命令）
- Modify: `src/ipostudio/cli/main.py`（注册四命令 + `WELCOME_STEPS` 三步更新 + `_welcome_text` 箭头逻辑）
- Modify: `tests/cli/test_main.py`（欢迎卡断言更新）
- Modify: `tests/qa/test_cli_ux_adversarial.py`（walker 子集加 `status --json`）
- Test: `tests/cli/test_server_cmd.py`（追加）

**Interfaces:**
- Consumes: Task 5 的 `_run_start` / `DEFAULT_TIMEOUT_S`；`engines.supervisor` 的 `stop_instance` / `probe_health`；`engines.repo` 的 `active_instance`；Task 2 的 `activate_model`。
- Produces: 顶层命令 `start` / `status` / `stop` / `restart`；`WELCOME_STEPS` 引用 `ipo models`（Task 2 已注册，满足既有"卡片只引用已注册命令"守卫）。

- [ ] **Step 1: 写失败测试**

追加到 `tests/cli/test_server_cmd.py`：

```python
def test_start_shorthand_boots_the_default_service(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    started = _invoke("start")
    assert started.exit_code == 0, started.stderr
    assert "server running" in started.output
    _invoke("stop")

def test_start_shorthand_honors_auto_start_off(service_env):
    runner = CliRunner()
    assert runner.invoke(
        cli, ["config", "set", "auto_start_server", "false"]
    ).exit_code == 0
    result = _invoke("start")
    assert result.exit_code == 0
    assert "auto_start_server is off" in result.output

def test_start_shorthand_is_idempotent_when_running(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("start").exit_code == 0
    again = _invoke("start")
    assert again.exit_code == 0
    assert "already running" in again.output
    _invoke("stop")

def test_start_selects_model_then_boots(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    started = _invoke("start", "--model", "tiny-q4")
    assert started.exit_code == 0, started.stderr
    active = _invoke("config", "get", "local_chat_model")
    assert "tiny-q4" in active.output
    _invoke("stop")

def test_reserved_flags_fail_with_plan_pointers(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    cloud = _invoke("start", "--cloud")
    assert cloud.exit_code == 1
    assert "reserved" in cloud.stderr and "gateway" in cloud.stderr
    app = _invoke("start", "--app-path", "D:/apps/demo")
    assert app.exit_code == 1
    assert "reserved" in app.stderr

def test_status_json_stays_clean_when_stopped(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("status", "--json")
    assert result.exit_code == 0
    assert "\x1b[" not in result.output
    payload = json.loads(result.output)
    assert payload["state"] == "stopped"

def test_stop_and_restart_shorthands(service_env, monkeypatch):
    _patch_fake_engine(monkeypatch)
    assert _invoke("model", "--select", "tiny-q4").exit_code == 0
    assert _invoke("start").exit_code == 0
    assert _invoke("restart").exit_code == 0
    assert "running" in _invoke("status").output
    stopped = _invoke("stop")
    assert stopped.exit_code == 0
    assert "stopped" in stopped.output
```

`tests/cli/test_main.py` 的欢迎卡断言更新（行号以当前实现为准）：

1. :557 `assert "ipo config list" in result.output`（欢迎卡用例内）→ 改为 `ipo models`。注意 :366 的 `ipo config list` 属于 config-get 未知键错误文案（`see \`ipo config list\``），**不是**欢迎卡断言，不得改动。
2. :607-618 `test_welcome_card_marks_next_step_by_state`：两处 `guide_line = next(... "ipo guide" ...)` → 改为取含 `ipo models` 的行（变量名改 `models_line`），断言不变（未初始化箭头在 doctor 行、已初始化箭头在 models 行）。
3. :585-592 `test_global_flags_without_subcommand_still_show_welcome` 断言 `ipo guide`——guide 仍是第三步，**不改**。
4. :621 `test_welcome_card_only_references_registered_commands` 从 `WELCOME_STEPS` 泛化推导——**不改**。

`tests/qa/test_cli_ux_adversarial.py` walker 子集再扩：加 `"status --json"`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/cli/test_server_cmd.py tests/cli/test_main.py tests/qa -v`
Expected: FAIL —— unknown command 'start'；欢迎卡断言失败

- [ ] **Step 3: 实现**

`src/ipostudio/cli/server_cmd.py`：

1. import 区补（Codex P0 折叠：`start --model` 调用的扫描/登记名此前缺失，会在首跑路径触发 NameError；`ConfigError` 是 save 权限/锁冲突的既有错误契约）：**Task 5 已导入 `open_db_only`，此处不得重复**：

```python
from ipostudio.catalog.repo import upsert_models
from ipostudio.catalog.scan import model_scan_roots, scan_model_files
from ipostudio.cli.models_cmd import activate_model
from ipostudio.conf.loader import ConfigError
```

2. 文件末尾追加四个顶层命令：

```python
@click.command("start")
@click.option("--server", "as_server", is_flag=True, default=True,
              help="start the inference server (the default action; the flag "
                   "exists for spec §9.11 option parity and is accepted but "
                   "always on)")
@click.option("--model", "model_name", default=None, metavar="NAME",
              help="activate this model, then start the server")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True)
@click.option("--cloud", "cloud", is_flag=True, default=False,
              help="reserved: cloud providers arrive with the gateway plan")
@click.option("--app-path", "app_path", default=None,
              help="reserved: the desktop shell arrives with the P20 plan")
def start(as_server: bool, model_name: str | None, timeout_s: float,
          cloud: bool, app_path: str | None) -> None:
    """Start the app's default services (spec §9.11)."""
    if cloud or app_path:
        reserved = " --cloud" if cloud else ""
        reserved += " --app-path" if app_path else ""
        _fail(
            f"{reserved.strip()} is reserved for a later milestone (gateway "
            f"plan / desktop shell plan) and is not available in this build; "
            f"see `ipo guide`"
        )
    conn, cfg = open_config_and_db()
    try:
        if model_name is not None:
            # ENG F7: an explicit selection is honored even when the gates
            # below skip the start — the user asked for the activation
            files, _skipped, _truncated = scan_model_files(
                model_scan_roots(cfg.general.model_dirs, resolve_data_dir())
            )
            upsert_models(conn, files)
            try:
                activate_model(conn, model_name, cfg)
            except (LookupError, ValueError, ConfigError) as exc:
                _fail(str(exc))
        running = active_instance(conn)
        if running is not None:
            click.echo(
                f"server already running at http://{running['host']}:"
                f"{running['port']} (model {running['model_name']}); "
                f"`ipo server restart` applies the new selection"
            )
            return
        if not cfg.general.auto_start_server:
            click.echo(
                "auto_start_server is off; nothing to start "
                "(enable with `ipo config set auto_start_server true`)"
            )
            return
        _run_start(conn, cfg, None, None, None, timeout_s)
    finally:
        conn.close()

@click.command("status")
@click.option("--json", "as_json", is_flag=True, help="emit machine-readable output")
def status(as_json: bool) -> None:
    """Show the default service status (exit 0 even when stopped)."""
    conn = open_db_only()
    try:
        instance = active_instance(conn)
        health = None
        if instance is not None:
            health = probe_health(instance["host"], instance["port"], 2.0)
    finally:
        conn.close()
    state = instance["state"] if instance is not None else "stopped"
    if as_json:
        click.echo(
            json.dumps(
                {"state": state, "instance": instance, "health": health},
                ensure_ascii=False, indent=2,
            )
        )
        return
    if instance is None:
        click.echo("server: stopped (start with `ipo start` or `ipo server start`)")
        return
    click.echo(
        f"server: {state} at http://{instance['host']}:{instance['port']} "
        f"(model {instance['model_name']}); health: {health}"
    )
    if instance["state"] == "running" and health != "ok":
        click.echo(
            "not responding — the engine may have exited; see `ipo server logs` "
            "or stop it with `ipo server stop`"
        )

@click.command("stop")
def stop() -> None:
    """Stop the default service (idempotent)."""
    conn = open_db_only()
    try:
        stopped = stop_instance(conn)
    finally:
        conn.close()
    if stopped is None:
        click.echo("no running server instance")
        return
    if stopped["state"] != "stopped":
        _fail(f"stop refused: {stopped['detail']}")
    click.echo(f"server stopped (model {stopped['model_name']})")
    if stopped["detail"]:
        click.echo(f"note: {stopped['detail']}")

@click.command("restart")
@click.option("--model", "model_name", default=None, metavar="NAME")
@click.option("--timeout", "timeout_s", type=float, default=DEFAULT_TIMEOUT_S,
              show_default=True)
def restart(model_name: str | None, timeout_s: float) -> None:
    """Restart the default service (applies config and model changes)."""
    conn, cfg = open_config_and_db()
    try:
        # precheck BEFORE stopping: a typo'd model or missing engine must
        # never cost the user a running server (Codex DX fold); the
        # selection persists, matching `ipo start --model` semantics
        engine_path, problem = resolve_engine(cfg.engines.llama_cpp_path)
        if engine_path is None:
            _fail(problem)
        if model_name is not None:
            try:
                activate_model(conn, model_name, cfg)
            except (LookupError, ValueError, ConfigError) as exc:
                _fail(str(exc))
            model_name = None  # selection persisted; start resolves it
        stop_instance(conn)
        _run_start(conn, cfg, model_name, None, None, timeout_s)
    finally:
        conn.close()
```

`src/ipostudio/cli/main.py`：

1. 注册块追加：
```python
from ipostudio.cli.server_cmd import restart, start, status, stop

cli.add_command(start)
cli.add_command(status)
cli.add_command(stop)
cli.add_command(restart)
```
2. `WELCOME_STEPS` 改为（中英同步）：
```python
WELCOME_STEPS: dict[str, list[tuple[str, str]]] = {
    "zh": [
        ("ipo doctor --fix", "初始化数据目录并完成环境体检"),
        ("ipo models", "扫描本地模型目录（先放入 .gguf 模型文件）"),
        ("ipo guide", "阅读完整命令手册"),
    ],
    "en": [
        ("ipo doctor --fix", "initialize the data directory and verify the environment"),
        ("ipo models", "scan the local model directories (drop in a .gguf first)"),
        ("ipo guide", "read the full command manual"),
    ],
}
```
3. `_welcome_text` 的 `is_next` 判定改为（docstring 同步：箭头语义 = 未初始化标 doctor --fix、已初始化标 models——核心回路的入口）：
```python
        is_next = (command == "ipo doctor --fix" and not initialized) or (
            command == "ipo models" and initialized
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/cli tests/qa -v`
Expected: 全部 PASS（含更新后的欢迎卡断言）

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿

```bash
git add src/ipostudio/cli tests/cli tests/qa/test_cli_ux_adversarial.py
git commit -m "feat: add ipo start/status/stop/restart and loop-focused welcome card"
```

---

### Task 7: `ipo chat` 一次性补全（engines/openai_client.py + cli/chat_cmd.py）

**Files:**
- Create: `src/ipostudio/engines/openai_client.py`
- Create: `src/ipostudio/cli/chat_cmd.py`
- Modify: `src/ipostudio/cli/main.py`（注册 `chat`）
- Test: `tests/engines/test_openai_client.py`（新建）、`tests/cli/test_chat_cmd.py`（新建）

**Interfaces:**
- Consumes: `cli/base.py` 的 `open_config_and_db` / `_fail`；`engines.repo` 的 `active_instance` / `record_completion`；`engines.supervisor` 的启动面（测试）。
- Produces:
  - `openai_client.ChatError(Exception)` — 消息用户安全（已脱敏）。
  - `chat_completion(host: str, port: int, *, model: str, prompt: str, temperature: float, top_p: float, top_k: int, repeat_penalty: float, timeout_s: float) -> dict` — 完整响应 JSON。
  - 顶层命令 `chat`（PROMPT 必选参，`-` 读 stdin）。

- [ ] **Step 1: 写失败测试**

`tests/engines/test_openai_client.py` 全文：

```python
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from ipostudio.engines.openai_client import ChatError, chat_completion
from ipostudio.engines.supervisor import choose_port

FAKE = Path(__file__).parent / "fake_llama_server.py"

@pytest.fixture
def fake_server():
    import subprocess

    port = choose_port("127.0.0.1", 18600)
    proc = subprocess.Popen(
        [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1
            ) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(0.05)
    yield port
    proc.terminate()
    proc.wait(timeout=10)

def test_chat_completion_returns_choice_payload(fake_server):
    payload = chat_completion(
        "127.0.0.1", fake_server, model="fake", prompt="hi",
        temperature=0.2, top_p=0.9, top_k=40, repeat_penalty=1.1,
        timeout_s=10,
    )
    assert payload["choices"][0]["message"]["content"] == "echo:hi"

def test_chat_completion_down_server_raises_chat_error():
    with pytest.raises(ChatError) as excinfo:
        chat_completion(
            "127.0.0.1", 1, model="m", prompt="hi",
            temperature=0.2, top_p=0.9, top_k=40, repeat_penalty=1.1,
            timeout_s=0.5,
        )
    assert "cannot reach the server" in str(excinfo.value)
    assert "ipo server start" in str(excinfo.value)
```

`tests/cli/test_chat_cmd.py` 全文：

```python
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from ipostudio.cli.main import cli
from ipostudio.engines.openai_client import ChatError
from ipostudio.engines.repo import last_completion
from ipostudio.engines.supervisor import (
    choose_port,
    start_instance,
    stop_instance,
)
from ipostudio.store.database import migrate, open_db

FAKE = Path(__file__).resolve().parents[1] / "engines" / "fake_llama_server.py"
GGUF = b"GGUF" + b"\x00" * 28

@pytest.fixture
def running_service(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "tiny-q4.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    assert runner.invoke(cli, ["model", "--select", "tiny-q4"]).exit_code == 0
    conn = open_db(tmp_path / "data" / "app.db")
    migrate(conn)
    port = choose_port("127.0.0.1", 18700)
    argv = [sys.executable, str(FAKE), "--host", "127.0.0.1", "--port", str(port),
            "--model", "tiny-q4.gguf"]  # /props identity surface (Codex fold)
    outcome = start_instance(
        conn, argv, engine="llama.cpp", model_name="tiny-q4",
        model_path="tiny-q4.gguf", host="127.0.0.1", port=port,
        log_path=tmp_path / "logs" / "engine.log", timeout_s=20,
        poll_interval=0.05,
    )
    assert outcome.ok, outcome.instance["detail"]
    yield tmp_path, conn
    stop_instance(conn)
    conn.close()

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_chat_completes_against_running_server(running_service):
    _tmp, conn = running_service
    result = _invoke("chat", "hello")
    assert result.exit_code == 0, result.stderr
    assert "echo:hello" in result.output
    record = last_completion(conn)
    assert record is not None and record["status"] == "ok"
    assert record["prompt_chars"] == len("hello")
    # the exchange itself is stored (truncated), not just counters
    assert record["prompt_text"] == "hello"
    assert record["output_text"] == "echo:hello"

def test_chat_persists_null_content_as_error(running_service, monkeypatch):
    _tmp, conn = running_service
    from ipostudio.cli import chat_cmd

    monkeypatch.setattr(
        chat_cmd, "chat_completion",
        lambda *a, **k: {"choices": [{"message": {"content": None}}]},
    )
    result = _invoke("chat", "hello")
    assert result.exit_code == 1  # not a TypeError crash (Codex shape fold)
    assert "must be a string" in result.stderr
    assert last_completion(conn)["status"] == "error"

def test_chat_redacts_secret_shapes_before_persist(running_service):
    _tmp, conn = running_service
    secret = "Bearer sk-abc123def456ghi789jkl012"
    result = _invoke("chat", f"analyze this: {secret}")
    assert result.exit_code == 0, result.stderr
    stored = last_completion(conn)
    assert secret not in (stored["prompt_text"] or "")
    assert secret not in (stored["output_text"] or "")

def test_chat_record_survives_reconnect(running_service):
    tmp_path, conn = running_service
    assert _invoke("chat", "again").exit_code == 0
    instance_id = last_completion(conn)["instance_id"]
    # a SECOND connection sees the row; the fixture-owned connection stays
    # open for the teardown's stop_instance (Codex determinism fold)
    fresh = open_db(tmp_path / "data" / "app.db")
    record = last_completion(fresh)
    assert record["instance_id"] == instance_id
    fresh.close()

def test_chat_without_server_guides_start(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("chat", "hello")
    assert result.exit_code == 1
    assert "ipo server start" in result.stderr

def test_chat_error_is_recorded_and_reported(running_service, monkeypatch):
    _tmp, conn = running_service
    from ipostudio.cli import chat_cmd

    def _explode(*args, **kwargs):
        raise ChatError("server returned HTTP 500: boom")

    monkeypatch.setattr(chat_cmd, "chat_completion", _explode)
    result = _invoke("chat", "hello")
    assert result.exit_code == 1
    assert "boom" in result.stderr
    record = last_completion(conn)
    assert record["status"] == "error"
    assert "boom" in record["detail"]

def test_chat_stdin_prompt(running_service):
    result = CliRunner().invoke(cli, ["chat", "-"], input="piped prompt\n")
    assert result.exit_code == 0, result.stderr
    assert "echo:piped prompt" in result.output
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/engines/test_openai_client.py tests/cli/test_chat_cmd.py -v`
Expected: FAIL —— `No module named 'ipostudio.engines.openai_client'`（或 unknown command 'chat'）

- [ ] **Step 3: 实现**

`src/ipostudio/engines/openai_client.py` 全文：

```python
"""Minimal OpenAI-compatible chat client for the running engine server
(public /v1/chat/completions protocol; llama-server documents the endpoint).
Non-streaming by design — streaming arrives with the conversation plan."""

import json
import urllib.error
import urllib.request

from ipostudio.logs import redact_unambiguous

class ChatError(Exception):
    """A completion could not be produced; the message is user-safe."""

def chat_completion(
    host: str,
    port: int,
    *,
    model: str,
    prompt: str,
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
    timeout_s: float,
) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "repeat_penalty": repeat_penalty,
        "stream": False,
    }
    host_part = f"[{host}]" if ":" in host else host
    request = urllib.request.Request(
        f"http://{host_part}:{port}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    # HTTPError subclasses OSError: this arm must come first
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ChatError(
            f"server returned HTTP {exc.code}: {redact_unambiguous(detail)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ChatError(
            f"cannot reach the server at {host}:{port} "
            f"({redact_unambiguous(str(exc.reason))}); start it with "
            f"`ipo server start`"
        ) from exc
    except OSError as exc:
        raise ChatError(
            f"cannot reach the server at {host}:{port} "
            f"({redact_unambiguous(str(exc))}); start it with "
            f"`ipo server start`"
        ) from exc
    except ValueError as exc:
        raise ChatError(f"server response was not valid JSON: {exc}") from exc
```

`src/ipostudio/cli/chat_cmd.py` 全文：

```python
"""`ipo chat` — one completion against the running server (spec §9.12 CLI
conversation, non-streaming slice).  Every attempt lands a completions row so
the M0' slice requirement (records survive restarts) holds for failures too."""

import time

import click

from ipostudio.cli.base import _fail, open_config_and_db
from ipostudio.engines.openai_client import ChatError, chat_completion
from ipostudio.engines.repo import active_instance, record_completion

@click.command("chat")
@click.argument("prompt", metavar="[PROMPT]")
@click.option("--timeout", "timeout_s", type=float, default=600.0,
              show_default=True,
              help="seconds before the completion gives up (spec §15 local budget)")
def chat(prompt: str, timeout_s: float) -> None:
    """Send one completion to the running server.

    PROMPT is the message text, or "-" to read stdin (for pipelines)."""
    if prompt == "-":
        import sys

        if sys.stdin is None:
            _fail("no stdin stream is available for '-'")
        prompt = sys.stdin.read()
    if not prompt.strip():
        _fail("empty prompt")
    conn, cfg = open_config_and_db()
    try:
        instance = active_instance(conn)
        if instance is None:
            _fail(
                "no server is running; start one with `ipo server start` "
                "(catalog: `ipo models`)"
            )
        if instance["state"] != "running":
            _fail(
                f"server is {instance['state']}, not ready; check `ipo status` "
                f"and `ipo server logs`"
            )
        started = time.monotonic()
        try:
            response = chat_completion(
                instance["host"], instance["port"],
                model=instance["model_name"], prompt=prompt,
                temperature=cfg.tuning.server_temp,
                top_p=cfg.tuning.server_top_p,
                top_k=cfg.tuning.server_top_k,
                repeat_penalty=cfg.tuning.server_repeat_penalty,
                timeout_s=timeout_s,
            )
        except ChatError as exc:
            _record_failure(conn, instance, prompt, started, str(exc))
            _fail(str(exc))
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        if not isinstance(content, str):
            # presence is not type-correctness: null/number/list must take
            # the error path, not crash on len() (Codex shape fold)
            _record_failure(conn, instance, prompt, started,
                            "malformed response payload")
            _fail("server returned a malformed response payload "
                  "(choices[0].message.content must be a string)")
        record_completion(
            conn, instance_id=instance["id"],
            model_name=instance["model_name"],
            prompt_text=prompt, output_text=content,
            prompt_chars=len(prompt), output_chars=len(content),
            duration_ms=int((time.monotonic() - started) * 1000),
            status="ok",
        )
    finally:
        conn.close()
    click.echo(content)

def _record_failure(conn, instance, prompt, started, detail: str) -> None:
    record_completion(
        conn, instance_id=instance["id"],
        model_name=instance["model_name"],
        prompt_text=prompt, prompt_chars=len(prompt), output_chars=0,
        duration_ms=int((time.monotonic() - started) * 1000),
        status="error", detail=detail[:500],
    )
```

`src/ipostudio/cli/main.py` 注册块追加：

```python
from ipostudio.cli.chat_cmd import chat

cli.add_command(chat)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/engines/test_openai_client.py tests/cli/test_chat_cmd.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿

```bash
git add src/ipostudio/engines/openai_client.py src/ipostudio/cli/chat_cmd.py src/ipostudio/cli/main.py tests/engines/test_openai_client.py tests/cli/test_chat_cmd.py
git commit -m "feat: add one-shot ipo chat with persisted completion records"
```

---

### Task 8: 文档 + roadmap 回写 + QA 对抗 + 全量回归 + 推送

**Files:**
- Create: `tests/qa/test_loop_adversarial.py`
- Modify: `tests/qa/test_cli_ux_adversarial.py`（walker 子集补 `server list --json`、`server info --json`）
- Modify: `README.md`、`CHANGELOG.md`、`TODOS.md`、`docs/design/roadmap.md`

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: 路线图 M0′ 结论回写（P2 入口条件满足的记录）；新 TODOS 条目（本计划全部延后项）。

- [ ] **Step 1: 写 QA 对抗测试**

`tests/qa/test_loop_adversarial.py` 全文：

```python
"""Adversarial guards for the core value loop surface.

Inherited contracts: byte-clean --json (the cli-ux walker auto-covers the new
listers — this module adds the loop-specific misbehavior checks), honest
missing-engine reporting (ADR-010), state-literal pinning (§10.2), and the
credential non-disclosure channel scan over the new commands."""

import inspect
import json

from click.testing import CliRunner

import ipostudio.cli.chat_cmd as chat_cmd
import ipostudio.cli.models_cmd as models_cmd
import ipostudio.cli.server_cmd as server_cmd
from ipostudio.cli.main import cli

GGUF = b"GGUF" + b"\x00" * 28

def _invoke(*args):
    return CliRunner().invoke(cli, list(args))

def test_new_cli_modules_never_style_directly():
    for module in (models_cmd, server_cmd, chat_cmd):
        source = inspect.getsource(module)
        assert "click.style" not in source
        assert "click.secho" not in source

def test_state_literals_are_pinned_in_one_place():
    from ipostudio.engines.repo import SERVICE_STATES as repo_states
    from ipostudio.engines.supervisor import SERVICE_STATES

    assert SERVICE_STATES == ("stopped", "starting", "loading", "running", "failed")
    assert repo_states is SERVICE_STATES

def test_engine_log_name_follows_per_process_convention():
    from ipostudio.engines.supervisor import ENGINE_LOG_FILE

    assert ENGINE_LOG_FILE.startswith("engine-")
    assert ENGINE_LOG_FILE.endswith(".log")

def test_missing_engine_never_fakes_readiness(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "m.gguf").write_bytes(GGUF + b"\x00" * 36)
    # deterministic on every machine: the configured engine path is missing,
    # so the start fails regardless of whether llama-server is on PATH
    ghost = tmp_path / "ghost-engine"
    assert CliRunner().invoke(
        cli, ["config", "set", "llama_cpp_path", str(ghost)]
    ).exit_code == 0
    assert _invoke("model", "--select", "m").exit_code == 0
    result = _invoke("server", "start")
    assert result.exit_code == 1
    assert "does not exist" in result.stderr
    assert "llama_cpp_path" in result.stderr
    # and nothing was recorded as running
    listing = json.loads(_invoke("server", "list", "--json").output)
    assert all(row["state"] != "running" for row in listing["instances"])

def test_configured_engine_path_that_vanishes_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    (tmp_path / "models").mkdir()  # Codex determinism fold
    (tmp_path / "models" / "m.gguf").write_bytes(GGUF + b"\x00" * 36)
    runner = CliRunner()
    runner.invoke(cli, ["model", "--select", "m"])
    ghost = tmp_path / "ghost-engine"
    runner.invoke(cli, ["config", "set", "llama_cpp_path", str(ghost)])
    result = _invoke("server", "start")
    assert result.exit_code == 1
    assert "llama_cpp_path" in result.stderr

def test_chat_channel_scan_shows_no_secret_shapes(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    for args in (["chat", "hi"], ["status"], ["server", "info"]):
        result = _invoke(*args)
        combined = result.output + (result.stderr or "")
        assert "sk-" not in combined
        assert "Bearer " not in combined

def test_guide_still_mentions_every_top_level_command(tmp_path, monkeypatch):
    monkeypatch.setenv("IPO_DATA_DIR", str(tmp_path))
    result = _invoke("guide")
    assert result.exit_code == 0
    for name in ("models", "model", "model-info", "server", "start",
                 "status", "stop", "restart", "chat"):
        assert name in result.output
```

`tests/qa/test_cli_ux_adversarial.py` 的 walker 子集断言最终形态（Task 2/6 增量后的收口）：

```python
    assert {
        "version --json", "doctor --json", "config path --json", "config list --json",
        "models --json", "model --json", "status --json",
        "server list --json", "server info --json",
    } <= {" ".join(args) for args in cases}
```

- [ ] **Step 2: 跑 QA 测试确认通过（它们是守卫，不驱动新实现）**

Run: `.venv/Scripts/python.exe -m pytest tests/qa -v`
Expected: 全部 PASS（若失败，修的是前序任务的实现，不是放宽测试）

- [ ] **Step 3: 文档**

`README.md` 在 Configuration 节之后新增 "Core loop quickstart" 节（全文）：

```markdown
## Core loop quickstart

The minimal loop: scan a local model, activate it, start the llama.cpp
server, complete one prompt — records persist across restarts.

1. Install llama.cpp and put `llama-server` on your PATH (official releases:
   <https://github.com/ggml-org/llama.cpp/releases>; Homebrew:
   `brew install llama.cpp`; on Windows grab `llama-server-<edition>-win-x64.zip`
   from the same releases page, or `winget install ggml.llama.cpp`). Or point
   the `llama_cpp_path` setting at the executable:
   `ipo config set llama_cpp_path "C:\llama\llama-server.exe"`. On Linux,
   unpack the release build for your architecture onto your `PATH`
   (e.g. `~/.local/bin`).
2. Download any small instruct GGUF (e.g. Qwen2.5-0.5B-Instruct or
   Llama-3.2-1B-Instruct from Hugging Face or ModelScope — with
   `pip install huggingface_hub` a single `huggingface-cli download
   <repo-id> --include *.gguf --local-dir .` fetches one) and drop it into
   `<data-dir>\models` (default `~/.ipostudio/models`; `ipo doctor --fix`
   creates the directory if it does not exist yet), or register another
   directory: `ipo config set model_dirs -- '["D:/models"]'`.
3. Run the loop:

    ipo doctor --fix          # one-time: create the data layout
    ipo models                # scan and list local .gguf models
    ipo model --select NAME   # activate one as the default chat model
    ipo server start          # launch llama-server (picks a free port)
    ipo chat "hello"          # one completion through the running server
    ipo status                # state, address, live health
    ipo server info           # instance + last completion record
    ipo server stop           # stop (idempotent)

Notes: completion records and instance history live in SQLite and survive
restarts (`ipo server info`, `ipo server list`). Closing the terminal that
started the server may stop the engine (durable background service comes
with the engine-supervision plan). Model downloading and engine installation
stay manual until the model-management plan lands its downloader. Use a
recent llama.cpp release: `server_flash_attn: on/off` needs a build whose
`llama-server` accepts valued `--flash-attn` (the default `auto` omits the
flag and works everywhere). Chat records are redacted for secret-shaped
tokens (Bearer / `sk-`…) at the persistence boundary and stay in the local
SQLite file; retention controls arrive with the model-management plan. The
engine writes its own stdout/stderr verbatim to `logs/engine-llama-cpp.log`
— display is redacted, but treat that file as raw engine output.
`ipo server stop` proves port ownership against the engine's `/props`
document before signaling and refuses a foreign listener. Shorthand
semantics: `ipo start --model NAME` persists the selection; `ipo server
start/restart --model NAME` overrides for that command only; `ipo start` is
a no-op success when a server is already running, while `ipo server start`
reports the conflict as an error.
```

`CHANGELOG.md` 顶部新增 Unreleased 条目（沿用现有格式）：

```markdown
## [Unreleased]

### Added
- `ipo models` / `ipo model --select` / `ipo model-info`: local GGUF catalog
  (scan, activate, details) backed by a new `models` table.
- `ipo server start/stop/restart/list/info/logs` and the `ipo
  start/status/stop/restart` shorthands: single-instance llama.cpp
  supervision with SQLite-persisted service states (stopped/starting/
  loading/running/failed), occupied-port avoidance, and per-process engine
  logs (`logs/engine-llama-cpp.log`).
- `ipo chat PROMPT`: one non-streaming completion against the running server
  via its OpenAI-compatible endpoint; every attempt (ok or error) is recorded
  in a new `completions` table and visible after restarts.
- Stop safety: `ipo server stop` proves port ownership against the engine's
  `/props` document before signaling; a foreign listener is refused with
  manual guidance, a silent port sends no signal, and a timed-out startup
  terminates its engine instead of orphaning it.
- `engines.llama_cpp_path` config key (empty = resolve `llama-server` from
  PATH).
- Config files are stamped with `config_version` on save so a downgrade
  degrades gracefully instead of rejecting a config this build wrote;
  conversation records are redacted for secret-shaped tokens at the
  persistence boundary.
- `ipo guide`/`ipo help` now document command arguments and subcommand
  options (server/config children included).
- First-run welcome card now points initialized users at `ipo models`.
```

`docs/design/roadmap.md` 的 "里程碑 M0′" 节末尾追加（回写切片结论）。**回写门（CEO 评审 #2）**：回写文本必须区分两类验证——假引擎自动化验证（已完成）与真机小模型冒烟（手动门）。若真机冒烟已由执行者/用户完成并成功，写"已完成真机冒烟"；否则必须写"真机冒烟待用户执行，P2 入口条件以前者为最终标准"。Task 8 的执行者在推送前于开发机执行下方真实冒烟清单（有真实 llama.cpp 与任意小 GGUF 时；**自 Task 4 supervisor 落地起即可手动执行，不必等到 Task 8**——Codex CEO/ENG 时序折叠）。**P2 立项门槛（Codex CEO 折叠）：** 技术连通不构成继续投入的证据——P2 立项前须有一类明确用户用自有材料完成一次真实任务，且相对其现有做法可测改善。**止损线：** 真机冒烟失败且当日无法定位修复，则停止后续投入并向用户回报（仅保留文档与回写收尾）：

```text
# Manual real-model smoke (one-time gate for the M0' writeback):
# 1. install llama.cpp, put llama-server on PATH (README quickstart)
# 2. drop any small .gguf into ~/.ipostudio/models
#    (record the download time — the writeback separates it from TTHW)
ipo doctor --fix
ipo models            # the real GGUF appears
ipo model --select <name>
ipo server start      # real engine loads the real weights
ipo chat "hello"      # a real answer comes back
#    -> record time-to-first-answer separately (TTHW evidence, Codex fold)
ipo server info       # record shows the exchange
ipo server stop
```

回写文本（追加到 roadmap M0′ 节）：

```markdown
**切片结论（2026-10-05 回写）**：M0′ 以产品命令形态交付（核心回路计划
`docs/superpowers/plans/2026-10-05-core-value-loop.md`）：`ipo models` 扫描
→ `ipo model --select` 激活 → `ipo server start`（llama.cpp，SQLite 实例行
+ 五态状态机）→ `ipo chat` 一次补全（OpenAI 兼容端点，交换内容入库）→
重启经 `ipo server info` 可查。与原案差异：装引擎/下模型保持手动（下载器
按 ADR-005 完整留给 P2；引擎自动安装非任何阶段承诺）。验证分层：全部 8
任务以假引擎子进程替身自动化验证（架构 §5）；真机小模型冒烟按上方清单
执行——[执行者回填：已完成/待用户执行]，它是 P2 入口条件的最终标准。
竞争检查点（CEO 评审 #6）：本地"下载→运行→对话"层存在成熟免费在位者
（Ollama/LM Studio）；本项目的差异化在楔子功能（docparse+知识库/多引擎
统一网关/跨工具记忆）。触发器：若在位者接管本层全部用户价值且楔子层无
法建立差异化，P2/P3 的本地运行层投入需重新裁决。
```

`docs/design/architecture.md` 追加 ADR-011（CEO 评审 #4：把"自建监管 vs 外部服务"的裁决落档）：

```markdown
### ADR-011 核心回路的进程监管：自建 vs 外部服务（2026-10-05）

- 要解决的问题：最小闭环可以（a）自建 llama.cpp 进程监管（启停/端口/状态机），或（b）不监管任何进程——用户外部自起引擎或指向任意 OpenAI 兼容端口，产品只做目录/激活/补全/记录。CEO 评审指出 (b) 以 ~20% 面积交付 ~80% 用户可见价值，且 schema 的 `server_mode=remote` 天然是逃生门。
- 选择：a)，但把 (b) 登记为 P4 网关计划的直接前身。理由：规格 §5.3 F03 把安装检查/启停/多实例/状态展示列为核心功能（P3 的验收面），最小闭环以真实产品命令兑现 F03 的最小子集是路线图排位裁决（2026-10-04）的直接内容；(b) 所需的"任意外部 OpenAI 兼容端点"按规格属 F04 云端服务商管理（P4），届时 `server_mode=remote` + 服务商登记自然兑现，`engines/openai_client.py` 即其客户端抽象的雏形。
- 后果：M0′ 阶段 `server_mode=remote` 保持诚实封锁（报错指明到达计划）；已知限制（孤儿进程随终端退出、Windows 硬杀、PID 身份启发式）分别由 TODO-017/ADR-010/TODO-016 承接。`completions` 表与 `instances` 表按 P6/P3 演进，属脚手架件（在位期间承担记录与诊断职责）。
```

`TODOS.md` 追加九条（沿用既有条目格式：What/Why/Pros(可选)/Cons(可选)/Context/Effort/Priority/Depends on）：

```markdown
## TODO-014: doctor 增加第五项 engine/models 检查
- **What:** doctor 增加 `engine` 检查（发现 llama-server、统计目录内模型数），JSON 契约从四项扩为五项。
- **Why:** 缺引擎/缺模型的引导目前只在 `ipo models` 空态与 `ipo server start` 错误里；doctor 作为体检入口应覆盖。
- **Context:** 核心回路计划范围裁决 #4：本计划不动 doctor 四项契约。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** 无

## TODO-015: 引擎日志轮转与多实例日志名（P3 前）
- **What:** `logs/engine-llama-cpp.log` 无轮转；多实例落地时按实例命名并在 `ipo logs` 聚合。
- **Why:** TODO-004 的引擎侧延伸；单文件单写者安全但会无限增长。
- **Context:** 核心回路计划引入第一个长驻子进程时的既知限制（supervisor 模块注释）。
- **Effort:** human: S / CC: S
- **Priority:** P2（优先级），时序 P3 前
- **Depends on:** TODO-004

## TODO-016: stop 的 PID 级身份加固（P3 前）
- **What:** 文档级身份证明已在本计划交付（`probe_identity` /props 模型守卫：owned 才发信号、foreign 拒绝并如实留行、absent 不发信号——Codex 三声部折叠，替代旧"端口健康应答即放行"启发式）。余下为 PID 级加固：记录引擎进程启动时刻/create_time 并比对，覆盖"记录 PID 被回收而端口仍服务本模型"的残余窗口。
- **Why:** /props 守卫把误杀面从"任何 200/503 应答"收窄到"端口上确是本模型"，但 PID 与端口文档的绑定仍是间接推断；PID 重用窗口内的 kill 仍是用户机器信任问题。
- **Context:** 核心回路计划范围裁决 #6 + Codex 停止安全折叠；跨平台进程身份探需无分支实现设计。
- **Effort:** human: M / CC: M
- **Priority:** P2（优先级），时序 P3 前
- **Depends on:** 无

## TODO-019: 竞争转向触发器与楔子 MVP 排位（下一计划入口）
- **What:** 为"本地运行层"（下载/运行/对话的商品层）写明竞争转向判据；把 CEO 评审 #6 的楔子 MVP 建议（docparse+知识库 / 多引擎网关 / 跨工具记忆 三选一先做）列为下一轮路线图排位的必答题。**判据具体化（Codex CEO 折叠）：** 旧触发条件"在位者接管全部用户价值"几乎不可操作——下一轮基础设施投入前必须选定一个楔子方向并写明试用入口、替换对象、成功指标与停止日期；选定前商品层不再吸收结构性投入。
- **Why:** 本层存在成熟免费在位者（Ollama/LM Studio）；产品差异化在楔子层。无触发器时后续计划可能继续在商品层加码（CEO 评审 #6）。
- **Context:** roadmap M0′ 回写已含触发器文本（核心回路计划 Task 8）；下一计划排位时由 CEO 双声部裁决。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** 下一轮路线图排位

## TODO-017: 常驻后台服务与 detach（P3）
- **What:** `ipo server start` 目前孤儿进程 + 三平台对称的"关终端即停"限制；P3 引入按需后台服务进程（ADR-004 完整形态）。
- **Why:** 服务生命周期与终端解耦是多实例/空闲卸载的前提。
- **Context:** 核心回路计划范围裁决 #5；R1 禁平台分支，detach 方案须跨平台设计（服务进程 + 轻客户端）。
- **Effort:** human: L / CC: M
- **Priority:** P3
- **Depends on:** P3 引擎监管

## TODO-018: chat 流式输出与 NDJSON 事件（P6）
- **What:** `ipo chat` 增加流式渲染与 `--json` NDJSON 事件（start/event/chunk/result，§9.11）。
- **Why:** 规格授权的 CLI 对话完整形态；非流式切片已把记录面打通。
- **Context:** 核心回路计划范围裁决 #3；事件契约与 agent run（P7）共用设计。
- **Effort:** human: M / CC: S
- **Priority:** P6
- **Depends on:** P6 对话

## TODO-021: 模型目录剪枝（P2）
- **What:** `ipo models`/扫描时与文件系统对账：消失的文件从 models 表移除或标记 missing；P2 下载器落地时并入完整生命周期。本计划已交付：`_resolve_model` 的存在性+分片族完整性复核（启动前）、列表 `(missing)` 标注；本项补移除/清理，并把 **path-addressable 激活**（同名不同目录时按路径激活，Codex DX 死循环折叠的根治）随本项一并设计。
- **Why:** 目录是 insert-only（ENG Finding 3），已删模型靠启动前复核兜底；同名歧义在 ENG F2 下被拒绝且 P2 前无解，需与剪枝同设计。
- **Context:** 核心回路计划 ENG 评审 F3；P2 模型管理的主责面。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** P2 模型管理

## TODO-022: start 的检查-生成序列化（P2 多入口前）
- **What:** `ipo server start` 的 active-instance 检查与 INSERT 分处两个 autocommit 步骤，两个并发 **CLI 进程** start 可各自生成引擎；用 `BEGIN IMMEDIATE` 事务（migrate() 先例）或 ConfigStore 式咨询锁把"检查+登记"包成单序列化段。本计划已交付**进程内**一半（Codex ENG 竞态折叠）：`_touch(expect=...)` 条件状态转换 + stop 条件写 + 败者 terminate，start/stop 交错已有测试；跨进程双 start 仍在。
- **Why:** 进程内交错已闭环；跨进程窗口内仍可出现两行 running 与一个孤儿引擎。
- **Context:** 核心回路计划 ENG 评审；P2 GUI/嵌入方进程内调用落地前完成。
- **Effort:** human: S / CC: S
- **Priority:** P2（优先级），时序 P2 落地前
- **Depends on:** 无

## TODO-020: --json 输出方言收敛（P7 前）
- **What:** 列表型 `--json` 现为 pretty 单文档（与 version/doctor/config 一致）；§9.11 的 NDJSON 事件方言（start/event/chunk/result）属 agent run/chat 流式场景。P7 设计事件流时明确两方言边界并写入门面文档。
- **Why:** 防止 P6/P7 事件流与既有列表方言冲突（CEO 评审 #7）。
- **Depends on:** P6/P7

## TODO-023: 会话记录保留策略与删除工具（P2）
- **What:** `completions` 表默认保存（已脱敏的）交换内容且无删除入口；P2 提供 `chat --no-save` 与记录清除命令（或等价面），README 写明保留策略（Codex CEO/DX/ENG 三声部信任折叠）。
- **Why:** 本地单机存储风险有限，但"默认永久保存用户提示"应有明示出口；脱敏已在持久化边界交付，本项补控制面。
- **Context:** 核心回路计划 Codex 信任折叠；与 P2 模型管理的隐私文档共用一节。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** P2 模型管理（文档面共用）

## TODO-024: 监听地址与连接地址分离（P3 前）
- **What:** `server_host` 为 `0.0.0.0` 等通配地址时，健康探测/聊天请求/展示直接复用监听地址；按地址族推导可连接地址（回环优先）并统一 IPv6 URL 括号（Codex ENG 折叠；`choose_port` 的 IPv6 绑定面已随本计划交付）。
- **Why:** 通配监听在部分栈上可连、部分栈上不可连；`http://0.0.0.0:port` 的展示对用户无操作意义。
- **Context:** 核心回路计划 Codex 网络地址折叠；多实例/远程面（P3/P4）前完成。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** 无
```

- [ ] **Step 4: 全量回归 + ruff + 提交**

Run: `.venv/Scripts/python.exe -m pytest -q && .venv/Scripts/python.exe -m ruff check src tests`
Expected: 全绿（预计 191 基线 + 约 60-70 新测试）

```bash
git add tests/qa README.md CHANGELOG.md TODOS.md docs/design/roadmap.md
git commit -m "test: add core-loop adversarial guards; document the minimal loop"
```

- [ ] **Step 5: 推送并确认 CI**

```bash
git push origin main
gh run watch $(gh run list --branch main --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```
Expected: 三平台矩阵全绿。

---

## Self-Review 记录（计划作者已跑）

1. **规格覆盖**：§5.2 本地管理切片→T1/T2；§5.3 最小切片（启停/端口避让/活动模型/明确报告）→T3/T4/T5；§9.11 `start`/`status/stop/restart`/`server.*`/`models`/`model --select`/`model-info`→T5/T6/T2；§9.12 CLI 对话→T7；§10.1/10.2→T1/T4（字面量 CHECK 钉死 + QA 守卫）；§11.2 `llama_cpp_path` 为增量登记键（ADR-003"键族按子项目增量登记"），三处同步点已写入 T3；§12.1/§13（空态引导/不完整权重跳过/截断提示/失败原因与重试入口=stop+start）→T1/T2/T4/T5；§15（端口≤20 候选、本地 600s）→T4/T5/T7。M0′ 切片五步（装引擎→下模型→一次补全→落盘→重启可查）全部有命令承载，T8 回写 roadmap。**刻意不覆盖**（有据）：T02/T03/T04 下载器（P2）、T05/T06 多实例（P3）、流式（P6）、网关（P4）。
2. **占位符扫描**：无 TBD/TODO 式空步；无"实现略"式步骤；无行内勘误——所有代码块即最终形态。
3. **类型一致性**：`find_model` 返回 `list[dict]` 全线一致；`start_instance(conn, argv, *, engine, model_name, model_path, host, port, log_path, timeout_s, poll_interval, probe, spawn)` 在 T4 定义、T5/T6/T7 调用一致；`_run_start(conn, cfg, model_name, host, port, timeout_s)` T5 定义、T6 复用一致；`SERVICE_STATES` 单一定义于 supervisor.py、repo.py 再导出；`stop_instance` 的 `identify=probe_identity` 注入点与 `_touch(expect=...)` 条件写在 T4 定义、T5/T6 调用一致；`open_db_only` 于 T2 定义、T5/T6 的五个 conn-only 命令面使用；`resolve_engine`/`build_server_argv` 的 monkeypatch 点（T5 测试）与 T3 的模块属性名一致；`activate_model` 的 LookupError/ValueError 契约在 T2 定义、T6 捕获一致；monkeypatch 目标 `chat_cmd.chat_completion` 与 T7 的 `from ... import chat_completion` 导入形态一致（补丁生效）。

<!-- autoplan-accepted:ceo -->
- 模式：SELECTIVE EXPANSION（autoplan 覆盖）；14 项范围裁决（计划头部，含 #14 M0 上限诚实标注）全部生效，执行者不得扩大。
- 回路命令面锁定为：`ipo models`、`ipo model --select`、`ipo model-info`、`ipo server start/stop/restart/list/info/logs`、`ipo start`、`ipo status`、`ipo stop`、`ipo restart`、`ipo chat`；服务状态字面量 stopped/starting/loading/running/failed 由 003 迁移 CHECK 钉死。
- 配置键 `llama_cpp_path` 加入 engines 族时必须三处同步：`conf/schema.py`、`tests/conf/test_schema.py` SPEC_DEFAULTS、`tests/qa/test_conf_adversarial.py` ROUNDTRIP_VALUES + `len(FLAT_KEYS) == 61`。
- 新增无必选参 `--json` 命令在全新数据目录上无参调用必须 exit 0（QA walker 自动覆盖契约）。
- 每任务 RED→GREEN→全量回归→提交；基线 191 tests + ruff 全绿；只用 `.venv/Scripts/python.exe`；凭据永不落盘/上屏；R1 守卫（src/ 禁 os.name/sys.platform/os.path.）每任务保持绿。
- 【CEO 评审折叠 #1】completions 表存交换内容（prompt_text/output_text，2000 字符截断）；`ipo chat` 成功/失败都记录内容；`ipo server info` 回显片段；`tests/cli/test_chat_cmd.py` 断言 prompt_text/output_text 入库。
- 【CEO 评审折叠 #2】instances 表带 engine_version（start_instance 内 `--version` 尽力探测，失败记空串）；Task 8 的 roadmap M0′ 回写以"真机小模型冒烟清单"为门——未跑则回写文本必须写"待用户执行"（占位符 `[执行者回填：已完成/待用户执行]` 不得留空）。
- 【CEO 评审折叠 #4/#7】Task 8 向 docs/design/architecture.md 追加 ADR-011（自建监管 vs 外部服务；remote=P4 逃生门；completions/instances 为脚手架件按 P6/P3 演进）。
- 【CEO 评审折叠 #5/#6】`ipo server start` 成功输出含终端生命周期提示；TODOS.md 落 TODO-014..020 七条（016 时序 P2、019 竞争触发器、020 --json 方言）。
- 【Section 2 折叠 A7】scan_model_files 的 skipped 计数包含不可读目录（silence is never free）。
- 【规格闭环】find_model 后缀匹配为组件感知 Python 匹配（无 LIKE 通配面）；Task 5/8 缺引擎测试为确定性幽灵路径形态。
- 【DX 折叠 #1】Task 8 README 块：安装指引含 Windows 资产/winget 提示；GGUF 来源给小型 instruct 模型举例（HF/ModelScope）。
- 【DX 折叠 #2/#3】`ipo status` 在 running 且 health≠ok 时输出与 server info 一致的修复指引；显式 `--port` 失败 detail 追加端口核对提示（port_given 分支）。
- 【DX 折叠 #4/#5】`ipo start --server` 帮助文本明示"spec §9.11 option parity, always on"；错误文案去 "reap" 行话（supervisor 超时 detail 与 server info）；引擎错误删除配置系统语义泄漏句。
- 【DX 记录性义务】`ipo chat` 的 completions 行含 prompt_text/output_text（已列）；qa/test_loop_adversarial 的状态字面量钉死测试保持 repo is supervisor 断言。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 【DX 折叠 #1】Task 8 README 块：安装指引含 Windows 资产/winget 提示；GGUF 来源给小型 instruct 模型举例（HF/ModelScope）。
- 【DX 折叠 #2/#3】`ipo status` 在 running 且 health≠ok 时输出与 server info 一致的修复指引；显式 `--port` 失败 detail 追加端口核对提示（port_given 分支）。
- 【DX 折叠 #4/#5】`ipo start --server` 帮助文本明示"spec §9.11 option parity, always on"；错误文案去 "reap" 行话（supervisor 超时 detail 与 server info）；引擎错误删除配置系统语义泄漏句。
- 【DX 记录性义务】`ipo chat` 的 completions 行含 prompt_text/output_text（已列）；qa/test_loop_adversarial 的状态字面量钉死测试保持 repo is supervisor 断言。
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- 【ENG-F1 阻断修复】scan.py 分片归属按各候选自身 _SHARD 匹配导出的 base 相等判定（防同前缀家族吞并）；tests/catalog 增 prefix-colliding families 测试（两家族各自完整入册）。
- 【ENG-F2】activate_model 在按唯一路径选中后校验裸名的唯一性，歧义则 ValueError（P2 落路径寻址选择）；tests/cli 增歧义名拒绝测试。
- 【ENG-F3】_resolve_model 校验 model['path'] 存在性，缺失报"文件已不存在+重扫指引"；目录剪枝记 TODO-021。
- 【ENG-F5】`ipo server logs` 逐行过 redact_text 再输出。
- 【ENG-F14】probe_health 与 chat_completion 的 URL host 含冒号时加方括号。
- 【ENG-F15】server_host 非回环时 stderr 警告未认证端点暴露。
- 【ENG-F7】`ipo start --model` 的激活先于 running/auto_start_server 两道门执行；running 提示语补 restart 指引。
- 【ENG-F8】scan 深度拒算入 unreadable；配置根为文件时计入 unreadable。
- 【ENG-F9】_now() 统一为 SQLite datetime('now') 同格式。
- 【ENG-F10】server_cmd._resolve_model 复用 models_cmd._refresh（单扫描视图）。
- 【ENG-F16】open_config_and_db 增 OSError 臂（数据目录不可读走同一错误契约）。
- 【ENG-F11/F12/F13 测试】probe 503→loading 真实 HTTP 测试；e2e 断言 engine_version 非空；_warn_reserved_tuning stderr 断言。
- 【ENG-F4/F6 记录】并发 start 序列化记 TODO-022（P2 前）；--flash-attn 版本敏感性写入 README Notes。
<!-- /autoplan-accepted:eng -->


## Review record

<!-- autoplan-accepted:ceo -->
- 模式：SELECTIVE EXPANSION（autoplan 覆盖）；14 项范围裁决（计划头部，含 #14 M0 上限诚实标注）全部生效，执行者不得扩大。
- 回路命令面锁定为：`ipo models`、`ipo model --select`、`ipo model-info`、`ipo server start/stop/restart/list/info/logs`、`ipo start`、`ipo status`、`ipo stop`、`ipo restart`、`ipo chat`；服务状态字面量 stopped/starting/loading/running/failed 由 003 迁移 CHECK 钉死。
- 配置键 `llama_cpp_path` 加入 engines 族时必须三处同步：`conf/schema.py`、`tests/conf/test_schema.py` SPEC_DEFAULTS、`tests/qa/test_conf_adversarial.py` ROUNDTRIP_VALUES + `len(FLAT_KEYS) == 61`。
- 新增无必选参 `--json` 命令在全新数据目录上无参调用必须 exit 0（QA walker 自动覆盖契约）。
- 每任务 RED→GREEN→全量回归→提交；基线 191 tests + ruff 全绿；只用 `.venv/Scripts/python.exe`；凭据永不落盘/上屏；R1 守卫（src/ 禁 os.name/sys.platform/os.path.）每任务保持绿。
- 【CEO 评审折叠 #1】completions 表存交换内容（prompt_text/output_text，2000 字符截断）；`ipo chat` 成功/失败都记录内容；`ipo server info` 回显片段；`tests/cli/test_chat_cmd.py` 断言 prompt_text/output_text 入库。
- 【CEO 评审折叠 #2】instances 表带 engine_version（start_instance 内 `--version` 尽力探测，失败记空串）；Task 8 的 roadmap M0′ 回写以"真机小模型冒烟清单"为门——未跑则回写文本必须写"待用户执行"（占位符 `[执行者回填：已完成/待用户执行]` 不得留空）。
- 【CEO 评审折叠 #4/#7】Task 8 向 docs/design/architecture.md 追加 ADR-011（自建监管 vs 外部服务；remote=P4 逃生门；completions/instances 为脚手架件按 P6/P3 演进）。
- 【CEO 评审折叠 #5/#6】`ipo server start` 成功输出含终端生命周期提示；TODOS.md 落 TODO-014..020 七条（016 时序 P2、019 竞争触发器、020 --json 方言）。
- 【Section 2 折叠 A7】scan_model_files 的 skipped 计数包含不可读目录（silence is never free）。
- 【规格闭环】find_model 后缀匹配为组件感知 Python 匹配（无 LIKE 通配面）；Task 5/8 缺引擎测试为确定性幽灵路径形态。
- 【DX 折叠 #1】Task 8 README 块：安装指引含 Windows 资产/winget 提示；GGUF 来源给小型 instruct 模型举例（HF/ModelScope）。
- 【DX 折叠 #2/#3】`ipo status` 在 running 且 health≠ok 时输出与 server info 一致的修复指引；显式 `--port` 失败 detail 追加端口核对提示（port_given 分支）。
- 【DX 折叠 #4/#5】`ipo start --server` 帮助文本明示"spec §9.11 option parity, always on"；错误文案去 "reap" 行话（supervisor 超时 detail 与 server info）；引擎错误删除配置系统语义泄漏句。
- 【DX 记录性义务】`ipo chat` 的 completions 行含 prompt_text/output_text（已列）；qa/test_loop_adversarial 的状态字面量钉死测试保持 repo is supervisor 断言。
<!-- /autoplan-accepted:ceo -->

<!-- autoplan-accepted:dx -->
- 【DX 折叠 #1】Task 8 README 块：安装指引含 Windows 资产/winget 提示；GGUF 来源给小型 instruct 模型举例（HF/ModelScope）。
- 【DX 折叠 #2/#3】`ipo status` 在 running 且 health≠ok 时输出与 server info 一致的修复指引；显式 `--port` 失败 detail 追加端口核对提示（port_given 分支）。
- 【DX 折叠 #4/#5】`ipo start --server` 帮助文本明示"spec §9.11 option parity, always on"；错误文案去 "reap" 行话（supervisor 超时 detail 与 server info）；引擎错误删除配置系统语义泄漏句。
- 【DX 记录性义务】`ipo chat` 的 completions 行含 prompt_text/output_text（已列）；qa/test_loop_adversarial 的状态字面量钉死测试保持 repo is supervisor 断言。
<!-- /autoplan-accepted:dx -->

<!-- autoplan-accepted:eng -->
- 【ENG-F1 阻断修复】scan.py 分片归属按各候选自身 _SHARD 匹配导出的 base 相等判定（防同前缀家族吞并）；tests/catalog 增 prefix-colliding families 测试（两家族各自完整入册）。
- 【ENG-F2】activate_model 在按唯一路径选中后校验裸名的唯一性，歧义则 ValueError（P2 落路径寻址选择）；tests/cli 增歧义名拒绝测试。
- 【ENG-F3】_resolve_model 校验 model['path'] 存在性，缺失报"文件已不存在+重扫指引"；目录剪枝记 TODO-021。
- 【ENG-F5】`ipo server logs` 逐行过 redact_text 再输出。
- 【ENG-F14】probe_health 与 chat_completion 的 URL host 含冒号时加方括号。
- 【ENG-F15】server_host 非回环时 stderr 警告未认证端点暴露。
- 【ENG-F7】`ipo start --model` 的激活先于 running/auto_start_server 两道门执行；running 提示语补 restart 指引。
- 【ENG-F8】scan 深度拒算入 unreadable；配置根为文件时计入 unreadable。
- 【ENG-F9】_now() 统一为 SQLite datetime('now') 同格式。
- 【ENG-F10】server_cmd._resolve_model 复用 models_cmd._refresh（单扫描视图）。
- 【ENG-F16】open_config_and_db 增 OSError 臂（数据目录不可读走同一错误契约）。
- 【ENG-F11/F12/F13 测试】probe 503→loading 真实 HTTP 测试；e2e 断言 engine_version 非空；_warn_reserved_tuning stderr 断言。
- 【ENG-F4/F6 记录】并发 start 序列化记 TODO-022（P2 前）；--flash-attn 版本敏感性写入 README Notes。
<!-- /autoplan-accepted:eng -->


---

## ENG DUAL VOICES — CONSENSUS TABLE

| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Architecture sound? | YES（分层/无环锁/SQLite 协调点/假引擎契约均为正确的 M0′ 便宜原语） | unavailable | N/A（单声部） |
| 2. Test coverage sufficient? | 图完成；16 缺口中 3 测试缺口折叠（F11/F12/F13），其余路径 OK | unavailable | N/A |
| 3. Performance risks addressed? | YES（扫描 500×深度4 封顶、端口 20 候选、无全表扫描） | unavailable | N/A |
| 4. Security threats covered? | YES（列表式 spawn 无 shell、参数化 SQL、零新依赖、无凭据面；F15 非回环警告已折叠） | unavailable | N/A |
| 5. Error paths handled? | YES（Error Registry 13+ 路径；F16 OSError 臂补齐共享入口） | unavailable | N/A |
| 6. Deployment risk manageable? | YES（已知限制全部 TODO 化 + roadmap 回写门诚实） | unavailable | N/A |

Codex 不可用（provider 连接超时，会话内第三次同征失败）——ENG 全表 N/A 单声部。**单声部 HIGH**：ENG-F1 分片前缀碰撞（真 bug，测试抓不到）——已作阻断修复折叠。

## ENG 评审发现处置（16 项，FULL_REVIEW）

| # | 严重度/置信 | 发现 | 处置 |
|---|---|---|---|
| 1 | HIGH/9 | 分片组前缀碰撞：`llama-` 吞并 `llama-instruct-`，两模型静默消失 | **ACCEPTED 阻断**：按各候选自身 base 相等判定 + prefix-collision 测试 |
| 2 | MED/8 | 路径激活回写歧义名 → server start 卡死 | ACCEPTED：激活时校验裸名唯一性，歧义拒绝 |
| 3 | MED/9 | 目录无剪枝：已删文件在引擎层才失败 | ACCEPTED：_resolve_model 存在性检查 + TODO-021 剪枝 |
| 4 | MED/8 | 并发 start 无序列化（两引擎竞态） | DEFERRED：TODO-022（P2 多入口前；跨模块重构不进 timebox） |
| 5 | MED/9 | server logs 未脱敏 | ACCEPTED：逐行 redact_text |
| 6 | LOW-MED/6 | --flash-attn 值的引擎版本敏感 | ACCEPTED：README Notes 注明版本要求 |
| 7 | LOW-MED/7 | `ipo start --model` 被门序吞掉 | ACCEPTED：激活先于两道门 |
| 8 | LOW/8 | 深度拒/文件根不计入 skipped | ACCEPTED：两处计数 |
| 9 | LOW/9 | 时间戳双格式混列 | ACCEPTED：_now() 对齐 SQLite 格式 |
| 10 | LOW/9 | _refresh 双实现漂移风险 | ACCEPTED：server_cmd 复用 models_cmd._refresh |
| 11 | LOW/8 | 503→loading 无真实 HTTP 测试 | ACCEPTED：--load-delay 真实探测测试 |
| 12 | LOW/9 | engine_version 无断言 | ACCEPTED：e2e 断言非空 |
| 13 | LOW/9 | _warn_reserved_tuning 无测试 | ACCEPTED：stderr 断言测试 |
| 14 | LOW/8 | IPv6 裸主机破坏两处 URL | ACCEPTED：含冒号加方括号 |
| 15 | LOW/7 | 非回环绑定无警告 | ACCEPTED：stderr 暴露警告 |
| 16 | INFO/8 | open_config_and_db 缺 OSError 臂 | ACCEPTED：补臂（共享入口一次修十命令） |

## ENG Section 1 Architecture — 依赖图（新组件 vs 既有）

```
EXISTING                                    NEW (this plan)
====================                        ====================================================
conf/schema.py  <---------------------------  engines/llama_server.py   (ServerTuning -> argv)
conf/loader.py  <---------------------------  cli/base.py               (load_config/ConfigError)
conf/paths.py   <---------------------------  cli/base.py               (路径解析)
cli/ui.py       <---------------------------  cli/base.py               (use_color 色门)
store/database.py <-------------------------  catalog/repo, supervisor, base (open_db/migrate)
store/migrations/001_init.sql                002_models.sql, 003_instances.sql (自动发现)
logs.py (redact_text/unambiguous) <---------  supervisor._tail / openai_client / server logs

NEW 内部边（按锁无环）：
  catalog/scan <--- catalog/repo <--- cli/models_cmd --(activate_model)--> cli/server_cmd
  engines/discovery + llama_server + supervisor + repo --> cli/server_cmd (_run_start; Task 6 复用)
  engines/repo --imports SERVICE_STATES--> supervisor；supervisor 永不 import repo（环锁）
  engines/openai_client --> cli/chat_cmd
  SQLite instances/completions 行 = 跨进程协调点（start 即退，stop/status/chat 异进程信任行+活探测）
  三个 cli 命令模块 --> cli/base（open_config_and_db/_fail/_SuggestingGroup）
```
耦合评估：领域包零互引（ADR-008 保持）；唯一跨域调用经 `activate_model` 显式函数——可接受。SPOF：SQLite（WAL+busy_timeout+race-safe migrate 库内机制覆盖）。每条新路径一个现实生产失败已在 Failure Modes Registry 给出处理。

## ENG Section 2 Code Quality — 发现已全部进入处置表（F2/F5/F8/F9/F10/F16 共 6 项代码质量类，全 ACCEPTED；_INSTANCE_COLUMNS 双写为已声明例外）

## ENG Section 3 Test Review — 覆盖图与缺口

```
CODE PATHS（新增 → 计划测试）
catalog/scan: 单文件✓ 坏魔数✓ 分片✓ **F1 前缀碰撞 GAP→已补测试** 孤儿/缺片✓ 深度/隐藏✓ **F8 计数 GAP→已补** 截断✓ 不可读✓ 空根✓ 去重✓
catalog/repo: upsert 幂等✓ 三级查找✓ **F2 路径激活歧义 GAP→已补测试**
cli/models_cmd: 列表/空态/json/坏配置 + show/select/missing/ambiguous/info/activate ✓✓
cli/base: 建议组(继承)✓ 错误入口✓ **F16 OSError GAP→实现已补（OSError 测试随 bad-config 家族）**
engines/discovery: 4 测试（含 PATHEXT 双名）✓
engines/llama_server: argv 4 测试✓ **F6 真机 flash-attn 接受度→真机冒烟清单覆盖**
fake_llama_server: 契约测试✓
engines/supervisor: probe down✓ **F11 真实 503 GAP→已补测试** choose_port✓ start 六路✓ **F12 version 断言 GAP→已补** stop 四路✓ 状态钉死✓ 日志名✓
engines/repo: 查询面✓
cli/server_cmd: start 八路✓ info/list/logs✓ **F13 warn 测试 GAP→已补** restart 语义✓
cli 顶层: start/auto-off/idempotent/--model/reserved/status-json/stop/restart ✓ **F7 --model×门序组合→折叠后重排序覆盖**
engines/openai_client: payload✓ 不可达✓ **HTTP 错误体路径由 chat_cmd monkeypatch 家族覆盖**
cli/chat_cmd: 成功记录✓ 重连✓ 无服务✓ 错误记录✓ stdin✓ **空 prompt 路径→实现直接 _fail（低风险）**
qa/test_loop: 样式/状态钉死/日志名/幽灵引擎×2/密钥扫描/guide ✓
walker: 9 面，fresh-dir exit 0 + 可解析 ✓

COVERAGE: 折叠后全部计划内路径有测试 | GAPS: 0 未决（3 测试缺口已补入计划）
```
LLM/eval 范围：不适用（无 prompt 工程面）。测试计划工件：`~/.gstack/projects/ipostudio/savior-main-eng-review-test-plan-20261005-083804.md`。

## ENG Section 4 Performance — 扫描有界（500×深度4+计数跳过）、choose_port O(20)、completions 无扫描读路径、启动毫秒级。0 阻断。

## ENG Failure Modes Registry

| 代码路径 | 失败模式 | Rescued? | Test? | 用户所见 |
|---|---|---|---|---|
| scan 分片归属 | 前缀碰撞吞并 | Y（F1 修复） | Y（F1 测试） | 两家族完整入册 |
| server start | 双 start 竞态 | 部分（TODO-022） | N/A（竞态） | 罕见双引擎（P2 前收敛） |
| _resolve_model | 模型文件已删 | Y（F3） | —（手动可验） | 重扫指引 |
| server logs | 引擎输出泄密形态 | Y（F5） | —（显示面） | 脱敏行 |
| probe/client | IPv6 裸主机 | Y（F14） | —（默认回环） | 正常 URL |
| open_config_and_db | 数据目录不可读 | Y（F16） | 家族覆盖 | 结构化错误 |

CRITICAL GAPS：0。

## ENG Completion Summary

```
  +====================================================================+
  |   MEGA PLAN REVIEW — ENG COMPLETION SUMMARY                        |
  +====================================================================+
  | Step 0 Scope Challenge | scope accepted as-is（裁决 #1-#14 既定；   |
  |                        | 复杂度门触发但 P2 覆盖禁止缩减）            |
  | Architecture Review    | 0 阻断（依赖图无环、SPOF 有界）             |
  | Code Quality Review    | 6 项发现，全部 ACCEPTED 折叠                |
  | Test Review            | 覆盖图完成；3 测试缺口折叠；覆盖率折叠后 100%|
  | Performance Review     | 0 阻断                                     |
  | NOT in scope           | written（裁决 + TODO-021/022 延后）         |
  | What already exists    | written（ENG 声部 5 项基线复核确认）        |
  | TODOS.md updates       | TODO-021/022 增补（累计 014..022 九条）     |
  | Failure modes          | 6 行，0 critical gaps                      |
  | Unresolved decisions   | 0（全部经管线授权折叠）                     |
  | Outside voice          | codex unavailable（连接超时 ×3）单声部      |
  | Parallelization        | Sequential implementation, no              |
  |                        | parallelization opportunity（单主线 8 任务  |
  |                        | 强顺序依赖：1→2→3→4→5/6/7→8）               |
  | Lake Score             | N/A                                        |
  +====================================================================+
```

## Implementation Tasks（ENG 折叠映射）

- [x] **T1 (P1)** — catalog/scan — ENG-F1 分片前缀碰撞修复+测试（已折入 Task 1 文本）
- [x] **T2 (P2)** — cli/engines — ENG-F2/3/5/14/15/16/7/8/9/10 单行修复（已折入 Tasks 2/5/6/7 文本）
- [x] **T3 (P2)** — tests — ENG-F11/12/13 测试补齐（已折入 Tasks 4/5 文本）
（任务工件：~/.gstack/projects/ipostudio/tasks-eng-review-20261005-083833.jsonl——3 行，均已在计划文本落地，执行者按任务顺序即得）


### CEO 双声部 — Claude 本地声部（2026-10-05，INPUT: ceo 529131da…）

7 项发现，建议 REVISE BEFORE EXECUTION（不废计划）：
1. **[critical] 闭环的"价值"是惰性遥测**——completions 只存字符数不存内容，"重启可查"证明的是记账不是价值。建议：存交换内容（可截断）或把 completions 从价值叙事降级、以"真机一次真实补全"为 M0′ 证明标准。
2. **[high] 旗舰里程碑用回声服务器自证**——全部测试打 fake 引擎；argv 翻译层对真实 llama-server 版本的兼容风险无从暴露；Task 8 却回写"P2 入口条件满足"。建议：回写以一次真机小模型冒烟为门；实例行记录引擎版本。
3. **[high] 切片不再消灭它要消灭的风险**——M0′ 原案是 ≤2 天一次性探针（失败先修路线图）；本计划变成 8 任务生产子系统，触碰 M0 债务上限（"超出 M0 路径的精良实现押后"），而两个真正的高风险未知（真实引擎、真实用户）都被推迟。建议：守住 timebox 精神，样式守卫泛化与 walker 扩面移交 P2。
4. **[high] 漏评的替代方案：完全不监管进程**——外部自起引擎（用户自己跑 llama-server 或任意 OpenAI 兼容端口）+ `ipo chat`/目录/记录 ≈80% 用户价值 ÷20% 面积，消灭整个 stop/PID/端口竞争类；schema 里 `server_mode=remote` 本就是逃生门却被本计划封锁。建议：补一页 build-vs-external ADR；恢复 remote 的逃生门地位。
5. **[medium-high] 已知损坏的 UX 即默认路径 + 误杀残余**——关终端即停是真实用户第一周必踩；stop 在 Windows=TerminateProcess（优雅升级逻辑在最大份额 OS 上是死代码）；守卫验证端口却按记录 PID 发信号（PID 重用可误杀）。建议：README 首位警告；kill 前廉价身份关联（或端口应答与 PID 无法关联时拒绝 kill）；TODO-016 提级。
6. **[medium] 在有成熟免费在位者的商品层施工且无竞争检查点**——下载→运行→对话正是 Ollama/LM Studio 的入门面；差异化楔子（docparse+KB/多引擎网关/跨工具记忆）再滑一个里程碑。建议：宣布楔子 MVP 为下一交付；为本地运行层加竞争转向触发器。
7. **[medium] 6 个月轨迹：契约硬化在将被替换的进程模型上 + 第二条 chat 路径**——P3 落 ADR-004 完整形态、M0 验收是网关中介回路；本计划把退出码/端口避让展示/start 语义钉死在孤儿进程模型上，`ipo chat` 绕过 M0 必经的网关；`--json` 用 pretty JSON 与 §9.11 的 NDJSON 事件方言冲突。建议：计划内标注脚手架 vs 耐用件；chat 走可被网关实现的客户端抽象；`--json` 改单行紧凑 JSON 收敛方言。

---

## CEO DUAL VOICES — CONSENSUS TABLE

| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Premises valid? | NO→（折叠 #1/#2 后部分成立） | unavailable | N/A（单声部，不标 CONFIRMED） |
| 2. Right problem to solve? | PARTLY | unavailable | N/A（单声部） |
| 3. Scope calibration correct? | NO→（裁决 #14 诚实标注 + 真机冒烟门后收敛） | unavailable | N/A（单声部） |
| 4. Alternatives sufficiently explored? | NO→（ADR-011 补档） | unavailable | N/A（单声部） |
| 5. Competitive/market risks covered? | NO→（触发器 + TODO-019 补） | unavailable | N/A（单声部） |
| 6. 6-month trajectory sound? | PARTLY | unavailable | N/A（单声部） |

单声部 critical 标记：#1（惰性遥测）为单模型 critical——已按建议折叠（交换内容入库 + server info 回显）。Codex 不可用（provider 连接超时，重连 5/5 失败），覆盖缺口如实记录。

## CEO 评审发现处置（Analyze→Resolve→Apply，autoplan 六原则自动裁决）

| # | 发现 | 处置 | 依据 |
|---|---|---|---|
| 1 | completions 惰性遥测 | ACCEPTED：表加 prompt_text/output_text（2000 字符截断），chat 记录交换内容，`server info` 回显片段；测试断言内容入库 | P2 爆炸半径内 <1d |
| 2 | 回声服务器自证 / 回写门 | ACCEPTED：instances 加 engine_version（--version 探测）；Task 8 回写门 = 真机小模型冒烟清单，未跑则回写"待用户执行" | P1/P2 |
| 3 | M0 债务上限张力 | PARTIAL：裁决 #14 诚实标注形态变更来历；真机冒烟门补信息增益；QA 守卫泛化保留（<5 文件，P2 会在同表面施工） | P5/P6 |
| 4 | 外部服务替代方案 | ACCEPTED(ADR)/DEFER(remote)：architecture.md 增 ADR-011；`server_mode=remote` 保持 P4 前诚实封锁（规格 F04 属 P4；openai_client 即届时雏形）；"external-server-first 改道"本身作为 Gate 呈报项 | P5/P3 |
| 5 | 终端关闭 UX + 误杀 | ACCEPTED：`server start` 成功输出加终端生命周期提示；TODO-016 提级为 P2 时序；README 警告已有 | P2/P3 |
| 6 | 竞争在位者无检查点 | ACCEPTED：roadmap 回写含转向触发器；TODO-019 登记；"楔子 MVP 先行"作为 Gate 呈报项（改动路线图排位，单声部不自动裁决） | P6 |
| 7 | 脚手架标注 / chat 抽象 / --json 方言 | ACCEPTED/DEFER：ADR-011 记录脚手架件与演进归属；openai_client 即网关客户端雏形（注释在案）；--json 保持与既有命令一致的 pretty 单文档（walker 契约），NDJSON 事件方言留 P7——登记 TODO-020 | P5 |

## Review Sections 1–11（SELECTIVE EXPANSION，implementation-ready 深度）

**Section 1 Architecture** — 依赖图：cli/{models,server,chat}_cmd → cli/base → conf/store/logs；catalog/engines → conf/store/logs（ADR-008 边界守住，领域包零互引）。数据流四径：scan→upsert（dup path=upsert 幂等/空根=空态/不可读=计数跳过）；start→spawn→health→state（nil=无模型指引/空=无空闲端口 20 候选报错/error=failed 行+日志尾）；chat→active_instance→POST（nil=指引 start/503=loading/200=ok/error=记录+stderr）；stop→guard→signal→stopped（nil=幂等 no-op）。状态机：五态 CHECK 钉死；非法迁移被 DB 拒绝。SPOF：SQLite=协调点（WAL + race-safe migrate + busy_timeout，既有学习 sqlite-wal-cold-open 已在库内解决）；引擎崩溃由健康探测呈现（不静默）。回滚：纯增量迁移+新命令，git revert 即可。0 阻断。

**Section 2 Error & Rescue Map** — registry 见下方表：全部新代码路径逐面核，无未救 GAP。发现并修复 1 项：不可读目录静默跳过 → 计入 skipped（A7 已折叠）。

**Section 3 Security** — 无网络监听（仅出站回环）；子进程 argv 全部来自本地 config（pydantic 校验枚举/范围；extra_args 为用户自有配置，本地单用户威胁模型内可接受）；SQL 全参数化（find_model 无 LIKE 通配面）；引擎日志读取经 redact_text；chat 错误体经 redact_unambiguous（先例学习 broad-redaction-corrupts-prose 应用正确）；无新凭据路径。High 项：0。

**Section 4 Data Flow & Interaction** — 多 CLI 进程经 SQLite 行协调；migrate BEGIN IMMEDIATE 序列化（库内保证）。并发双 start：各自 INSERT starting 行、各自 choose_port，微秒窗内可能同端口→后 spawn 者绑定失败→failed 行（如实报告，spec 允许；彻底串行化属 P3）。交互表：重复 start=refused+restart 指引；陈旧状态=health 探测标注；零模型=空态指引；大目录=500 截断+提示；引擎中途死亡=status health down+reap 指引。全部处理。

**Section 5 Code Quality** — DRY：open_config_and_db/_fail 收敛于 base ✓；_refresh 与 _resolve_model 共享 scan+upsert 语义但错误语境不同——接受（各 <8 行）；supervisor._get 与 repo.get_instance 并存——依赖方向锁定的代价，已注释声明。命名/复杂度：_run_start 8 分支为 CLI 编排上限内。0 阻断。

**Section 6 Tests** — 金字塔：单元（scan/repo/argv/discovery/client）< 集成（supervisor e2e、CLI invoke）< 系统（真机冒烟手动门）。凌晨两点测试=假引擎全回路 e2e；敌意 QA=双 start/占端口/幽灵引擎/坏配置/畸形响应/stdin；混沌=外部 kill 引擎→status health down+指引。Flaky 登记：端口基座分文件错开（18300/18400/18555/18600/18700）+ choose_port 探测 + CI 三机并行；子进程超时 10-20s 宽限。LLM eval：不适用。

**Section 7 Performance** — scan 有界（500×深度4）；choose_port O(20)；completions 增长无全表扫描读路径（LIMIT 1/20），P6 由会话表取代（ADR-011）；引擎日志无轮转→TODO-015。0 阻断。

**Section 8 Observability** — 实例状态/引擎日志/补全记录三面可查；失败 detail+日志尾=三周后可诊断；admin=doctor（TODO-014 延后）。0 缺口。

**Section 9 Deployment & Rollout** — 迁移增量 CREATE IF NOT EXISTS；回滚=revert（表残留无害）；无 feature flag 需求；CI 三平台门=发布机制；部署后冒烟=pytest+`ipo version/doctor --json`。0 风险。

**Section 10 Trajectory** — 债：completions/instances 脚手架（ADR-011 登记）、--json 方言（TODO-020）、日志轮转（TODO-015）；可逆性 4/5；一年之问：ADR-011+supervisor 注释足以让 P3 工程师读懂取舍。0 阻断。

**Section 11 Design & UX** — SKIPPED（no UI scope；终端呈现契约由 DX 阶段深审）。

### 新登记 TODO（评审产生，Task 8 一并落 TODOS.md）

## TODO-020: --json 输出方言收敛（P7 前）
- **What:** 列表型 --json 现为 pretty 单文档（与 version/doctor/config 一致）；§9.11 的 NDJSON 事件方言（start/event/chunk/result）属 agent run/chat 流式场景。P7 设计事件流时明确两方言边界并写入门面文档。
- **Why:** 防止 P6/P7 事件流与既有列表方言冲突（CEO 评审 #7）。
- **Context:** 核心回路计划 Section 7/10 评审；walker 契约（json.loads）对两者兼容。
- **Effort:** human: S / CC: S
- **Priority:** P7
- **Depends on:** P6/P7

## NOT in scope（延后与拒绝，含理由）

- 模型下载器/`ipo models delete`/分类修正 — DEFERRED（P2 核心面，ADR-005 完整设计）
- 引擎自动安装 — SKIPPED（无阶段承诺；README 三平台指引）
- doctor 第五项 engine 检查 — DEFERRED（TODO-014）
- 引擎日志轮转/多实例日志名 — DEFERRED（TODO-015）
- stop 进程身份加固 — DEFERRED（TODO-016，提级 P2 时序）
- 常驻后台服务/detach — DEFERRED（TODO-017，P3）
- chat 流式/NDJSON 事件 — DEFERRED（TODO-018，P6）
- `server_mode=remote` 外部引擎直连 — DEFERRED（P4 F04；ADR-011 记录裁决）
- --json 方言收敛 — DEFERRED（TODO-020，P7）
- 多实例 T05/T06 — DEFERRED（P3）
- external-server-first 改道 / 楔子 MVP 先行 — 呈报 Final Approval Gate（路线图级方向，单声部发现不自动裁决）

## What already exists（复用面）

- 配置/校验/原子写：conf/loader.py + schema.py（ADR-003，键族增量登记）— 本计划只加 1 键
- SQLite 连接/WAL/race-safe 迁移：store/database.py — 002/003 走既有 migrate()
- 日志/脱敏：logs.py redact_text/redact_unambiguous — 引擎日志尾与 chat 错误体复用
- 呈现契约：cli/ui.py + _SuggestingGroup — 新命令全走既有门
- CLI 装配/帮助/文档生成：collect_command_docs 动态注册面 — 新命令自动进 help/guide
- QA 基建：--json walker（自动纳管新命令）、平台卫生守卫、191 测试基线

## Dream state delta（12 个月理想 vs 本计划落点）

```
  CURRENT STATE                     THIS PLAN                        12-MONTH IDEAL (M0+)
  P1 地基：可配置可体检，            首条真实价值回路：                经网关的完整闭环：
  零命令价值                         scan→select→serve→chat→record     下载模型→引擎实例→网关对话→
  （doctor/config/version）          手动装引擎/放模型                  持久化→重启可查；楔子差异化
```
本计划走完"地基→回路"这段；网关（P4）替换 chat 直连、会话（P6）替换 completions、监管（P3）替换孤儿进程——三者均有已登记演进路径（ADR-011）。

## Error & Rescue Registry

| 代码路径 | 可能出错 | 异常类 | Rescued? | 动作 | 用户所见 |
|---|---|---|---|---|---|
| open_config_and_db | 配置损坏/键非法 | ConfigError | Y | 逐条 detail→stderr | 问题+来源+修复指引, exit 1 |
| open_config_and_db | 库不可用 | sqlite3.Error | Y | doctor 指引 | exit 1 |
| scan_model_files | 目录不可读 | OSError | Y | 计入 skipped | "skipped N"提示 |
| scan_model_files | 截断 | — | Y | capped+flag | 截断提示 |
| resolve_engine | PATH 无引擎/配置路径缺失 | — | Y | 结构化 problem | 安装/修正指引, exit 1 |
| start_instance.spawn | 引擎不可执行 | OSError | Y | failed 行 | "cannot start engine" |
| start_instance.wait | 引擎启动即退 | — | Y | failed+日志尾（脱敏） | 退出码+末 15 行 |
| start_instance.wait | 健康超时 | — | Y | failed 行 | 600s 提示+logs/stop 指引 |
| start_instance.wait | Ctrl+C | KeyboardInterrupt | Y | terminate+failed | 中断说明 |
| probe_health | 503/连接失败 | HTTPError/OSError | Y | loading/down 分类 | 状态行如实 |
| stop_instance.kill | PID 已消失 | OSError | Y | 静默→状态写 stopped | "already gone"语义 |
| choose_port | 20 候选全占 | OSError | Y | None→报错 | 端口范围+host, exit 1 |
| chat_completion | HTTP 错误/连接/畸形 JSON | ChatError | Y | 记录 error 行+stderr | 原因+start 指引, exit 1 |

## Failure Modes Registry

| 代码路径 | 失败模式 | Rescued? | Test? | 用户所见 | Logged? |
|---|---|---|---|---|---|
| server start | 缺引擎 | Y | Y（ghost 路径） | 安装/修正指引 | instances 行 N/A（未建行即败） |
| server start | 引擎秒退 | Y | Y（exit-immediately） | failed+日志尾 | instances.detail |
| server start | 端口竞争输 | Y | Y（显式 --port 占用） | failed+日志尾 | instances.detail |
| server start | 重复启动 | Y | Y | refused+restart 指引 | —（拒绝路径） |
| server stop | PID 重用误杀 | 部分（port+health 守卫） | Y（守卫跳过 kill） | — | TODO-016 承接 |
| terminal close | 引擎随终端退出 | Y（对称限制+提示） | N/A（环境行为） | status health down | TODO-017 承接 |
| chat | 服务未启动/加载中 | Y | Y | start/status 指引 | completions error 行 |
| chat | 上游 500/畸形响应 | Y | Y | 原因+记录 | completions.detail |
| models scan | 目录不可读/伪 GGUF | Y | Y | skipped 计数 | skipped |

CRITICAL GAPS：0（误杀=守卫+TODO 承接；终端关闭=对称限制+提示+TODO 承接——均非静默失败）。

## Scope Expansion Decisions（SELECTIVE EXPANSION）

- Accepted: A1 交换内容入库、A2 engine_version+真机冒烟门、A5 终端提示+TODO-016 提级、A6 竞争触发器+TODO-019、A7 跳过计数、ADR-011、TODO-020
- Deferred: remote 模式（P4）、--json 方言（P7/TODO-020）、楔子 MVP 排位（Gate 呈报）
- Skipped: 引擎自动安装、下载器提前实现

## CEO Completion Summary

```
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY (CEO)             |
  +====================================================================+
  | Mode selected        | SELECTIVE EXPANSION（autoplan 覆盖）         |
  | System Audit         | 树净 @6372de5；191 绿；learnings 5 条命中应用 |
  | Step 0               | SELECTIVE EXPANSION；6 候选 4 延 2 拒        |
  | Section 1  (Arch)    | 0 阻断（SPOF=SQLite 已由库内机制覆盖）        |
  | Section 2  (Errors)  | 14 路径映射，0 GAP（A7 修复 1 项静默）        |
  | Section 3  (Security)| 0 High（误杀=守卫+TODO-016 提级）             |
  | Section 4  (Data/UX) | 边界表全覆盖；并发 start 竞争=如实失败         |
  | Section 5  (Quality) | 2 处已声明的小重复（依赖方向代价）             |
  | Section 6  (Tests)   | 图完成，0 缺口；flaky 风险登记                 |
  | Section 7  (Perf)    | 0 阻断（completions 增长无扫描读路径）          |
  | Section 8  (Observ)  | 0 缺口（TODO-014 延后已登记）                  |
  | Section 9  (Deploy)  | 0 风险（增量迁移+revert 回滚）                 |
  | Section 10 (Future)  | 可逆性 4/5；债 4 项全部 TODO 承接              |
  | Section 11 (Design)  | SKIPPED (no UI scope)                          |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (11 项)                               |
  | What already exists  | written                                       |
  | Dream state delta    | written                                       |
  | Error/rescue registry| 13 rows, 0 CRITICAL GAPS                      |
  | Failure modes        | 9 total, 0 CRITICAL GAPS                      |
  | TODOS.md updates     | 7 items (TODO-014..020)                       |
  | Scope proposals      | 6 proposed, 5 accepted, 2 skipped             |
  | CEO plan             | written (~/.gstack/.../ceo-plans/)            |
  | Outside voice        | codex unavailable（连接超时）— [single-model]  |
  | Lake Score           | N/A                                           |
  | Diagrams produced    | dream-state、依赖/数据流（文字图）              |
  | Stale diagrams found | 0                                             |
  | Unresolved decisions | 2（Gate 呈报）                                 |
  +====================================================================+
```

### Unresolved Decisions（Gate 呈报，单声部不自动裁决）
1. **external-server-first 改道**（Claude #4）：以"外部自起引擎 + 纯客户端"替代自建监管交付回路。成本：偏离规格 F03/P3 验收面与 2026-10-04 排位裁决；收益：面积 -80%、消灭 stop/PID 类风险。已折中（ADR-011 登记 remote=P4 逃生门）。
2. **楔子 MVP 先行**（Claude #6）：下一计划从 P2（模型管理）改为楔子功能之一。成本：M0 网关闭环被推后；收益：差异化前置、避开商品层竞争。已折中（TODO-019 触发器登记）。

---

## DX DUAL VOICES — CONSENSUS TABLE

| Dimension | Claude | Codex | Consensus |
|---|---|---|---|
| 1. Getting started < 5 min? | 6/10（暖路径 <2min；冷路径受既定手动范围限制，诚实披露） | unavailable | N/A（单声部） |
| 2. API/CLI naming guessable? | 7/10（单复数分工/组+简写一致；扣：model-info vs server info、--server 残留、双重启动语义未解释） | unavailable | N/A |
| 3. Error messages actionable? | 8/10（问题+原因+修复全覆盖；扣：status 缺教练行、--port 失败缺端口提示、reap 行话） | unavailable | N/A |
| 4. Docs findable & complete? | 8/10（guide 注册表驱动自动纳新；扣：GGUF 来源缺、Windows 安装提示缺、cmd.exe 引号） | unavailable | N/A |
| 5. Upgrade path safe? | 9/10（增量迁移、键三同步、CHECK 钉死、幂等 upsert） | unavailable | N/A |
| 6. Dev environment friction-free? | 8/10（R1 纪律真实验证；扣：任务命令硬编码 .venv/Scripts 路径对 POSIX 贡献者不友好、端口 e2e 有 CI 抖动风险） | unavailable | N/A |

Codex 不可用（provider 连接超时，重连 5/5 失败，与 CEO 阶段同征）——DX 全表 N/A，单声部 HIGH 项已标记。**单声部 HIGH**：前置条件文档（装引擎/取模型）是回路中最耗时两步却最薄——已折叠。

## DX 评审发现处置（DX POLISH，全部在已接受范围内）

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| 1 | HIGH | 前置文档最薄：无 Windows 安装提示、无 GGUF 来源 | ACCEPTED：README 块补 Windows 资产/winget 提示 + 小型 instruct GGUF 来源（HF/ModelScope 举例） |
| 2 | MEDIUM | `ipo status` 健康降级无修复指引（server info 有） | ACCEPTED：status 在 running 且 health≠ok 时输出同一教练行 |
| 3 | MEDIUM | 显式 `--port` 失败只有通用引擎退出信息 | ACCEPTED：失败 detail 追加"(you passed --port N; verify that port is free on host)"；预探测仍按裁决 #11 留 P3 |
| 4 | MEDIUM | `ipo start --server` 旗标从未被读取 | ACCEPTED：保留旗标（§9.11 选项齐性），帮助文本明示"accepted but always on" |
| 5 | LOW | reap 行话；引擎错误泄漏配置系统语义（none 只清 Optional）；model-info/server info 不对称；双重启动语义差异；cmd.exe 引号；venv 硬编码路径 | 部分 ACCEPTED：reap→"stop it with"（2 处）、none 泄漏句删除；其余记为评审备注（装饰性，不折入 timebox） |

## DX Review Passes 1–8（DX POLISH，全部评估无跳过）

**Pass 1 Getting Started — 6/10**：暖路径 5 命令一整块可复制（T8 README）；scan-before-resolve（裁决 12）省一轮；欢迎卡状态箭头指路；端口自动避让。冷路径受裁决 #1 手动范围限制（诚实披露于 README 与 roadmap 门）；doctor 不查引擎致失败发现偏晚（TODO-014 已登记）→ 折叠 F1 后预计 7/10。
**Pass 2 API/CLI — 7/10**：单复数分工、组+简写、统一 --json/--timeout、chat - 管道、退出码 0/1/2 全钉。扣分项见处置表 4/5 → 折叠后 7.5/10。
**Pass 3 Errors — 8/10**：三段式（问题+原因+修复）几乎全覆盖：引擎缺失双形态指引、模型未选指引、歧义匹配列候选、引擎退出带脱敏日志尾、超时给假设+两条恢复命令、chat 不可达指 start、库失败指 doctor。折叠 F2/F3/F5b 后 8.5/10。
**Pass 4 Docs — 8/10**：guide 注册表驱动（新命令自动出现，守卫测试钉住）；README quickstart 全可复制且 click `--` 用法正确；折叠 F1 后 8.5/10。
**Pass 5 Upgrade — 9/10**：增量迁移、每命令自迁移、新键默认空回退 PATH 且三处同步钉死、状态字面量单源+守卫测试、upsert 幂等。
**Pass 6 DevEnv — 8/10**：R1 全程无分支（PATHEXT 双名测试、SIGKILL 值适配、os.scandir 3.11 兼容）、零新依赖、tmp_path 卫生、端口分基座。venv 硬编码为本机约定（README 双平台）。
**Pass 7 Community — 4/10**：公开 GitHub 仓库 + MIT 已就位；无贡献指南/社区渠道/示例目录——地基阶段诚实现状，楔子期前不投入（路线图 M0 债务上限约束），不折入。
**Pass 8 DX Measurement — 6/10**：真机冒烟清单（可重复执行=准 TTHW 度量）+ roadmap 回写门 + /devex-review 回旋镖（TODO-003 已登记 P2）；无仪器化遥测（本地优先产品不应默认上报——留待 P17 监控计划）。

### DX Scorecard

```
+====================================================================+
|              DX PLAN REVIEW — SCORECARD                             |
+====================================================================+
| Dimension            | Score(post-fold)  | Initial | Trend  |
|----------------------|-------------------|---------|--------|
| Getting Started      | 7/10              | 6/10    | ↑      |
| API/CLI/SDK          | 7.5/10            | 7/10    | ↑      |
| Error Messages       | 8.5/10            | 8/10    | ↑      |
| Documentation        | 8.5/10            | 8/10    | ↑      |
| Upgrade Path         | 9/10              | 9/10    | →      |
| Dev Environment      | 8/10              | 8/10    | →      |
| Community            | 4/10              | 4/10    | →      |
| DX Measurement       | 6/10              | 6/10    | →      |
+--------------------------------------------------------------------+
| TTHW                 | 暖 <2 min；冷 ~20-40 min（手动装引擎+下模型，既定范围）|
| Competitive Rank     | Competitive（暖路径）；冷路径诚实标注 Needs Work        |
| Magical Moment       | `ipo chat "hello"` 首个真实本地回答（0D 载体=回路本身） |
| Product Type         | CLI Tool                                             |
| Mode                 | DX POLISH                                            |
| Overall DX           | 7.5/10（初评 7/10）                                   |
+====================================================================+
```

### Developer Persona Card（Step 0A，README 推断，P6）

- Who: 本地优先 AI 用户中的开发者/技术Power User——在自己机器上跑本地模型，终端熟练
- Context: 想要"下载→运行→对话"不注册不上云；对本机资源与路径有掌控欲
- Tolerance: 暖路径 ~5 分钟；冷路径愿付一次性安装成本但不读长文档
- Expects: `tool verb --flag` 约定、`--help` 自解释、错误给修复指引、复制即用的命令块

### Developer Empathy Narrative（Step 0B，基于计划内容，非运行时观察）

"我在终端里。`ipo` 打出来是一张三行欢迎卡，箭头告诉我下一步是 `ipo doctor --fix`——照做，四项 PASS。卡片现在指向 `ipo models`：空的，但它列出了搜索过的目录，还告诉我在哪放 .gguf、怎么登记别的目录。装好 llama-server、丢进一个小模型再跑一次：表里出现我的模型。`ipo model --select tiny-q4` 保存并提醒重启生效。`ipo server start` 选了空闲端口，打印地址、PID、日志路径，还提醒我别关终端。`ipo chat "hello"`——第一条本地回答回来了。`ipo server info` 能看到刚才那次问答的内容。全程没有一个'去读文档'的时刻；每次失败都告诉我原因和下一条命令。"

### Developer Journey Map（9 阶段）

| 阶段 | 开发者动作 | 摩擦点 | 状态 |
|---|---|---|---|
| 1. Discover | GitHub/README | 无社区渠道（Pass 7） | ok（阶段现实） |
| 2. Evaluate | README quickstart 通读 | — | ok |
| 3. Install | 装 llama.cpp + 放 GGUF（手动，既定） | F1 已折叠：Windows 提示+模型来源 | fixed |
| 4. Hello World | doctor→models→select→start→chat | 5 命令一整块；scan-before-resolve 省步 | ok |
| 5. Integrate | model_dirs 登记自定义目录/--json 脚本化 | cmd.exe 引号（备注，未折） | deferred |
| 6. Debug | server logs/info/status | F2/F3 已折叠：status 教练行+端口提示 | fixed |
| 7. Upgrade | 迁移/新键自动生效 | — | ok |
| 8. Scale | 多实例（P3） | 范围外（裁决 #2） | deferred |
| 9. Migrate | 增量迁移向前 | — | ok |

### First-Time Developer Confusion Report（Step 0G 摘要）

T+0:00 裸 `ipo` → 欢迎卡指路（已处理）；T+1:00 `ipo models` 空态 → 列出搜索根+放置指引（已处理）；T+3:00 `server start` 报缺引擎 → 确定性指引安装或设 llama_cpp_path（已处理）；T+8:00 放好模型直接 `model --select` → 先刷新再解析（裁决 12，已处理）；T+12:00 start 成功 → 终端生命周期提示（已处理）；T+15:00 chat 报"no server is running"→ 指回 start（已处理）。全部有界；无未处理困惑点。

### DX Implementation Checklist

```
DX IMPLEMENTATION CHECKLIST
============================
[x] Time to hello world（暖路径）< 5 min；冷路径手动范围诚实披露
[x] Installation is one command（pip install -e .；引擎安装手动=既定范围）
[x] First run produces meaningful output（doctor/欢迎卡/空态全指引）
[x] Magical moment via `ipo chat "hello"` 首个本地回答
[x] Every error message has: problem + cause + fix（Error Registry 13 行全 Y）
[x] API/CLI naming guessable（models/model 分工；server 组+简写）
[x] Every parameter has a sensible default（端口避让/600s/127.0.0.1）
[x] Docs have copy-paste examples that actually work（README quickstart）
[x] Upgrade path：增量迁移 + 键三同步 + CHECK 钉死
[ ] Community/贡献指南（Pass 7，楔子期前不投入）
[ ] TTHW 仪器化遥测（本地优先，P17 决策）
```

### NOT in scope（DX 延后项）

- 装饰性文案统一（model-info/server info 命名对称、双重启动语义差异说明、cmd.exe 引号变体）— 评审备注级，不折入 timebox
- 社区基建（贡献指南/示例目录/渠道）— 楔子期前不投入
- TTHW 遥测 — P17 监控计划裁决
- shell 补全（TODO-001，P2 前）

### What already exists（DX 复用面）

- 欢迎卡状态箭头（CLI-UX 计划交付）— 回路化复用
- `_SuggestingGroup` 命令建议 — 新命令组自动继承
- guide 注册表驱动 — 新命令自动入册
- 错误三段式契约 + QA walker --json 洁净守卫 — 新命令全继承

## Codex 补充声部（复跑成功，2026-10-05）

前三阶段评审期间 Codex 外部声部三次不可用（`workspace routing discovery timed out`，各阶段 close packet 已如实记录 `outside_status: unavailable`）。用户指令复跑：探测 auth/model/烟雾测试全过（codex-cli 0.159.1，模型 gpt-6-astra）；三份阶段提示词 = 边界声明 + 阶段对抗指令 + 前序共识摘要 + **计划实现节全文（156KB，经 stdin 规避 Windows 32KB argv 上限，无截断——上轮 26KB 截断的根因即 argv 限制）**；read-only 沙箱挂仓库根，允许只读核对源码声明。三路 `codex exec` 并行，全部 exit 0，`outside-review-result.ts` 校验通过（Recommendation 行齐备）。原始输出存档：`~/.gstack/projects/ipostudio/codex-outside-{ceo,dx,eng}-response.txt`。

### CEO 外部声部 — 10 条（8×P1、2×P2）

| # | 级 | 发现（缩写） | 裁决 | 落点 |
|---|----|--------------|------|------|
| CX1 | P1 | 验收只证技术连通，缺用户价值证据 | ACCEPT（文档） | roadmap 回写门：P2 立项门槛 = 明确用户真实任务+可测改善；止损线 |
| CX2 | P1 | 自建监管是循环论证（规格要求自建≠价值证明） | ACCEPT（文档） | ADR-011 已有外部端点优先逃生门；TODO-019 具体化对比承诺（见 Challenge ①） |
| CX3 | P1 | TODO-019 触发条件不可操作 | ACCEPT（文档） | TODO-019 具体化：选定一楔子+入口/替换对象/指标/停止日期（见 Challenge ②） |
| CX4 | P1 | 首跑范围排除了新手又没给熟手机会 | ACCEPT（文档） | Goal 增目标用户段（终端熟手；新手路径归 P2 下载器） |
| CX5 | P1 | 可靠性已是本次承诺而非未来增强 | ACCEPT（代码） | 超时终止孤儿进程 + 条件状态转换（见 DXF2/EXF2/EXF3） |
| CX6 | P1 | 默认保存对话无召回验证、无数据控制 | PARTIAL（代码+TODO-023） | 持久化边界脱敏 + QA 密钥样本；默认保存保留（本地库+重启可见裁决）；opt-out/清除入 TODO-023 |
| CX7 | P2 | 非流式单轮 chat 场景不明 | ACCEPT（文档） | Goal 定位：冒烟/诊断探针；流式 TODO-018 |
| CX8 | P2 | 工程约束替代用户决策（--server 恒开、model-info 必填名、R1） | REJECT（已裁决） | 三者均既有范围裁决/规格要求；--server 帮助文本已说明；语义不对称补 README（见 DXF11） |
| CX9 | P2 | 八任务 timebox 无预算无止损；真机验证太靠后 | ACCEPT（文档） | 冒烟清单标注"Task 4 起可执行"+止损线入回写门 |

### DX 外部声部 — 12 条（1×P0、7×P1、4×P2）

| # | 级 | 发现（缩写） | 裁决 | 落点 |
|---|----|--------------|------|------|
| DXF0 | **P0** | `ipo start --model` 缺 import → NameError 首跑崩溃 | **ACCEPT（代码）** | Task 6 import 区补 scan/upsert/activate/ConfigError（与 ENG 交叉印证） |
| DXF1 | P1 | guide 收集器：Argument 当选项、不递归子命令 | PARTIAL（代码） | 收集器升级（参数/子命令递归）；"崩溃"说法核实为不准（`Argument.help` 恒 None 不炸），缺口是完整性 |
| DXF2 | P1 | 启动超时留活引擎且 stop 不可达 | ACCEPT（代码） | 超时即 terminate+escalate；failed 行如实"已终止"（三声部一致） |
| DXF3 | P1 | stop 无 PID 所有权证明，健康 200/503 即放行 kill | ACCEPT（代码） | `probe_identity` /props 模型文档守卫：owned 才发信号/foreign 拒绝/absent 不发；TODO-016 改 PID 级残余 |
| DXF4 | P1 | README quickstart 非 5 分钟、不可复制 | ACCEPT（文档） | Linux 安装行、huggingface-cli 下载示例、doctor 先建目录、下载/TTHW 分记 |
| DXF5 | P1 | 同名歧义死循环（唯一路径也被拒+幽灵行） | PARTIAL（代码+TODO-021） | 拒绝消息精确化；列表 `(missing)` 标注；path-addressable 激活入 TODO-021 设计面 |
| DXF6 | P1 | save 不盖版本戳 → 降级读坏档 | ACCEPT（代码） | loader.save() 盖 `config_version` + 测试（Task 3） |
| DXF7 | P1 | completions 原文落盘违反凭据契约 | ACCEPT（代码） | `record_completion` 持久化边界 `redact_text` + 密钥样本测试（与 CEO/ENG 一致） |
| DXF8 | P2 | `model --select --json` 输出自然语言 | ACCEPT（代码） | 选择分支结构化 JSON（与 ENG EXF16 一致） |
| DXF9 | P2 | 激活成功提示与环境覆盖矛盾 | ACCEPT（代码） | `IPO_LOCAL_CHAT_MODEL` 覆盖警告接入 model --select |
| DXF10 | P2 | ConfigError/权限/SQLite 错误逃逸成 traceback；content null 崩溃 | ACCEPT（代码） | 三处 `(LookupError, ValueError, ConfigError)` 收口 + `isinstance(content, str)` 守卫 |
| DXF11 | P2 | start/server 语义不对称；restart 先停后验 | ACCEPT（代码+文档） | 两个 restart 先验引擎+模型再停；语义四行入 README Notes |

### ENG 外部声部 — 17 条（9×P1、8×P2）

| # | 级 | 发现（缩写） | 裁决 | 落点 |
|---|----|--------------|------|------|
| EXF1 | P1 | stop 身份守卫不足（同 DXF3） | ACCEPT | 同 DXF3 |
| EXF2 | P1 | 超时孤儿（同 DXF2） | ACCEPT | 同 DXF2 |
| EXF3 | P1 | 生命周期竞态：stop 可在写 PID 前标 stopped，start 随后复活 | ACCEPT（代码） | `_touch(expect=...)` 条件转换 + stop 条件写 + 败者 terminate + 交错测试 |
| EXF4 | P1 | 健康失败当进程退出，虚报停止 | ACCEPT | 身份守卫三分支：absent → 不发信号+如实 detail |
| EXF5 | P1 | extra_args 可覆盖 --host/--port/--model | ACCEPT（代码） | build_server_argv 托管旗标校验 + ValueError |
| EXF6 | P1 | 坏配置阻断 stop（事故恢复死锁） | ACCEPT（代码） | base.open_db_only；五个 conn-only 命令面（stop×2/status/list/info）脱离配置加载 |
| EXF7 | P1 | 相对路径跨 cwd 不稳定、重复登记 | ACCEPT（代码） | model_scan_roots `resolve()` + chdir 测试 |
| EXF8 | P1 | 陈旧行绕过完整性检查（截断/丢分片照常启动） | PARTIAL（代码） | `shard_family_complete` 启动前复核 + 列表标注；目录剪枝仍 TODO-021 |
| EXF9 | P2 | 分片数量相等≠序号连续（{1,3}-of-2 通过） | ACCEPT（代码） | 序号集合==1..N 校验 + 反例测试 |
| EXF10 | P2 | 扫描预算只限 GGUF 候选且 scandir 全量物化 | ACCEPT（代码） | 流式 scandir + `MAX_SCAN_VISITED` 全局访问预算 + 测试 |
| EXF11 | P2 | IPv6 主机 choose_port 必败；监听/连接地址混用 | PARTIAL（代码+TODO-024） | choose_port 按主机字面选地址族 + 65536 上限；连接地址推导入 TODO-024 |
| EXF12 | P2 | 端口 65535→65536 OverflowError；--port 0/负数、非有限 timeout | ACCEPT（代码） | choose_port 范围钳制 + _run_start 边界校验 |
| EXF13 | P1 | 交换内容与引擎日志违反凭据不落盘（同 DXF7） | ACCEPT | 同 DXF7；引擎日志为引擎进程直写，展示脱敏+README 残余声明 |
| EXF14 | P2 | chat 响应类型不校验（null/数字/列表崩溃） | ACCEPT（代码） | 同 DXF10 + null 用例 |
| EXF15 | P2 | ConfigError 逃逸 + 环境覆盖语义（同 DXF9/10） | ACCEPT | 同 DXF9/10 |
| EXF16 | P2 | select --json 违反契约（同 DXF8） | ACCEPT | 同 DXF8 |
| EXF17 | P1 | 代码块同步缺陷：Task 6 缺 import（同 DXF0）；两处 `_INSTANCE_COLUMNS` 均缺 `engine_version`，e2e 读取必 KeyError | **ACCEPT（代码）** | 两处列清单补 `engine_version`（与 1547 行 e2e 断言闭合） |
| — | P1 | 测试确定性四处失败（写前未建目录×5、包级样式守卫误杀 ui.py、prefers_latest 断言错误、重连测试关掉 fixture 连接） | **ACCEPT（代码）** | 五处 mkdir、ui.py 豁免、断言改为"停最新后旧行仍 active"、二次连接替戏 close |

（ENG 另两条时序/止损建议与 CX9 同项合并。）

### 三声部一致项（单声部关键发现升级为共识）

1. **超时孤儿进程**（CEO+DX+ENG）：start 超时旧行为"标 failed 留活进程"，而 stop 只查活动态 → 用户照错误提示操作也无法回收。折叠：超时即终止+升级杀，detail 如实。
2. **stop 身份守卫**（DX+ENG）：健康 200/503 不能证明 PID 所有权。折叠：/props 模型文档证明，foreign 拒绝、absent 不发信号；TODO-016 降级为 PID 级残余加固。
3. **completions 信任面**（CEO+DX+ENG）：原文入库+回显是凭据泄漏路径。折叠：持久化边界 `redact_text` + 真实形状密钥 QA；控制面 TODO-023。
4. **真机验证时序**（CEO+ENG）：全部实现后才碰真机=最大不确定性最后暴露。折叠：Task 4 起可手动冒烟 + 止损线 + P2 立项门槛。

### User Challenges 更新（三声部印证，仍待用户裁决）

- **Challenge ①（外部端点优先 vs 自建监管）**：Codex CEO 独立提出"循环论证"批评（CX2），与原 Challenge 同向。已折入 ADR-011 对比承诺与 TODO-019 具体化；**方向选择仍属用户**。
- **Challenge ②（楔子 MVP 排位）**：Codex CEO 独立批评原触发条件不可操作（CX3），与原 Challenge 同向。TODO-019 已具体化为"选定一楔子+试用入口/替换对象/成功指标/停止日期"；**选哪个楔子仍属用户**。
- **新 Challenge ③（会话记录默认保存）**：三声部一致要求控制面。本计划折入脱敏+QA；若用户要求 M0′ 即带 `--no-save`/清除命令（而非 TODO-023 到 P2），批准门时说明即可，为一个小型范围追加。

### 折叠清单（70 处替换）

Task 1 扫描（流式+访问预算+序号连续性+绝对路径身份+family_complete+4 测试）；Task 2（collector 升级、open_db_only、select --json/ConfigError/覆盖警告、激活消息、missing 标注、样式守卫豁免、fixture mkdir）；Task 3（托管旗标校验、/props 替身面、loader 版本戳+测试）；Task 4（`_INSTANCE_COLUMNS`×2 补 engine_version、条件状态机、超时终止、身份守卫重写 stop、6 个新/改测试）；Task 5（族完整性复核、端口/超时边界、五个 db-only 面、stop 拒绝语义、restart 预检、record 脱敏、fixture 修正）；Task 6（P0 import 修复、ConfigError、restart 预检+持久语义、stop 拒绝语义）；Task 7（content 类型守卫、重连测试修正、null/脱密测试）；Task 8（README 四处、CHANGELOG 三条、TODO-016/019/021/022 更新、TODO-023/024 新增、约束行、冒烟清单时序）。

### 声部结论

Codex 三阶段 Recommendation 均为 `revise before implementation`；上述 70 处修订即按其意见完成并逐条核实过计划原文（DX 的"collector 崩溃"一项核实为不准确，已按真实缺口折叠并注明）。本节起本计划具备完整外部声部覆盖：**OUTSIDE COVERAGE: codex × ceo/dx/eng completed（2026-10-05 复跑）**。
