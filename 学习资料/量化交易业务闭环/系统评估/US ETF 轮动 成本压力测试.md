# US ETF 轮动 成本压力测试

## 结论

- 50bps 下排名第一：`v1_turnover_guard`，CAGR 6.95%，Sharpe 0.555，MDD -31.20%。
- 成本压力只验证高换手脆弱性，不代表可纸盘或实盘。

## 成本压力表

| 方案 | 成本 | CAGR | Sharpe | MDD | Turnover | 成本拖累估算 | 50bps通过 |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline_current | 10bps | 5.98% | 0.490 | -33.66% | 321.20 | 32.12% | 否 |
| baseline_current | 25bps | 3.99% | 0.352 | -36.26% | 321.20 | 80.30% | 否 |
| baseline_current | 50bps | 0.74% | 0.123 | -53.91% | 321.20 | 160.60% | 否 |
| v1_combined_conservative | 10bps | 8.68% | 0.744 | -21.70% | 181.89 | 18.19% | 是 |
| v1_combined_conservative | 25bps | 7.51% | 0.655 | -23.56% | 181.89 | 45.47% | 是 |
| v1_combined_conservative | 50bps | 5.60% | 0.505 | -26.57% | 181.89 | 90.95% | 是 |
| v1_defense_regime_cap | 10bps | 6.07% | 0.495 | -33.75% | 317.92 | 31.79% | 否 |
| v1_defense_regime_cap | 25bps | 4.10% | 0.359 | -36.35% | 317.92 | 79.48% | 否 |
| v1_defense_regime_cap | 50bps | 0.88% | 0.133 | -52.32% | 317.92 | 158.96% | 否 |
| v1_macro_floor | 10bps | 6.42% | 0.509 | -32.44% | 289.00 | 28.90% | 否 |
| v1_macro_floor | 25bps | 4.61% | 0.388 | -34.98% | 289.00 | 72.25% | 否 |
| v1_macro_floor | 50bps | 1.67% | 0.188 | -42.26% | 289.00 | 144.50% | 否 |
| v1_risk_capped_selection | 10bps | 6.66% | 0.605 | -24.96% | 312.71 | 31.27% | 否 |
| v1_risk_capped_selection | 25bps | 4.71% | 0.448 | -28.10% | 312.71 | 78.18% | 否 |
| v1_risk_capped_selection | 50bps | 1.52% | 0.186 | -40.39% | 312.71 | 156.36% | 否 |
| v1_turnover_guard | 10bps | 9.41% | 0.722 | -27.63% | 143.63 | 14.36% | 是 |
| v1_turnover_guard | 25bps | 8.48% | 0.660 | -28.99% | 143.63 | 35.91% | 是 |
| v1_turnover_guard | 50bps | 6.95% | 0.555 | -31.20% | 143.63 | 71.81% | 是 |

## 方法

- 成本模型：strategy_daily_return = gross_weighted_asset_return - turnover * cost_per_turnover
- 50bps 生存规则：50bps survives when CAGR > 0, Sharpe > 0, and max drawdown is better than -40%.
- 说明：This is a research-only stress test. Passing it does not unlock paper or live trading.
