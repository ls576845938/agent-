---
book_id: STR-02
title: Following the Trend
authors: [Andreas Clenow]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Following the Trend - Andreas Clenow - 原文.md
source_format: epub_text_original_epub_cross_checked
source_sha256: b8311c0bf7e46c46b53d1afa219deb3e6e72ca14de3561e760e2a406ca46f757
source_line_count: 9126
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\Following the Trend (Andreas F. Clenow) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_source_sha256: 9fce783bb3c3d155352b50a20170921296344ac715e8b10d16fcb2928522f660
original_source_chapter_files: 10
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 10
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
annual_event_review_count: 22
annual_event_review_coverage_pct: 100
formula_review_status: 50_ch01_ch10_items_verified_concept_only
last_reviewed_at: 2026-07-15
---

# STR-02：Following the Trend

## 覆盖声明

本卡按正文逐段复核 10/10 章，并将第 6 章 1990—2011 年 22 个年度案例分别登记为事件证据。正文止于 `7608`，`7609` 起为参考文献；目录、表格重复年份和索引不计入章节边界。现已直接核对原 EPUB 的 OPF spine、`OEBPS/9781118410844_epub_ch_01.htm`—`ch_10.htm`、章名和全部一级/二级小节，将连续期货、ATR sizing、stop、相关风险、资本门槛、费用和执行共 50 项关闭为 `verified_concept_only`。该状态仅确认概念、公式主题和迁移边界，不认证书中历史参数、表格、基金表现或当前实现。

## L3 原始 EPUB 复核结论

| 章 | 原 EPUB 文件 | 已核小节簇 | 队列状态 |
|---|---|---|---|
| Ch01 | `OEBPS/9781118410844_epub_ch_01.htm` | diversified trend、traditional investment、managed futures、criticism、business、volatility、subscriptions/redemptions | `FORM-STR02-CH01-001`—`005` 均为 `verified_concept_only` |
| Ch02 | `OEBPS/9781118410844_epub_ch_02.htm` | futures asset class/exchanges/FX、limited life、term structure、basis gaps、sectors、tools/data | `FORM-STR02-CH02-001`—`005` 均为 `verified_concept_only` |
| Ch03 | `OEBPS/9781118410844_epub_ch_03.htm` | universe、position sizing、cost、cash interest、strategy anatomy | `FORM-STR02-CH03-001`—`005` 均为 `verified_concept_only` |
| Ch04 | `OEBPS/9781118410844_epub_ch_04.htm` | performance/correlation、parameter stability、trend filter、stop、risk level、core rules | `FORM-STR02-CH04-001`—`005` 均为 `verified_concept_only` |
| Ch05 | `OEBPS/9781118410844_epub_ch_05.htm` | behaviour、equity complement、direction、sector、cash、leverage | `FORM-STR02-CH05-001`—`005` 均为 `verified_concept_only` |
| Ch06 | `OEBPS/9781118410844_epub_ch_06.htm` | reading protocol、1990—2011、year-by-year conclusions | `FORM-STR02-CH06-001`—`005` 均为 `verified_concept_only` |
| Ch07 | `OEBPS/9781118410844_epub_ch_07.htm` | universes、comparison、fund replication、conclusions | `FORM-STR02-CH07-001`—`005` 均为 `verified_concept_only` |
| Ch08 | `OEBPS/9781118410844_epub_ch_08.htm` | multiple time frames、synthetic contracts、counter-trend、intraday stops、correlation/risk、roll、optimisation | `FORM-STR02-CH08-001`—`005` 均为 `verified_concept_only` |
| Ch09 | `OEBPS/9781118410844_epub_ch_09.htm` | required assets、going live、execution、cash、drawdown volatility、monitoring/follow-up | `FORM-STR02-CH09-001`—`005` 均为 `verified_concept_only` |
| Ch10 | `OEBPS/9781118410844_epub_ch_10.htm` | diminishing returns、crowding/soup bowl、initial risk | `FORM-STR02-CH10-001`—`005` 均为 `verified_concept_only` |

## 全书项目结论

