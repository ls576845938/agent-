---
book_id: STR-01
title: Systematic Trading
authors: [Robert Carver]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Systematic Trading - Robert Carver - 原文.md
source_format: epub_text_original_epub_cross_checked
source_sha256: 904d01287eff01c5232d93fe260c4fa74b7286ab7b9299edba1b558d24deaf8c
source_line_count: 19012
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\Systematic Trading - A unique new method for designing trading and investing systems (Robert Carver) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_source_sha256: 8d26a3fb528bc38d23b6d61c22193502f41e77f0854e62c3c42dba512fad7356
original_source_chapter_files: 15
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 15
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
appendix_review_coverage_pct: 100
formula_review_status: 75_ch01_ch15_items_verified_concept_only
last_reviewed_at: 2026-07-15
---

# STR-01：Systematic Trading

## 覆盖声明

本卡依据 EPUB 正文章节标题精读 15/15 章，并补读正文公式引用所依赖的附录 B—D，完成 `L2` 语义复核。原卡把 Epilogue、Glossary 和附录误并入第15章，本轮已把第15章正文边界修正为 `15060-16646`；附录单列覆盖。现已直接核对原 EPUB 的 OPF spine、15 个 chapter XHTML 和 Appendix B—D 的 Heading-3/4/5 结构，将 forecast scaling、拟合统计、组合权重、volatility target、position sizing、diversification multiplier、成本标准化和示例参数共 75 项关闭为 `verified_concept_only`。该状态只确认概念、公式主题和迁移限制，不认证书中历史参数、表格、日记或当前实现。

## L3 原始 EPUB 复核结论

| 范围 | 原 EPUB 文件 | 已核方法簇 | 队列状态 |
|---|---|---|---|
| Ch01—04 | `OEBPS/Autopilot_ebook-8.xhtml`、`-9.xhtml`、`-11.xhtml`、`-12.xhtml` | behavioral bias/override、rule mechanism/style/Sharpe、fitting/multiple tests/pooling、optimisation/handcrafting/Sharpe adjustment | 20 项均为 `verified_concept_only` |
| Ch05—08 | `OEBPS/Autopilot_ebook-14.xhtml`—`-17.xhtml` | modular framework、instrument eligibility、forecast scale/EWMAC/carry、forecast weights/diversification/cap | 20 项均为 `verified_concept_only` |
| Ch09—12 | `OEBPS/Autopilot_ebook-18.xhtml`—`-21.xhtml` | volatility target/capital、position unit chain、instrument portfolio/IDM、cost/turnover/capacity/speed | 20 项均为 `verified_concept_only` |
| Ch13—15 | `OEBPS/Autopilot_ebook-23.xhtml`—`-25.xhtml` | semi-automatic、asset allocation、staunch-system workflow与历史 diary | 15 项均为 `verified_concept_only` |
| Appendix B | `OEBPS/Autopilot_ebook-30.xhtml` | A/B rule、EWMAC、carry、forecast scalar与turnover | 支撑 Ch07、Ch12、Ch15 概念核验；参数禁用 |
| Appendix C | `OEBPS/Autopilot_ebook-31.xhtml` | bootstrap、return blocks、repeats、rule-of-thumb correlations | 支撑 Ch03—04 概念核验；历史经验矩阵禁用 |
| Appendix D | `OEBPS/Autopilot_ebook-32.xhtml` | forecast rescale、FDM/IDM、historic volatility | 支撑 Ch08—11 概念核验；固定常数禁用 |

## 全书项目映射

