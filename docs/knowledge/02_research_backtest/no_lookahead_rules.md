# No-Lookahead Rules

## 硬规则

1. 特征只能使用 `available_time <= decision_time` 的数据。
2. 标签可以使用未来收益，但必须隔离在 label pipeline 中。
3. 标准化、分位数、波动率、相关性必须滚动或训练期估计。
4. 参数选择不能用最终测试期表现。
5. 调仓价格必须晚于信号决策时间。
6. 成分股、财报、复权、换月规则必须 point-in-time。

## 必须测试

- 同一信号使用截断数据和全量数据时，截断日以前输出一致。
- 训练期结束后新增数据不能改变训练期特征。
- 回测 ledger 中每个交易的 signal timestamp 早于 execution timestamp。

## 报告字段

- `no_lookahead_status`
- `decision_time_rule`
- `feature_visibility_rule`
- `label_window`
- `execution_time_rule`
- `audit_sample`

