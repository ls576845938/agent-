---
book_id: STR-08
title: Quantitative Momentum
authors: [Wesley Gray, Jack Vogel]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Quantitative Momentum - Gray and Vogel - 原文.md
source_format: pdf_text_original_pdf_cross_checked
source_sha256: cef39d69e5e47419e4268bf84cbf008fcbbebdbeccde1a542f5d3e24f3e908fb
source_line_count: 9497
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\Quantitative Momentum A Practitioner’s Guide to Building a Momentum-Based Stock Selection System (Wesley R. Gray, Jack R. Vogel) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: 8ad3444f513927f9296aec9358ff49329705dde3857e05acc5e86614391f7245
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 9
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 11_ch01_ch09_appendix_a_b_items_verified_concept_only_from_original_pdf
last_reviewed_at: 2026-07-15
---

# STR-08：Quantitative Momentum

## 覆盖声明

本卡依据 PDF 目录和正文页首完成 9/9 章 `L2` 语义精读。Appendix A 的替代动量比较和 Appendix B 的指标定义不计入章节数。当前源文件哈希未变，按 UTF-8 物理行复核为 9497 行；旧卡的 9702 行记录已纠正。9章及Appendix A/B共11项已直接回看206页原PDF并关闭为`verified_concept_only`；历史组合、费用假设、股票universe、因子回归和指标不得作为项目证据。

## 全书项目映射

- `candidate_design`：美股横截面动量采用“过去收益水平 + 路径连续性”两阶段 challenger，并与 value、quality、fundamental momentum 和 time-series overlay 分开消融。
- `existing_rule_confirmed`：动量不是 growth 标签；必须保存 PIT universe、delisting、corporate action、signal/execute lag、成本、容量以及行业/市值/因子暴露。
- `risk_warning`：集中持仓、频繁调仓、长时间相对落后、动量 crash 和季节性交易都是策略合同的一部分；不能删除不利月份或只展示长期 CAGR。
- `evidence_boundary`：书中 1927—2014 等历史样本只用于提出问题；任何参数、持仓数、权重、费用、季节调仓、trend overlay 与绩效数字都保持 `research_only`。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Less Religion; More Reason | `307-761` | `L2/high` | 技术与基本面不应宗派化；价格动量、趋势、value 和 quality 都只能通过可证伪证据比较。横截面动量选择相对强者，时间序列动量判断单资产方向，组合语义不同。 | `existing_rule_confirmed`：使用不同 Signal/Forecast schema、基准和消融；投资名人、历史叙事或“技术/基本面”标签均不提高证据等级。 | `FORM-STR08-CH01-001`：`verified_concept_only` |
| 2 Why Can Active Investment Strategies Work? | `762-2092` | `L2/high` | 可持续主动收益需要可解释的错定价机制与套利限制；投资者必须承受容量、职业风险、基准落后和拥挤，否则异常可能无法被实际持有。风险补偿与误定价是竞争解释。 | `candidate_intake`：登记 who-pays、behavior/friction proxy、limits-to-arbitrage、capacity、holding pain、decay 与 falsification，不把高回报自动称为 alpha。 | `FORM-STR08-CH02-001`：`verified_concept_only` |
| 3 Momentum Investing Is Not Growth Investing | `2093-3051` | `L2/high` | 价格动量以过去相对收益排序，不等于高增长公司；growth、value、size、quality、sector 与市场暴露可能污染组合归因，行为解释也不是因果证明。 | `implementation_gap`：报告 factor/sector/size beta、long-only 与 long-short 差异、增量 IC/return 和匹配暴露基准，防止把 growth beta 误报为动量。 | `FORM-STR08-CH03-001`：`verified_concept_only` |
| 4 Why All Value Investors Need Momentum | `3052-3812` | `L2/high` | value 与 momentum 可能在不同状态失效且相关较低，组合可分散相对表现路径；但日本、危机和长期落后案例说明 stand-alone 及组合结论依赖样本与视角。 | `candidate_design`：value+momentum 比较 equal、risk-budgeted 和 constrained 组合，报告 stress correlation、active drawdown、tracking error 与边际信息，不机械 50/50。 | `FORM-STR08-CH04-001`：`verified_concept_only` |
| 5 The Basics of Building a Momentum Strategy | `3813-4473` | `L2/high` | generic momentum 通常按 formation return 排序并跳过最近月；短期反转、中期动量、持仓数、持有期、重叠组合、再平衡与权重会共同改变收益、换手和容量。更集中、更频繁的表观优势伴随更高实施成本。 | `candidate_design`：冻结 formation/skip/holding/rebalance、PIT universe、ranking tie-break、N、overlap、weight、delisting、signal/execute lag；成本和容量先于收益比较。 | `FORM-STR08-CH05-001`：`verified_concept_only` |
| 6 Maximizing Momentum: The Path Matters | `4474-5404` | `L2/high` | 相同累计收益可来自连续信息扩散或少数跳跃；frog-in-the-pan/信息离散度试图区分平滑与 jumpy 路径。路径质量可能筛除 lottery-like winner，但增加特征、阈值和解释自由度。 | `candidate_design`：路径指标作为独立 challenger，保存 daily sign、missing/session、jump/volatility 定义和阈值；用增量 OOS IC、turnover、capacity 与 crash-state 消融判定。 | `FORM-STR08-CH06-001`：`verified_concept_only` |
| 7 Momentum Investors Need to Know Their Seasons | `5405-6102` | `L2/high` | January、季末 window dressing、税损卖出和制度激励可能改变动量收益；作者据此设计 smart rebalance，但季节效应会衰减且存在数据挖掘风险。 | `risk_warning`：calendar effect 绑定交易所日历、税制、样本年代和预先定义月份；不得在 holdout 挑月份，必须做制度前后、placebo 月份和多重检验。 | `FORM-STR08-CH07-001`：`verified_concept_only` |
| 8 Quantitative Momentum Beats the Market | `6103-7218` | `L2/high` | quantitative momentum 将 generic 12-minus-1 排名与路径质量结合，并展示净费用组合、滚动 5/10 年、因子回归和 delisting 处理。标题中的“beats”来自特定历史 universe、成本与规则，不具项目外推力。 | `evidence_boundary`：按当前 PIT 美股数据重建 investable benchmark、gross/net ledger、rolling/fold/regime 分布、factor alpha、capacity 与不确定性；不复用书中回报。 | `FORM-STR08-CH08-001`：`verified_concept_only` |
| 9 Making Momentum Work in Practice | `7219-7716` | `L2/high` | value+momentum、trend overlay 和 core-satellite 改变绝对/相对回撤、跟踪误差与收益；趋势过滤降低历史尾部但牺牲部分收益，core-satellite 缓和但不消除相对痛苦。 | `candidate_design`：Portfolio/Risk 比较 standalone、组合、overlay 和 passive/core 基线；保持 signal 与 allocation 解耦，报告 active DD、TuW、turnover、stress correlation 与 forecast loss。 | `FORM-STR08-CH09-001`：`verified_concept_only` |

