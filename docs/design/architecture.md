# ipostudio 架构设计记录（洁净室独立实现）

> 依据：`Functional Specification v1.0.md`（下称"规格"）。
> 本文档只依据规格描述的**外部行为与接口契约**做独立设计；未参考、未复制任何第三方项目的内部实现。
> 规格第 1.3 节明确"不要求采用特定编程语言、GUI 框架或数据库产品"，因此以下所有技术选型均为独立决策。

## 0. 洁净室声明

- 实现依据仅限：规格正文、公共协议（OpenAI Chat Completions / Anthropic Messages / MCP / JSON-RPC 2.0 / HTTP Range / SSE）、公开标准与许可证兼容的第三方依赖。
- 所有模块划分、数据结构、命名（除规格 1.2 节规定的接口名称 `ipo`、`IPO_`、`ipo-`、`.ipobackup`、`ipostudio.kb`、`ipostudio.backup` 及标准协议字段外）均为独立设计。
- 重要决策以下列 ADR 记录，满足可审计性要求。

## 1. 系统形态（从第一原则推导）

规格要求的本质是一个**本地优先的单用户多进程系统**：

1. GUI 桌面壳、CLI `ipo`、HTTP 网关、MCP 端点、引擎子进程——五个入口共享同一份逻辑数据（规格验收标准 5）。
2. 存在长生命周期后台工作：模型下载（可暂停/续传）、推理引擎进程、计划任务调度、视频/音乐上游任务轮询。
3. 生成类流量需要流式转发（SSE / WebSocket / 逐块音频）。

由此得出进程模型（ADR-004）：**一个可选的后台服务进程 + 多个轻客户端进程**：

```
┌─────────────┐   ┌──────────┐   ┌────────────────────────────────┐
│ 桌面壳(后期) │   │ CLI ipo  │   │  ipostudio 后台服务 (常驻/按需) │
│  Tauri+Web  │   │          │   │  ├─ 网关 FastAPI (F05)          │
└──────┬──────┘   └────┬─────┘   │  ├─ 引擎监管器 (F03)           │
       │  本地HTTP/WS    │          │  ├─ 下载管理器 (F02)           │
       └────────┬───────┘          │  ├─ 调度器 (F08)               │
                ▼                  │  └─ 摄取/媒体任务工作器          │
       ┌──────────────────┐       └───────┬───────────────┬────────┘
       │ SQLite (WAL)      │◄──────────────┘               │ spawn/stdio
       │ ~/.ipostudio/     │                              ▼
       └──────────────────┘                    llama.cpp / vllm / sglang / mlx
```

- CLI 与桌面壳在没有后台服务时仍可完成纯数据操作（读配置、查库、离线命令），满足规格 5.26"部分命令离线可用"。
- 跨进程一致性靠 SQLite WAL + 配置文件原子写 + 短轮询（规格 11.1：跨进程变化约 2 秒窗口可见）。

## 2. 技术选型（ADR）

### ADR-001 后端语言与 Web 框架：Python 3.11+（目标 3.12）+ FastAPI

- 要解决的问题：网关必须提供 `/openapi.json`、`/docs`、`/redoc`（规格 9.1），校验错误必须是 `detail` 数组含 `loc/msg/type/input/ctx`（规格 9.6），且需要 SSE/WebSocket 流式。
- 可选方案：a) Node/TS + 手写校验与 OpenAPI 文档；b) Rust (axum)；c) Python + FastAPI。
- 选择：c)。FastAPI+Pydantic（MIT/BSD，许可证兼容）原生产出上述契约形态，是"通过正常依赖管理满足公共协议规格"的最短路径；同时 Python 生态覆盖 OCR/ASR/模型仓库 API 等外部依赖面。
- 理由：外部契约是规格强制的，其余方案都要手工复刻协议形态，违背"最自然、最简洁"原则。
- 版本基线：`requires-python >= 3.11`（`datetime.UTC` 等特性所需），CI 以 3.12 为主验证版本。

### ADR-002 存储：单文件 SQLite（WAL），无 ORM，仓库函数层

