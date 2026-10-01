---
book_id: EXE-01
title: Trading and Exchanges
authors: [Larry Harris]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Trading and Exchanges - Larry Harris - 原文.md
source_format: epub_text
source_sha256: d8da33f59d169116e9ba1ae454567f9d67df8c025627f7ba3133169d27c64883
source_line_count: 18373
card_status: chapter_semantic_review_l2_complete_formula_pending
chapter_count: 29
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 813_items_identified_pending_ch01_ch02_ch03_ch04_ch05_ch06_ch07_ch08_ch09_ch10_ch11_ch12_ch13_ch14_ch15_ch16_ch17_ch18_ch19_ch20_ch21_ch22_ch23_ch24_ch25_ch26_ch27_ch28_ch29
last_reviewed_at: 2026-07-13
---

# EXE-01：Trading and Exchanges

## 覆盖声明

本卡按 EPUB 正文章节而非后置 bibliography 定位 29 章，并完成全部章节的 `L1` 项目映射与 `L2` 语义精读，覆盖 `29/29=100%`；当前共登记 813 项待 `L3` 复核。市场制度、价差/冲击度量、broker 监管、信息交易、法律讨论与绩效公式不能直接当作当前 OKX、美股或 A 股 venue/法域事实。

## 全书项目映射

- `existing_rule_confirmed`：订单不等于成交，交易者动机、流动性、信息不对称和代理问题共同决定执行结果。
- `implementation_gap`：成本 attribution 仍需统一 fee、spread、slippage、impact、delay、funding/borrow 和 opportunity cost。
- `rejected_for_now`：历史交易所制度、floor/specialist 机制和案例不直接映射当前 venue。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Introduction | `653-800` | `L2/medium` | market microstructure研究谁交易、为何交易、如何搜索和组织成交，以及规则/信息系统如何共同决定liquidity、transaction cost、informative price、volatility与relative trading profit；它不替代instrument valuation、portfolio mandate、法律或税务判断。 | `domain_boundary_contract`：Strategy、Portfolio/Risk、OMS/Execution、Fill/Ledger、venue/broker与governance分层；任何利润解释同时登记other side、cost、information asymmetry、market structure、agency与settlement证据。 | `FORM-EXE01-CH01-001`—`018` |
| 2 Trading Stories | `803-1062` | `L2/medium` | 零售、机构、block、cash/futures hedge、option、bond 与 FX 案例共同展示 intent→authorization→routing/search→matching/negotiation→report/confirm→allocation→clearing/settlement 的链条；urgency、size/ADV、display/latent interest、routing incentive、broker discretion、basis/multi-leg 与 post-trade quote 会改变结果。 | `trade_lifecycle_scenario_contract`：案例只转化为跨资产fixture/failure mode，逐场景固定parent objective、capability、timestamps、quotes/books、child orders、fills、fees、allocation、clearing/settlement与reconciliation；不迁移旧venue/价格/税率/T+3。 | `FORM-EXE01-CH02-001`—`025` |
| 3 The Trading Industry | `1079-1774` | `L2/medium` | trading industry把beneficiary、sponsor、manager、trader、broker/dealer、venue、clearing、settlement、custody与regulator连接起来；instrument contract、market model、volume口径和法域共同决定角色责任，历史机构名称不能替代当前capability。 | `trading_industry_topology_contract`：显式记录principal/agent、asset/cash owner、decision/execution authority、venue/access、instrument/settlement、CCP/custody、volume lineage与rule authority/version；职责冲突和缺失状态fail-closed。 | `FORM-EXE01-CH03-001`—`030` |
| 4 Orders and Order Properties | `1777-2222` | `L2/medium` | 订单是带 instrument、side、quantity、price、activation、validity、display、settlement 和 routing 条件的交易意图；market 与 limit 分别承受价格不确定和成交不确定，stop 也不保证止损价。 | `order_semantics_contract`：`OrderIntent`、Order、Ack、Fill/Cancel 分离；只允许 capability 声明支持的 type/TIF/quantity/display/settlement，并显式处理 partial fill、gap、stale order 与 multi-leg atomicity。 | `FORM-EXE01-CH04-001`—`022` |
| 5 Market Structures | `2225-2738` | `L2/medium` | market structure由session、execution model、access、routing、information distribution、transparency、identifier与order-book规则共同定义；相同策略在不同call/continuous、quote/order/brokered或hybrid结构下不具可迁移性。 | `market_structure_capability_contract`：按venue/rule version保存session/auction、execution model、tick、access、routing/ack/cancel、data entitlement/latency、pre/post-trade visibility、book/display与canonical instrument ID；未知能力fail-closed。 | `FORM-EXE01-CH05-001`—`030` |
| 6 Order-driven Markets | `2741-3226` | `L2/medium` | order-driven 成交由 precedence 排名、matching、partial fill/remainder 与 trade-pricing rule 顺序决定；continuous、call 与 crossing 的定价和成交不确定不同。 | `matching_engine_contract`：保存规则版本、price/time/display/size precedence、queue state、allocation、incoming/resting order、trade price、partial fill、auction imbalance/clearing 与 reference-price freshness；触价不等于成交。 | `FORM-EXE01-CH06-001`—`021` |
| 7 Brokers | `3229-4064` | `L2/medium` | broker 同时承担代理、接入、清算结算、信用、路由、托管/公司行动与审计职责，其佣金、PFOF、利息、借券和自营收入会产生 principal-agent 冲突。 | `broker_capability_contract`：按 execution/clearing/custody/credit/borrow/data/reconciliation/asset-protection 分权；记录 routing 与利益冲突、best-execution、pre-trade limits、immutable audit、independent statements 和 failure/insolvency 处置。 | `FORM-EXE01-CH07-001`—`028` |
| 8 Why People Trade | `4075-4604` | `L2/medium` | 每笔交易应先声明要解决的投资/融资、资产交换、风险转移、信息、流动性或学习问题；相同flow/volume可由不同动机产生。hedge只在underlying exposure、vehicle correlation、basis、quantity和cash-flow匹配时降低风险，不能把交易动机或对手类型从结果反推。 | `trade_objective_and_hedge_contract`：保存objective/mandate、underlying exposure、edge或utility、alternative motives、hedge ratio/basis/residual risk、cost、authority与falsifier；交易/结算职责分离，越权、stale information和无法解释目的均fail-closed。 | `FORM-EXE01-CH08-001`—`030` |
| 9 Good Markets | `4607-5060` | `L2/medium` | good market不是单一spread、volume、speed或price-efficiency指标，而是先声明评价对象、备选结构、受益/受损主体及liquidity、transaction cost、informativeness、volatility、access与reliability之间的权衡；positive evidence与normative preference必须分离。 | `market_quality_decision_contract`：预注册alternatives、criteria/weights、stakeholders、metrics/baselines、data/rule versions、uncertainty和trade-offs；任何venue、规则或promotion判断不得由单一market-quality指标解锁。 | `FORM-EXE01-CH09-001`—`030` |
| 10 Informed Traders and Efficiency | `5075-5562` | `L2/medium` | 信息交易只有在估值/新闻/模式/相对价值判断优于市场且尚未进价、可在冲击与全成本后实施时才有正期望；价格发现同时向流动性提供者征收 adverse-selection 成本。 | `information_edge_contract`：登记 source legality/PIT、consensus/price-implied baseline、horizon/expiry、other side、signal uniqueness/correlation、impact/cost/capacity、alternative explanation 与 falsifier；stale/pseudo-information 不得形成 alpha。 | `FORM-EXE01-CH10-001`—`023` |
| 11 Order Anticipators | `5565-5906` | `L2/medium` | order anticipation利用已决定、尚未决定或被迫发生的交易，而非fundamental information；front running、quote matching、sentiment flow、squeeze与stop cascade分别依赖confidentiality、display/cancel、predictable flow、position closure和trigger exposure。异常价格/成交不能单独证明意图或违法。 | `order_exposure_and_anticipation_contract`：记录parent confidentiality、audience、route/exposure、split/display、queue/tick、borrow/deliverable、stop visibility、pre/post-order markout与alternative hypotheses；授权不明、泄漏或单一路径退出fail-closed。 | `FORM-EXE01-CH11-001`—`030` |
| 12 Bluffers and Manipulation | `5909-6208` | `L2/medium` | rumormonger通过虚假或误导性叙事改变他人判断，price manipulator通过真实交易、协同/wash活动或路径依赖的size/timing制造错误price/volume inference；但相同轨迹也可能来自合法投机、新闻、流动性或估值分歧，intent与违法不能由反转或盈利单独证明。 | `manipulation_risk_evidence_contract`：保存source authenticity/PIT、identity/linkage、order/fill path、side-size-speed impact、round trip、counterparty、communications/access和alternative hypotheses；只输出risk flag，法律定性与处置由当前规则和授权责任人完成。 | `FORM-EXE01-CH12-001`—`030` |
| 13 Dealers | `6227-6640` | `L2/medium` | dealer出售immediacy并承担未知下一手价格、inventory financing、one-sided flow与adverse selection；quoted spread不是利润，只有可由双边fills、inventory/cash ledger、markout、hedge与capital约束重建的realized spread才是证据。 | `dealer_capability_and_inventory_contract`：要求firm two-sided quote、size/expiry、inventory target/limit、quote skew、fills/fees/hedges、adverse-selection markout、capital/margin和kill/reconcile；当前缺真实双边与private fill，维持`rejected_for_now`。 | `FORM-EXE01-CH13-001`—`030` |
| 14 Bid/Ask Spreads | `6643-7156` | `L2/medium` | bid/ask spread 是即时性的价格，由正常经营/订单管理成本、库存与风险补偿、限价单 timing option、竞争和 adverse selection 共同决定；transaction-cost/transitory 与 adverse-selection/permanent 两部分的价格反转性质不同。 | `spread_mechanism_contract`：以当前 venue、订单方向、quote/book 时点、费用、取消延迟、波动、成交后 markout 和流动性竞争证据解释价差；quoted spread 不能单独证明总成本、做市利润或信息优势。 | `FORM-EXE01-CH14-001`—`029` |
| 15 Block Traders | `7159-7510` | `L2/medium` | block不是固定股数，而是相对当前正常容量难以成交的parent order；其成本来自latent-demand search、order exposure、对后续size的price-discrimination担忧及adverse-selection怀疑。broker/dealer、hidden/split/sunshine和delayed reporting只是不同信息—库存—透明度权衡。 | `large_order_capacity_and_exposure_contract`：按size/ADV/depth/time、latent search、audience/exposure、parent aggregation、concession、dealer inventory、reporting delay和precedence记录；当前小账户只保留capacity stress，不迁移block desk。 | `FORM-EXE01-CH15-001`—`030` |
| 16 Value Traders | `7513-7718` | `L2/medium` | 价值交易者只在价格与其基本价值估计显著偏离时承接流动性，直接或经dealer提供depth与resiliency；但其outside spread必须覆盖adverse selection、winner's curse、研究、融资、持仓和等待收敛的风险。 | `valuation_and_convergence_evidence_contract`：保存PIT估值模型/区间、信息集、偏离幅度、流动性需求者假说、收敛机制/期限、资金/借券、容量、成本和反证；价值与新闻交易纪律分离。 | `FORM-EXE01-CH16-001`—`024` |
| 17 Arbitrageurs | `7721-8458` | `L2/medium` | 套利交易的是由多腿构成的hedge portfolio，其信号是basis相对动态fair value越过含成本的bounds；pure与speculative arbitrage分别依赖可验证收敛机制和短期均值回归压过非平稳特定因素，二者都承受执行、基差、模型、carry与资本耗尽风险。 | `relative_value_and_multileg_execution_contract`：保存PIT fair-value模型、共同/特定因素、hedge ratio、收敛机制/期限、多腿原子性或顺序、borrow/funding/margin、全成本、容量、结构断裂与实际fills/ledger；相关性和gross spread不能解锁交易。 | `FORM-EXE01-CH17-001`—`036` |
| 18 Buy-Side Traders | `8461-8768` | `L2/medium` | buy-side执行是基于objective、urgency、value、spread/depth、limit fill probability与未成交后果的条件策略；order exposure提高对手发现和latent liquidity，却会泄露动机、未来冲击及免费交易期权。 | `buy_side_execution_and_exposure_contract`：Portfolio给出目标/期限/limit与容量，OMS记录market/limit、display/audience、parent拆分、broker/venue、fill概率、泄漏与实际fills；仅允许合规的匿名、隐藏和选择性暴露，欺骗与sting明确禁止。 | `FORM-EXE01-CH18-001`—`030` |
| 19 Liquidity | `8781-9130` | `L2/medium` | 流动性是在给定时间与成本下成交给定规模的条件能力，至少包含 immediacy、width、depth 与 resiliency；它来自买卖双方的动态搜索，随交易者身份、信息、规模、方向、时点、订单暴露和跨市场连接变化。 | `liquidity_capacity_contract`：按 size×cost×time 报告可成交概率、book/quote、fill 与 impact，并区分 displayed/latent liquidity、主动/被动搜索及成交后恢复；volume 或窄 spread 不能单独证明容量。 | `FORM-EXE01-CH19-001`—`023` |
| 20 Volatility | `9133-9318` | `L2/medium` | total volatility混合unexpected fundamental repricing与uninformed liquidity demand造成的transitory movement；前者可无成交跳价且不应系统反转，后者与spread/impact和流动性紧密相关并倾向多时间尺度反转。负序列相关只是候选证据，交割日变化、storage/perishability和结构模型假设会造成误判。 | `volatility_component_contract`：固定return/price、clock、horizon、session、delivery、quote/trade/order-flow 与 event set，分报total、fundamental-hypothesis、transitory-hypothesis及uncertainty；vol forecast、liquidity、impact与outage risk不得混称。 | `FORM-EXE01-CH20-001`—`020` |
| 21 Liquidity and Transaction Cost Measurement | `9333-9764` | `L2/medium` | 总交易成本包含 explicit、implicit 与 missed-opportunity cost；所有估计都依赖 side、parent order、价格基准和反事实。effective/realized spread、implementation shortfall、VWAP、开收盘与计量模型回答不同问题，并受拆单、策略方向、信息、timing discretion、gaming、样本和非平稳流动性影响。 | `transaction_cost_evidence_contract`：在 parent-order/decision 基准下统一 fills、未成交、fee、delay、impact 与机会成本，同时保留 time-of-trade 与 post-trade benchmark 作诊断；基准、时钟、方向、数量和缺失数据必须可重放。 | `FORM-EXE01-CH21-001`—`039` |
| 22 Performance Evaluation and Prediction | `9767-10544` | `L2/medium` | 绩效必须从现金流完整的组合收益出发，以预注册 benchmark/risk exposure 分离市场、因子、择时、选择与执行贡献；past winner 仍可能来自 luck、fat-tail/peso risk、造假、平滑、多重比较、survivorship 或选择过程。预测未来表现还要求原技能机制持续、资源仍在且具有相对对手的 comparative advantage。 | `performance_evidence_contract`：保存完整 trial/universe、失败和终止记录、现金/证券流、估值、benchmark/risk model、成本、暴露、tail、样本长度、multiplicity 与 OOS；禁止用筛选后的冠军或单一 t 值自证 skill。 | `FORM-EXE01-CH22-001`—`035` |
| 23 Index and Portfolio Markets | `10563-10764` | `L2/medium` | index是带components、weighting、divisor、corporate-action与return convention的版本化规则，index fund用可交易portfolio近似其total return并承担tracking error；ETF、futures、options与basket/package市场只是承载index risk的不同产品，价格发现、现金流和执行语义不能互换。 | `index_portfolio_and_product_evidence_contract`：保存PIT成分/权重/divisor、price或total-return口径、rebalance公告/生效时钟、fund holdings/cash/fees、creation-redemption/NAV、futures roll/settlement和实际fills；禁止未来成分、事后close与历史产品规则进入信号。 | `FORM-EXE01-CH23-001`—`024` |
| 24 Specialists | `10767-11176` | `L2/medium` | designated specialist以持续双边报价、last-resort liquidity和auction/order-book管理义务换取order-flow信息、选择时机、quote参与和佣金等特权；affirmative/negative obligations试图约束其agency/principal冲突，但服务与成本由不同交易者承担。 | `designated_liquidity_provider_governance_contract`：仅抽取current-rule下的义务、优先权、角色隔离、信息访问、资本、审计、服务指标与补偿对价；历史NYSE specialist、stopped stock、cream skimming和quote控制不映射当前电子venue。 | `FORM-EXE01-CH24-001`—`030` |
| 25 Internalization, Preferencing, Crossing | `11179-11398` | `L2/medium` | internalization、payment/rebate-driven preferencing和internal crossing可降低部分客户显性佣金或提供定制服务，却减少公开order exposure、削弱aggressive quote的获单回报并把marketable flow与public limit liquidity分割；best execution必须联合价格、速度、成交概率、规模与未成交反事实评价。 | `best_execution_and_routing_conflict_contract`：保存parent/order type、decision与route时钟、NBBO/book/hidden限制、venue、internalization/PFOF/rebate/fees、fills/nonfills、price improvement、markout、client/broker利益和同类替代路径；current规则与capability未知即fail-closed。 | `FORM-EXE01-CH25-001`—`026` |
| 26 Competition Within/Among Markets | `11401-11860` | `L2/medium` | consolidation借order-flow/network externality降低交易者搜索成本，fragmentation借异质market centers满足规模、信息、耐心、接入和信用差异；碎片化只有在跨segment信息低成本可见、订单可路由且套利可执行时才近似统一市场，同时会产生跨venue priority、公共监管和流动性供给外部性。 | `market_fragmentation_and_linkage_evidence_contract`：统一instrument/contract、clock、currency、fees、settlement与quote/book语义，保存venue capability/health、route/ack/cancel/fill、cross-market priority、duplicate防护、arbitrage legs、broker conflict和公共服务；显示best price不等于可达best execution。 | `FORM-EXE01-CH26-001`—`034` |
| 27 Floor vs Automated Systems | `11863-12112` | `L2/medium` | floor与automated auction可共享同一matching原则，差异主要在规则执行、接入、容量、协商、信息交换、数据报告和成本技术；自动化提高一致性、可扩展性和auditability，却把错误集中到代码、网络、认证、容量和恢复链，并可能放大latency/access不公平。 | `automated_trading_system_sre_contract`：保存rule/code version、deterministic audit、身份权限、data/order clocks、容量/headroom、冗余、failover、RTO/RPO、unknown-order reconciliation、security、kill/degraded/manual路径和replay；不把自动化或stop order当故障保险。 | `FORM-EXE01-CH27-001`—`026` |
| 28 Bubbles, Crashes, Circuit Breakers | `12115-12710` | `L2/medium` | 极端波动通常混合基本面重估、先前错价修正、拥挤/杠杆/止损反馈、流动性撤退、跨市场断连与系统容量故障；halt、price limit、margin/tax 与 collar 可能保护也可能阻断 price discovery 和 liquidity supply，其净效应依赖冲击来源、参与者和跨 venue 协调。 | `crisis_market_state_contract`：以 current venue rule/capability、market state、order backlog、quote/book freshness、cross-market basis、margin/default、halt/reopen auction 与 replay 证据驱动 fail-closed；历史崩盘叙事和熔断阈值不作预测信号。 | `FORM-EXE01-CH28-001`—`030` |
| 29 Insider Trading | `12713-13078` | `L2/medium` | 内幕交易讨论把重大非公开信息、非法获取/泄露、合法公开信息研究、异常交易侦测与公平、流动性、价格效率和公司治理权衡分开；市场轨迹、关系网络或盈利本身不能证明信息来源和违法。 | `material_nonpublic_information_governance_contract`：只允许合法授权、PIT、可追溯且已公开可用的信息进入研究；保存source/access/disclosure clock与entitlement，疑似MNPI、选择性披露、misappropriation或权限不明即隔离并升级合规审查。 | `FORM-EXE01-CH29-001`—`030`；法律定义、监管要求与处罚必须按当前法域权威来源复核 |