## 附录边界

- Appendix A `7717-8821`：fundamental momentum、earnings surprise/announcement return、momentum crash、52-week high、absolute strength、volatility constraint 和 time-series overlay 等替代方案；每项是独立模型族，不得按附录最好结果筛选。`FORM-STR08-APP-A-001`：`verified_concept_only`。
- Appendix B `8822-8855`：CAGR、standard/downside deviation、Sharpe、Sortino 与 worst drawdown 的简表定义；需对齐项目 return clock、risk-free/MAR、serial dependence、ledger 和 drawdown duration 口径。`FORM-STR08-APP-B-001`：`verified_concept_only`。

## 对现有 BTC 与美股系统的启发

- 美股：在现有横截面因子层增加 path-quality challenger 前，先固定 12-minus-1 generic baseline；路径过滤必须证明净成本后的边际价值，而不是替换基线后只看更好 CAGR。
- 美股：universe、持仓数、持有期、重叠组合与权重是联合设计变量；集中与高频不能脱离 ADV、impact、capacity、行业集中和退市收益评估。
- BTC：单标的路径连续性可作为 time-series forecast 质量特征，但不能照搬股票横截面 frog-in-the-pan 阈值；需单独处理 24/7 session、交易所跳价和事件性流动性。
- 共用：季节、路径、trend overlay 和 value+momentum 都是独立 trial family；保持 locked holdout 未查看，并用 purged/embargoed WF 与完整 trial ledger。
- 共用：Strategy 只输出 Forecast；组合、trend risk filter、core-satellite 和风险预算由 Portfolio/Risk 处理，任何成本或数据异常 fail-closed。

## L3 原始 PDF 复核结论

