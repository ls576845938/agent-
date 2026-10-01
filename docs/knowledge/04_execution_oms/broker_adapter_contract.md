# Broker Adapter Contract

## 目标

交易所/券商适配器只负责外部通信，不承载策略、组合或风控逻辑。

## 必须实现

- `get_account_state`
- `get_positions`
- `get_open_orders`
- `submit_order`
- `cancel_order`
- `get_fills`
- `reconcile`

## 规则

1. Adapter 不得生成策略信号。
2. Adapter 不得绕过 risk decision。
3. Adapter 必须返回结构化错误。
4. Adapter 必须支持 dry-run 或 paper mode。
5. Adapter 必须记录原始外部响应，供审计使用。
6. Adapter 异常默认 fail-closed。