## 已完成 L2：第 1 章

### 第 1 章：市场微观结构范围与端到端证据边界

- **论证链**：交易是买卖双方寻找对手、数量、价格和时机的双边搜索。broker组织搜索，dealer承接客户的交易问题并管理库存，patient liquidity supplier出售等待时间和可被选择成交的option，informed trader通过估值/信息优势推动price discovery，同时向less-informed flow转移成本。exchange的规则、通信和信息展示决定可做什么、可知什么及谁拥有优先权；competition、network/order-flow externality、fungibility和arbitrage连接又决定流动性集中和跨市场一致性。
- **成立条件**：任何研究命题必须声明instrument/venue、trader objective、other side、information set、order/market structure、broker/dealer role、search/exposure、liquidity、all-in cost、volatility、credit/settlement和legal scope。利润用relative benchmark和完整fills/positions/cash ledger解释；market-quality结论至少同时检查liquidity、cost、price informativeness、volatility和participant outcomes，不能用一个维度替代全部。
- **局限与反例**：本书研究trading organization而非证券估值、适当性、发行或组合目标；“trading zero-sum”是相对市场/交易对手的会计框架，不否认投资持有的经济收益，也不表示每笔成交一方必然错误。限价意愿是option类比而非标准期权，market concentration可来自network externality也可隐藏单点风险；free entry会压缩利润但现实存在资本、数据、监管和技术壁垒。书中角色、venue、制度和法律均有时代依赖。
- **项目动作**：建立 `MarketMicrostructureContext`：保存domain owner、instrument/venue/session、participant role、objective/urgency、information timestamp、order/market model、counterparty/other-side hypothesis、liquidity/cost/volatility metrics、broker/venue capability、credit/settlement state、rule/legal version和evidence links。研究结论沿 Strategy→Portfolio/Risk→OMS→Fill/Ledger 单向传递；任何跨域shortcut或缺少other-side/cost解释的alpha候选降级为concept_only。
- **禁止直接采用**：不得把书中“赢家/输家”、dealer、broker、arbitrage、market quality或regulatory判断直接映射当前主体；不得从零和叙事生成short signal，从information asymmetry推断具体知情者，从电子化推断公平/可靠，或迁移旧交易所、法律和税务描述。本章不授权交易、回测、holdout、参数、promotion或任何private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH01-001`—`018`。

## 已完成 L2：第 2 章

### 第 2 章：跨资产交易生命周期与案例证据降级

- **论证链**：不同资产的表面流程不同，但共同链条是先确定账户权限、instrument/contract、side、size、urgency与限制，再选择公开book、dealer、broker search、crossing或协商路径，随后经历partial fills、价格变化、trade report、client confirmation、allocation、clearing、cash/security transfer和reconciliation。大单执行尤其依赖信息暴露与latent liquidity：完全隐藏找不到对手，过度暴露又招致quote retreat和anticipation；hedge/option/FX还加入basis、多腿、contract multiplier、quote size、funding和settlement currency。
- **成立条件**：每个场景必须保存parent decision及原因/horizon、account/permission、instrument identifier、venue/counterparty、quote/book timestamp和firm size、route rationale/conflict、order type/TIF/discretion、child sequence、fill/average price、market-relative benchmark、fee/markup、allocation、clearing entity、settlement date/state、cash/security/margin entries与break resolution。case replay只能使用当时可见状态，不能以最终价格判断当时route好坏。
- **局限与反例**：章节是2001年前后美国floor/dealer制度叙事，SuperDot/SuperSoes/POSIT、specialist、open outcry、电话报价、纸证书、T+3、税率、交易费和报价习惯均可能失效。案例中的dealer意愿、stale indication、floor color、cross price与成交数量不可当统计规律；market-not-held把timing交给人类broker，不能无声映射自动OMS。cash/futures hedge只覆盖指定价格风险，仍有basis、quantity rounding、delivery和margin risk；option hedge不保证税务或完全对冲。
- **项目动作**：建立 `TradeLifecycleScenario` fixture集，至少覆盖retail limit未立即成交、route conflict、short locate、institutional split/latent search、illiquid block concession、cash-futures basis hedge、multi-leg option、OTC bond DVP与FX principal markup。每个fixture都验证OrderIntent≠Order≠Fill、parent-child聚合、unknown/stale quote、partial fill、duplicate/reconcile、allocation、settlement fail和ledger-derived PnL；当前任务只写知识契约，不运行回测或真实接口。
- **禁止直接采用**：不得把历史best quote、displayed size、broker/dealer名称、佣金、settlement周期、margin、option tax、bond spread或FX markup当当前事实；不得因成交后价格不利认定执行差，也不得因限价成交认定策略正确。不得复用故事中的order route、market-not-held权限或cash/futures数量公式到生产，除非当前contract/capability与独立fixture证据齐备。
- **L3 待复核**：`FORM-EXE01-CH02-001`—`025`。

## 已完成 L2：第 3 章

### 第 3 章：交易行业拓扑、合约语义与监管版本边界

- **论证链**：交易不是单一策略到订单的跳转，而是beneficiary/sponsor/manager/buy-side trader把目标交给broker/dealer或venue，随后由clearing、settlement、depository/custodian和regulatory体系完成确认、担保、资产交付与约束。principal与agent、dealer与broker、exchange forum与order matcher具有不同利益和责任；同一资产又因primary/secondary、listed/OTC、standardized/bespoke、physical/cash settlement及CCP安排而形成不同生命周期。reported volume还会因dealer intermediation、重复报告和监管口径产生双计或三计。
- **成立条件**：每个交易链必须能回答谁拥有资产/现金、谁设定目标、谁有decision/execution authority、谁以principal或agent成交、venue如何准入/撮合、instrument contract如何定义multiplier/notional/expiry/settlement、谁清算担保、谁托管交付、margin与position limit由谁执行、break/default由谁承担，以及适用rule/regulator/version。所有market-size、liquidity与volume比较必须保存source、scope、counting method、instrument universe和timestamp。
- **局限与反例**：章节大量事实停留在2000—2001年的美国市场，包括ECN/交易所名称、T+3、floor/specialist、第三/第四市场、listing threshold、监管分工、机构名称与成交量；它们只证明角色和制度会变化，不是当前规则。STP减少人工差错但不消除duplicate、break、settlement fail和reconciliation；CCP降低双边信用搜索却集中default与member风险；短结算周期降低敞口但提高prefunding和运营要求。instrument标签也有任意性，hybrid contract应按实际payoff、权利义务和settlement解释。
- **项目动作**：建立 `TradingIndustryTopologyEvidence`：记录legal/operational entity、beneficiary/sponsor/manager/trader、principal/agent、broker/dealer、venue/access、clearing member/CCP、settlement agent/depository/custodian、instrument contract/version、account/permission、asset/cash ownership、margin/default state、rule authority/version、volume lineage和evidence links。Strategy仍只产出Signal/Forecast/TargetPosition/OrderIntent；Portfolio/Risk审批，OMS/Execution路由，Fill/Ledger与custody/reconciliation证明资产现金变化。角色重叠、授权不明、break、margin不足或规则过期一律fail-closed。
- **禁止直接采用**：不得把书中T+3、SEC/CFTC/SRO辖权、交易所/清算所/经纪商名称、listing标准、volume、margin、front-month习惯或OTC结构写成当前事实；不得把zero net supply理解为无风险/无财富影响，把STP理解为无需对账，把CCP保证理解为无信用风险，把dealer volume当public demand，或仅凭instrument名称推断法律属性。不得据监管评论形成交易信号或法律结论；本章不授权回测、holdout、参数、promotion或private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH03-001`—`030`。

