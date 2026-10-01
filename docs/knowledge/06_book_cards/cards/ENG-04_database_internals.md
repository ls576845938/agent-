---
book_id: ENG-04
title: Database Internals
authors: [Alex Petrov]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Database Internals - Alex Petrov - 原文.md
source_format: epub_text_original_epub_cross_checked
source_sha256: a9699a0d0217892be6a756d942163fa7fb3ab25458c5645a0a6474f509333f46
source_line_count: 8844
original_source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Database Internals A deep-dive into how distributed data systems work (Alex Petrov) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_source_sha256: 1b1f3f51bc7ece848cfd37ba58e55c1ed652a510a71015284e4cc4b54f49f6c4
original_source_chapter_files: 14
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 14
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 70_ch01_ch14_items_verified_concept_only
last_reviewed_at: 2026-07-15
---

# ENG-04：Database Internals

## 覆盖声明

本卡已核对 14 章正文边界并完成逐段 `L2` 语义精读。现已直接核对原 EPUB 的 OPF spine、`OEBPS/ch01.html`—`ch14.html` 及全部 h1/h2/h3 方法簇，将 70 个存储布局、B-Tree、文件格式、恢复、LSM、分布式故障、复制、事务与共识条目关闭为 `verified_concept_only`。该状态只确认概念、算法关系与项目边界，不认证产品能力、理论复杂度、历史参数或当前实现，也不授权生产迁移。

## L3 原始 EPUB 复核结论

| 范围 | 原 EPUB 文件 | 已核方法簇 | 队列状态 |
|---|---|---|---|
| Ch01—04 | `OEBPS/ch01.html`—`ch04.html` | DBMS/layout/index/buffering、B-Tree hierarchy/split/merge、binary/page/slot/version/checksum、page header/rebalance/compression/vacuum | 20 项均为 `verified_concept_only` |
| Ch05—07 | `OEBPS/ch05.html`—`ch07.html` | buffer/recovery/ARIES/isolation/locks、CoW/lazy/FD/Bw/cache-oblivious tree、LSM/compaction/amplification/Bloom/log stacking | 15 项均为 `verified_concept_only` |
| Ch08—10 | `OEBPS/ch08.html`—`ch10.html` | partial failure/link/retry/exactly-once/FLP、heartbeat/phi/gossip、leader election algorithms | 15 项均为 `verified_concept_only` |
| Ch11—12 | `OEBPS/ch11.html`—`ch12.html` | CAP/ordering/linearizable/sequential/causal/session/eventual、repair/handoff/Merkle/version vector/gossip | 10 项均为 `verified_concept_only` |
| Ch13—14 | `OEBPS/ch13.html`—`ch14.html` | 2PC/3PC/Calvin/Spanner/partition/Percolator/coordination avoidance、broadcast/Paxos/Raft/PBFT | 10 项均为 `verified_concept_only` |

## 全书项目映射

