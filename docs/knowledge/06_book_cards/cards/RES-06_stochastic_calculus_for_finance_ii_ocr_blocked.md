---
book_id: RES-06
title: Stochastic Calculus for Finance II
authors: [Steven E. Shreve]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Stochastic Calculus for Finance II - Steven Shreve - 原文.md
source_format: scanned_pdf_ocr_with_corrupt_original_pdf
source_sha256: a36101eebdca35e1748ff96dd4eecc5de3b96484566a29cea8851e6f10ba8c03
source_line_count: 47489
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Stochastic Calculus for Finance II Continuous-Time Models (Springer Finance) (Shreve Steven) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: cacd95bad4672907405be781002f2777618c518b325b011f2f543d18507ef34e
card_status: chapter_semantic_review_l2_partial_10of11_low_confidence_ch07_source_structurally_corrupt
chapter_count: 11
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 91
formula_review_status: ch01_ch11_identified_ch07_and_original_pdf_xref_page_tree_xobject_corruption_blocked
last_reviewed_at: 2026-07-15
---

# RES-06：Stochastic Calculus for Finance II

## 覆盖声明

标题页、出版信息和完整目录确认本书为 Springer *Stochastic Calculus for Finance, Volume II: Continuous-Time Models*。此前卡片把全书误记为 8 章；完整目录明确为 11 章，另有 Appendix A—C。现已恢复 11/11 章索引、OCR 行界与 `L1` 项目映射。

当前已基于可连续检索的 OCR 章末总结和正文完成 Ch01—06、Ch08—11 的低可信语义 `L2`，覆盖 `10/11=90.9%`，清单按整数记为 `91%`。公式、符号和页序仍有损坏，原始扫描 PDF 没有可用文本层，Poppler 本地字符映射也无法提供独立文本抽查，因此全部公式继续阻塞于 `L3`。

PDF 物理页 `230` 仍出现大面积黑块，随后直接跳到 Ch07 §7.4.3；§7.1—7.4.2 的连续正文无法由当前载体证明。Ch05 标题页与 §5.2 前段在 OCR 中错序，已按可读正文重建边界；所有其余章节已完成低可信语义精读，Ch07 不得靠上下文猜补。

2026-07-16 本地源审计未发现第二份同书原件。Poppler 在重建该 PDF 时报告多组缺失 xref/page-tree 对象，至少涉及物理页树节点 `158`、`184`、`207`、`231`，并在 Ch07 邻近区域报告 `Im17140`—`Im17159` 图像 XObject 缺失；目标页段文本抽取只得到分页符，未恢复正文。该缺陷是文件对象结构损坏，不是单一渲染器、字体映射或 OCR 置信度问题；在取得 SHA 不同且可连续渲染的新原件前，缺页和全部公式继续 fail-closed。

进一步对象级审计确认 PDF 目录声明 `570` 页，但文件字节中只有 `446` 个真实 `/Type/Page` 对象、`446` 个与之逐一配对的 Resources 对象，Poppler 报告的缺失 Page 引用恰为 `124` 个。全文件 `25,376` 个图像对象中 `25,227` 个已被现存页面引用，仅余 `149` 个孤儿条带且没有任何孤儿 Resources 可重建缺失页；这不足以恢复 124 页的页面顺序、条带位置、公式和正文。对象号偏移、重建 xref、浏览器 PDFium、Poppler、pypdf/pdfplumber 或仅拼接孤儿条带均不能生成可审计的完整来源。

## 全书项目映射