## 已完成 L2：第 4 章

### 第 4 章：订单意图、成交不确定与 capability 边界

- **论证链**：订单只是向 broker/exchange 表达 instrument、side、quantity 与条件的指令，不是成交事实。market order 购买 immediacy，支付 spread、impact 并承担 submission 到 execution 的价格不确定；standing limit order 提供可被他人选择执行的流动性期权，换取潜在更好价格，却承担不成交、追价和 adverse selection。stop 只定义激活条件，触发后仍可能在跳空中远离 stop price 成交。
- **成立条件**：每个 `OrderIntent` 必须固定 instrument/venue、side、quantity、order type、limit/stop/touch、TIF、partial-fill、display、routing、settlement 与 multi-leg 条件；adapter 只接受 capability snapshot 明确支持且语义一致的组合。生命周期至少记录 create/submit/ack/activate/partial-fill/fill/cancel/reject/expire、exchange timestamps、remaining quantity、price/fee 和 reason code，stale GTC/open order 必须可盘点与撤销。
- **局限与反例**：书中的 floor、人工 broker、tick-sensitive、T+3、旧交易所和 specific order names 具有时代与 venue 依赖；IOC 与 FOK 在不同 venue 也不能假定同义。limit 触价不代表排队成交，hidden/reserve 令 displayed depth 低估真实数量；market-not-held 把执行判断和问责交给 broker，spread/substitution/special settlement 又引入多腿、代理、公司行动与结算风险。没有 queue、ack、partial fill、cancel 与 settlement 证据时，回测成交模型不得声称真实可执行。
- **项目动作**：建立 `OrderSemanticsEvidence`：保存 intent schema/version、capability snapshot/hash、pre-trade validation、state transitions、venue order id、parent/child relation、price protection、TIF、display、remaining quantity、cancel race、reject/expire、settlement 和 reconciliation。Strategy 仍只输出 Forecast/Target/OrderIntent；Portfolio/Risk 审批后 OMS 才可实例化 Order，只有 Fill/Ledger 生成仓位、现金和 PnL。
- **禁止直接采用**：不得把 stop 当 guaranteed stop-loss，把 limit touch 当 fill，把 market order 当确定价格，把 hidden depth 当可见深度，把 day/GTC/IOC/FOK/MOO/MOC/AON/MAQ、tick-sensitive、market-not-held、spread、iceberg 或 special settlement 名称直接写成跨 venue 统一语义；不得迁移书中价格、tick、T+3、人工代理责任或成交示例。private/order/paper/live capability 在未授权和无当前证据时保持 false。
- **L3 待复核**：`FORM-EXE01-CH04-001`—`022`。

## 已完成 L2：第 5 章

### 第 5 章：市场结构 capability、信息时钟与订单簿暴露

- **论证链**：market structure同时规定谁能在何时何地交易什么、如何撮合、能看到哪些order/quote/trade及何时看到。continuous与call解决immediacy和liquidity concentration的不同目标；quote-driven由dealer选择客户并承接库存，order-driven按precedence/pricing rule让public/dealer竞争流动性，brokered market通过搜索发现concealed/latent interest，现实多为hybrid。routing、presentation、market data与order book不是外围设施，而是决定可行动集合、信息优势、差错和成交证据的市场组成。
- **成立条件**：策略或执行假设必须绑定venue、rule/capability version、session state、continuous/call/auction phase、execution model、access/credit、tick、order types、precedence/pricing、routing/ack/cancel/reject/report、identifier mapping、data source/entitlement/latency、pre/post-trade transparency、depth/display、book ownership和settlement control。跨市场迁移只有在这些字段逐项等价或显式适配后才成立；实时、延迟、广播、查询和参与者专属数据必须分层。
- **局限与反例**：章节中的floor、open outcry、ECN、SIP、Level I/II/III、ticker规则、固定交易时段、数据费和毫秒/秒延迟均属历史事实。电子化通常更快且可审计，但只处理已编码的标准指令，也会产生schema mismatch、cancel race、outage和错误放大；透明度帮助弱信息方评估成本，却会暴露大单并改变standing liquidity。open book不等于完整可成交深度，closed/hidden book也不等于无流动性；IOI通常不firm。
- **项目动作**：建立 `MarketStructureCapabilityEvidence`：保存canonical instrument ID与vendor symbols、venue/session/auction clock、execution model、tick/lot、participant/access/credit、supported order semantics、precedence/pricing、route topology和state transitions、feed source/sequence/event/receive timestamp、entitlement/delay、top/depth/trade visibility、display/hidden/IOI firmness、book snapshot/hash和rule effective date。Strategy输出不依赖未声明数据；OMS仅发送adapter明确支持的指令；未知session、stale feed、identifier ambiguity、ack/cancel不确定或规则漂移均停止路由并进入reconcile。
- **禁止直接采用**：不得把书中市场分类当静态venue事实，把continuous理解为持续有成交，把call price当可随时成交价，把dealer quote当public order，把top-of-book当完整book，把member data当public data，把delayed/query feed当real-time，或因电子routing存在就声称低延迟/准确。不得从price clustering直接生成alpha，不得把旧ticker、交易时段、数据费、延迟、市场名称、透明度或监管要求写入配置；本章不授权回测、holdout、参数、promotion或private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH05-001`—`030`。

## 已完成 L2：第 6 章

### 第 6 章：优先级、撮合规则与参考价失真

- **论证链**：order-driven venue 先按 price 及 time/display/size 等 secondary precedence 排名，再匹配最高优先级买卖订单，最后按 uniform、discriminatory 或 derivative pricing 生成交易价。continuous market 由新到订单依次吃掉 resting liquidity，call auction 集中订单后以 clearing price 分配，crossing network 则借用外部参考价；三者的 fill probability、price impact、allocation 与 adverse selection 不同。
- **成立条件**：回放或模拟必须冻结 venue/session/rule version、tick、price band、order type/TIF、price-time-display-size precedence、pro-rata/其他 allocation、queue state、incoming/resting side、partial-fill/remainder、auction call/imbalance/clearing/tie-break 与 reference-price timestamp。每个 Fill 必须能从前序 book/order events 和规则确定性重建，无法观察 queue/hidden/cancel race 时必须显式给出模型区间或 blocked。
- **局限与反例**：书中的 oral auction、public-order precedence、POSIT、AZX、旧 tick 和佣金均具时代性。single-price 最大化 volume/surplus 依赖给定 order flow、理性 limit 与不可观测 valuation；真实参与者会因规则改变订单，不能把静态例子外推为 venue 优劣。continuous uniform pricing 可被拆单规避；crossing 的低冲击来自不发现价格与低 fill rate，stale/可操纵 reference price 会让知情者选择性交易。
- **项目动作**：建立 `MatchingRuleEvidence`：记录 capability/rule hash、book sequence、precedence key、allocation method、auction state、reference source/freshness、match inputs、fill/remainder、reject/cancel 和 deterministic replay checksum。BTC 与美股 adapter 分别实现当前 venue contract，不共享未经证明的 queue、auction 或 crossing 语义；backtest 只有在对应数据层级存在时才启用相应 fill model。
- **禁止直接采用**：不得把 price touch、bar high/low、成交量或 L1 quote 当 queue fill；不得假定所有 venue 都 price-time、market order 总优先、resting price 成交、IOC/FOK 同义、opening/closing auction 同规则、crossing midpoint 无冲击或 halt 后统一 call。不得迁移书中 tick、pro-rata 示例、surplus 数值、低于 10% crossing fill、佣金或历史制度。private/order/paper/live surface 继续保持 false。
- **L3 待复核**：`FORM-EXE01-CH06-001`—`021`。

## 已完成 L2：第 7 章

### 第 7 章：Broker 能力、代理冲突与资产保护

- **论证链**：broker 不只是下单通道，而是以客户代理身份提供对手方搜索、venue/dealer access、清算结算、信用保证、订单暴露管理与账户服务；front office、back office、proprietary/risk/compliance 的组合决定真实能力。其收入可能来自 commission、PFOF、cash/margin spread、short proceeds、securities lending 与自营，因此低佣金甚至零佣金不代表低总成本，也可能加剧 routing、internalization 和 client-vs-house 冲突。
- **成立条件**：broker 评估必须覆盖 legal entity、execution/clearing/custody 分工、client-asset segregation、cash/securities ownership、pre-trade credit、margin/liquidation、borrow/locate、corporate action、settlement/reconciliation、data/order protocol、best-execution policy、PFOF/internalization、outage/default/insolvency 与 complaint/incident 流程。Order 从 submit 到 disposition 的审计轨迹必须不可篡改，并保存当时 market state、route、ack/fill/cancel/reject、allocation 和独立 statement 对账。
- **局限与反例**：书中 SEC/NASD/SIPC、T+3、LIBOR、margin、commission、保险额度、street-name 与 suitability 细节均是旧美国制度，不能当当前法务意见；broker 声誉、规模或监管身份也不保证资产安全。best execution 不是单一最低价，必须结合 size、speed、fill probability、impact、service 与可审计基准；大客户可自行谈判的历史假设不豁免项目审计。synthetic short、soft dollar、PFOF 和 securities lending 都需当前合同与账本，不能凭机制推断收益。
- **项目动作**：建立 `BrokerCapabilityEvidence`：记录 entity/account/permission、execution-clearing-custody topology、API/data/order capabilities、credit/position limits、cash/margin/borrow terms、route/conflict disclosure、best-execution metrics、asset segregation、statement/reconciliation、RTO/RPO、incident/default/transfer-out 和 review owner。composition root 默认只装配 public/read-only 能力；任何 private/order/paper/live adapter 必须经明确授权和独立 gate，Strategy 不得直接持有 broker client。
- **禁止直接采用**：不得用 commission 排名替代 total-cost/capability 审查，不得迁移 PFOF 比例、margin rate、rebate、borrow fee、SIPC 额度、T+3、旧 FIX/OFE 或美国监管义务；不得以 broker 自报 fill、内部 statement 或 reputation 作为唯一真值。未经独立 custody/statement/reconciliation 证据，不得声称资产隔离、settled、best execution 或 broker-safe；所有真实写入与订单权限继续保持 false。
- **L3 待复核**：`FORM-EXE01-CH07-001`—`028`。

## 已完成 L2：第 8 章

### 第 8 章：交易目的、对冲残余风险与越权防线

- **论证链**：交易只是解决外部问题的工具。investor/borrower移动跨期现金流，asset exchanger取得当下更有用的资产，hedger转移已有风险，speculator以可证信息优势承担方向风险，dealer出售流动性；学习、娱乐、cross-subsidy和税务也会产生flow。一个主体可同时有多种动机，因此volume、side、turnover或盈利结果不能唯一识别目的。hedge要求先存在underlying exposure，再选择相关或反相关vehicle；forward、futures、option和swap分别引入搜索/信用、标准化/CCP、premium/非线性和cash-flow basis风险。
- **成立条件**：每个`TradeObjectiveEvidence`必须记录mandate、beneficial owner、objective category、problem horizon、underlying exposure/cash-flow、expected utility或edge source、other-side/alternative motives、instrument/vehicle、hedge ratio与单位、basis/correlation、expiry/settlement、cost、residual risks、authority和falsifier。投资的unconditional risk premium、投机的conditional edge、dealer的liquidity revenue必须分开归因；对冲效果从合并后的positions/cash flows/stress loss验证，而非从hedge leg单独盈亏判断。
- **局限与反例**：章节对fundamental value、informed/uninformed、gambler/futile的分类是解释框架，不是可观测标签，也不能据此评价具体个人。zero-sum只描述相对交易损益，不包含投资产生的经济现金流和全部成本。书中wheat、S&P合约乘数、LIBOR、tax-straddle、soft dollar和历史法律均不可迁移；beta、basis、correlation和duration会漂移，futures hedge会放弃有利方向，option hedge付premium且存在strike/expiry，swap仍有index/prepayment/default mismatch。paper success、短期盈利或高胜率不证明skill。
- **项目动作**：建立 `TradeObjectiveAndHedgeEvidence`：为每个parent intent保存objective/mandate、edge/utility、underlying exposure、hedge vehicle、quantity formula/version、market/basis/beta/duration inputs及PIT timestamp、expected residual exposure、cost/credit/liquidity/settlement风险、actual fills、combined ledger PnL和post-trade residual。另建agent-control字段：decision/execution/settlement owner分离、position/margin limit、exception approval、independent reconciliation和immutable audit；无法清楚说明“为何交易”、使用stale information、突破授权或隐藏亏损时立即fail-closed。
- **禁止直接采用**：不得由volume/turnover推断投资、对冲、投机或赌博动机；不得把historical return、paper portfolio、单次盈利、active manager或dealer身份当skill证据；不得把相关当完全对冲，把futures当保留upside，把put当免费保险，把CCP当无风险，或把old news当edge。不得实现书中beta数量、put-call parity、tax、LIBOR、contract multiplier、存续率或5%经验数字；不得据人格分类生成信号或放宽position limit。本章不授权回测、holdout、参数、promotion或private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH08-001`—`030`。

