---
book_id: RES-02
title: Evidence-Based Technical Analysis
authors: [David Aronson]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Evidence-Based Technical Analysis - David Aronson - 原文.md
source_format: pdf_text_plus_original_pdf_visual_formula_review
source_sha256: f1b89130ce4b2b15209ffa90b59370dc1d4b2d099460c3a0304cba6f36b90c10
source_line_count: 23890
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\Evidence-Based Technical Analysis Applying the Scientific Method and Statistical Inference to Trading Signals (David R. Aronson(auth.)) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: 8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2
card_status: original_pdf_formula_review_complete_concept_only
chapter_count: 9
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: ch01_ch09_30_items_each_verified_concept_only_complete
last_reviewed_at: 2026-07-14
---

# RES-02：Evidence-Based Technical Analysis

## 覆盖声明

本卡已完成9/9章`L2`语义精读和Ch01—Ch09各30项、共270项原PDF概念级`L3`复核；附录PDF页475—476的去趋势等价证明已在Ch01条目中覆盖。全书公式、图表、规则状态、历史统计和方法边界均有原PDF位置、可信度、项目映射及不可迁移约束。`verified_concept_only`只表示原文概念与显示公式已核，不表示公式代码、历史统计结果、案例参数、当前策略、执行表现或promotion证据已获项目验证。

## 全书项目映射

- `existing_rule_confirmed`：规则可复跑、零假设、可证伪预测、时间可得性、基准和多重试验留痕与项目研究合同一致。
- `implementation_gap`：候选登记仍需强制写入原始观察、经济机制、null、trial universe、评价时点、反证条件、竞争解释和所有未选中规则。
- `rejected_for_now`：书中把“可编程”视为客观性的充分边界、用全样本均值去趋势、成本外信号研究和 S&P 案例结论均不能直接进入本项目证据链。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Objective Rules and Their Evaluation | `769-1498` | `L3/high_concept_only` | 规则需无歧义、可复跑，并相对匹配仓位偏置和市场趋势的非预测基准评价；信号时点、可执行价格和成本必须分离。 | `existing_rule_confirmed`：Strategy只输出Signal/Forecast；基准、可得时点、执行延迟、成本与trial family写入evidence。 | `FORM-RES02-CH01-001`—`030`已由原PDF关闭为`verified_concept_only`；全样本centering只作事后benchmark，去趋势执行式括号已核 |
| 2 Illusory Validity of Subjective Methods | `1499-4587` | `L3/high_concept_only` | 主观图形在不确定环境中受过度自信、归因、事后、确认、可得性、代表性、小样本与虚假相关共同放大。 | `candidate_design`：人工判断只能先变成带时点、期限、阈值、失败定义和完整四格结果的可证伪记录。 | `FORM-RES02-CH02-001`—`030`已由原PDF关闭为`verified_concept_only`；心理学历史数字、示例阈值和随机图均不可迁移 |
| 3 Scientific Method and Technical Analysis | `4588-7315` | `L3/high_concept_only` | 观察只能生成假设；新样本预测、竞争零假设、反证和严格统计推断才把想法转为暂时性知识。 | `existing_rule_confirmed`：预登记 observation→hypothesis→prediction→verification→conclusion，成功是暂未拒绝而非证明。 | `FORM-RES02-CH03-001`—`030`已由原PDF关闭为`verified_concept_only`；逻辑反证不可机械替代概率检验，头肩案例规则与参数不迁移 |
| 4 Statistical Analysis | `7316-9674` | `L3/high_concept_only` | 统计推断以总体、样本、统计量和抽样分布连接历史观察与未知未来；标准误和 CLT 均依赖抽样与依赖假设。 | `implementation_gap`：明确 estimand、有效样本数、依赖结构、稳健统计量和 block resampling，不套用 IID 公式。 | `FORM-RES02-CH04-001`—`030`已由原PDF关闭为`verified_concept_only`；`n`/`n−1`、density/point probability、CLT与resampling语义已核 |
| 5 Hypothesis Tests and Confidence Intervals | `9675-11351` | `L3/high_concept_only` | p 值只描述 H0 下当前或更极端证据的概率；bootstrap、permutation 和 CI 的 null、重采样单位与覆盖语义不同。 | `candidate_design`：预登记 alpha/loss/power，报告 effect+CI，使用保持时间依赖的 resampling，并纠正 accept-H0 和 CI 概率误读。 | `FORM-RES02-CH05-001`—`030`已由原PDF关闭为`verified_concept_only`；p值、单双尾、Type I/II、bootstrap/permutation与CI coverage语义已核 |
| 6 Data-Mining Bias | `11352-14952` | `L3/high_concept_only` | 从多候选中按样本表现选赢家会系统高估未来表现；偏差受 trial 数、样本数、候选相关、正向离群和真实 merit 分散共同影响。 | `existing_rule_confirmed`：完整 trial ledger、nested selection、一次性 holdout、selection-aware null 与负结果留痕。 | `FORM-RES02-CH06-001`—`030`已由原PDF关闭为`verified_concept_only`；历史模拟、MX、WRC/MCP不迁移 |
| 7 Theories of Nonrandom Price Motion | `14953-17441` | `L3/high_concept_only` | 非随机运动是技术规则可能有效的必要条件但不充分；行为偏差、信息扩散、反馈、套利限制与风险溢价是竞争机制。 | `candidate_design`：edge_type 区分 mispricing/risk premium/liquidity/information diffusion，并预登记代理、竞争解释和失效条件。 | `FORM-RES02-CH07-001`—`030`已由原PDF关闭为`verified_concept_only`；历史实证、模型期限和风险收益数字不迁移 |
| 8 Case Study of Rule Data Mining | `17442-19843` | `L3/high_concept_only` | 6,402 规则案例的可迁移价值是完整枚举 input→operator→state→metric→selection，而不是具体 S&P 规则。 | `concept_only`：借鉴 immutable trial universe、naming、全候选 returns/predictions 和 selection-aware null；拒绝参数迁移。 | `FORM-RES02-CH08-001`—`030`已由原PDF关闭为`verified_concept_only`；公式、参数、输入和计数仅作历史provenance |
| 9 Case Study Results and Future of TA | `19844-21339` | `L3/high_concept_only` | 选择校正后 6,402 个规则均未拒绝共同无效 null；负结果、限制和复杂度搜索必须完整保留。 | `existing_rule_confirmed`：普通单规则 p 值不得评价赢家；复杂模型须 nested selection 和独立 validation，失败结果进入 registry。 | `FORM-RES02-CH09-001`—`030`已由原PDF关闭为`verified_concept_only`；赢家、p值、阈值、区间和复杂模型建议均不迁移 |

## 已完成 L2：第 1 章

### 第 1 章：客观规则、偏置基准与可执行时点

- **论证链**：本章把客观规则定义为可编程、对同一输入产生无歧义输出的变换，并用单阈值、双阈值、状态保持和传统/反向解释说明规则族如何形成。仅报告绝对收益没有意义：无预测力规则在上涨市场中只因长期偏多也会获利，因此评价必须匹配规则的多空时间占比和市场趋势。原文给出仓位偏置期望收益、去趋势收益、对数收益及 next-open 执行关系，并提醒发布延迟、修订和同收盘成交假设会产生前视。章节最后区分“预测信息研究”和“独立交易策略”，但选择在前者中不计成本；项目只接受其研究问题分层，不接受成本豁免。
- **成立条件**：规则规格必须保存输入字段、PIT/available time、算子和状态、阈值、初始化、缺失值、输出语义、决策时点、expiry、benchmark、传统/反向方向、trial family、成本层和复跑 hash。单阈值必须覆盖互斥且穷尽的状态；双阈值必须定义区间内的状态保持和冷启动。仓位偏置诊断需按同一评价区间、同一可交易时钟和同一方向约定计算；任何去均值、标准化或 detrend 只能在训练折拟合并冻结。收盘后才完整可得的信号不得以同收盘成交，经济评价使用可执行价格、spread、fee、impact、latency 和 capacity。
- **局限与反例**：可编程只证明可重复，不证明定义正确、PIT、统计显著、经济有效或可执行；输出 `+10/-10` 也不能绕过 Portfolio/Risk 直接成为合约数量。传统规则和反向规则都可能在同一历史样本中被挑选，因此是两个 trial，不是一个稳健性检查。全样本平均回报去趋势使用未来区间均值，在 rolling/OOS 中会泄漏，且去趋势收益只是识别仓位偏置的诊断，不是 cash/fill/position ledger PnL。随机信号、risk-free、buy-and-hold 和 incumbent 各回答不同问题，不能挑最容易战胜者。next-open 是本书日频假设，不适用于 auction、24/7 BTC、停牌、gap 或盘口冲击。
- **项目动作**：新增候选时把原始 signal、方向反转、阈值/状态变体全部登记为独立候选；先以无信息、buy-and-hold/cash、现有策略和匹配暴露的 placebo 构成基准层级。报告 gross signal diagnostic 与 net executable evidence 两套结果，但任何研究、paper 或 promotion 判断只采纳成本后证据。为 feature/decision/order/fill 建 availability chain，并用 prefix invariance、same-close rejection、lag/revision、gap、threshold equality、warm-up 和 state replay fixture 验证。Strategy 输出保持 Signal/Forecast，Portfolio/Risk 独立生成 TargetPosition，OMS 才生成和执行 OrderIntent。
- **禁止直接采用**：不得复制书中固定阈值、移动平均长度、binary always-in-market、S&P 1976—2004 数字、next-open 统一成交、全样本 detrend 或零成本案例；不得把客观规则称为有效规则、把正收益称为预测力、把去趋势收益称为可交易 PnL、把 signed rule output 直接解释为持仓数量。不得在看结果后决定传统或反向方向，也不得让成本外研究结果进入 paper/live 准备。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原载体复核结论**：`FORM-RES02-CH01-001`—`030`已回到原PDF关闭为`verified_concept_only`。正文为PDF页22—38（印刷页15—31），去趋势等价证明另在PDF页475—476的Eq.A.1—A.4。单/双阈值、traditional/inverse、position-bias benchmark、log return、next-open alignment与cost分层均已视觉核对。需要收紧两处：全back-test sample centering用于事后matched-bias benchmark时是诊断，不应一概称leakage；但若被当成online feature或可交易PnL则使用未来均值。原书去趋势执行式明确为`Pos_0×[log(O_{+2}/O_{+1})−ALR]`，ALR在仓位乘法括号内，不能写成`Pos×log return−ALR`。原书允许rule output直接代表仓位并在signal discovery中不扣cost，均不进入本项目生产边界。