- 要解决的问题：本地优先持久化 + 多进程读写 + 无服务器。
- 可选方案：PostgreSQL（违背本地优先轻量部署）、DuckDB（分析型）、逐域 JSON 文件（一致性差）、SQLite。
- 选择：SQLite，`sqlite3` 标准库直连，`PRAGMA journal_mode=WAL`；按功能域写仓库函数（repository functions），不引入 ORM。
- 理由：零部署、跨进程、事务一致；仓库函数层保持 SQL 可审计，避免 ORM 与洁净室命名要求冲突。物理表名不在规格约束内，由各子项目计划自行设计。

### ADR-003 配置：TOML 文件 + `IPO_` 环境变量覆盖 + Pydantic 校验

- 要解决的问题：规格 11 节的键集合、默认值、枚举/范围校验、未知键拒绝、GUI/CLI 语义一致。
- 设计：活动配置文件 `<数据目录>/settings.toml`（可用 `IPO_CONFIG` 指定其他路径）；文件内为小写蛇形键（如 `server_port`），环境变量 `IPO_SERVER_PORT` 覆盖；Pydantic 模型 `extra="forbid"` 实现未知键拒绝；原子写（临时文件 + `os.replace`）。
- 键族按子项目增量登记：核心计划实现 11.2 节全部通用/推理键，后续计划各自扩展 `TTS_*`、`ASR_*`、`KB_*` 等族。

### ADR-004 进程模型：后台服务进程 + 轻客户端

- 要解决的问题：引擎进程、下载、调度、网关需要常驻；CLI/桌面需要即起即走。
- 选择：`ipostudio-server`（内部名 `ipostudio.runtime`）按需启动、`ipo serve` 前台化；客户端经本地控制端点（网关同进程的路由）通信。
- 备选：全部塞进桌面壳进程（Electron 式）——被否决，因为 CLI 无头执行（规格 5.7/9.11）要求无 GUI 也能运行全部服务。

### ADR-005 可续传下载：分片元数据边车 + Range 协商

- 要解决的问题：规格 5.2 的暂停保留进度、HTTP Range 续传、服务端忽略 Range 时"安全退化不能错误追加"。
- 独立设计：目标文件 `<name>.part` + 边车 JSON `<name>.part.meta`（记录 url、etag/last-modified、已完成字节、分片表）。续传前以 `If-Range`/`Range: bytes=N-` 探测：返回 206 才追加；返回 200 视为服务端不支持 Range，丢弃已有分片从头整写（绝不拼接）。区间不一致或总量不符时不得登记为完整模型（对应下载状态机：`queued/downloading/paused/completed/failed/cancelled`）。
- 默认并发：2 个文件、每文件 4 连接（`IPO_DOWNLOAD_FILES/PARTS`）。

### ADR-006 日志：标准库 logging + 轮转 + 脱敏过滤器

- 要解决的问题：规格 5.23（实时/过滤/滚动/复制/清空、约 2MB 轮转、JSON/JSONL、凭据脱敏、崩溃后磁盘可读）。
- 设计：`RotatingFileHandler(maxBytes=2MB, backupCount=5)` 写 `<数据目录>/logs/`；自定义 `RedactionFilter` 对记录内疑似凭据值打码（消息 + traceback 双层，覆盖 `access_token=`、JSON 字段、URL 内嵌凭据等形态）；`json_lines=True` 时用 JSONL Formatter。CLI `ipo logs` 直接读磁盘文件（后台服务停止也可读）。
- **多进程所有权（Eng 审查决策）**：长驻进程（P3 引擎监管、P4 网关）各自写按进程命名的日志文件；不做单写者进程。前提登记 TODO-004。

### ADR-007 桌面壳：Tauri 2 + Web 前端（后期子项目落地）

- 选择 Tauri 而非 Electron：体积与内存占用更贴合"本地工作台"长期常驻的定位；Web 层与网关 `/chat`、`/agent` 网页端（规格 5.25）共享组件。此项在桌面壳计划开始时允许被复审推翻。

