# US ETF 轮动 书籍启发优化

## 结论

- 当前全体最优：`two_moving_averages_151`，50bps CAGR 6.55%，Sharpe 0.718，MDD -12.98%，Turnover 41.20。
- 最高 CAGR 候选：`baseline_v2_turnover_guard`，参数 `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}`，50bps CAGR 6.67%，Sharpe 0.692，MDD -17.87%，Turnover 64.36。
- 书籍启发最优：`two_moving_averages_151`，参数 `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}`。
- 书籍启发最优 50bps：CAGR 6.55%，Sharpe 0.718，MDD -12.98%，Turnover 41.20。
- 当前成本鲁棒基线 50bps：CAGR 6.67%，Sharpe 0.692，MDD -17.87%，Turnover 64.36。
- 本报告只做研究优化，不解锁纸盘或实盘。

## 151 策略覆盖

- 已从《151 Trading Strategies》目录解析出 `174` 个策略条目。
- 本轮直接映射并回测 `14` 个 151 启发策略族；其余大多需要期权链、VIX 期货、债券曲线、CDS/MBS、税务/困境证券或盘口级数据。
- 这不是说其他策略没价值，而是当前 ETF 日线 + FRED 宏观数据无法严谨验证那些策略。

| Chapter | Strategy Count |
|---|---:|
| Cash | 5 |
| Commodities | 6 |
| Convertibles | 2 |
| Cryptocurrencies | 2 |
| Distressed Assets | 7 |
| Exchange-Traded Funds (ETFs) | 8 |
| Fixed Income | 15 |
| Foreign Exchange (FX) | 6 |
| Futures | 7 |
| Global Macro | 4 |
| Indexes | 5 |
| Miscellaneous Assets | 4 |
| Options | 58 |
| Real Estate | 8 |
| Stocks | 21 |
| Structured Assets | 6 |
| Tax Arbitrage | 3 |
| Volatility | 7 |

## 收益和夏普偏低的原因

- 当前目标函数偏向 `50bps 成本后仍存活 + 低换手 + 低回撤`，不是最大化 CAGR。
- 策略是月度长-only ETF 轮动，不能做空、不能杠杆，也没有期权/波动率/期货 carry 等收益源。
- 2018 以后 SPY/QQQ 牛市很强，任何带宏观防守和现金/债券残余仓位的策略都会牺牲部分上行收益。
- 高成本压力会惩罚高换手策略，所以很多看似高收益的动量切换会被主动压下去。
- 本轮已加入 `aggressive_no_turnover_guard`；它不主动压换手，但 50bps 后换手普遍约 300，收益和回撤明显恶化，所以不能简单理解为“换手越高收益越高”。

## 书籍启发方向

| 方向 | 本轮实现 | 主要启发 |
|---|---|---|
| alpha_rotation_residual_151 | 50bps CAGR 6.04%, Sharpe 0.660, MDD -15.32%, Turnover 40.38 | 151 ETF and stock chapters: alpha/residual momentum after removing broad market beta. |
| channel_breakout_151 | 50bps CAGR 4.31%, Sharpe 0.646, MDD -12.55%, Turnover 35.91 | 151 stock chapter: channel strategy translated into 126-day Donchian-style breakout. |
| dual_momentum_absolute_relative | 50bps CAGR 4.35%, Sharpe 0.592, MDD -24.73%, Turnover 29.31 | Dual Momentum Investing and 151 Trading Strategies: rank by relative strength only after absolute momentum clears cash/defensive return. |
| ensemble_forecast_blend | 50bps CAGR 6.17%, Sharpe 0.678, MDD -15.20%, Turnover 39.96 | Active Portfolio Management and Systematic Trading: combine forecasts, then let portfolio construction and cost controls translate forecast into weight. |
| etf_mean_reversion_151 | 50bps CAGR 3.91%, Sharpe 0.580, MDD -14.86%, Turnover 36.97 | 151 ETF and futures chapters: mean reversion tested only inside positive long-term trend. |
| low_volatility_anomaly_151 | 50bps CAGR 5.33%, Sharpe 0.682, MDD -14.03%, Turnover 40.84 | 151 stock chapter: low-volatility anomaly mapped to ETF selection. |
| macro_vol_scaled_overlay | 50bps CAGR 6.39%, Sharpe 0.654, MDD -20.99%, Turnover 64.13 | Systematic Trading and volatility-targeting strategies: reduce offensive budget when market volatility is elevated. |
| multi_asset_tsmom_151 | 50bps CAGR 6.49%, Sharpe 0.688, MDD -15.66%, Turnover 40.37 | 151 ETF and futures chapters: multi-asset trend following / time-series momentum. |
| multi_speed_trend_forecast | 50bps CAGR 6.46%, Sharpe 0.705, MDD -15.20%, Turnover 40.16 | Systematic Trading and trend-following notes: blend several trend horizons into a capped forecast before position construction. |
| multifactor_portfolio_151 | 50bps CAGR 5.90%, Sharpe 0.677, MDD -15.63%, Turnover 40.79 | 151 stock chapter: multifactor portfolio combines momentum, low volatility, and trend quality. |
| quality_momentum_12_1 | 50bps CAGR 5.94%, Sharpe 0.660, MDD -15.48%, Turnover 39.22 | Quantitative Momentum: use 12-1 momentum, path quality, and volatility adjustment instead of raw recent strength. |
| r_squared_trend_quality_151 | 50bps CAGR 6.22%, Sharpe 0.659, MDD -16.48%, Turnover 40.28 | 151 ETF chapter: R-squared trend quality favors assets with cleaner trend fits. |
| sector_dual_momentum_151 | 50bps CAGR 3.13%, Sharpe 0.477, MDD -24.73%, Turnover 29.58 | 151 ETF chapter: dual-momentum sector rotation uses relative rank plus absolute/cash hurdle. |
| sector_momentum_ma_filter_151 | 50bps CAGR 5.94%, Sharpe 0.589, MDD -20.41%, Turnover 64.50 | 151 ETF chapter: sector momentum rotation with a moving-average filter. |
| sector_price_momentum_rotation_151 | 50bps CAGR 6.20%, Sharpe 0.606, MDD -20.48%, Turnover 62.79 | 151 ETF chapter: sector momentum rotation maps directly to sector ETF ranking. |
| single_moving_average_151 | 50bps CAGR 6.12%, Sharpe 0.668, MDD -13.45%, Turnover 40.94 | 151 stock chapter: single moving-average timing converted into ETF cross-sectional ranking. |
| support_resistance_breakout_151 | 50bps CAGR 4.11%, Sharpe 0.626, MDD -11.30%, Turnover 36.12 | 151 stock chapter: support/resistance translated into 63-day breakout strength. |
| three_moving_averages_151 | 50bps CAGR 5.41%, Sharpe 0.669, MDD -10.68%, Turnover 39.33 | 151 stock chapter: three moving averages require short, medium, and long trend alignment. |
| two_moving_averages_151 | 50bps CAGR 6.55%, Sharpe 0.718, MDD -12.98%, Turnover 41.20 | 151 stock chapter: two moving averages become a trend-strength forecast. |

