from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_manual_metadata_capture_operator_packet import (
    build_btc_manual_metadata_capture_operator_packet,
)


SCHEMA = Path("schemas/btc_manual_metadata_capture_operator_packet.schema.json")
REPORT = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json")


def test_btc_manual_metadata_capture_operator_packet_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["paper_gate_manual_inputs_complete"] is True
    inputs = {item["name"]: item for item in payload["required_manual_inputs"]}
    assert inputs["exchange_info"]["status"] == "verified"
    assert inputs["funding_info"]["status"] == "verified"
    fee_tier_status = payload["fee_tier_status"]
    if fee_tier_status["fee_tier_verified"] is True:
        assert inputs["fee_tier_overlay"]["status"] == "verified"
        assert fee_tier_status["manual_capture_required"] is False
        assert fee_tier_status["maker_fee_bps"] == 2.0
        assert fee_tier_status["taker_fee_bps"] == 5.0
        assert fee_tier_status["fee_blockers"] == []
    else:
        assert inputs["fee_tier_overlay"]["status"] == "awaiting_capture"
        assert fee_tier_status["manual_capture_required"] is True
        assert "btc_maker_taker_fee_tier_missing" in fee_tier_status["fee_blockers"]
    assert payload["paper_gate_manual_inputs_request"]["dry_run_command"].startswith(
        "make dry-run-btc-paper-gate-manual-inputs"
    )
    assert payload["paper_gate_manual_inputs_request"]["apply_command"].startswith(
        "make apply-btc-paper-gate-manual-inputs"
    )
    assert payload["paper_gate_manual_inputs_request"]["apply_and_validate_command"].startswith(
        "make apply-and-validate-btc-paper-gate-manual-inputs"
    )


