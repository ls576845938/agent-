---
book_id: PORT-03
title: Efficiently Inefficient
authors: [Lasse Heje Pedersen]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Efficiently Inefficient - Lasse Heje Pedersen - 原文.md
source_format: pdf_text
source_sha256: 59311b360adee79791ecd6947e5f7eb20c97d26b85803efeb8e72850f5635058
source_line_count: 17509
card_status: chapter_semantic_review_l2_complete_formula_pending
chapter_count: 16
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 491_items_identified_pending_ch01_ch16
last_reviewed_at: 2026-07-13
---

# PORT-03：Efficiently Inefficient

## 覆盖声明

本卡已用正文 `CHAPTER` 锚点重新核定 16 章边界。复核发现旧边界整体向后错位，既漏读章首又串入下一章，且旧队列存在“来源行号与描述内容不一致”；因此旧版第 1—8 章 `L2` 与 238 项队列已整体作废。当前 16 章均已按真实边界逐段重读并恢复 `L2`，覆盖 `16/16=100%`，重建 491 项 `L3` 待复核且不再保留分组占位。访谈、案例回报和名人经验只作假说/运营背景，不替代可复现实证。

## 全书项目映射

- `core_model`：“有效地无效”意味着 edge 只够补偿信息、交易、流动性、融资和组织成本；价格偏离不等于免费套利。
- `existing_rule_confirmed`：profit source、other side、market/funding liquidity、leverage、borrow、capacity、drawdown 与 independent risk control 必须显式。
- `candidate_library`：value、trend、liquidity provision、carry、low-risk、quality 是跨策略风格，但具体实现必须按市场合同重建。
- `scope_boundary`：fixed-income/convertible/event arbitrage 和 options 主要作风险案例；当前系统不具备相应数据/账本/权限。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Understanding Hedge Funds and Other Smart Money | `1183-1548` | `L2/medium` | 主动投资者通过信息生产和流动性供给改善市场，但 edge 受费用、杠杆、容量、组织与报告偏差制约。 | `governance_insight`：benchmark、全成本、风险暴露、容量与职责分离必须成为证据合同；账本与验证独立于策略。 | `FORM-PORT03-CH01-001`—`017` |
| 2 Evaluating Trading Strategies | `1549-2165` | `L2/medium` | alpha/beta、Sharpe/IR、tail、drawdown、年化和陈旧价格调整依赖 benchmark、频率、分布与数据生成过程。 | `performance_contract`：统一 return/benchmark/frequency/annualization/gross-net，报告估计误差、factor/tail/liquidity、stale mark 和 attribution。 | `FORM-PORT03-CH02-001`—`029` |
| 3 Finding and Backtesting Strategies | `2166-2852` | `L2/medium` | 可重复利润必须连接 information 或 liquidity compensation，并用 PIT、OOS、净成本和 trial accounting 检验。 | `candidate_intake`：登记 other side/who pays、why persistent、market/funding liquidity、PIT universe/data、cost/capacity、falsifier 和 trial count。 | `FORM-PORT03-CH03-001`—`035` |
| 4 Portfolio Construction and Risk Management | `2853-3219` | `L2/medium` | expected return、covariance、约束和成本决定仓位，独立 Risk 管理路径风险。 | `portfolio_risk_contract`：Strategy 与 Portfolio/Risk 分离；稳健估计、risk contribution、hard caps、liquidity stress 和 deterministic delever/re-entry。 | `FORM-PORT03-CH04-001`—`021` |
| 5 Trading and Financing a Strategy | `3220-4387` | `L2/medium` | 可实现收益由交易成本、容量、融资、margin/collateral 和强平反馈共同决定。 | `execution_funding_contract`：decision/arrival/fill、IS、size-conditioned cost、capacity、borrow/funding/margin/cash runway 与 forced-liquidation replay；异常 fail-closed。 | `FORM-PORT03-CH05-001`—`041` |
| 6 Introduction to Equity Valuation and Investing | `4388-4728` | `L2/medium` | intrinsic value 是现金流、增长、终值与折现率假设的函数。 | `valuation_contract`：模型、PIT inputs/vintage、cash-flow/discount-rate语义、terminal share、uncertainty、sensitivity 与 falsifier；model price 不作真值。 | `FORM-PORT03-CH06-001`—`016` |
| 7 Discretionary Equity Investing | `4729-5622` | `L2/low` | 基本面 stock picking 以 valuation、quality、management、catalyst 与 sell discipline 形成可证伪 thesis；经理访谈和历史个案只能生成低可信候选。 | `qualitative_evidence_contract`：保存 thesis、反方解释、falsifier、catalyst、management risk 与复核历史；输入必须合法、PIT、可审计，叙事不得绕过 Forecast/Portfolio/Risk。 | `FORM-PORT03-CH07-001`—`030` |
| 8 Dedicated Short Bias | `5623-6414` | `L2/medium` | short 不是 long 的镜像：基本面负面假说还必须承受 locate、loan fee、recall/buy-in、margin、squeeze、法律和无限上行损失。 | `short_contract`：负 Forecast 与可执行负仓位分离；locate/borrow、collateral、margin、recall、cover、MNPI/legal 与压力证据不完整时 fail-closed。 | `FORM-PORT03-CH08-001`—`030` |
| 9 Quantitative Equity Investing | `6415-8138` | `L2/medium` | 因子名只是起点；可实现量化股票策略取决于 PIT 定义、组合中性、成本、容量、拥挤、流动性和模型衰减。 | `factor_evidence_contract`：对齐 PIT factor、exposure neutralization、net cost/capacity、crowding stress、OOS 与 model decay。 | `FORM-PORT03-CH09-001`—`040` |
| 10 Introduction to Asset Allocation | `8139-9045` | `L2/medium` | strategic、tactical 与 security selection 必须分层；回报分解和风险贡献比名义资本权重更能揭示集中、流动性与杠杆风险。 | `allocation_evidence_contract`：美股/BTC 组合分别记录长期基准、战术tilt、risk contribution、liquidity、tail/shared exposure；跨资产公式只作待复核概念。 | `FORM-PORT03-CH10-001`—`030` |
| 11 Global Macro Investing | `9046-10270` | `L2/low` | macro 是带时点、传导、市场表达和反证的假说；carry、政策、增长/通胀、跨国value/momentum与反身性都可能因拥挤、内生性和制度变化失效。 | `macro_context_contract`：只接受 release-vintage 数据和可审计公开证据，保存已定价预期、legs/shared beta、falsifier 与 review；宏观叙事不得绕过 Signal/Portfolio/Risk。 | `FORM-PORT03-CH11-001`—`034` |
| 12 Managed Futures: Trend-Following Investing | `10271-11352` | `L2/medium` | 趋势收益依赖逐步价格调整与持续路径；vol scaling、跨市场分散和慢速信号也会在跳跃反转、拥挤、成本与margin压力下失效。 | `trend_evidence_contract`：与 STR-01/02 交叉检查 signal/vol/cost/capacity/tail；单 BTC 证据不得外推为多资产 CTA，CTA 也不得预设为 tail hedge。 | `FORM-PORT03-CH12-001`—`032` |
| 13 Introduction to Arbitrage Pricing and Trading | `11353-11702` | `L2/medium` | 实务 arbitrage 不是无风险：复制误差、成本、margin、先亏路径、非fungibility、模型错和中介约束都可能使关系断裂。 | `arbitrage_evidence_contract`：登记 payoff/replication、legs、convergence、funding/margin、cost、model/basis 与 broken-link risk；options/多腿执行当前 blocked。 | `FORM-PORT03-CH13-001`—`019` |
| 14 Fixed-Income Arbitrage | `11703-13133` | `L2/medium` | 曲线、carry、spread 与 basis 的小价差依赖高杠杆、repo、clientele flow 和多腿 hedge；压力期 funding/market liquidity 会共同撤退。 | `funding_liquidity_stress_contract`：借鉴 duration/risk contribution、cash runway、funding maturity、counterparty 与 forced-delever 治理；rates/credit/MBS交易仍 out of scope。 | `FORM-PORT03-CH14-001`—`041` |
| 15 Convertible Bond Arbitrage | `13134-14233` | `L2/medium` | convertible 是 bond、equity option、credit、borrow、funding 与 event terms 的动态多腿组合；model cheapness 会在流动性螺旋中继续恶化。 | `multi_leg_risk_contract`：借鉴 Greeks、cash-flow attribution、borrow/funding、event/indenture 和 spiral stress；缺 vol/credit/borrow/multi-leg ledger，当前 blocked。 | `FORM-PORT03-CH15-001`—`030` |
| 16 Event-Driven Investments | `14234-15875` | `L2/low` | event-driven 收益是承接 deal、流动性、法律、融资、借券、资本结构与跳空风险的补偿；表面对冲仍保留状态依赖的非线性尾部。 | `event_state_evidence_contract`：需公告 PIT、terms/version、审批/融资/投票状态、payoff/hedge、borrow、legal/corporate-action、gap、cash/margin 与逐事件仓位上限；当前实现 blocked。 | `FORM-PORT03-CH16-001`—`046` |