- `existing_rule_confirmed`：Signal → Forecast → TargetPosition → Portfolio/Risk → OrderIntent 的框架与本书核心思路一致。
- `implementation_gap`：BTC forecast 的 expected return/confidence 标定、美股 active portfolio 指标和成本后“不交易”决策仍需更完整证据。
- `rejected_for_now`：书中 forecast scale、cap、vol target 和投资者类型示例不是本项目固定参数。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 The Flawed Human Brain | `916-1260` | `L2/high` | 系统化只能约束决策流程，不能消除设计者的损失厌恶、过度自信、选择性解释和停用系统冲动。 | `existing_rule_confirmed`：参数、人工override、暂停/恢复和紧急例外必须预先定义并进入审计。 | Ch01历史交易与频率数字待L3 |
| 2 Systematic Trading Rules | `1261-2205` | `L2/high` | 规则需要可证伪机制、客观输入、跨市场适用边界和成本后收益来源；高Sharpe可能来自杠杆、负偏或过快交易。 | `candidate_design`：候选登记edge type、mechanism、falsifier、skew、crowding、funding和capacity。 | Ch02 Sharpe/杠杆/成本表待L3 |
| 3 Fitting | `2206-2985` | `L2/high` | fitting必须阻断时间机器、控制候选数、保留完整搜索流程、按时间OOS并修正多重比较；pooling只在语义和PIT一致时增加证据。 | `existing_rule_confirmed`：trial ledger、nested walk-forward、holdout lock和统一成本；书中T-test年数表不作门槛。 | Ch03模拟表与统计解释待L3 |
| 4 Portfolio Allocation | `2986-4580` | `L2/high` | 均值和相关估计误差会使单期优化极端化；bootstrap、收缩、约束和简单基线需比较稳定性而非只比in-sample Sharpe。 | `candidate_design`：与equal/inverse-vol/risk-budget/shrinkage对照，报告权重漂移、集中度和压力相关。 | Ch04 handcrafting/Sharpe调整待L3 |
| 5 Framework Overview | `4581-4811` | `L2/high` | trading rule、forecast、risk target、position sizing和portfolio必须通过单位明确的接口解耦；固定“每笔资本百分比”混淆风险层级。 | `existing_rule_confirmed`：Signal→Forecast→TargetPosition→Portfolio/Risk→OrderIntent，执行适配器隔离。 | 示例3%/固定合约数拒绝迁移 |
| 6 Instruments | `4812-5075` | `L2/high` | universe不是代码列表，而是数据许可、PIT可得性、最小单位、自然波动、相关、成本、流动性、偏度、venue和工具类型合同。 | `candidate_design`：BTC/美股universe逐项保存eligibility、min lot、funding/borrow、venue和压力退出条件。 | 历史合约规模和venue结论待L3 |
| 7 Forecasts | `5076-5603` | `L2/high` | Forecast应表达统一风险尺度上的方向与强度，并记录horizon、expiry和calibration；规则输出不能直接等同仓位。 | `implementation_gap`：统一forecast unit、sign、scale、confidence、expiry、quality evidence和no-forecast语义。 | Ch07尺度、cap、EWMAC/carry待L3 |
| 8 Combined Forecasts | `5604-6146` | `L2/high` | 组合forecast需要正权重、相关矩阵、尺度复原和cap；diversification multiplier依赖相关估计，不能把相关信号当独立breadth。 | `candidate_design`：保存raw forecasts、weights、covariance、effective breadth、multiplier与cap loss。 | Ch08矩阵公式与固定10/20/2.5待L3 |
| 9 Volatility Targeting | `6147-7154` | `L2/high` | 风险目标是长期可预测波动预算，不是最大损失；必须联合资本、杠杆可实现性、尾部/偏度、margin和估计误差，亏损后按当前资本缩减。 | `existing_rule_confirmed`：风险预算先于收益，目标由mandate和压力证据决定，不按回测最优或Kelly表直接设置。 | Ch09年化、Kelly和损失表待L3 |
| 10 Position Sizing | `7155-7547` | `L2/high` | 仓位链必须显式保留block value、价格波动、账户币种FX、instrument value volatility、vol scalar和forecast尺度，最后才round。 | `implementation_gap`：TargetPosition同时报告units、notional、currency、multiplier、vol forecast、lot rounding和constraint loss。 | Ch10仓位链与EWMA待L3 |
| 11 Portfolios | `7548-8270` | `L2/high` | subsystem仓位经instrument weights和portfolio diversification后形成组合目标；相关危机上升、最小单位和position inertia会使实现偏离连续目标。 | `candidate_design`：报告边际/集中风险、stress correlation、target-vs-rounded差异和no-trade band成本收益。 | Ch11相关折扣、乘数、10% inertia待L3 |
| 12 Speed and Size | `8271-9941` | `L2/high` | 可交易性由spread/fee/impact/roll/funding等成本、标准化turnover、容量和最小block共同决定；执行成本不能只按半点差。 | `implementation_gap`：expected alpha increment与fee/spread/slippage/impact/delay/funding比较，成本和容量按当前市场实测。 | Ch12标准成本、speed limit、四block待L3 |
| 13 Semi-automatic Trader | `9942-11591` | `L2/high` | 人工forecast仍需预定义尺度、风险预算、并发bet上限、stop/exit、position sizing、日志和每日对账；人工判断不豁免订单链。 | `concept_only`：任何人工信号也必须经过Portfolio/Risk、OMS、fills/ledger和审计。 | 个人spread-bet流程与数字不采用 |
| 14 Asset Allocating Investor | `11592-15059` | `L2/high` | 无杠杆低频配置受自然波动、现金、mandate约束、税费和再平衡频率共同限制；观点应转成小幅、可审计权重偏离。 | `candidate_design`：美股ETF研究预声明universe、PIT成分、rebalance calendar、cash/defensive asset和tracking error。 | ETF/相关/7.5%示例待L3 |
| 15 Staunch Systems Trader | `15060-16646` | `L2/high` | 完整系统把instrument eligibility、rule set、forecast weights、成本、风险目标、仓位、组合和daily process连成确定性证据链。 | `existing_rule_confirmed`：共享策略逻辑、版本化输入、确定性TargetPosition、受控执行和fail-closed promotion。 | futures/参数/日记均为历史示例 |

