---
book_id: EXE-02
title: Algorithmic and High-Frequency Trading
authors: [Alvaro Cartea, Sebastian Jaimungal, Jose Penalva]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Algorithmic and High-Frequency Trading - Cartea Jaimungal Penalva - 原文.md
source_format: scanned_pdf_ocr_with_original_pdf_visual_reference
source_sha256: 307096356471db7fbd83df5f876ce28754204adb6873eb454b263a19d7d9469d
source_line_count: 29812
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\算法和高频交易 Algorithmic and High-frequency Trading ( etc.) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: 0fbff9d4e9fc9ed464b48a0c849c84ab5c28de6b430d8623b220d12b8d12d7aa
original_pdf_page_count: 338
card_status: chapter_semantic_review_l2_complete_formula_pending
chapter_count: 12
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 380_ch01_ch12_items_identified_ch05_ch12_original_pdf_visually_cross_checked_all_math_pending_appendix_blocked
last_reviewed_at: 2026-07-14
---

# EXE-02：Algorithmic and High-Frequency Trading

## 覆盖声明

本卡依据 OCR 目录、章节标题和打印页定位全部 12 章并完成 `L1` 项目映射与章节级 `L2`。第 1—4 章因原始扫描/OCR质量仅保留低可信非公式语义；第 5—12 章已分别用原始扫描 PDF 印刷页 89—118、121—141、144—167、168—192、194—225、228—253、255—276、277—294 逐节交叉核对，当前章节覆盖 `12/12=100%`，共登记 380 项待复核关系。全部控制、HJB/PIDE/QVI、停时、执行、做市、统计套利、订单不平衡及数值结果只完成语义核对，公式转录、正则性、边界条件、参数识别、当前数据校准和数值方法仍未通过 `L3`；附录数学公式继续阻塞，不得进入实现、回测参数或promotion。本书不覆盖 IT 实现，不能替代项目 OMS、权限、安全、reconciliation 或 replay 合同。

## 全书项目映射

- `diagnostic_value`：LOB、spread/depth、market impact、order flow、adverse selection、inventory risk 和 fill probability 可定义 execution diagnostics。
- `architecture_boundary`：Strategy 不得因本书模型直接发单；模型最多进入 OMS/Execution adapter，并受 Portfolio/Risk、权限与 ledger 约束。
- `evidence_boundary`：缺真实 L2/queue/private fills、latency 和 venue rules 时，最优执行、做市、stat-arb 只能 research-only/diagnostic。
- `rejected_for_now`：HFT、做市、暗池和 queue-position 策略当前不具 promotion 条件；不得调用 private/order/live endpoint 验证。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 电子交易市场和限价订单簿 | `1145-2235` | `L2/low` | 电子市场把资产/产品合约、参与者目的、订单语义、matching/priority、透明度、data tier、colocation、跨venue路由、fee与动态LOB连接起来；主动/被动订单不能直接识别交易者类型，静态spread/depth也不能证明可执行性。 | `electronic_market_and_lob_capability_contract`：按instrument/venue/rule version保存order type/TIF/display/routing、matching/auction、event identity/sequence/clock、L1/L2/trades、fee/rebate、access latency和cross-venue state；仅公共数据诊断。 | `FORM-EXE02-CH01-001`—`030`；spread/mid/microprice与历史venue事实待原PDF/当前规则复核 |
| 2 金融市场微观结构概述 | `2236-3807` | `L2/low` | 流动性与价格发现来自库存承接、参与竞争、订单冲击、信息不对称和交易者紧迫性的共同作用；inventory-risk、fee/participation cost、transient/permanent impact与adverse selection是不同机制，不能由单一spread或order-flow回归互相替代。 | `market_microstructure_mechanism_and_liquidity_attribution_contract`：按parent/order/fill/quote时钟保存inventory、risk/volatility、competition proxy、fixed/variable cost、impact/reversal/markout、information alternatives和no-trade elasticity；模型假设与现实证据分层。 | `FORM-EXE02-CH02-001`—`034`；Grossman–Miller/Kyle/Glosten–Milgrom公式与参数待原PDF复核 |
| 3 实证和统计证据：价格和回报 | `3808-5579` | `L2/low` | 从日频到毫秒的结论依赖data feed语义、事件重建、sampling clock、zero returns、tick尺度、latency path、venue fragmentation与模型选择；单日回归、ACF、转移频率或pair均值回归只能是描述性候选，不能从统计显著直接生成HFT信号。 | `high_frequency_price_evidence_contract`：保存source/feed tier、event/order identity、sequence/clock、snapshot rebuild、corporate actions、price/return definition、sampling rule、zero/stale observations、tick/lot、latency path、venue alignment、trial/model set和OOS反证。 | `FORM-EXE02-CH03-001`—`036`；return/microprice/tail/ACF/VAR等公式和历史统计待原PDF复核 |
| 4 实证和统计证据：交易活动和市场质量 | `5580-8546` | `L2/low` | volume/volatility季节性、quoted/effective spread、tick、depth、trade size、temporary/permanent impact、cancel/replace和hidden orders共同描述条件化market quality；每项都受sampling、session、event selection、display状态、跨venue路由和数据异常影响。 | `market_activity_and_execution_quality_evidence_contract`：按instrument/venue/session保存volume/event/price clocks、spread/depth/size、trade signing、parent aggregation、multi-horizon impact/recovery、cancel/fill/hidden state、halt/outage和data-quality flags；指标缺失不互相代填。 | `FORM-EXE02-CH04-001`—`040`；所有统计公式、历史数值和hidden/queue解释待原PDF/当前feed复核 |
| 5 随机最优控制和停时 | `8547-11314`；PDF 印刷页 `89-118` | `L2/medium` | 控制问题必须先定义状态、控制、可容许集、动力学、运行/终端目标和时域；DPP给出递归分解，HJB/DPE是无穷小形式，verification连接候选解与可容许最优控制；计数/跳扩散加入强度和跳跃，停时形成障碍/自由边界，控制与停时组合形成QVI。 | `stochastic_control_model_spec_contract`：任何候选必须提交state/control/admissibility/objective/dynamics/generator/terminal-boundary/verification/numerical-method/units/stability/feasibility清单；仅研究规格，不直接产生Signal或OrderIntent。 | `FORM-EXE02-CH05-001`—`030`；原页已核语义，逐式转录、正则性与数值解仍待独立验证 |
| 6 连续交易的最优执行 I | `11315-13323`；PDF 印刷页 `121-141` | `L2/medium` | 连续MO执行把inventory、midprice、execution price、cash与trading speed分开；temporary/permanent impact、terminal/running inventory penalty、utility和非线性冲击改变执行路径。恒速/TWAP只在强简化条件下出现，永久冲击不影响策略也是特定线性模型结论。 | `continuous_execution_model_evidence_contract`：按parent目标、方向、剩余量、期限、mid/fill/cash、impact、risk、terminal residual和feasible speed保存模型与实证；仅作simulator challenger，必须允许no-trade/abort。 | `FORM-EXE02-CH06-001`—`030`；原页已核语义，逐式转录、校准与数值稳定仍待验证 |
| 7 连续交易的最优执行 II | `13324-15517`；PDF 印刷页 `144-167` | `L2/medium` | 执行策略可加入价格上限停止、外生净订单流和明/暗池双场所；边界改变终端条件，订单流改变短期漂移，暗池以随机时点/数量减少库存但引入不成交与信息风险。模型中的即时边界清算、独立Poisson流和无冲击暗池均是强假设。 | `execution_state_and_venue_uncertainty_contract`：保存price barrier、net-flow state、inventory constraints、lit/dark quantities、fill-size/time distribution、queue/priority、fallback、leakage/toxicity和venue capability；当前dark/queue/private evidence缺失，保持rejected-for-now。 | `FORM-EXE02-CH07-001`—`030`；原页已核语义，PIDE/边界/暗池匹配假设仍待验证 |
| 8 限价单和市价单的最优执行 | `15518-17951`；PDF 印刷页 `168-192` | `L2/medium` | LO以价格改善交换不确定成交，MO以成交确定性承担spread/impact；LO-only模型用深度控制fill intensity，LO/MO模型形成继续挂单与冲动成交的QVI，计划跟踪再加入偏离目标的running penalty。触价、指数fill和单位成交均是模型化简。 | `order_choice_and_fill_evidence_contract`：按order lifecycle保存submit/queue/reprice/cancel/expire/partial/full fill、ahead volume、book events、decision/arrival/fill clocks、MO fallback、target deviation和ledger；缺MBO/private fill时只做diagnostic/synthetic stress。 | `FORM-EXE02-CH08-001`—`030`；原页已核语义，fill intensity/QVI/冲动时机仍待验证 |
| 9 以交易量为目标 | `17952-21185`；PDF 印刷页 `194-225` | `L2/medium` | 以市场瞬时成交速率占比（POV）和累计成交量占比为目标会产生不同路径；随机volume、agent自身成交、其他参与者price impact和风险偏好都会改变策略。VWAP接近只是在特定目标/模型下的结果，不是成本或best execution证明。 | `volume_target_execution_evidence_contract`：定义market-volume范围、venue/side/trade condition、self-volume、calendar/event clock、late corrections、forecast、target ratio/cap、cumulative error、impact和fallback；BTC 24/7按venue/regime估计且保留无交易状态。 | `FORM-EXE02-CH09-001`—`030`；原页已核语义，volume过程/benchmark/效用递归仍待验证 |
| 10 做市 | `21186-23528`；PDF 印刷页 `228-253` | `L2/medium` | 做市商在买卖两侧选择挂单深度、是否挂单与数量，以价差收入交换随机成交、库存风险和逆向选择；库存边界、效用目标、MO引起的价格跳跃与短期alpha都会改变报价。无库存惩罚的常数深度只是退化特例。 | `market_making_safety_and_evidence_contract`：双边private fills、queue/MBO、order latency、inventory/cash/hedge ledger、fees/rebates、post-fill markout、stale-quote cancel、reconcile、duplicate/overfill防护和kill/degraded mode缺一即`rejected_for_now`。 | `FORM-EXE02-CH10-001`—`030`；原页已核语义，报价/规模/DPE/效用映射与毒性校准仍待验证 |
| 11 配对交易和统计套利策略 | `23529-25474`；PDF 印刷页 `255-276` | `L2/medium` | 配对/统计套利是对协整或短期alpha持续性的风险下注，不是无风险套利；固定波段、OU最优停时和多资产效用最优组合分别依赖稳定关系、成本、终端状态与可交易约束。 | `relative_value_research_and_leg_risk_contract`：PIT universe/权重、formation-trading切分、break监测、borrow/funding/margin、factor暴露、多腿fill/legging、corporate action、全成本和basket ledger齐备前仅`research_only`。 | `FORM-EXE02-CH11-001`—`030`；原页已核语义，停时阈值/测度变换/组合反馈与实证校准仍待验证 |
| 12 订单不平衡 | `25475-27098`；PDF 印刷页 `277-294` | `L2/medium` | 显示买卖深度不平衡的定义、采样和分箱决定其统计性质；离散/连续马尔可夫链、条件MO到达和价格跳跃可描述短时状态，但单日相关与模型内清算改进不证明方向alpha或可成交性。 | `order_imbalance_execution_feature_contract`：固定depth/venue/clock/event语义，sequence-correct L2、snapshot age、cancel/hidden、state transition、latency-aware OOS与真实queue/fill/markout证据缺失时仅`diagnostic_only`。 | `FORM-EXE02-CH12-001`—`030`；原页已核语义，生成矩阵/联合似然/跳跃分布与LO深度仍待验证 |

