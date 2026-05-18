# BTC Alpha Registry Summary

- Paper queue: `LOCKED`
- Live: `FROZEN`

## Registry Items

- `compression_expansion_breakout`: `candidate_gate_failed`; hypothesis layer passed but event-ledger candidate failed: event_profit_factor, walk_forward_pass_rate, regime_pass_rate (last_run_id `20260516T133000Z_compression_expansion_eventledger`)
- `liquidation_shock_recovery`: `archived`; full-ledger event_PF 0.998; lifecycle drag; no ablation passed (last_run_id `20260517T010000Z_liquidation_shock_attribution`)
- `low_vol_uptrend`: `hypothesis_rejected`; event_PF_proxy 0.979469; fold stability failed (last_run_id `20260516T120000Z_lowvol_uptrend`)
- `perp_dual_trend`: `archived`; event_PF stuck near 1.01-1.02; no stable repair pattern (last_run_id `20260516T100000Z_eventreturn_alpha`)
- `range_reclaim_momentum`: `hypothesis_rejected`; full_lifecycle_event_PF_proxy=1.098985; fold_pass_rate_lifecycle=0.250000; tail_top5=0.055292; reasons=raw_event_PF_proxy, target_active_event_PF_proxy, full_lifecycle_event_PF_proxy, fold_pass_rate_lifecycle, cost_stress_proxy_base (last_run_id `20260518T010000Z_range_reclaim_lifecycle`)

## Lifecycle-Aware Rule

New BTC hypotheses must pass full-lifecycle event_PF, lifecycle fold stability, cost proxy, and tail dependency before a skeleton is allowed.
Archived lines, including perp_dual_trend and liquidation_shock_recovery, remain inactive.
