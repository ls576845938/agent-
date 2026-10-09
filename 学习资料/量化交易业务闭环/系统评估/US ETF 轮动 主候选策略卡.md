# US ETF 轮动 主候选策略卡

## 策略身份

- Strategy ID：`us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x`
- 基础策略：`top1_higher_vol`
- 主候选：`min_adv_10m_to_shv + vol_target_20pct_cap1.5x`
- 账户假设：`10,000 USD`
- 当前状态：`forward_observation_only`
- 实盘状态：不允许真实下单

## 收益来源

策略收益来自三层：

1. ETF 横截面动量：在风险资产池中选择相对强势 ETF。
2. 宏观风控：用流动性、信用利差、趋势和利率冲击降低风险资产暴露。
3. 波动率缩放：在组合收益流层面做 20% 目标波动率，最大 1.5x 暴露。

这不是事后押注 QQQ 或科技资产；资产选择仍由原始轮动逻辑决定。

## 风险溢价和对手盘解释

- 动量收益：来自市场趋势延续、投资者反应不足、机构再平衡滞后。
- 宏观风控：试图避开流动性收缩、信用压力和趋势恶化阶段。
- 波动率缩放：用风险预算把低波动时期的有效暴露提高，但会承担融资成本和波动率跳升风险。

策略的对手盘不是明确单一交易者，而是慢反应资金、被动配置资金、风险预算约束资金和在宏观转折中被迫调仓的资金。

## 信号和调仓频率

- 原始调仓语义：`calendar_month_end_only_skip_if_not_trading_day`
- 调仓频率：月度，且保留原始外部策略的月末非交易日跳过行为。
- 观察频率：forward observation runner 可每日运行，但只有目标仓位变化时记录模拟 fill。
- 最小 ADV 约束：20 日 ADV 低于 `10,000,000 USD` 的标的转入 `SHV`。

## 成本模型

- 融资成本：`DGS2 + 1.5% broker spread`
- 滑点压力：`0bps / 10bps / 25bps / 50bps`
- 容量测试：`10k / 50k / 100k / 500k / 1m USD`
- 流动性检查：基于 20 日平均成交额和单名参与率。

## 10k 账户硬规则

- 初始不建议直接实盘使用 1.5x。
- forward observation 至少跑满 30-60 个交易日。
- 若未来进入实盘，先考虑 1x 或极低杠杆版本。
- 保证金、融资利率、整股/碎股、现金余额必须通过 preflight。
- 当前 runner 只允许写目标仓位和模拟账本，不允许 broker/private/order endpoint。

## 失效条件

任一条件触发，策略不得晋级：

- 30-60 日 forward observation 出现账本无法复算。
- 调仓日目标仓位和研究报告规则不一致。
- 25bps 成本压力后收益明显弱于 QQQ 且回撤没有优势。
- DBMF 或其他低流动性标的在 10k 账户下单次参与率超过阈值。
- 融资利率快速上升导致杠杆覆盖收益被明显侵蚀。
- 连续多个调仓周期出现宏观开关和动量选择解释不了的异常亏损。
- 出现真实下单、private endpoint 或 live flag。

## 停用规则

- forward ledger reconciliation 失败：立即停用 runner。
- 目标仓位包含低于 1 股且不支持碎股的标的：停用实盘晋级。
- 账户权益回撤超过研究报告中预期回撤区间：进入人工审阅。
- 外部 ETF/FRED 数据 stale 或质量报告失败：不生成新目标仓位。

## 下一阶段

```text
strategy card
-> 10k preflight
-> forward observation runner
-> target_positions / fills / portfolio_snapshots
-> 30-60 日人工审阅
-> 再决定是否做 1x 小资金纸盘
```