- `concept_only`：概率、条件期望、Brownian motion、Itô、Girsanov、Feynman–Kac、numeraire 和 jump processes 是定价/模型风险语言，不是策略 alpha。
- `rejected_for_now`：当前 BTC 趋势与美股 ETF/因子系统不因数学复杂度引入连续时间定价模型。
- `risk_warning`：风险中性、连续对冲、完备市场、无摩擦和指定 DGP 都是条件；数学上可复制/定价不等于现实可执行。
- `source_boundary`：任何公式、定理编号、页码、参数和推导在取得完整无损原件并逐式 `L3` 前不得转入规格或实现。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 General Probability Theory | `1633-6714` | `L2/low` | 概率空间把 outcome、可测事件和 countably additive measure 分开；随机变量与其 law 不是同一对象。期望、极限换序和 measure change 分别受可积、单调/支配及 density positivity/equivalence 条件约束。 | `project_rule_candidate`：DGP/measure evidence 必须保存 sample space、σ-algebra、law、density、integrability、convergence mode 与 source/target measure；不直接生成 Forecast。 | `FORM-RES06-CH01-001` |
| 2 Information and Conditioning | `6715-10268` | `L2/low` | σ-algebra 表示信息；measurability、independence 与 conditional expectation 分工不同。条件期望必须对目标信息集可测并满足 partial averaging；filtration/adaptedness、martingale 与 Markov 也不能混写。 | `existing_rule_confirmed`：每个 feature/decision 明确 as-of filtration；take-out/tower/independence 仅在各自条件成立时使用，零相关不等于独立。 | `FORM-RES06-CH02-001` |
| 3 Brownian Motion | `10269-14592` | `L2/low` | 缩放随机游走在特定极限下导向 Brownian/对数正态模型；Brownian 需要连续路径、独立正态增量与 filtration。quadratic variation、first passage 和 reflection principle 都绑定连续扩散与 stopping-time 条件。 | `risk_warning`：有限样本、细 bar 或 CLT 不证明真实价格为 Brownian；QV estimand、partition、jump/microstructure、event clock 与首次触碰语义必须独立验证。 | `FORM-RES06-CH03-001` |
| 4 Stochastic Calculus | `14593-18527` | `L2/low` | Itô integral 要求 integrand adapted 且满足平方可积条件，方可得到 martingale/isometry；Itô–Doeblin 以 quadratic/cross variation 产生二阶项，并扩展到多维过程、BSM复制与 Brownian bridge。 | `risk_warning`：微分乘法表只是积分/QV助记；连续复制、Gaussian/bridge conditioning、regularity和square-integrability均须显式，当前不实施衍生品。 | `FORM-RES06-CH04-001` |
| 5 Risk-Neutral Pricing | `18528-21269`（标题页/§5.1错序，标题行`19063`） | `L2/low` | Girsanov density、等价测度与 martingale representation 连接折现资产/组合、复制价格和 hedge；EMM存在支持无套利，EMM唯一在指定 Brownian filtration/可交易span下连接完备性。含股息资产应看再投资后的 total-return process。 | `architecture_boundary`：risk-neutral expectation不是physical Forecast；measure、numeraire、risk-loading rank、claim span、自融资和dividend cash ledger必须分别留证。 | `FORM-RES06-CH05-001` |
| 6 Connections with Partial Differential Equations | `21270-23456`（后接Ch07错序） | `L2/low` | 指定 state/time coefficient 的 SDE形成 Markov state；Feynman–Kac把条件期望与带terminal/domain条件的PDE连接。短率折现和Asian path dependence需加入足够状态，多维diffusion exposure决定理论hedge。 | `concept_only`：Monte Carlo与PDE共享同一DGP而非独立确认；state omission、边界、regularity、numerical error、离散成交和ledger必须另证。 | `FORM-RES06-CH06-001` |
| 7 Exotic Options | OCR 碎片 `23457-26120`；PDF页 `230-258` 损坏 | `L1/low` | 目录显示 barrier、lookback、Asian options、first passage、reflection 与 change of numeraire；现有正文从 §7.4.3 开始，前半章不可验证。 | `rejected_for_now`：当前无 options master/surface/exercise/settlement/ledger；来源缺损时 fail-closed。 | `FORM-RES06-CH07-001`；§7.1—7.4.2缺失 |
| 8 American Derivative Securities | `26121-29962` | `L2/low` | American value 是全部 stopping times 上折现payoff的最优值，也是覆盖任意exercise时点所需的最小hedging capital；discounted value为supermartingale，stopping/continuation region、complementarity与smooth pasting连接解析和概率刻画。 | `rejected_for_now`：exercise只能依赖当时filtration；expiry/kink、dividend event、notice/settlement与离散hedge必须建模。当前不实施American option。 | `FORM-RES06-CH08-001` |
| 9 Change of Numéraire | `29963-33138` | `L2/low` | 更换严格正的可交易numeraire必须同步更换risk-neutral measure；FX需区分domestic/foreign money-market numeraires和quote direction，bond numeraire产生只到期前有效的forward measure。随机利率闭式定价还需forward-price volatility假设。 | `architecture_boundary`：currency/unit、FX direction、rate、collateral、numeraire、measure和horizon成对保存；倒数汇率不能在错误测度下机械求期望，换单位不创造alpha。 | `FORM-RES06-CH09-001` |
| 10 Term-Structure Models | `33139-39454` | `L2/low` | 从coupon cash flows bootstrap zero curve后，本章分比较risk-neutral affine short-rate、HJM whole-curve drift restriction和fixed-tenor forward-LIBOR模型；参数简约性、跨maturity一致性与measure/compounding定义决定可识别和无套利。 | `rejected_for_now`：curve instruments、quotes、calendar/day-count、interpolation、collateral、benchmark/fallback、calibration和OOS residual均缺完整合同；LIBOR模型只作历史结构。 | `FORM-RES06-CH10-001` |
| 11 Introduction to Jump Processes | `39455-46550` | `L2/low` | Poisson/compound-Poisson以intensity、waiting time和jump-size law描述有限活动跳跃；compensator产生martingale，jump integral要求predictable/left-continuous exposure，QV包含jump squares。换测度可改intensity/law但不能创造原support外事件，jump-diffusion通常不完备。 | `risk_warning`：jump support、clock、compensator、simultaneous events、measure和hedge span必须显式；校准到期权价只是从多EMM中选择，不证明physical tail或可成交性。 | `FORM-RES06-CH11-001` |

