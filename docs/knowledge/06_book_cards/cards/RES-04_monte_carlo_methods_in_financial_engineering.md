---
book_id: RES-04
title: Monte Carlo Methods in Financial Engineering
authors: [Paul Glasserman]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Monte Carlo Methods in Financial Engineering - Paul Glasserman - 原文.md
source_format: scanned_pdf_ocr_with_original_pdf_visual_crosscheck
source_sha256: 32fa866500c117621d5d3953b5d37c9a52580ad2482d6e4ea070f1e3e24922bd
source_line_count: 65225
original_pdf_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Monte Carlo Methods in Financial Engineering Paul Glasserman (Springer) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_pdf_sha256: 83bdf67878cf2fafec97492caa0348bae55a7f510253eac75464d16149f88377
original_pdf_page_count: 606
card_status: chapter_semantic_review_l2_complete_low_confidence_formula_pending
chapter_count: 9
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: appendix_a_6_appendix_b_12_appendix_c_12_ch01_10_ch02_18_ch03_31_ch04_14_ch05_26_ch06_14_ch07_28_ch08_29_verified_1_blocked_source_gap_ch09_17_items_verified_concept_only
last_reviewed_at: 2026-07-15
---

# RES-04：Monte Carlo Methods in Financial Engineering

## 覆盖声明

本卡依据 OCR 正文、完整目录、章节导言与结语完成 9/9 章 `L2` 语义精读。已对本地 606 页原始扫描 PDF 核验标题页、目录、九章首页，视觉复核 Ch01 的 22 个关键页、Ch02 的全部 39 页、Ch03 的全部 106 页、Ch04 的 36 个关键页、Ch05 的全部 57 个有内容印刷页、Ch06 的 32 个关键页、Ch07 的全部 44 页、Ch08 原载体可用的全部 58 个印刷内容页 `422-479`、Ch09 的 45 个关键页，并逐页复核 Appendix A `539-544`、Appendix B 全部内容页 `545-557` 和 Appendix C 全部内容页 `559-567`；确认 Monte Carlo、随机路径、QMC、方差缩减、离散误差、敏感度、最优停止、尾部风险，以及 stochastic calculus、measure change、term structure 和利率衍生品引用边界。原始扫描 PDF 在 Ch07 印刷页 `420` 后直接跳到 Ch08 印刷页 `422`，缺 Ch08 首印刷页 `421`；目录边界页 `480`、Appendix B 章界页 `558` 与 Appendix C 章界页 `568` 无正文。章节语义可信度保持 `low`；Ch01 10项、Ch02 18项、Ch03 31项、Ch04 14项、Ch05 26项、Ch06 14项、Ch07 28项、Ch08 29项、Ch09 17项、Appendix A 6项、Appendix B 12项和 Appendix C 12项均仅关闭为 `verified_concept_only`，Ch08 页421保留1项`blocked_source_gap`，不得从 OCR 或概念核验直接转录实现。

原始载体核验范围：PDF 印刷页 Ch01 `1-4, 9-13, 17-19, 21, 23, 25, 27, 29, 31-33, 35-38`；Ch02 `39-77`；Ch03 `79-184`；Ch04 `185-187, 196, 200, 203, 205-206, 209-210, 214, 217, 220, 232-236, 240, 243, 245, 252-257, 260-262, 265, 269, 274, 276, 278-279`；Ch05 `281-337`；Ch06 `339-340, 343-348, 350-352, 355-358, 360-376`；Ch07 `377-420`；Ch08 `422-479`（缺 `421`，`480` 无正文）；Ch09 `481-487, 489, 491-493, 495-496, 498-499, 501, 503, 505-508, 510, 512-515, 517-523, 525-527, 529-530, 532-538`；Appendix A `539-544`；Appendix B `545-557`（`558` 无正文）；Appendix C `559-567`（`568` 无正文）。当前复核证明所有原载体可用页的原子主题及适用条件；仅 Ch08 页421保持 fail-closed。

## 全书项目映射

- `existing_rule_confirmed`：Monte Carlo 报告应包含随机种子、路径数、输入分布、收敛、置信区间和估计误差。
- `implementation_gap`：当前研究 robustness 主要给点估计和固定路径数，缺 lower confidence bound、收敛曲线与依赖保持的 resampling spec。
- `rejected_for_now`：模拟路径不能替代真实历史、paper runtime、fill ledger 或交易所证据。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Foundations | OCR `1071-4964`；PDF印刷页 `1-38` | `L2/low` | 把积分/期望转成样本均值，以大数定律说明一致性、CLT说明有限路径误差；效率比较必须同时绑定估计对象、方差和计算成本。衍生品定价部分依赖复制、无套利、风险中性、完备性与 numeraire 假设。 | `implementation_gap`：每个模拟 artifact 写明 estimand、measure/DGP、sampling distribution、seed、paths、cost、interval 与模型假设；定价等价不迁移为交易 edge。 | `FORM-RES04-CH01-001`—`010`；10项核心关系已核为`verified_concept_only` |
| 2 Generating Random Numbers and Random Variables | OCR `4965-9051`；PDF印刷页 `39-77` | `L2/low` | PRNG 是确定性算法；uniformity 不等于 independence。线性同余/组合生成器、inverse transform、acceptance-rejection 与 normal/multivariate-normal 变换会把周期、相关、随机维数和数值误差传入模拟。 | `candidate_design`：记录 RNG family/version/state/seed/substream、uniform consumption、变换算法与 covariance factor；测试边际、serial/cross correlation、并行流碰撞、restart determinism、端点和秩缺陷。 | `FORM-RES04-CH02-001`—`018`；18项核心关系已核为`verified_concept_only` |
| 3 Generating Sample Paths | OCR `9052-20281`；PDF印刷页 `79-184` | `L2/low` | 区分在离散日期精确匹配联合分布的模拟与 SDE 离散近似；从 Brownian/GBM 扩展到 Gaussian short-rate、square-root diffusion、jump、HJM 与 LIBOR market model 时，状态、测度、校准、相关结构、时间/期限网格和可精确采样条件均改变。 | `concept_only`：只在对应估值/风险问题采用；历史趋势回测不引入臆造扩散。任何 synthetic path 必须声明 DGP、state、measure/numeraire、校准窗口、exact/approximate、grid、jump convention 和不能覆盖的真实机制。 | `FORM-RES04-CH03-001`—`031`；31项核心关系已核为`verified_concept_only` |
| 4 Variance Reduction Techniques | OCR `20282-30204`；PDF印刷页 `185-280` | `L2/low` | control、antithetic、stratified/LHS、moment matching 与 importance sampling 只有利用问题结构时才可能显著增效；降方差过程若引入跨 replication 依赖，会使常规标准误和置信区间失效。 | `candidate_design`：与朴素 MC 同 estimand、同成本比较 bias/variance/CI coverage/ESS；控制量期望、抽样权重和 proposal misspecification 必须可审计。 | `FORM-RES04-CH04-001`—`014`；14项核心关系已核为`verified_concept_only` |
| 5 Quasi-Monte Carlo | OCR `30205-36373`；PDF印刷页 `281-338` | `L2/low` | 低差异点以确定性覆盖替代随机采样；理论误差率依赖 finite input dimension、variation、discrepancy、点集/序列、维度与坐标构造。Halton/Hammersley/Faure/Sobol/lattice、randomization、Brownian bridge/PCA 和 effective dimension 会改变表现，确定性单次结果没有普通 MC 的现成误差条且可出现假平台。 | `rejected_for_now`：当前 robustness 先补普通 MC interval；若研究 QMC，必须 randomized QMC 多次独立 replicate、报告 replicate dispersion/工作量/坐标映射，并与同预算 MC 和 variance-reduced MC 比较。 | `FORM-RES04-CH05-001`—`026`；26项核心关系已核为`verified_concept_only` |
| 6 Discretization Methods | OCR `36374-40261`；PDF印刷页 `339-376` | `L2/low` | Euler 与高阶方法分别面对 weak/strong error；variance reduction/QMC 只能减少固定离散层上的抽样误差，不能消除 discretization bias。jump、extreme、barrier crossing 与 path dependence 还需要专门插值或边界处理。 | `candidate_design`：盘口、强平或路径模拟分开报告 time step sensitivity、weak/strong target、barrier miss 和 sampling error；更细步长不等于更真实。 | `FORM-RES04-CH06-001`—`014`；14项核心关系已核为`verified_concept_only` |
| 7 Estimating Sensitivities | OCR `40262-44857`；PDF印刷页 `377-420` | `L2/low` | finite difference 的 bias 与 variance 同时依赖 step、光滑性和跨参数 coupling；pathwise 依赖路径可微、支配/一致可积与微分期望交换；likelihood-ratio 依赖显式密度、共同支撑、满秩与 score 方差。离散近似、discontinuity、长路径和二阶导数会改变目标或放大方差。 | `concept_only`：仅用于模型风险/Greeks；策略参数敏感度优先直接邻域重跑。`SensitivityEvidence` 必须保存 estimand、方法、step、coupling、path/score/tangent、support/rank、interchange 条件、discontinuity smoothing、离散 target、variance 与混合 estimator。 | `FORM-RES04-CH07-001`—`028`；28项核心关系已核为`verified_concept_only` |
| 8 Pricing American Options | OCR `44858-50808`；PDF印刷页 `421-480`，原载体可用 `422-479` | `L2/low` | 提前行权是 stopping-time/dynamic-programming 问题；同样本拟合和决策产生 high bias，独立 second pass 的可实施次优规则给 low bias。tree、partition、mesh、regression 与 dual 方法分别受 exercise-date/state-dimension、density/rank、basis 和 nested-simulation 成本约束；可靠结论应成对报告 lower/upper bounds。 | `rejected_for_now`：当前系统无 American option master/exercise/settlement/Greeks/ledger，不实施；只迁移信息集、训练/评价分离、可实施策略下界和 martingale 上界的治理模式。 | `FORM-RES04-CH08-001`—`030`；29项已核为`verified_concept_only`，页421一项`blocked_source_gap` |
| 9 Applications in Risk Management | OCR `50809-56681`；PDF印刷页 `481-538` | `L2/low` | 风险模拟先要求风险因子联合分布、固定 horizon/positions 与风险因子到组合价值的 mapping；VaR/尾概率、重尾、非线性、信用依赖和 recovery 假设分别决定尾部。delta-gamma、control/importance/stratified 只在支撑、权重、尾部样本和全量重估验证成立时可能增效。 | `candidate_design`：drawdown/liquidation/credit stress 输出 loss sign、risk-factor model、valuation mapping、tail count/interval/ESS、proposal weights、full-revaluation challenger、alternative DGP 与 dependence/recovery sensitivity；模拟最坏路径不是 VaR/ES 或真实可成交损失证据。 | `FORM-RES04-CH09-001`—`017`；17项核心关系已核为`verified_concept_only` |

## Ch01 原始扫描复核