## 已完成 L2：第 9 章

### 第 9 章：市场质量多目标、正向证据与规范判断分离

- **论证链**：market structure的任何变化都会重新分配liquidity、transaction cost、volatility、price informativeness、access和trader profit，因此“好市场”必须先定义受益对象与目标。positive analysis回答在明确假设和数据下各方案会产生什么后果；normative analysis再声明备选方案、评价标准及权重/可接受trade-off，选择社会福利最高的方案。市场的private benefit来自参与者低成本完成投资、融资、交换和对冲，public benefit来自informative prices支持资本/管理资源配置，以及liquid markets促进交换、专业化、risk sharing和较低capital cost。
- **成立条件**：任何market-quality或venue比较都必须保存decision question、完整alternatives、stakeholder/other-side、criteria与权重、metric definition、baseline、instrument/universe、data/rule version、event/receive clock、cost、uncertainty、distributional effect和falsifier。liquidity、cost、informativeness、volatility、access、reliability、capacity与fairness分项报告；primary-market capital allocation、secondary-market price discovery和execution quality不可混为一个结论。规范建议必须能追溯到已声明价值判断，不能伪装成统计事实。
- **局限与反例**：fundamental value是不可直接观测的反事实，price informativeness只能用代理和可证机制评估；高price、manager compensation或takeover并不单独证明管理质量，行业/市场/利率等共同因子会混淆。高liquidity可能帮助信息生产，也可能放大暴露、投机或外部性；更强信息效率可能与流动性、公平或隐私冲突。章节关于国家制度、污染许可、赌博、高速交易、SEC规则和公共政策优先级含作者价值判断与历史背景，不是当前法域事实或项目promotion标准。
- **项目动作**：建立 `MarketQualityDecisionEvidence`：记录alternatives、stakeholder map、positive hypotheses、criteria/weights、metric suite、data/capability/rule hash、measurement window、confidence interval、trade-offs和decision owner。venue readiness至少分报availability/outage、feed completeness/freshness、spread/depth/fill/impact、price discovery proxy、latency/reject/reconcile、access/counterparty与rule stability；任何维度缺失只可标unknown/blocked，禁止由综合分数掩盖。Agent手册中将“描述事实”和“价值选择”分栏，所有政策/结构迁移需当前权威规则复核。
- **禁止直接采用**：不得把高volume、低spread、快routing、透明、集中订单簿、dealer竞争、public-order precedence或informative price单独等同good market；不得把作者的社会福利排序、监管观点、国家比较、Rule FD/Order Handling/Manning规则、高速交易或赌博评价转成策略信号、法律结论或venue gate。不得硬编码primary issuance示例、required-return、manager option、污染许可或capital-cost关系。本章不授权回测、holdout、参数、promotion或private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH09-001`—`030`。

## 已完成 L2：第 10 章

### 第 10 章：信息是否进价、竞争与流动性代价

- **论证链**：market price 是可成交价格，fundamental value 是基于当前可得信息的条件期望而非未来真值；两者差异不可直接观察。value、news、information-oriented technical 与 relative-value/arbitrage 只是不同信息组织方式，只有判断准确、尚未被价格反映、能在竞争者之前或以足够低 impact 建仓并覆盖研究/交易成本时才可能盈利。知情交易推动价格向其估值移动，也让被选择成交的流动性提供者承担 adverse selection。
- **成立条件**：每个信息候选必须保存 source/access legality、release/vintage、consensus 与 price-implied baseline、information timestamp、decision horizon/expiry、expected magnitude/uncertainty、other side、competition/correlation、market impact、cost/capacity 与 falsifier。新闻信号需检验信息是否已经进价及过度/不足反应；技术模式需完整 trial 与新样本；relative-value 需说明 common 与 instrument-specific factors、legs、borrow/funding 和 broken-relation risk。
- **局限与反例**：fundamental value、noise、谁是 informed 均不可直接观察；“价格最终回归价值”缺时间与资金路径保证。forecast aggregation 的独立无偏误差、零净供给与线性需求是教学假设；past winner、税损、新闻案例和弱/半强/强式效率文献具有样本与时代依赖。unique/orthogonal 可能只是错得与众不同，低相关不等于高 precision；流动市场提高容量也加快 edge 被竞争消耗。
- **项目动作**：建立 `InformationEdgeEvidence`：保存 information set/version、public/MNPI classification、baseline/consensus、signal/forecast mapping、uncertainty、decay/expiry、competitor overlap、impact/cost/capacity、other-side mechanism、alternative hypotheses、OOS/trial ledger 与 kill condition。Strategy 只把合法且 PIT 的信息映射为 Forecast；Portfolio/Risk 处理 uncertainty、crowding、liquidity 和 tail，OMS/Fill/Ledger 证明是否在信息失效前实现净收益。
- **禁止直接采用**：不得把“知情”“价值”“新闻”“技术”“套利”“正交”或“有效市场”标签当 edge；不得迁移随机游走、独立无偏预测、`Q=2l(pi-0.3)`、最大利润、六个月/一年 momentum、历史事件反应、弱/半强/强式结论或任何新闻速度。不得使用 MNPI、私下关系、未授权数据、后验 fundamental value 或事后判断信息已进价；短期 order-flow toxicity 只能作执行风险候选，不得据本章直接下单。
- **L3 待复核**：`FORM-EXE01-CH10-001`—`023`。

## 已完成 L2：第 11 章

### 第 11 章：订单意图泄漏、可预测强制流与退出路径风险

- **论证链**：order anticipator从别人将要交易的信息获利，可分为已知既定订单的front runner、预测尚未决定flow的sentiment trader，以及制造稀缺迫使对手交易的squeezer。aggressive parent order暴露side/size后会吸引抢先拿走优价流动性；passive displayed order又向quote matcher提供类似可取消保护腿的option。predictable investment/hedging/asset-exchange flow可能短期推动价格，但会与value trader、basis变化和crowding竞争；borrow recall、deliverable scarcity、expiry和公开stop区域则可能把退出需求变成非线性强制流。
- **成立条件**：研究或执行判断必须保存parent objective、confidentiality class、authorized audience、broker/venue route、exposure events、display/hidden/split策略、queue/tick/time precedence、child timing、book/quote/trade sequence、cancel state、borrow/float/open interest/deliverable、expiry/notice、stop trigger、cross-market hedge、pre/post-order markout与完整替代解释。所谓front run、squeeze或manipulation必须区分公开推断、授权搜索、错误路由、普通information trade与违法泄密，法律结论只能来自当前权威规则和合格责任人。
- **局限与反例**：章节大量案例来自floor、旧tick和历史美国规则；“parasitic”、市场效率与社会福利评价含作者规范判断。quote matching只有在被跟随订单仍存在、可成交、价格改善成本较小且退出快于原订单时才有option-like收益，cancel、fill、gap和latency会使保护消失。seasonality、dynamic hedge、IPO flow、bubble与hard-to-value叙事都可能被市场预期、结构变化或value flow抵消；正确估值也可能因borrow recall或deliverable squeeze亏损。价格触发stop后的延续/反转不能证明有人操纵。
- **项目动作**：建立 `OrderExposureAndAnticipationEvidence`：为parent/child订单记录need-to-know权限、route recipients、IOI/RFQ/display、split/participation、information-leakage budget、queue/tick、book sequence、cancel race、markout与counterfactual execution；为强制流记录borrow availability/recall、float、open interest、deliverable inventory、expiry、margin和多条close-out route。surveillance只输出pattern/risk flag与evidence links，不输出违法定性；发现未授权访问、异常提前交易、退出路径单一、borrow/deliverable不足或stop cascade风险时缩减/阻断并升级人工复核。
- **禁止直接采用**：不得根据大单前价格变化、同向成交、窄tick、seasonality、open interest、short interest、stop附近波动或随后反转直接认定front running、squeeze、gunning或操纵；不得把quote matching的put/call类比当真实期权保证，不得复用January effect、历史IPO/期权动态对冲、案例阈值、五分钟窗口或法律结论。不得通过暴露客户订单、探测私有意图或制造强制交易生成alpha。本章不授权回测、holdout、参数、promotion或private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH11-001`—`030`。

## 已完成 L2：第 12 章

### 第 12 章：虚假信息、路径型价格冲击与反操纵证据边界

- **论证链**：bluff的核心不是简单“价格涨跌”，而是制造他人会误读的information set。rumormonger可伪造内容、冒充多主体或在易误解的时点传播真实内容；price manipulator可用aggressive trades、跨broker拆分、wash/协同成交、size与speed差异制造看似information-driven的price/volume。momentum trader和仅按net flow调价的liquidity supplier容易把路径当fundamental information；value trader可能以估值和资本对抗bluff，但也可能把真正informed flow误判成操纵。
- **成立条件**：任何反操纵分析必须保留原始消息/公告hash、publisher/domain/identity、publication/availability/ingest time、引用链、账户/设备/通信access、parent-child orders、broker/venue、counterparty linkage、fills、side/size/speed、pre/post quote/book、round-trip inventory、impact/markout、fundamental news、borrow/float和完整替代假设。异常检测只说明pattern与置信度；fraud、wash trade、intent和违法结论必须依当前法域证据标准、官方规则与人工调查，不能由模型自动裁决。
- **局限与反例**：章节主案例是虚构情景，PairGain等事实也属于1990年代制度；价格反转、拆单、多broker、发帖、先买后卖、高利润或失败都不是充分证据。价值估计同样不确定，bluffer可凭资本迫使value trader止损，illiquid、hard-to-value和hard-to-borrow只是易受影响条件而非操纵证明。书中“买卖冲击每单位必须完全对称”的线性结论依静态、可逆、无信息更新的简化模型；真实市场存在inventory、adverse selection、nonlinear depth、session和state dependence。
- **项目动作**：建立 `ManipulationRiskEvidence`：分层验证content authenticity、source provenance、identity/linkage、market-path anomaly和economic alternative。对impact按side×size×speed×state报告临时/永久分量、round-trip inventory与all-in cost；以matched benign flow、news/control windows和cross-venue evidence作对照。系统只产生`risk_flag/review_required/insufficient_evidence`，冻结可疑数据驱动信号并保留审计链；任何账户处置、举报或法律结论必须由授权流程执行。
- **禁止直接采用**：不得依据涨幅、成交量、momentum、消息板、匿名身份、多broker拆单、价格反转、small cap、难借券或买卖冲击不对称直接生成short/long alpha、认定操纵或识别个人；不得复现书中bluff、wash、假消息、拉抬打压或规避追踪方法。不得硬编码案例价格、利润、订单规模、SEC标准或线性impact参数。本章不授权回测、holdout、参数、promotion或private/order/paper/live操作。
- **L3 待复核**：`FORM-EXE01-CH12-001`—`030`。

## 已完成 L2：第 13 章

### 第 13 章：做市能力、库存账本与条件化报价证据

