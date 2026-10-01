---
book_id: STR-09
title: The Trend Following Bible
authors: [Andrew Abraham]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\The Trend Following Bible - Andrew Abraham - 原文.md
source_format: pdf_text_original_pdf_cross_checked
source_sha256: e5dd2924b8a7ee84d71def1d54a0f7190bab6179b21111fd97b55cf403ae23ca
source_line_count: 7876
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\The Trend Following Bible How Professional Traders Compound Wealth and Manage Risk (Andrew Abraham(auth.)) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: 1a7290754ccb4f8961cad7ae2bd3c88a7a29fc37676313bfeeacf3aaa4e3b1db
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 10
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 10_ch01_ch10_items_verified_concept_only_from_original_pdf
last_reviewed_at: 2026-07-15
---

# STR-09：The Trend Following Bible

## 覆盖声明

本卡依据 PDF 目录与正文页首完成 10/10 章 `L2` 语义精读。当前源文件哈希未变，按 UTF-8 物理行复核为 7876 行；旧卡的 8084 行记录已纠正。全书10项风险、计划、breakout、retracement、ATR stop、position risk与journal条目已直接回看209页原PDF并关闭为`verified_concept_only`；作者收益、风险比例、主观判断和案例仍不构成项目证据。

## 全书项目映射

- `existing_rule_confirmed`：趋势策略必须接受多数小亏损、少数大赢家、whipsaw、回吐和长期回撤；风险与纪律不能由临场预测替代。
- `candidate_design`：breakout 与 retracement 是两个独立基线；入场、初始 stop、trailing stop、加仓和退出分别建模并统一进入 Forecast/Portfolio/Risk/Execution。
- `operational_insight`：交易计划、journal、人工跳过、异常处置和复盘应转为 versioned run/event evidence；PnL 仍只能由 fills、positions 与 cash ledger 推导。
- `risk_warning`：书中“每笔交易独立”和“每个信号都要做”不适用于相关资产、重叠信号或受限组合；只有通过数据、资格、容量和风险门的信号才可进入 TargetPosition。
- `rejected_for_now`：作者的 1%/5%/20% 风险比例、账户规模、ATR/天数参数、持仓上限、金字塔加仓和收益承诺均不得迁移为项目默认值。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Get a Savvy Start | `860-1536` | `L2/high` | 趋势交易不是轻松致富；启动前要明确资本、时间、风险承受、现实预期和计划。stop 不能保证成交，overnight gap 会突破预设损失；过早止盈又会破坏少数大赢家。 | `candidate_intake`：声明账户/资本约束、可承受损失、操作频率、gap/liquidity 假设、停止条件和人工参与边界。 | `FORM-STR09-CH01-001`：`verified_concept_only` |
| 2 Getting the Most Out of This Method | `1537-1968` | `L2/high` | 方法只能通过长系列交易评价，单笔、单月或单年不能证明成败；亏损、停滞和未来更大回撤是预期组成。理解、练习、记录和一致执行比复制参数重要。 | `existing_rule_confirmed`：按 fold/path/year/regime 报告分布与有效样本；书籍只形成候选规格，不能解锁 implementation 或 promotion。 | `FORM-STR09-CH02-001`：`verified_concept_only` |
| 3 Why Trend Following? | `1969-2555` | `L2/high` | 趋势跟随不预测顶底，依赖持续价格运动与凸性收益分布；无方向高波动期会产生连续 whipsaw。分散可能降低 ruin 风险，但正常相关不能代表压力相关。 | `candidate_design`：报告 payoff convexity、win/loss asymmetry、top-trade concentration、whipsaw cost、flat/high-vol regime 和有效 breadth。 | `FORM-STR09-CH03-001`：`verified_concept_only` |
| 4 How Successful Trend Followers Trade | `2556-3550` | `L2/high` | 专业管理人案例反复强调顺势、cut losses、let profits run、分散和保护权益，但幸存者、选择性展示、账户门槛与不同速度使案例不可直接比较。 | `evidence_boundary`：原则由 Forecast、Portfolio/Risk、Execution 与 audit 分层实现；管理人 track record 和作者筛选不能作为项目绩效。 | `FORM-STR09-CH04-001`：`verified_concept_only` |
| 5 Managing the Risks when Trend Following | `3551-4113` | `L2/high` | 单笔风险由账户风险预算和 entry-stop 距离共同决定；组合还受 sector、open-equity、margin、方向数量、杠杆、gap 与 drawdown 约束。提高单笔比例会非线性放大回撤。 | `existing_rule_confirmed`：Portfolio/Risk 重算 current/stress exposure、correlation groups、gap/liquidity、margin、drawdown escalation 和 hard caps；作者比例仅登记。 | `FORM-STR09-CH05-001`：`verified_concept_only` |
| 6 Your Complete Robust Trading Plan | `4114-4557` | `L2/high` | 完整计划应预先定义市场、趋势筛选、entry/exit、初始与 trailing stop、仓位、sector/open risk、异常和复盘。参数形式不是关键，风险合同和一致执行更重要；pyramiding 同时增加收益与回撤。 | `implementation_gap`：转为 versioned strategy spec、risk config、run manifest、override/incident/replay；缺失字段或超限 fail-closed，禁止人工清单替代机器合同。 | `FORM-STR09-CH06-001`：`verified_concept_only` |
| 7 Trend Breakouts | `4558-4917` | `L2/high` | breakout 在价格突破后入场，结合初始硬 stop 与 ATR trailing stop；大多数交易失败，连续小亏后可能出现少数大趋势。趋势退出会回吐浮盈，假突破和 gap 是核心成本。 | `candidate_design`：冻结 lookback、price field、close/intraday trigger、eligibility、next-bar lag、initial/trailing stop、expiry、gap 与全成本；“所有信号”仅指所有合格且过风险门信号。 | `FORM-STR09-CH07-001`：`verified_concept_only` |
| 8 Trend Retracements | `4918-5376` | `L2/high` | retracement 先确认高周期趋势，再等待低周期 pullback 和 stop entry；可能改善入场距离，也可能反复改价、错过不回撤趋势或引入多周期泄漏。硬 stop 后再切 ATR trailing stop。 | `candidate_design`：作为 breakout 的独立 challenger，定义 native clocks、as-of 对齐、depth、entry/expiry/stop、missed-trade 与 fill probability，并做同样本同成本比较。 | `FORM-STR09-CH08-001`：`verified_concept_only` |
| 9 The Trend Follower Mindset | `5377-6392` | `L2/high` | fear、greed、ego、近期盈亏和不现实的平滑净值预期会诱发规则破坏。作者称每笔交易统计独立，但相关市场、共同趋势、重叠持有和状态持续使该假设通常不成立。 | `operational_insight`：记录 override、skipped signal、manual edit、reason、approver 与影响；用 effective bet count 和相关组替代名义交易数，禁止 revenge/tinkering。 | `FORM-STR09-CH09-001`：`verified_concept_only` |
| 10 My Trading Journal | `6393-7527` | `L2/high` | 日记展示少量交易、规则调整、连续小损、稀有大赢家及 MF Global 式资金冻结/无法退出风险。自由文本案例可帮助复盘，但无法证明完整性、成交真实性或 PnL。 | `operational_insight`：结构化 journal 关联 run_id、signal/forecast、risk decision、order/fill、cash/position、exception、counterparty event 与 postmortem；账本仍是唯一 PnL 来源。 | `FORM-STR09-CH10-001`：`verified_concept_only` |

