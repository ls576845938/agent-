# V1 Donchian 离线纵向链接入

票据：`STRATEGY-V1-DONCHIAN-OFFLINE`

变更风险：`demo_execution_semantics`

V0 行为基线：`2b4cada2ce62bdaba434f28099fffac0b6d0e03f`

V1 集中收尾基线：`69ef575f709609f36f754f86040822bc6eeca1c6`

发布语义：本票据不发布服务、不合并主分支、不启用 Demo/paper/live；最终只读页面的交付路径由独立治理票据和高风险审查决定。

## 目标与边界

V1 不实现第二套策略、风控、OMS 或账本。它只用显式离线市场和账户事实驱动现有运行链，验证原 Donchian 决策能从原注册函数进入持久账本：

```text
原 btc_strategy_registry.signal_callable
  -> 原 0.01 contracts 目标 / 原退出与冷却语义
  -> OkxDemoPaperRuntimeController.run_cycle
  -> BtcDemoProductionComposition (T2/T3/Guardian/OMS/protection)
  -> BTCDemoExecutionDispatcher
  -> 文件持久、无网络的显式模拟 venue 回执/fill
  -> 现有 BTCRuntimeStore ledger UOW
  -> strategy_decision_evidence_v2 (精确 input digest；v1 只读兼容)
```

内部 dispatcher 继续使用既有 `BTCExecutionMode.DEMO` 能力类型完成原边界校验，但输入 transport 仅是 `_OfflineVenue`，不创建 socket，不加载凭据，不启动 worker，不获得 Demo 交易授权。对外证据恒为 `evidence_kind=offline_execution` 且 `runtime_observed=false`。

## 架构师审定的精确 touch set

下列是根架构师在本票据中明确允许的文件和职责。本文档是生产者对消息授权的提交态记录；它本身不构成审批，独立高风险审查仍须核对实际 diff 和文档 hash。

| 路径 | 允许职责 |
|---|---|
| `quant_crypto/application/donchian_offline_replay.py` | 新增单一 Donchian 离线纵向切片；复用原链，禁止联网 |
| `quant_crypto/oms/okx_demo_paper_runtime.py` | 仅允许最小离线完成 K 线注入接线及证据；默认数据路径和安全条件不变 |
| `quant_crypto/runtime/control_plane.py` | 原时钟与阈值不变；仅修正 dispatcher 的动作级投影：经全部既有事实与能力校验的 `REDUCE_ONLY` 收紧为 `TradingMode.REDUCE_ONLY`，不再误映射为交易所 `CANCEL_ONLY` |
| `quant_crypto/portfolio/decision.py` | 版本化 `RiskReductionPlan` 直接来源，互斥支持真实 Signal 或 Forecast；不改数量、阈值或风险判断 |
| `quant_crypto/oms/shared_platform_v3.py` | 对减仓计划的 Signal/Forecast 来源与 target/bundle 做精确绑定；缺失、冲突、篡改均 fail-closed |
| `quant_shared/strategy_runtime/decision_envelope.py` | 新增资产中性外围决策证据信封；复用 `StrategyDecisionContext`，不修改旧 domain type |
| `tests/contracts/test_strategy_v1_donchian_offline.py` | V1 失败优先合同与纵向验收 |
| `tests/contracts/test_btc_okx_demo_paper_runtime.py` | dispatcher 动作投影、保护动作及 fail-closed 事实回归 |
| `tests/contracts/test_btc_shared_platform_v3_portfolio_exit.py` | Signal/Forecast 减仓来源的构造、兼容与拒绝合同 |
| `tests/contracts/test_btc_demo_production_composition.py` | 既有 T2/T3 composition 回归（当前仅验收读取，未修改） |
| `tests/contracts/test_btc_shared_platform_v3_oms_delegation.py` | Signal/Forecast 来源的 T5 精确绑定与篡改拒绝合同 |
| `tests/fixtures/strategy_v1/` | 本票据的固定输入与预期；不写 runtime artifact root/latest |
| `docs/architecture/strategy-admission-v1.md` | 本文：边界、映射、缺口与验收 |
| `.agent/handoffs/STRATEGY-V1-DONCHIAN-OFFLINE/` | append-only 提交态交接事件 |

