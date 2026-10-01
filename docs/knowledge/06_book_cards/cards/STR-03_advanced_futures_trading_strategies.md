---
book_id: STR-03
title: Advanced Futures Trading Strategies
authors: [Robert Carver]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Advanced Futures Trading Strategies - Robert Carver - 原文.md
source_format: pdf_text_original_pdf_cross_checked
source_sha256: 0d69db6c9846f899f924b9a3cf29f4e4c0860487baa7187286e4c2a8c331af6c
source_line_count: 19162
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Advanced Futures Trading Strategies (Robert Carver) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_source_sha256: 4584fcfe246b0d289d0244f6633e58244784c12e57fda2041ccb3a2543a1dfcb
original_source_page_count: 700
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 34
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 45_items_verified_concept_only
last_reviewed_at: 2026-07-15
---

# STR-03：Advanced Futures Trading Strategies

## 覆盖声明

本书将 30 个策略和 4 个战术分别作为章节。本卡已依据目录、正文页首和各章 trading plan 完成全部 34 章 `L2` 语义复核，覆盖率 `34/34=100%`；源文件实际为 `19162` 行。现已直接回看 700 页原 PDF 的六个 Part、34 个 chapter bookmark 和逐章核心术语，将 S01—S30、T01—T04 共 34 项关闭为 `verified_concept_only`。Appendix B 物理页 `679-690` 又拆为 11 个计算族，并逐页核对公式、符号、估计窗口和作者限制，全部关闭为 `verified_concept_only`。这只确认定义与迁移边界，不认证书中参数、表格、回测、成本或绩效；固定 annualisation、span、blend、cap 和交易日常数均不得直接迁移。

## 全书项目映射

- `candidate_design`：统一 position management 下比较 trend、carry、cross-sectional、mean reversion、spread 和 calendar，是本项目候选族治理的有用模板。
- `existing_rule_confirmed`：Signal/Forecast 与 position sizing、组合、执行、现金、风险必须分层；策略章不能直接越过 Portfolio/Risk 与 OMS。
- `implementation_gap`：BTC 永续的 funding、mark/index、liquidation、venue fragmentation 和 24/7 calendar 与传统期货不同，需独立合同和压力测试。
- `risk_warning`：30 个策略及其变体构成高 trial count；书中回测、参数、权重和 Jumbo portfolio 不作为本项目证据。

