---
book_id: STR-05
title: Quantitative Trading
authors: [Ernest P. Chan]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Quantitative Trading - Ernest P. Chan - 原文.md
source_format: pdf_text_original_pdf_cross_checked
source_sha256: c71ba5b7a1486a7386decc7f3d6e848b019658a4da535015fccc5bf7ebd5de0d
source_line_count: 9340
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Quantitative Trading How to Build Your Own Algorithmic Trading Business (Ernest P. Chan) (z-library.sk, 1lib.sk, z-lib.sk).pdf
original_source_sha256: 85466da2a2d214aec44932922682e05441571fb59ada56466871d8da1057eeef
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 8
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 27_backtest_execution_risk_special_topic_items_verified_concept_only_from_original_pdf
last_reviewed_at: 2026-07-15
---

# STR-05：Quantitative Trading

## 覆盖声明

本卡已逐段完成 8/8 章 `L2` 语义复核，章节覆盖率为 `100%`。现已直接回看 204 页原 PDF，将第 2、3、5、6、7 章的回测、执行、Kelly、协整、factor/PCA、OU、季节性和 HFT 共 27 项关闭为 `verified_concept_only`。这只证明书中确有对应公式、方法、案例和限制，不认证历史数据、示例代码、经验阈值、参数最优性或绩效。原书出版于 2009 年，平台、broker、费用、数据源和容量示例具有明显时代性；MATLAB 附录未计入章节数。

## 全书项目映射

- `existing_rule_confirmed`：策略筛选必须检查基准、回撤、成本、survivorship/look-ahead/data-snooping 和时间稳定性。
- `candidate_design`：均值回归、动量、协整、factor 和 regime switching 只作为独立候选族，不是现成策略。
- `architecture_boundary`：书中的自动交易系统观点需映射为 Strategy → Portfolio/Risk → OMS/Execution → Fill/Ledger，而不是脚本直连 broker。
- `rejected_for_now`：2009 年平台/broker/费用/资本数字、案例收益和高频可行性不作为当前实现依据。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 The Whats, Whos, and Whys of Quantitative Trading | `662-1025` | `L2/medium`：PDF 正文已读完；案例数字和时代背景不具当前效力 | 量化交易是可编码、可重复的决策与运营闭环；简单模型、充分资本缓冲、自动化纪律和持续研究比数学复杂度或人工干预更重要。 | `existing_rule_confirmed`（共享）：研究、执行、风险、监控和 fills/ledger 是同一闭环，策略脚本不能直接等同交易业务。 | `not_applicable`；2008 年资本、杠杆、工时和盈利案例不采用 |
| 2 Fishing for Ideas | `1026-2001` | `L2/medium`：正文已读完；原 PDF 概念已核 | 候选来源并不稀缺，真正困难是先按时间、技能、资本、数据、目标和容量筛适配性，再核对基准、风险调整收益、回撤、成本、PIT、近期衰减和试验自由度。 | `implementation_gap`（共享）：候选登记表增加 capital/data/holding/capacity/benchmark/drawdown/trial 来源，并把独立复核纳入 intake。 | `FORM-STR05-CH02-001`：`verified_concept_only`；书中阈值和成本数字不采用 |
| 3 Backtesting | `2002-3892` | `L2/medium`：正文与原 PDF 公式版面已核 | 可复现回测必须同时固定数据版本、复权/PIT 语义、可成交时钟、收益口径、泄漏控制、试验历史和成本；单次 train/test 好看不足以证明可泛化。 | `existing_rule_confirmed`（共享）：PIT 数据、signal/execute lag、截断不变性测试、purged walk-forward、锁定 holdout、trial ledger 和统一成本模型。 | `FORM-STR05-CH03-001` 至 `FORM-STR05-CH03-006`：均为 `verified_concept_only`；案例结果与经验阈值不采用 |
| 4 Setting Up Your Business | `3893-4356` | `L2/medium`：正文已读完；法律、监管、平台与费用信息已过时 | 研究到执行之间还需要账户权限、风险约束、broker 能力、资金安全、真实成交质量与业务连续性；最低费用不是唯一选择标准。 | `concept_only`（共享）：转化为 capability/permission、counterparty due diligence、reconciliation、BCP/DR 和 incident 清单；不作为 broker 选择结论。 | `not_applicable`；所有法律、税务、杠杆、保险、平台、硬件和费用陈述需当前权威来源 |
| 5 Execution Systems | `4357-5079` | `L2/medium`：正文与原 PDF 假设已核 | 自动化程度应由频率、延迟、控制和故障成本决定；执行必须比较意图、订单、成交与账本，现实成本和运行约束解释回测偏差。 | `existing_rule_confirmed`（BTC/美股）：执行 adapter 隔离权限，Strategy 不直连 broker；paper/live 分权，用 arrival/order/fill/ledger 和 reconciliation 解释偏差。 | `FORM-STR05-CH05-001` 至 `FORM-STR05-CH05-005`：均为 `verified_concept_only`；历史 API/DDE、ADV/市值阈值和“少量 live 才能发现过拟合”不采用 |
| 6 Money and Risk Management | `5080-5982` | `L2/medium`：正文与原 PDF 公式已核 | Kelly 在已知稳定分布下最大化长期对数增长，但估计误差、重尾、相关突变、流动性和再平衡成本会使最优杠杆严重失真；风险约束必须先于增长目标。 | `existing_rule_confirmed`（Portfolio/Risk）：Kelly 只作理论压力上界，实际 sizing 由风险预算、hard caps、流动性、尾部压力、drawdown 和执行能力共同限制。 | `FORM-STR05-CH06-001` 至 `FORM-STR05-CH06-006`：均为 `verified_concept_only`；full/half-Kelly、历史最大亏损和 lookback 经验值不采用 |
| 7 Special Topics in Quantitative Trading | `5983-8048` | `L2/medium`：正文与原 PDF 方法已核 | 均值回归、动量、regime、协整、因子、退出、季节性与 HFT 是不同假说族，各自依赖不同数据、时钟、成本和稳定性条件，不能拼成一个“统计套利”策略。 | `candidate_design`（BTC/美股）：每个方法独立预登记、trial、PIT/cost/WF/holdout；协整需结构突变，HFT 在深度、fill mapping、延迟与 replay 证据完备前保持 blocked。 | `FORM-STR05-CH07-001` 至 `FORM-STR05-CH07-009`：均为 `verified_concept_only`；书中案例、检验解释和参数不采用 |
| 8 Conclusion: Can Independent Traders Succeed? | `8049-8310` | `L2/medium`：正文已读完；主要为个人观察与案例叙事 | 小容量可能进入机构无法利用的利基，但成功取决于容量、成本、治理、持续研究和风险控制；独立身份本身不产生 alpha。 | `concept_only`（共享）：capacity、crowding、incentive、segregation-of-duties 和持续研究进入运营手册；readiness 仍只由 current-HEAD evidence/gate 决定。 | `not_applicable`；个人成功、机构失败和容量数字不转为 gate 或收益假设 |

