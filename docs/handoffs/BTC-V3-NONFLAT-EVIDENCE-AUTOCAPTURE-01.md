# BTC-V3-NONFLAT-EVIDENCE-AUTOCAPTURE-01

## Scope

BTC-only observe/replay implementation. It does not change signal thresholds,
parameters, holdouts, shared contracts, exchange adapters or execution
authorization.

## Delivered contract

- Flat heartbeat returns `waiting_for_natural_non_flat_sample` without creating
  order or fill evidence.
- A naturally occurring non-zero target automatically builds the ordered chain:
  Signal/Forecast → TargetPosition → cost/risk decision → OrderIntent → OMS
  lifecycle → Fill → position/cash/funding ledger → liquidation buffer →
  depth-fill mapping → reconciliation → audit DAG/replay.
- Every node carries the same run, strategy, immutable data and source-HEAD
  binding. Payload, dependency and node hashes are validated together with
  ordinal and dependency order.
- Risk rejection stops before OrderIntent. Partial fills and reconciliation
  failures remain fail-closed.
- Explicit zero and non-zero funding values are preserved; a real funding
  observation and private-WS observation remain independent blockers.
- Replay consumes only the supplied snapshot and rejects `latest`, `current`
  and `live` pointers.
- Fixture, diagnostic and historical samples can prove capability only and can
  never become promotion evidence.

## Gate classification

- `quality_checked=true` after contracts pass.
- `research_ready=false`
- `backtest_ready=false`
- `promotion_evidence_ready=false` on current main because no authorized
  current natural non-flat/private-WS/funding observation was produced.
- paper/live/private/order/withdraw remain false.
