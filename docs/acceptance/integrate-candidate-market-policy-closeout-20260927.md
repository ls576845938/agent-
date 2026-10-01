# 候选离线诊断、保护链与市场条件政策综合验收（A/B 阻断收口）

日期：2026-09-27  
角色：独立 integrator  
基线：`770392bacab55596da3238b1815af4476866f0de`  
当前集成候选：本文件随最终 integrated event 交付，精确 HEAD 以该 event 的 `deliverable_commit` 为准
冻结 A/B 计算源码：`f2455bfbcafd15404bb4ff98dd6bb925728d0339`

## 结论状态

当前结论是 **source integration 已通过；真实 A/B 没有完成，已按冻结规则 fail-closed；未授权发布或交易**。

- 已完成：候选离线诊断准入、注册候选的离线保护链、共享市场状态合同、真实历史阶段诊断、Donchian entry-only 条件政策消费、只读页面读模型。
- 实际结果：baseline 完成 `2960 / 2960`；conditioned 在 `1956 / 2960`、`2025-11-21T12:00:00+00:00` 因 `ProtectionTriggerAmbiguous:historical_protection_double_touch_ambiguous` 失败关闭，终态空头 `-0.01` 张保留，没有伪平仓。
- 计算与研究结论：原定“两臂各 2960 事件”验收未通过，所以不计算完整政策效果，不由 baseline 或条件臂的局部盈亏推导改善。
- 当前不能得出的结论：市场条件政策改善收益、任意 Alpha Factory 候选都可运行、M1 旧 Qlib v2 已由注册 worker 执行、Demo/paper/live 已具备准入。

## 本票 touch set 与职责边界

本综合验收只汇总已经审定的提交态交付，不重审全仓，也不扩大模型、策略、执行或权限范围：

1. `quant_shared/strategy_delivery/**` 与候选管理后端／前端：只区分离线诊断准入与研究／交易准入。
2. `quant_crypto/application/**` 的注册候选离线入口：只补真实 controller 的保护链与恢复证据。
3. `quant_shared/trend_environment/**`、市场状态诊断和封存构建器：只提供因果、版本化、create-only 的研究证据。
4. Donchian 历史回放的市场条件消费：只影响 **启用政策、空仓、原目标非零** 的新开仓；已有仓位、退出、减仓、反向先平继续走原业务。
5. 既有研究详情页：只读取提交态小摘要；GET 不恢复回放、不核账、不训练、不下单。

不属于本票：任意策略组合器、工厂包通用市场条件扩展、Demo 控制器、真实账户、交易所、private/order/live、promotion artifact、主分支发布。

## 用户要求的六项贯通标准

| 标准 | 当前状态 | 精确证据与边界 |
| --- | --- | --- |
| 至少两个不同候选包以同一路径验证 | 已有工程证据 | `docs/acceptance/btc-candidate-package-runtime-20260925.md` 记录两个不同 synthetic AST/model 包的合同验证；后续 `docs/acceptance/btc-candidate-offline-entry-20260925.md` 及 `integrated-btc-candidate-offline-entry-20260925-0e0a442ce` 才证明 default bootstrap、CLI／HTTP 和离线 authority chain 已接入。两者合并说明工程路径，不证明投资有效性。 |
| 研究批量推理与逐根运行推理一致 | 已有工程证据 | strategy delivery v3 重算 sealed validation/audit 指标，运行时只接受有界 AST、LightGBM text 与冻结预处理／校准；不训练、不隐式换校准。真实 M1 旧 v2 不属于该通用 worker 能力。 |
| 单位、币种、账户和版本错配拒绝 | 已有工程证据 | package、account、adapter、code、currency、state directory、market/observation hash 均进入精确解析；USDT 包不能绑定 USD 账户，恢复不能换包、换账户或换 attachment。 |
| Donchian 与旧 Qlib 兼容 | 限定通过 | Donchian 原信号／仓位／退出继续保留；旧 Qlib 离线只读入口仍兼容。管理诊断允许旧 M1 v2，不等于 `btc_registered_candidate` worker 支持它；worker 当前只支持 `factory_lgbm_ast_v1`。 |
| 真实 controller、保护链和持久恢复 | source 验收通过 | 独立运行过真实 controller 的 long-SL 与崩溃恢复；producer 覆盖 long/short SL/TP、effective-time 和历史回归。明确采样点触发，不推断相邻采样之间是否触发；旧永久 blocked 运行不复活。 |
| 页面精确关联 | blocked 阶段投影验收通过，完整 A/B 不通过 | 页面只按精确 trial/run/source、summary file/report hash 与两份 ledger receipt hash 读取小投影。显示 baseline `2960/2960`、conditioned `1956/2960`、精确 blocker 与保留的 `-0.01` 张空头；只展示 48 phase 封存计数，没有将旧 28 笔交易状态拼成新的逐 phase 钻取。 |