## 第 1—8 章综合卡

第 1—8 章均已按真实边界重新精读并恢复 `L2`；其中公式、历史数字、案例与访谈经验仍只登记为 `L3` 待复核，不构成生产参数或 promotion evidence。

### 第 1 章：主动资本、全成本、容量与职责分离

- **论证链**：主动投资者通过收集信息、把信息反映进价格并向有交易需求的主体提供流动性，获得的收益必须足以补偿研究、组织、交易、融资和流动性成本；可获利机会与流动性需求有限，因此主动资本存在容量上限。基金回报还混合 benchmark 暴露、杠杆、费用、资金流、报告选择和尾部风险，明星个案不能代表可投资的平均结果。
- **成立条件**：评价任何经理或策略必须先固定 benchmark、gross/net、费前/费后、现金与融资、active risk、杠杆、流动性、容量和投资者可实现口径；业绩库需要识别自愿报告、backfill、survivorship、停止报告与成功基金不报告等方向相反的选择机制。运营上应区分资本所有者、策略/研究、Portfolio/Risk、交易、托管/清算/融资、估值/净值、审计与合规职责。
- **局限与反例**：书中监管资格、募集限制、行业规模、经典费用结构和 master–feeder 税务安排均具有地域与时代性；历史高收益、弱持续性和“核心策略长期有效”是二手研究或作者判断。tracking error 只描述相对 benchmark 的波动，不揭示负偏度、肥尾、流动性撤回或错误 benchmark；按现金比例缩放波动也不等于风险在压力期线性缩放。
- **项目动作**：为策略建立 `StrategyEconomicsEvidence`，记录 profit source、other side、benchmark、gross/net、全部费用与交易/融资成本、active/market/factor exposure、leverage、liquidity、capacity、tail、数据选择偏差和不确定性；架构继续强制 Strategy 只产出 Forecast/Target/OrderIntent，Portfolio/Risk 独立审批，OMS/Fill/Ledger 生成可重放 PnL，估值、对账、审计证据不得由策略自证。
- **禁止直接采用**：不得迁移“2 and 20”、hurdle/HWM、20% 波动率、50% 现金缩放、历史基金数量/AUM/收益、经理持续性或行业相关性作为当前参数；不得把 hedge fund、market neutral、smart money、information edge 或 liquidity provider 标签当 alpha；不得以经理访谈、明星案例或费前业绩替代当前 HEAD 的 PIT、OOS、净成本和尾部证据。
- **L3 待复核**：`FORM-PORT03-CH01-001`—`017`。

### 第 2 章：绩效度量、年化假设与陈旧价格偏差

