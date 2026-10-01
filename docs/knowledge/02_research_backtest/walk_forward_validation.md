# Walk-Forward Validation

## 目标

防止策略只在全样本或单一历史区间上表现好。

## 规则

1. 训练窗口、验证窗口、测试窗口必须明确。
2. 参数只能在训练/验证期选择。
3. 测试期结果不得反向影响参数。
4. 每个 fold 必须记录独立表现。
5. 如果标签窗口重叠，必须 purge 和 embargo。
6. Fold 失败不能被平均收益掩盖。

## 最低报告

- fold 数量。
- 每个 fold 的起止时间。
- 每个 fold 的参数。
- 每个 fold 的收益、回撤、换手、暴露。
- positive fold count。
- acceptable fold count。
- 与 buy-and-hold 或 baseline 对比。

## 晋级要求

策略不能只靠一个 fold 或一个年份支撑全部收益。

