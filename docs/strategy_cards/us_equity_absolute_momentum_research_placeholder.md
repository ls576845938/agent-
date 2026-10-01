# US Equity Absolute Momentum Strategy Card

## Identity

- Strategy id: `us_equity_absolute_momentum_research_placeholder`
- Family: `absolute_momentum`
- Current status: `hypothesis_registered_only`
- Current stage: `strategy_hypothesis_registration`
- Paper/live status: locked

## Hypothesis

The strategy uses an ETF's own trailing return or trend state to decide whether to hold risk exposure or move to a cash-like defensive sleeve. It tests whether simple trend exposure management adds value beyond buy-and-hold.

## Expected Return Sources

- Time-series momentum in broad ETF sleeves.
- Drawdown reduction from moving to `SHV` or `IEF`.
- Reduced exposure during persistent bear regimes.

## Required Data

- Point-in-time adjusted ETF OHLCV.
- Cash or short-rate proxy for defensive return.
- Explicit rebalance calendar and signal timestamp.

## Validation Contract

- Must be tested with multiple lookbacks and thresholds.
- Must report CAGR, Vol, Sharpe, MDD, Calmar, turnover, and cost-stressed return.
- Must compare to buy-and-hold, fixed allocation, and cash.
- Must prove signals use only data visible at rebalance time.

## Stop Or Disable Conditions

- Return improvement is only from avoiding one historical crash.
- Drawdown reduction is too small to justify cash drag.
- Parameter neighborhood is unstable.
- Defensive asset data is stale or not point-in-time.

## Guardrails

- This is a registered hypothesis only.
- It cannot start forward observation, paper simulation, or live trading without validation gate approval.