以下 10 项已由 OCR 语义与原始扫描 PDF 关键页交叉核对。状态 `verified_concept_only` 只确认概念、关系和前提，不授权转录公式、采用书中参数或实现衍生品模型。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH01-001` | `1-2, 9-10` | 期望/积分的 iid 样本均值估计、强大数一致性、有限二阶矩 CLT、样本标准差与 `n^{-1/2}` 标准误。 | simulation artifact 必须保存 estimand、iid/矩条件、variance estimator、路径数和区间；增加一位精度的成本不能被忽略。 | `verified_concept_only` |
| `FORM-RES04-CH01-002` | `4, 9` | 欧式/亚式期权示例先固定 payoff、discount、风险中性 DGP、离散观察网格，再对路径 payoff 求均值；期望本身在定价假设成立前不等于价格。 | DGP、measure、payoff、grid 与 estimand 必须分字段记录；synthetic pricing 示例不迁移为 BTC/美股 alpha。 | `verified_concept_only` |
| `FORM-RES04-CH01-003` | `10-12` | 无偏估计器效率需同时比较单次方差和固定/随机计算时间；工作量归一化指标使用方差与期望计算时间的乘积，并依赖独立同分布 replication 等条件。 | 同预算 challenger 比较需保存 wall-time 分布、完成路径数、方差和依赖结构，不能只比较固定路径数的点估计。 | `verified_concept_only` |
| `FORM-RES04-CH01-004` | `12-13` | 有限样本偏差、ratio-of-means 偏差与离散化偏差来源不同；部分偏差随样本数消失，模型离散偏差需缩小步长或使用精确转移。 | 抽样误差、估计器偏差和模型/离散偏差分别报告；更多路径不能消除错误时间步或错误转移。 | `verified_concept_only` |
| `FORM-RES04-CH01-005` | `17-19` | 计算预算在减小偏差与增加 replication 之间分配；MSE 由 squared bias 与 variance 共同决定，最优收敛率依赖偏差阶、单路径成本阶及附加正则条件。 | 预算/步长规则必须预注册并做 sensitivity；书中渐近阶不作为项目路径数、网格或 promotion 阈值。 | `verified_concept_only` |
| `FORM-RES04-CH01-006` | `19, 21, 23, 25` | 复制定价依赖可预测、自融资、可达 payoff、边界条件和无套利；复制成本/PDE 结论还隐含连续交易、流动性和模型正则性。 | 当前系统无衍生品复制/Greeks/结算合同，故仅作假设审查；不得把理论无摩擦复制描述为可成交 PnL。 | `verified_concept_only` |
| `FORM-RES04-CH01-007` | `25, 27, 29` | stochastic discount factor 与等价 martingale measure 连接无套利；风险中性期望要求可达价格过程、numeraire 与 measure 一致，客观漂移和风险中性漂移不可混用。 | 每个估值/压力模拟记录 physical/risk-neutral measure、discount asset、drift source 和可达性；价格期望不等于现实收益预测。 | `verified_concept_only` |
| `FORM-RES04-CH01-008` | `31-32` | 有股息时应使用含再投资分红的总回报过程；连续 dividend yield 改变风险中性漂移，持有单股并提取分红不再是自融资。 | 美股复权、total-return 与 cash-dividend ledger 必须区分；未来复权因子和遗漏现金流均属 PIT/账本错误。 | `verified_concept_only` |
| `FORM-RES04-CH01-009` | `32-36` | change of numeraire 同时改变概率测度、贴现表示与漂移；在新测度下相对 numeraire 的可达价格成为 martingale。 | 任何测度变换都需版本化 likelihood ratio、numeraire、measure-specific dynamics 与 integrability 条件，不能只改 drift 字段。 | `verified_concept_only` |
| `FORM-RES04-CH01-010` | `36-38` | market price of risk 连接客观漂移、无风险利率与风险暴露；完备市场可唯一复制，不完备市场存在不可对冲风险、多个定价测度和非唯一价格。 | 非唯一模型输出应报告范围/challenger/不可对冲风险；无套利约束不等于唯一真实价值或交易 edge。 | `verified_concept_only` |

## Ch02 原始扫描复核

以下 18 项由 OCR 语义与原始扫描 PDF 印刷页 `39-77` 全章逐页交叉核对。它们关闭的是算法前提、状态、支撑、随机维数和数值边界；书中历史生成器常数、近似系数与实现细节仍须对当前库、平台和测试向量独立验证。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH02-001` | `39-41` | 伪随机序列由确定性状态递推产生；理想 uniform 序列同时要求各边际均匀及相互独立，有限统计检验通过不能证明二者。 | RNG evidence 保存 family/version/state/seed 与检验范围；“同 seed 可复现”不等于独立、均匀或适合并行模拟。 | `verified_concept_only` |
| `FORM-RES04-CH02-002` | `41-43` | 有限状态确定性递推最终必然进入循环；period、初始状态和吸收/零陷阱共同限制可用序列长度。 | 预先登记 stream budget、cycle/zero-state guard 与 restart state；单次实验消耗只占可证明 period 的小部分。 | `verified_concept_only` |
| `FORM-RES04-CH02-003` | `43-45` | 线性同余生成器的满周期依赖 modulus、multiplier、increment 与数论条件；参数组合而非算法名称决定周期。 | 禁止迁移书中历史常数；当前实现只采用已版本化库及其测试向量、period/substream 合同。 | `verified_concept_only` |
| `FORM-RES04-CH02-004` | `45-47` | 递推实现会受整数溢出、浮点舍入、运算顺序和机器字长影响；代数等价表达不保证跨平台产生同一比特序列。 | 保存 runtime/library/platform/bit generator 与 golden vectors；跨平台复现失败必须显式而非静默重播。 | `verified_concept_only` |
| `FORM-RES04-CH02-005` | `47-49` | skip-ahead 可把一条长序列划分为不重叠 substream，并支持 common random numbers 的路径对齐；任意选择不同 seed 不证明流间独立。 | 并行 worker 使用可审计 stream id、jump rule、allocation 与 overlap test；CRN 保存逐 draw 对齐和消费计数。 | `verified_concept_only` |
| `FORM-RES04-CH02-006` | `49-53` | 线性生成器在有限维空间形成 lattice；spectral、discrepancy 与统计检验只覆盖特定缺陷，低维通过不能排除高维结构。 | RNG qualification 保存维度、样本量、检验族和失败模式，并与目标模拟维数匹配；测试不能包装成通用随机性证明。 | `verified_concept_only` |
| `FORM-RES04-CH02-007` | `53-55` | combined generator 与 multiple-recursive generator 可延长周期并改善部分 lattice 结构，但状态初始化、参数及实现平台仍决定实际序列。 | 生成器切换视为 DGP/version 变化；需独立 baseline、substream、restart、cross-stream 与性能证据。 | `verified_concept_only` |
| `FORM-RES04-CH02-008` | `56-58` | inverse transform 以 generalized inverse 处理 CDF 的跳跃和平坦区间；连续单调映射通常每个样本消耗一个 uniform，并保留有利于 CRN/QMC 的结构。 | 固定 quantile convention、ties、`U=0/1` 端点和 uniform consumption；离散分布不得假设普通反函数唯一。 | `verified_concept_only` |
| `FORM-RES04-CH02-009` | `58-60` | 无闭式逆函数时需 root finding/近似；离散表查找和条件分解会把数值误差、排序、缓存及维度顺序传入样本。 | 版本化 inverse/CDF library、容差、tail region、lookup ordering 与 conditional order，并用 distributional oracle 验证。 | `verified_concept_only` |
| `FORM-RES04-CH02-010` | `60-62` | acceptance-rejection 要求 proposal 覆盖 target 支撑且存在有限常数使 target 密度受 proposal 包络；接受概率由密度比决定。 | 保存 target/proposal/support、包络常数证明、log-density 与 accept rule；支撑缺口或包络失效一律 fail-closed。 | `verified_concept_only` |
| `FORM-RES04-CH02-011` | `62-64` | 平均接受率与包络松紧直接决定候选次数；总效率还包括 target/proposal 计算成本，squeeze 可减少昂贵的精确密度求值。 | 报告 acceptance、candidates/output、uniforms/output、wall-time 和 squeeze 命中率；稀有条件事件的粗 rejection 单独压力测试。 | `verified_concept_only` |
| `FORM-RES04-CH02-012` | `64-65` | rejection 每个输出消耗随机数量的 uniform，映射通常不连续且不单调，因此会破坏固定维 QMC 构造并削弱 antithetic coupling。 | 任何 QMC/antithetic 方案必须声明 sampler 的随机维数和连续性；不满足时回退 fixed-dimension inverse/conditional sampler 或普通 MC。 | `verified_concept_only` |
| `FORM-RES04-CH02-013` | `65-67` | 多元正态 covariance 必须半正定；奇异 covariance 的分布位于低秩子空间，不存在全维 Lebesgue 密度。 | covariance evidence 保存 symmetry/PSD/rank/eigen diagnostics；奇异情形不得套用 full-density likelihood 或静默 jitter。 | `verified_concept_only` |
| `FORM-RES04-CH02-014` | `66-68` | 正态向量在线性变换下仍为正态，条件分布和矩母函数关系依赖均值、covariance block 与可逆性条件。 | 条件模拟保存 partition/order、求解器、rank/conditioning 和 conditional covariance 检查；不可逆块使用显式降秩处理。 | `verified_concept_only` |
| `FORM-RES04-CH02-015` | `68-70` | Box-Muller 用两个 uniform 生成一对 normal；Marsaglia-Bray 通过 rejection 避免部分函数求值，但 uniform 消耗无上界且含缓存/配对状态。 | normal sampler 保存算法、pair cache、端点处理与 draws/output；固定维 QMC 不使用随机长度 rejection 版本。 | `verified_concept_only` |
| `FORM-RES04-CH02-016` | `70-72` | normal CDF/quantile 的分段近似在中心和尾部具有不同 absolute/relative error；历史近似系数与精度声明依赖实现区域。 | 使用受维护数学库并锁定版本；分别验证中心、双尾、round-trip、单调性和端点，不从扫描页转录系数。 | `verified_concept_only` |
| `FORM-RES04-CH02-017` | `72-75` | 多元正态生成归结为寻找满足 `AA^T=Σ` 的 factor；Cholesky 需要正定性，变量顺序会改变 factor，半正定/近奇异矩阵会出现零主元和舍入敏感。 | 保存 covariance vintage、factor method/order、rank、condition、residual 与失败策略；禁止用未披露 jitter 把无效 covariance 伪装为有效。 | `verified_concept_only` |
| `FORM-RES04-CH02-018` | `75-77` | 特征分解给出按 eigenvalue 排序的 principal factors；截断提供均方意义下的低维近似及 explained variance，但会改变原 covariance 与尾部联合分布。 | PCA/factor reduction 保存 retained rank、eigen spectrum、covariance residual、tail/dependence challenger；高 explained variance 不等于尾部风险准确。 | `verified_concept_only` |

## Ch03 原始扫描复核

