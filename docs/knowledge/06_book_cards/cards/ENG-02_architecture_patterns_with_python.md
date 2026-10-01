---
book_id: ENG-02
title: Architecture Patterns with Python
authors: [Harry Percival, Bob Gregory]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Architecture Patterns with Python - Harry Percival and Bob Gregory - 原文.md
source_format: epub_text
source_sha256: e85612d49270aa964a99137f86bfe8bfa65683eacec0462c3152ac054ef1248d
source_line_count: 7338
card_status: complete_l2_no_quantitative_formula
chapter_count: 13
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: not_applicable
last_reviewed_at: 2026-07-13
---

# ENG-02：Architecture Patterns with Python

## 覆盖声明

已逐章阅读正文 13/13 章，并记录论证链、适用条件、反例、限制、项目映射和不采用项。本书没有需要转入量化计算的定量公式；表格仅总结架构权衡，代码片段仅用于理解模式，不作为生产实现。EPUB 文本存在标点乱码和少量重复段落，但章节顺序与语义连续，未影响本轮结论。

## 全书项目结论

- `existing_rule_confirmed`：项目现有 Strategy → Portfolio/Risk → OMS/Execution → Fill/Ledger 与 Domain → Service Layer → Repository/UoW → Adapter → Entrypoint 的依赖方向一致。
- `implementation_gap`：部分 builder/service 仍混合领域判定、文件读取、Git 查询、渲染和发布；BTC 与美股共享类型、证据读取和账本事务边界仍需由独立架构票据核定。
- `candidate_design`：优先引入窄 port、显式 UoW、composition root 和可重建 read model，不默认引入消息总线、CQRS 独立存储或微服务。
- `rejected_for_now`：把所有用例事件化、用 Redis Pub/Sub 充当可靠审计总线、让最终一致 read model 解锁 promotion，以及未经幂等设计自动重试订单路径。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 不得直接采用 | 待复核 |
|---|---|---|---|---|---|---|
| 1 Domain Modeling | `888-1197` | `L2/high`：EPUB 正文连续，无关键定量公式 | 模型是对适用域的有用压缩，不是现实本身；用统一语言、实体、值对象、领域服务和领域异常承载不变量。 | `existing_rule_confirmed`（共享）：`Signal`、`Forecast`、`TargetPosition`、`OrderIntent`、`RiskDecision`、`Fill` 应以领域语义和稳定身份/值语义区分。 | 不把每个名词都类化，不滥用 `NewType`、魔术方法或无行为对象；简单 CRUD 不因本章强行 DDD。 | `not_applicable` |
| 2 Repository Pattern | `1202-1529` | `L2/high`：正文、权衡表和边界说明完整 | Repository 以“内存集合”式窄接口隔离持久化，依赖应由 ORM/adapter 指向领域模型；fake 的难度可反向暴露抽象是否过宽。 | `implementation_gap`（共享）：行情、PIT 数据、artifact、ledger、strategy registry 和 evidence 读取应通过稳定 repository/port；提交职责不藏在 repository 内。 | 不照搬 SQLAlchemy classical mapping；ORM 已足够时不再叠层，简单 CRUD 不需要 Repository。 | `not_applicable` |
| 3 Coupling and Abstractions | `1534-1787` | `L2/high`：完整覆盖 functional core、DI、fake/mock 权衡 | 先把外部状态压缩为简单输入，把期望动作表示为简单输出，再由 imperative shell 执行；抽象应位于真正的变化缝隙。 | `candidate_design`（共享）：把 Clock、DataSource、GitState、ArtifactStore、ExchangeRules 和 BrokerAdapter 变成窄 port；gate/policy 核心接收快照并输出决定。 | 不教条禁止 mock，不为测试凭空制造接口；仍需少量真实集成/E2E 验证 adapter。 | `not_applicable` |
| 4 Flask API and Service Layer | `1792-2095` | `L2/high`：正文与 pros/cons 完整 | Service Layer 编排读取、校验、领域调用和提交；入口只解析协议，领域规则仍留在模型，避免倒置测试金字塔。 | `implementation_gap`（共享）：巨型 builder/service 应拆为纯 gate/replay policy、I/O adapter、renderer 和 publisher，CLI/API 不自行判 gate。 | 不把业务规则全部搬进 service 形成贫血领域；未出现编排重复时不新增一层。 | `not_applicable` |
| 5 TDD in High and Low Gear | `2100-2267` | `L2/high`：完整覆盖测试层级与反例 | 服务层测试降低重构耦合，领域层测试提供设计反馈和可执行语言；日常高档、复杂建模低档，二者按问题切换。 | `existing_rule_confirmed`（共享）：纯策略/风控单测、service/contract 测试、真实数据库/adapter 集成测试和少量 E2E 各自承担不同证据。 | 不把所有领域测试迁走，不仅为测试方便新增伪用例；测试替身不能替代真实数据库和 broker sandbox 合同。 | `not_applicable` |
| 6 Unit of Work | `2272-2529` | `L2/high`：完整覆盖提交、回滚、真实数据库差异与局限 | UoW 提供稳定快照和原子边界；显式 commit、默认 rollback 使系统默认安全，并把持久化接口缩到最小。 | `implementation_gap`（BTC/美股）：fill、position、cash ledger 和对账状态应在同一明确 UoW 中成功或全部失败；promotion 状态变更也需单一原子边界。 | 不假设 context manager 能让数据库与多个文件跨介质原子；不以 SQLite 事务测试替代目标数据库隔离、并发和嵌套事务测试。 | `not_applicable` |
| 7 Aggregates and Consistency Boundaries | `2534-2901` | `L2/high`：并发方案、性能条件和数据库差异均有明确警告 | Aggregate 是最小一致性和并发边界，只允许根对象修改内部状态；边界选择需同时满足不变量、锁竞争和数据规模。 | `candidate_design`（共享）：按 account/run/order-ledger 识别账本聚合；`artifacts/**/latest` 继续单写者；同一命令只修改一个清晰聚合。 | 不预设“一种正确聚合”，不照搬版本号或隔离级别；重试前必须验证幂等，SQLite/Postgres 语义不可混同。 | `not_applicable`；具体隔离级别需按目标存储另立规格 |
| 8 Events and the Message Bus | `2938-3211` | `L2/high`：三种事件收集方案及失败模式均覆盖 | Domain Event 表示已经发生的事实，可把次要反应与主用例分离；message bus 只是路由，不天然异步、可靠或并发。 | `concept_only`（共享）：审计、监控和 replay 可消费不可变事实事件；若采用，事件在成功提交后发布并保留因果/版本信息。 | 不把 `OrderIntent`、gate rebuild 请求或下单愿望命名为已发生事件；不接受 commit 暗中触发不可见副作用、循环事件链或无界同步 handler。 | `not_applicable` |
| 9 Message Bus as Application Core | `3216-3531` | `L2/high`：完整覆盖统一 handler、跨 UoW 和权衡 | 把外部输入与内部反应统一为消息可降低新增流程的结构成本，但会引入字段重复、不可预测结束时间和跨事务部分成功。 | `rejected_for_now`（共享）：当前模块化单体不需要把所有 service 改成 handler；仅可在 replay/monitoring 有明确收益时小范围试点。 | 不因形式统一就事件化全部用例；跨两个 UoW 的流程必须先定义补偿、重放、幂等和缺失事件检测。 | `not_applicable` |
| 10 Commands and Command Handlers | `3536-3737` | `L2/high`：命令/事件错误语义、重试和监控局限完整 | Command 表示指定接收者必须执行的意图，失败应显式返回；Event 是广播事实，可独立失败，但必须可观察、重试和最终处置。 | `existing_rule_confirmed`（BTC/美股）：`OrderIntent` 不是 `Fill`；执行命令必须经过 Risk/OMS 并 fail loudly，成交/拒单/撤单才是事实事件。 | 不对非幂等 broker/order 操作做通用自动重试；日志不是可靠消息存储，超过重试上限必须进入可审计 blocked/dead-letter 状态。 | `not_applicable` |
| 11 Events Across Microservices | `3742-3951` | `L2/high`：覆盖时序耦合、外部事件、可靠性缺口 | 服务应围绕业务动作和一致性边界，而非数据库名词拆分；异步消息降低时序耦合，但把复杂度转移到顺序、幂等、投递语义和可观测性。 | `rejected_for_now`（共享）：保持模块化单体；未来拆分数据、执行或监控服务前，先定义 schema version、outbox/inbox、幂等键、replay 和审计合同。 | 不按表拆微服务，不把 Redis Pub/Sub 示例视为可靠队列选型；内部事件不得无筛选升级为外部公开合同。 | `not_applicable` |
| 12 CQRS | `3956-4297` | `L2/high`：读写差异、四种实现和重建路径完整 | 写模型保护不变量，读模型为查询优化且可短暂陈旧；read model 必须可从权威写侧/事件重建，写命令仍需重新校验当前状态。 | `candidate_design`（共享）：dashboard、gate 状态和监控视图可由已提交 evidence/ledger 构建独立 read model，并记录 freshness、HEAD 和重建来源。 | read model 不得解锁 promotion/paper/live；不得用陈旧 dashboard 替代 current-HEAD gate 证据；查询不复杂时不建独立存储。 | `not_applicable` |
| 13 Dependency Injection and Bootstrapping | `4302-4661` | `L2/high`：显式/隐式依赖、三种注入方式和集成测试完整 | Composition root 集中初始化和能力注入；显式依赖让生产 adapter、fake 和受限实现可替换，但应优先手工、窄而透明的 DI。 | `candidate_design`（共享）：统一注入 Clock、DataRepository、ArtifactStore、PolicyVersion、ExchangeRules 和默认不可下单的 BrokerAdapter；entrypoint 不自行创建高权限依赖。 | 不引入反射式 DI 魔法或全局非线程安全 bus；默认参数若构造时有副作用必须延迟；fake 仍需配套“较真实”集成测试。 | `not_applicable` |

