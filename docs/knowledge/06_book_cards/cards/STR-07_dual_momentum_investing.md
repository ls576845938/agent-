---
book_id: STR-07
title: Dual Momentum Investing
authors: [Gary Antonacci]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Dual Momentum Investing - Gary Antonacci - 原文.md
source_format: epub_text_original_epub_cross_checked
source_sha256: 535ada87cdc5be225cbe9fac6b4fbfe32d9cf9194503cb44bb99c9d2af30dbfb
source_line_count: 6502
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\开源书籍\Dual Momentum Investing An Innovative Strategy for Higher Returns with Lower Risk (Gary Antonacci) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_source_sha256: 285e79f45982f11ab38b5d13f28aa185a359ab86005eb407f7915ca57380983f
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 10
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 11_ch01_ch10_appendix_b_items_verified_concept_only_from_original_epub
last_reviewed_at: 2026-07-15
---

# STR-07：Dual Momentum Investing

## 覆盖声明

本卡依据 EPUB 正文章节标题完成 10/10 章 `L2` 语义精读。Appendix A 为实现/资源示意，Appendix B 为论文式历史研究；两者不计入章节数。现已逐项回看原始 EPUB 的 `ops/ch1.html` 至 `ops/ch10.html` 和 `ops/appb.html`，将相对/绝对动量、dual momentum、回看期、风险指标、历史表格及附录方法共 11 项关闭为 `verified_concept_only`。这只证明书中确有相应定义、规则与限制，不认证图片表格数字、原始论文、数据版本、参数最优性或项目外推。

## 全书项目映射

- `candidate_design`：将相对强弱排序和绝对风险状态作为两个独立 Forecast 候选；组合逻辑由 Portfolio/Risk 消费，不允许 Strategy 直接切换资产或下单。
- `existing_rule_confirmed`：资产池、指数/ETF 映射、信号和成交时点、实际交易日历、回看/跳月/持有/调仓、防御资产资格、成本与基准必须事前声明。
- `risk_warning`：smart beta、均线、估值、52 周高点、盈利/收入、加速度、fresh momentum、行业轮动和风险平价均扩大 trial count；不得在 holdout 上筛选。
- `implementation_gap`：书中把美国综合债券或短债视为安全港，但项目必须动态验证 duration、credit、liquidity、real-yield、stress correlation 与可交易性，异常时 fail-closed。
- `rejected_for_now`：固定 12 个月参数、作者历史回测、杠杆、指数代理、收益数字、风险阈值和“长期有效”判断均不得直接成为项目参数、promotion gate 或生产结论。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 World's First Index Fund | `337-522` | `L2/high` | 低成本、低换手和宽基指数构成主动规则必须战胜的可投资基线；异常、风险溢价和产品容量会随参与者与制度变化而衰减。作者商品交易经历同时说明杠杆与异常事件可摧毁表面稳健策略。 | `existing_rule_confirmed`：报告 gross/net alpha、费用、换手、容量和拥挤，不以作者、基金或历史声誉替代证据。 | `FORM-STR07-CH01-001`：`verified_concept_only` |
| 2 What Goes Up… Stays Up | `523-720` | `L2/high` | 动量是收益持续性，但横截面相对强弱、单资产时间序列趋势及其 formation、skip、holding 约定不是同一信号。历史研究和管理人案例只能说明研究问题。 | `candidate_design`：分别冻结 relative rank 与 absolute state 的 price field、return horizon、skip、rebalance、universe、availability 和 execute lag。 | `FORM-STR07-CH02-001`：`verified_concept_only` |
| 3 Modern Portfolio Theory Principles and Practices | `721-897` | `L2/high` | 均值方差、CAPM、期权与组合保险提供风险语言，但正态、稳定相关、可连续调仓和可成交等假设在尾部、跳空与流动性压力下会失效。 | `existing_rule_confirmed`：动量过滤不替代 Portfolio/Risk；协方差、波动、杠杆、保证金、流动性、gap 和 rebalance replay 必须独立约束。 | `FORM-STR07-CH03-001`：`verified_concept_only` |
| 4 Rational and Not-So-Rational Explanations of Momentum | `898-1083` | `L2/high` | 风险补偿、市场摩擦、反应不足、过度反应、羊群和过度自信都可能解释动量；多个可讲述机制并不等于因果已确认。 | `candidate_design`：每个候选登记 mechanism family、PIT proxy、竞争解释、反证条件、regime/crowding 失效监控，禁止事后行为叙事。 | `FORM-STR07-CH04-001`：`verified_concept_only` |
| 5 Asset Selection: The Good, the Bad, and the Ugly | `1084-1485` | `L2/high` | 债券并非永久安全，股债与跨国相关会在压力期改变；风险平价可能集中杠杆久期，商品多头还包含 roll、crowding 和流动性风险。资产类别标签不自动提供独立风险溢价。 | `implementation_gap`：ETF universe manifest 保存存续、PIT 成分、费用、流动性和指数身份；防御资产执行 eligibility/freshness/duration/credit/real-yield/stress 测试。 | `FORM-STR07-CH05-001`：`verified_concept_only` |
| 6 Smart Beta and Other Urban Legends | `1486-1659` | `L2/high` | smart beta 常可还原为 size/value/sector/rebalancing 暴露；另类加权增加换手、跟踪误差、集中和费用，发布前回测优势可能在产品上线后消失。短样本与不可交易微盘会夸大因子。 | `candidate_design`：以廉价可复制基准做 factor/sector/rebalance attribution，报告 launch-date split、delisting、liquidity、turnover、tracking error 和净增量。 | `FORM-STR07-CH06-001`：`verified_concept_only` |
| 7 Measuring and Managing Risk | `1660-1800` | `L2/high` | 相对动量比较资产，绝对动量比较资产自身超额收益；书中 dual momentum 先相对选择，再用绝对状态过滤。Sharpe、Sortino、偏度和最大回撤各有样本长度、序列相关或尾部局限。 | `candidate_design`：Strategy 分别输出 cross-sectional Forecast 与 absolute-risk Forecast；Portfolio/Risk 决定 TargetPosition，并同时报告序列相关修正、drawdown 深度/次数/时长和 tail stress。 | `FORM-STR07-CH07-001`：`verified_concept_only` |
| 8 Global Equities Momentum | `1801-2076` | `L2/high` | GEM 每月在美股、非美股中按过去 12 个月相对收益选择，再检查选中资产相对 T-bill 的 12 个月超额收益；不通过则转综合债券。趋势过滤会滞后顶部和急速反弹，作者历史绩效不可外推。 | `candidate_design`：作为美股低频 ETF challenger，仅用 PIT index/ETF identity、月末真实交易日、信号后成交、可资格防御资产、全成本及 matched-exposure/no-trade 基准。 | `FORM-STR07-CH08-001`：`verified_concept_only` |
| 9 Mo' Better Momentum | `2077-2334` | `L2/high` | 多重比较、参数拟合、短样本和重复使用数据可把增强项变成回测幻觉；普通 holdout 也无法消除已知结果和试验次数。均线、估值、52 周高点、基本面动量、加速度、fresh momentum、债券/行业轮动均是新模型族。 | `risk_warning`：每项增强独立登记 trial/family/complexity budget，使用 purged/embargoed WF、multiple-testing 和 locked holdout；比较简单 dual momentum 基线及全成本。 | `FORM-STR07-CH09-001`：`verified_concept_only` |
| 10 Final Thoughts | `2335-2463` | `L2/high` | 规则纪律可减少临场判断，但“行为偏差长期存在”不能证明未来 alpha；策略仍会阶段性落后，容量、拥挤、成本和制度变化都可能导致衰减。 | `existing_rule_confirmed`：冻结规则和人工 override 审计，持续监测相对基准、成本、容量与 regime decay；结论保持 `research_only`，promotion 仅看当前 HEAD 证据。 | `FORM-STR07-CH10-001`：`verified_concept_only` |

