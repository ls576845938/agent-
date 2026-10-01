---
book_id: ENG-03
title: Designing Data-Intensive Applications
authors: [Martin Kleppmann]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Designing Data-Intensive Applications - Martin Kleppmann - 原文.md
source_format: epub_text_original_epub_cross_checked
source_sha256: 9335e35dd351aeb1cc51b1f9194d5f2b1330fd5ac78b94c89842151506bc2206
source_line_count: 16796
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Designing Data-Intensive Applications The Big Ideas Behind Reliable, Scalable, and Maintainable Systems (Martin Kleppmann) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_source_sha256: 4a82453aae813734835b79a58c49edcfeca5e95cd5e7c2aff958d9bff8125689
original_source_chapter_files: 12
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 12
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 120_ch01_ch12_items_verified_concept_only
last_reviewed_at: 2026-07-15
---

# ENG-03：Designing Data-Intensive Applications

## 覆盖声明

本卡已核对 12 章正文边界、主要子主题和 `L1` 项目映射，并完成第 1—12 章逐段 `L2` 语义精读。现已直接核对原 EPUB 的 OPF spine、`OEBPS/ch01.html`—`ch12.html` 与全部 h1/h2 主题，将 120 个性能、数据模型、存储、兼容性、复制、分区、事务、分布式故障、一致性/共识、批处理、流处理和可审计数据流条目关闭为 `verified_concept_only`。该状态只确认概念、算法关系和迁移边界；历史产品能力、性能数字和当前实现仍须独立验证。

## L3 原始 EPUB 复核结论

| 范围 | 原 EPUB 文件 | 已核方法簇 | 队列状态 |
|---|---|---|---|
| Ch01—03 | `OEBPS/ch01.html`—`ch03.html` | reliability/load/tail/maintainability、relational/document/graph/query、hash/LSM/B-tree/index/column storage | 30 项均为 `verified_concept_only` |
| Ch04—06 | `OEBPS/ch04.html`—`ch06.html` | encoding/schema/dataflow/RPC、replication/read guarantees/conflicts/quorum、partition/index/rebalance/routing | 30 项均为 `verified_concept_only` |
| Ch07—09 | `OEBPS/ch07.html`—`ch09.html` | ACID/isolation/serializability、partial failure/clocks/fencing/system model、linearizability/causality/2PC/consensus | 30 项均为 `verified_concept_only` |
| Ch10—12 | `OEBPS/ch10.html`—`ch12.html` | batch/join/materialization、stream/CDC/event time/join/fault tolerance、derived data/end-to-end correctness/privacy | 30 项均为 `verified_concept_only` |

## 全书项目映射

