from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_manual_metadata_capture_readiness_report import (
    build_btc_manual_metadata_capture_readiness_report,
)


SCHEMA = Path("schemas/btc_manual_metadata_capture_readiness_report.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json")


def test_btc_manual_metadata_capture_readiness_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_readiness_schema_requires_timestamped_make_import_command() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["post_capture_commands"][0] = (
        "make apply-btc-manual-metadata-import "
        "EXCHANGE_INFO_RAW=exchange_info_raw.json "
        "FUNDING_INFO_RAW=funding_info_raw.json"
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_readiness_schema_requires_validation_sequence() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["post_capture_commands"][2] = "pytest tests/contracts/test_btc_manual_metadata_import.py -q"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_readiness_schema_rejects_non_utc_generated_at() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["generated_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_readiness_schema_rejects_direct_overlay_write_commands() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["exchange_info"]["wrapper_command"] = (
        "python3 scripts/build_btc_exchange_info_overlay.py "
        "--input-json exchange_info_raw.json"
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_readiness_is_fail_closed_and_actionable() -> None:
    payload = build_btc_manual_metadata_capture_readiness_report(generated_at="2026-05-22T00:00:00Z")

    assert payload["status"] == "metadata_verified"
    assert payload["last_public_metadata_capture_status"]["status"] in {"missing", "capture_incomplete"}
    assert payload["manual_capture_operator_packet"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
    )
    assert payload["bundle_dir"] == "data/external/btc_perpetual/okx_swap/bundles/btc_okx_swap_btcusdt_history_365d_v1"
    assert payload["perpetual_evidence_ready"] is True
    assert payload["exchange_info"]["manual_capture_required"] is False
    assert payload["exchange_info"]["allowed_endpoint"] == "GET /api/v5/public/instruments"
    assert payload["exchange_info"]["source_url"] == "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
    assert payload["exchange_info"]["wrapper_command"] == "atomic_importer_only: use post_capture_commands[0]"
    assert "raw_symbol_info.instId=BTC-USDT-SWAP" in payload["exchange_info"]["required_fields"]
    assert "api_key_used=false" in payload["exchange_info"]["required_fields"]
    assert "order" in payload["exchange_info"]["forbidden_endpoint_families"]
    assert payload["exchange_info"]["blockers"] == []
    assert payload["funding_info"]["manual_capture_required"] is False
    assert payload["funding_info"]["allowed_endpoint"] == "GET /api/v5/public/funding-rate"
    assert payload["funding_info"]["source_url"] == "https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP"
    assert payload["funding_info"]["wrapper_command"] == "atomic_importer_only: use post_capture_commands[0]"
    assert payload["funding_info"]["empty_response_allowed"] is False
    assert payload["funding_info"]["source_method"] == "public_rest_response"
    assert payload["funding_info"]["blockers"] == []
    assert payload["safety"]["api_key_required"] is False
    assert payload["safety"]["strategy_retest_allowed"] is False
    assert payload["safety"]["compression_expansion_state"] == "archived"
    assert payload["blockers"] == []
    assert payload["post_capture_commands"][0].startswith("make apply-btc-manual-metadata-import")
    assert "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_CAPTURE_TIME>" in payload["post_capture_commands"][0]
    assert "--source-provider okx_swap" in payload["post_capture_commands"][1]
    assert payload["post_capture_commands"][2] == "make validate-btc-public-data-bundle"
    assert payload["post_capture_commands"][3] == "make validate-btc-public-data-bundle-strict"
    assert payload["post_capture_commands"][4] == "make rebuild-btc-paper-readiness-chain"


def test_btc_manual_metadata_capture_readiness_passes_when_provider_metadata_verified(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "funding_info_endpoint_response_available": True,
            "funding_info_source_method": "manual_offline_capture",
            "funding_interval_hours": 8.0,
            "funding_interval_source": "funding_info_endpoint",
            "funding_interval_inference_confidence": "high",
            "perpetual_evidence_ready": True,
            "blockers": [],
        },
    )

    payload = build_btc_manual_metadata_capture_readiness_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )

    assert payload["status"] == "metadata_verified"
    assert payload["exchange_info"]["manual_capture_required"] is False
    assert payload["funding_info"]["manual_capture_required"] is False
    assert payload["blockers"] == []


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
