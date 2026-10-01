# BTC Regime Filter Design

## Scope

This design is research-only and supports BTC Alpha Hardening Sprint candidates. It does not change live, paper, broker, or ledger behavior.

## Regime Labels

The classifier emits:

- `trending_up`
- `trending_down`
- `high_vol_trend`
- `low_vol_chop`
- `mean_reverting_chop`
- `liquidation_shock`
- `compression`
- `expansion`

## No-Lookahead Rule

All labels are computed from current and historical OHLCV values only:

- trend: rolling price change over a trailing window
- volatility: trailing realized volatility
- compression: trailing bar range and low volatility
- expansion: trailing volatility plus volume intensity
- liquidation shock: current negative return versus trailing volatility and volume intensity

The classifier does not use future returns, future extrema, future volume, or trade outcomes.

## Strategy Configuration

Candidates can use:

```yaml
allowed_regimes:
  - trending_up
  - trending_down
  - high_vol_trend
  - expansion
blocked_regimes:
  - low_vol_chop
  - mean_reverting_chop
  - liquidation_shock
```

If `allowed_regimes` is set, signals outside those regimes are forced flat. If `blocked_regimes` is set, signals inside those regimes are forced flat.

## Reporting

Each event-ledger fill stream is converted into closed trades and mapped to the regime at entry time. The report includes:

- Profit Factor
- Sharpe
- win rate
- turnover proxy
- average holding bars
- trade count
- PnL contribution
- pass/fail flag

The Sprint pass rate is the fraction of reported regimes that pass non-negative contribution and PF >= 1.0, with empty regimes counted as not harmful.