- **论证链**：return 可拆为 benchmark/factor 暴露与 residual，但 alpha 只是给定风险模型下的截距估计，不自动等于 skill；Sharpe、IR、Sortino、RAROC、alpha-to-margin、drawdown 等指标分别回答不同问题，缩放、杠杆和 benchmark 会改变表面结果。频率转换依赖收益独立同分布、方差随时间线性累积等假设；illiquid/stale marks 会压低当期 beta/volatility、抬高 alpha 和风险调整收益，需使用 lagged exposures 与经济风险证据修正。
- **成立条件**：每个指标必须固定 return type、risk-free/benchmark、factor set、frequency、arithmetic/geometric、simple/log、gross/net、annualization、sample、standard error 和 missing/stale-price policy；beta/alpha 回归需要残差与 benchmark 关系、稳定性和足够样本，跨频率缩放需检验 serial correlation、volatility clustering、overlap 和非同步定价。drawdown 必须固定 compounded wealth index、peak、窗口、符号、duration 与 recovery；tail metrics 必须声明 MAR、置信度、economic-capital 和 stress design。
- **局限与反例**：`t>2`、正态损失概率和 `sqrt(n)` 年化只在强假设下近似，multiple testing、选择性报告、结构变化、异方差和自相关会使显著性与区间失真；单一 market beta 可能把 value/size/other factors 当 alpha，加入因子又可能吸收真实策略来源。高 Sharpe 可能来自卖尾部、陈旧价格或不可加杠杆的容量约束；最大回撤是已实现路径统计，不能覆盖未见压力和融资撤回。
- **项目动作**：建立 `PerformanceEvidence`：保存 metric definition/version、benchmark/risk-free/factors、gross/net、frequency/annualization、sample、point estimate/SE/CI、autocorrelation/non-normality、stale-mark lags、tail/drawdown duration/recovery、leverage/margin/capacity 与 attribution；backtest 同时产出 gross、交易后、融资后与最终净收益，PnL 仅从 fills/positions/cash ledger 推导。Promotion 不以单一 Sharpe、alpha、t-stat、MDD 或 fee-adjusted track record 决定。
- **禁止直接采用**：不得把 `t>2`、CAPM alpha、Fama–French 三因子、SR=1、2.3%/16% 等损失概率、260 交易日、`sqrt(n)`、10% margin=10 倍杠杆、MAR=0/risk-free、lag 数 L 或书中任何 fee/risk 示例写成生产常量；不得把 zero benchmark IR、陈旧估值修正后的点估计或历史最大回撤当 promotion threshold。
- **L3 待复核**：`FORM-PORT03-CH02-001`—`029`。

### 第 3 章：利润来源、PIT 回测与回归—组合等价

- **论证链**：可重复利润需要回答交易对手为何持续站在另一侧，候选来源可分为 information advantage 与 liquidity compensation；后者又分 market liquidity、funding liquidity 和对 demand pressure 提供流动性。经济机制只生成假说，仍须用当时可得 universe/data、可执行 trading rule、时滞、OOS、成本和容量验证；predictive regression 与 portfolio sort 是同一信号—收益关系的不同表达，但统计显著不等于可交易净收益。
- **成立条件**：候选必须登记 profit source、other side、持久性、合法数据来源、基本面/noise/funding/market-liquidity 风险、催化剂与失效条件；回测逐时点解析 PIT universe、release/revision、signal、decision/arrival price、rebalance/entry/exit、position sizing、borrow/funding、transaction cost 和可交易性。参数只用模拟时点以前的数据估计，所有尝试与筛选进入 trial ledger，时间序列阈值只由过去窗口生成。
- **局限与反例**：information、risk premium、behavioral underreaction 与 demand pressure 可能给出相似价格模式，无法靠漂亮曲线唯一识别；illiquid premium 可能在 forced unwind 时集中损失，margin 与交易成本会共同恶化。当前成分股、修订后宏观/财报、同收盘信号成交、全样本均值/分位数、同样本参数估计和听说某策略赚钱后再回测都会泄漏；复杂度、反复调参、竞争与结构变化使回测系统性高估未来表现。
- **项目动作**：`CandidateEvidence` 强制 `profit_source/other_side/persistence`、PIT lineage、as-of/release/revision、signal horizon、execution lag、OOS scheme、trial count、gross/trading-net/funding-net、turnover/capacity、market/funding liquidity stress 与 falsifier；回归结果必须附对应可交易 portfolio、position normalization、成本和风险暴露。Strategy 不得因 signal 显著直接下单，仍只输出 Forecast/Target/OrderIntent，经 Portfolio/Risk、OMS、Fill/Ledger 审计链。
- **禁止直接采用**：不得迁移 300bp illiquidity premium、危机“两次/十年”、top 10%、20/10 日 breakout、1—2 日 lag、tercile、`t>2`、书中 margin/liquidity beta 或任何事件/指数/期权需求规律；不得把 gross spread、回归系数、Fama–MacBeth t-stat、历史负样本或“简单参数”当 promotion 充分条件。
- **L3 待复核**：`FORM-PORT03-CH03-001`—`035`。

### 第 4 章：稳健组合、独立风险覆盖与减仓再入场

- **论证链**：组合构建将多个 Forecast 转换为受 expected return、variance/covariance、相关、杠杆和约束共同决定的仓位；理论 mean–variance 解只是无摩擦基准，输入噪声会被矩阵求逆放大并产生极端 long/short。Risk 必须独立于策略，既在事前限制总量、单名、因子、流动性与尾部，也在 drawdown/融资恶化时按预注册规则减仓，并在恢复条件满足后确定性再入场。
- **成立条件**：所有仓位使用同一 horizon、return/covariance 单位、base currency、gross/net、cash/financing 和 constraint semantics；expected return 与 risk estimates 必须 PIT、收缩、稳定并带不确定性。risk target、hard limit、position/risk-contribution cap、VaR/ES/stress、MADD、delever steps、kill/abort、re-entry 和 owner 必须在损失前登记；压力模型同时改变相关、vol、spread、depth、margin、funding 和 liquidation cost。
- **局限与反例**：分散化在共享因子、拥挤和危机相关跳升时失效；conviction 是主观输入，不能越过 hard limits。波动率不覆盖卖尾部或 gap，历史 VaR 不描述阈值外损失且对当前仓位/结构变化敏感；ES 仍依赖尾部样本/模型。MDD/MADD、5% 单名、5%—25% vol、95%/99% VaR、25% drawdown 都是书中示例，不是项目阈值；单一历史压力和正态 sigma 叙事不能证明生存。
- **项目动作**：Portfolio 读取带 uncertainty 的 Forecast，在 turnover、cost、borrow、funding、liquidity、exposure、concentration 与 capital constraints 下求 TargetPosition；Risk 维护独立 `RiskDecisionEvidence`，输出 estimate version、risk contributions、limits、breach reason、stress losses、margin/cash runway、delever/re-entry state。OMS 只能执行通过 Risk 的 OrderIntent，Fill/Ledger 重放 PnL；Risk 数据缺失、估值陈旧、融资或对账异常一律 fail-closed。
- **禁止直接采用**：不得迁移 40%/5% position、5%—25% vol、95%/99% VaR、3 年历史窗口、25% MADD、mean–variance 闭式解、gamma、协方差矩阵、历史 LTCM/9·11/Lehman shocks 或“高 conviction 大仓位”；不得把低历史相关、低 VaR、已实现 MDD 或理论收敛当作加杠杆与 promotion 依据。
- **L3 待复核**：`FORM-PORT03-CH04-001`—`021`。

