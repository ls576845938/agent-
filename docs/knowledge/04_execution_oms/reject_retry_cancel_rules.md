# Reject Retry Cancel Rules

## 拒单

拒单必须记录：

- reject code。
- reject reason。
- original order intent。
- risk state。
- exchange response。
- next action。

## 重试

1. 重试必须使用幂等 id。
2. 重试前必须查询订单状态。
3. 不允许无限重试。
4. 价格过期、余额不足、风控拒绝不得自动重试。

## 撤单

1. 撤单请求不等于撤单完成。
2. 撤单期间可能继续成交。
3. 撤单失败必须进入 reconciliation。
4. 紧急停机时必须明确是撤单、平仓还是冻结。