- `existing_rule_confirmed`：支持 WAL、checkpoint、checksum、原子事务、schema version、append-only 与恢复链。
- `candidate_design`：用访问模式和放大成本评估 SQLite、Parquet、CSV、日志和索引，而不是按流行度迁移。
- `rejected_for_now`：当前本地量化系统不需要自研 B-Tree、LSM、Paxos 或分布式事务。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Introduction and Overview | `336-607` | `L2/high` | workload、storage medium、row/column、data/index、buffering/immutability/ordering共同决定存储结构；同名术语不保证同语义。 | `existing_rule_confirmed`：行情、ledger、artifact分别冻结访问模式、durability、layout和recovery，不按产品标签选型。 | `FORM-ENG04-CH01-001`—`005` |
| 2 B-Tree Basics | `610-943` | `L2/high` | B+-Tree以page fanout降低block transfer，比较次数与I/O层级不同；split/merge、occupancy与range sibling定义维护和扫描。 | `concept_only`：SQLite索引解释必须结合query plan、page/cache和当前benchmark。 | `FORM-ENG04-CH02-001`—`005` |
| 3 File Formats | `946-1257` | `L2/high` | binary layout需固定endianness、schema/version、header、page/slot、variable data、overflow与checksum；格式是长期reader contract。 | `implementation_gap`：manifest/artifact增加schema/version/hash/length、atomic write和old-reader fixture。 | `FORM-ENG04-CH03-001`—`005` |
| 4 Implementing B-Trees | `1260-1521` | `L2/high` | page header、separator/high key、overflow、breadcrumbs、rebalance、bulk load、compression与vacuum决定真实实现成本。 | `concept_only`：只审计SQLite vacuum/checkpoint/index与fragmentation，不自研B-Tree。 | `FORM-ENG04-CH04-001`—`005` |
| 5 Transaction Processing and Recovery | `1524-2129` | `L2/high` | ACID需transaction/lock/page cache/log/recovery协同；WAL先于dirty page，checkpoint协调log truncation，lock与latch保护不同层级。 | `existing_rule_confirmed`：SQLite/ledger/artifact publish保存journal、UoW、isolation、recovery和restore fixture。 | `FORM-ENG04-CH05-001`—`005` |
| 6 B-Tree Variants | `2132-2421` | `L2/high` | copy-on-write、lazy buffer、FD/Bw/cache-oblivious结构在read sync、write/space amplification、reconciliation与GC间权衡。 | `rejected_for_now`：仅提炼immutable snapshot、pointer swap与reclamation合同，不迁移存储。 | `FORM-ENG04-CH06-001`—`005` |
| 7 Log-Structured Storage | `2424-3039` | `L2/high` | memtable、immutable runs、Bloom、tombstone、compaction与table-view切换交换顺序写、读/写/空间放大和后台债务。 | `existing_rule_confirmed`：append-only仍需retention、dedupe、compaction、log-flush同步和replay checksum。 | `FORM-ENG04-CH07-001`—`005` |
| 8 Distributed Systems Overview | `3116-3551` | `L2/high` | concurrency、message passing、unbounded queue/latency、clock uncertainty、partial failure和remote semantics使本地抽象不可直接外推。 | `existing_rule_confirmed`：handoff只发现候选，必须验证commit/hash；timeout/remote result标unknown并reconcile。 | `FORM-ENG04-CH08-001`—`005` |
| 9 Failure Detection | `3554-3733` | `L2/high` | heartbeat/timeout只输出suspect；false positive与detection delay权衡，accrual detector把历史arrival转为连续怀疑度。 | `candidate_design`：监控分stale/unknown/blocked，阈值绑定当前分布且不触发危险交易重试。 | `FORM-ENG04-CH09-001`—`005` |
| 10 Leader Election | `3736-3937` | `L2/high` |rank/ring/invitation类选举在partition时可能多leader；稳定leader改善liveness但需term、majority与conflict resolution保障safety。 | `existing_rule_confirmed`：同一文件/latest单writer，owner/epoch/fencing明确，不以文件锁类比完整共识。 | `FORM-ENG04-CH10-001`—`005` |
| 11 Replication and Consistency | `3940-4441` | `L2/high` | CAP、linearizability、sequential/causal/eventual与session guarantees描述不同history；quorum与sloppy quorum有明确失败窗口。 | `existing_rule_confirmed`：区分shared immutable version、worktree cache、latest projection和current-HEAD authority。 | `FORM-ENG04-CH11-001`—`005` |
| 12 Anti-Entropy and Dissemination | `4444-4671` | `L2/high` | hinted handoff、read repair、Merkle、version vector和gossip分别优化近期缺写、热点读取、范围差异、因果缺口与概率传播。 | `concept_only`：用于hash reconciliation和缺片发现，不把handoff命名等同分布式数据库协议。 | `FORM-ENG04-CH12-001`—`005` |
| 13 Distributed Transactions | `4674-5009` | `L2/high` | 2PC以unanimity换原子提交并可能blocking；3PC依赖同步假设且partition可分裂，Calvin/Spanner类方案也有排序与协调前提。 | `rejected_for_now`：本地优先单库UoW、atomic rename、outbox/compensation和顺序集成。 | `FORM-ENG04-CH13-001`—`005` |
| 14 Consensus | `5012-5623` | `L2/high` | Paxos/Raft依赖proposal/term、相交quorum、durable log与leader恢复；PBFT需不同fault model和更高message/quorum成本。 | `concept_only`：治理只采用single-writer/committed handoff原则，不声称Git或人工流程实现共识算法。 | `FORM-ENG04-CH14-001`—`005` |

## L2 逐章项目结论

- **存储选型**：先冻结point/range/scan、row/column、write/update/delete、durability、recovery、retention与SLO，再比较SQLite/Parquet/CSV/log；产品类别和理论复杂度不是证据。
- **格式合同**：所有长期artifact/manifest明确endianness或文本编码、schema/version、units、header/row count、checksum、atomic publish、old/new reader与corruption fixture。
- **恢复合同**：WAL、dirty state、checkpoint、log truncation、backup/restore必须形成同一可测试链；commit ack、fsync和durability边界按当前SQLite配置实测。
- **后台债务**：B-Tree vacuum和LSM compaction都可能制造write/space amplification与tail latency；append-only、immutable或copy-on-write不等于无需GC/reclamation。
- **远端合同**：timeout只产生suspect/unknown，queue/backpressure、clock source、request ID、retry/reconcile、term/epoch/fencing和failure model必须显式。
- **复制与协调**：每类数据声明linearizable/causal/session/eventual需求；quorum、anti-entropy、2PC或consensus只在对应假设与故障fixture成立时使用。
- **当前边界**：本书用于审查现有SQLite、artifact和handoff，不授权自研storage engine、引入集群、分布式事务或BFT。

## 完成边界

14/14 章与 70 个算法、公式、历史参数及产品能力条目已完成原 EPUB 概念核验。当前 workload benchmark、crash/recovery 和 fault fixture 仍须由具体实现任务另行提供；本卡不迁移基础设施、不修改生产数据路径，也不构成 promotion evidence。
