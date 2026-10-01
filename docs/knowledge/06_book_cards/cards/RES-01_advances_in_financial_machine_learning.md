---
book_id: RES-01
title: Advances in Financial Machine Learning
authors: [Marcos Lopez de Prado]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Advances in Financial Machine Learning - Marcos Lopez de Prado - 原文.md
source_format: epub_text_plus_original_epub_visual_formula_review
source_sha256: 7c71d4fe44017ba0d71328846ea2f3664f4beb96f5a92c5eedb2a0ff5277a40c
original_epub_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Advances in Financial Machine Learning (Marcos M. López de Prado) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_epub_sha256: 3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1
source_line_count: 33683
card_status: original_epub_formula_review_complete_concept_only
chapter_count: 22
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: ch01_no_formula_ch02_50_ch03_30_ch04_30_ch05_30_ch06_30_ch07_30_ch08_30_ch09_30_ch10_30_ch11_30_ch12_30_ch13_30_ch14_30_ch15_30_ch16_30_ch17_30_ch18_30_ch19_30_ch20_30_ch21_30_ch22_30_items_verified_concept_only
last_reviewed_at: 2026-07-16
---

# RES-01：Advances in Financial Machine Learning

## 覆盖声明

本卡已避开目录和分部页重复，按正文标题定位22章并完成全部章节级`L2`与原EPUB概念级`L3`复核，覆盖`22/22=100%`；第1章无定量公式，Ch02关闭50项、Ch03—Ch22各关闭30项，共650项均为`verified_concept_only`。该状态只证明来源位置、概念、假设、错误/遗漏与项目边界已逐项核对；原文snippet、公式、历史案例、性能数字与阈值均未执行，不得直接进入生产代码、实现合同、回测或promotion evidence。

## 全书项目映射

- `existing_rule_confirmed`：金融样本非 IID、标签重叠、purge/embargo、trial count、PBO/DSR、组合协方差不稳定等已进入项目规范。
- `implementation_gap`：当前实验与 gate 仍需统一记录候选数、试验数、搜索空间变化、标签并发度、样本唯一性和多重检验风险。
- `rejected_for_now`：不因书中提供算法就自动引入 ML、量子搜索、HRP 或微观结构特征；必须有数据和基线增量证据。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Financial ML as a Distinct Subject | `2652-3812` | `L2/high` | 金融ML不是单人反复回测，而是数据治理、特征发现、经济理论、独立回测、部署和组合监督的证据生产链；低信噪比、非IID、短历史与多重试验使通用ML流程不足。 | `research_factory_and_evidence_separation_contract`：角色、输入、不可见信息、handoff、trial ledger、holdout owner、部署等价性和decommission条件显式化；任何阶段不得自行解锁promotion。 | 无定量公式；历史、组织优越性、硬件和ML能力主张不作项目证据 |
| 2 Financial Data Structures | `3813-5748` | `L2/high` | 金融样本先由PIT可见数据、事件语义和sampling operator构造；time/tick/volume/dollar、imbalance/run bar、篮子总回报、PCA权重、期货展期与CUSUM各改变时钟、可交易对象和统计分布，不能互换。 | `pit_event_bar_and_synthetic_instrument_contract`：保存release/revision、raw event、bar state/version、online threshold、basket weights/carry/cost/capacity、raw/rolled price和sample trigger；合成序列不替代各腿fill/ledger。 | `FORM-RES01-CH02-001`—`050`已由原EPUB关闭为`verified_concept_only`；代码未执行，历史统计仍不迁移 |
| 3 Labeling | `5749-6602` | `L2/high` | 标签是带起点、信息区间和终点的未来结果合同；固定期限忽略路径，triple barrier按首个profit/stop/time触达标注，meta-labeling只在外生side上学习act/pass，不能把概率直接当订单规模。 | `label_event_and_meta_model_contract`：保存event/feature time、barriers、target、side source/version、first touch、censor/tie/gap、cost、label span和split purge；Forecast与Portfolio sizing分离。 | `FORM-RES01-CH03-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码未执行，barrier参数与分类阈值不得迁移 |
| 4 Sample Weights | `6603-7947` | `L2/high` | 重叠label span共享同一批底层回报，事件数不等于独立样本数；并发度、平均唯一性、sequential bootstrap、收益/时间/class权重分别处理冗余、重要性、时变和稀有类，但不能制造IID或OOS证据。 | `non_iid_sample_weight_and_effective_sample_contract`：按训练折构造indicator/concurrency/uniqueness，记录resampling seed/probability和组合权重，报告effective sample size；测试集与实时feature禁止使用未来t1权重。 | `FORM-RES01-CH04-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码未执行，抽样/权重参数不得迁移 |
| 5 Fractionally Differentiated Features | `7948-8924` | `L2/high` | 分数差分以实数阶滤波在平稳性与历史依赖之间取舍；扩展窗会因不断加入负尾权重产生时变记忆和漂移，固定宽度FFD用同一截断权重向量提高可比性，但ADF过阈值和与原序列高相关都不证明预测力。 | `fractional_difference_training_transform_contract`：每个训练折独立选择候选d、截断阈值与窗口并冻结到验证期，保留warm-up、权重、诊断和搜索ledger；与原值、收益及简单滚动变换比较，禁止全样本选择d。 | `FORM-RES01-CH05-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码/ADF未执行，历史参数不得迁移 |
| 6 Ensemble Methods | `8925-9577` | `L2/high` | bagging只有在基学习器误差不完全相关时才降低预测方差，树/样本/特征随机化不能消除重叠标签和共同regime；OOB在金融时间依赖下易乐观，boosting对噪声与错标的迭代加权可能放大过拟合。 | `ensemble_diversity_and_validation_contract`：记录基学习器、样本/特征抽样、seed、误差相关、fold-local权重和完整trial；用purged/embargo验证、校准与简单模型基线，OOB只作训练诊断。 | `FORM-RES01-CH06-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码未执行，书中sklearn参数不得迁移 |
| 7 Cross-Validation in Finance | `9578-10634` | `L2/high` | 金融CV必须按完整信息区间而非仅样本起点切分：purge移除与测试label span相交的训练事件，embargo再隔离测试结束后的近邻训练事件；二者降低局部泄漏但不解决反复调参、测试复用和selection bias。 | `information_interval_split_and_selection_contract`：splitter接收版本化t0/t1与feature lookback/availability，明确闭区间、purge、时间/事件制embargo和fold hash；所有预处理fold-local，候选选择嵌套并由独立holdout owner控制。 | `FORM-RES01-CH07-001`—`030`已由原EPUB关闭为`verified_concept_only`；原文信息集空交式与正文/snippet矛盾，禁止照录 |
| 8 Feature Importance | `10635-11452` | `L2/high` | MDI衡量树内样本内impurity归因，MDA衡量打乱后的验证损失，SFI衡量单特征验证表现；三者分别受高基数/树偏差、相关替代与离分布置乱、交互遗漏影响，PCA一致性和跨资产stacking也不证明因果或无过拟合。 | `feature_importance_stability_and_intervention_contract`：重要性按fold、regime、asset和相关组报告，置乱保持时间/实体结构并做conditional/grouped challenger；所有选择嵌套，重要性仅生成假设，不解锁策略。 | `FORM-RES01-CH08-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码/历史图未复现，阈值不得迁移 |
| 9 Hyper-Parameter Tuning | `11453-12040` | `L2/high` | grid/random search都在验证分数上执行模型选择；purged CV只隔离单次fold信息，不能消除搜索空间、评分函数、重复运行和赢家选择造成的selection bias。log-uniform适合跨数量级采样，但边界本身仍是研究选择。 | `nested_hyperparameter_search_and_trial_ledger_contract`：预注册模型族、参数分布、预算、seed、score与tie rule；内层purged/embargo选参，外层评估完整选择流程，所有候选/失败/score访问入ledger。 | `FORM-RES01-CH09-001`—`030`已由原EPUB关闭为`verified_concept_only`；旧Pipeline/score代码未执行，搜索参数不得迁移 |
| 10 Bet Sizing | `12041-13186` | `L2/high` | 并发信号、预测概率、active-bet平均、离散化和price-divergence sigmoid都可生成归一化暴露候选，但它们混合了Forecast、Portfolio和Execution语义；概率校准、共同风险、成本、容量与约束缺失时不能称为仓位，更不能推导无损限价。 | `forecast_to_target_position_and_execution_separation_contract`：Strategy仅输出带周期/置信度的Forecast；Portfolio/Risk聚合并发观点、预算风险后产生TargetPosition；OMS独立基于市场状态、成本和保护规则生成OrderIntent。 | `FORM-RES01-CH10-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码未执行，curve、阈值与限价不得迁移 |
| 11 The Dangers of Backtesting | `13187-13856` | `L2/high` | 回测是特定历史路径下的反事实模拟，只能否证明显不可行与诊断成本/路径风险；即使PIT、成本和执行假设无误，反复试验、单一路径定向和只披露赢家仍会过拟合。CSCV/PBO量化IS赢家OOS排名衰减，但依赖完整同步trial矩阵与可分块绩效。 | `backtest_as_falsification_and_complete_trial_matrix_contract`：策略规格在回测前冻结；所有候选、失败、路径、人工选择和holdout访问写入append-only ledger；PBO/DSR仅作选择风险诊断，不覆盖数据、执行、账本或current-HEAD gate。 | `FORM-RES01-CH11-001`—`030`已由原EPUB关闭为`verified_concept_only`；原书12,780组合为source typo，代码/图未执行 |
| 12 Backtesting through Cross-Validation | `13857-14605` | `L2/high` | CPCV把N个连续group中每次选k个作test，经过purge/embargo后把测试预测重组为`φ=C(N-1,k-1)`条路径，用于观察同一冻结策略在多种训练/测试组合下的绩效分布；这些路径共享观测和模型，不能视为独立历史或消除selection bias。 | `combinatorial_path_distribution_and_dependence_contract`：预注册N/k、group/calendar、purge/embargo、path assignment和metric；报告路径相关、有效路径数、完整分布与trial adjustment，并与历史WF用途分开。 | `FORM-RES01-CH12-001`—`030`已由原EPUB关闭为`verified_concept_only`；公式/图未执行，路径不视为独立历史 |
| 13 Backtesting on Synthetic Data | `14606-16303` | `L2/high` | 章节用历史拟合的离散OU生成大量路径，在profit-taking/stop-loss网格上寻找最大Sharpe规则；它把单历史路径风险转为生成模型、参数估计、网格和Monte Carlo选择风险。合成路径可揭示规则在假设DGP下的机制与失败面，不能证明真实价格服从OU或存在唯一最优退出规则。 | `synthetic_dgp_diagnostic_and_model_risk_contract`：生成器、拟合窗口、参数不确定性、seed、path/horizon、规则网格、成本和失败面全部版本化；至少与random walk、jump/regime/heteroskedastic challenger比较，synthetic仅作diagnostic。 | `FORM-RES01-CH13-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码/热图未执行，阈值与Sharpe不得迁移 |
| 14 Backtest Statistics | `16304-17685` | `L2/high` | 回测评价应覆盖AUM/杠杆/容量、bet与turnover、ledger PnL/TWRR、收益集中、drawdown/TuW、implementation shortfall、Sharpe/PSR/DSR、分类与风险归因；任何单指标都受样本频率、serial dependence、非正态、trial count和会计定义影响。 | `performance_metric_provenance_and_selection_adjustment_contract`：每项指标绑定fills/positions/cash、return clock、benchmark、cost、sample/effective count和trial ledger；同时报告原始、非正态/依赖及选择调整结果，阈值不单独解锁gate。 | `FORM-RES01-CH14-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码/图未执行，0.95与IID年化不得迁移 |
| 15 Understanding Strategy Risk | `17686-18890` | `L2/high` | 二点收益模型把Sharpe写为命中概率p、正负payoff与独立bet频率n的函数，并由目标Sharpe反解临界precision/频率，再估计`P(p<p*)`作为策略失败敏感性；它揭示小幅命中率恶化可摧毁高频/负赔率策略，但不等同真实失败概率。 | `strategy_viability_sensitivity_and_stop_contract`：从ledger估计cost-adjusted payoff、有效独立bet、p的不确定性和regime漂移；联合PSR/DSR、尾部、相关和风险预算形成停机/复核条件，不把PM可调参数视为相互独立。 | `FORM-RES01-CH15-001`—`030`已由原EPUB关闭为`verified_concept_only`；代码/图未执行，0.05与IID频率不得迁移 |
| 16 Machine Learning Asset Allocation | `18891-20575` | `L2/high` | HRP把相关矩阵转成距离与层次树，经quasi-diagonalization和recursive bisection分配权重；它不求逆协方差，但仍依赖协方差估计、距离、linkage、窗口和离散树结构，原始算法还限定long-only/full-investment并忽略收益预测与业务约束。 | `constrained_allocation_challenger_and_tree_stability_contract`：在同一PIT universe、forecast、协方差、约束、再平衡与成本下，对比equal、IVP、HRP、shrinkage min-var及现有受约束组合，并报告树、权重与风险贡献稳定性。 | `FORM-RES01-CH16-001`—`030`已由原EPUB关闭为`verified_concept_only`；样本数主张有误，代码/MC未执行 |
| 17 Structural Breaks | `20576-22137` | `L2/high` | recursive-residual/level CUSUM与right-tail ADF、SADF、QADF/CADF和sub/super-martingale统计量可提示参数漂移或爆炸性，但结果依赖起点、窗口、trend/lag、价格变换、极值聚合、临界值和重复搜索；异常不自动等于泡沫、反转方向或alpha。 | `online_break_detection_and_strategy_invalidation_contract`：所有统计量prefix-only并保存as-of、窗口/transform、null、critical-value来源和trial lineage；break只触发risk reduction、冻结、诊断或再训练审批，不静默续用旧模型。 | `FORM-RES01-CH17-001`—`030`已由原EPUB关闭为`verified_concept_only`；Chow备择阈值有误，代码/图未执行 |
| 18 Entropy Features | `22138-23836` | `L2/high` | Shannon、plug-in与Lempel–Ziv可描述指定编码和窗口下的离散复杂性；数值由alphabet、threshold、word/match length、窗口方向、估计器与有限样本共同决定。高熵不证明有效市场，低熵不证明泡沫，熵也不能脱离单位把离散码与Gaussian differential entropy直接比较。 | `online_entropy_feature_and_encoding_provenance_contract`：所有编码边界与估计器参数在训练前缀拟合并冻结，保存symbol stream、alphabet、window/lag、units、bias/variance和baseline；只作feature/diagnostic，不自动生成方向、仓位或adverse-selection结论。 | `FORM-RES01-CH18-001`—`030`已由原EPUB关闭为`verified_concept_only`；normalized VI公式缺失，代码/图未执行 |
| 19 Microstructural Features | `23837-25339` | `L2/high` | tick rule、Roll/Parkinson/Corwin–Schultz、Kyle/Amihud/Hasbrouck、PIN/VPIN及订单事件特征分别从trade price、OHLC、signed volume、TAQ或order-book消息估计方向、spread、volatility、impact与flow imbalance；它们受数据层级、时钟、方向分类、模型假设和窗口影响，只是条件proxy，不等于真实可成交成本、知情交易概率或操纵定性。 | `microstructure_data_entitlement_and_proxy_validation_contract`：逐特征声明所需trade/quote/L2/MBO/FIX字段、venue/rule/clock、correction与ground truth；与quoted/effective spread、markout和真实order lifecycle对照，缺关键数据时保持diagnostic/blocked。 | `FORM-RES01-CH19-001`—`030`已由原EPUB关闭为`verified_concept_only`；cross-entropy为事后诊断，代码/图未执行 |
| 20 Multiprocessing and Vectorization | `25340-26320` | `L2/high` | vectorization、atom/molecule分区、异步进程池和on-the-fly reduction可改善CPU与内存利用，但只在任务独立、边界完整、归并代数正确且异常不被吞没时与串行语义等价；unordered completion、pickle、浮点归并、随机数和嵌套并行会破坏确定性。 | `partition_manifest_deterministic_map_reduce_contract`：每次运行保存atom/molecule coverage、halo/state、stable IDs、seed、worker/env、异常、reduction order和output hash；并行结果必须与单线程oracle逐项一致，禁止并发写同一文件/SQLite/latest。 | `FORM-RES01-CH20-001`—`030`已由原EPUB关闭为`verified_concept_only`；线性CPU缩放主张有误，代码未执行 |
| 21 Brute Force and Quantum Computers | `26321-26918` | `L2/high` | 多期离散组合把每期资本单位的有序弱组合、正负符号和H期Cartesian product扩成指数轨迹集，再对含forecast、covariance和transaction cost的Sharpe目标取最优；这只是离散模型内的oracle search，不能消除forecast/cost/model error。章节把qubit superposition描述成同时评估全部NP-hard解，属于不可直接迁移的硬件简化。 | `bounded_discrete_search_and_solver_claim_contract`：先冻结objective、约束、grid误差、trial budget与classical baselines；保存完整候选/失败/solver证书，量子/QUBO仅concept/rejected_for_now，不采购、不接入、不作为promotion证据。 | `FORM-RES01-CH21-001`—`030`已由原EPUB关闭为`verified_concept_only`；成本连续性与量子能力主张有误，代码未执行 |
| 22 High-Performance Computational Intelligence | `26919-27539` | `L3/high_concept_only` | MPI、HDF5、in-situ/streaming与并行I/O可在特定array/communication/workflow上降低延迟和峰值存储，但性能取决于算法、数据布局、network、virtualization与端到端任务图；2010年代HPC/cloud价格、速度和案例不能迁移。更快搜索VPIN参数或检测频谱不会自动提高统计有效性、因果识别或实时可行动性。 | `profile_first_reproducible_hpc_workflow_contract`：先profile并冻结correctness oracle、SLO、schema/lineage、retention、failure/replay和成本；比较单机/现有基础设施后才评估MPI/HDF5/in-situ，当前不采购、不迁移、不把HPC性能当研究证据。 | `FORM-RES01-CH22-001`—`030`已由原EPUB关闭为`verified_concept_only`；多数为项目派生证据指标而非书中公式，当前官方规格与本机fixture仍是任何实施前置 |

## 已完成 L2：第 1 章

### 第 1 章：研究工厂、职责分离与策略生命周期

- **论证链**：本章的稳定贡献不是“ML必胜”或某个算法，而是金融研究必须按证据生产链组织。单个研究员同时承担数据清洗、特征、策略、软件、执行模拟和回测，容易在压力下把偶然结果包装成策略；把很多单人筒仓并列也只会放大false positive和重复成本。书中提出数据curator、feature analyst、strategist、backtester、deployment和portfolio oversight等站点：特征发现不等于策略，策略需要解释谁因什么机制付钱，回测应知道候选如何被筛出并计入试验次数，部署要证明生产实现与原型逻辑等价，组合监督再按独立证据推进embargo、paper、graduation、re-allocation和decommission。该链条与本仓库的角色、worktree、handoff和gate边界一致，但书中阶段名称不能替代当前项目gate。
- **成立条件**：每项研究必须记录base commit、数据/特征/标签版本、research question、economic hypothesis、candidate/trial/search ledger、失败配置、训练/验证/holdout边界、角色与owner、可见信息集合、handoff deliverable、原型/生产语义等价检查、成本/执行假设和终止条件。数据角色对PIT、schema和lineage负责；特征角色只提交可复核diagnostic与不确定性；研究/策略角色形成Forecast或TargetPosition候选；独立验证者在不知道未来调参意图的条件下审查；部署不更改经济语义；Portfolio/Risk、OMS/Execution、Fill/Ledger和gate owner保持独立。跨角色只消费已提交且验证的不可变交付，未提交工作树文件、口头结论或共享latest路径不构成证据。
- **局限与反例**：研究“工厂化”本身不能保证发现alpha，过度分工可能造成上下文丢失、责任扩散、handoff延迟和指标博弈；小团队也不能机械复制大型机构岗位。书中关于“microscopic alpha”、ML优于人类、专有数据/软件优势、超级计算机、国家实验室模式、量子计算、行业成功率和组织范式的陈述多为作者经验或倡议，没有可迁移的比较证据。特征的黑箱发现不自动产生白箱经济机制，经济故事也可能事后拟合。保密backtest结果可减少研究者适应测试集，但若缺审计、可重复代码和独立owner，也可能掩盖错误。书中的embargo/paper/graduation只是生命周期概念，不能绕过本项目current-HEAD evidence和安全gate。
- **项目动作**：把“研究工厂”落实为现有治理而非新增组织层：候选登记后，数据准备、特征诊断、研究规格、独立回测审查、实现、证据gate按角色和worktree分离；每次handoff引用已提交commit、immutable manifest和验证结果。trial ledger记录所有候选、搜索空间变化、失败和holdout访问；backtester/gate owner只报告distribution、blockers和false flags，不替研究员继续调参。部署前做prototype-production parity、deterministic replay和ledger reconciliation；上线阶段名称全部映射为当前项目的research-only、backtest、promotion evidence、paper/live readiness，且private/order/live始终需额外明确授权。策略退役由break、drift、cost、capacity、data quality和risk breach触发，禁止静默重估后宣称仍是同一策略。
- **禁止直接采用**：不得因本章倡导ML、专有数据、HPC或分工就购买数据、引入复杂模型、扩大参数搜索、创建新agent写任务或改变promotion流程；不得把作者经验、机构案例、历史轶事、生产阶段或“工厂”隐喻称为当前项目证据。不得让feature analyst直接下单、让strategist查看独立holdout、让backtester把结果反馈为下一轮调参提示、让deployment修改策略含义或让handoff解锁paper/live。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **公式状态**：本章无需要转录的定量公式；表1.1/1.2是章节/踩坑索引。组织、历史、性能和行业主张仅作`concept_only`，未进入公式队列，也不提高后续章节证据等级。

## 已完成 L2：第 2 章

### 第 2 章：PIT数据、事件采样与合成交易对象

- **论证链**：本章先区分fundamental、market、analytics和alternative data。稳定规则是任何数据都要保留真实公开/可得时间、版本、修订和处理lineage；报告期末不等于披露时点，最终修订值不能回填首发日期。随后把bar视为从不规则事件到结构化样本的sampling operator：time bar固定日历时钟，tick/volume/dollar bar按交易活动，imbalance/run bar再用tick rule、方向量与在线预期触发不等长样本。不同bar会改变样本数、持续时间、重叠、分布和可用时点，书中“更接近IID/正态”只是待检验经验主张。多产品部分用“ETF trick”把动态权重、carry、FX、成本和再平衡映射为正的单位投资价值，并用PCA风险分布给出候选权重；单一期货则区分raw price、roll-gap-adjusted price和基于回报重建的非负指数。最后，downsampling和CUSUM只选择何时形成训练样本，不自动定义标签、方向或交易信号。
- **成立条件**：数据合同必须保存source/vendor、license/entitlement、canonical instrument、event/release/effective/available/receive/decision time、revision sequence、raw hash、schema、corporate action、trade condition、side/signing、price/size/currency和quality flags。bar manifest必须保存algorithm/version、input event range/hash、clock、threshold、tick/volume/dollar单位、OHLC/VWAP定义、auction/correction处理、partial residual、bar-open/close availability、online state/EWMA warm-up、session和deterministic replay checksum。篮子必须保存成分PIT universe、weights版本、FX/value-per-point、holdings、rebalance/roll、dividend/coupon/funding/margin、bid/ask/impact、最弱腿capacity和各腿可交易时钟；raw/rolled/total-return/synthetic price字段不得混用。CUSUM阈值、均值/波动基线与任何sample filter只能在训练可见历史拟合，并记录触发、reset、重复事件和未触发区间。
- **局限与反例**：公开时间和receive time不同，供应商可能覆盖原始值、重排历史、遗漏取消/修正或改变schema；“原始”feed也可能已聚合。time bar在低/高活动期的缺陷不意味着volume/dollar bar必然更独立，活动时钟可能把波动、流动性和自激事件内生地写入采样；不等长bar又使annualization、horizon和label span更复杂。tick rule在unchanged price、跨venue、auction、late/corrected trade和bid/ask bounce下会误签方向；EWMA warm-up和当前bar状态若不冻结会泄漏未来。imbalance/run触发不证明知情交易，可能来自拆单、做市补库或数据分片。ETF trick的正值序列会掩盖权重变化、不可同步成交、leg risk和margin；PCA权重对协方差、尺度、符号和小特征值敏感。roll-adjusted price可为负且不能用于position sizing，正值重建指数也不是可成交合约价格。CUSUM只减少阈值附近重复触发，不保证样本有预测力。
- **项目动作**：在现有数据层建立 `PITEventBarEvidence`：先保存不可变raw event/release版本，再由纯函数builder生成time/tick/volume/dollar与候选imbalance/run bars；同一事件集输出bar lineage、duration、event count、residual carry、availability和checksum。研究阶段比较bar count稳定性、serial dependence、heteroskedasticity、tail、label overlap、effective sample size和下游基线增量，禁止只挑最好结果。BTC按venue、trade condition、contract multiplier、quote/base/notional volume和24/7 regime分别构造；美股单列auction、odd-lot、off-exchange、corporate action和session。篮子/连续合约构造只为研究series和PnL attribution，Portfolio/Risk仍使用raw current prices和真实margin，OMS/Fill/Ledger仍逐腿执行与记账。所有builder增加prefix invariance、chunk-boundary、out-of-order/duplicate/correction、session reset、zero-volume、roll/corporate-action和unit-scale fixtures。
- **禁止直接采用**：不得复制书中固定bar size、EWMA长度、tick rule初值、imbalance/run阈值、PCA最小特征向量、ETF trick成本、roll方法或CUSUM的5%示例；不得把bar更接近正态称为alpha、把信息驱动命名解释为知情交易证据、把CUSUM触发当买卖信号、把合成篮子值当成交价或把rolled price用于资本占用。不得采购/处理权限不明的alternative data，不得回填修订财务、未来成分/权重、未来FX/roll或全样本协方差。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 状态**：`FORM-RES01-CH02-001`—`050`已由原EPUB正文锚点与32个公式图像、4个代码snippet、3个图示关闭为`verified_concept_only`。公式来源已核但实现仍需prefix-only、单位、边界、PIT和deterministic replay fixture；不得进入代码、参数、回测或promotion。

## Ch02 原始 EPUB 复核

