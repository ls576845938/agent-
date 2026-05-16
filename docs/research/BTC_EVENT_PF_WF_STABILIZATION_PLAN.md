# BTC Event-PF Bridge and Walk-Forward Stabilization Plan

## Step 0 Repository State

- Branch: `main`
- Starting commit: `e396e10`
- Dirty files inventory at sprint start: none (`git status --short` returned no paths)
- Applicable project rules: `./AGENTS.md`
- Current canonical source run: `artifacts/btc_canonical/20260516T061000Z_attribution/`
- Current HTML report: `docs/reports/quantstation_vnext_btc_alpha_attribution_report.html`
- Current safety state from canonical evidence: `PAPER QUEUE: LOCKED`, `LIVE: FROZEN`, `candidate_passed_internal_gate: 0`

## AGENTS.md Constraints Applied

- Strategies must not call brokers directly.
- Strategies may emit only `Signal`, `OrderIntent`, or `TargetPosition` style research outputs.
- All orders must pass the risk engine outside strategy code.
- All PnL used for gate decisions must come from fills and ledger.
- Every backtest must generate a manifest.
- Every experiment must record data version, strategy version, params, cost model, slippage model, and commit hash.
- No Sharpe optimization before cost, slippage, and walk-forward robustness validation.
- No live trading code before paper gate passes.
- No future function and no look-ahead bias.
- Do not rewrite unrelated files or silently catch trading/accounting errors.

## Current Actual Entry Points

- BTC canonical evidence: `scripts/run_btc_canonical_attribution.py`
- Canonical evidence helpers: `quant_us/research/btc_canonical.py`
- BTC regime and v2 hardening helpers: `quant_us/research/btc_alpha_hardening.py`
- BTC SQLite data loader: `backend/app/services/market_data.py` via `load_market_frame(source="sqlite", symbol="BTCUSDT", interval="1h", db_path="data/market_data.sqlite")`
- Event-ledger backtest: `quant_us/backtest/crypto_event.py` via `run_crypto_event_backtest`
- Cost stress scenarios: `quant_us/backtest/crypto_event.py` through `CRYPTO_COST_STRESS_SCENARIOS`
- Walk-forward helper: `quant_us/research/btc_canonical.py::rolling_walk_forward_for_signal`
- Regime gate helper: `quant_us/research/btc_canonical.py::regime_report_from_trades`
- PBO / DSR helpers: `quant_us/research/btc_canonical.py::simplified_pbo` and `simplified_dsr`
- Promotion gate: `quant_us/research/btc_canonical.py::evaluate_canonical_gate`
- Paper review lock: `quant_us/research/btc_canonical.py::decide_paper_queue_from_canonical`
- Previous attribution HTML generator: `scripts/generate_btc_attribution_html_report.py`
- Existing reports directory: `docs/reports/`
- New requested report directory: `reports/`

## Current Evidence Baseline

Source run: `20260516T061000Z_attribution`

| Strategy | PF | event_PF | Sharpe | MDD | Turnover | WF Pass | Regime Pass | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `btc_perp_dual_trend` | 1.2617 | 1.0141 | 0.336 | -6.08% | 308% | 75% | 50% | `candidate_gate_failed` |
| `btc_perp_dual_trend_v2` | 1.5993 | 1.0189 | 0.490 | -7.91% | 186% | 100% | 50% | `candidate_gate_failed` |
| `btc_perp_dual_trend_v3` | 2.0498 | 1.0176 | 0.422 | -8.53% | 105% | 50% | 100% | `candidate_gate_failed` |

Primary gap: v3 trade-level PF is high, but event-ledger PF is only 1.0176. Promotion must continue to use `event_PF`, not ordinary trade PF.

## Files Allowed For This Sprint

- New plan and research docs under `docs/research/`
- New static report under `reports/`
- New research scripts under `scripts/research/`
- New report generator under `scripts/reports/`
- New research-only helper module under `quant_us/research/`
- New v4 research config under `configs/btc/alpha_stabilization/`
- New artifacts under `artifacts/btc_canonical/{run_id}/`
- New focused tests under `tests/research/` and `tests/reports/`

## Files And Modules Not Allowed For This Sprint

