# Audit Trail

## 目标

任何资金、仓位、策略晋级、风控状态变化都必须能追溯。

## 审计链

`data snapshot -> feature -> signal -> forecast -> target position -> risk decision -> order -> fill -> ledger -> PnL -> report`

## 规则

1. 每个环节必须有 artifact 或 ledger。
2. 每个 artifact 必须记录生成代码和输入版本。
3. 人工审批必须记录审批人、时间和理由。
4. promotion gate 不能只记录 pass/fail，必须记录原因。
5. 修改历史结果必须用新 run id，不覆盖旧 run。