## 附录边界

- Appendix `8311-8579`：MATLAB 快速教程只作历史代码示例，不复制进项目。
- 案例回测必须重建在当前数据、成本、PIT 和 evidence contract 下，书中结果只作研究假说来源。

## 已完成 L2 章节

### 第 1 章：The Whats, Whos, and Whys of Quantitative Trading

- **论证链**：可编码信息形成规则 → 历史数据检验 → 自动化执行减少随意干预 → 持续研究与运营支持维持策略 → 资本缓冲和情绪纪律保证生存。
- **成立条件**：输入能被稳定定义，研究与运行职责可分离，系统能监控异常并在故障时安全停机。
- **反例与限制**：作者用个人成功/失败经历说明“简单优先”，属于经验论证而非普遍因果；复杂模型并非必然失败，简单模型也不自动稳健；高度自动化仍需要监控、对账和事故响应。
- **BTC 映射**：24/7 运行使“自动驾驶”风险更高，必须有 stale data、连接、余额、订单和 ledger 异常的 fail-closed 与值守升级路径。
- **美股映射**：开闭市、公司行动、PIT 基本面和 broker 时段规则要求日历/时钟 adapter，不能照搬书中开盘前后人工篮子流程。
- **共享动作**：每个策略票据同时声明 research、data、risk、execution、ledger、monitoring owner；单独回测曲线不构成可运行系统。
- **不得采用**：作者的起始资本、杠杆倍数、日常工时、首月盈利和独立交易者画像均为时代性案例，不进入参数或 readiness 判断。
- **公式/数字**：无需要转入项目计算的公式；所有经营数字视为历史叙事。

### 第 2 章：Fishing for Ideas