## Top 15

| Rank | Family | Params | 10bps CAGR | 25bps CAGR | 50bps CAGR | 50bps Sharpe | 50bps MDD | Turnover | Survives |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | two_moving_averages_151 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 7.25% | 6.98% | 6.55% | 0.718 | -12.98% | 41.20 | yes |
| 2 | multi_speed_trend_forecast | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 7.13% | 6.88% | 6.46% | 0.705 | -15.20% | 40.16 | yes |
| 3 | baseline_v2_turnover_guard | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 7.76% | 7.35% | 6.67% | 0.692 | -17.87% | 64.36 | yes |
| 4 | multi_asset_tsmom_151 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 7.17% | 6.91% | 6.49% | 0.688 | -15.66% | 40.37 | yes |
| 5 | ensemble_forecast_blend | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.84% | 6.59% | 6.17% | 0.678 | -15.20% | 39.96 | yes |
| 6 | multi_asset_tsmom_151 | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 7.56% | 7.16% | 6.48% | 0.646 | -17.75% | 64.00 | yes |
| 7 | single_moving_average_151 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.81% | 6.55% | 6.12% | 0.668 | -13.45% | 40.94 | yes |
| 8 | r_squared_trend_quality_151 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.89% | 6.64% | 6.22% | 0.659 | -16.48% | 40.28 | yes |
| 9 | macro_vol_scaled_overlay | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 7.47% | 7.06% | 6.39% | 0.654 | -20.99% | 64.13 | yes |
| 10 | alpha_rotation_residual_151 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.72% | 6.46% | 6.04% | 0.660 | -15.32% | 40.38 | yes |
| 11 | ensemble_forecast_blend | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 7.24% | 6.84% | 6.17% | 0.656 | -17.87% | 63.78 | yes |
| 12 | multifactor_portfolio_151 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.58% | 6.33% | 5.90% | 0.677 | -15.63% | 40.79 | yes |
| 13 | quality_momentum_12_1 | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.60% | 6.35% | 5.94% | 0.660 | -15.48% | 39.22 | yes |
| 14 | single_moving_average_151 | `{"max_monthly_turnover": 0.75, "min_hold_months": 4, "rebalance_blend": 0.75, "turnover_threshold": 0.35}` | 7.41% | 6.99% | 6.30% | 0.629 | -21.04% | 65.81 | yes |
| 15 | macro_vol_scaled_overlay | `{"max_monthly_turnover": 0.5, "min_hold_months": 5, "rebalance_blend": 0.75, "turnover_threshold": 0.55}` | 6.58% | 6.31% | 5.87% | 0.659 | -17.42% | 42.67 | yes |

## 暂缓方向

- `carry plus momentum`：Expected Returns and 151 Trading Strategies support carry/momentum blends, but this ETF data set has no reliable futures roll yield, funding, or term-structure carry fields yet.
- `residual momentum after multi-factor risk model`：Active Portfolio Management supports residual forecast construction, but the current ETF universe has only ETF prices and coarse macro data; a factor exposure model should be added before testing it.

## 方法

- Convert local markdown book notes into testable rotation variants, then compare them with the existing cost-robust baseline.
- 成本压力：Each candidate is evaluated at 10bps, 25bps, and 50bps turnover cost.
- 评分：0.25*50bps_sharpe + 3.0*50bps_cagr - 0.10*abs(50bps_mdd) + 0.05*mean_focus_year_excess; turnover is reported but no longer penalized in the primary score.
- 约束：Research-only; no paper/live unlock; same repaired ETF data and FRED macro data as prior reports.
