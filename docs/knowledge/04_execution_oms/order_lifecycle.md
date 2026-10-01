# Order Lifecycle

## 状态机

推荐订单状态：

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

## 规则

1. 状态只能按允许路径变化。
2. 每个外部订单必须有本地 `client_order_id`。
3. 重试必须幂等。
4. 部分成交必须更新剩余数量。
5. 撤单请求和撤单确认必须分开。
6. 成交回报乱序时必须能对账。

## 禁止

- 覆盖订单状态而不保留历史。
- 下单成功就假定成交成功。
- 网络超时后直接重复下单。