- **论证链**：dealer以principal身份在客户需要时买卖，出售的是immediacy而非稳定spread。买入后未知何时、向谁、以何价卖出，卖出后也未知回补成本；因此quoted bid/ask只有在双边flow、inventory和市场状态中才有意义。dealer以price/size skew把actual inventory拉回target，紧急时主动跨spread减仓；unexpected price move形成diversifiable inventory risk，informed trader选择有利一侧则形成adverse selection，使dealer买后跌、卖后涨并压缩realized spread。报价还须预先反映“下一位是buyer/seller”带来的条件信息差。
- **成立条件**：任何做市或流动性提供结论必须保存legal/principal role、instrument/venue/session、firmness、bid/ask/size/expiry、inside/own quote、inventory/target/imbalance、capital/margin/borrow/funding、client eligibility、parent/child orders、fills、fees/rebates、hedges、quote revisions、event/receive timestamps、realized spread和多horizon markout。dealer、speculator、broker和value-trader活动必须分账；inventory PnL只由fills、positions和cash ledger重建，不能用quoted spread×volume估算。
- **局限与反例**：章节依赖旧floor、Nasdaq、PFOF和人工client classification；“retail不知情、institutional知情、大单更知情”等启发式会产生歧视和误判，不能作为账户准入或报价规则。Madoff案例引用其自有网站且早于欺诈暴露，是来源可信度失败的典型反例，所有数字和经营描述均不得采信。diversification不消除共同跳跃、funding和liquidation；market value不等于fundamental value，order flow也可能来自hedge、bluff或forced trade。书中impact对称与平衡flow是简化机制。
- **项目动作**：建立 `DealerCapabilityAndInventoryEvidence`：以quote→order→fill→inventory→hedge→cash/PnL状态机记录firm two-sided obligation、size/expiry、target/limits、inventory age、quote skew reason、adverse-selection score、markout、capital/margin和reconciliation。做市readiness必须证明持续双边报价、真实可成交fills、尾部inventory stress、stale-quote/cancel/outage保护、independent ledger和kill switch；缺少private fill、真实双边义务或账户权限时只可研究模拟，所有dealer/paper/live安全旗标保持false。
- **禁止直接采用**：不得把limit order、maker fee、窄spread、高volume或偶发双边成交称为做市；不得以quoted spread推断利润，以客户身份/订单大小判定知情，以one-sided flow直接追价，或把快速turnover当低风险。不得迁移Madoff、旧Nasdaq、PFOF金额、Time Slicing、dealer名称、客户筛选、市场份额或FX历史volume。不得运行真实报价、private/order/paper/live接口。本章不授权回测、holdout、参数或promotion。
- **L3 待复核**：`FORM-EXE01-CH13-001`—`030`。

## 已完成 L2：第 14 章

### 第 14 章：即时性价格、价差组成与代理变量边界

- **论证链**：bid/ask spread 是 impatient trader 为即时成交支付、liquidity supplier 为等待和被选择成交获得的价格。竞争性 dealer/public limit order 会把价差压向提供流动性的全成本；该成本既含经营、订单管理、库存、时间与风险补偿，也含 standing limit order 授予更快交易者的 timing option。信息不对称使主动知情流选择性击中错误报价，形成不会系统反转的 adverse-selection/permanent component；其余正常成本与库存补偿主要形成会随买卖方向反转的 transaction-cost/transitory component。简单 Glosten-Milgrom 教学模型在特定假设下给出 `A-B=2PE`，只用于解释条件估值与盈亏平衡为何一致。
- **成立条件**：解释或比较价差必须固定 instrument/venue/session、tick/price scale、bid/ask/side、quote timestamp/age、displayed depth、订单规模、fee/rebate、cancel/replace latency、volatility horizon、trade direction、后续 markout horizon 与市场活动口径。跨资产只比较 relative spread（spread/price）仍不够，还需控制波动、信息事件、交易兴趣、规模、价格、行业和市场设计；以成交量、公司规模、分析师覆盖或披露制度代理不可观测机制时，必须登记代理假设、竞争解释和识别方法。
- **局限与反例**：零价差均衡依赖同质交易者、无信息差、无风险厌恶、无时间价值、即时免费撤单和相同佣金等教学条件；差异化佣金可机械改变 quoted spread 而不改变 all-in cost。equal ignorance 可能令估值波动低于真实价值波动，但现实中的 asymmetric information 会反向扩大价差。public limit traders 可因低经营成本压窄报价，也可能被 dealer 的订单流信息与速度优势选择；活跃度与窄价差相关同时受固定成本摊薄、库存周转、限价竞争和信息稀释影响，不能单凭相关性确定因果。书中的旧 GAAP、交易所、公司与商品案例只作机制假说。
- **项目动作**：建立 `SpreadMechanismEvidence`：保存 quote/book source 与 sequence、bid/ask/mid、spread absolute/relative、side-correct benchmark、order size/depth、fee/rebate、cancel latency、volatility/activity、event state、fill、post-fill markout、transitory/permanent decomposition method、proxy set、confounders、uncertainty 和 current-venue rule hash。研究报告将 quoted spread、all-in execution cost、passive fill economics、inventory/latency risk 与 adverse-selection markout 分列；缺少 trade direction、同步 quote 或未来 markout 时只报告可观察指标，不声称完成价差分解。
- **禁止直接采用**：不得把 quoted spread 当 effective/realized cost，把 maker rebate 或被动成交当净收益，把高成交量当流动性充分条件，把窄价差当低冲击/高深度/高韧性，把买卖后价格变化唯一归因于知情交易，或把 `2PE`、相对价差、历史代理关系写成当前生产定价、仓位或路由公式。不得据第 14 章自行运行策略、调参、生成 alpha/promotion 结论；private/order/paper/live capability 继续保持 false。
- **L3 待复核**：`FORM-EXE01-CH14-001`—`029`。

## 已完成 L2：第 15 章

### 第 15 章：大额订单容量、隐性流动性与披露权衡

- **论证链**：block是超过常规exchange/dealer liquidity、无法用普通流程轻易完成的相对概念，而非固定股数。大额parent order同时面对四个问题：愿意成交者可能尚未表达latent demand；扩大搜索会泄露side/size并引来front run或对手撤退；liquidity supplier担心initiator继续交易而要求更大concession；大额/匿名/紧急flow又常被怀疑含information。block dealer先用自有inventory承接再退出，block broker搜索并组装对手；两者都依赖对真实总量、动机、退出成本和交易后报告影响的判断。
- **成立条件**：任何large-order/capacity结论必须保存parent objective、total intended size、size/ADV与depth比例、time budget、venue/session、display/hidden/split、authorized audience、contact/exposure sequence、latent responses、concession benchmark、dealer/broker role、inventory/hedge/liquidation plan、child fills、trade-report timestamp、book precedence和all-in implementation shortfall。所谓“完整size”“uninformed motive”“trusted counterparty”只能作为有证据和置信度的声明，不能依身份或口头保证直接接受。
- **局限与反例**：章节依赖电话upstairs market、floor、旧13F、固定block threshold、90秒/90分钟/七天报告与历史exchange规则。匿名降低泄漏但削弱reputation机制；实名审计可能引入隐私、公平准入和利益冲突，也不能可靠识别information。sunshine disclosure可发现latent liquidity，也向市场免费授予anticipation option；delayed reporting帮助dealer退出，却损害其他参与者的信息对称。历史“80% seller initiated”、recommendation underperformance和机构分类均不可迁移。
- **项目动作**：建立 `LargeOrderCapacityAndExposureEvidence`：对每个parent保存capacity curve、normal vs stressed depth、expected fill time/cost、contact graph、need-to-know权限、IOI/RFQ firmness、leakage/markout、true-size uncertainty、dealer inventory age/limit、broker search结果、reporting/precedence rules和post-trade reconciliation。即使账户规模较小，也要用size×cost×time压力测试识别何时普通execution假设失效；但未具备真实block mandate、权限和审计时，不实现block desk、motive screening或off-market execution。
- **禁止直接采用**：不得用固定股数、单一ADV比例或成交额定义跨市场block；不得把large/anonymous buyer判为informed，把seller判为uninformed，或通过身份、13F、客户关系推断真实total size。不得迁移sunshine、delayed reporting、size precedence、EFP、场外协商、佣金、历史阈值或交易所名称；不得用broker recommendation分销库存。不得调用private/order/paper/live接口。本章不授权回测、holdout、参数或promotion。
- **L3 待复核**：`FORM-EXE01-CH15-001`—`030`。

## 已完成 L2：第 16 章

### 第 16 章：估值区间、终极流动性与赢家诅咒

- **论证链**：价值交易的收益不来自“低价”本身，而来自价格因非知情流动性需求偏离基本价值后再收敛。价值交易者可直接用限价/大宗承接需求，也可在dealer因单边flow和库存风险下调报价后接走库存；前者供应immediacy，后者虽从dealer取得即时成交，却向dealer供应size/depth，并提高市场resiliency。其可交易边界是outside spread：只有估计偏离足以覆盖研究、融资、库存、等待和执行成本，以及被更知情news trader逆向选择、或自身模型/信息错误造成winner's curse时才应交易。
- **成立条件**：任何value/convergence命题必须保存instrument/venue/session、PIT公开信息集、valuation model/version/inputs、point estimate与区间/uncertainty、market price/quote age、mispricing threshold、预期对手及其流动性动机假说、为何不是new information、entry size/price、capacity、financing/borrow、all-in cost、catalyst或收敛机制、horizon/expiry、markout、alternative explanations和falsifier。价值交易与新闻交易必须显式分类：前者要证明自己在向非知情需求供给流动性，后者要证明信息新增、何时可见及尚未进价；无法区分时保持unknown并缩减或拒绝风险。
- **局限与反例**：基本价值、对手是否知情及“价格回归价值”均不可直接观察；dealer改价也可能反映真实新闻而非库存，order-driven book耗尽也不证明flow非知情。winner's curse依赖common-value、估值分散和成交条件，双边单一价格拍卖可能由清算价缓和它，连续市场与有冲击的订单则仍会暴露估值极端者。更多竞争者、较大估值不确定性通常要求更保守报价，但市场力量、参与者愚蠢程度和私人价值会改变结论。章节中的oil lease、互联网股、dealer与拍卖例只说明机制，不是当前阈值或因果证据。
- **项目动作**：建立 `ValuationAndConvergenceEvidence`：把估值输出定义为带区间和expiry的Forecast，而非OrderIntent；附上data vintage、model risk、consensus/price-implied baseline、outside-spread threshold、liquidity-role hypothesis、counterparty/new-information风险、capital/financing/borrow/cost、expected convergence path和失效条件。Portfolio/Risk独立把估值不确定性、持有期、集中度、流动性与融资转成仓位上限；OMS只在授权后按capacity与price limit执行；Fill/Ledger用实际成交、现金、融资和markout重建结果，事后归因不得用“最终反转”自证原估值正确。
- **禁止直接采用**：不得因价格低于模型、偏离历史均值、dealer降价、单边flow、竞争者很多或成交后反转而自动买入；不得把未观察的交易者标记为uninformed/news trader，把outside spread当固定百分比，把研究成本或融资成本藏入alpha，或用更宽阈值掩盖失效模型。不得把价值交易称无风险、必然收敛或天然供给流动性，也不得据本章运行新回测、调参、查看holdout、生成promotion结论或调用private/order/paper/live接口；所有安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH16-001`—`024`。

## 已完成 L2：第 17 章

### 第 17 章：动态公平基差、多腿完整性与生存资本

- **论证链**：套利不是“看到两个价格不同就无风险获利”，而是把相关instrument组成一个hedge portfolio，定义reference leg、hedge ratios和basis，再以动态fair value与含交易/carry风险补偿的arbitrage bounds判断是否值得建立。pure arbitrage依赖运输、交割、现金结算或风险转换等可验证机制最终压住basis，但短期仍可能继续扩张并先耗尽资本；speculative arbitrage的basis含非平稳特定因素，只能押注短期均值回归先发生。套利者既以相对价值交易推动law of one price，也以跨市场“运输”流动性、重包装共同风险；价差是这项服务的预期补偿，不是已实现利润。
- **成立条件**：任何relative-value命题必须保存canonical instrument/contract、venue/session/clock、PIT prices与quote age、common和instrument-specific factors、hedge-portfolio numerator/legs、hedge-ratio model/version、basis definition、fair-value inputs/uncertainty、pure/speculative分类及其收敛机制、entry/exit bounds、expected horizon、transaction/impact/delay cost、funding/borrow/dividend/storage/delivery/corporate-action carry、margin/collateral、capacity、market-state、structural-break alternatives和falsifier。多腿执行必须有同一parent correlation ID、目标数量比、atomic capability或明确legging顺序、最大裸腿时长/损失、partial-fill补救、ack/cancel/reconcile与真实fills；任一腿状态unknown即fail-closed。
- **局限与反例**：相关、高历史协整或短期反转不证明未来收敛；fair value会随利率、股息、storage、volatility、税负、合同条款、特定事件和交易制度变化，所谓pure arbitrage也可能因融资、margin、delivery、buy-in或慢收敛在机制生效前被迫退出。pairs/stat-arb最容易把永久specific-factor变化误判为暂时错价；代表性basket存在tracking error，动态option hedge存在gamma/volatility与跳空风险，merger arbitrage还依赖deal failure、条款变更、审批和closing time。LTCM、ValueLine、旧期货/场内、公司并购和商品案例只作failure mode，历史数字、法规、税务与合约不能迁移。
- **项目动作**：建立 `RelativeValueAndMultilegExecutionEvidence`：Strategy只输出带模型区间、期限和break condition的relative-value Forecast；Portfolio/Risk依据basis volatility、model uncertainty、liquidity、borrow availability、margin stress、correlation break和time-to-convergence设置gross/net、单腿与组合限额，并保留staying-capital buffer，禁止max leverage。OMS仅在venue capability明确后选择simultaneous、illiquid-leg-first或interleaved执行，逐腿记录expected/actual price、impact、fill ratio和unhedged exposure；Fill/Ledger统一重建各腿、费用、融资、借券、股息、保证金、公司行动和交割，只有完整闭环才能计算net arbitrage PnL。
- **禁止直接采用**：不得把相关性、cointegration p值、历史均值、跨venue显示价差、现金期货basis、option parity、stub为负或并购折价自动称arbitrage；不得忽略时钟、currency、contract multiplier、settlement、borrow recall、tax/liability、tracking error或未成交腿，不得以gross spread、理论回归、后验收敛或“最终会对”掩盖中途破产。不得把crossed quote直接提交多腿订单、把dynamic hedge称无风险、把risk arbitrage称确定成交，或迁移书中参数/公司/venue规则。本章不授权新回测、调参、holdout查看、promotion判断或private/order/paper/live调用；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH17-001`—`036`。

