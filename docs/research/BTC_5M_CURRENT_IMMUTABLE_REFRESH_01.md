# BTC-5M-CURRENT-IMMUTABLE-REFRESH-01

## Scope and safety

- Base/current source head: `64e20af8867370d29cfbdb0d8798a78d9c3c5a95`.
- Producer role: `data_steward`; this is a public-market-data refresh only.
- Only Binance public spot klines were used (`https://api.binance.com/api/v3/klines`, with the existing public fallback path available to the refresh implementation).
- No credentials, private/order/live/broker/transfer/withdraw endpoint, paper queue, or promotion action was used.
- Mutable SQLite remains an external runtime compatibility source. Consumers must resolve the exact immutable manifest/version/hash below and must never fall back to mutable staging.

## Refresh and quality evidence

The external mutable source was refreshed under a task-owned single-writer lease. The first immutable-export attempt fail-closed because zero-byte `market_data.sqlite-wal` and `market_data.sqlite-shm` sidecars were present. After all refresh/read-only connections were confirmed closed, a normal SQLite `PRAGMA wal_checkpoint(TRUNCATE)` connection was closed; both sidecars disappeared naturally. No sidecar was force-deleted.

| interval | rows | first open (UTC) | latest open (UTC) | latest close (UTC) | gaps | duplicate keys | invalid OHLCV/UTC |
|---|---:|---|---|---|---:|---:|---:|
| 1m | 1,394,640 | 2024-01-01T00:00:00Z | 2026-08-26T11:59:00Z | 2026-08-26T11:59:59.999Z | 0 | 0 | 0 |
| 5m | 278,928 | 2024-01-01T00:00:00Z | 2026-08-26T11:55:00Z | 2026-08-26T11:59:59.999Z | 0 | 0 | 0 |
| 15m | 92,976 | 2024-01-01T00:00:00Z | 2026-08-26T11:45:00Z | 2026-08-26T11:59:59.999Z | 0 | 0 | 0 |
| 1h | 23,244 | 2024-01-01T00:00:00Z | 2026-08-26T11:00:00Z | 2026-08-26T11:59:59.999Z | 0 | 0 | 0 |

The 1h refresh wrote 582 rows and completed with no blockers. The short-interval refresh wrote 45,360 1m rows and deterministically resampled finalized 1m rows into 9,072 5m and 3,024 15m rows, with no in-progress tail consumed. The source SQLite SHA-256 is `40741d3929d3d337a784ff2a475148e68d6e3e7aaf944c34ed73d34eba6cfaea` (`595,976,192` bytes); the registered-main hardlink points to the same file identity.

## Immutable publication

- Dataset id: `btc-market-data-sqlite-snapshot`.
- Canonical dataset version: `btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1`.
- Canonical external storage: `D:\\vibe coding\\Obsidian\\量化系统\\shared-data\\datasets\\btc-market-data-sqlite-snapshot\\btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1`.
- Canonical Git manifest: `.agent/data_manifests/btc-market-data-sqlite-snapshot/btc-kline-binance-btcusdt-20260826T115959999Z-decimal18-v2-src40741d39-main64e20af8-qc2r1.json`.
- Canonical committed Git manifest SHA-256 (LF-normalized committed bytes): `ad6981dc7c8d5124b594ff4212192e5e94ff87c965bd3e3470f247da56defa9ee`.
- Canonical physical `_dataset_manifest.json` SHA-256: `0ee09f51f53608c16c9306334c5e4fbe7ede86f948c625ba91bbd36d7f327068` (kept separate from the Git manifest hash).
- Canonical physical attestation SHA-256: `37ca77e5f0e6075ed6ae084e44696585da24d589ec22429967e43efc66753ffa`.
- Canonical publisher aggregate inventory SHA-256: `cfe0fe05e59e0fef4919a601926563750f94a27dfb08f84f093e6440270385f4`; attestation table aggregate is `07e9fa576e03699687d0b5ee35c4216c9a9855204cd49c48c8e2ef1a0d92d4a5`.
- Canonical physical file count/bytes: `5 / 643,038,173` (four JSONL partitions plus the attestation).
- Source SHA-256 remains `40741d3929d3d337a784ff2a475148e68d6e3e7aaf944c34ed73d34eba6cfaea`; the attestation and publisher manifest both bind `producer_commit/source_head=33e30488c485bafbe020c16618cb3eb0578fb632`.
- Coverage is copied byte-for-byte from the qcv2r1 attestation: `2024-01-01T00:00:59.999000Z` through `2026-08-26T11:59:59.999000Z`. Publisher manifest coverage uses the same fixed-width representation, so the prior `.999Z`/`.999000Z` mismatch is closed.
- The exporter now canonicalizes every OHLCV number to finite decimal text with at most 18 places before writing JSONL; the full consumer kline attestation/payload scan returned `status=pass`, `blockers=[]`, `common_end=2026-08-26T11:59:59.999000Z`.

