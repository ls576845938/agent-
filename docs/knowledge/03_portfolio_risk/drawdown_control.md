# Drawdown Control

## 目标

回撤控制用于保护生存权，不用于曲线拟合。

## 规则

1. 最大回撤阈值必须预先定义。
2. 回撤触发后的动作必须明确：降仓、停机、只平不增、人工复核。
3. 回撤控制不能用未来高点以外的信息。
4. 恢复交易必须有冷静期和复核条件。
5. 回撤规则必须在回测、paper、live 中一致。

## 报告字段

- `current_drawdown`
- `max_drawdown`
- `drawdown_limit`
- `risk_state`
- `action`
- `resume_condition`