## 已完成 L2：第 1 章

### 第 1 章：电子市场合约、限价订单簿与访问层级

- **论证链**：电子交易算法不能脱离所交易资产与产品合约。股票、债券、基金、ETF、期货、互换和期权在现金流、赎回/creation、投票、到期、清算与风险暴露上不同；参与者又可能因融资、配置、对冲、信息、套利或流动性服务而交易。书中把基本面/流动性、知情/套利和做市作为便于建模的行为类型，但分类依赖时间尺度，基本面大单在毫秒视角可像噪声，做市商也可能主动吃单，知情者也可能被动挂单。因此不能从 maker/taker、MO/LO 或短期盈亏反推身份和动机。
- **成立条件**：任何 LOB 诊断必须绑定 canonical instrument、venue、session、rule/capability version、tick/lot、order type/TIF、display/hidden、routing、matching/precedence、auction、fee/rebate、market-data tier/entitlement、source/exchange/receive clock、sequence、event/order identity、add/modify/cancel/fill、side/price/size和cross-venue state。price-time、pro-rata、designated priority、IOC/FOK/GTD、peg、hide-not-slide、iceberg和non-routable等语义均以当前venue文档为准；历史美国订单保护、tick、venue数量和数据接口不能迁移。
- **局限与反例**：静态 LOB 快照只显示已展示流动性，不含隐藏数量、撤单概率、queue position、其他 venue、latency race、self-impact或成交后恢复。quoted spread、midprice、microprice和top-level imbalance都是定义/代理，不是真实价值或可成交价格；OCR 已损坏其公式与符号，禁止复制。direct feed、consolidated feed、colocation和非托管访问具有不同延迟与成本，书中的“公平”描述不能证明当前参与者等速。大 MO 可能跨层、跨venue、部分成交、重路由或取消，显示深度不能保证到达时仍存在。
- **项目动作**：建立 `ElectronicMarketAndLOBCapabilityEvidence`：public market-data adapter保存raw event、sequence gap、clock quality、snapshot rebuild、book checksum、fee/rule manifest和data-tier provenance；诊断层按size×price×time输出spread、depth、book walk、staleness、event rate、cancel/fill和cross-venue divergence，并为不可识别queue/private fill明确blocked。Strategy不得从书中订单类型直接发单；未来OMS adapter仅在current capability、Portfolio/Risk授权、pre-trade limits、unknown-order reconcile和Fill/Ledger均就绪时解释OrderIntent。
- **禁止直接采用**：不得从2013年NASDAQ样本、书中股票、venue数量、美国/欧洲规则、tick、maker/taker费率或colocation叙事推断当前BTC、美股或A股市场；不得把主动订单等同知情交易、被动订单等同做市、mid/microprice等同fair value、显示深度等同fill probability。不得由本章运行HFT/做市/最优执行回测、改参数、访问holdout或调用private/order/paper/live endpoint；全部数学与历史数字继续 `blocked_pending_original_pdf`，安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH01-001`—`030`。

## 已完成 L2：第 2 章

### 第 2 章：库存承接、信息不对称与流动性成本归因

- **论证链**：市场微观结构研究在明确交易规则下，交易策略如何共同决定资产交换、价格、成交量、风险转移、流动性与价格发现。做市商通过双边报价承接暂时不匹配的需求并提供 immediacy，却在等待反向流时承担库存价格风险；Grossman–Miller 的简化模型据此把流动性折价与冲击规模、波动、风险厌恶、做市竞争和参与成本联系起来。Kyle 模型转向知情交易者如何把交易混入噪声/流动性订单，并在预见price impact后控制规模；Glosten–Milgrom 模型则说明竞争做市商会根据订单方向更新价值分布，价差补偿与更知情对手交易的 adverse selection。三类机制回答不同问题，不能把库存补偿、显性费用和信息毒性混成一个spread解释。
- **成立条件**：机制诊断必须固定 instrument/venue/session、parent objective、quote/book/fill clocks、order-flow signing、inventory/cash/hedge ledger、risk horizon、volatility、fee/rebate/participation cost、market-maker competition proxy、trade size/urgency、pre/post-trade mid/markout、impact decay、public event set和alternative information hypotheses。流动性需同时报告size、all-in cost、fill time/probability与recovery；transient impact、permanent repricing、bid/ask bounce和adverse-selection markout必须用预声明horizon区分。
- **局限与反例**：本章模型分别依赖少数日期、正态现金价值、指数效用、固定或外生order-arrival/fill函数、risk-neutral竞争做市商、price-insensitive liquidity traders、单位订单、二点终值、线性impact和无直接库存成本等强假设。静态均衡参数不是可观测结构常数；负收益自协方差可能来自spread bounce、异步交易或微观噪声，正向markout也可能来自公共新闻而非知情流。竞争增加通常压低租金，但低参与成本、maker rebate或更多报价者不必然增加真实stress liquidity；过宽价差会令可选择的流动性需求退出，成交只剩高信息流，形成内生流动性枯竭。
- **项目动作**：建立 `MarketMicrostructureMechanismEvidence`：对每个执行run分解 explicit fee、quoted/effective spread、inventory carry、temporary impact、permanent markout、delay与opportunity cost；用真实fills/positions/cash重建inventory而非从quotes推断。订单流模型只输出conditional diagnostics，并与public-news baseline、size/urgency、venue state、cross-venue move和no-information null比较。若缺private fills、queue、participant identity或完整L2，adverse selection与fill model标记不可识别；Strategy不得消费“toxicity”标签直接下单，Portfolio/Risk与OMS独立决定风险预算、执行和kill条件。
- **禁止直接采用**：不得复制OCR中的效用、均衡、impact、autocovariance、fill probability、半价差或Bayesian更新公式，不得迁移模型参数、正态性、单位订单、零利润或risk-neutral假设。不得由wide spread、order imbalance、trade sign、短期反转或盈利直接判定informed trader，也不得把midprice称为真实价值、把静态最优quote用于做市。不得运行HFT/做市/最优执行新回测、改参数、查看holdout或调用private/order/paper/live endpoint；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH02-001`—`034`。

