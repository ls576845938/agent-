# 本地量化书库 Agent 入口

## 目的

本目录把外层 Obsidian 书库中的量化、统计、执行和工程书籍转化为项目 Agent 可执行的规则、检查项和来源映射。

本目录不是书籍原文副本，也不是 promotion evidence。Agent 必须先遵守仓库治理规则和对应模块规范，再按任务查阅书籍卡片。

## 权威顺序

发生冲突时，按以下顺序处理：

1. `AGENTS.md`、`00_codex_rules/` 和当前角色 playbook。
2. 当前 HEAD 的模块契约、测试、artifact、manifest、ledger 和 gate 报告。
3. `01_data_layer/` 至 `10_btc_trend_strategy_playbook/` 的项目规范。
4. 本目录中的书籍提炼规则。
5. 外层 Obsidian 的书籍原文、综合总结和案例。

书中观点只能生成研究假设、设计约束或验证计划，不能直接解除 `blocked`、`research_only` 或 `fail_closed`。

## 主要入口

- `local_quant_book_inventory.md`：当前 28 本独立 Markdown 书籍清单、来源质量和任务用途。
- `knowledge_card_schema.md`：逐书卡片字段、覆盖等级、可信度和完成判定。
- `coverage_manifest.md`：28 本书的真实覆盖率；区分章节索引、章节摘要、全文精读和公式复核。
- `formula_review_queue.md`：不得直接进入实现的公式、表格、数字和 OCR 疑点队列。
- `cards/`：每本书一张标准卡片，章节级记录来源行号、可信度、项目映射和待复核项。
- `agent_book_knowledge_playbook.md`：跨书籍提炼出的 Agent 工作规则、交付模板和禁止解释。

## 角色阅读路由

| 角色 | 默认阅读 | 按任务追加 |
|---|---|---|
| `architect` | 本文件、`agent_book_knowledge_playbook.md`、工程可靠性相关书目 | 数据、执行或研究模块对应书目 |
| `data_steward` | DDIA、Database Internals、金融时间序列 | PIT、schema、lineage、freshness、回放相关章节 |
| `researcher` | Systematic Trading、Evidence-Based Technical Analysis、AFML | 趋势、动量、因子、时间序列或蒙特卡洛相关书目 |
| `super_developer` | Architecture Patterns with Python、A Philosophy of Software Design、Legacy Code | 当前业务模块对应的领域书目 |
| `btc_developer` | Trading and Exchanges、Algorithmic and High-Frequency Trading、Systematic Trading | 期货、趋势、funding、mark/index、清算和执行书目 |

## 使用流程

1. 先确定任务属于 Data、Research、Backtest、Portfolio/Risk、Execution、Ledger、Monitoring/Replay 或 Gate。
2. 先读对应项目规范，再从清单选 2 至 4 本最相关来源。
3. 先看 `coverage_manifest.md`；只有达到所需覆盖等级的卡片才能支撑相应结论。
4. 把书中概念转成项目字段、接口、测试或 blocker，不直接照搬策略参数。
5. 明确来源质量；OCR、公式、表格和数字必须进入 `formula_review_queue.md` 并回看原始 PDF/EPUB。
6. 研究类结论默认标记 `concept_only` 或 `research_only`，直到当前 HEAD 证据满足项目 gate。
7. 交付时记录 `source_book_ids`、章节位置、覆盖等级、采用规则、未采用原因、验证命令和剩余风险。

## 来源边界

- 当前本地书库根目录：`D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD`。
- 外层 Obsidian 仅作为只读知识源；代码和治理根目录仍是 `agent-`。
- 不大段复制商业书原文；只保留必要的概念名称、项目化释义和来源文件名。
- 书籍不会提供当前市场状态、当前 gate 状态或当前 broker/exchange 事实，这些必须从本地最新证据读取。

## 更新规则

新增或替换书籍后：

1. 重新扫描 `书籍原文MD/`，区分独立书籍、重复转换和质量报告。
2. 更新 `local_quant_book_inventory.md`，注明格式和 OCR 风险。
3. 只有当新知识改变项目规则时，才修改模块规范；否则只更新书籍卡片。
4. 不用读书结论替代契约测试、数据验证、回测证据或 promotion gate。
5. 禁止把 `L0` 文件扫描或 `L1` 章节摘要描述成逐字读完全书。
