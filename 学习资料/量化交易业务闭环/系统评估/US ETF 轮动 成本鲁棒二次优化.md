# US ETF 轮动 成本鲁棒二次优化

## 结论

- 二次优化最优：`v2_turnover_guard_refined`，参数 `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}`。
- 50bps：CAGR 6.67%；Sharpe 0.692；MDD -17.87%；Turnover 64.36。
- 这一步只说明成本鲁棒性更强，仍然是 research-only。

## 家族最优

| 家族 | 参数 | 10bps CAGR | 25bps CAGR | 50bps CAGR | 50bps Sharpe | 50bps MDD | Turnover |
|---|---|---:|---:|---:|---:|---:|---:|
| v1_turnover_guard | `{"min_hold_months": 3, "turnover_threshold": 0.35}` | 9.41% | 8.48% | 6.95% | 0.555 | -31.20% | 143.63 |
| v1_combined_conservative | `{"defense_cap_when_spy_trend": 0.65, "drawdown_penalty": 1.0, "macro_floor": 0.5, "macro_floor_requires_spy_trend": true, "min_hold_months": 2, "reversal_filter_20d": 0.15, "risky_asset_cap": 0.25, "turnover_threshold": 0.25}` | 8.68% | 7.51% | 5.60% | 0.505 | -26.57% | 181.89 |
| v2_turnover_guard_refined | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 7.76% | 7.35% | 6.67% | 0.692 | -17.87% | 64.36 |
| v2_cost_robust_combined | `{"defense_cap_when_spy_trend": 0.65, "drawdown_penalty": 1.0, "macro_floor": 0.5, "macro_floor_requires_spy_trend": true, "max_monthly_turnover": 0.75, "min_hold_months": 3, "reversal_filter_20d": 0.15, "risky_asset_cap": 0.3, "turnover_threshold": 0.35}` | 8.66% | 8.14% | 7.27% | 0.691 | -19.44% | 81.22 |

## 方法

- 范围：Second-stage search around turnover_guard and combined_conservative because those survived 50bps in the prior stress report.
- 新控制项：max_monthly_turnover, rebalance_blend
- 评分：50bps_sharpe + 50bps_cagr - 0.5*abs(50bps_mdd) - 0.003*turnover + 0.25*mean_focus_excess_50bps
- 约束：Research-only; no paper/live unlock.