## 已完成 L2：第 18 章

### 第 18 章：买方执行目标、暴露预算与代理审计

- **论证链**：buy-side可控的关键不是预测价格，而是把portfolio objective转成与urgency、value、spread、standing depth、fill probability和missed-trade consequence一致的order policy。market order用价格不确定换成交概率，limit order用不成交风险换价格控制；两者不能脱离方向和估值只按spread宽窄选择。大额parent还要决定主动搜索或等待、全量或隐藏、一次或拆分、单broker或多broker、单venue或多venue。暴露能降低搜索成本并唤起latent/reactive interest，却同时泄露交易动机、后续price impact与standing order提供的免费option，因此执行质量来自“暴露多少、向谁、何时、以何种firmness”而非简单的maker/taker标签。
- **成立条件**：任何buy-side execution结论必须保存parent objective/mandate、decision timestamp与value/limit、side/total quantity、urgency/deadline、must-trade或optional状态、spread/depth/volatility、queue与better-priced size、fill-probability model/version/interval、nonfill fallback和opportunity cost。暴露证据需保存child/broker/venue、displayed/hidden/indication、firmness/expiry、audience/identity scope、contact sequence、parent aggregation、routing conflict、cancel/replace、information leakage、pre/post exposure markout和实际fills；broker discretion必须有授权边界、decision log、best-execution benchmark及独立reconciliation。
- **局限与反例**：窄spread只表示未含方向性value时market order相对更便宜；异常aggressive limit可能使一侧take liquidity很有利、另一侧仍不利。fill probability依赖market state、queue、volatility、interest和撤单竞争，历史经验或vendor optimizer都可能漂移；匿名不保证无法由flow推断动机，拆单/多broker也可能丢失parent视图并制造自我竞争。小单个体暴露低不代表同侧聚合flow无影响；time precedence、tick、hidden order、FOK、dual-trading和delayed-reporting效果均依当前venue规则。书中交易系统、1990年代样本、机构案例与佣金不能迁移。
- **项目动作**：建立 `BuySideExecutionAndExposureEvidence`：Portfolio/Risk负责target position、urgency、deadline、max participation、price/size limits和exposure budget；OMS在capability内选择market、limit、hidden、FOK、split和venue/broker path，并强制全局parent correlation ID，避免多broker重复或越量。每次decision记录forecast fill/cost/leakage与fallback，随后用Ack/Fill/Cancel、quote/book、implementation shortfall、missed cost和markout校准；只允许最小必要、可审计、符合当前规则的匿名/选择性暴露。broker/venue利益冲突、front-running风险、异常indication与access均进入独立审计，不由Strategy直接控制路由。
- **禁止直接采用**：不得把market order自动称take liquidity、limit order自动称cheap execution、hidden或拆单自动称更优，也不得从身份、声誉、flow或大单推断informed motive。书中伪装反向兴趣、虚报完成量/总量、故意取消、泄露假消息、利用不守密broker和sting/诱捕等deceptive/offensive策略一律拒绝，不得实现为执行算法；是否违法必须按当前法域和授权流程另核。不得用delayed reporting、历史tick或旧venue规则规避透明度，不得运行新回测、调参、查看holdout、形成promotion结论或调用private/order/paper/live接口；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH18-001`—`030`。

## 已完成 L2：第 19 章

### 第 19 章：规模、时间、成本与市场恢复的联合能力

- **论证链**：流动性不是静态标签，而是双边搜索产生的条件能力：在愿意投入的搜索时间内，以给定成本成交给定规模的概率。immediacy 描述多快，width 描述给定规模的单位成本，depth 描述给定成本可成交多少；width 与 depth 是同一 size-cost 关系的对偶表达，resiliency 则描述无信息订单失衡后价格恢复的速度。小额即时流动性可由 market maker 或 aggressive precommitted limit 提供，大额 depth 依赖 block/value trader、资本、客户信息和价格让步；arbitrageur 连接不同市场的流动性，但仍承担多腿同步与基差风险。
- **成立条件**：任何 liquidity/capacity 结论必须固定 instrument/venue/session、方向、订单规模、目标成本、允许等待时间、order exposure、displayed/hidden/latent scope、market state、trade motive/information risk、book/quote freshness、fee、fill probability、impact 和恢复窗口。报告应形成 size×cost×time surface 或至少一组离散情景，并保存未成交与撤单；resiliency 需要可辨识的冲击/订单失衡、基准价格及恢复判据，不能只观察事后反转。
- **局限与反例**：market order 不总是 take liquidity，limit order 也不总是 displayed；响应他人 RFQ 的主动单仍可能供给流动性。宽度窄可能只覆盖很小规模，深度大可能代价高且搜索慢；成交量高可由高周转或冲击交易产生，visible book 也会遗漏隐藏与潜在意愿。capital requirement 只证明 dealer 有能力，不证明愿意在 adverse selection 下报价；所谓 value trader 让价格恢复依赖其估值正确、资本充足和愿意交易，不能以后验反转认定 fundamental value。书中的 NYSE specialist、floor broker、block desk 与 synthetic-stock 案例只作机制说明。
- **项目动作**：建立 `LiquidityCapacityEvidence`：保存 observation window、venue/session/rule hash、side、size grid、cost grid、time budget、L1/L2/book sequence、displayed/hidden scope、quote age、fills/cancels/misses、fee、impact、market-state/event、cross-venue legs、recovery benchmark/horizon、probability/interval 与缺失字段。研究、Portfolio/Risk 和 OMS 共用容量快照，但分别用于信号可经营性、仓位上限与执行策略；数据粒度只支持 L1 时明确禁止 queue/depth/resiliency 强结论。
- **禁止直接采用**：不得把 volume、turnover、窄 spread、单档 size、capital standard、成交成功或价格反转单独称为 liquid；不得把 displayed book 当总流动性，把历史 dealer/value/arbitrageur 角色写成当前参与者事实，把 order type 直接等同 maker/taker，或把大单示例的价格路径、恢复速度和交易方式迁移到 BTC/美股。不得据本章自行运行回测、调参、路由订单或生成 promotion 结论；private/order/paper/live capability 继续保持 false。
- **L3 待复核**：`FORM-EXE01-CH19-001`—`023`。

## 已完成 L2：第 20 章

### 第 20 章：基本面重估、暂时性冲击与多尺度反转

- **论证链**：volatility是价格意外变化的倾向，随时间和状态变化。unexpected fundamental information可在common knowledge时无成交跳价，也可由少数知情者order flow推动价格永久重估；uninformed impatient flow则通过bid/ask bounce、大单impact和累计失衡令价格暂时偏离，随后由dealer/value/arbitrage activity修复。二者均可伴随volume，只有transitory component与交易成本和流动性不足直接相关，因此“高波动=市场失灵”不成立。
- **成立条件**：所有波动指标必须声明 price/return定义、sampling clock、horizon、session、currency、corporate action、instrument/delivery date、event information set、trade/quote/order-flow source、staleness、market state及annualization。variance、standard deviation、mean absolute deviation不能混用；分解需要预注册random-walk/mean-reversion模型、trade-sign与serial-covariance horizon，并报告估计误差、残差、regime stability和alternative explanations。
- **局限与反例**：expected carry或zero-coupon pull-to-par是可预测回报，不属于unexpected fundamental volatility；高storage cost、inelastic demand、perishability、political uncertainty和leverage会改变基本面price sensitivity。不同日期的spot commodity不是同一交割物，负序列相关可能来自跨日基本面而非temporary impact。Roll模型假设constant spread、independent equal-probability trade signs、random-walk value且只允许一阶反转；慢速恢复、time-varying spread、order splitting和informative flow会导致偏误。
- **项目动作**：建立 `VolatilityComponentEvidence`：保存 observation/window、return convention、sampling/horizon、event/vintage、venue/session/state、instrument/delivery、trade/quote/order flow、total-vol metrics、serial covariance/ACF、spread/impact、candidate fundamental/transitory components、model/version/assumptions、CI与out-of-support。Portfolio/Risk将price risk、liquidity/impact risk、execution uncertainty和system outage分别建模；Strategy只能使用PIT volatility forecast，OMS不得把estimated reversion当成交保证。
- **禁止直接采用**：不得把volume伴随价格变化自动称fundamental information，把负自相关自动称bid/ask bounce，把无反转自动称永久信息，把高波动自动称机会或市场失灵，或把Roll估计、书中storage/P-E/leverage关系及历史商品数字作为当前阈值。不得据本章运行新回测、调参、观察holdout、下单或形成promotion结论；所有安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH20-001`—`020`。

## 已完成 L2：第 21 章

### 第 21 章：反事实基准、总成本分解与估计偏差

- **论证链**：交易成本不是佣金或 spread 的单项和，而是 explicit cost、已成交的 implicit cost 及未成交/延迟的 opportunity cost。对买入，side-correct cost 取成交价高于基准的部分；对卖出方向相反，再乘数量。time-of-trade midpoint 产生 liquidity premium/effective spread，post-trade midpoint 产生 realized spread，decision-time midpoint 支撑 implementation shortfall；后者把实际组合与 paper portfolio 比较，并将已成交数量的价格差与未成交数量的机会成本放在同一基准。VWAP、开盘、收盘和计量模型只是不同估计器，不能互换。
- **成立条件**：成本证据必须保存 parent intent/order、strategy decision timestamp 与 benchmark、desk submission、broker release、每笔 fill、side、quantity、currency/price scale、quote source/age、bid/ask/mid、fee/tax/rebate、unfilled remainder、cancel/expiry reason、evaluation horizon、current/reference price、market state、benchmark rule/version 和 attribution owner。拆单必须聚合回原 parent order；broker 比较需匹配 size、urgency、information horizon、venue、market condition 与权限。单笔估计只作观测，汇总必须报告样本量、分布、置信区间与分组。
- **局限与反例**：理想的 no-trade counterfactual 不可直接观察；距离成交越近的基准通常噪声较低，却看不见 timing skill 和累积 impact，越远的基准可纳入更多路径效应，却混入新闻与投资决策。effective spread 会低估拆单的累计 impact，VWAP 可被自身成交污染，开收盘会偏置 momentum/contrarian，post-trade benchmark 会把 informed alpha 混入执行，任何随执行时点移动的基准都可能被延迟或贴合 benchmark gaming。平均可降随机噪声，不能消除偏差；机会成本又依赖评估日和可现实成交规模。
- **项目动作**：建立 `TransactionCostEvidence`：以 decision benchmark 为主键计算 parent-order implementation shortfall，并分列 manager delay、desk/trader delay、broker execution/impact、explicit fee/tax/rebate、unfilled opportunity 与 residual；另计算 side-correct effective/realized spread、post-fill markout 和 size-conditioned liquidity 作为诊断。回测成本模型只从不含 holdout 的训练/校准窗口估计，按 venue、size、aggressiveness、spread/depth、volume、volatility 与 regime 版本化，保留 prediction interval、out-of-support 和 stale-model fail-closed 标志。
- **禁止直接采用**：不得把 negative effective spread 当策略利润，把 maker fill 当低成本，把 VWAP/close beat 当 best execution，把 effective-realized 差唯一解释为 informed loss，把未成交数量乘事后有利价格直接称真实机会成本，或把历史 consultant 数值、30-day horizon、Roll/Lee-Ready/Glosten-Harris 假设写成当前真值。不得只评价 fills、忽略 misses，或通过改变释放时点优化指标；本章不授权新回测、调参、holdout 查看、订单路由或 promotion 结论，private/order/paper/live capability 保持 false。
- **L3 待复核**：`FORM-EXE01-CH21-001`—`039`。

