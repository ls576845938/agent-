# BTC Hypothesis Lab v2 Lifecycle-Aware Research Gate Plan

## Step 0 Repo Freeze

- Branch: `main`
- Commit at sprint start: `200fc69`
- Dirty files at sprint start: none
- Applicable agent rules: `AGENTS.md`

## Archived / Rejected / Active Research State

Archived alpha lines:

- `perp_dual_trend`: archived after event_PF stayed near 1.01-1.02 and no stable repair pattern emerged.
- `liquidation_shock_recovery`: archived after full-ledger event_PF stayed below 1 and no ablation passed event_PF, WF, and cost stress together.

Rejected hypotheses:

- `low_vol_uptrend`: rejected after event_PF_proxy 0.979469 and fold stability failure.

Current research hypothesis:

- `compression_expansion_breakout`: existing hypothesis artifacts found; hypothesis layer passed for skeleton, but event-ledger candidate validation later failed event_PF, WF, and regime gates.

## Sprint Run ID

`20260517T020000Z_hypothesis_lab_v2_lifecycle`

## Allowed Changes

- `artifacts/btc_research_registry/research_registry.json`
- `docs/research/BTC_ALPHA_REGISTRY_SUMMARY.md`
- `docs/research/BTC_HYPOTHESIS_LAB_V2_LIFECYCLE_PLAN.md`
- `quant_us/research/btc_hypothesis_lab_v2.py`
- `scripts/research/evaluate_btc_hypothesis_v2.py`
- `scripts/reports/generate_btc_hypothesis_lab_v2_lifecycle_html.py`
- v2 lifecycle artifacts under `artifacts/btc_hypothesis/{run_id}/`
- focused tests under `tests/research/` and `tests/reports/`

## Forbidden Changes

- No paper/live/broker/OMS runtime changes.
- No resurrecting `perp_dual_trend`.
- No resurrecting `liquidation_shock_recovery` as v2/v3.
- No strategy skeleton generation unless lifecycle-aware gate passes.
- No ordinary PF or signal equity in any gate.
- No target-active-only promotion logic.
- No hardcoded local absolute paths.

## Lifecycle-Aware Gate Contract

Every future BTC hypothesis must report:

- raw event-return distribution
- target-active event_PF_proxy
- full-lifecycle event_PF_proxy
- lifecycle drag
- cost-stress proxy
- fold stability
- tail dependency
- no-lookahead status
- skeleton guard decision

## Test Command

```bash
PYTHONPATH=. pytest \
  tests/research/test_btc_research_registry.py \
  tests/research/test_hypothesis_lab_v2_lifecycle_schema.py \
  tests/research/test_hypothesis_lab_v2_gate.py \
  tests/research/test_hypothesis_lab_v2_no_lookahead.py \
  tests/research/test_compression_expansion_lifecycle_report.py \
  tests/research/test_hypothesis_lab_v2_skeleton_guard.py \
  tests/research/test_hypothesis_lab_v2_safety_status.py \
  tests/reports/test_hypothesis_lab_v2_html_generation.py \
  -q
```

## Safety Rules

- `paper_queue=LOCKED`
- `live=FROZEN`
- `candidate_passed_internal_gate=0`
- `real_broker_api_called=false`
- `real_orders_created=false`

## Risk Notes

- Existing compression hypothesis has strong raw / target-active edge, but event-ledger candidate validation already showed full-lifecycle event_PF of only 1.0241.
- Lifecycle-aware gate is expected to reject any hypothesis whose target-active edge does not survive complete ledger lifecycle and fold stability.
