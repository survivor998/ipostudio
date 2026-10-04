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

## TODO-006: 选定开源许可证（公开仓库前必须）——已解决
- **What:** 在 Apache-2.0（审查推荐）与 MIT 之间选定并提交 LICENSE 全文；同步 pyproject 元数据。
- **Resolution:** 2026-10-04 用户以 **MIT** 初始化公开仓库 https://github.com/survivor998/ipostudio （GitHub 初始提交自带 LICENSE），pyproject 已同步 `license = "MIT"`。此项即用户本人对"择日决定"的裁决，登记于此备查。
- **Context:** 用户 2026-10-03 裁决：仓库暂私有、暂不选许可证；2026-10-04 用户创建公开仓库并选择 MIT，推翻此前裁决。
- **Effort:** human: S / CC: S
- **Priority:** 已解决
- **Depends on:** —

## TODO-005: wheel 构建与仓库外安装冒烟（M0 期间）
- **What:** `python -m build` 产 wheel，在仓库外 venv 安装并跑 `ipo doctor --json`（验证 SQL 迁移资源打包）。
- **Why:** editable 安装掩盖打包缺陷（Eng Codex #11）；发布可信度前提。
- **Context:** 2026-10-03 Eng 审查延后至 M0（与分发渠道决策同期）。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** M0

## TODO-007: 配置保存锁的等待反馈与陈旧锁自愈
- **What:** `_advisory_lock` 成功创建锁文件后写入持有者 PID+获取时间戳；等待期间定期向 stderr 报告"正在等待配置锁（持有者 PID X，已等待 N 秒）"；超时错误中附带 PID 与锁龄；对持有者进程已死亡的陈旧锁（Windows 下 OpenProcess 探活，等效 POSIX `kill(pid, 0)`）提供自动清除或一步到位的清除指引。
- **Why:** 2026-10-03 实测：陈旧锁下 `save()` 静默阻塞 5.01 秒后直接抛错，错误只给锁路径，用户无法区分"另一进程正在保存"与"上次崩溃留下的死锁"；5 秒全程零反馈，用户会判定命令卡死而强杀进程（src/ipostudio/conf/loader.py:315-345）。
- **Pros:** 竞争场景从"静默挂 5 秒 + 手工删锁"变为"有进度反馈 + 可自愈"；PID/锁龄让支持与诊断可定位持有者。
- **Cons:** 锁文件从空文件变为有内容，需容忍读到半写状态（先 O_EXCL 创建再写入，读方对空文件回退为现状行为）；探活 API 需跨平台测试。
- **Context:** 2026-10-03 QA 测试（gstack-qa）发现：QA-A-04 证实 5 秒阻塞符合文档但属无反馈静默等待；本席复测阻塞 5.01s 且错误无持有者信息。业界惯例即锁文件写 PID+时间戳并探活回收陈旧锁（py-filelock 的 timeout/retry 语义：https://dokk.org/dokks/py-filelock/ ；py-lock-run 按 PID+时限回收孤儿锁文件：https://github.com/philiprehberger/py-lock-run ）。
- **Effort:** human: M / CC: M
- **Priority:** P3
- **Depends on:** 无

## TODO-008: CLI 冷启动优化：延迟导入 pydantic 配置链
- **What:** 将 `from ipostudio.conf.loader import ...`（连带 pydantic/tomli_w，cli/main.py:13）从模块顶层移入真正读配置的两个函数（`_check_config`、`guide`）；`version`/`help` 等不读配置的命令不再支付该导入成本。
- **Why:** `-X importtime` 实测：CLI 导入总开销约 117ms，其中 conf.loader→schema→pydantic 链约 74ms（63%）；`ipo version` 端到端约 200ms。CLI 是产品统一入口，脚本/状态栏会高频调用；冷盘 + 杀软扫描下 pydantic_core 原生模块的磁盘加载会进一步放大差距。
- **Pros:** 不读配置的命令导入成本立减约六成；与 Python 3.15 已批准的惰性导入（PEP 810）方向一致。
- **Cons:** 导入错误从启动期移到命令执行期（PEP 810 讨论中的已知代价）；需确认 doctor 的 `_contained` 包装覆盖延迟导入点，报错仍结构化。
- **Context:** 2026-10-03 QA 测试（gstack-qa）发现：QA-C 域零缺陷但未覆盖启动延迟维度；本席以 `-X importtime` 实测上述占比。最佳实践引用：PEP 810 惰性导入（已批准）：https://peps.python.org/pep-0810/ 。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** 无