- **论证链**：公开来源产生候选 → 先做个人/系统适配筛选 → 再做 benchmark、Sharpe/IR、drawdown、cost、PIT、近期稳定性和 capacity 检查 → 通过后才进入严格回测。
- **成立条件**：候选必须能精确定义；数据和成本可获得；比较基准与目标风险口径一致；所有变体和失败尝试可追踪。
- **反例与限制**：作者建议修改公开策略直到可盈利，若不记录尝试次数会直接制造 data snooping；“近期表现好”不能替代 walk-forward/结构突变检验；低容量利基也可能因冲击和数据不足不可交易。
- **BTC 映射**：候选 intake 需增加交易所/合约、funding、basis、24/7 latency、深度、mark/index price、极端行情和容量字段；历史 ETF/股票成本数字无效。
- **美股映射**：必须使用 PIT universe、退市股、公司行动、借券/费率、locate、开闭市和延迟基本面；long-only 与中性策略使用不同 benchmark。
- **共享动作**：在 candidate registry 强制记录来源、假说、参数自由度、试验编号、预期持有期、数据预算、容量、基准、成本模型、回撤容忍、失败条件和 holdout 计划。
- **不得采用**：书中 Sharpe < 1、回撤 10%/20%、4 个月、资本 5 万/10 万美元、股票 5bp、ES 1bp 等均非当前阈值；“AI 只用线性回归”是作者经验偏好，不是模型禁令。
- **公式/数字**：`FORM-STR05-CH02-001` 已从原 PDF 关闭为 `verified_concept_only`；Information Ratio、Sharpe、drawdown 的项目实现仍以当前规范为准，书中阈值和历史数字不引用。

### 第 3 章：Backtesting

- **论证链**：独立复现策略 → 校验数据与公司行动 → 统一绩效定义 → 排除前视与幸存者偏差 → 控制参数/选择自由度 → 加入现实成本 → 用敏感性和真正未见数据检查稳定性。
- **成立条件**：数据可按当时可得性重建；信号时刻、订单时刻和成交假设分开；所有策略变体、参数搜索和人工选择均有 trial 记录；成本与容量按资产和订单状态建模。
- **数据限制**：复权价是派生视图且会随后续分红改变，必须固定 corporate-action snapshot；当前成分股不能回填历史；退市终值、停牌、NaN、异常 tick 和 OHLC 来源都需显式语义。
- **绩效限制**：Sharpe 的收益分母、融资/无风险利率、采样频率和年化只在收益独立等假设下可比较；drawdown 的符号、复利曲线和恢复定义必须统一；平均收益不能掩盖资本口径差异。
- **泄漏控制**：作者提出“截断末端后历史仓位必须完全不变”的不变性测试，适合作为本项目 look-ahead 合同测试；但它不能覆盖修订数据、未来 universe、全样本标准化、标签重叠和执行时钟泄漏。
- **反例与内部矛盾**：作者一方面警告不得依据 test set 调参，另一方面在 GLD/GDX 与开盘/收盘案例中反复比较 test 结果并选择更优变体；这些 test 已变成 validation，不再是锁定 holdout。动态滚动优化也不会自动消除 data snooping。
- **成本限制**：固定 `5bp × |Δweight|` 只是一阶上界/下界示例，遗漏 spread 状态、冲击、排队、部分成交、机会成本、借券、funding、费率层级和延迟；“不频繁所以成本影响不大”必须由订单级证据证明。
- **BTC 映射**：除普通 OHLC 外需固定 venue、contract、mark/index、funding、basis、合约换月/到期、24/7 bar 边界、交易所中断和深度快照；高低价触及不等于可成交。
- **美股映射**：必须使用 PIT constituents、退市与公司行动版本、真实交易日历、开闭盘 auction、借券/locate、SSR/halts 和延迟基本面；复权数据不得直接替代现金股息 ledger。
- **共享动作**：backtest evidence 增加 source hash、as-of、adjustment version、universe version、signal/execute/fill clock、trial ID、split plan、holdout access ledger、cost model version、capacity 和 truncation-invariance 结果。
- **不得采用**：`参数数 ≤ 5`、`样本数 = 252 × 参数数`、固定 train/test 比例、252 日/1,638 小时年化、示例 Sharpe、5bp 成本和案例阈值均为经验或时代数字；“先省略预防措施、上线后再补”与本项目 fail-closed 冲突。
- **公式/数字**：`FORM-STR05-CH03-001` 至 `FORM-STR05-CH03-006` 均已回看原 PDF 并关闭为 `verified_concept_only`；只保留公式语义与风险边界，不写入实现参数或复用案例结果。

### 第 4 章：Setting Up Your Business