- `existing_rule_confirmed`：趋势策略的可解释优势不在神秘入场指标，而在广泛机会集、波动率归一、组合风险、成本与持续执行；Strategy 仍只能输出 forecast/target，不得越过 Portfolio/Risk 和 OMS。
- `existing_rule_confirmed`：少数大赢家支付多数小亏损，必须报告收益集中度、方向/行业/事件归因、回撤路径、gap、相关跃升和交易成本，胜率与长期 CAGR 都不能单独支持 promotion。
- `candidate_design`：BTC 可用多周期趋势作为候选 forecast，但单 BTC 的时间尺度并不等于跨资产 breadth；不同周期、venue 或高度相关合约必须先做依赖修正。
- `candidate_design`：美股系统可将指数/行业 ETF 趋势作为独立候选，但股票数量不等于分散；压力期 equity beta、共同美元/利率主题和相关收敛必须由 Portfolio/Risk 聚合。
- `implementation_gap`：未来期货研究需要 contract chain、主力选择、研究调整价、真实成交价、roll event、合约乘数、币种、margin 与 roll PnL 分离合同。
- `implementation_gap`：组合风险不能停留在逐仓 ATR；需要当前持仓尺度、波动漂移、方向不对称、动态相关、主题集中和 gap/limit/margin stress。
- `risk_warning`：书中 10/100 均线、50/25 突破、100 日 ATR、20bp risk factor、3 ATR stop、资产池、费用和历史基金数字全部只作待复核结构，不是当前参数、风险限额或实盘证据。
- `risk_warning`：1990—2011 事件解释均为事后叙事，只能用于 replay/stress 场景设计，不得反向改写当期信号或形成 promotion 结论。

## L2 逐章项目结论

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Cross-Asset Trend Following with Futures | `474-706` | `L2/high` | 趋势只在持续价格运动中获利，单市场长期震荡会连续止损；分散、双向和小单笔风险使少数右尾交易覆盖多数亏损。基金经营还引入申赎、不可分割仓位、客户路径和纪律风险。 | BTC 单标的不得宣称跨资产 CTA 分散；报告 trade hit-rate、payoff、top contributors、investor-entry path 和 override policy。 | `FORM-STR02-CH01-001`—`005` |
| 2 Futures Data and Tools | `707-1231` | `L2/high` | 期货具有到期、逐日盯市、主力迁移、term structure、basis gap、点值/币种和交割风险；连续研究序列可以保留趋势但不是历史真实成交价。 | 建立 contract-chain/roll/metadata/P&L 数据合同；research adjusted series、actual tradable price 和 cash/FX ledger 不得混用。 | `FORM-STR02-CH02-001`—`005` |
| 3 Constructing Diversified Futures Trading Strategies | `1232-1430` | `L2/high` | 主要差异来自 universe、position sizing、horizon、risk level 和多模型，而非复杂入场；ATR sizing 只是让不同合约获得近似共同风险尺度。 | Forecast 与 target position 分层；target 保存 equity、risk budget、ATR、point value、FX、min lot、rounding 和 stale-vol blocker。 | `FORM-STR02-CH03-001`—`005` |
| 4 Two Basic Trend-Following Strategies | `1431-1828` | `L2/high` | 简单 MA 与 breakout 可作为基线；信号必须下一可交易时点执行。趋势过滤和波动 stop 改变路径，risk factor 改变整体尺度；参数应看宽邻域而非历史最优点。 | BTC 趋势研究以简单基线和预注册邻域比较；明确 signal/fill lag、EOD/intraday stop、gap、cost 和 trial budget。 | `FORM-STR02-CH04-001`—`005` |
| 5 In-Depth Analysis of Trend-Following Performance | `1829-2092` | `L2/high` | 交易分布右偏、盈利持有期更长；short 侧独立收益弱但可能在危机中降低组合相关。行业贡献、现金收益、费用与 notional leverage 必须拆开解释。 | 研究报告增加 long/short、sector/venue、top-tail、holding period、cash/funding、fees、notional、margin 和 cost-to-stop attribution。 | `FORM-STR02-CH05-001`—`005` |
| 6 Year by Year Review | `2093-7017` | `L2/high` | 22 年回放证明长期曲线掩盖启动时点、连续亏损、利润回吐、相关聚集、事件 gap 和客户行为；同一规则在不同年份由完全不同方向和行业驱动。 | 为 BTC/美股建立冻结输入的 event replay、worst-path 和 start-date cohort；宏观故事只作事后归因，不进入信号。 | `FORM-STR02-CH06-001`—`005`；见年度表 |
| 7 Reverse Engineering the Competition | `7018-7241` | `L2/high` | 产品相似度可由 universe、risk scale 和 horizon 三个维度近似；相关拟合只能说明共同暴露，不能证明策略身份、因果或未来收益。 | 做 forecast/position/factor/return exposure 相似度与重复 alpha 审计；复制研究必须固定候选维度并惩罚选择自由度。 | `FORM-STR02-CH07-001`—`005` |
| 8 Tweaks and Improvements | `7242-7406` | `L2/high` | 多周期、价差、反趋势、intraday failsafe、动态相关和 roll timing 都可改变路径；核心缺陷是逐仓风险忽略主题相关、持仓尺度和波动漂移。 | 每个 tweak 独立登记 trial；Portfolio/Risk 使用动态相关/主题压力和 current exposure，不把多个周期机械计为 breadth。 | `FORM-STR02-CH08-001`—`005` |
| 9 Practicalities of Futures Trading | `7407-7541` | `L2/high` | 不可分割合约形成最小资本和 rounding 约束；启动仓位、全球时区执行、逐日盯市、多币种现金、费用高水位与实盘—模拟偏差都需独立运行合同。 | min-contract feasibility、startup reconciliation、execution schedule、FX/cash ledger、margin buffer 与 daily expected-vs-realized diff 必须 fail-closed。 | `FORM-STR02-CH09-001`—`005` |
| 10 Final Words of Caution | `7542-7608` | `L2/high` | 历史收益含利息环境，市场拥挤和急反转可能压低未来收益；真实最大回撤可能超过模拟且可能在上线后立即发生，首要目标是生存。 | 风险预算不能由历史 CAGR 倒推；压力包包括 crowding、gap、相关跃升、launch timing、资金流失和低收益环境。 | `FORM-STR02-CH10-001`—`005` |

