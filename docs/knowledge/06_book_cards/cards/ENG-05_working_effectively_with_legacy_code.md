---
book_id: ENG-05
title: Working Effectively with Legacy Code
authors: [Michael Feathers]
source_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍原文MD\Working Effectively with Legacy Code - Michael Feathers - 原文.md
source_format: epub_text_original_epub_cross_checked
source_sha256: 5ed099a0eb7fe2788a545fd8710f52e299e4fb714c5ded2f7dc3b86965298bdb
source_line_count: 7528
original_epub_file: D:\vibe coding\Obsidian\量化系统\学习资料\量化交易业务闭环\书籍\Working Effectively with Legacy Code (Michael C. Feathers) (z-library.sk, 1lib.sk, z-lib.sk).epub
original_epub_sha256: 2878ffaa3d5a8a3c9128e1c80a90e3d93a3a21a425d0092ce63627a7963e3a1d
card_status: complete_l2_l3_items_verified_concept_only
chapter_count: 25
chapter_index_coverage_pct: 100
chapter_l1_coverage_pct: 100
chapter_l2_coverage_pct: 100
formula_review_status: 3_ch02_ch06_ch07_items_verified_concept_only_from_original_epub
last_reviewed_at: 2026-07-15
---

# ENG-05：Working Effectively with Legacy Code

## 覆盖声明

本卡已避开目录重复，按正文定位并精读 25/25 章，完成 `L2` 语义复核。代码案例用于识别依赖、反馈和重构边界，不直接复制语言专用技巧；3 个历史时间/成本估算已直接回看原 EPUB，均关闭为 `verified_concept_only`，仍不得成为测试 SLA、工期或 gate 阈值。

## 全书项目映射

- `existing_rule_confirmed`：修改既有量化链路前先建立反馈、characterization test 和 seam。
- `implementation_gap`：巨型 gate/replay/pipeline 服务虽有合同测试，但需要更细的纯规则行为锁定后才能安全拆分。
- `rejected_for_now`：不进行大爆炸重写，也不把临时 wrapper 永久化为新架构层。

## 章节卡