- **论证链**：策略需求决定账户和能力 → 比较全部交易成本与产品/API 能力 → 核查资金安全和风险约束 → 建立电力、网络、主机与远程运维连续性。
- **成立条件**：需求已明确到资产、频率、权限、容量、支持时段和故障恢复目标；候选机构和法规信息来自当前权威来源。
- **长期有效部分**：外部风险约束可能保护交易者；commission 只是成本一部分；paper/simulator、API、资金隔离、财务稳健性、赎回能力和灾难恢复都应先于自动化扩张。
- **时代性限制**：书中的 SEC/NASD、Series 7、Reg T、SIPC、prop firm、dark pool、broker 名单、税务、硬件、带宽和费用均是 2008 年描述，不能推断 2026 年状态。
- **BTC 映射**：候选 venue 需评估辖区、资产隔离、proof/审计、API 权限、withdraw 禁用、rate limit、24/7 支持、异常回滚、mark/index 和断连行为；本轮不访问任何 private endpoint。
- **美股映射**：需核查当前监管、账户保护、清算、PDT/margin、borrow/locate、auction、market data entitlement 和灾备；不得从本书给出法律或 broker 建议。
- **共享动作**：建立 broker/exchange capability matrix、权限最小化清单、资金/持仓/订单对账合同、RTO/RPO、备用数据与 kill-switch 演练证据。
- **不得采用**：多账户并行比较真实成交需要明确授权、独立账本和合规审查；不能为了比较执行质量绕过 private/order/live 禁令。
- **公式/数字**：无项目公式；所有数值和机构陈述标记 `source_currentness_blocked`。

### 第 5 章：Execution Systems

- **论证链**：最新数据进入策略 → 生成结构化订单需求 → 经 API/人工控制提交 → 记录订单与成交 → 将 paper/实际结果和理论路径对账 → 归因软件、成本、流动性或 regime 偏差。
- **架构纠偏**：书中 ATS 把数据、策略和订单传输放在同一程序；本项目必须拆成 Data → Strategy (`Signal/Forecast/TargetPosition/OrderIntent`) → Portfolio/Risk → OMS/Execution → Fill/Ledger → Monitoring，任何 adapter 都不能替代风控。
- **自动化条件**：低频可以保留人工审批但必须有可审计输入、超时和撤销；高频并不只是换成 C++，还需要时钟同步、行情/订单状态机、幂等、限流、恢复、容量和故障安全。
- **成本限制**：ADV 1%、低价股过滤、市值四次根和固定阈值是经验规则；拆单降低冲击却增加时延/机会成本，必须用订单级 arrival、decision、submission、ack、fill 和 cancel 时间戳评估。
- **paper 限制**：paper 可发现数据时序、软件和运行问题，但常不模拟队列位置、部分成交、拒单、借券、动态 spread/impact、venue outage 和资金约束；paper P&L 不是 promotion 证据本身。
- **偏差诊断**：先核对 signal/order/fill 是否一致，再分解费用、spread、impact、delay、unfilled、borrow/funding 和数据版本；剩余差异才讨论过拟合或 regime，不允许把差异笼统归为“坏运气”。
- **BTC 映射**：需要 websocket gap/reconnect、rate-limit、post-only/IOC/FOK、reduce-only、funding、liquidation、mark/index、partial fill 和 cancel race 语义；无授权时所有 order/private/live 旗标保持 false。
- **美股映射**：需要 auction、TIF、halts、SSR、borrow/locate、odd lot、corporate action、session 和 T+1 语义；历史 plus-tick 例子只说明规则制度会导致可交易性断层。
- **共享动作**：建立 expected-vs-actual reconciliation：`Signal → TargetPosition → OrderIntent → RiskDecision → Order → Ack/Reject → Fill → Position/Cash/PnL`，每步记录版本和 blocker。
- **不得采用**：不得让策略程序直接提交订单；不得因 paper 运行一个月或小额 live 表现就解锁；不得以“真实交易才能发现过拟合”为理由污染 holdout 或启动 live 研究。
- **公式/数字**：`FORM-STR05-CH05-001` 至 `FORM-STR05-CH05-005` 均已回看原 PDF 并关闭为 `verified_concept_only`；历史 DDE/API、阈值、paper/live 推断和实际绩效均不迁移。

### 第 6 章：Money and Risk Management

