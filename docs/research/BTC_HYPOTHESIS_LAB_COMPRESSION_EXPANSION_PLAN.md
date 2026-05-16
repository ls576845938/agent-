# BTC Hypothesis Lab + Compression-to-Expansion Event Breakout Research Plan

## Step 0 Repository State

- Branch: `main`
- Starting commit: `153a6c7`
- Dirty files inventory at sprint start: none (`git status --short` returned no paths)
- Applicable project rules: `./AGENTS.md`
- Previous low-vol run id: `20260516T120000Z_lowvol_uptrend`
- Previous low-vol artifacts: `artifacts/btc_hypothesis/20260516T120000Z_lowvol_uptrend/`
- Previous low-vol decision: `hypothesis_rejected`
- Previous low-vol strategy skeleton generated: `false`
- Previous low-vol paper queue: `LOCKED`
- Previous low-vol live status: `FROZEN`
- `perp_dual_trend` archive artifact: `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/alpha_renewal_decision.json`
- `perp_dual_trend` archive decision: `archive_perp_dual_trend`
- `perp_dual_trend` v5 generated: `false`

## AGENTS.md Constraints Applied

- Strategies must not call brokers directly.
- All PnL and gate evidence must remain ledger/event-return based; ordinary PF and signal equity are diagnostic only.
- Experiments must record data version, strategy version, parameters, cost/slippage model when applicable, and commit hash.
- No future function and no look-ahead bias.
- Do not introduce paper/live trading before gates.
- Add focused tests for research modules and report exact commands/results.
- Do not silently catch trading or accounting errors.

## Run ID Rule

Run ids use UTC timestamp plus hypothesis suffix:

`YYYYMMDDTHHMMSSZ_compression_expansion`

This sprint uses:

`20260516T122000Z_compression_expansion`

## Hypothesis Lab Design

The new lab module will be configuration driven so future BTC hypotheses can reuse the same pipeline:

1. Load a YAML hypothesis config.
2. Generate no-lookahead feature profiles from BTC 1h bars.
3. Generate forward event-return labels for 1h, 4h, 12h, 24h, and 48h.
4. Assign walk-forward style folds.
5. Analyze overall, direction, fold, regime, horizon, and tail dependency distributions.
6. Evaluate a hypothesis gate with fixed thresholds.
7. Generate a research-only skeleton only when the hypothesis passes.
8. Always write paper/live safety status as `LOCKED` / `FROZEN`.
9. Provide a stable data contract for static HTML reporting.

The compression-to-expansion implementation is the first lab-backed hypothesis. The lab must remain reusable for the future liquidation-shock recovery hypothesis.

## Planned Artifacts

- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/run_manifest.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/feature_profile.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/event_table.csv`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/compression_expansion_event_table.csv`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/distribution_report.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/compression_expansion_distribution_report.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/hypothesis_decision.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/compression_expansion_hypothesis_decision.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/paper_live_safety_status.json`
- `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/test_results.json`
- `reports/quantstation_vnext_btc_compression_expansion_hypothesis_20260516T122000Z_compression_expansion.html`
- `docs/reports/quantstation_vnext_btc_compression_expansion_hypothesis_20260516T122000Z_compression_expansion.html`

## Files Allowed For This Sprint

- `quant_us/research/btc_hypothesis_lab.py`
- `configs/btc/hypotheses/compression_expansion_breakout_v0.yaml`
- `scripts/research/run_btc_hypothesis_lab.py`
- `scripts/research/evaluate_btc_hypothesis.py`
- `scripts/reports/generate_btc_hypothesis_lab_html.py`
- New docs under `docs/research/`
- New static report copies under `reports/` and `docs/reports/`
- New artifacts under `artifacts/btc_hypothesis/20260516T122000Z_compression_expansion/`
- New focused tests under `tests/research/` and `tests/reports/`
- Optional research skeleton only if gate passes: `configs/btc/hypotheses/compression_expansion_breakout_v1_skeleton.yaml`

## Files And Modules Forbidden For This Sprint

- No broker adapter edits.
- No live runtime edits.
- No paper runtime edits.
- No OMS or execution risk path edits.
- No `perp_dual_trend` v5/v6 config or code restoration.
- No low-vol uptrend rescue or retuning.
- No order-flow entry trigger.
- No signal-equity gate use.
- No ordinary PF gate substitution.
- No gate threshold lowering.
- No `paper_ready`, `live_ready`, or `live_enabled` state.
- No hard-coded local absolute paths.

## Compression-to-Expansion Feature Contract

- Compression features use only current and historical bars:
  - realized volatility percentile
  - high-low range percentile
  - ATR percentile
  - band-width percentile
  - prior compression box from bars before the breakout bar
- Breakout features:
  - upside breakout is a close above the prior box high after compression.
  - downside breakout is a close below the prior box low after compression.
  - breakout is confirmed on the closed bar.
  - future event returns are labels only and start after the breakout event.
- Direction outputs:
  - `upside_breakout`
  - `downside_breakout`
  - `combined_directional`

## Hypothesis Gate Thresholds

- `active_event_count >= 200`
- `selected_direction_event_count >= 80`
- `event_PF_proxy >= 1.15`
- `fold_pass_rate >= 0.75`
- fold-level `event_PF_proxy > 1.05`
- `median_return >= 0`
- top 5 positive contribution `<= 0.35`
- at least 2 horizons with `event_PF_proxy >= 1.10`
- no-lookahead status must pass

Allowed decisions:

- `hypothesis_rejected`
- `hypothesis_needs_more_data`
- `hypothesis_passed_for_strategy_skeleton`

## Test Command

```bash
PYTHONPATH=. pytest \
  tests/research/test_btc_hypothesis_lab_config_schema.py \
  tests/research/test_btc_hypothesis_lab_no_lookahead.py \
  tests/research/test_compression_expansion_feature_profile.py \
  tests/research/test_compression_expansion_distribution_report.py \
  tests/research/test_compression_expansion_hypothesis_gate.py \
  tests/research/test_compression_expansion_tail_dependency.py \
  tests/research/test_compression_expansion_strategy_skeleton_guard.py \
  tests/research/test_hypothesis_lab_safety_status.py \
  tests/reports/test_hypothesis_lab_html_generation.py \
  -q
```

## Paper / Live Safety Rules

- `candidate_passed_internal_gate = 0`
- `paper_queue = LOCKED`
- `live = FROZEN`
- `real_broker_api_called = false`
- `real_orders_created = false`
- No automatic paper review queue creation.
- No broker or live runtime imports in research code.

## Risk Points

- Forward returns must be labels only.
- Prior breakout box must be built from bars before the breakout bar; no future high/low confirmation.
- Downside breakout can be analyzed as a label, but this sprint cannot create a paper/live short strategy.
- A high overall PF proxy is insufficient if folds, direction, tail dependency, or multi-horizon checks fail.
- Results must stay research-only even when a skeleton is generated.
