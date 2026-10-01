# Shared Platform V3 合同（T0 架构冻结）

## 决策

V3 是资产中性的共享安全内核合同，以加法方式发布在现有 V2 旁边。V2
消费者继续通过既有 `shared_platform_v2` 常量和
`require_shared_platform_v2()` 工作；V3 只通过独立的
`SHARED_PLATFORM_V3_VERSION`、`discover_shared_platform()` 和
`quant_shared.runtime.contracts` 被发现，不改写 V2 全局常量。

机器可读的 source of truth 是
`configs/governance/shared_platform_v3_compatibility_v1.json`，其结构由
`schemas/shared_platform_v3_compatibility.schema.json` 校验；
`docs/architecture/shared_platform_v3_compatibility_matrix.md` 是人读镜像。

## 共享层拥有的责任

- 运行时状态观测的稳定字段形状和显式 UTC 时间戳；
- 小写、可审计、不可变的 reason/blocker code 形状；
- 动作授权结果的观察记录形状（不授予任何资产域执行能力）；
- append-only、带 payload hash/previous hash 的审计事件形状；
- current-head/data-version 绑定的派生 read-model envelope 形状；
- 版本发现、兼容窗口和 fail-closed 数据约束。

## 明确不拥有的责任

共享层不拥有资产规则、交易策略、交易所或 broker adapter、订单路由/提交、
账本会计语义、资金/清算/市场规则、promotion/paper/live 权限、凭证或密钥。
资产域只能单向导入 `quant_shared`；共享层不得反向导入资产域、backend、
frontend 或第三方 SDK。所有未知值、缺失 hash、错误版本或不完整的审计链
必须保持不可授权的 fail-closed 结果。

## V3 接口责任

`RuntimeStateEnvelopeV3` 描述 runtime id、状态、活动/开仓/取消模式、worker
存活、heartbeat 和 blocker codes；`ActionAuthorizationV3` 只记录某个抽象
动作的允许/拒绝、reason 和 blocker，不解释或改变资产域权限；
`RuntimeAuditEventV3` 记录有序事件、UTC 时间、payload hash 与 previous hash；
`ReadModelEnvelopeV3` 将 runtime、动作决策和审计事件作为同一派生投影的输入，
并绑定 `current_head`、`data_version` 与明确的 status/decision。

这些类型是接口形状，不是新的状态机、权限判定器、OMS、broker client 或
执行队列；现有 `quant_shared.runtime.permissions.py`、`models.py`、
`state_machine.py` 的行为在 T0 不变。

## Strangler 顺序 T0→T8

以下九段责任链是本项目冻结顺序，机器可读的
`delivery_sequence` 与本表必须逐项一致，不得自行换序或改名：

| 阶段 | ticket_id | owner_scope | acceptance 摘要 |
| --- | --- | --- | --- |
| T0 Shared Platform V3 | `BTC-SHARED-PLATFORM-V3-01` | shared developer + independent integrator | ADR/schema/兼容矩阵；共享安全内核边界与 BTC/US/CN import boundary |
| T1 权限语义修复 | `BTC-SHARED-PLATFORM-V3-T1` | `quant_shared/runtime` | 反转前三个失败探针；kill 后只允许已证明的减仓/撤开仓单/加保护 |
| T2 BTC 纯风险内核 | `BTC-SHARED-PLATFORM-V3-T2` | `quant_crypto/risk` | 风险宪法、ActionRiskEffect、组合亏损、杠杆、保护可行性纯函数 |
| T3 决策与退出闭环 | `BTC-SHARED-PLATFORM-V3-T3` | `quant_crypto/portfolio` | 复用 Forecast/TargetPosition；超限独立 RiskReductionPlan；研究/运行时退出同合同 |
| T4 Guardian/Latch | `BTC-SHARED-PLATFORM-V3-T4` | `quant_crypto/application` | 纯 guardian、单写者 supervisor、持久 sticky latch；人工确认不能单独恢复 |
| T5 OMS 渐进迁移 | `BTC-SHARED-PLATFORM-V3-T5` | `quant_crypto/oms` | 保留大 runtime facade 并渐进委托，不整体重写 |
| T6 Operator Contract V2 | `BTC-SHARED-PLATFORM-V3-T6` | BTC application schema → backend adapter → integrator | 逐动作服务端授权、稳定 blocker、幂等、operation read model |
| T7 Crypto UI V2 | `BTC-SHARED-PLATFORM-V3-T7` | `frontend/src` | 拆分巨型 workspace；不推导权限/不硬编码风险值；stopped emergency 与 a11y |
| T8 Replay 与晋级重建 | `BTC-SHARED-PLATFORM-V3-T8` | researcher review + integrator | current-HEAD 不可变证据、确定性 replay、成本/退出一致；人工 gate 保留 |

每一步都必须保留旧合同的 fail-closed 语义。任何阶段不得以 V3 发现性、
read-model 或 handoff 解锁 paper、private、order、promotion 或 live。

## 兼容与弃用

兼容窗口中 V2 是 supported，V3 是 additive/discoverable/opt-in。只有当
对应域的所有调用方已迁移、当前 HEAD 的合同测试和审计证据通过、并完成独立
集成复核时，才可提出删除 V2 facade；不能因单一域迁移或 schema 发布删除旧符号。

## 非目标

本票据不修改权限判定，不迁移 BTC/US/CN 业务，不统一资产枚举，不重构
OMS/ledger，不新增策略或回测执行器，不触碰 backend/frontend、凭证、服务或
真实 broker endpoint。