- **论证链**：把目标定义为长期复合增长 → 用预期超额收益和协方差求 Kelly 配置 → 随权益与估计变化再平衡 → 用 fractional Kelly、历史损失和额外约束降低模型错配 → 管理市场、模型、软件、运营与人为风险。
- **成立条件**：收益过程近似稳定、均值和协方差可可靠估计、资产可按假定价格连续交易、融资和成本已净化、再平衡不会显著改变市场、目标确实是长期对数财富最大化。
- **数学限制**：`F*=C^-1M` 对均值误差和病态协方差极敏感，允许大幅多空权重；`f=m/s²`、`g=r+S²/2` 和 Gaussian 推导忽略跳跃、偏度、厚尾、非线性保证金、破产边界和有限样本。
- **风险限制**：half-Kelly 只是比例缩放，不是经过证明的安全阈值；用历史最大单期亏损限制杠杆无法覆盖未见事件；按亏损机械去杠杆可能与拥挤资金同时卖出并放大冲击。
- **止损限制**：止损不能保证成交价，gap 时只能实现更差价格；但书中“均值回归时不应止损”也不能覆盖模型失效、融资/保证金、流动性枯竭和错误仓位，项目仍需硬 kill、时间止损与风险限额。
- **估计限制**：用短 trailing mean/std 每日更新 Kelly 会把噪声、负均值和 regime 变化直接转成仓位，产生高换手与追涨杀跌；必须做 shrinkage、稳定性、turnover 和压力约束。
- **BTC 映射**：必须加入 funding、basis、mark/index、maintenance margin、liquidation waterfall、venue concentration、周末流动性、跳跃和 24/7 故障；Kelly 不能覆盖交易所清算非线性。
- **美股映射**：必须加入 borrow recall/fee、halts、auction/gap、sector/factor crowding、Reg-T/portfolio-margin、公司事件和隔夜跳空；历史 ETF 均值协方差不能当未来参数。
- **共享动作**：RiskDecision 先应用 gross/net、单资产/策略/venue、volatility、drawdown、liquidity、turnover、stress loss 和 loss-of-service caps，再允许任何优化权重；PnL 必须由 fills/positions/cash ledger 推导。
- **人为与软件风险**：错误仓位发现后按 incident/kill-switch 处理，不能等待“均值回归”；模型参数变更须重新预登记和验证，不允许因近期亏损临时覆盖生产规则。
- **不得采用**：full-Kelly、half-Kelly、半年 lookback、每日更新、历史最差损失比例、作者案例杠杆与“逐步小额实盘培养心理”都不构成本项目 sizing 或 live 依据。
- **公式/数字**：`FORM-STR05-CH06-001` 至 `FORM-STR05-CH06-006` 均已回看原 PDF 并关闭为 `verified_concept_only`；Kelly、half-Kelly、历史损失上限和示例杠杆不进入 production sizing。

### 第 7 章：Special Topics in Quantitative Trading

- **论证链**：先区分 mean reversion 与 momentum 的机制/时域 → 检查 regime 稳定性 → 对 spread 做 stationarity/cointegration → 用 factor/PCA 分解共同风险 → 设计与机制一致的 exit → 单独验证 seasonality/HFT → 最后再讨论 beta 与 leverage。
- **方法边界**：价格可在短周期均值回归、长周期趋势或反之；“均值回归更普遍”是经验观点，不是先验。均值回归对坏 tick、退市、基本面跳变和成本尤其敏感，动量对信息扩散期限、拥挤与进入延迟敏感。
- **regime 限制**：固定转移概率的 HMM 可能无法回答何时突变，但“输入大量特征寻找 turning point”会引入更严重的试验自由度。书中 GS 案例仅六个月、挑选最佳曲线和窗口，且没有真正锁定 holdout，不能证明 regime 模型。
- **协整限制**：ADF 拒绝单位根原假设不等于“95% 概率协整”；需要检验残差设定、lag、确定项、OLS 方向、多重配对、半衰期、结构突变、hedge-ratio 漂移和样本外稳定。平稳 spread 也不保证扣成本、借券和冲击后盈利。
- **因子限制**：`R=Xb+u` 只是线性分解，factor exposure/return 必须使用 PIT 基本面与可交易 universe；因子收益“延续到下一期”是额外预测假说。书中文字把 exposure 矩阵写成 `N×N`，而一般应为 `N×K`，需原版面复核。
- **PCA 限制**：主成分依赖估计窗口、标准化、缺失值和特征向量符号/排序；固定 exposure 与 factor-return momentum 假设不稳。书中负收益案例反而说明“解释方差”不等于“预测收益”。
- **退出限制**：fixed horizon、target、最新信号和 stop 是不同语义；OU half-life 估计依赖平稳、线性、参数稳定与噪声设定，不能直接称为“最优持有期”。均值回归策略也必须有结构破坏、时间、流动性和 hard risk exit。
- **季节性限制**：一年一次的日历效应有效样本极少，调整日期会增加 trial；期货还需正确 contract/roll、交割、假日、价格限制、carry 和 margin。书中汽油/天然气盈利序列不是当前证据。
- **HFT 限制**：大量交易只有在近似独立、均值稳定、成本可测时才提高 Sharpe；共同冲击、serial dependence、拥挤、queue、adverse selection 和 venue failure 会产生突然大亏。last-price 数据和 paper 均不足，不能以 real-time/live 作为唯一检验。
- **beta/leverage 限制**：低 beta 加杠杆可能提高历史 Sharpe，但融资、tail beta、相关上升、流动性和 deleveraging 会破坏等价；风险平价示例不是本项目配置参数。
- **BTC 映射**：候选应分为 cross-venue/basis/funding mean reversion、time-series momentum、volatility/liquidity regime、cointegrated spreads 和 microstructure；每类单独定义 venue、contract、funding、mark/index、depth、latency 和 liquidation。
- **美股映射**：PEAD/factor/seasonality 必须有 PIT earnings/expectations/fundamentals/constituents、公告可得时刻、borrow/locate、auction、corporate action 和真实日历；pair/factor 需行业事件与结构突变监控。
- **共享动作**：每个候选建立独立 hypothesis ID、economic mechanism、feature/label clock、trial count、baseline、purged WF、locked holdout、cost/capacity、failure monitor；不批量运行本章所有方法。
- **不得采用**：“最佳曲线一键 paper/real”、ADF 概率解释、平稳保证盈利、OU 半衰期即最优持有期、商品季节性继续盈利、HFT 不会突发巨亏、低 beta 加杠杆必优等结论全部拒绝。
- **公式/数字**：`FORM-STR05-CH07-001` 至 `FORM-STR05-CH07-009` 均已回看原 PDF 并关闭为 `verified_concept_only`；原始论文与案例未认证，HFT 仍因 depth、queue/fill、latency 和 replay 证据不足而 blocked。

