from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info
from scripts.fetch_btc_binance_usdm_public_data import build_fetch_plan, _write_json_payload


def test_landing_modes_are_documented_in_config() -> None:
    config = Path("configs/data/btc_perpetual_sources.yaml").read_text(encoding="utf-8")

    assert "landing_mode: local_archive_import" in config
    assert "allow_public_rest_fetch: false" in config
    assert "allow_network: false" in config
    assert "allow_private_endpoints: false" in config
    assert "allow_order_endpoints: false" in config


def test_public_rest_fetch_plan_uses_public_market_data_only() -> None:
    plan = build_fetch_plan(
        bundle_id="dryrun",
        symbol="BTCUSDT",
        interval="1h",
        start_time_ms=1_700_000_000_000,
        end_time_ms=1_700_003_600_000,
    )

    names = {item["name"] for item in plan}
    assert names == {
        "klines",
        "mark_price_klines",
        "premium_index_klines",
        "funding_rate",
        "funding_info",
        "exchange_info",
        "open_interest",
        "open_interest_hist",
    }
    assert all("order" not in str(item).lower() for item in plan)
    assert all("account" not in str(item).lower() for item in plan)


def test_public_rest_fetch_plan_requires_paired_window() -> None:
    with pytest.raises(Exception):
        # The collector layer rejects one-sided start/end windows before any network call.
        from quant_crypto.data.binance_usdm_public import build_public_url, PUBLIC_ENDPOINTS

        build_public_url(PUBLIC_ENDPOINTS["klines"], {"symbol": "BTCUSDT", "interval": "1h", "startTime": 1})


def test_public_rest_exchange_info_capture_writes_verifier_ready_provenance(tmp_path: Path) -> None:
    path = tmp_path / "exchange_info.json"
    _write_json_payload(
        path,
        "exchange_info",
        {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "contractType": "PERPETUAL",
                    "status": "TRADING",
                    "pricePrecision": 2,
                    "quantityPrecision": 3,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                        {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "100"},
                    ],
                }
            ]
        },
        url="https://fapi.binance.com/fapi/v1/exchangeInfo?symbol=BTCUSDT",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    status = evaluate_exchange_info(path)

    assert payload["source_method"] == "public_rest_response"
    assert payload["api_key_used"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["auth_headers_present"] is False
    assert payload["raw_symbol_info"]["symbols"][0]["symbol"] == "BTCUSDT"
    assert status["exchange_info_verified"] is True


def test_public_rest_funding_info_capture_writes_endpoint_provenance(tmp_path: Path) -> None:
    path = tmp_path / "funding_info.json"
    _write_json_payload(
        path,
        "funding_info",
        [],
        url="https://fapi.binance.com/fapi/v1/fundingInfo",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["source_method"] == "public_rest_response"
    assert payload["source_endpoint"] == "/fapi/v1/fundingInfo"
    assert payload["endpoint_response_available"] is True
    assert payload["raw_response"] == []
    assert payload["api_key_used"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["auth_headers_present"] is False
