# Active Portfolio Management Rule Cards

> 状态：旧版主题摘要，不计入 `L1/L2`。`PORT-01` 标准章节卡已完成 `22/22` 章 `L2`，188项仍待 `L3`，以 `coverage_manifest.md` 为准。

## 用途

约束 signal -> forecast -> portfolio -> execution 的组合流程。

## 转化规则

- Signal 不是仓位。
- Forecast 要有 IC 或等价置信度。
- IR 是主动管理预算。
- Breadth 必须是独立机会数。
- 组合要看 active risk 和 residual risk。
- 交易成本和约束会造成 transfer loss。

## 对应文件

- `03_portfolio_risk/forecast_to_portfolio_rules.md`
- `03_portfolio_risk/risk_budget.md`
- `03_portfolio_risk/position_sizing.md`
