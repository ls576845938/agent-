# US Equity Dual Momentum Strategy Card

## Identity

- Strategy id: `us_equity_dual_momentum_research_placeholder`
- Family: `dual_momentum`
- Current status: `hypothesis_registered_only`
- Current stage: `strategy_hypothesis_registration`
- Paper/live status: locked

## Hypothesis

The strategy combines time-series momentum and cross-sectional momentum across liquid ETFs. It should hold risk assets only when their own trend is positive, then prefer the strongest eligible sleeve versus defensive assets.

## Expected Return Sources

- Absolute momentum: avoid extended negative-trend regimes.
- Relative momentum: allocate to stronger risk or defensive sleeves.
- Defensive asset switch: reduce drawdown when risk assets lose trend.

## Required Data

- Point-in-time ETF prices and tradable universe.
- Defensive asset prices such as `SHV`, `IEF`, or `GLD`.
- Corporate-action adjustment replay before promotion.
- NYSE trading calendar and rebalance timestamps.

## Validation Contract

- Must enter the standard US equity backtest pipeline.
- Must compare against SPY, QQQ, 60/40, and SHV/cash.
- Must pass cost stress at 10bps, 25bps, and 50bps.
- Must pass walk-forward and parameter-neighborhood stability.
- Must document whether value comes from absolute trend, relative selection, or defensive allocation.

## Stop Or Disable Conditions

- Momentum filter fails to reduce drawdown versus benchmarks.
- Relative strength result depends on a single lookback.
- Defensive switch causes excessive whipsaw after costs.
- PIT universe, delisting, or corporate-action evidence is missing.

## Guardrails

- This is a registered hypothesis only.
- No paper simulation, broker call, private endpoint, order endpoint, or live order is allowed.
