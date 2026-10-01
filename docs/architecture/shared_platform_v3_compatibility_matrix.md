# Shared Platform V3 兼容矩阵（人读镜像）

机器可读 source of truth：
`configs/governance/shared_platform_v3_compatibility_v1.json`。
提交前后应使用 `schemas/shared_platform_v3_compatibility.schema.json` 校验
该 JSON；本 Markdown 不作为机器输入。

| 域 | 当前版本 | 允许导入 | 禁止反向导入 | V3 状态 |
| --- | --- | --- | --- | --- |
| `quant_shared` | `shared_platform_v3` | Python 标准库、`quant_shared.core` | `quant_crypto`、`quant_us`、`quant_cn`、backend、frontend、vendor SDK | adopted |
| `quant_crypto` | `shared_platform_v2` | `quant_shared` | `quant_us`、`quant_cn`、backend、frontend、vendor SDK | discoverable |
| `quant_us` | `shared_platform_v2` | `quant_shared` | `quant_crypto`、`quant_cn`、backend、frontend、vendor SDK | discoverable |
| `quant_cn` | `shared_platform_v2` | `quant_shared` | `quant_crypto`、`quant_us`、backend、frontend、vendor SDK | discoverable |

## 兼容窗口

- V2：`supported`，消费者保留现有导入和 `require_shared_platform_v2()`。
- V3：`additive_discoverable`，消费者显式 opt-in；不得覆盖 V2 常量。
- 删除 V2 facade 需要所有域迁移、当前 HEAD 合同/审计证据和独立集成批准。

## 冻结交付顺序 T0→T8

本表是 JSON `delivery_sequence` 的人读镜像；ticket、owner 和 acceptance
必须逐项保持一致。

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

## 责任与安全

V3 只定义 runtime state、抽象 action decision、append-only audit event 和
read-model envelope 的字段责任。资产规则、策略、venue/broker、订单、账本、
promotion/paper/live、密钥和权限仍由资产域或治理层拥有。缺失/非法代码、版本、
hash、时间或链路字段必须 fail-closed；本票据所有 promotion/paper/live/private/
order/real-order/transfer/withdraw 旗标均为 `false`。