以下 31 项由 OCR 语义与原始扫描 PDF 印刷页 `79-184` 全章逐页交叉核对。它们只确认路径构造、状态、测度、漂移、网格、跳跃、校准和精确性边界；不批准利率、衍生品、跳跃或 synthetic-market 模型实现，也不迁移书中历史 LIBOR 约定、公式常数、参数或案例结果。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH03-001` | `79-82` | Brownian motion 具有连续路径、独立正态增量；随机游走构造只在指定日期精确给出联合分布，日期间插值不是同一连续路径法则，Euler 对一般 SDE 即使在网格点也可能有误差。 | `SyntheticPathEvidence` 区分 exact-at-grid、between-grid interpolation 与 SDE approximation；每种目标分别保存网格、转移与误差。 | `verified_concept_only` |
| `FORM-RES04-CH03-002` | `82-84` | Brownian covariance 为时间最小值结构；顺序增量构造是该 covariance 的特定 factor，利用结构可把通用矩阵分解成本降为线性递推。 | 保存 covariance、factor/order 和复杂度；同一边际正态不证明时间联合结构正确。 | `verified_concept_only` |
| `FORM-RES04-CH03-003` | `84-87` | Brownian bridge 以端点条件分布递归补点，与顺序构造在固定网格上具有同一联合 law，但改变 normal 坐标的时间重要性；本身不自动降方差。 | QMC/CRN 记录 coordinate ordering、bridge schedule 与同预算 baseline；不把构造顺序称为独立精度提升。 | `verified_concept_only` |
| `FORM-RES04-CH03-004` | `87-91` | PCA/Karhunen–Loève 按解释方差排序路径坐标，截断可降有效维度但不再保持原离散联合 law，且一般矩阵构造成本高于随机游走。 | 保存 retained modes、variance ratio、covariance/path residual 和计算成本；截断路径只作为近似 challenger。 | `verified_concept_only` |
| `FORM-RES04-CH03-005` | `91-94` | 多维 Brownian 需 covariance factor；时间变化 covariance 可能每步重分解。可分离结构可用 Kronecker/PCA，但横截面维度增加会稀释前几个因子的解释率。 | 多资产 DGP 保存 time/cross covariance、PSD/rank/factor vintage、重分解策略与 residual；不得凭少数 PCA 因子覆盖尾部依赖。 | `verified_concept_only` |
| `FORM-RES04-CH03-006` | `95-98` | GBM 的价格漂移与 log-price 漂移相差 Itô 修正；固定网格有精确 lognormal 转移。lognormal 参数不是价格均值/方差，路径长期增长与期望增长可因右尾偏斜分离。 | 明确 state、drift convention、measure、log/level moments 与 exact transition；不能用均值路径代表典型路径。 | `verified_concept_only` |
| `FORM-RES04-CH03-007` | `98-101` | 风险中性股票漂移随利率和股息改变；FX、商品、forward/futures 取决于 numeraire、carry 和利率随机性，简单的 forward=futures 只在附加条件下成立。 | 估值 DGP 保存 asset class、carry/cash flows、measure/numeraire 和随机利率处理；定价漂移不得作为 physical Forecast。 | `verified_concept_only` |
| `FORM-RES04-CH03-008` | `101-104` | Asian、barrier、lookback 等路径 payoff 的离散监控与连续监控是不同 estimand；只在网格精确模拟底层仍会产生 monitoring/discretization bias。 | 路径事件证据固定 observation clock、continuous/discrete target、bridge/interpolation 与 miss-rate sensitivity。 | `verified_concept_only` |
| `FORM-RES04-CH03-009` | `104-106` | 非平坦期限结构要求从初始 discount/forward curve 初始化状态；可借 bond/forward ratio 构造路径，但输入曲线和计息约定决定初始一致性。 | 保存 curve vintage、bootstrap、day-count/accrual、bond/forward identity residual 与 PIT 时间。 | `verified_concept_only` |
| `FORM-RES04-CH03-010` | `106-108` | deterministic/local volatility 可匹配有限期权价格但校准通常非唯一；一般不再有精确转移，Euler/log-Euler 引入离散偏差并可能改变 positivity。 | 校准 evidence 保存 instruments、objective、nonuniqueness、regularization、scheme/grid 与 independent repricing；匹配市场不证明 DGP 真实。 | `verified_concept_only` |
| `FORM-RES04-CH03-011` | `108` | 多资产 GBM 依赖完整 covariance；change of numeraire 只有在 payoff 对资产具有相应齐次性时才可能降维，含固定 strike 比率的 payoff 未必减少状态维数。 | 任何降维声明保存 payoff homogeneity proof、numeraire、remaining state 与原模型 challenger。 | `verified_concept_only` |
| `FORM-RES04-CH03-012` | `109-112` | Gaussian short-rate 模型具有条件正态精确转移，均值回复模型可有 stationary law；Euler 是可比较近似，初始状态是否来自 stationary distribution 会改变路径分布。 | 保存 exact/Euler 标志、transition、initialization、stationarity assumption 与 grid challenger。 | `verified_concept_only` |
| `FORM-RES04-CH03-013` | `112-115` | 时间变化漂移可拟合初始利率曲线；零息债价格呈 affine 形式。短率与其时间积分可联合正态模拟，从而在 Gaussian 情形避免单独数值积分折现偏差。 | 利率 DGP 保存 curve calibration、bond residual、joint rate-integral covariance 与 discount-factor validation。 | `verified_concept_only` |
| `FORM-RES04-CH03-014` | `115-117` | forward measure 改变短率漂移并把对应 maturity bond 作为 numeraire；确定性折现表示只在该测度和现金流到期匹配时成立。 | 每个 payoff 记录 maturity-specific measure/numeraire、drift 与 discount identity；禁止跨测度复用路径而不加权。 | `verified_concept_only` |
| `FORM-RES04-CH03-015` | `117-120` | 多因子 Gaussian 模型的完整状态向量可 Markov，而标量短率未必 Markov；单因子强制债券收益瞬时完全相关，多因子用状态矩阵/因子 rank 放松该约束。 | 保存 state vector、transition matrix、observability/rank、bond-loading 与 correlation residual；不能只存短率。 | `verified_concept_only` |
| `FORM-RES04-CH03-016` | `121-125` | square-root diffusion 的零边界行为受 Feller 条件控制；Euler 截断/取正不等于原转移。常系数情形可由缩放 noncentral chi-square 精确采样。 | 保存 boundary regime、exact/approximate sampler、negative-state policy 与 transition-distribution tests；静默取正禁止。 | `verified_concept_only` |
| `FORM-RES04-CH03-017` | `125-128` | noncentral chi-square 可经 Poisson mixture 与 chi-square/gamma 采样；不同 gamma/Poisson 算法的随机消耗、接受率和历史常数影响复现与效率。 | sampler registry 锁定库版本、random dimension、acceptance、tail tests 与 golden vectors；不转录书中历史常数。 | `verified_concept_only` |
| `FORM-RES04-CH03-018` | `128-132` | CIR 债券价格具有 exponential-affine/Laplace 结构；联合短率与折现积分可借数值变换反演，但实现复杂。时间变化系数通常破坏闭式转移，分段常数/平均水平是近似；换测度后参数也改变。 | 标注 closed-form/numerical inversion/approximation、容差、curve fit、measure-specific parameters 与 independent bond/discount checks。 | `verified_concept_only` |
| `FORM-RES04-CH03-019` | `132-134` | 独立 CIR 因子可构造多因子 affine 模型，更一般相关 affine 模型条件更强；squared-Gaussian 和 CEV 变换只在特定参数/domain 下成立，近零边界尤其敏感。 | 保存 factor dependence、transform domain/Jacobian、boundary behavior 与 inverse checks；形式相似不授权模型互换。 | `verified_concept_only` |
| `FORM-RES04-CH03-020` | `135-138` | jump-diffusion 必须区分跳前 `S(t-)` 与跳后 `S(t)`；正乘性 jump 可保持价格非负。compound-Poisson 设定要求 jump size、count 与 Brownian 的独立性，风险中性漂移需含 jump compensator。 | jump DGP 保存 pre/post state、jump law、dependence、compensator、measure 与 positivity；不得沿用纯 GBM drift。 | `verified_concept_only` |
| `FORM-RES04-CH03-021` | `138-141` | 固定日期的 compound jump 可聚合 count/size 得到精确终值，但不识别区间内 jump times；显式 jump-time 模拟用于路径 payoff。若 intensity/jump law 依赖状态，简单聚合不再精确。 | 记录 estimand 是否需要 jump epochs、aggregation exactness、state dependence 与 event ordering。 | `verified_concept_only` |
| `FORM-RES04-CH03-022` | `141-144` | 非齐次 Poisson 可经 integrated intensity 反演或 thinning；thinning 需要对目标区间有效的强度上界，接受率决定成本。 | 保存 intensity vintage、integral/inverse tolerance、upper-bound proof、acceptance 与 missed-event tests。 | `verified_concept_only` |
| `FORM-RES04-CH03-023` | `144-148` | infinite-activity Lévy 过程不能逐 jump 穷举，应从 increment law 或受控截断/近似采样；gamma、variance-gamma、NIG 等 time change 的小跳结构不同，stable law 可能不存在普通方差或均值。 | 保存 activity/moment domain、increment sampler、truncation residual 与 tail challenger；无有限矩时禁用普通 variance/CLT 诊断。 | `verified_concept_only` |
| `FORM-RES04-CH03-024` | `149-153` | HJM 的状态是整条 forward curve；无套利漂移由 volatility 结构决定，而非独立自由参数。连续曲线一般不能精确有限维模拟。 | `CurveSimulationEvidence` 保存 curve state、volatility surface、drift identity 与 finite-dimensional approximation；漂移残差作为 fail-closed 检查。 | `verified_concept_only` |
| `FORM-RES04-CH03-025` | `153-157` | HJM 数值实现同时离散 calendar time 和 maturity；初始离散 forward 应与 interval-average/discount bonds 一致，否则起点即错价。 | 保存双网格、插值、initial bond reconstruction 与 residual；不能只报告 time step。 | `verified_concept_only` |
| `FORM-RES04-CH03-026` | `157-164` | 离散 HJM 漂移应由折现债券 martingale 条件构造，而非朴素连续漂移近似；实现中 volatility/drift 应从旧状态计算后再更新，relative-maturity 索引、accrual 和 payment date 必须对齐。 | 版本化 discrete drift、update order、index convention、cash-flow clock 与 martingale tests；更多路径不修复人工套利。 | `verified_concept_only` |
| `FORM-RES04-CH03-027` | `165-169` | simple forward rate 定义在 tenor/accrual 区间并与 bond ratio 相连；任意时点的 forward rates 不单独确定最短 discount bond。章节以 LIBOR 作为近似无风险基准属于历史设定。 | 项目若处理现代利率必须使用当前 benchmark、fallback 与 multi-curve 合同；保存 tenor/day-count 和 shortest-bond state，禁止直接迁移历史 LIBOR 设定。 | `verified_concept_only` |
| `FORM-RES04-CH03-028` | `169-172` | LMM 在 spot measure 与 terminal/forward measure 下具有不同无套利 drift；选定 numeraire 后相对债券为 martingale，单个 forward 仅在其对应 forward measure 下可为 lognormal martingale。 | 每条路径保存 measure/numeraire、active tenor set、drift summation range 与 covariance；禁止混用 measure-specific dynamics。 | `verified_concept_only` |
| `FORM-RES04-CH03-029` | `172-174` | caplet 在对应 forward measure、确定性 volatility 等条件下可用 Black 公式并反推 implied volatility；一般 payoff 需选择合适 numeraire 并模拟。forward swap rate 通常不能同时保持确定性 volatility，caplet 与 swaption 闭式便利存在模型取舍。 | calibration 保存 instrument family、measure、closed-form assumptions、implied-vol inversion 与 cross-instrument residual；不把单类拟合当全曲面一致。 | `verified_concept_only` |
| `FORM-RES04-CH03-030` | `174-180` | LMM 仍需时间离散；level Euler 可产生负 rate，log-Euler 保正但仍有 bias。tenor 边界取右连续约定会改变 drift sum。通常难以调整 rate drift 使离散债券严格 martingale，可改模拟 deflated bonds/差分变量以保 martingale；不同 measure 的 bias/variance 不同。 | 保存 scheme/state variable、positivity、tenor-boundary convention、martingale residual、caplet bias/CI、measure 与工作量；解析 Black 价格可作离散 bias oracle。 | `verified_concept_only` |
| `FORM-RES04-CH03-031` | `180-184` | caplet implied volatility 约束各 maturity volatility norm，而多因子主要增加跨期限 correlation 自由度；swaption/历史相关用于识别相关结构。stationary/PCA 因子常呈 level/slope/curvature，但闭式/近似校准与 simulation calibration 成本不同。 | 保存 cap/swaption inputs、volatility/correlation identifiability、factor rank/PCA vintage、level-slope-curvature residual 与 calibration cost；多因子不自动改善边际拟合或现实预测。 | `verified_concept_only` |

## Ch04 原始扫描复核

以下 14 项由 OCR 语义与原始扫描 PDF 36 个关键页交叉核对。它们只定义候选方法、估计前提和证据合同；任何方法仍须预注册、同 estimand 同成本比较，并用独立 replication 验证 bias、variance 与 interval coverage。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH04-001` | `185` | 方差缩减依赖问题结构；降低点估计方差可能引入 replication 依赖并破坏方便的标准误估计。 | 每个候选先声明利用的结构、依赖单元和有效 replication；效率提升与区间有效性分别验收。 | `verified_concept_only` |
| `FORM-RES04-CH04-002` | `186-187` | 单 control variate 要求已知 `E[X]`；固定系数保持无偏，最优线性系数由 covariance/variance 决定，收益取决于相关强度及额外计算成本。 | control 的期望、估计来源、相关稳定性和成本必须版本化；书中相关系数示例不迁移为阈值。 | `verified_concept_only` |
| `FORM-RES04-CH04-003` | `196, 200` | 估计 control 系数在大样本下可保留渐近 CLT，但有限样本会因同样本拟合产生偏差；multiple controls 还需处理维度、共线性和样本量。 | 系数拟合使用独立 pilot/fold 或报告同样本偏差；保存 control 数量、rank/conditioning、拟合样本与有效自由度。 | `verified_concept_only` |
| `FORM-RES04-CH04-004` | `203-205` | nonlinear control 可用 delta method 作大样本线性化；渐近等价不保证有限样本方差降低，强非线性可能需要很大样本。 | 非线性调整作为独立 challenger，必须报告有限样本 bias/coverage，不能凭渐近展开直接上线。 | `verified_concept_only` |
| `FORM-RES04-CH04-005` | `205-206, 209` | antithetic 通过保持边际分布、在配对内引入负依赖降方差；独立单元是 pair mean 而非 `2n` 个单值，收益须按等成本和配对 covariance 判断。 | RNG artifact 保存 pairing transform、pair id 与 pair-level variance/CI；禁止把配对样本当独立样本扩大 `n`。 | `verified_concept_only` |
| `FORM-RES04-CH04-006` | `209-210, 217` | stratified estimator 需要已知 stratum probability、条件采样和正确权重；proportional allocation 不增方差，最优 allocation 还依赖各层标准差。 | 分层边界、PIT 概率、条件 sampler、allocation 与层内方差必须冻结；最优 allocation 不得用 holdout 反推。 | `verified_concept_only` |
| `FORM-RES04-CH04-007` | `214, 217, 220, 232` | 条件采样可能昂贵；细化 strata 可降低残余方差，却减少每层样本并削弱方差估计，且高维全分层会维数爆炸。 | 分层设计同时报告 acceptance/cost、empty/small strata、层内样本和 variance-estimation error；优先预注册低维风险投影。 | `verified_concept_only` |
| `FORM-RES04-CH04-008` | `233-235` | poststratification 用独立样本的随机层计数配合已知层概率重新加权；ratio estimator 有有限样本偏差，仅在大样本下接近 proportional stratification。 | 保存零计数处理、层概率来源、ratio bias 与 coverage；不能把渐近等价描述为小样本保证。 | `verified_concept_only` |
| `FORM-RES04-CH04-009` | `236, 240, 243` | Latin hypercube 只保证每个一维边际分层，通过随机置换形成跨样本依赖；方差可因 covariance 增减，效果取决于低阶/加性结构。 | LHS 需按整个设计重复生成独立 replicate 估计误差；不得把行当 iid，也不得把书中案例倍数迁移。 | `verified_concept_only` |
| `FORM-RES04-CH04-010` | `243, 245` | path/moment matching 强制有限样本矩或 martingale 关系，但会改变路径分布并通常引入渐近消失的偏差；不同调整还在 positivity 与 martingale 保持间取舍。 | 任何路径调整保存原/后分布、约束、positivity、martingale 与 bias 检验；模拟一致性不等于市场真实。 | `verified_concept_only` |
| `FORM-RES04-CH04-011` | `252-254` | weighted Monte Carlo 以权重满足矩约束；权重解依赖可行性、目标函数和矩阵 rank，maximum-entropy 可保正权，least-squares 与 control variate 密切等价。 | 保存约束、目标、feasibility、rank/condition、weight dispersion/negative weight 与 baseline；校准不是自动降方差或模型正确。 | `verified_concept_only` |
| `FORM-RES04-CH04-012` | `255-257` | importance sampling 要求 proposal 覆盖原分布有效支撑，并以完整 likelihood ratio 修正；无偏不保证有限二阶矩，路径模型权重是逐转移密度比乘积。 | proposal、support、log-weight、normalization、transition density 与 estimand 全部可审计；漏一段权重即 fail-closed。 | `verified_concept_only` |
| `FORM-RES04-CH04-013` | `256, 260, 278` | 理论 zero-variance proposal 依赖未知目标而不可直接使用；错误 proposal 可增加乃至造成无限方差，偏斜 likelihood ratio 会使样本标准差低估风险、CLT coverage 很慢。 | 同时报告 weight tail、ESS/max weight、second-moment stress、CI coverage 与 defensive mixture；无有限方差证据不得称增效。 | `verified_concept_only` |
| `FORM-RES04-CH04-014` | `260-262, 265, 269, 274, 276, 278-279` | exponential tilting/change of drift 和 path-dependent optimal path 是问题特定近似；高维可参数化降维，但最优性取决于 cumulant domain、payoff/rare event 与优化稳定性。 | 预注册 twist family、目标事件、参数域、优化器、fallback 和朴素 MC challenger；示例 drift、strike 和降维节点均不迁移。 | `verified_concept_only` |