- `existing_rule_confirmed`：当前项目的 append-only、lineage、schema evolution、snapshot、replay、PIT 和 fail-closed 方向与本书一致。
- `implementation_gap`：BTC、美股证据仍存在 `latest` 与 current HEAD 不一致、不同 builder 重复读取与发布语义的问题。
- `rejected_for_now`：单机 SQLite 与本地 artifact 不因本书讨论分布式系统而自动迁移到复杂集群。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Reliable, Scalable, Maintainable Applications | `274-779` | `L2/high` | 可靠性是特定fault不升级为service failure；扩展性必须绑定load parameters与response-time distribution；可维护性依赖operability、simplicity和evolvability。 | `existing_rule_confirmed`：量化数据/gate/执行链需定义故障模型、SLO、p50/p95/p99、恢复与重放，而非笼统称稳定或可扩展。 | `FORM-ENG03-CH01-001`—`010` |
| 2 Data Models and Query Languages | `782-1585` | `L2/high` | relational、document和graph模型分别适合不同关系密度与访问路径；schema-less实为schema-on-read，declarative query将执行策略与业务语义分离。 | `existing_rule_confirmed`：raw、PIT snapshot、experiment、ledger和read model按不变量/查询模式分模；禁止万能JSON与展示表反向成为真值。 | `FORM-ENG03-CH02-001`—`010` |
| 3 Storage and Retrieval | `1588-2317` | `L2/high` | append log、hash、SSTable/LSM、B-tree、secondary index与column store在read/write/space amplification、range、recovery和analytics间权衡。 | `existing_rule_confirmed`：SQLite/Parquet/artifact选型先冻结真实工作负载、durability/recovery与benchmark；index和materialized view均视为可重建派生状态。 | `FORM-ENG03-CH03-001`—`010` |
| 4 Encoding and Evolution | `2320-3007` | `L2/high` | compatibility取决于writer/reader schema和dataflow生命周期；数据库、RPC与message broker具有不同版本共存、重试和未知字段风险。 | `existing_rule_confirmed`：artifact/event/API必须版本化并做old-reader/new-writer双向测试；RPC不得伪装local call，未知结果先reconcile。 | `FORM-ENG03-CH04-001`—`010` |
| 5 Replication | `3082-4061` | `L2/high` | single-/multi-leader与leaderless复制在durability、availability、lag、conflict和read guarantees间权衡；quorum交集不自动保证最新值或线性一致。 | `existing_rule_confirmed`：共享数据只认immutable manifest/commit；副本、cache和latest pointer必须报告lag、read guarantee、failover与conflict policy。 | `FORM-ENG03-CH05-001`—`010` |
| 6 Partitioning | `4064-4463` | `L2/high` | range/hash partition影响range query与热点，secondary index决定scatter/gather或跨分区写，rebalance和routing本身会制造负载与陈旧metadata。 | `existing_rule_confirmed`：symbol/date/run分区保持PIT与stable ownership；并行worker按manifest/halo确定性归并，异常使整run fail-closed。 | `FORM-ENG03-CH06-001`—`010` |
| 7 Transactions | `4466-5535` | `L2/high` | atomicity是abortability，ACID consistency依赖应用不变量；read committed、snapshot isolation仍可能lost update、write skew和phantom，serializability实现各有代价。 | `existing_rule_confirmed`：order/fill/position/cash与artifact publish从不变量反推UoW；SQLite隔离与retry必须用并发fixture验证。 | `FORM-ENG03-CH07-001`—`010` |
| 8 The Trouble with Distributed Systems | `5538-6503` | `L2/high` | 网络、进程和时钟存在unbounded delay与partial failure；timeout不能区分request loss、remote crash、slow execution或response loss，lease需fencing保护。 | `existing_rule_confirmed`：private/order/live仍禁用；任何远端unknown result先reconcile，事件排序依赖causality/sequence而非wall clock。 | `FORM-ENG03-CH08-001`—`010` |
| 9 Consistency and Consensus | `6506-7723` | `L2/high` | eventual、linearizable与serializable是不同保证；causality、total-order broadcast、2PC和consensus分别解决不同顺序/提交问题，并以协调、可用性和运维复杂度为代价。 | `existing_rule_confirmed`：唯一性、leader/lease、latest单写者和跨分区提交必须声明所需保证、epoch/quorum/fencing及失败终态，不能以CAP或quorum口号替代证据。 | `FORM-ENG03-CH09-001`—`010` |
| 10 Batch Processing | `7756-8671` | `L2/high` | batch以有界不可变输入追求throughput和可重跑；sort、partition、join、skew、deterministic retry与完整派生输出共同决定正确性和恢复。 | `existing_rule_confirmed`：研究、回测和证据builder使用冻结输入、run manifest、确定性分片/归并、完整输出与原子发布，不直接任意写在线真值。 | `FORM-ENG03-CH10-001`—`010` |
| 11 Stream Processing | `8674-9643` | `L2/high` | broker、partition log、offset、CDC、event time/window/join和state recovery共同定义重放语义；内部checkpoint不等于外部side effect exactly-once。 | `implementation_gap`：WS断线补数、去重、offset/retention/backpressure、PIT time-dependent join和external-effect reconcile需统一合同。 | `FORM-ENG03-CH11-001`—`010` |
| 12 The Future of Data Systems | `9646-10849` | `L2/high` | system of record经确定性数据流派生view；end-to-end operation ID、timeliness/integrity分离、约束范围与持续审计比盲信单组件保证更可靠。 | `existing_rule_confirmed`：不可变event/manifest、current-HEAD derivation、replay checksum和端到端对账构成证据DAG；展示与缓存不是source of truth。 | `FORM-ENG03-CH12-001`—`010` |

## 已完成 L2：第 1 章

### 第 1 章：故障模型、负载参数与尾延迟 SLO