| ID | 原始 PDF 位置 | 复核结果 | 项目边界 |
|---|---|---|---|
| `FORM-STR08-CH01-001` | 物理页 `19-31`；关键证据页 `28`；转换文 `307-761` | 原PDF明确定义time-series momentum为相对自身过去收益，cross-sectional momentum为相对其他股票表现。 | `verified_concept_only`：只确认信号分类；12个月示例、long/short动作和流派叙事不得迁移。 |
| `FORM-STR08-CH02-001` | 物理页 `32-59`；转换文 `762-2092` | sustainable active框架把mispricing与limits-to-arbitrage、职业/基准风险和持有痛苦联合解释。 | `verified_concept_only`：是候选机制框架，不证明错定价、因果或未来alpha。 |
| `FORM-STR08-CH03-001` | 物理页 `61-79`；关键证据页 `61-63`；转换文 `2093-3051` | 原PDF将momentum定义为价格相对收益排序，与price-to-fundamental的growth区分，并使用12个月跳过最近月、CRSP/delisting和long-only/long-short历史比较。 | `verified_concept_only`：仅确认定义与归因问题；历史样本、回归和结果未独立认证。 |
| `FORM-STR08-CH04-001` | 物理页 `80-93`；关键证据页 `82-88`；转换文 `3052-3812` | 原PDF展示1982—2014日本long-only/long-short、value/momentum和相关矩阵，并机械构造等权组合。 | `verified_concept_only`：数字只证明书中报告；不采用50/50、历史相关、CAGR/Sharpe或“日本有效”结论。 |
| `FORM-STR08-CH05-001` | 物理页 `95-109`；关键证据页 `97-99`；转换文 `3813-4473` | 原PDF将generic momentum设为含分红的过去12个月复合收益，并讨论跳过最近月、lookback、持仓数、持有期、再平衡、权重和交易成本。 | `verified_concept_only`：只形成完整策略规格字段；12-minus-1、top decile、持仓数和成本假设均禁用。 |
| `FORM-STR08-CH06-001` | 物理页 `111-123`；关键证据页 `119/121`；转换文 `4474-5404` | 原PDF确认`ID/FIP = sign(Past return) × (%negative − %positive)`，以过去252交易日正负日比例刻画路径，并报告1927—2007历史分组结果。 | `verified_concept_only`：公式定义已核但阈值、252日和历史绩效不迁移；必须作为独立trial验证边际OOS价值。 |
| `FORM-STR08-CH07-001` | 物理页 `125-137`；转换文 `5405-6102` | 原PDF讨论window dressing、tax-loss selling、January/quarter-end效应及smart rebalance，同时承认相关证据存在分歧和粗糙代理。 | `verified_concept_only`：只生成日历候选；月份、税制、显著性和调仓规则必须按当前制度预注册并做placebo/多重检验。 |
| `FORM-STR08-CH08-001` | 物理页 `138-161`；关键证据页 `138-141`；转换文 `6103-7218` | 原PDF把12-minus-1、FIP、季节筛选、1000股universe、top10%/top-half及交易成本串成历史算法，并报告费用、因子与绩效。 | `verified_concept_only`：只核实书中规格；universe、阈值、成本和收益必须用当前PIT数据独立重建。 |
| `FORM-STR08-CH09-001` | 物理页 `162-169`；关键证据页 `167`；转换文 `7219-7716` | 原PDF使用12月S&P500总回报均线作为trend overlay并展示value+momentum/core-satellite历史结果，明确overlay牺牲部分收益且core-satellite不能消除relative pain。 | `verified_concept_only`：仅保留组合候选与trade-off；均线、权重、T-bill和历史回撤数字禁用。 |
| `FORM-STR08-APP-A-001` | 物理页 `173-192`；转换文 `7717-8821` | 原PDF列出fundamental momentum、52-week high、absolute strength、volatility constraint与time-series overlay等替代模型。 | `verified_concept_only`：只建立独立trial family；未回溯各原论文，不按附录结果筛选。 |
| `FORM-STR08-APP-B-001` | 物理页 `193`；转换文 `8822-8855` | 原PDF确认CAGR、月度standard/downside deviation、Sharpe、Sortino(MAR=5%)、worst drawdown和月收益的简表定义。 | `verified_concept_only`：定义过于简化且缺serial dependence、ledger、cash flow、drawdown duration等条件，不作为项目指标实现规格。 |

## 完成边界

本书满足单书完成条件：9/9章 `L2`，9章及Appendix A/B共11项均回看原PDF并关闭为`verified_concept_only`，所有章节有项目映射且Markdown来源SHA-256未变。该完成状态不证明动量策略有效，不授权回测、参数迁移、holdout查看、promotion或任何broker/private/order/paper/live能力。
