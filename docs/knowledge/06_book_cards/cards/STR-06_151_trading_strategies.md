---
book_id: STR-06
title: 151 Trading Strategies
authors: [Zura Kakushadze, Juan Andres Serur]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\151 Trading Strategies - Zura Kakushadze and Juan Andres Serur - 原文.md
source_format: epub_text_repaired_original_local_headers_cross_checked
source_sha256: 2982d19d258200d94ff1c3df3a1a268d9d00ff41013a44b073fd18e332e1bbcf
source_line_count: 45112
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\151 Trading Strategies (Zura Kakushadze, Juan Andrés Serur) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_source_sha256: 59eb6d9efd70356e8cae3704c62f42f30c076446af09d9324812a091a83f1bcc
original_source_recovery: local_header_scan_2252_entries
original_source_chapter_files_recovered: 20
formal_strategy_heading_count: 151
variant_strategy_heading_count: 21
card_status: complete_l2_l3_items_verified_concept_only_source_recovered
chapter_count: 20
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 20_chapter_items_verified_concept_only_151_formal_strategy_catalog_verified
last_reviewed_at: 2026-07-15
---

# STR-06：151 Trading Strategies

## 覆盖声明

本卡依据修复后 EPUB 的 20 个独立 chapter item、目录链接和正文边界完成 20/20 章 `L1` 与 `L2` 策略定义精读，覆盖率 100%。本轮直接扫描损坏原 EPUB 的 2,252 个 ZIP local headers，成功恢复 `OEBPS/html/472911_1_En_1_Chapter.xhtml`—`20_Chapter.xhtml`；按“章节号.条目号 Strategy:”统计得到正式编号 151 项，另有 21 个未编号变体标题。20 个章节级公式/策略族条目据此关闭为 `verified_concept_only`。这只确认目录、定义、资产族和迁移边界，不认证任何公式图、参数、payoff、表格、回测或可实施性。

## L3 原始 EPUB 恢复复核结论

| 章 | 正式编号策略数 | 未编号变体数 | 原 EPUB 文件 | 队列状态 |
|---|---:|---:|---|---|
| Ch01 | 0 | 0 | `OEBPS/html/472911_1_En_1_Chapter.xhtml` | 证据边界条目 `verified_concept_only` |
| Ch02 | 56 | 2 | `OEBPS/html/472911_1_En_2_Chapter.xhtml` | options 目录已核；实现仍 blocked |
| Ch03 | 18 | 1 | `OEBPS/html/472911_1_En_3_Chapter.xhtml` | stocks 目录已核；仅少数候选可另立研究票据 |
| Ch04—10 | 44 | 10 | `OEBPS/html/472911_1_En_4_Chapter.xhtml`—`10_Chapter.xhtml` | ETF/fixed income/index/vol/FX/commodities/futures 七项均 `verified_concept_only` |
| Ch11—17 | 27 | 8 | `OEBPS/html/472911_1_En_11_Chapter.xhtml`—`17_Chapter.xhtml` | structured/convertible/tax/misc/distressed/real-estate/cash 七项均已核；blocked/rejected边界保持 |
| Ch18—20 | 6 | 0 | `OEBPS/html/472911_1_En_18_Chapter.xhtml`—`20_Chapter.xhtml` | crypto/macro/infrastructure 三项均已核；research-only/out-of-scope保持 |
| **合计** | **151** | **21** | 20 个 chapter XHTML | 20 个章节级队列项均为 `verified_concept_only` |

## 全书项目映射