## 已完成 L2：第 3 章

### 第 3 章：事件数据重建、采样时钟与高频统计外推边界

- **论证链**：高频价格研究不是把日线频率缩短即可。order-level feed用add/cancel/partial/full fill与隐藏成交事件描述resting orders，市价单常需由其对限价单的执行反推；取消/完成消息若省略价格和数量，必须通过order ID回接原始add事件后才能重建LOB。价格和收益又随trade/mid/microprice、calendar/event clock、sampling frequency、tick、corporate action与venue集合变化。高频样本会出现大量zero return、肥尾、duration clustering、bid/ask reversal和路径依赖；延迟使决策时快照与venue接收时状态分离。碎片化市场中，本地best quote、全市场best quote、隐藏流动性与实际fill也不是同一对象。
- **成立条件**：`HighFrequencyPriceEvidence` 必须保存source/feed tier与entitlement、schema/rule version、canonical instrument、raw event hash、sequence gap、order identity、add/modify/cancel/fill linkage、exchange/source/receive/decision clocks、snapshot checksum、trade signing、corporate-action/PIT adjustment、price type、return formula、calendar/event sampling、zero/stale handling、tick/lot、latency path/distribution、venue quote/trade synchronization和完整trial/model ledger。所有ACF、duration、tail、transition、regression与pair结果同时报告样本日/时段、事件数、缺失、置信区间、multiple testing、简单baseline和滚动OOS。
- **局限与反例**：书中主要是2013年少量美股及单日/短样本，ITCH字段、交易时段、拆股、NBBO、Reg NMS、venue数量与毫秒链路都已过时。订单流与收益同向不证明可预测因果；负自相关可能是bid-ask bounce，100ms净价格不变也可能掩盖多次相互抵消的变化。高频零收益令连续扩散近似失真，固定秒采样会混合不同event intensity。单步反转频率不保证更长历史有增量信息。pair/ETF成分关系、同业共同冲击和单日VAR/协整分量都可能因权重、价格尺度、非同步、结构变化与数据挖掘失效。
- **项目动作**：public-data层先实现sequence-complete事件回放、gap/duplicate/out-of-order检测、时钟质量和snapshot checksum；若feed只有MBP或聚合snapshot，明确禁止queue/order-level结论。诊断层分报calendar-time与event-time returns、zero/stale率、duration分布、spread-bounce-aware reversal、multi-horizon markout、tick/bps尺度、cross-venue quote age/divergence和decision-to-observation staleness。任何pair/lag/imbalance候选都需PIT universe、rolling estimation、purged OOS、完整trial ledger、成本/容量/borrow与多腿fill压力，不能用本章单日参数。
- **禁止直接采用**：不得复制OCR中的return、microprice、power-law、ACF、impact、Markov transition、OU/VAR/cointegration公式和估计值，不得迁移AAPL等样本频率、延迟、tick、venue占比或执行质量。不得把零收益当无风险、负自相关当mean-reversion alpha、订单流相关当方向信号、NBBO显示价当reachable fill或同业相关当套利关系。不得运行HFT/pairs新回测、调参、查看holdout或调用private/order/paper/live endpoint；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH03-001`—`036`。

## 已完成 L2：第 4 章

### 第 4 章：日内活动、执行质量与隐藏流动性证据

- **论证链**：交易活动具有持续性和显著日内季节性，但开盘、收盘、公告时点、目标执行、节假日、停牌/故障与算法跟随volume benchmark会共同塑造曲线。market quality不是单指标：quoted spread描述显示报价之间的即时价差，effective spread描述fill相对基准的结果；depth只覆盖显示并可立即执行的数量；volatility混合基本面变化与微观噪声；price impact还需区分book-walk的即时成本、后续恢复和较持久的repricing。撤单是流动性提供者响应信息和库存的必要状态迁移，高cancel rate不自动等于操纵；hidden orders可改善成交价并改变可见队列，但其不可见性让snapshot-based fill/capacity推断失真。
- **成立条件**：`MarketActivityAndExecutionQualityEvidence` 必须绑定canonical instrument、venue/session/regime、calendar/event clock、source/feed tier、sequence/order identity、trade condition/aggressor、volume单位与venue coverage、spread/mid基准、tick/bps、L1/L2 depth、parent/child aggregation、hidden/auction/internalized flags、cancel/replace/fill lifecycle、halt/outage、decision/arrival/fill/post-trade clocks和multi-horizon recovery。日内profile按完整日期分布而非单日曲线估计，单独标记early close、scheduled event、incident与zero-activity；market-quality指标逐字段保留missing/blocked，不用另一代理变量代填。
- **局限与反例**：交易量与波动/价差相关存在双向因果和共同信息驱动；收盘volume/depth增加可能来自强制完成目标，不等于信息更少或市场更安全。固定秒内交易激增可能是定时批量、timestamp discretization、机器异步或删极值处理。整数/五分/十分价位聚集可来自订单偏好、tick、stop/limit设置或样本构造，不证明支撑阻力。quoted spread随时可见而effective spread只在成交条件下可见，hidden price improvement和跨venue路由造成选择偏差。停牌时仍记录的cancel/quote消息会污染spread/volatility；稀疏资产零收益掩盖偶发跳跃，活跃资产大量quote reversals又可抬高变化次数而不抬高净波动。
- **项目动作**：public execution diagnostics同时输出calendar/event-time volume、seasonality bands、zero/outage flags、quoted/effective spread、top-N depth和size-conditioned book walk、trade/parent aggregation、10ms至更长horizon markout/recovery、cancel-to-add/fill lifecycle与hidden/unknown share。任何impact模型都对比无事件baseline、public news、same-side clustering、spread-at-entry和cross-venue move，并报告selection/endogeneity。没有MBO/order identity时不估queue或order-specific fill probability；没有private parent/fill时不把同毫秒成交拼成真实MO。异常状态进入独立incident regime，不删除后假装正常。
- **禁止直接采用**：不得复制OCR中的volume regression、volatility、spread、impact、survival/fill、permanent/temporary ratio或日内曲线参数，不得迁移2013年AAPL等样本、整手规则、odd-lot、tick、venue路由和hidden比例。不得把高volume当高quality、低effective spread当全部订单低成本、top depth当大单容量、cancel ratio当操纵、distance-to-mid当fill probability或hidden execution当可预测alpha。不得运行POV/VWAP/HFT/做市新回测、调参、查看holdout或调用private/order/paper/live endpoint；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH04-001`—`040`。

