# Quant System Non-Negotiables

## 目标

这些规则优先级高于策略收益。任何改动如果违反本文件，应停止实现并先修正设计。

## 硬规则

1. Strategy 不允许直接发送订单。
2. Strategy 只能输出 `Signal`、`TargetPosition`、`OrderIntent` 或同等抽象。
3. Risk Engine 必须位于信号和订单之间。
4. OMS / Execution 只能消费通过风控的订单意图。
5. PnL 必须由 fill ledger、position ledger、cash ledger 推导，不能由价格序列直接拼出来。
6. Backtest、paper、live 必须共享核心策略逻辑，不能维护三套策略实现。
7. 所有实验必须记录 `data_version`、`strategy_version`、`params`、`cost_model`、`slippage_model`、`run_id`、`code_version`。
8. 所有时间戳必须显式记录时区；系统内部默认 UTC，展示层才转换。
9. 禁止未来函数、全样本归一化、未来成分股、未来复权因子、回填财报。
10. 禁止因为回测结果不好而静默修改成本、撮合时点、数据过滤或评价窗口。
11. 实盘开关必须 fail-closed；任何数据、风控、账本、连接异常默认不能下单。
12. 任何核心 bug 修复必须补一个能复现旧错误的回归测试。

## Codex 开发约束

当修改数据、回测、策略、组合、风控、执行模块时，必须主动检查：

- 是否改变了可见数据边界。
- 是否改变了成交时间、价格、手续费或滑点假设。
- 是否影响 ledger 的可回放性。
- 是否绕过了 risk gate 或 promotion gate。
- 是否让 paper/live 逻辑偏离 backtest 逻辑。
- 是否补充或更新了契约测试。

## 禁止模式

- 用最终收益排序后继续手动调参，但不记录试验次数。
- 把研究脚本中的理想成交逻辑直接接到 paper/live。
- 只保留净值曲线，不保留逐笔仓位、成交和现金变动。
- 因为个人账户资金小就忽略滑点、最小下单量、交易所限制和停机规则。

