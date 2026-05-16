# BTC Low-Vol Uptrend Event-Continuation Research Plan

## Step 0 Repository State

- Branch: `main`
- Starting commit: `4e380ec`
- Dirty files inventory at sprint start: none (`git status --short` returned no paths)
- Applicable project rules: `./AGENTS.md`
- Previous sprint run id: `20260516T100000Z_eventreturn_alpha`
- Previous sprint artifacts: `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/`
- Previous sprint decision: `archive_perp_dual_trend`
- Previous sprint status: `research_failed`
- Previous v5 generated: `false`
- Paper queue: `LOCKED`
- Live: `FROZEN`

## AGENTS.md Constraints Applied

- Strategy code must not call brokers directly.
- All PnL and research evidence must derive from fills, ledger, or explicit event-return labels.
- Every experiment must record data version, strategy version, params, cost model, slippage model, and commit hash when applicable.
- No future function and no look-ahead bias.
- Do not introduce paper/live trading before gates.
- Do not silently catch trading or accounting errors.
- Add relevant tests and report exact commands/results.

## Current Archive Status

The `perp_dual_trend` strategy line is archived as `research_failed` in:

- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/alpha_renewal_decision.json`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/perp_dual_trend_archive_manifest.json`

This sprint must not restore that line, generate v5/v6, or reuse `perp_dual_trend` as the strategy candidate.

## Run ID Rule

Run ids use UTC timestamp plus sprint suffix:

`YYYYMMDDTHHMMSSZ_lowvol_uptrend`

This sprint uses:

`20260516T120000Z_lowvol_uptrend`

## Planned Artifacts

- `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/low_vol_uptrend_feature_profile.json`
- `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/low_vol_uptrend_event_table.csv`
- `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/low_vol_uptrend_distribution_report.json`
- `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/low_vol_uptrend_hypothesis_decision.json`
- `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/paper_live_safety_status.json`
- `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/test_results.json`
- `reports/quantstation_vnext_btc_low_vol_uptrend_hypothesis_20260516T120000Z_lowvol_uptrend.html`

## Files Allowed For This Sprint

- `quant_us/research/btc_low_vol_uptrend.py`
- `scripts/research/build_btc_low_vol_uptrend_event_profile.py`
- `scripts/research/analyze_btc_low_vol_uptrend_distribution.py`
- `scripts/research/evaluate_btc_low_vol_uptrend_hypothesis.py`
- `scripts/reports/generate_btc_low_vol_uptrend_hypothesis_html.py`
- New research docs under `docs/research/`
- New static report copies under `reports/` and `docs/reports/`
- New artifacts under `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/`
- New focused tests under `tests/research/` and `tests/reports/`
- Optional strategy skeleton only if hypothesis passes: `configs/btc/hypothesis/low_vol_uptrend_event_continuation_v1.yaml`

## Files And Modules Forbidden For This Sprint

- No broker adapter edits.
- No live runtime edits.
- No paper runtime edits.
- No OMS or live risk execution path edits.
- No `perp_dual_trend` v5/v6 config.
- No order-flow entry trigger.
- No signal-equity gate use.
- No closed-trade PF gate use.
- No gate threshold lowering.
- No broad strategy generation.
- No hard-coded local absolute paths.

## Task Split

1. Feature definition: define low volatility, uptrend confirmation, continuation state, shock/high-vol/downtrend exclusions, folds, and future-return labels with no lookahead in features.
2. Event-return distribution profile: generate horizon labels at 1h, 4h, 12h, 24h, and 48h where available.
3. Distribution analysis: aggregate event_PF proxy, positive rate, mean/median, skew/kurtosis, tails, fold stability, regime breakdown, and horizon stability.
4. Hypothesis gate: decide `hypothesis_rejected`, `hypothesis_needs_more_data`, or `hypothesis_passed_for_strategy_skeleton`.
5. Strategy skeleton guard: generate no config unless the hypothesis passes; any generated skeleton is research-only.
6. Safety artifact: paper queue locked, live frozen, no broker, no real orders.
7. HTML report and tests.

## Paper / Live Safety Rules

- `candidate_passed_internal_gate = 0`
- `paper_queue = LOCKED`
- `live = FROZEN`
- `real_broker_api_called = false`
- `real_orders_created = false`
- No `paper_ready`, `live_ready`, or `live_enabled` state.

## Test Command

```bash
PYTHONPATH=. pytest \
  tests/research/test_low_vol_uptrend_feature_profile_schema.py \
  tests/research/test_low_vol_uptrend_no_lookahead.py \
  tests/research/test_low_vol_uptrend_distribution_report.py \
  tests/research/test_low_vol_uptrend_hypothesis_gate.py \
  tests/research/test_low_vol_uptrend_strategy_skeleton_guard.py \
  tests/research/test_low_vol_uptrend_safety_status.py \
  tests/reports/test_low_vol_uptrend_html_generation.py \
  -q
```

## Risk Points

- Forward event returns are labels only and must not be used in feature construction.
- If active sample count is small or fold stability is poor, no skeleton may be generated.
- A high 1h event_PF proxy is insufficient if 4h/12h horizon and fold stability fail.
- Edge must not depend on order-flow or restored `perp_dual_trend` logic.
- Results are research-only and cannot unlock paper/live.