The earlier qcv1 publication remains immutable and non-selected. The first correction qcv2 publication is also immutable but orphaned/non-selected because its attestation carried the nonexistent source head `33e30488c912c8a7d95b0a1adf0f8ebea6c8c8b1`; it was never used as evidence or pointer target. The qcv2r1 version above is the sole canonical selector for this correction and was exported from the unchanged source SHA under the real committed exporter correction.

The runtime pointer is a logical selector only: it binds the exact qcv2r1 Git manifest path/version/hash, separate physical manifest hash, coverage end, and source hash. Its `consumer_readiness` remains `blocked`; immutable/read-only guardrails remain true and no promotion, paper, live, private, order, broker, or real-order capability is granted.

## Remaining research-only blockers

The refresh closes freshness and K-line integrity for the four required Binance spot partitions. The qcv2r1 kline contract is quality-checked and fully consumable, but overall DataReady remains fail-closed because the existing OKX L2 evidence/latency/queue requirements are not closed. Explicit blockers remain `btc_execution_latency_model_missing`, `btc_queue_model_missing`, and `btc_kline_dataready_not_promotion_evidence`; public K-lines do not prove queue position or order-to-fill latency. No promotion/paper/live gate was changed.

The qcv2r1 external publication is immutable and resolved with full file hashes. Consumers must resolve the Git-tracked qcv2r1 manifest and its exact physical version; mutable staging is never a fallback. The invalid qcv2 version remains retained solely for audit provenance and must not be selected.

## Reproducible commands

```text
py -3 scripts/research/run_btc_market_1h_data_refresh.py --market-db <external runtime DB> --output-dir <task root>/refresh-1h --execute-network --sleep-seconds 0.05 --fetch-limit 1000
py -3 scripts/research/run_btc_short_interval_data_refresh.py --market-db <external runtime DB> --output-dir <task root>/refresh-short --execute-network --sleep-seconds 0.05 --fetch-limit 1000
py -3 scripts/build_btc_kline_immutable_export.py --source <external runtime DB> --source-sha256 40741d3929d3d337a784ff2a475148e68d6e3e7aaf944c34ed73d34eba6cfaea --output-dir <task root>/immutable-export/<dataset version> --dataset-version <dataset version> --source-head 64e20af8867370d29cfbdb0d8798a78d9c3c5a95 --producer-role data_steward --now <UTC now> --freshness-sla-hours 48 --required-partition binance_spot:BTCUSDT:1m --required-partition binance_spot:BTCUSDT:5m --required-partition binance_spot:BTCUSDT:15m --required-partition binance_spot:BTCUSDT:1h
py -3 tools/agent_governance/shared_data.py publish --source <task root>/immutable-export/<dataset version> --shared-root D:\vibe coding\Obsidian\量化系统\shared-data --dataset-id btc-market-data-sqlite-snapshot --dataset-version <dataset version> --readiness-class quality_checked --quality-status pass --producer-role data_steward --schema-name btc_kline_dataready_attestation_v1
py -3 tools/agent_governance/shared_data.py resolve --manifest <published manifest> --shared-root D:\vibe coding\Obsidian\量化系统\shared-data
```