| 章 | 原文位置 | 等级/可信度 | 核心命题 | 项目映射 | 待复核 |
|---|---|---|---|---|---|
| 1 Changing Software | `460-557` | `L2/high` | 四类变更都只应改变目标行为并保存更大的既有行为面；重构与优化还需分别保持功能不变量。 | `existing_rule_confirmed`：任务先声明目标变化、必须保持的不变量、正确性证据与回归证据。 | Ch01 微秒示意不作性能阈值 |
| 2 Working with Feedback | `560-731` | `L2/high` | “Cover and Modify”要求变更点附近有快速、可定位的反馈；数据库、网络、文件系统和特殊环境测试不得冒充快速单测。 | `implementation_gap`：gate policy纯测试与artifact/SQLite集成测试分层，保留共同验收链。 | `FORM-ENG05-CH02-001`：`verified_concept_only` |
| 3 Sensing and Separation | `734-831` | `L2/high` | 测试替身有两种职责：感知不可观察副作用和隔离无关协作者；替身只证明边界交互，不证明真实外设。 | `candidate_design`：Clock、Repository、ArtifactStore、Git reader和exchange adapter使用窄fake，并由集成测试补真实边界。 | 无 |
| 4 The Seam Model | `834-1065` | `L2/high` | seam由可替换位置与enabling point共同定义；对象seam通常最显式，预处理/link seam只应作为难以解耦时的临时手段。 | `implementation_gap`：当前时间、环境、文件、网络和latest pointer改为显式注入点，禁止测试依赖隐蔽monkeypatch。 | 语言专用seam需按Python语义复核 |
| 5 Tools | `1068-1199` | `L2/high` | 自动重构、xUnit和mock缩短反馈，但工具可能保持语法而破坏行为，mock也不能替代领域断言。 | `existing_rule_confirmed`：自动改写后仍运行characterization、合同和针对性测试，不以工具成功作为验收。 | 无 |
| 6 No Time to Change It | `1206-1483` | `L2/high` | Sprout/Wrap Method/Class可让新行为在测试下生长，但会留下双重责任、委托层或静态“脚手架”。 | `candidate_design`：仅在旧服务暂不可测时包住policy/renderer；票据必须记录临时边界、owner与合并/删除条件。 | `FORM-ENG05-CH06-001`：`verified_concept_only` |
| 7 It Takes Forever to Make a Change | `1486-1573` | `L2/high` | 变更慢既来自理解成本，也来自反馈lag；依赖稳定接口和小测试集可降低平均反馈时间，但会增加接口/包概念成本。 | `candidate_design`：按policy、repository、renderer拆验证层；测量当前p50/p95反馈而非照搬书中秒数。 | `FORM-ENG05-CH07-001`：`verified_concept_only` |
| 8 How Do I Add a Feature? | `1576-1867` | `L2/high` | 遗留代码TDD先把目标类置于测试，再以失败测试、最小实现、去重复推进；“按差异编程”是临时过渡，继承组合爆炸与LSP风险必须退场。 | `existing_rule_confirmed`：新schema字段、gate或adapter先建失败测试；临时subclass/wrapper不得成为永久协议。 | 无 |
| 9 Class Not in Test Harness | `1870-2265` | `L2/high` | irritating/hidden/global/include/onion/aliased依赖都说明构造过程承担了过多环境和对象图责任。 | `implementation_gap`：builder不得隐式读取repo root、环境变量、全局latest或生产资源；优先参数化最小所需能力。 | 无 |
| 10 Method Not in Test Harness | `2268-2439` | `L2/high` | 私有方法优先经公共行为测试；难测长方法可抽method object，语言框架对象和不可见副作用需建立可感知边界。 | `candidate_design`：纯决策从写文件、日志、时间和进程退出中抽离，公共合同测试约束连接方式。 | 无 |
| 11 What Methods Should I Test? | `2442-2689` | `L2/high` | effect analysis从变更点追踪返回值、对象变异、全局/静态状态及外部副作用，直到语言或架构“防火墙”。 | `candidate_design`：schema/enum/decision变更先画影响链，测试覆盖可传播路径而非只覆盖被编辑函数。 | 无 |
| 12 Many Changes in One Area | `2692-2811` | `L2/high` | interception point用于检测单项影响，pinch point以少量入口覆盖一簇变更；它是起步覆盖，不应永久替代细粒度测试。 | `candidate_design`：EvidenceBundle、TargetPosition、ledger reconcile可作为候选pinch point，但须按具体change points证明覆盖。 | 大型pinch测试需防止演化成慢集成测试 |
| 13 Unknown Tests to Write | `2814-2975` | `L2/high` | characterization test记录“实际行为”而非授予其正确性；测试应覆盖目标路径、连接、类型转换、极值和不变量，疑似bug需标记并升级。 | `existing_rule_confirmed`：拆服务前锁定decision、blockers、guardrails、hash、顺序和边界转换；异常旧行为不得静默固化为规范。 | 无 |
| 14 Library Dependencies | `2978-2993` | `L2/high` | 对第三方库只依赖项目实际需要的窄接口，可降低升级、替换和测试成本；wrapper自身必须提供不同抽象而非透传。 | `candidate_design`：pandas、broker SDK、数据供应商和优化器经anti-corruption adapter隔离。 | 极短章节，结论仅限边界原则 |
| 15 Application Is All API Calls | `2996-3091` | `L2/high` | API调用链中仍应分离可测试计算核心；不要围绕供应商对象组织领域流程。 | `existing_rule_confirmed`：Strategy只输出Signal/Forecast/TargetPosition/OrderIntent，broker/exchange调用留在隔离adapter。 | 不授权访问任何交易端点 |
| 16 Don’t Understand the Code | `3094-3157` | `L2/high` | notes/sketch、listing markup、scratch refactoring和删除确认无用代码可辅助理解；探索性改动不是可交付重构。 | `candidate_design`：先做只读调用图、effect sketch和行为清单；scratch结果丢弃或在测试覆盖下重新实施。 | 删除仍需引用/运行时证据 |
| 17 Application Has No Structure | `3160-3295` | `L2/high` | 系统故事、Naked CRC和conversation scrutiny通过责任与协作语言暴露隐含架构，不以目录树代替结构。 | `candidate_design`：BTC/美股维护owner、权威数据、依赖方向和关键协作图，并用代码证据校验叙述。 | 访谈叙述不是实现事实 |
| 18 Test Code Is in the Way | `3298-3351` | `L2/high` | 测试类命名和位置要支持按生产责任导航；测试组织不清会掩盖行为覆盖与fixture复用边界。 | `implementation_gap`：合同测试按domain/gate/evidence责任分组，超长fixture拆为有语义builder。 | 无 |
| 19 Non-OO Project | `3354-3547` | `L2/high` | sensing、separation和小步变更不依赖OO；过程式代码可用函数边界、link substitution或局部对象化，但不应为模式强制改写。 | `existing_rule_confirmed`：Python纯函数保持纯函数，只在状态生命周期或可替换协作者需要时引入对象。 | C/link技巧不直接迁移 |
| 20 Class Too Big | `3550-3791` | `L2/high` | 大类拆分先识别职责、方法/变量分组和变更原因，再以测试支持渐进Extract Class；“大”本身不是边界证据。 | `implementation_gap`：巨型service按policy、repository、renderer、publisher责任抽取，并保持权威状态单一。 | 拆分顺序需当前调用图验证 |
| 21 Same Code Everywhere | `3794-4017` | `L2/high` | 重复消除前要确认语义和变化原因一致；局部先建立测试，再逐点汇聚到共同抽象。 | `candidate_design`：统一安全旗标、source parsing和证据字段；BTC/美股市场规则仅在语义相同时共享。 | 禁止以文本相似度直接合并 |
| 22 Monster Method | `4020-4231` | `L2/high` | monster method可借自动抽取或手工“引入可感知变量→小步抽取→持续编译/测试”处理；策略是先找可控小岛。 | `implementation_gap`：replay/gate builder逐段拆纯计算与I/O，禁止一次性重写或同时改行为。 | 手工抽取需连接与转换测试 |
| 23 Not Breaking Anything | `4234-4383` | `L2/high` | hyperaware/single-goal editing、保持签名、依赖编译器和结对复核降低无测试区的错误概率，但不能替代测试。 | `existing_rule_confirmed`：每票单一目标、兼容schema/API、静态检查与针对性测试；高风险diff需第二审查者。 | 编译成功不是行为证据 |
| 24 We Feel Overwhelmed | `4386-4409` | `L2/high` | 全面替换会遭遇双轨需求和持续漂移；长期改善依赖每天局部、可验证的债务回收。 | `existing_rule_confirmed`：短生命周期ticket和干净integrator worktree顺序推进，不建立“未来重写会解决”的豁免。 | 10年/10%为修辞示例 |
| 25 Dependency-Breaking Techniques | `4416-5633` | `L2/high` | 参数化、接口/实现抽取、override、delegation、global封装和语言级替换是风险不同的工具箱；选择应由依赖类型和最小改动决定。 | `candidate_design`：优先显式参数/Protocol/adapter；静态setter、全局替换、monkeypatch仅限受控测试并保留恢复。 | Ruby/C++/Java技巧需Python等价审查 |