### 第 8 章：Conclusion — Can Independent Traders Succeed?

- **论证链**：小资金降低市场冲击并允许低容量利基 → 机构规模、拥挤、激励和复杂度可能放大风险 → 独立者若能保持纪律与低成本可生存 → 容量饱和后需要新策略、数据和运营投入。
- **证据限制**：主要依据作者认识的幸存独立交易者和少数机构灾难，存在选择偏差、幸存者偏差与不可比规模；不能从叙事推出独立交易者具有普遍高 Sharpe。
- **容量结论**：策略收益随 capital、participation、holding horizon、venue depth 和 crowding 改变，容量必须是 backtest/paper/执行证据的函数，不是账户规模标签。
- **约束纠偏**：数学上约束会降低同一目标函数的最优值，但现实风险约束还能纠正模型错配、激励和尾部风险；不能因“自由度提高收益”删除 sector、gross、liquidity 或权限限制。
- **治理结论**：书中 rogue-trader 案例说明个人纪律不足以防欺诈或错误，需要 strategy/approval/execution/reconciliation 分权、不可变 fill/ledger、独立审计、异常告警和凭证最小权限。
- **增长限制**：增加策略、市场、频率或人员都会增加 trial、数据、执行、监控和相关性风险；表面不同策略可能持有相同暴露，必须做 factor/crowding 与压力相关检查。
- **BTC 映射**：小容量也会遇到薄深度、venue concentration、funding 和清算非线性；“提供流动性”不等于稳定盈利，adverse selection 和 exchange failure 可能瞬时放大损失。
- **美股映射**：低容量不能豁免 borrow、auction、halts、corporate action、PIT 和交易成本；长-only 更简单也不自动更安全。
- **共享动作**：每个 strategy/run 记录 capacity estimate、participation、crowding proxy、factor exposure、owner、approver、executor、reconciler 和 scale-up evidence；扩容需重新过 gate。
- **不得采用**：独立交易者成功、机构约束有害、长期总有 profitable niche、增加策略即可继续增长等观点不作为研究结论；对外募资与收益分成超出本地量化研发范围。
- **公式/数字**：无项目公式；账户规模、损失、回报与容量数字均为历史叙事，标记 `not_applicable`。

## L3 原始 PDF 复核结论