### 第 5 章：交易成本、容量、融资与流动性螺旋

- **论证链**：策略实施同时消耗 direct fees、spread、impact、未成交机会和融资利差；成本函数形状与 alpha decay 决定拆单、no-trade band、批量交易和速度。规模扩大令 marginal shortfall 上升并形成容量上限；杠杆又把 NAV、cash、long/short、derivatives、margin、borrow、collateral 与 funding spread 连成动态资产负债表。亏损、margin 上调、赎回、风险减仓和冲击可形成 liquidity spiral，迫使原本正期望策略在最差时点退出。
- **成立条件**：每笔 OrderIntent 记录 decision/arrival/benchmark、side、size、venue、spread/depth、execution/fill、fees、impact、opportunity cost 与未成交；成本模型按 size/ADV、vol、liquidity、urgency、event 和 regime 条件化并带区间。Portfolio/Risk 同时维护 gross/net/economic leverage、borrow availability/rate/recall、margin/haircut、collateral、cash/rebate/funding、counterparty、liquidation priority、capacity 与 cash runway，所有 PnL 从 fills、positions、cash ledger 推导。
- **局限与反例**：VWAP 可在自身主导成交时显示零成本，realized cost 对后测窗口敏感，effective cost 又混合外生价格移动；旧美股 bps、10% ADV、30% partial adjustment 和 OTC/电子市场分类都不具当前普适性。gross/net leverage 忽略不同方向、非线性衍生品和压力相关；cross-margining、稳定 rebate、固定 haircut 与可持续 PB funding 会在危机中失效。正常期波动和相关无法识别 forced selling、predatory trading 与跨市场 contagion。
- **项目动作**：建立 `ExecutionCostEvidence` 与 `FundingStateEvidence`：前者分解 explicit/spread/impact/delay/opportunity/failed-fill，比较 paper、decision、arrival、fill 与 post-trade marks；后者保存 long/short/notional/delta、NAV/cash、borrow/funding/rebate、margin/collateral、counterparty、headroom、stress calls 和 liquidation state。capacity 按 marginal net return、impact uncertainty、市场份额和多日退出测算；任何 borrow、margin、cash、price freshness、fill mapping 或 ledger 异常均阻断 OrderIntent。
- **禁止直接采用**：不得迁移 30% partial adjustment、5 分钟 realized mark、8.8/13.8/27/40 bps、10% ADV、3:1/5:1/1:1 leverage、45 日 notice、20% gate、10% haircut、102% collateral、1% margin-tail probability、±25/30bp funding spread、5% repo haircut或任何 liquidity-spiral价格路径；不得把 VWAP、纸面 alpha、gross return、静态 margin 或历史可融资性作为 promotion 证据。
- **L3 待复核**：`FORM-PORT03-CH05-001`—`041`。

### 第 6 章：现金流估值、终值敏感度与模型风险

- **论证链**：equity value 可由未来股东现金流按风险匹配的 discount rate 折现，也可借 clean-surplus 将其改写为 book value 加未来 residual income；Gordon、多阶段、relative valuation 和 implied cost of capital 都是对同一价值问题施加不同假设。模型输出不是可观测真值，price–value gap 可能是市场错价，也可能来自现金流、增长、终值、折现率、会计口径、comparable 或模型结构错误。
- **成立条件**：所有财报与市场输入必须 PIT、带发布/修订 vintage、币种、单位、稀释、corporate action 和 forecast horizon；dividend 广义口径需统一 distributions、buybacks 与 equity issuance。discount rate 与 cash flow 必须同属 equity 或 enterprise、nominal/real、levered/unlevered 和税后口径；terminal growth 必须满足长期可持续约束，terminal multiple 的 comparables、行业、周期与 accounting definitions 必须可审计。
- **局限与反例**：DDM 对长期 growth/discount-rate 差极敏感，terminal value 常主导结果；`g<k` 只解决稳态数学条件，不证明输入经济合理。CAPM required return、constant k/g、40× P/D、industry average P/E 与 implied IRR 都可能因 regime、leverage、会计质量和 selection 失真；positive earnings 仍可产生 negative residual income。自动化系统不能把 discretionary conversations 或不可重放 soft information 当 PIT feature。
- **项目动作**：建立 `ValuationEvidence`：保存 as-of、model/version、equity/enterprise、cash-flow definition、forecast vintages、discount-rate decomposition、growth/terminal assumptions、terminal-value share、comparable set、accounting adjustments、scenario/sensitivity、interval、market price、alternative models 与 falsifier。其输出只能成为 Forecast 特征或研究证据，Portfolio/Risk 再结合成本、流动性、borrow、uncertainty 和 exposure 形成仓位。
- **禁止直接采用**：不得迁移 beta=1.2、market premium=5%、risk-free=2%、required return=8%、40× P/D、constant growth/discount、CAPM、Gordon、多阶段或 residual-income 点估值；不得把 intrinsic value、margin of safety、high implied return、低 P/E/P/B 或 model–price gap 自动命名 alpha、设仓位或形成 promotion 结论。
- **L3 待复核**：`FORM-PORT03-CH06-001`—`016`。

### 第 7 章：定性研究、价值陷阱与访谈证据边界