V0 测试和 fixture 仅读，不修改冻结预期。前端、Qlib、其他市场、启动器、真实交易所与凭据全部在范围外。

## 证据绑定

`strategy_decision_evidence_v2` 不增加交易能力。它绑定：

- package digest：strategy id/version、params hash、code version；
- run id、data version 和 `StrategyDecisionContext` digest；
- 完整、规范化可见 OHLCV 前缀的 `input_digest`，以及由完整身份和输入派生的 event id；
- `primary` / `hold` / `reversal_close` / `reversal_open` / `exit` phase；
- 实际 signal、target、risk、order intent、client/exchange order、fill 和 ledger UOW 引用。

已完成的 terminal phase 通过持久证据幂等返回。`hold` 明确记录无订单结论，不回显全局最后一笔交易；`reversal_close` 不表示整根 K 线完成，因此不能吞掉同一根 K 线上的反向开仓阶段。历史 v1 wire 仍可读取，但缺少 `input_digest`，不得声称满足本轮精确恢复验收。

## 当前验收状态

| 验收 | 状态 | 证据/限制 |
|---|---|---|
| 原 Donchian long -> 非零模拟 fill -> 持久 ledger UOW | 通过 | 真实调用原 controller/composition/dispatcher；未 mock 风控、OMS 或 dispatcher |
| 显式 contracts/ctVal/lot/cost/protection | 通过 | `0.01 contracts`、`ctVal=0.01 BTC`、手续费/funding/滑点合同均显式 |
| 同事件重放与重启后重放 | 通过 | 不增加 submit、fill、ledger UOW 或 decision evidence |
| 未来前缀因果性 | 通过 | 只读取 `visible_until` 及之前的完成 K 线 |
| Signal/Forecast 减仓直接来源 | 通过 | `RiskReductionPlan v2` 互斥记录 `source_signal_id` / `source_forecast_id`；旧 Forecast wire 仍可显式构造，普通无来源 target 不会降格成 Signal |
| `REDUCE_ONLY` 动作级运行投影 | 通过 | 仅 `RUNNING/RISK_REDUCING`、runtime active、真实非 cancel-only、既有账户/private WS/ledger/public/REST 时效与 action capability 均成立，且 canonical projection 零 blocker 时，将原 `NORMAL` 快照收紧为 `REDUCE_ONLY + block_new_orders=true`；共享 `PermissionEvaluator` 未修改 |
| 减仓投影 fail-closed 回归 | 通过 | 真实 cancel-only、`FROZEN_UNKNOWN`、`STARTUP_RECONCILING`、private WS/ledger/account/withdraw/121 秒过期或 action capability 缺失均在 callback 前阻断；同一 `RISK_REDUCING` 事实不能开新风险；`CANCEL_ORDER/DEAD_MAN` 旧保护语义保留 |
| 连续五阶段业务链 | producer 技术通过，待独立终验 | 单一连续 OHLCV 前缀完成 open long -> hold -> reversal close -> restart/same-bar reopen short -> exit flat；4 order/4 fill/2 OCO cancel，未修改原策略、Guardian、OMS 或 ledger |
| 保护单终态同步 | producer 技术通过，待独立终验 | 平仓后不由 simulator 假清；复用 controller 的 owned-algo cancel + pending/history readback，将 long/short 两组 OCO 均确认为 `canceled` |
| 精确身份、输入与 no-trade 证据 | producer 技术通过，待独立终验 | identity 在 runtime 副作用前绑定；同 bar 换输入、身份变化、时间回退、未来/缺失/时区未知均拒绝；hold 证据的 order/fill/ledger 链接为空 |
| fill/ledger 已提交但 evidence 缺失 | producer 技术通过，待独立终验 | 从 exact phase input anchor 后的 lifecycle 与 ledger UOW 补证，重启和重放不增加 submit/fill/evidence |
| order intent 已持久但 post 结果缺失 | 安全阻断（预期） | 结果仍属 `submit_pending/unknown`；既有控制器拒绝 blind retry，重启保持 submit=0、fill=0、evidence=0。没有用模拟器的“未见订单”擅自宣告绝对未提交 |
| 部分成交/拒单/取消响应丢失、冲突 fill | 本纵向场景未运行 | 既有 OMS/runtime 分层回归仍保留；本切片按冻结范围未扩成一般故障注入框架 |

