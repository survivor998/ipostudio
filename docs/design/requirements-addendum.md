# 需求附录（用户指令，2026-10-03）

> 本附录记录用户在规格 v1.0 之外明确下达的两项需求指令。与规格正文冲突时，以本附录为准（用户为产品所有者）。各实现计划（`docs/superpowers/plans/`）必须将本附录与规格一并作为输入。

## R1 — Linux 与 Windows 全面支持

**指令原文**："确保 Linux 与 Windows 支持"。

- 三平台（macOS / Windows / Linux）均为一级支持目标；规格 §16 中"Windows/Linux 全面支持待确认"由本附录落实为**已确认支持**。
- 含义：
  1. 全部测试套件必须在 Windows 与 Linux 上通过（CI 三平台矩阵，见 P1 计划 Task 9）。
  2. 平台差异点必须显式处理：路径（`pathlib`）、编码（UTF-8 输出强化）、文件名合法性（Windows 保留名与非法字符，P2 下载器）、时区数据库（Windows 需 `tzdata` 包，P8 调度）、symlink（Windows 需开发者模式，P15 技能同步提供 copy 降级）、进程信号（P3 引擎监管用平台适配的终止方式）。
  3. 引擎可用性按平台如实标注（LLM 推理引擎矩阵见 `architecture.md` ADR-010）：llama.cpp 三平台；vllm/sglang 仅 Linux（Windows 经 WSL2 属用户自配，不承诺）；mlx 仅 Apple Silicon macOS。缺引擎时按规格 §5.3 模式"明确报告"，不得伪装可用。
  4. 桌面壳（P20）三平台构建。

## R2 — 更多文档格式（PowerPoint、Word、Excel 等）

**指令原文**："支持 More document formats (PowerPoint, Word, Excel, etc.) 更多文档格式"。

- 在规格 §7.3 文件类型表之上，追加办公文档类别：

  | 类别 | 扩展名 | 处理路径 |
  |---|---|---|
  | OOXML 文档 | `docx/pptx/xlsx` | 结构化解析（段落/表格/幻灯片/工作表值），进入知识库摄取、OCR 文档管线、会议纪要输入 |
  | ODF 文档 | `odt/odp/ods` | 同上 |
  | 传统二进制格式 | `doc/ppt/xls/rtf` | 不承诺原生解析；给出明确"请先转换为 docx/pptx/xlsx"提示（规格 §1.3 规则 3：预留能力明确标注） |

- 作用范围：知识库导入（F19/P13）、OCR 文档队列（F15/P11）、会议纪要小应用输入（F18/P12）。翻译（F16）仍为文本输入，不扩展。
- 大小限制沿用规格 §7.3"文档拖拽上传 100 MiB"。
- 实现策略见 `architecture.md` ADR-009（解析器注册表 + 归一化块模型）；具体库选型（python-docx / openpyxl / python-pptx，均 MIT）在 P11/P13 计划中经测试验证后锁定。
- 输出侧：知识库/OCR 结果仍以 Markdown 为主输出（规格 §8.2）；文档格式导出为后续可选需求，不在当前承诺内。

## 与规格的关系

- 规格正文其余部分继续有效。
- 本附录不改变规格 §20"未确定事项"清单的其余条目。
- 洁净室约束不变：格式解析依据公开的 OOXML（ECMA-376）/ODF（OASIS）标准与许可证兼容的第三方库，不参考任何第三方项目的解析实现。