## L2 精读记录（Ch01—06、Ch08—11，OCR 低可信）

### Ch01：概率对象、极限和换测度必须分合同

- `5721-5764` 的章末总结从 `(Omega,F,P)` 区分 outcome space、可测事件集合与 probability measure，并明确 countable additivity；数据表中的行、标签和经验频率不能自动替代这些理论对象。
- `5768-5798` 区分 random variable 与其 induced distribution：不同变量可同 law，同一变量在不同 measure 下也可有不同 law。模型卡必须保存变量定义、support、measure 和 units，不能只存分布名。
- `5798-5862` 把 expectation 定义为 Lebesgue integral，并明确 almost-sure convergence 本身不足以交换 limit 与 expectation；monotone/dominated convergence 各有非负单调或 integrable domination 条件。
- `5866-5893` 用非负、期望为一的 density 建新 measure，只有 density 严格为正时才保证 equivalence 与相同零概率集。risk-neutral density 不得与 physical probability、likelihood 或 sample weight 混写。

### Ch02：information set 是可验证对象而非叙述标签

- `9563-9591` 以 σ-algebra 表示可判定事件，并用 measurability 表示该信息足以确定随机变量；“计算时可获得”必须落实到具体 `F(t)`、时间戳和版本。
- `9595-9659` 区分 independence 与 irrelevance，并明确 independence 蕴含 uncorrelatedness、反向通常不成立；只有 jointly Gaussian 等附加条件下零相关才推出独立。
- `9664-9714` 定义 conditional expectation 为目标 σ-algebra 可测且满足 partial averaging 的随机变量，并列出 linearity、take-out、tower、independence 与 conditional Jensen；每条性质都需核验 measurability/integrability/嵌套关系。
- `9718-9789` 把 filtration、adapted process、martingale 与 Markov 分开：martingale 约束条件均值，Markov 约束给定当前状态后的未来分布。二者都不能授权读取未来，也不能证明当前状态已充分。

### Ch03：Brownian 极限不能成为市场事实

- `10319-11260` 从对称随机游走的缩放、增量、martingale 与 quadratic variation 进入连续极限，并连接二项模型的 log-normal limit；步长、时间缩放、独立性和风险中性概率都属于前提。
- `11373-11864` 的 Brownian 定义要求连续路径、独立正态增量和与 filtration 相容的未来增量独立；现实 BTC/股票的 jump、异步时钟、停牌和 order-flow dependence 不因采样变细而消失。
- `11870-12775` 区分一阶变差与 quadratic variation，并把几何 Brownian 波动率连接到 QV；项目必须保存 partition/clock、microstructure/jump treatment 与 estimator limit，不能把 realized variance 和模型 `sigma` 混名。
- `12910-13784` 的 first-passage/reflection 结论属于连续 Brownian：过程几乎必达非零水平，但 hitting time 期望可无限，联合最大值分布也依赖无跳跃路径。模型首次触碰不等于 quote、fill、强平或 ledger 事件。

### Ch04：随机积分结论绑定适应性与可积性

- `14637-15544` 从 simple integrand 构造 Itô integral，再以平方范数近似扩展到一般 integrand；`15431` 明确 integrand 必须对 Brownian filtration adapted，章末 `18008-18026` 才据此给出 martingale、零均值与 Itô isometry。
- `18031-18085` 区分 pathwise quadratic variation 与跨路径 variance，并把 `dW*dW=dt` 等乘法表定位为 differential notation；工程规格和测试必须回到积分、partition 与 convergence，而不是直接执行符号乘法。
- `18087-18230` 的多维 cross-variation、Itô–Doeblin 和 product rule把 covariance loading带入二阶项；相关 Brownian source、state ordering与loading matrix必须版本化，不能只存一个相关系数。
- `18226-18347` 的 BSM PDE/复制同时使用连续GBM、无摩擦、自融资、delta调仓和boundary conditions；`18351-18375` 的 Lévy/Gaussian识别也有精确连续时间条件，均不得当作现实可执行性证明。
- `16825-18003` 的 Brownian bridge等价于对未来终点条件化后的过程；它可用于条件模拟/平滑，但若把已知终点用于历史策略特征或决策，会直接形成future leakage。