## Ch05 原始扫描复核

以下 26 项由 OCR 语义与原始扫描 PDF 印刷页 `281-337` 全部有内容页面逐页交叉核对；目录章界到 `338`，原载体没有印刷内容页 `338`。条目只确认 QMC 适用前提、构造、随机化、误差和有效维度边界；不批准 QMC 实现，不迁移书中方向数、生成向量、skip、样本数、误差倍数或历史算法表。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH05-001` | `281-283` | QMC 把模拟写成单位超立方上的有限维积分并以确定性点集求平均；若单个输出所需 uniform 数无有限上界，如 acceptance-rejection，固定维 QMC 不能直接适用。 | `QMCEvidence` 保存 integrand mapping、finite dimension、uniform consumption bound 和端点规则；随机维 sampler 必须回退或重构。 | `verified_concept_only` |
| `FORM-RES04-CH05-002` | `283-285` | discrepancy 衡量特定集合族上的经验占比误差；ordinary/star/isotropic discrepancy 不同，轴对齐定义对旋转不具不变性。点集固定 `n` 与无限 sequence 的最优阶也不同。 | 保存 discrepancy definition、point-set/sequence、dimension、sample-size schedule 与 coordinate orientation；不能只写“低差异”。 | `verified_concept_only` |
| `FORM-RES04-CH05-003` | `285-287` | 低差异渐近界含随维度增长的常数和对数因子；有限样本、高维表现不能仅由渐近阶推出。Van der Corput 用 base-`b` radical inverse 构造一维嵌套序列，base 影响有限样本均匀性。 | 不迁移书中 base/skip；当前候选按实际维度、预算和完整 `n` 路径做预注册 benchmark。 | `verified_concept_only` |
| `FORM-RES04-CH05-004` | `287-290` | Koksma–Hlawka 将绝对积分误差上界写成 Hardy–Krause variation 与 star discrepancy 的乘积，但 variation/discrepancy 常难计算、上界可极松且要求有限 variation。 | 理论界仅作适用性审查，不能替代 randomized replicate error、coverage 或真实误差 oracle。 | `verified_concept_only` |
| `FORM-RES04-CH05-005` | `290-292` | barrier/indicator、边界不连续和旋转集合可使 variation 无限或显著改变界；轴向坐标选择因此直接影响 QMC，而非无关实现细节。 | 保存 payoff discontinuity、boundary orientation、rotation/change-of-variable 与原 mapping challenger。 | `verified_concept_only` |
| `FORM-RES04-CH05-006` | `290-293` | `(t,m,d)`-net 和 `(t,d)`-sequence 以 base-`b` elementary intervals 定义分层均匀性；较小 `t` 更好，但 base、维度与可用点数块共同决定性质。 | 序列 registry 保存 family/base/`t`/dimension、合法 block sizes、start index 与生成库版本。 | `verified_concept_only` |
| `FORM-RES04-CH05-007` | `293-295` | Halton 用互素 bases 的 Van der Corput 坐标，Hammersley 以固定 `n` 换一维改进；高维大 bases 会形成长单调段和差投影，leap 修复对参数敏感。 | 高维投影做 pairwise discrepancy/visual/数值诊断；禁止从案例选择 leap、base 或跳过长度。 | `verified_concept_only` |
| `FORM-RES04-CH05-008` | `296-297` | radical-inverse 的 digit 顺序、zero point、start index、递增 carry 与浮点实现共同决定实际序列；数学同族不保证库间同点。 | 保存 exact generator/version/start/zero/digit precision 与 golden points；切换库视为实验 DGP 变化。 | `verified_concept_only` |
| `FORM-RES04-CH05-009` | `297-303` | Faure 在共同 prime base 下用 generator matrices 扰动同一 Van der Corput 段，可获较好 `t`，但高维投影会周期性重复；矩阵、digit convention 与起始点影响实现。 | 不实现扫描页算法；候选仅用维护库并验证 projections、rank、start/skip 和 reference vectors。 | `verified_concept_only` |
| `FORM-RES04-CH05-010` | `303-308` | Sobol 以 base 2、primitive polynomial、direction numbers 和 generator matrices 构造 digital sequence；方向数初始化决定多维投影，算法名称不足以唯一标识序列。 | 保存 direction-number table hash、polynomial set、dimension limit、bit depth、start/skip 与 first-point vectors。 | `verified_concept_only` |
| `FORM-RES04-CH05-011` | `307-309` | Gray code 使相邻索引只改变一个 bit，可递归 XOR 更新点并提高速度；任意 start index 仍需正确初始化 Gray state，性能优化不改变所需序列定义。 | restart/partition 测试验证 index-to-point、sequential/random access 和 worker ranges；速度不替代序列一致性。 | `verified_concept_only` |
| `FORM-RES04-CH05-012` | `309-312` | Sobol 初始方向数需满足多维均匀性性质；同 polynomial 下更换初始化可改变低阶点和投影，历史表甚至只在部分维度满足声明条件。 | 禁止迁移书中表；使用当前维护表并保存来源/hash，做维度上限和投影资格测试。 | `verified_concept_only` |
| `FORM-RES04-CH05-013` | `312-316` | Sobol 的 `t` 随 primitive-polynomial degrees 和维度变化，给定表达可能不是最小 `t`；Niederreiter/generalized digital constructions 改善理论参数但实现/表仍需独立验证。 | family 选择基于当前库、维度、实测误差和重现性，不按历史理论排名直接批准。 | `verified_concept_only` |
| `FORM-RES04-CH05-014` | `316-318` | rank-1/higher-rank lattice rule 是固定大小点集，要求 generator 与 `n` 的整数条件；Korobov 形式简化参数但质量依赖生成向量，完整周期思想与 PRNG 的“小周期占用”目标不同。 | 保存 `n`、rank、generator vector、coprimality、construction source/hash；书中旧乘数不得迁移。 | `verified_concept_only` |
| `FORM-RES04-CH05-015` | `318-320` | lattice 积分误差可由 dual-lattice Fourier modes 表示，偏好平滑且边界周期的 integrand；非周期、不连续 payoff 会破坏该解释，固定规则可扩展但需特定嵌套构造。 | 保存 smoothness/periodicity、periodization transform、dual diagnostics 与 discontinuous baseline；不凭 lattice 名称推断适用。 | `verified_concept_only` |
| `FORM-RES04-CH05-016` | `320-323` | randomized QMC 通过保持各点均匀分布来获得无偏积分估计；独立随机化整个 `n` 点设计才形成独立 replicate。点内和点间仍相关，不能把 `n×R` 点当 iid。 | 保存 randomization family/seed/replicate id、points per replicate 和 replicate-level variance/CI。 | `verified_concept_only` |
| `FORM-RES04-CH05-017` | `320-323` | random shift、digit permutation、nested scramble 与 linear permutation 保留的 net 性质、计算/内存成本和方差不同；随机化可能降误差，也可能因 integrand 而比 MC 方差更高。 | 多种随机化作为预注册 challengers，报告 bias、replicate variance、CI coverage、生成成本和内存。 | `verified_concept_only` |
| `FORM-RES04-CH05-018` | `324-326` | 金融测试的 nominal dimension 可来自资产数或时间步数，但相关结构和表示方式决定真实难度。方法比较需固定一组问题、真值/高精度 oracle 和 RMSE/RMS-relative-error 定义。 | benchmark 保存 problem suite、oracle lineage、dimension source、correlation、payoff、cost 与 metric；单一案例不外推。 | `verified_concept_only` |
| `FORM-RES04-CH05-019` | `325-328` | 确定性 QMC 误差随 `n` 可非单调且对 family、skip、合法块大小和参数敏感；案例中的近 `n^{-1}` 斜率和倍数只属于特定问题/选点。 | 输出全预注册 `n` 网格曲线和 worst/median，不事后挑有利点数、斜率或方法。 | `verified_concept_only` |
| `FORM-RES04-CH05-020` | `328-329` | 运行均值可出现长平台并远离真值，基于局部波动的自动停止会误判收敛；跳过初段只能减轻而不能证明消除。 | 确定性 QMC 禁用单路径 plateau stopping；使用独立 randomized replicates、外部 oracle 和预算上限。 | `verified_concept_only` |
| `FORM-RES04-CH05-021` | `329-331` | randomized QMC 可用独立 replicate variance；公平比较应按 `n×variance` 或总工作量归一，并与 ordinary MC、variance-reduced MC 同时比较，而非只与最朴素 MC。 | 报告 generator+valuation wall-time、replicate count、variance/CI/coverage 和同预算 baselines。 | `verified_concept_only` |
| `FORM-RES04-CH05-022` | `331-333` | 低编号坐标常有更好均匀性，坐标分配应把重要随机输入放前；但“重要性”取决于 sequence family、integrand 和相关结构，反序分配案例并非通则。 | 保存 variable-to-coordinate map、importance rationale、permutation challengers 与 sensitivity；禁止事后择优。 | `verified_concept_only` |
| `FORM-RES04-CH05-023` | `331-332` | 旋转/change of variables 可在不改概率 law 的情况下显著改变 QMC 误差，因为 discrepancy 轴向；对普通 MC 同 law 的表示未必对 QMC 等价。 | transform registry 保存 orthogonality/Jacobian、law invariance、orientation 与 inverse tests，并保留原 mapping baseline。 | `verified_concept_only` |
| `FORM-RES04-CH05-024` | `333-336` | Brownian bridge 把终值/粗尺度分配给早期坐标，PCA 最大化前坐标解释方差；两者降低的是 effective dimension，不是 nominal dimension，且效果依赖 payoff、covariance 和路径功能。 | 保存 path construction、coordinate map、explained variance/effective-dimension diagnostics 与 payoff-specific error curves。 | `verified_concept_only` |
| `FORM-RES04-CH05-025` | `334-335` | 针对 payoff 的解析变量变换可把特定对称 lognormal 几何平均问题压到一维，但这是问题特定代数，不代表一般期权、BTC 或美股风险模型都可降维。 | 每个降维需证明 change-of-variable、Jacobian/law、remaining dimension 和适用 payoff；不可迁移示例公式。 | `verified_concept_only` |
| `FORM-RES04-CH05-026` | `335-337` | 高 nominal dimension 下 QMC 有效通常因为高阶变量重要性递减或 integrand 近似由少量低阶项组成。推荐先用普通 MC/方差缩减理解问题，再把其重构为积分后尝试 randomized QMC。 | 当前项目保持 `rejected_for_now`；未来候选须先有可靠 MC evidence，再做 randomized-QMC 同预算 challenger，不能用 QMC 路径替代历史或 runtime。 | `verified_concept_only` |

## Ch06 原始扫描复核

以下 14 项由 OCR 语义与原始扫描 PDF 32 个关键页交叉核对。它们只确认离散方法的误差目标、适用条件和证据合同；不批准任何 SDE、跳跃、屏障、衍生品或风险模型实现，也不迁移书中参数、步长或收敛率为项目阈值。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH06-001` | `339-340` | 时间离散化造成的是固定模型下的 discretization bias；固定网格后，方差缩减或 QMC 只能降低该网格 estimand 的 sampling error。Euler 需明确 SDE、状态维度、网格和最大步长，随机自适应步长要另行分析。 | `SimulationDiscretizationEvidence` 分开保存 continuous target、discrete target、scheme、grid/max step、adaptive rule、sampling interval 与 discretization study；增加路径数不能关闭网格偏差。 | `verified_concept_only` |
| `FORM-RES04-CH06-002` | `343-345` | strong error 比较同一概率空间上的路径/终值差；weak error 比较测试函数期望或分布。收敛阶是小步长渐近关系，常数可依赖目标函数，方法不能脱离 estimand 排名。 | 每个实验预注册 strong/weak target、norm/test function、coupling 和步长序列；价格、分位数、极值、first passage 不能共享一个笼统“order”。 | `verified_concept_only` |
| `FORM-RES04-CH06-003` | `345-347` | Euler 常见 strong order `1/2`、weak order `1` 依赖存在唯一性、增长/Lipschitz、时间正则及更强的系数/目标函数光滑性；终值期望的阶不自动扩展到尾部分位数、极值或不光滑 payoff。 | artifact 保存 coefficient/payoff regularity、moment/tail target 与理论适用证明；若正则性不明，只能用预注册网格收敛和独立基准作经验验证。 | `verified_concept_only` |
| `FORM-RES04-CH06-004` | `343-344, 347` | Milstein 型修正可把 scalar/适当多维情形的 strong order 提高，但多维 mixed Brownian/Lévy-area 项难模拟；其 weak order 仍可能与 Euler 相同。 | 不以“高阶”名称推断目标误差更小；保存维度、驱动 Brownian 结构、mixed-integral approximation、实际 strong/weak challenger 结果和计算成本。 | `verified_concept_only` |
| `FORM-RES04-CH06-005` | `348, 350-356` | weak second-order 展开需要系数高阶导数、矩匹配及多维 commutativity/近似积分条件；简化随机变量保持有限阶矩可保渐近阶，但普通正态增量可能有更小有限样本 bias。 | scheme registry 记录 derivative source、commutativity、increment law/moment checks、vector cross terms 与数值稳定性；公式只作概念合同，不直接转录实现。 | `verified_concept_only` |
| `FORM-RES04-CH06-006` | `356-358, 375` | 平方根动力和 kink payoff 可违反二阶理论条件，实测收敛会不规则；高阶修正甚至可能比 Euler 误差更大，因此必须与简单 Euler/外推基准数值比较。 | 所有高阶候选必须保留 Euler 与 extrapolated-Euler challenger，报告带区间的多网格 bias 曲线、导数/边界异常和失败区间；案例参数及误差值不迁移。 | `verified_concept_only` |
| `FORM-RES04-CH06-007` | `357-360` | 平滑积分型路径依赖可通过 supplementary state 转为终值问题；running maximum/minimum 的奇异动力不满足同样条件，即使底层 Brownian 网格值精确，极值离散仍可能只有更慢阶。 | 路径函数按 terminal/integral/extreme/barrier 分类，分别保存 augmentation/interpolation 与适用证明；不能用终值验证替代路径事件验证。 | `verified_concept_only` |
| `FORM-RES04-CH06-008` | `360-362` | Richardson 外推依赖可展开的 leading weak-bias term，权重必须匹配原 scheme 的阶；共享嵌套 Brownian increments 可降外推方差，但不改变 discretization bias，也不保证正相关。 | 冻结 fine/coarse grid、外推权重、阶假设和 coupling；分别报告 component bias、combined bias、covariance、variance 与 coverage，禁止事后挑网格或权重。 | `verified_concept_only` |
| `FORM-RES04-CH06-009` | `363-364` | jump-adapted 方法把 Poisson jump epochs 并入时间网格，在跳间应用 diffusion scheme，并按跳前离散状态施加 jump；其阶仍依赖系数条件，高 jump intensity 会使计算成本恶化。 | jump simulation 保存 intensity/state dependence、jump-time generator、combined grid、pre/post-jump state、thinning bound 和高强度 stress；固定网格与 jump-adapted 结果分开。 | `verified_concept_only` |
| `FORM-RES04-CH06-010` | `365-366` | 固定计算预算下，步长越细会减少可完成路径数；MSE 由 squared discretization bias 与 sampling variance 共同构成，最优分配依赖 weak order 和单路径成本假设。 | 预算设计保存 wall-time、steps/path、completed paths、bias estimate、variance/CI 与 MSE sensitivity；书中渐近率不作为路径数、步长或 gate 阈值。 | `verified_concept_only` |
| `FORM-RES04-CH06-011` | `366-369` | 离散网格会漏掉点间极值和 barrier crossing；Brownian-bridge interpolation 可在给定端点及局部系数下近似区间最大值/穿越概率，但 exactness 只对相应 Brownian 条件模型成立。 | liquidation/barrier/first-passage stress 必须声明 continuous/discrete monitoring、局部 bridge DGP、endpoint/grid、跨步 miss rate 与更细网格 challenger；不得把近似穿越称真实成交或清算证据。 | `verified_concept_only` |
| `FORM-RES04-CH06-012` | `369-370` | 用条件生存概率替代随机 crossing indicator 保持同一离散期望和 bias，并通过 conditional Monte Carlo 降方差，但可能失去早停而增加单路径成本。 | estimator 比较同时报告相同离散 estimand、variance、path cost、early-stop frequency 和 likelihood/survival products；只降方差不代表总效率或模型误差改善。 | `verified_concept_only` |
| `FORM-RES04-CH06-013` | `371-374` | 平滑可逆变量变换可改善 positivity、bounds、数值稳定性或 bias；log transform 对特定乘性模型可更准确，但一般理论有限，变换会同时改变 drift、diffusion 和正则性。 | 版本化 transform/inverse/Jacobian、原/变换后 SDE、domain/bounds、round-trip 与 bias tests；约束保持不证明分布、measure 或现实机制正确。 | `verified_concept_only` |
| `FORM-RES04-CH06-014` | `374-376` | 应在真正适用的折现资产等变量上检查 martingale；positivity、区间/排序约束与 martingale 可能冲突。章节建议高阶法始终与 extrapolated Euler 比较，并优先利用问题结构。 | 保存 martingale residual、bound/order violations、drift correction、target variable 与 baseline comparison；任何一项约束修复不得静默牺牲另一项。 | `verified_concept_only` |