## 第 6 章年度事件覆盖

| 年份 | 原文位置 | 等级/可信度 | 主要路径与归因 | 对项目的可复核启发 |
|---|---|---|---|---|
| 1990 | `2132-2371` | `L2/high` | 海湾战争前已有能源多头，事件放大利润；利率、农业空头和货币贡献明显，但年内高点后大幅回吐。 | 事件收益必须区分事前持仓与事后解释；保存 peak-to-year-end giveback 和投资者入场 cohort。 |
| 1991 | `2372-2536` | `L2/high` | 前三季度近乎停滞，年末长久期利率趋势带来主要收益；苏联政变本身对策略影响有限。 | 长时间无收益不是参数失效证据；禁止因短期 boredom 调参。 |
| 1992 | `2537-2782` | `L2/high` | 年初多主题反转与连续止损，年中反弹后再次回吐；不同地区股票分化提供分散，全年仅小幅正收益。 | 报告 stop cascade、position-count contraction 和地区相关变化，而非只看年度正负。 |
| 1993 | `2783-2963` | `L2/high` | 农产品长侧与部分利率主导，权益贡献很小；8 月金属/能源同步反转造成单日行业冲击。 | 组合盈利与股市同涨不等于 equity beta；做 sector shock 与 near-stop replay。 |
| 1994 | `2964-3204` | `L2/high` | 多行业假突破、长侧和权益/非农商品持续亏损，形成全期最差年度之一。 | 必须保留 bad-regime 证据和连续假突破统计；不得删除亏损市场美化结果。 |
| 1995 | `3205-3364` | `L2/high` | 主要收益几乎全部来自利率多头，并依靠高水位后才计提业绩费。 | 单一行业贡献率和 fee/high-watermark 必须分列，避免把集中暴露当稳定 alpha。 |
| 1996 | `3365-3603` | `L2/high` | 年初深亏、商品反弹、再次回撤，年末由商品、利率和权益共同修复；大赢家后仍显著回吐。 | 需要 path-aware drawdown/giveback 和多阶段 attribution，不以全年正收益遮盖过程风险。 |
| 1997 | `3604-3793` | `L2/high` | 两次利润全部回吐并转负，最后由美元主题与商品修复；风险报酬体验很差。 | 同年多次 peak-to-trough 应进入压力指标；现金利息贡献不得混为交易 alpha。 |
| 1998 | `3794-4013` | `L2/high` | 俄债/LTCM 危机环境下商品空头等持续趋势带来极高收益，但期间多次两位数回吐。 | 极佳年度也需评估 counterparty、giveback 和 concentration，不可据此提高风险。 |
| 1999 | `4014-4238` | `L2/high` | 科技泡沫并未全年提供平滑趋势，多个行业震荡；年末权益趋势才把结果拉回小幅正值。 | 热门叙事不等于可交易趋势；按月/日检查 whipsaw 和 benchmark-relative client pressure。 |
| 2000 | `4239-4493` | `L2/high` | 高风险权益多头先重创，随后商品、货币和利率修复；权益多空两侧全年均亏。 | 高内部相关行业必须设主题预算；方向双向并不自动消除 sector beta。 |
| 2001 | `4494-4756` | `L2/high` | 长期平淡后，利率多头与权益空头在危机阶段爆发；年末反转产生 gap 与利润回吐。 | 收益集中于短窗口时报告 burst concentration、corner portfolio 和 EOD stop gap。 |
| 2002 | `4757-4896` | `L2/high` | 年初仓位很少且回撤，后由利率多头、美元空头和权益空头快速修复，再经历大幅回吐。 | 低仓位状态的恢复等待期和重新建仓 lag 应进入 launch/restart 测试。 |
| 2003 | `4897-5182` | `L2/high` | 年初高度集中的熊市/弱美元主题同步获利，3 月风险偏好反转导致跨行业同时回吐，全年仍由货币主导。 | “多仓位”可能是一笔宏观主题；需要 latent-theme/cluster exposure 与 reversal stress。 |
| 2004 | `5183-5434` | `L2/high` | 由双位数盈利跌至近双位数亏损，最终仅能源/金属修复；年度收益不足补偿波动。 | 报告 ulcer/path volatility 和 client-experience，不以正收益自动判定可接受。 |
| 2005 | `5435-5679` | `L2/high` | 年初权益相关冲击、全年反复深亏，年末权益/利率/商品修复至小幅盈利；美元空头失败。 | 股票地区数量不等于分散；分离交易收益、利息和费用后再评价策略。 |
| 2006 | `5680-5917` | `L2/high` | 金属与商品推动至高点，权益/利率相关反转造成约 30 个百分点回吐，后再次修复。 | 相关性在盈利期也会累积；current—not entry—risk 和 correlated giveback 必须持续重算。 |
| 2007 | `5918-6157` | `L2/high` | 中国市场急跌使权益多头同日止损，恢复后再次相关回撤；最终由农产品和其他商品挽救。 | 需要 global-session gap、stop synchronization、re-entry lag 和 sector rescue concentration。 |
| 2008 | `6158-6360` | `L2/high` | 金融危机中利率多头、商品/美元主题贡献巨大，权益空头反而因暴烈反弹亏损；单日波动和对手方风险异常。 | 危机 stress 必须同时覆盖 broker/cash、相关反转、vol override 规则和安全降风险；不据极端年推高杠杆。 |
| 2009 | `6361-6593` | `L2/high` | 危机后趋势消失，美元主题与商品反复止损，全年亏损且现金利息保护消失。 | 极端盈利后立即坏年是 launch-timing 基准；连续同市场亏损也不能选择性跳过信号。 |
| 2010 | `6594-6790` | `L2/high` | 商品趋势带来快速盈利，权益/商品相关上升后大幅回吐；逐仓 sizing 未识别组合主题风险。 | 动态相关、cluster risk 和 portfolio-level cap 是明确实现缺口。 |
| 2011 | `6791-7017` | `L2/high` | 日本灾害、能源 margin 上调、欧债危机和急反转造成 gap、止损延迟与仓位骤减；仅利率最终盈利。 | margin shock、EOD-stop breach、position-count collapse 和跨行业相关一并进入 replay。 |