- 复核范围：原 EPUB `OEBPS/text00000.html`，正文锚点 `filepos0000153985` 至 Ch03 锚点 `filepos0000229506`；39个图像资源中32个为公式/符号、4个为代码snippet、3个为图示。
- 结论边界：公式图像可直接视觉读取，已恢复imbalance/run bars、ETF trick、PCA、roll和CUSUM的符号与条件；代码只核对source semantics，未执行。所有结果仅为 `verified_concept_only`。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH02-001` | EPUB `text00000.html#filepos0000153985` §2.1-2.2 | 原始、fundamental、market、analytics与alternative数据具有不同release、revision、lineage和权限语义。 | `PITDataContract` 保存release/effective/available/receive/revision clocks。 | `verified_concept_only` |
| `FORM-RES01-CH02-002` | 同上 §2.3 | bar是从不规则market events到结构化样本的sampling operator。 | 保存input event hash、OHLC/VWAP、close availability、residual与empty-bar规则。 | `verified_concept_only` |
| `FORM-RES01-CH02-003` | 同上 §2.3.1.1 | time bar按固定日历间隔闭合，但活动不均会造成过采或欠采。 | 核验session、timezone/DST、auction与BTC 24/7边界。 | `verified_concept_only` |
| `FORM-RES01-CH02-004` | 同上 §2.3.1.2 | tick bar按累计成交笔数阈值闭合。 | 核验trade aggregation、corrections、auction print与跨venue去重。 | `verified_concept_only` |
| `FORM-RES01-CH02-005` | 同上 §2.3.1.3 | volume bar按累计交易单位阈值闭合。 | 保存share/contract/base units、multiplier和partial residual。 | `verified_concept_only` |
| `FORM-RES01-CH02-006` | 同上 §2.3.1.4；`Image00522.jpg` | dollar bar按累计成交价值闭合；固定bar size的日频数量随市场规模变化。 | 核验price×size×multiplier×FX与动态阈值PIT更新；图2.1只作历史示例。 | `verified_concept_only` |
| `FORM-RES01-CH02-007` | 同上 §2.3.2.1；`Image00529.jpg` | tick rule定义 `b_t=b_{t-1}` 当价格不变，否则为价格变化的符号。 | 保存`b_0`、event ordering、unchanged-price、auction和quote-based challenger。 | `verified_concept_only` |
| `FORM-RES01-CH02-008` | 同上；`Image00530.jpg` | tick imbalance为 `theta_T=sum_{t=1}^T b_t`。 | 核验求和边界、side sign、late correction与chunk state。 | `verified_concept_only` |
| `FORM-RES01-CH02-009` | 同上；正文紧随 `Image00530.jpg` | 期初预期tick imbalance为预期bar长度乘买卖方向概率差。 | 只用已闭合历史bar估计 `E0[T]` 与 `P[b_t=1]`。 | `verified_concept_only` |
| `FORM-RES01-CH02-010` | 同上；`Image00532.jpg` | TIB闭合时刻是最早满足实际绝对tick imbalance不小于预期绝对阈值的T。 | 核验absolute value、不等号、reset、warm-up与零预期退化。 | `verified_concept_only` |
| `FORM-RES01-CH02-011` | 同上 §2.3.2.2；`Image00534.jpg` | volume或dollar imbalance为 `theta_T=sum b_t v_t`。 | `v_t` 明确为volume或notional并保存multiplier/FX。 | `verified_concept_only` |
| `FORM-RES01-CH02-012` | 同上；`Image00535.jpg` | 预期signed flow分解为buy-side条件均值减sell-side条件均值。 | 稀有side、zero volume与条件均值在线更新需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH02-013` | 同上；`Image00690.jpg` | 无条件平均flow满足 `E0[v_t]=v_plus+v_minus`。 | 核验概率权重、units与两侧分解round-trip。 | `verified_concept_only` |
| `FORM-RES01-CH02-014` | 同上；`Image00539.jpg` | 预期imbalance可化为 `E0[T](2v_plus-E0[v_t])`。 | 核验代数、estimate window与prefix-only状态。 | `verified_concept_only` |
| `FORM-RES01-CH02-015` | 同上；`Image00540.jpg` | VIB/DIB以最早满足绝对signed flow超过预期阈值的T闭合。 | 核验动态threshold、极端trade、min/max bar与no-trigger状态。 | `verified_concept_only` |
| `FORM-RES01-CH02-016` | 同上 §2.3.2.3；`Image00542.jpg` | tick-runs统计buy tick count与sell tick count两者较大值。 | 它不是最长连续run；核验tie与side定义。 | `verified_concept_only` |
| `FORM-RES01-CH02-017` | 同上；`Image00545.jpg` | 预期tick-run量为预期bar长度乘两侧方向概率较大值。 | 核验EWMA、probability normalization与0/1边界。 | `verified_concept_only` |
| `FORM-RES01-CH02-018` | 同上；`Image00547.jpg` | TRB在实际run count达到预期run threshold时闭合。 | 保存reset、warm-up、split-order challenger与deterministic replay。 | `verified_concept_only` |
| `FORM-RES01-CH02-019` | 同上 §2.3.2.4；`Image00548.jpg` | volume/dollar runs取buy-side累计flow与sell-side累计flow的较大值。 | 核验side sums、quantity units与event ordering。 | `verified_concept_only` |
| `FORM-RES01-CH02-020` | 同上；`Image00551.jpg` | 预期run flow为预期bar长度乘两侧概率加权条件flow的较大值。 | 保存side probability、conditional mean与估计版本。 | `verified_concept_only` |
| `FORM-RES01-CH02-021` | 同上；`Image00200.jpg` | VRB/DRB闭合时刻是最早达到预期最大侧flow阈值的T。 | 核验arg-min、max、absolute/side semantics与不稳定极端状态。 | `verified_concept_only` |
| `FORM-RES01-CH02-022` | 同上 §2.4.1；`Image00554.jpg` | ETF holdings在rebalance时由allocation、当前K、roll-open/value-per-point及gross allocation normalization决定，否则沿用前值。 | 保存weights vintage、roll open、FX、lot rounding、gross normalization与clock。 | `verified_concept_only` |
| `FORM-RES01-CH02-023` | 同上；`Image00291.jpg` | price increment在前一时点属于rebalance set时使用当前price减roll open，否则使用普通price change。 | 核验`t-1 in B`、old/new contract、open/close和direction。 | `verified_concept_only` |
| `FORM-RES01-CH02-024` | 同上；`Image00557.jpg` | 单位投资价值递推为前值加各腿先前holdings乘value-per-point及price increment与dividend之和。 | 必须与逐腿cash/position/fill ledger round-trip。 | `verified_concept_only` |
| `FORM-RES01-CH02-025` | 同上；`Image00559.jpg` | gross allocation normalization因子为allocation除绝对allocation总和。 | 零gross exposure、sign与leverage semantics需显式。 | `verified_concept_only` |
| `FORM-RES01-CH02-026` | 同上；`Image00561.jpg` | rebalance cost由旧holdings按price与新holdings按roll-open计算的绝对notional乘value-per-point和交易成本率求和。 | 核验双边、nonlinear impact、short方向与重复计费。 | `verified_concept_only` |
| `FORM-RES01-CH02-027` | 同上；`Image00562.jpg` | `{c_tilde}` 表示虚拟ETF单位交易成本序列。 | notation必须绑定currency、timestamp和cost model version。 | `verified_concept_only` |
| `FORM-RES01-CH02-028` | 同上；`Image00565.jpg` | 虚拟ETF bid-ask成本由旧holdings绝对notional乘value-per-point和cost rate求和。 | 不得把该线性近似替代真实逐腿spread/impact。 | `verified_concept_only` |
| `FORM-RES01-CH02-029` | 同上；`Image00567.jpg` | `c_tilde_t` 是虚拟ETF单位买卖成本标量。 | 与rebalance cost `c_t` 分字段，禁止混名。 | `verified_concept_only` |
| `FORM-RES01-CH02-030` | 同上；`Image00570.jpg` | 可交易篮子单位受 `min_i(v_i,t / abs(h_i,t-1))` 的最弱腿约束。 | volume不等于capacity；另加participation、depth、latency与leg risk。 | `verified_concept_only` |
| `FORM-RES01-CH02-031` | 同上 §2.4.2；`Image00043.jpg` | 组合方差在PCA基中满足 `sigma^2=omega'Vomega=beta'Lambda beta`。 | 核验PSD、eigen ordering、basis projection、units和training window。 | `verified_concept_only` |
| `FORM-RES01-CH02-032` | 同上；`Image00574.jpg` | PCA风险分解为 `sigma^2=sum beta_n^2 Lambda_nn`。 | small eigenvalue、rank与估计误差必须留证。 | `verified_concept_only` |
| `FORM-RES01-CH02-033` | 同上；`Image00575.jpg` | 给定目标风险分布R时正交载荷取 `beta_n=sigma sqrt(R_n/Lambda_nn)`。 | 核验平方根、符号非识别、normalization与极端杠杆。 | `verified_concept_only` |
| `FORM-RES01-CH02-034` | 同上；`Image00405.jpg` | 练习以 `omega_hat_t` 表示随时间估计的篮子allocation向量。 | 必须保存estimation window、as-of time与FX/roll inputs。 | `verified_concept_only` |
| `FORM-RES01-CH02-035` | 同上；`Image00576.jpg` | 图2.2比较inverse-variance与指定PCA risk distribution的component risk贡献。 | 图示不是当前数据上的稳定性、收益或最优性证据。 | `verified_concept_only` |
| `FORM-RES01-CH02-036` | 同上；`Image00579.jpg` | Snippet 2.1按eigendecomposition、目标risk distribution和risk target构造PCA weights。 | 仅核对源码语义；未执行、未验证约束或数值稳定性。 | `verified_concept_only` |
| `FORM-RES01-CH02-037` | 同上 §2.4.3；`Image00581.jpg` | Snippet 2.2构造roll gaps并从价格扣除以形成forward/backward adjusted series。 | 核验roll timestamp、open/close、direction与PnL invariance。 | `verified_concept_only` |
| `FORM-RES01-CH02-038` | 同上；`Image00099.jpg` | Snippet 2.3用rolled price change除以前一期raw price形成return并连乘为非负指数。 | raw price仍用于position sizing/capital；合成指数不是成交价。 | `verified_concept_only` |
| `FORM-RES01-CH02-039` | 同上 §2.5.2.1；`Image00584.jpg` | one-sided CUSUM递推 `S_t=max(0,S_{t-1}+y_t-E_{t-1}[y_t])`。 | 保存baseline fit、initial state、threshold units和prefix invariance。 | `verified_concept_only` |
| `FORM-RES01-CH02-040` | 同上；`Image00116.jpg` | CUSUM越阈值等价于存在某个reset后区间累计偏离达到h。 | 核验existential interval、absolute/one-sided semantics与clock。 | `verified_concept_only` |
| `FORM-RES01-CH02-041` | 同上；`Image00224.jpg` | negative CUSUM递推使用 `min(0,S^-_{t-1}+y_t-E_{t-1}[y_t])` 且初值0。 | 核验sign、reset与negative threshold comparison。 | `verified_concept_only` |
| `FORM-RES01-CH02-042` | 同上；`Image00587.jpg` | symmetric CUSUM的positive branch与one-sided递推一致。 | 两侧状态独立维护，任一触发后reset规则需版本化。 | `verified_concept_only` |
| `FORM-RES01-CH02-043` | 同上；`Image00590.jpg` | 书中以 `S_t=max(S_t^+,-S_t^-)` 汇总两侧偏离幅度。 | 不得把统计量符号解释为买卖方向。 | `verified_concept_only` |
| `FORM-RES01-CH02-044` | 同上；`Image00315.jpg` | Snippet 2.4实现symmetric CUSUM event filter并返回触发时间。 | 仅作source-verified概念；需边界、重复触发、missing和chunk fixtures。 | `verified_concept_only` |
| `FORM-RES01-CH02-045` | 同上；`Image00595.jpg` | 图2.3展示CUSUM样本时点相对原价格序列的稀疏化。 | 图示不证明预测力、IID、收益或合适阈值。 | `verified_concept_only` |
| `FORM-RES01-CH02-046` | 同上 §2.4.3 | rolled prices用于PnL simulation与mark-to-market，raw prices用于position sizing和capital consumption。 | 数据字段、units与用途必须隔离。 | `verified_concept_only` |
| `FORM-RES01-CH02-047` | 同上 §2.4.3 | forward/backward roll只决定锚定端点，不消除carry、basis或合约切换风险。 | 保存roll rule、calendar、liquidity switch和basis attribution。 | `verified_concept_only` |
| `FORM-RES01-CH02-048` | 同上 §2.5.1 | uniform downsampling与event-based sampling定义不同观测集合。 | 保存selection probability、seed/rule、coverage及与label span交互。 | `verified_concept_only` |
| `FORM-RES01-CH02-049` | 同上 §2.5.2 | CUSUM在本章只决定何时采样feature，不定义label、side或OrderIntent。 | Strategy、Portfolio/Risk与OMS边界保持独立。 | `verified_concept_only` |
| `FORM-RES01-CH02-050` | 同上全章 | bar、ETF、PCA、roll和CUSUM的历史公式均需当前数据、成本、容量与PIT fixture后方可实施。 | 本章只关闭为concept_only，不构成代码、参数、回测或promotion许可。 | `verified_concept_only` |

## 已完成 L2：第 3 章

### 第 3 章：标签事件、路径触达与meta-model边界

- **论证链**：监督学习要求每个feature event对应一个未来结果，但标签不是客观真值，而是由sampling、horizon、barrier、side、成本和可得价格共同定义的实验对象。固定horizon方法在第h个bar比较回报与固定阈值，既混淆不同bar duration和波动状态，也忽略期间是否先触发风险止损。动态阈值用当时可见的滚动波动缩放目标；triple barrier再设置profit-taking、stop-loss和vertical expiration，以首个触达决定事件终点和标签，因此每个样本的信息区间是从feature time到first touch。若没有外生方向，水平barrier需对称并让模型学习side；若已有primary model提供side，meta-labeling把收益按side重定向并学习`act/pass`，二级模型不是新的机会生成器。分类precision、recall、ROC和F1只是统计评价，是否交易及多少风险仍取决于经济成本和组合预算。
- **成立条件**：`LabelEventEvidence` 必须保存event_id、feature/decision/available time、price source、bar type/version、t0、vertical t1、profit/stop multiplier、volatility target及其fit window/version、side及source/model version、first-touch timestamp/type、realized return、cost-adjusted return、label、censor reason、gap/tie/intrabar ambiguity和label span。feature只可使用t0时可见信息；volatility、threshold、class transform和rare-label policy只在训练折拟合。若label span重叠，split必须purge相交训练事件并对边界加embargo。primary side、secondary act probability、Forecast confidence、Portfolio target和最终OrderIntent分字段存储，不允许概率直接穿透为数量。标签生成必须prefix-invariant、deterministic、跨分区一致，并保留所有未触发、缺价和被过滤事件。
- **局限与反例**：bar-level close/high/low通常不能识别同一bar内profit与stop谁先触达，gap可能同时越过barrier，snapshot或收盘价格也不保证可成交；若用未来实现波动、全样本EWMA或最终修订价格设置target，会产生泄漏。固定bar数量的vertical barrier在time、volume和event bars上代表不同日历时间；calendar-day搜索又受周末、停牌、24/7和session影响。标签barrier不是实际止损/止盈订单，未包含spread、fee、impact、latency、partial fill、price protection和margin call时不能声称可执行。meta-labeling不会天然限制过拟合，也不能证明primary side有效；同一训练集反复构造primary与secondary、选择barrier和阈值仍会泄漏/多重试验。按全样本频率递归删除rare labels会改变目标总体、抹去尾部风险并使不同折标签空间不一致。书中用睡眠、心理或生物信息评估人员的设想涉及隐私、劳动和合规风险，当前项目不采集或使用。
- **项目动作**：先把标签实现为独立、版本化、只读builder，而非策略代码的一部分。为每种候选同时保留fixed-horizon基线、对称triple-barrier和必要时的meta-label；用合成路径fixture覆盖profit-first、stop-first、vertical-first、gap、同bar双触达、missing price、zero volatility、无barrier、非对称barrier和side反转。所有事件输出t0/t1 span供purged CV与sample uniqueness使用；barrier width加入保守成本但不替代execution simulator。评估primary与secondary时分别报告coverage、class balance、precision/recall/F1、calibration、abstention、经济损失和按side/regime稳定性，并把threshold/label variant计入trial ledger。二级概率只形成Forecast置信度，Portfolio/Risk再基于风险预算、相关性、容量和成本生成TargetPosition；OMS独立决定是否以及如何执行。
- **禁止直接采用**：不得复制书中EWMA span、1日vertical barrier、`ptSl=[1,1]`、`[1,2]`、`[0,2]`、`minRet`、rare-label比例、随机森林或F1阈值；不得用全样本波动、未来bar、最终修订数据或测试集class distribution生成标签。不得把first touch当真实fill、把stop label当实际止损成交、把meta-label 1当OrderIntent、把classification probability直接映射杠杆或让secondary修正primary方向。不得因类别稀少静默删除tail/failure label，也不得使用员工生物/心理数据。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 状态**：`FORM-RES01-CH03-001`—`030`已由原EPUB跨文件正文与11个公式/符号、8个代码snippet、2个图示关闭为`verified_concept_only`。代码未执行，仍需路径顺序、gap、同bar双触达、timezone/session、label-overlap、cost和prefix-only fixture；不得进入参数、回测或promotion。

## Ch03 原始 EPUB 复核

- 复核范围：Ch03正文从 `OEBPS/text00000.html#filepos0000229506` 跨文件延续至 `OEBPS/text00001.html#filepos0000279229`；共21个图像资源，其中11个公式/符号、8个代码snippet、2个图示。
- 结论边界：fixed-horizon、dynamic target、triple barrier、first-touch、meta-labeling与rare-label处理均已回到原EPUB核对；代码只核对source semantics，未执行。全部结果仅为 `verified_concept_only`。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH03-001` | EPUB `text00000.html#filepos0000229506` §3.1 | 监督学习把feature event X与未来label/value y按event_id对应。 | 保存event_id、feature/available time、label version；禁止按行号隐式对齐。 | `verified_concept_only` |
| `FORM-RES01-CH03-002` | 同上 §3.2；`Image00188.jpg`、`Image00602.jpg` | 固定horizon return为 `P(t0+h)/P(t0)-1`。 | 保存起止index、price type、bar duration、corporate action与execution lag。 | `verified_concept_only` |
| `FORM-RES01-CH03-003` | 同上；`Image00599.jpg` | return相对正负threshold tau映射为 `{-1,0,1}`。 | 核验严格不等号、zero band、threshold units、cost与missing endpoint。 | `verified_concept_only` |
| `FORM-RES01-CH03-004` | 同上 §3.2 | 固定bar数h在不同bar类型和活动状态下不代表同一日历时间或风险。 | 分开calendar/event/bar horizon并保存实际duration与label span。 | `verified_concept_only` |
| `FORM-RES01-CH03-005` | 同上 §3.3；`Image00610.jpg`、`Image00733.jpg`、`Image00614.jpg` | barrier target应由当时可见的滚动volatility缩放；固定tau可能相对sigma过大或过小。 | 保存fit window、span/adjust、lag、annualization、warm-up与as-of time。 | `verified_concept_only` |
| `FORM-RES01-CH03-006` | 同上；`Image00615.jpg` | Snippet 3.1用前一日对齐return和EWMA standard deviation估计daily volatility。 | 核验searchback、timezone/session、weekend、24/7、missing与prefix-only。 | `verified_concept_only` |
| `FORM-RES01-CH03-007` | 同上 §3.4 | upper/lower horizontal barriers由target乘profit-taking与stop-loss multipliers定义。 | 核验long/short、非对称、0禁用、return convention、cost与gap。 | `verified_concept_only` |
| `FORM-RES01-CH03-008` | 跨 `text00000`/`text00001`；`Image00625.jpg` | vertical barrier取指定calendar horizon后首个可用price timestamp。 | 核验searchsorted direction、session、停牌/周末、末尾NaT与无vertical配置。 | `verified_concept_only` |
| `FORM-RES01-CH03-009` | 同上；`Image00619.jpg`、`Image00624.jpg` | first-touch time取profit、stop与vertical有效触达时间的最早值。 | 验证同bar双触达、tie priority、gap、missing、sorted index与parallel merge。 | `verified_concept_only` |
| `FORM-RES01-CH03-010` | 同上；`Image00618.jpg` | event return从t0计算至实际first-touch t1。 | 核验price source、side、first executable price、fees/impact与censor return。 | `verified_concept_only` |
| `FORM-RES01-CH03-011` | 同上；`Image00337.jpg` | 已知side时barrier return按side重定向，profit与stop可非对称。 | side必须t0已知并绑定primary model version；short return符号需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH03-012` | 同上 §3.4 | profit-taking、stop-loss与vertical三个开关形成不同barrier configurations。 | 版本化active flags；无终止与仅单侧配置需显式censor/failure。 | `verified_concept_only` |
| `FORM-RES01-CH03-013` | 同上；`Image00621.jpg` | 图3.1展示lower-horizontal-first与vertical-first两种不同路径结果。 | 图示只证明路径依赖；OHLC不能识别intrabar顺序时标记ambiguous。 | `verified_concept_only` |
| `FORM-RES01-CH03-014` | 同上；`Image00619.jpg`、`Image00624.jpg` | label builder输入close、events、target、pt/sl和并行molecule并聚合最早触达。 | 核验schema、timezone、duplicates、NaN、partition与deterministic merge。 | `verified_concept_only` |
| `FORM-RES01-CH03-015` | 同上；`Image00337.jpg` | `minRet`先过滤target过小的events，再执行barrier search。 | threshold仅训练折拟合；保存被滤事件、selection bias与零/负target。 | `verified_concept_only` |
| `FORM-RES01-CH03-016` | 同上；`Image00624.jpg` | 未知side时使用对称horizontal barriers并由return sign学习方向。 | 成本不一定对称；核验side placeholder和class解释。 | `verified_concept_only` |
| `FORM-RES01-CH03-017` | 同上；`Image00625.jpg` | vertical timestamp由event time加numDays后在close index中搜索首个位置。 | 核验exact match、search side、末尾censor与calendar semantics。 | `verified_concept_only` |
| `FORM-RES01-CH03-018` | 同上；`Image00628.jpg` | side-learning `bin` 为first-touch realized return的符号。 | 核验zero/tolerance、vertical-first、cost-adjusted return与NaN policy。 | `verified_concept_only` |
| `FORM-RES01-CH03-019` | 同上 §3.5；`Image00621.jpg` | vertical-first可使用return sign或单独编码0，两种expiration-label policies不同。 | 预注册policy并计入trial ledger；不得按OOS结果选择。 | `verified_concept_only` |
| `FORM-RES01-CH03-020` | 同上 §3.6；`Image00337.jpg`、`Image00633.jpg` | meta-labeling把realized return乘primary side后再判定结果。 | side在t0必须可见；primary/secondary版本和cashflow方向分别保存。 | `verified_concept_only` |
| `FORM-RES01-CH03-021` | 同上；`Image00633.jpg` | meta-label将side-adjusted return小于等于0映射为0，其余为1。 | 核验zero、cost threshold、abstain semantics与class balance。 | `verified_concept_only` |
| `FORM-RES01-CH03-022` | 同上 §3.6-3.7 | secondary positive probability表达act/pass confidence，不直接等于position size。 | 需OOS calibration；只输出Forecast，Portfolio/Risk另定target与cap。 | `verified_concept_only` |
| `FORM-RES01-CH03-023` | 同上；`Image00637.jpg` | confusion matrix区分TP、TN、FP、FN。 | 定义positive class、threshold、weights、overlap、fold aggregation与economic cost。 | `verified_concept_only` |
| `FORM-RES01-CH03-024` | 同上 §3.7 | precision为TP占全部predicted positives的比例。 | 核验zero predicted positives、sample weights、CI与prevalence sensitivity。 | `verified_concept_only` |
| `FORM-RES01-CH03-025` | 同上 §3.7 | recall为TP占全部actual positives的比例。 | 核验zero positives、weights、CI、coverage与abstention。 | `verified_concept_only` |
| `FORM-RES01-CH03-026` | 同上 §3.7 | F1是precision与recall的harmonic mean。 | 核验zero division；F1不含PnL、size、cost或tail loss。 | `verified_concept_only` |
| `FORM-RES01-CH03-027` | 同上 §3.7 | ROC描述提高TPR时接受FPR的threshold trade-off。 | threshold只在validation选择，并报告PR、calibration、cost与trial count。 | `verified_concept_only` |
| `FORM-RES01-CH03-028` | 同上 §3.9；`Image00640.jpg` | Snippet 3.8递归删除频率低于minPct的class，直到满足阈值或只剩两类。 | 仅训练折执行；保留tail/failure类审计与class-weight baseline。 | `verified_concept_only` |
| `FORM-RES01-CH03-029` | 同上 §3.4-3.6 | first-touch产生可变且重叠的t0/t1 label spans。 | 输出span供purge、embargo、uniqueness与sample weights；禁止仅按t0切分。 | `verified_concept_only` |
| `FORM-RES01-CH03-030` | 同上全章 | 标签证据必须同时包含PIT target、路径顺序、side、成本、censor、版本与Forecast/size分层。 | 本章只关闭为concept_only；代码未执行，不构成回测、实现或promotion许可。 | `verified_concept_only` |

## 已完成 L2：第 4 章

### 第 4 章：标签并发、平均唯一性与训练权重分层

- **论证链**：当事件`i`的label span尚未结束而事件`j`已开始，两者共同依赖重叠区间的底层回报，因此标签不是IID。强制不重叠会把feature sampling频率限制在最长horizon并丢失大量信息，正确做法是显式记录每个事件影响哪些bar。indicator matrix按bar×event标记覆盖，逐bar并发数是同时依赖该回报的label数量；事件在某bar的唯一性为并发数倒数，事件平均唯一性是其完整span上的平均。标准bootstrap在高度重叠样本上会反复抽到近似信息并污染out-of-bag评估；sequential bootstrap根据当前已抽样集合重新计算每个候选的边际平均唯一性，再按归一化概率抽取。后续训练权重可叠加独特回报归因、基于累计唯一性的时间衰减和类别权重，但三者目标不同，不能混成“样本重要性”单值而失去审计。
- **成立条件**：`NonIIDSampleWeightEvidence` 必须从版本化`t0/t1`和底层bar index构造indicator matrix，明确区间闭合、起止bar、timezone、missing/censored t1、分区边界和事件筛选。每个训练fold独立计算concurrency、average uniqueness、sample weight、decay和class weight；验证/test事件不得参与训练权重、bootstrap概率或class-frequency估计。sequential bootstrap保存seed、draw sequence、每步candidate uniqueness/probability、replacement、sample length和deterministic merge。最终fit weight拆分为`uniqueness_weight`、`return_weight`、`time_decay_weight`、`class_weight`及归一化结果，并报告sum、min/max、零权重、top concentration、Kish或等价effective sample size、unique event count和span coverage。
- **局限与反例**：平均唯一性在已知完整t1后才能计算，因此只能作为训练标签附属信息，不能成为实时feature或测试预测输入。它只量化时间覆盖重叠，不处理共同因子、同一发行人、跨资产相关、相同特征工程或重复经济假说；唯一性1也不保证独立。sequential bootstrap允许重复和重叠，只是模型内提高平均唯一性；书中随机span的Monte Carlo及0.6/0.7结果不能证明真实数据上泛化、无偏OOB或更高收益。按绝对回报加权会放大跳点、坏价、极端波动和难成交事件，也可能让模型追逐尾部而非稳定条件；删除neutral label不是普遍正确。时间衰减参数会静默改变有效样本历史，负值甚至删除最旧样本；结构变化不一定单调随时间。class balancing改变目标先验和regularization，稀有危机类更高权重不代表其概率或经济成本估计准确。
- **项目动作**：将`t0/t1` indicator、concurrency和uniqueness作为实验构建产物，并在manifest记录hash与fold。所有模型先报告无权重、仅uniqueness、uniqueness+class、可选time-decay的消融；return attribution只作为独立challenger并经过bad-tick/winsorization、cost和tail稳定性测试。bootstrap模型比较standard、sample-fraction-capped和sequential版本，使用相同base estimator、seed budget与purged CV，评价不仅看accuracy，还看calibration、effective sample size、OOS dispersion、turnover和成本。时间衰减通过预注册candidate和validation选择，不据holdout调整；结构break应由独立检测器触发再训练/退役，而非只靠衰减掩盖。权重计算增加single event、完全重叠、部分重叠、nested span、相邻边界、NaT、duplicate event、partition、seed replay和weight normalization fixture。
- **禁止直接采用**：不得复制书中`max_samples=mean uniqueness`、顺序bootstrap样本长度、Monte Carlo参数、absolute-return权重、线性decay参数、`balanced`或`balanced_subsample`默认值；不得用全样本t1、class frequency或future return计算训练fold权重。不得把bar数、事件数、交易数或bootstrap draws称为独立bet数，不得把较高average uniqueness称为IID、无泄漏或更高OOS收益，也不得用OOB accuracy替代purged validation。不得把未来t1派生权重传入实时Strategy/Forecast；当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 原文概念复核完成**：`FORM-RES01-CH04-001`—`030`已回到原EPUB核对；只关闭source semantics为`verified_concept_only`，未执行snippet、fixture或项目实现。

## Ch04 原始 EPUB 复核

- 复核范围：Ch04正文位于 `OEBPS/text00001.html#filepos0000279229` 至下一章 `#filepos0000329259`，共51个图像资源，其中37个公式/符号/矩阵、11个代码snippet、3个图示/结果图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。overlap、indicator、concurrency、uniqueness、bootstrap、return attribution、time decay与class-weight正文均已逐项对图核验。
- 结论边界：以下只确认书中公式和代码的概念语义；代码未执行，sklearn历史接口/bug、数值结果与默认参数未验证，全部状态仅为 `verified_concept_only`。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH04-001` | EPUB `text00001.html#filepos0000279229` §4.2；`Image00644.jpg` | 若后发事件在先发事件结束前开始，两标签共同依赖区间 `[t_j,0,min(t_i,1,t_j,1)]` 的底层return，因此不独立。 | 版本化t0/t1与return interval；测试相邻、部分、完全及nested span。 | `verified_concept_only` |
| `FORM-RES01-CH04-002` | 同上 §4.3；`Image00112.jpg` | `1_{t,i}`仅在事件span与return interval `[t-1,t]`重叠时取1。 | 明确闭区间、bar endpoint、timezone、NaT和partition语义。 | `verified_concept_only` |
| `FORM-RES01-CH04-003` | 同上；`Image00672.jpg` | 每个bar的并发标签数为 `c_t=sum_i 1_{t,i}`。 | 保存axis、零并发、duplicate event与integer overflow测试。 | `verified_concept_only` |
| `FORM-RES01-CH04-004` | 同上 §4.4 | 事件i在bar t的pointwise uniqueness为 `u_{t,i}=1_{t,i}/c_t`。 | 非覆盖bar不得参与；显式防止0/0并验证范围 `[0,1]`。 | `verified_concept_only` |
| `FORM-RES01-CH04-005` | 同上；`Image00698.jpg` | 平均唯一性为事件span内 `u_{t,i}`之和除以该事件覆盖bar数。 | 核验分母、inclusive endpoints、irregular bars和missing span。 | `verified_concept_only` |
| `FORM-RES01-CH04-006` | 同上 §4.4；`Image00732.jpg` | 平均唯一性可解释为事件span内并发度调和平均的倒数。 | 仅在有效覆盖bar和正并发度上验证等价；不外推为IID。 | `verified_concept_only` |
| `FORM-RES01-CH04-007` | 同上 §4.5；`Image00807.jpg` | I个item有放回抽I次时，特定item未被抽中概率 `(1-I^-1)^I` 趋于 `e^-1`。 | 同时报告有限I值与极限；unique draw不等于独立信息。 | `verified_concept_only` |
| `FORM-RES01-CH04-008` | 同上；`Image00824.jpg` | 标准bootstrap预期抽到的unique observations比例趋于 `1-e^-1≈2/3`。 | 核验draw count与population size；不得据此估计独立bet数。 | `verified_concept_only` |
| `FORM-RES01-CH04-009` | 同上；`Image00499.jpg`、`Image00601.jpg` | 若最多K个非重叠结果，未抽中概率近似 `e^{-K/I}`，unique比例上界不超过IID情形。 | K仅为理想化容量；需用真实overlap结构和ESS challenger。 | `verified_concept_only` |
| `FORM-RES01-CH04-010` | 同上 §4.5 | 书中建议用mean uniqueness限制bagging的`max_samples`。 | 仅作预注册challenger；按训练fold计算并比较邻域与简单基线。 | `verified_concept_only` |
| `FORM-RES01-CH04-011` | 同上 §4.5.1 | sequential bootstrap首次draw对I个事件使用均匀概率 `1/I`。 | 保存候选集、replacement、seed、sample length与空集合处理。 | `verified_concept_only` |
| `FORM-RES01-CH04-012` | 同上；`Image00160.jpg`、`Image00191.jpg` | 给定已抽序列phi，加入候选j后以新并发度计算其条件pointwise与平均唯一性。 | 对重复、自身完全重叠、无重叠及all-identical候选建fixture。 | `verified_concept_only` |
| `FORM-RES01-CH04-013` | 同上；`Image00165.jpg`、`Image00135.jpg` | 下一draw概率为各候选条件平均唯一性除以候选总和，且概率和为1。 | 验证非负、all-zero、tie、浮点归一化和稳定排序。 | `verified_concept_only` |
| `FORM-RES01-CH04-014` | 同上；`Image00153.jpg` | 每次draw后更新phi并重算概率，直到达到预设sample length。 | 持久化每步draw/probability；验证replacement、determinism与early stop。 | `verified_concept_only` |
| `FORM-RES01-CH04-015` | 同上 §4.5.2；`Image00170.jpg` | Snippet 4.3由bar index与t1构造bar×event indicator matrix。 | 核验sorted index、duplicates、NaT、inclusive slicing、chunk边界与内存。 | `verified_concept_only` |
| `FORM-RES01-CH04-016` | 同上；`Image00629.jpg` | Snippet 4.4按行求concurrency、逐列相除，再对非零覆盖bar求事件平均唯一性。 | 与直接区间算法交叉；稀疏/稠密表示、axis和NaN必须一致。 | `verified_concept_only` |
| `FORM-RES01-CH04-017` | 同上；`Image00706.jpg` | Snippet 4.5允许sample length独立于事件数且可重复抽同一列。 | 预声明sLength并报告unique count、repeat concentration与ESS。 | `verified_concept_only` |
| `FORM-RES01-CH04-018` | 同上 §4.5.3；`Image00183.jpg`—`Image00199.jpg` | 三事件示例从均匀 `1/3` 开始；首抽事件2后，第二draw概率为 `{5/14,3/14,6/14}`。 | 将indicator、每步candidate uniqueness和归一化概率固化为手算fixture。 | `verified_concept_only` |
| `FORM-RES01-CH04-019` | 同上 §4.5.4；`Image00203.jpg` | Monte Carlo示例随机生成event start与span，形成随机t1。 | 参数、分布与seed只属实验设置；记录censor与off-by-one。 | `verified_concept_only` |
| `FORM-RES01-CH04-020` | 同上；`Image00356.jpg`、`Image00377.jpg`、`Image00392.jpg` | 书中以重复模拟比较standard与sequential bootstrap的average uniqueness分布。 | 书中0.6/0.7、ANOVA和运行时不迁移；真实评估需CI、effect size与OOS指标。 | `verified_concept_only` |
| `FORM-RES01-CH04-021` | 同上 §4.6；`Image00410.jpg` | 事件原始权重是其span内按并发度分摊的log return之和的绝对值。 | 核验log-return price、bad ticks、absolute位置、cost、tail和零权重。 | `verified_concept_only` |
| `FORM-RES01-CH04-022` | 同上；`Image00220.jpg`、`Image00656.jpg` | 归一化权重 `w_i=tilde_w_i/sum_j tilde_w_j` 后再缩放，使总和等于事件数I。 | 明确归一化约定、zero sum、fold-local I及与其他weight乘积次序。 | `verified_concept_only` |
| `FORM-RES01-CH04-023` | 同上；`Image00115.jpg` | Snippet 4.10实现absolute-return attribution；正文指出neutral label与该单调权重语义冲突。 | 不自动删除0类；比较cost-aware、class weight和tail-preserving方案。 | `verified_concept_only` |
| `FORM-RES01-CH04-024` | 同上 §4.7；`Image00119.jpg`—`Image00143.jpg` | decay的时间轴是按事件排序后的累计平均唯一性，而非日历时间。 | 保存排序、tie、cumulative uniqueness与fold isolation；不得引入未来fold。 | `verified_concept_only` |
| `FORM-RES01-CH04-025` | 同上；`Image00134.jpg`、`Image00137.jpg` | 当 `c∈[0,1]`，线性函数令最新权重1、最旧权重c，斜率为 `(1-c)/sum_i bar_u_i`。 | 核验c边界、x方向、weight product与数值范围。 | `verified_concept_only` |
| `FORM-RES01-CH04-026` | 同上；`Image00140.jpg`、`Image00147.jpg` | 当 `c∈(-1,0)`，斜率为 `1/((c+1)sum_i bar_u_i)`，负值截为0，删除最旧部分。 | 验证zero crossing、截断比例和结构break基线；参数不得从holdout选择。 | `verified_concept_only` |
| `FORM-RES01-CH04-027` | 同上 §4.8 | class weight通过提高稀有label误分类代价改变训练目标。 | 保存class prior、cost matrix、regularization interaction、calibration与tail语义。 | `verified_concept_only` |
| `FORM-RES01-CH04-028` | 同上 §4.8 | `balanced`按训练集频率，`balanced_subsample`按各in-bag样本频率重加权；总权重尺度还会影响regularization。 | 绑定library/version并只在训练fold计算；比较无权重与显式成本基线。 | `verified_concept_only` |
| `FORM-RES01-CH04-029` | 同上 §4.4；`Image00750.jpg`—`Image00788.jpg` | average uniqueness依赖未来t1，只能与label一起用于训练集，不能用于testing forecast feature。 | fit/transform隔离；验证test events不参与weight或bootstrap probability。 | `verified_concept_only` |
| `FORM-RES01-CH04-030` | 同上全章 | 非IID权重证据需同时保存span、indicator、concurrency、uniqueness、抽样轨迹、权重分量与ESS。 | 本章只关闭原文概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 5 章

### 第 5 章：分数差分、平稳性诊断与训练期变换边界

- **论证链**：整数差分把价格变为收益，通常更容易满足弱平稳假设，但也可能移除对预测有用的低频依赖；保留level则可能留下单位根或爆炸性行为。分数差分把差分阶数`d`从整数扩展到实数，通过广义二项式权重将当前值与一条逐渐衰减的历史尾部卷积：`d=0`保留原序列，`d=1`退化为一阶差分，`0<d<1`提供中间变换。有限样本无法使用无限权重。标准扩展窗随时间使用不同长度的权重向量，早晚样本拥有不同记忆，并因持续加入负权重产生明显负漂移；固定宽度FFD在权重模低于阈值后截断，对所有可计算时点使用同一向量，减少该机械漂移。书中再沿候选`d`计算ADF统计量并选择首次越过临界值的最小`d*`，同时用与原序列相关性描述“记忆保留”。这只能形成候选特征工程，不等于alpha或完整平稳性证明。
- **成立条件**：`FractionalDifferenceEvidence`必须保存input series与单位、价格/log-price/累计序列语义、event/available time、fit interval、candidate d grid、每次试验、权重递推版本、threshold定义、截断宽度、warm-up/drop规则、missing/inf处理、输出available time和transform hash。`d`、阈值、窗口及ADF lag/trend/specification只在训练折选择；验证、测试和实时期使用冻结参数并仅消费前缀数据。平稳性至少联合报告ADF设定与p-value、KPSS或等价互补诊断、均值/方差/自相关稳定性、结构break和分段结果；相关性只作为变换距离指标，不命名为memory或predictive power。不同资产、字段、频率和regime分别拟合并计入trial ledger，不把一个期货示例的`d`迁移到BTC或美股。
- **局限与反例**：ADF拒绝单位根不等于序列在所有矩上平稳，也可能受lag、deterministic trend、结构突变、异方差、样本长度和重复搜索影响；未拒绝也不证明必有单位根。与原序列0.995相关可能主要来自共同趋势，既不是可预测信息，也不能证明低频成分稳定；书中把“memory”与“predictive power”并列属于未经项目证据支持的跳跃。按同一全样本反复搜索`d`、阈值和检验设定会泄漏并放大false positive。固定宽度截断消除扩展窗的机械漂移，但会改变频率响应并丢弃长尾；小`d`需要很长warm-up，导致样本起点、universe和regime覆盖改变。输入有缺口、复权/展期、极值、非同步bar或价格尺度变化时，卷积输出可能不可比。分数差分的非局部历史依赖还提高了实时状态、分区边界和重放一致性要求。
- **项目动作**：只把FFD作为训练期候选transform，并建立原始level、log-return/return、整数差分及简单滚动去趋势基线。每个purged训练折内预注册有限`d`/threshold网格，输出diagnostic surface而非只保存赢家；冻结选择后在验证期检查prefix invariance、分布漂移、结构break、样本损失、有效历史长度、下游预测增量、换手和成本。builder使用可序列化权重与状态，增加`d=0`、`d=1`、constant/ramp/sine、短序列、NaN gap、chunk boundary、restart replay、不同尺度、threshold边界和direct-convolution对照fixture。若FFD只改善ADF而不改善严格OOS基线，或增量依赖单一时期/资产，则拒绝该特征；不得因减少过差分就降低promotion证据门槛。
- **禁止直接采用**：不得复制书中`d=.35/.4`、`τ=1E-2/1E-5`、5% ADF阈值、E-mini统计量、87个期货结论或“全部`d<0.6`”；不得先对全样本选`d`再切分，不得把ADF通过、高原序列相关、非高斯或“driftless blend”描述为预测力、可交易性或跨市场稳健性。不得用累计和步骤人为保证需要差分后再把成功检验当经济发现，也不得让feature transform改变Strategy/Portfolio/OMS边界。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 原文概念复核完成**：`FORM-RES01-CH05-001`—`030`已回到原EPUB核对；只关闭source semantics为`verified_concept_only`，未执行snippet、ADF、fixture或项目实现。

## Ch05 原始 EPUB 复核

