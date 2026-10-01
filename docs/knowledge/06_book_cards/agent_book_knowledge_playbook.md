# 量化书籍到 Agent 行动的知识手册

## 目标

把本地 28 本书中的稳定知识转成项目可执行的研究规则、架构边界、测试要求和证据字段，同时避免把书中案例、历史回测或数学形式误当成当前策略证据。

统一转换链：

`book concept -> project hypothesis or contract -> implementation/test plan -> current-HEAD evidence -> promotion gate`

任何步骤都不能跳过。

当前手册是跨书籍主题汇总，不等于 28 本书全部完成章节精读。真实覆盖率以 `coverage_manifest.md` 为准；章节来源、可信度和公式状态以 `cards/` 中的单书卡为准。

## 一、来源使用合同

### 1. 书籍能提供什么

- 概念定义、问题分类和设计权衡。
- 策略假设、基线模型和失败机制。
- 数据、验证、组合、执行和工程检查清单。
- 可转化为字段、接口、测试和 blocker 的稳定规则。

### 2. 书籍不能提供什么

- 当前数据是否新鲜、完整或 point-in-time。
- 当前策略是否通过回测、paper 或 live gate。
- 当前交易所、broker、费用、保证金、限频或 API 状态。
- 当前 HEAD 的实现是否正确。
- 未经本项目验证即可使用的参数、杠杆或仓位。

### 3. 提炼状态

书籍知识进入项目时只允许使用以下状态：

- `concept_only`：仅用于理解或提出问题。
- `hypothesis_candidate`：已形成可检验假设，尚无本项目证据。
- `project_rule_candidate`：可形成契约或检查项，尚未纳入硬规则。
- `adopted_project_rule`：已进入项目规范并有测试或审计证据。
- `superseded`：被新证据、当前实现或更高优先级规则替代。

不得使用 `ready`、`validated` 或 `promotion_passed` 描述单纯读书结论。

书籍阅读覆盖另按 `knowledge_card_schema.md` 的 `L0` 至 `L3` 记录，知识采用状态不能替代阅读覆盖证据。

## 二、策略研究规则

来源：`STR-01` 至 `STR-12`、`RES-01`、`RES-02`、`PORT-02`、`PORT-03`。

### 1. 策略候选先登记，后回测

每个书籍策略或变体必须先写入候选记录：

- `candidate_id`
- `source_book_ids`
- `research_question`
- `economic_hypothesis`
- `edge_type`: trend、momentum、carry、value、liquidity、behavioral、market_structure 等
- `instrument_scope`
- `decision_horizon`
- `required_data`
- `signal_definition`
- `forecast_mapping`
- `baseline`
- `cost_and_slippage_assumptions`
- `risk_constraints`
- `failure_conditions`
- `trial_budget`
- `holdout_policy`

`151 Trading Strategies` 和 `Trading Systems and Methods` 属于候选方法库。收录某个方法不代表该方法具有经济解释、可交易性或样本外有效性。

### 2. 研究生产链不是单人回测循环

- 数据治理、特征诊断、经济假设、独立回测、部署和组合监督必须明确owner、输入、输出与不可见信息；特征不等于策略，回测结果不应成为继续适配测试集的调参提示。
- 每个handoff只消费已提交commit、不可变manifest和验证证据；未提交工作树、口头结论或latest路径不能跨角色解锁下一阶段。
- Backtester/gate owner必须知道候选如何产生并计入全部trial/search history，但研究员不得据独立holdout结果反复修补同一候选。
- 部署必须证明原型与生产逻辑等价；任何性能优化、并行化或adapter转换不得改变标签、特征、信号、仓位或执行语义。
- research-only、backtest、promotion evidence、paper/live readiness和decommission均服从当前HEAD gate；书中embargo/paper/graduation名称不具有授权效力。

### 3. 简单规则是基线，不是特权

- 趋势、突破、双动量和因子排序应先实现最简单、可复现的基线。
- 简单规则仍必须通过 PIT、成本、walk-forward、holdout、参数稳定和 ledger 检查。
- 复杂模型必须证明相对简单基线的增量价值，不能只报告自身收益。
- 书中参数只能作为预声明起点；不得因为本地全样本表现而反复修改。

### 4. 趋势与动量必须区分

- 时间序列趋势回答单个资产自身方向。
- 横截面动量回答同一时点哪些资产相对更强。
- 双动量组合相对强弱和绝对风险过滤，但资产池、回看窗口和防御资产必须预先声明。
- relative rank 与 absolute-risk state 是两个独立 Forecast；先做组件消融，再由 Portfolio/Risk 合成 TargetPosition，Strategy 不得直接切换资产或下单。
- 防御资产不是固定安全港；现金、短债、综合债券或其他替代品必须按 availability、duration、credit、liquidity、real-yield、stress correlation 和成本动态验资。
- duration、convexity、curve carry 与历史低波动是不同风险描述；债券或债券 ETF 被标为“防御”不能替代信用、期限、曲线、流动性和压力相关审计。
- 单 BTC 趋势可以验证工程闭环，不能代表跨市场 CTA 分散证据。
- 趋势策略的少数大赢家可以是结构特征，但仍要检查年份、市场状态、成本和前向观察。
- breakout 与 retracement 是入场 timing challenger，不是两个独立 alpha；必须共享冻结的趋势 Forecast，在同样本、同成本和同风险预算下比较 missed trade、fill、whipsaw 与尾部。
- “每个信号都执行”仅适用于通过数据、eligibility、capacity 和 Portfolio/Risk 门的合格信号；相关资产、重叠窗口和共同趋势必须按 lineage 去重，名义 trade 数不是独立 breadth。

### 5. 因子研究必须从预测质量出发

- 因子先做覆盖率、可见时间、标准化和异常值策略。
- 报告 IC、Rank IC、分组收益、换手、容量、行业和市值暴露。
- A 股、美股和 ETF 的交易制度、复权、停牌、涨跌停和 universe 不能混用。
- 多因子不是简单加总；必须检查相关性、正交化、暴露约束和成本后的边际价值。
- 股票动量不是 growth 标签；必须用匹配 size/sector/value/quality/growth 暴露的基准检验增量，并区分 long-only 与 long-short 结论。
- generic momentum、路径连续性、季节调仓、52周高点和基本面动量是不同 trial family；任何二阶段筛选都要先证明相对冻结基线的边际 OOS 价值。
- 大量faint/ephemeral alpha的纸面组合不能以数量制造稳健性；每个alpha保存lineage、时钟、成本和相关组，组合前先淘汰不可交易或同源重复项。

### 6. 特征重要性只生成可证伪假设

- MDI是树模型样本内impurity归因，受高基数、split机会、masking和相关特征稀释影响；总和为1或正值不代表预测有效。
- MDA必须在purged/embargo外层验证内执行，并用time/entity block或conditional/grouped permutation保持可行结构；随机逐行置乱可能制造离分布样本。
- SFI避免替代效应但遗漏交互；必须配合pair/group ablation、相关组总重要性和简单模型基线，不能按单一排名删特征。
- standardization、PCA、feature cluster、置乱规则和选择阈值全部fold-local；PCA解释高方差或与监督排名一致都不证明alpha、因果或无过拟合。
- 重要性报告至少包含per-fold、per-asset、per-regime分布，rank/score稳定性、null/placebo、availability shift、加入/删除OOS增量、数据与执行成本。
- 跨资产stacking必须做group/time split并审查资产机制、base rate、calendar、currency和样本支配；重要性只能更新research question，不能解锁promotion。

## 三、统计建模与金融数学规则

来源：`RES-01`、`RES-03` 至 `RES-06`。

### 1. 时间序列模型

- 建模前明确价格、收益、波动率、价差或因子序列的平稳性假设。
- ARMA、GARCH、协整、状态空间或 Kalman 模型只在训练窗口估计；参数不能使用未来数据。
- 必须保留残差诊断、预测误差、参数稳定性和滚动/扩展窗口对比。
- 高采样频率不等于高独立样本数；微观结构噪声、bid/ask bounce 和异步时间必须单独处理。
- 协整关系失效、结构突变或残差异常必须进入策略失效条件，不得静默重估后继续使用。
- 分数差分只能作为训练期拟合的候选变换；`d`、权重阈值、窗口宽度和检验设定必须在每个训练折选择并冻结，验证/实时期只使用当时可见前缀。
- ADF拒绝单位根不等于完整平稳，更不等于alpha；至少联合互补平稳性诊断、结构break、分段稳定性和严格OOS基线，原序列相关性只能描述变换距离。
- 扩展窗与固定宽度分数差分具有不同状态和warm-up语义；实现必须保存权重、截断、首个有效时点与transform hash，并通过`d=0/1`、direct convolution、chunk/restart和prefix invariance fixture。
- 分数差分必须与原值、收益/整数差分和简单滚动变换比较；若只改善检验统计量而无严格OOS增量，则拒绝该特征。
- structural-break统计量必须prefix-only，保存as-of、series transform、window/start-end、trend/lag、null、critical-value来源与完整trial；历史回填或全样本选阈值属于泄漏。
- CUSUM、SADF、QADF/CADF或SMT尖峰只说明指定null下的异常证据，不自动等于泡沫、反转方向、机制变化或alpha；必须并列数据错误、roll、microstructure、variance shift等解释。
- break detector只输出warning/evidence；Risk按预注册状态机降风险或冻结，重训必须新建model/candidate version并经审批与re-entry观察，不得静默续用旧策略。
- start/end、transform、lag、trend、minimum sample、quantile/penalty和threshold均为相关trial；临界值需有限样本/依赖校准并报告false alarm、检测延迟、采样与outlier敏感性。
- entropy不是序列固有单值；必须绑定raw series、clock、encoder/alphabet、training-only boundaries、word/match length、window direction、estimator、log base、output lag和prefix hash。
- plug-in与LZ的stationary/ergodic/finite-alphabet结论主要是渐近性质；短消息必须报告bias/variance、endpoint和restart，禁止靠重复、删首字符或反转未来后缀修补。
- binary、quantile和fixed-step编码分别丢幅度、强制边际均匀或放大稀有码；所有边界逐fold冻结，并与run/autocorrelation/volatility等简单基线同预算比较。
- high entropy不证明有效市场，low entropy不证明泡沫，entropy-CDF不等于adverse-selection概率；离散bits/nats与连续differential entropy必须分对象和单位。

最低模型证据字段：

- `model_family`
- `target_series`
- `stationarity_assumption`
- `fit_window`
- `parameter_version`
- `residual_diagnostics`
- `forecast_horizon`
- `forecast_interval`
- `rolling_stability_summary`
- `structural_break_checks`

### 2. 集成模型

- bagging、随机森林和boosting都不能自动修复金融label重叠、共同regime、数据泄漏或错误标签；先用第4章唯一性/并发度审计有效样本，再做集成。
- 集成是否降方差取决于基学习器误差相关而不只是数量；必须保存基学习器预测，报告pairwise prediction/error correlation、disagreement、seed稳定性和learner-count平台。
- OOB在重叠时间区间下可能与in-bag共享未来结果，只可作训练debug；最终模型选择使用purged/embargo验证，普通随机或仅stratified K-fold不合格。
- 所有sample/feature bootstrap、PCA、class/uniqueness weight、early stopping和calibration都在训练折拟合；参数、seed与失败试验进入trial ledger。
- 集成必须对比简单规则/线性/单学习器基线，并报告校准、按class/regime损失、turnover和成本；低预测方差、更多树或更高投票准确率不等于alpha。
- boost对错分样本的反复加权必须先隔离bad tick、错标和不可交易尾部；bagging也不能修复共同bias，二者不得按书中偏好直接选型。

### 3. 蒙特卡洛与场景模拟

- 蒙特卡洛用于评估不确定性、尾部、路径依赖、估值或风险，不用于制造额外历史样本。
- 报告随机种子、路径数、时间步、输入分布、参数来源、收敛诊断和置信区间。
- 使用方差缩减、重要性抽样或准蒙特卡洛时，必须说明估计对象和偏差风险。
- variance reduction若引入跨replication依赖，普通sample standard error/CI可能失效；必须保存依赖设计并验证interval coverage，不能只报告方差下降倍数。
- 单次确定性QMC结果没有普通MC的现成抽样误差；若用于证据，采用randomized QMC的多个独立scramble，报告replicate dispersion并与同预算MC比较。
- 稀有事件结果必须披露有效样本数和估计误差，不能只展示最坏路径。
- 模拟 fill、强平或盘口路径只属于 diagnostic，不能替代真实 paper runtime、成交 ledger 或交易所证据。
- American-option模拟中“同一路径未来信息选exercise产生high bias、次优规则产生low bias”是通用泄漏反例；任何序贯决策评估都必须按当时information set生成动作，事后最优路径只能作上界诊断。
- 历史拟合的OU、jump、regime或bootstrap生成器都只是候选DGP；参数按训练fold估计并报告CI/break/residual诊断，至少与random walk和异方差/跳跃challenger比较。
- path count增加只降低给定DGP下的Monte Carlo误差，不降低模型偏差；必须分开报告MC error、parameter uncertainty和generator misspecification。
- 在synthetic paths上搜索profit/stop、horizon或其他规则仍是模型选择；grid、seed、generator和metric进入trial ledger，输出failure surface与稳定区域而非单一argmax。
- synthetic first-touch不是fill，省略spread/fee/impact会改变规则面；合成结果不得称OOS market data、paper、真实PnL或promotion evidence。

### 4. 随机微积分与定价模型

- 文件名、下载名或二手书目不是来源身份；只有标题页、作者/版权、目录、载体hash和版本信息一致时才可引用。误标来源可按真实身份重登记，但必须保留alias warning，禁止沿用错误书名、卷号、页码或定理编号。
- filtration、measurability、adaptedness 和 conditional expectation 必须成为显式 information-set contract；无条件均值、全样本回看或事后可计算量不能冒充当时可见信息。
- LLN、CLT、极限换期望和普通标准误都依赖 IID、矩、支配或其他条件；金融 bars/trades/events 默认检查依赖、异方差、有效样本量和替代推断，不按行数套 `sqrt(n)`。
- Markov 标签要求当前状态对目标未来分布充分；只拟合下一期均值不够，drawdown、running max、entry、inventory、regime 等路径状态若影响决策必须显式扩充并做 OOS 反证。
- stopping policy 必须在每个时点仅由当时 filtration 决定；事后找全路径极值、最佳退出或最优 exercise 属于未来信息。Optional-sampling 结论还需核验有界性、可积性和 martingale 类型。
- convex transform、Jensen inequality 或 submartingale 标签只给指定条件下的期望方向；不证明可执行 alpha。payoff convexity、interest/dividend/carry、integrability、conditioning 和 transaction cost 必须同时核验。
- first-passage、reflection、barrier 或 liquidation 模型必须绑定 DGP、event clock、boundary、continuity/jump 和 observation rule；模型路径首次触碰不等于 quote 可见、订单成交、强平引擎触发或账本事件。
- 风险中性定价、复制和对冲结论依赖无套利、可交易性、连续性和模型假设。
- measure change 必须保存 source/target measure、Radon–Nikodym density、support/equivalence、numeraire、currency/unit、filtration 和 integrability；density/state-price density 不得与 physical probability、likelihood、price 或 expected return 混写。
- self-financing 是现金流合同，不是“策略理论上自洽”的同义词；真实系统仍由 fills、positions、cash、fee、borrow、funding、margin 和 corporate actions 推导财富变化。
- log-utility、state-price-density 反比终值或其他效用最优解只在指定 utility、budget、positive wealth、complete market 和 replicability 下成立；不得直接命名为 Kelly、CAPM、目标仓位或杠杆上限。
- law、probability mass、density、conditional density、likelihood 和 empirical histogram 必须分类型；density 不保证存在，条件密度只在分母有效的 almost-everywhere 区域定义，Gaussian 零相关推独立不得外推。
- 等价风险中性测度存在至多先支持 no-arbitrage 的相应方向；测度唯一、claim 可复制、市场完备和价格唯一必须分别证明，连续时间极限也不自动消除离散执行与现实不完备。
- Brownian/random-walk limit 必须声明time/space scaling、interpolation、convergence对象与拓扑；终点CLT、连续插值或更细bar不能证明真实路径连续、Gaussian、独立增量或Markov。
- quadratic variation、realized variance和volatility不得混名；保存partition/clock、integrated horizon、microstructure/jump treatment与estimator limit，连续模型的`[B]_t=t`不能直接成为离散数据事实。
- Itô integral只接收相对filtration adapted且square-integrable的integrand；`dB*dB=dt`等微分记号仅为quadratic-variation助记，规格和测试以积分形式、近似范数及离散误差为准。
- SDE/PDE/Feynman–Kac证据必须共同保存coefficient regularity、existence/uniqueness、state/transition density、terminal/boundary、integrability和numerical error；三种表示共享同一模型假设，不能算三份独立确认。
- Girsanov density必须证明为真martingale并满足指数可积等充分条件；market price of risk还要求volatility非零。仅有local martingale、形式指数或drift substitution不得发布新测度。
- martingale representation只覆盖生成filtration的风险源；新增jump/default/information/noise后必须扩展随机源和hedge span。EMM存在、EMM唯一、市场完备、claim可复制与现实可成交分别留证。
- 资产数等于风险源数不证明市场完备；`HedgeSpanEvidence` 必须保存 volatility/loading matrix、rank、singular values/condition number、风险溢价一致性、EMM存在/唯一和约束后可交易span。奇异结构可能对应套利，也可能对应不可复制风险。
- barrier contract 必须声明连续/离散监控、observation source、event/venue clock、边界是否包含、gap/overshoot、outage与latency；first touch不是fill、knockout确认或ledger事件。临近障碍的Greeks不稳定时必须有hard cap和残余/gap stress，书中tolerance不得迁移。
- Asian、lookback等路径依赖对象必须把accumulator、running maximum等加入可回放state，并冻结sampling calendar、fixing、频率、缺失规则和单位；连续积分与离散算术平均不得混写，terminal spot不足以重建payoff。
- quadratic/cross variation识别的是covariance而非唯一factor loading；factorization需版本化并报告正交旋转不可识别性，`rho=±1`等退化情形必须触发rank-collapse审计，有限样本realized covariance不构成Brownian结构证明。
- payoff若依赖不可交易的指数、oracle或barrier reference，则相关风险可能不在hedge span中并导致EMM不唯一；不得宣称精确复制或唯一hedge price，必须报告canonical reference、basis、liquidity、多腿fills和residual-risk scenarios。
- American exercise必须建成filtration-adapted stopping policy和obstacle/complementarity evidence，保存continuation/stopping region、边界误差、未达到最优时刻、notice/assignment/settlement与seller hedge；supremum不保证存在可达到的有限最优时刻。
- dividend/corporate action是带PIT时间戳和现金账本的跳变事件；冻结ex/record/pay date、amount、currency、tax/withholding、adjustment和reinvestment。无股息凸payoff的“不提前执行”不得外推，连续yield不得静默替代离散股息。
- forward price、forward contract MTM、futures price和expected future spot是不同对象；`DerivativeCashflowEvidence` 必须分开trade/delivery、daily settlement、margin、cash interest、credit/collateral和delivery ledger，contango/backwardation不得直接解释为alpha。
- term-structure模型必须对整组maturities共享同一no-arbitrage measure与drift restriction；curve evidence版本化instruments、quotes、day-count、calendar、interpolation/bootstrap、collateral、benchmark/fallback、initial curve、volatility和maturity consistency，逐期限独立拟合禁止冒充无套利曲线。
- 只有先证明有限维联合Gaussian，mean/covariance才决定完整law；随机integrand可能保留低阶矩却破坏Gaussian，累计过程也可能丢失Markov状态。模型卡必须保存coefficient随机性、finite-dimensional diagnostics和state augmentation。
- 精确拟合初始曲线、闭式解或多次微分恢复参数不证明calibration稳健；保存原始quote、插值与regularization、导数敏感度、parameter identifiability、non-parallel shift、tail与multi-factor challenger。一因子完美相关结构不得作为现实曲线风险模型默认值。
- square-root rate/factor模型必须保存Feller/boundary classification、state domain、exact/approximate transition和discretization positivity tests；非负连续SDE不能证明离散模拟无负值，也不能覆盖零/负利率制度或当前曲线适配性。
- 多因子affine模型必须区分latent state、可观测yield和模型强制identity，审计diffusion covariance在全状态域的PSD、factor observability、parameter Jacobian/conditioning、多解与OOS curve residual；因子数增加不构成识别或风险覆盖证据。
- numeraire只能是严格为正的可交易资产；`NumeraireMeasureEvidence` 成对保存asset、currency/unit、collateral、horizon/maturity、source/target measure、density、support/equivalence和integrability。换numeraire只改变单位与drift表示，不创造alpha或删除self-financing/fill/cash ledger。
- BGM/LIBOR market model只作历史结构来源；instantaneous forward、simple tenor LIBOR、RFR term rate和compounded-in-arrears rate不得混写。当前实现前必须重建benchmark/fallback spread、fixing/payment calendar、accrual/day-count、collateral、multi-curve、vol cube和forward-measure合同。
- lognormal/positive-rate标签不保证SDE存在或不爆炸；任何proportional-volatility模型都必须有existence、non-explosion、boundary和numerical stress。caplet-implied分段volatility是校准结果，不是physical forecast或交易参数。
- Brownian bridge、smoothing或任何conditioned-path generator若使用终点/未来约束，只能用于标记清楚的scenario、imputation或retrospective analysis；不得把conditioned future endpoint生成的状态回填为PIT feature、Signal或holdout证据。
- 对含股息资产，风险中性martingale对象通常是含再投资现金流的discounted total-return process，而非裸ex-dividend price；corporate-action event、税费、withholding、reinvestment和cash ledger必须保留，连续yield只是一种模型近似。
- Monte Carlo expectation、Feynman–Kac表示和PDE解是同一DGP/measure/payoff的等价计算视角，不算独立模型确认；state、terminal/boundary、regularity与numerical error必须共享同一versioned contract。
- American value、Snell envelope、complementarity和smooth pasting只在adapted stopping、payoff/discount contract及相应连续性条件下成立；expiry、jump、dividend或离散monitoring可破坏平滑边界。保存exercise notice/cutoff/assignment/settlement、boundary error和tie-breaking，未来路径选点一律视为泄漏。
- `FXContractEvidence` 必须保存base/quote与domestic/foreign方向、payment currency、notional、spot/forward convention、两侧rate/curve、numeraire、measure、collateral和settlement；汇率取倒数会改变Itô drift，不能在同一measure下机械反演期望或价格。
- forward measure只在对应bond maturity/horizon内有效；随机利率下的闭式option公式若依赖constant forward-price volatility，必须把该假设、asset-bond loading difference和self-financing bond hedge列为独立验证项。
- yield-curve bootstrap是instrument cash flows到discount factors的versioned transformation；保存quote hierarchy、cash-flow schedule、day-count/calendar、interpolation/extrapolation、collateral/default、benchmark/fallback和reconciliation。单一yield、short rate或初始curve拟合不证明跨maturity无套利。
- short-rate/affine模型若直接在risk-neutral measure构建，其factor dynamics只服务pricing，不得解释为physical rate forecast；HJM/curve模型必须对所有maturities共享drift restriction，逐期限独立校准不得冒充一致term structure。
- jump process的交易exposure必须predictable，工程上使用pre-jump position和event前可见state；post-jump观察后同刻改仓属于anticipation。jump QV、continuous QV、simultaneous jumps、event clock和compensator分别留证。
- jump measure change可调整intensity与jump-size law，但等价measure不得创造原support外事件；`JumpRiskEvidence`保存physical/pricing intensity、support、size law、density、compensator、Brownian dependence、EMM multiplicity和hedge residual。市场价格校准不识别physical tail。
- 有限jump-size模型的可复制性依赖每个独立jump source和Brownian source是否有足够可交易span；连续jump distribution通常不完备。pricing输出必须报告selected EMM/model risk，不得把一个校准价格描述为唯一无模型价格。
- 数学上可定价不等于现实中可执行；离散调仓、跳跃、成本、流动性和保证金必须另外建模。
- 不涉及衍生品估值或对冲的策略，不应为了形式复杂度强行引入连续时间模型。
- LIBOR、历史curve模型和旧市场惯例只作概念来源；用于当前利率或多币种系统前必须重建benchmark、fallback、tenor、compounding、day-count、calendar、collateral和curve conventions。
- OCR 公式不得直接进入生产代码；必须回看原书或权威公式来源并补数值测试。

