# Exposure Constraints

## 适用范围

资产、行业、因子、策略、交易所、币种、方向、杠杆。

## 规则

1. 每个 portfolio report 必须输出当前暴露。
2. 约束应在 target position 阶段执行，而不是成交后才发现。
3. 约束命中必须记录原因和调整量。
4. 多周期同向信号不能简单叠加突破暴露上限。
5. 交易所集中度和账户集中度属于风险暴露。

## 最低约束

- max long exposure。
- max short exposure。
- max gross exposure。
- max single asset exposure。
- max strategy exposure。
- max exchange exposure。
- max leverage。

