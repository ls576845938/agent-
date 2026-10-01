# Cost And Slippage Model

## 成本分类

- Commission。
- Exchange fee。
- Spread cost。
- Market impact。
- Delay cost。
- Funding or borrow cost。
- Tax or stamp duty。
- Opportunity cost from unfilled orders。

## 规则

1. 每个回测必须至少有基础、保守、压力三档成本。
2. 高频和小周期策略必须显式建模 bid/ask spread。
3. 限价单必须建模不成交风险。
4. 永续合约必须记录资金费率。
5. 成本模型变化必须改变 params hash 或 manifest。
6. 任何策略晋级必须通过成本压力测试。

## 输出字段

- `fee_paid`
- `spread_cost`
- `slippage_cost`
- `market_impact_cost`
- `funding_cost`
- `turnover`
- `cost_stress_summary`

