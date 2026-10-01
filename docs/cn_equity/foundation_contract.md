# CN-V3-CURRENT-MAIN-FOUNDATION-01

## 交付边界

本 Goal 在 current main 上重建纯 `quant_cn`、纯标准库、无副作用的 A 股领域基础：

- `quant_cn.data.contracts`：证券状态的 point-in-time 输入合同。
- `quant_cn.market.calendar`：只解析调用方注入 session/phase 的版本化日历。
- `quant_cn.market.rules`：按证券维度、生效区间和可见时间解析市场规则。
- `quant_cn.market.eligibility`：稳定 blocker 目录、确定性排序和恒 false 安全旗标。
- `quant_cn.application.foundation_preflight`：汇总 eligibility、blockers 与输入版本。

不包含当前市场真值、下载器、数据库、策略、回测引擎、组合、OMS、broker adapter、ledger、backend 或 UI。测试中的价格限制、整手、可卖等待期和费用均为 fixture，不能作为研究、回测、paper 或 live 证据。

## PIT 与 UTC

`PITSecurityRecord` 强制包含稳定证券 ID、venue、board、instrument、security type、state，以及：

- `event_time`
- `available_time`
- `ingested_at`
- `processed_at`
- `source`
- `version`
- 64 位小写十六进制 SHA-256 `checksum`

所有时间戳必须带时区并在对象内转换为 UTC。时间顺序必须满足：

`event_time <= available_time <= ingested_at <= processed_at`

决策只能消费 `available_time <= as_of` 的记录。不可见记录返回 `pit_record_not_available`，且不得泄露其 state、维度或 version。

## 日历与证券维度

`TradingSession` 通过 `calendar_version`、source、checksum 与 PIT 时间字段版本化。日历解析必须同时匹配：

- venue
- board
- instrument
- security type
- session 左闭右开区间
- phase 左闭右开区间

resolver 不推断工作日，不读取 `latest/current`，不访问网络。session/phase 缺失、不可见、重叠或关闭均产生 blocker。

## 有效期市场规则

每条 `EffectiveRule` 都包含 `rule_version`、`effective_from`、`effective_to`、可见性时间、证券维度、source 与 checksum。规则区间左闭右开，且不提供市场级默认。

必须显式注入四类规则：

- `PriceLimitPolicy`
- `BoardLotPolicy`
- `SellabilityPolicy`
- `FeePolicy`

缺失、不可见、尚未生效、已过期、同维度重叠或跨维度歧义均 fail-closed。Fee 的买卖两侧不能为空；真实零费用也必须通过带版本的零值组件表达。

## Preflight 与安全状态

`run_foundation_preflight` 只返回：

- `eligibility.eligible`
- `blockers`
- 已解析输入的 `versions`
- `safety_flags`

`promotion`、`paper`、`live`、`private`、`order`、`real_order`、`broker`、`network`、`withdraw` 均不可配置并恒为 `false`。

本交付最高只能标记为 `quality_checked`。Team Context 当前仍报告：

- `domain_read_model_missing`
- `cn_dataready_missing`
- `board_lot_rule_missing`
- `cn_data_coverage_incomplete`

数据师仍拥有 raw/derived 数据、immutable shared-data version、manifest、lineage、freshness 与 DataReady 结论。任何 handoff 或 manifest 都不能单独解锁 promotion、paper、live、private 或 order。
