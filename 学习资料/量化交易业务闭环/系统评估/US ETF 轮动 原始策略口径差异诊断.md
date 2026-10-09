# US ETF 轮动 原始策略口径差异诊断

## 结论

- 受控保留的原始基线：`original_v8_2_semantics`。
- 原始 V8.2 口径状态：`available`。
- 集成研究口径状态：`available`。
- 主因：The original script uses calendar month-end dates and skips months when the calendar month-end is not a trading day; the integrated backtest uses the actual last trading day of every month.
- 指标标签问题：The original analysis labels mean_daily_return*252 as CAGR. This is arithmetic annualized return, not compound annual growth rate.
- 结论：The original strategy can look better than the integrated version under its original rebalance semantics, but on the current 2018-2026 data it still does not beat buy-and-hold SPY or QQQ on CAGR.
- 下一步：Use original_v8_2_semantics as the protected baseline for future limited improvements; report all changes against this baseline and against SPY/QQQ separately.

## 原始 V8.2 口径

- 策略 true CAGR：9.79%；原脚本标成 CAGR 的算术年化：10.61%。
- 策略 MDD：-24.29%；Turnover：82.70。
- SPY true CAGR：12.62%；QQQ true CAGR：19.50%。
- 自然月末数量：102；实际调仓数量：70；跳过月份：32。

## 集成研究口径

- 策略 true CAGR：6.35%；算术年化：7.32%。
- 策略 MDD：-34.53%；Turnover：124.97。
- SPY true CAGR：12.62%；QQQ true CAGR：19.50%。
- 调仓语义：actual_last_trading_day_each_month。