## L2 逐章项目结论

1. **Ch01—02：先定义不变量和反馈回路。** 每项修改都要区分目标行为、保持行为、资源目标和证据；快速局部测试负责定位，较慢合同/集成测试负责真实边界，二者不可互相冒充。
2. **Ch03—05：seam必须显式、替身必须限界。** fake只证明调用方的输出或交互，不证明数据库、文件系统、Git或交易所真的工作；优先对象/参数seam，隐藏link、preprocessor或全局patch提高维护风险。
3. **Ch06—08：新行为可绕开旧泥潭，但临时结构必须退场。** Sprout、Wrap和Programming by Difference适合先把新行为置于测试，随后要消除重复、恢复清晰责任并检查LSP/组合爆炸。
4. **Ch09—10：构造和方法难测通常是隐藏依赖信号。** builder、构造器和方法不得自行发现环境、创建生产资源或把副作用藏在返回值之外；先抽纯决策，再为I/O建立窄端口。
5. **Ch11—13：测试选择由影响链和具体变更决定。** effect sketch追踪所有可传播效果，pinch point提供起步覆盖，characterization test记录实际行为；对路径、转换、极值、不变量和连接方式补针对性断言。
6. **Ch14—15：第三方API不是领域架构。** adapter应暴露项目语义并隐藏供应商对象；策略、组合和风险层保持纯领域接口，任何broker/exchange/private/order/live调用继续禁止。
7. **Ch16—18：理解与导航也是变更控制。** 只读草图、系统故事、责任协作和按生产责任组织测试可降低认知成本；探索性重构、访谈叙述和目录名称都不能代替代码与测试证据。
8. **Ch19—21：抽象由变化原因而非编程范式或文本重复决定。** 纯函数无需类化，共享逻辑要先证明语义与生命周期一致，市场专用规则保持隔离。
9. **Ch20—22：巨型类/方法按责任与可控步骤拆分。** 先锁定行为和单一权威，再抽纯policy、repository、renderer、publisher；每步保持可运行，不同时改变行为和结构。
10. **Ch23—25：低风险编辑纪律是最后防线，不是测试替代品。** 单目标、保持签名、编译/静态检查、第二审查者和最小依赖破除共同降低风险；侵入式全局技巧必须局限在测试并可恢复。