## 已完成 L2：第 5 章

### 第 5 章：随机控制、动态规划与停时问题的模型规格边界

- **论证链**：随机控制不是先选“最优公式”，而是先声明状态过程、可控制变量、可容许策略、运行奖励/惩罚、终端奖励、时间范围和随机动力学，再以价值函数比较所有可容许策略。DPP把当前到任意停时的回报与停时后的继续价值递归连接，HJB/DPE是其无穷小形式；候选PDE解只有在正则性、边界/终端条件、可容许反馈控制和受控SDE存在唯一性等条件满足后，才能由verification theorem连接回原问题。计数过程以受控强度和补偿过程描述离散到达，跳扩散把漂移、扩散、跳跃幅度与到达强度同时纳入生成元。最优停时把“继续”与“立即停止”放在同一障碍问题中；控制与停时同时存在时，连续区中的HJB与停止区中的奖励约束组合成QVI。
- **成立条件**：每个模型必须保存state vector及单位、control domain、information filtration、admissibility、horizon、objective sign、running/terminal reward、drift/volatility/intensity/jump map、generator、initial/terminal/boundary conditions、continuation/stopping region、regularity/existence assumptions、verification argument和numerical scheme。涉及执行时还要绑定inventory/cash/fill ledger、tick/lot、queue/fill uncertainty、temporary/permanent impact、fee、latency、venue capability和abort/no-trade状态。连续扩散、计数到达和跳扩散只能在当前数据能识别其机制时选用；强度、冲击和风险厌恶不是跨资产、venue或regime常数。
- **局限与反例**：DPP/HJB是求解框架，不证明经济目标正确、参数可识别或策略可执行。经典Merton问题忽略交易对价格的影响，而清算与限价单示例又依赖特定impact、fill probability和效用设定；这些模型不能互换。经典光滑解可能不存在，最优控制可能只在更强条件下是Markov控制，最优停时常需黏性解或数值自由边界。把离散LOB事件近似成扩散会丢失tick、queue和跳跃，把每次到达近似成独立Poisson会忽略自激、日内季节性和状态依赖；数值网格、截断与插值还可能制造虚假最优性。
- **项目动作**：新增 `StochasticControlModelSpec` 研究合同：候选只输出模型说明、可识别性诊断、基线、校准窗、参数不确定性、边界/单位测试、数值残差、policy feasibility和counterfactual stress，不直接接Strategy或OMS。先以确定性/TWAP、简单impact-aware、无交易和立即停止等基线验证方向；再做小型解析fixture、Monte Carlo与PDE/DPP一致性、网格收敛、终端条件、守恒/单调性、极端状态和不可容许控制拒绝测试。任何policy输出进入执行前仍须经过Forecast/Portfolio/Risk/OrderIntent/OMS/Fill/Ledger全链。
- **禁止直接采用**：不得复制OCR或扫描页中的价值函数、SDE、生成元、HJB、最优控制、强度、fill probability、障碍/QVI公式和示例参数；不得把verification theorem的形式条件当作当前实现已验证，不得用书中效用、风险厌恶、impact、Poisson或Brownian假设解释真实订单流。不得由本章运行新回测、调参、查看holdout或调用private/order/paper/live endpoint；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH05-001`—`030`。原 PDF 印刷页 89—118 已用于语义交叉核对；所有公式仍需第二遍逐式转录、符号表、维度检查和数值fixture。

## 已完成 L2：第 6 章

### 第 6 章：连续执行的状态分账、冲击假设与策略外推边界

- **论证链**：大额清算/收购要在更快执行造成的价格冲击与更慢执行暴露的价格风险之间权衡。模型先分离库存 `Q`、未受执行价差影响的中间价 `S`、含spread与暂时冲击的执行价、累计现金 `X` 和控制变量交易速度；永久冲击改变后续中间价，暂时冲击改变当前成交价。纯线性暂时冲击、无风险惩罚且要求期限内完全清算时会得到恒定速度，这只是TWAP样式的特例。终端惩罚允许留下残余库存，running inventory penalty或指数效用引入风险厌恶；在线性Brownian设定中两类偏好可形成参数映射。非线性暂时冲击把速度成本写成凸函数并借助Legendre变换得到反馈控制，通常需要数值PDE。
- **成立条件**：任何execution candidate必须绑定parent side/quantity/horizon、initial/remaining inventory、decision/arrival/fill/post-trade clocks、mid/reference definition、cash/fill ledger、spread、fee、temporary/permanent/transient impact、volatility、terminal/running penalty、utility、speed/participation/capacity limits和terminal residual处置。冲击函数必须由当前venue、instrument、size、time-of-day和regime的真实quotes/fills校准，并报告置信区间、selection/endogeneity与recovery；模型中的连续速度必须映射到离散child order、tick/lot、partial fill、latency和abort/no-trade状态。
- **局限与反例**：中间价无漂移Brownian、确定期限、连续可分交易、线性impact、常数spread/volatility、无queue/partial fill/fee/latency和已知参数都是强假设。恒速解依赖无风险惩罚和硬终端约束，不证明真实市场TWAP最优；“永久冲击不影响最优路径”依赖线性impact、固定总量和特定终端成本分解，不能泛化。终端二次惩罚只是剩余库存代理，过小会容忍未完成，过大近似硬约束并放大尾端交易。幂律指数略变可显著改变front/back loading，有限差分网格也可能制造策略差异；书中单日LOB快照回归不提供当前可交易impact参数。
- **项目动作**：在独立simulator中保留 `TWAP`、capacity-capped TWAP、linear-impact、risk-aware和nonlinear-impact challenger；统一从OrderIntent目标仓位生成parent schedule，不让execution模型创造alpha。输出implementation shortfall、fill-weighted price、remaining inventory、temporary/permanent markout、cash/position ledger、participation、speed/capacity breaches、terminal penalty和abort reason。先用零impact、零volatility、硬/软终端、买卖符号镜像、单位缩放和常量速度解析fixture核对方向，再做参数邻域、regime、流动性枯竭、gap/latency/partial-fill和无法完成目标的fail-closed压力。
- **禁止直接采用**：不得复制扫描页中的impact函数、HJB、Riccati/ODE、效用映射、Legendre变换、解析路径或图中参数；不得把midprice当fill、把implementation shortfall单一化为滑点、把永久/暂时冲击由单一post-trade窗口直接识别、把恒速称为普遍最优。不得运行新执行回测、调参、查看holdout或调用private/order/paper/live endpoint；Strategy仍只输出受治理的目标/意图，安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH06-001`—`030`。原 PDF 印刷页 121—141 已用于语义交叉核对；所有公式、参数与数值结论仍需第二遍逐式转录、维度检查、当前fills/quotes校准和simulator fixture。

