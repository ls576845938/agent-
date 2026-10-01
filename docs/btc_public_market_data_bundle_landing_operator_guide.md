# BTC Public Market Data Bundle Landing Operator Guide

This sprint lands BTCUSDT USD-M perpetual public market data into a local bundle. It is not a strategy optimization sprint.

## Landing Modes

`local_archive_import` is the preferred mode for bulk history. Download or prepare public archive files outside the repo, place them under `data/external/btc_perpetual/binance_usdm/bundles/<bundle_id>/`, then generate a manifest.

`public_rest_fetch` is an explicit tool mode for public REST supplement data. It is dry-run by default, requires `--allow-network --execute`, and also requires config flags `allow_public_rest_fetch=true` and `allow_network=true`.

## Bundle Directory

Required files:
- `btc_perpetual_bundle_manifest.json`
- `klines_1h.csv`
- `klines_4h.csv`
- `klines_1d.csv`
- `mark_price_klines_1h.csv`
- `premium_index_klines_1h.csv`
- `funding_rate.csv`
- `funding_info.json`
- `exchange_info.json`

Diagnostic files:
- `open_interest_hist_1h.csv`
- `open_interest_current.json`
- `agg_trades.csv`
- `liquidation_snapshots.csv`

## Manifest And Selection

Generate the manifest with:

```bash
python3 scripts/build_btc_perpetual_data_bundle_manifest.py \
  --bundle-dir data/external/btc_perpetual/binance_usdm/bundles/<bundle_id> \
  --bundle-id <bundle_id> \
  --source-type production \
  --license-note "<source and license note>"
```

Enable a real bundle only by setting `configs/data/btc_perpetual_sources.yaml`:

```yaml
providers:
  binance_usdm:
    enabled: true
    selected_bundle_id: <bundle_id>
    promotion_clean_allowed: true
```

## Validation

Normal CI mode can pass without a bundle if fail-closed artifacts are correct:

```bash
make validate-btc-public-data-bundle
```

Strict mode fails when no selected bundle is ready for preflight:

```bash
make validate-btc-public-data-bundle-strict
```

Review these artifacts:
- `artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json`
- `artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json`
- `artifacts/btc_data_status/latest/btc_data_status_report.json`
- `artifacts/btc_cost_model/latest/btc_cost_model_report.json`
- `artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json`
- `artifacts/btc_research_registry/research_registry.json`

Preflight pass means the selected bundle is structurally verifiable. It does not mean `perpetual_evidence_ready=true`.

`perpetual_evidence_ready=true` means data/cost source requirements can enter evidence review. It does not mean the alpha passed. Compression remains attribution/archive and cannot enter paper.

## 2026-05-19 Landing Run

Bundle id:

```text
btc_usdm_binance_btcusdt_20240101_20260512_v1
```

Sample range:

```text
2024-01-01T00:00:00Z to 2026-05-12T00:00:00Z
```

This run used `local_archive_import` from Binance Vision public USD-M archive files for:

- `klines_1h.csv`
- `klines_4h.csv`
- `klines_1d.csv`
- `mark_price_klines_1h.csv`
- `premium_index_klines_1h.csv`
- `funding_rate.csv`

The REST collector dry run remained no-network. An explicit public REST attempt against `fapi` returned HTTP 451 in this environment, so `funding_info.json` and `exchange_info.json` were not downloaded. No API key was used, no private/account/order endpoint was used, and downloaded archive files remain under the gitignored bundle directory.

Current validation result:

- `preflight_pass=false`
- `perpetual_evidence_ready=false`
- `funding_payment_in_ledger=true`
- `klines_verified=true`
- `mark_price_klines_verified=true`
- `premium_index_klines_verified=true`
- `funding_rate_verified=true`
- `funding_info_verified=false`
- `exchange_info_verified=false`

The active blockers are expected until endpoint-backed `funding_info.json`, `exchange_info.json`, and exchange rules are supplied and verified. Funding-rate sample coverage and funding-adjusted ledger replay are now present, but inferred fundingInfo is still not endpoint verification. Compression is archived; it must not be retested, sent to paper, or resurrected without a new hypothesis contract.

## Preflight Repair Notes

The preflight repair sprint initially could not close the May 2026 funding-rate gap from public archives. A later validated manual public fundingRate patch extended `funding_rate.csv` through `2026-05-12T00:00:00Z`.

`funding_info.json` may be supplied by a public `/fapi/v1/fundingInfo` response, a manual offline public capture, or a clearly marked inference from `funding_rate.csv` spacing. Inference can document `funding_interval_hours`, but it must not be labeled as endpoint verification.

`exchange_info.json` must be a public or manual public capture of BTCUSDT USD-M current trading rules. It needs `PRICE_FILTER.tickSize`, `LOT_SIZE.stepSize`, `LOT_SIZE.minQty`, and `MIN_NOTIONAL`. `pricePrecision` and `quantityPrecision` are not substitutes for tick or step size.

Use the manual capture request in `docs/btc_exchange_info_manual_capture_request.md` when `/fapi/v1/exchangeInfo` is reachable from another environment. The resulting overlay must explicitly set `api_key_used=false`, `private_endpoint_used=false`, and `auth_headers_present=false`.

HTTP 451 should stay visible as a blocker. Do not fill missing metadata from memory, private endpoints, API keys, or inferred price data.

## Funding Rate Coverage Repair Notes

The funding coverage repair task added a first-class gap report:

```text
artifacts/btc_data_status/latest/btc_funding_rate_gap_report.json
```

The current gap report shows 34 expected funding events missing from `2026-05-01T00:00:00Z` through `2026-05-12T00:00:00Z`. The inferred funding interval is 8 hours with high confidence, but the local file still ends at `2026-04-30T16:00:00Z`.

Archive diagnostics are recorded in:

```text
artifacts/btc_data_status/latest/btc_funding_rate_archive_repair_report.json
```

The May 2026 repair attempted one monthly URL and twelve daily URLs. They all returned HTTP 404 and added zero rows. The explicit public REST fallback attempted only `/fapi/v1/fundingRate`, used no API key, used no private endpoint, and returned HTTP 451 in this environment:

```text
artifacts/btc_data_status/latest/btc_funding_rate_public_rest_fetch_report.json
```

If a funding-rate patch is needed, create and validate a manual offline public patch as described in:

```text
docs/btc_funding_rate_manual_patch_operator_guide.md
```

The manual funding patch has now repaired the May 2026 funding coverage gap, and funding payments are replayed into a funding-adjusted net ledger artifact. Funding coverage repair alone does not make `perpetual_evidence_ready=true` while endpoint-backed fundingInfo and `exchange_info.json` are missing. It also does not change compression lifecycle state; compression is archived and must not be retested or sent to paper from this task.
