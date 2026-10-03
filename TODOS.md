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
