# BTC Funding Rate Manual Patch Operator Guide

## Purpose

Use this guide only when the local Binance Vision archive and explicit public REST fetch cannot supply the missing BTCUSDT USD-M perpetual funding-rate rows.

The patch source must be the public endpoint:

```text
/fapi/v1/fundingRate
```

Do not use API keys, private/account/order endpoints, or account-derived data.

## Expected Gap

Current missing range:

```text
2026-05-01T00:00:00Z through 2026-05-12T00:00:00Z
```

Expected rows at 8-hour spacing: 34.

Check the latest canonical gap report before creating a patch:

```bash
python3 scripts/build_btc_funding_rate_gap_report.py
jq '.expected_missing_funding_times' artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json
```

## Patch Files

Place patch files under the selected bundle:

```text
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/patches/
```

Required files:

```text
funding_rate_patch_20260501_20260512.csv
funding_rate_patch_20260501_20260512.metadata.json
```

CSV columns:

```text
timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id
```

`markPrice` may be empty only if the public response omits it. `fundingTime` must be a UTC millisecond timestamp.

## Metadata

The metadata file must include:

```json
{
  "schema_version": "btc_funding_rate_patch_metadata_v1",
  "patch_id": "funding_rate_patch_20260501_20260512",
  "csv_filename": "funding_rate_patch_20260501_20260512.csv",
  "csv_sha256": "<64 lowercase hex sha256>",
  "source_method": "manual_offline_public_rest_capture",
  "source_base_url": "https://fapi.binance.com",
  "source_endpoint": "/fapi/v1/fundingRate",
  "symbol": "BTCUSDT",
  "requested_start": "2026-05-01T00:00:00Z",
  "requested_end": "2026-05-12T00:00:00Z",
  "startTime": 1777593600000,
  "endTime": 1778544000000,
  "captured_at": "2026-05-19T00:00:00Z",
  "operator_note": "Captured from public REST in an accessible environment. No API key.",
  "api_key_used": false,
  "private_endpoint_used": false,
  "auth_headers_present": false,
  "record_count": 34,
  "expected_row_count": 34,
  "expected_first_fundingTime": 1777593600000,
  "expected_last_fundingTime": 1778544000000,
  "funding_interval_hours": 8,
  "target_bundle_id": "btc_usdm_binance_btcusdt_20240101_20260512_v1",
  "target_file": "funding_rate.csv",
  "merge_key": "fundingTime",
  "merge_policy": "fail_on_duplicate_fundingTime",
  "operator": "manual",
  "created_at": "2026-05-19T00:00:00Z",
  "requests": [],
  "blockers": []
}
```

Compute the checksum with:

```bash
sha256sum funding_rate_patch_20260501_20260512.csv
```

The metadata key is `csv_sha256`. Do not use a legacy `sha256` key.

## Validate

Run:

```bash
python3 scripts/validate_btc_funding_rate_patch.py
```

Validation fails on:

- API key usage
- private endpoint usage
- wrong endpoint
- wrong symbol
- missing or duplicated `fundingTime`
- non-monotonic time
- rows outside the expected gap
- non-numeric `fundingRate`
- checksum mismatch
- record-count mismatch
- empty patch
- expected funding times do not exactly match the 34 missing events from `btc_funding_rate_gap_report.json`
- non-finite `fundingRate`

## Merge

After validation passes:

```bash
python3 scripts/merge_btc_funding_rate_patch.py
python3 scripts/build_btc_funding_rate_gap_report.py
python3 scripts/build_btc_perpetual_data_bundle_manifest.py \
  --bundle-dir data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --bundle-id btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --source-type production \
  --promotion-clean-allowed \
  --license-note "Binance public USD-M archive plus manual offline public fundingRate patch."
```

The merge writes an atomic replacement, preserves sorted ascending `fundingTime`, rejects overlaps, and logs rows added.

The merge also rejects duplicate `fundingTime` values already present in the existing `funding_rate.csv`, creates a local backup before replacement when it actually writes, and verifies the post-write row order/count.

## Post-Merge Checks

Run:

```bash
make validate-btc-public-data-bundle
make validate-btc-public-data-bundle-strict
```

Even if funding coverage becomes complete, `exchange_info.json` is still required for perpetual provider verification. Funding coverage repair does not imply alpha pass, candidate pass, paper review, or live readiness.