## 离线诊断准入的精确含义

诊断宽限只适用于：

- `no_simulated_fills`
- `research_admission_not_proven`

它们允许“包完整、身份可复现”的候选进入隔离离线诊断管理流程，但不会变成研究通过或交易通过。其他完整性、真实性、质量、币种、账户、版本、适配器不匹配仍拒绝。Demo 不能沿用诊断准入。

首次 start 对不支持 adapter／worker 能力必须在 job/state 写入前拒绝；管理 SQLite 的惰性初始化不应被描述为“绝不创建数据库文件”。登记状态仍须显示 `start_allowed=false`，直到存在独立、审定的运行能力与授权。

## 市场状态与条件政策的已验边界

冻结策略为 `entry_path_efficiency_72h_v1`，只作用于 Donchian 空仓新开仓：

1. `policy.enabled=false` 时，sidecar 状态错误不能改变原业务。
2. 已有仓位时，provider 缺失、异常、旧状态或身份不匹配均不能阻断退出、减仓或反向先平；证据标为 `unavailable_non_entry_passthrough` 或 `mismatch_non_entry_passthrough`，且 `applied=false`。
3. 启用政策且空仓原目标非零时，状态必须严格匹配；未知状态拒绝原因是 `state_unknown`，身份不匹配继续 fail-closed。
4. 政策拒绝的新开仓必须同时有 `state_binding_status="verified"`；不能把错误 sidecar 记录成已验证。
5. 状态只使用当时可见、已完成的小时 K 线；duplicate、gap、72h primary window 已有定向回归。

历史阶段证据为 2960 bars、28 roundtrips、170 segments；仅是探索性条件诊断。资金费只有总额，OI／funding／depth 条件输入缺失，counterfactual 不是实际效果。

## 真实 A/B 封存结果（失败关闭）

两臂只允许使用冻结源码 `f2455bfbcafd15404bb4ff98dd6bb925728d0339`，并保持独立运行身份：

- baseline：`donchian-market-entry-baseline-20260927`
- conditioned：`donchian-market-entry-conditioned-20260927`

运行期间没有切换计算 worktree HEAD。baseline 完成；conditioned 遇到小时 K 线无法排序的止损／止盈双触达，按预先冻结的 `stop_on_ambiguity` 终止。该结果证明 fail-closed 生效，但不满足完整 A/B 效果估计条件。只读阻断摘要必须：

- 把执行源码、页面 publication HEAD、历史阶段 artifact 来源分别记录；
- 使用 consumer 的真实拒绝原因 `state_unknown`；
- 政策拒绝新开仓需 `state_binding_status="verified"`；
- phase 状态投影只能是 `consumer_phase/partial`；未持久化的多尺度数值为 `null`，并列出排序后的 `missing_fields`；
- 禁止用 `last_observation` 或 nearest-time 状态冒充旧 phase；
- 从同一运行的 fills、positions、cash ledger 核对收益、费用、资金费和持仓，不从日志猜测；
- 保留 conditioned 的 `-0.01` 张非空终态、精确 blocker 与时间，不强平、不按有利顺序补成交；
- 不携带完整 comparison、effect_verified 或 decision_effects，不对两臂未对齐的经济结果做差额；
- 不改策略、参数、成本、区间，不重跑第三臂。

## 已集成提交与独立验证