## 附录与旁证

- Appendix A `2464-2481`：实现/资源说明，只作为定位线索，不视为生产代码或可调用端点。
- Appendix B `2482-2772`：以过去 formation-period、资产、60/40、parity、杠杆和因子回归展示绝对动量；明确给出正超额收益过滤、月度再评估和历史成本假设。`FORM-STR07-APP-B-001` 已从原始 `ops/appb.html` 核为 `verified_concept_only`；其 1974—2012 结果、12 个月选择、T-bill/指数代理、20bp、月末回撤、相关、二阶随机占优、1.85 倍杠杆和因子 alpha 均不得当作项目样本外证据。
- Notes `2773-3189`、Bibliography `3553-4287`：用于回溯原始论文、样本和统计口径；未逐篇复核。

## 对现有 BTC 与美股系统的启发

- 美股：现有 ETF/指数轮动最适合把 relative rank 和 absolute-risk state 拆成两个可消融 Forecast，再由统一 Portfolio/Risk 合成；这样可独立判断收益提升来自选强还是降风险。
- 美股：综合债券、短债、现金或 T-bill 都只能是条件性 defensive candidate，必须通过当前市场和产品合同，而不是沿用书中“安全港”假设。
- BTC：单资产只能直接研究 absolute/time-series momentum；没有独立、同质且可交易的资产池时，不得把交易所、合约或不同报价简单冒充横截面 breadth。
- 共用：12 个月、月频和均线只是预登记 challenger，不是默认正确参数；任何变体必须进入 trial ledger，保持 locked holdout 未查看。
- 共用：趋势退出不能消除 overnight gap、流动性枯竭、稳定币/交易所/债券信用、相关性收敛和执行失败，所有异常继续由 Portfolio/Risk 与执行链 fail-closed。

## L3 原始 EPUB 复核结论