## 与当前架构的可执行映射

### BTC

- 将趋势规则限制为 `ForecastEvidence` 候选，记录 horizon、direction、strength、expiry、source bars 和 warmup；不得直接生成订单。
- 多周期组合先估 forecast correlation、effective breadth 和共同回撤；同一 BTC 的 20/50/100 日版本不能机械当三条独立 alpha。
- `TargetPositionEvidence` 显式保存 vol estimate、risk budget、price/contract unit、rounding、current exposure、stress correlation 和 blocked reason。
- event replay 至少覆盖 gap、flash move、funding/basis 反转、venue outage、stale price、流动性坍塌和相关跃升；本卡不授权运行新回测。

### US Equity

- universe 需 PIT、可交易且保存成分版本；指数/行业 ETF 数量不等于分散，压力期共同 equity beta 必须聚合。
- 趋势 forecast 与 stock selection forecast 分开归因，避免行业/市场趋势重复计为多个 alpha。
- short-side 研究另行包含 borrow/locate、recall、gap、limit、corporate action 和成本合同；书中期货对称多空不能直接迁移。
- start-date cohort、sector attribution、top contributors 和 event replay 应进入研究 evidence，但不因此形成 promotion 结论。

## 使用限制

- 本卡完成的是原文语义覆盖，不证明本项目当前 BTC、美股或未来期货策略有效、可交易或 ready。
- 书中数据止于 2011/2012 左右，基金、利率、市场结构、产品和软件描述均可能过时，只作历史案例。
- 50 个公式/数量条目均已回看原 EPUB 并关闭为 `verified_concept_only`；这不授权迁移窗口、阈值、风险比例、资本门槛、费用或收益数字。
- 第 6 章事件表只生成可复核压力场景，不允许查看或污染 holdout，也不允许用事后事件选择参数。