### ADR-008 模块边界（包内分层）```
ipostudio/                  # Python 包（后台服务 + CLI + 网关同源）
  conf/       # ADR-003 配置：schema.py / loader.py / paths.py
  logs.py     # ADR-006 日志
  store/      # ADR-002 数据层：database.py + migrations/NNN_*.sql
  cli/        # `ipo` 命令（click）
  runtime/    # 后台服务装配（后续计划）
  downloads/  # ADR-005 下载引擎（P2）
  catalog/    # 模型目录/搜索/扫描（P2）
  engines/    # 引擎监管（P3）
  gateway/    # FastAPI 网关（P4/P5）
  chatl/      # 对话领域（P6）
  agentx/     # Agent 运行时（P7）
  autosched/  # 自动化（P8）
  voice/ media/ ocr/ translate/   # 多模态域（P9-P11）
  docparse/   # 文档格式解析注册表（ADR-009，P11/P13 消费）
  promptlib/ minis/               # 提示词/小应用（P12）
  kb/         # 知识库（P13）
  memstore/   # 记忆（P14）
  skillhub/   # 技能（P15）
  toolbridge/ # 编码工具接入（P16）
  metrics/    # 监控评测（P17）
  vault/      # 备份恢复（P18）
  netaccess/  # 代理/网页/隧道（P19）
apps/desktop/ # Tauri 壳（P20，独立构建）
```

- 规则：领域包之间不互相 import，只允许依赖 `conf/store/logs` 与显式接口模块；跨域调用一律经 `runtime` 装配层组合。

### ADR-009 文档格式策略：解析器注册表 + 归一化块模型（需求附录 R2）

- 要解决的问题：知识库/OCR/会议纪要需摄取 OOXML（docx/pptx/xlsx）与 ODF（odt/odp/ods），且格式集合会继续增长。
- 可选方案：a) 每个消费方各自解析；b) 独立 `docparse` 模块统一解析为归一化块；c) 外部命令行转换（LibreOffice headless）。
- 选择：b)。新增 `ipostudio/docparse/` 模块：按扩展名注册解析器（Python 库：python-docx、python-pptx、openpyxl，均 MIT；ODF 后续评估），统一输出归一化块序列 `{kind: paragraph|table|slide|sheet, index, page, text, ref}`——`ref` 为可核对定位（`docx¶12`、`xlsx!Sheet2!C7`、`pptx#slide4`），保留表格关系与工作表位置；供分块器与 OCR 管线消费。传统二进制格式（doc/ppt/xls/rtf）不承诺解析，明确提示转换（预留标注）。
- **P13 锁定前义务（CEO 审查）**：用真实 DOCX/PPTX/XLSX/ODF 样本验证"导入 → 检索 → 回答 → 定位原文"闭环后方可冻结块模型；外部转换方案（LibreOffice headless）需以实测质量与部署成本对比后决定是否作为可选兜底，不凭"依赖重"提前排除。
- 理由：a) 违反 DRY 且格式能力检查（F18/F19 卡片"缺项"展示）需要统一查询点；c) 引入重外部依赖且许可/部署面不可控，仅作为用户自配的可选兜底，不作承诺。解析依据 ECMA-376/OASIS ODF 公开标准，洁净室约束不变。

### ADR-010 三平台支持矩阵与平台差异处理（需求附录 R1）

- 要解决的问题：macOS/Windows/Linux 均为一级目标（附录 R1），差异必须显式管理而非散落各处。
- 设计：
  1. **CI 三平台矩阵**（P1 Task 9）是支持的执行机制——Windows/Linux/macOS 全绿才算通过。
  2. 引擎可用性矩阵（运行时探测后如实展示）：llama.cpp=三平台；vllm/sglang=仅 Linux（Windows+WSL2 属用户自配，不承诺）；mlx=仅 Apple Silicon macOS。缺引擎按规格 §5.3 明确报告。
  3. 已识别的平台差异点及归属：UTF-8 输出强化（P1 CLI）；下载文件名 Windows 保留名/非法字符清洗（P2）；引擎进程终止信号适配（P3）；`tzdata` 依赖（P8，Windows 上 zoneinfo 无系统库）；symlink→copy 降级（P15）；桌面三平台构建（P20）。
  4. **验证分期（CEO 审查共识）**：P1 交付本地等价验收（全量测试 + 平台卫生守卫测试），三平台机器验证为 **P2 入口条件**（远端建立后的首次三平台绿）；此前不得宣称 R1"已验证"。
  5. **引擎承诺分层**：llama.cpp 为唯一契约保证引擎（三平台）；vllm/sglang/MLX 为平台标记的附加项（Linux-only / Apple-Silicon-only），界面如实标注，维护面诚实。
