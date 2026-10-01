---
book_id: STR-11
title: 因子投资方法与实践
authors: [石川, 刘洋溢, 连祥斌]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\因子投资方法与实践 - 石川 刘洋溢 连祥斌 - 原文.md
source_format: pdf_text_original_pdf_cross_checked
source_sha256: e739721044148bd0894e95fbef5fa881631172240555d59fdc9c7d022f9fa018
source_line_count: 15070
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\因子投资方法与实践(因子投资中文版首著)(博文视点出品) (石川, 刘洋溢, 连祥斌) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_source_sha256: dcf1a9beb089c35a1110308c48669bc61b0a113c20643b36451e19faf077a33a
original_source_page_count: 423
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 7
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 36_factor_methods_models_anomalies_and_practice_items_verified_concept_only_from_original_pdf
last_reviewed_at: 2026-07-15
---

# STR-11：因子投资方法与实践

## 覆盖声明

本卡已按 PDF 文本逐章完成 7/7 章 `L2` 语义复核，覆盖正文 `109-12612`。现已直接回看 423 页原 PDF 的章节书签、公式正文和关键实证段落，将 36 个方法、模型、异象与实践条目关闭为 `verified_concept_only`。这只确认书中确有对应定义、公式和案例，不认证 A 股历史结果、固定阈值、经验参数、数据版本、原论文或对美股/BTC 的外推；复杂公式的实现仍须以项目规范和独立测试为准。

第 3—5 章的主要实证对象是中国 A 股。其因子方向、阈值、收益、停牌/涨跌停、做空和交易成本结论不得迁移到美股；全书股票因子结果也不得直接迁移到 BTC。可迁移的是研究方法、证据边界、组合/风险接口和反过拟合约束。

## 全书项目映射

- `methodology_source`：排序组合、Fama–MacBeth、HAC/Newey–West、GMM、GRS、spanning、多重检验、样本外检验和模型敏感性可转化为美股因子研究规范。
- `existing_rule_confirmed`：预测变量、定价因子、异象、因子暴露、基准收益和 residual/alpha 必须分开；显著 residual 只表示“相对所选模型未解释”。
- `data_contract`：公司行动、停牌、财报修订、报告期、披露/可得时点、TTM、成分股、退市和 borrow 都必须 point-in-time。
- `portfolio_risk_contract`：Forecast、风险模型、目标函数、约束、成本、容量、归因和执行必须分层；风险模型未解释的收益方向绝不等于无风险。
- `research_governance`：每个变量、窗口、阈值、正交化顺序、组合方式、模型族和样本选择都进入 trial ledger；固定 `t≈2/3/3.8` 或 `IC>2%` 不是项目 gate。
- `market_boundary`：A 股结论只作方法案例；美股和 BTC 均需按各自时钟、数据、做空/融资、流动性和执行结构重新提出可证伪假说。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 因子投资基础 | `109-836` | `L2/medium` | 区分因子、模型、异象与定价误差，并将截面收益、时序共同波动、风险和归因放进统一框架。 | Forecast alpha、factor exposure、benchmark、systematic risk 和 residual 分账；相关因子不重复计信息。 | 2 项均为 `verified_concept_only` |
| 2 因子投资方法论 | `837-3401` | `L2/medium` | 排序、回归、稳健标准误、模型检验、正交化和 GMM 都依赖明确的数据、样本与统计假设。 | 因子研究规格冻结 PIT sample、breakpoints、weights、lags、exposure、SE、tests、cost 和 capacity。 | 6 项均为 `verified_concept_only` |
| 3 主流因子解读 | `3402-5027` | `L2/medium` | 数据处理决定实证有效性；规模、价值、动量、盈利、投资和换手必须分别检验。 | 美股重建 filing-time fundamentals、delisting、borrow、corporate action 和 sector exposure；A 股结果不迁移。 | 4 项均为 `verified_concept_only` |
| 4 多因子模型 | `5028-6145` | `L2/medium` | 模型解释力随因子定义、测试资产、样本、权重和复杂度变化，单一模型没有真值地位。 | 多基准 sensitivity、模型版本和复杂度登记；residual 不直接命名为 alpha。 | 3 项均为 `verified_concept_only` |
| 5 异象研究 | `6146-6856` | `L2/medium` | 复合分数可增强样本内区分，也会放大阈值、变量和组合选择自由度。 | 每个组件和组合方式计 trial；验证 incremental OOS、borrow、turnover、capacity、outlier 和模型敏感性。 | 3 项均为 `verified_concept_only` |
| 6 因子研究现状 | `6857-9527` | `L2/medium` | factor zoo、发表偏差、行为解释、样本外衰减、成本、拥挤和 ML 共同限制因子证据。 | 先验机制、trial ledger、FDR/DSR/PBO、locked holdout、simple baseline、decay/crowding monitoring。 | 7 项均为 `verified_concept_only` |
| 7 因子投资实践 | `9528-12612` | `L2/medium` | 收益模型、风险模型、优化、成本、指数化、择时、归因和另类数据必须在可投资约束下组合。 | Portfolio 输出 exposure/risk/cost/turnover/capacity/constraint loss；timing 只作独立 challenger。 | 11 项均为 `verified_concept_only` |

