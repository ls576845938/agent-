# BTC Funding Rate Coverage Repair Task

## Scope

This task repairs only the BTCUSDT USD-M perpetual `funding_rate.csv` sample coverage gap for the bundle:

```text
btc_usdm_binance_btcusdt_20240101_20260512_v1
```

It does not repair `exchange_info.json`, does not run a strategy retest, and does not change paper/live gates.

## Current Coverage

The target sample range is:

```text
2024-01-01T00:00:00Z to 2026-05-12T00:00:00Z
```

The local `funding_rate.csv` currently has 2587 records:

```text
first fundingTime: 2024-01-01T00:00:00Z
last fundingTime:  2026-05-12T00:00:00Z
```

The funding interval inferred from local `fundingTime` spacing is 8 hours with high confidence. The previous 34-event gap from `2026-05-01T00:00:00Z` through `2026-05-12T00:00:00Z` has been repaired by a validated manual public fundingRate patch.

The canonical machine-readable status is:

```text
artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json
```

## Archive Diagnostics

Archive repair attempts are recorded in:

```text
artifacts/btc_data_status/latest/btc_funding_rate_archive_repair_report.json
```

The repair script records every attempted monthly and daily URL, HTTP status, and error type. A `404` is recorded as `not_found`; HTTP `451` is recorded separately as network or regional unavailability; URL construction errors are recorded as `path_generation_error`.

The archive diagnostics remain useful provenance: the archive repair attempt added zero rows, and the later manual patch path supplied the missing May 2026 rows.

## Public REST Fallback

The only permitted REST endpoint for this task is:

```text
/fapi/v1/fundingRate
```

The fetch helper defaults to dry-run and requires explicit `--allow-network --execute`. It does not accept API keys, does not read API-key environment variables, and rejects private/account/order-style endpoints.

This run attempted the public REST fallback and received HTTP 451. The report is:

```text
artifacts/btc_data_status/latest/btc_funding_rate_public_rest_fetch_report.json
```

No patch rows were generated.

## Manual Patch Path

If public archive and REST are unavailable, the next repair path is a manual offline public REST capture from an accessible environment. The operator should create:

```text
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/patches/funding_rate_patch_20260501_20260512.csv
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/patches/funding_rate_patch_20260501_20260512.metadata.json
```

The patch is validated before merge with:

```bash
python3 scripts/validate_btc_funding_rate_patch.py
```

The validator now checks the patch against the canonical 34 expected missing funding events from:

```text
artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json
```

The metadata checksum field is `csv_sha256`; a legacy `sha256` key is rejected.

The merge path rejects duplicate `fundingTime`, non-monotonic timestamps, bad checksums, bad record counts, API-key usage, private endpoint usage, and rows outside the expected gap.

The merge path only writes after validation passes. It rejects overlap with the existing file, rejects duplicate funding times already present in the existing file, writes through a temporary file, creates a local backup, and verifies the post-write row order and count.

## Funding Info Boundary

`funding_info.json` currently comes from `inferred_from_funding_rate_spacing`.

That inference can make `funding_interval_hours=8.0` usable for diagnostics, but it is not endpoint verification. It must not be reported as `funding_info_endpoint_verified=true`.

Funding coverage repair also does not make `perpetual_evidence_ready=true` while `exchange_info.json` remains missing.

## Strategy Boundary

Funding coverage repair is not an alpha pass. It does not change:

- `candidate_passed_internal_gate=0`
- `paper_queue_status=locked`
- `live_status=frozen`
- `current_candidates=[]`
- `compression_expansion_breakout=archived/archive_only`
