# BTC Promotion Gate Canonical Rules

Run date: 2026-05-16

## Rule

BTC attribution sprint promotion decisions must read only canonical evidence:

```text
artifacts/btc_canonical/{run_id}/{strategy_id}/canonical_backtest_report.json
artifacts/btc_canonical/{run_id}/{strategy_id}/gate_inputs.json
```

Legacy evidence, strict evidence, optimization reports, signal-equity reports,
frontend summaries, and hand-written metrics are diagnostic only.

## Required Canonical Markers

The single-strategy report must contain:

```json
{
  "schema_version": "btc_canonical_backtest_report_v1",
  "evidence_source": "canonical_event_ledger"
}
```

Gate code rejects any report that does not have those markers.

## Gate Inputs

The gate reads:

- `metrics.profit_factor`
- `metrics.event_profit_factor`
- `metrics.annual_turnover`
- `metrics.walk_forward_pass_rate`
- `metrics.regime_pass_rate`
- `metrics.max_drawdown`
- `metrics.pbo`
- `metrics.dsr`
- `cost_stress_base.passed`
- `cost_stress_harsh.survives`
- `no_lookahead_status.status`
- `event_ledger_status.status`
- `diagnostics.signal_equity_diagnostic_only`

Signal equity can be saved only under diagnostics. It is not a gate input.

## Thresholds

- PF >= `1.15`
- event PF >= `1.15`
- annual turnover <= `10.0`
- walk-forward pass rate >= `0.80`
- regime pass rate >= `0.75`
- max drawdown >= `-15.0%`
- PBO <= `0.50`
- DSR >= `0.10`
- base cost stress passes
- harsh cost stress survives
- no-lookahead passes
- event-ledger status passes

## Allowed States

- `research_failed`
- `research_candidate`
- `candidate_gate_failed`
- `candidate_passed_internal_gate`
- `paper_review_pending`

## Forbidden States

- `paper_ready`
- `live_ready`
- `live_enabled`

## Paper Review

Paper review can unlock only when 1 to 3 candidates pass all canonical gates.
Even then:

- max state is `paper_review_pending`
- `paper_auto_start` remains `false`
- no paper runtime starts
- live remains frozen

Current canonical run:

```text
artifacts/btc_canonical/20260516T061000Z_attribution/promotion_decision.json
```

Current result: `paper_review_queue_locked=true`, `live_frozen=true`.