## L3 原始 PDF 复核索引

- 第 1 章（PDF `7-26`）：`FORM-STR11-CH01-001`、`FORM-STR11-CH01-002`，均为 `verified_concept_only`。
- 第 2 章（PDF `27-96`）：`FORM-STR11-CH02-001`、`FORM-STR11-CH02-002`、`FORM-STR11-CH02-003`、`FORM-STR11-CH02-004`、`FORM-STR11-CH02-005`、`FORM-STR11-CH02-006`，均为 `verified_concept_only`；Fama–MacBeth、Newey–West、GRS、正交化与 GMM 原文已核。
- 第 3 章（PDF `97-157`）：`FORM-STR11-CH03-001`、`FORM-STR11-CH03-002`、`FORM-STR11-CH03-003`、`FORM-STR11-CH03-004`，均为 `verified_concept_only`；A 股数据和历史表格不迁移。
- 第 4 章（PDF `158-191`）：`FORM-STR11-CH04-001`、`FORM-STR11-CH04-002`、`FORM-STR11-CH04-003`，均为 `verified_concept_only`；模型 residual 仍为 benchmark-relative。
- 第 5 章（PDF `192-223`）：`FORM-STR11-CH05-001`、`FORM-STR11-CH05-002`、`FORM-STR11-CH05-003`，均为 `verified_concept_only`；复合分数、锚定反转与 IVOL 均保持独立 challenger。
- 第 6 章（PDF `224-290`）：`FORM-STR11-CH06-001`、`FORM-STR11-CH06-002`、`FORM-STR11-CH06-003`、`FORM-STR11-CH06-004`、`FORM-STR11-CH06-005`、`FORM-STR11-CH06-006`、`FORM-STR11-CH06-007`，均为 `verified_concept_only`；最小 Bayes 因子、FDR、行为参数、情绪、ML 与 IPCA 均不得直接转 gate 或信号。
- 第 7 章（PDF `291-377`）：`FORM-STR11-CH07-001`、`FORM-STR11-CH07-002`、`FORM-STR11-CH07-003`、`FORM-STR11-CH07-004`、`FORM-STR11-CH07-005`、`FORM-STR11-CH07-006`、`FORM-STR11-CH07-007`、`FORM-STR11-CH07-008`、`FORM-STR11-CH07-009`、`FORM-STR11-CH07-010`、`FORM-STR11-CH07-011`，均为 `verified_concept_only`；Barra、优化、成本、Smart Beta、择时、归因、另类数据和 RTI/DR 均需当前项目数据重新验证。

## 单书完成边界

- 7/7 章 `L2` 已完成，36/36 个登记项目均直接回看原 PDF 并关闭为 `verified_concept_only`。
- “完成”只表示知识抽取与来源核对闭环，不表示公式实现、A 股实证、原论文、阈值、模型选择或历史收益已经项目认证。
- 美股必须按 filing-time fundamentals、退市、borrow、行业暴露和全成本重建；BTC 只迁移研究方法与风险语义，不能移植股票横截面结果。

## 第 1 章：因子投资基础

**论证链**

1. 因子投资至少包含三种不同语义：用变量预测截面预期收益、用因子解释收益共同运动、用模型检验未解释收益。
2. CAPM/APT/多因子模型把资产收益拆成因子暴露乘因子溢价与模型未解释部分；后者是否为真实 alpha 取决于模型、样本和误差。
3. 因子之间相关会造成信息重复；增加因子只有在提供增量解释且保留经济含义时才有价值。
4. 因子可用于收益预测、风险模型、择时、归因和产品化，但这些用途的目标函数和验证标准不同。

