---
book_id: STR-04
title: Trading Systems and Methods
authors: [Perry Kaufman]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Trading Systems and Methods - Perry Kaufman - 原文.md
source_format: pdf_text_original_pdf_bookmarks_cross_checked
source_sha256: f741994cba06ac0630e9dc75699763b0cbeb618ad4773c0dc110cf6aa9b8241d
source_line_count: 55158
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\Trading Systems and Methods (Perry J. Kaufman) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_source_sha256: 25a2b085bcee92b93c82f0b8da4d6e330dc5801d08bb0063c1814641579d6d8b
original_source_page_count: 2285
card_status: chapter_semantic_review_l2_complete_original_pdf_structure_verified_formula_pending
chapter_count: 24
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 24_chapter_method_clusters_original_pdf_bookmarks_verified_formulae_tables_parameters_pending
last_reviewed_at: 2026-07-15
---

# STR-04：Trading Systems and Methods

## 覆盖声明

本卡依据 PDF 目录和正文页首定位 24 章。第 1—24 章已全部完成逐章 `L2` 语义精读，覆盖率 `24/24=100%`。现已直接核对 2285 页原 PDF 的 24 个 chapter bookmark、物理页范围和一级子节结构，确认 24 个章节方法簇均有原始来源。由于每个 `FORM-STR04-*` 代表一整章高密度方法簇而非单一公式，本轮状态仅提升为 `original_pdf_structure_verified_formula_pending`；全书逐式、逐表、逐参数 `L3` 仍未完成，不能计为单书 complete，也不证明任何方法对当前 BTC 或美股系统有效。

## 全书项目映射