## 策略章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| S01 Buy and hold, single contract | `493-1930` | `L2/high` | 单一期货 buy-and-hold 仍需合约选择、乘数、roll、back-adjust、spread、margin 与尾部统计；历史最优标的选择具有事后偏差，最大回撤也高度样本不稳定。 | 每类策略保留最简单 benchmark，并分离 spot beta、futures return、roll、cost 与 cash；当前规格不能用历史“最佳合约”定 universe。 | `FORM-STR03-S01-001` |
| S02 Buy and hold with risk scaling | `1931-2694` | `L2/high` | 固定风险目标把资本、预期 Sharpe 与合约风险连接到仓位，但 Kelly/效用推导依赖强假设；不可分割合约会造成最小资本和持续风险偏差。 | TargetPosition 保存 capital、target risk、price risk、multiplier、FX、min lot、rounding 和 realized-risk deviation；风险上限来自授权而非书中最优值。 | `FORM-STR03-S02-001` |
| S03 Buy and hold with variable risk scaling | `2695-3439` | `L2/high` | 滚动波动预测可降低 regime 间风险错配，但 transition、vol-of-vol、估计 lag、成本历史和短样本 SR 都会制造不确定性。 | 波动只用当时可得数据，保存 estimator/version/as-of、shock cap、stale fallback 和 entry/current risk；高换手策略需历史成本敏感性。 | `FORM-STR03-S03-001` |
| S04 Buy and hold portfolio with variable risk position sizing | `3440-4402` | `L2/high` | 多合约组合需 instrument weights、sub-strategy correlation、IDM、最低资本和成本联合决定；全样本 IDM、当前存活/流动 universe 和历史 SR 权重都会引入拟合或幸存偏差。 | 比较简单、shrinkage 和受约束组合；相关、IDM、eligibility 与 instrument addition 全部滚动/PIT，报告组合风险偏差和不可行状态。 | `FORM-STR03-S04-001` |
| S05 Slow trend following, long only | `4403-4824` | `L2/high` | 慢速 long-only filter 可在下跌期空仓；dynamic sizing 通常改善风险控制但提高调整交易，static sizing 可能保留更肥右尾也放大左尾。 | 作为 ETF/BTC spot 基线，分别比较 static/dynamic、turnover、tail 与 realized target risk；不能与可做空策略混用 mandate。 | `FORM-STR03-S05-001` |
| S06 Slow trend following, long and short | `4825-5213` | `L2/high` | 双向趋势能参与下跌并降低 sub-strategy correlation，但历史 long-only benchmark 受长期债券/权益上涨抬高；回归 alpha 只是在特定样本和线性模型下的校正。 | BTC perpetual 另计 funding、short/liquidation；美股 short 另计 borrow。beta/alpha 只作归因，不证明未来 edge 或解锁杠杆。 | `FORM-STR03-S06-001` |
| S07 Slow trend following with trend strength | `5214-5536` | `L2/high` | 将二元方向变成风险调整后的连续 forecast，需 scalar、cap 和 position mapping；单标的结果可能变差，主要价值是统一组合接口和后续多规则组合。 | Forecast 显式保存 raw/scaled/capped、direction、strength、horizon、confidence 与 calibration；书中绝对平均和 cap 数值不得迁移。 | `FORM-STR03-S07-001` |
| S08 Fast trend following with trend strength | `5537-5790` | `L2/high` | 更快 EWMAC 提高响应、turnover 与成本敏感度；forecast smoothing/buffer 可减少交易但也增加 delay，净价值取决于标的成本和信号速度。 | 按 instrument × rule 的 fee/spread/slippage/funding/impact 比较快慢规则；执行 lag 与 no-trade buffer 进入同一 trial。 | `FORM-STR03-S08-001` |
| S09 Multiple trend following rules | `5791-6674` | `L2/high` | 多速度规则先按成本排除，再按 style/rule/variation 分配并以 forecast correlation/FDM 还原尺度；名义规则数远大于有效 breadth。 | 记录 rule lineage、turnover budget、forecast weights/correlation/FDM 和边际贡献；cost cutoff、权重与 multiplier 都是待验证选择。 | `FORM-STR03-S09-001` |
| S10 Basic carry | `6675-7593` | `L2/high` | carry 由可交易合约间价格差、时间距和风险尺度构造，受 curve、storage、CTD、季节性和合约选择影响；back-adjusted price 不能直接代替真实曲线。 | BTC funding、perpetual-spot 与 dated basis 分开建模；所有 legs、expiry/funding clock、annualization、roll 和资产专用例外版本化。 | `FORM-STR03-S10-001` |
| S11 Combined carry and trend | `7594-7991` | `L2/high` | forecast 统一尺度允许组合 convergent carry 与 divergent trend，但结果对 style 权重、可交易规则集、FDM、资产数量和风险偏好敏感；60/40 只是作者选择。 | Portfolio 层组合 signal，报告冲突、相关、tail、cost-after increment 和 small-vs-large universe 差异；固定权重与历史表格禁用。 | `FORM-STR03-S11-001` |
| S12 Adjusted trend | `7992-8443` | `L2/high` | 极端 EWMAC forecast 的后续收益并非线性递增，作者用 pooled 102 instruments 检验 double-V 与 scale-and-cap；快规则尤其 EWMAC2 成本恶化，组合改善很小，作者明确认为复杂度不值得。 | 非线性映射必须 pooled、预注册并与线性基线同 trial 比较；按成本、尾部和 OOS 增量拒绝边际改进，禁止资产专属曲线拟合。 | `FORM-STR03-S12-001` |
| S13 Trend and carry in different risk regimes | `8444-8663` | `L2/high` | 相对波动以当前估计除以过去十年均值，再用历史分布分位划 regime；carry 调整无改善，trend 调整虽提高 Sharpe 却降低 skew，并错过 2008 危机趋势收益，长期波动漂移仍会污染状态。 | regime 只用当时可得状态并记录估计滞后/不确定性；危机降仓同时报告被放弃的 convex upside，阈值不得在 holdout 选择。 | `FORM-STR03-S13-001` |
| S14 Spot trend | `8664-8947` | `L2/high` | synthetic spot trend 旨在剥离 back-adjusted futures trend 中的 carry；其 Sharpe 较低、beta 较低、正偏度较高且与 carry 相关更低，组合权重改变后可改善部分归因，但资产类别权重被作者视为易过拟合。 | forecast provenance 区分 raw contract、back-adjusted、synthetic spot、index 与 mark；分别归因 price trend、roll/carry 和成本，不迁移书中固定组合权重。 | `FORM-STR03-S14-001` |
| S15 Accurate carry | `8948-9296` | `L2/high` | 季节性、长周期和固定月份 carry 修正需要同步利率、storage 与 curve 数据，但五个季节合约的小样本中复杂估计未改善结果；front/current 比较还可能与实际持有期错配。 | carry horizon 必须匹配预期 holding period，季节因子保持 PIT；关键输入缺失时 fail-closed，复杂公式无 OOS 增益则保留简单基线或放弃 carry。 | `FORM-STR03-S15-001` |
| S16 Trend and carry allocation | `9297-9607` | `L2/high` | 资产类别相对表现会被不等长历史扭曲：商品 trend 优势在共同样本消失，权益 trend 较弱但调低配置仅带来有限改善；单 instrument 样本不足，绩效费还可能改变账户曲线时序。 | allocation trial 使用共同样本、完整 trial ledger 和资产类别级候选，禁止逐标的调权；Portfolio 层管理风险，并分离 benchmark、费用和样本长度影响。 | `FORM-STR03-S16-001` |
| S17 Normalised trend | `9608-9950` | `L2/high` | 先按近期波动递归标准化价格再做 EWMAC；与原趋势相关约 0.97、换手/成本约高 25%，组合结果近乎相同，故它是高相关 challenger 而非新增独立 breadth。 | 保存 normalized-price recursion、as-of volatility、scalar 训练窗与 turnover；按边际 effective breadth 和净成本增量决定是否保留，禁止全样本归一。 | `FORM-STR03-S17-001` |
| S18 Trend following asset classes | `9951-10212` | `L2/high` | 用各合约 volatility-normalised return 构造资产类别指数，并把同一类别 forecast 分发给成员；可纳入不能交易的标的增强测量，但三类 trend 相关约 0.96、组合约 0.98，整体提升很小，有限资本账户可能受益更多。 | group index 的 universe、权重和 membership 必须 PIT；instrument/group forecast 作为高度相关来源去重，未交易成分也要通过数据质量与可得性审计，权益加权优化视为拟合候选。 | `FORM-STR03-S18-001` |
| S19 Cross-sectional momentum | `10213-10562` | `L2/high` | instrument 与 asset-class normalised price 之差生成相对价格，再按多 horizon 平滑；这只是方向 forecast，不保证市场中性。单独 Sharpe 较弱但与 carry/trend 相关低，小权重或有分散价值，作者权重本身带样本内选择。 | PIT universe、成员不足产生的零序列、lag、borrow 与成本均显式处理；净 beta/sector/venue 暴露另做 Portfolio 约束，相关性优势不能代替正向 OOS edge。 | `FORM-STR03-S19-001` |
| S20 Cross-sectional carry | `10563-10833` | `L2/high` | 对 90 日平滑 carry 减去同类资产当期中位数；中位数保证多空数量平衡但不保证平均 forecast 为零，风险取决于截面 dispersion。独立表现约为方向 carry 的一半，新增 instruments 通常比新增高相关规则更有价值。 | 同时间戳、同单位、同 expiry/funding horizon 后才能截面比较；记录 dispersion、有效成员和 residual beta，BTC 还需 venue credit/transfer/margin 风险，优先扩展可靠标的 breadth。 | `FORM-STR03-S20-001` |
| S21 Breakout | `10834-11252` | `L2/high` | forecast 由价格在 rolling min/max 区间的位置连续生成，再以 horizon/4 EWMA 平滑；短窗成本陡升，额外中性阈值会增加成本与拟合。其与 EWMAC 组合相关约 0.97，加入 trend+carry 仅有小幅改善。 | 预定义 window、price field、区间同值处理、signal lag、smooth、cost speed limit 与 gap；作为高相关 trend challenger 按净增量评估，不把名义新规则计作独立 breadth。 | `FORM-STR03-S21-001` |
| S22 Value | `11253-11454` | `L2/high` | 以 instrument 相对 asset-class 的 normalised price 做五年慢均值回归并 30 日平滑；独立组合亏损、五年 horizon 导致有效样本极少，仅因与 trend/carry 低相关而在 5% 样本内权重下略改善组合，作者承认该权重存在拟合。 | 慢锚、PIT group、warm-up 和结构突变显式化；低相关亏损策略只能是受限 challenger，权重预注册并用 OOS/压力测试验证，不能以组合 Sharpe 微增掩盖独立负 edge。 | `FORM-STR03-S22-001` |
| S23 Acceleration | `11455-11770` | `L2/high` | acceleration 是已缩放 EWMAC forecast 在快均线 span 内的变化率；最快两档成本不可接受，保留四档。其与趋势相关低于 0.76、跨档分散较强，但单标的 Sharpe 仅 0.08、组合成本高，加入 trend+carry 后才有小幅改善。 | 保存 parent forecast lineage、difference horizon、二次 scalar、turnover 与 cost；作为独立增量 trial 检验在原趋势、执行延迟和净成本后是否仍含信息，不能从同源衍生规则重复计算 breadth。 | `FORM-STR03-S23-001` |
| S24 Skew – A case study | `11771-12422` | `L2/high` | 该章给出通用 strategy-to-forecast 流程：先有可解释收益机制，再选可量化且对噪声稳健的统计、明确 absolute/demeaned/relative/cross-sectional 形式、风险尺度、scalar/cap、成本和组合贡献。skew 对少数 outlier 敏感，短窗产生更负尾部；组合改善伴随 beta 上升和正偏度下降。 | 策略卡必须记录机制、输入扰动测试、forecast 类型、PIT 去均值、trial family、成本、beta/skew/tail 与失效状态；calendar/cross-market 大搜索空间默认多重检验高风险。 | `FORM-STR03-S24-001` |
| S25 Dynamic optimisation | `12423-13323` | `L2/high` | 每日用 greedy integer search 最小化离散持仓对未取整最优组合的 covariance tracking error，再加交易成本 penalty 和组合 tracking-error buffer；它可让小资本近似大组合，但不是全局最优，书中 cost penalty 50 和 buffer 1% 经样本校准。 | 位于 TargetPosition→OrderIntent 之间，输入仅未取整目标、PIT covariance、cost、当前仓位和硬约束；需 deterministic tie-break、tracking-error/cost 分解、rounding replay、敏感性和不可行状态，禁止把作者参数视为默认值。 | `FORM-STR03-S25-001` |
| S26 Fast mean reversion | `13326-13988` | `L2/high` | 用前一日可得的五日 EWMA equilibrium 与小时价偏离构造 forecast，不使用 buffer，并以相邻一手 limit ladder 降成本、gap 时用 market order 回到最优仓位。证据仅始于 2013，回测假设触价后一小时按 limit 成交，且容量、队列、冲击和负偏尾部非常关键。 | `rejected_for_now`：无合格 intraday/quote/L2/fill、session calendar、queue/partial-fill、latency、gap 与 capacity 模型前不得进入 promotion；fast 与 daily 策略需独立执行适配器和 ledger attribution。 | `FORM-STR03-S26-001` |
| S27 Safer fast mean reversion | `13989-14326` | `L2/high` | 仅在 EWMAC16 trend 与 mean-reversion 同号时交易，并用过去十年相对波动的历史分位 multiplier 降低高波动仓位；这改善样本 Sharpe/skew，但扩大部分 tail，vol overlay 是后加功能且仍依赖短历史和自动化执行。 | `research_only`：overlay 作为已登记增量 trial，状态必须 PIT；报告被过滤交易、危机表现、二次 scalar、tail/turnover/capacity，任何订单异常或监控缺失 fail-closed。 | `FORM-STR03-S27-001` |
| S28 Cross instrument spreads | `14327-15340` | `L2/high` | 两腿 synthetic price 可为零或负，风险用价格差波动而非百分比；高相关压低表观波动并放大杠杆，相关从 0.961 降到 0.86 即可令示例风险近翻倍。trend spread 较分散但 lower tail/成本较高，carry spread 基本无 edge，异步 roll 会扭曲 carry。 | 先验证 hedge ratio、相关 shock、gross leverage、min capital、双腿成本/roll/FX/margin 和 simultaneous-fill；单腿暴露必须有限额、超时补救与 ledger，低相关不能掩盖零或负独立 edge。 | `FORM-STR03-S28-001` |
| S29 Cross instrument triplets | `15341-15723` | `L2/high` | 三腿 butterfly 用两翼对冲中间腿，hedge ratios 依赖各腿波动/相关并受整数合约放大；比 spread 杠杆、成本、最低资本和 tail 更差。仅三个案例中除 oil crack 外表现弱且常与底层高度相关，快速均值回归还要求三腿近同步限价成交。 | `rejected_for_now`：两腿 atomicity、补救、capacity 与账本成熟前不实施；若研究，所有 ratio、rounding、gross/net exposure、三腿 fill sequence 和 correlation-break stress 必须可重放。 | `FORM-STR03-S29-001` |
| S30 Calendar trading strategies | `15724-16314` | `L2/high` | 同一标的不同 expiry 的 spread/triplet 分别交易曲线 slope/convexity；市场惯例 R=1、X=Y=0.5 便于组合报价但未必风险最优，所有 legs 必须同步 roll。曲线长期均值回归又会在危机跳到新 equilibrium，导致高杠杆、肥尾和 trend 的期权式收益。 | `concept_only`：可映射 BTC dated/perpetual basis，但需独立 expiry/funding clock、term-vol、同步 roll、multi-leg margin/fill 与 regime-shift stress；书中样本结果不支持直接实现或 promotion。 | `FORM-STR03-S30-001` |