**成立条件**

- excess return、benchmark、frequency、factor return、exposure 和 residual 的定义一致。
- 因子可交易性、暴露稳定性、协方差估计和样本误差被显式记录。
- “被定价”与“历史均值为正”分开检验。

**限制与反例**

- 高历史溢价可能来自短腿、微盘股、无成本、遗漏因子或数据挖掘。
- 因子相关不等于经济机制相同，正交也不创造经济独立性。
- 书中的机构规模、ETF 表现、固定阈值和案例数字只具有历史说明作用。

**项目动作**

- Forecast 只表达条件预期收益及不确定性；Portfolio/Risk 单独维护系统暴露、协方差和风险预算。
- PnL 归因分为 benchmark、factor/systematic、active/residual 和 execution/cost，均引用同一 as-of 与模型版本。
- BTC 仅迁移因子/暴露/风险语义；funding、basis、term structure、order flow 等必须作为独立市场结构假说。

**不得采用**

- 不得把模型 residual、正 t 值或正历史溢价直接称为可交易 alpha。
- 不得把相关因子收益重复计入 breadth 或组合分散度。

**L3 结论**：`FORM-STR11-CH01-001`、`FORM-STR11-CH01-002` 均为 `verified_concept_only`。

## 第 2 章：因子投资方法论

**论证链**

1. 单变量、双重和多重排序是构造因子模拟组合的粗粒度方法；独立排序与条件排序回答不同问题。
2. 时序回归、截面回归和 Fama–MacBeth 回归估计对象不同；generated regressor、errors-in-variables、cross-sectional dependence 与 serial correlation 需要不同修正。
3. White/Newey–West、GRS、spanning、alpha 检验和 GMM 都依赖样本长度、分布、平稳性、识别、矩条件和权重矩阵。
4. 正交化只回答“控制某组暴露后的增量部分”，结果依赖顺序和控制集。

**成立条件**

- 预先冻结 universe、PIT breakpoints、group count、weighting、rebalance、lag、missing/negative denominator、test assets 和 standard-error estimator。
- Fama–MacBeth 使用正确的时点排列；对序列相关另做 HAC/lag 处理。
- GRS 等联合检验满足相应样本、正态和维度条件；GMM 的 moment、stationarity、identification 和 overidentification 可审计。

**限制与反例**

- 排序组合不保证纯目标暴露；结果可能由 size、sector、liquidity 或短腿驱动。
- company characteristic 与 time-series beta 都可作 exposure proxy，但都不是普遍真值。
- 固定 `t=2`、`t=3` 或 Spearman/IC 阈值忽略 trial count 和依赖结构。

**项目动作**

- 因子研究模板必须记录数据版本、可得时点、构造参数、变换拟合窗口、测试资产、比较模型、SE/lag、trial count、成本和容量。
- 每个新因子先做相关、条件排序和多变量增量检验，再进入组合 challenger。
- 所有模型比较保留参数、残差诊断、失败原因与多重检验修正。

**不得采用**

- 不得用单次排序或单一回归显著性解锁 promotion。
- 不得在看过结果后更换 breakpoint、权重、SE、test assets 或正交顺序而不增加 trial。

**L3 结论**：`FORM-STR11-CH02-001` 至 `FORM-STR11-CH02-006` 均为 `verified_concept_only`。

## 第 3 章：主流因子解读

**论证链**

1. 价格复权、停牌、财报修订和披露时点不是清洗细节，而是决定信号是否泄漏的研究合同。
2. 使用当前后复权历史、最新修订财报或未来成分股会重写过去；停牌填价格与填零收益对动量、波动和 beta 的影响不同。
3. 市场、规模、价值、动量、盈利、投资和异常换手是独立假说；不同市场、区间、权重和短腿可产生相反结论。
4. 负结果同样是证据，例如某种动量或投资定义在给定 A 股样本中不显著，不能通过换定义掩盖。

**成立条件**

- 公司行动与 total-return 语义 point-in-time；停牌/无成交处理按统计量分别定义。
- 财报使用决策时已公开的最新版本，区分原始、修订、报告期、发布日期和可用时间；TTM/单季计算可回放。
- 因子定义、样本、权重、再平衡、做空与成本均版本化。