## Ch01 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页22—38，附录证明PDF页475—476。
- 结论边界：objective只表示可精确定义和复跑，不证明PIT、统计、经济、执行或promotion有效；centered-return与matched-position-bias等价只覆盖附录中的additive raw-return设定。任何signal仍须经Forecast、Portfolio/Risk、OMS/Execution与Fill/Ledger。

| ID | 原 PDF 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH01-001` | PDF页22—23 | objective判据是精确定义、可编程、输出无歧义。 | reproducibility不是validity或executability。 | `verified_concept_only` |
| `FORM-RES02-CH01-002` | PDF页23—24；Fig.1.1 | rule以算子把market time series变成output series。 | 保存lineage、operator/state/clock/output version。 | `verified_concept_only` |
| `FORM-RES02-CH01-003` | PDF页23—24 | 原书允许signed output表示position quantity。 | 项目拒绝直通，数量由Portfolio/Risk决定。 | `verified_concept_only` |
| `FORM-RES02-CH01-004` | PDF页24—25 | binary rule默认long/short两态且持续持仓。 | neutral、initial state与always-invested风险需显式。 | `verified_concept_only` |
| `FORM-RES02-CH01-005` | PDF页24—26；Fig.1.3 | `input>threshold`为+1，否则−1，等号归下支。 | NaN、units、tie与warm-up需fixture。 | `verified_concept_only` |
| `FORM-RES02-CH01-006` | PDF页25；Fig.1.2 | moving-average cross映射price相对动态阈值。 | 冻结window、availability、adjustment与tie policy。 | `verified_concept_only` |
| `FORM-RES02-CH01-007` | PDF页26 | fixed threshold被限定于近stationary输入。 | transform/stationarity仅训练前缀选择。 | `verified_concept_only` |
| `FORM-RES02-CH01-008` | PDF页26—28；Fig.1.4 | 双阈值区间内保持旧state形成hysteresis。 | 冷启动、touch/cross、restart replay需定义。 | `verified_concept_only` |
| `FORM-RES02-CH01-009` | PDF页27—28 | zone与direction可组成多状态mode。 | 每种组合计trial，历史例不迁移。 | `verified_concept_only` |
| `FORM-RES02-CH01-010` | PDF页28—29；Fig.1.5 | traditional与inverse取相反direction。 | 两者为独立候选，不得事后翻转。 | `verified_concept_only` |
| `FORM-RES02-CH01-011` | PDF页29 | inverse不是原规则的稳健性证明。 | 双向结果和selection完整留痕。 | `verified_concept_only` |
| `FORM-RES02-CH01-012` | PDF页29—30 | 绝对performance必须相对benchmark解释。 | benchmark的period/risk/exposure/clock/cost一致。 | `verified_concept_only` |
| `FORM-RES02-CH01-013` | PDF页30 | no-predictive-power rule是最低benchmark。 | 另保留cash、buy-hold、incumbent与placebo。 | `verified_concept_only` |
| `FORM-RES02-CH01-014` | PDF页30—32 | 无预测规则也可因trend与position bias非零收益。 | 使用matched-exposure null。 | `verified_concept_only` |
| `FORM-RES02-CH01-015` | PDF页30—32 | predictive、position bias与market trend是概念分解。 | 不作已识别因果方程；beta/cost另报。 | `verified_concept_only` |
| `FORM-RES02-CH01-016` | PDF页33 | `ER=p(L)ADC−p(S)ADC`。 | 要求position assignment无预测，保存return convention。 | `verified_concept_only` |
| `FORM-RES02-CH01-017` | PDF页33；代数推导 | 二元always-in-market时`ER=(2p(L)−1)ADC`。 | derived identity；有neutral/size时不成立。 | `verified_concept_only` |
| `FORM-RES02-CH01-018` | PDF页32—34；Fig.1.6 | 不同long fraction可混淆无预测规则排名。 | matched placebo与uncertainty必须报告。 | `verified_concept_only` |
| `FORM-RES02-CH01-019` | PDF页34 | observed减matched random benchmark隔离增量。 | 只作同sample诊断，不是ledger PnL。 | `verified_concept_only` |
| `FORM-RES02-CH01-020` | PDF页34—35 | detrending为逐项减完整测试期sample mean。 | ex-post benchmark可用；online/PnL使用则泄漏。 | `verified_concept_only` |
| `FORM-RES02-CH01-021` | PDF页35；Appendix页475—476 | Eq.A.1—A.4证明additive设定下centering与matched benchmark等价。 | 不覆盖compounding、cost、dynamic size或nonlinear payoff。 | `verified_concept_only` |
| `FORM-RES02-CH01-022` | PDF页35 | centered returns下无预测assignment期望为0。 | zero mean不等于IID、无beta、无tail或无risk。 | `verified_concept_only` |
| `FORM-RES02-CH01-023` | PDF页36 | `log(current price/prior price)`定义daily log return。 | price>0、adjustment、roll与units需保存。 | `verified_concept_only` |
| `FORM-RES02-CH01-024` | PDF页36 | detrended log return减测试期average log return。 | 只作事后benchmark，不替代Fill/Ledger。 | `verified_concept_only` |
| `FORM-RES02-CH01-025` | PDF页36—37 | close signal不得假设same-close fill，书中例用next open。 | next-open非普适，需venue/session/order evidence。 | `verified_concept_only` |
| `FORM-RES02-CH01-026` | PDF页37 | `Pos_0×log(O_{+2}/O_{+1})`对齐day0 close state与后续open interval。 | 核验index、timezone、gap与holding interval。 | `verified_concept_only` |
| `FORM-RES02-CH01-027` | PDF页37 | 去趋势式为`Pos_0×[log(O_{+2}/O_{+1})−ALR]`。 | ALR在括号内；完整测试期均值仅作事后诊断。 | `verified_concept_only` |
| `FORM-RES02-CH01-028` | PDF页37 | delayed/revised input按真实availability滞后。 | 保存release/receive/revision/decision时间。 | `verified_concept_only` |
| `FORM-RES02-CH01-029` | PDF页38 | cost含commission、spread与market impact slippage。 | 另补fee、latency、partial fill、funding/borrow/tax。 | `verified_concept_only` |
| `FORM-RES02-CH01-030` | PDF页38 | 原书signal discovery不扣cost，stand-alone trading需扣cost。 | gross只作诊断；经济排名/promotion必须net executable。 | `verified_concept_only` |

## 已完成 L2：第 2 章

### 第 2 章：主观判断偏差、虚假相关与审计化反制

- **论证链**：本章的稳定结论不是“图表必然无效”，而是无法排他定义、复跑和反证的图形解释不能形成可靠知识。不确定市场会同时触发模式偏好、有限信息处理、过度自信、乐观、自利归因、控制幻觉、事后偏差、故事偏好和确认偏差。对二元信号与结果，只看“信号出现且结果出现”的确认格会制造虚假相关；必须同时统计 false positive、false negative 和共同缺席。可得性与代表性又使近期、鲜明、相似和小样本事件被过度计权，随机序列中的簇、连胜和图形因此被误读为可预测结构。
- **成立条件**：任何人工 chart review、研究员排除或 regime 标注必须在知道结果前写入 timestamped decision ledger，包含输入快照、规则版本、观察者、预测方向、horizon、favorable/adverse threshold、abstention、评价时点和明确失败条件。二元或多类主张必须保存完整 confusion/contingency counts、base rate、样本数、缺失与未触发记录，而不是只保存命中案例。主观候选若不能客观化，只能作为假设生成来源；若保留人工 forecast，必须冻结后续解释、盲化评审并与 simple/random/no-signal 基准比较。
- **局限与反例**：章节大量心理学和历史案例支持“人会系统偏差”，不能证明某位研究员、某类图形或当前 BTC/美股市场一定无效。专家判断有时可利用难以编码的信息，但仍需前瞻记录和可评价输出；自动模型也会复制确认偏差、selection bias 和故事偏好。完整四格计数不自动处理时间依赖、类别不平衡、非平稳、选择性标签或经济损失。随机图能生成类似形状只否定“形状出现即证明预测力”，不证明价格过程完全随机。书中将不可检验主张称为“无意义”是方法论立场，项目采用更窄的治理表述：不得作为验证、promotion 或执行证据。
- **项目动作**：研究 UI/记录模板增加 `observation_before_outcome`、`falsifier`、`alternative_explanations`、`base_rate`、`all_cases_count`、`manual_override_reason` 和 `review_blinded` 字段。人工图形先转换成确定的 pivot、容差、窗口、确认、expiry 和 exclusion rule，再把每次改定义计入 trial ledger。建立 placebo/random-walk chart、label shuffle、future-hidden replay 和 analyst disagreement 诊断；评估同时报告四格、calibration、coverage、abstention、regime 和成本。负例、未触发和失败预测永久保留，禁止只归档“经典案例”。
- **禁止直接采用**：不得因为叙事合理、权威引用、近期命中、视觉相似、早期成功或研究员信心而提高候选等级；不得事后移动趋势线、改变 horizon、重命名 regime 或把失败归因于外部环境而不登记新 trial。不得把图表、attention heatmap 或 LLM 解释当作独立证据，也不得将心理学案例转换成交易参数。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原载体复核结论**：`FORM-RES02-CH02-001`—`030`已回到原PDF关闭为`verified_concept_only`。正文为PDF页39—107（印刷页33—101）。本章没有可迁移的交易公式；可复核的定量核心是四格计数与条件比例比较。Fig.2.16的`A=37,B=17,C=33,D=13`给出`37/54≈0.685`与`33/46≈0.717`，说明只看37个确认案例会误判；Fig.2.17的`A=47,B=7,C=23,D=23`给出约`0.870`对`0.5`。这些数字只核概念，不是项目阈值。书中对主观TA的强否定被收紧为：不可证伪、不可复跑或缺完整分母的主张不得成为验证、promotion或执行证据；随机图形只能反驳“形状即证明”，不能证明市场过程随机。

## Ch02 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页39—107，下一章从PDF页108开始。
- 结论边界：本章是认知偏差与证据完整性审计，不产生Signal或参数。四格完整只是必要条件，仍须处理时间依赖、选择、类别不平衡、censoring、abstention与经济损失。

| ID | 原 PDF 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH02-001` | PDF页39—41 | 怀疑立场针对不可检验主张。 | 怀疑不等于预设无效；允许反证。 | `verified_concept_only` |
| `FORM-RES02-CH02-002` | PDF页40—41 | 可复核性是公共知识边界，不是有效性充分条件。 | 主观与形式模型分别治理。 | `verified_concept_only` |
| `FORM-RES02-CH02-003` | PDF页45—47 | 人会在噪声中寻找模式。 | false-positive与miss损失显式。 | `verified_concept_only` |
| `FORM-RES02-CH02-004` | PDF页47—48；Fig.2.3 | 多种heuristic/bias会联合作用。 | 用具体控制而非偏差标签。 | `verified_concept_only` |
| `FORM-RES02-CH02-005` | PDF页48—50 | 有限信息处理限制主观多因素整合。 | 历史记忆容量数字不作参数。 | `verified_concept_only` |
| `FORM-RES02-CH02-006` | PDF页49—50 | 一致模型可减少不稳定加权。 | 形式化模型仍可能selection-biased。 | `verified_concept_only` |
| `FORM-RES02-CH02-007` | PDF页51—53 | 置信度可系统高于准确率。 | 保存概率与实际频率校准。 | `verified_concept_only` |
| `FORM-RES02-CH02-008` | PDF页54 | 乐观偏差削弱失败反馈。 | 预登记停止与退役规则。 | `verified_concept_only` |
| `FORM-RES02-CH02-009` | PDF页54 | 自利归因阻断信念更新。 | 独立复核失败原因。 | `verified_concept_only` |
| `FORM-RES02-CH02-010` | PDF页54—55 | 预定义退出和日志减少事后重述。 | append-only时间戳与版本。 | `verified_concept_only` |
| `FORM-RES02-CH02-011` | PDF页55 | 更多信息可只提高信心。 | feature按增量证据评价。 | `verified_concept_only` |
| `FORM-RES02-CH02-012` | PDF页56 | 参与、选择、信息、熟悉和早期成功诱发控制幻觉。 | 报告trial、override与早期幸运。 | `verified_concept_only` |
| `FORM-RES02-CH02-013` | PDF页57—63；Figs.2.6—2.12 | 结果知识会重构事前判断。 | pre-outcome snapshot与盲化回放。 | `verified_concept_only` |
| `FORM-RES02-CH02-014` | PDF页62—64 | 仅提醒避免偏差不能隔离结果污染。 | 依靠机械隔离而非自律。 | `verified_concept_only` |
| `FORM-RES02-CH02-015` | PDF页64 | 预定义错误、程序和时点使人工预测可证伪。 | 20%/六个月只是例，不迁移。 | `verified_concept_only` |
| `FORM-RES02-CH02-016` | PDF页65—67 | 鲜明故事可压过抽象频数。 | 叙事、统计与替代解释分栏。 | `verified_concept_only` |
| `FORM-RES02-CH02-017` | PDF页68—76 | 确认偏差影响搜索、感知与解释。 | 保存负例和完整搜索路径。 | `verified_concept_only` |
| `FORM-RES02-CH02-018` | PDF页73—77；Fig.2.14 | 重命名和模糊预测可维持信念。 | 改定义即新版本/new trial。 | `verified_concept_only` |
| `FORM-RES02-CH02-019` | PDF页77—79 | 主张可先表示为二元predictor/outcome关系。 | 冻结pattern、window与clock。 | `verified_concept_only` |
| `FORM-RES02-CH02-020` | PDF页79 | 只看共同出现遗漏其余三类。 | 四格必要但不充分。 | `verified_concept_only` |
| `FORM-RES02-CH02-021` | PDF页79—80；Fig.2.15 | `A/B/C/D`覆盖四种组合。 | 保存unknown、abstention与lineage。 | `verified_concept_only` |
| `FORM-RES02-CH02-022` | PDF页81—84；Figs.2.16—2.17 | 比较`A/(A+B)`与`C/(C+D)`；两组示例算术已核。 | 另报CI、base rate、依赖与selection。 | `verified_concept_only` |
| `FORM-RES02-CH02-023` | PDF页84—86；Table 2.1 | 主观方法常缺未触发/失败分母。 | 表中模式清单不补完整case。 | `verified_concept_only` |
| `FORM-RES02-CH02-024` | PDF页86—91 | 图表适合生成假设，不验证预测力。 | 图表/LLM解释非promotion evidence。 | `verified_concept_only` |
| `FORM-RES02-CH02-025` | PDF页88—91；Fig.2.18 | 随机序列也会出现经典形状。 | 不据此证明市场随机。 | `verified_concept_only` |
| `FORM-RES02-CH02-026` | PDF页92—99 | heuristic会把偶然结构解释为规律。 | 形式检验和新样本仍必需。 | `verified_concept_only` |
| `FORM-RES02-CH02-027` | PDF页92—94 | 近期、鲜明、易回忆事件被高估。 | 使用完整case registry。 | `verified_concept_only` |
| `FORM-RES02-CH02-028` | PDF页94—99；Figs.2.19—2.20 | representativeness会忽略base rate。 | 报告prevalence、precision/recall与calibration。 | `verified_concept_only` |
| `FORM-RES02-CH02-029` | PDF页99—104；Figs.2.21—2.25 | 随机数据常不符合直觉交替原型。 | null需匹配实际依赖而非默认IID。 | `verified_concept_only` |
| `FORM-RES02-CH02-030` | PDF页104—107 | 小样本比例、簇和连胜容易被过度解释。 | 报告effective n、streak null与不确定性。 | `verified_concept_only` |