## Ch07 原始扫描复核

以下 28 项由 OCR 语义与原始扫描 PDF 印刷页 `377-420` 全部 44 页交叉核对。它们只确认敏感度 estimator 的目标、正则条件、偏差/方差机制和证据合同；不批准 Greeks、衍生品或校准实现，不迁移书中 step、方差表或模型参数，也不替代策略参数的预注册邻域重跑。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH07-001` | `377-379` | 敏感度是参数化期望的导数；finite difference 在多个参数值模拟同一 estimand，forward 与 central 形式的函数评估数、bias 和可用 coupling 不同。 | `SensitivityEvidence` 保存 estimand、参数语义/单位、baseline、perturbed values、difference form、random-stream policy 和工作量；不得把策略回测参数搜索包装成 Greek。 | `verified_concept_only` |
| `FORM-RES04-CH07-002` | `379-381` | forward/central difference 的 leading bias order 依赖相应阶数的可微性和局部展开；kink、边界或离散规则会使理论阶失效。 | step study 预注册对称性、step grid、regularity 与 boundary events，报告 empirical bias curve；书中渐近阶不作项目阈值。 | `verified_concept_only` |
| `FORM-RES04-CH07-003` | `381-383` | 差分除以 step 会放大噪声；独立抽样、普通 common random numbers 和 pathwise-continuous coupling 可使 numerator variance 分别呈不同阶，不能只凭“用了 CRN”推断效率。 | 保存 pair identifier、coupling construction、numerator variance/covariance、effective pairs 与 CI coverage；对同预算独立采样作 challenger。 | `verified_concept_only` |
| `FORM-RES04-CH07-004` | `383-384` | 降低 step 同时降低 truncation bias 并可能提高 simulation variance；MSE-optimal step 取决于未知的 leading bias/variance 常数、路径数和正则性。 | step 由 pilot 或预注册多尺度估计并带 uncertainty；禁止迁移历史最优 step、只报最小点或事后选择。 | `verified_concept_only` |
| `FORM-RES04-CH07-005` | `384-386` | 同一 common-normal coupling 下，连续 call payoff 可保持平滑差分，而 digital payoff 的状态跳变使 numerator variance 恶化；很小 step 可能显著增大误差。 | 按 payoff/决策函数是否连续分层，记录 threshold-crossing frequency 与 variance scaling；离散仓位、止损和清算规则不得套用平滑结论。 | `verified_concept_only` |
| `FORM-RES04-CH07-006` | `385-386` | Richardson/extrapolation 只在存在稳定 bias expansion 且组合权重匹配阶数时消去 leading bias；共享随机数改变组合方差。 | 冻结 expansion 假设、steps、weights 与 coupling，分别报告 component/combined bias、covariance 和失败区间。 | `verified_concept_only` |
| `FORM-RES04-CH07-007` | `377-386` | 二阶 finite difference 的更高次 step 除数使方差问题更严重；common randomness 可减轻但不自动恢复可用 MSE。 | Hessian/Gamma 候选必须单列 second-order step grid、numerator cancellation、variance/condition 与一阶替代；默认不进入生产 sizing。 | `verified_concept_only` |
| `FORM-RES04-CH07-008` | `377-386` | 多参数一阶差分成本随参数数增长，完整二阶交叉项成本更快增长；response-surface/design 方法以额外函数形式和相关误差假设换取较少评估。 | 参数敏感度登记 active dimensions、design matrix/rank、replicate dependence、surrogate bias 和 trial budget；不以低成本曲面替代真实邻域重跑。 | `verified_concept_only` |
| `FORM-RES04-CH07-009` | `387-389` | pathwise 方法固定随机流后对 simulation output 求导，再对路径导数取平均；“每个参数点几乎处处可导”不等于存在对所有参数同时有效的可微样本集。 | 保存 random-input representation、path functional、derivative target 和 null-set/quantifier 说明；自动微分结果仍需数学 interchange 证据。 | `verified_concept_only` |
| `FORM-RES04-CH07-010` | `389-394` | 对连续 call、Asian、lookback、spread/max 等 payoff，链式法则可沿状态或极值传播；kink 在连续分布下命中概率为零时仍可能获得可用 pathwise estimator。 | tangent/path trace 保存 state recursion、active max/index、tie handling、payoff derivative 和 integrability checks；案例可行性不迁移至任意规则。 | `verified_concept_only` |
| `FORM-RES04-CH07-011` | `390-397` | digital payoff 的简单 pathwise derivative 几乎处处为零而真实导数非零；barrier crossing 等不连续事件同样破坏直接 pathwise。 | discontinuity registry 标记 jump surface、crossing/tie probability 与 estimator failure；禁止把零梯度解释为零风险。 | `verified_concept_only` |
| `FORM-RES04-CH07-012` | `394-397` | pathwise 无偏性的充分条件包括状态导数存在、payoff 在零概率异常集外可微、随机 Lipschitz/支配变量可积，从而允许微分与期望交换；更强平方可积条件对应差分 variance 控制。 | artifact 保存 domination/UI 或 dominated-convergence 论证、moment tests 与 counterexample；只通过数值 spot check 不足以声称无偏。 | `verified_concept_only` |
| `FORM-RES04-CH07-013` | `397-399` | 对离散化 diffusion 沿 Euler 等状态递推传播 tangent，得到的是离散 estimator 的导数；它继承原 scheme 的 discretization error，且多维全 Jacobian 可有显著成本。 | 分开标记 continuous sensitivity 与 discrete-scheme sensitivity，保存 tangent dimension、scheme/grid、memory/time cost 和 multi-grid convergence。 | `verified_concept_only` |
| `FORM-RES04-CH07-014` | `399-400` | 冻结 derivative coefficient、drift 或其他状态依赖可降低 tangent 计算，但形成近似 estimator；误差可随 maturity 或路径长度累积。 | 所有 tangent shortcut 版本化 approximation、omitted derivative terms、horizon stress，并与 exact-for-scheme tangent 和 finite-difference baseline 比较。 | `verified_concept_only` |
| `FORM-RES04-CH07-015` | `400-401` | 对 digital/barrier 等可先条件化，把 indicator 替换为条件概率或 survival-product，使剩余 integrand 可微；这会改变路径构造、likelihood 和单路径成本。 | 保存 conditioning sigma-field、smoothed estimand 等价证明、survival/likelihood product、cost 与 residual discontinuity；平滑不是删掉真实事件。 | `verified_concept_only` |
| `FORM-RES04-CH07-016` | `401-403` | likelihood-ratio method 对概率密度求导，把 payoff 乘以 score；无偏性仍要求导数与积分交换，而不是因公式含 score 自动成立。 | 保存 density/version、parameter entry、score derivation、integrability/interchange 和 mean-score check；不得从 OCR 直接编码 score。 | `verified_concept_only` |
| `FORM-RES04-CH07-017` | `403-405` | 同一参数可通过显式 payoff/path dependence、density dependence或二者表示，形成 pathwise、LRM 或 hybrid estimator；score 可跨 payoff 复用但依赖选定 density representation。 | estimator registry 明确 representation、explicit/implicit parameter paths、shared score scope 与 hybrid chain rule，防止漏项或双计。 | `verified_concept_only` |
| `FORM-RES04-CH07-018` | `405-407` | 路径联合密度按 transition 分解时，score 是受参数影响 transition 的分数和；参数只影响初始 transition 与影响全部 transition 的情形有不同方差增长。 | 保存 transition factorization、affected-step mask、per-step score、martingale/covariance diagnostics 和 horizon scaling。 | `verified_concept_only` |
| `FORM-RES04-CH07-019` | `406-409` | Gaussian mean/covariance score 包含 inverse covariance、trace 和 quadratic terms，并要求相关密度满秩；矩阵维度、导数和 factorization 必须一致。 | 保存 covariance rank/condition、factor/order、mean/covariance derivatives、solve residual 和 finite-difference identity tests；禁用显式不稳定逆矩阵。 | `verified_concept_only` |
| `FORM-RES04-CH07-020` | `409-410` | LRM 要求参数变化时概率律绝对连续且有共同支撑；Uniform 区间端点随参数移动的反例表明形式 score 可存在但 estimator 仍错误。 | support contract 保存 domain、boundary motion、Radon–Nikodym/absolute-continuity 条件和 support-difference tests；支撑变化默认 fail-closed。 | `verified_concept_only` |
| `FORM-RES04-CH07-021` | `410-411` | rank-deficient Gaussian 没有全维密度；降维后 payoff 可能显式依赖参数而需 hybrid derivative。人为加入小噪声虽恢复密度，却可在噪声趋零时引发 variance 爆炸。 | 保存 intrinsic dimension、coordinate reduction、explicit payoff derivative、regularization epsilon path 与 variance stress；不得用微噪声掩盖结构奇异。 | `verified_concept_only` |
| `FORM-RES04-CH07-022` | `410-411, 419-420` | score variance 可随首个观测时点趋零、transition 数或 horizon 增长而恶化；score 和常为 martingale。score 均值为零可作 control variate，但通常不能消除定性增长。 | 报告 per-step/aggregate score variance、time-step/horizon curve、control coefficient 与 residual variance；路径更细不等于 sensitivity 更准。 | `verified_concept_only` |
| `FORM-RES04-CH07-023` | `411-413, 420` | 高阶 density derivatives 含更高次随机项，纯 LRM Gamma 常有大方差；pathwise-LRM 两种次序的 mixed estimator 通常更稳，但优劣依 payoff/strike/maturity，有限差分一阶 estimator仍需选 step。 | 二阶敏感度同时保留 pure LRM、mixed orders 与 finite-difference challengers，报告同预算 variance/MSE；书中方差表不迁移。 | `verified_concept_only` |
| `FORM-RES04-CH07-024` | `413-415` | 原过程 transition density 不可得时，可对 Euler/高阶离散近似的显式 transition law 使用 LRM；无偏只针对离散过程，不会增加该 scheme 之外的 discretization error，但也不消除它。 | estimator target 标记 original process 或 approximate process，保存 scheme/grid/transition density 和 sensitivity discretization study。 | `verified_concept_only` |
| `FORM-RES04-CH07-025` | `415-416` | 多因子/多利率模型的一步 covariance 可因状态维数超过驱动因子而奇异；若跨多步 loading 变化使累积矩阵满秩，可在冻结 drift 等近似下构造多步 Gaussian score。 | 保存 factor count、state dimension、multi-step rank、drift approximation、invertibility/condition 和 approximation challenger；满秩只证明可计算，不证明模型正确。 | `verified_concept_only` |
| `FORM-RES04-CH07-026` | `416-417` | 可将 payoff 分为平滑近似与局部 discontinuity correction，对前者 pathwise、后者 LRM；该混合 estimator 也可解释为带零均值 correction 的 control variate，线性化宽度决定方差。 | 预注册 smoothing family/width、partition identity、control coefficient、bias check 与 variance curve；禁止事后选择最优宽度。 | `verified_concept_only` |
| `FORM-RES04-CH07-027` | `418` | 对校准工具价格的敏感度可由 weighted/control-variate correction 或回归 slope 表示；当模型期望不等于市场校准价时，校正首先修复模型误差而非纯降方差。 | 保存 calibration instrument、observed price/vintage、model expectation gap、regression design、hedge interpretation 和 residual；校准敏感度不等同真实 hedge effectiveness。 | `verified_concept_only` |
| `FORM-RES04-CH07-028` | `418-420` | 适用时 pathwise 通常计算更省且方差较小；finite difference 易实现但无法逃避连续性与 step 的 bias/variance 权衡；LRM 可处理不光滑 payoff 却需显式密度且常高方差。Malliavin/Skorohod 扩展更一般但计算昂贵，二阶导数通常最难，组合 estimator 可互作 control。 | 方法选择矩阵按 regularity、support/density、rank、discontinuity、order、horizon、cost 和 empirical MSE 决定；复杂方法必须与简单 finite-difference/pathwise baseline 同预算比较。 | `verified_concept_only` |

## Ch08 原始扫描复核

原始扫描 PDF 在印刷页 `420` 后直接跳到 `422`，因此 OCR 所含 Ch08 首印刷页 `421` 无法与原载体核对，`FORM-RES04-CH08-001` 保持 `blocked_source_gap`。其余印刷页 `422-479` 已全部逐页视觉复核并拆为 29 项；目录边界页 `480` 在原载体无正文。以下内容只确认最优停止、偏差方向、复杂度和上下界证据合同，不批准 American/Bermudan option 实现，也不迁移案例参数、basis、路径数或误差表。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH08-001` | `421` | OCR 显示本章导言，但原始扫描 PDF 缺该印刷页，无法核验首段、符号或公式。 | 缺无损原页前不得引用或重建；禁止用相邻页/OCR 猜测补齐。 | `blocked_source_gap` |
| `FORM-RES04-CH08-002` | `422-423` | 定价目标是在风险中性测度下对 admissible stopping times 最大化折现非负 payoff；Markov state、numeraire/discount、exercise dates 与状态增广共同定义问题。 | 最优停止 artifact 保存 measure、state/augmentation、payoff、discount、exercise calendar、filtration 与 settlement；当前项目保持 `rejected_for_now`。 | `verified_concept_only` |
| `FORM-RES04-CH08-003` | `423-425` | finite-exercise/Bermudan 问题与连续可行权不同；章节假设 exercise-date 状态可精确模拟并把路径离散误差暂时隔离。dynamic programming 用 immediate payoff 与 conditional continuation value 递推。 | 分开记录 contract discretization、path discretization 与 stopping approximation；不能把 Bermudan 近似称连续 American 真值。 | `verified_concept_only` |
| `FORM-RES04-CH08-004` | `425-426` | 任意近似 value/continuation function 都诱导第一个进入 exercise region 的可实施 stopping rule；该规则价值不超过最优值。 | 每个政策保存 decision-time information set、continuation estimate、tie rule 和 realized stopping time；可实施策略只给 lower-bound 候选。 | `verified_concept_only` |
| `FORM-RES04-CH08-005` | `426-427` | parametric exercise boundary/value function 把无限维 stopping problem 限制到有限参数族，易于解释但在高维下需要问题特定结构；族内最优值通常低于全局最优。 | 参数族预注册经济结构、dimension、constraints 与 approximation gap；禁止事后扩族直到样本内最优。 | `verified_concept_only` |
| `FORM-RES04-CH08-006` | `427-428` | 同一模拟样本选择最优参数会因 max/Jensen 和未来信息产生样本内 high bias；冻结规则后用独立 second pass 估值得到该次优规则价值并对真值 low-biased。 | 强制 training/evaluation path split、frozen policy hash 与独立 seeds；不得把 high/low bias 相互“抵消”成无偏点估计。 | `verified_concept_only` |
| `FORM-RES04-CH08-007` | `428-430` | exercise-date 参数可逆序分解成一维/低维搜索，但逐日坐标优化或重复 backward passes 不保证原联合问题全局最优。 | 保存 optimizer/order、surviving-path sample、iterations、multi-start 与 optimality gap；示例阈值和搜索法不迁移。 | `verified_concept_only` |
| `FORM-RES04-CH08-008` | `430` | parametric continuation/value approximation 需选择 basis，并通过模拟 conditional expectations 逆序拟合；basis 是模型假设而非纯计算细节。 | 保存 basis registry、rank/condition、fit sample、residual、out-of-sample policy value 和 challenger basis。 | `verified_concept_only` |
| `FORM-RES04-CH08-009` | `431-434` | random tree 从每节点独立分支并 backward induction；节点数随 branching factor 与 exercise dates 指数增长。节点内 max 与同一 successors 均值导致 high bias，但在矩条件下随分支数增加收敛。 | 报告 branch/date complexity、memory/time、high-bias proof conditions 和 convergence curve；有限树结果不称无偏。 | `verified_concept_only` |
| `FORM-RES04-CH08-010` | `434-436` | low tree estimator 用 leave-one-out/独立子样本决定 exercise 与估 continuation，分离 decision information 后产生 low bias并随分支数收敛。 | 保存 leave-one-out mapping、decision/value samples、conditional independence 和低界区间。 | `verified_concept_only` |
| `FORM-RES04-CH08-011` | `436-437` | high estimator 的下置信限与 low estimator 的上置信限可组成保守真值区间；需要独立 tree replications 和各自标准误，随 outer replications/branching 增加收缩。 | bound artifact 保存 upper/lower estimator、one-sided limits、union-bound coverage、independence 与 gap；midpoint 不自动有理论地位。 | `verified_concept_only` |
| `FORM-RES04-CH08-012` | `437-440` | depth-first processing 将 tree storage 从全节点降到按深度/分支规模；pruning 依赖可证明 continue/exercise bounds，antithetic/LHS/control 可降方差但不改变偏差来源。 | 保存 traversal determinism、peak memory、pruning bound/decision、variance-reduction dependence 与 unpruned baseline。 | `verified_concept_only` |
| `FORM-RES04-CH08-013` | `441-443` | state-space partitioning 以固定 cells 的有限状态动态规划近似原状态；模拟估 transition/payoff 对该离散模型一致，但离散模型相对真值误差方向不可预测。独立 second pass 的 induced policy仍给 low bound。 | 分开报告 cell-model convergence 与 true-value gap、empty cells、partition design 和 independent-policy valuation；高维 cell 数指数增长。 | `verified_concept_only` |
| `FORM-RES04-CH08-014` | `443-446` | stochastic mesh 固定每期节点数并跨相邻日期全连接，用 weights 估 continuation。Markov mesh、权重可测性和平均正确定价 continuation 是 high-bias/收敛分析的核心条件。 | mesh artifact 保存 node generator、M1-M3 checks、weights、dependency graph、rank/support 与 branch-free complexity。 | `verified_concept_only` |
| `FORM-RES04-CH08-015` | `446-448` | 在 mesh 条件下 backward max 产生 high bias；把 mesh weights 扩展到全状态空间并用独立路径执行 induced stopping rule产生 low estimator。先增 mesh size 再增 evaluation paths 才有对应收缩论证。 | 保存 high/low phase order、weight extension、independent evaluation paths、nested limits 与 gap。 | `verified_concept_only` |
| `FORM-RES04-CH08-016` | `449-450` | interleaving estimator 在 exercise 节点用 immediate payoff、continue 节点从该节点起执行次优规则，混合 high/low 机制；若 continuation paths 不独立，偏差方向需另证。 | 标记每节点 estimator type、path reuse/independence 和未证明 bias；不得仅因数值位于上下界间称正确。 | `verified_concept_only` |
| `FORM-RES04-CH08-017` | `450-452` | likelihood-ratio mesh weights 用目标 transition density 除 node proposal/marginal density，把无条件下游节点重新加权为当前状态的 conditional continuation；需要共同支撑与可计算密度。 | 保存 target/proposal density、support、log weights、ESS/max weight、transition version 和 conditional-pricing identity tests。 | `verified_concept_only` |
| `FORM-RES04-CH08-018` | `452-454` | independent-path、conditional pair 和 mixture-node constructions 产生不同权重；“入节点权重均值为1”可避免 European 路径权重乘积的指数方差，并对应隐式 stratification。 | 保存 node ancestry、mixture denominator、weight-sum residual、path-product variance 与 construction challenger。 | `verified_concept_only` |
| `FORM-RES04-CH08-019` | `454-457` | mesh high estimator计算约随 exercise dates 与节点数平方增长，low paths另增成本；weights 可跨 payoffs 重用但存储大。controls/Gaussian transform 可降成本或方差，历史经验收敛率非保证。 | 报告 generation/weight/value/low-phase wall-time、storage、reuse scope、control 与同预算 error；案例复杂度常数/收敛率不迁移。 | `verified_concept_only` |
| `FORM-RES04-CH08-020` | `457-459` | transition density 可能未知、近似或因增广状态/低驱动维度而奇异。constrained weights 用已知 conditional moments 约束并以 quadratic/entropy objective 选解；只对约束函数 span 正确定价。 | 保存 moment functions/targets、feasibility、rank/condition、objective、negative weights、residual 和 omitted-span error。 | `verified_concept_only` |
| `FORM-RES04-CH08-021` | `459-461` | regression 把 continuation 投影到 basis span，OLS 依赖 design matrix nonsingularity；backward recursion 用估计下游 value，basis 数在高维可快速增长。 | 保存 basis/transform、sample split、rank/condition、regularization、residual 和 projection error；不把 in-sample fit当 continuation真值。 | `verified_concept_only` |
| `FORM-RES04-CH08-022` | `461-464` | 用 fitted continuation直接 backward max 的 regression estimator可 high-biased；由拟合函数定义 policy 后在独立路径 second pass 的 low estimator与 LSM 通常 low-biased，basis 选择显著影响边界。 | 强制 independent policy valuation，报告 high/low/gap、basis ablation、exercise-region sanity 与 negative-continuation handling。 | `verified_concept_only` |
| `FORM-RES04-CH08-023` | `465-467` | regression 可重写为 implicit mesh weights；weights 对节点对称、可为负、只正确价格 basis span，依 covariance geometry 而非 transition density。显式构权重较直接预测更昂贵。 | 保存 leverage/weight distribution、negative/extreme weights、projection span、matrix factorization 与 direct-regression parity test。 | `verified_concept_only` |
| `FORM-RES04-CH08-024` | `468-470` | regression polynomial weights可振荡并远离目标状态给负/大权重；LR weights更局部但计算昂贵。随着样本增加，LR approximation可收敛而固定不充分 basis 保留 approximation bias。 | 比较同预算 localness、weight tail、basis misspecification、density error 与 value-function curve；图中参数和优劣不迁移。 | `verified_concept_only` |
| `FORM-RES04-CH08-025` | `471-472` | duality 将 stopping-time 最大化转成零初值 martingale/supermartingale 上的最小化；任意有效 martingale给 upper bound，最优 value-function martingale使等号成立。 | `StoppingBoundEvidence` 保存 lower policy、martingale increments、conditional-zero check、upper pathwise max、gap 和 coverage。 | `verified_concept_only` |
| `FORM-RES04-CH08-026` | `473-474` | 从 approximate value function直接相减通常不是 martingale difference；必须减 conditional expectation。nested simulation 可无偏估该条件项并恢复有效 upper-bound 方向，但增加 inner cost。 | 保存 inner/outer independence、subpath count、conditional-zero residual、nested variance/cost 和 approximate-value hash。 | `verified_concept_only` |
| `FORM-RES04-CH08-027` | `474-476` | 也可从可实施 stopping rule构造 martingale differences，需要估 stopping-policy payoff 的 conditional expectations；每步 subpath长度随机。lower/upper gap可指导是否增加 basis 或 inner samples。 | 保存 policy version、subpath stopping horizon、inner allocation、martingale check、bound gap decomposition 与 compute budget。 | `verified_concept_only` |
| `FORM-RES04-CH08-028` | `476-478` | 若 continuation恰在 regression span，regression residual等于最优 martingale increment；一般 residual不是 martingale，回归点估与 dual upper bound可分离，差距诊断 basis fit。 | 不把普通 regression residual直接当 upper-bound increment；验证 conditional mean zero，并用 dual-regression gap作模型诊断。 | `verified_concept_only` |
| `FORM-RES04-CH08-029` | `478-479` | 方法选择存在正交的复杂度轴：tree随exercise dates指数增长，partition随state dimension指数增长，mesh需density且节点平方成本，regression较快但basis-dependent；可靠实现应 second-pass low estimator配 dual upper bound。 | 选择矩阵保存 state/date dimensions、density availability、basis knowledge、cost、lower/upper gap 与失败模式；不能只报单点价格。 | `verified_concept_only` |
| `FORM-RES04-CH08-030` | `422-479` | 全章反复区分三类误差：同样本 max 的 upward selection/future-information bias、次优 stopping policy 的 downward approximation bias、以及 path/state/mesh/regression numerical error。偏差方向来自信息集与 estimator construction，不来自方法名称。 | 将此模式迁移到回测治理：训练/选择与独立评价分离，任何可实施策略只声明 OOS 下界式绩效证据，oracle/dual只作上界诊断；不产生 promotion 结论。 | `verified_concept_only` |