## L2 论证链与采用条件

### 1. Domain Modeling

- **论证链**：业务专家的统一语言 → 具体例子与不变量 → 值对象/实体/领域服务 → 快速领域测试 → 可演进核心模型。
- **成立条件**：问题包含会变化且需要保护的业务规则；团队能与领域专家核对词义和反例。
- **限制与反例**：模型只在其适用域内有效；简单减法示例本身不足以证明 DDD 成本合理；实体哈希、静默失败和过度类型化都有额外风险。
- **项目动作**：将策略输出、风险决策、订单意图、成交事实和账本实体的身份/值语义写入共享领域 ADR，不因同名字段混用概念。

### 2. Repository Pattern

- **论证链**：领域不依赖存储 → Repository 提供最小集合接口 → real/fake adapter 共享 port → 快速 service 测试与可替换持久化。
- **成立条件**：领域复杂度或替换/测试需求足以覆盖新增抽象成本。
- **限制与反例**：ORM 已提供部分隔离；手工 mapping 与额外层会增加维护和陌生成本；CRUD 包装器通常不值得。
- **项目动作**：先盘点散落的 SQLite、JSON、artifact 和 Git 读取点，只为重复且高风险的读写建立窄 repository，提交由 UoW 控制。

### 3. Coupling and Abstractions

