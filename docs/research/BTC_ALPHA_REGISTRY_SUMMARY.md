# BTC Alpha Registry Summary

- Paper queue: `LOCKED`
- Live: `FROZEN`

## Archived Alpha

- `perp_dual_trend`: event_PF stuck near 1.01-1.02; no stable repair pattern (last_run_id `20260516T100000Z_eventreturn_alpha`)
- `liquidation_shock_recovery`: full-ledger event_PF 0.998; lifecycle drag; no ablation passed (last_run_id `20260517T010000Z_liquidation_shock_attribution`)
- `compression_expansion_breakout`: hypothesis layer passed but full-lifecycle event-ledger candidate failed event_PF, walk-forward, and regime gates; v2 lifecycle gate rejected the raw/target-active edge (last_run_id `20260516T133000Z_compression_expansion_eventledger`)

## Rejected Hypothesis

- `low_vol_uptrend`: event_PF_proxy 0.979469; fold stability failed (last_run_id `20260516T120000Z_lowvol_uptrend`)
- `range_reclaim_momentum`: full_lifecycle_event_PF_proxy=1.098985; fold_pass_rate_lifecycle=0.250000 (last_run_id `20260518T010000Z_range_reclaim_lifecycle`)

## Continue / Pending Research


## Lifecycle-Aware Rule

No hypothesis may generate a strategy skeleton from raw or target-active event-return evidence alone.
The v2 gate requires full-lifecycle event_PF, lifecycle drag, fold stability, cost-stress proxy, and tail checks.