## 离线经济口径

- 连续 OHLCV 只用于原 Donchian 信号；模拟成交价固定为 `60000 USDT`，不是历史 K 线成交回报，也不能用于评价策略收益。
- 风险成本输入继续显式包含 funding `1 bp`；本冻结场景没有实际 funding bill/cash event，账本 funding cashflow 为 `0`。
- 最终权益 `4999.988 USDT` 仅由初始 `5000` 与四笔各 `-0.003 USDT` 的 fee 重算。它证明 fills/cash/position/ledger 一致，不证明 alpha 有效。

`BTCExecutionDispatchFacts` 当前不承载 recovery-ack 或 kill-switch 的独立输入，本次没有扩大该事实 schema；这些状态仍由原 canonical projection 的直接入口与既有回归负责，不能从本动作映射的通过推断为已覆盖。

当前交付最多是 `quality_checked`。它不是 promotion evidence，不证明策略收益有效，不解锁 Demo/paper/live/private/order/transfer/withdraw。

## 停止条件

本轮在上述单一 Donchian 离线链、冻结恢复矩阵与 fail-closed 边界形成可审提交时停止。producer 测试通过不等于独立终验、只读页面或正式发布通过；不为测试全绿而补造 Guardian 健康、放宽 unknown intent、扩大事实 schema，或引入新模型、新 OMS、前端重构和策略参数调整。

## V1 closeout producer 验证

- 冻结纵向/恢复矩阵：`6 passed`。其中 order-intent 已持久但 post 未知的重启保持 fail-closed/no-duplicate；它不是自动恢复继续交易。
- V0 与 BTC registry/context/composition/risk/portfolio/Guardian/OMS/runtime 兼容子集：`219 passed`。
- 更宽的原 V0 命令在本 sparse 工作树先得到 `71 passed, 2 failed`；两项失败均因范围外 `quant_us/compat/shared_platform.py` 未 materialize 及其 validator 输入缺失，不是业务断言失败。本票据未修改或提交该只读依赖。
- M1 精确历史 blob 冻结：`1 failed`，因为授权后的 V1 源增量使受保护路径集合超出旧白名单。冻结测试和预期未修改；必须由最终独立审查按实际提交 blob 审定，producer 不得自行放宽。
- 没有运行部分成交/拒单/一般 cancel-response-loss/conflicting-fill 的新纵向场景，没有运行前端、服务、Demo、paper、private/order/live 或 promotion 验收。

## 2026-09-15 replay boundary 复验

`STRATEGY-V1-REPLAY-BOUNDARY-20260915` 已把 dispatcher 的 exchange snapshot 新鲜度时钟改为构造注入；默认仍为 `utc_now`，30/120 秒阈值、RiskEvidence 的真实时钟签发/验签及权限语义均未改变。封存的 observation clock 可跨当前日期重放，31 秒过期输入仍在 callback 前拒绝。

恢复语义已改为：只有全新模拟账户 bootstrap 可以创建健康事实；已存在 state 使用文件持久 Guardian latch，并保留 `FROZEN_UNKNOWN`、`write_path_trusted=false`、private-WS disconnected 与 tripped latch，不能由离线 adapter 在重启时自动改写为健康。正常关闭会写入精确 clean-stop 事件，一次性恢复资格还须匹配当前恢复投影、identity 与未触发 latch；unknown intent 继续 fail-closed。

当前集中验收仍有一个范围外直接阻断：正常 `reversal_close` 的真实 composition/Guardian 观察只收到 sanitized pending OCO，缺少可验证的 owner 与 reduce-only 字段，因此持久 latch 正确记录 `protective_order_owner_missing`、`protective_order_reduce_only_unknown`；重启后不得新开空仓。不能在 adapter 中补造这两个布尔量，也不能改写 exchange snapshot/ledger hash 来做绿。故五阶段技术验收尚未通过，本提交只能作为 `blocked_fail_closed` 的边界证据，不得进入页面、Demo、paper、live 或 promotion。