- **论证链**：识别 I/O 与决策耦合 → 把状态抽象为简单数据 → 纯函数输出动作 → shell 执行动作 → edge-to-edge fake 验证。
- **成立条件**：能找到稳定输入/输出缝隙，且抽象同时改善测试与新用例，而不是只服务 mock。
- **限制与反例**：显式依赖会增加参数与结构；mock/patch 并非永远错误；端到端验证仍不可省。
- **项目动作**：gate builder 的纯判定函数只消费 evidence snapshot，不直接读文件、Git、网络或时钟；renderer/publisher 留在外壳。

### 4. Service Layer

- **论证链**：入口出现取数、校验、错误和提交编排 → 提取用例层 → fake repository/UoW 测试整条工作流 → 入口变薄。
- **成立条件**：同一用例可能由 CLI、API、调度器等多个入口驱动，或入口已经出现重复编排。
- **限制与反例**：纯 Web CRUD 可直接用薄 controller；把规则塞进 service 会造成贫血模型。
- **项目动作**：把 promotion、replay、ledger reconciliation 的领域政策与 I/O、报告渲染、latest 发布拆开，但不创建无业务含义的空层。

### 5. TDD in High and Low Gear

- **论证链**：低层测试提供设计反馈但耦合高，高层测试覆盖工作流且重构稳定 → 根据任务切换档位 → 维持测试金字塔。
- **成立条件**：service API 是稳定用例边界，领域关键不变量仍有直接测试。
- **限制与反例**：高层测试看不到对象设计问题，低层测试会把实现粘死；只保留一种层级都会失真。
- **项目动作**：研究公式/风控不变量用低档单测，builder/use-case 用高档测试，SQLite/adapter 用集成测试，promotion 仅保留少量完整链路测试。