- **论证链**：discretionary equity 将 valuation、business quality、management、industry dynamics、catalyst 和 capital reallocation 组织为可更新 thesis；value 与 quality 不能只看低价格或高增长，需区分 price mean reversion 与 fundamentals deterioration、good growth 与 empire building、reported earnings 与可持续 cash flow。经理访谈展示研究组织与风险思维，但属于自述和幸存者样本，不能直接转译为系统参数。
- **成立条件**：每个 thesis 必须保存 as-of、来源/许可、事实与判断分离、consensus baseline、valuation scenarios、quality/management proxies、catalyst、holding horizon、position rationale、counter-thesis、falsifier、kill condition 与更新时间；soft information 只有在合法、可审计、可时间戳和可复核时才能进入研究记录。量化映射必须使用 PIT filings/financials/estimates/corporate actions，并独立验证成本、borrow、capacity、factor exposure 和 OOS。
- **局限与反例**：intrinsic value、quality、management integrity 和 competitive advantage 都含主观判断；low P/B 可因 book value 下修而“回归”，growth 可由低价、并购或会计提前确认制造。Buffett/Maverick 的回报、杠杆、融资与组织条件不可复制，访谈会选择性披露成功流程；单个破产案例只能提示 management/execution risk。catalyst、activism、flow anticipation、front-running 与公开做空报告还涉及当前法律、市场操纵与信息来源边界。
- **项目动作**：建立 `QualitativeThesisEvidence`：记录 claim、source class、as-of、observable proxies、consensus、valuation/quality decomposition、management/catalyst、expected horizon、alternative explanations、falsifier、decision owner 与 review history；低可信访谈只生成待验证候选，不进入自动 Signal。研究输出必须经过 Forecast schema、Portfolio/Risk 与客观数据交叉验证，不允许人类叙事直接产生 OrderIntent。
- **禁止直接采用**：不得迁移 margin of safety 图示、P/B/value/quality/GARP/QARP 标签、Buffett 0.76 Sharpe/19% excess/25% vol/1.6× leverage、2—3 年 horizon、4:1 positions/staff、1 年 holding、5% 13D、45%/30%—60% net exposure或任何经理格言；不得将管理层访谈、调查员观察、公开报告、明星业绩或破产故事视为可重放 alpha。
- **L3 待复核**：`FORM-PORT03-CH07-001`—`030`。

### 第 8 章：借券合同、强制回补与做空非对称性

- **论证链**：short 不等于 long 的镜像：卖出所得被抵押并额外占用 margin，borrow availability、rebate/loan fee、daily roll、recall/buy-in 和法规会在 thesis 收敛前终止交易；价格上涨同时造成 mark-to-market loss 与更高美元 margin，集体回补可形成自我强化 squeeze。short frictions 可能让悲观看法无法进入价格，但 high short interest/fee 既可能反映信息，也可能反映拥挤、难借和极端尾部风险。
- **成立条件**：下单前必须取得 instrument/date/quantity/venue/counterparty 级 locate，保存 fee/rebate、term、collateral、margin、recall notice、buy-in、corporate action、tax 与 legal status；估算 position 的 mark-to-market、borrow accrual、gap、price-multiple、margin-call、recall-cluster 和 cover-impact 路径。fundamental red flags 使用 PIT filings/restatements/insider transactions/related parties，并同时记录 bull case、已入价程度、反证和 cover trigger。
- **局限与反例**：书中 90% easy-to-borrow、0.10%—0.20%/1%—50% fee、100→105、20% margin 和实证 3% 月度异常收益均为旧样本；证券借贷可重用不保证实际 locate，short-interest 可超过 float 也不代表可持续可借。Enron/AOL 和 Chanos 访谈具有事后选择、幸存者与自述偏差；涉嫌欺诈、公开批评、MNPI、front-running/manipulation 和临时禁空均受当前法律约束。
- **项目动作**：建立 `ShortAvailabilityEvidence` 与 `ShortRiskState`：前者记录 as-of locate、available quantity、fee/rebate、term、recall/buy-in、counterparty、corporate action 和 source；后者记录 market/borrow exposure、margin/cash headroom、price-multiple stress、crowding、days-to-cover、gap/squeeze loss、cover liquidity 与 hard caps。Strategy 只生成 negative Forecast，Portfolio/Risk 在 borrow 与压力证据完整时才允许负 TargetPosition；OMS 在 recall/fee/margin/freshness 异常时禁止新增并确定性减仓。
- **禁止直接采用**：不得迁移 loan-fee分布、3%异常收益、Enron 7%/9%、AOL 8倍/1%仓位/5%—7%损失、50只/5%/3%/2%/1%仓位或“never leveraged”；不得把 high short interest、high fee、insider selling、CEO离职、opaque filing、低 ROC、公开做空报告或 fraud 叙事自动转成 short signal 或 promotion 证据。
- **L3 待复核**：`FORM-PORT03-CH08-001`—`030`。

## 已完成 L2：第 9 章

### 第 9 章：因子契约、组合中性与拥挤流动性风险

- **论证链**：量化股票把经济信念编码为可重复模型，以广覆盖、纪律和组合工程换取大量小 edge；fundamental quant、stat arb 与 HFT 的持有期、容量、成交决定方式和可回测性不同。value、momentum、quality、low-risk/BAB 只是风格标签，真正收益同时混合风险补偿、行为偏差、制度约束、交易摩擦和偶然性；组合层还会暴露 market、industry、factor、crowding、funding 与 liquidity risk。
- **成立条件**：每个因子必须冻结 universe、PIT accounting/price vintage、signal formula、lag、winsorization/normalization、breakpoints、rebalance、weighting、long/short eligibility、borrow、market/beta/industry/factor neutralization、volatility target、cost、capacity 与 benchmark。新增信号必须有事前经济机制，并通过跨时期/地区或适用资产的真正 OOS、发现后样本、机制中间变量、增量组合贡献和全成本检验。
- **局限与反例**：book-to-market、12—1 momentum、quality、low beta 与 residual reversal 都可能受定义、会计制度、微盘、行业、风险模型、卖空和成本驱动；历史负相关不保证压力期分散。2007 quant event 显示许多表面 market-neutral 组合可因重叠持仓、共同去杠杆和流动性撤回同步崩跌；30-sigma 叙事通常说明正态/稳定波动模型失效，而不是事件不可重复。stat arb 的“关系”可被 corporate actions、币种、fungibility 和 leg execution 打断；HFT 回测受订单本反身性、延迟、排队和数据质量约束。
- **项目动作**：建立 `FactorDefinitionEvidence`、`FactorPortfolioEvidence` 与 `CrowdingStressEvidence`：前者保存定义、PIT lineage、训练/OOS、trial ledger 和版本；中者保存 exposures、neutralization residual、turnover、borrow、decision/arrival/fill 成本、capacity 与净贡献；后者保存持仓重叠代理、流动性/融资冲击、相关跳升、共同去杠杆、现金 runway 和 deterministic delever/re-entry。Strategy 仍只输出 Forecast/Target/OrderIntent；HFT、队列、被动成交和 private/order/live 表面在无专门证据与授权时保持 blocked。
- **禁止直接采用**：不得迁移 top/bottom 30% 或 10%、12—1 窗口、130/30、1.4/0.7 beta 缩放、6% 波动目标、历史 Sharpe、4 日约 25% 损失、90% 十分钟下跌、30-sigma、75,000 合约、20 分钟执行或任何历史 value/momentum/quality/BAB 回报；不得把 dollar-neutral 当 beta-neutral，把低历史相关当压力分散，把 gross factor return 当可实现 alpha，或把经理访谈与单次危机复盘当 promotion evidence。
- **L3 待复核**：`FORM-PORT03-CH09-001`—`040`。