- **论证链**：系统由数据库、cache、index、queue与batch等组件组合后，应用本身承担跨组件正确性。fault是组件偏离spec，failure是整体未提供承诺服务；硬件fault往往较独立，软件bug、资源耗尽和依赖退化更可能相关并形成级联，人为配置错误则需通过安全接口、隔离环境、渐进发布、监控与可恢复设计降低影响。scalability不是标签，必须先定义QPS、read/write ratio、fan-out、active users或data volume等load parameters，再观察throughput和response-time distribution。maintainability由operability、simplicity和evolvability共同决定。
- **成立条件**：每个量化服务声明service contract、fault set、failure state、SLO/error budget、load vector、capacity headroom、p50/p95/p99/max、timeout、queue/backpressure、RTO/RPO和degraded mode。性能基准固定输入、缓存、并发、硬件与measurement window；尾延迟按end-to-end fan-out测量。生产保护优先消除不可逆security/data-loss fault；可恢复fault通过checksum、replay、reconcile、canary和deterministic rollback验证。
- **局限与反例**：平均延迟掩盖tail，单机吞吐不代表end-to-end capacity，历史Twitter或disk MTTF不是当前系统参数。冗余会引入共同软件、配置、时钟和依赖fault，并不自动可靠。chaos injection只有在隔离、blast radius、abort和恢复证据齐全时才合理；本项目当前研究员边界不运行生产故障实验。所谓simplicity也不能靠隐藏状态、无schema JSON或吞异常实现。
- **项目动作**：建立`DataServiceReliabilityEvidence`：保存contract、load/SLO、fault injection或synthetic fixture、observed failure、detection、containment、recovery、replay checksum和current-HEAD。BTC/美股builder、latest pointer和dashboard同时报告freshness、source run、HEAD、partial/failed状态及恢复动作；timeout、partial和corrupt输出默认fail-closed。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH01-001`—`010`；历史数字只作定位，性能结论必须在当前机器与真实工作负载重测。

## 已完成 L2：第 2 章

### 第 2 章：领域关系、查询模式与 schema-on-read 代价

- **论证链**：document model利用局部性表达self-contained tree，但many-to-many和共享实体会转化为应用join与一致性负担；relational model把关系独立化并由declarative query交给optimizer；graph model适合关系本身不断扩展的场景。normalized reference减少重复但增加join，denormalization改善局部读取却增加写同步。declarative query隐藏访问路径，imperative traversal更容易被物理布局或schema变化绑定。所谓schemaless只是约束从write-time转移到read/application-time。
- **成立条件**：先按aggregate/invariant、relationship cardinality、query/read-write pattern、evolution和PIT语义选model。raw event、canonical instrument、release vintage、experiment/run、order/fill/ledger和dashboard read model分别定义稳定ID、reference、null/default、units和version。任何denormalized/read model保存source IDs、build version、as-of、freshness和rebuild path。
- **局限与反例**：document locality只在整文档共同读取且大小受控时成立；many-to-many、局部更新、并发写和cross-document constraints会削弱优势。relational、document或graph都能模拟其他模型，能表达不等于易维护或性能合适。NoSQL、JSON、graph或Datalog名称不构成选型证据；历史产品join、schema和query能力可能已变化。
- **项目动作**：增加`DataModelDecisionEvidence`，记录domain relation、cardinality、query set、write conflicts、PIT/version、constraints、migration和current benchmark。展示表只能是projection；promotion、position、cash与fill仍由权威ledger/manifest重建。禁止因方便把所有artifact塞入无版本JSON blob。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH02-001`—`010`；重点验证document-relational impedance、schema-on-read、query locality与历史产品能力。

## 已完成 L2：第 3 章

### 第 3 章：存储放大、恢复语义与派生索引