## 已完成 L2：第 3 章

### 第 3 章：可证伪假设、竞争零假设与新样本验证

- **论证链**：本章把科学研究拆为观察、假设、预测、验证和结论五阶段。观察与归纳可提出一般化主张，但有限历史不能逻辑证明其对未来成立；演绎只能在前提为真时保证结论。`If A then B; B` 不能推出 `A`，所以盈利回测与“规则有预测力”一致，却也与运气、数据挖掘、趋势暴露和错误实现一致。研究应从竞争零假设出发，预先推导在新观察中应出现和不应出现的结果，再用不符合预测的证据反驳；通过只意味着暂未被拒绝。客观化图形的关键是给出排除规则，而不只是描述理想形状。
- **成立条件**：每个候选必须保存原始观察与其所用数据、经济假设、竞争 null、方向性预测、适用总体、operation/test、评价样本、成功阈值、falsifier、替代解释、结论和状态。假设必须对尚未知结果作出有期限、有幅度、有基准的预测；历史解释不能代替新样本。模型复杂度只有在同等可验证表现下才受简约原则偏好；统计显著和经济显著分开。客观化主观模式时必须定义 inclusion、exclusion、pivot、tolerance、signal time、expiry 和 prediction error，且版本冻结后才可评价。
- **局限与反例**：现实统计检验不能像纯演绎一样确定证伪，结论依赖数据质量、检验功效、误差率、依赖结构和模型假设；原文借“排中律”把 null 与 alternative 视为完全互补，项目必须允许模型错设、复合假设、equivalence region 和 inconclusive。简单不等于正确，复杂模型也可能有真实机制；Occam 只能在可比证据下作次级偏好。未拒绝 null 不证明无效，拒绝 null 也不证明唯一机制。书中对 subjective/objective/useful 的四分法仍缺 current-HEAD、成本、容量、risk、ledger 和 execution 证据，不能直接映射 promotion 状态。
- **项目动作**：把候选 registry 的状态机限定为 hypothesis、specified、tested、rejected、inconclusive、corroborated-research-only，不使用 proven/ready。每次实验先保存五阶段记录和竞争解释，再执行任何允许的研究；模型选择流程本身作为被评价对象，失败候选和 ad hoc 修改保留。对人工 forecast 强制定义截止时点、最大 adverse move、目标幅度和先后触达规则。证据评审先排除 leakage、sampling luck、multiple testing、trend/beta、cost omission 和 implementation error，再讨论机制；任何 current-HEAD gate 另走 backtest evidence contract。
- **禁止直接采用**：不得把单次盈利、统计显著、传统权威、历史拟合或“尚未被反驳”写成证明；不得在结果已知后补 null、成功阈值、解释或 exclusion rule。不得把 200 日均线、头肩形态、伪价格案例或旧论文结果直接迁移为 BTC/美股候选通过证据，不得用“客观且显著”绕过 Portfolio/Risk、OMS、Fill/Ledger 和 promotion gate。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原载体复核结论**：`FORM-RES02-CH03-001`—`030`已回到原PDF关闭为`verified_concept_only`。正文为PDF页108—168（印刷页103—163）。形式逻辑的肯定前件、否定后件、肯定后件谬误和否定前件谬误均已视觉核对；但作者把概率性市场检验类比为演绎反证时表述过强，项目要求辅助假设、误差率、功效、依赖、模型错设与`inconclusive`状态。五阶段流程位于PDF页149—152；头肩客观化案例位于PDF页153—167，包含过滤波、峰谷、垂直/水平对称、完成时限与look-ahead控制，均只是历史方法示例。PDF页167—168的TA四分类缺PIT、成本、容量、risk、ledger和current-HEAD gate，不能映射为promotion readiness。

