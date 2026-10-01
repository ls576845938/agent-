# BTC Alpha Renewal Decision

- Run ID: `20260516T100000Z_eventreturn_alpha`
- Source run: `20260516T080000Z_eventpf_wf`
- Decision: `archive_perp_dual_trend`
- Status: `research_failed`
- v5 generated: `False`

## Conclusion

Archive the `perp_dual_trend` line as `research_failed`. The code and artifacts are retained, but no v5 is generated because the event-return evidence does not show a stable, rule-fixable defect.

## Evidence

- event_PF is constrained by near-balanced positive and negative hourly event returns rather than by ordinary closed-trade aggregation alone
- terminal exposure explains part of PF/event_PF divergence but does not create a gate-passing candidate
- failed folds 3 and 4 do not expose one robust, no-lookahead rule that would plausibly lift event_PF to 1.15
- order-flow and exit surgery had already failed to solve event_PF in the previous sprint

## Alpha Hypothesis Backlog

### BTC long-only event continuation after low-vol uptrend confirmation

- Rationale: Prior attribution showed long exposure in trending_up and low-vol uptrend contexts carries the cleanest positive contribution.
- Required data: BTCUSDT 1h OHLCV, multi-timeframe trend state, event-ledger fills
- Expected event-level edge: fewer adverse hourly mark-to-market events during confirmed continuation windows
- No-lookahead requirements: trend and volatility confirmation must use only current and historical bars
- First experiment plan: rank low-vol uptrend continuations by event-return PF and hold-age decay before creating a strategy candidate
- Stop condition: archive if event_PF < 1.10 or failed folds remain concentrated after first pass

### BTC compression-to-expansion breakout with event-return objective

- Rationale: Expansion regimes showed high payoff in trade attribution, but must be optimized directly on event returns.
- Required data: BTCUSDT OHLCV, volume/quote volume, range compression features
- Expected event-level edge: large positive event-return clusters after expansion onset, with explicit adverse-event stop
- No-lookahead requirements: compression thresholds must be expanding or rolling historical quantiles only
- First experiment plan: build a diagnostic breakout label-free signal and evaluate event-return distribution by expansion age
- Stop condition: archive if positive event sums are not at least 1.15x negative sums after costs

### BTC liquidation-shock recovery continuation

- Rationale: Current trend line avoids shocks, but post-shock continuation may offer a different event-return source.
- Required data: BTCUSDT OHLCV, volume shock state, liquidation proxy from candle/volume
- Expected event-level edge: asymmetric positive event-return rebounds after capitulation without broad short exposure
- No-lookahead requirements: shock detection must be bar-close only and recovery confirmation must wait for subsequent historical bars
- First experiment plan: profile event returns for post-shock windows before any strategy implementation
- Stop condition: archive if rebound edge is single-window only or max drawdown worsens above gate limits

## Safety

- PAPER QUEUE: LOCKED
- LIVE: FROZEN
- No v5, paper_ready, live_ready, or live_enabled state is created.