- **论证链**：append-only log提供顺序写和较简单crash recovery，但读取需要index，空间回收依赖segment compaction/tombstone。SSTable/LSM以memtable、sorted runs、merge和Bloom filter换取高写吞吐与range scan；B-tree原地page update借WAL和latch维持durability/concurrency。secondary/compound/full-text index服务不同query。OLTP和analytics的访问形态不同，column store、compression、sort order和materialized aggregate以写入/刷新成本换scan效率。
- **成立条件**：存储决策冻结record/key cardinality、point/range/scan比例、append/update/delete、latency SLO、durability、recovery、retention、compaction、memory和并发。所有index/view/cube均标为derived，可由immutable source重建并校验checksum。benchmark报告read/write/space amplification、p95/p99、CPU/I/O/RSS、compaction stall、checkpoint/recovery和cold/warm差异。
- **局限与反例**：append-only不等于immutable truth，compaction会丢历史版本，除非保留独立raw/audit层。LSM不总比B-tree快，merge debt、write amplification、Bloom false positive和range overlap会制造尾延迟；B-tree也受page split、WAL/fsync和fragmentation影响。column store不适合所有点写/低延迟事务。书中磁盘、压缩和产品性能数字不能迁移到SSD、当前SQLite/Parquet或本项目数据量。
- **项目动作**：增加`StorageWorkloadEvidence`，保存workload hash、engine/layout/index、durability/fsync、checkpoint/compaction、benchmark和recovery drill。raw market/audit保持append-only版本；artifact/latest采用完整写入、hash验证、原子pointer swap，绝不将index、cache、materialized view当source of truth。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH03-001`—`010`；需要当前硬件microbenchmark与crash/recovery fixture，不进行基础设施迁移。

## 已完成 L2：第 4 章

### 第 4 章：writer/reader schema、滚动升级与远程调用失配

- **论证链**：encoding把memory object转为bytes，但language-native serialization常带兼容与安全问题；JSON/XML/CSV广泛却在number、binary和schema上含糊；Thrift/Protobuf以field tags演化，Avro由writer schema与reader schema resolution解码。forward compatibility要求old reader处理new writer，backward compatibility要求new reader处理old writer。database、RPC和message dataflow决定版本共存时长；旧代码读取新数据后再写回可能丢unknown fields。RPC存在网络延迟、timeout、重复执行和结果未知，不能当local function。
- **成立条件**：每个artifact/event/API保存schema ID/version、writer code/HEAD、units、required/optional/default、unknown-field policy和compatibility matrix。字段只按允许规则增加/删除/改type，复用tag和静默改语义禁止。rolling upgrade同时测试old-reader/new-writer与new-reader/old-writer；archive保留writer schema。remote command使用idempotency key、deadline、retry budget、dedupe和reconcile-before-retry。
- **局限与反例**：有schema不等于语义兼容，字段同名但单位、时钟、枚举或default改变仍会破坏系统。JSON数字可丢大整数精度，CSV缺稳定schema，unsafe deserialization可执行任意对象逻辑。message broker能buffer/redeliver但会产生重复、乱序和积压；actor/location transparency不能消除网络部分失败。书中具体编码大小和产品版本已过时。
- **项目动作**：增加`SchemaCompatibilityEvidence`：保存writer/reader fixtures、golden bytes/JSON、round-trip、unknown fields、old/new matrix、migration、rollback和archive decode。量化`Signal/Forecast/TargetPosition/OrderIntent/Fill/Ledger`消息必须显式version；trade/order timeout不得盲重发，先查询权威状态并对账。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH04-001`—`010`；重点复核field-tag、Avro resolution、numeric precision、unknown-field retention与RPC failure semantics。

## 已完成 L2：第 5 章

### 第 5 章：复制滞后、冲突与读取保证