## Ch03 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页108—168，Ch04从PDF页169开始。
- 结论边界：本章建立研究论证与记录结构，不验证任何技术规则。严格逻辑反证只适用于真前提和确定蕴含；随机市场结果通常只能在预注册统计模型下概率性挑战主张。

| ID | 原 PDF 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH03-001` | PDF页108 | 科学方法不是自动发现知识的cookbook。 | 流程合规不等于候选有效。 | `verified_concept_only` |
| `FORM-RES02-CH03-002` | PDF页109—111；Fig.3.1 | 权威/传统不能替代矛盾观察。 | 当前证据优先于旧书与专家。 | `verified_concept_only` |
| `FORM-RES02-CH03-003` | PDF页109—112 | ad hoc补丁可追随旧事实。 | 修改计新trial并保留旧版本。 | `verified_concept_only` |
| `FORM-RES02-CH03-004` | PDF页112—114 | 公共可复核观察优于私人解释。 | 保存data/code/params/run/hash。 | `verified_concept_only` |
| `FORM-RES02-CH03-005` | PDF页112—114 | 简约只在证据可比时优先。 | 不以简单替代OOS/cost/risk证据。 | `verified_concept_only` |
| `FORM-RES02-CH03-006` | PDF页113—115 | 科学知识强调公共验证并承认不完全客观。 | 保存observer和measurement边界。 | `verified_concept_only` |
| `FORM-RES02-CH03-007` | PDF页114—115 | 经验主张与公理恒等式不同。 | 公式正确不证明市场假设。 | `verified_concept_only` |
| `FORM-RES02-CH03-008` | PDF页115；`Y=f(X)` | 预测关系与解释机制回答不同问题。 | 通式不作实现规格。 | `verified_concept_only` |
| `FORM-RES02-CH03-009` | PDF页116 | 权威和传统不是规则证明。 | 引用只作provenance。 | `verified_concept_only` |
| `FORM-RES02-CH03-010` | PDF页116 | 二值逻辑要求定义完备。 | 允许unknown/inconclusive/misspecified。 | `verified_concept_only` |
| `FORM-RES02-CH03-011` | PDF页117 | proposition与argument结构已核。 | 拆分前提、预测和结论。 | `verified_concept_only` |
| `FORM-RES02-CH03-012` | PDF页117—120；Figs.3.2—3.3 | 有效演绎要求前提真。 | 同时验证前提数据与实现。 | `verified_concept_only` |
| `FORM-RES02-CH03-013` | PDF页121—122；Figs.3.4—3.5 | `A→B,A⇒B`为有效形式。 | 只推导冻结的observable prediction。 | `verified_concept_only` |
| `FORM-RES02-CH03-014` | PDF页122—123；Figs.3.4—3.5 | `A→B,¬B⇒¬A`为有效形式。 | 概率结果需误差控制，非单次逻辑反证。 | `verified_concept_only` |
| `FORM-RES02-CH03-015` | PDF页123—125 | 肯定后件不能由盈利推出预测力。 | 排查运气、泄漏、挖掘和暴露。 | `verified_concept_only` |
| `FORM-RES02-CH03-016` | PDF页124—125 | 否定前件不能推出后件为假。 | 一个机制失败不排除其他机制。 | `verified_concept_only` |
| `FORM-RES02-CH03-017` | PDF页126—128 | 归纳外推固有不确定性。 | 保存总体、采样和regime边界。 | `verified_concept_only` |
| `FORM-RES02-CH03-018` | PDF页128 | `700/1000=0.7`是历史频率示例。 | effective n、依赖与CI另报。 | `verified_concept_only` |
| `FORM-RES02-CH03-019` | PDF页135—137 | Popper式反证结构已核。 | 冻结条件、辅助假设与operation。 | `verified_concept_only` |
| `FORM-RES02-CH03-020` | PDF页136—137 | 同一观察可符合多个假设。 | 保留竞争解释和区分性预测。 | `verified_concept_only` |
| `FORM-RES02-CH03-021` | PDF页137 | 黑天鹅逻辑挑战无例外命题。 | 统计反例先排查噪声和data error。 | `verified_concept_only` |
| `FORM-RES02-CH03-022` | PDF页137—140 | 科学结论暂时且可修订。 | 使用corroborated-research-only。 | `verified_concept_only` |
| `FORM-RES02-CH03-023` | PDF页139—143 | 可检验主张必须排除某些未来结果。 | 保存horizon/threshold/expiry/error。 | `verified_concept_only` |
| `FORM-RES02-CH03-024` | PDF页144 | null作为“无新发现”起点。 | 另存effect/equivalence/misspecification。 | `verified_concept_only` |
| `FORM-RES02-CH03-025` | PDF页144—148 | 冲突证据应公开拒绝、缩小或修订。 | 修改即新版本/new trial。 | `verified_concept_only` |
| `FORM-RES02-CH03-026` | PDF页149—152 | 五阶段流程已核。 | 字段、clock、owner和hash齐全。 | `verified_concept_only` |
| `FORM-RES02-CH03-027` | PDF页150—151 | 200日均线盈利不能证明预测力。 | 参数、市场背景和结果不迁移。 | `verified_concept_only` |
| `FORM-RES02-CH03-028` | PDF页152 | 先排除sampling luck与data mining。 | 另查PIT、cost、capacity和实现。 | `verified_concept_only` |
| `FORM-RES02-CH03-029` | PDF页152 | 一致观察仅暂时支持主张。 | 区分rejected/inconclusive/corroborated。 | `verified_concept_only` |
| `FORM-RES02-CH03-030` | PDF页153—168；Figs.3.6—3.16 | 头肩客观化需包含/排除、对称、完成与no-lookahead规则。 | 历史过滤器/阈值/结果不迁移，TA分类非gate。 | `verified_concept_only` |

## 已完成 L2：第 4 章

### 第 4 章：抽样分布、标准误与金融时间序列依赖

- **论证链**：本章从总体、样本、总体参数、样本统计量、推断及可靠性声明六要素解释统计推断。样本均值会因抽到的观察不同而变化，所有可能同样大小样本的统计量分布构成 sampling distribution，其宽度量化抽样不确定性。经典框架以大数定律、中心极限定理和 `SE=σ/√n` 连接样本量、总体波动与均值标准误，并以 bootstrap/permutation 作为单一样本下近似抽样分布的计算方法。稳定结论是“点估计必须伴随其抽样机制和不确定性”，不是“历史日收益天然是随机独立样本”。
- **成立条件**：每项研究必须先定义 estimand、目标总体/时间范围、sampling unit、观察可得性、统计量、依赖结构和推断目标。均值、方差、标准差、标准误、年化与置信区间必须使用一致单位和明确分母；样本标准差的 `n-1` 修正只处理有限样本方差估计，不修复非平稳或依赖。应用 LLN/CLT 前至少检查 serial/cross-sectional dependence、heteroskedasticity、tail、cluster、overlap、regime 和有效样本数；不满足 IID 时使用与数据生成结构匹配的 HAC、cluster 或 block 方法并记录参数与诊断。
- **局限与反例**：书中的珠子随机抽样可重复、同分布且总体固定，历史金融路径只有一条、按时间到达且总体会变化；“immediate practical future”不是可观察固定总体。`σ/√n`、普通 bootstrap 和随机 permutation 在自相关、波动聚集、重叠持仓、共同市场因子和事件簇下会低估不确定性。大样本不自动消除结构突变、data snooping、未来函数或坏数据；CLT 的收敛速度在重尾和强依赖下可能很慢。均值对正向离群和稀疏巨额收益敏感，正态近似与 68/95 经验法则不能直接用于收益尾部。
- **项目动作**：证据包增加 `EstimandAndSamplingEvidence`，保存 population claim、sample construction、time/entity clusters、statistic、units、dependency diagnostics、effective_n、resampling scheme、seed/repetitions 和 interval method。均值同时配 median、trimmed/winsorized challenger、tail contribution、block stability 和 regime 分解；标准误至少比较 naive IID 与 dependence-aware 版本。用 synthetic IID、AR、GARCH、clustered event、overlapping return、single outlier、structural break 和 missing/correction fixture 检查区间覆盖与统计量稳定性，但当前不运行策略回测。
- **禁止直接采用**：不得把观察数、bar 数、trade 数直接当独立 `n`，不得复制书中 sample size、正态假设、`SE=σ/√n`、68/95 区间或普通逐行 bootstrap。不得因样本大就宣称不确定性小，也不得将 sampling distribution 的窄化写成经济稳健、可执行或 promotion 通过。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原载体复核结论**：`FORM-RES02-CH04-001`—`030`已回到原PDF关闭为`verified_concept_only`。正文为PDF页169—220（印刷页165—216）。Fig.4.14的样本均值为`x̄=Σx_i/n`；Fig.4.15用`n`描述当前样本的离散，Fig.4.34则用`n−1`估计未知总体标准差，二者用途不可混淆；Fig.4.35的`SE(x̄)=σ̂/√n`只适用于经典独立条件。原书把约30个观察作为CLT经验示意，不是通用门槛。连续变量的density值不是点概率，概率对应区间积分/面积。bootstrap近似sampling distribution但不天然生成null；permutation需要exchangeability，Monte Carlo需要明确DGP。所有历史样本量、珠子实验和正态68/95比例均不可迁移为市场参数。

## Ch04 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页169—220，Ch05从PDF页221开始。
- 结论边界：本章提供经典抽样推断框架，不证明金融收益IID、stationary、finite variance或normal。任何标准误和重采样结果必须绑定实际依赖、selection和sample construction。

| ID | 原 PDF 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH04-001` | PDF页169—176；Figs.4.1—4.4 | 推断量化样本外推的不确定性。 | 多规则需selection-aware distribution。 | `verified_concept_only` |
| `FORM-RES02-CH04-002` | PDF页177—193；Figs.4.5—4.13 | statistic推断parameter并附可靠性。 | 明确estimand、population和sampling unit。 | `verified_concept_only` |
| `FORM-RES02-CH04-003` | PDF页177—180；Fig.4.5 | 放回、混匀和等机会构造随机样本。 | 金融路径不具该物理机制。 | `verified_concept_only` |
| `FORM-RES02-CH04-004` | PDF页179—180 | random variable是概率实验数值结果。 | 保存support/unit/clock/law。 | `verified_concept_only` |
| `FORM-RES02-CH04-005` | PDF页179—183；Table 4.1 | statistic随样本改变而随机。 | 冻结统计量和sample construction。 | `verified_concept_only` |
| `FORM-RES02-CH04-006` | PDF页190 | 推断六要素已核。 | 六要素不替代PIT/cost/selection。 | `verified_concept_only` |
| `FORM-RES02-CH04-007` | PDF页190—192；Fig.4.12 | “immediate practical future”是不可直接观察总体。 | 明确时间、市场、regime和DGP。 | `verified_concept_only` |
| `FORM-RES02-CH04-008` | PDF页190—193 | 历史样本须代表目标总体。 | 检查coverage、break和drift。 | `verified_concept_only` |
| `FORM-RES02-CH04-009` | PDF页192—194；Fig.4.13 | parameter未知、statistic可观察。 | 不把样本最优值当真值。 | `verified_concept_only` |
| `FORM-RES02-CH04-010` | PDF页194—195 | 描述统计压缩样本。 | 保留tail/path/regime与原始数据。 | `verified_concept_only` |
| `FORM-RES02-CH04-011` | PDF页195；Fig.4.14 | `x̄=(x1+…+xn)/n=Σxi/n`。 | 核验units/weights/NaN/availability。 | `verified_concept_only` |
| `FORM-RES02-CH04-012` | PDF页195—197 | mean/median/mode回答不同问题。 | 联合稳健性，不挑有利者。 | `verified_concept_only` |
| `FORM-RES02-CH04-013` | PDF页195；Fig.4.14 | `n`为纳入求和的观测数。 | 不等同独立bets，另报effective n。 | `verified_concept_only` |
| `FORM-RES02-CH04-014` | PDF页196—197；Fig.4.16 | dispersion与center是不同属性。 | SD不覆盖tail/cluster/regime风险。 | `verified_concept_only` |
| `FORM-RES02-CH04-015` | PDF页196；Fig.4.15 | 描述性SD使用`n`。 | 与总体SD估计的`n−1`分开。 | `verified_concept_only` |
| `FORM-RES02-CH04-016` | PDF页197—200；Fig.4.17 | probability按长期相对频率解释。 | 单路径市场须定义repeatability。 | `verified_concept_only` |
| `FORM-RES02-CH04-017` | PDF页198—199；Fig.4.18 | LLN描述相对频率/均值收敛。 | 样本大不修复bias/drift/leakage。 | `verified_concept_only` |
| `FORM-RES02-CH04-018` | PDF页201—204；Figs.4.19—4.24 | density是连续分布密度。 | density值非点概率，声明base measure。 | `verified_concept_only` |
| `FORM-RES02-CH04-019` | PDF页204—206；Figs.4.24—4.26 | 区间概率等于密度面积。 | 核验support、atoms和积分边界。 | `verified_concept_only` |
| `FORM-RES02-CH04-020` | PDF页205—206；Figs.4.25—4.26 | 阈值以上概率对应尾部面积。 | 尾向和“更极端”须预登记。 | `verified_concept_only` |
| `FORM-RES02-CH04-021` | PDF页206—213；Figs.4.27—4.30 | sampling distribution绑定procedure/statistic/n。 | selection operator也改变分布。 | `verified_concept_only` |
| `FORM-RES02-CH04-022` | PDF页207—213；Figs.4.29—4.30 | mean distribution来自假想重复样本。 | 单一依赖路径需结构化近似。 | `verified_concept_only` |
| `FORM-RES02-CH04-023` | PDF页207—209；Figs.4.27—4.28 | 宽度量化sampling variability。 | 不覆盖全部model/data/selection误差。 | `verified_concept_only` |
| `FORM-RES02-CH04-024` | PDF页213—215；Fig.4.31 | 经典条件下样本大则均值分布窄。 | 使用effective n。 | `verified_concept_only` |
| `FORM-RES02-CH04-025` | PDF页215 | parent variation大则均值分布宽。 | 处理异方差、tail和break。 | `verified_concept_only` |
| `FORM-RES02-CH04-026` | PDF页215—217；Figs.4.32—4.33 | CLT是条件性渐近结果。 | “约30”不是统一门槛。 | `verified_concept_only` |
| `FORM-RES02-CH04-027` | PDF页216；Fig.4.32 | 正态约68%/95%区间已核。 | 仅正态参考，不套金融尾部。 | `verified_concept_only` |
| `FORM-RES02-CH04-028` | PDF页218；Fig.4.34 | `σ̂=sqrt(Σ(x_i−x̄)^2/(n−1))`。 | 修正不处理依赖/drift/heavy tail。 | `verified_concept_only` |
| `FORM-RES02-CH04-029` | PDF页218—219；Fig.4.35 | `SE(x̄)=σ̂/√n`。 | 依赖数据用HAC/cluster/block。 | `verified_concept_only` |
| `FORM-RES02-CH04-030` | PDF页219 | bootstrap/Monte Carlo/permutation语义不同。 | 保存unit/block/seed/repetitions/MC error。 | `verified_concept_only` |