| 交付 | source commit | integrated event commit | 独立验证摘要 |
| --- | --- | --- | --- |
| 离线诊断准入 | `0e3d8ae5391e8a904e2ba40fce7167db8ec94eff` | `22dbc38f3e0e0c93c3fa7452983a1a8b8e63f663` | soft blocker 限定、Demo 拒绝、旧 blocker 完整展示、定向回归 |
| 注册候选离线保护 | `ed963919de90ee30ede9ef20557edf12bac71844` | `3da459a2267011a430562547b6a0929b40e1d975` | 真实 long-SL＋崩溃恢复独立通过；producer long/short SL/TP 等证据复用 |
| 市场状态共享与阶段证据 | `b63cbf2f3ebb14259e99b793d5b1e210e640ba4a` | `45a74ed888645938b1781d5e9f3eff52144eeb49` | 31 passed；精确 Git blob；封存 create-only |
| 市场状态读模型／页面 | `6b77734f7c0fa34df7bb5d044b4bd15b665e558f` | `7a1a12f175e9878ffa34d754d3d8d8beca6a42e2` | GET 不计算；counterfactual 与 effect 分离；原布局保留 |
| Donchian entry-only consumer | `f2455bfbcafd15404bb4ff98dd6bb925728d0339` | `ad036fb1de882587e781114085214f5c1693c372` | 6 consumer＋87 history/spec/effective＋11 V1 Donchian＋31 shared；P1 failure-first 后修复 |
| A/B 小摘要读模型／页面 | `bf3bff57fb89cf8e50b378af2aad7420179a4169` | `2ac2f8e541161c73645025666636ab83ddd39914` | backend 35、frontend 11、pycompile/diffcheck；reason/schema P1 failure-first 后修复 |
| 真实 blocked 阶段回执 | `c26a6046f4a0412281b630b2f31a8ea77504d240` | published handoff `9c3ed1dd42c9926ab575fc45d10464bb2e0a20bb` | 3 个外部封存 file hash、summary/report hash、2 个 receipt hash、2 组 Decimal 核账算术、48 phase verified/partial/no-order 与全安全旗标 false 已独立通过 |
| blocked 只读小投影／页面 | 最终 integrated event 的 `deliverable_commit` | 本票最终 integrated event | backend 42 passed，frontend 9 passed；投影只展示进度、blocker、receipt 绑定、终态持仓和 48 phase 封存计数，不提供新的逐 phase 钻取 |

所有测试均为 source integration 或只读投影验收；测试数量不能替代真实 A/B 经济结果。独立 sparse TypeScript 全量检查因依赖解析及无关 `CandidateHandoffInbox` 问题未作为本票通过证据；相关组件定向测试已通过。

本文档中的 13 个完整 40 位 Git 引用均已用 `git cat-file -e <ref>^{commit}` 机械核验；表内六组 source／integrated-event 映射也已从对应 event commit 中重新读取 `deliverable_commit` 并逐项匹配。禁止根据短 SHA 手工补写后缀。

## 最终判定规则

完整政策效果验收仍必须同时满足以下条件；本次因第 3 项未满足，研究比较判定为不通过，不得因阻断回执或页面能显示就降低为“整体通过”：

1. 两臂均为唯一新身份，writer 正常退出；没有第三次重跑。
2. create-only 摘要、hash、ledger 核账回执和 append-only handoff 全部提交并通过独立校验。
3. baseline 和 conditioned 均完成 2960 事件，两臂的决策、订单、成交、账本数量可精确关联；异常和缺证如实阻断。
4. 页面读取同一摘要，数字与核账回执一致；不把历史阶段或 fixture 拼成真实 trial。
5. 所有安全旗标继续为 false，且没有创建真实注册、账户或运行授权。

未通过时只报告精确断点，不自动改策略、扩窗、搜参、开第三臂或启动 M3/M4、Demo、paper、live。

## 保持 fail-closed 的事项

- 当前真实候选管理目录仍为空／未激活；本集成候选未合 main、未部署页面。
- M1 旧 Qlib v2 可被诊断管理，不是通用 factory worker 的可执行输入。
- 市场条件 attachment 当前只由冻结 Donchian spec 实际消费；共享校验器不等于任意未来工厂策略包会自动接受该扩展。
- `c44550ff247a4a4e21ccf2354ad704a76f965dd3` 及其 superseding 修订 `b385e1924d4eae5d11c587f2fba23b362d9d3bbf` 的 exact-state join helper 未通过独立验收，也未被本集成候选消费。两套依赖环境的复算 hash 不一致，且旧诊断状态的 `source_binding_hash=79de6c…` 与新 consumer phase 的 `source_binding_hash=1141ae…` 用途和绑定也不同；因此没有证明能精确重建实际 phase，不将原因简化为单一 Python／pandas 版本差异。旧封存不改写，页面继续使用 `consumer_phase/partial`、`null + missing_fields`。
- Demo、paper、live、promotion、private、order、real_order、transfer、withdraw 均保持 `false`。
- 本文件和 handoff 只证明代码与证据合同，不授予交易权限。