## 已完成 L2：第 22 章

### 第 22 章：技能与运气、完整试验总体及比较优势

- **论证链**：总绩效同时受管理决策、不可预测事件、不可控市场/因子和投资约束影响，因此 absolute return 不能识别 skill。有效归因先以包含收入、费用、融资、借券、保证金和公司行动的完整组合收益为基础，再与能表示“没有主动管理会怎样”的 benchmark 比较，并按 concurrent exposure 分解 market/factor、timing、selection 与 implementation。过去绩效只有在它确实反映技能、技能机制未来仍有效且关键人员/数据/资源仍存在时才可能预测未来；统计显著也必须通过足够长样本、功效、多重比较、尾部形状、数据真实性和选择过程审查。
- **成立条件**：绩效证据必须固定 evaluation objective、portfolio/account、cash/security flows、valuation source、currency、return convention、benchmark/universe、risk-factor model/version、concurrent exposures、fees/costs、trial registry、sample start/end、sampling frequency、missing periods、terminated/failed strategies、selection rule、number/effective number of trials、correlation、confidence/power、tail metrics 与 OOS period。manager/策略比较必须同风险、同容量、同市场状态和同成本；形成结论前必须能回答 other side、edge mechanism、resource persistence 与失效条件。
- **局限与反例**：IRR 与 holding-period return 回答不同资金流问题，百分比收益必须几何复利；illiquid valuation 可平滑波动并虚增 t 值。市场调整或 beta alpha 仍可能遗漏规模、风格、流动性和动态暴露；更频繁采样不能替代更长历史。正态 t-test 会低估 fat tail 和负偏度，短波动、martingale/doubling 或稀有灾难可制造长期小赢的 peso pattern。冠军来自大 trial pool 时标准单策略检验无效；只展示存活基金、宣传 winners 或事后选择起点会产生 selection/survivorship bias，随后均值回归不是自动反向 alpha。
- **项目动作**：建立 `PerformanceEvidence`：以 run/trial ledger 和 immutable universe 为根，保存 gross/net return、cash/position/fill/ledger reconciliation、benchmark/factor exposures、portfolio/strategy/execution attribution、turnover/cost/capacity、tail/drawdown、trial count/effective breadth、selection/survival state、statistical estimate/CI/power、multiple-testing control、OOS/locked-holdout 状态与 process/resource evidence。研究阶段只报告“证据支持到何种程度”，不把统计筛选自动转为仓位或 gate；任何后验选择都在完整 trial family 中重算。
- **禁止直接采用**：不得把 raw return、单年冠军、market-adjusted alpha、t>1.64、95% confidence、历史 2% skill、20年以上样本、基金相关性或书中经理数字当固定阈值；不得把低波动当低风险、稳定正收益当高技能、均值回归当预测信号、幸存记录当完整总体，或用当前项目 holdout 补足样本。不得因书中比较优势论述自行运行新回测、改参数、查看 holdout 或形成 promotion/paper/live 结论；所有交易安全旗标保持 false。
- **L3 待复核**：`FORM-EXE01-CH22-001`—`035`。

## 已完成 L2：第 23 章

### 第 23 章：指数版本、复制误差与产品可交易语义

- **论证链**：index不是天然存在的“市场”，而是由component universe、weighting method、divisor、corporate-action处理与price/total-return convention共同定义的规则产品；同名index在不同版本、日期和回报口径下可能不是同一对象。index fund持有可交易portfolio以复制index，tracking error来自holdings/cash、dividend timing、deposits/redemptions、reconstitution、fees与交易成本；减少交易、抽样或替代成分可能提高net return，却增加复制偏差。index products把广泛的index risk压缩成单一基金份额或衍生合约，集中order flow、降低多证券安排/清算成本并常更快发现共同风险价格，但这种领先不表示component价格错误或产品天然更优。
- **成立条件**：任何index/ETF/rotation命题必须保存index provider、methodology/version/hash、announcement/effective timestamps、PIT components、shares/free-float/weights、divisor、currency、price或total-return口径、dividend与corporate-action处理、rebalance schedule和license/source lineage。fund/product证据还需保存legal vehicle、holdings/cash/fees、NAV timestamp与valuation source、creation/redemption unit和authorized capability、premium/discount、tracking difference/error、spread/depth、settlement、tax仅作法域注释；futures/options需另存multiplier、expiry、roll、margin、cash settlement和basis。portfolio trade必须保留全部legs、benchmark、aggregate/leg fills与allocation。
- **局限与反例**：price-weighted、capitalization-weighted、equal-weighted和geometric index表达不同暴露；price index不含income，不能直接作为total-return benchmark。完全复制也会因fees/cash flow和dividend reinvestment落后，抽样复制又引入tracking/model risk。reconstitution前后价格变化可混合被动flow、liquidity、momentum、信息和预期，事后反转不能唯一识别临时冲击；“index market领先cash”依赖时钟、交易活跃度和共同风险，并非固定因果。书中Russell样本、program-trade阈值、ESP、Liquidnet、ETF税务、佣金、指数规模与旧产品清单均过时，只作机制案例。
- **项目动作**：建立 `IndexPortfolioAndProductEvidence`：数据层提供append-only index snapshots和announcement→effective事件，resolver只按研究时点返回当时已知成分、权重与divisor；Strategy使用total-return、可交易且PIT的index/product series，明确signal clock、rebalance delay和T+1/venue限制。Portfolio/Risk分离index exposure、tracking risk、product basis、roll/margin与component liquidity；OMS依据ETF、cash basket或futures的current capability选择路径，不把NAV、close或理论basket当成交价。Fill/Ledger纳入份额、现金、股息、fees、creation/redemption、roll、corporate actions与全部legs，对账后才能报告tracking difference和net performance。
- **禁止直接采用**：不得使用未来成分、未来权重、事后divisor、修订后公告时间或存活指数回填历史；不得把price index收益当total return，把index close/NAV当日内可成交价，把ETF份额、open-end fund、cash basket、futures和options当同一资产。不得从index inclusion预设上涨、从deletion预设下跌、从futures领先推断现金市场错误，或迁移历史program threshold、package quote、tax/fee和产品规则。不得据本章运行新回测、调参、查看holdout、生成promotion结论或调用private/order/paper/live接口；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH23-001`—`024`。

## 已完成 L2：第 24 章

### 第 24 章：强制流动性义务、角色冲突与特权对价

- **论证链**：specialist制度把dealer、agency broker和auction/exchange official三种角色集中给指定主体，以affirmative obligation要求其在无人愿意交易时维持meaningful two-sided quote、有限规模和orderly market，又以negative obligation要求其让位于更优或同价public orders、不得随意消耗客户limit liquidity。义务会在adverse-selection和波动期造成成本，因此制度用order-flow先见、选择参与时机、quote/auction影响、部分brokerage revenue等特权补偿。问题不是单看spread或continuity，而是特权价值是否与增量liquidity相称、agency/principal冲突是否可审计、受益者与承担成本者是否错位。
- **成立条件**：任何designated-liquidity-provider结论必须固定current venue/rule/version、designation和scope、session/auction、minimum quote size、max spread或meaningful-quote标准、normal/stress obligations、exemptions、public price/time precedence、agency/principal account、order-information access、quote/control权限、commission/rebate与penalty。服务证据至少包含quote uptime、spread/depth、fill/price improvement、reversal/resiliency、inventory/capital、stress participation、cancel/confirm latency、audit trail、complaints/enforcement及counterfactual baseline；同时按market/limit、small/large和home/other venue报告benefit/cost distribution。
- **局限与反例**：price continuity可能缓和无信息冲击，也可能迫使dealer在真实价值变化时逆势亏损或延迟price discovery；现代quote/book可见性提高后，连续last price不再是唯一fairness指标。spread、depth、reversal和price improvement都可被选择性参与、stopped order或quote设置影响，单项KPI不能证明公共服务。public-good/free-rider与order-flow externality可能形成自然垄断和集中，也可能只是历史floor/routing制度产物。书中NYSE/AMEX/CBOE、tick变化、commission、opening/stopping、ITS、公司数量和2001监管均属旧制，不得当当前venue capability或法律。
- **项目动作**：建立 `DesignatedLiquidityProviderGovernanceEvidence`：venue adapter只从官方current rules加载provider obligation/capability，按principal/agency/auction权限分权并对order-book、client identity和stop/conditional order数据实施最小访问。Risk独立监控inventory、capital、quote obligation和stress headroom；OMS强制public priority、account segregation、idempotent cancel/confirm与完整event timestamps；监控层同时报告provider service、private benefit、customer harm和cross-venue free-rider。当前BTC和美股系统没有被本章证明具备specialist角色，因此只保留架构审查模板，不创建specialist策略或假设指定流动性承诺。
- **禁止直接采用**：不得利用agency order、book imbalance、客户身份、size或stop信息进行自营speculation、quote matching、cream skimming、选择性step-ahead、触发stop、gunning、stopped-stock look-back或opening-price操纵；不得以price improvement掩盖被剥夺的limit fill，也不得让principal账户决定agency order的展示、取消或成交时机。不得迁移历史tick、participation rate、commission、quote义务、capital标准或assignment机制。本章不授权新回测、调参、holdout查看、promotion结论或private/order/paper/live调用；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH24-001`—`030`。

## 已完成 L2：第 25 章

### 第 25 章：最佳执行、路由冲突与流动性碎片化

- **论证链**：internalization由dealer/broker自有账户承接客户单，preferencing以payment、rebate或非货币利益把order flow定向给特定dealer/ECN，internal crossing则在同一broker客户间撮合。三者可能用wholesale利润补贴低佣金、给小单price improvement或提供匿名/大宗服务，却把订单移出共同搜索场所。best execution不是“成交在NBBO”或“佣金最低”的单指标：marketable order关心price、speed、size和impact，standing limit order还关心本应何时成交以及是否失去有利fill。路由收益若归broker、执行损失由client承担，就产生代理冲突；order flow离开aggressive public quote后，又会降低报价者获单概率并扩大全市场spread。
- **成立条件**：任何routing/best-execution结论必须保存client/portfolio objective、parent与child ID、order type、side/size/urgency/limit、decision/submission/route/ack/fill/cancel时钟、current NBBO与depth/hidden limitation、venue/counterparty、internalized/preferenced/crossed状态、PFOF/rebate/commission/fee/ancillary benefit、price improvement、fill speed/rate、partial/nonfill、markout、implementation shortfall和opportunity cost。路由政策需按security、size、order type和market state预注册候选venue与权重，以ex-ante expected quality和同类cohort比较，保存定期review、exception、complaint和adjustment；broker/client收益与公开市场外部性分列。
- **局限与反例**：NBBO只覆盖显示价格和规模，不证明大单、hidden liquidity或standing limit的最佳结果；limit order是否“应成交”需要不可观察queue与cancel反事实。低佣金可能由更差隐性价格补贴，也可能在竞争充分时降低小单net cost；书中perfect-competition结论依赖自由进入、同成本和无market power，现实集中、switching cost与规模经济会破坏。internal crossing限制外部搜索但也可能提供速度、匿名、规模或定制服务；集中order book并非自动最优。章节中的旧SEC规则编号、NBBO实践、Primex/ECN、NYSE算法、佣金与账户转移时长必须按当前官方规则复核。
- **项目动作**：建立 `BestExecutionAndRoutingConflictEvidence`：Strategy不得选择broker/venue，只输出受Portfolio/Risk批准的OrderIntent；OMS依据current capability、预注册路由政策与client-first objective路由，所有internalization、rebate、PFOF和crossing利益进入冲突登记且不得覆盖hard price/size/risk constraints。执行后按matched cohort计算all-in cost、fill/miss、speed、price improvement、realized spread和markout，生成可重放exception report；standing limit另做queue/fill opportunity audit。监控同时观察公开quote获单率、spread/depth和venue concentration，但任何市场外部性结论保持多假说。
- **禁止直接采用**：不得因佣金低、成交在NBBO、有price improvement、venue支付rebate或客户曾接受服务就声称best execution；不得把retail/small flow自动标记uninformed，把large/institutional flow自动标记toxic，也不得只把有利marketable orders内部化、把不利flow和limit risk外包给公开市场。不得为收取双边佣金限制order exposure、偏袒dealer/关联客户、用payment优化routing或用历史limit-protection算法伪造queue优先。不得迁移旧法规、报告标准和venue规则，不得运行新回测、调参、查看holdout、形成promotion结论或调用private/order/paper/live接口；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH25-001`—`026`。

## 已完成 L2：第 26 章

### 第 26 章：碎片化市场、跨venue联接与公共外部性

- **论证链**：市场集中有两层含义：交易者聚到同一流动性网络可降低对手搜索成本并强化best-price competition；market centers分化则用不同规则、order exposure、速度、接入、信用和定制服务满足异质需求。order-flow externality令流动性吸引流动性并保护incumbent，也可能阻止更优创新进入。碎片化不必破坏price formation：若各segment的trades/quotes低成本、及时且可比地传播，且部分参与者能跨segment调整订单、路由流动性或做套利，多个片段可共同形成统一价格与容量；反之hidden/stale data、不可达市场、broker利益冲突和跨腿失败会把显示价差变成假机会。
- **成立条件**：任何cross-venue/market-structure结论必须固定canonical instrument或economically equivalent contract、venue/rule/capability version、session/clock/timezone、currency/FX、tick/lot/multiplier、fees/rebate/tax、settlement/clearing、access/credit、market-data entitlement/latency/age、quote/book firmness、hidden scope、trade reporting和venue health。路由证据需保存parent/child、candidate venues、expected price/depth/fill/cost、route/ack/cancel/fill clocks、priority与secondary precedence、duplicate/overfill prevention、failover和actual all-in outcome；cross-market arbitrage另存每腿borrow/funding/margin、basis、synchronization与broken-link stress。
- **局限与反例**：consolidated market最大化同一结构内的价格竞争，却未必满足大单保密、patient limit、impatient immediacy或不同信用层级；fragmentation提供差异化服务，却至少增加信息基础设施、routing和arbitrage资源成本。公开top-of-book不包含hidden/latent size，fast linkage也可能破坏需要协商时间的市场；best displayed price不保证queue、size、latency、fees后可执行。跨segment通常能实施price priority，却难实施global time/public-order precedence；小tick和maker rebate可能改善quote也可能鼓励quote matching。书中ECN/Nasdaq/NYSE/ITS、旧API、venue清单、program规则和decimalization叙事均不能作为当前事实。
- **项目动作**：建立 `MarketFragmentationAndLinkageEvidence`：数据层按统一schema摄取各venue的rules、status、L1/L2/trades并保留source clock与staleness；OMS先做capability/access/credit检查，再以client-first all-in executable outcome比较route，所有venue共享全局parent ID、remaining quantity和reconcile-before-retry。跨venue策略在任一关键数据陈旧、订单状态unknown、leg不可借/不可达或settlement不兼容时fail-closed。监控层分报liquidity concentration、route share、cross-venue basis、link latency、duplicate/fill divergence、outage/failover、public surveillance与market-center conflict，不把market share或窄spread单独当市场质量。
- **禁止直接采用**：不得把不同venue同名symbol直接视同一instrument、把异步quote拼成crossed market、把best price当可成交价格、把arbitrage显示basis当净利润，或在未确认cancel前跨venue重发。不得假设所有交易者同质、所有市场自由接入、所有broker追求best price、API link必然提升质量、集中必然公平或碎片化必然创新；不得迁移旧tick、precedence、routing、监管和market-share结论。本章不授权新回测、调参、holdout查看、promotion结论或private/order/paper/live调用；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH26-001`—`034`。