### 5. 尾部风险与极值模型

- VaR是绑定loss sign、position side、return convention、amount/currency、as-of、horizon和tail probability的条件分位数，不得称“最大损失”；ES、完整loss distribution和scenario stress必须并列报告。
- normal/EWMA、RiskMetrics、平方根时间和normal-correlation portfolio VaR只作强假设基线；非线性头寸、厚尾、jump、volatility clustering、时变相关与流动性压力必须另建风险证据。
- empirical quantile、quantile regression、GEV、Hill/Pickands、POT/GPD和extremal index是独立候选族；threshold、block、tail order、covariates、run length与软件参数化均在训练折选择并进入trial ledger。
- 每个尾部估计必须披露effective exceedance/cluster count、support与moment existence、parameter/model uncertainty、threshold sensitivity和dependence diagnostics；渐近理论、稳定图或无ACF不证明有限样本可靠或IID。
- ES并非自动稳健：尾均值不存在、exceedance过少或阈值不稳时必须blocked；return level与单期VaR、多期alpha-root与通用时间缩放不得混写。
- 任何centering、volatility filter、threshold或tail covariate只使用当时可见训练前缀；全样本去均值、事后看图选阈值、逐项删“不显著”变量和挑最有利方法均属泄漏/多重试验。
- `TailRiskForecastEvidence`至少保存risk contract、fit scope、tail method、effective tail sample、VaR/ES interval、extremal index、breach sequence、coverage/independence/ES calibration、scenario stress、alternatives和current-HEAD provenance。
- 尾部输出只进入Portfolio/Risk；breach、数据、模型、账本或校准异常默认fail-closed，不得由VaR/ES直接生成Signal、TargetPosition、OrderIntent或promotion结论。

### 6. 多变量动态、协整与相对价值

- CCM、VAR、VMA或VARMA只描述给定information set下的线性联合动态；异步时钟、共同市场、stale quotes、厚尾和conditional heteroskedasticity必须先审计，lead-lag、显著系数或portmanteau结果不得称因果或信息优势。
- reduced-form innovation covariance不识别结构冲击；Cholesky structural form和IRF依赖component ordering，必须保存ordering/restriction alternatives、区间与rolling stability。
- dimension、lag、deterministic terms、zero constraints、VAR/VMA/VARMA family和regularization都在训练折选择；`k²p`参数膨胀时优先简单/shrinkage baseline，禁止按全样本t值删项后复用同一检验。
- cointegration只适用于integration order明确且存在稳定linear combination的序列；lag、rank、constant/trend、normalization、window、break、pair和threshold均是相关trial，Johansen critical values必须匹配specification。
- `β`是normalization-dependent relation，`α`是conditional adjustment；cointegration、同业标签、高R²、spread ADF或opposite-sign loadings均不保证经济机制、收敛时间、market neutrality或关系持续。
- pairs/relative-value evidence必须重建self-financing dollar weights、gross/net/factor/sector/FX exposure、borrow/recall、dividend/corporate action、multi-leg fills、margin/cash runway、cost/capacity、gap与delisting；log-price spread increment不是fill-ledger PnL。
- 全样本筛pair、估hedge ratio/mean/std、用邻近未来点替换异常值、看结果选entry/exit或假设spread“必回归”均被禁止；关系break触发Risk降仓/冻结和新版本审批，不得静默重估。
- `MultivariateDynamicsEvidence`与`RelativeValueRelationEvidence`只产生Forecast/relationship/risk evidence；Strategy不得直连broker，cointegration或IRF不得直接解锁TargetPosition、OrderIntent、paper/live或promotion。

### 7. PCA、统计因子与因子组合

- factor必须声明用途为risk decomposition、forecast feature、dimension reduction或mimicking portfolio；market/macro/fundamental/statistical factor的可观测性、构造方向和证据语义不可互换。
- macro surprise必须绑定PIT release/vintage/consensus和训练期forecast model；模型residual只表示给定information set下innovation，不自动是市场未预期信息或因果冲击。
- fundamentals、industry、universe、breakpoints、rebalance与delisting必须PIT；当前分类回填历史、全样本去均值/标准化/PCA/排序或修订后宏观数据均属于泄漏。
- PCA最大化样本方差而非expected return；covariance/correlation choice、scale、window和universe改变components，eigenvector sign/rotation非唯一，near-equal eigenvalues应比较subspace而非单一loading。
- explained variance、scree elbow、latent factor标签、高R²、低specific variance或factor-count检验不得单独证明风险模型准确、经济机制或alpha；必须报告residual cross/serial/vol/tail、eigen-gap、loadings/subspace drift和OOS utility。
- factor model默认的diagonal specific covariance、fixed exposure、normality和independence均需challenger；高维covariance/inverse必须检查PSD、conditioning、shrinkage和estimation error。
- PCA L2-normalized weights不是budgeted/self-financing portfolio；任何factor-mimicking组合另过gross/net、cash、borrow、turnover、cost、capacity、multi-asset fills和ledger对账。
- `FactorModelEvidence`与`DimensionReductionEvidence`版本化factor definition、PIT construction、fit transform、factor count/rotation/alignment、covariance、residuals、stability与economic falsifier；latent score默认只作compression/risk state，不能直接生成订单。

### 8. 条件协方差与动态相关

- conditional covariance必须绑定vector、joint clock、currency、mean residual、forecast horizon和information set；缺失/异步市场不能靠静默取共同日期假装同步。
- EWMA、shrinkage与简单factor covariance是强制基线；DVEC、BEKK、CCC/DCC、Cholesky或factor-vol只有证明proper-loss、portfolio-risk calibration和stress增量后才可采用。
- 每个forecast matrix必须检查symmetry、PSD、eigenvalue floor、condition number与reconstruction；非PSD、数据断层、optimizer failure或校准异常默认fail-closed。
- Cholesky参数和sequential high-dimensional model依赖instrument ordering；保存理论顺序、permutation alternatives与joint-refit差异，禁止把ordered regression系数解释成因果spillover。
- DCC target/window/scalars、correlation transform、GARCH order、distribution/df、initial state与factor count均为训练内trial；全样本sample correlation/PCA或按显著性删项后复用检验均被禁止。
- diagnostics使用完整`Σ^-1/2 a` whitened innovation，并联合检查linear、squared、cross-product、tail和break；逐资产除sigma与Ljung–Box未拒绝不足以证明joint model。
- crisis correlation、high persistence、smooth curve、higher likelihood或多模型VaR接近都不是准确性证据；报告realized-proxy loss、VaR/ES breach、model disagreement、correlation shock和liquidity/jump stress。
- `ConditionalCovarianceForecastEvidence`进入Portfolio/Risk并受model-risk budget、concentration与exposure constraints约束；Strategy不得由dynamic correlation直接生成Signal、TargetPosition或OrderIntent。

### 9. 状态空间、Kalman 滤波与潜在状态

- state-space必须显式区分transition state、process shock、observation、measurement error及各自clock；state只是给定模型的信息压缩，不是可直接观测的市场真值或经济机制。
- `s(t|t-1)`、`s(t|t)`、`s(t+j|t)`与`s(t|T)`使用不同information set；生产研究只允许filtered/predicted output，smoothed state/disturbance必须标记`future_conditioned=true`并隔离到事后诊断。
- system matrices、noise covariance、initial state、diffuse treatment、dynamic coefficient variance、season/cycle specification与fit window均是训练内trial；验证期只做冻结参数的顺序filter，禁止重新平滑验证区间。
- Kalman optimality和independent Gaussian innovations依赖线性高斯、正确模型、已知参数和初始化；厚尾、jump、regime、nonlinearity、correlated errors与估计误差必须通过challenger和uncertainty体现。
- missing observation只跳过measurement update并传播更大不确定性，不等于零值、插值或missing-at-random；partial vector、irregular gap、informative missing和全缺失区间分别保留证据。
- innovation diagnostics使用完整forecast-error covariance whitening，并检查linear、squared、cross、tail、break与coverage；全样本参数下回算innovation不得称真实OOS，未拒绝diagnostics不得称模型正确。
- time-varying alpha/beta、trend、seasonal、cycle与ARMA state representation均可能不唯一；random walk、平滑曲线、窄区间和latent标签不能证明因果、结构稳定或预测增量。
- `StateSpaceForecastEvidence`保存PIT regressors、matrices/dimensions、initialization、fit fold、numerical method、innovation/missing diagnostics、filtered/predicted/smoothed lineage、forecast uncertainty与alternatives；输出仍只进入Forecast或Portfolio/Risk。

### 10. MCMC、Bayesian 计算与后验预测

- posterior由likelihood、prior、parameterization和conditioned data共同决定；所谓noninformative prior也可能在弱识别、边界、高维或transform下主导，必须保存prior predictive与敏感度。
- burn-in、单条稳定trace、一次诊断或相似多起点均不证明收敛；每个关键parameter/function/tail量报告多链rank/scale诊断、ESS、MCSE、autocorrelation、boundary mass与mode coverage。
- posterior dispersion、sampling variability与Monte Carlo error不可混写；raw draws通常相关，iteration count不是ESS，普通draw t-ratio不得代替posterior probability、credible interval、decision loss与MCSE。
- Gibbs block、MH proposal、Griddy support/grid、FFBS mixture/linearization、state blocking和parameterization都是算法trial；记录acceptance、stickiness、divergence、ESS/sec、grid tail mass与approximation challenger。
- missing/outlier/volatility/regime latent draws条件于模型；full-sample imputation、FFBS path、smoothed outlier或state probability使用未来信息，只进入派生诊断层，不覆盖raw数据、不进入同时间戳Signal。
- posterior predictive必须从forecast origin可得posterior出发，future regressors只能是已知值或显式scenario；分别传播parameter/state/process uncertainty并用coverage、PIT/rank、proper loss和tail breach校准。
- Bayesian VaR、SV、dynamic covariance或regime forecast只覆盖模型内不确定性，不自动覆盖结构break、数据修订、流动性、execution、ledger或model misspecification；必须并列simple baseline与stress。
- `BayesianComputationEvidence`和`PosteriorPredictiveEvidence`保存model/prior hashes、chain seeds、warmup/draws、sampler diagnostics、ESS/MCSE、latent information-set lineage、predictive calibration与current-HEAD provenance；输出仍停在Forecast或Portfolio/Risk。

## 四、回测与证据规则

来源：`RES-01`、`RES-02`、`STR-05`、`STR-07`。

### 1. 先定义反证条件

- 在看最终收益前写清零假设、基线、成功阈值和失败条件。
- 客观规则必须可由另一个 Agent 在相同数据版本上复跑。
- 记录所有 trial、失败配置、人工排除和搜索空间变化。
- 书中历史结果只用于确定问题，不得作为本项目先验通过证据。
- Sharpe、MAR、drawdown、R²和回报平滑度测量不同对象；高或稳定的单一指标不能排除杠杆、集中、流动性、gap、crowding和隐藏尾部，风险结论必须按mandate使用成组指标与压力场景。
- 策略目录、参考文献或只含机制叙述而无数值模拟、回测和实证研究的来源，只能生成研究问题；不得被包装为候选有效性、参数依据或 promotion evidence。
- options、structured credit、convertibles、tax arbitrage、distressed、real estate 与 infrastructure 条目在缺少对应资产主数据、法律/税务、定价、融资、执行及 fill-ledger 合同时保持 blocked/out-of-scope；不得借相似名称迁移到 BTC 或美股实现。
- 均线、估值、52周高点、盈利/收入、动量加速度、fresh momentum、行业轮动和防御资产集合均是独立模型族；必须登记搜索路径、有效trial和复杂度预算。
- 可编程只证明规则可重复，不证明PIT、有效、可交易或可提升；signed rule output必须停在Signal/Forecast，仓位由Portfolio/Risk独立决定。
- 传统解释与反向解释、阈值/状态变体和人工例外均是独立trial；不得看结果后翻转方向、移动边界或重命名regime而不登记新候选。
- 评价必须使用分层基准：无信息/placebo、cash或risk-free、buy-and-hold、incumbent及匹配市场暴露与仓位偏置的基准；不得挑最容易战胜者。
- 全样本均值去趋势会泄漏未来；任何centering、detrend或normalization只能在训练折拟合并冻结，且诊断收益不得替代fill/position/cash ledger PnL。
- 人工图形和主观forecast只能生成假设；若要评价，必须在结果未知时冻结方向、horizon、favorable/adverse threshold、expiry、失败条件、输入快照和观察者，并保留完整四格分母、负例及未触发记录。
- 图形、叙事、近期鲜明案例、权威引用和研究员信心不是证据；用blinded replay、random-walk/placebo chart、base rate、完整case count和竞争解释反制事后、确认、可得性与代表性偏差。
- 单笔/单期输赢评价的是结果，不自动评价事前决策质量；近期连亏、幸运短记录和成功管理人案例均不得触发未登记的参数修改或系统替换。
- 采用observation→hypothesis→prediction→verification→conclusion五阶段记录；盈利或显著只与候选一致，不构成证明，状态使用rejected、inconclusive或corroborated-research-only，不使用proven/ready。
- 每项统计结论先定义estimand、目标总体、sampling unit、依赖结构、统计量和可靠性声明；bar/trade/event数量不是天然独立样本数，必须报告effective sample size。
- `SE=σ/√n`、普通IID bootstrap、逐行permutation和CLT正态近似都要求可辩护的抽样/依赖条件；金融序列默认比较HAC、cluster或block方案并保留naive结果仅作对照。
- p值仅为H0与检验流程成立时当前或更极端证据的概率，不是H0为真概率、候选成功概率或本次拒绝错误概率；大p值写`fail to reject/inconclusive`，不得写接受H0。
- frequentist CI描述重复抽样程序的覆盖率，不给已实现区间赋参数后验概率；CI必须与effect、方法、依赖假设和coverage诊断一并报告。
- bootstrap与permutation测试不同null：前者重采样规则收益，后者依赖signal与未来收益在H0下可交换；若破坏状态持续、regime、calendar、跨规则相关或波动簇，随机化结果无效。
- alpha、单双尾、minimum effect、Type I/II loss与target power须预登记；固定0.05和“Type I总比Type II严重”不是项目通用决策规则，统计显著不等于经济显著。
- 赢家统计量必须由复制完整selection operator的null评价；trial count、effective n、候选相关、正向离群与winner gap共同报告，不得用单规则p值评价多规则搜索赢家。
- holdout一经查看即失去virgin状态；walk-forward/test段也不能反复参与选择。WRC、MCP、MX shrinkage仅作待复核历史方法，不得替代nested selection、PBO/DSR/CPCV与current-HEAD evidence contract。
- 理论必须写成可证伪的竞争机制；“市场非随机”“投资者有偏差”或“套利有限”只能生成候选，不能证明alpha或解锁执行。
- 候选必须用`edge_type`区分mispricing、risk premium、liquidity service、information diffusion与institutional constraint；未被某一风险模型解释的收益不得自动命名为mispricing。
- 风险溢价候选必须把crash、liquidity、funding、crowding与capacity纳入Portfolio/Risk预算；承担真实风险或提供流动性服务的回报不能称为无风险alpha。
- 规则搜索应由declarative spec确定性生成完整candidate registry，保存input lineage、transform DAG、operator/state、参数域、方向反转、失败候选、fold-level结果与universe checksum。
- 已发表论文、书籍规则、研究员记忆与共享历史探索均属于prior snooping；无法重建的既往试验量必须披露并降低结论上限，不能把书中规则登记为fresh hypothesis。
- 结果报告必须并列unadjusted与selection-adjusted effect/p/CI、winner gap和null hash；负结果以`fail_to_reject`、`rejected`或`inconclusive`保留，不得漂白或只保存冠军。
- 复杂度、feature、模型族和组合逻辑都是新的搜索维度；采用内层拟合、外层选择和独立outer validation，任何用于选择复杂度的validation都不再是holdout。
- RES-02中的WRC/MCP数值、6,402规则、S&P区间、最佳规则、p值、置信区间和阈值均为不可迁移的历史案例，不得作为当前BTC或美股参数、基准或gate证据。
- return合同必须明确simple/log、gross/net、cash-flow、corporate action、FX/numeraire、frequency、session、unit与aggregation；不同语义不得在模型、组合、执行和PnL层混用。
- portfolio simple return按期初价值权重精确聚合，portfolio log return线性加权通常只是小收益近似；权重、再平衡、short dividend、borrow、funding和margin必须进入证据。
- 边际厚尾或normality rejection不产生预测力；时间序列模型应声明conditional information set、状态变量、矩存在性、依赖、break与rolling diagnostics，并先与简单基线比较。
- 零ACF、Ljung–Box未拒绝或PACF截尾只约束线性均值依赖，不证明IID、white noise或模型充分；继续检查conditional variance、tail、nonlinearity、break与calibration。
- AR stationarity、MA invertibility和unit root必须按明确的多项式/根约定分别验证；近单位根、公共因子和optimizer失败不得静默变成有效模型。
- order、maximum lag、AIC/BIC、ADF deterministic term/lag、seasonal period、HAC bandwidth和fractional `d`都属于模型选择自由度，必须fold-local并进入trial ledger。
- ADF未拒绝只能写`fail_to_reject_unit_root_null`；不得写“证明含单位根”，且需与break、trend-stationary、near-unit-root及其他预声明检验竞争。
- serial correlation本身不必然使OLS系数不一致；exogeneity决定一致性，HC/HAC只能在其适用条件下修正协方差，不能修复endogeneity、spurious regression或泄漏。
- differencing可以去除随机趋势，也可能过度差分或破坏cointegration；level/difference/error-correction候选必须由独立时间序列合同协调。
- forecast必须绑定origin、horizon、information set、loss与baseline；区间同时披露innovation、parameter、model、transform-back和regime uncertainty，不复制固定1.96近似。
- 慢衰减ACF不自动证明long memory；structural break、regime mixture、volatility clustering和sampling artifact必须作为竞争解释。
- volatility字段必须声明physical/risk-neutral、variance/standard deviation、instantaneous/integrated、horizon、annualization、session与proxy；implied、realized和conditional forecast不得混写。
- 单期squared return是高噪声variance proxy；低相关不自动否定forecast，评价需披露proxy measurement error、forecast loss、coverage与baseline。
- ARCH/GARCH order、innovation distribution、tail/skew参数、initial variance、optimizer、mean equation和删参均属于联合trial family，必须fold-local并保留失败拟合。
- GARCH persistence接近1不等于IGARCH；unit-root variance、break、regime和misspecification需竞争，finite second/fourth moments与positivity分别验证。
- EGARCH/TGARCH的sign asymmetry不证明财务leverage因果，GARCH-M系数不证明risk premium；机制、预测和风险预算证据分离。
- standardized residual的Ljung–Box未拒绝只支持有限线性诊断，不证明IID或模型充分；继续检查squared/absolute dependence、tail、sign bias、break和calibration。
- `Σ intraday return²`命名realized variance而非volatility；采样频率、microstructure、overnight、jump、auction、tick与跨venue时钟必须留证。
- 波动forecast只进入Portfolio/Risk作为风险输入；不得由Strategy或模型直接映射数量、杠杆、限额或订单。
- nonlinearity test只检验指定linear、Gaussian、IID或参数化null；拒绝可能来自heteroskedasticity、heavy tail、break、regime mixture、遗漏变量、时钟/数据错误，不识别正确模型、机制、方向或alpha。
- threshold variable、delay、threshold、regime count、transition function、state dynamics、kernel/bandwidth、network architecture/activation/regularization/optimizer/seed均属模型选择自由度，必须fold-local并进入完整trial ledger。
- TAR的observed regime与Markov switching的hidden state不可混写；hidden model需区分filtered、predicted与smoothed probability，state label和expected duration不得直接变成硬仓位规则。
- kernel/local smoothing必须报告support density、boundary、effective local sample、bandwidth sensitivity与维数；普通leave-one-out会破坏时序依赖，改用purged rolling inner validation。
- neural network的universal approximation只证明表示能力；必须报告多seed分布、失败拟合、calibration、简单线性/random-walk基线与nested OOS，单次命中率或较低sample SSR不构成增量证据。
- nonlinear multi-step forecast的bootstrap必须版本化innovation distribution和forecast origin，并分开报告Monte Carlo、parameter、state、model与regime uncertainty；固定path count不是通用充分性标准。
- directional、magnitude与distributional forecast评价回答不同问题；loss、threshold、utility、horizon和baseline预注册，MAPE近零分母、class imbalance与预测区间校准需单独处理。
- regime subgroup改善只有在regime于forecast origin可见、分组预注册且有效样本充足时才可报告；局部危机期胜出不能覆盖整体不增量、成本、容量或状态漂移。
- nonlinear model输出停在`Signal`或`Forecast`；Portfolio/Risk独立处理uncertainty、risk budget、TargetPosition与no-trade，任何state probability或NN score不得直达OMS/order。
- “高频”必须绑定数据层级与真实时钟；daily、bar、trade、quote、order、L2/MBO不可混写，缺逐笔quote/L2、sequence与current venue rule证据时不得声称HFT、price discovery或可执行microstructure edge。
- 非同步last trade、stale price与bid-ask bounce可制造lead-lag、负autocorrelation和portfolio predictability；所有短周期信号先对synchronization、mid/quote/trade price、spread与trade-sign dependence做反事实分解。
- microstructure数据合同至少保存canonical instrument/venue、event/receive/sequence clocks、session/auction/half-day、tick/lot/rule hash、correction/cancel/bust、late/out-of-order、duplicate与same-timestamp tie-break。
- 高频清洗是推断的一部分：保留raw immutable记录、规则版本、drop/repair reason、前后计数、sequence gaps和clock-quality摘要；不得静默删除overnight、zero duration、bad print或after-hours。
- trade-level大样本不等于独立有效样本；显著性必须处理event clustering、serial/cross dependence、session blocks与effective n，历史tick制度下的t ratio和反转概率不可迁移。
- duration必须区分between trades与between price changes，并冻结zero-duration、cross-session gap和diurnal adjustment；no trade不等于no information，也可能是halt、latent liquidity、report delay、data loss或venue migration。
- ordered price、action/direction/size与PCD联合模型的category、conditioning order和sampling process属于estimand合同；只保留price-change trades会改变样本与目标，不得与all-trades结果直接比较。
- ACD order、innovation distribution/hazard、initial state、diurnal function、threshold/delay和删参为联合trial family；normalized-residual ACF未拒绝不证明IID，仍需tail、hazard/PIT calibration、break与OOS loss。
- lag-1 transaction reversal常是spread与price discreteness，不是净成本alpha；研究必须扣fee/spread/impact/latency并保留unfilled counterfactual，probability或duration forecast仍只输出`Forecast`。
- 单序列before/after intervention显著不证明制度因果；market-rule研究需准确event date、anticipation、control/counterfactual、共同趋势、并发事件与robust inference，历史decimalization案例只作方法定位。
- continuous-time模型必须标记用途与测度：physical DGP、risk-neutral pricing、hedging和scenario generator不可混写，risk-neutral drift/implied parameter不得作为physical return forecast。
- 零return ACF或Ljung–Box未拒绝不证明GBM、independent increments、normality或constant volatility；drift尤其弱识别，单年样本年化结果不得进入expected-return规格。
- Black-Scholes复制依赖continuous self-financing hedge、complete/frictionless market、no jumps、可借可卖和无限流动性；现实需另报discrete hedge、spread/impact、latency、borrow/funding、margin与gap residual。
- option contract与定价输入必须版本化underlying、payoff、multiplier、exercise/settlement、curve/day-count、dividend/carry、borrow、surface snapshot和corporate action；公式相同不代表合约相同。
- put-call parity与lower bound只是满足输入和可交易假设下的no-arbitrage关系；未验证双边quote、费用、借券、保证金、exercise和多腿原子性前不得称可实现套利。
- Brownian continuity、lognormal support和constant parameters是候选DGP，不覆盖jump、halt、limit、default、stochastic vol与regime；pricing model value也不是市场事实或账本PnL。
- jump diffusion承认厚尾但使市场不完备；jump intensity/size、diffusive volatility与risk premium/measure联合识别，不能以“jump可分散”默认唯一价格。
- continuous-time估计必须记录observation scheme、discretization/transition approximation、irregular clock、microstructure、parameter CI、optimizer/MCMC与alternative models；path count或更细time step不修复model bias。
- pricing公式进入L3前至少通过put-call parity、monotonicity、zero-vol/zero-jump、maturity、time-step、series truncation和Monte Carlo/library交叉fixture。
- 非衍生品趋势策略默认不因数学完备引入SDE复杂度；Greek、price、implied vol和jump probability仍只作risk/forecast evidence，不得直达TargetPosition或order。

