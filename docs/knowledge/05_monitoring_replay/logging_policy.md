# Logging Policy

## 原则

日志用于审计和复盘，不是只给开发者调试。

## 必须记录

- run id。
- strategy id。
- data version。
- decision time。
- signal。
- forecast。
- target position。
- risk decision。
- order id。
- fill id。
- error code。

## 规则

1. 交易路径日志必须结构化。
2. 不记录密钥、token、个人支付信息。
3. 错误日志必须可关联到 run id 和 order id。
4. paper/live 日志必须可重放。