- `candidate_library`：只把条目当作研究问题索引；每个候选需另写经济机制、PIT 数据、执行约束、trial budget 和 falsification。
- `risk_warning`：151 个条目构成极高多重试验风险，不能批量实现、批量回测或按书中结果筛选。
- `scope_boundary`：本项目近期相关的是 stocks、ETF、indexes、volatility、futures、cryptocurrencies、global macro 和 cash/liquidity 的少数条目。
- `rejected`：违法、不道德或超出系统资产/权限边界的活动（如洗钱、loan sharking）明确拒绝；复杂信用/税务/实物资产策略只作概念。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Introduction and Summary | `1490-1618` | `L2/high` | 将策略定义为在预定时间达到持仓目标的一组指令；对冲可不具独立盈利目标，但有成本。作者明确本书没有数值模拟、回测或实证研究，且市场结构变化会令策略失效。 | `existing_rule_confirmed`：目录与参考文献只能触发独立研究票据，不能形成 candidate/promotion evidence；弱而短暂的信号必须先过成本、稳定性和多重试验约束。 | `FORM-STR06-CH01-001`；151条目录完整性待L3 |
| 2 Options | `1619-3553` | `L2/high` | 56 个编号策略覆盖 covered/protective、vertical/calendar/diagonal、straddle/strangle/guts、ratio、butterfly/condor/iron、box、collar 和 seagull；本质是重组方向、波动、期限、尾部及行权风险。 | `rejected_for_now`：项目尚无 options master、surface/greeks、exercise/assignment、borrow/margin 和多腿 fill/ledger 合同，不进入实现或回测。 | `FORM-STR06-CH02-001`；payoff/盈亏平衡/Greeks待L3 |
| 3 Stocks | `3554-6080` | `L2/high` | 20 个股票策略族覆盖 price/earnings/residual momentum、value、low-vol、implied vol、多因子、pairs/cluster regression、均线/channel、M&A、KNN/stat-arb、market making 和 alpha combo。每类使用不同信息时钟、执行和风险；大量 faint/ephemeral alpha 的纸面利润可能被成本吞噬。 | `candidate_library`：近期只保留 PIT price/earnings momentum、value、low-vol、factor attribution 与简单均线/channel 基线；M&A、options-implied、market making、intraday/stat-arb 保持 blocked。 | `FORM-STR06-CH03-001`；逐条公式/样本待L3 |
| 4 Exchange-Traded Funds | `6081-6731` | `L2/high` | sector/alpha rotation、dual momentum、R²、IBS mean reversion、LETF pair 与 multi-asset trend 分别依赖回看期、回归、OHLC、日重置路径和风险权重。LETF 双空暴露短期尾部，忽略相关的对角协方差权重不等于组合最优。 | `candidate_design`：仅 sector/dual momentum 和简单趋势进入美股 ETF challenger；必须 PIT universe、真实交易日、T+1、分红、费用、borrow、全成本和压力相关。 | `FORM-STR06-CH04-001`；LETF/IBS不进入近期实现 |
| 5 Fixed Income | `6732-7945` | `L2/high` | 从零息、固定息和浮息现金流进入 duration/convexity；bullet、barbell、ladder 和 immunization 管理期限风险，butterfly、低风险/value/carry、roll-down、steepener/flattener、CDS basis 与 swap spread 再引入曲线、信用、融资及多腿风险。 | `concept_only`：仅用于防御资产、duration/convexity 和利率曲线风险解释；历史低波动或低相关不能代替当前信用、流动性与压力相关审计，无完整 curve/credit/repo/执行合同时不交易。 | `FORM-STR06-CH05-001`；现金流/久期/曲率/曲线公式待L3 |
| 6 Indexes | `7946-8524` | `L2/high` | cash-and-carry、dispersion、ETF intraday arbitrage 与 volatility targeting 分别依赖指数成分、期权/期货、同步价格、融资和无风险资产。只观察价差不证明可原子成交；风险目标也不能忽略相关、跳空和换手。 | `candidate_design`：仅保留指数 volatility-targeting challenger；arbitrage/dispersion 需 options/futures/constituent synchronized quote/fill 与多腿账本，当前 blocked。 | `FORM-STR06-CH06-001` |
| 7 Volatility | `8525-9185` | `L2/high` | VIX futures basis、ETN carry、short VXX hedge、volatility risk premium、risk reversal 和 variance swap 都在重组 term structure、vega/gamma/skew 与尾部风险；平稳 carry 可在跳跃中反转。 | `risk_warning`：仅作为 volatility state/stress taxonomy；无完整 surface、greeks、exercise、borrow、margin、gap 与 ledger 前不实施。 | `FORM-STR06-CH07-001`；全章实施blocked |
| 8 Foreign Exchange | `9186-9830` | `L2/high` | HP-filter trend、carry、dollar carry、momentum-carry combo 与 triangular arbitrage 依赖利率、融资、bid/ask、同步三腿和极速执行。历史最小方差权重仍有非平稳估计风险。 | `concept_only`：用于多币种 cash/funding 与同步报价合同；FX carry 和 triangular arbitrage 不迁移成 BTC venue 套利。 | `FORM-STR06-CH08-001`；三腿执行blocked |
| 9 Commodities | `9831-10424` | `L2/high` | roll yield、COT hedging pressure、commodity diversification、value、skew premium 与 OU 定价模型分别依赖真实合约链、报告时钟、库存/供需、spot 与风险中性假设。资产标签和低历史相关不保证压力分散。 | `concept_only`：用于 futures curve/roll/COT contract；BTC 永续 funding、basis 和 inventory 机制另建规格，不套用商品公式。 | `FORM-STR06-CH09-001` |
| 10 Futures | `10425-11368` | `L2/high` | direct/cross/interest-rate hedge、calendar spread、volume/OI contrarian 与 vol-scaled trend 涉及 hedge ratio、basis、expiry、近远月、成交量/OI时钟和多腿风险。低净波动可能隐藏 legging 与相关断裂。 | `candidate_library`：仅简单趋势作基线；calendar/cross-hedge 要求合约链、roll、multiplier、FX、margin、atomic/partial execution 与真实各腿 ledger。 | `FORM-STR06-CH10-001` |
| 11 Structured Assets | `11369-12016` | `L2/high` | CDO 的 attachment/detachment、equity/mezzanine/senior carry、index/tranche/CDS hedge 和 curve trade 均依赖违约、回收率、相关与模型；MBS 另有提前偿付、extension、流动性和估值风险。 | `out_of_scope`：不纳入当前 BTC/美股系统；仅作“对冲后 carry 仍可能保留相关尾部、模型和流动性风险”的反例。 | `FORM-STR06-CH11-001`；waterfall/expected-loss/hedge公式待L3 |
| 12 Convertibles | `12017-12343` | `L2/high` | convertible arbitrage 与 option-adjusted spread 同时暴露 equity、credit、rates、volatility、borrow、conversion terms 和动态 hedge；所谓价差取决于模型与可执行对冲。 | `out_of_scope`：缺完整可转债条款、期权、借券、信用、融资及多腿 fill/ledger，当前拒绝实现。 | `FORM-STR06-CH12-001`；定价/OAS/hedge待L3 |
| 13 Tax Arbitrage | `12344-12630` | `L2/high` | municipal bond 与 cross-border tax arbitrage（含期权结构）的收益取决于司法辖区、账户身份、持有期、税率和反避税规则，书中描述会随法律变化。 | `rejected_for_now`：不实现、不回测、不提供税务结论；任何相关判断必须基于当前法域权威文本并由合格法律/税务专业人士复核。 | `FORM-STR06-CH13-001`；仅登记不可迁移边界 |
| 14 Miscellaneous Assets | `12631-13396` | `L2/high` | inflation swap、TIPS-Treasury relative value、weather demand hedge 和 spark spread 分别需要通胀指数、现金债/融资、天气结算以及燃料—电力转换与区域合同。 | `out_of_scope`：仅作 domain-specific data、settlement、unit conversion 与 basis 风险案例，不纳入当前 universe。 | `FORM-STR06-CH14-001`；专用定价/结算公式待L3 |
| 15 Distressed Assets | `13397-13908` | `L2/high` | buy-and-hold、active distressed、reorganization、buy outstanding debt 和 loan-to-own 依赖破产顺位、债权条款、控制权与法律程序；distress risk puzzle 也会随反弹和模型设定反转。 | `out_of_scope`：价格、违约概率或 beta 信号不能替代法律、资本结构和基本面尽调，不纳入实现。 | `FORM-STR06-CH15-001`；违约模型/hedge与法律前置待L3 |
| 16 Real Estate | `13909-14605` | `L2/high` | mixed/intra-asset、property/economic/geographic diversification、regional momentum、inflation hedge 与 fix-and-flip 涉及低频估值、appraisal smoothing、不可分割、融资、维修及法律风险。 | `out_of_scope`：不作为可交易候选；低历史相关和低波动不得跨映射到流动证券而忽略估值滞后与交易不可行性。 | `FORM-STR06-CH16-001`；配置/动量/估值关系待L3 |
| 17 Cash | `14606-15053` | `L2/high` | cash 是 drawdown、机会和突发流动性管理工具；repo 还引入 collateral、counterparty、term 与 haircut。书中同时列出洗钱、典当和高利贷，不因被称为 strategy 就具项目合法性。 | `mixed`：仅 liquidity buffer 与 repo 概念进入现金合同；money laundering、pawnbroking、loan sharking 永久 `rejected_illegal_or_unethical`。 | `FORM-STR06-CH17-001` 仅限合法流动性/repo |
| 18 Cryptocurrencies | `15054-15725` | `L2/high` | ANN 以技术指标预测 BTC 短期方向，Bernoulli Naive Bayes 以清洗后的 tweet vocabulary 分类情绪；两者都缺少充分 PIT、标签、去重、发布延迟、交易成本和漂移说明。 | `research_only`：只能形成模型风险清单，不能支持 BTC 生产；要求 PIT text/event、dedup、release lag、purged WF、calibration、cost、ablation 和 drift。 | `FORM-STR06-CH18-001`；书中模型不进入实现 |
| 19 Global Macro | `15726-16082` | `L2/high` | fundamental macro momentum、headline-core inflation hedge、跨国固收多因子和公告日切换都依赖宏观 first release、revision、时区和真实可交易时点。100% 日切换还放大 gap 与成本。 | `candidate_design`：只作 BTC/美股 regime/context Forecast 候选；必须 vintage/release/receive-time aware，禁止修订值回填和公告后信息进入同刻信号。 | `FORM-STR06-CH19-001` |
| 20 Infrastructure | `16083-16366` | `L2/high` | 以长期持有为主，访问工具可含基金、ETF、股票和 municipal securities；主要命题是分散、通胀对冲、稳定现金流、brownfield/greenfield 与行业分散，而非可直接执行的量化规则。 | `out_of_scope`：不进入当前交易系统；稳定现金流、长期期限和通胀敏感标签不能替代证券级 PIT 数据、估值、信用、流动性和成本验证。 | `FORM-STR06-CH20-001`；无可直接迁移定量公式 |

## 完成边界

20/20 章、151 个正式编号和 20 个章节级策略族条目已完成原 EPUB 恢复与概念核验，并按 `candidate_library`、`candidate_design`、`concept_only`、`blocked`、`out_of_scope`、`rejected_for_now` 和 `rejected_illegal_or_unethical` 建立二级边界。公式图、payoff、参数和表格未认证；任何条目在独立 PIT 数据、执行合同、成本、trial ledger 与 OOS 证据完成前都不得转成实现或 promotion 结论。