## 已完成 L2：第 5 章

### 第 5 章：检验语义、重采样 null 与区间覆盖

- **论证链**：本章区分 hypothesis testing 与 estimation：前者检验预先指定的 H0，后者估计参数及区间。p 值是“假定 H0 与检验流程成立时，得到当前或更极端统计量的概率”，不是 H0 为真/假的概率。Type I 与 Type II error 体现错误拒绝与漏检之间的权衡；阈值应由错误成本和研究设计预先决定。bootstrap 对规则收益重采样，permutation 则打乱 signal 与未来市场收益的配对，二者测试不同 null；percentile bootstrap 以重采样统计量分位数构造区间。项目采纳这些结构，但纠正原文把 p 值近似解释为本次误拒绝概率、把未拒绝写成接受，以及把 realized frequentist CI 写成参数概率区间的表述。
- **成立条件**：检验前保存 H0/HA、effect definition、one/two-sided、test statistic、alpha、minimum effect、Type I/II loss、target power、sampling/resampling unit、repetitions/seed 和 multiple-testing family。p 值必须附 effect size、CI、样本/有效样本数和 assumption diagnostics；`fail to reject`、`reject` 与 `inconclusive` 分开。bootstrap 若要保留时间依赖须采用预注册 block/stationary/cluster 方案；permutation 只有在 H0 下交换性成立且不破坏 signal persistence、market regime、calendar 和 cross-rule correlation 时有效。Monte Carlo p 值需报告有限重复误差。
- **局限与反例**：小 p 值不表示 H0 很不可能，也不表示结果可交易、经济显著或可复现；大 p 值可能来自低功效、噪声大、样本小或检验错设。固定 0.05/0.01 标签和“Type I 总比 Type II 严重”不是通用决策规则，实际损失随风险、容量、机会成本和用途变化。普通 IID bootstrap 不能保留收益依赖，任意 permutation 会破坏波动状态和状态型信号；对数收益去趋势和全样本中心化仍可能泄漏。percentile CI 对偏差、偏斜、重尾和边界参数敏感；大样本 CLT 不能为所有 performance ratio 提供对称近似。样本均值无偏、有效或充分需要具体 DGP 条件，非平稳未来不由历史均值保证。
- **项目动作**：统一 `StatisticalTestEvidence` 与 `IntervalEvidence`：保存 null generator、exchangeability/block 依据、统计量方向、极端值计数、Monte Carlo standard error、CI 方法和 coverage target。对同一候选报告 point estimate、dependence-aware interval、practical significance 和 sensitivity；naive IID 只作对照。检验和 CI 不一致时不挑有利者，检查单双尾、偏斜、bias correction、依赖和实现。对 resampling 增加 seed replay、constant/no-signal、known effect、AR/GARCH、regime block、cross-rule correlation 和 finite-repetition fixture。
- **禁止直接采用**：不得复制书中 500/5000 次重采样、80/90/95% 区间、0.05 阈值、逐日 IID bootstrap、全排列打乱或 MA50/TT-4-91 案例；不得把 p 值称为 H0 为真概率、本次拒绝错误概率或 candidate 成功概率，不得把 realized frequentist CI 称为参数落入区间的后验概率。不得写“接受 H0”或仅凭未显著判定无效。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原载体复核结论**：`FORM-RES02-CH05-001`—`030`已回到原PDF关闭为`verified_concept_only`。正文为PDF页221—257（印刷页217—253）。p值的右尾面积与H0条件已视觉核对，但原文把小p与“更有信心拒绝H0”及本次错误概率联系得过强，项目明确禁止解释为`P(H0|data)`或本次拒绝错误概率。H0/HA互斥穷尽是检验规格，不保证模型无错设；高p只能`fail_to_reject`。ordinary bootstrap、White-style centering和Monte Carlo permutation案例分别位于PDF页238—247，书中1,231观察、5,000次、具体规则收益与p值均不可迁移。频率学CI的coverage是重复程序性质，realized interval不能给固定参数赋90%/99%后验概率；percentile bootstrap还需检验bias、skew、tail和coverage。