### 2. 切分与泄漏

- 时间序列不使用随机 K-fold。
- 切分按完整信息区间而非样本起点：每个事件保存feature依赖/available time与label`t0/t1`，闭区间相交时从训练集purge；边界包含关系、同端点和censored事件必须有确定语义。
- embargo隔离测试结束后的序列依赖，只能按预注册的最长lookback、label horizon、发布延迟、bar/session语义确定；书中固定`1%T`不得直接采用，需要时再采用CPCV。
- 标准化、协方差、波动率和特征选择只能在训练数据上拟合。
- imputation、bar/采样阈值、fracdiff、PCA、class/uniqueness weight、calibration和early stopping同样必须fold-local；splitter、输入hash、purged IDs与fold hash全部留证。
- purge/embargo只降低已知时间区间泄漏，不能修复未来修订、全样本预处理、跨资产共享信息或反复选择；K和embargo variant也必须计入trial ledger。
- OOB、普通K-fold、仅`shuffle=False`的StratifiedKFold或score随K上升后出现平台，都不得称为无泄漏证据。
- 已看过的 holdout 必须锁定；observe-only 数据不得反向用于选参或替换候选。

### 3. 标签事件合同

- 标签是版本化实验定义，不是客观真值；每个事件保存feature/available time、t0、vertical t1、profit/stop barrier、volatility target、side source、first touch、cost、censor/tie/gap和label span。
- feature、波动率、threshold、rare-label策略只在训练折拟合；标签可使用未来结果，但其完整信息区间必须提供给purge/embargo，不能只按起点切分。
- triple-barrier的触达不等于真实fill；同bar双触达、gap、停牌、周末、partial fill、spread、fee、impact和latency必须明确降级或交给execution simulator。
- meta-labeling只在外生primary side上学习act/pass；secondary probability属于Forecast置信度，Portfolio/Risk独立决定TargetPosition，OMS独立决定执行。
- 删除rare labels会改变目标总体；必须按训练折版本化并保留被删数量、tail含义和替代class-weight基线，禁止静默删除失败/尾部事件。

### 4. 非IID样本权重与重采样

- label span重叠会共享底层回报；事件数、bar数、交易数和bootstrap draws都不能直接称为独立样本或独立bet。
- indicator、concurrency、average uniqueness、resampling probability和class frequency必须按训练fold计算；未来t1可用于训练标签权重，但不得成为测试/实时feature。
- sequential bootstrap只降低当前抽样集合的信息冗余，不保证IID、无泄漏或更高OOS收益；仍需purged validation和相同trial budget的标准bootstrap基线。
- uniqueness、return attribution、time decay和class weight目标不同，必须分字段保存并做消融；最终权重报告归一化、集中度、零权重和effective sample size。
- 时间衰减和稀有类加权会改变目标分布，参数只能在validation选择；结构break应独立检测，不能靠衰减或删除旧样本静默掩盖。

### 5. 超参数搜索是模型选择

- grid/random/Bayesian search都必须预注册模型族、完整space/distribution、边界来源、预算、seed、score、tie、refit和失败规则；任何搜索空间变化都新增trial。
- 内层purged/embargo CV只选参，外层purged/embargo CV评估包含搜索在内的完整流程；outer与holdout不得反馈参数范围、score或模型族。
- 保存每个候选的fold scores、fit状态、耗时、sample-weight路由和candidate manifest；不得只保留best params/best score。
- log-uniform仅用于有依据的正值乘法尺度，不能覆盖零/负/分类参数；其上下界本身必须登记为研究选择。
- accuracy、F1和log-loss优化对象不同，均不是PnL；至少报告class/regime损失、proper score、calibration和经济cost matrix。
- 分类概率属于Forecast置信度，不能直接映射仓位；weighted log-loss或absolute-return weight也不能替代Portfolio/Risk与fill-derived PnL。
- brute force、grid、integer、annealing或quantum solver都只是候选选择器；先冻结objective、constraints、grid、candidate count、budget与baseline，所有solver/embedding/hardware变化进入trial ledger。
- finite-grid global optimum只对该离散objective成立；必须报告quantization error、unique feasible count、near-best plateau、optimality gap与forecast/covariance/cost敏感性，不得称真实未来最优。
- `sum(abs(weight))=1`、`sum(weight)=1`、cash、gross/net leverage与shortability是不同约束；zero-weight sign必须去重，solver结果仍只形成Portfolio/Risk候选。
- 量子superposition不自动提供全部解或一般NP-hard加速；当前项目对量子/QUBO保持concept/rejected，不采购、不联网、不接生产、不作为promotion evidence。

### 6. 最低验证包

- 简单基线和经济解释。
- 无未来函数与截断一致性测试。
- walk-forward / purged CV / holdout 结果。
- 参数邻域和结构变化压力。
- 基础、保守、极端三档成本。
- 年份、regime、极端行情和收益集中度。
- order/fill/position/cash ledger 可重放 PnL。
- `candidate_count`、`trial_count`、`selected_by` 和拒绝理由。

### 7. 回测只作否证与风险诊断

- 回测是单一历史路径上的反事实模拟，不是实验、因果证明或未来收益保证；主要职责是淘汰明显不可行候选并暴露仓位、换手、成本、集中度和路径风险。
- 策略、数据、label、params、cost、execution与失败条件必须在结果揭示前冻结；失败后可开新candidate，但必须引用旧结果并累计trial，禁止“从头开始”清空历史。
- append-only trial ledger记录所有候选、失败、人工排除、报告查看、模型/score/space变化和holdout访问；只保留最终赢家会系统性低估选择风险。
- PBO/CSCV、DSR或其他multiple-testing调整评估的是选择流程风险；需要完整同步trial矩阵、可分块metric和敏感性分析，不能给单策略颁发ready状态。
- walk-forward只有一条测试路径，可被反复定向；随机block/CPCV也不能创造新历史、修复PIT/成本/执行错误或替代独立前向数据。
- CPCV以`C(N,k)`个split重组`C(N-1,k-1)`条路径；N/k、group、purge/embargo和path assignment必须预注册且可重放，每条路径每个group恰有一个测试预测。
- CPCV路径共享数据和训练集合，必须报告路径相关矩阵、effective path count和保守区间；名义路径数不得作为独立样本数，也不得按`1/sqrt(paths)`制造伪精度。
- WF用于历史可部署性、paper/replay核对；CPCV属于使用未来period训练的counterfactual cross-fit诊断，不能与真实历史wealth/ledger混称。
- 即使PBO低或回测保守，PIT、purge/embargo、execution replay、fill/position/cash reconciliation、observe-only前向和current-HEAD gate仍须分别通过。

### 8. 绩效指标必须有来源和适用条件

- PnL、wealth、return、AUM、leverage、turnover和cost统一从fills、positions、cash ledger及外部cash-flow事件生成；报告不得各自重算或用mark近似替代ledger。
- 指标面板同时覆盖gross/net/long-short PnL、capacity、bet/trade/effective count、holding、turnover、HHI集中、DD/TuW、execution shortfall和risk/regime attribution。
- Sharpe必须保存原频率、return clock、risk-free、sample/effective count和serial-dependence处理；`sqrt(periods)` annualization只在IID假设明确成立时使用。
- PSR/DSR保存非年化Sharpe、T、skew、kurtosis、benchmark和完整/effective trials；它们是近似selection diagnostics，0.95或任何单阈值不得直接解锁gate。
- accuracy、precision、recall、F1和log-loss需报告class语义、base rate、calibration及退化分母；不得为改善F1任意交换positive/negative业务定义。
- 所有指标按fold/path/year/regime报告完整分布，新增metric、频率、benchmark或bet定义均计入trial ledger，禁止只展示最有利统计量。
- 横截面动量必须联合报告 universe、持仓数、holding/overlap、weight、rebalance、turnover、ADV/impact、capacity、delisting 与 active drawdown；集中和高频优势不得脱离实施成本。

## 五、forecast、组合与风险预算规则

来源：`STR-01`、`STR-02`、`STR-07`、`PORT-01` 至 `PORT-03`。

- Signal 必须先转成有单位、周期、置信度和失效条件的 forecast。
- 仓位来自 forecast、波动率、相关性、容量、成本和风险预算，不来自书中杠杆示例。
- 分类概率、z-score、active-signal并发度或归一化`[-1,1]` size都只是`normalized_exposure_candidate`；概率必须校准，重复/重叠观点按lineage和共同风险去重。
- 多个active forecast不能只按事件数简单平均；聚合必须保留side、horizon、quality、expiry、相关组和当时可知的closure，未来first-touch`t1`不得用于实时状态。
- step discretization只能作为带显式成本与hysteresis的no-trade region候选，风险退出不得被rounding延迟；阈值必须在validation确定并做turnover/cost压力。
- Portfolio/Risk在现有仓位、波动/协方差、风险预算、杠杆、保证金、容量和成本约束后输出TargetPosition；目标变化不等于OrderIntent。
- IC、IR 和 breadth 必须使用样本外或滚动证据；同一观点的高频重复不能冒充独立 breadth。
- expected return 要注明来源是风险补偿、行为偏差、结构约束还是市场微观结构。
- 组合报告必须区分 benchmark、active return、residual return、active risk 和 residual risk。
- 约束造成的 forecast loss / transfer loss 必须可见。
- 对流动性、融资、拥挤和相关性上升做压力测试；正常期相关性不能替代危机相关性。
- leveraged/inverse ETF、volatility carry和variance/skew策略包含日重置、borrow、vega/gamma、term-structure及跳跃风险；无完整衍生品/账本合同一律blocked。
- 风险平价、固定股债配置和趋势防御均只是allocation challenger；债券久期杠杆、信用、相关收敛和跳空执行风险必须显式进入压力测试。
- 每次调仓比较预期 alpha 增量和总执行成本，价值不足时允许不交易。
- strategy risk与portfolio risk分开：前者关注edge/precision/payoff/cost/有效机会随时间失效，后者关注当前持仓暴露、波动、相关和资本损失；两者都必须通过。
- 以precision、正负payoff和bet frequency反解目标Sharpe只能作二点模型敏感性；真实评估保留连续ledger outcomes、runs/tails和重叠，名义trade/forecast数不等于有效独立bets。
- profit/stop、机会阈值和频率会共同改变p、payoff、holding与cost，不能逐项独立优化；目标Sharpe、评估期和failure threshold均需预注册并计入trial。
- `P(p<p*)`只表示简化模型下未达目标的概率，不是破产概率或完整风险；必须给CI并与PSR/DSR、HHI、DD/TuW、calibration drift和前向观察联合。
- 停机/复核条件至少覆盖data quality、edge/payoff erosion、cost/borrow/funding、correlation/capacity、drawdown和风险限额；不得因低波动持仓忽略策略失效。
- HRP只作为allocation challenger，与equal、IVP、shrinkage min-var、risk parity和当前受约束组合在同一PIT universe、forecast、协方差、rebalance、约束与成本下比较。
- 不求逆或能在奇异协方差上出权重不等于稳健；必须报告eigenspectrum/condition、tree/cluster稳定性、weight L1/turnover、risk contribution和stress loss。
- distance、linkage、window、shrinkage和recursive split都是研究选择并进入trial ledger；聚类树不得直接解释为稳定行业、因子或因果层级。
- 原始HRP的long-only/full-investment及缺失return、cash、short、margin、capacity和cost约束必须由Portfolio/Risk显式覆盖，并保存binding flags与不可行状态。
- 趋势组合不能把逐仓ATR或名义市场数量当portfolio risk/breadth；必须重算current exposure、vol drift、方向不对称、动态相关、共同主题、gap和margin stress。
- 增加市场或系统只有在lineage、压力相关、流动性和容量证明风险来源独立时才增加有效分散；历史弱市场不能仅因单独收益低而删除，同质系统数量不能冒充breadth。
- initial stop、ATR trailing、pyramiding、sector/open-risk cap 分属信号、风险与执行合同；stop不保证fill，任何参数和作者风险比例不得直接迁移。
- 多周期趋势只生成多个相关forecast候选；同一标的、同一价格源和高度重叠窗口先做相关/lineage去重，再计算effective breadth和总风险。

## 六、市场微观结构与执行规则

来源：`EXE-01`、`EXE-02`、`STR-03`、`STR-04`。

- 订单、成交、仓位和现金是不同对象；任何仓位变化必须来自 fill。
- journal、人工复盘和交易计划只补充审计语义；必须关联run、signal、risk decision、order/fill、position/cash、override和incident，且不得替代ledger PnL。
- 成本至少拆为 fee、spread、slippage、impact、delay、funding/borrow 和未成交机会成本。
- 限价触及不等于成交；必须说明队列、部分成交、撤单和 time-in-force 假设。
- 市价单提高成交确定性，承担价格不确定性；限价单相反。
- 小周期策略必须检查 LOB 深度、延迟、队列位置和 adverse selection。
- 缺 tick/L2 和时间对齐证据时，不得把 OHLCV 回测描述为高频或做市验证。
- 做市模型必须管理库存风险、报价偏移、毒性订单流和停机条件。
- 最优执行模型优化的是既定目标仓位的交易路径，不会创造 alpha。
- execution模型必须分开记录mid/reference price、fill price、inventory、cash与trading speed；temporary/permanent impact、terminal residual和risk penalty不可混成单一slippage。
- 恒速/TWAP只是在硬终端完成、线性暂时冲击且无风险等强条件下的解析特例；任何最优路径都必须受真实capacity、partial fill、latency、fee和abort/no-trade约束。
- price barrier只改变研究模型的状态/边界，不能把“触价”解释为剩余量可即时按该价成交；必须压力测试gap、overshoot、latency、depth和terminal residual。
- order-flow执行修正必须有非负库存、禁止未授权反向/空头和期限收敛约束；无约束PIDE产生的负速度或目标完成后继续交易必须拒绝。
- dark/conditional venue只有在当前规则、priority、reference price、minimum size、private fill、leakage/toxicity与fallback均有证据时才可建模；否则只做synthetic no-fill/partial-fill stress。
- LO触价、显示深度或distance-to-mid都不等于fill probability；必须用order identity、ahead volume、queue events、partial fill、cancel/reprice和多时钟证据，无法识别时标记blocked。
- LO/MO切换属于OMS执行选择而非Strategy alpha；任何理论QVI/impulse时点都必须经过price protection、capacity、latency、剩余量、reconcile和kill约束。
- target-tracking执行器只评价对既定parent schedule的偏离与成本，不能用“跟踪成功”证明目标仓位、TWAP/AC路径或promotion正确。
- POV、累计成交量占比和VWAP是不同执行目标/benchmark；必须明确market-volume范围、self-volume、trade condition、venue、时钟和late corrections，不得互相代称。
- volume-target策略必须有分母floor、participation/capacity cap、PIT volume forecast、zero/burst/outage处理和fallback；接近VWAP或高跟踪相关性不等于低implementation shortfall。
- BTC 24/7 volume curve必须按venue、weekday、session proxy和regime滚动估计；书中单日/美股曲线及固定POV参数不得迁移。
- 订单不平衡必须版本化depth范围、displayed/hidden口径、venue集合、quantity单位、snapshot/event clock、采样窗口、bin和zero-denominator；不同定义的结果不得直接拼接或比较。
- 不平衡的自相关、MO条件到达或后续markout只能是短周期候选证据，必须与spread bounce、public news、撤单反应、cross-venue move、self-impact和时钟偏差等替代解释做rolling OOS对照。
- 不平衡驱动的LO深度必须受非负/tick/lot、queue/fill、partial fill、cancel latency、deadline、price protection和reconcile约束；无MBO/private fill时只做diagnostic，解析负深度不得被解释为MO权限。
- 随机控制模型必须先声明state、control、admissibility、objective、dynamics、generator、terminal/boundary、verification和numerical scheme；DPP/HJB/QVI或解析候选不等于参数可识别、策略可执行或promotion evidence。
- public REST/WS 延迟不能替代真实 order latency、queue position 或 private fill reconcile。
- tick rule、Roll、Parkinson、Corwin–Schultz、Kyle、Amihud、Hasbrouck、PIN和VPIN都是特定数据与假设下的proxy；必须绑定venue/rule、trade/quote层级、clock、units、classification、window、SE和output lag。
- OHLC-only spread/impact估计不能证明真实quoted/effective spread、depth、queue或可成交成本；应与trade+quote、fill、markout和implementation shortfall对照，缺证据时保持diagnostic/blocked。
- aggressor、cancel、round size、TWAP phase、order-flow persistence与cross-entropy loss只能生成研究线索；不得直接定性informed trader、toxicity、front-running、spoofing、collusion或manipulation。
- PIN/VPIN必须报告mixture identifiability、classification error、bucket/window、volume units与不确定性；单阈值、Flash Crash叙事或文献分歧不得解锁执行或gate。
- 每个订单必须显式携带 instrument、side、quantity、price、activation、validity、display、settlement 与 routing 语义；capability 未声明支持即 fail-closed。
- matching、precedence、partial fill、auction、reference price、session 与 market-data entitlement 必须绑定 venue/rule version；触价、显示深度和理论优先级都不等于成交。
- broker、internalization、PFOF/rebate、preferencing 与 venue routing 都有 principal-agent 冲突；best execution 必须联合价格、速度、成交概率、规模、费用、markout 与未成交反事实评价。
- 流动性是 `size × cost × time` 的条件能力，至少拆分 width、depth、immediacy、resiliency 与 displayed/latent liquidity；volume、窄 spread 或单次 fill 不能证明容量。
- quoted spread 不是 dealer 利润；做市与限价流动性必须由双边 fills、inventory/cash ledger、hedge、fees 和 post-trade markout 重建。
- 双边做市必须显式限制inventory、cash、notional、capital和hedge capacity，并把quote age、stale-cancel、queue/latency、partial fill与单边连续成交纳入kill/degraded条件；无private fill与order-state证据时保持rejected。
- MO后markout与短期alpha只能是条件化诊断，必须比较public news、共同因子、自身impact、venue lead-lag和时钟偏差等替代解释；不得直接标记toxic或知情交易者。
- 自动做市订单状态必须先reconcile再retry，并防止unknown-order、duplicate、self-trade与overfill；理论最优报价、触发侧和数量不得绕过Portfolio/Risk、OMS/Execution、Fill/Ledger和审计链。
- 大额订单以相对 ADV/depth/time 的容量定义，不用固定股数；parent aggregation、order exposure、latent-demand search、concession 与 reporting delay 必须可审计。
- relative-value/arbitrage 只有在 fair-value 模型、收敛机制、多腿执行、borrow/funding/margin、全成本与资本生存均可证明时才成立；相关性和 gross basis 不够。
- 配对/统计套利不是无风险套利；pair、cointegration weight和entry/exit必须在PIT universe内按formation/trading窗口冻结，并接受结构断裂、伪配对、multiple testing和survivorship反证。
- 多腿策略必须由Portfolio/Risk约束gross/net/leverage、factor、concentration、shortability、borrow/funding和leg-risk；OMS记录partial/no fill、超时、re-hedge、abort/unwind，Fill/Ledger按basket重建成本后PnL。
- 理论OU阈值或效用最优组合不含真实borrow、容量、离散成交和跳跃时只能作为research challenger；两腿按mid同时成交、无限short或零终端头寸均不得作为默认执行假设。
- market quality 是 liquidity、cost、informativeness、volatility、access、reliability 与不同参与者福利的多目标权衡，单一 spread、volume 或 speed 指标不得解锁 venue/promotion 判断。
- abnormal price/volume、关系网络、盈利、反转或拆单模式只能产生调查线索；manipulation、front-running 或 insider-trading 定性必须保留 alternative hypotheses 并交由当前规则和授权责任人。
- 自动化 venue/OMS 必须有 rule/code hash、有限状态机、时钟、容量、冗余、RTO/RPO、unknown-order reconcile-before-retry、duplicate/overfill 防护、kill/degraded mode 和 deterministic replay。
- crisis 状态需联合 halt/limit/reopen、quote age、backlog、cross-venue basis、margin/liquidation、capacity 与 recovery 评估；价格暴跌、反弹或 circuit breaker 本身不证明 bubble、风险消失或机制有效。
- 信息型研究只允许合法授权、PIT、可追溯且已广泛公开的数据；疑似重大非公开信息、选择性披露、misappropriation、提前可见或权限不明时必须隔离并升级合规审查。

## 七、数据与工程可靠性规则

来源：`ENG-01` 至 `ENG-05`、`RES-01`。

### 1. 模块设计

- 优先深模块：接口简单，内部吸收复杂性。
- 通过信息隐藏隔离数据源、存储、broker、交易所和报告格式变化。
- Domain 不依赖数据库、文件路径、HTTP、环境变量或 SDK。
- Service Layer 编排用例；Repository 隔离存储；Unit of Work 管理原子写入。
- 事件只承载已经发生的事实，命令表达希望发生的动作，两者错误语义不同。

### 2. 数据持久化

- 原始市场数据和审计账本优先 append-only；修正通过新版本表达。
- WAL、checkpoint、快照和 replay 是恢复链的一部分，不能只依赖最终表。
- B-Tree、LSM 或列式存储是访问模式权衡，不应因书中性能描述盲目迁移。
- schema 演化必须有兼容策略、迁移边界和旧 reader 测试。
- 复制、分区或缓存不能改变 PIT 可见性和数据版本语义。
- storage engine、index和column layout只按当前workload、durability、recovery与p95/p99 benchmark选择；append-only raw、compacted serving和materialized read model必须分层。
- relational、document或graph按aggregate、cardinality与query pattern选择；schema-less只是schema-on-read，展示/denormalized数据始终保留authority、freshness和rebuild lineage。
- schema evolution同时验证old-reader/new-writer与new-reader/old-writer；字段tag、单位、时钟、枚举和default不得静默改义，archive必须可定位writer schema。
- remote timeout表示结果未知而非未执行；command必须有idempotency/dedupe/deadline，并在重试前读取权威状态对账。
- replication必须声明ack durability、lag、read guarantee、failover和conflict policy；副本、cache、worktree与`latest`均不能替代commit/manifest权威证据。
- partitioning必须保存stable key/hash、owner epoch、skew、secondary-index freshness、rebalance和routing；任何分片遗漏、重复或陈旧epoch使全run失败。
- transaction从应用不变量反推UoW和isolation；read committed或snapshot isolation仍需lost-update、write-skew、phantom和retry-side-effect并发fixture。
- distributed safety优先于availability：timeout只表示unknown，wall clock不证明因果，lease必须由接收端fencing；错误结果不得为追求liveness返回。
- 长期数据搜集、清洗和成交偏差跟踪本身是研究资产；理论价与实际成交价必须分别保存，规模扩大后的capacity/impact不能由小资金结果外推。
- 统一研究平台应统一schema、lineage、trial、cost与组合约束接口，而不是把Strategy、Portfolio/Risk、OMS和Ledger合并成不可隔离的单一黑箱。

### 3. 金融数据结构与采样

- 财务、宏观和分析数据必须分别保存period/effective、first release、revision、vendor available和本项目receive time；最终修订值不得回填首发或报告期末。
- 社交媒体/新闻文本还必须保存原始发布、抓取、删除/修订、去重、语言和实体映射时钟；tweet sentiment或公告日策略不得使用事后清洗语料与同刻不可得标签。
- bar是有状态sampling operator，不是原始事实；每个bar保存input event hash/range、clock、threshold、warm-up、residual、availability、session、algorithm version和replay checksum。
- time、tick、volume、dollar、imbalance和run bar会改变样本时钟、持续时间与分布；必须在同一PIT事件集比较，不得因名称含information就解释为知情交易或更优alpha。
- tick rule、EWMA和CUSUM必须prefix-only并有warm-up/reset/unchanged-price/out-of-order/correction fixture；sample trigger只选训练事件，不等于标签、方向或订单。
- 合成篮子与连续合约必须分开raw、rolled、total-return和synthetic series；权重、FX、carry、roll、cost、capacity与每腿可交易时钟可追溯，资本和执行仍使用真实各腿价格与ledger。