### 6. Unit of Work

- **论证链**：多个相关写操作需稳定快照与整体成功 → UoW 包含 repository 和事务 → 显式 commit → 任何异常或早退默认 rollback。
- **成立条件**：存储支持明确事务，且边界与业务用例一致。
- **限制与反例**：ORM session 已提供 UoW；多线程、嵌套事务、跨数据库/文件写入和目标数据库隔离语义仍需专门设计。
- **项目动作**：账本写入采用显式 commit/fail-closed；文件 artifact 与数据库状态不得假装单事务，需 immutable write + pointer swap/补偿合同。

### 7. Aggregates and Consistency Boundaries

- **论证链**：先定义不变量 → 找到必须共同一致的最小对象集 → 只通过 aggregate root 修改 → repository 只返回 aggregate → 用锁/版本保护并发。
- **成立条件**：边界足够小以允许并发，又足够大以完整保护不变量；数据规模与查询模式经测量可接受。
- **限制与反例**：聚合没有唯一答案；乐观锁需要冲突重试，悲观锁可能死锁；数据库隔离定义不同；跨聚合只能接受或治理最终一致。
- **项目动作**：先从 Fill/Position/Cash 的账本不变量反推聚合，而非从表结构命名；并发测试必须使用目标数据库语义。

### 8. Domain Events and Message Bus

- **论证链**：模型记录事实事件 → bus 将事实映射到后续 handler → 主用例与通知/审计分离 → 可跨聚合最终一致。
- **成立条件**：事件是不可变已发生事实，发布点、失败处理和 handler 可见性明确。
- **限制与反例**：书中 bus 同步且不可靠；UoW 自动发布隐藏副作用；事件链会出现循环、性能和调试问题。
- **项目动作**：只把成功提交后的成交、拒单、账本变更和 gate verdict 作为事实；研究信号和订单意图继续保持命令/候选语义。

### 9. Message Bus as Application Core

- **论证链**：外部输入与内部事件统一为消息 → handler 采用同一签名 → bus 收集新事件并串联 UoW → 新流程只增加消息与 handler。
- **成立条件**：流程复杂度高到足以抵消 bus、字段重复和调试成本，并具备跨事务恢复能力。
- **限制与反例**：多个 UoW 会部分成功；返回值暴露读写混合；Web 请求结束时间不再直观；事件与模型字段双重维护。
- **项目动作**：当前只保留概念，不重构全系统；若监控/replay 试点，先做单一事实流和故障注入验收。

