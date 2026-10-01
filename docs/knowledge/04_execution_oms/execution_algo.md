# Execution Algo

## 目标

执行算法解决“如何交易”，不是解决“是否应该持仓”。

## 基础算法

- Immediate market。
- Passive limit。
- Limit with timeout。
- TWAP。
- VWAP。
- Participation of volume。
- Reduce-only emergency exit。

## 选择依据

- 订单规模。
- 盘口深度。
- 价差。
- 紧急程度。
- alpha decay。
- 市场冲击。
- 未成交风险。

## 规则

1. 紧急风控平仓优先成交确定性。
2. 普通调仓优先控制 implementation shortfall。
3. 小账户也必须考虑最小下单量和手续费台阶。
4. 高频策略没有盘口和延迟数据时，不得宣称完成执行验证。

