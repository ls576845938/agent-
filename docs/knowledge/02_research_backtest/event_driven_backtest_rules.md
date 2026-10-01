# Event-Driven Backtest Rules

## 原则

回测应模拟事件顺序，而不是用一条向量表达式直接拼净值。

## 事件顺序

1. Data event。
2. Feature update。
3. Signal decision。
4. Portfolio target。
5. Risk check。
6. Order intent。
7. Simulated execution。
8. Fill。
9. Ledger update。
10. Report artifact。

## 规则

- 每个 fill 必须来自一个 order intent。
- 每个 position change 必须来自 fill。
- PnL 必须来自 ledger。
- 同一 bar 内不能既看收盘信号又按同一收盘价成交，除非明确建模 auction。
- 成交模型必须记录 order type、delay、cost、slippage。

## 禁止模式

- 直接用 `position.shift(1) * return` 当完整回测系统。
- 没有订单和成交就声称 paper/live 已打通。
- 回测和 paper 使用不同策略逻辑。

