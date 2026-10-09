# US ETF 轮动 5方案优化报告

## 结论

- 当前最优实验：`v1_turnover_guard`，参数 `{"min_hold_months": 3, "turnover_threshold": 0.35}`。
- 最优实验 CAGR：9.10%；Sharpe：0.701；最大回撤：-28.09%；换手：143.63。
- baseline CAGR：5.32%；Sharpe：0.444；最大回撤：-34.53%；换手：321.20。

## 方案排名

| 方案 | 最优参数 | CAGR | Sharpe | MDD | Turnover | 2015超额 | 2022超额 | 2023超额 | 2024超额 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1_macro_floor | `{"macro_floor": 0.65, "macro_floor_requires_spy_trend": true}` | 5.81% | 0.469 | -33.05% | 289.00 | -17.99% | 9.41% | -20.60% | -18.50% |
| v1_turnover_guard | `{"min_hold_months": 3, "turnover_threshold": 0.35}` | 9.10% | 0.701 | -28.09% | 143.63 | 4.49% | 14.17% | -14.43% | -19.34% |
| v1_risk_capped_selection | `{"drawdown_penalty": 1.0, "reversal_filter_20d": 0.15, "risky_asset_cap": 0.2}` | 6.01% | 0.553 | -26.02% | 312.71 | -16.54% | 6.49% | -21.93% | -19.98% |
| v1_defense_regime_cap | `{"defense_cap_when_spy_trend": 0.35}` | 5.41% | 0.449 | -34.63% | 317.92 | -21.44% | 6.77% | -21.94% | -18.11% |
| v1_combined_conservative | `{"defense_cap_when_spy_trend": 0.65, "drawdown_penalty": 1.0, "macro_floor": 0.5, "macro_floor_requires_spy_trend": true, "min_hold_months": 2, "reversal_filter_20d": 0.15, "risky_asset_cap": 0.25, "turnover_threshold": 0.25}` | 8.29% | 0.714 | -22.32% | 181.89 | -13.58% | 11.01% | -17.73% | -15.48% |

## Baseline

- CAGR：5.32%；Sharpe：0.444；MDD：-34.53%；换手：321.20。

## 方法

- 优化评分：sharpe + cagr - 0.5*abs(max_drawdown) - 0.01*turnover + 0.5*mean_focus_year_excess_improvement
- 约束：All experiments remain research-only and reuse the same repaired external ETF/FRED data.
- 所有方案仍为 research-only，不允许直接纸盘或实盘。
