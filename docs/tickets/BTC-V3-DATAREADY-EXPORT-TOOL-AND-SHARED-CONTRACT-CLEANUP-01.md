# BTC-V3-DATAREADY-EXPORT-TOOL-AND-SHARED-CONTRACT-CLEANUP-01

## Scope

This ticket delivers an offline, fail-closed BTC K-line exporter and retires the
stale US governance assertion that BTC and US trading contracts share Python
class identity. It does not collect market data, publish a shared-data version,
modify a real SQLite database, or authorize any execution runtime.

## Governed source

The only real-data input reviewed for this ticket is the validated committed
handoff
`published-btc-v3-dataready-immutable-publication-01-2780aa156`.
That handoff is blocked evidence. The current data-steward audit records source
SHA-256 `11278c46...`, 575,434,752 bytes, SQLite integrity `ok`, and 1,741,871
`market_klines` rows. The table persists `close_time`, `close_time_ms`,
`ingested_at`, and `updated_at`, but not explicit `event_time`,
`available_time`, or `is_finalized`. Its global common end is stale: Binance
4h/1d stop at 2026-05-11 and Coinbase 1m stops at 2024-01-03. The available L2
input is still a diagnostic single snapshot without sequence/gap/reconnect
history. No real payload is converted or represented as ready by this ticket.

## Export contract

`scripts/build_btc_kline_immutable_export.py` invokes the BTC-owned exporter in
`quant_crypto.data.immutable_kline_export`.

The exporter:

- opens a proven snapshot with SQLite `mode=ro&immutable=1` and `query_only`;
- verifies the caller-supplied source SHA-256, SQLite integrity, schema, source
  stability, UTC timestamps, PIT ordering, explicit finalized state, OHLCV,
  duplicates, interval continuity, common end, and freshness;
- preserves explicit `event_time`/`available_time`/`is_finalized` when present;
- for the current-main legacy table only, applies the already-governed PIT
  projection `event_time=available_time=close_time` and finalized iff
  `close_time <= generated_at`;
- excludes future/unclosed rows and attests `derived_from_close_time`;
- defaults to strict validation of every source partition;
- accepts a repeatable explicit required partition set only when every selected
  partition exists, and attests required/included/excluded partitions plus
  `not_in_required_partition_set` reasons;
- emits deterministic partitioned JSONL tables rather than a database payload;
- excludes in-progress rows and records their counts;
- binds output files to source lineage, current inputs, per-file SHA-256, and an
  aggregate inventory SHA-256 in
  `btc_kline_dataready_attestation.json`;
- stages output and publishes the destination directory only after all checks
  pass.

Input lacking either explicit PIT fields or the governed `close_time` contract
exits nonzero without an output directory. Missing required partitions, stale
required partitions, and malformed selection declarations also fail closed. A
successful fixture export is `quality_checked` only. Publication, consumption,
research, backtest, promotion, paper, and live decisions remain separate.

## Shared contract cleanup

The US adoption governance contract now records the integrated boundary:

- US retains `quant_us` domain types;
- BTC uses the single stable `quant_crypto.trading_contracts` identity in both
  full and official BTC sparse checkouts;
- compatibility is limited to wire enum values and dataclass field names;
- no BTC dependent on `quant_us` remains;
- the completed cleanup references
  `published-btc-v3-engineering-blocker-closure-01-6216788f`.

No `quant_us` runtime or shared enum/schema is changed.

## Readiness and remaining blockers

- `quality_checked`: eligible after the ticket-owned tests pass.
- `research_ready`: false.
- `backtest_ready`: false.
- `promotion_evidence_ready`: false.

Remaining owners and actions:

- `architect`: decide whether a declared fresh Binance 1m/5m/15m/1h subset can
  be used; this ticket does not make that readiness decision.
- `data_steward`: run the exporter against a proven immutable snapshot only
  after the required partition set is approved, then publish separately.
- `data_steward`: publish real timestamp-aligned OKX public L2 history and its
  attestation.
- `integrator`: forward-port the two commits from this older isolated branch
  onto the architect-approved current main and rerun the scoped contracts.

All promotion, paper, live, private, order, broker, withdraw, demo,
paper-queue, real-order, network, and secret flags remain false.
