from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from quant_crypto.data.binance_usdm_metadata import (
    build_funding_info_endpoint_overlay,
    build_inferred_funding_info_overlay,
    evaluate_funding_info,
)


SCHEMA = Path("schemas/btc_funding_info_overlay.schema.json")


def test_inferred_funding_info_overlay_is_schema_valid_but_not_endpoint_verified(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_inferred_funding_info_overlay(bundle_dir=tmp_path, captured_at="2026-05-19T00:00:00Z")

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert payload["source_method"] == "inferred_from_funding_rate_spacing"
    assert payload["endpoint_response_available"] is False
    assert payload["funding_interval_hours"] == 8.0
    assert payload["inference_confidence"] == "high"
    assert "btc_funding_info_endpoint_not_verified_inferred_only" in payload["blockers"]


def test_inferred_funding_info_overlay_default_capture_timestamp_is_schema_valid(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_inferred_funding_info_overlay(bundle_dir=tmp_path)

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert payload["captured_at"].endswith("Z")
    assert "+00:00" not in payload["captured_at"]


def test_funding_info_overlay_schema_requires_raw_response_array() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert schema["properties"]["raw_response"]["type"] == "array"
    assert schema["properties"]["raw_response"]["items"]["$ref"] == "#/$defs/funding_info_row"


def test_funding_info_overlay_schema_rejects_non_utc_capture_timestamp() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = _schema_valid_payload()
    payload["captured_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_funding_info_overlay_schema_rejects_blank_operator_note() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = _schema_valid_payload()
    payload["operator_note"] = "   "

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_funding_info_overlay_schema_rejects_blank_source_url_or_doc() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = _schema_valid_payload()
    payload["source_url_or_doc"] = "   "

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_funding_info_overlay_schema_rejects_malformed_endpoint_rows() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    base = _schema_valid_payload()

    for raw_response in (
        [{"adjustedFundingRateCap": "0.02500000"}],
        [{"symbol": "BTCUSDT"}],
        [
            {
                "symbol": "BTCUSDT",
                "adjustedFundingRateCap": "NaN",
                "adjustedFundingRateFloor": "-0.02500000",
                "fundingIntervalHours": 8,
            }
        ],
        [
            {
                "symbol": "BTCUSDT",
                "adjustedFundingRateCap": "0.02500000",
                "adjustedFundingRateFloor": "-0.02500000",
                "fundingIntervalHours": "Infinity",
            }
        ],
        [1],
    ):
        payload = {**base, "raw_response": raw_response}
        try:
            jsonschema.validate(payload, schema)
        except jsonschema.ValidationError:
            continue
        raise AssertionError(f"schema accepted malformed fundingInfo raw_response: {raw_response!r}")


def test_funding_info_overlay_schema_accepts_empty_and_valid_adjustment_rows() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    base = _schema_valid_payload()

    for raw_response in (
        [],
        [{"symbol": "ETHUSDT"}],
        [
            {
                "symbol": "BTCUSDT",
                "adjustedFundingRateCap": "0.02500000",
                "adjustedFundingRateFloor": "-0.02500000",
                "fundingIntervalHours": 8,
            }
        ],
    ):
        jsonschema.validate({**base, "raw_response": raw_response}, schema)


def test_empty_funding_info_endpoint_response_can_be_valid_without_btcusdt_row(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "funding_info.json").write_text(
        json.dumps(
            {
                "source_method": "public_rest_response",
                "source_endpoint": "/fapi/v1/fundingInfo",
                "captured_at": "2026-05-19T00:00:00Z",
                "symbol": "BTCUSDT",
                "endpoint_response_available": True,
                "raw_response": [],
                "symbol_adjustment_record_present": False,
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}

    status = evaluate_funding_info(tmp_path, manifest)

    assert status["endpoint_response_available"] is True
    assert status["symbol_adjustment_record_present"] is False
    assert status["funding_interval_hours"] == 8.0
    assert status["funding_info_verified"] is True
    assert status["blockers"] == []


def test_public_funding_info_requires_utc_capture_timestamp_for_verification(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "funding_info.json").write_text(
        json.dumps(
            {
                "source_method": "public_rest_response",
                "source_endpoint": "/fapi/v1/fundingInfo",
                "captured_at": "2026-05-19T08:00:00+08:00",
                "symbol": "BTCUSDT",
                "endpoint_response_available": True,
                "raw_response": [],
                "symbol_adjustment_record_present": False,
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}

    status = evaluate_funding_info(tmp_path, manifest)

    assert status["funding_info_verified"] is False
    assert "btc_funding_info_captured_at_missing" in status["blockers"]


def test_manual_funding_info_requires_endpoint_response_available_for_verification(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "funding_info.json").write_text(
        json.dumps(
            {
                "source_method": "manual_offline_capture",
                "source_endpoint": "/fapi/v1/fundingInfo",
                "source_url_or_doc": "https://fapi.binance.com/fapi/v1/fundingInfo",
                "captured_at": "2026-05-22T00:00:00Z",
                "symbol": "BTCUSDT",
                "endpoint_response_available": False,
                "raw_response": [],
                "symbol_adjustment_record_present": False,
                "operator_note": "manual public fundingInfo capture; no API key and no private endpoint",
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}

    status = evaluate_funding_info(tmp_path, manifest)

    assert status["endpoint_response_available"] is False
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_response_not_available" in status["blockers"]


def test_manual_funding_info_overlay_wraps_raw_endpoint_response(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    jsonschema.validate(payload, json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert payload["source_method"] == "manual_offline_capture"
    assert payload["endpoint_response_available"] is True
    assert payload["raw_response"] == []
    assert status["funding_info_verified"] is True
    assert status["blockers"] == []


def test_manual_funding_info_overlay_rejects_whitespace_operator_note(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="   ",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert "btc_funding_info_operator_note_missing" in payload["blockers"]
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_operator_note_missing" in status["blockers"]


def test_manual_funding_info_overlay_rejects_whitespace_source_url_or_doc(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[],
        source_method="manual_offline_capture",
        source_url_or_doc="   ",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert "btc_funding_info_source_url_missing" in payload["blockers"]
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_source_url_missing" in status["blockers"]


def test_btcusdt_funding_info_adjustment_row_verifies_with_required_fields(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[
            {
                "symbol": "BTCUSDT",
                "adjustedFundingRateCap": "0.02500000",
                "adjustedFundingRateFloor": "-0.02500000",
                "fundingIntervalHours": 8,
                "disclaimer": False,
            }
        ],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is True
    assert payload["symbol_adjustment_record_present"] is True
    assert payload["funding_interval_source"] == "funding_info_endpoint"
    assert status["symbol_adjustment_record_present"] is True
    assert status["funding_info_verified"] is True
    assert status["blockers"] == []


def test_funding_info_endpoint_error_body_is_not_verified(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response={
            "code": 0,
            "msg": "Service unavailable from a restricted location according to 'b. Eligibility'.",
        },
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_endpoint_error_response" in payload["blockers"]
    assert "btc_funding_info_endpoint_response_not_array" in payload["blockers"]
    assert status["endpoint_response_available"] is False
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_error_response" in status["blockers"]
    assert "btc_funding_info_endpoint_response_not_array" in status["blockers"]


def test_funding_info_endpoint_non_array_payload_is_not_verified(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response={"note": "unexpected object shape"},
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_endpoint_response_not_array" in payload["blockers"]
    assert status["endpoint_response_available"] is False
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_response_not_array" in status["blockers"]


def test_funding_info_endpoint_malformed_array_items_are_not_verified(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[1, "bad-row"],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_endpoint_array_item_not_object" in payload["blockers"]
    assert status["endpoint_response_available"] is False
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_array_item_not_object" in status["blockers"]


def test_funding_info_endpoint_embedded_error_object_is_not_verified(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[{"code": 0, "msg": "Service unavailable."}],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_endpoint_error_response" in payload["blockers"]
    assert status["endpoint_response_available"] is False
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_error_response" in status["blockers"]


def test_funding_info_endpoint_rows_require_symbol(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[{"adjustedFundingRateCap": "0.02500000"}],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_endpoint_row_symbol_missing" in payload["blockers"]
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_endpoint_row_symbol_missing" in status["blockers"]


def test_btcusdt_funding_info_adjustment_row_requires_interval_and_cap_floor(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[{"symbol": "BTCUSDT"}],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_btcusdt_funding_interval_missing" in payload["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_cap_missing" in payload["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_floor_missing" in payload["blockers"]
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_btcusdt_funding_interval_missing" in status["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_cap_missing" in status["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_floor_missing" in status["blockers"]


def test_btcusdt_funding_info_adjustment_row_rejects_non_finite_numbers(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)

    payload = build_funding_info_endpoint_overlay(
        bundle_dir=tmp_path,
        raw_response=[
            {
                "symbol": "BTCUSDT",
                "adjustedFundingRateCap": "NaN",
                "adjustedFundingRateFloor": "-Infinity",
                "fundingIntervalHours": "Infinity",
            }
        ],
        source_method="manual_offline_capture",
        source_url_or_doc="https://fapi.binance.com/fapi/v1/fundingInfo",
        captured_at="2026-05-22T00:00:00Z",
        operator_note="manual public fundingInfo capture; no API key and no private endpoint",
    )
    (tmp_path / "funding_info.json").write_text(json.dumps(payload), encoding="utf-8")
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}
    status = evaluate_funding_info(tmp_path, manifest)

    assert payload["endpoint_response_available"] is False
    assert "btc_funding_info_btcusdt_funding_interval_missing" in payload["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_cap_missing" in payload["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_floor_missing" in payload["blockers"]
    assert status["funding_info_verified"] is False
    assert "btc_funding_info_btcusdt_funding_interval_missing" in status["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_cap_missing" in status["blockers"]
    assert "btc_funding_info_btcusdt_adjusted_floor_missing" in status["blockers"]


def test_funding_info_overlay_cli_wraps_raw_public_response(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps({"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}),
        encoding="utf-8",
    )
    raw_path = tmp_path / "funding_info_raw.json"
    raw_path.write_text(json.dumps([]), encoding="utf-8")

    subprocess.check_call(
        [
            sys.executable,
            "scripts/build_btc_funding_info_overlay.py",
            "--bundle-dir",
            str(tmp_path),
            "--input-json",
            str(raw_path),
            "--source-method",
            "manual_offline_capture",
            "--source-url-or-doc",
            "https://fapi.binance.com/fapi/v1/fundingInfo",
            "--operator-note",
            "manual public fundingInfo capture; no API key and no private endpoint",
            "--captured-at",
            "2026-05-22T00:00:00Z",
        ]
    )

    output = tmp_path / "funding_info.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    status = evaluate_funding_info(tmp_path, {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"})

    assert payload["source_method"] == "manual_offline_capture"
    assert payload["endpoint_response_available"] is True
    assert status["funding_info_verified"] is True


def test_funding_info_overlay_cli_rejects_non_standard_json_constants(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps({"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}),
        encoding="utf-8",
    )
    raw_path = tmp_path / "funding_info_raw.json"
    raw_path.write_text('[{"symbol":"BTCUSDT","fundingIntervalHours":Infinity}]', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_btc_funding_info_overlay.py",
            "--bundle-dir",
            str(tmp_path),
            "--input-json",
            str(raw_path),
            "--source-method",
            "manual_offline_capture",
            "--source-url-or-doc",
            "https://fapi.binance.com/fapi/v1/fundingInfo",
            "--operator-note",
            "manual public fundingInfo capture; no API key and no private endpoint",
            "--captured-at",
            "2026-05-22T00:00:00Z",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "invalid or non-standard" in result.stderr
    assert not (tmp_path / "funding_info.json").exists()


def test_funding_info_overlay_cli_requires_explicit_utc_capture_time_for_raw_input(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "btc_perpetual_bundle_manifest.json").write_text(
        json.dumps({"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-02-09T16:00:00Z"}),
        encoding="utf-8",
    )
    raw_path = tmp_path / "funding_info_raw.json"
    raw_path.write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_btc_funding_info_overlay.py",
            "--bundle-dir",
            str(tmp_path),
            "--input-json",
            str(raw_path),
            "--source-method",
            "manual_offline_capture",
            "--source-url-or-doc",
            "https://fapi.binance.com/fapi/v1/fundingInfo",
            "--operator-note",
            "manual public fundingInfo capture; no API key and no private endpoint",
        ],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "captured_at is required" in result.stderr
    assert not (tmp_path / "funding_info.json").exists()


def test_incomplete_funding_rate_coverage_blocks_funding_info_verification(tmp_path: Path) -> None:
    _write_funding_rate(tmp_path / "funding_rate.csv", count=120)
    (tmp_path / "funding_info.json").write_text(
        json.dumps(
            {
                "source_method": "public_rest_response",
                "source_endpoint": "/fapi/v1/fundingInfo",
                "captured_at": "2026-05-19T00:00:00Z",
                "symbol": "BTCUSDT",
                "endpoint_response_available": True,
                "raw_response": [],
                "symbol_adjustment_record_present": False,
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    manifest = {"sample_start": "2026-01-01T00:00:00Z", "sample_end": "2026-05-12T00:00:00Z"}

    status = evaluate_funding_info(tmp_path, manifest)

    assert status["funding_info_verified"] is False
    assert "btc_funding_rate_coverage_incomplete_for_funding_info_verification" in status["blockers"]


def _write_funding_rate(path: Path, *, count: int) -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        timestamp = start + timedelta(hours=8 * index)
        funding_ms = int(timestamp.timestamp() * 1000)
        rows.append(f"{timestamp.isoformat().replace('+00:00', 'Z')},{funding_ms},BTCUSDT,0.0001,100000,f{index}")
    path.write_text(
        "timestamp,fundingTime,symbol,fundingRate,markPrice,source_record_id\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def _schema_valid_payload() -> dict[str, object]:
    return {
        "source_method": "manual_offline_capture",
        "source_endpoint": "/fapi/v1/fundingInfo",
        "source_url_or_doc": "https://fapi.binance.com/fapi/v1/fundingInfo",
        "captured_at": "2026-05-22T00:00:00Z",
        "symbol": "BTCUSDT",
        "endpoint_response_available": True,
        "raw_response": [],
        "symbol_adjustment_record_present": False,
        "funding_interval_hours": 8.0,
        "funding_interval_source": "inferred_from_funding_rate_spacing",
        "inference_confidence": "high",
        "spacing_diagnostics": {},
        "operator_note": "manual public fundingInfo capture",
        "blockers": [],
    }