## 已完成 L2：第 27 章

### 第 27 章：自动化执行 SRE、可审计规则与接入公平

- **论证链**：floor oral auction与automated rule-based auction都可按类似order-driven原则撮合买卖，不能仅凭界面判断市场质量。自动化把规则固化为程序，能更快处理消息、统一执行、直接分布式接入、准确报告market data并自然产生完整event trail；但它只会忠实执行被编码的规则和缺陷，网络、认证、容量、时钟、软件或灾备失效会同时影响大量参与者。floor擅长实时协商size、交换counterparty/latent interest和依靠reputation传递非结构化信息，却受人工容量、physical access、记录错误、选择性信息及agency abuse限制。系统选择因此是可验证service/cost/risk权衡，而不是“电子必胜”或“人工更有流动性”。
- **成立条件**：任何automated execution readiness必须保存market rule/spec hash、matching/priority implementation version、order state machine、source/exchange/OMS clocks、identity/authentication/authorization、data entitlement、regional/network latency distribution、throughput/queue/headroom、rate limits/backpressure、dependency map和single-point-of-failure审查。SRE证据需包含redundant compute/network/vendor/path/power、backup与hot recovery、RTO/RPO、failover/failback、idempotency、unknown-order reconcile-before-retry、duplicate/overfill prevention、kill switch、degraded/manual mode、immutable audit、deterministic replay、security incident与independent QA/load/chaos测试边界；测试不得触达生产交易端点。
- **局限与反例**：programmed consistency不证明规则公平、代码正确或所有参与者access相等；共址、自动策略、data tier和网络路径会制造sub-millisecond advantage。完整系统日志也可能因clock skew、丢包、外部broker行为或权限缺口而不完整。自动化容量高但极端surge仍会饱和；stop order在断线、gap或venue outage时不保证触发和成交，不能替代本地risk/kill/reconciliation。floor的counterparty筛选与full-size reputation可帮助大单，也可能泄露敏感意图、歧视参与者或无法审计。书中floor市场、专线成本、系统价格、venue和Madoff案例均过时。
- **项目动作**：建立 `AutomatedTradingSystemSREEvidence`：OMS/adapter以显式finite-state machine管理intent→submit→ack→partial/fill/cancel/reject，所有retry先查询并reconcile；market data、order gateway、risk与ledger分别监控freshness、latency、capacity和divergence。失联时停止新增风险，保留现有order unknown状态并走预定义cancel-all/venue kill/manual escalation，不用推测补单。每次release用合同fixture、fault injection和replay验证priority、partial fill、out-of-order events、duplicate ack、network partition与recovery；Portfolio/Risk在degraded state收紧限额，Strategy不得直接感知broker或决定failover route。
- **禁止直接采用**：不得因系统自动化就声称fair、fast、secure、low-cost或best execution，也不得因floor市场存续推断其技术更优。不得把client disconnect视为order canceled、把missing ack视为未下单、把stop loss当断线保险、把backup存在视为RTO达标，或在主链状态unknown时切换venue重复下单。不得迁移历史latency、capacity、成本和venue比较，不得自行运行production load/chaos测试、新回测、调参、holdout查看、promotion判断或private/order/paper/live调用；安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH27-001`—`026`。

## 已完成 L2：第 28 章

### 第 28 章：反馈型极端波动、市场状态切换与危机 SRE

- **论证链**：极端波动不是单一“坏消息→价格跌”的线性过程。乐观叙事、momentum/order anticipation、财富与保证金反馈可先推动拥挤错价；value/arbitrage 受估值不确定、short/borrow、资本和timing risk限制，无法保证及时纠偏。信心转折后，获利了结、stop、margin liquidation、流动性撤退和跨市场价格领先可共同放大卖压；order backlog、未知 fill、quote失真和cash/futures断连又把执行不确定升级为恐慌。fundamental 与 transitory movement 可同时存在，触发新闻不等于根本原因，事后反转也不证明此前全部非基本面。
- **成立条件**：危机判断必须固定 instrument/venue/session、current rule hash、price/return horizon、market state、halt/limit/auction status、quote/book age、order/ack/fill/cancel backlog、capacity/latency/error、direction/size/imbalance、leverage/margin/liquidation、borrow/short constraints、cross-market basis与leg executability、event information set、fundamental uncertainty及recovery window。对 halt 或 circuit breaker 的评价需区分 fundamental discovery 与 transitory imbalance，并验证其他 venue 的联动、order migration、reopen price discovery 和 clearing exposure。
- **局限与反例**：fundamental value不可观察，bubble/crash标签高度后验；1929、1987、1989、palladium、Iomega、Nasdaq、日本案例的制度、参与者与数据均不可迁移。dynamic hedge/portfolio insurance在小规模、连续可交易和低impact时可能工作，拥挤后却产生同向反馈；halt可给流动性供应者和信息处理时间，也可能延迟必然重估、制造gravitational rush、压制arbitrage并把订单挤到其他venue。transaction tax/margin等粗粒度限制会同时伤害dealer、informed/value和utilitarian flow；历史监管规则、阈值和政治解释不能当当前法规或最优政策。
- **项目动作**：建立 `CrisisMarketStateEvidence`：保存 trigger/event、state transition、venue/rule/capability hash、reference/index source、halt/limit/reopen auction、order gateway/backlog/duplicate prevention、market-data freshness、L1/L2/fills、cross-venue basis/legs、margin/liquidation/default、capacity saturation、RTO/RPO、kill-switch、manual escalation、reconciliation与deterministic replay。Strategy只能在已声明的crisis regime中降级或停止发信号；Portfolio/Risk独立收紧gross/net/leverage/liquidity limits；OMS在stale、unknown state、unconfirmed orders或跨腿失配时fail-closed。
- **禁止直接采用**：不得用价格大涨/大跌直接判bubble/crash、用历史月份或新闻故事生成alpha、把bounce当必然、把halt当风险消失、把price limit当可成交价格、把动态对冲当保证底线、把显示价差当跨市场套利可执行，或迁移书中1987规模、delta、交易量、Rule 80A/80B阈值与监管结论。不得自行运行危机回测、改risk参数、查看holdout、发起order或生成promotion/paper/live结论；所有安全旗标继续为false。
- **L3 待复核**：`FORM-EXE01-CH28-001`—`030`。

## 已完成 L2：第 29 章

### 第 29 章：重大非公开信息治理、合法研究边界与合规证据

- **论证链**：本章把 inside information 概括为会影响证券价值、尚未向公众可用的重大信息，同时强调具体法律定义依赖成文法、监管规则与判例，经济解释不能代替当前法域法律意见。直接内幕人、tippee、受托服务人员、政府雇员及盗用雇主/客户机密者可能通过不同链路取得信息；相反，只依赖已公开资料进行独立分析而形成的私有结论，不因结论有价值就自动成为内幕信息。异常价格、成交量、期权仓位、关系网络与时机可触发调查，却不能单独证明信息传递、主观明知或违法；合法研究与非法信息交易可能产生相同市场轨迹。
- **成立条件**：任何信息型研究都必须保存 source owner、原始载体/hash、acquisition method、license/entitlement、recipient/audience、confidentiality、materiality assessment、public-disclosure channel、首次广泛公开时刻、ingest/availability clock、PIT transform、access principals、downstream datasets/models/runs和人工升级记录。公开网页出现不必然等于已广泛公开，选择性披露、embargo、错误权限、提前获得的政府/研究报告、顾问/打印/法律/投行材料和口头提示均需默认隔离；跨美股、BTC 与 A 股使用时必须逐法域核验最新规则。
- **局限与反例**：书中 SEC 定义、Regulation FD、申报期限、预设交易计划、short-swing profit、刑责/民责数字和案例均为历史材料，不能当作 2026 年有效法律。图关系、异常收益、集中财富下注、新闻前成交或知情人与获利者之间的联系只提供调查线索；长期未离散披露的信息尤其难从价格/成交量识别。内幕交易可能加快短期价格发现，也会提高 adverse-selection 成本、削弱流动性供应、损害投资者信心及诱发管理层不分享信息、扭曲项目选择或抢跑公司交易；这些经济权衡不授权项目自行判断行为合法性。
- **项目动作**：建立 `MaterialNonpublicInformationGovernanceEvidence`：数据目录为每个 source 标注 `public_authorized`、`restricted_review` 或 `blocked`，研究管线只消费 `public_authorized` 且 PIT 可证明的数据；访问采用最小权限、分环境隔离和不可变审计，模型特征保留到原始披露的lineage。异常交易检测只能输出 `compliance_risk_flag` 与alternative hypotheses，不输出违法定性；疑似MNPI、来源不明、提前可见、访问越权或披露时间无法证明时，停止传播/研究/交易使用并交由合规或法律责任人处理。Strategy仍只输出Signal/Forecast/TargetPosition/OrderIntent，不能借信息优势绕过Portfolio/Risk、OMS和Fill/Ledger。
- **禁止直接采用**：不得抓取、索取、推断或传播机密/私有信息，不得利用误配权限、提前发布、员工/顾问关系或个人身份图谱生成信号；不得因信息出现在小范围会议、未公告网页或聊天转述就视为公开，也不得因公开资料分析准确就反向声称其违法。不得把本章处罚数字、申报时限、交易窗口或政策主张写入生产规则；不得由收益、订单模式或关系推断直接处罚账户。本章不授权新回测、改参数、查看holdout、生成promotion结论或调用private/order/paper/live endpoint，所有安全旗标保持false。
- **L3 待复核**：`FORM-EXE01-CH29-001`—`030`。

## 全书 L2 完成状态

EXE-01 的 29 章已全部完成 `L2` 语义精读。下一步仅将跨章节稳定规则压缩同步到 Agent 手册；813 个条目仍为 `identified_pending`，未完成原版公式、数字、法规与当前 venue 事实的 `L3` 复核，不构成回测、promotion、paper 或 live 证据。
