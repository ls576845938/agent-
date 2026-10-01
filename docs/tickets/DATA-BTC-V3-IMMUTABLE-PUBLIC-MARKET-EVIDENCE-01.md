# DATA-BTC-V3-IMMUTABLE-PUBLIC-MARKET-EVIDENCE-01

## Boundary

This data-steward ticket is based on
`311c5ec743dec6e4b6e4295bde41dad1710acf6e` and uses the planner-created
sparse worktree
`agent/data_steward/data-btc-v3-immutable-public-market-evidence-01`.
The first Git command returned `core.sparseCheckout=true`.

The Git touch set is limited to the new immutable dataset manifest, its
attestation, this receipt, and the append-only producer handoff. No Python,
application, strategy, portfolio/risk, OMS, ledger, backend, frontend,
shared schema, enum, resolver, SQLite, latest/current pointer, scheduler, or
runtime artifact is modified.

## Immutable publication

- Dataset: `btc-okx-v3-immutable-public-market-evidence`
- Version:
  `btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7`
- Storage:
  `datasets/btc-okx-v3-immutable-public-market-evidence/btc-okx-v3-public-btcusdt-20260727T075929750Z-src311c5ec7`
- Aggregate SHA-256:
  `1fcd9cc02adbaca7c77bf97a4af021deef231916bd7d650768af654756fe5d24`
- Files/bytes: `33` / `4092849`
- Readiness: `quality_checked`
- Quality: `pass_with_research_only_warnings`
- Promotion, paper, live, private, order, and paper-queue unlock: all false.

The immutable payload contains raw public metadata captures, REST market and
funding data, current open interest, timestamp-aligned REST trades/books,
server-time samples, capture reports, and their source manifests. Consumers
must resolve it through the committed shared-data manifest; the staging path
is not a deliverable.

## Coverage and quality

The public REST bundle covers `2026-06-27T00:00:00Z` through
`2026-07-27T00:00:00Z`. It contains 8,642 finalized 5-minute bars, 722
1-hour bars, and 91 funding events. Funding has no duplicate record IDs and
its maximum observed interval is 8 hours.

The timestamp-aligned REST preflight captured 20 samples over 87 seconds:
2,000 book-level rows and 2,000 trade rows. All 20 samples are two-sided,
non-crossed, and have positive bid and ask depth; no duplicate book record ID
was found. The rows expose timestamp, side, level, price, size, spread,
depth-notional, and order-count inputs suitable for research-only depth-fill
mapping diagnostics.

This is not sequence-valid WebSocket L2 evidence. The public WS collector
failed before connecting because `websocket-client` is unavailable. The REST
book endpoint exposes no exchange sequence/checksum, and the 87-second
preflight is not a 30-natural-day L2 observation. A single current
open-interest snapshot is not open-interest history. Five public server-time
samples selected an offset of `2588.239ms`, which exceeds the configured
threshold.

## Remaining blockers

- `btc_okx_websocket_client_dependency_missing`
- `real_timestamp_aligned_l2_missing`
- `btc_okx_l2_sequence_continuity_unverified`
- `l2_lt_30_natural_days`
- `btc_open_interest_history_not_verified_diagnostic_partial`
- `btc_okx_server_time_offset_exceeds_threshold`
- `manifest_data_schema_mismatch`
- `manifest_quality_status_not_pass`
- `l2_manifest_attestation_readiness_mismatch`
- `not_promotion_evidence`

The existing mutable runtime pointer still independently reports
`immutable_snapshot_not_published` and
`data_steward_attestation_required`; this ticket does not rewrite that
pointer or mislabel a public API bundle as a SQLite snapshot.

## Governance evidence

Read `AGENTS.md`, the knowledge README, non-negotiables, shared and
data-steward playbooks, data reliability/quality/schema rules, BTC perpetual
funding and crypto reference-price rules, and the public WebSocket gapfill
rules. Catalog hash:
`568cf9c4f4d96d1cff4d331f29b69ec40ad28b6c13156d542c586ef5d8314a11`.

Active pitfall IDs: `GOV-CONCURRENCY-001`, `GOV-DIRTY-001`,
`GOV-HANDOFF-001`, `GOV-PITFALL-001`, `GOV-ROOT-001`,
`GOV-STORAGE-001`, `QSYS-GATE-001`, `QSYS-SECURITY-001`,
`GOV-PROMPT-001`, and `GOV-WINDOWS-001`.

No raw pitfall log was read because no catalog source incident investigation
was required. Initial scoped dirty checks were clean. No other worktree's
uncommitted files were consumed or changed.