**限制与反例**

- A 股的 ST、涨跌停、壳价值、T+1、做空限制和 2000—2019 样本结论不适用于美股。
- 等权重、多空和零成本结果常由微盘股或不可实现短腿驱动。
- 某一时期的因子方向不是因子定义的一部分。

**项目动作**

- 美股按 SEC filing/publication time、PIT constituents、delisting returns、borrow/locate、halt、corporate action 和 sector exposure 重建。
- 每个因子独立预登记机制、定义、基准、成本和失效条件，不批量试完后择优。
- BTC 不使用公司基本面因子结论；只借用数据时钟、独立假说和可交易性评估方法。

**不得采用**

- 不得复用书中 A 股因子收益、阈值、月度调仓或粗略 `3‰` 成本。
- 不得用当前修订财报、当前复权价格或未来 universe 回填历史。

**L3 结论**：`FORM-STR11-CH03-001` 至 `FORM-STR11-CH03-004` 均为 `verified_concept_only`。

## 第 4 章：多因子模型

**论证链**

1. CAPM、FF3、Carhart4、盈利/价值四因子、FF5、q-factor、mispricing 和行为模型选择了不同的风险或错误定价代理。
2. breakpoint universe、排序方式、权重、再平衡和变量构造变化会改变同名因子的含义。
3. GRS、alpha 和 spanning 只评价模型相对所选 test assets 的表现；模型排序会随 universe、样本期和 test assets 翻转。
4. 更多因子或复合变量提高样本内解释力，但也增加自由度、冗余和事后叙事风险。

**成立条件**

- 每个 benchmark model 带明确因子定义、数据版本、样本、频率、权重和模型版本。
- 比较使用相同 test assets、样本和费用口径，并报告复杂度和 trial count。
- 混合变量需分解暴露，例如 `EP = BM × ROE` 同时含价值和盈利信息。

**限制与反例**

- 单一模型较低 alpha 不代表模型正确；较高 residual 也不证明新 alpha。
- 中国市场模型、底部 30% 剔除或特定十年窗口可能改变排名。
- 书中的简约度指标只作示例，不是项目度量。

**项目动作**

- 美股至少保留简单市场基准、经典多因子基准和项目风险模型三类 sensitivity。
- 归因结果显示 benchmark-relative residual，并附模型间范围，而非单点 alpha。
- 模型新增因子必须证明增量 OOS 信息、经济含义和可投资性。

**不得采用**

- 不得挑选最有利 benchmark model 生成 promotion 结论。
- 不得把复合模型的更高样本内解释力当作机制证明。

**L3 结论**：`FORM-STR11-CH04-001` 至 `FORM-STR11-CH04-003` 均为 `verified_concept_only`。

## 第 5 章：异象研究

**论证链**

1. F-Score、G-Score、预期差、基本面锚定反转和特质波动率展示了从变量到复合分数、排序和多因子 alpha 的路径。
2. 复合分数可能改善样本内分层，但每个组件、阈值、替代变量、缺失处理和组合规则都会增加 trial。
3. “mispricing score” 若由既有异象拼接，可能循环地用异象解释异象。
4. IVOL 结论对 benchmark model、异常点和样本敏感，不能把模型残差波动当作客观实体。

**成立条件**

- 组件具备独立经济机制、PIT 数据和预登记组合方式。
- 与简单单变量、等权重组合和现有模型比较 incremental OOS value。
- 同时评估 long-only、short leg、borrow、turnover、capacity、outlier 和模型敏感性。

**限制与反例**

- 高 headline alpha 常依赖等权重、微盘短腿与零成本；long-only 效果可能弱得多。
- A 股替代变量和阈值不适用于美股。
- 单一极端样本可改变 IVOL 结论。

**项目动作**

- 复合异象只登记为 `candidate_design`/challenger；trial ledger 展开到组件和阈值层。
- 用 ablation、OOS、成本、容量和模型敏感性证明复合比分量有增量价值。
- 对异常点同时报告保留、稳健估计和预注册过滤结果。

**不得采用**

- 不得以复合分数更显著为由跳过独立组件检验。
- 不得把“mispricing”标签当成机制证据或交易授权。

**L3 结论**：`FORM-STR11-CH05-001` 至 `FORM-STR11-CH05-003` 均为 `verified_concept_only`。

## 第 6 章：因子研究现状

**论证链**