## 已完成 L2：第 10 章

### 第 10 章：配置层级、收益分解与风险预算

- **论证链**：资产配置先区分可投资集合、长期 policy/benchmark、围绕基准的 tactical tilt 和类内 security selection；所谓被动、恒定权重、流动性配置与 risk parity 实际承担不同交易、融资和风险来源。股票、债券、信用和货币回报可进一步拆成 cash yield/carry、growth、valuation 或 spread change 与损失项，但这些恒等式和近似不直接给出可实现 expected return。
- **成立条件**：配置证据必须固定 universe、benchmark、币种、risk-free、horizon、rebalance、cash flow、cost、tax、liquidity、financing、covariance、tail dependence 与风险贡献口径。任何 timing predictor 必须按发布 vintage、当时可得阈值和 expanding/rolling 估计形成真正 OOS；跨资产回报分解需统一 total payout、inflation、duration、default/recovery、quote convention 与复利单位。
- **局限与反例**：market portfolio 的均衡一致性不证明适合当前负债或交易范围；constant-weight 隐含逆势交易，illiquid allocation 会阻断再平衡。risk parity 的相似 Sharpe、稳定波动和相关性假设会在压力期失效，且 leverage 引入 margin 与 forced delever。dividend-yield timing 的历史回归存在持久预测量偏误、选择偏差、估计误差和 OOS 失败；美国长期回报、CAPE、信用损失与 PPP/carry 统计均受样本、制度和时代限制。
- **项目动作**：建立 `AllocationEvidence`：保存 strategic benchmark、tactical thesis/falsifier、asset/strategy expected-return decomposition、uncertainty、risk contribution、liquidity/cash runway、funding/margin、shared factor/tail exposure、rebalance/cost 与归因。当前可用于检查 BTC 与美股策略是否共享 equity/liquidity/macro beta，但不得因“跨资产”标签假定分散；债券、信用和 FX 在缺数据、执行、账本与权限合同时保持 out of scope。
- **禁止直接采用**：不得迁移 60/40、inverse-vol、equal-risk、任何 leverage、1926—2013 回归系数、median split、11.2%/4.2%、历史 equity premium、2%/3.5% growth、十年 CAPE、duration/credit-loss、carry/PPP 或澳元示例；不得把 full-sample high/low、长期均值、美国样本、gross carry 或名义资本分散当 production 参数、可实现 alpha 或 promotion evidence。
- **L3 待复核**：`FORM-PORT03-CH10-001`—`030`。

## 已完成 L2：第 11 章

### 第 11 章：宏观假说、政策时点与反身反馈

- **论证链**：global macro 把 carry、央行 reaction function、增长/通胀 shock、国家相对价值/趋势、贸易与政治事件组织成跨市场表达；任何收益都同时承担汇率、曲线、融资、流动性、拥挤与政策内生性。Soros 的 reflexivity 强调价格、信用、抵押品和行为会反过来改变 fundamentals，但其核心价值是提醒模型在 far-from-equilibrium 状态可能失效，而不是提供可知的泡沫转折公式。
- **成立条件**：宏观输入必须保存 release time、vintage/revision、调查期、预期值与 surprise，区分会计恒等式、结构假说和经验相关。每个 thesis 需列出 legs、horizon、carry/cost、shared beta、政策/法律状态、替代解释、falsifier、kill condition 与 owner；regime 只能是概率性 context。跨资产因子还需各自 PIT 定义、roll、currency hedge、borrow/funding、成本、OOS 和 capacity。
- **局限与反例**：carry 具有负偏度并在资金紧张时跨市场同步 unwind；peg 可在长期稳定后突然断裂。Taylor rule、Phillips curve、AS/AD 与四象限都是依赖制度和时点的近似；央行目标会变，GDP/TFP/通胀会修订。跨资产 value/momentum 的旧样本、费用前 Sharpe 和负相关可能受选择与危机相关跳升影响；主题和反身性阶段不可预知。Soros 访谈同时承认错误预测和不可知转折，名人成功不修复这些识别问题。
- **项目动作**：建立 `MacroContextEvidence`：记录 as-of/release/vintage、consensus/surprise、shock type/horizon、policy regime、market pricing、trade legs、carry/cost、shared exposure、feedback indicators、uncertainty 与 falsifier。当前只作为 BTC/美股 Forecast 的背景特征候选和压力情景来源；rates、FX、credit、commodity 在缺数据、执行、账本与权限合同时保持 out of scope，任何 private/order/live 表面保持 false。
- **禁止直接采用**：不得迁移澳元/日元 4%、3× carry、任何 carry Sharpe、Taylor 4%/1.5/0.5、NAIRU、growth-inflation 资产表、五年 reversal、PPP、图中 value/momentum 相关、2% peg band、Soros 大仓位或利润后加风险；不得用修订后宏观数据、事后 shock/regime、briefcase 轶事、主题故事或反身性标签直接择时、定仓或形成 promotion 结论。
- **L3 待复核**：`FORM-PORT03-CH11-001`—`034`。

## 已完成 L2：第 12 章

### 第 12 章：趋势证据、波动缩放与尾部边界