## 已完成 L2：第 7 章

### 第 7 章：价格边界、订单流状态与多场所随机成交

- **论证链**：本章在连续执行上加入三类状态变化。其一，限价最优收购在库存目标、期限或中间价触及价格上限时停止，并对期限/触价时的剩余量作终端执行；因此价值函数除了时间与库存边界，还需要价格障碍边界，策略随离边界距离与波动变化。其二，其他参与者的买卖订单流被建模为均值回复的跳跃过程，净订单流进入中间价漂移和执行PIDE，候选速度由经典库存项与未来净流预测修正。其三，明市连续MO与暗池随机匹配同时减少库存；暗池可能按参考中间价成交而避免模型中的暂时冲击，但订单等待、随机到达和随机数量要求明市路径承担失败回退。
- **成立条件**：价格边界模型必须声明barrier来源、观察/触发clock、触发时剩余库存如何执行、边界可达性、gap/overshoot与真实capacity。订单流状态必须基于sequence-correct feed定义side、event、decay/jump、日内季节性和可预测范围，并对非负库存、禁止意外反向/空头、期限收敛和控制上限加约束。多场所执行必须保存lit/dark order ID、posted/remaining/cancelled/fill quantity、arrival/priority/minimum-size/conditional规则、reference-price clock、partial fill、information leakage、toxicity、venue failure和fallback schedule；当前venue capability与private fills未证明时不可校准或调用。
- **局限与反例**：中间价触及上限即以该价瞬间完成全部剩余量隐含无限流动性且无gap、spread、latency或冲击；真实市场的limit/stop语义不能由此替代。独立Poisson跳跃、指数衰减和线性price response忽略自激、共同新闻、状态依赖和跨venue反馈；PIDE的无约束候选甚至可能产生负交易速度或目标完成后继续交易。暗池订单“无冲击、按mid、到达即全量执行、排在队首、成交量足够大”是显式特例；更高arrival intensity也不必然改善真实执行，因为adverse selection、information leakage、minimum size、conditional firm-up和机会成本会同时变化。
- **项目动作**：execution simulator加入三个独立stress layer：price barrier/gap与terminal residual；public order-flow state但不赋予不可观测participant identity；venue leg的随机fill/partial/no-fill和fallback。每个challenger与无barrier、无order-flow、lit-only基线比较，报告implementation shortfall、remaining inventory、constraint hit、negative-speed rejection、venue-leg attribution、fill-time distribution和最坏未完成路径。订单流只能作为短周期执行诊断，经rolling/purged OOS和alternative-news baseline后才可进入candidate；dark场所只允许synthetic failure scenario，不建立真实routing或promotion结论。
- **禁止直接采用**：不得复制价格边界PDE/PIDE、最大值原理界、订单流强度/衰减、Feynman–Kac表示、暗池到达率/数量分布、解析路径或图中参数。不得把price limit等同可成交限价、把净订单流当方向alpha、让无约束模型越过零库存、把暗池mid fill称为无成本或把arrival rate当fill guarantee。不得访问dark/private/order/paper/live endpoint，不运行新回测、调参或查看holdout；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH07-001`—`030`。原 PDF 印刷页 144—167 已用于语义交叉核对；所有边界、PIDE、强度、暗池匹配和数值结果仍需逐式转录、当前规则核验和failure-first simulator fixture。

## 已完成 L2：第 8 章

### 第 8 章：限价成交证据、MO回退与计划跟踪

- **论证链**：MO通常提高成交确定性但支付spread、book walk和impact；LO可能获得优于mid的价格，却要承担排队、撤单、价格远离和期限末未成交。LO-only模型把挂单深度作为控制，以外部MO到达和深度相关fill intensity驱动库存离散下降；最优深度随剩余库存、时间、到达率和终端惩罚变化。指数效用与running inventory penalty在特定Brownian/指数强度设定下可映射。允许LO与MO并用时，连续区继续调整LO深度，停止/冲动区立即执行MO，价值满足QVI；加入目标库存路径后，running penalty从“偏离零库存”改为“偏离计划”。
- **成立条件**：fill模型必须绑定venue/order type/TIF/display、tick/lot、MBO或明确降级的MBP层级、order identity、ahead volume、queue priority、add/modify/cancel/trade linkage、partial fill、hidden/iceberg、self-cancel/reprice、exchange/source/receive/decision clocks、latency和session/rule version。MO回退必须有剩余量、可见/隐含depth、capacity、价格保护、最大slippage、期限和kill条件。计划跟踪需固定parent objective、target schedule来源和版本、允许偏离、terminal residual、no-trade/abort，并把计划质量与执行质量分开。
- **局限与反例**：块状LOB、固定订单量、独立Poisson到达、指数fill probability、单次fill恰好一单位、无队列ahead/cancel、mid为Brownian、无adverse selection和静态参数都是强假设。更深挂单在模型中提高价差收益但降低fill intensity，真实市场还可能因queue跳动、maker fee、隐藏流动性、价格趋势和毒性流使关系反转。QVI给出的MO时机依赖单位冲动成本和无冲击执行；真实MO可能部分成交、跨层/venue、延迟或被价格保护拒绝。跟踪TWAP/AC计划只证明执行器贴合给定路径，不证明该目标路径或目标仓位正确。
- **项目动作**：建立 `OrderChoiceAndFillEvidence`：按child order回放queue-aware lifecycle，分别输出touch、eligible、partial/full fill、cancel/replace、expiry、time-to-fill、markout和MO fallback cost；数据不足时明确 `queue_unidentifiable`，禁止用distance-to-mid直接当fill probability。simulator比较LO-only、MO-only、LO-with-deadline-fallback和target-tracking，采用realistic queue/latency/partial-fill/no-fill stress，并报告remaining inventory、target deviation、impulse count、price improvement、adverse markout和ledger一致性。任何MO冲动必须由OMS执行并经过Portfolio/Risk、price/capacity limits和reconcile。
- **禁止直接采用**：不得复制指数fill函数、到达率、最优深度、效用映射、QVI阈值、MO时点、TWAP/AC参数或图中收益。不得把LO触价当fill、把发布深度当queue position、把更高理论price improvement当更优execution、把目标计划当alpha或让Strategy直接选择/发送MO。不得访问private/order/paper/live endpoint，不运行新回测、调参或查看holdout；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH08-001`—`030`。原 PDF 印刷页 168—192 已用于语义交叉核对；所有fill intensity、QVI、冲动边界、计划惩罚和数值结果仍需逐式转录、MBO/private fill证据及failure-first simulator验证。

