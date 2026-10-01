# BTC Event-Return Attribution and Alpha Renewal Plan

## Step 0 Repository State

- Branch: `main`
- Starting commit: `147f689`
- Dirty files inventory at sprint start: none (`git status --short` returned no paths)
- Applicable project rules: `./AGENTS.md`
- Previous sprint run id: `20260516T080000Z_eventpf_wf`
- Previous sprint artifacts: `artifacts/btc_canonical/20260516T080000Z_eventpf_wf/`
- Previous sprint HTML: `reports/quantstation_vnext_btc_eventpf_wf_stabilization_20260516T080000Z_eventpf_wf.html`
- Previous delivery summary commit: `147f689 Add BTC event PF WF delivery summary HTML`
- `docs/alpha-radar-mvp-3-9-6-delivery-report.html`: not present and not tracked by git at sprint start. It had been an unrelated untracked file and was removed before this sprint.

## AGENTS.md Constraints Applied

- Strategy code must not call brokers directly.
- All PnL for gates must come from fills and ledger.
- Every backtest must generate a manifest.
- Every experiment must record data version, strategy version, params, cost model, slippage model, and commit hash.
- No future function and no look-ahead bias.
- No paper/live changes before gates.
- Do not silently catch trading/accounting errors.
- Add relevant tests for core research changes.

## Current Evidence Baseline

All BTC candidates remain below gate. Promotion continues to use event-ledger `event_PF`, not closed-trade PF.

| Strategy | PF | event_PF | Sharpe | MDD | Turnover | WF | Regime | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `btc_perp_dual_trend` | 1.2617 | 1.0141 | 0.3363 | -6.084% | 308% | 75% | 50% | failed |
| `btc_perp_dual_trend_v2` | 1.5993 | 1.0189 | 0.4901 | -7.9128% | 186% | 100% | 50% | failed |
| `btc_perp_dual_trend_v3` | 2.0498 | 1.0176 | 0.4216 | -8.5324% | 105% | 50% | 100% | failed |
| `btc_perp_dual_trend_v4_eventpf_wf` | 1.6314 | 1.0205 | 0.5146 | -7.8350% | 122% | 50% | 100% | failed |

## Run ID Rule

Run ids use UTC timestamp plus sprint suffix:

`YYYYMMDDTHHMMSSZ_eventreturn_alpha`

This sprint uses:

`20260516T100000Z_eventreturn_alpha`

## Planned Artifacts

- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/event_return_attribution.json`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/event_return_table.csv`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/terminal_exposure_audit.json`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/failed_fold_autopsy.json`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/alpha_renewal_decision.json`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/promotion_decision.json`
- `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/paper_live_safety_status.json`
- `reports/quantstation_vnext_btc_event_return_alpha_renewal_20260516T100000Z_eventreturn_alpha.html`

## Files Allowed For This Sprint

- New research helper module under `quant_us/research/`
- New scripts under `scripts/research/`
- New report generator under `scripts/reports/`
- New research docs under `docs/research/`
- New static HTML reports under `reports/` and `docs/reports/`
- New artifacts under `artifacts/btc_canonical/20260516T100000Z_eventreturn_alpha/`
- New focused tests under `tests/research/` and `tests/reports/`

## Files And Modules Not Allowed For This Sprint

- No broker adapters.
- No live runtime changes.
- No paper runtime changes.
- No OMS or live risk execution path edits.
- No gate threshold lowering.
- No signal-equity or closed-trade PF promotion use.
- No broad new strategy set.
- No order-flow entry trigger reintroduction.
- No hard-coded local absolute paths.
- No deletion of existing tests.

## Task Split

1. Event-return attribution: recover hourly ledger equity snapshots from event-ledger manifests and attribute event returns by fold, regime, side, exposure, holding age, cost bucket, and state.
2. Terminal exposure audit: compare `mark_to_market_at_end`, `force_flat_at_end`, and `closed_trades_only_diagnostic` without changing gate semantics.
3. Failed fold autopsy: isolate fold 3 and fold 4 event-return losses and decide whether failures share a stable, rule-fixable pattern.
4. Alpha renewal decision: continue with one v5 only if event-return evidence is stable; otherwise archive the perp dual trend line and create a small alpha hypothesis backlog.
5. Gate and safety: keep paper queue locked and live frozen unless canonical gate passes, which is not the expected default.
6. HTML report: produce self-contained diagnostic report.
7. QA: add focused tests and run the requested core test set.

## Paper / Live Safety Requirements

- `PAPER QUEUE` remains `LOCKED` unless a candidate passes all canonical gates.
- `LIVE` remains `FROZEN`.
- No real broker API calls.
- No real orders created.
- Maximum allowed state is `paper_review_pending`; forbidden states are `paper_ready`, `live_ready`, and `live_enabled`.

## Test Command

```bash
PYTHONPATH=. pytest \
  tests/research/test_event_return_attribution_schema.py \
  tests/research/test_event_pf_from_event_returns.py \
  tests/research/test_terminal_exposure_audit.py \
  tests/research/test_failed_fold_autopsy_schema.py \
  tests/research/test_alpha_renewal_decision.py \
  tests/research/test_v5_optional_generation_guard.py \
  tests/research/test_v5_gate_thresholds.py \
  tests/research/test_paper_queue_locked_eventreturn.py \
  tests/research/test_live_frozen_eventreturn_no_side_effects.py \
  tests/reports/test_event_return_html_generation.py \
  -q
```

## Risk Points

- Event-return observations are mark-to-market ledger equity returns, not closed trade PnL. The report must keep those definitions separate.
- Some event-return fields such as closed PnL, open PnL, and slippage are estimated from available manifests and fills; missing precision must be marked explicitly.
- Failed fold 3 and 4 may not share a stable pattern. If so, a v5 should not be generated.
- If terminal flattening materially changes event_PF, that is a policy question, not a permission to choose the most favorable metric.
- If evidence remains consistent but alpha is weak, the correct output is archiving this alpha line and preserving all artifacts.
