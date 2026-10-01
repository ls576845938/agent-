# BTC-V3-OKX-L2-IMMUTABLE-EXPORT-01

## Scope and ceiling

This ticket adds a BTC-owned, offline, fail-closed exporter for already-landed
OKX public WebSocket `books` capture segments. It reuses
`fetch_btc_okx_public_ws_l2_raw_capture.py` filenames and capture manifests.
It does not collect data, access private/order/live endpoints, read secrets,
publish shared data, write a database, enqueue paper orders, or unlock
promotion. The maximum result is `quality_checked`.

## Input and replay contract

Each repeated segment input requires:

- the segment directory;
- the expected SHA-256 of `okx_public_ws_l2_raw_messages.jsonl`;
- the expected SHA-256 of
  `okx_public_ws_l2_raw_capture_manifest.json`.

The manifest must attest public-only OKX `BTC-USDT-SWAP` `books` capture with
all API-key, private, order, and broker flags false. The exporter verifies input
hashes and source stability before committing the output directory.

Replay begins in `waiting_for_snapshot` for each segment and connection.
Reconnect resets the book. Any update before the new snapshot, sequence gap,
duplicate, out-of-order sequence, invalid nonzero checksum, invalid clock
ordering, excessive receipt lag, zero-liquidity/one-sided/crossed book, or
partition-boundary continuation quarantines the state and blocks the complete
export. No partial destination is retained.

## Output and blockers

Valid fixture input emits deterministic JSONL under
`venue=okx/instrument_id=BTC-USDT-SWAP/date=YYYY-MM-DD/` and
`btc_okx_l2_dataready_attestation.json`. The attestation binds segment hashes,
file hashes, aggregate hashes, sequence/checksum/clock/two-sided coverage,
coverage and common end, and all false safety guardrails. Its dataset identity
matches the existing DataReady consumer:
`btc-okx-timestamp-aligned-public-l2-history`.

The CLI is `scripts/build_btc_okx_l2_immutable_export.py`. It accepts only
local segment paths, hashes, output identity, UTC cutoff, and validation
thresholds; it exposes no network or publication option.

The v2 exporter consumes the complete capture timing envelope. Observed
history is the sum of validated capture durations minus measured reconnect
windows, not `common_end - coverage_start`. Segment capture windows must be
exactly contiguous and their first sequence must continue the prior segment;
overlap, gap, or rollback blocks the destination. Manifest gap/connection
counts are reconciled to raw connection transitions. Recovered reconnects
produce explicit `gap_windows` and reduce two-sided temporal coverage;
unrecovered reconnects block.

A short fixture retains:

- `btc_okx_l2_history_below_30_natural_days`;
- `btc_execution_latency_model_missing`;
- `btc_queue_model_missing`;
- `btc_okx_l2_natural_execution_observation_missing`.

Accordingly `research_ready=false`, `backtest_ready=false`,
`promotion_evidence_ready=false`, `paper=false`, and `live=false`.
