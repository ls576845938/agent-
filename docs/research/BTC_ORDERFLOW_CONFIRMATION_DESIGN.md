# BTC Order-Flow Confirmation Design

## Objective

`btc_orderflow_confirmed_trend_v1` converts order-flow from a direct trading trigger into a confirmation factor for an existing BTC trend signal.

## Rules

- Order-flow cannot open a position by itself.
- A long entry requires a persistent long trend and persistent bullish order-flow confirmation.
- A short entry requires a persistent short trend and persistent bearish order-flow confirmation.
- If trend and order-flow conflict, the signal is flat.
- Conflict cannot create a reverse position.
- Position changes pass through min holding, cooldown, and exit hysteresis.
- Regime filters can block noisy low-volatility chop and shock regimes.

## Confirmation Inputs

- trailing fast/slow/regime moving-average trend
- trailing momentum threshold
- trailing volatility cap
- taker-buy ratio
- buy-pressure deviation versus trailing average
- quote-volume and trade-count intensity
- persistence window

All inputs are based on current and trailing data only.

## Expected Effect

The design should reduce false flips from standalone taker-buy pressure. The target is lower turnover than the legacy `btc_orderflow_pressure` while retaining information when order-flow agrees with a broader trend.
