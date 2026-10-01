# BTC-V3-DEMO-OMS-RUNTIME-HARDENING-01

## Scope

BTC-only hardening of the existing `okx_demo_paper_runtime`. No shared schema,
shared entrypoint, US/CN module, exchange endpoint, secret, data, paper queue, or
live/Demo order was accessed.

## Delivered boundary

- Production runtime storage defaults outside the Git worktree and remains
  explicitly configurable; tests use temporary directories.
- The append-only event log uses stable idempotency keys, monotonic sequence
  numbers, previous-event hashes, event hashes, flush and fsync.
- The independently atomic checkpoint records its matching event sequence/hash.
- Recovery replays events after the checkpoint and fails closed on corruption,
  hash/sequence drift, conflicting duplicates, checkpoint drift, or a truncated
  tail. An unclean active runtime remains cancel-only.
- Ledger UoW commits order, fill, position, cash and funding evidence in one
  durable envelope and refuses missing mark, index, liquidation-buffer or venue
  rule context.
- The private WS contract accepts recorded fixtures only and has no authorized
  connection path. Existing BTC exchange-runtime replay remains the owner of
  public WS reconnect, sequence, gapfill, clock-drift, outage and cancel-only
  evaluation.

## Verification

- Ticket-owned contracts: 15 passed.
- Related BTC OMS/exchange regressions: 27 passed.
- Covered crash/restart, truncated log, duplicate/conflicting idempotency,
  lifecycle states, out-of-order/hash-chain failure, incomplete ledger/risk
  context, reconciliation/clock/connection failure, and recorded-only private
  WS behavior.

## Gate classification

- `quality_checked=true`
- `research_ready=false`
- `backtest_ready=false`
- `promotion_evidence_ready=false`
- `paper_ready=false`
- `live_ready=false`

Actual Demo/private/order execution is outside this Goal and remains blocked.
This delivery is implementation and fixture evidence only.
