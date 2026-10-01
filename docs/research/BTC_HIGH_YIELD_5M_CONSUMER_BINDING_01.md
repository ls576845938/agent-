# BTC high-yield 5m consumer binding

## Scope and status

This document records the bounded, offline research-data consumer change for
`BTC-HIGH-YIELD-5M-CONSUMER-BINDING-01`.  It does not register a strategy,
create a paper/live candidate, or unlock promotion.  All broker, private,
order, paper, live, transfer, and withdraw flags remain `false`.

The consumer is research-only.  The data pointer can remain
`consumer_readiness=blocked` when its blockers are exactly the three governed
research blockers below; that state is preserved in provenance and is never
upgraded by this consumer.

## Immutable source selection

The default selector is the committed object
`.agent/runtime_manifests/btc-market-data-v1.json` at the current `HEAD`.
The selector resolves the committed manifest Git spec:

`HEAD:.agent/data_manifests/btc-market-data-sqlite-snapshot/btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1.json`

The qcv2r1 binding observed for this producer run is:

| binding | value |
| --- | --- |
| dataset id | `btc-market-data-sqlite-snapshot` |
| dataset version | `btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1` |
| Git manifest SHA-256 | `ad6981dc7c8d5124b594ff4212192e5e94ff87c965bd3e3470f247da56efa9ee` |
| physical manifest SHA-256 | `0ee09f51f53608c16c9306334c5e4fbe7ede86f948c625ba91bbd36d7f327068` |
| aggregate inventory SHA-256 | `cfe0fe05e59e0fef4919a601926563750f94a27dfb08f84f093e6440270385f4` |
| selected file | `exchange=binance_spot/symbol=BTCUSDT/interval=5m/part-00000.jsonl` |
| selected file SHA-256 | `76e8654cd11fc40b873b30d4a6fa8b2ed618256721e3b7840e180bd0f0359c08` |
| selected rows | `278928` |
| coverage | `2024-01-01T00:04:59.999000Z` – `2026-08-26T11:59:59.999000Z` (physical close events) |
| consumer blockers | `btc_execution_latency_model_missing`, `btc_queue_model_missing`, `btc_kline_dataready_not_promotion_evidence` |

The selector, manifest, resolver, physical manifest, every declared file hash,
and the existing Kline attestation/payload contract are checked before the
5m file is read.  Unknown blockers, identity/version/path/coverage/hash,
attestation, guardrail, or payload errors fail closed.

## Time and payload semantics

Only the manifest-declared Binance Spot `BTCUSDT` 5m JSONL partition is loaded.
Rows must be finalized, finite and positive OHLC values with non-negative
volume, valid UTC `event_time`/`available_time`, and strict 5m event cadence.
The physical event is the close event.  The frame index is derived as:

`derived_open = event_time - 5 minutes + 1 millisecond`

For qcv2r1 this yields an index from `2024-01-01T00:00:00Z` through
`2026-08-26T11:55:00Z`.  Physical close and available timestamps stay in the
provenance fields; they are not relabelled as the frame open time.

## Legacy compatibility

`--market-db-path` and `--manifest` default to `None`.  Supplying either
requires supplying both, and selects an explicitly named read-only legacy
SQLite path.  The selector path is never replaced by a missing, mutable,
staging, glob, or SQLite fallback.

## Safety and readiness boundary

The report records the selected dataset/version/coverage and all hash bindings,
`access_mode=immutable_shared_data_jsonl`, `research_only=true`, and
`public_network_called=false`.  The research GA remains subject to its
existing unseen-holdout, cost, latency/queue, funding, mark/index, liquidation,
and manual review blockers.  No search was run for this consumer smoke and no
promotion artifact was rebuilt.