## 附录覆盖

| 附录 | 原文位置 | 等级/可信度 | 覆盖结论 | 项目边界 |
|---|---|---|---|---|
| B Trading Rules | `17637-18173` | `L2/high` | 已复核A/B、EWMAC、carry定义、缩放、cap和跨资产carry口径。 | 仅登记公式；参数和Panama连续合约方法不迁移。 |
| C Portfolio Optimisation | `18174-18861` | `L2/high` | 已复核bootstrap步骤、block依赖、经验相关矩阵和其时间不稳定性。 | rule-of-thumb相关不能替代当前PIT/OOS估计与压力矩阵。 |
| D Framework Details | `18862-18972` | `L2/high` | 已复核forecast rescale、`1/sqrt(wΣwᵀ)`乘数、SMA/EWMA波动计算。 | 公式待L3，固定10、25/36日和负相关floor不作默认。 |

## L2 逐章项目结论

1. **研究治理（Ch01—04）**：系统化的价值是把行为偏差、搜索空间和估计不确定性暴露出来；机制叙事、回测Sharpe和优化器输出都不能绕过trial ledger、PIT、nested OOS、holdout隔离与稳健基线。
2. **领域接口（Ch05—08）**：rule只产生forecast，forecast经明确单位、期限、缩放、权重和相关性组合；风险层和组合层决定仓位，strategy不得直接调用broker或输出订单。
3. **风险与仓位（Ch09—11）**：volatility target、capital、skew/tail、margin、block value、FX、instrument volatility、forecast、weights和diversification构成一条带单位的可审计链；连续目标与可交易整数目标必须同时保存。
4. **成本与容量（Ch12）**：成本证据至少包含fee、spread、slippage、impact、delay、funding/borrow、roll和tax scope；turnover、position inertia、min lot和capacity共同决定no-trade或降速，不以书中固定speed limit裁决。
5. **运行流程（Ch13—15）**：人工、静态配置和全自动策略都共享风险、仓位、组合、执行、fills/ledger和审计合同；差别只在forecast来源、rebalance频率和执行适配器，不在安全边界。
6. **附录公式**：EWMAC、carry、forecast scale、bootstrap、correlation、diversification和EWMA已完成原 EPUB 概念核验；实现仍必须重建单位、时间索引、PIT、成本和当前市场证据。

## 适用限制

- 本书使用2014—2015附近的市场、费用、合约、税制和产品示例；所有数值与instrument清单均已过时，只作历史说明。
- 固定forecast平均绝对值10、cap 20、multiplier cap 2.5、256交易日、25/36日波动窗口、10% inertia、四block、0.13/0.08 SR成本上限和Half-Kelly折扣均不得成为项目默认值。
- 书中Sharpe、T-test、bootstrap和rule-of-thumb相关未覆盖本项目全部多重比较、非独立收益、结构断点、尾部、资金费率、借券、永续合约和市场冲击风险。
- 本轮未运行新回测、未改参数、未读取holdout、未生成promotion结论，也未触达broker/private/order/paper/live端点。