- 复核范围：Ch05正文位于 `OEBPS/text00001.html#filepos0000329259` 至下一章 `#filepos0000371207`，共47个图像资源，其中36个公式/符号、4个代码snippet、5个图、2个表。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。广义二项式、权重递推、扩展窗weight-loss、FFD截断与ADF选择正文均已逐项对图核验。
- 结论边界：只确认书中公式与示例的概念语义；代码、ADF、历史E-mini数据、87期货表和逆变换练习均未执行，全部状态仅为 `verified_concept_only`。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH05-001` | EPUB `text00001.html#filepos0000329259` §5.1-5.2 | 目标是在满足预定平稳性诊断的候选中选择尽量小的差分阶数，以少删历史依赖。 | 将stationarity、transform distance与predictive value分开；只在训练折选择。 | `verified_concept_only` |
| `FORM-RES01-CH05-002` | 同上 §5.4 | backshift满足 `B^k X_t=X_{t-k}`，差分算子写为 `(1-B)^d`。 | 核验索引方向、prefix-only、available time和边界padding。 | `verified_concept_only` |
| `FORM-RES01-CH05-003` | 同上；`Image00154.jpg` | 整数n的二项式展开生成有限阶组合权重。 | 对n=0、1、2做解析fixture并核验组合数与正负号。 | `verified_concept_only` |
| `FORM-RES01-CH05-004` | 同上；`Image00158.jpg`、`Image00847.jpg` | 实数d使用广义二项式级数，`(1-B)^d`产生无限权重尾部。 | 保存d domain、级数约定、截断准则与数值精度。 | `verified_concept_only` |
| `FORM-RES01-CH05-005` | 同上 §5.4.1；`Image00163.jpg`—`Image00172.jpg` | 分数差分输出 `tilde_X_t=sum_k omega_k X_{t-k}` 是仅用当前及历史值的因果卷积。 | 与direct convolution对照；核验lag顺序、chunk与restart。 | `verified_concept_only` |
| `FORM-RES01-CH05-006` | 同上 §5.4.2；`Image00178.jpg` | `d=0`时 `omega_0=1` 且其余为0，输出等于原序列。 | exact identity fixture；阈值逻辑不得删除当前权重。 | `verified_concept_only` |
| `FORM-RES01-CH05-007` | 同上；`Image00175.jpg`、`Image00178.jpg` | `d=1`时权重为 `{1,-1,0,...}`，退化为一阶差分。 | 核验首值、NaN、价格/log-price及符号约定。 | `verified_concept_only` |
| `FORM-RES01-CH05-008` | 同上；`Image00176.jpg` | 权重递推为 `omega_k=-omega_{k-1}(d-k+1)/k`。 | 与广义二项式直接计算比对并测试浮点误差。 | `verified_concept_only` |
| `FORM-RES01-CH05-009` | 同上；`Image00178.jpg` | 对 `0<d<1`，除 `omega_0=1` 外后续权重均在 `(-1,0)` 并衰减。 | 在接近0/1边界的d grid核验符号和收敛。 | `verified_concept_only` |
| `FORM-RES01-CH05-010` | 同上；`Image00228.jpg` | 对 `1<d<=2`，`omega_1<-1` 且 `k>=2` 的权重为正；更高区间符号随整数部变化。 | 分d区间验证；禁止把 `0<d<1` 结论外推。 | `verified_concept_only` |
| `FORM-RES01-CH05-011` | 同上 §5.4.3；`Image00190.jpg`—`Image00202.jpg` | 当k足够大时 `|omega_k/omega_{k-1}|<1`，权重从由int[d]决定的一侧趋于0。 | 核验limit、underflow、停止条件和非整数d。 | `verified_concept_only` |
| `FORM-RES01-CH05-012` | 同上 §5.4.1-5.4.3 | 无限衰减尾部比整数差分保留更长的filter历史响应。 | 不把impulse-response tail直接称为统计long memory或预测信息。 | `verified_concept_only` |
| `FORM-RES01-CH05-013` | 同上 §5.5.1；`Image00206.jpg`—`Image00213.jpg` | 扩展窗在时点t使用从样本起点到t的全部可用权重，因此不同时点记忆长度不同。 | 保存起始点、有效长度、排序和跨分区carry state。 | `verified_concept_only` |
| `FORM-RES01-CH05-014` | 同上；`Image00216.jpg` | relative weight-loss `lambda_l` 用被舍弃绝对权重占总绝对权重的比例衡量。 | 核验分子区间、绝对值、分母与阈值方向。 | `verified_concept_only` |
| `FORM-RES01-CH05-015` | 同上；`Image00425.jpg`、`Image00741.jpg` | `l*`由 `lambda_{l*}<=tau` 且下一位置超过tau的边界确定。 | 测试严格/非严格不等式、off-by-one及d趋近0/1。 | `verified_concept_only` |
| `FORM-RES01-CH05-016` | 同上；`Image00758.jpg`、`Image00767.jpg` | 扩展窗持续加入负尾权重，会在有限样本中产生机械负漂移。 | 用constant/ramp解析序列区分filter artifact与真实数据趋势。 | `verified_concept_only` |
| `FORM-RES01-CH05-017` | 同上 §5.5.2；`Image00771.jpg`、`Image00775.jpg` | FFD找到首个满足保留权重模大于等于tau、下一权重模小于等于tau的截断点。 | 明确首次穿越、绝对值、相等边界与非单调例外。 | `verified_concept_only` |
| `FORM-RES01-CH05-018` | 同上；`Image00779.jpg`、`Image00781.jpg` | 截断后 `tilde_omega_k=omega_k` 对 `k<=l*`，其余为0，固定宽度为 `l*+1` 个权重。 | 核验weight count与max lag的off-by-one。 | `verified_concept_only` |
| `FORM-RES01-CH05-019` | 同上；`Image00783.jpg` | FFD输出为固定向量 `sum_{k=0}^{l*} tilde_omega_k X_{t-k}`。 | direct convolution、prefix、chunk/restart与序列化状态fixture。 | `verified_concept_only` |
| `FORM-RES01-CH05-020` | 同上；`Image00794.jpg` | 只有在累积至少 `l*+1` 个有效历史值后才产生FFD输出。 | 明确首个有效index、NaN/drop policy和partition warm-up。 | `verified_concept_only` |
| `FORM-RES01-CH05-021` | 同上 §5.6；`Image00798.jpg` | `d*`是使FFD输出满足预注册stationarity criterion的最小候选d。 | 固定grid、tie、ADF specification并保存全部候选surface。 | `verified_concept_only` |
| `FORM-RES01-CH05-022` | 同上；`Image00801.jpg`—`Image00806.jpg` | 书中以 `d*=0`、`d*<1`、`d*>1`启发式区分已平稳、单位根和爆炸性序列。 | 仅作诊断解释；与trend、break、heteroskedasticity challenger并列。 | `verified_concept_only` |
| `FORM-RES01-CH05-023` | 同上；`Image00808.jpg`、`Image00809.jpg` | 示例沿d grid计算ADF statistic并与固定critical value比较。 | 保存lag/trend/sample/critical-value版本；补充互补诊断与多重搜索。 | `verified_concept_only` |
| `FORM-RES01-CH05-024` | 同上；`Image00808.jpg` | 原序列与FFD序列相关性被用作变换后历史保留代理。 | 高相关不命名为memory、alpha或predictive power证据。 | `verified_concept_only` |
| `FORM-RES01-CH05-025` | 同上 §5.6 | E-mini示例在d grid中首次越过ADF阈值附近选择d。 | 历史数值与5%阈值不迁移；d、tau、lag均计入trial ledger。 | `verified_concept_only` |
| `FORM-RES01-CH05-026` | 同上；`Image00812.jpg`、`Image00815.jpg` | 书中87个期货表主张样本内所有序列均在 `d<0.6` 达到ADF阈值。 | 仅记录历史主张；需原数据、PIT连续合约和多重检验复核。 | `verified_concept_only` |
| `FORM-RES01-CH05-027` | 同上 §5.7 | 章节建议先累计序列，再搜索最小ADF通过d并作为feature。 | 不人为制造非平稳后宣称经济发现；必须与简单transform基线比较。 | `verified_concept_only` |
| `FORM-RES01-CH05-028` | 同上练习 | 练习要求比较FFD(d)后再FFD(-d)的近似逆变换。 | 区分无限级数理论与fixed-width有限截断误差；不视为已验证恒等式。 | `verified_concept_only` |
| `FORM-RES01-CH05-029` | 同上练习 | 练习把FFD、CUSUM、triple barrier、sequential bootstrap和sample weights串为联合实验。 | 每步fold-local并记录lineage/trials；书中练习参数不得迁移。 | `verified_concept_only` |
| `FORM-RES01-CH05-030` | 同上全章 | FFD证据需保存训练期拟合、冻结权重、warm-up、可重放状态及多诊断结果。 | 本章只关闭原文概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 6 章

### 第 6 章：集成降方差、学习器相关性与金融验证边界

- **论证链**：本章从bias、variance和irreducible noise分解出发，把ensemble定义为组合多个基学习器。bagging对训练样本有放回重采样、独立拟合并平均回归输出或分类概率/投票；在基学习器方差相近时，集成方差由学习器数量`N`和预测误差平均相关`ρ`共同决定，`N`增加只能消除不相关部分，相关部分形成方差下限。金融label高度重叠时，即使bootstrap样本行号不同也可能依赖同一底层回报，树之间接近相同，OOB样本也与in-bag样本共享信息，因此方差下降和OOB泛化估计都会失真。随机森林再随机抽取候选特征以降低树间相关，但不改变这一信息重叠事实；boosting顺序提高错分样本权重，可能同时降低bias与variance，也更容易追逐噪声、错价、尾部或错误标签。集成的稳定贡献是“测量并降低有效误差相关”，不是“树多就不会过拟合”。
- **成立条件**：`EnsembleEvidence`必须保存target/label span、base estimator及版本、preprocessing、hyperparameters、sample/feature bootstrap语义、replacement、sample fraction、feature fraction、tree/learner count、seed序列、fit weights、class weights、aggregation和calibration。所有transform、PCA、class frequency、uniqueness、resampling及early stopping只在训练折拟合；验证使用purged/embargo split，不采纳普通随机K-fold、书中简单stratified non-shuffle K-fold或OOB作为最终OOS。报告单学习器与ensemble的bias proxy、预测dispersion、pairwise error/prediction correlation、effective sample size、calibration、class/regime loss、turnover和成本；增加学习器数量时验证方差平台、计算成本和seed稳定性。概率平均、硬投票、weighted vote和stacking分开登记，输出仍是Forecast，不直接映射仓位或OrderIntent。
- **局限与反例**：标准MSE bias-variance-noise分解依赖数据生成与损失假设，金融噪声通常不是IID白噪声，并含regime、异方差、标签错误和可避免的数据质量问题。书中多数投票准确率改进关系假设学习器独立、同准确率、类别结构简单且损失对称；真实模型误差相关、类别不平衡、abstention与交易成本使accuracy不等于经济价值。bagging可降低方差却保留共同bias；随机特征或PCA不保证经济多样性，PCA若全样本拟合会泄漏且降低可解释性。OOB在重叠label下乐观，但普通stratified K-fold同样不足，必须按第7章信息区间purge/embargo。`average uniqueness`不是可直接复制的`max_samples`默认值。boosting并非必然比bagging差，bagging也不保证“不overfit”；两者都需相同防泄漏验证。早停SVM再bagging可能把未收敛bias包装成稳定输出，更多学习器不能保证抵消系统性错误。
- **项目动作**：每个ML候选先建立线性/规则、单树或单一正则模型基线，再比较bagging、RF或boosting；不得同时无预算搜索多个家族。对同一fold保存各基学习器预测矩阵，计算预测相关、错误相关、disagreement、calibration和按regime一致性，确认增量来自有效多样性而非重复试验。label overlap通过第4章indicator/uniqueness诊断，resampling在训练fold内比较standard、sequential或受限sample fraction，但不预设某种必胜。OOB仅用于训练期debug，最终模型选择使用第7章purged/embargo并把estimator count、feature subsampling、depth/leaf、class weight、boosting rounds、learning rate、early stopping和seed计入trial ledger。实现增加single learner equivalence、identical learners、perfectly correlated errors、independent synthetic errors、seed replay、probability aggregation、missing class、sample-weight routing和parallel deterministic merge fixture。
- **禁止直接采用**：不得复制`1000`棵树、`5% min_weight_fraction_leaf`、`max_samples=avgU`、`balanced_subsample`、PCA+RF、`max_iter=1E5`、`tol=1E-3`、低K值或任何sklearn示例；不得把OOB、训练投票准确率、树数增加或低预测方差称为OOS、alpha或稳健性。不得使用全样本PCA、class balance、uniqueness或错误权重；不得因少数类加权就声称尾部风险已覆盖，也不得让boosting反复聚焦坏价而缺数据质量隔离。集成输出只进入Forecast/研究证据，Portfolio/Risk、OMS/Execution和Fill/Ledger边界不变。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 原文概念复核完成**：`FORM-RES01-CH06-001`—`030`已回到原EPUB核对；只关闭source semantics为`verified_concept_only`，未执行snippet、协方差/binomial fixture、sklearn或项目实现。

## Ch06 原始 EPUB 复核

- 复核范围：Ch06正文位于 `OEBPS/text00001.html#filepos0000371207` 至下一章 `#filepos0000404229`。该起点在正文前另有一次目录链接，本次以正文锚点最后一次出现为准；共31个图像资源，其中26个公式/符号、2个代码snippet、3个图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。MSE分解、bagged variance、投票概率、RF与boosting流程均已逐项对图核验。
- 结论边界：只确认书中公式、启发式和历史sklearn示例的概念语义；代码、旧bug、library参数、数值图和性能结论均未执行或复现，全部状态仅为 `verified_concept_only`。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH06-001` | EPUB `text00001.html#filepos0000371207` §6.2 | 书中数据生成假设为 `y=f(x)+epsilon`。 | 保存conditional target定义、feature可见时间；误差不默认白噪声。 | `verified_concept_only` |
| `FORM-RES01-CH06-002` | 同上 §6.2 | 书中进一步假设 `E[epsilon_i]=0`。 | 按训练fold/regime检查conditional bias；数据错误不得归入irreducible noise。 | `verified_concept_only` |
| `FORM-RES01-CH06-003` | 同上 §6.2 | 书中以固定 `E[epsilon_i^2]=sigma_epsilon^2` 表示噪声方差。 | 增加异方差、serial dependence、tail与label-noise诊断。 | `verified_concept_only` |
| `FORM-RES01-CH06-004` | 同上；`Image00818.jpg`—`Image00826.jpg` | expected test MSE分解为squared bias、estimator variance与noise variance。 | 明确期望针对训练集随机性与新样本；不把可修数据问题视为noise。 | `verified_concept_only` |
| `FORM-RES01-CH06-005` | 同上 §6.3 | bagging回归输出为N个基学习器预测的简单平均。 | 测试单学习器、identical learners、shape与可选权重语义。 | `verified_concept_only` |
| `FORM-RES01-CH06-006` | 同上 §6.3 | 硬分类投票用预测某类的学习器占比形成class vote proportion。 | 核验class order、tie、missing class与abstention。 | `verified_concept_only` |
| `FORM-RES01-CH06-007` | 同上 §6.3 | 基学习器支持概率时可对class probabilities求均值。 | 对齐类别列并检查归一化、calibration及与硬投票差异。 | `verified_concept_only` |
| `FORM-RES01-CH06-008` | 同上 §6.3 | N个训练集由原训练事件有放回随机抽样形成，基学习器独立拟合。 | 保存replacement、draw count、event weights、seed与fold。 | `verified_concept_only` |
| `FORM-RES01-CH06-009` | 同上 §6.3.1；`Image00836.jpg` | ensemble mean variance为全部learner covariance求和后除以 `N^2`。 | 用任意PSD covariance matrix与直接prediction matrix交叉计算。 | `verified_concept_only` |
| `FORM-RES01-CH06-010` | 同上；`Image00838.jpg`、`Image00843.jpg` | `bar_sigma^2=N^-1 sum_i sigma_i^2` 定义平均单学习器预测方差。 | 明确样本轴、ddof和prediction-vs-residual variance。 | `verified_concept_only` |
| `FORM-RES01-CH06-011` | 同上；`Image00849.jpg`、`Image00850.jpg` | 平均预测相关由两两 `sigma_i sigma_j rho_ij` 聚合定义。 | 分开prediction、residual与error correlation并按fold/regime报告。 | `verified_concept_only` |
| `FORM-RES01-CH06-012` | 同上；`Image00836.jpg` | 等方差等平均相关近似下，ensemble variance为 `bar_sigma^2[bar_rho+(1-bar_rho)/N]`。 | 解析核验N、rho及相关矩阵PSD可行域。 | `verified_concept_only` |
| `FORM-RES01-CH06-013` | 同上 §6.3.1 | 当平均相关为0时，ensemble variance按 `1/N` 下降。 | 用独立synthetic errors复核；现实数据不得预设独立。 | `verified_concept_only` |
| `FORM-RES01-CH06-014` | 同上；`Image00223.jpg` | 当平均相关趋于1时，ensemble variance趋于单学习器平均方差。 | identical prediction matrix fixture；增加N不得伪造降方差。 | `verified_concept_only` |
| `FORM-RES01-CH06-015` | 同上 §6.3.1 | `N→∞`只能消除不相关方差，相关项形成variance floor。 | 保存learner-count/seed曲线与平台，不把有限图称为收敛证明。 | `verified_concept_only` |
| `FORM-RES01-CH06-016` | 同上 §6.3.2 | 在独立、同准确率p的二元correct-vote编码下，正确票数服从 `Binomial(N,p)`。 | 明确equal-p/independence假设；相关误差另用实证矩阵。 | `verified_concept_only` |
| `FORM-RES01-CH06-017` | 同上；`Image00016.jpg`、`Image00138.jpg` | 多数投票的充分条件是正确票数大于 `N/2`，概率为对应binomial upper tail。 | 核验偶数N、tie policy、tail求和边界与数值稳定性。 | `verified_concept_only` |
| `FORM-RES01-CH06-018` | 同上；`Image00019.jpg` | k分类时正确票数大于 `N/k` 只是必要非充分条件；真正成功还需胜过每个错误类。 | 建多分类反例并保存class-specific vote vector。 | `verified_concept_only` |
| `FORM-RES01-CH06-019` | 同上；`Image00026.jpg`、`Image00174.jpg` | 书中给出足够大N且 `p>1/k` 时集成准确率可能超过单学习器p的条件。 | 类别不平衡、cost-sensitive与相关误差下不得使用固定chance基准。 | `verified_concept_only` |
| `FORM-RES01-CH06-020` | 同上；`Image00035.jpg`—`Image00041.jpg` | bagging主要降低variance；poor/common-biased learners不会因投票自动修复bias。 | 用共同偏差fixture并与简单模型比较。 | `verified_concept_only` |
| `FORM-RES01-CH06-021` | 同上 §6.3.3；`Image00046.jpg` | label overlap使不同bootstrap行集合仍共享底层回报，推动learner correlation接近1。 | 连接Ch04 indicator/concurrency；按底层bar而非行号衡量重叠。 | `verified_concept_only` |
| `FORM-RES01-CH06-022` | 同上 §6.3.3 | OOB事件可能与in-bag事件的信息区间重叠，导致OOB accuracy乐观。 | OOB只作debug；最终使用按信息区间purged/embargo验证。 | `verified_concept_only` |
| `FORM-RES01-CH06-023` | 同上 §6.3.3 | 书中以average uniqueness限制 `max_samples`，或建议sequential bootstrap。 | 仅作训练折challenger；报告ESS、sample fraction与消融。 | `verified_concept_only` |
| `FORM-RES01-CH06-024` | 同上 §6.4 | RF同时随机bootstrap训练事件，并在每个节点无放回抽取候选特征子集。 | 绑定library/version，区分sample与feature replacement语义。 | `verified_concept_only` |
| `FORM-RES01-CH06-025` | 同上 §6.4；`Image00050.jpg` | 随机特征子集旨在降低树间相关，但不保证经济假设或误差真正多样。 | 测量实际error correlation并检查相关特征组/PCA泄漏。 | `verified_concept_only` |
| `FORM-RES01-CH06-026` | 同上；`Image00055.jpg` | 书中RF示例组合depth/leaf、feature fraction、sample fraction、class weight和outer bagging。 | 所有参数计入trial；不得复制旧sklearn默认与示例值。 | `verified_concept_only` |
| `FORM-RES01-CH06-027` | 同上 §6.5；`Image00060.jpg` | boosting逐轮提高错分样本权重、降低正确样本权重，并拒绝低于阈值的learner。 | 保存每轮weight concentration；隔离坏价、错标与tail events。 | `verified_concept_only` |
| `FORM-RES01-CH06-028` | 同上 §6.5-6.6 | boosting最终按各learner训练表现加权聚合，而非bagging的简单平均。 | 聚合权重与训练指标版本化；模型选择仍基于purged validation。 | `verified_concept_only` |
| `FORM-RES01-CH06-029` | 同上 §6.7 | 对难扩展基学习器早停后并行bagging，是以单learner bias/variance换计算和ensemble variance。 | 保存convergence status、wall time和bias proxy；更多learner不修复系统错误。 | `verified_concept_only` |
| `FORM-RES01-CH06-030` | 同上全章 | 金融ensemble证据需保存overlap、fold隔离、seed、预测矩阵、误差相关、聚合和完整trial。 | 本章只关闭原文概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 7 章

### 第 7 章：信息区间切分、purging、embargo与选择偏差

- **论证链**：普通K-fold假定观测可被互斥分到训练与测试后便不共享信息，但金融feature具有序列依赖，label又常由`t0`到first-touch/vertical`t1`的一段未来路径决定。相邻事件若落入不同fold，训练事件与测试事件可能共享底层回报；即使feature无预测力，模型也能借近重复的`(X,Y)`获得虚假表现。purging因此从训练集移除label信息区间与测试label区间相交的事件，区间相交包括训练起点落入测试区间、训练终点落入测试区间或训练区间完全包住测试区间。embargo再排除测试结束后的一段训练起点，以减轻序列相关feature、长lookback或边界状态残留。该方法适用于调参、模型评估和回测切分，但只处理特定信息泄漏；同一CV反复筛选上千配置仍会产生multiple testing和selection bias。
- **成立条件**：`InformationIntervalSplitEvidence`必须保存event_id、feature start/end/lookback、feature available/decision time、label t0/t1、区间闭合约定、timezone/session、censor/NaT policy、group/universe、splitter/version、fold assignment、purged IDs/reason、embargo type/size、train/test input hash和fold hash。相交判定应以明确公式`max(start_i,start_j) <= min(end_i,end_j)`或等价闭区间逻辑实现，并扩展到feature lineage与发布延迟，不只看label。所有标准化、imputation、bar阈值、fracdiff、PCA、特征选择、class/uniqueness weights、calibration和early stopping按训练fold拟合。超参数选择使用内层purged/embargo CV，外层只估计选择流程；最终holdout由独立owner单次解封，访问、失败候选和trial count全部入ledger。
- **局限与反例**：purge仅删除已知区间相交，不能发现错误timestamp、未来修订、全样本预处理、跨资产共同信息、供应商回填或研究者反复查看测试结果；embargo也不是这些错误的替代品。固定`1%T`是书中启发式，未必对应feature lookback、最长label horizon、bar duration、交易日或24/7日历；过短泄漏，过长又减少训练样本并改变regime覆盖。仅在测试后embargo依赖信息可得与训练方向假设；若pipeline有双向滤波、centered window、future-filled missing或非因果状态，前后都可能污染。书中“feature重叠但label独立即不泄漏”的表述过窄：共享预处理状态、entity、revision或selection也可泄漏。原文约`9970-9983`在“应purge”语境中显示`Φ_i∩Φ_j=∅`，逻辑应为非空交集，疑似符号抽取缺失，必须回看原版。性能随K上升的平台不是无泄漏证明，也可能来自样本量、regime或模型变化。
- **项目动作**：统一实现纯函数splitter，以label span、feature dependency interval和availability构造禁配矩阵；先生成测试fold，再从训练候选中purge所有相交事件，并按预注册的时间/事件规则embargo。增加touching endpoints、train-contained-in-test、test-contained-in-train、跨多个test intervals、NaT/censored、zero-length、weekend/session、DST、24/7、跨资产shared release、longest-lookback、partition和deterministic replay fixture。每个实验报告raw/purged/embargo train size、移除比例、span coverage、effective sample size、class/regime分布和fold metric distribution；若某fold不足、缺类或只覆盖单一regime则fail-closed，不通过减少隔离来凑样本。K、embargo和split variant均计入trial ledger；OOB、普通K-fold、walk-forward和purged CV不得挑最优后只报告赢家。
- **禁止直接采用**：不得复制`K=10`、`1% embargo`、低K建议、accuracy大于`1/2`、书中`PurgedKFold/cvScore` snippet或旧sklearn bug workaround；不得把`shuffle=False`的StratifiedKFold称为合格金融CV，也不得把purging/embargo通过称为无泄漏。不得按全样本最长horizon、最终`t1`分布或测试表现调整embargo，不得让测试/holdout参与transform、权重、threshold、feature/model family选择。不得因验证分数降低而缩短隔离或重新定义label，当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 原文概念复核完成**：`FORM-RES01-CH07-001`—`030`已回到原EPUB核对；原文 `Phi_i∩Phi_j=empty` 与“overlap”正文及Snippet 7.1相矛盾，已按source typo登记而不照录实现。其余只关闭source semantics为`verified_concept_only`，未执行snippet、fixture、sklearn或项目实现。

## Ch07 原始 EPUB 复核

- 复核范围：Ch07正文位于 `OEBPS/text00001.html#filepos0000404229` 至下一章 `#filepos0000434781`，共8个图像资源，其中1个公式、4个代码snippet、3个示意图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。K-fold、purge三种区间相交、embargo、PurgedKFold与weighted scoring均已逐项核对。
- 重要矛盾：§7.4.1原文写“purge ... such that `Phi_i∩Phi_j=empty`”，但同段定义为共享随机信息、后续三个闭区间相交条件及Snippet 7.1均删除重叠事件；因此项目合同采用“非空交集触发purge”，同时把原式保留为source typo证据。
- 结论边界：旧sklearn issue、书中1% embargo、低K启发式和代码均未执行或验证；全部状态仅为 `verified_concept_only`。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH07-001` | EPUB `text00001.html#filepos0000404229` §7.1-7.2 | CV目标是估计指定训练算法对未来未见样本的generalization error。 | 固定目标总体、时间方向、loss与selection procedure；CV不是locked holdout。 | `verified_concept_only` |
| `FORM-RES01-CH07-002` | 同上 §7.2；`Image00063.jpg` | K-fold把样本划为K个互斥测试子集，每折以其中一个测试。 | 验证覆盖、互斥、时间顺序及每event一次test。 | `verified_concept_only` |
| `FORM-RES01-CH07-003` | 同上 §7.2 | 第i折训练集是除第i测试子集外其余子集的并集。 | 索引补集、无重复与deterministic fold assignment fixture。 | `verified_concept_only` |
| `FORM-RES01-CH07-004` | 同上 §7.2 | K-fold输出K×1指标向量，而非无不确定性的单分数。 | 保存完整fold分布、size/weight与聚合规则。 | `verified_concept_only` |
| `FORM-RES01-CH07-005` | 同上 §7.2 | 书中以平衡二分类fair-coin情形说明accuracy超过1/2。 | 实际基线使用class prior、cost、calibration和abstention。 | `verified_concept_only` |
| `FORM-RES01-CH07-006` | 同上 §7.3 | serial feature使相邻X相似，overlapping labels使相邻Y相似。 | 分测feature dependence与label interval overlap；近似号不是独立性检验。 | `verified_concept_only` |
| `FORM-RES01-CH07-007` | 同上 §7.3 | 相似的train/test `(X,Y)` pair可让无关feature产生虚假表现。 | 建irrelevant-feature fixture并隔离shared transform/state。 | `verified_concept_only` |
| `FORM-RES01-CH07-008` | 同上 §7.3 | 若训练label依赖测试label使用的共同信息，应从训练集purge。 | 用lineage/interval判定并记录删除reason与source event。 | `verified_concept_only` |
| `FORM-RES01-CH07-009` | 同上 §7.3 | 书中称仅X相似或仅Y相似不必然构成其特定pair leakage。 | 该范围不覆盖transform、entity、release、selection与runtime-state泄漏。 | `verified_concept_only` |
| `FORM-RES01-CH07-010` | 同上 §7.4.1 | 原文印成 `Phi_i∩Phi_j=empty`，与共享信息定义、三个相交条件及Snippet 7.1冲突。 | 登记source typo；实现必须用非空信息交集/区间相交触发purge。 | `verified_concept_only` |
| `FORM-RES01-CH07-011` | 同上 §7.4.1 | label由闭区间 `[t0,t1]` 内的信息路径决定。 | 明确端点、first-touch bar、available time与zero-length event。 | `verified_concept_only` |
| `FORM-RES01-CH07-012` | 同上；`Image00065.jpg` | triple-barrier示例label为事件起点至终点return的sign。 | 连接Ch03并核验gap、same-bar touch、missing/censor与price source。 | `verified_concept_only` |
| `FORM-RES01-CH07-013` | 同上 §7.4.1 | 训练起点落入测试闭区间构成overlap。 | 核验等号、touching endpoint和共享底层bar。 | `verified_concept_only` |
| `FORM-RES01-CH07-014` | 同上 §7.4.1 | 训练终点落入测试闭区间构成overlap。 | 测试NaT、倒置interval和边界。 | `verified_concept_only` |
| `FORM-RES01-CH07-015` | 同上 §7.4.1 | 训练区间完全包住测试区间也构成overlap。 | 测试long horizon、多个test intervals与containment。 | `verified_concept_only` |
| `FORM-RES01-CH07-016` | 同上；`Image00068.jpg` | Snippet 7.1以三类闭区间条件删除重叠训练事件。 | 与 `max(starts)<=min(ends)` 做truth-table等价测试。 | `verified_concept_only` |
| `FORM-RES01-CH07-017` | 同上 §7.4.1 | purged train等于候选训练事件减去与任一test interval相交者。 | 多test interval、duplicates和stable ordering fixture。 | `verified_concept_only` |
| `FORM-RES01-CH07-018` | 同上 §7.4.1 | 测试集连续且内部无训练事件时，可用测试envelope加速purge。 | 仅在前提成立时启用，并与逐interval结果对照。 | `verified_concept_only` |
| `FORM-RES01-CH07-019` | 同上 §7.4.1；`Image00071.jpg` | 未purge时增大K会增加邻近重叠并机械改善表现；书中以平台作诊断。 | score-vs-K只作诊断，K也进入trial；平台不证明无泄漏。 | `verified_concept_only` |
| `FORM-RES01-CH07-020` | 同上 §7.4.2 | 测试开始前已经结束且当时可得的训练label通常无需后向embargo。 | 仍检查feature lookback、release lag与非因果transform。 | `verified_concept_only` |
| `FORM-RES01-CH07-021` | 同上 §7.4.2 | 测试结束后至 `t_test_end+h` 内开始的训练事件进入embargo。 | 定义起止等号、calendar/event time及相邻fold合并。 | `verified_concept_only` |
| `FORM-RES01-CH07-022` | 同上；`Image00074.jpg`、`Image00078.jpg` | embargo可先扩展test interval终点，再应用同一purge逻辑。 | 分开time-length与event-count h；检查session与overflow。 | `verified_concept_only` |
| `FORM-RES01-CH07-023` | 同上 §7.4.2 | `h≈0.01T`只是书中经验启发式。 | 不复制固定比例；由依赖窗口、release lag和bar clock预注册。 | `verified_concept_only` |
| `FORM-RES01-CH07-024` | 同上 §7.4.3；`Image00461.jpg` | fitting、backtest与performance evaluation的split均应统一purge/embargo。 | 单一splitter/version输出fold hash，禁止调用路径分叉。 | `verified_concept_only` |
| `FORM-RES01-CH07-025` | 同上练习 | shuffle把时间邻近和路径重叠事件随机散入train/test。 | 金融时间CV默认禁shuffle；IID synthetic例外需显式声明。 | `verified_concept_only` |
| `FORM-RES01-CH07-026` | 同上 §7.5；`Image00477.jpg` | Snippet 7.4把sample weight同时路由至fit和score/log-loss。 | 按锁定library版本测试weight routing；旧issue不代表当前状态。 | `verified_concept_only` |
| `FORM-RES01-CH07-027` | 同上；`Image00477.jpg` | 概率score显式使用 `clf.classes_` 对齐class columns。 | 测missing class、class order与probability column alignment。 | `verified_concept_only` |
| `FORM-RES01-CH07-028` | 同上 §7.3及练习 | 反复比较同一CV上的配置会把validation变成被过拟合的选择集。 | 记录全部trial，采用nested selection并保留独立holdout。 | `verified_concept_only` |
| `FORM-RES01-CH07-029` | 同上练习 | train/validation/test三分在test被反复查看或反向选择时仍失效。 | 独立owner、单次解封、访问ledger与候选冻结。 | `verified_concept_only` |
| `FORM-RES01-CH07-030` | 同上全章 | 合格金融验证需完整信息区间、fold-local变换、purge/embargo与selection ledger。 | 本章只关闭原文概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 8 章

### 第 8 章：特征重要性、替代效应与非因果解释边界

- **论证链**：本章反对反复“训练—回测—换特征”直到出现漂亮结果，转而比较三类重要性。MDI把树节点impurity decrease归因给被选特征并跨树平均，计算快但完全样本内，受高基数、split机会、masking和相关特征稀释影响；归一化后总和为1也会让纯噪声获得正份额。MDA在purged/embargo验证折内逐列置乱，按相对score下降衡量预测重要性，可用于多模型并允许负重要性，但相关替代特征会互相遮蔽，普通逐行置乱还会破坏时间、实体和联合分布，产生离分布样本。SFI逐个特征独立验证，避免替代却遗漏交互和层级关系。PCA可缓解线性共线并降维，但只解释feature variance；其与监督重要性排序一致不等于无过拟合、预测机制或因果。逐资产并行聚合与跨资产stacking分别面临排名不稳定和分布同质性假设。
- **成立条件**：`FeatureImportanceEvidence`必须保存feature lineage/available time、target/label span、model与score、split/fold hash、sample weight、method/version、baseline score、perturbed score、per-fold importance、seed、permutation unit/block、correlated group、asset/regime、aggregation和uncertainty。MDI同时报告cardinality、missingness、split frequency与null baseline；MDA至少比较naive、time-block/entity-block和相关组/conditional permutation，并确认置乱样本仍在合理support；SFI与pair/group ablation检查交互。standardization、PCA、feature clustering、group定义和选择阈值按训练fold拟合；选择后的模型必须在外层purged/embargo流程重估。跨资产stacking保存instrument、calendar、currency、session、normalization和group split，防止同一时点/标的泄漏与大样本资产支配。
- **局限与反例**：书中“20次即可找到5%显著的假策略”是直觉性表述；若独立检验，20次至少一次false positive的概率约为`1-0.95^20`而非必然，真实相关试验还需effective trial count。口号“backtesting不是研究工具，feature importance才是”同样过度：重要性使用label、模型、score和反复选择，也会被过拟合，只能辅助提出与反证假设。将MDI未被抽到的0替换NaN、`max_features=1`或总和1都不是通用无偏修复。MDA逐列随机置乱可制造不可能状态，score下降可能反映模型依赖而非特征可用价值；负值也可能来自噪声。PCA在全样本拟合会泄漏，top variance方向可能完全无预测力；PCA rank与重要性高相关可能来自尺度、共同构造或同一数据重复选择。stacking不保证更一般，regime、资产机制和label base rate不齐会产生Simpson式聚合错误。
- **项目动作**：特征研究先按经济机制和lineage注册feature family，再在固定模型/score/trial budget下做null、MDI、blocked/grouped MDA、SFI及group ablation；不因单一排名删特征。报告每fold/asset/regime分布、rank stability、sign/score stability、相关组总重要性、加入/删除后的严格OOS增量、计算与数据成本，并对重要特征执行lag、availability、placebo、future-shift和坏数据敏感性测试。置乱操作以同日横截面、同asset时间block或条件邻域保持可行结构，具体单位预注册。PCA只作为fold-local challenger，保留loadings与解释方差，不把component直接解释为原始经济变量。重要性只更新research question和候选feature contract；任何特征进入策略仍需独立基线、selection-adjusted验证和current-HEAD evidence。
- **禁止直接采用**：不得复制`max_features=1`、零值转NaN、95% PCA方差、weighted Kendall tau阈值、40/10/10/20 synthetic配置、10到100折、RF默认参数或stacking偏好；不得把MDI总和1、MDA score下降、SFI单变量有效、PCA一致、跨资产平均排名或synthetic识别正确称为因果、稳健或alpha。不得用全样本standardization/PCA/cluster，不得随机打乱破坏时间/实体结构，也不得看holdout重要性后回选特征。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 原文概念复核完成**：`FORM-RES01-CH08-001`—`030`已回到原EPUB核对；只关闭source semantics为`verified_concept_only`，未执行snippet、synthetic experiment、PCA/importance fixture或项目实现。

