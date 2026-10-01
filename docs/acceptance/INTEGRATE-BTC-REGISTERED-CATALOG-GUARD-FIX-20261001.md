# BTC Registered Candidate 外置目录 Guard 独立集成审查

## 票据与结论

- integration ticket: `INTEGRATE-BTC-REGISTERED-CATALOG-GUARD-FIX-20261001`
- role: `integrator`
- approved base: `4157ac389104cfaf50f8a2f48551dbb63f291067`
- producer deliverable: `402415d505c82e2dc608c0d9735a79c003a9c80e`
- producer handoff commit: `c207bca1bdb966ab283fb8e1efd5b44cfcbbce94`
- change risk: `unclassified`
- gate impact: `none`
- readiness ceiling: `quality_checked`

独立审查确认：正式 app composition 注入 exact
`CandidateResearchArchiveGuard` 时，原 registered worker 的信任检查只接受裸
`ResearchArchiveCatalog`，因而会在经济状态创建前以
`registered_trusted_source_required` 阻断。生产方修复只扩展受信 composition
图，不改变策略、风控、OMS、保护、成交、账本或权限语义。该提交必须通过独立集成
合入 main，不能按 producer fastpath 直接发布。

## 提交态交付核验

- `4157ac3...` 是 `402415d...` 的祖先；`402415d...` 是 `c207bca...` 的祖先。
- producer deliverable 相对 base 只包含：
  - `quant_crypto/application/btc_registered_candidate.py`
  - `tests/integrations/test_candidate_offline_lifecycle.py`
  - `docs/acceptance/BTC-REGISTERED-CATALOG-GUARD-FIX-20261001.md`
- canonical handoff 校验为 `valid`。
- Git 对象按仓库规范 LF 计算的 SHA-256 与 handoff 逐项一致：
  - production: `c31158aa4fcf68e14ae732b2a81b6398aa3d684400260121e0b534baf85a742b`
  - test: `7cf781c2e241d500a1894eaed8e6513058047dcf95a289f3e9860b50ea482ac3`
  - producer report: `752c4ea1e09139662d91dd89fb377ccc20e330420511152f30edfce46befa31d`
  - producer handoff: `46b8936e50aa2461b25f8609446c31cf299b3119db6faa1bf78a3c3c2cf43dc0`
- Windows 解包物是 CRLF；未经规范化的字节哈希不同，未被误当作交付漂移。
- 集成工作树在消费前，声明范围内为 clean；未读取或消费生产方未提交文件。

## 独立安全审查

接受路径要求 exact service、sources、accounts、store、factory wrapper、factory、
guard、roots、inputs 和内层 archive；外置 guard 还要求官方 manifest loader / resolver、
同一 repo/factory/qlib roots、同一 readonly archive，并在每次 worker 信任检查重新执行
owner、revision、hash 与路径核验。subclass、伪 wrapper、递归 wrapper、内层对象替换、
实例方法覆盖和 root 漂移均在经济状态创建前拒绝。裸
`ResearchArchiveCatalog` 的既有 loader / resolver 注入兼容保持不变。

生产方拒绝矩阵没有单独覆盖 guard 自身方法覆盖。独立集成补充
`guard._validated` 实例覆盖断言；生产代码未因此改变。

## 测试证据

生产方回执：

- failure-first 正式 Guard + `build_delivery_service` + registered worker：
  `1 failed in 146.66s`，精确 blocker 为
  `registered_trusted_source_required`、`cursor=0`，无经济状态；
- 修复后正式 Guard 正例完成非零 fill 与 ledger reconciliation；
- 既有裸 catalog 非零 FOK、重复、恢复和账本回归：`1 passed in 337.03s`；
- 信任图矩阵：`1 passed in 175.96s`。

生产方第一次修复后双用例进程实际为 `1 passed, 1 failed in 692.30s`；失败来自新增
测试漏导入导致的 `NameError`，不是 worker 正例失败。补导入后，信任图和裸路径分别
通过。此中间回执未写入 producer 报告，本集成报告如实补录，不将它隐藏或改写为整轮
通过。

独立集成回执：

- 首次运行把 pytest 临时目录放在本票据 worktree 内，既有安全合同按预期拒绝：
  `account_catalog_must_be_external`，`1 failed in 17.18s`；该环境回执保留，不归因为
  生产代码缺陷；
- 使用仓库外 `C:\\tmp\\btc-catalog-guard-integrator-trust-20261001-b` 重跑同一信任边界
  用例，包含新增 guard 方法覆盖断言：`1 passed in 157.46s`；
- JUnit：`.tmp/pytest-trust-graph-external.xml`；失败环境 JUnit：
  `.tmp/pytest-trust-graph.xml`；
- `git diff --check` 通过。

未重复生产方 692 秒正例或完整裸路径长测。正式 main 浏览器 Guard → worker 完整生命
周期将作为独立正例，在本集成提交合入并冻结新的 main HEAD 后执行，避免同一长测重复
三次。

## 运行与安全边界

- 本提交不生成 promotion readiness，不重建 promotion artifact/read model。
- 旧 job `coff_26063ef15012000eac4964f7695433c7` 保持 blocked、未修改、未续跑。
- 本集成阶段未启动 backend/frontend、未创建新 registration/job，未访问账户、secret、
  private/order/live endpoint。
- 新正式运行必须把 source/calculation provenance、registration、input 和 execution
  identity 绑定到最终集成后的 main HEAD；producer D/H 仅是源码审查血缘，不能冒充
  runtime HEAD 或新的模型训练来源。
- `promotion`、`paper`、`live`、`private`、`order`、`real_order`、`transfer`、
  `withdraw`、`execution_permission`、`runtime_observed` 均保持 `false`。
- 真实 v3 候选及 48 小时验收仍是独立未完成项；本票据只服务明确标注 synthetic 包的
  系统接入正式验收。