- **论证链**：leader复制将写顺序集中到leader；同步副本提高已确认写的耐久性但降低可用性，异步副本允许lag并可能在failover丢已确认写。read-after-write、monotonic read和consistent-prefix分别解决不同陈旧读异常。multi-leader把冲突检测推迟到异步复制，leaderless以read/write quorum、read repair和anti-entropy修复副本，但sloppy quorum、并发写、clock skew与stale replica使“法定人数”不等于强一致。
- **成立条件**：复制证据声明authority/leader、ack条件、replication log position、lag metric、read routing、failover RPO/RTO、split-brain/fencing、conflict relation与merge policy。任何read model/cache/dashboard明确read guarantee和staleness bound；新副本从consistent snapshot加精确log offset恢复。
- **局限与反例**：异步ack不是durability保证；failover可能丢写、重复ID或双leader。last-write-wins依赖不可靠wall clock并会静默丢并发写。`w+r>n`只保证集合交集，在sloppy quorum、并发、失效窗口和弱durability下仍可能读不到最新。版本向量表达因果，不提供业务合并语义。
- **项目动作**：增加`ReplicationConsistencyEvidence`，保存commit/log offset、replica lag、read guarantee、failover、conflicts、repair和current-HEAD。跨代理交付继续只认已提交deliverable与immutable manifest，worktree副本和`latest`展示不作权威事实。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH05-001`—`010`。

## 已完成 L2：第 6 章

### 第 6 章：分区热点、二级索引与重平衡

- **论证链**：range partition保留局部range scan但顺序key易热点，hash partition均匀负载却丢失range locality；极端key仍需额外拆分。document-local secondary index写局部但查询scatter/gather，term-global index读集中但写跨分区且常异步。rebalance必须平衡数据、请求和恢复成本，`hash mod N`在节点数变化时搬动近乎全部key；routing metadata需要一致来源。
- **成立条件**：分区合同保存partition key/hash/version、boundaries、owner、replicas、hot-key policy、secondary-index freshness、rebalance state和routing epoch。并行研究分片使用stable atom ID、owner区间、lookback/label halo、partition manifest和确定性reduce；跨分区约束显式验证。
- **局限与反例**：均匀key count不等于均匀CPU/I/O/latency；celebrity symbol、市场开收盘和单run热点会击穿hash均衡。自动failure detection叠加自动rebalance可放大过载形成级联。scatter/gather tail由最慢partition决定，陈旧routing可重复或漏处理。
- **项目动作**：增加`PartitionExecutionEvidence`，报告per-partition rows/bytes/load/p95、skew、movement、routing epoch、duplicates/gaps和reconstruction checksum。当前单机未证明SLO不足，不引入distributed shard。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH06-001`—`010`。

## 已完成 L2：第 7 章

### 第 7 章：事务不变量、弱隔离异常与可串行化

- **论证链**：atomicity处理部分失败并允许abort/retry；ACID consistency是应用定义的不变量，不是数据库自动赋予；isolation防并发race，durability只降低丢失风险。read committed排除dirty read/write但允许read skew；snapshot isolation给一致snapshot却不阻止lost update、write skew和phantom。serial execution、2PL与SSI分别通过单线程顺序、锁或乐观冲突检测提供serializability，性能与abort模式不同。
- **成立条件**：从业务不变量反推transaction boundary、objects/predicates、isolation level、conflict strategy、idempotency和retry。`Fill→Position→Cash`、order state与artifact publish同一权威介质时用明确UoW；跨文件/DB/broker不能伪装原子事务，必须outbox/manifest/compensation/reconcile。
- **局限与反例**：数据库声称ACID/serializable不够，产品命名与真实语义可能不同。CAS只在比较值未发生ABA/隐藏依赖时安全；snapshot isolation下两事务可分别读同一前提后写不同对象，仍破坏总体约束。abort必须完整重试且外部side effect去重，否则“安全重试”会重复。
- **项目动作**：增加`TransactionInvariantEvidence`，保存invariant、read/write set、predicate、isolation、commit/abort、retry、external effects和并发fixture。SQLite版本/journal/locking行为必须实测；当前不修改生产账本或paper状态。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH07-001`—`010`。

## 已完成 L2：第 8 章

### 第 8 章：部分失败、时钟不确定与 fencing

- **论证链**：distributed request无响应时无法区分request丢失、remote down、排队/暂停、已执行或response丢失。timeouts只能触发怀疑，网络/queue/process pauses没有可靠上界。time-of-day clock可跳变，monotonic clock适合duration但不跨节点排序；NTP只给有限精度。lease holder在长暂停后可能继续写，必须由storage校验单调fencing token。系统模型区分synchronous/partially synchronous/asynchronous及crash-stop/recovery/Byzantine；correctness需分safety和liveness。
- **成立条件**：远端操作保存request/idempotency ID、attempt、deadline、ack/unknown、authoritative query和reconciliation。duration用monotonic clock，event保存source sequence、exchange/event time、receive time与clock uncertainty；任何lease/leader写入带monotonic epoch/fencing并由接收端拒绝旧token。
- **局限与反例**：timeout不是失败证明，重试可能重复order或overfill；wall-clock timestamp不能可靠决定因果或last writer。多数派不能防同一bug/config污染所有节点。理论算法在stable storage、clock或pause假设被现实破坏时仍可能失败；Byzantine方案也不能修复所有节点运行同一漏洞代码。
- **项目动作**：增加`DistributedOperationEvidence`，保存system model、safety/liveness、clock/timeout、unknown-result reconcile、fencing、checksums和failure fixture。broker/private/order/live endpoint继续禁止，所有交易安全旗标保持false。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH08-001`—`010`。