- **论证链**：time-series momentum 用单一市场过去 excess return 的方向形成 long/short，并通过单资产波动缩放、跨资产/期限组合和持续再平衡争取捕捉逐步展开的价格路径。书中把趋势分为 catalyst 后 underreaction、资金流与 herding 延续、过度延伸后 reversal；这种机制既可产生 crisis alpha，也会在瞬时跳跃、快速反转或既有同向仓位下放大损失。
- **成立条件**：趋势证据必须冻结 continuous-contract/roll、excess-return、lookback、signal lag、vol estimator、target、covariance、rebalance、decision/arrival/fill、fees、margin、cash 与 universe vintage。组合层需报告每个市场和资产类 risk contribution、rolling/stress correlation、turnover、capacity、gap/reversal/whipsaw 与 delever/re-entry。任何跨资产结论必须来自相应市场数据和执行合同，不能由单 BTC 回测外推。
- **局限与反例**：1/3/12 月、40% 单资产波动和 10% 组合目标是历史研究设计，不是最优参数；gross Sharpe、传统因子 alpha、smile 与低平均相关受 hindsight、选择、费用、遗漏因子和危机路径影响。equal-vol 不处理跳跃、流动性和相关聚集；daily/weekly gross 优势可能被成本吞噬。书中最大经理样本有事后选择，模拟费用与历史交易成本不确定；Harding 也明确指出 CTA 在 crash 前持多股票时可能成为 tail exacerbator。
- **项目动作**：建立 `TrendStrategyEvidence`：记录 market/universe、signal formula/version、PIT price/roll、horizon ensemble、vol/covariance、gross/net exposure、cost/capacity、margin/cash、attribution、crowding 与 tail scenarios。BTC 与美股策略可复用该证据结构，但必须分别验证 trend persistence、成本、borrow/funding 和执行；Strategy 只输出 Forecast/Target/OrderIntent，Portfolio/Risk 独立决定风险预算和强制降杠杆。
- **禁止直接采用**：不得迁移 58 个市场、1/3/12 月窗口、40%/10% 波动目标、EWMA/covariance参数、周四信号周五收盘、任何历史 Sharpe/alpha/t-stat/R²/相关、2-and-20、1%—4%成本、8%—12% margin 或经理窗口偏好；不得把 underreaction/herding 故事、低平均相关、历史 crisis 表现、CTA 标签或“agnostic”自述当生产参数、tail hedge 或 promotion evidence。
- **L3 待复核**：`FORM-PORT03-CH12-001`—`032`。

## 已完成 L2：第 13 章

### 第 13 章：复制关系、收敛条件与套利生存风险

- **论证链**：教材 arbitrage 以相同或更优 payoff、零净投入和确定收敛为定义；实务 relative-value 通常需要 margin、borrow、动态 hedge 与多腿执行，价差可能先扩大甚至永不收敛。no-arbitrage 可通过同证券、复制组合或 self-financing strategy 给出相对价格，但交易摩擦把点价格改成区间，fungibility、自然到期和中介资本决定关系强弱。
- **成立条件**：任何套利候选必须冻结各 leg 的 instrument/venue/currency/settlement、cash-flow/payoff、exercise/dividend、quote time、transferability、convergence event、borrow/funding/margin、spread/impact、hedge rule、model/version 与 path cash。理论 risk-neutral probability 只用于定价，不得当真实方向概率；多腿 PnL 必须从 fills、positions、cash 与 collateral ledger 重建。
- **局限与反例**：dynamic replication 对离散成交、jump、stochastic volatility、gamma 和成本敏感；到期 payoff 匹配也不能避免中途 margin call。put-call parity 受 dividend、short constraint、early exercise 和 settlement 影响。BSM market-model gap 可能是模型或 volatility 错而非 mispricing，OTM put smirk可反映真实 crash risk；需求压力在受限中介下会持续，卖保险获得的是承担尾部风险的 expected premium，不是确定套利。
- **项目动作**：建立 `ArbitrageRelationEvidence`：保存 legs/payoff、replicating portfolio、upper/lower bound、convergence clock、fungibility、funding/margin、borrow、execution atomicity、basis/model error、stress loss 与 kill condition。该结构可用于审查未来相对价值候选，但当前系统缺 options surface、curve、multi-leg OMS、collateral 与动态 hedge ledger，所有 options、rates 和多腿 arbitrage 保持 research-only/blocked。
- **禁止直接采用**：不得迁移 put-call parity、binomial delta/cash、risk-neutral q、BSM/d1/d2、implied-vol高低、每日delta hedge、smirk、保险需求或任何理论 $2 mispricing 为生产交易；不得把相近证券、dual listing、同underlying、终值复制或模型价格差称为无风险、ready 或 promotion evidence。
- **L3 待复核**：`FORM-PORT03-CH13-001`—`019`。

## 已完成 L2：第 14 章

### 第 14 章：曲线相对价值、融资流动性与资本生存

- **论证链**：fixed-income arbitrage 用 duration、convexity、forward、curve factor 与 multi-leg hedge 隔离部分利率风险，再承接 carry、clientele demand、repo specialness、spread 或 basis。价差通常很小，因此策略依赖杠杆和稳定融资；目标 basis 正是未被 hedge 的风险，clientele flow 若继续、repo恶化或中介同步减仓，所谓 convergence trade 会先成为大额 mark-to-market loss。
- **成立条件**：需要完整 zero/forward curve、coupon/day-count/settlement、key-rate duration/convexity、repo/CSA/margin、specialness、borrow、multi-leg fills、cash/collateral 与 counterparty ledger。每项 relative-value thesis 必须保存 curve/model version、flow source、convergence clock、carry/funding decomposition、residual node/basis、stress widening、cash runway 与 kill condition；risk-neutral/forward 隐含量不得误作真实预测。
- **局限与反例**：duration immunization只覆盖小幅平行移动，butterfly仍保留kink和模型误差；carry、roll-down与term premium受曲线变化和风险偏好影响。on/off-the-run、swap spread、credit、MBS与vol trade分别叠加market/funding liquidity、benchmark/credit、default/recovery、prepayment/negative convexity和jump/model risk。Scholes访谈强调flow与mean reversion，却也指出压力期physical/human capital同时稀缺，中介会从流动性供给者变成流动性需求者。
- **项目动作**：把本章抽象为 `FundingLiquidityStressEvidence`：记录 gross/net exposure、risk contribution、funding rate/maturity、margin/collateral、counterparty concentration、liquidity/impact、crowding、basis widening、cash runway、investor redemption 与 deterministic delever/re-entry。该合同可用于 BTC 和美股组合压力测试；但 repo、bond curve、swap、CDS、MBS、rates options 与 multi-leg execution 在无数据、账本和权限时全部保持 blocked。
- **禁止直接采用**：不得迁移任何 YTM/duration/convexity/forward/butterfly/carry/on-off PnL、swap/credit/MBS公式、期限、0.23 hedge ratio、2013 Treasury、历史 spread、LIBOR、repo specialness、default/recovery、dealer flow 或经理阈值；不得把 duration-neutral、curve-smooth、high carry、wide spread、model discrepancy 或 client demand 称为无风险、可实施或 promotion evidence。
- **L3 待复核**：`FORM-PORT03-CH14-001`—`041`。

