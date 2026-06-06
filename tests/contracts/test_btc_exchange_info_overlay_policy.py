from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from quant_crypto.data.binance_usdm_metadata import evaluate_exchange_info
from scripts.build_btc_exchange_info_overlay import build_exchange_info_overlay


SCHEMA = Path("schemas/btc_exchange_info_overlay.schema.json")


def test_manual_exchange_info_overlay_can_verify_current_rules_without_historical_lineage(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))
    path = _write_payload(tmp_path, payload)
    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is True
    assert status["source_method"] == "manual_offline_capture"
    assert status["symbol"] == "BTCUSDT"
    assert status["contractType"] == "PERPETUAL"
    assert status["status"] == "TRADING"
    assert status["tickSize"] == 0.1
    assert status["stepSize"] == 0.001
    assert status["minNotional"] == 100.0
    assert status["historical_rule_lineage_available"] is False
    assert payload["blockers"] == []
    assert status["blockers"] == []


def test_exchange_info_overlay_schema_requires_btcusdt_rule_shape() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["properties"]["raw_symbol_info"]["$ref"] == "#/$defs/btcusdt_symbol_info"


def test_exchange_info_overlay_schema_rejects_missing_required_symbol_fields() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = build_exchange_info_overlay(
        source_payload={**_valid_symbol_info(), "contractType": "CURRENT_QUARTER"},
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_exchange_info_overlay_schema_rejects_non_utc_capture_timestamp() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T08:00:00+08:00",
        operator_note="manual public exchangeInfo capture",
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_exchange_info_overlay_schema_rejects_blank_operator_note() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="   ",
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_exchange_info_overlay_schema_rejects_blank_source_url_or_doc() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="   ",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_exchange_info_overlay_schema_requires_allowed_public_endpoint_provenance() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="operator saved a file from the browser",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_exchange_info_overlay_schema_rejects_missing_required_filters() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = build_exchange_info_overlay(
        source_payload={**_valid_symbol_info(), "filters": []},
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_exchange_info_overlay_schema_rejects_zero_or_non_numeric_filters() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    for filters in (
        [
            {"filterType": "PRICE_FILTER", "tickSize": "0"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"},
        ],
        [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "minQty": "bad", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"},
        ],
        [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "0.000"},
        ],
    ):
        payload = build_exchange_info_overlay(
            source_payload={**_valid_symbol_info(), "filters": filters},
            source_method="manual_offline_capture",
            source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
            captured_at="2026-05-19T00:00:00Z",
            operator_note="manual public exchangeInfo capture",
        )
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(payload, schema)


def test_exchange_info_missing_required_filters_fails(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload={**_valid_symbol_info(), "filters": []},
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    path = tmp_path / "exchange_info.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_tick_size_missing" in status["blockers"]
    assert "btc_exchange_info_step_size_missing" in status["blockers"]
    assert "btc_exchange_info_min_notional_missing" in status["blockers"]


def test_exchange_info_overlay_rejects_unknown_source_method() -> None:
    with pytest.raises(ValueError):
        build_exchange_info_overlay(
            source_payload=_valid_symbol_info(),
            source_method="inferred_from_price_data",
            source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
            captured_at="2026-05-19T00:00:00Z",
            operator_note="manual public exchangeInfo capture",
        )


def test_exchange_info_rejects_non_perpetual_or_non_trading_symbol(tmp_path: Path) -> None:
    symbol_info = {**_valid_symbol_info(), "contractType": "CURRENT_QUARTER", "status": "BREAK"}
    payload = build_exchange_info_overlay(
        source_payload=symbol_info,
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    path = tmp_path / "exchange_info.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_contract_type_not_perpetual" in status["blockers"]
    assert "btc_exchange_info_status_not_trading" in status["blockers"]


def test_exchange_info_does_not_use_precision_as_tick_or_step(tmp_path: Path) -> None:
    symbol_info = {
        key: value
        for key, value in _valid_symbol_info().items()
        if key != "filters"
    }
    payload = build_exchange_info_overlay(
        source_payload=symbol_info,
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    path = tmp_path / "exchange_info.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert status["pricePrecision"] == 2
    assert status["quantityPrecision"] == 3
    assert status["tickSize"] is None
    assert status["stepSize"] is None
    assert "btc_exchange_info_tick_size_missing" in status["blockers"]
    assert "btc_exchange_info_step_size_missing" in status["blockers"]


def test_exchange_info_requires_explicit_no_api_key_and_no_private_endpoint(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    payload["api_key_used"] = True
    payload["private_endpoint_used"] = True
    payload["auth_headers_present"] = True
    path = _write_payload(tmp_path, payload)

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_api_key_usage_not_explicitly_false" in status["blockers"]
    assert "btc_exchange_info_private_endpoint_usage_not_explicitly_false" in status["blockers"]
    assert "btc_exchange_info_auth_headers_not_explicitly_false" in status["blockers"]


def test_exchange_info_manual_capture_requires_operator_note(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    payload["operator_note"] = ""
    path = _write_payload(tmp_path, payload)

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_operator_note_missing" in status["blockers"]


def test_exchange_info_manual_capture_rejects_whitespace_operator_note(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    payload["operator_note"] = "   "
    path = _write_payload(tmp_path, payload)

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_operator_note_missing" in status["blockers"]


def test_exchange_info_manual_capture_rejects_whitespace_source_url_or_doc(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    payload["source_url_or_doc"] = "   "
    path = _write_payload(tmp_path, payload)

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_source_url_missing" in status["blockers"]


def test_exchange_info_manual_capture_requires_allowed_public_endpoint_provenance(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="operator saved a file from the browser",
        captured_at="2026-05-19T00:00:00Z",
        operator_note="manual public exchangeInfo capture",
    )
    path = _write_payload(tmp_path, payload)

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_source_endpoint_missing_or_invalid" in status["blockers"]


def test_exchange_info_requires_utc_capture_timestamp(tmp_path: Path) -> None:
    payload = build_exchange_info_overlay(
        source_payload=_valid_symbol_info(),
        source_method="manual_offline_capture",
        source_url_or_doc="offline capture from /fapi/v1/exchangeInfo",
        captured_at="2026-05-19T08:00:00+08:00",
        operator_note="manual public exchangeInfo capture",
    )
    path = _write_payload(tmp_path, payload)

    status = evaluate_exchange_info(path)

    assert status["exchange_info_verified"] is False
    assert "btc_exchange_info_captured_at_missing" in status["blockers"]


def test_exchange_info_overlay_cli_wraps_raw_public_exchange_info_response(tmp_path: Path) -> None:
    raw_path = tmp_path / "exchange_info_raw.json"
    raw_path.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    subprocess.check_call(
        [
            sys.executable,
            "scripts/build_btc_exchange_info_overlay.py",
            "--bundle-dir",
            str(bundle),
            "--input-json",
            str(raw_path),
            "--source-method",
            "manual_offline_capture",
            "--source-url-or-doc",
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            "--operator-note",
            "manual public exchangeInfo capture; no API key and no private endpoint",
            "--captured-at",
            "2026-05-22T00:00:00Z",
        ]
    )

    output = bundle / "exchange_info.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    status = evaluate_exchange_info(output)

    assert payload["api_key_used"] is False
    assert payload["private_endpoint_used"] is False
    assert payload["auth_headers_present"] is False
    assert payload["raw_symbol_info"]["symbol"] == "BTCUSDT"
    assert status["exchange_info_verified"] is True


def test_exchange_info_overlay_cli_rejects_non_standard_json_constants(tmp_path: Path) -> None:
    raw_path = tmp_path / "exchange_info_raw.json"
    raw_path.write_text('{"symbols":[{"symbol":"BTCUSDT","pricePrecision":NaN}]}', encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_btc_exchange_info_overlay.py",
            "--bundle-dir",
            str(bundle),
            "--input-json",
            str(raw_path),
            "--source-method",
            "manual_offline_capture",
            "--source-url-or-doc",
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            "--operator-note",
            "manual public exchangeInfo capture; no API key and no private endpoint",
            "--captured-at",
            "2026-05-22T00:00:00Z",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "invalid or non-standard" in result.stderr
    assert not (bundle / "exchange_info.json").exists()


def test_exchange_info_overlay_cli_requires_explicit_utc_capture_time_for_raw_input(tmp_path: Path) -> None:
    raw_path = tmp_path / "exchange_info_raw.json"
    raw_path.write_text(json.dumps({"symbols": [_valid_symbol_info()]}), encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_btc_exchange_info_overlay.py",
            "--bundle-dir",
            str(bundle),
            "--input-json",
            str(raw_path),
            "--source-method",
            "manual_offline_capture",
            "--source-url-or-doc",
            "https://fapi.binance.com/fapi/v1/exchangeInfo",
            "--operator-note",
            "manual public exchangeInfo capture; no API key and no private endpoint",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "captured_at is required" in result.stderr
    assert not (bundle / "exchange_info.json").exists()


def _valid_symbol_info() -> dict[str, object]:
    return {
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


def _write_payload(root: Path, payload: dict[str, object]) -> Path:
    path = root / "exchange_info.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
