# BTC Registered Candidate 外置目录 Guard 信任边界修复

## 票据与结论

- ticket: `BTC-REGISTERED-CATALOG-GUARD-FIX-20261001`
- role: `btc_developer`
- base commit: `4157ac389104cfaf50f8a2f48551dbb63f291067`
- change risk: `unclassified`
- gate impact: `none`
- readiness ceiling: `quality_checked`
- integration: 必须由独立 integrator 在提交态交付上完成；不得 fast-forward main

当前 F 的正式 app composition 在配置外置 candidate catalog 时，把官方
`CandidateResearchArchiveGuard` 作为 `ResearchDeliverySources.archive` 注入
`build_delivery_service`。原 `_require_trusted_service` 只接受裸
`ResearchArchiveCatalog`，因此合法 registered worker 在 `cursor=0` 被
`registered_trusted_source_required` 阻断。

本修复只扩展 registered candidate 的受信 composition 图；不改变 package、账户、
执行身份、Signal/Forecast/Target/OrderIntent、风险、OMS、成交、账本或权限语义。

## 接受的正式 Guard 图

Guard 路径只接受：

1. exact `CandidateResearchArchiveGuard`；
2. exact `CandidateResearchRoots` 且 `configured=True`；
3. exact `OfflineInputs`；
4. exact 内层 `ResearchArchiveCatalog`，且使用项目官方 manifest loader/resolver；
5. exact `ResearchDeliverySources`、`FactoryDeliveryReader`（最多官方一层）和
   exact `AlphaFactoryService`；
6. `sources.repo/qlib_root`、roots、inputs repo、内层 archive repo，以及实际
   factory `root/qlib_root/readonly_archive` 为同一正式配置。

在调用任何可替换方法之前，先拒绝 subclass、伪 wrapper 和实例方法覆盖；随后每次
worker trust 检查都调用真实 `roots.revalidate()`，保留 catalog owner、revision、
SHA-256、path 与 root 变化的既有 fail-closed 拒绝。

裸 `ResearchArchiveCatalog` 路径保持兼容，包括构造器支持的
`manifest_loader` / `manifest_resolver` 注入；该兼容不会扩展到外置 Guard 路径。

## Failure-first 与回归证据

Failure-first 使用正式 `resolve_candidate_research_roots`、
`CandidateResearchArchiveGuard`、`build_delivery_service` 和 registered worker：

- 修复前：`status=blocked`、`cursor=0`；
- 只读查询临时 job SQLite 得到精确
  `blocker=registered_trusted_source_required`；
- 测试断言按预期失败：`1 failed in 146.66s`；
- 未创建经济运行 state。

修复后聚焦验证：

- 正式 guard worker 正例在双测试进程中通过，完成非零 fill 与 ledger
  reconciliation，且全部权限仍为 false；
- guard 信任图拒绝矩阵与裸 catalog loader 注入兼容：
  `1 passed in 175.96s`；
- 既有裸 catalog 非零 FOK、重复调用、重启恢复与 ledger 对账：
  `1 passed in 337.03s`。

拒绝矩阵覆盖 catalog hash/root 变化、伪 guard、guard/roots/inputs subclass、
内部 archive 替换、guard/roots/inputs/archive/wrapper 方法覆盖、非官方 manifest
loader/resolver、sources/factory roots 不一致、readonly archive 不一致、递归
wrapper 与内层 reader 替换。所有拒绝均发生在经济 state 创建之前。

## 未运行与保持阻断

- 未跑全仓或完整生命周期矩阵；由独立 integrator 在提交态交付上集中验收。
- 未重训模型、扩展数据窗口、启动 backend/frontend、访问账户、private/order/live
  endpoint，也未读取 secret。
- 未重建 promotion artifact/read model；本票 `gate_impact=none`，本文档和
  handoff 都不是 promotion evidence。
- 旧正式 job `coff_26063ef15012000eac4964f7695433c7` 保持 blocked，未修改、
  未重放、未伪造为通过。
- `promotion`、`paper`、`live`、`private`、`order`、
  `real_order`、`transfer`、`withdraw`、`execution_permission`、
  `runtime_observed` 均保持 `false`。
