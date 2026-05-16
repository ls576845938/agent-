# Runtime Boundary Audit

Run date: 2026-05-16

## Scope

This audit records runtime boundaries for the BTC Alpha Attribution and
Evidence Unification Sprint. The sprint is research-only and must not trigger
paper or live trading.

## Active Research Entrypoints

- `scripts/run_btc_canonical_attribution.py`
  - reads BTC SQLite data
  - runs event-ledger backtests
  - writes canonical artifacts
  - does not import live runtime
  - does not call broker APIs
- `quant_us/research/btc_canonical.py`
  - builds canonical reports
  - builds trade attribution from ledger fills
  - evaluates canonical gate inputs
- `quant_us/backtest/crypto_event.py::run_crypto_event_backtest`
  - event-driven replay path
  - PnL source is `ledger_fills`

## Review-Only Entrypoints

- `backend/app/services/paper_review.py`
- `quant_us/research/paper_review_candidate.py`
- `quant_us/research/paper_review_bridge.py`
- `quant_us/research/evidence_registry.py`
- `quant_us/research/automation/promotion_gate.py`
- `backend/app/services/research_gate.py`
- CLI readiness/report commands in `quant_us/cli.py`

These can inspect evidence and report readiness, but this sprint must not use
them to start paper or live execution.

## Paper / Live Safety Shells

Observed safety-oriented modules:

- `quant_us/live/runtime.py`
- `quant_us/live/paper_runtime.py`
- `quant_us/live/paper_orchestrator.py`
- `quant_us/live/shadow_live.py`
- `quant_us/live/live_order_submission_gate.py`
- `quant_us/live/live_pilot_*`
- `backend/app/live/vnpy_adapter.py`

These are not modified by this sprint. They remain outside the active research
path.

## Inactive For This Sprint

- real broker submission
- paper auto-start
- live readiness promotion
- live order execution
- one-shot live pilot execution
- VN.py live adapter execution

## Safety Conclusion

Current canonical promotion decision:

```text
PAPER QUEUE: LOCKED
LIVE: FROZEN
```

No strategy is allowed to become `paper_ready`, `live_ready`, or
`live_enabled` in this sprint. Any future paper transition must come from
manual review of canonical evidence and can only reach `paper_review_pending`.