### 10. Commands and Command Handlers

- **论证链**：把“希望发生”与“已经发生”分开 → command 单接收者、失败冒泡 → event 多订阅者、失败隔离 → 日志/重放/有限退避恢复。
- **成立条件**：单命令能在一个一致性边界内原子完成，事件 handler 幂等且有失败终态。
- **限制与反例**：事件失败并非自动安全；日志可重放示例不足以构成可靠队列；通用重试可能重复外部副作用。
- **项目动作**：订单命令必须携带幂等键、权限和风险证据；网络超时不得推断“未下单”，必须经查询/对账确定事实。

### 11. Events Across Microservices

- **论证链**：按名词/表拆服务产生双向 RPC 与时序耦合 → 按业务动词和一致性边界拆分 → 通过事件弱化远距离耦合。
- **成立条件**：服务能独立提交、消息可持久化、消费者幂等、schema 可演进并有端到端追踪。
- **限制与反例**：异步只转移复杂度；Pub/Sub 不保证可靠投递；全局流程更难看见，at-least-once/at-most-once 需要明确选择。
- **项目动作**：在单体边界尚未稳定前不拆服务；未来外部事件必须区分内部/公开 schema，并有 outbox、重放和版本治理。

### 12. CQRS

- **论证链**：写侧为不变量付出复杂度，读侧只需高效查询 → 分离 command/query → 可用 SQL、ORM 或独立 read model → 事件更新并可从权威状态重建。
- **成立条件**：读写访问模式明显不同，陈旧窗口可接受，且写侧在执行时重新验证真值。
- **限制与反例**：独立 read store 增加同步与运维成本；查询简单时 repository/SQL 足够；现实世界数据本就可能过期。
- **项目动作**：监控与 dashboard 可缓存，但必须显示 source run、commit、as-of 和 freshness；promotion gate 只读 current-HEAD 权威 evidence。

### 13. Dependency Injection and Bootstrapping

- **论证链**：隐式 import/patch 使副作用和测试耦合 → 显式依赖 → composition root 集中初始化与注入 → real/fake/less-fake adapter 分层验证。
- **成立条件**：存在多个 adapter 或权限能力需要按运行模式替换；注入点可集中在少数 handler/use-case。
- **限制与反例**：反射 DI、依赖链和全局 bus 会引入魔法与线程问题；构造默认依赖可能立即产生副作用。
- **项目动作**：bootstrap 默认注入无下单能力的 adapter，paper/live 能力必须显式授权；所有高权限依赖在 composition root 可审计地装配。

## 对 Agent 的可执行规则

1. 先识别领域不变量和一致性边界，再讨论表、框架或消息中间件。
2. 纯研究/风控/gate policy 不读取外部状态，只接收显式快照并输出领域决定。
3. 所有持久化写入采用显式 commit、默认 rollback；跨文件与数据库不得伪装为原子事务。
4. `OrderIntent`、command、event、fill 和 ledger record 必须语义分离；事实只能在成功提交或权威外部确认后产生。
5. 自动重试只适用于已证明幂等的操作；订单超时先对账，禁止盲目重发。
6. read model 必须标识 freshness、HEAD 和可重建来源，且不得作为 promotion 解锁证据。
7. 保持模块化单体；消息总线、独立 CQRS store 和微服务须以故障恢复收益证明其复杂度。
8. composition root 默认装配最低权限 adapter；任何 private/order/live 能力仍需显式授权和独立 gate。

## 公式与数字复核结论

- 本书没有进入量化策略、组合、风险或执行计算的公式。
- 章节中的测试计数、示例数量、重试次数和性能数量级均为教学例子，不转入项目参数。
- 架构 pros/cons 表为定性总结，已在逐章限制中记录，不需要 L3 数值复核。
- 因此本卡 `formula_review_status = not_applicable`；该状态不表示书中代码已获生产实现批准。