## 战术章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| T01 Contract selection and rolling | `16319-16897` | `L2/high` | expiry 选择同时受 liquidity/risk/tail/seasonality/carry 可计算性、delivery 和 roll frequency 约束；front contract 可能最液态却具 jump/delivery 风险。passive roll、natural close 或 spread roll 各有 basis、空仓/双仓和成本权衡，RV legs 必须协调。 | contract resolver 保存 eligibility、volume/risk threshold、delivery type、roll decision/as-of 和各腿映射；research continuous series、实际持仓/成交与 roll ledger 分离，临近实物交割默认 fail-closed。 | `FORM-STR03-T01-001` |
| T02 Execution | `16898-17299` | `L2/high` | execution 需同时记录 sampled spread、submission-time spread 和 realised mid-to-fill；交易时间、size/ADV、L2、impact 与 algo passive/aggressive 状态决定真实成本。algo 节省平均 spread 的同时呈负偏尾部，overnight limit ladder 还暴露 gap 和信息泄露。 | OMS 只消费 OrderIntent；保存 arrival/mid/order-book/fill、size、latency、cancel/replace、partial fill 和 algo state，按 fill ledger 归因。容量与成本函数使用实际数据，异常时段和 overnight orders 有硬 guard。 | `FORM-STR03-T02-001` |
| T03 Cash and compounding | `17300-17766` | `L2/high` | initial/variation margin 从 free cash 分离，多币种 margin 可由 FX trade 或 borrowing 支持；闲置现金追求收益会引入额外风险和流动性错配。固定资本在亏损后不降仓可导致破产，full/half compounding 都要求亏损时同步降低 notional capital。 | cash、segregated margin、variation margin、FX balance/loan、interest、withdrawal/high-watermark 与 position PnL 分账；capital base 变更进入 sizing lineage，现金/汇率/保证金不足或 stale 一律 fail-closed。 | `FORM-STR03-T03-001` |
| T04 Risk management | `17767-18471` | `L2/high` | 风险 overlay 取 estimated portfolio、jump/non-stationary、correlation-shock 与 leverage multipliers 的最小值，只能降仓；另以 margin、max-forecast、single-instrument leverage、open interest、position/trade limits 控制市场与操作风险。书中 99% 分位和阈值是样本化选择。 | Risk 独立于 strategy，基于 PIT covariance/tail/liquidity/margin 先缩未取整目标，再施加硬仓位/交易限额；bad data、超限、异常频率、手工 override 全审计并 fail-closed，阈值须授权和压力验证。 | `FORM-STR03-T04-001` |

