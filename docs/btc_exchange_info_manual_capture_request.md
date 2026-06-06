# BTC Public Metadata Manual Capture Request

Use this only in an environment that can access the Binance public USD-M Futures API. This request does not need an API key and must not call private, account, position, or order endpoints.

## Requests

```bash
curl -sS -o exchange_info_raw.json -w "%{http_code}\n" \
  "https://fapi.binance.com/fapi/v1/exchangeInfo" \
  > exchange_info_http_status.txt

curl -sS -o funding_info_raw.json -w "%{http_code}\n" \
  "https://fapi.binance.com/fapi/v1/fundingInfo" \
  > funding_info_http_status.txt

cat exchange_info_http_status.txt
sha256sum exchange_info_raw.json
wc -c exchange_info_raw.json
cat funding_info_http_status.txt
sha256sum funding_info_raw.json
wc -c funding_info_raw.json
```

Allowed endpoints:

```text
GET /fapi/v1/exchangeInfo
GET /fapi/v1/fundingInfo
```

Forbidden endpoint families:

```text
account
order
position
listenKey
userData
leverage
margin
transfer
broker
income
balance
```

## Atomic Bundle Import

Place `exchange_info_raw.json` and `funding_info_raw.json` as two distinct files somewhere outside the selected bundle first, then run the dry-run import from the repo. The importer rejects reused raw paths and raw capture files located under the bundle directory.
Both HTTP status sidecars must contain `200`; HTTP 451 or any other non-200 response is not acceptable manual capture evidence.

If this repo is running from an allowed network environment, use the repo-local capture wrapper first. It calls only the two public endpoints above, writes raw files under `artifacts/`, and does not write into the selected data bundle:

```bash
make capture-btc-public-metadata
```

When both endpoint responses are captured, the report at `artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json` includes ready-to-run `dry_run_import_command` and `apply_import_command` values under `raw_capture_artifacts`.

```bash
make dry-run-btc-manual-metadata-import \
  EXCHANGE_INFO_RAW=exchange_info_raw.json \
  FUNDING_INFO_RAW=funding_info_raw.json \
  BTC_MANUAL_METADATA_CAPTURED_AT=2026-05-22T00:00:00Z
```

Only after the dry-run import verifies both contracts, run the write-capable import:

```bash
make apply-btc-manual-metadata-import \
  EXCHANGE_INFO_RAW=exchange_info_raw.json \
  FUNDING_INFO_RAW=funding_info_raw.json \
  BTC_MANUAL_METADATA_CAPTURED_AT=2026-05-22T00:00:00Z
```

The importer stages both overlays in a temporary directory, verifies both contracts, and writes nothing if either side fails. On success it writes:

```text
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/exchange_info.json
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/funding_info.json
data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1/btc_perpetual_bundle_manifest.json
```

The dry-run writes `artifacts/btc_data_status/latest/btc_manual_metadata_dry_run_report.json`; the write-capable import writes `artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json`. The authoritative import report records accept/reject status, normalized UTC `captured_at`, raw input file path, byte size, and SHA-256 for both `exchange_info_raw.json` and `funding_info_raw.json`, plus `exchange_info_output_sha256` and `funding_info_output_sha256` for the generated selected-bundle overlays.
The importer also refuses to write if the target `bundle_dir` or `bundle_id` does not match `configs/data/btc_perpetual_sources.yaml`.
Keep the `sha256sum` and `wc -c` output with the capture notes so the import report provenance can be checked against the raw files.
Use the actual UTC capture time for `BTC_MANUAL_METADATA_CAPTURED_AT`; the importer rejects missing, non-UTC, or future timestamps.

## Minimum Accepted BTCUSDT Fields

The generated `exchange_info.json` must contain:

- `source_method=manual_offline_capture`
- `source_endpoint=/fapi/v1/exchangeInfo`
- `source_url_or_doc`
- `captured_at`
- `symbol=BTCUSDT`
- `api_key_used=false`
- `private_endpoint_used=false`
- `auth_headers_present=false`
- `operator_note`
- `raw_symbol_info.symbol=BTCUSDT`
- `raw_symbol_info.contractType=PERPETUAL`
- `raw_symbol_info.status=TRADING`
- `PRICE_FILTER.tickSize`
- `LOT_SIZE.minQty`
- `LOT_SIZE.stepSize`
- `MIN_NOTIONAL.notional` or `MIN_NOTIONAL.minNotional`
- `pricePrecision` and `quantityPrecision`
- `historical_rule_lineage_available=false`

`pricePrecision` and `quantityPrecision` are diagnostics only. They must not be used as replacements for tick size or step size.

An empty raw array response is acceptable for `/fapi/v1/fundingInfo`; it means no symbol-specific funding cap/floor/interval adjustment was returned. The endpoint response still must be captured and imported before `funding_info_verified=true`.
If the array is non-empty, every item must be a JSON object.
Every non-empty fundingInfo row must include `symbol`; if a `BTCUSDT` row is present, it must include parseable `fundingIntervalHours`, `adjustedFundingRateCap`, and `adjustedFundingRateFloor`.
An error object with `code`/`msg` or `error` fields is not a valid fundingInfo endpoint response and will be rejected.

## Verification

After the atomic import, run:

```bash
python3 scripts/build_btc_exchange_info_overlay.py \
  --bundle-dir data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --validate-only

python3 scripts/build_btc_funding_info_overlay.py \
  --bundle-dir data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --validate-only

python3 scripts/build_btc_perpetual_data_bundle_manifest.py \
  --bundle-dir data/external/btc_perpetual/binance_usdm/bundles/btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --bundle-id btc_usdm_binance_btcusdt_20240101_20260512_v1 \
  --source-type production \
  --promotion-clean-allowed \
  --license-note "Binance public USD-M Futures market data local archive and manual public metadata capture."

make validate-btc-public-data-bundle
make validate-btc-public-data-bundle-strict
```

Passing metadata verification does not imply alpha pass. Compression remains attribution/archive until a separate strategy evidence contract changes that state.