### 4. 并行与向量化

- 并行前先有single-thread oracle与partition manifest；atoms必须stable-ID、无遗漏、无重复，跨分区lookback/label span/bar state使用显式halo和owner区间。
- worker只消费冻结输入并输出唯一分片；异常、timeout、partial、duplicate或schema mismatch使全run fail-closed，同一文件、SQLite、ledger和`latest`始终单writer原子发布。
- asynchronous/unordered结果必须按stable key确定性归并；reducer需声明identity、associativity、commutativity和浮点策略，order-sensitive in-place更新不得生成证据。
- seed按run/partition/atom派生并保存；process、thread、BLAS、spawn/fork、serialization和library版本进入环境证据，chunk/batch变化不得改变结果。
- 性能只认当前机器的serial/parallel wall time、CPU、peak RSS、I/O、serialization与reduce分解；CPU数不等于线性speedup，并行搜索仍完整计入trial ledger。

### 5. HPC 与流式工作流

- HPC、cloud、MPI、HDF5、ADIOS或GPU只是执行候选；先profile算法、data layout、I/O、communication、compute、reduction与publish critical path，并建立single-node correctness oracle和SLO。
- benchmark固定input/output/cache/concurrency，报告cold/warm wall time、p50/p95/p99、throughput、CPU、I/O、network、serialization、peak RSS、failure recovery和总成本；历史speedup与价格比例不可迁移。
- HDF/chunk/index/compression必须保留schema、PIT、lineage、checksum、correction、跨版本读取与single-writer语义；in-situ过滤不得删除raw audit、fill、order或promotion所需事实。
- 更快计算只提高trial吞吐，不验证VPIN、FFT、alert或因果；新增参数/硬件/数据布局尝试进入trial ledger，early warning仍需base rate、delay、false positive/negative、action loss与Risk审批。
- 分布式方案只有在算法/单机优化仍无法满足当前SLO且failure/replay/cost证据齐全时才进入架构评审；当前不因书中案例采购或迁移基础设施。
- eventual、linearizable、serializable、causal和quorum是不同保证；唯一性、leader/lease、latest单写者与跨分区提交必须声明冲突域、epoch/quorum、fencing、unknown/in-doubt和恢复，不以CAP口号替代故障证据。
- 批处理只消费冻结、版本化输入并输出完整派生dataset；partition/join/skew/attempt、确定性归并、partial cleanup、checksum与原子pointer publish进入`BatchRunEvidence`，失败任务不得直接任意修改在线真值。
- 流处理必须版本化event ID、partition/sequence、event/receive/process time、offset/retention、watermark/window、PIT join、checkpoint、dedupe与external-effect reconciliation；引擎内部“exactly once”不得外推到订单或账本副作用。
- 数据集成先指定system of record，再由可重放log/CDC和确定性幂等derivation生成view；operation ID贯穿端到端，timeliness与integrity分开监控，raw到artifact/read model/ledger持续hash、restore、replay和对账。
- storage选型先冻结point/range/scan、row/column、update/delete、durability、recovery、retention和SLO；B-Tree/LSM或产品标签不得替代当前query plan与benchmark。
- 长期文件与artifact必须版本化encoding/schema/header/length/checksum，并用完整新run写入、校验、atomic pointer swap和old/new reader fixture发布。
- WAL、dirty state、checkpoint、log truncation、backup/restore是同一恢复合同；append-only、immutable、copy-on-write和LSM均不免除GC、compaction、reclamation与crash测试。
- failure detector只产生suspect，leader election只改善coordination/liveness；timeout、heartbeat、rank或文件锁不能证明节点死亡或single-leader safety，必须有term/epoch/fencing和权威状态查询。
- quorum、anti-entropy、2PC、Paxos/Raft/PBFT只在其fault model、durability、membership和message assumptions已验证时适用；当前本地系统不得借概念类比自称实现分布式一致性。

### 6. 遗留代码修改

- 修改无测试代码前先区分目标变化与必须保持的不变量；characterization test只记录当前可观察行为，不自动证明该行为正确。
- 快速纯规则测试、合同测试和真实边界集成测试分层运行；数据库、网络、文件系统或特殊环境测试不得冒充快速单测，历史秒数不得直接设SLA。
- 用显式参数、Protocol、fake或窄adapter建立sensing/separation seam；fake只证明调用方边界，真实资源仍需独立集成证据。
- effect sketch从变更点追踪返回值、对象变异、全局状态与外部副作用；pinch point可作为覆盖起点，但不得长期替代细粒度测试。
- Sprout、Wrap、临时subclass或静态脚手架只用于先把新行为置于测试；票据必须记录owner、临时责任和合并/删除条件。
- 一次只建立一个安全边界；巨型service按policy、repository、renderer、publisher等变化原因小步抽取，不在同一步同时改行为和结构。
- 核心 bug 必须先有能复现旧错误的失败测试；characterization中发现疑似bug要标记并调查依赖者，不能静默固化。
- 若无法隔离副作用，先报告设计blocker；不以全模块重写、工具自动改写成功、编译通过或第二审查替代行为证据。
- 复杂性审计优先识别change amplification、cognitive load、unknown unknowns、dependency和obscurity；类数、函数长度或代码行数不能单独证明设计优劣。
- 模块只有在用窄接口隐藏显著内部复杂性时才有价值；pass-through wrapper、重复异常处理、配置转嫁和context grab-bag应重新分配信息所有权。
- schema、clock、authority、HEAD/freshness、路径和安全状态必须各有唯一权威实现；相邻层提供不同抽象，通用机制与市场专用policy分离。
- 能由类型、空对象、原子操作消除的非法状态优先消除；重要network loss、unknown order、corrupt evidence不得mask，继续fail-closed并进入对账。
- 性能优化先固定workload、profile和baseline，再围绕critical path简化；历史倍数和纳秒数字不可迁移，无显著收益的复杂化必须撤销。
- 静态reference data、数量级错误和小规模有效/放大失效必须由schema/unit guard、dynamic fixture、golden/prefix tests及scale replay覆盖；明星作者代码同样需要逐行review。
- 开放协作必须配合least privilege、owner、review、access audit、offboarding、succession和关键岗位runbook；共享代码不能等同于无边界访问。

## 八、BTC 与美股专用解释

### BTC / Crypto

- 趋势书提供 signal、forecast、vol targeting 和组合思想，不提供当前永续可执行证明。
- Forecast必须保存方向、尺度、horizon、expiry、confidence、calibration、raw/combined值、weights、correlation、multiplier和cap loss；固定10/20/2.5或书中rule weights不得作为BTC默认参数。
- 永续TargetPosition必须从account currency、capital、risk budget、mark/index语义、contract multiplier、FX、vol forecast、funding、margin、min lot和liquidation stress推导，并同时保存连续目标与round后目标。
- 永续必须额外验证 funding、mark/index、maintenance margin、liquidation、深度、outage 和 exchange rules。
- 单 BTC 回测不能声称获得跨市场分散；多周期高度相关信号不能重复计算 breadth。
- 任何书中高杠杆、分批建仓或滚仓示例都必须经过当前 risk budget、成本和强平证据。
- 趋势event replay至少覆盖gap、flash move、funding/basis反转、venue outage、stale price、流动性坍塌、相关跃升和launch后立即回撤；事后事件叙事不得进入信号。

### US Equity

- ETF/股票universe必须保存PIT eligibility、成分与复权、borrow、corporate action、lot、spread/impact、税费scope和rebalance calendar；书中ETF、相关矩阵和无杠杆风险示例不迁移。
- 配置观点只能形成带vintage、horizon、uncertainty、benchmark和tracking-error预算的小幅TargetPosition偏离；价格目标或宏观叙事不得直接改权重。
- 动量和因子方法必须使用 point-in-time universe、公司行动、复权、退市和发布日语义。
- 12-1 动量、路径质量和行业/市值中性属于候选设计，不是固定通过参数。
- ETF 轮动必须预声明 required universe、交易日历、再平衡日和 T+1 执行。
- A 股因子结论不能直接迁移到美股；市场制度和样本必须重新验证。
- 指数、行业ETF或多股票趋势持仓必须聚合共同equity beta、美元/利率主题和压力相关；证券数量不等于独立分散。

## 九、已完成 L2 的可追溯规则

本节只收录已完成整本 `L2` 的书籍结论。`L2_confirmed` 表示已核对章节论证与限制，不表示公式完成 `L3`、代码已实现、策略有效或 gate 通过。