## Ch09 原始扫描复核

以下 17 项由 OCR 语义与原始扫描 PDF 45 个关键页交叉核对。它们只确认风险模拟的 estimand、模型输入、稀有事件权重与失效边界；不批准 VaR/信用模型实现，不迁移书中阈值或案例结果，也不构成 promotion evidence。

| 条目 | PDF印刷页 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-CH09-001` | `481-483` | 组合损失模拟必须同时指定风险因子变化的联合分布和风险因子到组合价值的 mapping；损失定义为负的价值变化，并固定 horizon、组合组成且忽略区间内极值。 | `TailRiskSimulationEvidence` 保存 position snapshot、horizon、loss sign、factor state/DGP、valuation mapping 与 intrahorizon omissions；任一缺失则 tail metric fail-closed。 | `verified_concept_only` |
| `FORM-RES04-CH09-002` | `483-484, 489-491` | VaR 是损失分布分位数，连续性/tie 约定影响定义；单一分位数不描述超越后的损失。样本分位数的不确定性依赖分位点密度，也可用 order-statistic/binomial 区间。 | 报告 quantile convention、exceedance probability、tail count、CI 方法和 ES/conditional-excess challenger；点 VaR 不得单独解锁 gate。 | `verified_concept_only` |
| `FORM-RES04-CH09-003` | `484-485` | normal-market/linear-portfolio 使损失近似正态并由 covariance 与 sensitivities 决定；短 horizon 零均值、条件正态和线性价值均是附加假设。 | 记录 covariance vintage、conditional state、mean treatment、delta mapping 与 normality/heavy-tail challenger；解析 VaR 只是受限基线。 | `verified_concept_only` |
| `FORM-RES04-CH09-004` | `485-487` | delta-gamma 是局部二阶 Taylor 近似；对相关正态因子可白化、对角化并用特征函数反演近似损失分布，但 off-diagonal gamma、导数可得性和尾部局部误差限制其可靠性。 | 保存 delta/gamma source、evaluation point、factorization/eigen diagnostics、inversion error，并以 full revaluation 检查尾部 mapping error。 | `verified_concept_only` |
| `FORM-RES04-CH09-005` | `489-492` | 朴素 MC 对每个风险因子情景完整重估组合并统计 exceedance；瓶颈是重估成本，历史模拟尾部有缺口，近似重估还引入函数形式和高维拟合风险。 | 保存 full/approx valuation 标志、tail events、revaluation cost、historical window gaps、surrogate training domain 和 exact-value challenger。 | `verified_concept_only` |
| `FORM-RES04-CH09-006` | `492-493` | delta-gamma control variate 需要可计算的近似尾概率；总体损失与近似高度相关不保证尾部 indicator 高相关，极端阈值下 control 系数也难稳定估计。 | 报告 loss/indicator correlation、tail observations、control expectation、coefficient pilot 与 quantile inversion coverage；均值相关不能替代尾部有效性。 | `verified_concept_only` |
| `FORM-RES04-CH09-007` | `495-499` | importance sampling 可用 delta-gamma 引导均值/方差扭曲，但必须按完整 likelihood ratio 加权；twisting 参数域和选择依据来自近似分布，最终 estimand 仍用真实组合损失事件。 | 冻结 proposal/twist/domain/optimizer、support、log-weight、ESS/max weight，并在同一情景执行 full revaluation 与朴素 MC challenger。 | `verified_concept_only` |
| `FORM-RES04-CH09-008` | `501-505` | importance sampling 可再按近似损失分层；需要已知层概率和条件采样，acceptance-rejection 候选成本与 portfolio revaluation 成本共同决定效率，高维/极端设计可失效。 | 保存 strata、probability、conditional sampler、acceptance、allocation、层内 tail count 与总工作量；案例方差缩减倍数不迁移。 | `verified_concept_only` |
| `FORM-RES04-CH09-009` | `506-510` | 高峰厚尾可由正态混合或尺度混合刻画，但 kurtosis 不是完整尾部描述；多元 t 的分量即使不相关也因共享尺度而不独立，相关矩阵不能穷尽尾部依赖。 | challenger DGP 至少覆盖 normal、mixture、t/scale-mixture，并报告 tail index/moment existence、shared-scale dependence 与 horizon sensitivity。 | `verified_concept_only` |
| `FORM-RES04-CH09-010` | `512-514` | 重尾下 delta-gamma 各分量不再独立且可能无矩母函数；间接 delta-gamma 通过条件尺度变量构造可反演对象，但计算成本和变换近似误差不同于正态情形。 | 保存 direct/indirect approximation、conditioning variable、moment domain、inversion grid/cost、transform derivatives 和 full-revaluation tail error。 | `verified_concept_only` |
| `FORM-RES04-CH09-011` | `514-517` | 对重尾对象直接指数扭曲可能无法归一化；章节改为扭曲间接近似量，所得渐近最优性主要针对近似事件而非真实组合损失。 | 重尾 IS 必须证明 proposal 可归一、权重有限性和目标事件覆盖，报告 tail ESS/second moment，并把近似最优性标成间接证据。 | `verified_concept_only` |
| `FORM-RES04-CH09-012` | `517-520` | 重尾 IS 可结合分层并用一组情景估多个阈值，但效果随 copula、边际参数和组合非线性而显著变化，极端数字/障碍组合可几乎无增益。 | 预注册 threshold range、共享 proposal/strata、copula/parameter challengers 与失败组合；每个阈值单独报告 CI 和有效尾样本。 | `verified_concept_only` |
| `FORM-RES04-CH09-013` | `520-523` | 信用估值区分客观违约分布与风险中性估值分布；default time/intensity、discounting、recovery/LGD 与 filtration 共同决定 survival 和现金流价值，intensity 并非对任意信息集都存在。 | `CreditRiskSimulationEvidence` 版本化 measure、filtration、intensity/survival、discount curve、recovery convention、cash-flow timing 和 objective-risk challenger。 | `verified_concept_only` |
| `FORM-RES04-CH09-014` | `525-529` | 多主体违约的核心是联合依赖；equity correlation、common factors、correlated intensities 和 copula 可给相同边际却产生不同联合尾部，变量变换通常不保留线性相关。 | 保存 marginal PD、factor/correlation/copula version、conditional independence、tail-dependence challenger 和 joint-default sensitivity；相关系数不等于违约依赖事实。 | `verified_concept_only` |
| `FORM-RES04-CH09-015` | `529-530` | 组合信用损失由违约 indicators 与 LGD/exposure 求和；独立同质情形只是起点，真实尾损失受集中度、异质 PD/LGD/exposure 和依赖支配。 | credit stress 保存 obligor/exposure/LGD/PIT PD、concentration、sector/factor grouping、joint-default scenarios 与 loss-distribution interval。 | `verified_concept_only` |
| `FORM-RES04-CH09-016` | `532-536` | 因子信用模型可在给定 common factors 后扭曲条件违约概率，再扭曲因子均值；两阶段 likelihood ratio 保持无偏，但参数选择只在特定模型和目标下增效。 | 保存 conditional PD、indicator twist、factor shift、完整 log-weight、unbiasedness check、weight diagnostics 与 untwisted challenger；禁止迁移示例均值。 | `verified_concept_only` |
| `FORM-RES04-CH09-017` | `535-537` | 章节只覆盖风险管理的一小部分；极端分位数误差会被低密度放大，QMC 不专门适合小概率，重尾 IS、信用暴露路径和动态保险模型仍属问题特定研究。 | 所有 tail 结论附 model-risk boundary、alternative DGP/full-revaluation challenger、density/CI sensitivity 和未覆盖机制；研究证据不等于 promotion。 | `verified_concept_only` |

## 附录复核

- Appendix A 已逐页视觉核对原始扫描 PDF 印刷页 `539-544`；以下条目只确认数学概念、关系和使用条件，未迁移任何数值常数或项目参数。

| 条目 | 原文位置 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-APP-A-001` | PDF印刷页 `539-540` | almost-sure、probability、`p`-norm 与 distribution convergence 的定义和蕴含关系；一致估计量与强一致估计量分别对应依概率和几乎处处收敛。 | 模拟报告必须声明所称“收敛”的对象与模式，不能把分布收敛、均值收敛和路径收敛混写。 | `verified_concept_only` |
| `FORM-RES04-APP-A-002` | PDF印刷页 `540-541` | distribution convergence 的分布函数、bounded-continuous-function 与 characteristic-function 表述；Slutsky 型加法/乘法结论要求另一个极限为常数；分布收敛本身不保证矩收敛，需 uniform integrability 等附加条件。 | 对均值、方差和尾部量的声明必须单独验证矩条件，弱收敛图或点估计稳定不能替代。 | `verified_concept_only` |
| `FORM-RES04-APP-A-003` | PDF印刷页 `541-542` | 有限正方差 iid 样本均值的标量 CLT，以及随机向量样本均值的多元 CLT。 | CLT 区间必须记录 iid/方差/向量协方差等前提；相关路径或方差缩减样本不得无条件套用。 | `verified_concept_only` |
| `FORM-RES04-APP-A-004` | PDF印刷页 `542-543` | 已知方差与一致标准差估计下的渐近正态区间、样本标准差定义，以及正态样本下的精确 Student-`t` 区间。 | artifact 必须区分 exact 与 asymptotic interval，并保存 variance estimator、自由度和 coverage target。 | `verified_concept_only` |
| `FORM-RES04-APP-A-005` | PDF印刷页 `543` | 目标半宽下路径数随方差与正态分位数平方增长；Chebyshev 可给更保守的有限方差界，但不能被描述为同等效率的正态近似。 | 路径预算应由预注册的误差半宽、置信水平和方差估计驱动，不能只固定一个便利路径数。 | `verified_concept_only` |
| `FORM-RES04-APP-A-006` | PDF印刷页 `543-544` | dependent replications 下常规标准误会失效；可按独立 batch 聚合。离散步长随样本量变化会形成 triangular array，需要相应 CLT 条件而非直接使用 iid 结论。 | 方差缩减、公共随机数和时步收敛实验必须保存依赖结构、batch 设计及 triangular-array 条件。 | `verified_concept_only` |