## 已完成 L2：第 9 章

### 第 9 章：一致性保证、因果顺序与共识成本

- **论证链**：eventual consistency只承诺最终收敛，不说明何时可见；linearizability把并发操作解释为单副本上的实时顺序，serializability则约束事务等价顺序，两者相互独立。linearizability适合leader/lock、唯一性和跨通道时序，但partition期间通常以availability为代价。causality形成偏序；Lamport timestamp可构造全序，却不能单靠时间戳即时决定唯一性。total-order broadcast与反复consensus等价。2PC依赖coordinator和所有participant，coordinator失效可使事务in-doubt并长期持锁；epoch/term与相交quorum支撑共识安全，但多数可达、leader稳定和成员配置是liveness前提。
- **成立条件**：先逐项声明read/write guarantee、real-time/causal requirement、conflict scope、partition/failure model、quorum、epoch、membership、durability和recovery。唯一性、leader/lease与单写者发布必须将冲突操作路由到同一决策域，并由接收端fencing。ZooKeeper/etcd类协调服务只保存小型coordination metadata，watch/lease/CAS不是业务真值或通用数据库。
- **局限与反例**：`w+r>n`只证明副本集合可能相交，不自动提供linearizability；CAP不能解释正常网络时的latency、consistency模型或具体故障。timestamp total order不等于已知所有更早消息已到达。2PC不是2PL，XA所谓exactly-once带来blocking、锁、异构协议与运维成本。consensus不提供无限吞吐、跨地域低延迟或自动正确的业务不变量。
- **项目动作**：增加`ConsistencyCoordinationEvidence`，保存operation class、required guarantee、authority、partition key、epoch/term、quorum、fencing、unknown/in-doubt、recovery和Jepsen-style fixture范围。`latest`只由单writer原子指向完整且hash验证的run；跨介质发布不伪装全局事务。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH09-001`—`010`；不以本书历史产品状态替代当前实现与故障验证。

## 已完成 L2：第 10 章

### 第 10 章：不可变批输入、确定性数据流与完整发布

- **论证链**：service、batch和stream对应request latency、bounded throughput与unbounded event processing。Unix的小工具、统一接口、逻辑/编排分离和透明中间结果使组合可理解。外部sort与in-memory aggregation取决于working set；MapReduce按map、partition/sort、reduce组织确定性重试。reduce-side join通用但受shuffle与skew影响，map-side broadcast/partitioned join依赖输入大小、共同分区和排序前提。批处理输出应是完整派生dataset，而不是在失败重试中任意修改在线记录。
- **成立条件**：输入immutable/versioned，mapper/reducer纯且deterministic，partition manifest、sort key、join key、skew policy、attempt和side-effect boundary显式。输出先写唯一run目录，完成row/checksum/schema/reconciliation后再原子发布pointer。dataflow engine若省略中间materialization，仍保存lineage、checkpoint/recompute边界与memory/spill证据。
- **局限与反例**：重跑安全只在输入冻结、任务确定性和side effect隔离时成立；热点key会使最慢reducer决定尾部。broadcast join可能耗尽内存，partitioned join在布局不一致时产生漏/错配。框架声明fault tolerant不证明业务输出完整；更少中间落盘会缩短I/O，也可能扩大重算与内存故障域。
- **项目动作**：增加`BatchRunEvidence`，保存input manifest/hash、code/params/env、partition/attempt、join/skew、determinism、partial cleanup、output manifest/hash和atomic publish。研究与回测builder只生成版本化artifact，不直接更新权威ledger或展示表。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH10-001`—`010`；分布式框架不作为当前选型，先验证单机SLO与恢复瓶颈。

## 已完成 L2：第 11 章

### 第 11 章：可重放事件流、事件时间与外部副作用

