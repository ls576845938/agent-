# BTC Exchange Info Metadata Policy

`exchange_info.json` records the current Binance USD-M BTCUSDT trading-rule snapshot used by the BTC perpetual bundle.

Allowed sources:

- `public_rest_response`: direct public capture from `/fapi/v1/exchangeInfo`.
- `manual_offline_capture`: manual public capture from an accessible environment or official public response, with provenance.
- `official_public_rest_capture`: equivalent public capture produced by a controlled public-data process.

Minimum required fields:

- `source_method`, `source_endpoint` or source URL, and `captured_at`.
- BTCUSDT `raw_symbol_info`.
- Explicit provenance flags: `api_key_used=false`, `private_endpoint_used=false`, and `auth_headers_present=false`.
- `operator_note` for manual offline captures.
- `contractType=PERPETUAL`.
- `status=TRADING` or a documented historical status.
- `PRICE_FILTER.tickSize`.
- `LOT_SIZE.stepSize` and `LOT_SIZE.minQty`.
- `MIN_NOTIONAL.notional` or `MIN_NOTIONAL.minNotional`.
- `pricePrecision` and `quantityPrecision` as diagnostics only.

Rules:

- `pricePrecision` and `quantityPrecision` must not replace `tickSize` or `stepSize`.
- Manual captures can verify current exchange rules, but `historical_rule_lineage_available=false` unless historical rules are actually supplied.
- Manual captures without an operator note, or with any API-key/private-endpoint flag set, must fail verification.
- Missing filters keep `exchange_info_verified=false`.
- Exchange rules must not be inferred from price data.

Manual capture request:

```text
docs/btc_exchange_info_manual_capture_request.md
```

Current sprint status:

- `exchange_info.json` remains missing because public REST returned HTTP 451 and no manual offline capture was provided.
- Preflight and provider verification remain fail-closed.
