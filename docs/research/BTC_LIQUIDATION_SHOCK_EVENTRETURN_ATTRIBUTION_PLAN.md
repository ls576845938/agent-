# BTC Liquidation-Shock Event-Return Attribution and Skeleton Decision Plan

## Step 0 Repo Freeze

- Branch: `main`
- Commit at sprint start: `a99ca0e`
- Dirty files at sprint start: none
- Applicable agent rules: `AGENTS.md`

## Source Evidence

- Previous event-ledger validation run:
  `artifacts/btc_candidate_validation/20260516T234000Z_liquidation_shock_eventledger/`
- Current candidate: `liquidation_shock_recovery_v1_event_ledger`
- Current status: `candidate_gate_failed`
- Paper queue: `LOCKED`
- Live: `FROZEN`

## Current Blocking Metrics

- PF: `1.560750` diagnostic only
- event_PF: `0.998000`
- WF pass: `0.750000`
- regime pass: `0.800000`
- cost stress base: fail
- cost stress harsh: fail
- PBO / DSR: `0.250000 / 0.000000`
- Fail reasons: `event_profit_factor`, `walk_forward_pass_rate`, `cost_stress_base`, `cost_stress_harsh`, `dsr`

## This Sprint Run ID

`20260517T010000Z_liquidation_shock_attribution`

Outputs go under:

`artifacts/btc_candidate_attribution/20260517T010000Z_liquidation_shock_attribution/`

## Allowed Changes

- `docs/research/BTC_LIQUIDATION_SHOCK_EVENTRETURN_ATTRIBUTION_PLAN.md`
- `docs/research/BTC_LIQUIDATION_SHOCK_SKELETON_DECISION.md`
- `quant_us/research/btc_liquidation_shock_attribution.py`
- `scripts/research/build_btc_liquidation_shock_event_return_attribution.py`
- `scripts/research/autopsy_btc_liquidation_shock_failed_fold.py`
- `scripts/research/analyze_btc_liquidation_shock_regime_failure.py`
- `scripts/research/ablate_btc_liquidation_shock_exit_lifecycle.py`
- `scripts/research/analyze_btc_liquidation_shock_recovery_confirmation.py`
- `scripts/reports/generate_btc_liquidation_shock_attribution_html.py`
- focused tests under `tests/research/` and `tests/reports/`
- static reports and reproducible summary artifacts for this run

## Forbidden Changes

- No paper/live/broker/OMS runtime changes.
- No gate threshold lowering.
- No strategy promotion based on ordinary PF.
- No fold-specific date hardcoding.
- No future return or future high/low in feature definitions.
- No deleting old tests.
- No local absolute path in artifacts/configs.

## Task Breakdown

1. Build event-return attribution from ledger equity snapshots and v1 signal lifecycle.
2. Autopsy fold 3 without hardcoding dates into strategy logic.
3. Analyze mean-reverting-chop drag and controlled ablations.
4. Compare exit lifecycle variants: 6 / 12 / 18 / 24 / 36 bars plus confirmation variants.
5. Analyze recovery confirmation rules with no-lookahead constraints.
6. Decide whether v2 is evidence-supported or archive the skeleton.
7. Write safety status and static HTML report.
8. Add schema/no-lookahead/gate/safety/html tests.

## Test Command

```bash
PYTHONPATH=. pytest \
  tests/research/test_liquidation_shock_event_return_attribution_schema.py \
  tests/research/test_liquidation_shock_event_pf_recompute.py \
  tests/research/test_liquidation_shock_fold3_autopsy.py \
  tests/research/test_liquidation_shock_mean_reverting_chop_analysis.py \
  tests/research/test_liquidation_shock_exit_lifecycle_ablation.py \
  tests/research/test_liquidation_shock_recovery_confirmation_no_lookahead.py \
  tests/research/test_liquidation_shock_v2_generation_guard.py \
  tests/research/test_liquidation_shock_v2_gate_thresholds.py \
  tests/research/test_liquidation_shock_paper_live_safety.py \
  tests/reports/test_liquidation_shock_attribution_html_generation.py \
  -q
```

## Safety Rules

- Paper queue remains `LOCKED`.
- Live remains `FROZEN`.
- `real_broker_api_called=false`.
- `real_orders_created=false`.
- v2 may only be generated if cross-fold evidence is stable; otherwise skeleton must be archived.

## Risks

- Event-ledger attribution may show ordinary PF is disconnected from event_PF because active exposure has nearly symmetric positive/negative event sums.
- Fold 3 may be a localized failure, which is not enough evidence for v2.
- Mean-reverting-chop keep-out may reduce losses but also reduce sample sufficiency or fail to improve WF/cost stress.
- Shorter exits may improve event_PF but break fold stability or cost stress.