## Ch05 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页221—257，Ch06从PDF页258开始。
- 结论边界：本章只提供单规则经典检验与估计框架。当前项目还需时间依赖、selection-aware null、multiple testing、成本、容量和current-HEAD evidence，任何显著结果均不自动晋级。

| ID | 原 PDF 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH05-001` | PDF页221—222 | testing与estimation回答不同问题。 | 检验、点估计和区间并列。 | `verified_concept_only` |
| `FORM-RES02-CH05-002` | PDF页221—222 | point与interval estimate已核。 | 报告effect、interval和method。 | `verified_concept_only` |
| `FORM-RES02-CH05-003` | PDF页222—223 | 确认例不能证明预测力。 | 保留null、竞争解释和falsifier。 | `verified_concept_only` |
| `FORM-RES02-CH05-004` | PDF页224 | hypothesis绑定未知parameter。 | 明确population/unit/direction。 | `verified_concept_only` |
| `FORM-RES02-CH05-005` | PDF页225—228；Figs.5.1—5.3 | `H0: expected return≤0`。 | 优先成本后minimum effect。 | `verified_concept_only` |
| `FORM-RES02-CH05-006` | PDF页225—226；Fig.5.1 | `HA: expected return>0`。 | 拒绝H0不识别机制或可执行性。 | `verified_concept_only` |
| `FORM-RES02-CH05-007` | PDF页227—229；Figs.5.2—5.3 | 以零作为least-favorable边界。 | 核验monotonicity和模型错设。 | `verified_concept_only` |
| `FORM-RES02-CH05-008` | PDF页231—232；Figs.5.5—5.6 | test三要素已核。 | 另存null generator和selection。 | `verified_concept_only` |
| `FORM-RES02-CH05-009` | PDF页232—235；Figs.5.6—5.8 | mean return作为test statistic。 | 另报稳健统计量和net-cost口径。 | `verified_concept_only` |
| `FORM-RES02-CH05-010` | PDF页233—235；Figs.5.7—5.8 | 偏离可能来自sampling或H0错误。 | 另查leakage/mining/exposure/data。 | `verified_concept_only` |
| `FORM-RES02-CH05-011` | PDF页235—236；Fig.5.9 | p值是H0下当前或更极端概率。 | 明确tail、ordering和conditioning。 | `verified_concept_only` |
| `FORM-RES02-CH05-012` | PDF页235—236 | alpha应事前定义。 | 与family/loss/power共同登记。 | `verified_concept_only` |
| `FORM-RES02-CH05-013` | PDF页235—237 | 原文对p值置信/错误语义过强。 | 禁止写H0概率或本次错误概率。 | `verified_concept_only` |
| `FORM-RES02-CH05-014` | PDF页235—236；Fig.5.9 | 单侧正收益使用右尾。 | 双侧/equivalence需不同极端域。 | `verified_concept_only` |
| `FORM-RES02-CH05-015` | PDF页236—237 | significance由p与alpha比较。 | 不等于经济显著或稳定。 | `verified_concept_only` |
| `FORM-RES02-CH05-016` | PDF页237；Fig.5.10 | Type I定义已核。 | 单检验alpha非family error。 | `verified_concept_only` |
| `FORM-RES02-CH05-017` | PDF页237；Fig.5.10 | Type II定义已核。 | 高p只fail-to-reject。 | `verified_concept_only` |
| `FORM-RES02-CH05-018` | PDF页238 | error loss决定alpha/power权衡。 | “Type I通常更重要”不普遍化。 | `verified_concept_only` |
| `FORM-RES02-CH05-019` | PDF页238—242；Figs.5.11—5.12 | centered bootstrap构造零均值null。 | dependence/selection/centering需匹配。 | `verified_concept_only` |
| `FORM-RES02-CH05-020` | PDF页239、243—247；Figs.5.13—5.15 | permutation随机重配state与return。 | 需exchangeability和结构保持。 | `verified_concept_only` |
| `FORM-RES02-CH05-021` | PDF页240—241；Fig.5.11 | bootstrap输入为interval returns。 | 保存cost/clock/state/centering lineage。 | `verified_concept_only` |
| `FORM-RES02-CH05-022` | PDF页240—242；Fig.5.11 | ordinary bootstrap有放回同长度抽样。 | 时间数据使用block/cluster。 | `verified_concept_only` |
| `FORM-RES02-CH05-023` | PDF页240—242；Figs.5.11—5.12 | resampled statistics形成经验分布。 | 5,000次非参数，报告MC error。 | `verified_concept_only` |
| `FORM-RES02-CH05-024` | PDF页243—247；Figs.5.13—5.15 | permutation无放回重排配对。 | 多规则保持共同置换与selection。 | `verified_concept_only` |
| `FORM-RES02-CH05-025` | PDF页243—244；Fig.5.13 | 随机配对依赖exchangeability。 | regime/calendar/overlap可使其失效。 | `verified_concept_only` |
| `FORM-RES02-CH05-026` | PDF页242、247；Figs.5.12、5.14 | empirical p为达到/超过观察值比例。 | 加一修正并报MC interval。 | `verified_concept_only` |
| `FORM-RES02-CH05-027` | PDF页247—248；Fig.5.15 | sample mean作point estimator。 | 非平稳/selection下性质不保证。 | `verified_concept_only` |
| `FORM-RES02-CH05-028` | PDF页248—249 | unbiased/consistent/efficient/sufficient已核。 | 性质绑定具体DGP和model class。 | `verified_concept_only` |
| `FORM-RES02-CH05-029` | PDF页249—253；Figs.5.16—5.20 | CI coverage是重复程序长期性质。 | realized CI非参数后验概率。 | `verified_concept_only` |
| `FORM-RES02-CH05-030` | PDF页253—257；Figs.5.21—5.23 | percentile bootstrap按分位数截尾。 | 检查bias/skew/tail/coverage和alpha匹配。 | `verified_concept_only` |

## 已完成 L2：第 6 章

### 第 6 章：赢家诅咒、完整 trial universe 与 selection-aware 证据

- **论证链**：本章定义 data-mining bias 为按历史表现从多规则中选出的赢家，其观察表现相对未来期望表现的系统正偏。单个预先指定估计量的随机误差可正可负，但选择最大值后，噪声中的正向分量被主动保留，观察表现同时承担“选择”和“估计”两种角色便失去普通单规则推断语义。偏差由五项共同决定：测试规则数越多越大、有效观察越多越小、候选收益相关越低越大、正向离群越强越大、候选真实 merit 越相近越大。章节比较 holdout/walk-forward、Markowitz-Xu shrinkage、WRC 与 multi-rule permutation；稳定结论是完整搜索空间必须进入 null 和评估流程。
- **成立条件**：trial universe 必须包含所有规则家族、方向反转、参数、feature、label、cost、split、seed、metric、人工排除和中途修改；保存每个候选的 interval return/prediction、选择指标、相关结构和失败原因。selection procedure 在训练/内层验证中冻结，外层数据只评价完整流程；最终 holdout 由独立 owner 一次性解封，任何查看后再选择都会使其失去 virgin 状态。selection-aware 检验必须保持候选间相关、时间依赖和实际 winner-selection operator，并与简单 incumbent/placebo 比较。WRC/MCP 只作历史方法候选，需与现代 SPA/stepdown/DSR/PBO/CPCV 等当前项目规范交叉复核后才能采用。
- **局限与反例**：书中“更多规则通常更可能找到好规则”需要存在真实 merit 分散、足够样本和正确评价；在纯噪声、泄漏或错误指标上只会更可靠地挑中幻觉。所谓单规则测试若规则来自先验探索、书籍筛选、人工记忆或共享历史，也已属于隐藏多重试验。OOS 只有在未被触碰、分布目标仍相关且无泄漏时才近似无偏；checkerboard 切分会跨时间泄漏，walk-forward test 段也可能重叠或被反复消费。WRC 的共同零均值 null、中心化与普通逐日 bootstrap、MCP 的全局随机配对和旧式 500 次模拟都可能不适配依赖/非平稳数据；初版 WRC/MCP 还会因大量劣质高方差规则损失 power。MX shrinkage 原文也承认可能严重失真。
- **项目动作**：候选 registry 自动生成 immutable `trial_id` 和 family hash，实验报告同时输出 total/effective trial count、candidate correlation、winner gap、positive-outlier contribution、selection metric 与 nested-OOS dispersion。将所有变体的 fold-level prediction/return 保留为 selection-aware evidence，不只留冠军。holdout access ledger 与 candidate freeze hash 强绑定；一旦解封，不允许回到同一 gate 调参。建立 pure-noise、one-true-rule、correlated duplicates、inverse rules、high-variance loser、positive outlier、small/large effective-n 和 repeated-holdout synthetic fixture验证校正方法，但不在本轮运行真实策略回测。
- **禁止直接采用**：不得只报告赢家、把相关候选简单按名义数量或完全忽略、把 OOS 标签用于多轮筛选、把 walk-forward 每折结果反向调参或把书籍/论文筛选当成零 trial。不得复制 S&P 规则宇宙、MX shrinkage、WRC/MCP 实现、500 次模拟、随机日重采样或书中实验偏差数字；不得把 selection-adjusted 显著称为 promotion ready。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原始PDF复核结论**：`FORM-RES02-CH06-001`—`030`均关闭为`verified_concept_only`。稳定结论是保存完整trial universe并以复制winner operator的selection-aware null评价，不是迁移书中模拟偏差。五因素只保留方向；真实merit不可观察。MX公式`H′=R+B(H−R)`已视觉核对但不采用；WRC/MCP仅作历史候选，项目仍需依赖保持、完整候选矩阵、现代SPA/stepdown/DSR/PBO/CPCV和独立holdout治理交叉验证。本轮未运行回测、未读取holdout。

## Ch06 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页258—333，Ch07从PDF页334开始。
- 视觉覆盖：76/76页，9张contact sheet；未发现缺页或渲染缺陷。
- 证据边界：历史ATR/S&P 1928—2003、3.97%、月份数、规则数、模拟偏差和旧方法实现均不可迁移；只提取研究治理与selection-aware推断合同。

| 复核项 | 原PDF位置 | 已核结论 | 项目边界 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH06-001`—`005` | PDF页258—268 | 赢家选择、bias定义、客观方法失效、OOS下降、merit+luck | 单路径不识别bias；保留regime/cost/data竞争解释 | `verified_concept_only` |
| `FORM-RES02-CH06-006`—`010` | PDF页267—275 | 搜索空间、收益风险、隐性trial、双重角色、选择估计复用 | 人工分支也计trial；外层评价完整选择流程 | `verified_concept_only` |
| `FORM-RES02-CH06-011`—`014` | PDF页275—293 | 随机/系统误差、maximum null、两成因、五因素 | null复制依赖与winner operator；五因素只作方向 | `verified_concept_only` |
| `FORM-RES02-CH06-015`—`019` | PDF页291—323 | trial数、effective n、相关、正向尾部、merit dispersion | 保存全候选矩阵、tail贡献、winner gap与不确定性 | `verified_concept_only` |
| `FORM-RES02-CH06-020`—`024` | PDF页294—326 | 模拟边界、校正分类、OOS、walk-forward、holdout消费 | 历史数值不迁移；nested selection与one-shot holdout | `verified_concept_only` |
| `FORM-RES02-CH06-025`—`030` | PDF页326—333 | MX、WRC、完整universe、MCP、power、版本来源 | 旧方法不直接采用；验证依赖、power、实现与现代替代 | `verified_concept_only` |

