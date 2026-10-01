# Market Microstructure And Execution Rules

来源主线：Trading and Exchanges。

## 适用范围

回测撮合、滑点模型、OMS、交易所适配器、paper/live 执行、成交复盘。

## 核心规则

1. 订单不是成交；成交必须有独立 fill ledger。
2. 市价单、限价单、止损单、撤单、拒单、部分成交必须区分。
3. 回测成交价不能默认等于信号 bar 的收盘价，除非明确说明决策和执行时点。
4. 滑点模型必须和品种、周期、流动性、订单类型、交易规模匹配。
5. 高频或小周期策略必须考虑 bid-ask spread、盘口深度、队列位置、延迟和 maker/taker fee。
6. 如果没有盘口数据，不得声称完成真实高频验证。
7. Paper execution 必须模拟订单生命周期，而不仅是把目标仓位记到账本。
8. Live adapter 必须幂等；重复提交、网络重试、回报乱序不能制造重复订单。
9. 所有执行异常必须可审计：拒单、撤单失败、部分成交、价格偏离、超时。
10. 任何真实下单路径默认关闭，且必须被 risk gate 和 manual gate 同时允许。
11. 市场订单购买确定性成交，支付价格不确定性；限价订单购买价格保护，承担不成交风险。
12. 订单路由必须记录 venue、order type、time in force、maker/taker 假设和 best execution 依据。
13. 流动性至少拆成 tightness、depth、resiliency 三个维度，不能只看成交量。
14. 回测成本至少区分显性成本和隐性成本：commission、fee、spread、market impact、delay cost。
15. 执行效果应以 implementation shortfall 或同等指标衡量，而不是只看成交均价。
16. Broker / exchange adapter 是代理层，存在 principal-agent 风险；策略不能假定外部路由总是最优。
17. 交易后必须 reconcile：本地订单、交易所订单、成交回报、账户余额、仓位必须一致。
18. 对于限价订单，回测必须说明排队假设；仅凭触及限价不能默认成交。
19. 对于小周期策略，成交延迟和 bid/ask bounce 可以决定策略生死，必须做压力测试。
20. 交易所维护、断连、限频、最小下单量、精度约束都属于执行风险，不是工程细节。

## 流动性定义

执行模块必须尽量记录：

- `tightness`: bid-ask spread 或有效价差。
- `depth`: 最优档和多档可成交数量。
- `resiliency`: 大单冲击后价格和盘口恢复速度。
- `immediacy`: 需要多快完成交易。
- `adverse_selection_risk`: 成交后价格不利移动风险。
- `market_impact`: 本单对价格的影响。

## 回测撮合最低字段

- `decision_time`
- `order_created_time`
- `order_type`
- `side`
- `target_qty`
- `limit_price`
- `simulated_fill_time`
- `simulated_fill_price`
- `filled_qty`
- `fee`
- `slippage`
- `spread_cost`
- `market_impact_cost`
- `delay_cost`
- `implementation_shortfall`
- `liquidity_assumption`
- `queue_assumption`
- `time_in_force`
- `venue`

## 订单生命周期

推荐状态：

- `created`
- `risk_checked`
- `submitted`
- `accepted`
- `partially_filled`
- `filled`
- `cancel_requested`
- `cancelled`
- `rejected`
- `expired`
- `reconciled`

## 成本与绩效归因

执行报告至少拆分：

- 决策价格到下单价格的延迟成本。
- 下单价格到成交价格的执行成本。
- 半价差成本或有效价差成本。
- 市场冲击成本。
- 未成交导致的机会成本。
- 手续费、交易所费率、资金费率或借贷成本。

对于 paper/live，必须输出：

- `paper_price`
- `arrival_price`
- `fill_price`
- `benchmark_price`
- `implementation_shortfall`
- `fill_rate`
- `cancel_rate`
- `reject_rate`
- `average_latency_ms`

## 禁止模式

- 回测默认下一根开盘全额成交，但不记录这个假设。
- 纸盘只算理论仓位，不模拟订单状态。
- 实盘连接异常时继续沿用上一轮信号下单。
- 下单失败后无限重试。
- 小资金策略忽略最小下单量和手续费台阶。
- 限价单只要 K 线最低价碰到限价就默认完全成交。
- 用 OHLCV 回测宣称已经验证盘口策略。
- 只记录目标仓位，不记录订单和成交。
- 只看交易所成交成功，不做账户和本地 ledger 对账。

## BTC 执行适配

BTC 现货/永续至少区分：

- spot、perp、margin 的账户和风险不同。
- maker/taker fee 不同。
- 永续需要资金费率和强平风险。
- 交易所最小下单量、价格精度、数量精度会影响小资金账户。
- 周末和节假日仍交易，传统市场日历不能直接套用。
- 交易所停机、API 限频、WebSocket 断流必须触发 fail-closed。