## 已完成 L2：第 9 章

### 第 9 章：POV、累计成交量与benchmark执行边界

- **论证链**：parent order拆成child order时，单笔相对LOB容量和同时间其他订单决定局部冲击；较长区间又要处理代理累计参与造成的单边压力。本章区分两类volume target：POV要求代理瞬时交易速率接近其他参与者速率的比例；累计成交量占比要求已完成数量接近市场累计量的比例。两者在随机volume下不等价。volume可用均值回复跳跃速率或复合Poisson累计量描述，策略由库存清算项、当前/预期未来volume与跟踪惩罚共同组成。其他交易者的买卖不平衡若影响中间价，会额外调整执行。指数效用版本再把价格风险与POV偏离同时纳入递归目标。
- **成立条件**：必须先定义market volume的instrument/venue集合、trade condition、side/aggressor、是否含auction/odd-lot/internalized/off-book、是否排除agent自身、source/feed tier、exchange/source/receive clock、late/corrected/cancelled trade和跨venue去重。POV分母接近零、数据延迟、burst/outage和volume forecast误差必须有floor/cap/hold/abort规则。累计目标需保存target ratio、market cumulative、agent cumulative、remaining parent、horizon和benchmark clock；VWAP计算与可执行价格、fees、impact、opportunity cost分开。
- **局限与反例**：固定比例惩罚不是经济成本，高惩罚可强迫追随噪声volume并在流动性恶化时过度交易；低惩罚又可能偏离benchmark。均值回复shot-noise、独立Poisson、有限矩、线性impact和已知长期均值忽略日内季节性、共同事件、自激、venue迁移和agent成交对分母/价格的反馈。高相关的执行速率与市场volume可能只是目标构造结果；平均价格接近VWAP不表示更低implementation shortfall。累计volume的未来终值不可知，实时VWAP/POV受late prints和修正影响；BTC 24/7不存在通用“日内曲线”。
- **项目动作**：在simulator中分别实现volume-capped TWAP、POV、累计volume target和VWAP benchmark，仅作为执行challenger。输入使用PIT volume snapshot与预测分布，输出participation ratio、cumulative tracking error、self-volume share、volume forecast error、impact/markout、remaining inventory、constraint/denominator-floor hit和fallback reason。每个策略与同parent、同capacity/fees/latency的TWAP和no-trade基线比较，并在zero-volume、burst、halt/outage、late correction、cross-venue shift和无法完成目标下fail-closed。
- **禁止直接采用**：不得复制POV/累计volume闭式策略、volume jump/decay参数、Feynman–Kac表示、VWAP差值、指数效用映射或图中相关性。不得把volume spike当可用容量、把高participation当流动性、把接近VWAP当best execution、把agent自身成交重复计入外部volume或让volume目标改变Strategy目标仓位。不得访问private/order/paper/live endpoint，不运行新回测、调参或查看holdout；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH09-001`—`030`。原 PDF 印刷页 194—225 已用于语义交叉核对；所有volume定义、随机过程、POV/累计目标、其他交易者冲击和效用递归仍需逐式转录、PIT数据定义与simulator验证。

## 已完成 L2：第 10 章

### 第 10 章：库存约束、双边报价与逆向选择证据

- **论证链**：基础模型让做市商围绕中间价发布买卖限价单，外部MO按与报价深度相关的强度到达并随机成交；成交同时改变现金和库存。目标把终端现金、库存按中间价清算、终端库存惩罚与持有期库存风险结合起来，DPE中的买卖跳跃项因此给出随时间和库存变化的最优深度。库存偏离零时，两侧成交强度的不对称形成均值回复；取消库存边界与惩罚后，常数报价深度只是在最大化单次价差收益乘成交概率的退化特例。触发式做市进一步把控制改成是否在买侧、卖侧或双侧挂单，最优数量模型则允许一次压缩多单位库存。指数效用在特定Brownian中间价、指数成交强度和参数重标度下可与运行库存惩罚策略对应，但不是普遍等价。逆向选择部分分别建模MO到达引起的中间价跳跃，以及可观测短期均值回复alpha；二者都会使成交后的价格变化进入报价决策，要求避开预期markout不利的一侧。
- **成立条件**：任何做市研究必须绑定instrument/venue/session/rule version、tick/lot、maker/taker fee与rebate、order type/TIF/post-only、自成交防护、双边order lifecycle、MBO/queue ahead、hidden/iceberg、external MO与自有fill的事件链接、exchange/source/receive/decision/ack/fill clocks、cancel/replace latency、inventory/cash/position/hedge ledger、capital/margin/funding、inventory/cash/notional/concentration limits、terminal liquidation、post-fill multi-horizon markout和public-news alternatives。短期alpha必须说明状态可观测性、半衰期、预测时钟、结构变化和OOS范围；做市PnL只能由真实fills、positions、cash、fees、hedges和markouts推导，不能由quoted spread或理论fill intensity代替。
- **局限与反例**：本章假设中间价为连续Brownian或受MO驱动的简单跳扩散，买卖MO独立Poisson到达，成交概率按报价距离指数衰减，订单可被一单位或给定数量完整成交，参数静态且没有真实queue、partial fill、cancel race、latency、跨venue、自成交、fee tier、funding、margin和exchange failure。模型中的最优挂单可能在市场移动前无法撤回；显示在两侧不代表两侧都能成交，成交也可能集中在价格即将不利移动的一侧。无库存限制的常数深度会允许库存无界漂移；数量模型一次成交后也不保证库存归零。效用与二次惩罚的映射依赖特殊参数关系。MO后同向markout可能来自公共新闻、共同因子、代理商自身影响或时间戳偏差，不能自动命名为informed/toxic flow；短期alpha估计若使用成交后信息或慢时钟会产生未来函数。
- **项目动作**：建立只读 `MarketMakingSafetyAndEvidence` 规格，首先验证数据与账本可识别性，不实现或路由做市策略。证据包按child order重放submit/ack/live/partial/full fill/cancel/reject/expire/unknown状态，重建bid/ask两侧queue、quote age、fill-to-markout、inventory/cash/hedge和all-in PnL，并把spread capture、inventory carry、adverse markout、fees/rebates、hedge cost与unwind cost分解。failure-first场景至少覆盖stale quote、feed gap、clock drift、cancel未确认、unknown order、duplicate retry、partial/overfill、单边连续成交、price gap、venue disconnect、margin/capital breach与无法对冲；任何状态不确定先reconcile再行动并进入degraded/kill。当前缺private fills、order permissions、真实latency和完整ledger，因此只允许public-data diagnostics和synthetic stress，gate保持`rejected_for_now`。
- **禁止直接采用**：不得复制最优报价深度、成交强度、库存边界、触发区域、最优数量、效用参数映射、逆向选择修正、短期alpha过程或图中参数；不得把两侧quote、quoted spread、touch、显示深度或模型成交率当真实收入与fill证据，不得从成交后markout直接判定知情交易者。Strategy不得直接挂单、撤单或切换买卖侧；任何未来OrderIntent仍必须经过Portfolio/Risk、OMS/Execution、Fill/Ledger和审计链。不得访问private/order/paper/live endpoint，不运行新回测、调参或查看holdout；所有安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH10-001`—`030`。原 PDF 印刷页 228—253 已用于语义交叉核对；所有DPE、矩阵ODE、最优深度/数量、效用等价、MO价格跳跃和短期alpha策略仍需第二遍逐式转录、维度/边界检查、当前venue规则与真实双边fill证据。