## 已完成 L2：第 7 章

### 第 7 章：竞争价格机制、套利限制与风险溢价边界

- **论证链**：本章先指出价格存在某种非随机性只是 TA 可能有效的必要条件，任何具体规则仍需独立证据。科学理论必须解释既有事实并对新观察提出可证伪预测；“历史会重复”“价格反映一切”等宽泛口号不能承担机制。章节把 EMH/random walk 与行为金融作为竞争解释，讨论 underreaction、overreaction、anchoring、representativeness、disposition、herding/information cascade、positive feedback、noise-trader risk 和 limits to arbitrage，最后区分错误定价收益与 equity、hedging、liquidity、price-discovery 等风险/服务溢价。
- **成立条件**：每个候选保存 `edge_type`、mechanism、causal chain、可观察代理、horizon、受影响资产/参与者、风险承担、capacity、crowding、反事实和失效条件。行为机制必须落到事前可测的 news surprise、attention、ownership、flow、liquidity、short constraint、arbitrage capital、volume/price response 等代理，并与 risk premium、beta、liquidity、funding 和 data snooping 竞争。机制证据与预测证据分开；理论只能提高可解释性和外部验证优先级，不能提高统计结果本身。
- **局限与反例**：同一 momentum/reversal 事实可被信息扩散、风险补偿、正反馈、制度约束或数据偏差解释，单一回报形状不识别机制。行为偏差存在不代表价格可交易预测，个体非理性也可被聚合、套利或成本抵消；风险溢价可持续但伴随真实尾部/流动性风险，不能命名为无风险 alpha。书中 2007 年前的 EMH、行为金融论文与商品期货论断是历史综述，不证明当前 BTC 或美股状态。理论越精致也可能越容易事后包办解释。
- **项目动作**：候选 registry 增加 `mispricing`、`risk_premium`、`liquidity_service`、`information_diffusion`、`institutional_constraint` 和 `unknown` 互斥主标签，并保存竞争标签。对 momentum、reversal 或 divergence 候选执行 state/event interaction、proxy falsification、placebo、lead-lag、risk exposure、cost/capacity 和 regime stability 设计；预测失效但机制代理成立时仍判候选失败，不以故事挽救。Portfolio/Risk 对风险溢价候选单列 crash、liquidity、funding 和 crowding budget。
- **禁止直接采用**：不得把“市场非随机”“投资者有偏差”“套利有限”或风险溢价存在直接转成 Signal；不得复制书中 momentum horizon、52 周高点、volume confirmation、behavioral threshold、期货趋势收益或 countertrend 规则。不得把未被风险模型解释的收益自动称 mispricing，也不得把可持续风险补偿称 alpha。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原始PDF复核结论**：`FORM-RES02-CH07-001`—`030`均关闭为`verified_concept_only`。稳定结论是理论只能生成可证伪机制候选，不能由非随机性、行为偏差或风险溢价直接推出具体Signal。EMH检验依赖information set、risk model与benchmark；同一momentum/reversal可由扩散、风险补偿、反馈、约束或数据偏差解释。BSV/DHS/HS与MLM等历史模型、期限、收益和图表不迁移。本轮未运行回测、未读取holdout。

## Ch07 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页334—389，Ch08从PDF页390开始。
- 视觉覆盖：56/56页，7张contact sheet；未发现缺页或渲染缺陷，PDF页389为Part II分隔页。
- 证据边界：2007年前EMH/行为金融研究、S&P/股票/期货样本、momentum期限、MLM指数、收益和风险调整数字均仅作历史来源；不构成BTC、美股策略或风险预算。

