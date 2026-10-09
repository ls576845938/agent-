# US ETF 轮动 Walk-Forward 与参数稳定性

## 结论

- 参数邻域数量：36；50bps 存活率：100.0%。
- 邻域中位数：CAGR 6.56%；Sharpe 0.664；MDD -17.64%；Turnover 57.88。
- Walk-forward OOS：CAGR 7.90%；总收益 130.35%；SPY 231.95%；Sharpe 0.751；MDD -17.87%；存活率 63.6%。
- 当前基准参数 50bps：CAGR 6.67%；Sharpe 0.692；MDD -17.87%；Turnover 64.36。
- 全样本最优参数：`{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 1.0, "turnover_threshold": 0.55}`。
- 结论：这一步只验证参数邻域和 walk-forward 是否站得住，仍然不解锁纸盘或实盘。

## Walk-Forward Folds

| Test Year | Selected Params | Return | SPY | Sharpe | MDD | Alive |
|---:|---|---:|---:|---:|---:|---:|
| 2015 | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 1.0, "turnover_threshold": 0.35}` | -0.52% | -0.76% | 0.058 | -17.87% | 否 |
| 2016 | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 1.0, "turnover_threshold": 0.35}` | -0.31% | 11.20% | 0.000 | -12.12% | 否 |
| 2017 | `{"max_monthly_turnover": 0.5, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 19.73% | 18.48% | 2.825 | -4.64% | 是 |
| 2018 | `{"max_monthly_turnover": 0.75, "min_hold_months": 3, "rebalance_blend": 1.0, "turnover_threshold": 0.35}` | 5.63% | -7.01% | 0.468 | -12.12% | 是 |
| 2019 | `{"max_monthly_turnover": 0.5, "min_hold_months": 4, "rebalance_blend": 1.0, "turnover_threshold": 0.55}` | 7.81% | 28.65% | 1.194 | -3.41% | 是 |
| 2020 | `{"max_monthly_turnover": 0.75, "min_hold_months": 3, "rebalance_blend": 0.75, "turnover_threshold": 0.45}` | 13.67% | 15.09% | 1.174 | -9.95% | 是 |
| 2021 | `{"max_monthly_turnover": 0.5, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | -3.75% | 28.79% | -0.254 | -12.76% | 否 |
| 2022 | `{"max_monthly_turnover": 0.5, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | -1.52% | -19.95% | -0.131 | -9.12% | 否 |
| 2023 | `{"max_monthly_turnover": 0.75, "min_hold_months": 5, "rebalance_blend": 1.0, "turnover_threshold": 0.35}` | 4.70% | 24.81% | 0.715 | -5.22% | 是 |
| 2024 | `{"max_monthly_turnover": 0.75, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 15.35% | 24.00% | 1.224 | -6.29% | 是 |
| 2025 | `{"max_monthly_turnover": 0.75, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 30.93% | 16.64% | 2.573 | -5.74% | 是 |

## 方法

- For each test year, pick the best parameter on the prior 5 calendar years at 50bps, then evaluate the next calendar year out of sample.
- 存活规则：Alive at 50bps when CAGR > 0, Sharpe > 0, max drawdown > -40%, and total turnover < 140.
- 评分：sharpe + cagr - 0.5*abs(max_drawdown) - 0.003*turnover
- 约束：Research-only; no paper/live unlock.