## 附录边界

- Appendix B `18553-18861`、PDF 物理页 `679-690`：已拆为以下 11 个计算族，均直接回看原 PDF 并关闭为 `verified_concept_only`。

| 公式 ID | PDF 物理页 | 原式/规则语义 | 项目迁移与测试边界 |
|---|---:|---|---|
| `FORM-STR03-APP-B-001` | `679-683` | roll 日以新旧合约价差递归平移历史序列；新增 roll 时把价差施加到既有 back-adjusted history。 | 连续研究价与真实合约/成交/roll ledger 分离；固定 roll calendar、同日双价可得性、价差方向、缺口和无未来 fixture 必测，调整价不得用于现金 PnL。 |
| `FORM-STR03-APP-B-002` | `684-685` | 期货百分比收益以 back-adjusted 价格差除以当时实际持有合约价；负价时先估 price-risk，再用一致的正参考价换算 percentage-risk。 | 分母必须是 as-of held-contract price；零/负价、换月、合约乘数、FX 和参考价 provenance 必测，任意正参考价不能成为隐含自由参数。 |
| `FORM-STR03-APP-B-003` | `684-686` | 等权均值与总体型标准差用于日收益风险，书中以 `16≈√256` 年化。 | 明确样本/总体分母、收益时钟、缺失值和 serial dependence；项目 annualisation 由真实 calendar/frequency 配置，常数 16/256 禁止硬编码。 |
| `FORM-STR03-APP-B-004` | `684-686` | EWMA 均值和标准差以衰减参数递归加权，span 映射为 `λ=2/(N+1)`。 | 只用当时可得收益；保存 span/alpha convention、warm-up、min periods、lag、NaN、shock 和重启状态，32 日只是作者选择。 |
| `FORM-STR03-APP-B-005` | `684-686` | 当前波动与十年慢均值按 `0.7/0.3` 混合以降低估计漂移。 | 慢均值必须滚动/PIT且有冷启动与 stale fallback；十年、0.7/0.3 均登记为 trial，不作默认参数。 |
| `FORM-STR03-APP-B-006` | `687` | instrument correlation 用周收益，forecast correlation 用 forecast 值；负相关截零，回测中逐年用当时历史更新，forecast 可跨标的 pooled stacking。 | 明确 clock/alignment、PIT window、pairwise missing、shrinkage/PSD、pool membership 与 effective sample；截零和年度更新均须 challenger 对照。 |
| `FORM-STR03-APP-B-007` | `687-688` | covariance 由波动向量与相关矩阵组合；作者用约六个月 correlation span、32 日 volatility span，jump risk 以历史 99% 波动分位替代当前波动。 | 单位、矩阵维度、PSD、as-of、不同 half-life、相关跃升与 percentile 样本必须测试；99%、25/52 周和 32 日均禁直接迁移。 |
| `FORM-STR03-APP-B-008` | `688-689` | forecast turnover 为逐日 scaled forecast 绝对变化相对目标绝对 forecast 的均值再年化。 | 保存 signal timestamp、缺失交易日、目标尺度、跨标的 aggregation 与 cost linkage；`256` 和分母 `10` 仅属作者 convention。 |
| `FORM-STR03-APP-B-009` | `689` | position turnover 为逐日合约变化绝对值除以 forecast `+10` 对应平均持仓，再年化。 | 使用未取整目标还是实际 fill-derived position 必须分别报告；零分母、min lot、roll trade、FX 与 calendar 必测，不能以 turnover 代替真实成本。 |
| `FORM-STR03-APP-B-010` | `689` | `FDM=1/sqrt(wρwᵀ)`，forecast correlation 负值先截零，作者 cap 为 2，并建议年度 PIT 更新后做约 30 日 EWMA。 | 权重和相关必须同一 rule set/as-of；矩阵 PSD、近奇异、cap、平滑、pooling 和effective breadth 必测，FDM 不得创造风险预算。 |
| `FORM-STR03-APP-B-011` | `690` | `IDM=1/sqrt(wρwᵀ)`，输入为 instrument sub-strategy return correlation；负值截零，作者 cap 为 2.5，并建议年度更新和约 30 日 EWMA。 | PIT universe/weights/correlation、退市与新增标的、矩阵稳定、cap 和 realized target-risk deviation 必测；IDM 只能缩放既有授权风险，不能解锁杠杆。 |