| 复核项 | 原PDF位置 | 已核结论 | 项目边界 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH07-001`—`005` | PDF页334—337 | 非随机必要非充分、理论边界、可证伪预测、反ad-hoc、信息反映语义 | 理论只排序候选；固定信息集、时点与失败条件 | `verified_concept_only` |
| `FORM-RES02-CH07-006`—`010` | PDF页336—345、357—358 | underreaction、EMH/risk benchmark、random-walk语义、joint hypothesis | 区分IID/martingale；保存risk-model与benchmark敏感性 | `verified_concept_only` |
| `FORM-RES02-CH07-011`—`015` | PDF页345—351、358—359、365—369 | noise/liquidity、representativeness、disposition、herding、套利限制 | 行为proxy与common-information/risk/constraint竞争 | `verified_concept_only` |
| `FORM-RES02-CH07-016`—`020` | PDF页352—364 | 历史momentum、异质参与者、conservatism、anchoring、narrative | 历史样本不迁移；叙事不得改冻结评分规则 | `verified_concept_only` |
| `FORM-RES02-CH07-021`—`025` | PDF页364—373；Figs.7.9—7.11 | streak错觉、共同判断、cascade、feedback与尾部 | placebo/完整分母；区分外生信息和机械流 | `verified_concept_only` |
| `FORM-RES02-CH07-026`—`030` | PDF页374—388；Figs.7.12—7.15 | BSV/DHS/HS机制、风险/服务溢价与机制证据合同 | 模型名和历史数字不是证据；风险溢价与mispricing分账 | `verified_concept_only` |

## 已完成 L2：第 8 章

### 第 8 章：规则生成器、搜索空间 provenance 与案例不可迁移性

- **论证链**：案例把 40 类 input series 经 moving average、channel breakout、channel normalization、crossing/state operators 转换为 trend、extreme/transition 和 divergence 三类 long/short 规则，并枚举传统/反向、lookback、threshold displacement 和 companion series，形成 6,402 个明确命名候选。其核心价值是让每个候选和完整规则宇宙可重建，从而使 WRC/MCP 的 maximum-statistic null 有输入。作者也承认 prior-research snooping 无法完全消除、全样本 detrending 被用于评价、复杂规则未纳入且 always-in-market 二元结构限制表达。
- **成立条件**：现代 `RuleGeneratorEvidence` 必须保存 input data lineage/availability、transform DAG、operator/version、parameter domains、state initialization、equality/missing rules、direction inversion、candidate count、family hash 和 deterministic enumeration checksum。所有 input 数据必须 PIT、含 revision/constituent/corporate-action 语义；transform、threshold 和 normalization 按训练折拟合。每个候选保存 fold-level prediction/return、cost、exposure、selection metric 和失败状态，生成器的任何代码/参数变化产生新 universe version。
- **局限与反例**：作者主动避开已发表规则不能消除其阅读记忆和共同历史数据造成的隐性 snooping；书籍本身被本项目读取后也成为 prior research，故 6,402 规则不能被视为 fresh hypothesis。全样本平均收益 detrending 泄漏未来，日频 next-open 不覆盖 auction、gap、BTC 24/7 和真实冲击；零成本 signal-return 不能评价可执行策略。40 个输入、三类主题、固定 lookback/threshold、简单规则和 S&P 单市场均是案例边界。channel normalization、reciprocal 和 divergence 会改变单位、tail 和 lead-lag，需独立验证。
- **项目动作**：将规则研究实现为 declarative spec→deterministic candidate registry，而不是在回测循环中临时拼参数。生成前冻结数据 manifest、candidate domains、方向、成本、split 和 selection operator；生成后输出完整候选清单及 hash，任何人工删除保留 reason。传统/反向、long/neutral、short/neutral 和 abstention 版本分别登记；复杂组合另走 nested selection，不能顺手叠加。书中规则仅用于生成测试 fixture 与 governance schema，不进入候选库默认值。
- **禁止直接采用**：不得复制 6,402 数量、1980—2005 数据、40 个 input、移动平均/突破跨度、10/20 threshold displacement、15/30/60 normalization、traditional/inverse 方向或 S&P 结果；不得把全枚举称为穷尽所有 TA，也不得因命名完整就声称无 snooping。不得使用全样本 detrend、零成本收益、指数不可成交价格或无 revision 证明。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原始PDF复核结论**：`FORM-RES02-CH08-001`—`030`均关闭为`verified_concept_only`。稳定结论是规则必须由可声明、可重建的data→transform→operator→state→candidate pipeline生成，并保存完整候选宇宙，而不是迁移6,402数量或任何S&P规则。MA/LMA、CBO、CN、双重CN divergence公式及858/2,808/2,736计数已视觉核对；全样本去趋势被明确标记为未来泄漏，所有历史输入、窗口、阈值和方向均禁用。本轮未运行回测、未读取holdout。

## Ch08 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页390—441，Ch09从PDF页442开始。
- 视觉覆盖：52/52页，7张contact sheet；未发现缺页或渲染缺陷，公式、Tables8.1—8.4与Figs.8.1—8.30均可辨认。
- 证据边界：1980—2005 S&P样本、40项输入、11个lookback、阈值、四日LMA、双重CN、规则数与历史显著性均不迁移；仅提取生成器和provenance合同。

| 复核项 | 原PDF位置 | 已核结论 | 项目边界 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH08-001`—`005` | PDF页390—392 | 案例目的、snooping、隐藏参数与prior-research边界 | 历史案例research-only；全部人工与文献分支计trial | `verified_concept_only` |
| `FORM-RES02-CH08-006`—`013` | PDF页392—395、405—419 | 输入族、三类规则、全样本去趋势、共同null与历史alpha | PIT lineage；全样本centering禁入在线流程 | `verified_concept_only` |
| `FORM-RES02-CH08-014`—`019` | PDF页395—405；Figs.8.1—8.8 | transform pipeline、schema、MA/LMA、CBO与CN公式 | 明确lag、窗口、equality、zero range与prefix invariance | `verified_concept_only` |
| `FORM-RES02-CH08-020`—`022` | PDF页405—419；Tables8.1—8.2 | raw/indicator输入及其历史构造 | 保存source/revision/calendar/units；输入表不证明预测力 | `verified_concept_only` |
| `FORM-RES02-CH08-023`—`027` | PDF页420—441；Table8.3 | 参数枚举、方向、E状态机、cross事件与组合计数 | declarative spec复算、dedup和stable ordering | `verified_concept_only` |
| `FORM-RES02-CH08-028`—`030` | PDF页430—441；Figs.8.24—8.30 | divergence、双重CN及生成器证据合同 | 对齐时钟/lag；历史公式不构成默认策略 | `verified_concept_only` |

## 已完成 L2：第 9 章

### 第 9 章：选择校正负结果、案例限制与嵌套复杂度搜索

- **论证链**：案例中最佳规则在普通单规则检验下看似极显著，但在复制 6,402 规则选择过程的 WRC/MCP null 下并未拒绝“所有规则无预测力”；约 320 个名义 5% 显著结果与随机 false positive 规模一致。稳定结论是赢家必须相对 maximum-of-N null 而非零中心单规则 null 评价，且“不显著”应保存为研究资产。作者随后明确案例限制：只测简单 always-long/short 规则、仅 S&P、prior-research snooping 只能缓解；复杂度增加必须经 train→test 选择并由未参与选择的 validation 评价。
- **成立条件**：结果报告必须同时保存 unadjusted 与 selection-adjusted effect/p/CI、完整 candidate count/correlation、resampling version/seed/repetitions、winner identity/gap、negative candidates 和 null distribution hash。结论用 `fail_to_reject_all_rules_null`，不写“证明全部规则无效”。复杂模型需内层参数搜索、外层复杂度选择和独立 outer validation；每次扩展 feature、market、rule family 或 complexity 都创建新 trial universe，旧结果不能充当未污染 validation。
- **局限与反例**：书中 p 值、11% null 中心、15%显著阈值、1,999 次 replication 和 320 个 false positives 都是该规则宇宙、相关、样本与实现的历史结果，完全不可外推。WRC/MCP 相近不证明其共同假设正确；普通 daily resampling、全样本 detrend、成本缺失和 80% CI 仍限制证据。未拒绝共同 null 可能源于低 power 或候选质量差，不证明 TA/非随机性不存在。作者推崇复杂规则，但复杂度更高同时扩大搜索空间、泄漏和不可执行风险，不能视为默认优越。
- **项目动作**：负结果进入 immutable strategy registry，保存 rejected/inconclusive 原因和避免重复探索的 universe hash。报告模板强制并列 single-trial、family-adjusted、economic threshold、cost/capacity、risk exposure 和 holdout status；任何表格按 winner 排序时仍展示 selection-adjusted 列。复杂模型采用 nested purged/embargo workflow，最外层只评价完整建模流程；validation 被用于 complexity selection 后不再称 holdout。人机协作仅用于提出可证伪 feature/target spec，LLM 或专家不能修改已冻结评分规则。
- **禁止直接采用**：不得迁移最佳规则 E-12-28-10-30、任何收益/p 值/CI/显著阈值、作者建议的复杂组合或市场扩展；不得把 6,402 规则负结果写成当前美股/BTC 结论，也不得把普通 p 值显著候选重新捞回。不得因 WRC/MCP 未拒绝而缩小 trial family、换市场或增加复杂度后继续使用同一验证数据。当前不运行新回测、不查看或污染 holdout、不访问 private/order/paper/live endpoint，安全旗标保持 false。
- **原始PDF复核结论**：`FORM-RES02-CH09-001`—`030`均关闭为`verified_concept_only`。稳定结论是负结果必须连同完整family、普通与selection-adjusted证据、方法版本、限制和失败候选一起保存；不能把fail-to-reject写成证明无效，也不能因结果不佳缩小family、换市场、换复杂度后复用验证集。WRC/MCP p值、null中心、15%/17%阈值、80%区间、320个名义false positives和所有规则结果均为历史案例。复杂度选择必须nested，validation一经用于选择即被消费。本轮未运行回测、未读取holdout。

## Ch09 原始 PDF 复核

- 来源：原PDF SHA256 `8896ace097b7a9e185f337673e373784d592f5645203b234f2614dea1b1d4fb2`；正文PDF页442—474；附录PDF页475—476已由`FORM-RES02-CH01-021`覆盖，Notes从PDF页477开始。
- 视觉覆盖：正文33/33页、附录2/2页，共35/35页，5张contact sheet；未发现缺页或渲染缺陷，Figs.9.1—9.10和Table9.1均可辨认。
- 证据边界：最佳规则、10.25%、WRC/MCP p值、1,999次replication、11% null中心、15%/17%阈值、80%区间、320个名义false positives及所有专家/模型历史数字均不可迁移。

| 复核项 | 原PDF位置 | 已核结论 | 项目边界 | 状态 |
|---|---|---|---|---|
| `FORM-RES02-CH09-001`—`009` | PDF页442—445；Figs.9.1—9.3 | 目标边界、共同null、赢家maximum、WRC/MCP、阈值与naive false positives | 只写fail-to-reject；全部历史数字禁用 | `verified_concept_only` |
| `FORM-RES02-CH09-010`—`012` | PDF页445—448；Table9.1 | 结果表、普通/校正证据及selection-aware区间 | 项目补成本/风险/HEAD并验证coverage与实现 | `verified_concept_only` |
| `FORM-RES02-CH09-013`—`017` | PDF页449—451 | benchmark、detrending、next-open、完整family及prior snooping | 全样本centering仅ex-post；PIT/执行/current method另证 | `verified_concept_only` |
| `FORM-RES02-CH09-018`—`022` | PDF页451—453 | 复杂规则、neutral、单市场及扩展猜想限制 | 简单规则负结果不外推；新市场/indicator创建新family | `verified_concept_only` |
| `FORM-RES02-CH09-023`—`027` | PDF页453—462；Figs.9.4—9.8 | 组合规则、非线性搜索、三分数据、复杂度选择和validation消费 | nested purged/embargo；外层评价完整流程 | `verified_concept_only` |
| `FORM-RES02-CH09-028`—`030` | PDF页462—474；Figs.9.9—9.10 | 人机协作、feature trial与负结果合同 | 专家/LLM只提交冻结spec；失败结果immutable保留 | `verified_concept_only` |

## 全书复核状态

RES-02 已完成9/9章`L2`和270/270项原PDF概念级`L3`，知识卡达到`original_pdf_formula_review_complete_concept_only`。这不是公式实现、当前策略、回测、holdout、paper/live或promotion evidence；全部安全边界保持不变。全局书库下一步转入RES-03逐章原PDF复核。