## Ch08 原始 EPUB 复核

- 复核范围：Ch08正文位于 `OEBPS/text00001.html#filepos0000434781` 至下一章 `#filepos0000476302`，共24个图像资源，其中11个公式/符号、9个代码snippet、4个结果图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。MDI、MDA、SFI、PCA、weighted Kendall、parallel/stacked importance与synthetic示例均已逐项核对。
- 结论边界：书中历史相关系数、PCA一致性、synthetic排名和参数均未复现；重要性只作为模型依赖诊断，不是因果、alpha、无过拟合或promotion证据。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH08-001` | EPUB `text00001.html#filepos0000434781` §8.1 | 独立5%检验重复m次至少一次false positive概率为 `1-(1-.05)^m`；书中“约20次”是直觉。 | 保存trial dependence与effective trial count；不得描述为必然。 | `verified_concept_only` |
| `FORM-RES01-CH08-002` | 同上 §8.2 | feature importance被用于追问模型依赖哪些信息，而不是继续盲目循环回测。 | 只生成research hypothesis；importance本身使用label且可被选择过拟合。 | `verified_concept_only` |
| `FORM-RES01-CH08-003` | 同上 §8.3 | substitution effect使相关特征分摊、遮蔽或互换重要性。 | duplicate/correlated feature与group-importance fixture。 | `verified_concept_only` |
| `FORM-RES01-CH08-004` | 同上 §8.3.1 | 单节点MDI把sample-weighted impurity decrease归因给split feature。 | 固定criterion、parent/child weights和sample-weight语义。 | `verified_concept_only` |
| `FORM-RES01-CH08-005` | 同上 §8.3.1 | 单树feature importance汇总该特征在所有split节点的weighted decrease。 | 未使用feature为0；保存归一化前总贡献。 | `verified_concept_only` |
| `FORM-RES01-CH08-006` | 同上；`Image00087.jpg` | forest MDI跨树求均值，并用树间离散估计均值不确定性。 | 保存per-tree values；区分tree SD、mean SE与树间相关。 | `verified_concept_only` |
| `FORM-RES01-CH08-007` | 同上 §8.3.1 | 书中以 `max_features=1` 增加每个特征被候选机会、减轻masking。 | 仅作challenger；联合评估性能、tree correlation与library版本。 | `verified_concept_only` |
| `FORM-RES01-CH08-008` | 同上；`Image00087.jpg` | 书中把0替换NaN，解释为某树未随机选择该feature。 | 必须同时保存selection count；被选无贡献与未被选不能混同。 | `verified_concept_only` |
| `FORM-RES01-CH08-009` | 同上 §8.3.1 | 归一化MDI非负且feature importances总和为1。 | pure-noise/cardinality null；simplex约束不证明任何feature有效。 | `verified_concept_only` |
| `FORM-RES01-CH08-010` | 同上 §8.3.1 | 两个完全替代feature可能近似平分原有MDI。 | duplicate columns、多seed与group-sum稳定性fixture。 | `verified_concept_only` |
| `FORM-RES01-CH08-011` | 同上 §8.3.1 | impurity importance偏向类别更多、split机会更多的变量。 | 变化cardinality、missingness和noise support的null fixture。 | `verified_concept_only` |
| `FORM-RES01-CH08-012` | 同上 §8.3.2；`Image00504.jpg` | MDA先在未置乱的purged CV test fold计算baseline score。 | 保存fold、sample weights、score方向与baseline。 | `verified_concept_only` |
| `FORM-RES01-CH08-013` | 同上；`Image00504.jpg` | 单列置乱后的score loss定义permutation importance，并允许负值。 | 核验seed、零分母、score direction和support shift。 | `verified_concept_only` |
| `FORM-RES01-CH08-014` | 同上；`Image00504.jpg` | negative log-loss与accuracy分别按不同maximum-possible score归一化。 | 明确符号、boundedness、class order和sample-weight routing。 | `verified_concept_only` |
| `FORM-RES01-CH08-015` | 同上 §8.3.2 | 逐列置乱相关替代feature时，双方都可能看似无关。 | grouped/conditional permutation并报告cluster总贡献。 | `verified_concept_only` |
| `FORM-RES01-CH08-016` | 同上 §8.3.2 | 普通逐行shuffle会破坏时间、实体和联合support。 | 使用time/entity block或conditional permutation并做support诊断。 | `verified_concept_only` |
| `FORM-RES01-CH08-017` | 同上 §8.4.1；`Image00092.jpg` | SFI为每个单feature独立模型的purged OOS score。 | 相同model/score/folds比较；preprocessing必须fold-local。 | `verified_concept_only` |
| `FORM-RES01-CH08-018` | 同上 §8.4.1 | SFI避免substitution，但遗漏只在组合或层级split中有效的feature。 | XOR/hierarchical synthetic与pair/group ablation。 | `verified_concept_only` |
| `FORM-RES01-CH08-019` | 同上 §8.4.2 | PCA先以训练mean/std标准化 `Z=(X-mu)/sigma`。 | 常数列、missing、ddof及fit/transform隔离fixture。 | `verified_concept_only` |
| `FORM-RES01-CH08-020` | 同上 §8.4.2；`Image00541.jpg` | PCA求解 `Z'ZW=W Lambda`，W为正交特征向量。 | 核验scale、eigen排序、符号不定与退化eigenvalue。 | `verified_concept_only` |
| `FORM-RES01-CH08-021` | 同上 §8.4.2 | 主成分 `P=ZW`，在书中尺度下 `P'P=Lambda`。 | 验证shape、orthogonality、scale与inverse transform。 | `verified_concept_only` |
| `FORM-RES01-CH08-022` | 同上；`Image00541.jpg` | 保留累计解释方差达到阈值的最小主成分数。 | 95%不作默认；阈值只在训练选择并计入trial。 | `verified_concept_only` |
| `FORM-RES01-CH08-023` | 同上；`Image00100.jpg` | PCA eigenvalue rank与监督importance rank一致被书中视为确认性线索。 | 不是无过拟合证明；加label permutation与全流程selection null。 | `verified_concept_only` |
| `FORM-RES01-CH08-024` | 同上；`Image00586.jpg` | weighted Kendall tau强调importance头部与inverse PCA rank的一致性。 | 固定weight function、tie与rank orientation；数值阈值计入trial。 | `verified_concept_only` |
| `FORM-RES01-CH08-025` | 同上 §8.5 | parallel方法先得资产i、feature j、criterion k的重要性，再跨资产聚合。 | 明确asset weights、missing feature、uncertainty与rank substitution。 | `verified_concept_only` |
| `FORM-RES01-CH08-026` | 同上；`Image00609.jpg`—`Image00335.jpg` | stacking把变换后的多资产样本合成共同 `(X,y)` 并拟合一个模型。 | group/time split、asset ID/base rate、currency/session与样本支配诊断。 | `verified_concept_only` |
| `FORM-RES01-CH08-027` | 同上 §8.5 | rolling standardization试图令跨资产特征近似同分布。 | 同质性必须检验；防同日共享信息和future-window泄漏。 | `verified_concept_only` |
| `FORM-RES01-CH08-028` | 同上 §8.6；`Image00338.jpg`—`Image00360.jpg` | informative/redundant/noise synthetic DGP用于检查三方法已知失效模式。 | 仅验证指定DGP；保存seed、ground truth、相关与interaction机制。 | `verified_concept_only` |
| `FORM-RES01-CH08-029` | 同上；`Image00349.jpg`、`Image00352.jpg` | `1/N_features`均匀MDI线只是展示参考。 | 不是显著性阈值；使用label-permutation/null distribution。 | `verified_concept_only` |
| `FORM-RES01-CH08-030` | 同上全章 | importance证据需fold/regime/asset稳定性、结构保持置乱与嵌套选择。 | 本章只关闭原文概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 9 章

### 第 9 章：超参数搜索、评分目标与嵌套选择证据

- **论证链**：grid search枚举离散参数笛卡尔积并选择平均CV score最高者，randomized search从预设分布抽取固定次数，以计算预算换取更广覆盖；二者都是在同一验证证据上比较候选。purged/embargo splitter可减少候选内部的时间泄漏，却不能抵消候选数量、参数边界、分布、score、seed或模型族反复改变后的selection bias。跨数量级正参数用log-uniform可使每个乘法尺度获得相近抽样机会，但`[a,b]`仍需经济/数值依据。分类score决定优化对象：accuracy忽略置信度，F1聚焦指定positive class且忽略true negative，log-loss惩罚对错误类别的高置信概率；任何一种都不是PnL。书中把概率、样本回报权重和仓位/PnL直接并列，跨越了Forecast到Portfolio/Risk的项目边界。
- **成立条件**：`HyperparameterSearchEvidence`必须保存model/pipeline/library version、search method、完整space/distribution及边界来源、conditional parameter、candidate count、n_iter、seed、resource budget、inner/outer splitter及fold hash、preprocessing、fit/score sample-weight routing、score定义/方向、class label、probability clipping、refit/tie/failure rule、每个候选fold scores、fit status/time和selected candidate。内层purged/embargo只负责选参，外层purged/embargo评估包含搜索在内的完整procedure；最终holdout不参与space、score或模型族选择。搜索前冻结trial budget，搜索后不得只保留best params；参数邻域、seed和calibration在outer predictions上报告。
- **局限与反例**：穷举并不客观，grid粒度和边界决定可见赢家；random search效率依赖分布，固定n_iter也可能遗漏狭窄可行区。log-uniform不适用于零、负值、分类参数或自然线性尺度，极端小/大值还可能导致数值失败。F1在positive label切换、阈值和类别先验变化时不可比，也不评价概率校准；accuracy在不平衡类下可被多数类支配；log-loss对错标和概率0/1极敏感，最优log-loss不保证最佳经济效用。absolute-return sample weight可能放大坏价和不可交易尾部，weighted log-loss仍不是fill-derived PnL。书中的旧sklearn Pipeline、`fit_params`和issue workaround是版本相关历史，不能直接复制。调好后再bagging会新增estimators、sample fraction和seed等搜索维度，不能称为免费稳健化。
- **项目动作**：每个研究问题先定义简单模型与有限搜索空间；将模型族、feature set、score、splitter、参数分布和随机种子都作为trial维度登记。建立nested purged/embargo流程：inner返回candidate与完整score surface，outer只返回选择流程的预测与损失；对失败、timeout、NaN score和缺类fold采用预注册fail-closed规则。分类同时报告proper scoring rule、calibration、class/regime损失和经济cost matrix，不用单一F1/accuracy/log-loss决定策略。实现增加grid count、random seed replay、log-uniform CDF/inverse sampling、zero/negative bounds、conditional parameter、fit/score weight routing、missing class、probability clipping、tie和all-failed fixture。任何outer/holdout反馈不得反向扩大space。
- **禁止直接采用**：不得复制`F1`、`neg_log_loss`、SVC的`C/gamma`范围、`1E-3—1E3`、25次random search、10-fold、bagging包装或书中Pipeline子类；不得把best CV score、best params、更多搜索或purged CV称为无选择偏差。不得以全样本class balance/return weight、outer fold或holdout调整score、threshold、search distribution和模型族。分类概率只属于Forecast置信度，不直接决定仓位；Portfolio/Risk仍依据风险预算、相关性、容量和成本生成TargetPosition。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **L3 原文概念复核完成**：`FORM-RES01-CH09-001`—`030`已回到原EPUB核对；只关闭source semantics为`verified_concept_only`，未执行snippet、nested search、library routing、scoring fixture或项目实现。

## Ch09 原始 EPUB 复核

- 复核范围：Ch09从 `OEBPS/text00001.html#filepos0000476302` 跨文件延续至 `OEBPS/text00002.html#filepos0000503563`，共10个图像资源，其中4个公式、4个代码snippet、2个图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。grid/random search、log-uniform CDF/PDF、multiclass log-loss与Pipeline sample-weight workaround均已核对。
- 结论边界：旧sklearn API/issue、SVC参数范围、search次数、历史图和书中“概率对应仓位”类比均不迁移；概率只属于Forecast，Portfolio/Risk独立决定TargetPosition。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH09-001` | EPUB `text00001.html#filepos0000476302` §9.2 | grid search在预定义候选集合上最大化用户指定CV score。 | 固定score方向、fold聚合、tie/failure；outer评估完整选择procedure。 | `verified_concept_only` |
| `FORM-RES01-CH09-002` | 同上 §9.2 | 无conditional参数时，grid候选数是各离散取值数的笛卡尔积。 | 保存实际展开candidate manifest与fit count。 | `verified_concept_only` |
| `FORM-RES01-CH09-003` | 同上；`Image00387.jpg` | 每个候选在PurgedKFold/embargo inner folds上拟合与评分。 | purge不消除selection bias；transform fold-local并使用outer evaluation。 | `verified_concept_only` |
| `FORM-RES01-CH09-004` | 同上；`Image00387.jpg`、`Image00389.jpg` | 旧Pipeline示例通过step-name参数把sample weight路由给最终estimator。 | 按锁定library/version做metadata routing contract test。 | `verified_concept_only` |
| `FORM-RES01-CH09-005` | 同上；`Image00387.jpg` | tuned estimator再包bagging会新增estimator count、sample/feature fraction与seed。 | 作为新增trial维度，不称为默认稳健化。 | `verified_concept_only` |
| `FORM-RES01-CH09-006` | 同上 §9.2，交叉引用Ch03 | precision为predicted positives中true positives比例。 | 固定positive class、zero division与sample weights。 | `verified_concept_only` |
| `FORM-RES01-CH09-007` | 同上 §9.2，交叉引用Ch03 | recall为actual positives中被识别比例。 | 核验censor、abstain与class weighting语义。 | `verified_concept_only` |
| `FORM-RES01-CH09-008` | 同上 §9.2，交叉引用Ch03 | F1是precision与recall的调和平均。 | 固定positive label、threshold与zero-division policy。 | `verified_concept_only` |
| `FORM-RES01-CH09-009` | 同上 §9.2 | 全预测多数类可获高accuracy/低loss，却可能recall为0。 | 与prior、balanced metric、proper score与cost matrix比较。 | `verified_concept_only` |
| `FORM-RES01-CH09-010` | 同上 §9.2 | accuracy和log-loss对label重命名对称，F1依赖positive class。 | 保存class order/positive label；禁止跨实验静默切换。 | `verified_concept_only` |
| `FORM-RES01-CH09-011` | 同上；`Image00389.jpg` | Pipeline fit参数命名与路由是library-version contract。 | 旧workaround不采用；锁定版本验证每step接收/拒绝权重。 | `verified_concept_only` |
| `FORM-RES01-CH09-012` | 同上 §9.3；`Image00391.jpg` | random search以固定 `n_iter` 控制抽取和评估候选数量。 | 保存seed、draws、duplicates、failed draws与实际fit count。 | `verified_concept_only` |
| `FORM-RES01-CH09-013` | 同上 §9.3 | random search不会像grid那样因各维取值数直接乘法膨胀预算。 | 分布不合理时无关维度仍稀释有效draws。 | `verified_concept_only` |
| `FORM-RES01-CH09-014` | 同上 §9.3.1 | `log X~Uniform(log a,log b)` 定义区间 `0<a<b` 的log-uniform。 | 保存log base、单位、positive-domain与bounds来源。 | `verified_concept_only` |
| `FORM-RES01-CH09-015` | 同上；`Image00394.jpg` | 区间内CDF为 `[log x-log a]/[log b-log a]`，区间外为0或1。 | 核验边界连续性、monotonicity与base invariance。 | `verified_concept_only` |
| `FORM-RES01-CH09-016` | 同上；`Image00569.jpg` | 区间内PDF为 `1/[x log(b/a)]`，区间外为0。 | 积分归一化、边界及overflow/underflow fixture。 | `verified_concept_only` |
| `FORM-RES01-CH09-017` | 同上 §9.3.1 | inverse-CDF采样等价于 `X=a(b/a)^U`。 | seed replay、endpoint convention与empirical-CDF test。 | `verified_concept_only` |
| `FORM-RES01-CH09-018` | 同上；`Image00403.jpg` | CDF的log base因分子分母同比缩放而抵消。 | 多base解析/数值对照；避免极端数值失稳。 | `verified_concept_only` |
| `FORM-RES01-CH09-019` | 同上；`Image00401.jpg`、`Image00406.jpg` | log-uniform对相等乘法区间赋予相等概率质量。 | 不用于零、负、categorical或自然线性尺度参数。 | `verified_concept_only` |
| `FORM-RES01-CH09-020` | 同上 §9.3.1 | 分布族及a/b边界本身也是研究者选择。 | 预注册来源；边界或分布变化计入trial ledger。 | `verified_concept_only` |
| `FORM-RES01-CH09-021` | 同上 §9.4；`Image00409.jpg` | multiclass log-loss为one-hot标签与预测概率对数乘积的负样本均值。 | 固定normalization、class/sample weights、log base与clipping。 | `verified_concept_only` |
| `FORM-RES01-CH09-022` | 同上 §9.4 | `Y_{n,k}`是每行一个1的one-hot target matrix。 | 核验class order、missing class、soft/censored label与shape。 | `verified_concept_only` |
| `FORM-RES01-CH09-023` | 同上；`Image00411.jpg` | log-loss对错误类别的高置信概率施加更大惩罚。 | 概率0/1 clipping、错标与calibration敏感性。 | `verified_concept_only` |
| `FORM-RES01-CH09-024` | 同上 §9.4 | sample-weighted log-loss按事件权重聚合classification loss。 | 固定分母/归一化；return weight不等于utility或PnL。 | `verified_concept_only` |
| `FORM-RES01-CH09-025` | 同上 §9.4 | neg-log-loss只是对raw loss取负，使较大score更优。 | scorer sign、raw loss和report字段分离，避免双重取负。 | `verified_concept_only` |
| `FORM-RES01-CH09-026` | 同上 §9.4 | accuracy忽略预测概率置信度与calibration。 | 与log-loss、Brier、calibration和cost matrix并列。 | `verified_concept_only` |
| `FORM-RES01-CH09-027` | 同上 §9.4 | 书中把side、probability和return weight类比为PnL输入。 | 概率只进Forecast；Portfolio/Risk另定risk/capacity/cost sizing。 | `verified_concept_only` |
| `FORM-RES01-CH09-028` | 同上 §9.4 | classification score与fill-derived PnL不是同一目标。 | 可做cost-sensitive validation，但不得用回测赢家反调score。 | `verified_concept_only` |
| `FORM-RES01-CH09-029` | 同上全章 | model family、space、score、seed、refit与post-bagging共同构成trial count。 | 保存全部candidate/失败/访问；outer/holdout不反馈inner设计。 | `verified_concept_only` |
| `FORM-RES01-CH09-030` | 同上全章 | 合格调参证据需nested purged validation、固定预算与candidate manifest。 | 本章只关闭原文概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 10 章

### 第 10 章：预测置信度、目标仓位与执行限价的职责隔离

- **论证链**：本章展示方向判断正确仍可能因路径和初始仓位过大而亏损，因此尝试把信号强度映射为`[-1,1]`暴露。方法包括：按long/short active signal并发度拟合分布或做容量预算；把分类概率相对随机基准的z-statistic经Normal CDF映射到连续size；对仍在label horizon内的active bets取平均；按step离散化减少jitter；以及按forecast price与market price差的sigmoid动态调整target，并反推所谓breakeven limit。稳定启发是仓位应随证据强度、并发观点和成本变化，而不是一次性满仓。但书中把label probability直接称为bet size、把triple-barrier forecast反推为price target、再由target生成limit price，跨越了Strategy、Portfolio/Risk和OMS三层，不能原样迁移。
- **成立条件**：`ForecastToTargetEvidence`必须保存forecast_id、instrument、side、horizon/expiry、expected return/unit、probability与calibration version、uncertainty、correlation group、active-set规则、aggregation、risk budget、vol/covariance、capacity、cost、current position、constraint result、target position和版本。多个active forecasts按经济观点和共享风险去重，不能把重叠事件数当独立breadth。概率到exposure的任何curve、step/hysteresis、最大仓位和更新频率只在训练/validation确定，并做calibration、regime与成本压力。Portfolio/Risk输出TargetPosition后，OMS才根据bid/ask、depth、tick/lot、urgency、TIF、price protection和fill probability形成OrderIntent；limit price不能由研究公式直接写入订单。
- **局限与反例**：分类概率受base rate、calibration、distribution shift和model selection影响，不等于expected return、赔率或可承担风险；Normal z映射也没有自动经济最优性。并发signal可能是同一趋势、相同feature或重叠label的重复表达，数量增多不代表更强独立证据；mixture fit和历史最大并发对regime敏感。active-bet平均会混合不同起点、horizon、side、质量和失效条件，且用未来`t1`定义实时active state可能泄漏，实际只能使用当时已知expiry/closure。离散化可降换手，也会延迟风险退出并制造阈值跳变。动态price-target假定forecast单位可与现价比较、曲线单调且forecast不变；真实gap、spread、partial fill、费用、impact、stale quote和target revision都会使“不能实现亏损”失效。限价位于现价与forecast之间也不保证成交或盈利。
- **项目动作**：将书中所有size先降级为`normalized_exposure_candidate`，由Portfolio/Risk用预期收益、置信区间、波动、相关、现有仓位、风险预算、杠杆、保证金、容量和成本统一求解。并发聚合保存每个forecast的live-known start/expiry、lineage和correlation cluster，比较latest-only、equal-active、confidence-weighted和risk-aware聚合，但不据holdout选赢家。step discretization改为带成本阈值和hysteresis的no-trade region，并确保risk breach可立即越过。OMS limit-price模型独立验证fill probability、adverse selection和机会成本，不继承label barrier。增加uncalibrated probability、identical signals、opposite horizons、stale forecast、gap-through、partial fill、tick/lot rounding、risk limit、restart和ledger reconciliation fixture。
- **禁止直接采用**：不得复制Gaussian-mixture并发映射、历史最大并发预算、Normal CDF probability curve、active-bet简单平均、`d=.2/.01/.05/.1`、sigmoid/power curve、`m*=.95,x=10,Q=100`或书中limit price；不得把probability、label、normalized size、TargetPosition、OrderIntent和fill混为一体。不得用完整未来`t1`判断实时active、把并发事件数称独立breadth、把离散化称成本证据或把公式限价称breakeven/无损。Strategy不得直接调用broker/exchange或生成订单，PnL仍只由fills、positions和cash ledger推导。当前不运行新回测、不查看holdout、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH10-001`—`030`已回到原EPUB关闭为`verified_concept_only`。公式、4段旧代码和3张图均未执行；本章只提供研究概念与反例入口，不构成仓位算法、OrderIntent、回测、holdout或promotion证据。

## Ch10 原始 EPUB 复核

- 复核范围：Ch10从 `OEBPS/text00002.html#filepos0000503563` 至Ch11起点 `OEBPS/text00002.html#filepos0000536917`；共45个图像资源，其中38个公式/符号、4个代码snippet、3张图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。并发CDF/预算、二元与多类概率z映射、active平均、离散化、sigmoid及其逆函数、平均限价、宽度校准和power alternative均已逐项核对。
- 结论边界：源码和图未执行；书中“bet size”统一降级为暴露候选。Strategy仅输出Forecast，Portfolio/Risk决定TargetPosition，OMS独立决定OrderIntent；公式限价不保证成交、盈亏平衡或无损。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH10-001` | EPUB `text00002.html#filepos0000503563` §10.2 | 归一化size `m∈[-1,1]`，符号表示方向、绝对值表示强度。 | 仅作`normalized_exposure_candidate`；capital base和风险上限由Portfolio/Risk定义。 | `verified_concept_only` |
| `FORM-RES01-CH10-002` | 同上 §10.2 | 相同终点方向判断可因建仓路径不同而产生不同PnL。 | 用fills/positions/cash/cost重算；方向正确不证明sizing正确。 | `verified_concept_only` |
| `FORM-RES01-CH10-003` | 同上 §10.3 | 净并发度为active long数减active short数。 | active只使用当时已知closure/expiry，并按lineage去重。 | `verified_concept_only` |
| `FORM-RES01-CH10-004` | 同上 §10.3；`Image00413.jpg` | 净并发CDF相对`F[0]`分段映射到正负归一化暴露。 | mixture仅训练期拟合；保存regime、tail、identifiability与零点处理。 | `verified_concept_only` |
| `FORM-RES01-CH10-005` | 同上 §10.3；`Image00417.jpg`—`Image00422.jpg` | long/short并发各除历史最大值后相减形成budget size。 | 历史最大值不直接采用；验证零分母、outlier和regime漂移。 | `verified_concept_only` |
| `FORM-RES01-CH10-006` | 同上 §10.4 | meta-model给出的分类概率被用作size输入。 | 概率先保存calibration与side，仅形成Forecast字段。 | `verified_concept_only` |
| `FORM-RES01-CH10-007` | 同上 §10.4；`Image00424.jpg` | 二分类无信息零假设为`P[x=1]=1/2`。 | 非均衡prior或非对称成本时基准必须由训练fold定义。 | `verified_concept_only` |
| `FORM-RES01-CH10-008` | 同上；`Image00426.jpg` | 二分类概率z为`(p-1/2)/sqrt[p(1-p)]`。 | 检查`p→0/1`数值边界、校准和分布漂移。 | `verified_concept_only` |
| `FORM-RES01-CH10-009` | 同上 §10.4；Figure 10.1 | `m=2Φ(z)-1`把z映射至`[-1,1]`。 | 单调与对称不等于经济最优；不得直接成为仓位或订单。 | `verified_concept_only` |
| `FORM-RES01-CH10-010` | 同上；`Image00429.jpg`—`Image00434.jpg` | K类概率和为1，无信息基准为`1/K`。 | 保存class order、missing class与fold-local prior。 | `verified_concept_only` |
| `FORM-RES01-CH10-011` | 同上；`Image00429.jpg`—`Image00434.jpg` | 最大类别概率相对`1/K`按Bernoulli方差标准化为z。 | 核验tie、K变化和概率校准；z仅为置信强度候选。 | `verified_concept_only` |
| `FORM-RES01-CH10-012` | 同上；`Image00000.jpg` | 多类强度经CDF后乘预测label符号得到signed size。 | side、confidence和target拆字段，label不得兼作仓位。 | `verified_concept_only` |
| `FORM-RES01-CH10-013` | 同上 §10.4 | probability-to-size映射隐含概率已校准且base rate稳定。 | 保存calibration fold/version、reliability和regime drift。 | `verified_concept_only` |
| `FORM-RES01-CH10-014` | 同上 §10.5；Snippet 10.2 | 时点t的active set由当时尚未结束的forecast事件组成。 | 实时状态禁止读取未来first-touch `t1`。 | `verified_concept_only` |
| `FORM-RES01-CH10-015` | 同上 §10.5；Snippet 10.2 | active bets的size在时点t取算术平均。 | 验证空集、异方向/期限/质量与duplicate lineage。 | `verified_concept_only` |
| `FORM-RES01-CH10-016` | 同上 §10.5 | active平均分母是当时有效事件数。 | 事件数不是独立breadth；需比较correlation/risk-aware aggregation。 | `verified_concept_only` |
| `FORM-RES01-CH10-017` | 同上 §10.5；`Image00014.jpg` | 连续size按step `d`四舍五入离散化。 | 固定rounding mode并测负值、half-step与浮点边界。 | `verified_concept_only` |
| `FORM-RES01-CH10-018` | 同上；Snippet 10.3 | 离散结果clip回`[-1,1]`。 | 覆盖overshoot、`d`不整除1及risk-exit越级。 | `verified_concept_only` |
| `FORM-RES01-CH10-019` | 同上 §10.6 | price divergence定义为forecast price减当前market price。 | 固定价格类型、单位、horizon、timestamp与可交易性。 | `verified_concept_only` |
| `FORM-RES01-CH10-020` | 同上；`Image00210.jpg` | sigmoid为`m[ω,x]=x/sqrt(ω+x²)`。 | 检查量纲、odd symmetry、`ω`边界和极限；只作curve候选。 | `verified_concept_only` |
| `FORM-RES01-CH10-021` | 同上；`Image00193.jpg` | 归一化暴露乘最大头寸Q并整数化得到target。 | Q由风险、容量、保证金及lot约束确定，不是策略常数。 | `verified_concept_only` |
| `FORM-RES01-CH10-022` | 同上；`Image00285.jpg` | 当市场价趋近forecast price时sigmoid target趋近0。 | forecast可更新；成本、趋势延续和期限需独立建模。 | `verified_concept_only` |
| `FORM-RES01-CH10-023` | 同上 §10.6 | 调整需求是target position减current position。 | delta只属于Portfolio需求，OMS决定是否交易与拆单。 | `verified_concept_only` |
| `FORM-RES01-CH10-024` | 同上；`Image00361.jpg` | inverse为`L[f,ω,m]=f-m sqrt[ω/(1-m²)]`。 | 覆盖`|m|→1`奇点、单位与单调性；不得直接生成限价。 | `verified_concept_only` |
| `FORM-RES01-CH10-025` | 同上；`Image00339.jpg` | 多单位调仓的limit price按中间target level对应价格取平均。 | 平均值不等于fill、breakeven或无损价格。 | `verified_concept_only` |
| `FORM-RES01-CH10-026` | 同上；`Image00396.jpg` | 给定校准点`(x,m*)`，`ω=x²(m*^{-2}-1)`。 | 测`m*→0/1`、`x=0`和单位缩放；校准点必须预注册。 | `verified_concept_only` |
| `FORM-RES01-CH10-027` | 同上 §10.6 | 书中以单调target曲线主张价格趋近forecast时不会实现亏损。 | 以gap、spread、cost、partial fill、stale forecast和revision反例拒绝普遍保证。 | `verified_concept_only` |
| `FORM-RES01-CH10-028` | 同上 §10.7；`Image00081.jpg`、`Image00104.jpg`、`Image00489.jpg` | power alternative为`sgn(x)|x|^ω`，在归一化域内以ω控制曲率。 | 检查domain、`x=0`、`ω=0/1`、端点和导数；不迁移书中参数。 | `verified_concept_only` |
| `FORM-RES01-CH10-029` | 同上 §10.5—10.7 | averaging与discretization是换手启发式，不含显式成本最优化。 | 改用带成本阈值和hysteresis的no-trade challenger，risk breach可立即越过。 | `verified_concept_only` |
| `FORM-RES01-CH10-030` | 同上全章 | 概率到落地必须分离Forecast、Portfolio/Risk、OMS和Fill/Ledger。 | 本章只关闭来源概念；不构成实现、回测、holdout或promotion证据。 | `verified_concept_only` |

## 已完成 L2：第 11 章

### 第 11 章：回测的否证职责、完整试验账本与PBO边界