1. p-value 表示原假设下观测到当前或更极端数据的概率，不是原假设为真的概率，也不等于经济显著性。
2. FWER、FDR、FDP、bootstrap reality check 和经验/Bayesian 修正说明：候选越多，传统单次显著性越不可信。
3. Harvey、Chordia 等文献中的 `t≈3.0/3.4/3.8` 是特定因子集、估计方法和假设下的历史结果，不是通用阈值。
4. 行为金融学提供有限套利、认知偏差、损失厌恶、有限注意力和情绪等可检验机制，但事后故事不能替代预测。
5. 异象可能来自风险补偿、错误定价或数据窥探；公告窗口、未来基本面、注意力/套利成本代理和全新样本可帮助区分，但都不是单项定论。
6. 真实因子样本外也会因曝光、拥挤、数据时效、交易成本和做空约束衰减；基本面因子不能替代完整的财报/行业分析。
7. ML 的优势是高维预测和特征选择；walk-forward 只防未来信息，不消除反复试验、依赖泄漏、小样本和过拟合。

**成立条件**

- 研究前记录全部已尝试候选、模型、参数、样本和停止规则；未发表/失败试验也计入 trial universe。
- 行为或风险机制提出可证伪预测，且在独立数据、不同状态和替代解释下检验。
- ML 使用时间顺序、purge/embargo、训练窗内变换、simple baseline、nested selection、locked holdout 和可解释性/稳定性诊断。
- 因子收益报告成本、short availability、publication/OOS split、crowding 和 decay。

**限制与反例**

- 先验概率本身主观；Bayesian p-value 不能隐藏先验敏感性。
- 情绪 PCA/PLS 指标可能混入商业周期、共同测量误差和高度持久序列伪回归。
- 行为模型可解释部分异象但解释不了全部；一种理论可被修改为支持相反方向。
- 复杂 ML 样本内表现、特征重要性或高切线 Sharpe 不证明可交易性。

**项目动作**

- 项目只使用预注册的 multiple-testing 方案；固定 t 阈值不解锁任何 gate。
- 机制证据拆为 risk、mispricing、data-snooping 三类，并保留竞争解释。
- 对因子建立 publication、crowding、valuation、pairwise correlation、volatility、reversal、short interest、turnover 和 cost 监控。
- 基本面信号附会计勾稽、修订、行业事件和异常项，而不是只读几个 ratios。
- ML challenger 与简单线性/排序基准在相同 OOS、成本和容量合同下比较。

**不得采用**

- 不得把 p-value、`t>3`、高 OOS R² 或单次模拟结果解释为“因子为真”。
- 不得用行为金融故事事后解释所有失败，或用 walk-forward 声称已经消除过拟合。
- 不得把书中发表后衰减比例、成本后收益或机器学习排名迁移为项目预期。

**L3 结论**：`FORM-STR11-CH06-001` 至 `FORM-STR11-CH06-007` 均为 `verified_concept_only`。

## 第 7 章：因子投资实践

**论证链**

1. 收益模型中的对象是 return predictor；预测变量、因子投资组合和模型 alpha 不是同义词。
2. 候选预测变量需具备逻辑、持续性、信息增量、稳健性、可投资性和普适性；IC、排序和回归只覆盖其中一部分。
3. 风险模型通过暴露、因子协方差和特质风险估计资产协方差；Barra/纯因子组合是一种实现，不是唯一真值。
4. 收益模型与风险模型错位时，优化器会把风险模型未解释的收益方向误判为低风险并过度配置。
5. 目标函数、约束和成本共同决定 TargetPosition；均值—方差、最小方差、最大分散、风险平价和等权只有在特定条件下等价。
6. Smart Beta 是透明规则、因子暴露与可投资性的权衡；理论多空因子不等于可投资产品。
7. 因子择时以等权为基准，估值、动量、波动、情绪和宏观关系动态且成本后经常失去优势。
8. 风格分析和风险归因都依赖模型；风险必须同时归因于系统因子和个股特质部分。
9. 另类数据需要匹配技术、领域知识、无偏采集、足够历史和增量信息；新颖不等于独占或有效。
10. 跨资产因子配置要处理模拟组合、下行相关和尾部风险，历史低相关不能代表压力期独立。

**成立条件**