- `candidate_library`：作为基线与反例目录，供研究票据选择少量有经济机制、可交易数据和明确 falsification 的方法。
- `existing_rule_confirmed`：测试完整性、成本、风险归一、现实约束和组合分散优先于复杂指标。
- `risk_warning`：大量方法带来极高 researcher degrees of freedom；每个变体都必须计入 trial ledger，禁止批量注册 paper candidate。
- `rejected_for_now`：占星、纯图形主观识别和无法定义 PIT 输入/客观规则的方法不进入系统研究队列。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Introduction | `2014-3026` | `L2/high` | 系统方法必须在交易前给出完整客观规则，但自动化不保证数据、成本或风险正确。作者的开发准则强调机制先行、最简表达、逐组件增量验证、检查遗漏和手工复算；异常好结果与坏结果同样优先怀疑。 | `existing_rule_confirmed`：候选先写 mechanism、clock、input、cost/risk、failure 与 falsification；逐组件 ablation、人工 oracle 和异常好结果审计进入 evidence contract，书中市场占比与历史费用禁用。 | `FORM-STR04-CH01-001` |
| 2 Basic Concepts and Calculations | `3027-5125` | `L2/high` | 样本误差、均值类型、分布矩、频数分布、t/自由度、自相关、收益复利与风险年化必须按问题选择；价格与交易收益常偏态肥尾，单一标准差或正态概率会失真。经济数据还存在低频、修订和“预期差”时钟。 | `implementation_gap`：统一 simple/log/geometric return、frequency、annualization、sample/population、downside/tail、missing/revision/as-of；统计函数需中间值 fixture，阈值、252 日与历史概率均待 L3。 | `FORM-STR04-CH02-001` |
| 3 Charting | `5126-8248` | `L2/high` | chart 的频率、起点、坐标尺度、画框比例和线段选择都改变视觉结论；趋势在事后更清楚，突破发生时反而最不确定。back-adjusted futures 的历史绝对价不能直接当真实 support/resistance，复杂形态还依赖人工上下文。 | `concept_only`：只允许可确定性编码、prefix-invariant 的 price field/scale/window/trigger；形态失败必须可证伪，研究调整价与真实合约价分离，所有 candle/目标价变体计入 trial family。 | `FORM-STR04-CH03-001` |
| 4 Charting Systems | `8249-9620` | `L2/high` | 将 thrust、inside/outside day、pivot、retracement、channel、CCI 和 candle 自动化会暴露旧规则中的歧义、市场漂移与层层确认自由度。书中 412 个 candle 组合经出现次数过滤后“成功”比例大幅下降，且胜率未说明幅度和净收益。 | `candidate_library`：仅保留简单 channel/breakout/pivot 基线；每个方向、确认、阈值、持有期和 pattern family 都登记 trial，报告 occurrence、payoff、cost 与 OOS，不实现 Fibonacci/Gann 等 revelation rule。 | `FORM-STR04-CH04-001` |
| 5 Event-Driven Trends | `9621-11337` | `L2/high` | swing、point-and-figure 与 N-day breakout 只在事件触发时更新，可降低时间噪声并快速响应突破，但风险可能高于时钟型趋势；swing filter、反转顺序和 weekly holiday 处理使其本质上是 path-dependent 状态机。历史 breakout/Turtle 窗口和组合风控只反映特定市场与年代。 | `candidate_design`：建立 event-state replay，明确 high/low/close、strictness、filter 更新、same-bar precedence、holiday/session、next tradable fill、gap 与 stop；N-day 作为基线，全部 Turtle 数值禁用。 | `FORM-STR04-CH05-001` |
| 6 Regression Analysis | `11338-12929` | `L2/high` | 回归首先解释历史关系，不自动预测未来；forecast 要求未来 regime 与训练期可比且 horizon 越远误差越大。频率对齐、detrending/stationarity、residual、共线性、变量选择和收敛决定线性/多元/ARIMA 的可信度，更多变量并不必然更好。 | `candidate_design`：滚动/PIT 训练，保存 transform/inverse、feature release lag、residual diagnostics、coefficient stability、prediction interval、convergence 与 simple slope/MA baseline；禁止 level regression 和全样本变量筛选。 | `FORM-STR04-CH06-001` |
| 7 Time-Based Trend Calculations | `12930-14118` | `L2/high` | 时间型趋势算子都以降噪换取滞后；简单/加权/指数/双重平滑的权重、drop-off、残余影响和 warm-up 不等价。均线周期与指数平滑常数并非线性对应，等距参数网格会造成不均匀搜索；lead plot 只是图形位移，不能成为可交易预测。 | `candidate_library`：统一 operator kernel、price field、权重归一化、初始化、warm-up、lag/drop-off/residual-impact 和缺失值语义；按等效半衰期/有效窗口采样参数，lead/centered 变换禁止进入因果信号。 | `FORM-STR04-CH07-001` |
| 8 Trend Systems | `14119-16601` | `L2/high` | 趋势收益依赖少数 fat-tail 大单，代价是低胜率、滞后、横盘 whipsaw、成本与回撤；速度、信号取 price cross 还是 trend turn、band 和执行延迟会改变风险画像。等待更好成交可能错失不回撤的突破，止盈或紧止损还可能切断右尾。 | `candidate_design`：BTC/美股分别建立最简慢趋势、breakout 与 band 基线；明确 close/next-open、same-bar、signal/fill lag、cost、gap、long-only 和退出语义，按多市场/多周期稳定性而非最佳参数筛选，所有书中窗口与阈值禁用。 | `FORM-STR04-CH08-001` |
| 9 Momentum and Oscillators | `16602-19466` | `L2/high` | momentum、MACD、RSI、stochastic 与 divergence 多由价格差、趋势差或滚动区间重表达；缩放、平滑和 boundedness 决定极值停留、滞后与阈值稳定性。原始 momentum 的量纲随价格和波动 regime 漂移，逆势极值并不保证价格反转；不同算子在同周期下可能高度同质。 | `candidate_library`：区分 trend confirmation、entry timing 与 countertrend；只用滞后滚动尺度做 percent/volatility normalization，保存 zero-denominator、cap、warm-up 与 extreme persistence；做 operator similarity、feature ablation 和 threshold trial accounting，不接受主观 divergence。 | `FORM-STR04-CH09-001` |
| 10 Seasonality and Calendar Patterns | `19467-21916` | `L2/high` | 季节性必须绑定可交易日历、合约与经济机制；cash、单合约、continuous/back-adjusted futures 的月收益不能互换。均值容易被少数极端年份支配，median、正收益年份占比、分期样本和波动范围揭示 regime 漂移；更细日频会增加噪声，并不增加独立年度样本。 | `candidate_design`：建立 PIT calendar/session/holiday、contract month/roll、cash-vs-futures 与 release/weather as-of 合同；按年度为独立重复单元，报告 median、hit-rate、tail range、subperiod stability 和 trial family。美股仅研究有机制的财报/税务/节假日效应，BTC 不迁移农业季节性。 | `FORM-STR04-CH10-001` |
| 11 Cycle Analysis | `21917-23722` | `L2/high` | Fourier/spectral、MESA、Hilbert 与 phasing 都要求先处理趋势、端点和频率；周期长度、振幅与相位会漂移，低频样本通常只有极少完整周期。FFT 受窗口、采样长度和 stationarity 约束；MESA/短样本方法以适应性换取统计不稳定，战争/K-wave 等长周期叙事缺少足够重复。 | `research_only`：先用合成数据验证 detrend/window/endpoint/phase 算法，再做 rolling dominant-frequency、phase stability、minimum-cycle-count 和 surrogate/noise falsification；centered/lagged phasing 不得泄漏未来，长周期叙事与占星周期默认拒绝进入信号库。 | `FORM-STR04-CH11-001` |
| 12 Volume, Open Interest, and Breadth | `23723-25742` | `L2/high` | volume/OI/breadth 是参与度而非方向真值：日内 U 型、节假日、财报、到期换月、延迟发布和成分范围都会改变口径。futures contract 与 total volume/OI 生命周期不同，breadth 必须匹配交易 universe；volume 极不稳定，spike 可能是耗竭也可能只是事件，传统确认/背离解释需独立检验。 | `candidate_design`：数据合同记录 venue/universe、PIT constituents、session/bar timestamp、report latency、contract/total/roll 和 tick-vs-actual volume；只用已完成区间并按同一 intraday bucket 归一化。指标先作增量 filter/ablation，比较 price-only baseline，历史窗口与阈值禁用。 | `FORM-STR04-CH12-001` |
| 13 Spreads and Arbitrage | `25743-28780` | `L2/high` | spread/arbitrage 的低净波动不等于无风险；carry、basis、delivery、seasonality、borrow、FX 与结构变化决定关系，legging、短缺、到期、流动性和单腿波动失配可使风险高于 outright。相关性只描述短期共动，cointegration/均值回复还需平稳性、hedge ratio 与断裂监控；IV/HV 与不可交易量不能混作可复制套利。 | `candidate_design`：统一 leg identity、单位/乘数、quote/FX、expiry/roll、carry/dividend/borrow、hedge ratio、margin 和 atomic/spread-order fill；多腿 ledger 与压力场景覆盖 legging、halt、short recall、basis break 和 correlation collapse。先模拟净成本后的可执行组合，不把书中比例、阈值或“risk-free”叙事当结论。 | `FORM-STR04-CH13-001` |
| 14 Behavioral Techniques | `28781-32103` | `L2/high` | 本章把新闻、事件冲击、COT/市场意见与 Fibonacci、Elliott、Gann、占星并列，但可证伪性完全不同。新闻效应取决于预期差、精确发布时间和可成交反应；price shock 可能多年不出现且止损成交恶化。COT 的持仓日期、发布日和分类变更必须区分；主观波浪、任意起点/比例与天体叙事提供巨大选择自由度。 | `mixed`：仅保留预注册的 scheduled-event surprise、lagged shock ratio 和 PIT COT 候选，保存 source timestamp、availability、revision、expected/actual、pre-event state 与 fill delay；Fibonacci/Elliott/Gann/占星及媒体封面故事默认 `rejected_for_now`，不得借软件客观化外观绕过证据门槛。 | `FORM-STR04-CH14-001` |
| 15 Short-Term Patterns | `32104-34425` | `L2/high` | pivot、日内高低分布、开盘缺口、weekday/weekend、reversal 与连续形态都高度依赖 session 定义和市场 regime。24 小时市场的“开盘缺口”常是人为切出的 business session；频率表与方向命中率会被长期牛熊偏置、bar 边界和少数极端日扭曲，许多传统格言只是可检验假设。 | `research_only`：预注册 venue/calendar/session、overnight cut、bar timestamp、auction/regular-hours、gap reference、same-bar path 和 next-tradable fill；按 bull/bear/sideways 与 subperiod 报告机会数、幅度、成本和尾部。无 quote/auction 数据前只建描述性基线，不注册 promotion 候选。 | `FORM-STR04-CH15-001` |
| 16 Day Trading | `34426-36322` | `L2/high` | 日内收益空间短且噪声高，commission 之外的 direction-dependent slippage、spread、order size/volume、missed order、locked limit、close/settlement 和价格冲击可吞掉毛利。opening-range/volatility breakout 有大量 bar、阈值、过滤、反转和退出自由度；书中无成本示例不能作为可交易证据。 | `rejected_for_now`：当前系统缺少足够 quote/L2、真实 fill、latency、unable/missed-fill 和容量 replay，不支持 day-trading production。未来研究须使用 session-aware event replay、order-type/queue/slippage model、partial fill 与 adverse selection，并把每个规则组合计入 trial ledger。 | `FORM-STR04-CH16-001` |
| 17 Adaptive Techniques | `36323-37349` | `L2/high` | KAMA、VIDYA、MAMA/FAMA、FRAMA、adaptive RSI/stochastic 与 parabolic 等都先估计 noise/volatility/cycle/state，再动态改变 smoothing、period、band 或 stop；状态误判会把额外噪声变成参数抖动。KAMA 的 noise 不等同 volatility，多个自适应趋势输出高度相似，屏幕更平滑不代表净收益更稳健。 | `candidate_design`：固定参数 champion 对比单一、因果、限幅 challenger；保存 state estimator、fast/slow bound、smoothing transform、rounding、warm-up、update cadence 和 parameter path。做 frozen-state、delayed-state、no-adaptation ablation 与 turnover/cost 归因，书中 2/30、8–10 等值禁用。 | `FORM-STR04-CH17-001` |
| 18 Price Distribution Systems | `37350-38958` | `L2/high` | price/return/volatility distribution、zone、skew/kurtosis、inventory 与 Market Profile 回答的是不同问题；长样本可包含结构断裂，短样本又易受 regime 偏置。Market Profile 的 TPO 是“某时间块曾成交过该价”而非成交量，value area/形态常带解释性判断；从 OHLC 假定区间内每个价格都成交会伪造分布。 | `concept_only`：明确 observation unit、bin/tick、price-vs-return、inflation/FX adjustment、rolling clock 与 structural-break policy；volume-at-price 只接受真实逐笔/聚合成交，TPO 需精确 session 与 bar coverage。先用 synthetic distributions/known ticks 验证 moments、bins 与 value area，不把“公平价值”当预测真值。 | `FORM-STR04-CH18-001` |
| 19 Multiple Time Frames | `38959-39563` | `L2/high` | 多时间框架让低频方向、中频 setup、高频 entry 分工，但相同时长的 hourly/daily/weekly 聚合并不等价；高频 bar 噪声更多，未完成的周线/日线还会造成未来泄漏。组合多个相近趋势/oscillator 容易重复信息，规则冲突、跨频对齐和订单时钟决定真实结果。 | `candidate_design`：forecast/signal 按原生 frequency 独立生成并只在 bar close 后可用，as-of join 到执行时钟；定义 higher-frame precedence、conflict/no-trade、staleness、warm-up 与 partial-bar exclusion。报告 effective breadth、component ablation、incremental cost 和 single-frame baseline，5 倍周期等历史常数禁用。 | `FORM-STR04-CH19-001` |
| 20 Advanced Techniques | `39564-43047` | `L2/high` | volatility/ATR/IV/HV 的单位、价格源和窗口决定其用途，back-adjusted futures 不能直接使用百分比波动。fuzzy/expert/genetic/neural/ML 都是搜索或函数逼近工具，不创造封闭、稳定的市场关系；输入、目标、层数、特征与算法选择会扩大搜索空间，强模型几乎必然能拟合偶然模式。 | `risk_warning`：复杂模型只能作为机制明确的 challenger；统一 PIT preprocessing、label horizon、train/validation/locked holdout、trial lineage、simple baseline、calibration、feature ablation 和 drift/failure monitor。波动特征另存 unit/source/lag，深层模型与自动规则发现当前低优先级。 | `FORM-STR04-CH20-001` |
| 21 System Testing | `43048-46100` | `L2/high` | 测试用于验证预先写下的机制、风险和期望，不是从海量组合中发现故事。adjusted data、经济数据修订、成本、样本 regime、参数采样尺度、walk-forward 窗口、跨市场一致性和 price shock 都会改变结论；峰值参数不如宽阔稳定区。书中“最终 OOS 后用全数据重测”会污染锁定证据，60/20/20 也不是通用保证。 | `existing_rule_confirmed_with_conflict`：采用项目的 pre-registration、purged/embargoed WF、trial ledger、locked holdout access ledger、multiple-testing、current-HEAD evidence 和 shock decomposition；holdout 一经查看绝不回流调参或全样本重估。手工复算交易、邻域/跨市场稳定和异常好结果审计为必需。 | `FORM-STR04-CH21-001` |
| 22 Adding Reality | `46101-47891` | `L2/high` | 计算机只能更快执行已定义语义；错误数据、选择性样本、复杂集成和强搜索会更快放大错误。真实运行与回测的差异集中在 dirty/missing ticks、settlement/last、paper fills、price shock、相关性收敛、信号拥挤和 operational disconnect；极端事件不可预测，历史恰好获利更可能是运气。 | `implementation_gap`：realism replay 覆盖 bad/missing/late data、gap/halt/cancelled trades、stale signal、spread/latency/partial fill、capacity、correlated liquidation、signal similarity 与 crisis mode；paper 仅验证管线，不证明可执行性。预设 fail-closed/kill/recovery，不采用事后为已知危机定制的规则。 | `FORM-STR04-CH22-001` |
| 23 Risk Control | `47892-51143` | `L2/high` | return、standard deviation、drawdown、time-under-water、downside risk、VaR、ruin 与流动性描述不同风险；月度平滑会隐藏日内/日间路径。stop 不能保证成交价且存在 proximity risk，profit-taking 可能切断趋势右尾。volatility sizing、margin reserve、相关性和杠杆必须组合计算；Kelly/optimal f 对胜率、payoff 和最大损失估计极敏感。 | `existing_rule_confirmed`：Portfolio/Risk 独立施加 gross/net、single-name/strategy/venue、liquidity、margin、drawdown、stress-correlation 与 service-loss caps；position sizing 用因果波动并限制跳变。VaR 不替代 gap/tail stress，stop 通过 OMS/replay 验证，Kelly/optimal f 仅作降杠杆压力上界，绝不直接放大生产仓位。 | `FORM-STR04-CH23-001` |
| 24 Diversification and Portfolio Allocation | `51144-53232` | `L2/high` | 分散应基于策略实际 return stream、风险贡献和压力期共振，而非名义资产数；正常期 covariance 会在危机时失效。equal-dollar、inverse-vol/equal-risk、mean-variance、Solver/GA 和 volatility targeting 都依赖估计窗口、目标与约束；低在场率会机械压低样本波动，最优权重可能集中且不稳定，频繁风险缩放增加 turnover。 | `candidate_design`：以 equal 与 inverse-vol 为基线，对 shrinkage/constrained min-var/risk-parity challenger 使用 PIT universe/covariance、cash/short/margin/liquidity/capacity/turnover 约束；报告 weight/risk-contribution stability、condition、stress correlation、rebalance cost、infeasibility 和 post-rounding risk。vol targeting 滞后且最后再过硬 exposure cap。 | `FORM-STR04-CH24-001` |

