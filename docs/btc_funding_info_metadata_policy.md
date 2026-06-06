# BTC Funding Info Metadata Policy

`funding_info.json` records the provenance of the Binance USD-M funding schedule metadata used by the local BTC perpetual bundle.

Allowed sources:

- `public_rest_response`: captured from `/fapi/v1/fundingInfo`. The response can be an empty array; Binance only returns symbols with adjusted caps, floors, or intervals, so a missing `BTCUSDT` row is not automatically a missing endpoint.
- `manual_offline_capture`: captured from an accessible public environment or official public response and written with `captured_at`, source URL, and operator note.
- `inferred_from_funding_rate_spacing`: derived from local `funding_rate.csv` event spacing. This may support an interval diagnostic, but it is not endpoint verification.

Verification rules:

- `endpoint_response_available=true` with a valid raw response can verify the endpoint even when `symbol_adjustment_record_present=false`.
- The valid raw `/fapi/v1/fundingInfo` response shape is an array; an empty array is allowed, and non-empty arrays must contain JSON objects.
- Non-empty endpoint rows must include `symbol`. If a `BTCUSDT` row is present, it must include parseable `fundingIntervalHours`, `adjustedFundingRateCap`, and `adjustedFundingRateFloor`; otherwise the endpoint response is treated as malformed instead of falling back to inferred spacing.
- Error bodies such as `{ "code": ..., "msg": ... }` or payloads with an `error` field are not valid endpoint responses and must not verify fundingInfo.
- If no BTCUSDT adjustment row exists, `funding_interval_hours` may be inferred from high-confidence `fundingTime` spacing.
- Inference confidence must be high and spacing must be stable.
- Funding-rate coverage must align to the bundle sample range.
- Inferred-only metadata must keep `funding_info_verified=false`; it cannot be presented as public endpoint verification.

Manual endpoint capture workflow:

```bash
curl -sS -o funding_info_raw.json -w "%{http_code}\n" \
  "https://fapi.binance.com/fapi/v1/fundingInfo" \
  > funding_info_http_status.txt

cat funding_info_http_status.txt
```

Then verify it together with the matching `exchange_info_raw.json` using the atomic metadata importer in dry-run mode. Keep the two raw capture files distinct and outside the selected bundle; the importer rejects reused raw paths and raw files located under the bundle directory.
The `exchangeInfo` and `fundingInfo` HTTP status sidecars must both contain `200`; a 451 body or any non-200 response remains incomplete evidence.

```bash
make dry-run-btc-manual-metadata-import \
  EXCHANGE_INFO_RAW=exchange_info_raw.json \
  FUNDING_INFO_RAW=funding_info_raw.json \
  BTC_MANUAL_METADATA_CAPTURED_AT=2026-05-22T00:00:00Z
```

Only after the dry-run verifies both metadata contracts, run the write-capable import:

```bash
make apply-btc-manual-metadata-import \
  EXCHANGE_INFO_RAW=exchange_info_raw.json \
  FUNDING_INFO_RAW=funding_info_raw.json \
  BTC_MANUAL_METADATA_CAPTURED_AT=2026-05-22T00:00:00Z
```

The importer writes nothing unless both `exchangeInfo` and `fundingInfo` verify in a staged directory, and it refuses targets that do not match the selected bundle in `configs/data/btc_perpetual_sources.yaml`. Use `scripts/build_btc_funding_info_overlay.py` only for low-level validation/debugging of the funding overlay contract.

The dry-run report is `artifacts/btc_data_status/latest/btc_manual_metadata_dry_run_report.json`; only the write-capable import writes `artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json`. The authoritative import report includes normalized UTC `captured_at`, raw input file path, byte size, and SHA-256 for both manual payloads, plus output SHA-256 values for the generated selected-bundle overlays so accepted and rejected imports remain auditable.
Use the actual UTC capture time for `BTC_MANUAL_METADATA_CAPTURED_AT`; the importer rejects missing, non-UTC, or future timestamps.

An empty raw response is acceptable for `/fapi/v1/fundingInfo`; it means no symbol-specific funding cap/floor/interval adjustment was returned. In that case BTCUSDT interval may still be inferred from high-confidence local `funding_rate.csv` spacing, but the endpoint response itself must be captured and wrapped before `funding_info_verified=true`.

Validate the selected bundle overlay:

```bash
python3 scripts/build_btc_funding_info_overlay.py \
  --bundle-dir data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --validate-only
```

Current sprint status:

- REST access to `fapi` returned HTTP 451 in this environment.
- `funding_info.json` was written as `inferred_from_funding_rate_spacing`.
- `funding_interval_hours=8` has high spacing confidence, but `endpoint_response_available=false`.
- Funding-rate coverage now aligns to the selected bundle sample through `2026-05-12T00:00:00Z`.
- `funding_info_verified=false` remains correct because inferred spacing is not endpoint verification.
