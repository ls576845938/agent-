# Replay Engine

## 目标

系统必须能用历史 artifact 重放一次决策，解释当时为什么这样交易。

## 输入

- 数据快照。
- 策略版本。
- 参数。
- 风控配置。
- 当前仓位。
- 历史订单和成交。

## 输出

- 重放 signal。
- 重放 target position。
- 重放 risk decision。
- 与原始 artifact 的 diff。

## 规则

1. Replay 不得访问当前实时数据。
2. Replay 必须固定 clock。
3. Replay 必须固定 random seed。
4. Replay 失败应视为严重可审计性问题。