- **论证链**：历史回测是在已实现单一路径上模拟“若当时运行”的反事实，不是可重复控制实验，也不能证明因果或未来收益。它可以检查仓位、换手、成本敏感性、极端路径和工程一致性，却同时暴露于survivorship、look-ahead、事后叙事、data snooping、成本、outlier、借券/融资、margin和隐藏风险。即使这些错误全部修复，只要研究者在同一数据上运行大量候选并只展示赢家，仍会产生selection bias。章节提出CSCV/PBO：把所有`N`个trial的同步绩效列组成`T×N`矩阵，按时间切成偶数个block，枚举一半block作IS、另一半作OOS；每次选出IS赢家，观察它在OOS候选中的相对rank并转为logit，统计logit小于0的频率作为过拟合概率估计。它评估的是“选择流程是否把IS赢家推到OOS下半区”，不是策略真实成功概率。
- **成立条件**：`BacktestSelectionEvidence`必须保存research question、冻结前规格、data/code/cost/execution版本、candidate/trial/search lineage、失败/timeout/人工排除、每次结果查看与后续动作、同步performance series、common calendar、missing/no-trade处理、metric及其subsample可估条件、CSCV block定义、组合数、每次IS winner、OOS rank/logit和PBO uncertainty。trial矩阵必须包含所有实质候选而非只含最终邻域；不同频率策略对齐时保留cash/no-position、exposure和缺失语义，不能通过downsample抹去风险。回测实现与研究者分权，结果只返回预注册的pass/fail与风险分布，不提供用于继续调参的隐含提示；holdout由独立owner控制并记录访问。
- **局限与反例**：PBO要求候选在同步period上可比，block内顺序保留但block之间仍可能受长记忆、regime、重叠与共同市场因子影响；block数和绩效metric也是选择维度。Sharpe在短subsample、非正态、serial correlation和不同exposure下可能不稳定；不同交易频率强行聚合到common index会改变风险。候选高度相关时名义N不等于有效trial count，漏记早期试验会严重低估PBO。单一walk-forward可被反复针对，但随机组合也不能创造新历史或替代前向数据。书中“bagging变差说明原策略过拟合”“全资产类模型更可信”“模拟大量场景更难过拟合”都只是启发式：共同bias、错误生成器或反复调scenario同样会过拟合。失败后“从头开始”若删除历史，反而清洗了trial ledger。
- **项目动作**：把回测作为冻结候选的falsification gate：先登记经济机制、baseline、成功/失败阈值、数据/成本/风险假设和trial budget，再运行一次版本化流程；失败可以开启新candidate_id，但必须引用旧候选和结果，不得重置试验计数。建立append-only `TrialSelectionLedger`，记录feature、label、model、params、split、cost、manual decision、report hash和holdout access。对高风险候选在样本允许时计算PBO/DSR或等价selection adjustment，同时报告raw与effective trials、IS/OOS rank decay、block/regime敏感性；样本不足则明确不可估，不以0替代。任何正面结果仍需PIT、purge/embargo、成本、execution replay、ledger reconciliation、前向observe-only和current-HEAD gate逐项独立成立。
- **禁止直接采用**：不得把“flawless backtest”、保守成本、walk-forward、PBO低、bagging稳定、跨资产有效或scenario数量多描述为证明/ready；不得复制`S=16`、12,870组合、Sharpe metric、50/50 block或任一PBO阈值。不得仅把最终候选装入trial矩阵，不得删除失败、重命名同一想法逃避计数、按PBO结果改block/metric后只报告赢家，也不得让回测者向研究员泄露holdout方向。当前不运行新回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，所有安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH11-001`—`030`已回到原EPUB关闭为`verified_concept_only`。CSCV block、组合数、IS winner、OOS rank、logit和PBO积分均已核对；原书正文把`C(16,8)`写成12,780，数学结果应为12,870，登记为source typo。公式与图未执行，不构成回测、holdout或promotion证据。

## Ch11 原始 EPUB 复核

- 复核范围：Ch11从 `OEBPS/text00002.html#filepos0000536917` 至Ch12起点 `OEBPS/text00002.html#filepos0000576018`；共28个图像资源，其中26个公式/符号、2张结果图，无可执行代码snippet。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。同步trial矩阵、CSCV分块与组合、IS/OOS score、相对rank、logit及PBO积分均已逐项核对。
- 结论边界：原书数字“12,780”与其组合公式冲突，`C(16,8)=12,870`；登记为source typo。PBO只诊断选择流程在给定矩阵/metric/block设计下的排名衰减，不能证明策略未来成功或替代PIT、成本、执行、账本、前向观察与current-HEAD gate。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH11-001` | EPUB `text00002.html#filepos0000536917` §11.2 | backtest是在一条已实现历史路径上的反事实模拟，不是可重复实验。 | 只作sanity/falsification；不称因果或未来收益证明。 | `verified_concept_only` |
| `FORM-RES01-CH11-002` | 同上 §11.3 | 同一数据上重复trial会提高偶然赢家与false discovery风险。 | 保存名义/有效trial及完整selection procedure。 | `verified_concept_only` |
| `FORM-RES01-CH11-003` | 同上 §11.2 | 用当前universe回填过去造成survivorship bias。 | constituent、delisting、bankruptcy与entry/exit必须PIT。 | `verified_concept_only` |
| `FORM-RES01-CH11-004` | 同上 §11.2 | release、distribution delay和backfill错位造成look-ahead。 | 保存event/release/receive/decision time与revision序列。 | `verified_concept_only` |
| `FORM-RES01-CH11-005` | 同上 §11.2—11.4 | testing-set训练与事后叙事把结果反馈进研究。 | 冻结规格、独立结果owner及append-only decision ledger。 | `verified_concept_only` |
| `FORM-RES01-CH11-006` | 同上 §11.2 | 历史模拟无法完全观测真实交易成本与订单簿交互。 | fee/spread/impact/delay/fill/机会成本分层并报告不确定性。 | `verified_concept_only` |
| `FORM-RES01-CH11-007` | 同上 §11.2 | 少数outlier可主导回测结果。 | 报告收益集中、leave-one-event/period和tail replay。 | `verified_concept_only` |
| `FORM-RES01-CH11-008` | 同上 §11.2 | short cash product依赖borrow availability、fee和inventory。 | 缺PIT locate/borrow证据时fail-closed或降级long-only。 | `verified_concept_only` |
| `FORM-RES01-CH11-009` | 同上 §11.5 | backtest overfitting被定义为多次回测后的selection bias。 | 与单模型fit overfit分开，评估对象是选择流程。 | `verified_concept_only` |
| `FORM-RES01-CH11-010` | 同上 §11.5 | 必须记录每次回测以估计最终赢家的选择风险。 | 失败、排除、重命名、score和holdout访问不可删除。 | `verified_concept_only` |
| `FORM-RES01-CH11-011` | 同上 §11.6 | 单一walk-forward测试路径可被反复针对而过拟合。 | 时间顺序正确仍不是独立holdout；每次反馈计trial。 | `verified_concept_only` |
| `FORM-RES01-CH11-012` | 同上 §11.6 | N个trial的同步绩效列组成`M∈R^{T×N}`。 | 所有候选使用共同rows/calendar，保留no-trade和missing语义。 | `verified_concept_only` |
| `FORM-RES01-CH11-013` | 同上 §11.6 | 不同交易频率需下采样到共同索引后比较。 | 显式保存aggregation、cash/no-position、exposure和成本，不只保留交易点。 | `verified_concept_only` |
| `FORM-RES01-CH11-014` | 同上 §11.6 | M沿时间轴切为偶数S个互斥等尺寸block。 | 预注册S、calendar、remainder、regime和long-memory压力。 | `verified_concept_only` |
| `FORM-RES01-CH11-015` | 同上；`Image00630.jpg` | 每个block矩阵尺寸为`(T/S)×N`。 | 核验T整除、row order、同步列与缺失策略。 | `verified_concept_only` |
| `FORM-RES01-CH11-016` | 同上；`Image00226.jpg`、`Image00229.jpg` | 选`S/2`个block作IS，共`C(S,S/2)`种组合。 | 使用精确整数计算并识别complement pair依赖。 | `verified_concept_only` |
| `FORM-RES01-CH11-017` | 同上 §11.6 | 原书称`S=16`产生12,780组合，但`C(16,8)=12,870`。 | 登记source typo；不得照录或据此迁移S。 | `verified_concept_only` |
| `FORM-RES01-CH11-018` | 同上；`Image00232.jpg`—`Image00239.jpg` | 组合c中的`S/2`个block拼成`J`，尺寸为`(T/2)×N`。 | 核验shape、row order与block identity。 | `verified_concept_only` |
| `FORM-RES01-CH11-019` | 同上；`Image00242.jpg`—`Image00247.jpg` | OOS矩阵`J̄`是M中J的row complement，尺寸同为`(T/2)×N`。 | 测完整覆盖、互斥、complement pair和顺序。 | `verified_concept_only` |
| `FORM-RES01-CH11-020` | 同上 §11.6 | 在J的每个trial列上计算IS score vector R。 | metric须能在subsample估计；预注册NaN、少量bet与tie规则。 | `verified_concept_only` |
| `FORM-RES01-CH11-021` | 同上；`Image00250.jpg`、`Image00252.jpg` | `n*=argmax_n{R_n}`选出IS赢家。 | tie不得查看OOS打破；winner rule写入trial manifest。 | `verified_concept_only` |
| `FORM-RES01-CH11-022` | 同上；`Image00256.jpg`—`Image00264.jpg` | 在`J̄`上用同一metric形成OOS score vector `R̄`。 | 不得改变normalization、重新选metric或反馈拟合。 | `verified_concept_only` |
| `FORM-RES01-CH11-023` | 同上；`Image00267.jpg`—`Image00282.jpg` | IS赢家`n*`的OOS score在`R̄`中转换为相对rank `ω̄_c∈(0,1)`。 | 固定rank方向、tie方法、端点和N不足处理。 | `verified_concept_only` |
| `FORM-RES01-CH11-024` | 同上 §11.6 | rank percentile表达IS赢家在OOS候选集合的位置。 | 候选高度相关时名义percentile不等于独立证据比例。 | `verified_concept_only` |
| `FORM-RES01-CH11-025` | 同上；`Image00286.jpg` | `λ_c=log[ω̄_c/(1-ω̄_c)]`，中位rank对应0。 | 核验sign、tie和endpoint；禁止静默clipping。 | `verified_concept_only` |
| `FORM-RES01-CH11-026` | 同上；`Image00295.jpg` | 所有组合的logit形成归一化经验密度`f(λ)`。 | 报告组合依赖、block sensitivity和不确定性。 | `verified_concept_only` |
| `FORM-RES01-CH11-027` | 同上；`Image00298.jpg` | `PBO=∫_{-∞}^{0}f(λ)dλ`，即IS赢家落入OOS下半区的概率质量。 | 给置信区间与设计敏感性，不设通用阈值。 | `verified_concept_only` |
| `FORM-RES01-CH11-028` | 同上 §11.6 | block内保持原时间顺序，组合发生在block层。 | 不据此假定block独立；压力长记忆、重叠和regime cluster。 | `verified_concept_only` |
| `FORM-RES01-CH11-029` | 同上全章 | PBO评估给定trial universe与选择规则，不是单策略未来成功概率。 | 不替代PIT、cost、execution、holdout、forward或promotion gate。 | `verified_concept_only` |
| `FORM-RES01-CH11-030` | 同上全章；止于 `#filepos0000576018` | 合格回测证据需冻结规格、完整trial矩阵、选择调整与独立gate。 | 仅关闭来源概念；不运行回测、不查看holdout、不形成promotion结论。 | `verified_concept_only` |

## 已完成 L2：第 12 章

### 第 12 章：CPCV组合路径、相关性与历史解释边界

- **论证链**：walk-forward按真实时间先训练后测试，适合与paper历史重放核对，但只有一条路径、早期训练样本少且易被反复定向。普通purged CV让每段只作一次test并可用其余时期训练，提供等训练量的stress/inferential scenario，却不是当时可部署的历史绩效。CPCV再把`T`个观测按时间切为`N`组，每个split选择`k`组作test、其余作train，枚举`C(N,k)`个split；每组出现于`C(N-1,k-1)`个test split，因此可把测试预测重组为`φ=C(N-1,k-1)`条覆盖所有group的路径。每个split都要purge相交label并在test早于部分train时embargo。输出从单一Sharpe扩展为路径绩效分布，但路径复用了同一观测、feature和训练集合，属于相关重采样诊断，不是新增市场历史。
- **成立条件**：`CPCVEvidence`必须保存T/N/k、group边界与remainder、calendar/session、split组合、train/test IDs、label/feature信息区间、purged/embargo IDs、model/preprocessing/seed、每个group-split预测、path assignment、每条路径的完整positions/fills/cash-derived metric、路径相关矩阵、effective path count和distribution summary。N/k、metric、path assembly和失败规则在结果前冻结；所有fold-local transform与权重按各split重拟合。WF与CPCV报告分别标注`historical_replay`和`counterfactual_cross_fit_scenario`，不得拼接成同一实盘曲线。若group太短、purge后训练不足、路径缺段或同一regime支配，应fail-closed而非提高N制造路径数。
- **局限与反例**：CV/CPCV用测试期之后的数据训练模型，所以某条路径不能解释为当时真实可运行的财富过程，也不能与paper ledger逐时点一一核对。CPCV只重组已有观测顺序，没有模拟新价格、流动性、成交或制度状态；共享group导致路径高度相关，名义`φ`远大于有效路径数。书中把路径均值方差在`φ`增大、相关趋零时降到0，并进一步声称无selection bias/恢复true Sharpe，是理想化等相关极限；现实中`φ`有上限、相关不为0、Sharpe本身不稳定，且研究者仍可选择N/k/metric/strategy。reverse-history破坏因果、corporate action、session和market-impact语义，只能作敏感性诊断。普通CV“知道除测试期外一切”的压力场景也可能使用未来regime，不代表对真正未知未来的泛化。
- **项目动作**：仅对已冻结且数据足够的高风险候选增加CPCV challenger，并保留标准historical WF作为可部署性/reconciliation基线。预注册少量N/k，计算split数、训练比例、名义路径数、purge后样本和计算预算；path assignment必须deterministic且每条路径每group恰有一个测试预测。报告完整路径收益、drawdown、turnover、cost、年份/regime和相关矩阵，使用effective path count/cluster bootstrap或保守区间，不以`1/sqrt(φ)`假装独立。CPCV、WF和普通CV任何方法被看过后都计入trial ledger；只报告其中最好者属于selection bias。增加group remainder、k=1、k=2、N=6、complement、duplicate/missing prediction、purge boundary、path coverage、seed replay和correlated-path variance fixture。
- **禁止直接采用**：不得复制`k=2`、`N=φ+1`、`N=T`、半样本训练、目标1000路径、Sharpe metric或任意N/k；不得把CPCV路径称为独立样本、新历史、paper replay、future scenarios、true Sharpe或无selection bias。不得按结果增加路径、改变group/metric或只展示有利路径，也不得因路径分布稳定绕过PIT、execution、ledger、forward observation与current-HEAD gate。当前不运行CPCV/新回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH12-001`—`030`已回到原EPUB关闭为`verified_concept_only`。group remainder、split/path count、训练比例、WF warm-up、expected Gaussian maximum与相关路径均值方差均已核对；公式和路径图未执行，不构成CPCV运行、回测、holdout或promotion证据。

## Ch12 原始 EPUB 复核

- 复核范围：Ch12从 `OEBPS/text00002.html#filepos0000576018` 至Ch13起点 `OEBPS/text00002.html#filepos0000609384`；共22个图像资源，其中20个公式/符号、2张CPCV split/path分配图，无代码snippet。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。WF warm-up、CPCV group/split/path identity、训练比例、Gaussian expected maximum、trial winner inflation和相关路径均值方差均已逐项核对。
- 结论边界：CPCV路径共享观测、group和训练集合，`φ`是名义路径数而非独立样本数。书中“相关趋零、路径趋多即可恢复true Sharpe并消除selection bias”是理想化极限；实际还受有限`φ`、相关、非正态、metric与N/k/strategy选择影响。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH12-001` | EPUB `text00002.html#filepos0000576018` §12.2 | WF每个决策只使用此前可得训练观测。 | 仍需PIT、fold-local state与label purge；顺序不单独证明无泄漏。 | `verified_concept_only` |
| `FORM-RES01-CH12-002` | 同上 §12.2 | train事件的label span跨入test时必须purge。 | 复用Ch07 information-interval predicate与边界fixture。 | `verified_concept_only` |
| `FORM-RES01-CH12-003` | 同上 §12.2 | 书中称WF无需test后embargo，因为train总在test之前。 | 仅对严格因果pipeline成立；全样本transform仍可泄漏。 | `verified_concept_only` |
| `FORM-RES01-CH12-004` | 同上；`Image00307.jpg`—`Image00314.jpg` | 首半数决策为`(T-t0)/2`，平均训练量为`T/4+3t0/4`，占比`1/4+3t0/(4T)`。 | 固定decision indexing与warm-up；报告各时点实际训练量。 | `verified_concept_only` |
| `FORM-RES01-CH12-005` | 同上 §12.3 | 普通CV对每个test period使用其余period训练。 | 标记为counterfactual cross-fit，不称历史可部署绩效。 | `verified_concept_only` |
| `FORM-RES01-CH12-006` | 同上 §12.3 | 每个观测恰属于一个普通CV test fold。 | 核验覆盖、互斥、fold size与missing prediction。 | `verified_concept_only` |
| `FORM-RES01-CH12-007` | 同上 §12.4.1 | 前N-1组大小为`floor(T/N)`，末组吸收remainder。 | 测T<N、calendar gap和稳定边界；组不能跨错误session语义。 | `verified_concept_only` |
| `FORM-RES01-CH12-008` | 同上；`Image00317.jpg` | k个test group的split数为`C(N,N-k)=C(N,k)`。 | exact combinatorial fixture并预估fit预算/overflow。 | `verified_concept_only` |
| `FORM-RES01-CH12-009` | 同上；`Image00320.jpg` | 所有split的test group-slot总数为`k C(N,k)`。 | 与枚举incidence matrix逐项比对。 | `verified_concept_only` |
| `FORM-RES01-CH12-010` | 同上 §12.4.1 | 对称枚举使每个group进入相同数量的test split。 | 验证每组incidence一致，不代表市场regime均衡。 | `verified_concept_only` |
| `FORM-RES01-CH12-011` | 同上；`Image00323.jpg` | `φ[N,k]=k C(N,k)/N=C(N-1,k-1)`。 | 验证整数性、incidence与deterministic path assignment。 | `verified_concept_only` |
| `FORM-RES01-CH12-012` | 同上；`Image00326.jpg`、Figure 12.1 | `N=6,k=2`时`C(6,4)=15`个split。 | 仅作组合fixture，示例参数不得迁移。 | `verified_concept_only` |
| `FORM-RES01-CH12-013` | 同上；Figure 12.1—12.2 | `φ[6,2]=5`，每组测试5次并分配到5条完整路径。 | 每路径每group一次、每test cell仅消费一次。 | `verified_concept_only` |
| `FORM-RES01-CH12-014` | 同上 §12.4.1 | 每个split的raw训练比例为`θ=1-k/N`。 | purge后有效比例更低；报告raw/effective train size。 | `verified_concept_only` |
| `FORM-RES01-CH12-015` | 同上 §12.4.1 | 书中实践约束`k≤N/2`以保留至少半数group训练。 | 不是充分样本条件；按class/regime/ESS fail-closed。 | `verified_concept_only` |
| `FORM-RES01-CH12-016` | 同上 §12.4.1 | N或k增大可提高名义φ，但改变训练量与组合预算。 | 同时报告split/fit count、训练比例、purge损失与依赖。 | `verified_concept_only` |
| `FORM-RES01-CH12-017` | 同上 §12.4.2 | 每个split对train/test label interval执行purge。 | 与Ch07统一splitter/hash并测试多test group包围情形。 | `verified_concept_only` |
| `FORM-RES01-CH12-018` | 同上 §12.4.2 | 当test早于部分train时对后续train施加embargo。 | embargo依据feature/label依赖预注册，不复制固定比例。 | `verified_concept_only` |
| `FORM-RES01-CH12-019` | 同上；Figure 12.2 | group-split test预测被确定性组装为φ条路径。 | 每group一次、无duplicate/missing并保存assignment checksum。 | `verified_concept_only` |
| `FORM-RES01-CH12-020` | 同上 §12.4.2 | 每条路径产生一个metric，形成而非单点的绩效分布。 | 由positions/fills/cash重算并报告路径相关矩阵。 | `verified_concept_only` |
| `FORM-RES01-CH12-021` | 同上 §12.4.3 | `k=1`时`φ[N,1]=1`，CPCV退化为普通CV。 | split数仍为N；验证只能组装一条覆盖路径。 | `verified_concept_only` |
| `FORM-RES01-CH12-022` | 同上 §12.4.3 | `k=2`时`φ[N,2]=N-1`。 | 核验N=2/3/6边界与组合identity。 | `verified_concept_only` |
| `FORM-RES01-CH12-023` | 同上；`Image00367.jpg` | `N=φ+1,k=2`是目标路径数的书中启发式，split数为`C(N,N-2)`。 | 不直接采用；还需样本、purge、依赖和计算约束。 | `verified_concept_only` |
| `FORM-RES01-CH12-024` | 同上 §12.5；`Image00346.jpg` | IID标准正态样本最大值以两个Normal quantile和Euler常数加权近似，并有`sqrt(2 log I)`上界。 | 仅在IID、standard Normal、large-I近似条件下使用。 | `verified_concept_only` |
| `FORM-RES01-CH12-025` | 同上；`Image00432.jpg`、`Image00536.jpg` | 若`y_i/σ[y_i]~Z`且真实均值0，最大估计Sharpe的期望仍为正。 | 候选相关、非正态与effective trial count需另行调整。 | `verified_concept_only` |
| `FORM-RES01-CH12-026` | 同上 §12.5 | FWER、FDR、PBO等选择调整需要完整trial count。 | 漏记或未知trial时不得给低selection-risk结论。 | `verified_concept_only` |
| `FORM-RES01-CH12-027` | 同上 §12.5 | 单策略的φ个path metric定义均值`μ_i`与方差`σ_i²`。 | 固定sample/weight定义并报告effective path count。 | `verified_concept_only` |
| `FORM-RES01-CH12-028` | 同上；`Image00594.jpg` | 等方差、平均相关`ρ̄_i`下，`Var(μ_i)=σ_i²[1+(φ-1)ρ̄_i]/φ`。 | 用实际covariance矩阵复算，禁止默认`ρ̄=0`。 | `verified_concept_only` |
| `FORM-RES01-CH12-029` | 同上；`Image00552.jpg`—`Image00845.jpg`、`Image00006.jpg` | 书中由`ρ̄<1`推导降方差，并在`φ→∞,ρ̄→0`时声称零方差；但`φ≤φ[T,T/2]`。 | 共享数据、有限φ和选择自由使“true Sharpe/无bias”不能作现实保证。 | `verified_concept_only` |
| `FORM-RES01-CH12-030` | 同上全章；止于 `#filepos0000609384` | 合格CPCV证据需组合覆盖、依赖度量、trial调整与历史用途隔离。 | 仅关闭来源概念；不运行CPCV、不查看holdout、不形成promotion结论。 | `verified_concept_only` |

## 已完成 L2：第 13 章

### 第 13 章：合成生成过程、退出规则网格与模型风险

- **论证链**：章节把已持有position的退出规则参数化为profit-taking与stop-loss，并指出在单一历史上枚举阈值、最大化Sharpe会针对outlier过拟合。替代方案是假设每个机会的价格/PnL服从离散Ornstein–Uhlenbeck过程，先用完整历史估计mean-reversion、long-run equilibrium与shock scale，再从观测初始条件生成大量路径；对每个threshold pair施加profit/stop/vertical first-touch，计算terminal PnL与Sharpe heatmap，选全局或条件最优规则。该流程不再直接选择某条历史噪声，但仍在估计DGP、参数、网格和模拟随机数上做模型选择。OU只是教育性生成器；随机游走、跳跃、regime shift、stochastic volatility、spread/impact和非同步成交都可能改变所谓最优区域。
- **成立条件**：`SyntheticRuleEvidence`必须保存economic question、position/exposure单位、entry/available time、生成器family/version、训练窗口、PIT input hash、参数估计与covariance/CI、residual diagnostics、stationarity/break tests、initial-state sampling、path count/horizon、seed/common-random-number policy、barrier grid、first-touch/tie/gap规则、cost/fill model、每节点完整distribution、Monte Carlo error和selection adjustment。参数只在训练fold拟合并冻结到validation generator；不能全样本估计后称OOS。至少建立random walk、OU、jump diffusion、regime-switch/heteroskedastic和empirical block bootstrap challenger，使用同一rule set比较。输出是failure surface、sensitivity和candidate bounds，不直接给OMS退出参数。
- **局限与反例**：OU stationarity、Gaussian IID shocks、恒定φ/σ、连续可成交和相同机会分布都是强假设；φ接近1时half-life和equilibrium估计极不稳定，结构break会让历史平均无意义。用全历史估计DGP把未来regime信息写进模拟；大量synthetic paths只减少条件于该错误模型的Monte Carlo error，不能减少model bias。网格上的max Sharpe仍受节点数、范围、步长、horizon、seed和metric选择影响；同一模拟样本反复调规则也会过拟合。书中省略成本以展示对称性，会系统性改变窄profit/宽stop区域；first-touch不等于fill。高达3、9、12的非年化Sharpe是指定无成本DGP结果，不是市场证据。章节的“唯一最优规则”只是conjecture，实验支持和“几乎必然优于历史过拟合规则”均未构成证明。
- **项目动作**：synthetic只用于回答“若DGP/成本/执行满足这些假设，规则如何失效”，不用于发现或批准alpha。每个候选先做参数/模型不确定性传播：从训练期parameter posterior/bootstrap抽样，再跨generator family、initial state、regime、jump、spread/impact和fill quality形成scenario cube；报告rule rank stability、broad plateau、tail loss、holding time、barrier touch mix和worst-case，而非只报argmax。网格、paths、seed和generator variants全部计入trial ledger，validation只检验预注册规则区域。实现增加φ=0/near±1、constant path、single jump、same-bar dual touch、vertical-only、cost-dominates-edge、parameter recovery、seed replay、common-random-number、Monte Carlo convergence与dimension fixture。
- **禁止直接采用**：不得复制OU、Gaussian shocks、σ=1、20×20网格、100,000 paths、maxHP=100、任一half-life/forecast、Sharpe argmax或图中profit/stop区域；不得把synthetic称unseen market data、OOS、历史回放、真实fill、paper或promotion evidence。不得从全样本估计OU、忽略参数不确定性/成本后选规则，也不得把heatmap平滑、路径多或conjecture称唯一最优。退出规则仍由Portfolio/Risk与OMS结合真实风险和执行约束审批，PnL由fill/position/cash ledger推导。当前不运行模拟/回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH13-001`—`030`已回到原EPUB关闭为`verified_concept_only`。barrier exit、Sharpe objective、overfit定义、OU过程/分布、OLS参数映射和half-life均已核对；2段旧代码和25张热图未执行，历史阈值、path count、horizon与Sharpe均不得迁移。

## Ch13 原始 EPUB 复核

- 复核范围：Ch13从 `OEBPS/text00002.html#filepos0000609384` 至Ch14起点 `OEBPS/text00002.html#filepos0000682127`；共113个图像资源，其中86个公式/参数图、2段代码snippet、25张heatmap。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。退出barrier、Sharpe网格、overfit不等式、离散OU、有限期Gaussian分布、OLS恢复、half-life及25组历史结果均已逐项审阅。
- 结论边界：synthetic只回答“给定DGP时规则如何表现”；路径数只降低条件Monte Carlo误差，不降低错误DGP的model bias。书中`σ=1`、20×20网格、100,000 paths、maxHP=100及heatmap最优区域均为教育性案例。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH13-001` | EPUB `text00002.html#filepos0000609384` §13.2 | 单机会MtM PnL为`π_{i,t}=m_i(P_{i,t}-P_{i,0})`。 | 核验side与units；真实PnL仍由fills/positions/cash/cost推导。 | `verified_concept_only` |
| `FORM-RES01-CH13-002` | 同上；`Image00025.jpg`—`Image00582.jpg` | 首次满足`π≥π̄>0`或`π≤π̲<0`时退出，且`π̲<π̄`。 | 增加vertical、同step双触达、gap与不可成交规则。 | `verified_concept_only` |
| `FORM-RES01-CH13-003` | 同上；`Image00585.jpg` | terminal opportunity PnL取`π_{i,T_i}`。 | first-touch mark不等于fill；加入fees/slippage/partial fill。 | `verified_concept_only` |
| `FORM-RES01-CH13-004` | 同上；`Image00597.jpg` | trading rule参数化为`R={π̲,π̄}`。 | barrier单位、side、horizon与风险约束显式化。 | `verified_concept_only` |
| `FORM-RES01-CH13-005` | 同上；`Image00600.jpg` | `R*=argmax_{R∈Ω} SR_R`，其中SR为terminal PnL均值除标准差。 | 全网格、metric、失败节点和访问次数计入trial ledger。 | `verified_concept_only` |
| `FORM-RES01-CH13-006` | 同上；`Image00612.jpg` | 若IS最优规则的期望OOS Sharpe低于Ω中规则的中位数，则称其overfit。 | 保存expectation/median universe并连接PBO/selection adjustment。 | `verified_concept_only` |
| `FORM-RES01-CH13-007` | 同上 §13.4；`Image00647.jpg` | 离散OU：`P_t=(1-φ)E_0[P_T]+φP_{t-1}+σε_t`。 | 固定time step、price单位、参数语义和as-of估计窗口。 | `verified_concept_only` |
| `FORM-RES01-CH13-008` | 同上 §13.4 | shock假设`ε_t~N(0,1)`且IID。 | 检验tail、jump、heteroskedasticity和serial dependence。 | `verified_concept_only` |
| `FORM-RES01-CH13-009` | 同上；`Image00051.jpg` | 代入position映射得到PnL AR过程。 | 核验m、entry和equilibrium的维度及符号。 | `verified_concept_only` |
| `FORM-RES01-CH13-010` | 同上；`Image00142.jpg` | 有限期PnL为Gaussian，均值含`(1-φ)E_0[P_T]Σφ^j-P_0`。 | 测t=0/1/large-t及`φ→±1`边界。 | `verified_concept_only` |
| `FORM-RES01-CH13-011` | 同上；`Image00142.jpg` | 条件方差为`m_i²σ²Σ_{j=0}^{t-1}φ^{2j}`。 | 用closed-form几何和对照并检查数值稳定性。 | `verified_concept_only` |
| `FORM-RES01-CH13-012` | 同上 §13.4 | 固定参数离散OU平稳充要条件为`|φ|<1`。 | structural break和time-varying参数需独立诊断。 | `verified_concept_only` |
| `FORM-RES01-CH13-013` | 同上；`Image00691.jpg`、`Image00670.jpg` | 回归形式为`P_t-E_0[P_T]=φ(P_{t-1}-E_0[P_T])+ξ_t`并堆叠X/Y/Z。 | 机会拼接、panel dependence、intercept与PIT窗口留证。 | `verified_concept_only` |
| `FORM-RES01-CH13-014` | 同上；`Image00748.jpg` | `φ̂=cov[Y,X]/cov[X,X]`。 | 报告unit-root/small-sample bias、weights与cluster uncertainty。 | `verified_concept_only` |
| `FORM-RES01-CH13-015` | 同上；`Image00748.jpg` | residual写为`ξ̂=Y-Z-φ̂X`，隐含equilibrium由Z项给出。 | `φ≈1`时long-run mean不稳定，必须给CI与break sensitivity。 | `verified_concept_only` |
| `FORM-RES01-CH13-016` | 同上；`Image00748.jpg` | `σ̂=sqrt(cov[ξ̂,ξ̂])`。 | 固定ddof/time-step并压力heteroskedasticity与outlier。 | `verified_concept_only` |
| `FORM-RES01-CH13-017` | 同上；`Image00842.jpg`、`Image00079.jpg`、`Image00168.jpg` | profit/stop候选笛卡尔积形成规则mesh。 | 范围、步长、无效节点和节点数均计trial。 | `verified_concept_only` |
| `FORM-RES01-CH13-018` | 同上 §13.5 | 以`{σ̂,φ̂}`和观测初始状态生成conditional Monte Carlo paths。 | 保存seed、parameter draw和common-random-number policy。 | `verified_concept_only` |
| `FORM-RES01-CH13-019` | 同上；`Image00437.jpg` | 最大holding period形成vertical barrier。 | `100`不迁移；按经济horizon/session定义并报告censor。 | `verified_concept_only` |
| `FORM-RES01-CH13-020` | 同上 §13.5 | 同一批paths用于所有rule nodes的first-touch比较。 | common paths降低比较噪声但使节点相关，保存covariance。 | `verified_concept_only` |
| `FORM-RES01-CH13-021` | 同上；`Image00500.jpg`、`Image00837.jpg` | 每个node用terminal PnL样本估计Sharpe。 | 报告MC CI、非正态、成本和selection adjustment。 | `verified_concept_only` |
| `FORM-RES01-CH13-022` | 同上；`Image00686.jpg` | mesh argmax给出条件于DGP与初始状态的规则。 | 只作candidate；报告plateau与rank stability，不批准单点。 | `verified_concept_only` |
| `FORM-RES01-CH13-023` | 同上；`Image00027.jpg`、`Image00463.jpg` | 给定profit target后在对应slice选择stop-loss。 | forecast uncertainty与风险约束进入诊断；不直接写入OMS。 | `verified_concept_only` |
| `FORM-RES01-CH13-024` | 同上；`Image00052.jpg`—`Image00075.jpg` | 给定最大stop-loss后在可行slice选择profit-taking。 | 风险上限不是优化变量，simulation不得放宽。 | `verified_concept_only` |
| `FORM-RES01-CH13-025` | 同上；`Image00521.jpg` | `0<φ<1`时half-life `τ=-log(2)/log(φ)`。 | 固定时间单位并测`φ≤0`、`φ→1`与数值稳定性。 | `verified_concept_only` |
| `FORM-RES01-CH13-026` | 同上；`Image00631.jpg` | inverse mapping为`φ=2^{-1/τ}`。 | round-trip与单位fixture；τ网格不是经验事实。 | `verified_concept_only` |
| `FORM-RES01-CH13-027` | 同上 §13.6；Figures 13.1—13.25 | heatmap完全条件于forecast、half-life、σ、horizon和无成本DGP。 | 跨parameter posterior和generator family报告，阈值/Sharpe不迁移。 | `verified_concept_only` |
| `FORM-RES01-CH13-028` | 同上 §13.5—13.6 | 大path count只降低给定DGP下的Monte Carlo error。 | 分离MC SE、parameter uncertainty与generator misspecification。 | `verified_concept_only` |
| `FORM-RES01-CH13-029` | 同上 §13.6 | 书中省略交易成本以保持图形对称。 | fee/spread/impact/fill/opportunity cost必须进入scenario cube。 | `verified_concept_only` |
| `FORM-RES01-CH13-030` | 同上全章；止于 `#filepos0000682127` | 合格synthetic证据需DGP竞争、参数不确定性、成本与失败面。 | 仅关闭来源概念；不运行模拟/回测、不查看holdout或形成promotion结论。 | `verified_concept_only` |

## 已完成 L2：第 14 章

### 第 14 章：绩效口径、收益集中与试验调整统计

