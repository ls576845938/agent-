# BTC Perpetual Bundle Preflight Repair Sprint

This sprint repairs BTCUSDT USD-M perpetual bundle preflight and provider verification gaps only. It is not a strategy sprint, alpha sprint, retest, or paper/live unlock.

Completed:

- Added fundingInfo metadata overlay policy and builder.
- Added exchangeInfo metadata overlay policy and builder.
- Added strict current-rule validation for exchangeInfo filters.
- Added explicit funding interval inference from local `funding_rate.csv` spacing.
- Attempted public archive repair for May 2026 funding-rate coverage; no archive rows were available. A later validated manual public fundingRate patch repaired the coverage gap.
- Regenerated manifest, preflight, provider verification, funding ledger, cost model, candidate gate, and registries.

Current result:

- `funding_rate.csv` now ends at `2026-05-12T00:00:00Z`.
- `funding_info.json` is inferred-only; it is not endpoint verified.
- `exchange_info.json` remains missing.
- `preflight_pass=false`.
- `perpetual_evidence_ready=false`.
- `funding_payment_in_ledger=true` with a funding-adjusted net ledger artifact.
- `candidate_passed_internal_gate=0`.
- `paper_queue_status=locked`.
- `live_status=frozen`.

Safety notes:

- HTTP 451 from public REST is recorded as a blocker, not bypassed.
- Inferred funding interval is not treated as a verified fundingInfo endpoint response.
- Current exchangeInfo, if later supplied, will not be treated as historical rule lineage unless the source includes historical rules.
- Preflight pass would not imply alpha pass.
- Perpetual evidence readiness would not imply paper eligibility.
- `compression_expansion_breakout` is archived and remains paper/live locked.

Next step:

Capture endpoint-backed `fundingInfo` and manual public `exchangeInfo` metadata from an accessible environment. Do not retest or resurrect archived compression-expansion without a new hypothesis contract.
