# US ETF 轮动 基准替代价值评估

## 结论

- Gate 状态：`defensive_candidate_only_not_spy_qqq_replacement`。
- 进攻型替代通过数：`0` / `58`。
- 防守型候选通过数：`26` / `58`。
- 本报告不允许纸盘或实盘晋级，只判断是否值得替代长持基准。

## 基准表现

| Benchmark | CAGR | Sharpe | MDD | Total Return |

## 受保护原始基线

- Baseline：`original_v8_2_semantics`，不混入当前候选排名。
- 调仓语义：`calendar_month_end_only_skip_if_not_trading_day`。
- true CAGR：9.79%；算术年化：10.61%；MDD：-24.29%；Turnover：82.70。
- 同期 SPY true CAGR：12.62%；同期 QQQ true CAGR：19.50%。

|---|---:|---:|---:|---:|
| SPY | 7.08% | 0.453 | -56.47% | 469.51% |
| QQQ | 10.74% | 0.536 | -70.40% | 1235.49% |
| 60_40_SPY_IEF | 4.47% | 0.438 | -37.78% | 204.18% |
| equal_offensive_etf | 7.01% | 0.556 | -35.74% | 459.25% |

## 最优候选

- 进攻排序第一：`two_moving_averages_151`，CAGR 6.55%，Sharpe 0.718，MDD -12.98%，状态 `defensive_candidate_only`。
- 防守排序第一：`two_moving_averages_151`，CAGR 6.55%，Sharpe 0.718，MDD -12.98%，状态 `defensive_candidate_only`。

## 候选排名

| Rank | Family | Status | CAGR | Sharpe | MDD | Excess CAGR vs SPY | Excess CAGR vs QQQ | MDD Improvement vs SPY |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | two_moving_averages_151 | defensive_candidate_only | 6.55% | 0.718 | -12.98% | -0.53% | -4.18% | 43.49% |
| 2 | multi_speed_trend_forecast | defensive_candidate_only | 6.46% | 0.705 | -15.20% | -0.63% | -4.28% | 41.28% |
| 3 | multi_asset_tsmom_151 | defensive_candidate_only | 6.49% | 0.688 | -15.66% | -0.60% | -4.25% | 40.81% |
| 4 | three_moving_averages_151 | defensive_candidate_only | 5.41% | 0.669 | -10.68% | -1.67% | -5.32% | 45.79% |
| 5 | baseline_v2_turnover_guard | defensive_candidate_only | 6.67% | 0.692 | -17.87% | -0.41% | -4.06% | 38.61% |
| 6 | single_moving_average_151 | defensive_candidate_only | 6.12% | 0.668 | -13.45% | -0.96% | -4.62% | 43.02% |
| 7 | ensemble_forecast_blend | defensive_candidate_only | 6.17% | 0.678 | -15.20% | -0.92% | -4.57% | 41.28% |
| 8 | low_volatility_anomaly_151 | defensive_candidate_only | 5.33% | 0.682 | -14.03% | -1.75% | -5.40% | 42.44% |
| 9 | multifactor_portfolio_151 | defensive_candidate_only | 5.90% | 0.677 | -15.63% | -1.18% | -4.83% | 40.85% |
| 10 | alpha_rotation_residual_151 | defensive_candidate_only | 6.04% | 0.660 | -15.32% | -1.04% | -4.69% | 41.15% |
| 11 | quality_momentum_12_1 | defensive_candidate_only | 5.94% | 0.660 | -15.48% | -1.14% | -4.79% | 40.99% |
| 12 | r_squared_trend_quality_151 | defensive_candidate_only | 6.22% | 0.659 | -16.48% | -0.87% | -4.52% | 39.99% |
| 13 | ensemble_forecast_blend | defensive_candidate_only | 6.17% | 0.656 | -17.87% | -0.91% | -4.56% | 38.61% |
| 14 | macro_vol_scaled_overlay | defensive_candidate_only | 5.87% | 0.659 | -17.42% | -1.22% | -4.87% | 39.05% |
| 15 | multi_asset_tsmom_151 | defensive_candidate_only | 6.48% | 0.646 | -17.75% | -0.60% | -4.25% | 38.73% |
| 16 | channel_breakout_151 | rejected_vs_buy_hold | 4.31% | 0.646 | -12.55% | -2.77% | -6.42% | 43.93% |
| 17 | macro_vol_scaled_overlay | defensive_candidate_only | 6.39% | 0.654 | -20.99% | -0.70% | -4.35% | 35.48% |
| 18 | support_resistance_breakout_151 | rejected_vs_buy_hold | 4.11% | 0.626 | -11.30% | -2.97% | -6.62% | 45.17% |
| 19 | alpha_rotation_residual_151 | defensive_candidate_only | 5.99% | 0.634 | -17.97% | -1.09% | -4.74% | 38.50% |
| 20 | multi_speed_trend_forecast | defensive_candidate_only | 6.01% | 0.628 | -18.83% | -1.08% | -4.73% | 37.64% |

## 规则

- 进攻型替代：50bps candidate CAGR must exceed max(SPY, QQQ), Sharpe must exceed max(SPY, QQQ), and drawdown must not be worse than the harsher SPY/QQQ drawdown.
- 防守型候选：50bps candidate CAGR must be at least 75% of SPY CAGR, Sharpe must exceed SPY, and drawdown must be at least materially lower than SPY and QQQ.
- 淘汰：Candidate is neither an offensive replacement nor a defensive allocation candidate.