| Agent 规则 | 项目动作 | 反向来源 | 状态 |
|---|---|---|---|
| 领域对象必须区分稳定身份、值语义、命令意图和已发生事实。 | 共享 ADR 明确定义 `Signal`、`Forecast`、`TargetPosition`、`OrderIntent`、`RiskDecision`、`Order`、`Fill` 和 ledger record。 | [ENG-02 Ch01](cards/ENG-02_architecture_patterns_with_python.md#1-domain-modeling)、[ENG-02 Ch10](cards/ENG-02_architecture_patterns_with_python.md#10-commands-and-command-handlers) | `L2_confirmed` |
| 纯决策核心不得直接读取数据库、文件、Git、时钟、broker 或 exchange。 | 将外部状态压成显式 snapshot/port，核心只输出领域决定，I/O 留在 adapter/shell。 | [ENG-02 Ch02–04](cards/ENG-02_architecture_patterns_with_python.md#2-repository-pattern) | `L2_confirmed` |
| 持久化写入显式 commit、默认 rollback；跨介质不能伪装为原子事务。 | Fill/Position/Cash 在同一 UoW；artifact 使用 immutable write、校验和 pointer swap/补偿合同。 | [ENG-02 Ch06](cards/ENG-02_architecture_patterns_with_python.md#6-unit-of-work) | `L2_confirmed` |
| 一致性边界从不变量反推，不能从表名或服务名反推。 | 对 order/fill/position/cash、account/run 和 `latest` 单写者分别定义 aggregate、锁与并发测试。 | [ENG-02 Ch07](cards/ENG-02_architecture_patterns_with_python.md#7-aggregates-and-consistency-boundaries) | `L2_confirmed` |
| 事件只描述成功提交或权威确认后的事实；message bus 不天然可靠、异步或并发。 | 事件携带 schema/version/causality；跨 UoW 前先定义 outbox、幂等、重放、补偿和失败终态。 | [ENG-02 Ch08–11](cards/ENG-02_architecture_patterns_with_python.md#8-domain-events-and-message-bus) | `L2_confirmed` |
| read model 可陈旧但必须可重建，且不得解锁 promotion。 | Dashboard 显示 source run、HEAD、as-of、freshness 和权威 evidence；写命令重新校验真值。 | [ENG-02 Ch12](cards/ENG-02_architecture_patterns_with_python.md#12-cqrs) | `L2_confirmed` |
| composition root 默认装配最低权限能力。 | 默认 BrokerAdapter 无下单能力；private/order/paper/live 依赖只在明确授权与独立 gate 后注入。 | [ENG-02 Ch13](cards/ENG-02_architecture_patterns_with_python.md#13-dependency-injection-and-bootstrapping) | `L2_confirmed` |
| 复杂性由高频修改路径中的放大、认知负担、未知依赖、dependency与obscurity判断，不按文件大小机械拆分。 | `DesignComplexityEvidence`记录change set、knowledge owner、interfaces/config/errors、reader review、alternatives和rejected design。 | [ENG-01 Ch01–05](cards/ENG-01_a_philosophy_of_software_design.md#l2-逐章项目结论) | `L2_confirmed`；复杂度加权关系已核为`verified_concept_only` |
| 每层必须提供不同且更高价值的抽象，复杂性应由最能封装它的模块承担。 | 清理pass-through wrapper/variable，统一schema、clock、authority、HEAD/freshness与publish语义；context保持小且immutable。 | [ENG-01 Ch06–09](cards/ENG-01_a_philosophy_of_software_design.md#l2-逐章项目结论) | `L2_confirmed` |
| 错误消除不能变成吞错；调用方不需要的内部细节可mask，影响完整性与交易结果的状态必须暴露。 | decision/result类型显式区分success、blocked、unknown、corrupt和failed；unknown order先reconcile，evidence异常fail-closed。 | [ENG-01 Ch10](cards/ENG-01_a_philosophy_of_software_design.md#l2-逐章项目结论) | `L2_confirmed` |
| 接口、文档和命名先表达抽象、unit/clock、前后置、side effect与异常；难以简短描述或命名即触发重新设计。 | 新gate/resolver/ledger先写合同和两种ADR方案，注释靠近唯一事实源，cross-module rule进入可发现design note。 | [ENG-01 Ch11–18](cards/ENG-01_a_philosophy_of_software_design.md#l2-逐章项目结论) | `L2_confirmed` |
| 架构潮流和性能优化只在降低当前已测复杂性或关键路径成本时采用。 | bug先失败测试；抽象按整体设计；优化绑定profile/baseline/correctness/rollback，微服务、pattern或inheritance不自动获批。 | [ENG-01 Ch19–21](cards/ENG-01_a_philosophy_of_software_design.md#l2-逐章项目结论) | `L2_confirmed`；RAMCloud历史数字已核为`verified_concept_only` |
| 系统保证必须按操作声明，不能用ACID、CAP、quorum或exactly-once标签代替语义。 | `ConsistencyCoordinationEvidence`保存read/write guarantee、conflict scope、partition model、epoch/quorum、fencing、in-doubt、恢复与并发故障fixture。 | [ENG-03 Ch05–09](cards/ENG-03_designing_data_intensive_applications.md#第-9-章一致性保证因果顺序与共识成本) | `L3_verified_concept_only`；120项已核，当前实现另证 |
| 批处理必须可由不可变输入确定性重建完整输出，失败或partial不得发布。 | `BatchRunEvidence`保存input/code/params/env、partition/attempt、join/skew、determinism、output checksum和atomic pointer publish。 | [ENG-03 Ch10](cards/ENG-03_designing_data_intensive_applications.md#第-10-章不可变批输入确定性数据流与完整发布) | `L3_verified_concept_only`；运行正确性另证 |
| 流处理的输入、状态、输出和外部副作用必须分别证明重放与去重语义。 | `StreamReplayEvidence`保存snapshot/log offset、event clocks、duplicate/reorder/late、window/PIT join、checkpoint、replay checksum和external reconcile。 | [ENG-03 Ch11](cards/ENG-03_designing_data_intensive_applications.md#第-11-章可重放事件流事件时间与外部副作用) | `L3_verified_concept_only`；产品能力待当前验证 |
| read model、cache和dashboard都是可重建派生状态，完整性必须端到端持续审计。 | `EndToEndIntegrityEvidence`连接system-of-record、dataflow DAG、operation IDs、constraints、timeliness/integrity、hash、restore、replay、ledger reconciliation和current HEAD。 | [ENG-03 Ch12](cards/ENG-03_designing_data_intensive_applications.md#第-12-章派生数据端到端完整性与持续审计) | `L3_verified_concept_only`；不是promotion evidence |
| 存储和索引必须按当前访问模式、放大成本与恢复目标选择，理论复杂度不能代替实测。 | `StorageEngineEvidence`固定query/write set、layout/index、page/cache、cold/warm p95/p99、read/write/space amplification、recovery和cost。 | [ENG-04 Ch01–07](cards/ENG-04_database_internals.md#l2-逐章项目结论) | `L3_verified_concept_only`；70项已核，仍需当前benchmark |
| artifact文件格式是长期reader contract，必须能检测损坏、演化和partial publish。 | 保存encoding、schema/version、units、producer HEAD、row/length、checksum、compatibility matrix、corruption fixture和atomic pointer。 | [ENG-04 Ch03–06](cards/ENG-04_database_internals.md#l2-逐章项目结论) | `L3_verified_concept_only`；不证明当前reader兼容 |
| commit与恢复必须联合验证WAL、dirty state、checkpoint、log truncation、backup与restore。 | `StorageRecoveryEvidence`记录journal/fsync、commit ack、checkpoint、crash point、replay、restore checksum、RTO/RPO和current version。 | [ENG-04 Ch05](cards/ENG-04_database_internals.md#l2-逐章项目结论) | `L2_confirmed`；当前SQLite行为待实测 |
| heartbeat和timeout只能产生怀疑；leader、replica或远程操作状态必须由权威协议确认。 | `RemoteStateEvidence`保存request ID、observer、clock、latency distribution、suspect level、term/epoch、fencing、unknown result和reconciliation。 | [ENG-04 Ch08–10](cards/ENG-04_database_internals.md#l2-逐章项目结论) | `L2_confirmed`；交易端点继续禁用 |
| 复制、anti-entropy、distributed commit与consensus不得脱离具体fault model和quorum假设。 | 对每类数据声明consistency/session guarantee、N/R/W、membership、durability、repair、blocking/in-doubt和partition fixture；无需求不引入协议。 | [ENG-04 Ch11–14](cards/ENG-04_database_internals.md#l2-逐章项目结论) | `L2_confirmed`；仅概念，不是迁移批准 |
| 遗留代码修改必须先声明目标行为、保持不变量和可观察反馈；characterization只记录事实，不授予正确性。 | `LegacyChangeEvidence`保存change points、effect sketch、invariants、characterization、targeted path/conversion tests、疑似bug和reviewer。 | [ENG-05 Ch01–13](cards/ENG-05_working_effectively_with_legacy_code.md#l2-逐章项目结论) | `L2_confirmed`；3项历史估算已核为`verified_concept_only` |
| seam和临时重构结构必须显式、最小且可退场，fake或wrapper不能替代真实边界证据。 | 每个seam记录sensing/separation目的、enabling point、production/test实现、integration test、owner和remove/merge condition。 | [ENG-05 Ch03–10](cards/ENG-05_working_effectively_with_legacy_code.md#l2-逐章项目结论) | `L2_confirmed`；语言技巧需Python复核 |
| 巨型类、monster method和重复逻辑按变化原因渐进拆分，不因代码长度、文本相似或OO模式直接合并。 | `RefactorEvidence`保存责任图、权威状态、单目标步骤、保持签名、每步测试、共享语义证明和未退场脚手架。 | [ENG-05 Ch19–25](cards/ENG-05_working_effectively_with_legacy_code.md#l2-逐章项目结论) | `L2_confirmed`；不构成重构批准 |
| 规则、forecast、risk target、position和portfolio必须是单位明确的独立合同，Strategy不得直接输出可发送订单。 | `ForecastEvidence`与`TargetPositionEvidence`保存source/horizon/expiry/scale、raw/combined、weights/correlation、capital/risk、block/FX/vol、continuous/rounded target和约束损失。 | [STR-01 Ch05–11](cards/STR-01_systematic_trading.md#l2-逐章项目结论) | `L3_verified_concept_only`；75项已核，固定参数禁用 |
| 可交易性必须联合成本、turnover、capacity、min lot和压力流动性评估，不能只看回测Sharpe或commission。 | `TradabilityEvidence`保存fee/spread/slippage/impact/delay/funding/borrow/roll、target/fill turnover、depth/participation、rounding和no-trade理由。 | [STR-01 Ch06](cards/STR-01_systematic_trading.md#l2-逐章项目结论)、[STR-01 Ch12](cards/STR-01_systematic_trading.md#l2-逐章项目结论) | `L3_verified_concept_only`；历史阈值禁用 |
| 人工、静态配置和自动策略共享Portfolio/Risk、OMS、Fill/Ledger与审计合同，只允许forecast来源和运行频率不同。 | 每种模式声明forecast source、rebalance clock、operator capability、override、target、orders、fills、cash/position reconcile和fail-closed状态。 | [STR-01 Ch13–15](cards/STR-01_systematic_trading.md#l2-逐章项目结论) | `L3_verified_concept_only`；不授权交易端点 |
| 趋势策略的主要研究自由度是universe、sizing、horizon、risk和组合，不应靠复杂入场或历史最优参数掩盖缺失的组合证据。 | 简单MA/breakout作为基线；候选登记signal/fill lag、成本、参数邻域、trial budget、方向/行业归因和失败条件。 | [STR-02 Ch01–05](cards/STR-02_following_the_trend.md#l2-逐章项目结论) | `L3_verified_concept_only`；25项已核，参数禁用 |
| 多仓位、多市场和多周期不自动构成分散，压力期可能收敛为同一宏观主题。 | `TrendPortfolioRiskEvidence`保存current exposure、entry/current vol、cluster/factor、stress correlation、gap/margin、position-count collapse和top contribution。 | [STR-02 Ch06–08](cards/STR-02_following_the_trend.md#l2-逐章项目结论) | `L3_verified_concept_only`；15项已核，不证明当前分散 |
| 期货研究价、可成交合约、roll、逐日现金和目标仓位必须分离；启动、执行和监控偏差均需对账。 | futures contract保存chain/roll/actual/adjusted/multiplier/FX/margin；startup与daily diff只作只读证据，交易能力继续隔离。 | [STR-02 Ch02](cards/STR-02_following_the_trend.md#l2-逐章项目结论)、[STR-02 Ch09–10](cards/STR-02_following_the_trend.md#l2-逐章项目结论) | `L3_verified_concept_only`；不授权broker/private/order/paper/live |
| Forecast来源必须显式分离并登记谱系；back-adjusted、synthetic spot、normalised、asset-class、breakout和acceleration的名义规则数不等于独立breadth。 | `ForecastLineageEvidence`保存price source、parent rule、normalisation/scalar、correlation、effective breadth、净成本和边际OOS贡献；高相关challenger不得重复计风险预算。 | [STR-03 S07–S24](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论) | `L2_confirmed`；章节及Appendix B计算族已核 |
| regime与cross-sectional forecast必须使用当时可得状态和PIT universe；低相关不能替代正向独立edge。 | 保存state estimator/as-of/lag、membership、同步单位、dispersion、zero/warm-up处理、residual beta、trial权重和危机被放弃收益；holdout不参与阈值或权重选择。 | [STR-03 S13](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论)、[STR-03 S18–S22](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论) | `L2_confirmed`；阈值和权重禁用 |
| 离散合约优化是TargetPosition到OrderIntent之间的可执行映射，不是Strategy，也不能以回测最优成本参数替代硬风险约束。 | `DiscretePortfolioEvidence`保存未取整目标、PIT covariance、integer grid、objective/cost/buffer、当前仓位、constraints、tie-break、tracking error、infeasibility和确定性replay。 | [STR-03 S25](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论) | `L2_confirmed`；作者参数待L3且禁用 |
| 小时级均值回归依赖quote/L2/queue/fill与独立执行语义，不能由日线回测或触价即成交假设支持。 | fast candidate保持`research_only`，独立保存session、latency、partial fill、cancel/replace、gap market order、capacity、negative tail和daily-strategy netting/attribution；缺证据fail-closed。 | [STR-03 S26–S27](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论) | `L2_confirmed`；当前不可promotion |
| 两腿、三腿和calendar相对价值的低表观波动来自hedge，可能通过高杠杆、相关断裂、异步roll和单腿成交转化为肥尾。 | `MultiLegEvidence`保存每腿expiry/ratio/units、gross/net、correlation shock、margin/cost、simultaneous roll/fill、partial exposure、timeout补救和ledger；三腿实施保持blocked。 | [STR-03 S28–S30](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论) | `L2_confirmed`；S29 rejected-for-now |
| contract selection、execution、cash和runtime risk是独立于Strategy的战术合同，任何异常都必须向下游传播为拒绝或降仓。 | 保存expiry eligibility/delivery/roll、arrival-to-fill、free cash/margin/FX loan/interest、portfolio/jump/correlation/leverage multiplier及position/trade limits；override全审计。 | [STR-03 T01–T04](cards/STR-03_advanced_futures_trading_strategies.md#l2-逐章项目结论) | `L2_confirmed`；不授权交易端点 |
| 连续期货、风险和分散倍数必须保留单位、时钟与估计谱系；back-adjusted price、turnover、FDM/IDM不能越权替代PnL、真实成本或风险预算。 | `FuturesCalculationEvidence`保存held contract/roll diff、price-vs-percent risk、annualisation、EWMA/blend、correlation/covariance、forecast/position turnover、FDM/IDM、PIT window、矩阵稳定和参数trial；16/256、32日、十年、0.7/0.3、cap2/2.5均禁硬编码。 | [STR-03 Appendix B](cards/STR-03_advanced_futures_trading_strategies.md#附录边界) | `L3_verified_concept_only`；不证明实现正确或ready |
| 趋势、动量、oscillator、季节、cycle、volume/breadth和adaptive指标首先是算子族，不是独立alpha；等距参数、同源变体和图形lead会扩大搜索或造成泄漏。 | `SignalOperatorEvidence`保存kernel/price field、unit/scale、warm-up/lag/drop-off、normalization/cap、native clock、lineage/similarity、trial family和component ablation；centered/lead计算禁止进入因果信号。 | [STR-04 Ch07–12](cards/STR-04_trading_systems_and_methods.md#章节卡)、[STR-04 Ch17–19](cards/STR-04_trading_systems_and_methods.md#章节卡) | `L2_confirmed`；原PDF章节结构已核，逐式/表/参数仍待L3 |
| 新闻、COT、日内、gap和多腿关系必须绑定真实availability、session、合约与执行时钟；玄学或主观图形不能因软件化而获得证据。 | 事件保存expected/actual/release/revision与fill lag，COT分开position/report date；日内保存session/bar/auction/quote/fill；spread保存leg/expiry/units/FX/carry/borrow/atomicity。Fibonacci/Elliott/Gann/占星保持拒绝。 | [STR-04 Ch13–16](cards/STR-04_trading_systems_and_methods.md#章节卡) | `L2_confirmed`；日内与三腿实施仍blocked |
| backtest用于验证预注册机制，不得用最终OOS/holdout继续选参数或全样本重估；峰值、单市场成功和危机顺风收益都不是稳健性。 | evidence contract强制PIT data、purged/embargoed WF、trial ledger、locked holdout access、multiple-testing、参数邻域/跨市场、人工复算、cost和price-shock attribution；任何holdout查看均不可逆。 | [STR-04 Ch01](cards/STR-04_trading_systems_and_methods.md#章节卡)、[STR-04 Ch21](cards/STR-04_trading_systems_and_methods.md#章节卡) | `L2_confirmed`；书中旧式final all-data refit不采用 |
| paper/自动化只能验证管线；bad/missing/late data、gap/halt、未成交、相关清算和信号拥挤必须通过现实回放，不能由历史净值代替。 | `RealismReplayEvidence`覆盖settlement/last、cancelled trades、stale signal、spread/latency/partial fill、unable、capacity、correlation collapse、crisis mode、kill/recovery和ledger reconcile；异常默认fail-closed。 | [STR-04 Ch22](cards/STR-04_trading_systems_and_methods.md#章节卡) | `L2_confirmed`；不授权paper/live |
| 标准差、VaR、drawdown、ruin和流动性描述不同风险；正常期相关与低净spread波动会在gap、legging和压力期失效，Kelly/optimal-f对估计误差过敏。 | Portfolio/Risk先应用gross/net、single/strategy/venue、liquidity、margin、drawdown、stress-correlation、capacity和service-loss caps；allocation比较equal/IVP/shrinkage/risk-parity并报告turnover、稳定、rounding和不可行。 | [STR-04 Ch23–24](cards/STR-04_trading_systems_and_methods.md#章节卡) | `L2_confirmed`；Kelly/optimal-f仅作降杠杆压力上界 |
| 书籍候选先按资源与机制筛选，再进入试验。 | Candidate registry 记录 capital/data/horizon/capacity/benchmark/cost/trial/holdout/failure，不因公开来源或作者业绩提高优先级。 | [STR-05 Ch01](cards/STR-05_quantitative_trading.md#第-1-章the-whats-whos-and-whys-of-quantitative-trading)、[STR-05 Ch02](cards/STR-05_quantitative_trading.md#第-2-章fishing-for-ideas) | `L2_confirmed`；Ch02 已核为`verified_concept_only` |
| test set 一旦用于比较变体就成为 validation，不再是 locked holdout。 | 所有阈值、universe、时点和模型族选择进入 trial ledger；采用 purged WF、multiple-testing 控制与独立 holdout access ledger。 | [STR-05 Ch03](cards/STR-05_quantitative_trading.md#第-3-章backtesting) | `L2_confirmed`；6项已核为`verified_concept_only` |
| 截断未来数据后，历史信号/仓位必须保持完全不变。 | 将 prefix-invariance 纳入 backtest 合同，并另测修订数据、未来 universe、全样本变换、标签重叠和 execute lag。 | [STR-05 Ch03](cards/STR-05_quantitative_trading.md#第-3-章backtesting) | `L2_confirmed`；原PDF概念已核，覆盖边界仍需项目合同测试 |
| broker/venue 选择看全部能力与故障边界，不只看 commission。 | 建 capability/permission、资金安全、reconciliation、RTO/RPO、支持时段、rate limit 和 failure semantics 清单。 | [STR-05 Ch04](cards/STR-05_quantitative_trading.md#第-4-章setting-up-your-business) | `L2_confirmed`；当前法规/机构信息另查权威来源 |
| Strategy 不得直接生成可发送订单，paper 不证明真实可执行性。 | 强制 `Strategy → Portfolio/Risk → OMS/Execution → Fill/Ledger`；对比 decision/arrival/submission/ack/fill/cancel，paper 结果保持 research-only。 | [STR-05 Ch05](cards/STR-05_quantitative_trading.md#第-5-章execution-systems) | `L2_confirmed`；5项已核为`verified_concept_only` |
| Kelly 只能作为理想化增长上界，风险硬约束优先。 | 先应用 gross/net、单资产/策略/venue、drawdown、liquidity、turnover、stress、margin 和 loss-of-service caps，再讨论任何优化权重。 | [STR-05 Ch06](cards/STR-05_quantitative_trading.md#第-6-章money-and-risk-management) | `L2_confirmed`；6项已核为`verified_concept_only`，production sizing禁用 |
| 协整、因子、PCA、OU、季节性、regime 和 HFT 必须拆成独立假说。 | 每类单独预登记 mechanism、clock、PIT、cost、capacity、WF、holdout 和失效监控；禁止批量试完再择优。 | [STR-05 Ch07](cards/STR-05_quantitative_trading.md#第-7-章special-topics-in-quantitative-trading) | `L2_confirmed`；9项已核为`verified_concept_only`，HFT仍blocked |
| 容量和治理决定扩容，独立/机构身份不产生 alpha。 | Scale-up 记录 participation、crowding、factor exposure、压力相关、owner/approver/executor/reconciler；扩容重新过 gate。 | [STR-05 Ch08](cards/STR-05_quantitative_trading.md#第-8-章conclusion--can-independent-traders-succeed) | `L2_confirmed` |
| 预测变量、定价因子、异象、因子暴露和模型 residual 是不同语义。 | Forecast、risk exposure、benchmark/factor PnL 与 residual 分账；任何 residual 都标注 benchmark model/version，不直接命名为 alpha。 | [STR-11 Ch01](cards/STR-11_factor_investing_methods_and_practice.md#第-1-章因子投资基础) | `L2_confirmed`；2项已核为`verified_concept_only` |
| 因子研究必须先冻结 PIT、lag、breakpoint、weight、exposure、SE、test assets 与 trial set。 | 标准研究规格同时记录构造、推断、multiple testing、成本、borrow、容量和模型敏感性；结果后改设定增加 trial。 | [STR-11 Ch02](cards/STR-11_factor_investing_methods_and_practice.md#第-2-章因子投资方法论)、[STR-11 Ch03](cards/STR-11_factor_investing_methods_and_practice.md#第-3-章主流因子解读) | `L2_confirmed`；10项已核为`verified_concept_only` |
| 模型解释力和 residual 都是 benchmark-relative，不是机制真值。 | 用多个预声明模型做 sensitivity，固定 test assets/sample/cost，报告模型间范围、复杂度和增量 OOS 信息。 | [STR-11 Ch04](cards/STR-11_factor_investing_methods_and_practice.md#第-4-章多因子模型) | `L2_confirmed`；3项已核为`verified_concept_only` |
| 复合分数的每个组件、阈值、替代变量和组合方式都属于搜索自由度。 | Composite challenger 必须做 ablation、简单基线、独立 OOS、outlier/model sensitivity、borrow、turnover、cost 和 capacity。 | [STR-11 Ch05](cards/STR-11_factor_investing_methods_and_practice.md#第-5-章异象研究) | `L2_confirmed`；3项已核为`verified_concept_only` |
| p-value 不是原假设为假的概率，固定 t/IC 阈值不得解锁 gate。 | 保存完整 trial universe，预声明 FDR/DSR/PBO 等修正和 locked holdout；文献 `t=3/3.4/3.8` 只作历史结果。 | [STR-11 Ch06](cards/STR-11_factor_investing_methods_and_practice.md#第-6-章因子研究现状) | `L2_confirmed`；7项已核为`verified_concept_only` |
| 风险或行为叙事必须提出可证伪预测，不能事后包办解释。 | 将 risk、mispricing、data snooping 作为竞争机制；用新样本、状态、基本面、注意力/套利成本代理和负结果共同检验。 | [STR-11 Ch06](cards/STR-11_factor_investing_methods_and_practice.md#第-6-章因子研究现状) | `L2_confirmed`；原PDF公式已核，行为参数不得迁移 |
| 风险模型未解释的收益方向绝不等于无风险，因子 timing 默认对比等权净收益。 | 建 return/risk exposure alignment；优化输出风险、成本、容量、约束损失和 infeasibility，timing/crowding 只作预注册 challenger/压力监控。 | [STR-11 Ch07](cards/STR-11_factor_investing_methods_and_practice.md#第-7-章因子投资实践) | `L2_confirmed`；11项已核为`verified_concept_only` |
| Forecast 必须相对明确 consensus/benchmark、horizon、uncertainty 和 skill calibration；raw signal 不是 alpha，time-series score 与 cross-sectional score 不得混用，未观察因子也不得机械置零。 | `ForecastEvidence` 保存raw/naive/refined、as-of/horizon/expiry、score_type、training-only scaler、per-asset distribution、volatility-scaling test、IC prior/posterior/interval、signal/factor covariance、direct/indirect view、marginal OOS contribution、risk-bucket diagnostic、trial lineage、cost与失败状态；return view不得覆盖独立Risk。 | [PORT-01 Ch01–02](cards/PORT-01_active_portfolio_management.md#第-1-章主动管理闭环)、[PORT-01 Ch10–13](cards/PORT-01_active_portfolio_management.md#第-10-章raw-signal-到-refined-forecast) | Ch01—02 9项、Ch10 10项、Ch11 8项、Ch12 11项、Ch13 10项均`L3_verified_concept_only`；当前OOS技能另证 |
| signal analysis 不是 investable backtest；数据错误先于 alpha 解释，统计显著性、经济价值、事件衰减和完整 trial universe 必须并列。 | `InformationAnalysisEvidence` 保存signal/test-portfolio identity、formation/weight/control/frequency、data reconciliation、benchmark/risk model、alpha/beta/IR/t-stat及依赖修正、turnover/up-down/regime slices、event/market clocks、arrival/decay/effective breadth、complete trials、OOS split、cost与falsifier；研究long/short约束不产生执行授权。 | [PORT-01 Ch12](cards/PORT-01_active_portfolio_management.md#第-12-章受控信息组合显著性与事件研究) | `L3_verified_concept_only`；11项已核，当前PIT数据、OOS价值和可投资性另证 |
| risk factor model、expected-return model、factor forecast 和 residual 语义必须隔离；解释共同风险或低 unexplained variance 不证明因子收益可预测；standard deviation、semivariance、shortfall/VaR、active/residual risk 与 factor/specific attribution只覆盖各自定义和模型。 | `RiskEvidence` 版本化 as-of、benchmark/holdings、PIT exposure、factor/specific covariance、PSD/rank/conditioning、total/active/residual/model-external stress、marginal direction与reconciliation；`FactorExpectedReturnEvidence` 另存factor/exposure/forecast定义、benchmark/intercept、Q/diversification、rank/rotation、OOS error/IC与成本。residual不自动命名为alpha；平方根缩放、对角specific covariance、GLS权重、sector attribution和APT表示均保存假设与challenger。 | [PORT-01 Ch03](cards/PORT-01_active_portfolio_management.md#第-3-章风险模型与风险归因)、[PORT-01 Ch07](cards/PORT-01_active_portfolio_management.md#第-7-章apt-与因子收益预测) | Ch03 `L3_verified_concept_only` 9项、Ch07 `L3_verified_concept_only` 7项已核；当前风险覆盖与因子forecast技能另证 |
| model price 不是事实；不确定现金流必须按状态风险定价，市场价差只有绑定有限收敛机制、catalyst 与 expiry 后才可能形成 Forecast。 | `ValuationEvidence` 保存as-of、cash-flow state/timing/currency、probability/version、discount curve/numeraire、state-price或risk-adjustment model、replication/market-completeness boundary、model-price range、market price、misvaluation sign、convergence/half-life/catalyst/expiry、sensitivity、challenger与fail-closed状态；估值性质、无套利存在和唯一性分开验证。 | [PORT-01 Ch08](cards/PORT-01_active_portfolio_management.md#第-8-章风险调整估值与收敛) | `L3_verified_concept_only`；9项已核，当前现金流、概率、折现与收敛技能另证 |
| DDM、可比估值和 returns-based analysis 是彼此独立的候选模型；增长、可比组、收敛期、风险控制和非线性处理都不能看 holdout 后选择。 | `PracticalValuationEvidence` 保存PIT财报/股本/债务/分红/回购、growth/payout/ROE、discount/terminal assumptions、implied与analyst forecast、training-only shrinkage、comparable-group版本、IRR/NPV语义、benchmark/risk controls、nonlinear trial lineage、sensitivity、OOS error、cost与falsifier；未收缩、简单DDM和市场基线并列。 | [PORT-01 Ch09](cards/PORT-01_active_portfolio_management.md#第-9-章ddm可比估值与-returns-based-analysis) | `L3_verified_concept_only`；11项已核，当前PIT输入、OOS技能与收敛证据另证 |
| benchmark timing 与 stock selection 是不同 forecast、风险预算和归因来源；value added 是给定二次偏好下的预期风险调整量，不是实现 PnL。 | `ActiveValueAddedEvidence` 保存 benchmark/mandate、time/risk premium、benchmark forecast、alpha、active beta、timing/selection risk aversion、active/residual risk、cost 与 realized attribution；仅在 active beta 为零且分解正交时合并 active/residual 口径。 | [PORT-01 Ch04](cards/PORT-01_active_portfolio_management.md#第-4-章benchmark择时与-value-added) | `L3_verified_concept_only`；5项已核，当前偏好参数与实现归因另证 |
| information ratio 必须区分 ex ante opportunity 与 ex post realization；最大 IR、线性 residual frontier、最优 residual risk 和 `IR²` value added 只在给定 alpha/covariance、二次偏好、线性尺度和无约束条件下成立。 | `InformationRatioEvidence` 保存 benchmark、alpha/risk versions、annualization、sample/effective years、dependence-aware interval、gross/net cost、constraints/capacity、risk aversion、constrained/unconstrained frontier 与失败状态；禁止按目标 IR 反向缩放后把结果称为已验证 skill。 | [PORT-01 Ch05](cards/PORT-01_active_portfolio_management.md#第-5-章ir机会集与风险预算) | `L3_verified_concept_only`；8项已核，当前OOS技能与可执行frontier另证 |
| breadth 必须是有效独立机会，资产数、调仓频率、lag 和信号数不能直接计数；half-life 是预测能力衰减而非持仓期，旧信号/收益只有证明增量信息才可进入 Forecast。 | `BreadthEvidence` 与 `TemporalForecastEvidence` 保存opportunity unit、arrival/as-of/expiry、delay grid、overlap、signal/outcome/portfolio/lag correlation、OOS IC/IR decay与区间、half-life model/challenger、effective dimension、current/lagged mixture、past-return availability、incremental value、turnover/cost与失败状态。 | [PORT-01 Ch06](cards/PORT-01_active_portfolio_management.md#第-6-章基本定律与有效-breadth)、[PORT-01 Ch13](cards/PORT-01_active_portfolio_management.md#第-13-章信息半衰期与旧信息再利用)、[PORT-01 Ch19](cards/PORT-01_active_portfolio_management.md#第-19-章benchmark-timingactive-beta-与低-breadth) | Ch06 8项、Ch13 10项均`L3_verified_concept_only`；Ch19待L3，当前OOS技能、有效breadth与实现IR另证 |
| 约束是信息损失和输入调节，不得只把输出看起来更稳就视为正确；modified alpha 只诊断约束损失，long/short 解除约束但不创造 alpha，成本期限、no-trade、QP、账户离散度和做空可行性均依赖显式假设。 | `PortfolioConstructionEvidence` 保存raw/refined alpha、training-only scaler、neutralization target/method/residual、benchmark/current holdings、risk-model/covariance rank/PSD/conditioning/shrinkage、cost side/horizon/impact/capacity、risk-aversion units、objective terms、constraint set/binding/shadow/modified alpha、constrained/unconstrained transfer loss、marginal value/risk/cost、no-trade reason、solver/infeasibility、factor/common/specific decomposition、account dispersion/convergence、estimate-error stress与challenger；`LongShortConstraintEvidence` 另存long-only/short-enabled objective与risk-model版本、gross/net/beta/cash exposure、binding rate、discarded negative alpha、positive-side knock-on loss、size/factor bias、borrow/locate/recall/buy-in、margin/collateral/funding/basis/roll、squeeze/gap/liquidation/venue stress及成本后OOS差值。 | [PORT-01 Ch14](cards/PORT-01_active_portfolio_management.md#第-14-章输入调节约束与成本后的组合构建)、[PORT-01 Ch15](cards/PORT-01_active_portfolio_management.md#第-15-章long-only-约束表达效率与做空边界) | Ch14 14项、Ch15 8项均`L3_verified_concept_only`；当前输入、优化器、borrow/funding、组合结果和做空权限另证 |
| 交易成本必须按 implementation shortfall 全链度量，成交记录不覆盖未下单和未成交意图；turnover、constraint repair 与 alpha-seeking trade 必须分账，边际价值不足时保持 no-trade。 | `TransactionCostEvidence` 对齐 decision/arrival/submission/ack/fill/cancel/replace，保存paper target、未成交数量、fee/spread/impact/delay/opportunity、side/venue/session/regime、ADV/participation/volatility、model/calibration/coverage/censoring、expected-vs-realized error与capacity stress；`TurnoverFrontierEvidence` 保存initial/feasible/target holdings、choice set、purchase/sale/cash-flow treatment、forced-vs-alpha turnover、frontier/slope/implied cost、heterogeneous cost、binding与no-trade reason；`ExecutionScheduleEvidence` 隔离short-horizon alpha/risk/impact，保存immediate benchmark、path/boundaries、order lifecycle、partial fill、queue/cancel latency、adverse selection、residual exposure、solver/infeasibility与fail-closed状态。 | [PORT-01 Ch16](cards/PORT-01_active_portfolio_management.md#第-16-章implementation-shortfallturnover-frontier-与执行调度) | `L3_verified_concept_only`；12项已核，当前成本模型、执行可达性和订单权限另证 |
| 绩效归因必须从冻结的期初决策连接预测、持仓、执行、成交和账本；横截面排名、终值、单一IR/Sharpe/t-stat或事后最佳因子都不能证明skill，显著性与经济价值必须分列。 | `PerformanceAttributionEvidence` 保存period/benchmark/return/cash-flow conventions、Forecast/TargetPosition/RiskDecision/Order/Fill/Position/Cash/PnL lineage、beginning holdings、PIT factor model/exposure/return、total/active/residual、beta surprise/timing、factor/specific/constraint/cost/shortfall、compound/log/arithmetic bridge、cross-product allocation与unexplained reconciliation；`PerformanceInferenceEvidence` 保存sample/effective periods、annualization、dependence-robust interval、alpha/beta/IR/Sharpe/t-stat、prior/conditioning variables、survivorship/coverage/size/risk bias、style conditioning、model sensitivity、economic value与falsifier。 | [PORT-01 Ch17](cards/PORT-01_active_portfolio_management.md#第-17-章skillluck-与可追溯绩效归因) | `L3_verified_concept_only`；12项已核，当前skill、归因模型与ledger一致性另证 |
| 战术配置和 defensive timing 是相对 benchmark 的独立预测问题，不能与选股 alpha 混账；资产数不是独立breadth，跨币种配置必须保持多numeraire一致，timing只有真正新增的时序信息才增加breadth。 | `AssetAllocationEvidence` 保存mandate/strategic benchmark、asset/market universe、PIT macro release/vintage/lag、training/OOS windows、raw/prior/refined forecast、IC/view covariance、risk model、raw/constrained weights、turnover/cost/capacity、OOS interval/regime/contribution concentration；`CurrencyPerspectiveEvidence` 保存base/local/asset/cash currencies、numeraire、spot/forward/fixing、local/FX/converted return与covariance term、hedge instrument/ratio/cost、perspective-specific return/risk、multi-numeraire round-trip residual与benchmark/currency-basket provenance；`BenchmarkTimingEvidence` 保存usual/exceptional return、forecast clock/expiry/frequency、score/IC/independent-bet decomposition、target/realized active beta、timing-risk budget、instrument/basis/roll/margin/cost、stock-beta error/residual risk及ex-ante/ex-post attribution。 | [PORT-01 Ch18](cards/PORT-01_active_portfolio_management.md#第-18-章战术资产配置benchmark-prior-与跨币种一致性)、[PORT-01 Ch19](cards/PORT-01_active_portfolio_management.md#第-19-章benchmark-timingactive-beta-与低-breadth) | Ch18 10项、Ch19 10项均`L3_verified_concept_only`；当前配置skill、FX hedge、timing skill与交易权限另证 |
| 外部经理、名人、历史因子、平均业绩、top trajectory、persistence和行为金融文献只提供背景；survivorship、coverage、style、fees、sample maximum与选择规则未审计时不得外推。 | `ExternalPerformanceLiteratureEvidence` 保存source/date/market、manager/fund universe、inclusion/exclusion/dead-fund coverage、sample period、benchmark/style/factor controls、gross/net fees/cost、holdings/turnover、winner/persistence definition、candidate count/selection rule、multiple-testing/survivorship/coverage bias、正负冲突结果、effect/interval/economic value、transferability verdict与falsifier；Promotion只接受本项目PIT、完整trial、成本后OOS、当前HEAD和locked-holdout access evidence。 | [PORT-01 Ch20](cards/PORT-01_active_portfolio_management.md#第-20-章历史经理记录persistence-与证据外推) | `L3_verified_concept_only`；7项已核，当前策略skill与promotion evidence另证 |
| 动态、流动性、负债、税务、非线性和行为机制未解决时必须显示 model-risk boundary。 | 建立 `DynamicStateEvidence`、`LiquidityStateEvidence`、`LiabilityTaxEvidence` 和 `ModelRiskRegister`；Liquidity 分 tightness/depth/resiliency/cross-impact，复杂机制登记 state/clock/path、mandate/jurisdiction、simple baseline、trial budget、反例和 fail-closed 条件，不由静态优化器或行为叙事外推。 | [PORT-01 Ch21](cards/PORT-01_active_portfolio_management.md#第-21-章未解问题与模型风险预算) | `L3/high_concept_only`；6 项原PDF已核 |
| 数学和自动化只能利用信息，不能创造信息或修复错误目标。 | `ActiveManagementClosedLoopEvidence` 连接 source/consensus/benchmark/clock、Forecast、RiskDecision、TargetPosition、Order/Fill/Ledger、Attribution、版本与 blocker；`EffectiveBreadthEvidence` 记录依赖簇、重叠、effective count、marginal IC、cost/capacity；`InformationValueEvidence` 记录 OOS incremental value/interval、trial、decay/crowding 与 falsifier。任一 stale/missing/blocked 或无增量信息状态向下游传播并回 benchmark/no-trade。 | [PORT-01 Ch22](cards/PORT-01_active_portfolio_management.md#第-22-章闭环总结与信息不可替代性) | `L3/high_concept_only`；4 项原PDF已核 |
| Expected return 是不可观测量，历史收益、理论、市场前瞻指标和调查只能作为相互制约的证据；跨资产历史比较必须先统一收益与风险调整口径。 | `ExpectedReturnEvidence` 强制记录 source/as-of、horizon、currency、nominal/real、total/excess、gross/net、benchmark/consensus、conditioning information、risk/mispricing/artifact解释、interval、trial count、rare-event stress和失效条件；`HistoricalForwardBaselineEvidence` 分开 sample/endpoints/subperiods/repricing 与 formula/unit/as-of/unchanged-state/overlap/effective breadth；`CrossAssetHistoricalReturnEvidence` 记录 universe/PIT、sample/start/end、arithmetic/geometric、total/excess、nominal/real、risk-free、currency/hedge、collateral、duration/rating、price/income/roll/cash、cost/tax、stale/survivorship 与 source/version；`ReturnMetricSemantics` 强制 ex-ante/ex-post、expected/required、time-series/cross-sectional、simple/log、inflation source/vintage、hedge residual、factor-set version、higher moments、liquidity 与 bias flags；Sharpe 和 benchmark-relative IR 分开。`ReturnSourceTaxonomy` 对 asset/style/factor 去重，未解释 residual 不自动命名 alpha。 | [PORT-02 Ch01–04](cards/PORT-02_expected_returns.md#第-1-章预期收益的多源证据与三视角) | Ch01—04 `L3/high_concept_only` 40项原EPUB已核 |
| return predictability 不唯一证明 risk premium 或 mispricing；风险补偿必须绑定坏状态、可识别 exposure 与 price of risk。 | `RiskPremiumHypothesis` 记录 payoff/SDF/state proxy、计价单位、factor/characteristic definition、PIT beta、price-of-risk、cross-sectional/time-series prediction、conditioning set、who bears loss、who pays、liquidity/funding/capacity、alternative rational/behavioral/artifact explanations、falsifier、trial universe 与 OOS result；模型存在、拟合或故事本身不解锁预测。 | [PORT-02 Ch05–07](cards/PORT-02_expected_returns.md#第-5-章理性风险定价多因子与市场摩擦) | Ch05 `L3/high_concept_only` 25项原EPUB已核；Ch06—07 39项待L3 |
| 跨资产预期收益必须拆成 carry、cash-flow growth 和 valuation change，并扣除 default、option、financing 与成本。 | 为股票、债券、信用、商品、BTC spot/perpetual/futures 分别建立构件、报价、roll、collateral 和 residual uncertainty。 | [PORT-02 Ch08–18](cards/PORT-02_expected_returns.md#第-8-章equity-risk-premium-的多方法证据)、[PORT-02 Ch21](cards/PORT-02_expected_returns.md#第-21-章forward-looking-measures-与三构件收益分解) | `L2_confirmed`；公式待 L3 |
| forward、curve steepness、basis、funding 或 yield spread 首先是 break-even 量，不自动等于市场预期或 alpha。 | 逐资产比较其对 future price/rate change 与 net excess return 的预测，并分离 roll、default、option、financing 和 bad-state loss。 | [PORT-02 Ch22](cards/PORT-02_expected_returns.md#第-22-章carryyield-spread-的预期与风险溢价分解) | `L2_confirmed`；48 项待 L3 |
| 主观调查、market-implied 和 model-implied forecast 是不同证据源。 | 调查保存 respondent universe、weighting、field/publish date、mean/median/mode、distribution、staleness 和 market snapshot；不得用 sentiment 冒充 expected return。 | [PORT-02 Ch23](cards/PORT-02_expected_returns.md#第-23-章survey-based-subjective-expected-returns) | `L2_confirmed`；28 项待 L3 |
| Tactical model 必须以简单基线、完整 trial ledger 和净可实现性为中心。 | timing/selection、binary/regression/rank/optimizer 使用同一 PIT rolling OOS、normalization、turnover、cost、capacity、crowding和forecast interval。 | [PORT-02 Ch24](cards/PORT-02_expected_returns.md#第-24-章tactical-forecast-的模型资产与实施边界) | `L2_confirmed`；47 项待 L3 |
| calendar、business-cycle 和 secular regime 都必须视为独立、易过拟合且会漂移的假说。 | 季节效应使用真实交易日和完整搜索族；macro state 使用vintage probability与transition lag；secular view只输出多情景、signpost和反证。 | [PORT-02 Ch25–27](cards/PORT-02_expected_returns.md#第-25-章seasonal-regularities-的制度机制与衰减) | `L2_confirmed`；137 项待 L3 |
| volatility 和 Sharpe 不能覆盖 correlation jump、negative skew、tail beta、liquidity、funding、crowding 与 operational risk。 | Portfolio/Risk 同时报 bad-state loss、drawdown、skew、liquidity/capacity、margin/liquidation、common holdings 和 scenario loss。 | [PORT-02 Ch18–20](cards/PORT-02_expected_returns.md#第-18-章illiquidity-characteristicliquidity-beta-与融资螺旋)、[PORT-02 Ch28](cards/PORT-02_expected_returns.md#第-28-章风险期限技能与全成本的净收益目标) | `L2_confirmed`；公式待 L3 |
| diversification、rebalancing、vol targeting 和 leverage 只有在相关性、收益差、融资、成本和危机退出假设成立时才改善净复利。 | 同时报告 AM/GM、variance drain、rebalance/no-rebalance、levered/unlevered、cash/margin ledger 和 correlation-one stress；允许 no-trade。 | [PORT-02 Ch28](cards/PORT-02_expected_returns.md#第-28-章风险期限技能与全成本的净收益目标) | `L2_confirmed`；84 项待 L3 |
| 主动管理成本前零和、成本后负和；ex-post alpha 混合 skill、luck、hidden beta、capacity 和 reporting bias。 | manager/strategy 评价使用 factor-adjusted、fee/cost-adjusted、dead-fund-aware、dollar-weighted return 与 ex-ante decision quality。 | [PORT-02 Ch28–29](cards/PORT-02_expected_returns.md#第-28-章风险期限技能与全成本的净收益目标) | `L2_confirmed`；公式待 L3 |
| “长期、规模大、资源丰富”不是自然优势的充分证据。 | `NaturalEdgeEvidence` 必须证明 liability horizon、liquidity buffer、stable risk tolerance、capacity、governance、incentive 和 crisis behavior；否则回低成本基线。 | [PORT-02 Ch29](cards/PORT-02_expected_returns.md#第-29-章长期投资者的自然优势约束与治理) | `L2_confirmed`；55 项待 L3 |
| 固定名义收益目标或“需要 X%”不得覆盖市场现实与负债约束。 | 机构目标随 inflation、real yield、risk premium、liability 和 regulation 更新；禁止用 expected asset return 美化 liability discount rate 或 funding ratio。 | [PORT-02 Ch29](cards/PORT-02_expected_returns.md#第-29-章长期投资者的自然优势约束与治理) | `L2_confirmed`；公式待 L3 |
| 主动收益必须解释谁付钱、为何持续，并覆盖研究、交易、融资、流动性、组织与容量成本。 | `StrategyEconomicsEvidence` 登记 profit source、other side、benchmark、gross/net、全成本、leverage、liquidity、capacity、tail 和 falsifier；标签与经理故事不算 edge。 | [PORT-03 Ch01](cards/PORT-03_efficiently_inefficient.md#第-1-章主动资本全成本容量与职责分离)、[PORT-03 Ch03](cards/PORT-03_efficiently_inefficient.md#第-3-章利润来源pit-回测与回归组合等价) | `L2_confirmed`；52 项待 L3 |
| alpha、Sharpe、drawdown 和年化结果都依赖 benchmark、频率、估值与分布假设，陈旧价格可制造虚假平滑。 | `PerformanceEvidence` 固定 return/benchmark/factor/frequency/gross-net，报告 SE/CI、自相关、非正态、stale-mark lags、tail、drawdown duration/recovery 和模型敏感性。 | [PORT-03 Ch02](cards/PORT-03_efficiently_inefficient.md#第-2-章绩效度量年化假设与陈旧价格偏差) | `L2_confirmed`；29 项待 L3 |
| Strategy 的信号不能替代稳健组合与独立 Risk；输入噪声、路径和流动性会放大理论最优解。 | Portfolio/Risk 对 expected return、covariance、cost、borrow、funding、liquidity 和 uncertainty 施加 hard caps、risk contribution、stress、deterministic delever/re-entry；缺证据 fail-closed。 | [PORT-03 Ch04](cards/PORT-03_efficiently_inefficient.md#第-4-章稳健组合独立风险覆盖与减仓再入场)、[PORT-03 Ch05](cards/PORT-03_efficiently_inefficient.md#第-5-章交易成本容量融资与流动性螺旋) | `L2_confirmed`；62 项待 L3 |
| 估值与定性研究只能形成带输入版本、反方解释、催化剂和反证条件的 thesis，model price 不是事实。 | `ValuationEvidence` 保存 PIT cash-flow/discount-rate/terminal assumptions、sensitivity 与 uncertainty；`QualitativeEvidence` 保存 thesis、management risk、catalyst、falsifier 和 review history。 | [PORT-03 Ch06](cards/PORT-03_efficiently_inefficient.md#第-6-章现金流估值终值敏感度与模型风险)、[PORT-03 Ch07](cards/PORT-03_efficiently_inefficient.md#第-7-章定性研究价值陷阱与访谈证据边界) | `L2_confirmed`；46 项待 L3 |
| 做空不是做多的镜像；负面 Forecast 只有在 locate、borrow、margin、recall、buy-in、squeeze 和法律证据齐全时才可能转成负仓位。 | `ShortabilityEvidence` 逐时点记录可借数量、fee、collateral、recall/cover、concentration、gap stress 与 MNPI/legal 状态；任一关键项缺失则 no-trade。 | [PORT-03 Ch08](cards/PORT-03_efficiently_inefficient.md#第-8-章借券合同强制回补与做空非对称性) | `L2_confirmed`；30 项待 L3 |
| 因子名、配置标签和宏观叙事都不是可迁移策略；PIT 构造、已定价预期、共享暴露、成本、容量和状态漂移必须分开验证。 | 因子建 `FactorEvidence`，配置建 `AllocationEvidence`，宏观建 `MacroContextEvidence`；分别保存 vintage、neutralization、risk contribution、market pricing、falsifier 与 OOS 衰减。 | [PORT-03 Ch09](cards/PORT-03_efficiently_inefficient.md#第-9-章因子契约组合中性与拥挤流动性风险)、[PORT-03 Ch10](cards/PORT-03_efficiently_inefficient.md#第-10-章配置层级收益分解与风险预算)、[PORT-03 Ch11](cards/PORT-03_efficiently_inefficient.md#第-11-章宏观假说政策时点与反身反馈) | `L2_confirmed`；104 项待 L3 |
| 趋势的跨市场分散与 crisis alpha 不是单 BTC、低平均相关或 CTA 标签可证明的属性。 | `TrendStrategyEvidence` 冻结 roll、lookback、signal lag、vol/covariance、cost、margin 和 universe vintage，报告 gap/reversal/whipsaw、stress correlation 与逐市场风险贡献。 | [PORT-03 Ch12](cards/PORT-03_efficiently_inefficient.md#第-12-章趋势证据波动缩放与尾部边界) | `L2_confirmed`；32 项待 L3 |
| 理论复制、relative value 或终值收敛不能消除中途 margin、borrow、basis、jump、模型和多腿执行风险。 | `ArbitrageRelationEvidence` 记录 legs/payoff、replication、convergence clock、fungibility、funding/margin、borrow、atomicity、basis/model error、path cash 和 kill condition。 | [PORT-03 Ch13](cards/PORT-03_efficiently_inefficient.md#第-13-章复制关系收敛条件与套利生存风险) | `L2_confirmed`；19 项待 L3，实施 blocked |
| 小价差、高杠杆和动态 hedge 会把 market liquidity、funding liquidity、counterparty 与 forced delever 连成同一生存问题。 | `FundingLiquidityStressEvidence` 和 `MultiLegRiskEvidence` 保存 funding maturity、margin/collateral、cash runway、Greeks、borrow、event terms、multi-leg fills、spiral stress 与 deterministic closeout。 | [PORT-03 Ch14](cards/PORT-03_efficiently_inefficient.md#第-14-章曲线相对价值融资流动性与资本生存)、[PORT-03 Ch15](cards/PORT-03_efficiently_inefficient.md#第-15-章多腿-greeks融资螺旋与事件条款) | `L2_confirmed`；71 项待 L3，rates/options/convertible blocked |
| 事件收益是承接 completion、legal、financing、borrow、corporate-action 与 failed-deal gap 的补偿，表面对冲仍可能是 short-tail。 | `EventStateEvidence` 版本化公告/条款和状态迁移，重建 payoff/hedge、审批/投票/融资、completion/failure/renegotiation、gap、cost、cash/margin 与逐事件损失上限。 | [PORT-03 Ch16](cards/PORT-03_efficiently_inefficient.md#第-16-章事件状态机交易条款与跳空尾部) | `L2_confirmed`；46 项待 L3，法律/事件数据/多腿实施 blocked |
| 名人案例、历史回报、监管做法、经验仓位和非公开关系只用于提出问题，不能提高证据等级。 | 所有书中案例回到当前公开 PIT 数据、当前法域、完整 trial、净成本 OOS、locked holdout access ledger 和 current-HEAD evidence；MNPI 或不可审计来源直接禁止。 | [PORT-03 Ch07](cards/PORT-03_efficiently_inefficient.md#第-7-章定性研究价值陷阱与访谈证据边界)、[PORT-03 Ch16](cards/PORT-03_efficiently_inefficient.md#第-16-章事件状态机交易条款与跳空尾部) | `L2_confirmed`；案例均为 low-confidence input |
| 交易系统必须从目的、授权和订单意图贯穿到成交、清算、结算与账本，角色和事实不可混写。 | `TradeLifecycleEvidence` 保存 beneficiary/principal/agent、objective、instrument、decision、authorization、parent/child、route、ack、fill、allocation、clearing、settlement 和 reconciliation。 | [EXE-01 Ch01](cards/EXE-01_trading_and_exchanges.md#第-1-章市场微观结构范围与端到端证据边界)、[EXE-01 Ch02](cards/EXE-01_trading_and_exchanges.md#第-2-章跨资产交易生命周期与案例证据降级)、[EXE-01 Ch03](cards/EXE-01_trading_and_exchanges.md#第-3-章交易行业拓扑合约语义与监管版本边界) | `L2_confirmed`；73 项待 L3 |
| 订单语义、市场结构和撮合结果必须由当前 capability 与规则版本决定。 | `OrderAndMarketCapabilityEvidence` 固定 type/TIF/display/activation/settlement、session/auction、tick、precedence、queue、partial fill、reference price、data entitlement 和 rule hash；未知即 fail-closed。 | [EXE-01 Ch04](cards/EXE-01_trading_and_exchanges.md#第-4-章订单意图成交不确定与-capability-边界)、[EXE-01 Ch05](cards/EXE-01_trading_and_exchanges.md#第-5-章市场结构-capability信息时钟与订单簿暴露)、[EXE-01 Ch06](cards/EXE-01_trading_and_exchanges.md#第-6-章优先级撮合规则与参考价失真) | `L2_confirmed`；73 项待 L3 |
| broker、路由与交易目的都必须显式审计授权、利益冲突和未成交反事实。 | `BrokerAndExecutionObjectiveEvidence` 保存 broker execution/clearing/custody/credit 权限、routing economics、PFOF/rebate、best-execution dimensions、objective/urgency、hedge basis/residual risk 和 client-first alternatives。 | [EXE-01 Ch07](cards/EXE-01_trading_and_exchanges.md#第-7-章broker-能力代理冲突与资产保护)、[EXE-01 Ch08](cards/EXE-01_trading_and_exchanges.md#第-8-章交易目的对冲残余风险与越权防线)、[EXE-01 Ch18](cards/EXE-01_trading_and_exchanges.md#第-18-章买方执行目标暴露预算与代理审计)、[EXE-01 Ch25](cards/EXE-01_trading_and_exchanges.md#第-25-章最佳执行路由冲突与流动性碎片化) | `L2_confirmed`；114 项待 L3 |
| 市场质量、信息优势和异常交易必须区分正向机制证据、规范偏好与法律定性。 | `MarketQualityAndInformationEvidence` 预注册 stakeholders/criteria/trade-offs，信息研究保存 legality/PIT/consensus/horizon/cost/falsifier；order anticipation/manipulation/MNPI 仅输出 risk flag、alternative hypotheses 与 escalation。 | [EXE-01 Ch09](cards/EXE-01_trading_and_exchanges.md#第-9-章市场质量多目标正向证据与规范判断分离)、[EXE-01 Ch10](cards/EXE-01_trading_and_exchanges.md#第-10-章信息是否进价竞争与流动性代价)、[EXE-01 Ch11](cards/EXE-01_trading_and_exchanges.md#第-11-章订单意图泄漏可预测强制流与退出路径风险)、[EXE-01 Ch12](cards/EXE-01_trading_and_exchanges.md#第-12-章虚假信息路径型价格冲击与反操纵证据边界)、[EXE-01 Ch29](cards/EXE-01_trading_and_exchanges.md#第-29-章重大非公开信息治理合法研究边界与合规证据) | `L2_confirmed`；143 项待 L3，法律需当前权威来源 |
| dealer、spread、block 与 liquidity 都是条件化容量问题，显示报价和 volume 不能证明利润或可成交性。 | `LiquidityAndDealerEvidence` 按 size/cost/time 保存 width/depth/immediacy/resiliency、displayed/latent、inventory、two-sided fills、fees/hedges/markout、parent exposure、ADV 与 recovery。 | [EXE-01 Ch13](cards/EXE-01_trading_and_exchanges.md#第-13-章做市能力库存账本与条件化报价证据)、[EXE-01 Ch14](cards/EXE-01_trading_and_exchanges.md#第-14-章即时性价格价差组成与代理变量边界)、[EXE-01 Ch15](cards/EXE-01_trading_and_exchanges.md#第-15-章大额订单容量隐性流动性与披露权衡)、[EXE-01 Ch19](cards/EXE-01_trading_and_exchanges.md#第-19-章规模时间成本与市场恢复的联合能力) | `L2_confirmed`；112 项待 L3 |
| 估值、套利和波动分解必须声明收敛机制、反方信息、路径风险与多腿生存条件。 | `ValuationRelativeValueEvidence` 保存 PIT value range、liquidity-demand hypothesis、fair basis、hedge ratio、leg atomicity、borrow/funding/margin、fundamental/transitory alternatives、capital runway 和 kill condition。 | [EXE-01 Ch16](cards/EXE-01_trading_and_exchanges.md#第-16-章估值区间终极流动性与赢家诅咒)、[EXE-01 Ch17](cards/EXE-01_trading_and_exchanges.md#第-17-章动态公平基差多腿完整性与生存资本)、[EXE-01 Ch20](cards/EXE-01_trading_and_exchanges.md#第-20-章基本面重估暂时性冲击与多尺度反转) | `L2_confirmed`；80 项待 L3 |
| 交易成本与绩效必须使用预先定义的反事实基准，并覆盖未成交、完整试验总体和比较优势。 | `ExecutionAndPerformanceEvidence` 从 decision/arrival/submission/ack/fill/cancel 分解 fee/spread/impact/delay/opportunity，绩效另保存 benchmark/risk model、cash flows、trial universe、tail、multiplicity 与 OOS。 | [EXE-01 Ch21](cards/EXE-01_trading_and_exchanges.md#第-21-章反事实基准总成本分解与估计偏差)、[EXE-01 Ch22](cards/EXE-01_trading_and_exchanges.md#第-22-章技能与运气完整试验总体及比较优势) | `L2_confirmed`；74 项待 L3 |
| 指数产品、指定流动性义务和碎片化 venue 不能仅凭同名 symbol、best price 或市场份额互换解释。 | `ProductAndVenueLinkageEvidence` 版本化 PIT components/weights/divisor、ETF/futures cash-flow/roll、DLP obligations/privileges、canonical instrument、access/fees/settlement、cross-venue route/ack/fill 与 duplicate protection。 | [EXE-01 Ch23](cards/EXE-01_trading_and_exchanges.md#第-23-章指数版本复制误差与产品可交易语义)、[EXE-01 Ch24](cards/EXE-01_trading_and_exchanges.md#第-24-章强制流动性义务角色冲突与特权对价)、[EXE-01 Ch26](cards/EXE-01_trading_and_exchanges.md#第-26-章碎片化市场跨venue联接与公共外部性) | `L2_confirmed`；88 项待 L3 |
| 自动化和危机控制必须以可审计状态机、容量、恢复和对账证据为准，不能把 stop、halt 或 backup 当保证。 | `ExecutionSREAndCrisisEvidence` 保存 rule/code hash、clocks、FSM、headroom/backpressure、RTO/RPO、failover、unknown-order reconciliation、halt/limit/reopen、margin/liquidation、cross-venue basis、kill/degraded mode 和 replay。 | [EXE-01 Ch27](cards/EXE-01_trading_and_exchanges.md#第-27-章自动化执行-sre可审计规则与接入公平)、[EXE-01 Ch28](cards/EXE-01_trading_and_exchanges.md#第-28-章反馈型极端波动市场状态切换与危机-sre) | `L2_confirmed`；56 项待 L3，生产压力/交易端点禁止触达 |
| 金融 ML 的标签、验证、选择、绩效、strategy viability、风险配置、结构突变、entropy、microstructure、parallel computation、离散配置搜索与HPC workflow必须围绕完整信息区间、非IID重叠、单一ledger、完整trial universe和一致约束构造。 | 除既有研究证据对象外，`ParallelRunEvidence`必须保存atom universe/stable IDs、molecule boundaries、coverage/disjoint hash、halo/owner、run/atom seed、worker/env/code hash、dispatch/retry/exception/cancel、canonical order、reducer identity/algebra/tree、serial oracle hash、tolerance、peak RAM、I/O/serialization与single-writer sink。`DiscreteOptimizationEvidence`另存objective/forecast/covariance/cost版本、`K`、唯一可行数、gross/net/cash/leverage约束、trajectory数量、objective uncertainty/near-best gap、solver/embedding/penalty/precision、经典复算和trial ledger。`HPCWorkflowEvidence`另存workload/query mix、input/schema/chunk/index/compression、PIT/lineage、single-node oracle、hardware/software版本、partition/communication/reduction、cold/warm latency与throughput、peak RSS、cost、failure/retry/checkpoint、retention/replay、output hash与SLO。并行、量子/退火或HPC只优化已证明等价且可复核的计算，不改变研究、回测或promotion语义。 | [RES-01 Ch01–22](cards/RES-01_advances_in_financial_machine_learning.md#章节卡) | `L3_complete_concept_only`；Ch02 50项与Ch03—Ch22各30项共650项已由原EPUB核为`verified_concept_only`。Ch20的5000 CPU线性缩放、Ch21的量子能力及Ch22的HPC/cloud成本性能、VPIN intrinsic/实时有效和NUFFT身份推断均为overclaim或历史主张；Ch22多数队列项是项目派生证据指标而非书中公式，实施仍须当前官方规格与本机fixture；annealer与HPC采购/迁移均`rejected_for_now` |
| Monte Carlo 必须把 estimand、DGP、状态、测度、抽样误差、离散误差和模型误差分开；增加路径数不能修复错误分布、时间/期限网格、跳跃、曲线、价值 mapping 或现实机制。 | `MonteCarloEvidence` 保存 measure/numeraire/DGP/state、RNG family/version/state/seed/substream/stream budget、platform/golden vectors、uniform consumption、sampler random dimension/endpoints、covariance PSD/rank/factor/order/residual、paths、exact-at-grid/interpolation/approximation、position snapshot/horizon/loss sign、risk-factor joint model、full/approx valuation mapping、continuous/discrete target、scheme/time-and-maturity-grid/max step、strong/weak target、regularity、exact/approximate、bias/variance/MSE、sensitivity estimand/method/step/coupling、path functional/tangent、density/score/support/rank/interchange、discontinuity smoothing、hybrid estimator、stopping filtration/exercise calendar、training/evaluation path split、continuation/basis/rank、high/low estimator、policy lower bound、martingale upper bound、nested simulation、bound gap、filtration/adaptedness/integrability、local-vs-true martingale、RN density/unit mean/equivalence/Girsanov、rate compounding/day-count/benchmark、curve/yield/forward/swap round-trip、futures resettlement/convexity、rate-option fixing/accrual/payment/quote convention、QMC family/base/dimension/start/skip/direction-table hash/finite-input bound、randomization/replicate/coordinate map/effective dimension/discrepancy/variation、curve/benchmark/day-count/accrual、measure-specific drift、jump pre/post state/intensity/compensator/activity/moment domain、martingale residual、calibration identifiability、quantile/tail count/CI/coverage、ESS、工作量归一效率、依赖/batch/pair/strata/coupling结构、proposal/support/log-weight/weight tail、barrier/transform/invariant、heavy-tail/copula/default/recovery evidence、收敛曲线、full-revaluation 与 alternative-DGP challenger；模拟路径不替代历史、fills 或 runtime。 | [RES-04 Ch01](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch01-原始扫描复核)、[RES-04 Ch02](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch02-原始扫描复核)、[RES-04 Ch03](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch03-原始扫描复核)、[RES-04 Ch04](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch04-原始扫描复核)、[RES-04 Ch05](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch05-原始扫描复核)、[RES-04 Ch06](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch06-原始扫描复核)、[RES-04 Ch07](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch07-原始扫描复核)、[RES-04 Ch08](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch08-原始扫描复核)、[RES-04 Ch09](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#ch09-原始扫描复核)、[RES-04 Appendix A/B/C](cards/RES-04_monte_carlo_methods_in_financial_engineering.md#附录复核) | `L2_confirmed_low_confidence`；Ch01 10项、Ch02 18项、Ch03 31项、Ch04 14项、Ch05 26项、Ch06 14项、Ch07 28项、Ch08 29项、Ch09 17项、Appendix A 6项、B 12项、C 12项已核；仅Ch08页421缺失 |
| 策略百科只能充当研究问题索引；条目数量、名称和书中分类既不证明 edge，也不授权批量实现或批量回测。 | `StrategyCatalogIntake` 对每个入选条目单独登记机制、PIT 数据、asset/capability、trial family、成本、执行、风险、falsifier 与拒绝理由；违法、不道德、越权和缺关键合同的条目直接拒绝。 | [STR-06 Ch01–04](cards/STR-06_151_trading_strategies.md#章节卡)、[STR-06 Ch11–20](cards/STR-06_151_trading_strategies.md#章节卡) | `L3_verified_concept_only`；151正式编号已核，多数仍概念或blocked |
| 相对动量与绝对动量是两个可消融 Forecast；防御资产、形成期和月频不是可迁移常数。 | `DualMomentumEvidence` 保存 PIT universe、rank/absolute benchmark、formation/skip、真实月末、signal-to-fill lag、防御资产 eligibility/credit/duration、成本、基准、trial family 和状态衰减；单 BTC 不得伪造横截面 breadth。 | [STR-07 Ch02–08](cards/STR-07_dual_momentum_investing.md#章节卡)、[STR-07 Ch09–10](cards/STR-07_dual_momentum_investing.md#章节卡) | `L2_confirmed`；10章及Appendix B共11项已核为`verified_concept_only` |
| 横截面动量的过去收益、路径质量、季节效应和 trend overlay 是独立模型族，不能从同一历史赢家中事后拼装。 | `MomentumResearchEvidence` 固定 PIT universe、delisting、formation/skip/holding/rebalance、path metric、calendar placebo、factor/sector exposure、turnover/capacity、trial lineage 与 matched baseline。 | [STR-08 Ch03–08](cards/STR-08_quantitative_momentum.md#章节卡)、[STR-08 Ch09](cards/STR-08_quantitative_momentum.md#章节卡) | `L2_confirmed`；9章及Appendix A/B共11项已核为`verified_concept_only` |
| 趋势计划必须把入场、initial stop、trailing stop、加仓、组合上限、异常和复盘拆成版本化合同；stop 不是成交保证。 | `TrendOperatingPlanEvidence` 连接 strategy spec、Forecast、risk budget、gap/liquidity stress、OrderIntent、fill/ledger、override、skipped signal、incident 与 journal；参数和风险比例不得从案例迁移。 | [STR-09 Ch01–08](cards/STR-09_the_trend_following_bible.md#章节卡)、[STR-09 Ch09–10](cards/STR-09_the_trend_following_bible.md#章节卡) | `L2_confirmed`；10 项规则/案例已核为`verified_concept_only` |
| 波动率风险单位、R-multiple、breakout 与相关限额只能统一普通状态下的比较尺度，不能覆盖 gap、流动性、相关跃升和不可分割约束。 | `RobustTrendRiskEvidence` 保存 ATR/clock、entry-stop、realized R、min lot、single/group/directional caps、MFE/MAE、参数 plateau、trial count、stress correlation、capacity 和 Monte Carlo lineage；书中风险比例及最优表格禁用。 | [STR-10 Ch03–08](cards/STR-10_turtle_trading_rules.md#章节卡)、[STR-10 Ch09–13](cards/STR-10_turtle_trading_rules.md#章节卡) | `L2_confirmed_low_confidence`；OCR、原版规则、图表和公式待 L3 |
| 传记中的人才、保密、自动化和历史收益只能形成组织与事故假设，不能证明模型、文化或量化方法优越。 | `ResearchOrganizationEvidence` 保存角色/ownership、data lineage、peer challenge、model-risk review、capacity、override、incident、succession、access/offboarding 与可接管 runbook；所有策略仍回到独立 PIT/OOS/cost/ledger 证据。 | [STR-12 Ch01–10](cards/STR-12_the_man_who_solved_the_market.md#章节卡)、[STR-12 Ch11–15](cards/STR-12_the_man_who_solved_the_market.md#章节卡) | `L2_confirmed`；无定量公式，叙事事实不作 alpha 证据 |
| 高频价格、LOB、最优执行、做市和订单不平衡模型必须先证明数据层级、事件时钟、queue/fill、状态与可容许控制；HJB/QVI 解不证明现实可执行。 | `HighFrequencyExecutionEvidence` 保存 feed tier、sequence/clock、book rebuild、parent/child lifecycle、queue/ahead volume、partial fill、latency、inventory/cash ledger、impact/markout、admissibility、numerical error、kill/reconcile 和 capability。 | [EXE-02 Ch01–04](cards/EXE-02_algorithmic_and_high_frequency_trading.md#章节卡)、[EXE-02 Ch05–12](cards/EXE-02_algorithmic_and_high_frequency_trading.md#章节卡) | `L2_confirmed`；380 项章节关系及 Appendix 数学待 L3，private/order/live 保持禁用 |
| 技术规则的可检验性来自明确算子、状态递归、完整规则生成器、PIT数据、matched-exposure基准、人工判断的事前封存、完整分母、可区分竞争解释的新预测和对数据挖掘的校正，不来自图形直觉、可编程本身或单条显著结果。 | `TechnicalRuleEvidence`保存rule generator/state/equality/initialization、全部方向与候选、data/PIT、decision→execution interval、gross/net cost layers、cash/buy-hold/incumbent/matched-position-bias placebo、bootstrap/null、selection adjustment、OOS与falsifier。`ManualForecastEvidence`另存pre-outcome input snapshot、observer、forecast/falsifier、horizon/threshold/expiry/first-touch、abstention、hidden-outcome replay、`A/B/C/D` counts、prevalence、conditional rates、precision/recall/calibration、missing denominator、dependence/selection、alternative explanations和versioned belief change。`ScientificClaimEvidence`保存observation→hypothesis→prediction→verification→conclusion五阶段、premises/auxiliary assumptions、target population、H0/HA/equivalence/misspecification、discriminating prediction、operation、error/power、competing explanations、ad-hoc change ledger和rejected/inconclusive/corroborated状态；概率性市场结果不得伪装成演绎证明。`SamplingInferenceEvidence`保存estimand、target population/time/regime、sample construction/unit、statistic、units、`n`与effective n、population/sample/statistic distribution、dependence/heteroskedasticity/tail/break diagnostics、density/base measure/atoms、IID与dependence-aware SE、resampling/null generator、exchangeability/block/cluster、seed/repetitions/Monte Carlo error和未覆盖的model/data/selection uncertainty。`StatisticalTestEvidence`保存H0/HA/equivalence、effect/minimum effect、tail/ordering、test statistic、alpha、Type I/II loss、power、null generator、family/selection adjustment、p-value计算与Monte Carlo interval、decision和assumption diagnostics；`IntervalEvidence`保存estimand、point estimate、interval method、nominal coverage、one/two-sided、bootstrap centering/quantiles、coverage diagnostics和realized-interval频率学边界。`SelectionAwareResearchEvidence`保存完整trial universe/family hash、候选spec与return/prediction matrix、total/effective trials、candidate correlation、winner operator/metric/gap、tail contribution、selection/estimation split、nested OOS、holdout owner/access/freeze hash、WRC/MCP/SPA/stepdown/PBO/DSR/CPCV方法版本与假设、共同resample/permutation、power及失败候选。`MechanismEvidence`保存edge_type、causal chain、PIT proxy、participant/state/horizon、information set/diffusion clock、risk model/benchmark/cost、counterfactual/competing explanations、lead-lag、capacity/crowding、crash/liquidity/funding budget、falsifier与failure state；mispricing、risk premium、liquidity service、information diffusion、institutional constraint和unknown分账。`RuleGeneratorEvidence`保存input lineage/availability、transform DAG/fit scope/warm-up、operator/version/index/lag/equality/missing、state initialization/hold/expiry、parameter domains/directions、declarative spec、deterministic enumeration count/order、invalid/dedup ledger、candidate/universe hash、formula round-trip、prefix invariance及data/code变更后的新version。`NegativeResultEvidence`保存完整family/hash、winner/metric、unadjusted与selection-adjusted effect/p/interval、null distribution/method/version/seed/repetitions/MC error、failed candidates、power、benchmark/cost/risk/capacity、holdout status、limitations、rejected/inconclusive reason和禁止缩family/换口径漂白的append-only历史。全测试期centering只可作ex-post benchmark；若进入online feature或可交易PnL则fail-closed。Strategy output不得直接解释为合约数量。 | [RES-02 Ch01–05](cards/RES-02_evidence_based_technical_analysis.md#章节卡)、[RES-02 Ch06–09](cards/RES-02_evidence_based_technical_analysis.md#章节卡) | `L3_complete_concept_only`；Ch01—Ch09各30项、共270项已由原PDF核为`verified_concept_only`，附录证明已纳入Ch01。四格计数为必要非充分条件；随机图只反驳“形状即证明”；形式逻辑不能替代概率检验；`SE=σ̂/√n`与CLT只在条件成立时使用；p值和realized CI均不得作后验概率解释。去趋势等价证明仅覆盖additive raw returns；执行式为`Pos_0×[log(O_{+2}/O_{+1})−ALR]`，书中next-open、200日均线、头肩过滤器、历史模拟、行为模型期限、MLM图表、6,402规则、赢家/p值/阈值/区间、历史输入/公式/参数、MX、WRC/MCP实现与成本外signal研究均不直接迁移 |
| 收益必须先固定价格、现金流、时钟、单位、聚合、权重和benchmark/funding语义；simple、log、portfolio与excess return不可混作同一PnL字段。 | `ReturnDefinitionEvidence` 保存instrument/version、price/cash-flow、clock、simple/log、gross/net、decimal/percentage、aggregation、weight timing、benchmark/funding及round-trip/boundary fixtures；`ConditionalDistributionEvidence`另存support、moments、tail、dependence、information set、likelihood和diagnostics。 | [RES-03 Ch01](cards/RES-03_analysis_of_financial_time_series.md#第-1-章收益语义条件分布与经验特征边界) | `L3_verified_concept_only`；30项已核，当前数据与实现另证 |
| 线性时间序列模型必须分离stationarity、AR roots、MA invertibility、order selection、innovation与forecast information set；单位根、HAC或慢ACF都不能单独证明模型。 | `LinearTimeSeriesEvidence` 保存series/clock、transform、root convention、candidate/order hash、criterion、fit scope、innovation、residual diagnostics、forecast recursion、interval components、break sensitivity和simple baseline；所有lag、test与bandwidth进入trial ledger。 | [RES-03 Ch02](cards/RES-03_analysis_of_financial_time_series.md#第-2-章线性依赖根条件动态回归与长记忆诊断) | `L3_verified_concept_only`；30项已核，当前模型增量另证 |
| volatility 必须先固定 physical/risk-neutral/realized/proxy estimand、horizon、clock 和 information set；ARCH/GARCH族的正性、矩、根、分布与proxy loss必须分别证明。 | `ConditionalVolatilityEvidence` 保存mean residual source、variance estimand、model/distribution/initialization、positivity、stationarity/moments、fit fold、forecast horizon、proxy-aware loss、tail/sign/break diagnostics、parameter/model uncertainty和EWMA/realized/simple baselines；输出只进入Forecast或Portfolio/Risk。 | [RES-03 Ch03](cards/RES-03_analysis_of_financial_time_series.md#第-3-章波动-estimand条件方差模型与可观测代理) | `L3_verified_concept_only`；30项已核，当前校准与增量另证 |
| 非线性检验、regime、kernel、state-space和神经网络只定义candidate family；阈值、state、bandwidth、architecture、seed与检验拒绝均不能替代稳定预测增量。 | `NonlinearModelEvidence` 保存null/alternative、family、threshold/delay/state、transition、bandwidth/local sample、architecture/seed/scaler、fit fold、diagnostics、bootstrap/predictive distribution、parameter/state/model uncertainty、complete trial ledger和linear/naive baseline。 | [RES-03 Ch04](cards/RES-03_analysis_of_financial_time_series.md#第-4-章非线性检验状态解释与样本外增量边界) | `L3_verified_concept_only`；30项已核，当前预测增量另证 |
| 高频与微观结构研究必须先证明trade/quote/order/L2层级、venue/feed/rule、event/session clock、tick、sequence、correction和清洗；异步、bid-ask bounce、duration与sampling selection可制造假相关。 | `MicrostructureDataEvidence` 保存source/level/venue/rule hash、event/receive clock、sequence/tie-break、tick/session、raw immutability、drop/repair counts、trade-sign/quote semantics、same-time ordering、duration/no-change sampling、effective n和current capability；无相应层级则fail-closed。 | [RES-03 Ch05](cards/RES-03_analysis_of_financial_time_series.md#第-5-章事件时钟微观结构偏差与duration证据边界) | `L3_verified_concept_only`；30项已核，当前逐笔/L2能力另证 |
| 连续时间模型必须先区分physical DGP、risk-neutral pricing、hedging与scenario用途；Wiener/GBM、Black-Scholes或jump模型的数学闭式不能替代测度、复制、离散观测和现实摩擦证据。 | `ContinuousTimeModelEvidence` 保存purpose/measure、SDE/jump、clock、observation/discretization、estimation、parameter uncertainty、path/residual diagnostics和alternatives；`DerivativePricingEvidence`另存contract/payoff、curve/dividend/borrow、surface、measure、Greeks、hedge clock、cost/margin、jump stress、replication error与reconciliation。 | [RES-03 Ch06](cards/RES-03_analysis_of_financial_time_series.md#第-6-章连续时间-dgp复制定价与测度跳跃边界) | `L3_verified_concept_only`；30项已核，当前定价、校准与实现另证 |
| VaR、ES、quantile与EVT输出必须绑定loss sign、amount/currency、as-of、horizon、tail probability和信息集；threshold、block、tail order、distribution与extremal-index设定均是训练内trial，单点尾部量不得直接生成仓位或订单。 | `TailRiskForecastEvidence` 保存risk contract、conditional distribution、fit window、tail method、threshold/block/order、effective exceedances/clusters、extremal index、VaR/ES及区间、support/moment checks、breach序列、coverage/independence/ES calibration、scenario stress、model alternatives和current-HEAD provenance。 | [RES-03 Ch07](cards/RES-03_analysis_of_financial_time_series.md#第-7-章条件尾部风险evt-阈值与极值聚集) | `L3_verified_concept_only`；30项已核，当前风险校准与实现另证 |
| 多变量动态必须冻结component/order/unit/clock、lag convention、matrix dimensions、stationarity、innovation covariance和识别限制；cross-correlation、Cholesky IRF、cointegration或spread回归不得写成因果、套利或market-neutral。 | `MultivariateTimeSeriesEvidence` 保存vector contract、CCM/lag sign、VAR/VMA/VARMA orders、roots、identification/order alternatives、likelihood/initial state、residual diagnostics、forecast/IRF intervals与break sensitivity；`CointegrationEvidence`另存integration tests、deterministic spec、rank/normalization、ECM/Johansen、PIT universe、threshold trials、多腿成本/borrow/dividend/margin/fills和failure states。 | [RES-03 Ch08](cards/RES-03_analysis_of_financial_time_series.md#第-8-章联合动态结构识别与协整交易边界) | `L3_verified_concept_only`；30项已核，当前关系、预测与执行另证 |
| factor与PCA必须先声明用途为risk、forecast、compression或mimicking portfolio，并冻结PIT factor/universe、scale、center、matrix、component count和rotation；variance explained、loading标签或数学正交不等于alpha、经济机制或自融资组合。 | `FactorModelEvidence` 保存factor definition/vintage、exposure/return timing、loadings、factor/specific covariance、residual dependence、mimicking weights与ledger constraints；`DimensionalityReductionEvidence`另存train-only universe/center/scale、matrix hash、solver、eigen/subspace、count criterion、rotation/alignment、reconstruction/downstream error、stability和simple baselines。 | [RES-03 Ch09](cards/RES-03_analysis_of_financial_time_series.md#第-9-章因子语义pca-识别与高维稳定性边界) | `L3_verified_concept_only`；30项已核，当前因子、风险与预测增量另证 |
| 条件协方差必须冻结vector/order/unit/calendar、mean residual source、horizon和information set；每步验证symmetry、PSD、conditioning与correlation bounds，并用full whitening、cross-products、tail、break和realized-loss检查，不以单变量残差或likelihood改善替代风险增量。 | `ConditionalCovarianceEvidence` 保存target/clock、model/distribution/initialization、EWMA/DVEC/BEKK/CCC/DCC/Cholesky/factor spec、roots、ordering/permutation、PSD/eigen/condition checks、whitening convention、forecast path、proxy-aware loss、parameter/generated-factor uncertainty、stress/model disagreement和shrinkage/EWMA baselines；输出只进入Portfolio/Risk。 | [RES-03 Ch10](cards/RES-03_analysis_of_financial_time_series.md#第-10-章条件协方差正定约束与风险输入边界) | `L3_verified_concept_only`；30项已核，当前协方差校准与风险实现另证 |
| 状态空间输出必须编码conditioned-through time并分离prediction、filtering与smoothing；初始化、missing mask、矩阵维度/PSD、innovation、parameter uncertainty和数值实现共同决定可信度，future-conditioned state/disturbance只作诊断。 | `StateSpaceForecastEvidence` 保存state/observation equations、matrix dimensions、noise/cross-noise、initialization/diffuse mode、available regressors、missing masks、filter/predict/smooth lineage、innovation/full whitening、likelihood/optimizer、state/observation intervals、parameter/model uncertainty、prefix invariance、square-root/singular handling和simple baselines；生产只暴露filtered/predicted。 | [RES-03 Ch11](cards/RES-03_analysis_of_financial_time_series.md#第-11-章状态信息集kalman-数值与-smoothing-泄漏边界) | `L3_verified_concept_only`；30项已核，当前filter实现与预测增量另证 |
| MCMC模型必须先固定变量、时钟、信息集、likelihood、prior、parameterization、sampler和收敛诊断；missing/outlier/SV/regime latent path 与 posterior predictive 必须标注 conditioned-through time，posterior复杂度不能替代预测增量。 | `BayesianComputationEvidence` 保存 model/prior hashes、parameter transforms、sampler blocks/proposals/grid、chain seeds、warmup/draws、ESS/MCSE、prior/initialization/parameterization sensitivity与approximation error；`PosteriorPredictiveEvidence`另存forecast origin、conditioned data/vintage、future-regressor policy、parameter/state/process draws、calibration、baseline和model-risk exclusions。full-path posterior只进入 `future_conditioned` 诊断区，实时输出仍停在Forecast或Portfolio/Risk。 | [RES-03 Ch12](cards/RES-03_analysis_of_financial_time_series.md#第-12-章mcmc-近似潜在路径与后验预测证据边界) | `L3_verified_concept_only`；30项已核，当前实现、校准与预测增量另证 |
| 无套利、自融资、测度变换、效用优化、SDE/PDE 和利率模型只说明给定市场与模型下的定价或偏好一致性，不产生 physical Forecast、市场均衡或现实 hedge 保证；概率极限、law/density、条件估计、状态压缩、凸性变换、first passage、停止规则、martingale representation 与 terminal-wealth optimization 必须携带sample space、clock、base/source/target measure、filtration及其生成条件、density/atoms、conditional version、numeraire、utility/domain、attainable set、measurability、integrability/representation space、convergence mode/topology、process tightness、partition/mesh、evaluation convention、variation estimand、completion space、transform regularity、state/driver dimension、kernel/density existence、generator/PDE direction、dependence family、充分状态、transition kernel、loading matrix/rank/column space/nullspace/condition number、stopping-time admissibility和cash-flow语义。 | `FinancialModelContract` 保存 probability space/filtration、sample-path support/null-set boundary、filtration generation/equality、discrete/continuous clock、tradable span/rank、source/target measure、absolute continuity/equivalence、density/state-price process、density local/true-martingale status、Novikov/sufficient condition、inverse density、Bayes rule、numeraire、physical/pricing drift、market-price-of-risk units/domain、utility/risk aversion/domain、budget/attainability、concavity certificate、payoff/settlement、cash-flow/ledger、自融资、replicability、claim→value→hedge construction order、martingale-representation existence/non-algorithm status、loading matrix/rank/column-space consistency/nullspace/condition number、near-singular sensitivity、EMM existence/uniqueness、completeness/span proof、nullspace hedge residual、arbitrage implication direction、state transition/augmentation/kernel、Markov state sufficiency/completeness、path accumulator units/window/normalization、fixing calendar/observation rule、phase transition/state handoff、kernel/density/base-measure/atoms、SDE solution existence/uniqueness/type、Markov sufficiency、generator/KBE sign、differentiation-under-integral、Feynman–Kac regularity/growth/uniqueness、PDE terminal/boundary/degeneracy、stochastic numeraire、shared-driver cross loading、stopping rule、barrier source/monitoring/inclusive rule/rebate、overshoot/fill boundary、continuation/obstacle、Snell-envelope minimality、compound-payment superposition、optional-sampling conditions、hitting-time transform/CDF/density/tail/mean existence、stochastic-integrator/integrand、adaptedness、square-integrability、partition/mesh、left/right/midpoint convention、first/quadratic/cross variation、Itô isometry、`L2(dt×P)` approximation/completion、`C^{1,2}`/local regularity、gradient/Hessian、state/driver dimensions、covariance/loading factorization、Brownian-recognition continuity/martingale/QV conditions、exact-vs-estimated QV/cross-QV、factorization/rotation identification、rank-collapse/conditioning、barrier-reference tradability/canonical instrument、alive/knockout state、MPR nullspace/EMM nonuniqueness、unspanned auxiliary-state exposure、dual-asset delta hedge、first-passage non-hit mass、exercise-supremum attainment、bounded optional sampling/localization、obstacle/complementarity residual、free-boundary smooth-fit/gamma jump、consumption cash flow、Snell-envelope minimality、first-contact/expiry semantics、dividend-event PIT dates/left-right state、convex-payoff no-early-exercise conditions、event-time exercise/continuation max、pre/post-dividend delta、reinvestment cash/share ledger、assignment semantics、forward delivery-price-vs-MTM、futures variation-margin cash-flow、settlement/delivery ledger、stochastic-rate bond risk、forward-futures covariance spread、historical backwardation/contango semantics、all-maturity EMM consistency、curve instrument/quote/day-count/calendar/bootstrap/interpolation contract、yield/forward/short-rate convention、HJM drift surface residual、cross-maturity market-price-of-risk、initial-curve timestamp、bond/forward-vol surface round-trip、maturity-zero-vol boundary、hedge admissibility/discretization/cost/residual、barrier Greeks/distance/time-to-expiry/capacity、CIR/CEV boundary classification、calibration、numerical cross-check/error、market incompleteness 和 residual risk；`DistributionEvidence`另存mapping/law/base measure、atoms、density existence、joint/marginal/conditional version、support、covariance/precision、rank/condition number、Gaussian-family proof、finite-dimensional joint-law coverage、pairwise-vs-joint boundary、MGF/density nonsingularity、deterministic-vs-stochastic integrand、conditional-vs-unconditional Gaussian、covariance-kernel round-trip、state sufficiency/augmentation、proof-gap register、deterministic-coefficient identity、affine bond-price/drift residual、curve/vol calibration identifiability、multi-derivative stability、conditional bivariate-Gaussian law、single-factor curve-shape residual、negative-rate/bond-above-par boundary、Feller zero-boundary classification、fixed-time-vs-pathwise positivity、non-central-chi-square transition、stationary-density normalization/KFE residual、degenerate-boundary PDE、Riccati/closed-form round-trip、deterministic time-change双时钟、short-end curve identity、curve-monotonicity/root-solve、source inconsistency、two-factor state semantics、affine covariance PSD/rank、Y-state drift closure/Feller positivity、correlated-driver transform、coupled Riccati residual、fixed-tenor yield identity、factor observability/identifiability、numéraire eligibility/strict positivity、measure-density/inverse-density、measure horizon、normalized-asset martingale、forward/stock measure drift shift、volatility invariance、dual-measure option decomposition、Merton probability/price residual、normalized self-financing round-trip、hedge proof gap、HJM lognormal-forward explosion/non-explosion、remaining-tenor transport、simple-vs-continuous rate、accrual tenor、partial bond-vol seed、recursive bond-vol/forward consistency、forward-measure horizon/drift removal、historical Black caplet、caplet integrated-variance bootstrap、vol-surface differentiation conditioning、bond-product round-trip、swap schedule/telescoping/par-rate identity、historical LIBOR与current RFR/fallback boundary及nonlinear/tail challengers；`StatisticalLimitEvidence`另存null-set convention、dominating envelope、effective sample size、conditioning atoms、partial-averaging、conditional-law residual、normalization、finite-dimensional convergence、function-space topology、tightness、proof mode与proof gap。 | [RES-05 Ch01](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch01-原始-pdf-复核)、[RES-05 Ch02](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch02-原始-pdf-复核)、[RES-05 Ch03](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch03-原始-pdf-复核)、[RES-05 Ch04](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch04-原始-pdf-复核)、[RES-05 Ch05](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch05-原始-pdf-复核)、[RES-05 Ch06](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch06-原始-pdf-复核)、[RES-05 Ch07](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch07-原始-pdf-复核)、[RES-05 Ch08](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch08-原始-pdf-复核)、[RES-05 Ch09](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch09-原始-pdf-复核)、[RES-05 Ch10](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch10-原始-pdf-复核)、[RES-05 Ch11](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch11-原始-pdf-复核)、[RES-05 Ch12](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch12-原始-pdf-复核)、[RES-05 Ch13](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch13-原始-pdf-复核)、[RES-05 Ch14](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch14-原始-pdf-复核)、[RES-05 Ch15](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch15-原始-pdf-复核)、[RES-05 Ch16](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch16-原始-pdf-复核)、[RES-05 Ch17](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch17-原始-pdf-复核)、[RES-05 Ch18](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch18-原始-pdf-复核)、[RES-05 Ch19](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch19-原始-pdf-复核)、[RES-05 Ch20](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch20-原始-pdf-复核)、[RES-05 Ch21](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch21-原始-pdf-复核)、[RES-05 Ch22](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch22-原始-pdf-复核)、[RES-05 Ch23](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch23-原始-pdf-复核)、[RES-05 Ch24](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch24-原始-pdf-复核)、[RES-05 Ch25](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch25-原始-pdf-复核)、[RES-05 Ch26](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch26-原始-pdf-复核)、[RES-05 Ch27](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch27-原始-pdf-复核)、[RES-05 Ch28](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch28-原始-pdf-复核)、[RES-05 Ch29](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch29-原始-pdf-复核)、[RES-05 Ch30](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch30-原始-pdf-复核)、[RES-05 Ch31](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch31-原始-pdf-复核)、[RES-05 Ch32](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch32-原始-pdf-复核)、[RES-05 Ch33](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch33-原始-pdf-复核)、[RES-05 Ch34](cards/RES-05_stochastic_calculus_and_finance_lecture_notes.md#ch34-原始-pdf-复核) | `L3_complete_concept_only`；Ch01 30项、Ch02 17项、Ch03 16项、Ch04 19项、Ch05 20项、Ch06 21项、Ch07 14项、Ch08 29项、Ch09 25项、Ch10 17项、Ch11 26项、Ch12 28项、Ch13 35项、Ch14 33项、Ch15 37项、Ch16 40项、Ch17 28项、Ch18 29项、Ch19 28项、Ch20 36项、Ch21 30项、Ch22 52项、Ch23 33项、Ch24 52项、Ch25 83项、Ch26 32项、Ch27 48项、Ch28 67项、Ch29 58项、Ch30 96项、Ch31 142项、Ch32 66项、Ch33 113项、Ch34 124项已核 |
| 概率、信息集、Brownian/QV、Itô、risk-neutral、PDE、American exercise、numeraire、term structure 与 jump 规则只可使用已恢复章节；损坏来源不得靠推断补齐。 | `SourceIntegrityBoundedModelEvidence` 逐项保存原文行号、来源质量、measure/clock/state/assumption、公式状态和 blocked section；Ch07 exotic-options 前半及附录保持不可引用。 | [RES-06 Ch01–06](cards/RES-06_stochastic_calculus_for_finance_ii_ocr_blocked.md#章节卡)、[RES-06 Ch08–11](cards/RES-06_stochastic_calculus_for_finance_ii_ocr_blocked.md#章节卡) | `L2_confirmed_low_confidence_partial`；10/11 章，Ch07 与全部公式 blocked |

### L2 手册使用限制

- `RES-05` 已完成 Ch01—34 共34/34章 L2；Ch01 37页/30项、Ch02 10页/17项、Ch03 7页/16项、Ch04 10页/19项、Ch05 7页/20项、Ch06 6页/21项、Ch07 5页/14项、Ch08 14页/29项、Ch09 8页/25项、Ch10 4页/17项、Ch11 8页/26项、Ch12 8页/28项、Ch13 13页/35项、Ch14 14页/33项、Ch15 9页/37项、Ch16 11页/40项、Ch17 7页/28项、Ch18 5页/29项、Ch19 5页/28项、Ch20 10页/36项、Ch21 4页/30项、Ch22 9页/52项、Ch23 5页/33项、Ch24 8页/52项、Ch25 16页/83项、Ch26 4页/32项、Ch27 8页/48项、Ch28 9页/67项、Ch29 7页/58项、Ch30 9页/96项、Ch31 16页/142项、Ch32 5页/66项、Ch33 9页/113项、Ch34 13页/124项均为`verified_concept_only`。现已进一步把 density local/true-martingale、Novikov sufficient condition、inverse density/Bayes rule、equivalence、numeraire、market-price-of-risk domain、Brownian-generated filtration equality、representation space/integrability、tradable loading span、rank/column-space consistency/nullspace/conditioning、near-singular sensitivity、MPR 解的存在与唯一性、EMM/完备性分类、theorem-vs-algorithm、explicit model-arbitrage construction、nullspace hedge residual、barrier source/monitoring/inclusive rule、reflection support、terminal-boundary discontinuity、stopped-process PDE、near-barrier Greek/cash stress、tolerance-boundary approximation、path accumulator units/window/normalization、fixing calendar、有限变差状态增广、pre/post-average phase handoff、sample-support/null-set boundary、claim→value→hedge construction order、Markov state sufficiency、stochastic numeraire、shared-driver cross hedge、Brownian-recognition exact conditions、exact-vs-estimated QV/cross-QV、factorization/rotation non-identifiability 和 correlation-boundary rank collapse/conditioning、barrier-reference tradability、alive/knockout state、MPR nullspace/EMM nonuniqueness、unspanned auxiliary-state exposure 和 dual-asset delta hedge、first-passage non-hit mass、exercise-supremum attainment、bounded optional sampling、obstacle/complementarity residual、free-boundary smooth-fit/gamma jump、consumption cash flow、Snell-envelope minimality 和 first-contact/expiry semantics、dividend-event PIT dates/left-right state、event-time exercise/continuation max、pre/post-dividend delta、reinvestment cash/share ledger 和 assignment semantics、forward delivery-price-vs-MTM、futures variation-margin cash-flow、settlement/delivery ledger、stochastic-rate bond risk、forward-futures covariance spread 和 historical backwardation/contango semantics、all-maturity EMM consistency、curve instrument/quote/day-count/calendar/bootstrap/interpolation contract、yield/forward/short-rate convention、HJM drift surface residual、cross-maturity market-price-of-risk、initial-curve timestamp、bond/forward-vol surface round-trip和maturity-zero-vol boundary、finite-dimensional joint-law coverage、pairwise-vs-joint boundary、deterministic-vs-stochastic integrand、conditional-vs-unconditional Gaussian、covariance-kernel round-trip、state sufficiency/augmentation和proof-gap register、deterministic-coefficient identity、affine bond-price/drift residual、curve/vol calibration identifiability、multi-derivative stability、conditional bivariate-Gaussian law、single-factor curve-shape residual和negative-rate/bond-above-par boundary、Feller zero-boundary classification、fixed-time-vs-pathwise positivity、non-central-chi-square transition、stationary-density normalization/KFE residual、degenerate-boundary PDE、Riccati/closed-form round-trip、deterministic time-change双时钟、short-end curve identity、curve-monotonicity/root-solve和source inconsistency、two-factor state semantics、affine covariance PSD/rank、Y-state drift closure/Feller positivity、correlated-driver transform、coupled Riccati residual、fixed-tenor yield identity和factor observability/identifiability、numéraire eligibility/strict positivity、measure-density/inverse-density、measure horizon、normalized-asset martingale、forward/stock measure drift shift、volatility invariance、dual-measure option decomposition、Merton probability/price residual、normalized self-financing round-trip、hedge proof gap、HJM lognormal-forward explosion/non-explosion、remaining-tenor transport、simple-vs-continuous rate、accrual tenor、partial bond-vol seed、recursive bond-vol/forward consistency、forward-measure horizon/drift removal、historical Black caplet、caplet integrated-variance bootstrap、vol-surface differentiation conditioning、bond-product round-trip、swap schedule/telescoping/par-rate identity和historical LIBOR与current RFR/fallback boundary映射为研究证据合同；风险中性测度与表示定理只作指定模型中的定价/存在性工具，不作为 physical Forecast、任意 claim 唯一价格、现实可计算 hedge、可执行套利、exotic implementation、ledger 或promotion许可。Ch34已完成逐页L3概念复核，因此本书达到全书原始PDF概念级复核完成态；但仍不是衍生品/利率实现许可、当前RFR或benchmark规格或promotion evidence。
- `RES-06` 当前完成 Ch01—06、Ch08—11 共10/11章低可信 L2；其概率、information set、Brownian/QV、Itô、risk-neutral/market completeness、SDE/PDE、American exercise、numeraire/FX、term structure与jump内容仅用于交叉确认既有边界。仅Ch07前半和Appendix源损坏，11章全部公式待来源修复与L3，因此不得描述为整本精读完成、独立公式证据或实现许可。 2026-07-16本地复查未发现第二份原件，Poppler确认多组xref/page-tree节点及Ch07邻近图像XObject缺失，其他本地解析器亦不能稳定恢复；该项继续fail-closed，不能以OCR猜补公式、页码或缺失正文。 对象级审计进一步确认570页目录仅存446个Page及446个配对Resources，缺失Page引用恰为124个；25,376个图像对象仅149个为无Resources的孤儿条带，不足以恢复缺页顺序、版面、公式或正文。
- `RES-01` 已完成22/22章L2与原EPUB概念级L3；Ch02 50项、Ch03—Ch22各30项，共650项均关闭为`verified_concept_only`。内容覆盖数据/标签/验证/选择、bet-sizing、回测风险、绩效、strategy-risk、HRP、结构突变、entropy、microstructure、parallel provenance、离散搜索与HPC workflow；既有source errors/omissions/overclaims均保留。Ch20确认并行代数边界但否定5000 CPU近线性外推；Ch21确认gross/net混淆、zero-sign重复、缺grid误差界与QUBO/量子能力证明；Ch22确认13个图片资源只有10幅历史图与1个参考文献公式图，没有独立算法公式或snippet，latency/TCO/MPI parity/FNR/precision等队列项是项目派生合同。任何并行、离散或HPC实现仍须确定性、可行性、经典复算、current-version规格、本机profile与failure/replay fixture；不运行书中代码/benchmark，不授权采购、迁移、回测或promotion。
- `RES-04` 已完成9/9章及Appendix A/B/C全部原载体可用内容页的低可信概念级复核；Appendix B全13个内容页拆12项stochastic-calculus/measure-change边界，Appendix C全9个内容页拆12项curve/benchmark/rate-derivative边界。全书现有187项章节、30项附录，共217项为`verified_concept_only`，仅Ch08页421保留`blocked_source_gap`；模拟路径不得替代历史、paper runtime、fill ledger或真实风险分布。
- `ENG-01` 已满足单书完成条件：21/21章 L2，复杂度加权关系、注释成本估算和RAMCloud历史性能数字3项已直接回看原EPUB并关闭为`verified_concept_only`；本书仍只是设计审查来源，不是当前代码已审计、重构获批或性能目标证据。
- `ENG-02` 已满足单书完成条件，因为没有需转入项目的定量公式；其代码示例仍未获生产批准。
- `ENG-03` 已满足单书完成条件：12/12章及120个可靠性、负载/尾延迟、数据模型、存储、兼容性、复制、分区、事务、部分失败、一致性/共识、批处理、流处理与可审计数据流条目均直接回看原EPUB并关闭为`verified_concept_only`；这不是基础设施迁移批准、当前实现证据或promotion evidence，不得据此引入集群、改生产schema、broker或数据路径。
- `ENG-04` 已满足单书完成条件：14/14章及70个存储布局、B-Tree、文件格式、WAL/checkpoint、LSM、故障检测、复制、分布式事务和共识条目均直接回看原EPUB并关闭为`verified_concept_only`；本书只支持审查当前SQLite/artifact/handoff，不证明当前实现正确，也不授权自研storage engine、引入集群、分布式事务或BFT。
- `ENG-05` 已满足单书完成条件：25/25章 L2，测试聚合时间、变更准备成本和反馈延迟3项历史估算已直接回看原EPUB并关闭为`verified_concept_only`；本书只支持遗留代码变更与重构证据设计，不证明当前BTC/美股实现正确、不批准重构，也不得把书中秒数或工时设为测试SLA、工期或promotion gate。
- `STR-01` 已满足单书完成条件：15/15章、附录B—D及75个拟合、forecast、组合、风险、仓位、成本、容量、运行流程和历史参数条目均直接回看原EPUB并关闭为`verified_concept_only`；本书不证明当前策略有效或可执行，固定10/20/2.5、256日、25/36日、10% inertia、四block、成本上限与Kelly折扣均不得迁移或解锁promotion。
- `STR-02` 已满足单书完成条件：10/10章、1990—2011共22个年度案例及50个连续期货、趋势、仓位、组合风险、回放、复制、执行、现金和历史数字条目均直接回看原EPUB并关闭为`verified_concept_only`；10/100均线、50/25突破、100日ATR、20bp、3 ATR、资本门槛、费用、基金收益和事件数字均不得迁移，本书不证明当前BTC/美股策略有效、可执行或ready。
- `STR-03` 已满足单书完成条件：S01—S30与T01—T04共34章L2，加上Appendix B物理页679—690拆出的11个back-adjust、收益/波动、相关/协方差、turnover、FDM/IDM计算族，共45项均直接回看原PDF并关闭为`verified_concept_only`。16/256、32日、十年、0.7/0.3、60/40、99%分位、cap2/2.5、cost penalty、buffer、风险/资本门槛和历史绩效均不得迁移，也不证明当前BTC/美股策略有效、可执行或ready。
- `STR-04` 已完成24/24章 L2，并直接核对2285页原PDF的24个chapter bookmark、物理页和一级方法簇；因每个队列项覆盖整章高密度公式/表格，当前仅为`original_pdf_structure_verified_formula_pending`，不计单书complete。历史参数、图形方法、旧式全样本重估和触价成交假设不得迁移或解锁paper/live。
- `STR-06` 已满足单书完成条件：通过原EPUB的2,252个local headers恢复20个chapter XHTML，核得151个正式编号及21个未编号变体，20个章节级策略族条目均关闭为`verified_concept_only`；公式图、payoff、参数和表格不认证，目录只能建立研究问题，options、信用、多腿、违法或越权条目继续blocked/rejected。
- `STR-07` 已满足单书完成条件：10/10章 L2，relative/absolute定义、GEM顺序、风险指标、trial治理和Appendix B共11项已直接回看原EPUB并关闭为`verified_concept_only`；12个月、月频、T-bill/综合债券、20bp、1.85倍杠杆、因子alpha和历史绩效均不得迁移。
- `STR-08` 已满足单书完成条件：9/9章 L2，定义、路径质量、季节、费用、因子、退市、组合、Appendix A候选和Appendix B指标共11项已直接回看原PDF并关闭为`verified_concept_only`；12-minus-1、FIP、月份、成本、权重、均线和历史绩效均不得迁移或从holdout挑选。
- `STR-09` 已满足单书完成条件：10/10章 L2，breakout/retracement、仓位、stop、风险公式/比例、管理人记录和journal共10项已直接回看原PDF并关闭为`verified_concept_only`；作者参数、业绩与交易独立性主张均不得迁移，journal仍不替代fill/position/cash ledger。
- `STR-10` 已完成13/13章低可信 L2，但OCR、原始扫描PDF、原版海龟规则、图表、历史数字和全部公式仍待逐页L3；风险比例、ATR窗口、加仓和历史最优系统不得迁移。
- `STR-12` 已满足单书完成条件，因为是叙事性传记且无需转入项目的定量公式；其人物、组织、收益和策略故事仍只作低等级问题线索，不构成当前研究或文化证据。
- `RES-02` 已完成9/9章L2和270/270项原PDF概念级L3；附录去趋势证明已纳入Ch01。该书达到`original_pdf_formula_review_complete_concept_only`，但仍不是公式代码、当前策略、回测、holdout、paper/live或promotion evidence。
- `RES-03` 已完成 12/12 章 L2 与 360/360 项原PDF `L3/high_concept_only` 复核，覆盖收益与分布、线性时间序列、条件波动、非线性、微观结构、连续时间、尾部风险、多变量关系、因子降维、条件协方差、状态空间及 MCMC/Bayesian predictive。该书达到 `original_pdf_formula_review_complete_concept_only`，但不是公式代码、当前研究、回测、holdout、paper/live或promotion evidence；任何历史模型、参数、measure、tail threshold、cointegration relation、factor label/loading、covariance path、state、prior、posterior或predictive设定均不得直接转入生产研究规格。
- `STR-05` 已满足单书完成条件：8/8章 L2，回测、执行、Kelly、协整、factor/PCA、OU、季节性和HFT共27项已直接回看原PDF并关闭为`verified_concept_only`；全部经验阈值、历史结果和时代性接口不得迁移，HFT/private/order/paper/live仍保持blocked。
- `STR-11` 已满足单书完成条件：7/7章 L2，CAPM/Fama–MacBeth/HAC/GRS/GMM、因子模型、异象、FDR/Bayes、ML/IPCA、Barra、优化、归因、另类数据和RTI/DR共36项已直接回看原PDF并关闭为`verified_concept_only`；A股结果、固定阈值、经验参数和历史绩效不得迁移至美股/BTC。
- `PORT-01` 已满足单书完成条件：22/22 章 L2，主动管理闭环、forecast/CAPM baseline、风险定义/模型/归因、benchmark timing/stock selection、ex ante/ex post IR、residual frontier、最优风险、value-added objective、基本定律、有效 breadth、APT/因子预测边界、风险调整/实务估值、基础/高级预测、信息分析、信息时效、输入调节、约束/成本/no-trade、optimizer robustness、账户离散度、long-only constraint loss、long/short 实施边界、implementation shortfall、turnover frontier、执行调度、skill/luck推断、可追溯绩效归因、战术资产配置、跨币种一致性、benchmark timing、active-beta归因、历史业绩外推边界、动态/流动性/负债/税务/非线性/行为模型风险及信息不可替代性共 188 项均由原PDF核为 `verified_concept_only`。该书达到 `original_pdf_formula_review_complete_concept_only`，但不是公式代码、当前研究/预测/组合/估值/执行/skill/配置/timing证据、订单许可或 promotion evidence。
- `PORT-02` 已完成 29/29 章 L2；29章1038项加 Appendix B provenance 1项，共1039项。Ch01—05 的 expected-return 证据、跨资产/跨币种收益口径、风险调整术语，以及 present value、CAPM、SDF/bad-state covariance、多因子、conditional risk、WDRA/habit、co-skewness、学习、供需/流动性/分歧、EMH joint hypothesis 和 adaptive-market 边界共65项，已由原EPUB/XHTML/Table 2.1、3.1—3.7、4.1、5.1/Box 4.1—4.2、5.1/式5.1—5.6/Figure 1.1—1.5、2.1—2.8、3.1—3.12、5.1—5.2核为 `verified_concept_only`；Ch06—29 仍有973项、Appendix B 1项待 L3，因此尚不是整本公式完成态、当前预测或 promotion evidence。
- `PORT-03` 已完成 16/16 章 L2，但 491 个公式、统计解释、模型关系、历史数字和案例仍在 `formula_review_queue.md`，因此只是章节语义完成态；rates、options、convertible、distressed 与 event-driven 实施继续 blocked。
- `EXE-01` 已完成 29/29 章 L2，但 813 个公式、机制、历史数字、监管规则和案例仍在 `formula_review_queue.md`；当前 venue/broker/API/费用/处罚/法域事实必须另查权威来源，因此不是公式完成态、法律意见、执行 readiness 或 promotion evidence。
- `EXE-02` 已完成12/12章语义L2，其中Ch01—04因OCR保持低可信、Ch05—12已做原页语义核对；380项章节关系与Appendix数学仍待逐式L3，HFT、做市、暗池、queue-position、private/order/live能力继续blocked。
- 上表只允许 Agent 生成候选、合同、测试或 blocker；不得据此运行新回测、改参数、查看 holdout、生成 promotion 结论或打开交易权限。

## 十、Agent 交付模板

### 书籍知识采用记录

```yaml
knowledge_claim_id: BOOK-CLAIM-...
source_book_ids: [STR-01, RES-02]
source_files: []
concept: ...
project_translation: ...
affected_modules: []
status: concept_only
required_evidence: []
known_limitations: []
conflicts_with_current_rules: []
```

### 研究候选记录

```yaml
candidate_id: ...
source_book_ids: []
economic_hypothesis: ...
instrument_scope: ...
decision_horizon: ...
data_and_pit_requirements: []
signal_definition: ...
forecast_mapping: ...
baseline: ...
trial_budget: ...
holdout_policy: ...
cost_model: ...
risk_constraints: []
failure_conditions: []
promotion_ceiling: research_only
```

## 十一、禁止解释

- 不把书中收益曲线或案例当作当前策略 evidence。
- 不把传记中的组织故事当作可复现 alpha。
- 不把数学复杂度当作预测能力。
- 不把 Monte Carlo 路径当作真实样本或真实成交。
- 不把单市场趋势结果当作多资产 CTA 证据。
- 不把方法百科中的策略名称直接注册为 paper candidate。
- 不从 OCR 文本直接复制公式、参数或代码到生产路径。
- 不用书籍结论覆盖当前 HEAD 的 blocker、安全旗标或人工 gate。