- **论证链**：传统broker的load balancing与fan-out是不同消费语义，ack/redelivery可造成duplicate与reorder。partitioned append log以offset、retention和consumer lag换取replay。CDC必须从consistent snapshot加精确log position启动；event sourcing区分command与已发生event，current state和view由event推导。event time与processing time不同，late/out-of-order数据要求watermark和window策略。stream-stream、stream-table与table-table join都依赖时间语义，未版本化dimension会让历史重放得到新结果。checkpoint/exactly-once通常只覆盖处理引擎内部，外部side effect仍需原子提交或idempotency/deduplication。
- **成立条件**：事件保存stable ID、source partition/sequence、event/receive/process time、schema、producer HEAD和correction version。consumer保存offset、retention horizon、lag/backpressure、dedupe state、checkpoint与rebuild source。window声明type、timezone/calendar、allowed lateness、watermark、update/retraction。time-dependent join使用PIT version/as-of ID，外部写使用end-to-end operation ID、single writer/fencing和reconcile。
- **局限与反例**：broker ack不等于业务效果已唯一发生，retention/compaction也不等于永久审计历史。event sourcing仍需处理错误event、schema evolution、隐私删除与历史增长。idempotency若依赖不同重放顺序、非确定逻辑或多writer，可能失效。processing-time窗口不能稳定重演历史；watermark只是完成度估计。
- **项目动作**：增加`StreamReplayEvidence`，保存source snapshot/log offset、event schema/clock、duplicate/reorder/late fixture、window/join、checkpoint、replay checksum、external effects与reconciliation。BTC WS断线补数和美股增量数据在合同齐全前保持research-only/fail-closed。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH11-001`—`010`；“exactly once”必须拆成输入、状态、输出和外部效果分别验证。

## 已完成 L2：第 12 章

### 第 12 章：派生数据、端到端完整性与持续审计

- **论证链**：单一工具无法覆盖所有访问模式，应先指定system of record，再通过有序log/CDC和确定性、幂等derivation构建index、cache、model和materialized view。batch与stream都处理数据流，统一依赖历史replay、fault-equivalent output和event-time window。端到端duplicate suppression需要客户端生成operation ID并贯穿所有hop，TCP、数据库事务或stream checkpoint单独都不够。timeliness是新鲜度，integrity是无丢失、重复或矛盾；前者可暂时滞后，后者必须检测修复。数据系统不能盲信hardware/database承诺，应以immutable event、deterministic derivation、hash、replay和end-to-end audit持续验证。
- **成立条件**：每个derived dataset声明authority、input order、code/schema/params、PIT/as-of、operation ID、idempotency、constraint scope、freshness和rebuild path。严格唯一/不可补偿操作在冲突域同步协调；可补偿约束可异步检查，但必须有bounded risk、状态机、owner和repair evidence。审计覆盖从raw/event到artifact/read model/ledger的完整链，并定期做restore/replay/reconciliation。
- **局限与反例**：log-based loose coupling通常牺牲read-your-writes和全局total order；多partition、跨服务和跨地域因果依赖仍需metadata与业务设计。immutable不自动正确，也与删除/隐私要求存在张力。加密hash只证明字节关系，不证明输入合法、业务决策正确或应当收集数据。预测系统的bias、feedback loop、不可申诉决策和数据滥用是实质风险，数据最小化、用途边界与访问控制属于系统合同。
- **项目动作**：增加`EndToEndIntegrityEvidence`，保存system-of-record、dataflow DAG、operation IDs、constraints、timeliness/integrity指标、hash/replay/restore、audit findings和current-HEAD。dashboard/cache/latest保持可重建projection；promotion只认权威evidence DAG，不因展示正常解锁。
- **L3 原 EPUB 复核**：对应章 10 项均已关闭为 `verified_concept_only`；`FORM-ENG03-CH12-001`—`010`；伦理、法规和产品能力需当前权威来源另行验证，本轮不联网。

## 完成边界

第 1—12 章及 120 个公式、算法语义、产品能力与历史数字条目已完成原 EPUB 概念核验。当前项目实现、性能、故障恢复和产品能力仍需具体任务证据；本卡不迁移基础设施、不修改生产 schema、broker 或数据路径，也不据此形成 promotion 结论。
