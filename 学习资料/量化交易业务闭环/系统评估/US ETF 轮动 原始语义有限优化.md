# US ETF 轮动 原始语义有限优化

## 结论

- 决策：`offensive_candidate_for_manual_review`。
- 受保护基线：`original_v8_2_semantics`，调仓语义 `calendar_month_end_only_skip_if_not_trading_day`。
- 原始基线 true CAGR：9.79%，MDD：-24.29%。
- 最高 CAGR 候选：`top1_higher_vol`，true CAGR 17.79%，MDD -22.00%。
- 价值评分第一：`top1_higher_vol`，true CAGR 17.79%，MDD -22.00%。
- 同期 SPY true CAGR：12.62%；QQQ true CAGR：19.50%。

## 候选排名

| Rank | Candidate | true CAGR | Arithmetic Ann. | Sharpe | MDD | Turnover | Beats SPY | Beats QQQ |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | top1_higher_vol | 17.79% | 18.16% | 0.966 | -22.00% | 67.50 | yes | no |
| 2 | top1_concentrated | 16.37% | 16.59% | 0.984 | -19.10% | 67.92 | yes | no |
| 3 | medium_horizon_momentum | 11.70% | 12.27% | 0.793 | -17.62% | 83.43 | no | no |
| 4 | step_macro_gate | 10.49% | 11.25% | 0.710 | -22.59% | 81.40 | no | no |
| 5 | higher_target_vol_30 | 10.66% | 11.75% | 0.655 | -26.41% | 86.03 | no | no |
| 6 | long_horizon_momentum | 10.07% | 10.79% | 0.703 | -24.29% | 81.98 | no | no |
| 7 | higher_target_vol_25 | 10.46% | 11.49% | 0.658 | -25.71% | 84.98 | no | no |
| 8 | original_v8_2_semantics | 9.79% | 10.61% | 0.669 | -24.29% | 82.70 | no | no |
| 9 | top3_higher_vol | 9.75% | 10.50% | 0.679 | -28.29% | 79.83 | no | no |
| 10 | top3_diversified | 9.50% | 10.17% | 0.689 | -26.19% | 79.48 | no | no |

## 方法

- 允许改动：TOP_N, TARGET_VOL, TARGET_VOL_INVERTED, MOM_WEIGHTS, MACRO_MODE。
- 禁止改动：rebalance semantics, benchmark data, cost model, lookahead behavior, live/paper unlock。
- 本报告只做研究，不解锁纸盘或实盘。