### Ch05：风险中性价格只在复制与span条件下成立

- OCR 中 Ch05 标题页位于 `19063`，但 §5.2 正文已从 `18528` 开始；本卡按 `18528-21269` 登记可读范围并保留错序警告，公式页码不得据此直接引用。
- `18528-18617` 的 Girsanov构造要求指数density及相关Itô integral是真martingale；`18671-18703` 再用strict positivity保证actual/risk-neutral measures等价并共享零概率事件。
- `18707-19052` 在非零volatility、适应的rate/return/volatility下改变drift而保留volatility，使折现stock和自融资portfolio成为martingale；money-market account与bond的instantaneous risk语义明确不同。
- `19063-19834` 把F(T)-measurable payoff的risk-neutral conditional expectation与martingale representation映射到复制portfolio；只有filtration由对应Brownian source生成且hedge loading可解时，理论price才等于replication capital。
- `19835-21049` 分开陈述基本定理：EMM存在排除模型套利，EMM唯一与完备性相连；多资产风险溢价方程无解可产生套利，多解则表示未spanned risk。现实constraints/liquidity/fills会进一步缩小可复制集合。
- `21053-21108` 指出含股息资产应使“股价加再投资股息”的折现total-return process为martingale，而非仅看ex-dividend price；PIT corporate-action和cash ledger不能被连续yield静默替代。

### Ch06：PDE与模拟必须共享完整状态合同

- `21282-21314` 把risk-neutral Monte Carlo与PDE列为同一估值问题的两种计算路线，并说明Asian option需要多维state；二者共享DGP、measure和payoff，不能互相充当独立验证。
- `21318-21748` 的SDE只允许time/current state和driving Brownian进入系数，以获得书中Markov模型类；真实随机volatility、regime、jump或遗漏变量必须加入state或明确破坏Markov假设。
- `21755-22130` 的Feynman–Kac/discounted Feynman–Kac把条件期望连接到PDE与terminal/domain条件；解存在、唯一、regularity、boundary与numerical convergence缺一不可，解析/数值解都不是ledger PnL。
- `22211-22766` 在short-rate模型中，折现因子依赖未来rate path，但给定当前Markov rate可把bond price写成state function；yield、bond、money-market account和bond option仍有不同cash-flow/units与terminal conditions。
- `22784-23155` 的Asian案例把累计过程与spot组成二维Markov state；累计量单独并非Markov。理论hedge来自diffusion term matching，实际还需sampling calendar、离散rebalance、cost、multi-leg fills和residual-risk evidence。

### Ch08：American exercise是适应信息的最优停止合同

- `26252-26751` 定义 stopping time 的核心是时点 `t` 的停止决定只能依赖 `F(t)`；利用未来涨跌选择是否停止的随机时点明确不是 stopping time，并会破坏 optional-sampling 下的 martingale/supermartingale 性质。
- `26757-27956` 对 perpetual put 先评估任意exercise level，再优化边界；价值同时满足 payoff dominance、discounted supermartingale 与某个最优停止后martingale，是覆盖持有人任意exercise策略所需的最小初始资本。
- `27379-27942` 用 linear complementarity 划分 stopping/continuation sets，并以 smooth pasting连接函数与一阶导数；这属于连续扩散与regular boundary下的模型性质，不得假定在jump、离散监控或expiry kink处普遍成立。
- `27970-28354` 的finite-expiration put增加time-dependent boundary、terminal/asymptotic conditions；`28158-28166` 明确smooth pasting在到期时不成立。数值网格、边界误差和exercise tie-breaking必须进入验证证据。
- `28443-29304` 只在无股息等条件下得到American call与European call等价；离散股息会产生除息前exercise比较。corporate-action timing、amount、tax、settlement与post-dividend hedge state必须PIT可回放。

### Ch09：FX方向、numeraire与measure必须成组变化