| 公式/项目 | 原始来源位置 | 原始 EPUB 直接证据 | 结论与项目边界 |
|---|---|---|---|
| `FORM-STR07-CH01-001` | `ops/ch1.html`；转换文 `337-522` | 正文明确把低换手、免管理费、分散化作为被动基线优势，并说明商品风险溢价随参与者增加而衰减、交易存在容量约束，过度杠杆叠加异常事件可致失败。 | `verified_concept_only`：只确认 investable benchmark、容量和杠杆问题；基金、商品收益、费用和作者案例不迁移。 |
| `FORM-STR07-CH02-001` | `ops/ch2.html`；转换文 `523-720` | 正文回顾 relative strength 研究，并预告 absolute momentum 与 relative momentum 的风险差异及其组合。 | `verified_concept_only`：只确认两类信号必须分开；历史研究收益、6—12月区间及交易成本数字未认证。 |
| `FORM-STR07-CH03-001` | `ops/ch3.html`；转换文 `721-897` | 正文描述 Markowitz mean-variance、CAPM、正态/独立假设及 1987 portfolio-insurance 反馈卖压。 | `verified_concept_only`：只保留假设审计与尾部/流动性压力；理论权重、历史比例和因果定量结论禁用。 |
| `FORM-STR07-CH04-001` | `ops/ch4.html`；转换文 `898-1083` | 正文并列 risk-based 与 anchoring、underreaction、herding、overreaction、overconfidence 等行为解释，并呈现文献间分歧。 | `verified_concept_only`：这些是竞争机制，不是因果确认或未来 alpha 证据。 |
| `FORM-STR07-CH05-001` | `ops/ch5.html`；转换文 `1084-1485` | 正文讨论股债相关可变、风险平价集中债券并用杠杆、杠杆的 fat-tail/流动性/对手方风险，以及商品 roll return 的年代变化。 | `verified_concept_only`：只形成 defensive eligibility 与 stress 清单；相关、收益、久期、杠杆和 roll 数字均需当前产品重估。 |
| `FORM-STR07-CH06-001` | `ops/ch6.html`；转换文 `1486-1659` | 正文将部分 smart beta 收益归于 value/small-cap 暴露，并列出 turnover、tracking error、流动性及 launch 后衰减问题。 | `verified_concept_only`：只保留归因与可复制基线；指数、费用、换手和因子优劣数字不迁移。 |
| `FORM-STR07-CH07-001` | `ops/ch7.html`；转换文 `1660-1800` | 正文定义 relative momentum 为资产间比较，absolute momentum 为资产自身过去趋势，并以资产收益减 T-bill 后正负定义 absolute state；同时说明 Sharpe、Sortino 和月末最大回撤局限。 | `verified_concept_only`：只确认信号分类和指标风险；T-bill、频率、risk-free、序列相关和 drawdown clock 必须项目化。 |
| `FORM-STR07-CH08-001` | `ops/ch8.html`；转换文 `1801-2076` | 原始 EPUB 明确 GEM 顺序：先比较 S&P 500 与 ACWI ex-U.S.，再与 T-bill 比较，不通过转 U.S. aggregate bonds，每月重复；作者采用 12 月回看。 | `verified_concept_only`：只核实书中算法；12月、月频、指数拼接、防御资产、切换次数、成本和绩效全部禁用。 |
| `FORM-STR07-CH09-001` | `ops/ch9.html`；转换文 `2077-2334` | 正文明确 5% 水平测试 20 个以上策略可偶然出现显著项，并指出普通 holdout 不计尝试次数且研究者可能已知后半段；均线、估值、52周高点和 fresh momentum 均是新增模型。 | `verified_concept_only`：只确认 trial governance；作者对 12 月“已验证”的判断不解锁参数，所有增强独立预注册。 |
| `FORM-STR07-CH10-001` | `ops/ch10.html`；转换文 `2335-2463` | 正文承认 anomaly 可能随广泛采用而失去部分盈利能力，也承认 dual momentum 会阶段性落后基准并要求纪律。 | `verified_concept_only`：只支持衰减和 override 监控；行为持续、200年叙事及未来有效性判断不成立为项目证据。 |
| `FORM-STR07-APP-B-001` | `ops/appb.html`；转换文 `2482-2772` | 附录明确月度数据、指数替代、正超额收益切换 T-bill、每次切换扣 20bp、月末最大回撤、2—18月搜索、12月/1月 benchmark、1.85倍杠杆和历史因子分析。 | `verified_concept_only`：只确认方法与假设清单；图片表格数值、原始论文、样本、替代指数、成本、参数、杠杆、因子 alpha 和绩效均未独立认证。 |

## 单书完成边界

- 10/10 章 `L2` 已完成，11/11 个登记项目均已直接回看原始 EPUB 并关闭为 `verified_concept_only`。
- “完成”仅表示本书知识抽取与来源核对闭环，不表示任何策略、参数、历史数字、原始论文或绩效已获项目验证。
- 后续若研究 GEM 或 absolute momentum，必须另开研究票据，预注册 universe、formation/skip、月末时钟、signal-to-fill lag、防御资产、成本和 trial family；本卡不授权回测、holdout 访问或 promotion。