### Appendix B：Results from Stochastic Calculus

Appendix B 原始扫描 PDF 全部内容页 `545-557` 已逐页核对；章界页 `558` 无正文。以下 12 项只确认随机微积分概念、假设和使用边界，不批准 SDE、复制定价或测度变换实现。

| 条目 | 原文位置 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-APP-B-001` | PDF印刷页 `545-546` | filtration、adapted process、Brownian filtration 与 Itô integral 的平方可积条件；Itô process 的 drift/diffusion 表示要求相应可积性。 | 模拟模型保存 probability space/filtration、adaptedness、integrability、Brownian dimension 与 coefficient units；形式 `dX` 不替代定义。 | `verified_concept_only` |
| `FORM-RES04-APP-B-002` | PDF印刷页 `546-547` | 多维 Itô formula 包含时间导数、gradient、covariance-weighted Hessian 和 stochastic integral；product rule 多出 quadratic-covariation 项。 | generator/AD/hedging fixture 核对维度、Hessian 对称、covariance、cross term 与 units；不得照 OCR 转录。 | `verified_concept_only` |
| `FORM-RES04-APP-B-003` | PDF印刷页 `548` | strong SDE solution 固定 probability space/Brownian motion；Lipschitz 与 linear-growth 是方便的存在唯一充分条件，不是必要条件，square-root diffusion 需其他定理。 | 模型合同区分 strong/weak solution、existence、pathwise/law uniqueness 和 boundary exceptions；通用定理不可覆盖非 Lipschitz 模型。 | `verified_concept_only` |
| `FORM-RES04-APP-B-004` | PDF印刷页 `549` | 满足相应条件的 SDE 解是 strong Markov；Gaussian process 不必 Markov，SDE 解也不必 Gaussian，线性 SDE 加 Gaussian 初值才给 Gaussian process。 | 状态充分性、Markov、Gaussian 三项分别验证；不能由模型标签互相推导。 | `verified_concept_only` |
| `FORM-RES04-APP-B-005` | PDF印刷页 `549-550` | 常系数线性 SDE 有 matrix-exponential 表示；均值、协方差由 deterministic integrals 和 Itô isometry 得出。 | 线性模型 fixture 保存 matrix orientation、initial law、mean/covariance ODE/closed form 与 simulation moment parity。 | `verified_concept_only` |
| `FORM-RES04-APP-B-006` | PDF印刷页 `550-551` | martingale 要求 integrability 与 conditional-mean property；local martingale 不自动是真 martingale。非负 local martingale 是 supermartingale，常期望等附加条件可恢复 martingale。 | 所有“driftless/martingale”声明保存 UI/class-D 或平方可积证据、expectation curve 和 strict-local counterexample；缺证据 fail-closed。 | `verified_concept_only` |
| `FORM-RES04-APP-B-007` | PDF印刷页 `551-552` | stochastic integral 在平方可积条件下是 martingale并满足二阶等距；stochastic exponential 至少是 local martingale，期望保持为1才是真 martingale。 | density/discount process 保存 nonnegative、unit mean、integrability、second moment 与 numerical expectation residual。 | `verified_concept_only` |
| `FORM-RES04-APP-B-008` | PDF印刷页 `552-553` | Brownian filtration 下的 martingale representation 把平方可积 martingale/terminal claim 表成初值加 stochastic integral；依赖 filtration 与 completeness。 | 复制/hedging只能在声明 filtration、tradable span、integrability 和 market completeness 后讨论；不迁移为真实市场可复制结论。 | `verified_concept_only` |
| `FORM-RES04-APP-B-009` | PDF印刷页 `553-554` | Radon–Nikodym derivative 定义 absolutely continuous measure change；equivalence 要双向绝对连续/共同 null sets，density ratio 改变边际分布并需 support 覆盖。 | proposal/measure registry 保存 base/target、support、RN derivative、normalization、zero-density convention 与 inverse check。 | `verified_concept_only` |
| `FORM-RES04-APP-B-010` | PDF印刷页 `554-555` | 有限维独立 normal drift shift 可由 product likelihood ratio 实现；逐个有限维 measures 等价不保证无限时域极限等价。 | 长路径/高维 importance sampling 保存 horizon/dimension、log-weight、ESS、mutual-singularity stress；有限样本 identity 不外推无限维。 | `verified_concept_only` |
| `FORM-RES04-APP-B-011` | PDF印刷页 `555-556` | nonnegative unit-mean density martingale 定义一致的有限时域 measures；conditional expectation 在变换测度下需乘 density process 比率。 | numeraire/measure-change evidence 保存 density process、conditional formula、UI/extension horizon 与 consistency tests。 | `verified_concept_only` |
| `FORM-RES04-APP-B-012` | PDF印刷页 `556-557` | Girsanov 在有限时域把 Brownian drift shift 与等价测度联系起来；exponential density 必须是真 martingale，Novikov 只是充分条件。测度变换改 drift 不改 diffusion 的结论受假设限制。 | 保存 gamma/adaptedness、Novikov或替代证明、unit-mean test、sign convention、finite horizon 与 transformed drift/diffusion fixture。 | `verified_concept_only` |

### Appendix C：The Term Structure of Interest Rates

Appendix C 原始扫描 PDF 全部内容页 `559-567` 已逐页核对；章界页 `568` 无正文。书中 LIBOR/Eurodollar 名称及市场惯例是历史背景，所有当前 benchmark、day-count、fallback、clearing 和 quote convention 必须另从现行权威来源核验。

| 条目 | 原文位置 | 已核内容 | 项目映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES04-APP-C-001` | PDF印刷页 `559` | continuous、simple 与 periodic compounding 产生不同 growth/discount factors；day-count fractions 可不等。 | curve contract 保存 compounding、day count、calendar、accrual fractions、currency 与 units；同名 rate 不可直接比较。 | `verified_concept_only` |
| `FORM-RES04-APP-C-002` | PDF印刷页 `560` | coupon bond 是 zero-coupon cash flows 的组合；随机 short rate 下零息债价格是风险中性折现因子的期望，依赖 measure/model。 | 现金流表与 discount curve 分离，保存 payment dates、accrual、curve vintage、measure/model 和 reconciliation。 | `verified_concept_only` |
| `FORM-RES04-APP-C-003` | PDF印刷页 `560-561` | zero/coupon bond yield 是由价格反解的 convention-dependent summary，不等于原始可观测同一对象。 | yield artifact 保存 price source、solver、compounding/day-count、cash flows 和 convergence；不将 yield 当唯一曲线状态。 | `verified_concept_only` |
| `FORM-RES04-APP-C-004` | PDF印刷页 `561-562` | simple forward rate 由两期限零息债无套利比值得出；书中把 forward LIBOR 当特例时明确忽略银行信用风险。 | 当前项目使用 benchmark-neutral `ForwardRateEvidence`；历史 LIBOR 公式只作结构，必须另核现行 benchmark、credit/fallback 和 fixing。 | `verified_concept_only` |
| `FORM-RES04-APP-C-005` | PDF印刷页 `562` | continuously compounded forward rate 是 log discount 的期限差，instantaneous forward 是其极限；bond price 是 forward curve 积分，yield 是区间 forward 平均。 | curve builder 保存 interpolation/differentiation、smoothness、boundary、negative rates 与 round-trip bond/forward/yield tests。 | `verified_concept_only` |
| `FORM-RES04-APP-C-006` | PDF印刷页 `562-564` | fixed-for-floating swap 可视作 fixed/floating bonds 差；par swap rate 由起止 discount factors 与 annuity denominator 决定。 | swap fixture 保存 notional、payment schedule、accruals、discount/projection curves、sign 与 par-value residual；单曲线简化须显式。 | `verified_concept_only` |
| `FORM-RES04-APP-C-007` | PDF印刷页 `564` | forward swap rate 是使未来起始 swap 当前价值为零的 rate；单期情形退化为对应 forward rate。 | 保存 option-expiry/swap-tenor、annuity、curve set 和 single-period identity；历史 LIBOR 名称禁迁移。 | `verified_concept_only` |
| `FORM-RES04-APP-C-008` | PDF印刷页 `564-565` | futures 因每日/连续 resettlement，其价格是风险中性条件期望；forward rate在对应 forward measure 下是 martingale，两者通常因 term-structure dynamics/convexity不同。 | futures/forward 分账，保存 settlement ledger、margin cash flows、measure、convexity adjustment 与 curve model；不得混用 quote。 | `verified_concept_only` |
| `FORM-RES04-APP-C-009` | PDF印刷页 `565` | cap 是 caplets 组合、floor 是 floorlets 组合；caplet payoff 的 fixing、accrual、payment date 与正负方向必须明确。 | derivative contract 保存 fixing/start/end/payment、accrual、strike、notional、payer/receiver、calendar 与 settlement。 | `verified_concept_only` |
| `FORM-RES04-APP-C-010` | PDF印刷页 `565` | payment-date caplet 可在 fixing date 用对应 discount factor转换为 bond/forward-rate payoff，复制涉及两期限 bonds；仍需 term-structure dynamics 定价。 | 保存 payoff-time conversion、numeraire/discount factor、replicating assets 与 units；静态代数不证明可成交复制。 | `verified_concept_only` |
| `FORM-RES04-APP-C-011` | PDF印刷页 `566` | caplet Black formula 是市场 quote/implied-vol convention；假定特定 forward lognormal 表达，章节明确其不一定单独构成完整无套利 term-structure price model。 | implied-vol ingestion 保存 quote convention、shift/negative-rate handling、annuity/discount、solver 和 model-consistency challenger；历史公式不直接实现。 | `verified_concept_only` |
| `FORM-RES04-APP-C-012` | PDF印刷页 `566-567` | swaption payoff 是 swap annuity 乘 forward swap rate 超额的正部；Black swaption quote同样是 implied-vol convention，不自动证明动态模型一致。 | 保存 payer/receiver、expiry/tenor、annuity、underlying schedule、quote model 与 no-arbitrage/model challenger；当前无合同故不实施。 | `verified_concept_only` |

## L3 复核边界

9/9 章与 Appendix A/B/C 的全部原载体可用内容页均已完成低可信概念级复核：Ch01 10项、Ch02 18项、Ch03 31项、Ch04 14项、Ch05 26项、Ch06 14项、Ch07 28项、Ch08 29项、Ch09 17项、Appendix A 6项、Appendix B 12项、Appendix C 12项关闭为 `verified_concept_only`。Ch08 首印刷页421缺失，保留1项`blocked_source_gap`；在取得无损原页前，本书不能标记单书 `complete`，也不能提供实现或 promotion 参数。