- `29967-30171` 区分currency、domestic/foreign money-market account和`T`-bond numeraires；真正的numeraire是严格正的可交易资产，不是抽象币种标签，相关measure也不是可省略元数据。
- `30187-30715` 的change-of-numeraire theorem用折现并归一化的numeraire构造density，使所有相对价格在新measure下成为martingales；volatility vector按资产与numeraire loading之差变化，units与measure必须同步。
- `30719-31458` 对FX明确quote为“每单位foreign对应多少domestic”，并分别构造domestic/foreign measures。汇率倒数经Itô产生额外drift；Siegel paradox来自在错误measure下对倒数套同一均值规则，不是套利机会。
- `31514-31879` 的forward FX、Garman–Kohlhagen和put-call duality同时绑定quote direction、domestic/foreign rates、支付币种、strike units与对应measure；机械取倒数或交换币种会改变cash flow和numeraire。
- `31888-32051` 以`T`-maturity zero-coupon bond作numeraire得到只在`T`前有效的forward measure；forward price在该measure下为martingale，其volatility是asset与bond loading之差。
- `32098-32549` 的随机利率call公式还假设`T`-forward price具有常数volatility，并显式验证stock/bond hedge自融资；它不是“随机利率下仍可直接使用经典BSM”的通用结论。

### Ch10：期限结构是跨maturity的一致合同

- `33143-33250` 从coupon bond现金流递归bootstrap zero-coupon prices，再由maturity-specific discount factors定义yield curve；这一过程依赖instrument cash flows、quote、day-count、calendar、interpolation与default-free假设，不能从一个“利率”字段恢复。
- `33280-33322` 指出finite-factor short-rate模型从抽象factors开始，无法仅由short rate推断market price of risk，因此书中直接在risk-neutral measure下构造并校准bond/derivative prices；这些factor dynamics不是physical Forecast。
- `33326-33357` 与 `35393-36425` 把HJM state设为整条forward curve，并要求所有maturities共享同一market-price-of-risk/drift restriction；逐期限独立拟合即使每条曲线看似合理，也可能产生跨期限套利。
- `38023-38118` 的affine模型通过Markov factors和Riccati/PDE得到bond prices，校准前还需消除参数重参数化；parameter parsimony、Jacobian/conditioning、多解和OOS curve residual必须留证。
- `38235-38297` 强调whole curve虽是无限维对象，有限Brownian drivers仍限制可生成的curve family；低维factor不能因拟合初始曲线就声称覆盖非平行shift、basis或tail。
- `33367-33383`、`38299-38487` 的forward-LIBOR/BGM以固定tenor simple rate避免instantaneous lognormal forward爆炸，并在forward measure下得到Black caplet结构。LIBOR tenor、历史0.25/0.50等示例及旧benchmark不得迁移到当前RFR。

### Ch11：jump风险通常意味着不完备与可预测性约束

- `39572-40127` 用IID exponential waiting times和constant intensity构造Poisson process；原始counting process因单向上跳不是martingale，减去compensator后才成为martingale。真实event intensity的时变、聚集和regime必须另建模型。
- `40164-40799` 的compound Poisson增加IID jump-size law，并可在有限support时分解为多个独立Poisson sources；support、sign、units、simultaneous-jump规则与source count都会改变hedge维度。
- `40803-41471` 明确adapted integrand不足以保证jump stochastic integral为martingale；使用left-continuous（更一般为predictable）exposure才避免在看到jump后同刻改仓。order/fill状态机必须使用pre-jump position，不能事后套用post-jump仓位。
- `41475-42002` 的jump quadratic variation累加jump squares，cross variation只由simultaneous jumps贡献；连续Brownian QV、jump variation和离散realized estimators必须分解报告。
- `43029-44211` 的measure change可调整Poisson intensity和compound jump-size distribution，但equivalence要求原先不可能的jump sizes在新measure下仍不可能；density、support、intensity、compensator和Brownian/jump independence必须成套保存。
- `44413-46457` 展示单一jump size可能由单一风险资产span，而多jump sizes加Brownian source需要更多证券；连续jump distribution通常要求无限span，因此jump-diffusion存在多risk-neutral measures。选定parametric EMM并校准市场价格不是唯一真实概率或完备性证据。

## 附录边界

- 目录确认 Appendix A—C 分别涉及高级概率、conditional expectation existence 和第二资产定价基本定理证明。
- 当前 OCR 在 Ch11 summary 后跳入索引，附录正文同样不连续；不单独计入 `L1/L2`，不得引用其证明或公式。

## 剩余来源阻塞与公式复核前置

Ch01—06、Ch08—11的低可信语义 `L2` 已完成。Ch07与Appendix仍需取得可完整读取、页序正确且无黑块的原始PDF/EPUB并核验SHA；当前不从损坏页猜公式、定理或缺失论证。11章全部公式继续保留为`L3 blocked`，不得进入代码、参数、回测或gate。