def test_btc_manual_metadata_capture_operator_packet_schema_requires_timestamped_make_import_commands() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    payload["post_capture_dry_run_import_command"] = (
        "make dry-run-btc-manual-metadata-import "
        "EXCHANGE_INFO_RAW=exchange_info_raw.json "
        "FUNDING_INFO_RAW=funding_info_raw.json"
    )
    payload["post_capture_import_command"] = (
        "make apply-btc-manual-metadata-import "
        "EXCHANGE_INFO_RAW=exchange_info_raw.json "
        "FUNDING_INFO_RAW=funding_info_raw.json"
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_validation_sequence() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["post_import_validation_commands"] = ["make validate-btc-public-data-bundle"]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_rejects_non_utc_generated_at() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["generated_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_rejects_non_public_capture_commands() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    payload["capture_requests"][0]["url"] = "https://fapi.binance.com/fapi/v2/account"
    payload["capture_requests"][0]["command"] = (
        'curl -sS -H "X-MBX-APIKEY: secret" "https://fapi.binance.com/fapi/v2/account" '
        "-o exchange_info_raw.json"
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_raw_provenance_commands() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    payload["capture_requests"][0].pop("sha256_command", None)
    payload["capture_requests"][1]["size_command"] = "wc -c ../funding_info_raw.json"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_http_status_sidecars() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    payload["capture_requests"][0].pop("http_status_file", None)
    payload["capture_requests"][1]["required_http_status"] = 451

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_acceptance_invariants() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["acceptance_checks"] = [
        item for item in payload["acceptance_checks"] if "must not be in the future" not in item
    ]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_fee_tier_action() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    payload["fee_tier_overlay_request"]["dry_run_command"] = (
        "make dry-run-btc-fee-tier-overlay-import BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS>"
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_combined_manual_input_action() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    payload["paper_gate_manual_inputs_request"]["dry_run_command"] = (
        "make dry-run-btc-paper-gate-manual-inputs EXCHANGE_INFO_RAW=exchange_info_raw.json"
    )

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_schema_requires_required_manual_inputs() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["required_manual_inputs"] = payload["required_manual_inputs"][:2]

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_manual_metadata_capture_operator_packet_is_public_only_and_actionable(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json",
        {
            "status": "capture_incomplete",
            "network_called": True,
            "next_required_action": "manual_capture_from_allowed_network",
            "endpoint_results": {
                "exchange_info": {"http_status": 451},
                "funding_info": {"http_status": 451},
            },
            "blockers": [
                "btc_binance_public_rest_http_451_geoblocked",
                "btc_public_metadata_exchange_info_capture_failed",
                "btc_public_metadata_funding_info_capture_failed",
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json",
        {
            "status": "ready_for_manual_capture",
            "exchange_info": {"source_url": "https://fapi.binance.com/fapi/v1/exchangeInfo"},
            "funding_info": {"source_url": "https://fapi.binance.com/fapi/v1/fundingInfo"},
            "post_capture_commands": [
                "make apply-btc-manual-metadata-import "
                "EXCHANGE_INFO_RAW=exchange_info_raw.json "
                "FUNDING_INFO_RAW=funding_info_raw.json "
                "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_CAPTURE_TIME>"
            ],
            "blockers": ["btc_perpetual_exchange_info_not_verified", "btc_perpetual_funding_info_not_verified"],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {
            "status": "fail",
            "fee_model": {
                "fee_tier_verified": False,
                "maker_fee_bps": None,
                "taker_fee_bps": 4.0,
                "fee_tier_overlay": None,
                "fee_tier_import_report": None,
                "fee_tier_import_report_verified": False,
                "fee_blockers": ["btc_maker_taker_fee_tier_missing"],
            },
            "blockers": ["btc_maker_taker_fee_tier_missing"],
        },
    )

    payload = build_btc_manual_metadata_capture_operator_packet(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requests = {item["name"]: item for item in payload["capture_requests"]}
    required_inputs = {item["name"]: item for item in payload["required_manual_inputs"]}

    assert payload["status"] == "awaiting_manual_capture"
    assert payload["operator_action"] == "manual_capture_from_allowed_network"
    assert payload["manual_inputs_status"] == "awaiting_manual_inputs"
    assert payload["paper_gate_manual_inputs_complete"] is False
    assert required_inputs["exchange_info"]["status"] == "awaiting_capture"
    assert required_inputs["exchange_info"]["action"] == "manual_capture_from_allowed_network"
    assert required_inputs["funding_info"]["status"] == "awaiting_capture"
    assert required_inputs["funding_info"]["action"] == "manual_capture_from_allowed_network"
    assert required_inputs["fee_tier_overlay"]["status"] == "awaiting_capture"
    assert required_inputs["fee_tier_overlay"]["action"] == "capture_public_fee_schedule_and_import"
    assert "btc_maker_taker_fee_tier_missing" in required_inputs["fee_tier_overlay"]["blockers"]
    assert payload["capture_attempt_report"] == "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json"
    assert payload["readiness_report"] == "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json"
    assert payload["last_public_metadata_capture_status"]["status"] == "capture_incomplete"
    assert payload["last_public_metadata_capture_status"]["network_called"] is True
    assert payload["last_public_metadata_capture_status"]["exchange_info_http_status"] == 451
    assert payload["last_public_metadata_capture_status"]["funding_info_http_status"] == 451
    assert requests["exchange_info"]["endpoint"] == "GET /fapi/v1/exchangeInfo"
    assert requests["exchange_info"]["url"] == "https://fapi.binance.com/fapi/v1/exchangeInfo"
    assert requests["exchange_info"]["command"] == (
        'curl -sS -o exchange_info_raw.json -w "%{http_code}\\n" '
        '"https://fapi.binance.com/fapi/v1/exchangeInfo" > exchange_info_http_status.txt'
    )
    assert requests["exchange_info"]["http_status_file"] == "exchange_info_http_status.txt"
    assert requests["exchange_info"]["http_status_command"] == "cat exchange_info_http_status.txt"
    assert requests["exchange_info"]["required_http_status"] == 200
    assert requests["exchange_info"]["sha256_command"] == "sha256sum exchange_info_raw.json"
    assert requests["exchange_info"]["size_command"] == "wc -c exchange_info_raw.json"
    assert requests["exchange_info"]["output_file"] == "exchange_info_raw.json"
    assert requests["exchange_info"]["empty_response_allowed"] is False
    assert requests["funding_info"]["endpoint"] == "GET /fapi/v1/fundingInfo"
    assert requests["funding_info"]["url"] == "https://fapi.binance.com/fapi/v1/fundingInfo"
    assert requests["funding_info"]["command"] == (
        'curl -sS -o funding_info_raw.json -w "%{http_code}\\n" '
        '"https://fapi.binance.com/fapi/v1/fundingInfo" > funding_info_http_status.txt'
    )
    assert requests["funding_info"]["http_status_file"] == "funding_info_http_status.txt"
    assert requests["funding_info"]["http_status_command"] == "cat funding_info_http_status.txt"
    assert requests["funding_info"]["required_http_status"] == 200
    assert requests["funding_info"]["sha256_command"] == "sha256sum funding_info_raw.json"
    assert requests["funding_info"]["size_command"] == "wc -c funding_info_raw.json"
    assert requests["funding_info"]["output_file"] == "funding_info_raw.json"
    assert requests["funding_info"]["empty_response_allowed"] is True
    assert payload["post_capture_import_command"].startswith("make apply-btc-manual-metadata-import")
    assert "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_CAPTURE_TIME>" in payload["post_capture_import_command"]
    assert payload["post_capture_dry_run_import_command"].startswith("make dry-run-btc-manual-metadata-import")
    assert "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_CAPTURE_TIME>" in payload["post_capture_dry_run_import_command"]
    assert "make dry-run-btc-manual-metadata-import" not in payload["post_capture_import_command"]
    assert payload["post_import_validation_commands"][1] == "make validate-btc-public-data-bundle"
    assert payload["post_import_validation_commands"][2] == "make validate-btc-public-data-bundle-strict"
    assert payload["post_import_validation_commands"][3] == "make rebuild-btc-paper-readiness-chain"
    assert payload["fee_tier_overlay_request"]["name"] == "fee_tier_overlay"
    assert payload["fee_tier_overlay_request"]["required_for"] == "maker_taker_fee_tier_verification"
    assert payload["fee_tier_overlay_request"]["source_url_or_doc"] == "https://www.okx.com/en-us/fees"
    assert payload["fee_tier_overlay_request"]["output_file"] == "artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json"
    assert payload["fee_tier_overlay_request"]["dry_run_report"] == (
        "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_dry_run_report.json"
    )
    assert payload["fee_tier_overlay_request"]["import_report"] == (
        "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json"
    )
    assert payload["fee_tier_overlay_request"]["dry_run_command"].startswith(
        "make dry-run-btc-fee-tier-overlay-import"
    )
    assert "BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS>" in payload["fee_tier_overlay_request"]["dry_run_command"]
    assert "BTC_FEE_TIER_TAKER_BPS=<TAKER_FEE_BPS>" in payload["fee_tier_overlay_request"]["dry_run_command"]
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in (
        payload["fee_tier_overlay_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in (
        payload["fee_tier_overlay_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_CAPTURED_AT=<UTC_CAPTURE_TIME>" in payload["fee_tier_overlay_request"]["dry_run_command"]
    assert payload["fee_tier_overlay_request"]["import_command"].startswith(
        "make apply-btc-fee-tier-overlay-import"
    )
    assert "BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS>" in payload["fee_tier_overlay_request"]["import_command"]
    assert "BTC_FEE_TIER_TAKER_BPS=<TAKER_FEE_BPS>" in payload["fee_tier_overlay_request"]["import_command"]
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in (
        payload["fee_tier_overlay_request"]["import_command"]
    )
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in (
        payload["fee_tier_overlay_request"]["import_command"]
    )
    assert "BTC_FEE_TIER_CAPTURED_AT=<UTC_CAPTURE_TIME>" in payload["fee_tier_overlay_request"]["import_command"]
    assert payload["fee_tier_overlay_request"]["post_import_rebuild_command"] == (
        "make rebuild-btc-paper-readiness-chain"
    )
    assert payload["fee_tier_overlay_request"]["post_import_validation_command"] == "make validate-btc-evidence"
    assert payload["paper_gate_manual_inputs_request"]["name"] == "paper_gate_manual_inputs"
    assert payload["paper_gate_manual_inputs_request"]["required_for"] == "btc_paper_readiness_manual_input_gate"
    assert payload["paper_gate_manual_inputs_request"]["dry_run_command"].startswith(
        "make dry-run-btc-paper-gate-manual-inputs"
    )
    assert payload["paper_gate_manual_inputs_request"]["apply_command"].startswith(
        "make apply-btc-paper-gate-manual-inputs"
    )
    assert payload["paper_gate_manual_inputs_request"]["apply_and_validate_command"].startswith(
        "make apply-and-validate-btc-paper-gate-manual-inputs"
    )
    assert "EXCHANGE_INFO_RAW=exchange_info_raw.json" in payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    assert "FUNDING_INFO_RAW=funding_info_raw.json" in payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    assert "EXCHANGE_INFO_HTTP_STATUS=exchange_info_http_status.txt" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "FUNDING_INFO_HTTP_STATUS=funding_info_http_status.txt" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "BTC_MANUAL_METADATA_CAPTURED_AT=<UTC_METADATA_CAPTURE_TIME>" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_MAKER_BPS=<MAKER_FEE_BPS>" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_TAKER_BPS=<TAKER_FEE_BPS>" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "BTC_FEE_TIER_CAPTURED_AT=<UTC_FEE_CAPTURE_TIME>" in (
        payload["paper_gate_manual_inputs_request"]["dry_run_command"]
    )
    assert "EXCHANGE_INFO_RAW=exchange_info_raw.json" in (
        payload["paper_gate_manual_inputs_request"]["apply_and_validate_command"]
    )
    assert "BTC_FEE_TIER_SOURCE=manual_public_okx_swap_fee_schedule" in (
        payload["paper_gate_manual_inputs_request"]["apply_and_validate_command"]
    )
    assert "BTC_FEE_TIER_SOURCE_URL_OR_DOC=https://www.okx.com/en-us/fees" in (
        payload["paper_gate_manual_inputs_request"]["apply_and_validate_command"]
    )
    assert payload["paper_gate_manual_inputs_request"]["post_apply_rebuild_command"] == (
        "make rebuild-btc-paper-readiness-chain"
    )
    assert payload["paper_gate_manual_inputs_request"]["post_apply_validation_command"] == "make validate-btc-evidence"
    assert payload["paper_gate_manual_inputs_request"]["post_apply_readiness_command"] == (
        "make check-btc-paper-validation-readiness"
    )
    assert payload["fee_tier_status"]["cost_model_report"] == "artifacts/btc_cost_model/latest/btc_cost_model_report.json"
    assert payload["fee_tier_status"]["cost_model_status"] == "fail"
    assert payload["fee_tier_status"]["fee_tier_verified"] is False
    assert payload["fee_tier_status"]["manual_capture_required"] is True
    assert payload["fee_tier_status"]["maker_fee_bps"] is None
    assert payload["fee_tier_status"]["taker_fee_bps"] == 4.0
    assert payload["fee_tier_status"]["fee_tier_import_report_verified"] is False
    assert "btc_maker_taker_fee_tier_missing" in payload["fee_tier_status"]["fee_blockers"]
    assert any(
        "BTC_MANUAL_METADATA_CAPTURED_AT is the actual UTC capture time" in item
        for item in payload["acceptance_checks"]
    )
    assert any("must not be in the future" in item for item in payload["acceptance_checks"])
    assert any("both contain 200" in item for item in payload["acceptance_checks"])
    assert any("record sha256sum and byte size" in item for item in payload["acceptance_checks"])
    assert any("exchange_info_raw.json and funding_info_raw.json are distinct files" in item for item in payload["acceptance_checks"])
    assert any("raw capture files are kept outside the selected bundle directory" in item for item in payload["acceptance_checks"])
    assert any("dry-run import report is written separately" in item for item in payload["acceptance_checks"])
    assert any("write-capable manual import report is written" in item for item in payload["acceptance_checks"])
    assert any("exchange_info_output_sha256 must match" in item for item in payload["acceptance_checks"])
    assert any("funding_info_output_sha256 must match" in item for item in payload["acceptance_checks"])
    assert any("BTC_FEE_TIER_MAKER_BPS and BTC_FEE_TIER_TAKER_BPS" in item for item in payload["acceptance_checks"])
    assert any("BTC_FEE_TIER_CAPTURED_AT is the actual UTC fee schedule capture time" in item for item in payload["acceptance_checks"])
    assert any("dry-run fee tier import report" in item for item in payload["acceptance_checks"])
    assert any("write-capable fee tier import report" in item for item in payload["acceptance_checks"])
    assert any("overlay_payload_sha256 must match" in item for item in payload["acceptance_checks"])
    assert payload["safety"]["api_key_required"] is False
    assert payload["safety"]["private_endpoints_allowed"] is False
    assert payload["safety"]["order_endpoints_allowed"] is False
    assert payload["safety"]["writes_bundle_files_during_capture"] is False
    assert payload["safety"]["strategy_retest_allowed"] is False
    assert "order" in payload["safety"]["forbidden_endpoint_families"]
    assert "btc_binance_public_rest_http_451_geoblocked" in payload["blockers"]
    assert "btc_maker_taker_fee_tier_missing" in payload["blockers"]


def test_btc_manual_metadata_capture_operator_packet_passes_when_verified(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json",
        {
            "status": "metadata_verified",
            "exchange_info": {
                "verified": True,
                "source_url": "https://fapi.binance.com/fapi/v1/exchangeInfo",
            },
            "funding_info": {
                "verified": True,
                "source_url": "https://fapi.binance.com/fapi/v1/fundingInfo",
            },
            "post_capture_commands": [],
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json",
        {
            "status": "capture_complete",
            "network_called": True,
            "next_required_action": "wrap_and_validate_metadata",
            "endpoint_results": {
                "exchange_info": {"http_status": 200},
                "funding_info": {"http_status": 200},
            },
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {
            "status": "pass",
            "fee_model": {
                "fee_tier_verified": True,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 4.0,
                "fee_tier_overlay": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json",
                "fee_tier_import_report": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json",
                "fee_tier_import_report_verified": True,
                "fee_blockers": [],
            },
            "blockers": [],
        },
    )

    payload = build_btc_manual_metadata_capture_operator_packet(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )

    assert payload["status"] == "metadata_verified"
    assert payload["operator_action"] == "no_manual_capture_required"
    assert payload["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["paper_gate_manual_inputs_complete"] is True
    assert payload["blockers"] == []


def test_btc_manual_metadata_capture_operator_packet_blocks_when_cost_model_report_missing(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json",
        {
            "status": "metadata_verified",
            "exchange_info": {
                "verified": True,
                "source_url": "https://fapi.binance.com/fapi/v1/exchangeInfo",
            },
            "funding_info": {
                "verified": True,
                "source_url": "https://fapi.binance.com/fapi/v1/fundingInfo",
            },
            "post_capture_commands": [],
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json",
        {
            "status": "capture_complete",
            "network_called": True,
            "next_required_action": "wrap_and_validate_metadata",
            "endpoint_results": {
                "exchange_info": {"http_status": 200},
                "funding_info": {"http_status": 200},
            },
            "blockers": [],
        },
    )

    payload = build_btc_manual_metadata_capture_operator_packet(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    required_inputs = {item["name"]: item for item in payload["required_manual_inputs"]}

    assert payload["status"] == "awaiting_manual_capture"
    assert payload["operator_action"] == "manual_capture_from_allowed_network"
    assert payload["manual_inputs_status"] == "awaiting_manual_inputs"
    assert payload["paper_gate_manual_inputs_complete"] is False
    assert payload["fee_tier_status"]["cost_model_report"] is None
    assert payload["fee_tier_status"]["cost_model_status"] == "missing"
    assert payload["fee_tier_status"]["fee_tier_verified"] is False
    assert payload["fee_tier_status"]["manual_capture_required"] is True
    assert "btc_cost_model_report_missing" in payload["fee_tier_status"]["fee_blockers"]
    assert "btc_cost_model_report_missing" in required_inputs["fee_tier_overlay"]["blockers"]
    assert "btc_cost_model_report_missing" in payload["blockers"]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
