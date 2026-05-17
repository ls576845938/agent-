# BTC Alpha Registry Summary

- Paper queue: `LOCKED`
- Live: `FROZEN`

## Archived Alpha

- `perp_dual_trend`: event_PF stuck near 1.01-1.02; no stable repair pattern (last_run_id `20260516T100000Z_eventreturn_alpha`)
- `liquidation_shock_recovery`: full-ledger event_PF 0.998; lifecycle drag; no ablation passed (last_run_id `20260517T010000Z_liquidation_shock_attribution`)

## Rejected Hypothesis

- `low_vol_uptrend`: event_PF_proxy 0.979469; fold stability failed (last_run_id `20260516T120000Z_lowvol_uptrend`)

## Continue / Pending Research

- `compression_expansion_breakout`: status `candidate_gate_failed`; hypothesis layer passed but event-ledger candidate failed: event_profit_factor, walk_forward_pass_rate, regime_pass_rate

## Lifecycle-Aware Rule

No hypothesis may generate a strategy skeleton from raw or target-active event-return evidence alone.
The v2 gate requires full-lifecycle event_PF, lifecycle drag, fold stability, cost-stress proxy, and tail checks.