## 已完成 L2：第 15 章

### 第 15 章：多腿 Greeks、融资螺旋与事件条款

- **论证链**：convertible bond 把 straight debt、equity conversion option、issuer call/put 与 credit 放在同一合同中；典型 arbitrage long convertible、short delta stock，并可能再对冲 rates/credit。收益来自 coupon/carry、gamma/realized volatility 与 model discount 收敛，同时支付 financing、short dividend/fee、theta、交易成本，并承受 vega、default、borrow、event 和 dynamic-hedge residual。
- **成立条件**：必须逐券解析 indenture、conversion/call/put/make-whole、seniority、coupon、maturity、corporate event 与 settlement；保存 valuation/model version、delta/gamma/vega/theta、stock borrow、rates/credit hedge、multi-leg fills、cash/collateral、margin、counterparty、liquidity/capacity 与 terminal-event ledger。理论价差、Greek 与转换决策必须按当前条款和可成交价格复核。
- **局限与反例**：straight-bond+call 是粗略分解，credit 与 equity 联动可使低价区域出现 negative gamma；delta hedge对 jump、离散成交和borrow不完美。positive gamma并非免费，必须支付theta、vol premium和rehdge成本。2008 显示 systematic cheapening、margin上调、融资撤回和market illiquidity同步发生，convertible甚至可比同issuer straight debt更便宜；takeover还可能造成long bond与short stock双亏。
- **项目动作**：抽象 `MultiLegRiskEvidence`：记录 leg/payoff、Greek/exposure、borrow/funding、margin/collateral、cash-flow attribution、event terms、basis/model error、liquidity spiral、gap/default/takeover 与 deterministic closeout。该结构可用于未来复杂策略审查及当前 BTC/美股多风险暴露压力测试；但本项目缺 convertible master、options surface、credit、borrow 和 multi-leg OMS/ledger，策略实施保持 blocked。
- **禁止直接采用**：不得迁移 conversion/parity公式、任何 BSM/tree/Greek、55→85→55、13.4/18.6股、gamma profit、theta/vega结论、历史折价、分类、prime-broker leverage、596券样本、takeover protection、Griffin额外short或dealer关系；不得把 theoretical cheapness、positive gamma、high moneyness、hard-to-borrow edge、危机后反弹或名人案例称为可实现 alpha 或 promotion evidence。
- **L3 待复核**：`FORM-PORT03-CH15-001`—`030`。

## 已完成 L2：第 16 章

### 第 16 章：事件状态机、交易条款与跳空尾部

- **论证链**：merger arbitrage 通过买入 target、并按 cash、fixed/floating exchange 或 collar 条款对冲 acquirer 风险，赚取 deal spread；但真正保留的是无法对冲的 completion、renegotiation、financing、regulatory 与 failed-deal gap。spin/split/carve-out、distressed、capital-structure 和 index/event flow 同样依赖强制买卖、复杂条款或受限资本提供流动性，而不是无风险价格收敛。
- **成立条件**：每个事件必须有 PIT 公告与文件版本、event type、consideration/payoff、exchange ratio/collar、关键日期、审批/投票/融资/税务/诉讼状态、break fee 与退出条款；逐日重建 completion/failure/competing-bid 情景、deal spread、downside gap、borrow/recall、dividend、funding、margin、交易成本和 cash runway。仓位应以失败损失和组合容忍度反推，并限制单事件、单行业、同监管和同融资来源集中度。
- **局限与反例**：单笔 hedge 不能消除熊市中 deal failure 同步上升，组合呈近似 short-put 的非线性 beta；index future 或 put overlay 又可能昂贵且 basis 不稳。negative stub 会因不分配、税务、破产、退市、hard-to-borrow、buy-in 和 margin call 长期不收敛；distressed 与 bankruptcy 依赖管辖法、债权顺位、重组投票和主动治理。书中历史 spreads、失败率、RAIM 回报、案例利润、Paulson 仓位和次贷瀑布均不可跨时代直接迁移。
- **项目动作**：建立 `EventStateEvidence`，保存 immutable announcement/terms/version、状态迁移、payoff legs、hedge ratio、completion/failure/renegotiation scenarios、expected return range、gap loss、legal/regulatory/financing owner、borrow/funding/margin、liquidity/capacity 与 deterministic exit。该合同可作为未来事件研究和现有组合 gap stress 的模板，但 Strategy 仍只输出 Forecast/Target/OrderIntent，Portfolio/Risk 独立批准，OMS/Fill/Ledger 才能形成 PnL。
- **禁止直接采用**：不得迁移 deal spread 年化、10% 失败率、3%—10% 单笔上限、历史 11.1% 回报、short-put alpha、stub hedge、1,000bp distressed 定义、capital-structure model、index inclusion effect、10% 公司持股、100:1 次贷赔率或任何名人案例；不得基于 MNPI、未验证传闻、事后完成状态、当前并购数据库、法律意见或不可审计行业关系生成信号。当前缺 event master、条款解析、法律/监管、borrow、corporate-action 与 multi-leg ledger，实施保持 blocked。
- **L3 待复核**：`FORM-PORT03-CH16-001`—`046`。

## 下一轮精读重点

全书 16 章 `L2` 已完成，下一步先做章节边界、来源位置、项目映射和 491 项队列的全书一致性审计，再按风险优先级推进 `L3` 原式/原研究复核与跨书 Agent 手册汇总。公式、费用、业绩、统计阈值、因子参数、成本、融资、估值、借券、拥挤、宏观、趋势、套利、曲线、多腿、事件条款或访谈经验在复核前均不得当作生产事实。