- return predictor 具备明确 as-of、expiry/half-life、expected return unit、uncertainty 和 baseline。
- 风险模型通过事前/事后 bias、正定性、shrinkage、压力相关和模型版本验证。
- 优化器显式输入收益、协方差、现有仓位、约束、成本、容量和 no-trade 选项；报告 feasibility 与 constraint loss。
- 归因固定 benchmark、factor definitions、窗口和模型版本，并报告模型敏感性。
- 另类数据有 lineage、采集偏差、覆盖、许可、修订和可用时间合同。

**限制与反例**

- `IC>2%`、历史均值参数、MAD 常数、经验 shrinkage 系数和指数历史表现都不能直接成为项目参数。
- 风险模型假定特质收益互相独立可能在压力期失效；样本协方差与均值估计都不稳定。
- 复杂配置方法需要更多参数，可能不如等权；约束过多可导致无解。
- Smart Beta 和另类数据都可能因拥挤、供应商共享、短历史和交易成本失效。
- 风格 residual/alpha 会随因子集和样本改变；事后归因不证明事前可复制。

**项目动作**

- Forecast → Portfolio/Risk 接口携带 expected return、horizon、confidence/interval、expiry、source run 和 factor exposures；Strategy 不直接输出订单。
- 风险模型与收益模型建立 exposure alignment report；未解释方向加入额外风险、上限或 challenger 隔离。
- Portfolio 输出 unconstrained/constrained target、risk contribution、turnover、cost、capacity、tracking error、constraint loss 和 infeasibility reason。
- 成本模型至少区分 fee/spread/impact/borrow/funding，并允许不交易；成本缺失 fail-closed。
- 因子 timing 独立预注册并以等权净收益为基准；情绪/宏观数据必须 vintage-aware。
- 归因分离 factor/systematic、specific、portfolio construction 与 execution/cost，不让 attribution 反向改写 locked evidence。
- 另类数据只进入研究候选；无 lineage、代表性、历史长度或许可时保持 blocked。

**不得采用**

- 不得把风险模型无法解释的预测收益当作无风险 alpha。
- 不得把均值—方差、风险平价、Smart Beta、IC 加权或防御性择时当成默认最优方案。
- 不得用书中 A 股指数、ETF、基金、市场规模、费率和历史胜率生成当前投资结论。
- 不得把另类数据供应商的加工信号视为独占、无偏或即插即用。

**L3 结论**：`FORM-STR11-CH07-001` 至 `FORM-STR11-CH07-011` 均为 `verified_concept_only`。

## 市场差异边界

- A 股停牌、涨跌停、T+1、ST/壳价值、发行/退市、做空限制和财报披露制度与美股不同。
- 美股应用必须以 SEC filing/publication timestamp、point-in-time constituents、delisting returns、borrow availability、真实 corporate actions、交易所日历和 sector exposure 重建。
- BTC 没有公司财报、行业和股票借券的同构语义；只能迁移研究治理、风险模型、成本、拥挤、归因与择时验证框架。
- 书中任何历史因子收益、显著性、阈值、参数、费率、ETF 规模或案例结论都不是当前项目证据。

## 与项目现有规范的合并结论

- 与 `financial_ml_validation_rules.md` 一致：搜索空间、trial count、purged walk-forward、multiple testing 和 locked holdout 必须同时存在。
- 与 `no_lookahead_rules.md` 一致：财报修订、披露 lag、复权、成分股和截面变换必须 point-in-time，且 prefix-invariance 可验证。
- 与 `forecast_to_portfolio_rules.md` 一致：预测、风险和组合是不同领域对象；优化器只输出受约束 TargetPosition。
- 与 `risk_budget.md` 一致：因子暴露、相关性、流动性、容量、成本和压力期共同决定风险预算，固定书中比例不得复用。
- 与 `backtest_evidence_contract.md` 一致：本卡只能生成候选、合同、测试和 blocker，不能作为回测结果或 promotion evidence。

## 后续 L3 复核顺序

1. 第 2 章统计检验与 GMM/GRS：先核原 PDF 公式、假设和维度。
2. 第 6 章多重检验、Bayesian p-value、OOS/ML 指标：对照原论文定义和项目 trial ledger。
3. 第 7 章收益/风险模型错位、协方差调整、优化、成本和风险归因：对照 Portfolio/Risk 合同。
4. 第 3—5 章因子与异象：制作“A 股结论—美股不可迁移项—可迁移方法”差异矩阵。
