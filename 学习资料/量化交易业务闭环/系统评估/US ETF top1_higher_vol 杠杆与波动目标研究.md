# US ETF top1_higher_vol 杠杆与波动目标研究

## 结论

- 状态：`leveraged_candidate_manual_review_required`。
- 未杠杆 true CAGR：17.79%，MDD：-22.00%。
- 最优杠杆/波动目标变体：`fixed_2x`，CAGR 27.96%，MDD -44.34%，Sharpe 0.847。
- QQQ CAGR：19.50%，MDD：-35.62%。
- 本报告不改变资产选择规则，不给 QQQ 或科技资产特权，只在组合收益层面研究杠杆。

## 排名

| Rank | Variant | CAGR | Vol | Sharpe | MDD | Calmar | Avg Lev | Max Lev | Beats QQQ Lower DD |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | fixed_2x | 27.96% | 37.57% | 0.847 | -44.34% | 0.631 | 2.00 | 2.00 | no |
| 2 | vol_target_25pct_cap2x | 24.55% | 24.94% | 1.006 | -30.63% | 0.801 | 1.50 | 2.00 | yes |
| 3 | fixed_1.5x | 23.33% | 28.18% | 0.887 | -33.13% | 0.704 | 1.50 | 1.50 | yes |
| 4 | vol_target_25pct_cap1.5x | 21.59% | 22.76% | 0.974 | -26.61% | 0.811 | 1.31 | 1.50 | yes |
| 5 | vol_target_20pct_cap1.5x | 20.36% | 19.68% | 1.041 | -23.34% | 0.873 | 1.18 | 1.50 | yes |
| 6 | vol_target_20pct_cap2x | 20.82% | 20.81% | 1.014 | -26.84% | 0.776 | 1.31 | 2.00 | yes |
| 7 | vol_target_25pct_cap2x_dd_delever | 20.73% | 22.82% | 0.941 | -28.72% | 0.722 | 1.34 | 2.00 | yes |
| 8 | fixed_2x_dd_delever | 23.11% | 34.14% | 0.783 | -43.11% | 0.536 | 1.77 | 2.00 | no |
| 9 | fixed_1.2x | 20.11% | 22.54% | 0.927 | -26.43% | 0.761 | 1.20 | 1.20 | yes |
| 10 | vol_target_15pct_cap1.5x | 16.43% | 15.61% | 1.053 | -19.65% | 0.836 | 0.99 | 1.50 | no |
| 11 | vol_target_20pct_cap2x_dd_delever | 17.73% | 18.98% | 0.956 | -24.37% | 0.728 | 1.16 | 2.00 | no |
| 12 | vol_target_15pct_cap2x | 16.60% | 16.08% | 1.036 | -20.26% | 0.819 | 1.06 | 2.00 | no |
| 13 | vol_target_20pct_cap1.5x_dd_delever | 17.13% | 18.03% | 0.968 | -23.14% | 0.740 | 1.05 | 1.50 | no |
| 14 | fixed_1.5x_dd_delever | 19.23% | 25.61% | 0.817 | -32.95% | 0.584 | 1.33 | 1.50 | no |
| 15 | vol_target_25pct_cap1.5x_dd_delever | 17.93% | 20.94% | 0.894 | -27.44% | 0.653 | 1.16 | 1.50 | no |
| 16 | fixed_1.2x_dd_delever | 16.53% | 20.49% | 0.850 | -26.46% | 0.625 | 1.06 | 1.20 | no |
| 17 | vol_target_15pct_cap2x_dd_delever | 14.19% | 14.67% | 0.979 | -18.72% | 0.758 | 0.95 | 2.00 | no |
| 18 | vol_target_15pct_cap1.5x_dd_delever | 13.95% | 14.24% | 0.989 | -18.57% | 0.751 | 0.88 | 1.50 | no |

## 方法

- 融资成本：4.50%/年，仅对超过 1x 的暴露扣除。
- 约束：Research only; leveraged variants require financing, margin, and manual risk review before any paper/live consideration.