## L3 原始 EPUB 复核结论

| ID | 原始 EPUB 位置 | 复核结果 | 项目边界 |
|---|---|---|---|
| `FORM-ENG05-CH02-001` | `OEBPS/html/ch02.html`；转换文 `630-638` | 原 EPUB 确认 3000 类、每类约10个测试形成30000个测试；每个0.1秒合计3000秒即50分钟，作者近似为“接近1小时”；减半为25分钟近似“半小时”；每个0.01秒合计300秒即5分钟，正文写5—10分钟。 | `verified_concept_only`：算术方向正确但为近似历史示意；当前测试预算必须按测试层、cold/warm与p50/p95/总时长实测。 |
| `FORM-ENG05-CH06-001` | `OEBPS/html/ch06.html`；转换文 `1206-1212` | 原 EPUB 确认“为解依赖和写测试投入2小时、随后变更15分钟”的假设案例，并明确无法知道不写测试的变更/调试反事实，也无法预知该区域何时再次修改。 | `verified_concept_only`：只是投资回收叙事，不是成本收益估计；不得转换为工期承诺或重构ROI。 |
| `FORM-ENG05-CH07-001` | `OEBPS/html/ch07.html`；转换文 `1502-1510` | 原 EPUB 确认作者主张主流语言可把局部重编译与测试降至10秒内、积极团队可到5秒内，并以5—10秒任务与一分钟反馈比较认知切换；该主张绑定当时语言、构建和依赖环境。 | `verified_concept_only`：仅支持缩短反馈lag的方向；当前Python/Windows/CI必须独立测量，不设历史秒数SLA或promotion gate。 |

## 适用限制

- 本书讨论的是安全修改方法，不证明当前BTC或美股服务已经正确、可重构或满足promotion条件。
- 书中Java/C++/C#/Ruby技术要按当前Python模块、pytest fixture、Protocol与进程边界重新设计；不得逐语法迁移。
- `FORM-ENG05-CH02-001`、`FORM-ENG05-CH06-001`、`FORM-ENG05-CH07-001`已由原 EPUB 关闭为`verified_concept_only`；当前项目仍必须独立测量并报告分布、样本与环境。
- characterization test可能固化错误行为；疑似bug必须显式标记、调查依赖者并用失败测试定义修复目标。
- 本轮没有运行回测、修改参数、读取holdout、生成promotion结论或触达任何broker/private/order/paper/live端点。

本书满足单书完成条件：25/25章 `L2`、3/3个历史估算均由原 EPUB 关闭为`verified_concept_only`，所有章节有项目映射且 Markdown 来源 SHA-256 未变。该完成状态不证明当前BTC/美股实现正确、不批准重构，也不提供测试SLA、工期或promotion证据。
