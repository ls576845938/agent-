# Risk Budget

## 目标

先定义能承受的风险，再决定追求多少收益。

## 必配预算

- Account max drawdown。
- Daily loss limit。
- Per-strategy risk budget。
- Per-asset exposure limit。
- Gross and net exposure。
- Leverage limit。
- Turnover budget。
- Liquidity budget。
- Model risk budget。

## 规则

1. Risk budget 是配置，不是回测后补充解释。
2. 每次 target position 生成必须检查预算。
3. 风险预算被触发必须进入报告。
4. 超预算默认拒绝或缩仓，不允许继续下单。
5. 风险预算变化必须记录审批和生效时间。