- **论证链**：章节把评价拆成一般特征、未调风险绩效、runs/drawdown、execution shortfall、风险效率、分类和归因。AUM、leverage、capacity、long ratio、bet frequency、holding period和turnover描述策略可运行形态；PnL/TWRR、hit/miss和long PnL描述结果；正负收益与月份的normalized HHI揭示集中，drawdown和time-under-water揭示路径痛苦；fee/slippage与profit-per-turnover揭示成本余量。Sharpe把超额均值除以波动，PSR用track length、skew和kurtosis估计超过benchmark Sharpe的概率，DSR再把benchmark提高到多trial下预期最大值。分类score只隔离meta-model统计表现，风险归因只描述暴露来源。整套面板用于发现脆弱性，而不是从大量指标里挑一个最好看的数。
- **成立条件**：`PerformanceMetricEvidence`必须保存metric/version、currency、AUM/capital base、return clock、annualization、risk-free/benchmark、external cash flow timing、fills/positions/cash ledger hash、fee/slippage/borrow/funding、bet segmentation、trade/turnover definition、sample count/effective count、serial dependence、skew/kurtosis estimator、trial count/effective trials和confidence method。PnL必须从fills、positions和cash推导并含terminal liquidation；TWRR明确cash-flow subperiod；Sharpe同时报告原频率与依赖调整，PSR/DSR保存非年化input、benchmark、N及候选相关。DD/TuW从同一wealth series与HWM定义计算。所有指标报告完整面板、fold/path/regime分布与缺失原因。
- **局限与反例**：年度bet数、trade数和return observations都不是独立样本；position连续同side合并为一个bet也可能掩盖多次决策。long ratio接近0.5不是所有market-neutral策略的必要条件，underlying correlation也不能单独区分beta与动态hedge。TWRR消除external cash-flow timing影响，但不能修复错误估值或不可成交mark。normalized HHI依赖bet切分与符号，集中正收益可能是趋势策略结构，不应机械惩罚；DD/TuW对起点、频率和wealth定义敏感。annualized Sharpe乘`sqrt(a)`依赖IID，金融收益常有autocorrelation、heteroskedasticity和重叠。PSR/DSR是近似统计量，短样本skew/kurtosis极不稳定；DSR书中`N`指独立trials，现实需有效trial count。0.95不是通用promotion阈值。F1在退化类别下可能未定义，交换正负label只为提高score会破坏业务语义。
- **项目动作**：建立单一metrics builder，从不可变ledger生成wealth、returns、bets、turnover、cost和exposure，再派生所有指标；禁止各报告自行重算。最低面板加入gross/net/long-short PnL、AUM/leverage/capacity、bet/trade/effective counts、holding/turnover、cost components、HHI+/HHI-/time、DD/TuW、raw/dependent Sharpe、PSR/DSR inputs、calibration/class metrics和risk/regime attribution。对收益集中执行leave-one-period/event与top-contribution，Sharpe执行HAC/block bootstrap或等价依赖敏感性，PSR/DSR对effective trials、skew/kurtosis和track length做区间。metric阈值、选择和新增指标都计入trial ledger；不得在结果后换频率、benchmark或bet定义。
- **禁止直接采用**：不得复制long ratio 0.5、95% DD/TuW、PSR/DSR 0.95、IID annualization、Sharpe benchmark、HHI解释、F1 positive-label切换或任何GIPS片段作为当前完整规范；不得把trade/bet/path数称独立样本，不得只报annualized Sharpe、赢家metric或未披露trial的DSR。不得从mark-to-market近似而非ledger生成PnL，也不得把分类score、risk attribution或cost余量称promotion evidence。当前不运行回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH14-001`—`030`已回到原EPUB关闭为`verified_concept_only`。TWRR、normalized HHI、Sharpe、PSR、DSR expected-max threshold、分类公式与退化边界均已核对；4段旧代码和3张图未执行，书中0.95、95-percentile与IID年化均不得迁移。

## Ch14 原始 EPUB 复核

- 复核范围：Ch14从 `OEBPS/text00002.html#filepos0000682127` 跨文件至Ch15起点 `OEBPS/text00003.html#filepos0000741410`；共48个图像资源，其中41个公式/符号、4段代码snippet、3张图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。TWRR、HHI、DD/TuW、Sharpe/PSR/DSR、分类score与归因流程均已逐项审阅。
- 结论边界：所有绩效指标必须来自同一fills/positions/cash ledger与预注册return clock。PSR/DSR是依赖track length、非正态估计与trial假设的近似统计量；DSR原式中的N假设独立trial，现实候选相关时必须使用完整ledger和依赖敏感性。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH14-001` | EPUB `text00002.html#filepos0000682127` §14.3 | average AUM以long/short dollar position绝对值描述资本尺度。 | 固定cash、derivative notional/delta与time weighting。 | `verified_concept_only` |
| `FORM-RES01-CH14-002` | 同上 §14.3 | leverage可按平均gross dollar position除平均AUM估计。 | ratio-of-averages与average-of-ratios分开，加入margin/funding。 | `verified_concept_only` |
| `FORM-RES01-CH14-003` | 同上 §14.3 | capacity是仍达到目标risk-adjusted performance的最高AUM。 | 绑定impact、turnover、liquidity和不确定性，不视为历史常数。 | `verified_concept_only` |
| `FORM-RES01-CH14-004` | 同上 §14.3；Snippet 14.1—14.2 | flatten或flip划分bet，trade count不等于bet count。 | 测partial scale、zero crossing、multi-asset和decision lineage。 | `verified_concept_only` |
| `FORM-RES01-CH14-005` | 同上 §14.3 | annual turnover为年度成交美元额相对平均AUM。 | 锁定one/two-way、gross/net、FX与derivative口径。 | `verified_concept_only` |
| `FORM-RES01-CH14-006` | 同上 §14.4 | total PnL含收益、成本与terminal liquidation。 | 只从fills/positions/cash ledger推导。 | `verified_concept_only` |
| `FORM-RES01-CH14-007` | 同上 §14.4 | hit ratio为正PnL bets占比，并配合hit/miss平均payoff。 | 固定zero PnL、dependence、weights与net-cost口径。 | `verified_concept_only` |
| `FORM-RES01-CH14-008` | 同上 §14.4.1；`Image00757.jpg` | `r_{i,t}=π_{i,t}/K_{i,t}`，π含price/accrual/trade项，K含dirty-price capital与ramp-up。 | 复算external-flow timing、clean/dirty、accrual与transaction average。 | `verified_concept_only` |
| `FORM-RES01-CH14-009` | 同上；`Image00273.jpg` | lifetime growth为`φ_{i,T}=Π_{t=1}^T(1+r_{i,t})`。 | 测`r=-1`、missing subperiod、精度与cash-flow边界。 | `verified_concept_only` |
| `FORM-RES01-CH14-010` | 同上；`Image00368.jpg` | annualized geometric return为`R_i=φ_{i,T}^{1/y_i}-1`。 | 固定elapsed-year day count与nonpositive wealth处理。 | `verified_concept_only` |
| `FORM-RES01-CH14-011` | 同上 §14.5.1；`Image00444.jpg` | 正负bet returns分别按各自绝对总额归一为weights。 | 测空集、单点、符号及cost-adjusted returns。 | `verified_concept_only` |
| `FORM-RES01-CH14-012` | 同上；`Image00510.jpg`、`Image00616.jpg` | raw HHI为归一化weights平方和。 | 核验weights sum、n=1和floating precision。 | `verified_concept_only` |
| `FORM-RES01-CH14-013` | 同上；`Image00510.jpg`、`Image00616.jpg` | normalized HHI为`(Σw²-1/n)/(1-1/n)`，均匀映射0、单点映射1。 | n≤1显式NA，不用0掩盖无样本。 | `verified_concept_only` |
| `FORM-RES01-CH14-014` | 同上 §14.5.1 | 月份bet counts可同样形成时间集中度。 | 固定calendar/session、零月份与观察窗。 | `verified_concept_only` |
| `FORM-RES01-CH14-015` | 同上 §14.5.2；Figure 14.1 | DD是相邻HWM之间的峰值至谷值损失。 | 固定dollar/percentage、起点与未恢复episode。 | `verified_concept_only` |
| `FORM-RES01-CH14-016` | 同上 §14.5.2；Snippet 14.4 | TuW是HWM至重新突破前高的持续时间。 | 区分calendar/trading time并保留未恢复尾段。 | `verified_concept_only` |
| `FORM-RES01-CH14-017` | 同上 §14.6 | slippage比较order时mid与实际fill并按turnover归一。 | side、partial fill、delay、spread、fee和机会成本拆分。 | `verified_concept_only` |
| `FORM-RES01-CH14-018` | 同上 §14.6 | dollar PnL/turnover表示break-even cost余量。 | 测零/小分母、gross/net和capacity scaling。 | `verified_concept_only` |
| `FORM-RES01-CH14-019` | 同上 §14.6 | dollar PnL/execution cost表示成本恶化缓冲。 | 不称可实现倍数；报告cost uncertainty与零分母。 | `verified_concept_only` |
| `FORM-RES01-CH14-020` | 同上 §14.7.1；`Image00297.jpg` | `SR=μ/σ`基于超额收益均值与标准差。 | 保存return clock、risk-free、ddof、overlap和serial dependence。 | `verified_concept_only` |
| `FORM-RES01-CH14-021` | 同上 §14.7.4；`Image00208.jpg` | annualized SR常以原频率SR乘`sqrt(a)`。 | 仅IID成立；必须有HAC/block或直接年度聚合challenger。 | `verified_concept_only` |
| `FORM-RES01-CH14-022` | 同上 §14.7.2；`Image00834.jpg` | PSR为Normal CDF作用于`(SRhat-SR*)sqrt(T-1)`除非正态标准误。 | 使用非年化SR、T、skew、kurtosis并核对符号。 | `verified_concept_only` |
| `FORM-RES01-CH14-023` | 同上；`Image00834.jpg` | PSR分母含`1-γ3hat·SRhat+(γ4hat-1)SRhat²/4`。 | 评估small-sample moments、serial dependence和数值正定。 | `verified_concept_only` |
| `FORM-RES01-CH14-024` | 同上 §14.7.3；`Image00277.jpg` | DSR是以多trial expected-max threshold为benchmark的PSR。 | N与candidate dependence显式留证；不以0.95单独解锁gate。 | `verified_concept_only` |
| `FORM-RES01-CH14-025` | 同上；`Image00372.jpg` | `SR*`由trial SR方差平方根乘两个Normal quantile的Euler加权近似。 | 核验independent/equidistributed/large-N假设与N=1边界。 | `verified_concept_only` |
| `FORM-RES01-CH14-026` | 同上 §14.7.3 | true SR为0时，更多/更分散trial抬高赢家estimated SR。 | 完整trial ledger与effective N；漏记时保持blocked。 | `verified_concept_only` |
| `FORM-RES01-CH14-027` | 同上 §14.7.4 | information ratio以benchmark excess mean除tracking error并年化。 | benchmark/PIT weights、active-return clock与依赖调整留证。 | `verified_concept_only` |
| `FORM-RES01-CH14-028` | EPUB `text00003.html` §14.8；`Image00727.jpg`—`Image00538.jpg` | accuracy、precision、recall与F1由confusion counts定义，退化分母可未定义。 | 固定positive label、abstain与zero-denominator；不得为提分换label语义。 | `verified_concept_only` |
| `FORM-RES01-CH14-029` | 同上 §14.9 | 每个risk class先划互斥category，再比较portfolio与universe-weighted indices。 | 保存PIT category、rescaled weights、overlap residual与非因果边界。 | `verified_concept_only` |
| `FORM-RES01-CH14-030` | 同上全章；止于 `#filepos0000741410` | 合格绩效证据需ledger来源、完整面板、依赖/非正态与trial调整。 | 仅关闭来源概念；不运行回测、不查看holdout或形成promotion结论。 | `verified_concept_only` |

## 已完成 L2：第 15 章

### 第 15 章：命中率、赔率、有效频率与失败概率敏感性

- **论证链**：章节把每个bet简化为win/loss二点分布。对称payoff下，单bet均值为`π(2p-1)`、方差为`4π²p(1-p)`，年度Sharpe只依赖precision `p`与IID bet频率`n`；非对称payoff下，均值、方差和Sharpe再取决于`π+`与`π-`。由目标Sharpe可反解所需precision或频率，展示策略对小幅p、n或payoff变化的脆弱性。随后把未来precision视为随机变量：从历史正负bet估计平均payoff和年度频率，bootstrap指定评估期内的precision分布，计算低于目标Sharpe所需临界`p*`的概率。该量描述在固定二点/IID模型下未达目标的概率，不是破产概率、最大损失概率或完整策略风险。
- **成立条件**：`StrategyViabilityEvidence`必须保存bet segmentation、cost-adjusted outcome、positive/zero/negative规则、payout distribution、calendar frequency、label/position overlap、effective independent bets、target metric/horizon、p/payout/frequency estimator、bootstrap/block scheme、KDE/bandwidth、critical p、failure probability与CI。p、π+/π-和n按fold/regime/asset估计并联合建模，因为threshold、机会筛选、容量和执行会同时改变它们。annualization只能使用有效频率与依赖调整。策略停机条件需同时覆盖calibration drift、payoff erosion、cost/borrow/funding、tail/run、drawdown、data quality和Portfolio风险；`P(p<p*)`只能作为一个diagnostic。
- **局限与反例**：真实bet不是IID、固定二点payoff：收益连续、重尾、serially dependent、重叠且受position sizing和共同市场状态驱动。名义n增大不必提高Sharpe，可能只是同一观点高频切片并增加成本；书中把这称为HFT经济基础过度简化。precision不是市场单独决定，label、threshold、abstention与execution会改变base rate和payoff。PM设定profit/stop与机会频率时会反向改变p、holding和cost，不能ceteris paribus独立优化。普通有放回bootstrap破坏runs/regime，KDE在少量或边界`[0,1]`precision上有偏；large-k Normal近似忽略overdispersion。平均win/loss抹去tail和gap。目标Sharpe及评估年限本身是选择维度，失败概率不能替代PSR/DSR或资本/保证金风险。
- **项目动作**：从ledger生成版本化bet outcomes，并保留连续return与路径，不先压缩成二点；二点模型只作baseline sensitivity。报告break-even/target precision、required effective frequency、payoff ratio与局部/场景敏感性，再用block/bootstrap、beta-binomial或hierarchical regime model估计p分布，并传播payout/cost不确定性。构建viability surface而非单值：p、payoff、effective n、cost和correlation同时受压，标出目标不可达、margin/stop和decommission区域。与PSR/DSR、HHI、run/DD/TuW、calibration和forward observation交叉；任何p阈值或failure probability均预注册并给CI。增加symmetric/asymmetric、p=0/.5/1、zero payoff、negative expectancy、dependent bets、regime shift、block bootstrap、KDE boundary和round-trip fixture。
- **禁止直接采用**：不得复制p=.55/.7、n=52/260/396、Sharpe 2、两年评估、IID binomial、Gaussian mixture/KDE、任一failure阈值或“高频提高n即可成功”；不得把trade/forecast数称独立bets，不得把π+/π-/n视为PM完全可控，也不得把`P(p<p*)`称破产概率、portfolio risk或promotion结论。不得为提高viability调整label/barrier后漏记trial。当前不运行回测/模拟、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH15-001`—`030`已回到原EPUB关闭为`verified_concept_only`。对称/非对称二点mean、variance、Sharpe、implied precision/frequency、bootstrap precision、Normal approximation与failure integral均已核对；`Image00543.jpg`的Normal近似遗漏`floor(nk)`样本量缩放，与前文bootstrap定义矛盾，登记为source formula omission。5段旧代码和3张图未执行，书中0.05、p/n/payoff案例均不得迁移。

## Ch15 原始 EPUB 复核

- 复核范围：Ch15从 `OEBPS/text00003.html#filepos0000741410` 至Ch16起点 `OEBPS/text00003.html#filepos0000774986`；共32个图像资源，其中24个公式/符号、5段代码snippet、3张图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。二点payoff moments、对称/非对称Sharpe、quadratic implied precision、临界p、bootstrap/KDE/Normal近似及failure积分均已逐项审阅。
- 结论边界：`P(p<p*)`只是在固定二点、IID、target和估计方案下未达Sharpe目标的概率，不是破产、drawdown、portfolio VaR或完整strategy failure probability。p、payoff、frequency、cost与threshold现实中联动。原书Normal近似的方差项遗漏`floor(nk)`分母，项目不得照录。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH15-001` | EPUB `text00003.html#filepos0000741410` §15.2 | symmetric bet以p获`+π`、以`1-p`获`-π`。 | 仅作二点baseline；保存cost-adjusted连续outcome与IID假设。 | `verified_concept_only` |
| `FORM-RES01-CH15-002` | 同上 §15.2 | `E[X]=π(2p-1)`。 | 测p=0/.5/1与sample estimator。 | `verified_concept_only` |
| `FORM-RES01-CH15-003` | 同上 §15.2 | symmetric二阶矩`E[X²]=π²`。 | variable/zero payoff时不成立。 | `verified_concept_only` |
| `FORM-RES01-CH15-004` | 同上 §15.2 | `Var[X]=4π²p(1-p)`。 | 与direct moments round-trip并测边界。 | `verified_concept_only` |
| `FORM-RES01-CH15-005` | 同上；`Image00810.jpg` | `θ[p,n]=sqrt(n)(2p-1)/(2sqrt[p(1-p)])`。 | n必须为有效独立bets；p端点奇异，IID年化不迁移。 | `verified_concept_only` |
| `FORM-RES01-CH15-006` | 同上；`Image00414.jpg`、`Image00768.jpg` | target θ的required p为`[1+sqrt(1-n/(θ²+n))]/2`。 | 核验domain、根选择与round-trip。 | `verified_concept_only` |
| `FORM-RES01-CH15-007` | 同上 §15.2 | Sharpe式可反解required n。 | 名义频率不等有效bets；报告整数化与不可达域。 | `verified_concept_only` |
| `FORM-RES01-CH15-008` | 同上 §15.3 | asymmetric bet以p获`π+`、以`1-p`获`π-`且`π-<π+`。 | 不默认符号；连续分布作为主证据。 | `verified_concept_only` |
| `FORM-RES01-CH15-009` | 同上 §15.3 | `E[X]=(π+-π-)p+π-`。 | 使用net-cost payoff并测p边界。 | `verified_concept_only` |
| `FORM-RES01-CH15-010` | 同上 §15.3 | `E[X²]=(π+²-π-²)p+π-²`。 | 核验数值scale与overflow。 | `verified_concept_only` |
| `FORM-RES01-CH15-011` | 同上 §15.3 | `Var[X]=(π+-π-)²p(1-p)`。 | 与direct moments及equal-payout退化比较。 | `verified_concept_only` |
| `FORM-RES01-CH15-012` | 同上；`Image00005.jpg` | asymmetric `θ=sqrt(n)[(π+-π-)p+π-]/[(π+-π-)sqrt(p(1-p))]`。 | 明确effective n、zero variance和payoff units。 | `verified_concept_only` |
| `FORM-RES01-CH15-013` | 同上；`Image00098.jpg` | `π-=-π+`时退化为symmetric Sharpe。 | symbolic/numeric round-trip。 | `verified_concept_only` |
| `FORM-RES01-CH15-014` | 同上 §15.3 | target Sharpe对p形成`ap²+bp+c=0`，系数由n、θ和payoff spread构成。 | 核验discriminant、degenerate spread与所有候选根。 | `verified_concept_only` |
| `FORM-RES01-CH15-015` | 同上；`Image00187.jpg` | valid root为`p=(-b+sqrt(b²-4ac))/(2a)`。 | p须在[0,1]；处理无实根、双根与另一根。 | `verified_concept_only` |
| `FORM-RES01-CH15-016` | 同上 §15.3；Snippet 15.4 | Sharpe式可反解required betting frequency。 | 使用effective independence、ceil与years定义。 | `verified_concept_only` |
| `FORM-RES01-CH15-017` | 同上 §15.3 | break-even p满足`E[X]=0`，即`-π-/(π+-π-)`。 | 加入cost并检查payoff符号与不可达域。 | `verified_concept_only` |
| `FORM-RES01-CH15-018` | 同上 §15.3 | θ对p/n/payoff的变化展示局部脆弱性。 | 参数联动时使用joint scenario surface，不只报偏导。 | `verified_concept_only` |
| `FORM-RES01-CH15-019` | 同上 §15.4 | future precision p被建模为随机变量。 | 使用regime/base-rate/calibration层级模型，不假设固定IID。 | `verified_concept_only` |
| `FORM-RES01-CH15-020` | 同上；`Image00703.jpg`、`Image00111.jpg` | `p_{θ*}=max{p|θ≤θ*}`定义未达target的临界precision。 | target与payout/frequency/cost不确定性共同传播。 | `verified_concept_only` |
| `FORM-RES01-CH15-021` | 同上；`Image00212.jpg` | strategy diagnostic为`P[p<p_{θ*}]`。 | 不称破产、drawdown或portfolio risk。 | `verified_concept_only` |
| `FORM-RES01-CH15-022` | 同上 §15.4.1 | `π-`估计为nonpositive outcomes条件均值。 | 固定zero归属、tail、cost与CI。 | `verified_concept_only` |
| `FORM-RES01-CH15-023` | 同上 §15.4.1 | `π+`估计为positive outcomes条件均值。 | 报告small count、concentration与CI。 | `verified_concept_only` |
| `FORM-RES01-CH15-024` | 同上；`Image00398.jpg` | nominal annual bet frequency为`n=T/y`。 | T必须是bets非trades；另报effective count。 | `verified_concept_only` |
| `FORM-RES01-CH15-025` | 同上 §15.4.1 | k年bootstrap每次抽`floor(nk)`个outcomes。 | 依赖下改block/cluster并传播n/k不确定性。 | `verified_concept_only` |
| `FORM-RES01-CH15-026` | 同上；`Image00464.jpg` | 每次bootstrap precision是正outcomes占比。 | 固定zero、weights、block与seed replay。 | `verified_concept_only` |
| `FORM-RES01-CH15-027` | 同上 §15.4.1 | KDE拟合bootstrap precision分布`f[p]`。 | 处理[0,1] boundary、atoms、bandwidth与Beta challenger。 | `verified_concept_only` |
| `FORM-RES01-CH15-028` | 同上；`Image00543.jpg`、`Image00650.jpg` | 原书写`f[p]~N[p̄,p̄(1-p̄)]`，但前文每次用`floor(nk)`样本，遗漏样本比例方差的`1/floor(nk)`缩放。 | 登记source formula omission；IID近似应核验sample-size scaling，并处理overdispersion/effective n。 | `verified_concept_only` |
| `FORM-RES01-CH15-029` | 同上；`Image00814.jpg` | failure diagnostic为`∫_{-∞}^{pθ*}f[p]dp`。 | 检查support leakage、积分、CI及model comparison。 | `verified_concept_only` |
| `FORM-RES01-CH15-030` | 同上全章；止于 `#filepos0000774986` | 合格strategy-risk证据需连续ledger outcomes、有效bets和联合不确定性。 | 仅关闭来源概念；不运行回测/模拟、不查看holdout或形成promotion结论。 | `verified_concept_only` |

## 已完成 L2：第 16 章

### 第 16 章：协方差误差、层次树与受约束配置边界

- **论证链**：均值—方差与CLA类解依赖协方差逆矩阵，样本协方差的微小误差会在病态矩阵上放大成极端、跳变的配置。HRP尝试以三阶段规避直接求逆：先将相关系数变成距离并按linkage生成层次树，再quasi-diagonalize叶序，最后在树上递归二分；每次用子簇内部的inverse-variance权重估计cluster variance，再把父簇权重按对方cluster variance的倒数比例分给两个子簇。该流程产生long-only、权重和为1的候选，并能在奇异协方差下给出数值结果；但样本相关、窗口、距离、linkage或细小扰动可改变离散树和叶序，因此“不求逆”只消除一种数值放大机制，不等于统计稳健或经济最优。
- **成立条件**：`AllocationEvidence`必须保存PIT universe、availability、return clock、forecast/expected-return版本、covariance estimator、shrinkage、window/half-life、missing处理、distance定义、linkage/tie rule、tree与leaf order、cluster variance、recursive split、raw/rounded weights、cash/short/leverage、turnover、cost、capacity、borrow/funding/margin和全部约束及binding flags。HRP、equal、IVP、shrinkage min-var、risk parity和现有受约束配置必须使用同一输入、rebalance calendar、成本与ledger口径；报告covariance eigenspectrum/condition、树/cluster稳定性、weight L1/turnover、risk contribution、stress loss和净结果，而非只比较方差均值。
- **局限与反例**：HRP仍使用sample covariance及其对角/相关结构；single linkage易出现chaining，其他linkage也会改变树，相关距离只表达线性同动且不含预期收益、尾部、流动性和因果层级。IVP型cluster variance忽略簇内非对角项对局部权重的直接优化，递归二分把离散树当作连续风险结构；树的漂亮图形不证明稳定经济行业或风险因子。原始算法没有处理现金、做空、杠杆、最小/最大仓位、换手、税费、容量、借券、保证金或多期路径。书中Monte Carlo生成过程、资产数、样本长度和“普遍优于”数值依赖任意DGP与比较实现，不能迁移为当前BTC或美股证据。
- **项目动作**：把HRP加入只读allocation challenger harness，而非替换Portfolio/Risk：对同一冻结输入比较equal、IVP、HRP、shrinkage min-var、risk parity和当前受约束配置；预注册window、shrinkage、distance、linkage、rebalance和constraint overlay，所有变体进入trial ledger。执行rolling/regime和输入扰动敏感性，保存cophenetic/cluster co-membership、leaf order、weight L1、turnover、风险贡献、集中度、stress与成本后差异；树不稳定而权重稳定、或反之，都分别报告。增加identity/equicorrelation/block/singular covariance、perfect correlation、tie、asset permutation、missing history、new/delisted asset、zero variance、constraint conflict、rounding和deterministic replay fixture。
- **禁止直接采用**：不得复制书中correlation distance、single linkage、窗口、long-only/full-investment、MC参数或优越性数字作为生产默认；不得声称“不求逆”“可处理奇异矩阵”就等于稳健、分散或适合实盘，也不得把聚类树解释成稳定经济真相。Strategy不得输出HRP订单；组合权重仍由Portfolio/Risk在显式约束下形成TargetPosition，OMS/Execution与Fill/Ledger保持分离。当前不运行新配置回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH16-001`—`030`已回到原EPUB关闭为`verified_concept_only`。两层距离、single linkage、quasi-diagonalization、IVP、cluster variance、recursive split与附录证明均已核对；原书把`N(N+1)/2`独立协方差参数数目误作非奇异样本数下限，登记为source statistical error。8个代码图、9个figure资源与书中Monte Carlo均未执行。

## Ch16 原始 EPUB 复核

- 复核范围：Ch16从 `OEBPS/text00003.html#filepos0000774986` 至Ch17起点 `OEBPS/text00003.html#filepos0000850574`；共77个图像资源，其中53个公式/符号、8个代码图、9个figure资源、7个example矩阵/示意图。
- 来源身份：原EPUB SHA256为 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`。correlation/profile distance、nearest/single linkage、linkage matrix、leaf ordering、cluster IVP/variance/split及IVP附录均已逐项审阅。
- 结论边界：HRP不求逆只避免一种数值放大，不证明统计稳健、经济最优或满足业务约束。原书的`N(N+1)/2`样本下限混淆参数数量与样本协方差秩；其`O(log n)`至`O(n)`复杂度未计covariance、distance与hierarchical clustering，不是端到端复杂度。

| 公式/命题ID | EPUB位置 | 原始命题或推导 | 项目证据映射 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH16-001` | EPUB `text00003.html#filepos0000774986` §16.2 | covariance condition number是最大/最小特征值比。 | 报告PSD修复、零/负数值特征值与完整eigenspectrum。 | `verified_concept_only` |
| `FORM-RES01-CH16-002` | 同上 §16.2 | N节点complete graph有`N(N-1)/2`条无向边。 | 核验N=0/1/2与对角/有向语义。 | `verified_concept_only` |
| `FORM-RES01-CH16-003` | 同上 §16.4.1；`Image00747.jpg`、`Image00841.jpg` | `d_{ij}=sqrt[(1-ρ_{ij})/2]∈[0,1]`。 | 核验ρ边界、missing、PSD修复与clipping。 | `verified_concept_only` |
| `FORM-RES01-CH16-004` | 同上 §16.4.1 | d被要求满足非负、同一性、对称与三角不等式。 | 对估计/修复后的输入逐条件验证。 | `verified_concept_only` |
| `FORM-RES01-CH16-005` | 同上；`Image00167.jpg`、`Image00263.jpg` | profile distance为`dtilde_{ij}=sqrt[Σ_n(d_{n,i}-d_{n,j})²]`。 | 固定是否含自身维度、normalization与missing policy。 | `verified_concept_only` |
| `FORM-RES01-CH16-006` | 同上；`Image00218.jpg` | 每轮选择当前profile distance最小的pair合并。 | tie、asset permutation与deterministic ordering留证。 | `verified_concept_only` |
| `FORM-RES01-CH16-007` | 同上；`Image00549.jpg` | single linkage取新簇与item间成员距离最小值。 | 压力chaining并比较complete/average/Ward challenger。 | `verified_concept_only` |
| `FORM-RES01-CH16-008` | 同上 §16.4.1；`Image00082.jpg` | linkage matrix有N-1行，记录两个子节点、merge distance与cluster size。 | 固定node index、row order和library version。 | `verified_concept_only` |
| `FORM-RES01-CH16-009` | 同上 §16.4.2；Snippet 16.2 | quasi-diagonalization递归展开linkage节点得到叶序。 | 核验完整覆盖、index base、左右tie与置换等价。 | `verified_concept_only` |
| `FORM-RES01-CH16-010` | 同上 Appendix 16.A.2；`Image00568.jpg` | diagonal V下IVP权重与`1/V_{ii}`成比例并归一化。 | 处理zero/negative/missing variance、cash与bounds。 | `verified_concept_only` |
| `FORM-RES01-CH16-011` | 同上 §16.4.3；`Image00440.jpg` | 子簇内部权重为`diag(V)^{-1}/tr[diag(V)^{-1}]`。 | 单元素、零方差及忽略off-diagonal影响留证。 | `verified_concept_only` |
| `FORM-RES01-CH16-012` | 同上；`Image00359.jpg` | cluster variance为`wtilde' V wtilde`。 | covariance对称化、PSD、单位与数值精度核验。 | `verified_concept_only` |
| `FORM-RES01-CH16-013` | 同上；`Image00503.jpg` | 左子簇split factor为`α=1-V_left/(V_left+V_right)`。 | 测zero/negative/infinite variance及方向。 | `verified_concept_only` |
| `FORM-RES01-CH16-014` | 同上 §16.4.3 | 父权重分别乘α与`1-α`递归传播。 | 核验奇数簇、终止、顺序与rounding。 | `verified_concept_only` |
| `FORM-RES01-CH16-015` | 同上；`Image00688.jpg` | 非负split且和为1保持`Σw=1`与long-only simplex。 | constraint overlay后重新验证，负权重扩展另立合同。 | `verified_concept_only` |
| `FORM-RES01-CH16-016` | 同上 Appendix 16.A.2；`Image00423.jpg`、`Image00479.jpg` | unconstrained min-var为`V^{-1}a/(a'V^{-1}a)`。 | 可逆/奇异、shrinkage、pseudoinverse和约束语义分开。 | `verified_concept_only` |
| `FORM-RES01-CH16-017` | 同上 §16.2；`Image00717.jpg` | 原书称至少需`N(N+1)/2`个IID observations才可估计非奇异N维covariance。 | 登记source statistical error：这是独立参数数目；样本协方差秩主要要求有效样本数大于N，并另受依赖/missing影响。 | `verified_concept_only` |
| `FORM-RES01-CH16-018` | 同上 §16.4.1 | N项agglomerative tree经过N-1次merge形成根簇。 | 树压缩会丢信息且依赖distance/linkage。 | `verified_concept_only` |
| `FORM-RES01-CH16-019` | 同上 §16.4 | HRP由clustering、quasi-diagonalization、recursive bisection三阶段组成。 | 保存每阶段输入输出hash与deterministic replay。 | `verified_concept_only` |
| `FORM-RES01-CH16-020` | 同上 §16.5—16.6 | 书中HRP/IVP/CLA比较采用long-only、full-investment约束。 | 所有challenger必须同cash、short、leverage、bounds与cost。 | `verified_concept_only` |
| `FORM-RES01-CH16-021` | 同上 §16.5—16.6 | 权重平方和、最大权重及分散可描述配置集中。 | 与effective names、risk concentration及signed weights分开。 | `verified_concept_only` |
| `FORM-RES01-CH16-022` | 同上 §16.6；Snippet 16.5 | Monte Carlo比较定义协方差DGP、IS估计与OOS实现。 | DGP、seed、trial count、selection和参数不确定性完整登记。 | `verified_concept_only` |
| `FORM-RES01-CH16-023` | 同上 §16.6 | OOS variance由冻结权重与后续realized covariance计算。 | 使用同return clock/window/cost并给CI。 | `verified_concept_only` |
| `FORM-RES01-CH16-024` | 同上 §16.6 | 配置净结果需考虑rebalance引发的turnover与成本。 | 固定turnover、no-trade、spread/impact和capacity。 | `verified_concept_only` |
| `FORM-RES01-CH16-025` | 同上全章 | HRP不显式求逆，因此奇异V仍可产生raw candidate。 | 可生成不等于稳定；测试perfect correlation和zero variance。 | `verified_concept_only` |
| `FORM-RES01-CH16-026` | 同上 §16.7 | 业务约束可在recursive split或raw weights后引入。 | bounds、cash、short、margin、capacity及infeasible状态显式求解。 | `verified_concept_only` |
| `FORM-RES01-CH16-027` | 同上全章 | 原始HRP只用risk structure，不使用expected-return forecast。 | 与forecast-aware基线同输入比较，不事后补alpha叙事。 | `verified_concept_only` |
| `FORM-RES01-CH16-028` | 同上 §16.4—16.7 | distance、linkage、window、rebalance和constraint变体构成trial space。 | 全部变体/失败入ledger，不只保留最佳树。 | `verified_concept_only` |
| `FORM-RES01-CH16-029` | 同上；Figures 16.3—16.8 | dendrogram表达样本距离下的离散嵌套，不是稳定经济因果层级。 | 报告bootstrap co-membership、regime和permutation稳定性。 | `verified_concept_only` |
| `FORM-RES01-CH16-030` | 同上全章；`Image00460.jpg`、`Image00049.jpg`；止于 `#filepos0000850574` | 合格配置证据需同输入基线、约束、成本、树/权重稳定性；书中复杂度只覆盖递归分配而非完整pipeline。 | 仅关闭来源概念；不运行allocation/MC/回测、不查看holdout或形成promotion结论。 | `verified_concept_only` |

## 已完成 L2：第 17 章

### 第 17 章：在线结构突变、爆炸性统计与策略失效审批

- **论证链**：本章把结构变化分成CUSUM与explosiveness两族。Brown–Durbin–Evans以逐步扩展样本的recursive least-squares one-step residual累积偏离检验参数稳定；Chu–Stinchcombe–White直接比较level相对候选起点的标准化偏离，并可向后扫描起点。Chow-type DF假设单一未知break且bubble持续到样本末端；SADF对每个当前终点固定右端、向后扩展多个起点，取right-tail ADF极值，以允许多个bubble/burst周期；QADF/CADF用高分位或条件尾部矩降低单个极值影响，sub/super-martingale测试再尝试多项式、指数和幂趋势。共同逻辑是“当前prefix是否与指定null显著不符”，不是识别真实机制、泡沫原因、可交易方向或未来持续期。
- **成立条件**：`StructuralBreakEvidence`必须保存series/units、raw/log/reciprocal及corporate-action/roll处理、event/bar clock、as-of、warm-up、prefix hash、null/alternative、regression/trend/lag、minimum sample、candidate start/end windows、variance estimator、test statistic、aggregation、critical-value/p-value来源、finite-sample calibration、multiple-testing调整、detected interval、delay、regime/asset稳定性和完整trial ledger。实时值只能由当时可见前缀生成；每个fold独立选择并冻结transform、lag、trend、minimum length、q/v/φ和threshold。策略层必须预先定义warning、risk-reduce、freeze、decommission、retrain与re-entry审批，break证据不得直接转OrderIntent。
- **局限与反例**：recursive CUSUM和level CUSUM对初始点/参考点敏感；向后扫描虽降低单点任意性，却增加相关重复检验。Chow类单break/持续到末端假设会漏掉周期性爆炸；SADF取最大t值对采样频率、timestamp、outlier、lag/trend和minimum window敏感，非标准临界值不能套普通ADF表。QADF/CADF增加q、v、tail regularization等研究自由度，也不能证明“更稳健”会带来增量预测。raw/log/reciprocal分别改变误差、尺度与经济语义；爆炸性可来自roll、split、数据错误、illiquidity、market microstructure或政策跳跃。向后窗口含未来相对起点的信息，若回填为历史feature会泄漏。大量start/end组合计算昂贵，HPC只加速搜索，不修复multiple testing或错误null。
- **项目动作**：建立prefix-only break monitor并与模型/策略状态机分离：先用synthetic known-break、no-break、variance-shift、outlier、gap、roll与correction fixture校准检测延迟和false alarm，再在冻结候选上比较recursive CUSUM、level CUSUM、SADF及简单rolling parameter/residual drift基线。所有窗口、lag、trend、transform、q/v/φ和threshold作为trial维度，报告raw/effective trial、family-wise或FDR/模拟校准、event clustering和跨采样稳定性。命中只产生`break_warning`与证据包；Risk可按预注册规则降风险/冻结，研究员诊断数据、执行、参数或市场机制，批准后以新model/candidate version重训并设置re-entry观察，不覆盖旧历史。
- **禁止直接采用**：不得复制`b_0.05=4.6`、q=.95、v=.025、φ=.5/1、minimum sample、lag/trend、SADF/CADF水平、书中bubble日期、E-mini结果或FLOP数字作为当前默认；不得把价格暴涨/暴跌、right-tail拒绝或统计尖峰称为泡沫定性、反转信号、可持续alpha或promotion evidence。不得用全样本选择transform/threshold后回填实时feature，不得在break后静默重估并宣称仍是同一策略，也不得让检测器直接下单。当前不运行break回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH17-001`—`030`已回到原EPUB关闭为`verified_concept_only`。章节边界为`text00003.html#filepos0000850574`至`#filepos0000901244`，共70个独立图片资源，其中63个公式/符号、4个代码图、3个历史图表；公式并未丢失，而是以图片保存。recursive residual、两类CUSUM、Chow/ADF/SADF、复杂度、log-price动力学、QADF/CADF和SMT均已逐式核对；书中Chow型回归把爆炸备择写成`δ>1`，与`Δy_t=δy_{t-1}D_t+ε_t`及`ρ>1`不一致，应为`δ>0`，登记为source mathematical error。代码、历史图、Monte Carlo临界值和性能数字均未执行。

