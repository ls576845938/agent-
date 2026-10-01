# BTC-V3-DATAREADY-CONSUMER-01

## Outcome

This Goal adds a fail-closed BTC consumer for data-steward-owned immutable
market-data publications. It does not collect, publish or mutate market data.

The consumer recognizes:

- `.agent/runtime_manifests/btc-market-data-v1.json`;
- immutable dataset `btc-market-data-sqlite-snapshot`;
- immutable dataset `btc-okx-timestamp-aligned-public-l2-history`.

It validates the shared manifest schema, `data_steward` producer identity,
producer commit availability, readiness and quality status, immutable
version/URI, aggregate inventory SHA-256, file sizes and per-file SHA-256.
Physical data is resolved read-only through `shared_data.py` contracts.

## Data attestations

The K-line snapshot must contain
`btc_kline_dataready_attestation.json` with:

- explicit UTC `event_time` and `available_time`;
- PIT enforcement;
- finalized versus in-progress rows, with in-progress rows excluded;
- interval coverage, missing/duplicate counts, common end and freshness.

The OKX L2 history must contain
`btc_okx_l2_dataready_attestation.json` with:

- OKX venue and UTC event/snapshot time fields;
- sequence validation, gap and recovery accounting;
- event/snapshot ordering;
- two-sided coverage;
- clock-offset attestation and freshness.

## Current-HEAD consumption result

The committed report is
`docs/handoffs/BTC-V3-DATAREADY-CONSUMER-01-consumption-report.json`.

Current main contains the mutable runtime pointer, but its immutable
publication remains `awaiting_data_steward_publication`. No committed K-line
snapshot manifest, OKX timestamp-aligned L2 manifest or attestation exists.
The real report therefore remains blocked with:

- `immutable_snapshot_not_published`;
- `data_steward_attestation_required`;
- `immutable_manifest_not_published`;
- `okx_timestamp_aligned_l2_manifest_not_published`.

No local `data/market_data.sqlite` bytes were read. No `data/`, `artifacts/` or
shared-data version was written.

## Readiness and safety

Fixture validation proves the consumer implementation is
`quality_checked`. The real current-HEAD consumption report remains:

- `quality_checked=false`;
- `research_ready=false`;
- `backtest_ready=false`;
- `promotion_evidence_ready=false`.

An immutable data manifest is not strategy promotion evidence. Promotion still
requires the current-HEAD strategy, risk, OMS, fill/ledger, audit and gate
chain. Paper, live, private, order and withdraw permissions remain false.

## Owner and next action

Owner: `data_steward`.

Publish both immutable datasets with their attestations through
`shared_data.py`, commit the generated manifests, and emit a DataReady handoff.
An integrator must merge those manifests before this consumer may report
`quality_checked`.

## Validation

- Ticket-owned consumer contracts: `8 passed`.
- Shared-data, BTC PIT, exchange runtime and shared-boundary regression:
  `19 passed`.
- The complete related regression selection produced `20 passed, 2 failed`.
  Both failures are classified as `external_evidence_missing`: the sparse
  worktree does not contain the pre-existing
  `artifacts/btc_research_registry/research_registry.json` and
  `artifacts/global_research_registry/research_registry.json`. They were not
  fabricated or rebuilt by this Goal.
- The real report builder intentionally exits blocked while immutable
  manifests are absent; its JSON output is schema-valid and its required
  blockers are asserted by contract tests.