- 理由：把"支持三平台"从口号变成 CI 门禁 + 差异清单，每个差异点有归属计划，避免平台问题在后期集中爆发。

### ADR-011 核心回路的进程监管：自建 vs 外部服务（2026-10-05）

- 要解决的问题：最小闭环可以（a）自建 llama.cpp 进程监管（启停/端口/状态机），或（b）不监管任何进程——用户外部自起引擎或指向任意 OpenAI 兼容端口，产品只做目录/激活/补全/记录。CEO 评审指出 (b) 以 ~20% 面积交付 ~80% 用户可见价值，且 schema 的 `server_mode=remote` 天然是逃生门。
- 选择：a)，但把 (b) 登记为 P4 网关计划的直接前身。理由：规格 §5.3 F03 把安装检查/启停/多实例/状态展示列为核心功能（P3 的验收面），最小闭环以真实产品命令兑现 F03 的最小子集是路线图排位裁决（2026-10-04）的直接内容；(b) 所需的"任意外部 OpenAI 兼容端点"按规格属 F04 云端服务商管理（P4），届时 `server_mode=remote` + 服务商登记自然兑现，`engines/openai_client.py` 即其客户端抽象的雏形。
- 后果：M0′ 阶段 `server_mode=remote` 保持诚实封锁（报错指明到达计划）；已知限制（孤儿进程随终端退出、Windows 硬杀、PID 身份启发式）分别由 TODO-017/ADR-010/TODO-016 承接。`completions` 表与 `instances` 表按 P6/P3 演进，属脚手架件（在位期间承担记录与诊断职责）。

## 3. 数据目录布局（独立设计，规格只要求持久化）

```
<IPO_DATA_DIR 或 ~/.ipostudio>/
  settings.toml        # 活动配置
  data/app.db          # SQLite 主库
  logs/                # 轮转日志
  downloads/           # .part + 边车 + 完成后的模型文件
  models/              # 默认模型目录之一（MODEL_DIRS 可加更多）
  media/{images,video,audio}/   # 生成素材
  backups/             # .ipobackup
  skills/              # 中央技能库默认位置之一
```

## 4. 错误与退出码约定

- CLI：成功 `0`；click 用法错误 `2`；运行失败 `1`（规格 9.11"失败非零退出"）。
- 网关 HTTP 状态码严格按规格 12.2 表；协议错误体形态按对应协议（OpenAI 风格 `error` 对象 / Anthropic 风格 / 校验 `detail` 数组）。
- 所有长任务状态机命名遵循规格 10.2 的枚举字面量（持久化字段用这些字面量，保证外部可观察行为一致）。

## 5. 测试架构

- 单元/集成：pytest；HTTP 契约用 `fastapi.testclient`（进程内）；下载续传行为用本地 `http.server` 模拟 206/200/中断（规格 T02–T04 的可自动化子集）。
- 引擎进程管理用假可执行脚本（打印预期 stdout 后 sleep）代替真实 llama.cpp，验证监管器逻辑，不依赖权重。
- 规格第 18 节测试场景编号在各子项目计划中逐一映射到具体测试；无法自动化（真实音频播放等）的场景在计划中标注手动验证步骤。

## 6. 与规格接口名称的对照（唯一强制命名）

| 规格名称 | 用途 | 落点 |
|---|---|---|
| `ipo` | CLI | console_script 入口 |
| `IPO_` | 环境变量前缀 | 配置加载器 |
| `ipo-tts/ipo-asr/ipo-image` | 能力别名 | 网关模型别名路由 |
| `.ipobackup` / `ipostudio.backup` | 备份 | vault 模块 |
| `ipostudio.kb` | 知识库交换格式 | kb 模块 |
| `x-typesafe-request-id`、`req_`+32hex | 判定请求头 | 网关 systemone 端点 |

其余一切内部命名（文件、类、函数、变量、错误类型、日志文案）为本项目独立命名。
