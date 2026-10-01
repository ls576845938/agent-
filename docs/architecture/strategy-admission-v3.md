# V3 Qlib 候选离线纵向闭环

> 2026-09-16 统一收口候选状态：**blocked / 未通过完整 V3 验收，未集成或发布**。下文中的两类证据为各自局部覆盖，不得解释为全链通过。最新断点与测试矩阵见 `docs/operations/strategy-v3-unified-closeout-20260916.md`。

票据：`STRATEGY-V3-QLIB-OFFLINE-20260916`  
基线：`b6b4b14c37bd6ae3d201b56f64eba439ec428399`  
风险等级：`demo_execution_semantics`

## 目标与停止点

V3 只验证一条离线纵向链：

`sealed Qlib prediction -> frozen candidate policy -> explicit BTC/OKX unit conversion -> existing BTC T2/T3/Guardian/OMS/dispatcher -> offline venue fill -> persistent ledger -> exact evidence binding`

不训练、不搜参、不建第二套 OMS，不改 Risk/Guardian/OMS core，不连接账户或交易所，不启动 Demo/paper/live，不产生 promotion 证据。停止点是可独立审查的源码候选与离线证据，不是发布。

## 两类证据严格分离

### 真实封存候选

- 运行：`m1-okx-qlib`，模型、数据、校准和政策身份以 V2 封存合同及存档 manifest 的完整 SHA-256 为准，不使用文档中的截断哈希作校验。
- 固定预测：1,392 条；测试 IC `-0.08289163706703358`。
- 账户状态：本轮新建的隔离模拟账户；历史 `research_decisions.jsonl` 仅作为结果 oracle，不提供本轮的仓位、批准、退出或账本状态。
- 输入：只读 resolver 返回的存档内固定相对路径，同时校验外层 manifest、dataset manifest 和实际消费字节的哈希；旧 manifest 中指向存档外的 `files` 不参与读取。
- 结果：每一条候选决策经统一 `execute` 准入与政策步骤；严格无金融副作用的拒绝按最多 64 条提交到既有持久 runtime 日志。1,392 个逻辑决策对应 22 个物理批次事件，每条证据绑定批次序号/hash/索引；批准数为 0，模拟成交为 0，`no_simulated_fills` 保留。
- 含义：证明封存预测与原候选政策能确定性重放；不证明 Alpha 有效，也不证明可交易。

### 显式非零 fixture

- 独立 namespace：`strategy-v3-nonzero-fixture-only`。
- 本轮局部覆盖：long 开仓、重复去重、质量阻断时保持仓位；独立初始账户的 short 开仓与原 hard-stop 退出。连续 long→反向先平的重启用例当前仍被离线 dead-man 维护时间事实阻断，故本候选不能宣称完整重启/经济闭环通过。
- 明确缺项：同一账户平仓后，手续费/资金费使原 policy 输出不再精确落到交易所 lot，因此连续“反向平仓 -> 反向再开”被单位合同拒绝。本轮不反算 forecast、不改政策或上限来制造五阶段全绿。
- 真值类型：`explicit_fixture_not_candidate_effectiveness`。
- 它不得汇入真实候选的收益、成交率或有效性结论。

## 边界与不变量

1. 研究和离线重放共用 `evaluate_candidate_policy`；该纯步骤无时钟、文件、模型、账户、OMS 或 transport 所有权，且始终 `execution_permission=false`。
2. 原候选 Target 使用 BTC 数量。执行 Target 使用 OKX 合约张数；`ctVal/lot/min/cap` 都必须显式且可精确表示。不可表示、低于最小数量或超限时拒绝，不向上取整，不截断为 `0.01`。
3. runtime 的封存接线同时绑定 `Signal / Forecast / candidate Target / execution Target / OrderIntent`、run/account/bar/units/model/data/policy/code 来源。默认 `None` 继续走原 Donchian 路径。
4. 接线只在 offline frame provider + offline credential namespace + fake venue 三项同时成立时可用。返回 `approved=true` 的 callback 不会产生权限；仍必须通过现有 cap、T2/T3/T4/T5、Guardian、dispatcher 和 ledger。
5. 非空仓加仓、跨零、单位不可表示、过期/未来输入、错身份/版本/来源、缺账户事实或 Guardian latch 仍 fail-closed。原 proposal 与执行拒绝分层留证，不把拒绝静默写成 hold。
6. 仅适配器自己的精确干净停机检查点可恢复离线健康事实；`FROZEN_UNKNOWN`、断连、未信任写路径、unknown intent、Guardian 或账本异常不会在对象重建时被清零。账本已提交但决策证据写入中断时，只补证据并恢复原 order/fill/ledger UOW 引用，不再下单。
7. 资金费 cashflow 缺失以 `okx_demo_funding_cashflow_unknown` 在订单前拒绝；转换对象在执行边界再根据当前交易所过滤器验算，不信任调用方构造的 dataclass。
8. 离线成交价和 mark 是不同事实；同刻下一决策不回拨时钟或补造行情。读写日志尾部截断由既有 store 返回 blocker，本适配器在初始化拒绝恢复；不自动清除坏尾。批次日志并非任意硬崩溃下的原子事务。

## 安全状态

`runtime_observed=false`，`execution_permission=false`，`promotion=false`，`paper=false`，`live=false`，`private=false`，`order=false`，`real_order=false`，`transfer=false`，`withdraw=false`。

这些状态在通过源码和离线验收后仍不改变；后续只能由独立集成/发布决策推进。
