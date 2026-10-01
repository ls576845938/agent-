# BTC-V3-OKX-L2-HISTORY-PIPELINE-01

## Status

Follow-up ticket specification only. No collector, network call, data
publication, scheduler, secret access, private endpoint, or order endpoint is
implemented or run by the exporter ticket.

## Owner and boundary

- Code owner: `btc_developer`.
- Data publication owner: `data_steward`.
- Shared wiring owner: `integrator` when a shared entrypoint change is needed.
- Reuse the existing BTC L2 capture, depth observation, replay, and evidence
  contracts; do not create a second collection stack.

## Required immutable inputs

- public OKX order-book snapshot and incremental update records;
- instrument, venue, channel/depth, event time, snapshot time, available time,
  sequence identifiers, checksum where supplied, and receipt clock metadata;
- source HEAD, collector version, immutable data version, capture window,
  partition inventory, and per-file plus aggregate SHA-256;
- a data-steward attestation describing authorization, gaps, clock drift,
  two-sided coverage, and immutable URI/version.

No field may be guessed from ingestion order or backfilled after observation.

## Required outputs

- partitioned, non-database immutable L2 table files;
- `btc_okx_l2_history_attestation.json`;
- a consumer result accepted by the BTC DataReady contract;
- inputs suitable for the existing
  `btc_okx_l2_depth_observation_batch_report.json` and
  `btc_depth_slippage_fill_mapping_report.json` builders.

Every output binds data version, run ID, source HEAD, parameters, lineage, input
hashes, output hashes, UTC event/snapshot/available times, and an explicit
promotion-evidence classification.

## Acceptance

- public-only fake/recorded-fixture contracts pass without network access;
- sequence reset, duplicate, out-of-order update, gap, stale snapshot,
  one-sided book, zero liquidity, clock drift, checksum failure, reconnect, and
  partition-boundary cases fail closed or are explicitly classified;
- replay is deterministic and never consumes a snapshot unavailable at the
  decision time;
- two-sided depth coverage and common time window are complete;
- immutable publication resolves through `shared_data.py` with verified hashes;
- the BTC DataReady consumer accepts the manifest and attestation;
- fixture and diagnostic outputs are explicitly not promotion evidence;
- missing, stale, wrong-HEAD, partial, or hash-mismatched evidence cannot retire
  the historical depth-fill blocker.

All promotion, paper, live, private, order, broker, withdraw, demo,
paper-queue, real-order, network, and secret flags remain false unless a later
independent authorization explicitly changes them.