## Ch17 原始 EPUB 复核

- 来源：原EPUB SHA256 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`，`OEBPS/text00003.html#filepos0000850574`至`#filepos0000901244`。
- 结论边界：这些检验只说明当前前缀相对指定null的统计异常；普通Normal/ADF临界值、书中`b_0.05=4.6`、q/v/φ示例和历史bubble日期均不迁移。任何向后窗口、transform、lag、trend和threshold选择都进入完整trial ledger。

| ID | 原 EPUB 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH17-001` | §17.3.1；`Image00766.jpg` | 基础模型为`y_t=beta_t' x_t+epsilon_t`。 | 保存特征向量、截距、时钟、rank与prefix；不把递归估计当因果变化。 | `verified_concept_only` |
| `FORM-RES01-CH17-002` | 同上；`Image00004.jpg` | 扩展样本产生`beta_hat_(k+1),...,beta_hat_T`路径。 | 初始k、更新顺序、数值求解与as-of必须冻结。 | `verified_concept_only` |
| `FORM-RES01-CH17-003` | 同上；`Image00097.jpg` | one-step residual为`omega_hat_t=(y_t-beta_hat_(t-1)'x_t)/sqrt(f_t)`。 | 预测必须只用`t-1`可见估计；索引和leverage分母需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH17-004` | 同上；`Image00185.jpg` | `f_t=sigma_hat_epsilon^2[1+x_t'(X_t'X_t)^-1x_t]`。 | 原书X索引需在实现中明确训练截止；奇异/近奇异默认fail-closed。 | `verified_concept_only` |
| `FORM-RES01-CH17-005` | 同上；`Image00241.jpg` | recursive-error scale以`1/(T-k)`聚合one-step residual偏差平方。 | 自由度、中心化、异方差与序列依赖不由该式解决。 | `verified_concept_only` |
| `FORM-RES01-CH17-006` | 同上；`Image00280.jpg` | BDE CUSUM为`S_t=sum_(j=k+1)^t omega_hat_j/sigma_hat_omega`。 | 双侧/单侧、起点、reset与边界必须显式登记。 | `verified_concept_only` |
| `FORM-RES01-CH17-007` | 同上正文 | 常参数null下书中写`S_t~N[0,t-k-1]`。 | 这是模型内近似；非Gaussian、异方差和依赖需重校准。 | `verified_concept_only` |
| `FORM-RES01-CH17-008` | §17.3.2；`Image00704.jpg` | level statistic为`S_(n,t)=(y_t-y_n)/(sigma_hat_t sqrt(t-n))`。 | raw/log、起点n、gap和单位必须冻结。 | `verified_concept_only` |
| `FORM-RES01-CH17-009` | 同上；`Image00230.jpg` | scale为`(t-1)^-1 sum_(i=2)^t(Delta y_i)^2`。 | 漂移、异方差和market-clock依赖仍需校准。 | `verified_concept_only` |
| `FORM-RES01-CH17-010` | 同上；`Image00661.jpg` | one-sided boundary为`sqrt(b_alpha+log(t-n))`。 | `b_0.05=4.6`来自特定Monte Carlo，不迁移为默认阈值。 | `verified_concept_only` |
| `FORM-RES01-CH17-011` | 同上；`Image00146.jpg` | 对backward starts取`sup_n S_(n,t)`降低单一参考点依赖。 | 相关窗口增加重复搜索，必须计入effective trials。 | `verified_concept_only` |
| `FORM-RES01-CH17-012` | §17.4.1；`Image00345.jpg`、`Image00276.jpg` | 基础AR(1) null为`rho=1`，备择在候选break后转为`rho>1`。 | 只覆盖单break且持续至样本末端的特定备择。 | `verified_concept_only` |
| `FORM-RES01-CH17-013` | 同上正文 | `D_t[tau*]`在`t<tau*T`为0、之后为1。 | 取整、trim、session gap与online availability需显式化。 | `verified_concept_only` |
| `FORM-RES01-CH17-014` | 同上；`Image00697.jpg` | 回归为`Delta y_t=delta y_(t-1)D_t[tau*]+epsilon_t`。 | 书中写`H1:delta>1`是source error；按`rho=1+delta`应为`delta>0`。 | `verified_concept_only` |
| `FORM-RES01-CH17-015` | 同上；`Image00299.jpg` | 单break DFC以`delta_hat/sigma_hat_delta`构造right-tail统计量。 | t-stat仍需非标准临界值；不得套普通t表。 | `verified_concept_only` |
| `FORM-RES01-CH17-016` | 同上；`Image00533.jpg` | 未知break统计取trim区间各`DFC_tau`的supremum。 | 候选数量、trim和family-wise校准均进入证据。 | `verified_concept_only` |
| `FORM-RES01-CH17-017` | §17.4.2；`Image00740.jpg` | ADF回归含截距、lagged level与L阶lagged differences。 | constant/trend、L、missing与solver语义必须预注册。 | `verified_concept_only` |
| `FORM-RES01-CH17-018` | 同上；`Image00347.jpg`、`Image00513.jpg` | `SADF_t=sup_(t0 in [1,t-tau]) ADF_(t0,t)`。 | 每个t只能使用当前prefix；窗口ties/NaN和minimum length需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH17-019` | 同上正文 | 普通ADF是SADF只保留最长单一窗口的特例。 | 特例关系不代表两者共享同一临界值。 | `verified_concept_only` |
| `FORM-RES01-CH17-020` | §17.4.2.2；`Image00418.jpg`、`Image00020.jpg` | 书中按三角窗口计数给出`O(n^2)`个ADF回归。 | 这是朴素算法模型；实现复杂度、I/O和并行开销另计。 | `verified_concept_only` |
| `FORM-RES01-CH17-021` | 同上；`Image00020.jpg` | 回归数为`sum_(t=tau)^T(t-tau+1)=(T-tau+2 choose 2)`。 | minimum length与端点约定会改变off-by-one。 | `verified_concept_only` |
| `FORM-RES01-CH17-022` | 同上；Table 17.1、`Image00466.jpg`、`Image00284.jpg` | 书中逐矩阵操作展开单次、单更新和全序列FLOPs。 | 只适用于其inverse-based solver；QR/SVD/递推实现与硬件需另测。 | `verified_concept_only` |
| `FORM-RES01-CH17-023` | §17.4.2.1；`Image00792.jpg`—`Image00101.jpg` | raw-price与log-price ADF具有不同尺度/异方差解释。 | transform只能在训练前缀选择，corporate action与roll需先处理。 | `verified_concept_only` |
| `FORM-RES01-CH17-024` | §17.4.2.3；`Image00485.jpg`—`Image00580.jpg` | zero-lag log-price动态递推为固定点加`(1+beta)^t`项。 | 离散时钟、overflow、`beta=-1/0`边界与噪声解释需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH17-025` | 同上；`Image00705.jpg`—`Image00215.jpg` | 书中按`beta<0`、`=0`、`>0`区分steady/unit-root/explosive并给half-life。 | 还需检查`|1+beta|`稳定域、振荡边界和经济语义。 | `verified_concept_only` |
| `FORM-RES01-CH17-026` | §17.4.2.4；`Image00308.jpg`、`Image00446.jpg` | QADF以backward-window ADF集合的q分位替代supremum。 | quantile定义、插值、q搜索与采样敏感性进入trial ledger。 | `verified_concept_only` |
| `FORM-RES01-CH17-027` | 同上；`Image00455.jpg`、`Image00471.jpg` | dispersion为`Q_(q+v)-Q_(q-v)`，且q=1时未定义。 | v约束、atoms和小样本不稳定需显式处理。 | `verified_concept_only` |
| `FORM-RES01-CH17-028` | §17.4.2.5；`Image00495.jpg`、`Image00511.jpg` | CADF以上尾条件均值C与条件二阶矩度量centrality/dispersion，且`C<=SADF`。 | empirical tail、空tail、K、regularization与outlier需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH17-029` | §17.4.3；`Image00746.jpg`—`Image00059.jpg` | SMT比较线性/二次/指数/幂趋势，并以`(t-t0)^phi`惩罚窗口长度。 | φ全范围是trial；绝对t值不提供方向或持续期。 | `verified_concept_only` |
| `FORM-RES01-CH17-030` | 全章；止于`#filepos0000901244` | 合格break证据需prefix、null、窗口、校准、trial与失效状态机。 | 4个代码图、3个历史图和阈值均未执行；不回测、不看holdout、不授权promotion。 | `verified_concept_only` |

## 已完成 L2：第 18 章

### 第 18 章：编码来源、有限样本熵与信息论解释边界

- **论证链**：Shannon entropy是指定离散随机变量平均信息量，mutual information比较联合分布与边际乘积；plug-in estimator用长度w的word经验频率估计entropy rate，依赖stationary/ergodic和`n`远大于`w`。Lempel–Ziv用新substring或最长匹配长度刻画可压缩性，Kontoyiannis类估计器在有限alphabet、stationarity、ergodicity及相应mixing条件下给出渐近结果。连续return必须先编码：binary保留符号而丢幅度/零值，quantile编码在训练内强制近均匀，sigma编码固定数值步长并让稀有码产生尖峰。Gaussian differential entropy、generalized mean/effective number、PCA风险集中与order-flow entropy是进一步映射；它们共享信息论语言，但对象、单位和假设不同。
- **成立条件**：`EntropyFeatureEvidence`必须保存raw series/units、PIT availability、sampling clock、transform、zero/missing/correction处理、encoder family、training-only boundaries、alphabet/version、word/match length、window direction/length、minimum history、estimator/base、normalization、bias correction、output lag、prefix hash、restart state和trial lineage。离散entropy用bits/nats明确log base，Gaussian differential entropy另标continuous density及measurement scale，二者不得直接排名。每个fold重拟合quantile/sigma边界；实时LZ只能消费当前前缀，任何需要中心点右侧字符的对称match必须延迟到全部字符可见或改成经验证的one-sided实现。输出与volatility、autocorrelation、run、imbalance和简单compression基线做同预算增量比较。
- **局限与反例**：plug-in在alphabet/word维度相对样本过大时有严重稀疏与向下偏差；LZ定理是渐近收敛，不保证短消息单调、无偏或跨窗口可比。书中“重复短消息”会人为制造周期结构，删除首bit或反转消息也改变as-of和端点权重，不能作为实时修补。binary删除zero会改变时钟；quantile编码机械抬高边际entropy并可能掩盖幅度/regime变化；sigma若用全样本min/std会泄漏且对outlier敏感。高熵可能只是噪声、measurement error或alphabet过细，低熵可能来自tick size、halt、stale quote或确定性执行。市场效率、泡沫、maximum-entropy black swan与adverse selection叙事都不是由单个entropy值识别；PIN/VPIN映射还依赖订单方向分类、volume clock、到达率与CDF校准。
- **项目动作**：仅建立只读entropy feature challenger：对同一PIT stream比较binary、training-quantile、robust fixed-step和简单sign-run/autocorrelation/realized-vol基线；预注册alphabet、w/n/k、window、log base和estimator，保存每折边界与symbol stream hash。先用constant、periodic、IID Bernoulli、Markov、Gaussian、heavy-tail、outlier、zero-heavy、regime-switch和chunk/restart fixture测偏差、方差、端点、prefix invariance与latency，再报告fold/regime分布和增量。portfolio effective-number只作risk concentration diagnostic，并与weight、factor-risk、marginal contribution和stress共同报告；order-flow entropy在真实tick/L2、方向分类与volume-bar证据缺失时保持blocked。
- **禁止直接采用**：不得复制10/7/5/2字母、message 100、window 100/198、N=256、quantile 10、全样本sigma、standard-Normal 1.42或任何示例熵值；不得重复消息、删除首字符、反转未来后缀或用全样本min/quantile/std构造实时feature。不得把high entropy称效率、low entropy称泡沫，把maximum entropy称最可能盈利路径，或把entropy-CDF称adverse-selection概率。不得把离散entropy与differential entropy混单位，也不得让feature直接输出仓位/订单。当前不运行熵特征回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH18-001`—`030`已回到原EPUB关闭为`verified_concept_only`。章节边界为`text00003.html#filepos0000901244`至`#filepos0000963505`，共65个独立图片资源，其中58个公式/符号、4个代码图、3个图表；公式并未丢失，而是以图片保存。Shannon/MI、plug-in、LZ极限与估计器、编码、Gaussian differential entropy、generalized mean/effective number、PCA concentration及PIN/VPIN均已核对。原书只声称normalized variation of information是由MI派生的metric，未给定义式，登记为source omission；离散熵使用`log2`而Gaussian differential entropy使用自然对数，跨对象比较必须显式单位/尺度。代码、图表、历史阈值和练习均未执行。

## Ch18 原始 EPUB 复核

- 来源：原EPUB SHA256 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`，`OEBPS/text00003.html#filepos0000901244`至`#filepos0000963505`。
- 结论边界：离散entropy rate、continuous differential entropy、portfolio diversity与order-flow proxy是不同estimand；必须保存alphabet、log base、measurement scale、window direction、prefix/delay与estimator assumptions。书中重复短消息、删除首bit或反转消息的建议会改变实时语义，不作为项目修补方法。

| ID | 原 EPUB 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH18-001` | §18.2；`Image00095.jpg` | `H[X]=-sum_x p[x]log2 p[x]`。 | 保存alphabet、probability estimator、log base与bits；采用`0log0=0`约定。 | `verified_concept_only` |
| `FORM-RES01-CH18-002` | 同上；`Image00641.jpg` | `0<=H[X]<=log2|A|`，均匀分布取上界。 | empty/singleton alphabet、估计误差与归一化边界需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH18-003` | 同上；`Image00715.jpg`、`Image00151.jpg` | self-information为`log2(1/p[x])`。 | p=0/1、平滑与unseen symbol策略必须显式。 | `verified_concept_only` |
| `FORM-RES01-CH18-004` | 同上；`Image00045.jpg` | redundancy为`1-H[X]/log2|A|`。 | alphabet改变会机械改变结果；`|A|=1`分母失效。 | `verified_concept_only` |
| `FORM-RES01-CH18-005` | 同上；`Image00184.jpg` | MI写成joint相对marginal product的log-density ratio期望。 | support mismatch、zero cell、离散/连续base measure与bias correction需登记。 | `verified_concept_only` |
| `FORM-RES01-CH18-006` | 同上；`Image00184.jpg` | `MI=H[X]+H[Y]-H[X,Y]`，在共同单位下非负且独立时为0。 | estimator bias可产生负值；不把association解释为因果。 | `verified_concept_only` |
| `FORM-RES01-CH18-007` | 同上；`Image00494.jpg` | bivariate Normal下`MI=-1/2 log(1-rho^2)`。 | log base决定nats/bits；rho边界、非Gaussian反例与稳定性需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH18-008` | 同上正文 | 原书只称normalized variation of information为MI派生metric，未给公式。 | 登记source omission；未核原始定义前不得实现或宣称metric性质。 | `verified_concept_only` |
| `FORM-RES01-CH18-009` | §18.3；`Image00591.jpg`—`Image00760.jpg` | length-w word经验概率是其在length-n message中的出现频率。 | overlapping count、有效起点、boundary与stationarity需明确。 | `verified_concept_only` |
| `FORM-RES01-CH18-010` | 同上；`Image00292.jpg` | plug-in entropy rate为word经验entropy除以w。 | unseen words与finite-sample downward bias不由MLE解决；n应远大于w。 | `verified_concept_only` |
| `FORM-RES01-CH18-011` | §18.4；Snippet 18.2 | LZ dictionary size/message length仅是parser-specific complexity候选。 | parser、overlap、短消息和normalization必须版本化；snippet未执行。 | `verified_concept_only` |
| `FORM-RES01-CH18-012` | 同上；`Image00371.jpg`、Snippet 18.3 | `L_i^n`为当前位置后缀与前n字符最长匹配长度加1。 | 对称窗口消费i之后数据，实时feature需延迟或改用已验证one-sided实现。 | `verified_concept_only` |
| `FORM-RES01-CH18-013` | 同上；`Image00514.jpg` | Ornstein–Weiss极限为`L_i^n/log2 n -> 1/H`。 | 仅在stationary/ergodic、finite alphabet等条件下almost sure成立。 | `verified_concept_only` |
| `FORM-RES01-CH18-014` | 同上；`Image00787.jpg` | sliding estimator为平均`L_i^n/log2 n`后取倒数。 | n、k、求和位置、zero/short match和endpoint需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH18-015` | 同上；`Image00831.jpg` | expanding estimator聚合`L_i^i/log2 i`并取倒数。 | 原书中心窗口造成even-length/末bit问题，不是天然online。 | `verified_concept_only` |
| `FORM-RES01-CH18-016` | 同上；`Image00457.jpg` | modified estimators改为平均`log2 n/L`以放宽Doeblin条件。 | 算术/调和聚合不是可互换实现；假设与版本必须锁定。 | `verified_concept_only` |
| `FORM-RES01-CH18-017` | 同上；`Image00645.jpg`—`Image00047.jpg` | 书中启发式为`N≈n+(log2 n)^2`，并陈述渐近一致性而非单调性。 | n/k全是trial；198/58示例不迁移，重复消息会伪造结构。 | `verified_concept_only` |
| `FORM-RES01-CH18-018` | §18.5.1正文 | binary encoder以正负映射1/0并删除zero。 | 删除zero改变时钟且丢幅度；zero-heavy/tick-size需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH18-019` | §18.5.2正文 | quantile encoder把returns映射到近等频alphabet。 | 边界仅在训练前缀拟合冻结；ties/OOS overflow与机械抬升边际熵需报告。 | `verified_concept_only` |
| `FORM-RES01-CH18-020` | §18.5.3；`Image00234.jpg` | sigma encoder从minimum按固定step分箱，code数为range/step上整。 | 原书未限定training-only；全样本min/std会泄漏且对outlier敏感。 | `verified_concept_only` |
| `FORM-RES01-CH18-021` | §18.6；`Image00324.jpg` | Gaussian differential entropy为`1/2 log(2*pi*e*sigma^2)`。 | 公式用自然log、受measurement scale影响，不能与离散bits直接比较。 | `verified_concept_only` |
| `FORM-RES01-CH18-022` | 同上；`Image00664.jpg` | Normal假设下`sigma=exp(H-1/2)/sqrt(2*pi)`。 | 仅为IID Gaussian model identity；不自动年化、不替代realized volatility。 | `verified_concept_only` |
| `FORM-RES01-CH18-023` | §18.7；`Image00835.jpg` | generalized weighted mean为`(sum_i p_i x_i^q)^(1/q)`。 | q<0要求x>0；q趋0/无穷、zero weights与数值稳定需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH18-024` | 同上；`Image00121.jpg`、`Image00211.jpg` | Hill effective number为`(sum_i p_i^q)^(1/(1-q))`。 | p必须归一；q<1的zero概率与q=1极限需显式处理。 | `verified_concept_only` |
| `FORM-RES01-CH18-025` | 同上；`Image00649.jpg` | `lim_(q->1) log N_q[p]=H[p]`，单位取决于log base。 | 近q=1用稳定极限实现；不得把diversity直接称alpha。 | `verified_concept_only` |
| `FORM-RES01-CH18-026` | §18.8.3；`Image00813.jpg` | PCA factor exposure为`f_omega=W'omega`。 | eigenvector sign/order、degenerate eigenspace与covariance版本需登记。 | `verified_concept_only` |
| `FORM-RES01-CH18-027` | 同上；`Image00512.jpg`—`Image00238.jpg` | component risk share为`theta_i=f_i^2 lambda_i/sum_n f_n^2 lambda_n`，concentration为`1-effective_number/N`。 | PSD、zero total risk、factor rotation与estimator uncertainty需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH18-028` | §18.8.4；`Image00329.jpg`、`Image00564.jpg` | PIN为`alpha*mu/(alpha*mu+2epsilon)`；volume-clock近似把它联系到绝对order imbalance。 | alpha/mu/epsilon不可直接由熵识别；VPIN模型与争议不能被简化为真概率。 | `verified_concept_only` |
| `FORM-RES01-CH18-029` | 同上正文 | 将buy-volume quantile message的LZ entropy CDF作为adverse-selection feature。 | tick classification、volume bars、training-only quantiles、PIT CDF和标签ground truth缺一即blocked。 | `verified_concept_only` |
| `FORM-RES01-CH18-030` | 全章；止于`#filepos0000963505` | 合格entropy证据需编码、窗口、单位、偏差、prefix与简单基线。 | 4代码图、3图表和练习未执行；不回测、不看holdout、不授权promotion。 | `verified_concept_only` |

## 已完成 L2：第 19 章

### 第 19 章：微观结构数据权属、流动性代理与定性边界

- **论证链**：本章按数据丰富度梳理三代microstructure proxy。第一代仅靠交易价或OHLC：tick rule递归推断aggressor，Roll用相邻price-change负协方差反推effective spread，Parkinson与Corwin–Schultz从high/low拆波动与spread。第二代加入volume：Kyle以price change对signed volume回归估impact，Amihud以absolute return除dollar volume衡量illiquidity，Hasbrouck再用TAQ/Bayesian设定估跨资产cost。第三代把交易到达视为good/bad/no-news的Poisson mixture，PIN估不可观测arrival rates，VPIN在volume clock上用buy/sell volume imbalance近似。order size、cancel/limit/market event、TWAP周期、options trade/quote差异和signed-flow persistence可形成额外特征；最后的cross-entropy CDF把“信息”定义为某个做市预测模型的相对失败程度，而不是市场参与者客观身份。
- **成立条件**：`MicrostructureFeatureEvidence`必须保存venue/instrument/rule version、data entitlement、trade/quote/L1/L2/MBO/FIX级别、exchange sequence、event/receive/decision time、timezone、session、tick/lot、price/size units、trade condition、aggressor source与ground-truth coverage、quote age、cancel/replace/correction、hidden/auction/cross/odd-lot处理、bar builder与clock、window/lag、estimator、SE/t-stat、output latency和feature hash。spread/impact proxy必须与同时点quoted/effective/realized spread、post-trade markout、depth、fill和implementation shortfall对照；PIN/VPIN保存classification、volume bucket、parameter fit/identifiability和uncertainty。任何做市profit/adverse-selection标签必须来自双边fills、inventory和cash ledger，而非mid-price反事实。
- **局限与反例**：tick rule在zero tick沿用旧side且初值任意，accuracy随venue、hidden liquidity、quote/trade异步和aggregation改变。Roll要求无drift、IID Normal mid innovations、独立等概率trade signs；sample covariance非负时spread无实数解并不表示零成本。OHLC estimator受overnight gap、limit/halt、stale extreme、bar length和24/7 session影响，negative alpha clipping会引入质量选择。Kyle/Amihud/Hasbrouck单位、sampling与self-impact不同，t-stat也会被sample size、autocorrelation和heteroskedasticity放大。PIN mixture可能多峰、不可识别或局部最优，VPIN强依赖bulk classification、bucket size、window与volume clock；文献结论本身相互冲突。高cancel、round size、TWAP周期、order-flow persistence或cross-entropy loss不能识别GUI trader、predator、informed trader、manipulation或未来方向。
- **项目动作**：建立只读microstructure feature registry，逐项标记最低数据等级与fallback：OHLC-only的Roll/HL/Corwin只作低置信proxy，trade+quote可验证aggressor/effective spread，L2/MBO才研究queue/cancel/depth，private fills另由Execution/Ledger管理。用known synthetic、exchange aggressor tags、quote-mid对齐和fill/markout fixtures测试zero tick、crossed/stale quote、out-of-order、correction、session gap、roll、split、volume unit、empty bucket、cancel burst和restart；报告classification confusion、proxy error、SE/HAC、regime与venue稳定性。把round-size、TWAP phase、cancel和options disagreement仅作为合法公开数据上的research hypothesis；疑似front-running、spoofing、collusion或MNPI一律不实现，只输出alternative hypotheses与合规升级。
- **禁止直接采用**：不得复制tick-rule高accuracy、5-minute bars、任一E-mini histogram、round-size倍数、TWAP时段、PIN/VPIN阈值、95%显著性、Flash Crash解释或50bp案例；不得用OHLC proxy声称真实spread/depth/queue/HFT验证，不得把lambda、VPIN、cancel rate或cross-entropy CDF称“知情交易概率”或操纵证据。不得开发章节建议的front-run TWAP行为，不得从options/quotes、订单模式或关系推断MNPI身份。Strategy只可输出经验证的Forecast候选；Portfolio/Risk、OMS/Execution、Fill/Ledger和compliance边界不变。当前不运行微观结构回测、不读取private order/fill、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH19-001`—`030`已回到原EPUB关闭为`verified_concept_only`。本章跨越`text00003.html#filepos0000963505`与`text00004.html`，止于`text00004.html#filepos0001034475`；共48个独立图片资源，其中43个公式/符号、2个代码图、3个历史图。tick rule、Roll、Parkinson、Corwin–Schultz、Kyle/Amihud/Hasbrouck impact、PIN mixture与VPIN均已逐式核对。Roll的`c`是half-spread而非full spread；VPIN是特定volume-clock/classification下的proxy且原书同时记录了相互冲突的预测研究。章节末cross-entropy loss必须等待真实label实现，因此其CDF只能按label end time作为事后模型诊断，不能回填为同一事件的实时feature。代码、图和推荐采样参数均未执行。

## Ch19 原始 EPUB 复核

- 来源：原EPUB SHA256 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`；起于`OEBPS/text00003.html#filepos0000963505`，续于`OEBPS/text00004.html`，止于`#filepos0001034475`。
- 结论边界：spread、volatility、impact、PIN/VPIN与information percentile均是模型依赖proxy。必须声明trade/quote/L2/MBO层级、venue、clock、aggressor classifier、bar construction、currency/units、correction与ground truth；缺字段或无法对照真实quote/fill/markout时保持blocked。

| ID | 原 EPUB 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH19-001` | §19.3.1；`Image00839.jpg` | tick rule按`Delta p`正负赋`b_t=+1/-1`，zero tick沿用前值。 | b0、correction/out-of-order、auction与venue aggressor tag需confusion matrix。 | `verified_concept_only` |
| `FORM-RES01-CH19-002` | 同上；`Image00648.jpg` | 累计trade sign可作order-flow primitive，signed volume为`b_t V_t`。 | volume units、partial/cross trades与聚合边界需显式。 | `verified_concept_only` |
| `FORM-RES01-CH19-003` | §19.3.2；`Image00375.jpg`、`Image00262.jpg` | Roll latent mid为无漂移random walk，innovation IID Normal。 | 这是反事实假设；drift、异方差、依赖与非Normal需反例诊断。 | `verified_concept_only` |
| `FORM-RES01-CH19-004` | 同上；`Image00259.jpg` | transaction price为`p_t=m_t+b_t c`，c是half-spread。 | constant spread、tick rounding、hidden liquidity和quote midpoint需对照。 | `verified_concept_only` |
| `FORM-RES01-CH19-005` | 同上；`Image00435.jpg` | Roll要求sign等概率、serially independent且与innovation正交。 | 实际sign persistence/endogeneity会破坏识别。 | `verified_concept_only` |
| `FORM-RES01-CH19-006` | 同上；`Image00498.jpg`、`Image00702.jpg` | 模型下`cov(Delta p_t,Delta p_(t-1))=-c^2`。 | estimator、CI与非负covariance必须报告，不把模型失败隐藏为0。 | `verified_concept_only` |
| `FORM-RES01-CH19-007` | 同上；`Image00684.jpg` | 书中实现`c=sqrt(max(0,-lag1 covariance))`。 | max-clipping会掩盖无实数解；c为half-spread，full spread是2c。 | `verified_concept_only` |
| `FORM-RES01-CH19-008` | 同上正文 | latent innovation variance为observed variance加两倍lag covariance。 | 负方差、finite sample与HAC敏感性需fail-closed。 | `verified_concept_only` |
| `FORM-RES01-CH19-009` | §19.3.3；`Image00770.jpg`、`Image00008.jpg` | Parkinson以log high-low平方和`4log2`常数识别GBM volatility。 | continuous path、无jump/gap、bar/session与annualization需冻结。 | `verified_concept_only` |
| `FORM-RES01-CH19-010` | §19.3.4；`Image00091.jpg` | Corwin–Schultz beta聚合相邻bar的log high-low平方。 | rolling length、missing/extreme与24/7/session boundary需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH19-011` | 同上；`Image00161.jpg` | gamma为两bar联合high-low的log range平方。 | joint extreme provenance与overnight gap会改变estimand。 | `verified_concept_only` |
| `FORM-RES01-CH19-012` | 同上；`Image00283.jpg` | alpha由beta/gamma及模型常数组合分离spread成分。 | 根号domain、近边界稳定性与negative alpha率需记录。 | `verified_concept_only` |
| `FORM-RES01-CH19-013` | 同上；`Image00189.jpg` | percentage spread为`2(exp(alpha)-1)/(1+exp(alpha))`。 | 与quoted/effective/realized spread同单位对照，不能称可执行成本。 | `verified_concept_only` |
| `FORM-RES01-CH19-014` | 同上正文；Snippets 19.1—19.2 | 原书建议negative alpha截为0。 | clipping率与raw值必须保留；代码未执行，模型失败不得静默变0。 | `verified_concept_only` |
| `FORM-RES01-CH19-015` | §19.4.1正文 | Kyle market maker线性定价`p=lambda y+mu`。 | intercept、units、simultaneity与nonlinear/concave impact需challenger。 | `verified_concept_only` |
| `FORM-RES01-CH19-016` | 同上；`Image00139.jpg` | informed demand一阶条件为`x=(v-mu)/(2lambda)`，要求`lambda>0`。 | risk neutrality、single informed trader与terminal-value假设必须保留。 | `verified_concept_only` |
| `FORM-RES01-CH19-017` | 同上；`Image00221.jpg`—`Image00673.jpg` | linear equilibrium给出alpha、beta、mu与lambda的Normal/noise-variance解。 | 理论均衡系数不等于经验回归；分布、唯一性与identification需区分。 | `verified_concept_only` |
| `FORM-RES01-CH19-018` | 同上；`Image00846.jpg` | empirical Kyle lambda回归`Delta p_t`对`signed volume b_t V_t`。 | clock、price reference、HAC SE、self-impact与unit normalization需登记。 | `verified_concept_only` |
| `FORM-RES01-CH19-019` | §19.4.2；`Image00171.jpg` | Amihud proxy以bar absolute log return除bar dollar volume。 | zero volume、currency、corporate action、bar length与aggregation需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH19-020` | §19.4.3；`Image00439.jpg` | Hasbrouck回归absolute log return对signed square-root dollar volume。 | Bayesian prior/Gibbs、cross-asset scale、clock与TAQ cleaning需另证。 | `verified_concept_only` |
| `FORM-RES01-CH19-021` | §19.5.1；`Image00687.jpg` | expected security value按no/bad/good-news states加权。 | alpha/delta as-of、payoff states与Bayesian update需保存。 | `verified_concept_only` |
| `FORM-RES01-CH19-022` | 同上；`Image00743.jpg`—`Image00106.jpg` | breakeven bid/ask由informed/uninformed到达条件期望决定。 | inventory、competition、asymmetric rates与真实quote行为未包含。 | `verified_concept_only` |
| `FORM-RES01-CH19-023` | 同上；`Image00796.jpg`、`Image00382.jpg` | delta=1/2时spread与`PIN_t=alpha_t mu/(alpha_t mu+2epsilon)`相关。 | 四个latent参数估计不确定性必须传播；PIN不是观测事实。 | `verified_concept_only` |
| `FORM-RES01-CH19-024` | 同上；`Image00816.jpg` | PIN likelihood是good/bad/no-news三Poisson mixture。 | parameter bounds、multimodality、label switching与optimizer failures全记录。 | `verified_concept_only` |
| `FORM-RES01-CH19-025` | §19.5.2；`Image00497.jpg`、`Image00036.jpg` | VPIN为rolling equal-volume bars绝对buy-sell imbalance之和除总volume。 | bulk/tick classification、bucket/window、partial bucket与correction决定结果。 | `verified_concept_only` |
| `FORM-RES01-CH19-026` | 同上；`Image00683.jpg` | equal-size volume bars满足平均`V_B+V_S=V`的构造恒等式。 | classification不完整、cross trade与bucket close异常必须fail-closed。 | `verified_concept_only` |
| `FORM-RES01-CH19-027` | §19.6.1正文 | size/cancel/limit/market event rates必须以eligible state exposure为分母。 | replace chain、duplicate message、venue与MBO/FIX entitlement需明确。 | `verified_concept_only` |
| `FORM-RES01-CH19-028` | §19.6.2正文 | phase concentration与signed-flow autocorrelation只提示TWAP/order-splitting候选。 | timezone/session、multiple lags、HAC、herding与public-news alternatives需比较。 | `verified_concept_only` |
| `FORM-RES01-CH19-029` | §19.6.3；`Image00438.jpg` | microstructural information定义为realized OOS cross-entropy负值的历史CDF percentile。 | loss需真实label；只可在label end后作模型诊断，禁止回填为同事件实时feature。 | `verified_concept_only` |
| `FORM-RES01-CH19-030` | 全章；止于`text00004.html#filepos0001034475` | 合格microstructure证据需data level、clock、classification、proxy validation与ledger。 | 2代码图、3历史图未执行；不回测、不看holdout、不授权promotion。 | `verified_concept_only` |

## 已完成 L2：第 20 章

### 第 20 章：分区完备性、确定性归并与并行故障语义

