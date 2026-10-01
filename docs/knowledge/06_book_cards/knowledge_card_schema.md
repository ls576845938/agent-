# 逐书知识卡合同

## 目标

本合同用于证明“读到什么程度”，避免把目录扫描、关键词检索或章节摘要误报为全书精读。每本书必须有独立卡片、稳定来源标识、章节级来源位置、可信度、项目映射和公式复核状态。

## 覆盖等级

| 等级 | 名称 | 最低证据 | 不代表什么 |
|---|---|---|---|
| `L0` | 来源登记 | 文件名、SHA-256、格式、总行数 | 未阅读章节 |
| `L1` | 章节结构处理 | 全部章节边界、标题、行号、章节级概要和初步项目映射 | 未逐段核对全部论证 |
| `L2` | 章节语义精读 | 阅读章节正文，记录关键论证、条件、反例、限制和可执行项目映射 | 公式、表格和数字未必已回看原 PDF/EPUB |
| `L3` | 公式与证据复核 | 公式、表格、数字、脚注或 OCR 疑点已回看原始载体或权威来源，并记录复核结果 | 不等于本项目策略有效或 gate 通过 |

## 必填元数据

每张卡片必须包含：

- `book_id`
- `title`
- `authors`
- `source_file`
- `source_format`
- `source_sha256`
- `source_line_count`
- `card_status`
- `chapter_count`
- `chapter_index_coverage_pct`
- `chapter_l1_coverage_pct`
- `chapter_l2_coverage_pct`
- `formula_review_status`
- `last_reviewed_at`

## 章节字段

每章至少记录：

- 章节号和标题。
- 原文 Markdown 的起止行。
- 当前覆盖等级。
- 可信度：`high`、`medium` 或 `low`。
- 可信度理由。
- 章节核心命题。
- 对 BTC、美股或共享基础设施的项目映射。
- 不得直接采用的结论、参数或案例。
- 待复核公式、表格、数字或 OCR 疑点；没有则写 `无`。

## 可信度规则

- `high`：结构清晰的 EPUB 文本，已完成 `L2`；关键数字或公式已完成必要 `L3`。
- `medium`：完成 `L1`，或 PDF 文本已完成 `L2` 但表格、脚注仍可能错位。
- `low`：OCR、章节边界不稳定、公式损坏，或只完成关键词/目录检索。
- 可信度只描述知识提炼质量，不描述策略胜率、收益或 promotion readiness。

## 项目映射状态

每条项目映射必须标记以下之一：

- `existing_rule_confirmed`：当前项目已有对应规则，书籍用于解释或补充。
- `implementation_gap`：规范存在但实现或证据字段缺失。
- `candidate_design`：可进入预登记研究候选，默认 `research_only`。
- `concept_only`：只作为架构或研究背景，不建议立即实现。
- `rejected_for_now`：与当前数据、执行能力、安全边界或项目阶段不匹配。

## 公式复核状态

- `not_applicable`：本章无需要转入项目的公式、表格或数字。
- `identified_pending`：已定位候选，但尚未回看原始 PDF/EPUB 或权威来源。
- `verified_concept_only`：已复核，但仅用于解释，不进入生产计算。
- `verified_for_spec`：可用于研究规格，仍需数值测试和实现审查。
- `verified_for_implementation`：公式、单位、边界和数值测试均已通过；该状态不能由书籍卡单独授予。

## 完成判定

单本书只有同时满足以下条件才能标记 `complete`：

1. `chapter_index_coverage_pct = 100`。
2. `chapter_l2_coverage_pct = 100`。
3. 所有公式、表格、数字和 OCR 疑点均为已解决状态，或明确标记不适用。
4. 每章至少有一条项目映射或明确的“不适用”理由。
5. 来源 SHA-256 与当前只读书库一致。

全库只有 28 本书全部满足单书完成判定，且 Agent 手册中的每条跨书规则能反向链接到章节卡，才可声明“全部书籍处理完成”。