| 公式/项目 | 原 PDF 物理页 | 原 PDF 直接证据 | 结论与项目边界 |
|---|---:|---|---|
| `FORM-STR05-CH02-001` | `31-52` | 原文逐项讨论 benchmark、Sharpe、drawdown、成本、survivorship 和 data-snooping；明确参数过多会拟合历史偶然。 | `verified_concept_only`：只保留 candidate intake 字段；书中筛选阈值、近期表现与费用数字不迁移。 |
| `FORM-STR05-CH03-001` | `58-62` | 原 PDF 直接给出 split/dividend adjustment 讨论、调整链和数据库差异。 | `verified_concept_only`：只确认 corporate-action/PIT 风险；调整价不能替代 raw price、现金股息 ledger 和版本冻结。 |
| `FORM-STR05-CH03-002` | `67-69` | 原 PDF 给出收益、risk-free/excess return、Sharpe 及 `sqrt(N_T)` 年化，并以 `252×6.5=1638` 举例。 | `verified_concept_only`：公式结构已核；频率、无风险、独立性、BTC 24/7 和实际交易日历必须另定。 |
| `FORM-STR05-CH03-003` | `70-72` | 原 PDF 用 compounded return/equity、high watermark 计算 maximum drawdown 和 duration。 | `verified_concept_only`：只确认指标构造；项目权益必须来自 fills/positions/cash，另固定符号、恢复和缺失值口径。 |
| `FORM-STR05-CH03-004` | `73-81` | 原 PDF 定义 look-ahead bias，并建议截断未来数据后历史仓位应保持不变；同时讨论 lag。 | `verified_concept_only`：prefix-invariance 可进入合同，但不能覆盖修订数据、未来 universe、全样本变换、标签重叠和 execute lag。 |
| `FORM-STR05-CH03-005` | `75-82` | 原 PDF 明称 `252×自由参数数` 只是经验、非统计文献结论，并讨论 train/test、moving optimization、参数敏感性。 | `verified_concept_only`：拒绝全部经验阈值；moving optimization 也不能自动消除 trial/selection leakage。 |
| `FORM-STR05-CH03-006` | `84-89` | 原 PDF 在均值回归案例中用固定 5bp 乘权重变化扣成本并据此改变策略结果。 | `verified_concept_only`：只作成本敏感性示意；spread、impact、queue、partial fill、borrow/funding、latency 与机会成本另建。 |
| `FORM-STR05-CH05-001` | `101-107` | 原 PDF 将行情获取、算法生成订单和 broker 提交放入 semi/full automation，并展示 DDE/API 历史实现。 | `verified_concept_only`：只保留自动化分层；必须改写为 Strategy→Risk→OMS→Fill/Ledger，历史接口不复制。 |
| `FORM-STR05-CH05-002` | `109-110` | 原 PDF 给出 `$5`、`1% ADV`、10:1 和市值四次根等容量经验规则。 | `verified_concept_only`：确认其为 rule of thumb 并全部拒绝迁移；按当前订单簿、波动、参与率和压力状态校准。 |
| `FORM-STR05-CH05-003` | `109-112` | 原 PDF 说明拆分大单可降 impact 但增加 slippage，并将其定义为触发价与平均成交价差。 | `verified_concept_only`：只保留 trade-off；项目使用 decision/arrival/submission/fill、queue、partial fill 和 opportunity cost。 |
| `FORM-STR05-CH05-004` | `111-112` | 原 PDF 将 paper trading 用于发现软件与明显 look-ahead 问题。 | `verified_concept_only`：paper 只提供诊断证据，不模拟真实 queue/impact/borrow/funding，也不解锁 promotion。 |
| `FORM-STR05-CH05-005` | `112-116` | 原 PDF 列出 actual-vs-expected 偏差的过拟合、成本、时序、规则和 regime 原因，并声称部分偏差需小额实盘发现。 | `verified_concept_only`：保留归因清单；拒绝以 live 研究替代 locked holdout，残差不得称为 bad luck。 |
| `FORM-STR05-CH06-001` | `118-120` | 原 PDF 给出多策略 Gaussian Kelly `F*=C^-1M`，并在独立策略下化为 `f=m/s²`，说明均值和协方差语义。 | `verified_concept_only`：仅作无约束增长上界；均值误差、病态协方差、重尾、成本和不可交易权重使其不能直接 sizing。 |
| `FORM-STR05-CH06-002` | `120-122,134-135` | 原 PDF 连接 volatility drag、growth rate、Kelly 最优增长与 Sharpe，并依赖 Gaussian/连续近似。 | `verified_concept_only`：只解释增长—波动关系；不进入 production sizing 或绩效承诺。 |
| `FORM-STR05-CH06-003` | `120-128` | 原 PDF 因参数不确定与非 Gaussian 建议 half-Kelly，并讨论 leverage normalization、权益再平衡和 trailing re-estimation。 | `verified_concept_only`：half-Kelly、半年窗口和每日更新均非安全阈值；必须先过 hard caps、margin、流动性与 turnover。 |
| `FORM-STR05-CH06-004` | `121-126` | 原 PDF 用 SPY 及多资产历史样本演示 Kelly、Sharpe、融资后增长和组合杠杆。 | `verified_concept_only`：仅确认数值示意流程；历史数据、risk-free、复权、杠杆和结果不复用。 |
| `FORM-STR05-CH06-005` | `127` | 原 PDF 建议取 half-Kelly 与“可容忍单期回撤/历史最大损失”杠杆的较小值。 | `verified_concept_only`：方法明确但被拒绝；历史最大值不能覆盖未见尾部，改用多情景 stress、gap、流动性、venue 与 margin caps。 |
| `FORM-STR05-CH06-006` | `128-133` | 原 PDF 说明 stop 在跳空时无法保证价格，也讨论均值回归、亏损去杠杆、模型/软件/运营风险。 | `verified_concept_only`：区分策略 exit、hard risk stop、error-position kill 和 incident recovery；禁止等待均值回归。 |
| `FORM-STR05-CH07-001` | `138-142` | 原 PDF 明确价格可在不同时域同时 mean-reverting 与 trending，策略必须先指定条件、时域和 reference price。 | `verified_concept_only`：只建立候选分类；“均值回归普遍”不是先验。 |
| `FORM-STR05-CH07-002` | `143-147` | 原 PDF 描述 turning-point 与 hidden Markov/regime switching，并明确指出恒定转移概率等假设使其实际交易价值有限。 | `verified_concept_only`：高过拟合候选；需 nested/purged WF、trial ledger、稳定性和成本，禁止一键 paper/live。 |
| `FORM-STR05-CH07-003` | `148-154` | 原 PDF 展示 CADF/ADF、OLS hedge ratio、cointegration 与 correlation 的区别及 GLD/GDX 案例。 | `verified_concept_only`：公式与案例存在已核；p-value、deterministic terms、lag、方向、多重配对和结构突变必须重建。 |
| `FORM-STR05-CH07-004` | `155-158` | 原 PDF 定义 factor model、factor exposure/return 和 specific return，并给出截面关系。 | `verified_concept_only`：解释不等于预测；PIT fundamentals、维度、normalization、universe 和 OOS persistence 另验。 |
| `FORM-STR05-CH07-005` | `158-161` | 原 PDF 用 PCA 由历史 returns/covariance 提取 eigenvector/eigenvalue 并截断统计因子。 | `verified_concept_only`：只确认统计因子流程；centering、missing、rolling stability、因子数 trial 和成本另验。 |
| `FORM-STR05-CH07-006` | `162-164` | 原 PDF 用 OU 过程描述 spread，并给出 `ln(2)/θ` half-life，进而称其可决定持有期。 | `verified_concept_only`：公式概念已核；half-life 不是经验证最优期，需离散估计、参数不确定、结构破坏和 hard/time/liquidity exit。 |
| `FORM-STR05-CH07-007` | `165-173` | 原 PDF 讨论股票/商品季节性、固定日期交易和历史案例，同时承认股票季节性可能衰减。 | `verified_concept_only`：每个日期是独立 trial；真实日历、PIT universe、contract roll/expiry、carry、margin 和成本必须重建。 |
| `FORM-STR05-CH07-008` | `173-175` | 原 PDF 以 law of large numbers 解释高频大量“bets”与高 Sharpe，再据此讨论高杠杆。 | `verified_concept_only`：该论证依赖近似独立、稳定正均值和可测成本；depth、queue/fill、latency、adverse selection、replay 和 venue failure 未具备则 blocked。 |
| `FORM-STR05-CH07-009` | `175-177` | 原 PDF 用 low-beta 与 risk-parity 示例讨论 `23/77` 和 `1.8x` 杠杆。 | `verified_concept_only`：只保留融资后风险比较；权重、杠杆和历史 Sharpe 禁用，并加入 tail beta、相关跃升、流动性和 deleveraging。 |

## 单书完成边界

- 8/8 章 `L2` 已完成，27/27 个登记项目均直接回看原 PDF 并关闭为 `verified_concept_only`。
- “完成”只表示本书知识抽取和来源核对闭环，不表示公式适合实现、原始数据或论文已认证、案例已复现，也不产生策略参数或绩效结论。
- 本轮未运行回测、未修改参数、未查看 holdout、未调用 broker/private/order/paper/live endpoint；任何候选仍须另开研究票据并满足当前 evidence contract。