- **论证链**：本章从vectorized Cartesian product转向multiprocessing。它把不可再分的任务称atom，把单worker顺序处理的一组atoms称molecule；linear partition适合近似等成本任务，nested partition按三角循环的累计工作量划分rows以减少长尾。通用engine把callback、molecule和kwargs封装为job，单线程路径用于debug，多进程路径异步返回；大输出可边到达边redux，PCA示例再用列分块和线性可加性降低峰值RAM。稳定贡献是“先证明问题可分解和输出可归并，再选择并行层级”，不是书中近似线性加速、GIL简述或旧版pickle workaround。
- **成立条件**：`ParallelRunEvidence`必须保存run/code/data/env版本、atom universe与stable ID、partition algorithm/version、molecule boundaries、cost estimate、halo/lookback/state ownership、worker/process/thread/BLAS配置、seed hierarchy、job payload hash、start/end/status/attempt/error、serialization format/version、reduction function/identity/order、output schema/count/range/hash和single-thread oracle hash。所有atoms必须无遗漏无重复，跨partition窗口需显式halo且只输出owner区间；PIT availability、sort order、timezone、bar residual和label span不能被chunk截断。异步结果按stable key确定性归并，任何worker失败、timeout、duplicate或partial output使整次运行fail-closed。
- **局限与反例**：vectorization可能因broadcast/alignment/dtype改变语义或制造巨大中间数组；multiprocessing受serial fraction、spawn、IPC、pickle、I/O、memory bandwidth、cache和scheduler限制，不会按CPU数线性加速。书中GIL解释过度简化：Python线程、进程、C扩展与I/O行为依runtime/library而异。`imap_unordered`按完成顺序返回，非交换redux、DataFrame join、dict/list in-place更新和浮点加法会产生非确定结果；arrival-order streaming虽省RAM，却可能改变值。bound-method pickle hack依旧版Python且反序列化不可信对象有代码执行风险。nested BLAS/process pool会oversubscribe；fork/spawn与Windows入口语义不同。把搜索向量化或并行化只提高trial吞吐，不降低multiple testing。
- **项目动作**：对每个候选builder先建立serial reference和partition manifest，再实现map/reduce；验证1 worker、2 workers、不同molecule/batch、乱序完成、worker crash/retry、empty/singleton、non-divisible、upper/lower triangle、lookback halo、DST/session、random seed、chunk/restart与低内存场景。reduction优先使用有identity且可证明associative/commutative的操作；order-sensitive或floating aggregation按stable key固定树形顺序并采用补偿求和/容差。限制外层process与BLAS线程总量，记录peak RSS、serialization/I/O/compute/reduce时间和真实speedup/efficiency；只有当前机器基准证明净收益才启用。任何文件、SQLite或`latest`保持单writer，worker只写唯一临时分片并由owner原子发布。
- **禁止直接采用**：不得复制24/5000 CPU、1/5000时间、`mpBatches=10`、10×100 timeit、旧pickle注册、任一partition/batch/thread默认或性能数量级；不得因并行任务返回成功就接受缺失/重复/乱序输出，不得用unordered in-place reduction生成证据。不得让worker读取live/current/latest漂移状态或并发写同一artifact/ledger，不得通过更多CPU扩大未登记搜索空间。当前不运行性能基准、回测或HPC任务，不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH20-001`—`030`已回到原EPUB关闭为`verified_concept_only`。章节边界为`text00004.html#filepos0001034475`至`#filepos0001074501`，共38个独立图片资源，其中22个公式/符号、14个代码图、2个分区图。Cartesian enumeration、linear/nested partition、triangular roots、async job dispatch、pickle、streaming reduction与blockwise PCA均已核对。原书把24-task示例外推为“5000 CPUs耗时约为单线程1/5000”，违反任务并行度上限且忽略Amdahl串行比例、进程/通信/调度/I/O开销，登记为source performance overclaim。`imap_unordered`配合非交换reducer或浮点加法不能保证bitwise determinism；旧版bound-method pickle补丁也不是当前Python兼容性许可。所有代码与性能数字均未执行。

## Ch20 原始 EPUB 复核

- 来源：原EPUB SHA256 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`，`OEBPS/text00004.html#filepos0001034475`至`#filepos0001074501`。
- 结论边界：并行化不改变业务语义的前提是atom全集覆盖且互斥、halo/owner明确、异常完整传播、随机数与stable ID独立于worker/chunk、reducer代数满足要求、输出按canonical order重建且只有单一持久化写者。速度与内存必须在当前机器、相同工作量和相同输出下实测。

| ID | 原 EPUB 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH20-001` | §20.2；Snippets 20.1—20.2 | Cartesian search space大小为各维候选数乘积。 | empty dimension、trial count、materialization与memory explosion需登记。 | `verified_concept_only` |
| `FORM-RES01-CH20-002` | 同上；`Image00730.jpg`、`Image00313.jpg` | 所谓vectorized实现实际使用compiled iterator/product，必须枚举每个组合恰一次。 | 维度顺序、stable ID与loop oracle逐项对照；代码未执行。 | `verified_concept_only` |
| `FORM-RES01-CH20-003` | §20.3；Snippets 20.3—20.4 | 同工作量speedup应定义为serial elapsed/parallel elapsed。 | warm-up、I/O/cache、serialization和CI必须同口径。 | `verified_concept_only` |
| `FORM-RES01-CH20-004` | 同上正文 | 原书称5000 CPUs约获1/5000耗时。 | 登记source performance overclaim：示例仅24 tasks且忽略Amdahl与开销。 | `verified_concept_only` |
| `FORM-RES01-CH20-005` | §20.4.1；Snippet 20.5 | molecule数受atom数与worker/batch目标约束。 | empty/singleton、workers>atoms与scheduler overhead需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH20-006` | 同上；`Image00255.jpg` | linear partition以N+1个单调边界切分atom index range。 | 完整union、pairwise disjoint、zero-length与rounding需证明。 | `verified_concept_only` |
| `FORM-RES01-CH20-007` | 同上；Figure 20.1 | equal-count partition只在atom成本近等时近似平衡work。 | 非均匀成本应over-decompose/dynamic schedule，不能只看count。 | `verified_concept_only` |
| `FORM-RES01-CH20-008` | §20.4.2；`Image00321.jpg` | lower-triangular nested loop总任务数为`N(N+1)/2`。 | N=0/1、inclusive diagonal与off-by-one需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH20-009` | 同上；`Image00700.jpg` | off-diagonal为`N(N-1)/2`，diagonal为N。 | sum invariant与upper/lower symmetry需验证。 | `verified_concept_only` |
| `FORM-RES01-CH20-010` | 同上；`Image00302.jpg` | M个molecule目标work为`N(N+1)/(2M)`。 | integer rounding、M>N与真实cost model mismatch需报告。 | `verified_concept_only` |
| `FORM-RES01-CH20-011` | 同上；`Image00442.jpg`—`Image00611.jpg` | 首边界由`r1(r1+1)/2`等于目标work求正根。 | root仅是实数目标，round policy必须保证单调覆盖。 | `verified_concept_only` |
| `FORM-RES01-CH20-012` | 同上；`Image00351.jpg`—`Image00294.jpg` | 后续边界由累计triangular work减前一累计量递推求根。 | rounding drift、empty partition、duplicate boundary与last=N需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH20-013` | 同上；Snippet 20.6 | upper triangle通过反向owner顺序复用同一总work逻辑。 | row mapping、stable ordering与upper/lower oracle需对照。 | `verified_concept_only` |
| `FORM-RES01-CH20-014` | §20.5.1；Snippet 20.7 | job count由worker数、mpBatches与atom上限共同决定。 | 过分解改善straggler但增加pickle/scheduler开销。 | `verified_concept_only` |
| `FORM-RES01-CH20-015` | 同上；Figure 20.2 | makespan受最慢worker累计job成本支配。 | runtime variance、front-loading、straggler与dynamic scheduling需实测。 | `verified_concept_only` |
| `FORM-RES01-CH20-016` | §20.5.2；`Image00805.jpg` | `imap_unordered`按完成顺序返回而非提交顺序。 | 每个atom携带stable key，重试/重复/late result后canonical sort。 | `verified_concept_only` |
| `FORM-RES01-CH20-017` | §20.5.3—20.5.4；Snippets 20.10—20.11 | callback payload依赖pickle round-trip，原书含旧bound-method补丁。 | code/env hash、Windows spawn、安全与当前Python兼容性需独立验证。 | `verified_concept_only` |
| `FORM-RES01-CH20-018` | §20.5.5；Snippet 20.12 | reducer需identity并完整fold所有molecular outputs。 | empty/single、in-place return None、schema mismatch与exception需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH20-019` | 同上；Snippets 20.12—20.13 | parallel map/reduce应等于serial callback后按同规则归并。 | stable order、index alignment、NaN与tolerance需serial oracle。 | `verified_concept_only` |
| `FORM-RES01-CH20-020` | 同上正文 | streaming reduction峰值不必保存全部outputs。 | accumulator、largest molecule、pickle buffers和copy/in-place仍占内存。 | `verified_concept_only` |
| `FORM-RES01-CH20-021` | 同上；`Image00225.jpg` | unordered arrival只有在reducer满足所需结合/交换语义时结果稳定。 | dict/list conflict、join顺序与non-commutative reducer禁止unordered。 | `verified_concept_only` |
| `FORM-RES01-CH20-022` | 同上 | floating addition非结合，worker/chunk变化会改变低位。 | 固定reduction tree或补偿求和，并报告ULP/tolerance而非声称bitwise相同。 | `verified_concept_only` |
| `FORM-RES01-CH20-023` | §20.4—20.5全节 | partition必须满足atom union等于universe且两两互斥。 | stable ID、coverage hash与duplicate/missing audit是运行证据。 | `verified_concept_only` |
| `FORM-RES01-CH20-024` | 同上 | rolling/stateful任务需要input halo，但只由owner输出core interval。 | lookback、label span、bar residual与restart边界需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH20-025` | 同上 | 随机任务seed必须由run/partition/atom stable IDs确定性派生。 | worker/chunk不变量、RNG与library version需保存；原书未提供合同。 | `verified_concept_only` |
| `FORM-RES01-CH20-026` | §20.6；`Image00407.jpg`、`Image00341.jpg` | `P=Z W_tilde=sum_b Z_b W_tilde_b`可按不交叠column blocks加总。 | labels/order、gap/overlap、sparse fill与serial dot oracle需验证。 | `verified_concept_only` |
| `FORM-RES01-CH20-027` | 同上；`Image00556.jpg` | 保留M components使累计eigenvalue share达到tau。 | sort、negative/degenerate eigenvalues、tau边界与PIT fit需显式。 | `verified_concept_only` |
| `FORM-RES01-CH20-028` | 同上；`Image00341.jpg`、Snippet 20.14 | blockwise reduction仅在线性加法和正确索引对齐时等价。 | duplicate columns、NaN alignment、floating order与schema需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH20-029` | 同上正文 | block count在peak RAM、I/O、serialization与parallel overhead间权衡。 | 只接受当前机器benchmark；示例B/worker数不得迁移。 | `verified_concept_only` |
| `FORM-RES01-CH20-030` | 全章；止于`#filepos0001074501` | 合格parallel证据需coverage、halo、seed、failure、reduction与serial parity。 | 14代码图、2分区图未执行；单写者保持，不回测、不授权promotion。 | `verified_concept_only` |

## 已完成 L2：第 21 章

### 第 21 章：离散轨迹搜索、目标误差与量子主张降级

- **论证链**：章节把N资产、H期的allocation trajectory写成`N×H`权重矩阵，每期由forecast mean/covariance和依赖相邻权重变化的cost得到net return，再最大化整条路径Sharpe。为避免非凸、非光滑和时变输入，它把资本离散为K单位：每期枚举`x_1+…+x_N=K`的有序非负整数解，归一化为absolute weights，叠加sign permutations形成静态集合Ω，再枚举`Ω^H`全部轨迹。该方法可在有限网格上找到已定义目标的全局离散最优，但搜索规模指数增长。将问题编码为integer/QUBO可能适配特定求解器；qubit superposition不等于免费存储、评估并读出所有解，也不能证明一般NP-hard问题获得有效最优解。
- **成立条件**：`DiscreteOptimizationEvidence`必须保存decision variables/units、horizon、initial state、forecast/covariance/cost版本及uncertainty、objective、cash/net/gross/leverage/short/borrow/margin/capacity/turnover/terminal约束、K/grid、feasible-set generator、dedup规则、candidate/trajectory count、pruning、solver/backend/version、seed、time/memory limit、status、objective bound/gap、solution certificate、constraint residual和classical baseline。每个zero weight的正负符号不得重复计数；“full investment”必须区分net sum、gross absolute sum和cash。目标、K、约束和solver在结果前冻结，所有被看过的解与硬件/embedding变化进入trial ledger。
- **局限与反例**：章节仍假设每期multivariate Normal且跨期独立，只是均值/协方差随h变化；Sharpe把多期路径压成均值/波动，忽略wealth compounding、drawdown、cash/margin和tail。平方根换仓成本虽在零点非光滑，但并非一般“非连续”；其参数、impact/capacity和交叉资产执行未由fills校准。`sum abs(weight)=1`是gross约束，不等同通常net full-investment；直接乘`2^N`会为zero weights生成重复符号。网格最优受K和边界影响，K增大既改变可行集也放大trial。全局最优会放大forecast、covariance和cost误差，是optimizer's curse而非真实未来最优。quantum annealing还需有限精度、embedding、sampling、constraint penalty与classical verification，章节的“同时评估全部解”不能作为能力声明。
- **项目动作**：当前保持`rejected_for_now`，只提炼solver contract。若未来出现明确受约束离散配置问题，先与cash/equal/hold-current、greedy/no-trade、dynamic programming、MILP/MIQP或受约束局部方法比较；用tiny exhaustive oracle验证generator、constraints与objective，再做K、forecast/covariance/cost、terminal和stress敏感性。报告feasible count与unique count、best/near-best plateau、optimality gap、runtime/memory、solution instability和未实现约束；任何solver输出仍只形成TargetPosition候选，经Portfolio/Risk与执行可行性审批。量子研究只能写独立concept note，不安装依赖、不调用云硬件、不扩大本任务范围。
- **禁止直接采用**：不得复制Normal/time-independent假设、sqrt cost、Sharpe objective、K/N/H、`2^N`符号计数、随机矩阵rank/sigma、size 3/4、10×100 timeit或任一dynamic/static收益；不得把finite-grid global optimum称真实全局最优、可执行最优或promotion证据。不得声称superposition自动解决NP-hard、量子计算同时免费评估所有轨迹，或以硬件速度掩盖目标/约束错误。不得因穷举能处理ill-conditioned covariance就跳过稳健估计、成本、风险和ledger。当前不运行暴力/量子搜索、不查看holdout、不生成promotion结论、不访问网络、云量子、private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH21-001`—`030`已回到原EPUB关闭为`verified_concept_only`。章节边界为`text00004.html#filepos0001074501`至`#filepos0001099298`，共20个独立图片资源，其中12个公式/符号、7个代码图、1个示意图。net-return、sqrt turnover cost、跨期Sharpe、weak composition、gross-exposure grid、signed feasible set与trajectory Cartesian product均已核对。原书把`sqrt(|Delta omega|)`称为non-continuous，实际连续但在零点不可微；按每个absolute vector生成`2^N`符号会对zero slots产生重复，unique数量应按nonzero support计。章节未证明该特定优化问题NP-hard，却把superposition表述为同时评估/存储所有解并称量子计算天然适合NP-hard，登记为source quantum capability overclaim。代码、随机例子、annealer与性能练习均未执行。

## Ch21 原始 EPUB 复核

- 来源：原EPUB SHA256 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`，`OEBPS/text00004.html#filepos0001074501`至`#filepos0001099298`。
- 结论边界：离散穷举只给定grid/model内oracle；forecast、covariance、cost、constraint与grid误差仍主导现实风险。QUBO/annealer需要明确binary encoding、auxiliary variables、penalty calibration、embedding、precision、sample verification与classical baseline；本书叙述不构成当前硬件能力或复杂度证明。

| ID | 原 EPUB 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH21-001` | §21.3正文 | 每期return假设为`N(mu_h,V_h)`，跨期独立但参数可变。 | 保存horizon/clock与cross-horizon covariance omission；tail与forecast uncertainty另建scenario。 | `verified_concept_only` |
| `FORM-RES01-CH21-002` | 同上 | trajectory `omega`是N资产×H期allocation matrix。 | orientation、cash、initial/terminal state与可交易约束需显式。 | `verified_concept_only` |
| `FORM-RES01-CH21-003` | 同上；`Image00164.jpg` | `r=diag(mu'omega)-tau[omega]`给每期net expected return。 | expected不等于realized；risk-free、units与cost timing需一致。 | `verified_concept_only` |
| `FORM-RES01-CH21-004` | 同上；`Image00598.jpg` | 首期成本按`sum_n c_(n,1)sqrt(|omega_(n,1)-omega_n*|)`。 | sqrt cost连续但零点不可微；fixed fee、spread与cross-impact未覆盖。 | `verified_concept_only` |
| `FORM-RES01-CH21-005` | 同上；`Image00148.jpg` | 后续成本按相邻期allocation变化的sqrt绝对值加总。 | path-dependent但非真实执行模型；capacity/direction/fill calibration需另证。 | `verified_concept_only` |
| `FORM-RES01-CH21-006` | 同上；`Image00626.jpg` | objective分子汇总H期net means，分母为各期`omega_h'V_h omega_h`之和平方根。 | 隐含跨期独立且无cross-horizon covariance；不是realized Sharpe估计量。 | `verified_concept_only` |
| `FORM-RES01-CH21-007` | §21.4；`Image00214.jpg` | 在每期`sum_i|omega_(i,h)|=1`下最大化轨迹objective。 | ties、forecast uncertainty、多目标与约束可行性需保存。 | `verified_concept_only` |
| `FORM-RES01-CH21-008` | 同上正文 | 时变mu/V、nondifferentiable cost与Sharpe ratio使问题非简单QP。 | 原书“non-continuous cost”术语错误；可转化特例须独立识别。 | `verified_concept_only` |
| `FORM-RES01-CH21-009` | §21.5.1正文 | K units在N assets上的有序非负整数配置满足`sum_i p_i=K`。 | cash slot、lot、upper/lower bounds与K/N边界需显式。 | `verified_concept_only` |
| `FORM-RES01-CH21-010` | 同上；`Image00735.jpg` | weak compositions数量为`C(K+N-1,N-1)`。 | 这是ordered asset slots，不是无序integer partitions。 | `verified_concept_only` |
| `FORM-RES01-CH21-011` | 同上正文 | Stirling只近似组合规模，不生成解或证明可求。 | small K/N误差、log-space与upper/lower bounds需报告。 | `verified_concept_only` |
| `FORM-RES01-CH21-012` | §21.5.2；`Image00415.jpg` | absolute grid weights为`|omega_i|=p_i/K`。 | K>0、rounding、currency/lot mapping与continuous optimum距离需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH21-013` | 同上；`Image00430.jpg` | 书中“full investment”实际约束是`sum_i|omega_i|=1`。 | 这是gross exposure=1，不是signed net sum=1；cash/leverage/short需区分。 | `verified_concept_only` |
| `FORM-RES01-CH21-014` | 同上正文 | N维sign Cartesian product给至多`2^N`个符号向量。 | zero weights使+0/-0重复，不能把生成次数当unique count。 | `verified_concept_only` |
| `FORM-RES01-CH21-015` | 同上；Snippet 21.2 | support size s的unique signed variants是`2^s`。 | canonical zero sign、dedup hash与symmetry constraints需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH21-016` | 同上；`Image00443.jpg` | Omega是全部weak compositions经sign扩展后的unique union。 | exact count、deterministic ordering与业务constraints需另过滤。 | `verified_concept_only` |
| `FORM-RES01-CH21-017` | §21.5.3正文 | trajectory set Phi是Omega的H次Cartesian product，cardinality为`|Omega|^H`。 | state-dependent constraints会改变乘积结构；overflow需log计数。 | `verified_concept_only` |
| `FORM-RES01-CH21-018` | 同上；Snippet 21.3 | exhaustive cost至少与`|Omega|^H × objective_cost`成正比。 | streaming/parallelism不减少candidate count；所有timeout保留。 | `verified_concept_only` |
| `FORM-RES01-CH21-019` | §21.5全节 | 单坐标grid step为`1/K`。 | objective error取决于mu/V/cost敏感性；K本身是trial。 | `verified_concept_only` |
| `FORM-RES01-CH21-020` | 同上 | 原书未给continuous optimum到grid optimum的误差界。 | 登记source omission；需Lipschitz/empirical K sensitivity，不能称global现实最优。 | `verified_concept_only` |
| `FORM-RES01-CH21-021` | §21.3—21.5 | turnover cost使当前决策依赖initial与previous allocation。 | zero-coupling时才可能逐期分解；terminal condition需显式。 | `verified_concept_only` |
| `FORM-RES01-CH21-022` | Exercises | dynamic optimum等于逐期static optima需要objective跨期可分且无coupling cost。 | 书中仅提问未证明；不得据练习当充分必要定理。 | `verified_concept_only` |
| `FORM-RES01-CH21-023` | §21.6.1；Snippet 21.4 | known-rank random matrix用于数值fixture。 | seed、shape、target rank与eigenvalue tolerance需验证；代码未执行。 | `verified_concept_only` |
| `FORM-RES01-CH21-024` | 同上；Snippets 21.4—21.5 | covariance输入应symmetric PSD且horizon/units一致。 | numerical negative eigenvalues、repair与condition number需登记。 | `verified_concept_only` |
| `FORM-RES01-CH21-025` | 全章objective | point estimates的mu/V/cost未传播估计不确定性。 | robust/scenario objective、PIT fit与double-counting需独立合同。 | `verified_concept_only` |
| `FORM-RES01-CH21-026` | 同上 | 单个argmax不展示near-best plateau或weight instability。 | 预注册epsilon并报告near-best set、gap和weight dispersion。 | `verified_concept_only` |
| `FORM-RES01-CH21-027` | §21.5—21.6 | K、constraints、objective、solver与hardware变化都增加trial lineage。 | failed/timeout/embedding runs完整保留且不得触碰holdout。 | `verified_concept_only` |
| `FORM-RES01-CH21-028` | §21.1—21.5正文 | 任意Sharpe/sqrt-cost问题并非直接binary quadratic form。 | QUBO需auxiliary bits、penalty与precision/embedding证据；书中未给映射。 | `verified_concept_only` |
| `FORM-RES01-CH21-029` | §21.5.3正文 | superposition/annealer叙述不提供最优性证书。 | source quantum capability overclaim；每个sample须经典objective/constraint/gap复核。 | `verified_concept_only` |
| `FORM-RES01-CH21-030` | 全章；止于`#filepos0001099298` | 合格离散搜索证据需objective、grid、unique count、constraints、gap与baseline。 | 7代码图、1示意图未执行；不采购、不接入、不搜索、不授权promotion。 | `verified_concept_only` |

## 已完成 L2：第 22 章

### 第 22 章：端到端性能证据、流式保留与HPC迁移门槛

- **论证链**：本章以LBNL CIFT项目说明HPC处理streaming/time-series的工具链：硬件侧强调compute、global storage与低延迟network布局，软件侧包括MPI显式通信、HDF5多维array/chunk/compression/index和ADIOS类in-situ/in-transit处理；天文、聚变、电力与Flash Crash案例展示自动workflow、边缘连通、baseline预测、HDF5/MPI、VPIN和non-uniform FFT。对本项目最有用的不是HPC优于cloud的结论，而是把性能拆成算法、data layout、I/O、communication、compute、reduction和deadline，并要求边界数据与跨节点结果正确。速度只缩短得到某一统计量的时间，不能验证该统计量、标签、因果或行动政策。
- **成立条件**：`HPCWorkflowEvidence`必须保存workload/query mix、input bytes/records/schema/chunk/index/compression、PIT/lineage、single-node oracle、hardware/CPU/GPU/RAM/storage/network、virtualization/container、MPI/HDF/library/compiler版本、partition/communication/reduction、warm-up/cache、concurrency、wall/CPU/I/O/network/serialization/queue/publish时间、throughput、peak RSS、cost、failure/retry/checkpoint、RTO/RPO、output hash和SLO。streaming alert另存event definition、base rate、label latency、detection delay、false positive/negative、precision/recall、calibration、decision owner和action/no-action损失。in-situ丢弃或汇总前必须有不可变raw capture、retention policy、checksum、replay path和审计批准，不能为省I/O删除promotion所需事实。
- **局限与反例**：章节对HPC/cloud性能和成本的比较来自约2010—2017硬件、网络、virtualization、价格与机构补贴，当前已不具可迁移性；20TB、21×、234×、720×、2–10×、3–7×等数字混合了format、index、算法、replication、core count和平台。跨领域案例只证明workflow可运行，不证明金融机制。VPIN速度提升后扩大参数搜索，从20%降至7%的false positive及“不是逐合约拟合”仍有selection/multiple-testing风险；threshold变化不按十倍减少event也不能证明事件intrinsic或实时有效。NUFFT在once-per-minute出现峰值可由TWAP、scheduled feed、auction、timestamp quantization或aggregation共同产生，不能定性HFT身份。低latency warning若缺可靠label、action policy、risk/ledger和人机审批，可能更快地产生错误动作。
- **项目动作**：维持`profile_first`：对当前builder、feature、replay或gate先采样CPU、I/O、memory、serialization、lock和critical path，建立serial correctness与SLO；依次尝试算法/数据结构、列裁剪、chunk/index、batch/stream、单机并行和现有存储，再评估分布式。每个方案在同数据、同输出、同cache policy下报告cold/warm、p50/p95/p99、throughput、peak memory、cost与failure recovery，性能回归进入CI但不解锁研究gate。HDF5/MPI/in-situ只可作为future architecture candidate；必须先证明schema evolution、append/correction、concurrent reader、single writer、checkpoint、deterministic reduction和跨版本可读。任何新算力带来的额外search都计入trial ledger。
- **禁止直接采用**：不得复制dirac1/Magellan配置、512 cores、HDF5/MPI/ADIOS、C++、任何speedup/cost比例、VPIN参数、false-positive阈值、Flash Crash因果、NUFFT频率或“cloud无用/HPC更便宜”结论；不得为性能复制数据后把规模数字称真实，不得用throughput替代freshness/correctness。不得in-situ丢弃raw order/fill/audit或绕过不可变manifest，不得因早期预警更快就自动下单或改risk state。当前不运行HPC benchmark、不采购/迁移基础设施、不联网、不运行新回测、不查看holdout、不生成promotion结论、不访问private/order/paper/live endpoint，安全旗标保持false。
- **原载体复核结论**：`FORM-RES01-CH22-001`—`030`已回到原EPUB关闭为`verified_concept_only`。正文起于`text00004.html#filepos0001099298`，经§22.8与References结束；共13个独立图片资源，其中12个承载Fig.22.1—22.10，另1个仅为参考文献中的`√s=7 TeV`，没有独立算法公式或代码snippet。队列中的latency、throughput、parallel efficiency、TCO、MPI parity、read amplification、retention、FNR/precision等多数是项目为了让历史案例可审计而派生的证据指标，不是原书公式；已逐项标出source omission或governance gap。书中HPC/cloud成本与性能、VPIN threshold稳定性、NUFFT身份推断均为历史或推断性主张，不构成当前架构、统计或采购证据。

## Ch22 原始 EPUB 复核

- 来源：原EPUB SHA256 `3763828c757aebbf741e094f20407ae5798e1ee4193589c4a59cec313e4808f1`，`OEBPS/text00004.html#filepos0001099298`至§22.8/References。
- 结论边界：性能只能在相同输入、工作量、算法、输出正确性、cache policy和硬件资源下比较；速度提升不证明feature有效、事件因果、alert可行动或平台更便宜。任何HDF5/MPI/ADIOS采用都必须回到当前官方规格、本机profile、failure/replay和不可变数据合同，本章只提供候选概念。

| ID | 原 EPUB 位置 | 核对结论 | 项目映射/风险 | 状态 |
|---|---|---|---|---|
| `FORM-RES01-CH22-001` | §22.1—22.3 | 原文要求及时streaming响应，未给latency求和式。 | ingest至publish分解为项目metric；保存clock、overlap与tail latency。 | `verified_concept_only` |
| `FORM-RES01-CH22-002` | §22.3 | 原文区分throughput与quick turnaround，未定义吞吐公式。 | records/bytes口径、wall clock、backpressure与drop需冻结。 | `verified_concept_only` |
| `FORM-RES01-CH22-003` | §22.4；§22.6.4—22.6.5 | 历史speedup由baseline/candidate时间比得到，但工作量与平台不恒定。 | correctness、cache、replication、algorithm和hardware分解后才可比较。 | `verified_concept_only` |
| `FORM-RES01-CH22-004` | §22.4；§22.6.4 | 原文无`speedup/processors`的parallel-efficiency定义。 | 项目派生metric；保存资源口径、oversubscription与CI。 | `verified_concept_only` |
| `FORM-RES01-CH22-005` | Fig.22.2—22.3、22.8 | 原文联系virtualization/network/I/O与scaling，未给Amdahl/Gustafson界。 | 历史图不得外推，strong/weak scaling另核。 | `verified_concept_only` |
| `FORM-RES01-CH22-006` | §22.4成本段落 | 2011—2017成本比不是完整TCO方程。 | compute/storage/network/license/operations、补贴与failure另存。 | `verified_concept_only` |
| `FORM-RES01-CH22-007` | 同上 | 原文无按workload/record/SLO归一的unit-cost定义。 | 项目派生metric；failed run和idle capacity不得漏计。 | `verified_concept_only` |
| `FORM-RES01-CH22-008` | §22.5.1；§22.6.2 | MPI定义通信操作，未给global coverage/互斥合同。 | halo、stable ID、missing/duplicate与rank failure需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH22-009` | §22.5.1 | 原文未定义communication payload bytes。 | 项目另存serialization、latency、topology与message count。 | `verified_concept_only` |
| `FORM-RES01-CH22-010` | §22.5.1 | 原文无serial-reduction parity要求。 | floating order、rank count和非结合reducer必须对照oracle。 | `verified_concept_only` |
| `FORM-RES01-CH22-011` | §22.5.2 | HDF5 dataset由array、attributes、dimensions和dtype组成并可分组。 | 补endian、units、timezone、schema/version与missing。 | `verified_concept_only` |
| `FORM-RES01-CH22-012` | §22.5.2 | 原文称compression减少network/I/O，未给ratio公式。 | CPU、random access、lossless checksum和dtype需实测。 | `verified_concept_only` |
| `FORM-RES01-CH22-013` | §22.5.2；Fig.22.8 | 原文报告HDF5/index提速，未定义read amplification。 | chunk/index/cache/predicate按cold/warm同口径测量。 | `verified_concept_only` |
| `FORM-RES01-CH22-014` | §22.5.2 | 原文未讨论chunk shape/count。 | 明确是项目实现合同；当前HDF5规格另核。 | `verified_concept_only` |
| `FORM-RES01-CH22-015` | Fig.22.8 | 原文只称index降低access time，未定义selectivity。 | 保存build/storage cost、staleness、correction和query mix。 | `verified_concept_only` |
| `FORM-RES01-CH22-016` | §22.5.3 | 原文允许in-situ丢弃irrelevant data，未给retention ratio。 | dropped fields、audit minimum、replay和审批必须留证。 | `verified_concept_only` |
| `FORM-RES01-CH22-017` | §22.5.3 | 原文未要求immutable raw capture或loss contract。 | source governance gap；promotion事实不得不可逆丢弃。 | `verified_concept_only` |
| `FORM-RES01-CH22-018` | §22.6.2；Fig.22.5 | 更新connected-component算法修复旧算法常漏的edge blobs。 | cross-partition merge、missed-edge和determinism需fixture。 | `verified_concept_only` |
| `FORM-RES01-CH22-019` | §22.6.3 | recursive自喂预测会累积误差并产生不现实长程结果。 | 与direct baseline比较，保存horizon与uncertainty。 | `verified_concept_only` |
| `FORM-RES01-CH22-020` | §22.6.3；Fig.22.6 | treatment差值随control或LTAP baseline改变。 | counterfactual、randomization、自选择与group/individual边界需显式。 | `verified_concept_only` |
| `FORM-RES01-CH22-021` | §22.6.4；Fig.22.8 | ASCII/HDF与serial/parallel只比较runtime，未报告output parity。 | source evidence gap；性能前先核record/order/tolerance/checksum。 | `verified_concept_only` |
| `FORM-RES01-CH22-022` | 同上 | 原文明确把10年S&P 500数据复制10次。 | replicated scale与unique coverage分开，审计cache/compression。 | `verified_concept_only` |
| `FORM-RES01-CH22-023` | §22.6.5；Fig.22.9 | 报告FPR 20%→7%，未定义denominator、CI或event matching。 | label、dependence、CI与multiplicity缺失则不作alert证据。 | `verified_concept_only` |
| `FORM-RES01-CH22-024` | §22.6.5 | 原文未报告false negatives。 | FNR是项目必须补充的metric；定义window、late/censored events。 | `verified_concept_only` |
| `FORM-RES01-CH22-025` | §22.6.5 | 原文未报告precision或base rate。 | PPV/calibration/action loss另建合同，防base-rate fallacy。 | `verified_concept_only` |
| `FORM-RES01-CH22-026` | §22.6.5 | 列6组最终VPIN参数但未披露完整grid与trial count。 | source selection gap；全candidate ledger且禁止holdout选参。 | `verified_concept_only` |
| `FORM-RES01-CH22-027` | Fig.22.9后 | 以threshold变化未使event数降10倍推断“intrinsic”与实时有效。 | source inference overclaim；稳定性不证明机制或可行动性。 | `verified_concept_only` |
| `FORM-RES01-CH22-028` | §22.6.6；Fig.22.10 | NUFFT用于irregular observations，章节未给变换方程。 | 保存timestamp、window/leakage、detrend、calendar和trial family。 | `verified_concept_only` |
| `FORM-RES01-CH22-029` | 同上 | once-per-minute amplitude超邻频10倍并被解释为TWAP。 | source identity overclaim；scheduled/quantized/aggregated反例未排除。 | `verified_concept_only` |
| `FORM-RES01-CH22-030` | 全章至§22.8/References | 合格HPC证据合同为项目综合，而非书中单一公式。 | 12个图像资源承载10幅图，1个仅为参考文献公式；未执行benchmark。 | `verified_concept_only` |

## 全书后续复核重点

RES-01已完成22/22章`L2`与原EPUB概念级`L3`：Ch02 50项、Ch03—Ch22各30项，共650项均为`verified_concept_only`。这不是代码、数值、性能、市场事实或外部引用的复现完成态；所有snippet均未执行，历史参数/阈值/速度/收益未迁移，当前library/API/venue/数据规格仍须在具体实施票据中重新验证。本卡只可作为Agent研究与设计边界，不是backtest、paper/live、采购或promotion evidence。