## TODO-009: CLI 进程内调用泄漏 IPO_* 环境变量
- **What:** `ipo` 组回调把 --config/--data-dir 写入 `os.environ` 且从不还原（cli/main.py:72-75）；改为经 click `ctx.obj` 传递，或以 context manager 在调用结束后还原环境变量。
- **Why:** 一次性 CLI 进程中无害（刻意设计的 escape-hatch 语义），但 P2 起 GUI/嵌入方会在同一进程内反复调用 CLI：一次 `--data-dir` 调用即把 IPO_DATA_DIR 泄漏到整个进程生命周期，后续所有配置/数据库/日志路径解析被静默重定向到旧目录（QA-C-02；现有测试已被迫自建环境还原 fixture 规避）。
- **Pros:** 消除嵌入方的隐式进程级全局状态；测试不再需要环境快照 fixture。
- **Cons:** 需梳理 `conf/paths.py` 对环境变量的全部读取点，确保真正的 shell 环境变量优先级（escape-hatch parity）不受影响。
- **Context:** 2026-10-03 QA 测试（gstack-qa）发现：QA-C-02 记为 design note（"harmless for the one-shot CLI process... a leak for any embedder"）。click 官方建议组间共享状态走 `ctx.obj` 而非全局可变状态：https://click.palletsprojects.com/en/stable/complex/ 。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** 无；宜在 P2 GUI 进程内调用落地前完成

## TODO-010: migrate() 注册表复查与应用之间的 TOCTOU 窗口
- **What:** 并发迁移失败方在 UNIQUE 约束冲突（`_migrations.name`）上应识别为"他方已注册"并干净跳过，而非抛 `MigrationFailure`；即把第二次 `executescript` 内的注册冲突折叠回正常路径。
- **Why:** 2026-10-03 QA 测试（gstack-qa）日志分析（H-03）确认：`BEGIN IMMEDIATE` 后的注册表复查在第二个 `executescript`（自带隐式 COMMIT）之外，写锁在复查与应用之间短暂释放，微秒级窗口内并发方会得到 spurious `MigrationFailure` 而非干净跳过。后果安全（事务已回滚、重试即成功），但违背"并发启动序列化"的文档承诺。依据：docs.python.org sqlite3 executescript 隐式 COMMIT 语义（https://docs.python.org/3/library/sqlite3.html#sqlite3.Cursor.executescript ）。
- **Pros:** 并发冷启动从"偶发报错（可重试）"变为完全静默；行为与 migrate() docstring 的 race-safe 声明一致。
- **Cons:** 窗口为微秒级、实测难触发；新增一个 UNIQUE 冲突分支需要谨慎限定（仅 `_migrations.name` 冲突才算并发注册）。
- **Context:** 2026-10-03 QA 测试（gstack-qa）发现（分析报告 H-03，确定性重放探针证实机制）。触发概率未测量；P2 多入口并发落地前完成即可。
- **Effort:** human: S / CC: S
- **Priority:** P2
- **Depends on:** P1 Task 6

## TODO-011: save() 原样回写磁盘上未经校验的已知键值
- **What:** 决策并实现：save() 合并时是否对磁盘侧的已知键值先过一遍 schema 校验（拒绝或修复非法值），而非原样回写。
- **Why:** 2026-10-03 QA 测试（gstack-qa）日志分析（H-07）确认的行为：手写 settings.toml 中一个非法已知键若在加载时被 IPO_ 环境覆盖遮蔽（加载成功），save() 会把磁盘上的非法值原样合并回写；下次无该环境变量启动即 ConfigError，等于把一次性错误固化为持久故障。
- **Pros:** 消除"环境变量遮蔽下保存一次、下次裸启动即坏"的陷阱。
- **Cons:** 校验-拒绝语义与"脏键合并保留未知键"的宽容姿态存在张力：拒绝可能阻塞用户修复配置的唯一路径（用户只能改文件，而改文件正是坏了的东西）。需产品决策：拒绝、修复为默认值、或保留现状并写入文档。
- **Context:** 2026-10-03 QA 测试（gstack-qa）发现（分析报告 H-07，探针证实）。属设计权衡，非缺陷修复；与 unknown-key 拒绝策略（spec §11.2）一并考虑。
- **Effort:** human: S / CC: S
- **Priority:** P3
- **Depends on:** 产品决策