## 结论边界

Conclusion `7528-7588` 重申纪律、风险和长期过程；属于观点总结，不构成策略有效性、收益承诺或 promotion evidence。

## 对现有 BTC 与美股系统的启发

- BTC：24/7 市场仍存在交易所断连、周末流动性、跳价和无法撤单；stop 是 OrderIntent 条件，不是成交保证，必须通过 native L2/quote、partial fill、latency 和 service-loss replay。
- BTC：breakout 与 retracement 应共享同一趋势 Forecast 基线，分别测试 entry timing；多交易所或多合约信号不能冒充独立 breadth，需按共同 BTC 风险去重。
- 美股：overnight gap、停牌、涨跌幅异常、退市和开盘拍卖使 close signal→next-session fill 必须显式；行业集中与指数成分共同风险优先于名义持仓数。
- 共用：初始 stop、ATR trailing、pyramiding、sector cap 和 open-risk cap 属于不同合同层，均需版本化、压力测试和不可行状态；Strategy 不直接操作账户。
- 共用：journal 用于审计与复盘，不得替代 order/fill/position/cash ledger；券商、交易所或托管冻结默认 fail-closed。

## L3 原始 PDF 复核结论

| ID | 原始 PDF 位置 | 复核结果 | 项目边界 |
|---|---|---|---|
| `FORM-STR09-CH01-001` | 物理页 `24-38`；关键证据页 `32`；转换文 `860-1536` | 原 PDF 明确指出 stop 不能保证在limit move或overnight gap中退出，并把资本、风险承受与计划作为启动前提。 | `verified_concept_only`：确认执行风险方向，不采用账户规模、风险比例或主观适配结论。 |
| `FORM-STR09-CH02-001` | 物理页 `41-47`；关键证据页 `41`；转换文 `1537-1968` | 原 PDF 明确以long series of trades评价方法，并称单笔、单月或单年不重要，只要损失受控。 | `verified_concept_only`：只是评价期限原则，不能替代有效样本、OOS、成本和trial校正。 |
| `FORM-STR09-CH03-001` | 物理页 `51-61`；转换文 `1969-2555` | 原 PDF 反复描述小亏损、少数大赢家、whipsaw、分散和ruin风险，但未提供可迁移的完整试验总体。 | `verified_concept_only`：只支持完整分布与压力相关检查，历史结果和收益承诺不采用。 |
| `FORM-STR09-CH04-001` | 物理页 `65-93`；转换文 `2556-3550` | 原 PDF 确认管理人记录、回撤和速度差异均由作者选择性汇编；本轮仅验证书中载有这些陈述，未独立认证外部业绩。 | `verified_concept_only`：管理人案例只用于偏差审查，不作项目绩效、基准或参数证据。 |
| `FORM-STR09-CH05-001` | 物理页 `96-106`；关键证据页 `96/98`；转换文 `3551-4113` | 原 PDF 给出`R = e^(-2a/d)`并称其为risk of ruin，另推荐约1%单笔风险；正文同时承认仓位取决于账户、风险承受和经验，stop可被gap/limit突破，历史相关会变化。 | `verified_concept_only`：公式命名、定义与适用条件不足以形成项目风险模型；1%/2%/5%、账户和相关阈值全部拒绝迁移。 |
| `FORM-STR09-CH06-001` | 物理页 `109-117`；转换文 `4114-4557` | 原 PDF 确认完整计划应覆盖是否入场、趋势方法、风险、stop、退出和异常，并同时容纳breakout、retracement与pyramiding。 | `verified_concept_only`：只提取字段合同，不采用作者方法、过滤器或风险数字。 |
| `FORM-STR09-CH07-001` | 物理页 `118-130`；关键证据页 `125`；转换文 `4558-4917` | 原 PDF 的breakout示例使用X日突破、Y日hard stop、ATR trailing、1%/5%/20%与最多10个多头等占位或经验限制，并明确多数交易不工作。 | `verified_concept_only`：只作为可预注册baseline结构；X/Y、ATR和所有比例/数量均需独立研究且当前禁用。 |
| `FORM-STR09-CH08-001` | 物理页 `131-145`；关键证据页 `131`；转换文 `4918-5376` | 原 PDF 列出七条retracement规则，混合smoothed rate-of-change、breakout risk、MACD、合约美元风险、组合风险和core-equity限制。 | `verified_concept_only`：规则混合多个模型族和主观参数，只保留“高周期趋势+回撤入场”的challenger定义。 |
| `FORM-STR09-CH09-001` | 物理页 `148-168`；关键证据页 `157`；转换文 `5377-6392` | 原 PDF 明确声称每笔交易与下一笔统计独立，并用赌场类比支持长期执行纪律。 | `verified_concept_only`：独立性主张不适用于重叠持有、相关市场与状态持续；项目改用effective bet count和cluster exposure。 |
| `FORM-STR09-CH10-001` | 物理页 `172-200`，MF Global叙事另见物理页 `11`；转换文 `6393-7527` | 原 PDF 确认journal包含作者模型、交易、规则变更和有限案例；MF Global属于作者亲历叙事。自由文本无法证明完整交易分母、成交、现金流或PnL。 | `verified_concept_only`：journal只作审计入口，必须关联run/order/fill/position/cash ledger与incident，历史账户和业绩数字不采用。 |

## 完成边界

本书满足单书完成条件：10/10章 `L2`、10/10项风险/规则/案例已回看原PDF并关闭为`verified_concept_only`，所有章节有项目映射且Markdown来源SHA-256未变。该完成状态不证明趋势策略有效，不授权回测、参数迁移、holdout查看、promotion或任何broker/private/order/paper/live能力。