## L3 原始 PDF 结构复核

| 章节项目 | 原 PDF 物理页 | 原 PDF 书签/一级子节证据 | 当前状态 |
|---|---:|---|---|
| `FORM-STR04-CH01-001` | `83-121` | `System Development Guidelines`、`Profile of a Trading System` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH02-001` | `122-210` | `Simple Measures of Error`、`Moments of the Distribution`、`Standardizing Risk and Return`、`Probability` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH03-001` | `211-339` | `Chart Formations`、`Trendlines`、`Price Objectives`、`Candlestick Charts` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH04-001` | `340-397` | `Thrust Method`、`Pivot Points`、`Channel Breakout`、`CCI`、`Computer Recognition` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH05-001` | `398-470` | `Swing Trading`、`Point-and-Figure`、`N-Day Breakout` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH06-001` | `471-538` | `Linear Regression`、`Correlation`、`Multivariate Approximations`、`ARIMA` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH07-001` | `539-586` | `Moving Average`、`Drop-Off Effect`、`Exponential Smoothing`、`Lags and Leads` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH08-001` | `587-687` | `Trend Systems`、`Bands and Channels`、`Trend Speed`、`Early Exits` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH09-001` | `688-804` | `Momentum`、`Oscillators`、`Velocity and Acceleration`、`Divergence` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH10-001` | `805-922` | `Seasonal Pattern`、`Weather Sensitivity`、`Seasonal Trades`、`Stock Market` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH11-001` | `923-1002` | `Cycle Basics`、`Maximum Entropy`、`Short Cycle Indicator`、`Phasing` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH12-001` | `1003-1086` | `Volume and Open Interest`、`Breadth Indicators`、`Intraday Volume Patterns` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH13-001` | `1087-1209` | `Carrying Charges`、`Spreads`、`Arbitrage`、`IV versus HV` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH14-001` | `1210-1354` | `News`、`Event Trading`、`COT`，以及 Fibonacci/Elliott/Gann/Astrology | `original_pdf_structure_verified_formula_pending`；玄学分支保持拒绝 |
| `FORM-STR04-CH15-001` | `1355-1453` | `Daily Highs and Lows`、`Time of Day`、`Opening Gaps`、`Weekday/Weekend` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH16-001` | `1454-1528` | `Transaction Costs`、`Slippage and Liquidity`、`Intraday Breakout`、`HFT` | `original_pdf_structure_verified_formula_pending`；日内/HFT仍 blocked |
| `FORM-STR04-CH17-001` | `1529-1569` | `Adaptive Trend`、`Adaptive Momentum`、`Adaptive Intraday Breakout` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH18-001` | `1570-1637` | `Price Distributions`、`Inventory Models`、`Market Profile` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH19-001` | `1638-1662` | `Two/Three Time Frames`、`Triple Screen`、`KST` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH20-001` | `1663-1799` | `Volatility`、`Liquidity`、`Fuzzy/Expert`、`GA`、`Neural Networks` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH21-001` | `1800-1917` | `Test Data`、`Testing Integrity`、`Parameter Search`、`Costs`、`Valid Results` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH22-001` | `1918-1987` | `Final Steps`、`Extreme Events`、`Runs`、`System Trade-Offs`、`Signal Similarity` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH23-001` | `1988-2116` | `Measuring Return and Risk`、`Position Sizing`、`Stops`、`Leverage`、`Ruin` | `original_pdf_structure_verified_formula_pending` |
| `FORM-STR04-CH24-001` | `2117-2196` | `Portfolio Models`、`Classic Allocation`、`Solver`、`GASP`、`Volatility Stabilization` | `original_pdf_structure_verified_formula_pending` |

## 未完成边界

- 24/24 章的来源、物理页和章节方法簇已经原 PDF 结构核验，但这不等于章内所有公式、表格、参数和历史结果已逐项复核。
- 下一阶段应把每章方法簇拆成原子公式/表格 ID，记录符号、假设、原页、可信度和项目边界；在此之前本书保持 `formula_pending`，单书完成数不增加。
- 日内、HFT、订单、paper/live、复杂 ML、玄学图形和书中历史参数均不因结构核验而解锁。