## 已完成 L2：第 11 章

### 第 11 章：协整持续性、最优停时与多腿执行边界

- **论证链**：配对交易先构造两个或多个资产价格的线性组合或协整因子，假设其偏离是暂时的，再在“便宜”时做多组合、“昂贵”时做空组合并等待回归。书中明确统计套利不是零风险套利。固定标准差波段可反复开平仓，但终端可能遗留头寸，波段越宽通常交易越少且单次幅度更大，不能只凭样本P&L或Sharpe选阈值。OU模型把协整因子写成均值回复扩散，通过变分不等式、价值匹配和平滑粘贴分别求退出、进入和双边进出阈值；交易成本、贴现、均值回复速度和波动共同决定continuation/exercise区域，进入与退出阈值即使参数相同也不必对称。多资产部分把短期alpha定义为对数价格组合，在特殊线性扩散、可逆协方差和指数效用下求连续最优投资；策略包含经典漂移项与协整修正，并随期限临近衰减。
- **成立条件**：相对价值研究必须保存PIT universe、候选对/篮子生成规则、价格类型与币种、corporate action/dividend、对数/水平变换、hedge/cointegration weights的估计窗与版本、formation/trading切分、平稳性与残差诊断、break/date监测、trial数量和multiple-testing校正。每个信号还要绑定entry/exit/stop/timeout、目标gross/net/factor暴露、capital/margin、shortability、borrow locate/rate/recall、funding、FX、tax、tick/lot、capacity和market regime。多腿执行必须记录parent basket、每腿OrderIntent、decision/arrival/fill clocks、partial/no fill、legging exposure、hedge fallback、cancel/reconcile、fees/slippage/impact和basket级cash/position/PnL ledger；无法原子成交时必须有最大leg-risk、超时和abort/unwind规则。
- **局限与反例**：单日INTC/SMH样本、当日估计权重、固定标准差和10,000条同模型模拟不能证明关系在未来稳定。价格差或相关性不等于协整，历史协整也会因指数成分、公司事件、产业变化、ETF权重、tick/fee、交易时段和共同因子断裂。OU、无限期限、常参数、连续路径和固定成本忽略跳跃、状态依赖、离散交易、动态hedge ratio与终端强制平仓；平滑粘贴阈值在不可成交或有限期限下会改变。多资产效用模型假设连续无摩擦交易、无限borrow/short、无持仓/杠杆/成交约束、协方差可逆且参数已知；理论组合可能极端杠杆、对估计误差敏感，风险中性测度下协整因子变成Brownian也不等于真实世界无均值回归或不存在alpha。单腿成交会暂时制造方向和因子暴露，组合回归正确仍可能因borrow召回、基差扩大或流动性枯竭而破产。
- **项目动作**：建立 `RelativeValueAndLegRiskEvidence`：研究层只输出候选Forecast/TargetPosition及不确定性，不直接生成多腿订单。先以滚动formation窗口估计权重并冻结到trading窗口，执行PIT universe、purged walk-forward、结构断裂、参数漂移、伪配对/null、multiple-testing和存活偏差反证；报告spread half-life、threshold turnover、time-in-trade、break frequency、capacity、gross/net/factor/sector/beta暴露与成本后结果。Portfolio/Risk负责gross/net/leverage、factor、concentration、borrow与leg-risk预算；OMS把篮子拆腿并在partial fill、拒单、halt、borrow loss、basis blowout和venue outage下re-hedge或fail-closed；Fill/Ledger从各腿真实成交、现金、费用、融资和公司行动重建basket PnL。当前不运行新回测、不查看holdout，也不形成promotion结论。
- **禁止直接采用**：不得复制固定标准差、OU参数、进入/退出阈值、cointegration权重、Sharpe、效用风险厌恶、协方差、测度变换、显式最优组合或图中参数；不得把相关、均值回归、协整检验通过、单日回归或同模型Monte Carlo盈利称为套利或稳定alpha。不得用全样本选择pair/weights/threshold，不得回填未来成分、公司行动、borrow或break信息，不得假设两腿同时按mid成交、无限short/borrow、零市场冲击或零终端库存。不得访问private/order/paper/live endpoint；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH11-001`—`030`。原 PDF 印刷页 255—276 已用于语义交叉核对；所有OU基本解、变分不等式、平滑粘贴、双边阈值、alpha动力学、HJB、Girsanov变换和显式组合仍需逐式转录、有限期限/约束扩展、PIT数据及真实多腿fill证据。

## 已完成 L2：第 12 章

### 第 12 章：订单不平衡定义、事件时钟与执行特征边界

- **论证链**：本章把订单不平衡定义为所选LOB范围内显示买方数量减卖方数量，再除以两者总和；只看touch、前n档或中间价附近固定距离会得到不同特征。单日ORCL示例把连续不平衡分箱，观察到状态相关的买卖MO比例、U形总到达率、自相关和后续价格变化关联。离散时间链按固定100ms样本估计转移矩阵，连续时间模型则在状态停留区间内联合建模状态跳转和买卖MO事件；二者因average-window与instantaneous state不同而不等价。价格模型再按不平衡状态估计MO到达与随后短窗中间价跳跃分布，日间部分用函数型数据分析描述不同日期的活动曲线。最优清算把不平衡状态、MO到达、价格跳跃和LO成交共同放入DPE，候选挂单深度随库存、时间和状态变化；无约束解出现负深度时，作者将控制域约束为非负，说明解析反馈本身不保证执行可行。
- **成立条件**：`OrderImbalanceExecutionFeatureEvidence` 必须绑定instrument/venue/session/rule version、MBO/MBP层级、displayed/hidden/iceberg、depth定义、price-distance/tick范围、side、quantity单位、zero-denominator、snapshot rebuild、sequence gap、add/cancel/replace/trade linkage、exchange/source/receive/decision clocks、snapshot age和cross-venue覆盖。离散链需保存sampling interval、window aggregation、bin edges、empty/rare states、transition counts、row stochasticity和regime；连续链需保存event identity、state holding time、MO side/intensity、censoring与联合likelihood。价格反应必须固定event time、reference mid、horizon、trade signing、public-news/cross-venue/self-impact替代解释。进入执行模型前还需真实order ID、queue ahead、partial fill、cancel/reprice latency、fees/rebates、post-fill markout、inventory/cash ledger和deadline fallback。
- **局限与反例**：显示深度极易被撤单、隐藏订单、iceberg补充、跨venue迁移和latency改变；不平衡接近正一/负一不代表可按该方向成交，也不识别参与者意图。固定100ms平均会混合多个事件并制造/消除状态转移，事件时钟又可能对高活动期过度加权；矩阵对数不一定生成合法生成矩阵，稀有状态的转移率和跳跃分布估计不稳定。单日2013年NASDAQ ORCL、五档分箱、1秒价格窗和年度活动曲线不能迁移到当前美股或BTC；BTC 24/7还受venue碎片、永续资金费、清算、跨市场lead-lag和无统一session影响。自相关和条件价格变化可能来自spread bounce、共同新闻、价格移动先改变深度、撤单反应或时间戳偏差。模型假设外部MO按状态Poisson到达、LO成交概率只由深度指数衰减、单位完整成交且无queue/latency/adverse selection；模拟更快清算仍可能有更差all-in cost和markout。
- **项目动作**：先实现只读的feature-definition与data-quality合同，不把不平衡直接接入Strategy。对每个候选并行计算touch、固定档数、固定bps/tick、单venue和合并venue版本，报告coverage、sequence gaps、snapshot age、cancel burst、hidden/unknown、state occupancy、transition CI和不同clock敏感性；任何定义变更视为新feature version。预测研究必须使用rolling/purged OOS，比较last return、spread、volatility、MO flow、public event和no-feature基线，报告calibration、decay、turnover、capacity、markout与multiple trials。执行层只在真实queue/fill证据齐备后把该特征作为LO/MO challenger输入，并受非负深度、tick/lot、price protection、deadline、inventory、cancel/reconcile和fail-closed约束；当前仅允许public-data diagnostic与synthetic stress，不运行新回测或查看holdout。
- **禁止直接采用**：不得复制不平衡档位、100ms/1秒窗口、转移矩阵、生成矩阵、MO到达率、价格跳跃分布、函数主成分、最优深度或图中参数；不得把高不平衡解释为知情买卖、方向alpha、fill guarantee或操纵证据。不得用snapshot触价代替fill、用平均窗口链代替事件链、用同日估计和模拟评价声称OOS有效，也不得让负深度代表未授权MO。Strategy不得直接根据不平衡发单，LO/MO选择仍属于受Portfolio/Risk约束的OMS/Execution。不得访问private/order/paper/live endpoint；安全旗标保持false。
- **L3 待复核**：`FORM-EXE02-CH12-001`—`030`。原 PDF 印刷页 277—294 已用于语义交叉核对；所有不平衡定义、Markov MLE/生成矩阵、联合事件似然、条件跳跃、FDA基、DPE和约束最优深度仍需逐式转录、sequence-correct L2、latency-aware OOS和真实fill/markout证据。

## 附录边界

- Appendix A `27099` 起为随机分析、Feynman–Kac、PDE 等数学工具；OCR 公式全部不可引用。
- 本书模型必须在独立 simulator 中验证，不能成为 private/order/live 调用理由。

## 下一轮精读重点

第 1—4 章低可信非公式语义与第 5—12 章原页语义级 `L2` 均已完成，章节覆盖 `12/12=100%`，累计登记 380 项待复核关系。下一轮不进入新回测或参数迁移，而是审计本卡与Agent手册的引用、状态和项目映射；附录及全部逐式 `L3` 继续保持阻塞，安全与promotion旗标不变。
