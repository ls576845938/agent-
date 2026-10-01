# Strategy Interface Contract

## 目标

Research、backtest、paper、live 使用同一策略接口，避免研究结果无法实盘复现。

## 输入

策略入口是冻结的 `StrategyDecisionContext V1`，不得把 broker、数据库、
ledger 或进程全局变量作为隐式输入。它至少包含：

- identity：`run_id`、`strategy_id`、strategy/code/data version 及其摘要。
- clock：backtest/paper/shadow/live/replay/warmup mode、event/available/decision
  time、是否新 bar、是否 final。
- 只读视图：Market、Features、Universe、Position/Exposure。
- state：schema version、revision、payload、digest、last decision fingerprint。
- capabilities：当前入口明确允许产生的决策对象类型。
- parameters：仅保存冻结后的策略参数和兼容元数据；runtime mode 以 typed
  clock 为权威。

`event_time <= available_time <= decision_time` 是硬约束。上下文及其嵌套
mapping/list/position snapshot 必须深度不可变，调用方修改原始对象不得反向污染
策略视图。

## 输出

策略只能输出以下之一：

- `Signal`
- `Forecast`
- `TargetPosition`
- `OrderIntent`

推荐路径是：

`Signal -> Forecast -> TargetPosition -> RiskDecision -> OrderIntent -> OMS`

兼容策略仍可实现 `on_bar()`；权威 runtime 调用 `Strategy.decide()`，返回冻结的
`StrategyDecision`。每个策略、每个事件获得独立绑定的 identity/state context，
禁止多个策略共享同一个可变 context。

## 状态合同

- 跨事件状态只能来自 `StrategyStateSnapshot`。
- 策略只能基于当前 snapshot 产生 `StrategyStateTransition`；不得修改 context。
- transition 必须绑定完整 identity digest、state schema、expected revision、
  previous digest，并且 `next_revision = expected_revision + 1`。
- service layer 在接受决策输出后执行 CAS；revision/digest 冲突或状态文件损坏时
  fail-closed。
- 文件实现采用单写者和同目录原子 replace；重启只会读到前一完整 revision 或
  下一完整 revision。
- state payload 仅允许 JSON 往返后类型和含义不变的标量、mapping 与 sequence；
  datetime、Decimal、Enum、Path、set、bytes、NaN/Infinity 等必须在策略边界先显式编码，
  不得在重启后静默变型。
- service 以完整 identity 与 MarketEvent 内容计算确定性 decision fingerprint，
  每次已接受的决策（包括无业务状态变化的策略）都原子写入最后事件水位线。重启后
  最后已接受事件的重复投递必须被审计并 fail-closed 地抑制，不得再次调用策略或
  重复产出决策对象。
- 该最后事件水位线只保证对应策略求值的 at-most-once 抑制，不声称与下游 Portfolio/Risk/OMS
  跨域 exactly-once；若状态已提交而下游尚未接受输出，恢复流程应保持空操作并由
  审计/replay 显式处置，不能静默重放订单意图。
- code/data/strategy version 改变后使用新的 identity digest，旧状态不得自动恢复
  到不兼容策略。
- 组合策略把子策略状态按 child strategy identity 命名空间化，并将同一事件中的
  子状态更新聚合为父策略的一次原子 transition。

backtest、paper、shadow、live、replay 与 warmup 共用同一 context/state contract；
允许差异只体现在显式 mode、适配器权限和 capability，不允许策略按模式维护三套
alpha 逻辑。

## 禁止

- 策略直接调用 broker。
- 策略直接读写数据库。
- 策略直接写 ledger。
- 策略内部访问当前真实时间。
- 策略按 backtest/paper/live 写三套逻辑。
- 策略把运行状态保存在 module global、context 属性或未版本化的进程内 singleton。
- context 暴露 `submit_order`、`cancel_order`、broker、exchange、ledger 或数据库句柄。
- runtime 接受 future-timestamp output，或在未持有 capability 时接受相应输出。