- Appendix C `18862` 起：Jumbo portfolio 合约清单仅作历史 universe 示例，不是当前可交易清单。

## L3 原始 PDF 复核结论

- Part One：S01 `22-67`、S02 `68-94`、S03 `95-119`、S04 `120-149`、S05 `150-164`、S06 `165-178`、S07 `179-191`、S08 `192-202`、S09 `203-233`、S10 `234-265`、S11 `266-279`，对应 11 项均为 `verified_concept_only`。
- Part Two：S12 `280-297`、S13 `298-307`、S14 `308-317`、S15 `318-331`、S16 `332-343`、S17 `344-355`、S18 `356-366`、S19 `367-378`、S20 `379-389`，对应 9 项均为 `verified_concept_only`。
- Part Three：S21 `390-404`、S22 `405-411`、S23 `412-422`、S24 `423-444`、S25 `445-476`，对应 5 项均为 `verified_concept_only`。
- Part Four：S26 `477-499`、S27 `500-513`，对应 2 项均为 `verified_concept_only`，但小时执行仍保持 `research_only`。
- Part Five：S28 `514-552`、S29 `553-570`、S30 `571-595`，对应 3 项均为 `verified_concept_only`，三腿实现仍为 `rejected_for_now`。
- Part Six：T01 `596-613`、T02 `614-626`、T03 `627-645`、T04 `646-669`，对应 4 项均为 `verified_concept_only`，不授权任何交易端点。
- Appendix B：物理页 `679-690` 的 back-adjust、return denominator、simple/EWMA/blended volatility、correlation、covariance、forecast/position turnover、FDM 和 IDM 共 11 项均为 `verified_concept_only`；固定常数和参数不迁移。
- 单书完成边界：34 个策略/战术条目与 11 个 Appendix B 计算族均已完成 L2/L3 概念核验，故本书计入 complete；这不等于当前实现、回测、执行或 promotion 通过。