- No live runtime implementation edits.
- No paper runtime implementation edits except read-only safety evidence if already present.
- No broker adapter edits.
- No OMS/Risk live execution path edits.
- No real order submission paths.
- No gate threshold lowering.
- No changes that make signal equity eligible for promotion.
- No unrelated frontend or dashboard expansion.
- No Qlib, PyPortfolioOpt, or large dependency integration.

## Planned Run ID And Artifact Paths

Planned run id: `20260516T080000Z_eventpf_wf`

Artifacts:

- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/event_pf_bridge_report.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/event_pf_bridge_table.csv`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/walk_forward_fold_attribution.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/walk_forward_fold_table.csv`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/exit_surgery_ablation_report.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/side_regime_ablation_report.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/orderflow_keepout_confirmation.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/btc_perp_dual_trend_v4_eventpf_wf_results.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/btc_perp_dual_trend_v4_eventpf_wf_gate_input.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/btc_perp_dual_trend_v4_eventpf_wf_decision.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/promotion_decision.json`
- `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/paper_live_safety_status.json`

HTML:

- `reports/quantstation_vnext_btc_eventpf_wf_stabilization_20260516T080000Z_eventpf_wf.html`

Config:

- `configs/btc/alpha_stabilization/btc_perp_dual_trend_v4_eventpf_wf.yaml`

## Gate Thresholds

- `event_PF >= 1.15`
- `PF >= 1.15`
- `annual_turnover <= 10.0`
- `walk_forward_pass_rate >= 0.80`
- `regime_pass_rate >= 0.75`
- `cost_stress_base == pass`
- `cost_stress_harsh` must not be catastrophic.
- `no_lookahead_status == pass`
- `event_ledger_status == pass`
- `PBO <= 0.50`
- `DSR >= 0.10`
- Evidence bridge must show no material inconsistency.

## Implementation Sequence

1. Event-PF bridge: add `scripts/research/build_btc_event_pf_bridge.py` and research helpers to explain ordinary PF, trade PF, fill/event PF, cashflow PF, cost and aggregation deltas.
2. WF fold attribution: add `scripts/research/build_btc_wf_fold_attribution.py` and fold-level attribution with fail reasons, side/regime/exit/cost contribution.
3. Exit surgery ablation: evaluate no-same-bar flip, flat-then-confirm reverse, cooldowns, reverse regime alignment, exit hysteresis, and combined surgery.
4. Side/regime ablation: evaluate long bias, short restrictions, high-vol/trending-down blocks, and expansion-confirmed short rules.
5. Order-flow keep-out confirmation: keep order-flow diagnostic unless event PF and WF both improve without unacceptable fill activity.
6. v4 candidate: write exactly one final config and canonical result for `btc_perp_dual_trend_v4_eventpf_wf`.
7. Gate and safety: write promotion decision and paper/live safety artifact. Maximum allowed status is `paper_review_pending`; live remains frozen.
8. HTML report: generate self-contained static HTML under `reports/`.
9. Tests: add focused schema, gate, no-side-effect, no-lookahead, and HTML generation tests; run the core test command.

## Test Command

Planned focused test command:

```bash
PYTHONPATH=. pytest \
  tests/research/test_event_pf_bridge_report_schema.py \
  tests/research/test_event_pf_gate_uses_event_pf.py \
  tests/research/test_pf_metric_definition_no_confusion.py \
  tests/research/test_walk_forward_fold_attribution_schema.py \
  tests/research/test_signal_flip_exit_surgery.py \
  tests/research/test_side_regime_ablation_no_lookahead.py \
  tests/research/test_orderflow_not_forced.py \
  tests/research/test_v4_gate_thresholds.py \
  tests/research/test_paper_queue_locked_v4_failed.py \
  tests/research/test_live_frozen_no_side_effects.py \
  tests/reports/test_html_eventpf_wf_report_generation.py \
  -q
```

## Risk Points

- A high ordinary trade PF can be an aggregation artifact and must not override event-ledger PF.
- Reducing `signal_flip_exit` may also remove profitable recovery trades; ablation must verify event PF and WF, not only trade PF.
- Restricting shorts can improve stability but may reduce expansion-window contribution.
- Fold pass rate can improve by reducing activity too far; v4 must not pass through trivial near-zero trading.
- Any evidence inconsistency keeps research invalid and paper queue locked.
- Existing ignored manifests and data files may be large; this sprint must produce compact, reproducible JSON/CSV artifacts.
