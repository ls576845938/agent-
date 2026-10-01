# BTC 保护单事实归一化与关联

状态：源码候选，等待独立 `demo_execution_semantics` 审查；未发布、未合入 main、未开启 Demo／paper／live。

## 根因与职责边界

原始 OKX OCO 的 `side` 与 `reduceOnly` 在 `_sanitize_algo_order` 中丢失；订单提交前交给生产 composition 的事实也只有交易所快照、私有 WS、账本和 runtime 摘要，没有带入本地持久的父订单意图、owned-algo 生命周期与已验证 active receipt。因此首次 reversal-close 的非空仓 Guardian 观察无法证明挂单属于当前 runtime，也无法证明其关闭方向，触发：

- `protective_order_owner_missing`
- `protective_order_reduce_only_unknown`

本候选没有修改 Guardian、Risk、OMS 生命周期、账本、PermissionEvaluator、策略或执行顺序。它只建立一个纯、无 IO 的归一化投影，并让 production composition 的预分类、`GuardianObservation` 与 Guardian evaluate 消费同一份投影内容。

## 事实合同

交易所原始快照和 canonical ledger hash 保持不变。归一化发生在独立副本中，不能信任快照自报的 `owned`、`owner_identity` 或 `close_position`。

内部 ownership 必须同时满足：

1. 当前快照 hash 与投影声明完全一致；
2. 当前 account hash、runtime identity、run id、source HEAD、liveness epoch、strategy id/version 完全一致；
3. 交易所 pending OCO 的 algo、algo client、parent、instrument、side、posSide、quantity 与状态唯一且一致；
4. 本地持久 owned-algo 记录、父订单意图和已验证 active receipt 三者均绑定同一身份；
5. 当前非空仓位的 instrument、posSide 与数量一致；
6. 仅支持既有 `BTC-USDT-SWAP`、`long_short_mode`：`sell+long` 为平多，`buy+short` 为平空。

`reduceOnly` 保留为 `true`／`false`／`unknown` 三态。在 `long_short_mode` 中，关闭事实来自明确的 `side+posSide`，其 applicability 标为 `not_applicable_long_short_mode`；缺失字段不会被补成 `true`。net mode、错 side、外来或重复身份、错数量、终态 receipt、错 run/source/account/epoch、snapshot mismatch 与未来观察时间继续 fail-closed。保护单或父订单存在时间较长本身不构成陈旧；没有新增 TTL。

## 数据流

```text
raw OKX pending OCO
  -> sanitizer 保留 side 与 reduceOnly 三态
  -> 当前 snapshot hash
  + persisted parent intent
  + persisted owned-algo lifecycle
  + verified active readback receipt
  + current account/run/source/epoch/strategy identity
  -> hosted_protection_facts 纯归一化副本
  -> composition pre-classifier
  -> GuardianObservation.open_orders / protection_facts
  -> unchanged Guardian evaluate
```

runtime 只交付上述字段的白名单副本，不暴露整个 `risk_control`、保护策略或 outcome probe。旧的缺 provenance 记录不会被回填为新证明。

### Parent 缺失时的限定关联

交易所 pending OCO 可以不返回 raw parent。此时只能用同一条持久
owned-algo 记录中**唯一且完整匹配**的 `algoId + algoClOrdId` pair 取得
parent，再继续校验 parent intent、active receipt、账户、run、source、epoch、
strategy、snapshot、方向与数量。关联过程不裁剪 `A` 后缀，也不从单个 ID
推导 parent。

如果 raw parent 非空，它必须与本地 parent 相同。若 registry 中另有记录与
当前 OCO 共享 `algoId` 或 `algoClOrdId`，即使存在一条 exact pair，也视为
归属冲突并拒绝。只有全部证明完成后，detached projection 才补入 parent；
原始 snapshot 与 canonical ledger hash 不变。

## 验收结果

- Failure-first：base sanitizer 对真实 OCO `side` 测试 3/3 失败，首错 `KeyError: side`；同时无法表达 `reduceOnly` 三态。
- 归一化、白名单、不可变、composition 同事实测试：15 passed。
- composition 与现有保护单／bundle 兼容回归：39 passed。
- 冻结 V1 离线矩阵：10 passed；覆盖开多、持有不加、反向先平、反向开空、退出归零、重复事件、身份／时间拒绝、ledger-before-evidence 与 intent-before-post fail-closed。
- 原始 snapshot 在白名单投影前后结构相同，canonical ledger hash 相同。
- Parent join failure-first：限定新增用例初始为 4 failed／1 passed；旧逻辑既
  拒绝 raw parent 缺失的 long/short，也会漏过共享单个 algo 标识的冲突。
- Parent join 修复后：helper 15 passed；helper 与 composition 关联测试
  16 passed；冻结 V1 文件 11 passed。新增 E2E 仅在测试 readback 边界移除
  `parentClOrdId`／`clOrdId`，并复用原五阶段经济、重复、重启、账本、证据和
  安全断言；没有修改模拟器、策略参数、成本或金标。

V1 的两个 fault hook 仍是同进程注入，随后通过显式 `close()` 释放资源再构造 runner；本票没有把它描述为 OS 级强杀恢复，也没有新增一般化崩溃恢复算法。独立子进程 hard-crash 验收未运行。

## Gate

本候选 readiness 上限为 `quality_checked`。`promotion_eligible=false`；Demo、paper、live、private endpoint、order endpoint、real order、transfer、withdraw 与 execution permission 全部保持 false。下一步仅允许独立 integrator 审查提交态源码、测试与 hash；本票不授权合并或发布。
