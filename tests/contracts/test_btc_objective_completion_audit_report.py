from __future__ import annotations

import json
import hashlib
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_objective_completion_audit_report import (
    build_btc_objective_completion_audit_report,
)


REPORT = Path("artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json")
SCHEMA = Path("schemas/btc_objective_completion_audit_report.schema.json")


def test_btc_objective_completion_audit_schema_valid() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_metadata_without_import_provenance() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    manual = payload["requirements"]["manual_exchange_info_capture"]
    manual["status"] = "complete"
    manual["verified"] = True
    manual["manual_capture_required"] = False
    manual["import_status"] = "verified"
    manual["import_writes_performed"] = True
    manual["import_captured_at"] = None
    manual["raw_input_files"]["exchange_info_raw"]["exists"] = True
    manual["raw_input_files"]["exchange_info_raw"]["size_bytes"] = 0
    manual["raw_input_files"]["exchange_info_raw"]["sha256"] = "a" * 64
    manual["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_non_utc_generated_at() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["generated_at"] = "2026-05-22T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_funding_without_endpoint_response() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    funding = payload["requirements"]["funding_info_endpoint_policy_repair"]
    funding["status"] = "complete"
    funding["verified"] = True
    funding["manual_capture_required"] = False
    funding["import_status"] = "verified"
    funding["import_writes_performed"] = True
    funding["import_captured_at"] = "2026-05-22T00:00:00Z"
    funding["endpoint_response_available"] = False
    funding["blockers"] = []
    for raw in funding["raw_input_files"].values():
        raw["path"] = "raw.json"
        raw["exists"] = True
        raw["size_bytes"] = 1
        raw["sha256"] = "a" * 64
        raw["current_file_verified"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_funding_ledger_without_reconciliation() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    funding_ledger = payload["requirements"]["funding_ledger_net_pnl_integration"]
    funding_ledger["status"] = "complete"
    funding_ledger["funding_payment_in_ledger"] = True
    funding_ledger["funding_merged_into_net_ledger"] = True
    funding_ledger["funding_events_count"] = 1
    funding_ledger["funding_payment_count"] = 1
    funding_ledger["funding_adjusted_net_pnl_reconciled"] = False
    funding_ledger["funding_adjusted_net_pnl_reconciliation_delta"] = 1.0
    funding_ledger["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_funding_ledger_without_csv_reconciliation() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    funding_ledger = payload["requirements"]["funding_ledger_net_pnl_integration"]
    funding_ledger["status"] = "complete"
    funding_ledger["funding_payment_in_ledger"] = True
    funding_ledger["funding_merged_into_net_ledger"] = True
    funding_ledger["funding_events_count"] = 1
    funding_ledger["funding_payment_count"] = 1
    funding_ledger["funding_adjusted_net_pnl_reconciled"] = True
    funding_ledger["funding_adjusted_net_pnl_reconciliation_delta"] = 0.0
    funding_ledger["funding_adjusted_ledger_exists"] = True
    funding_ledger["funding_adjusted_ledger_reconciled_to_report"] = False
    funding_ledger["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_funding_ledger_without_payments() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    funding_ledger = payload["requirements"]["funding_ledger_net_pnl_integration"]
    funding_ledger["status"] = "complete"
    funding_ledger["funding_payment_in_ledger"] = True
    funding_ledger["funding_merged_into_net_ledger"] = True
    funding_ledger["funding_events_count"] = 0
    funding_ledger["funding_payment_count"] = 0
    funding_ledger["funding_adjusted_net_pnl_reconciled"] = True
    funding_ledger["funding_adjusted_net_pnl_reconciliation_delta"] = 0.0
    funding_ledger["funding_adjusted_ledger_exists"] = True
    funding_ledger["funding_adjusted_ledger_reconciled_to_report"] = True
    funding_ledger["funding_adjusted_ledger_trade_count"] = 1
    funding_ledger["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_archive_with_retest_allowed() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    archive = payload["requirements"]["archive_compression_expansion_breakout"]
    archive["status"] = "complete"
    archive["registry_next_action"] = "limited_retest_allowed"
    archive["limited_retest_allowed"] = True
    archive["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_archive_with_paper_unlock() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    archive = payload["requirements"]["archive_compression_expansion_breakout"]
    archive["status"] = "complete"
    archive["paper_review_pending_allowed"] = True
    archive["paper_queue"] = "OPEN"
    archive["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_hypothesis_v2_with_skeleton_path() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    hypothesis = payload["requirements"]["btc_hypothesis_lab_v2_controlled_search"]
    hypothesis["status"] = "complete"
    hypothesis["strategy_skeleton_generated"] = False
    hypothesis["strategy_skeleton_path"] = "configs/btc/hypotheses/bad_skeleton.yaml"
    hypothesis["candidate_generation_allowed"] = False
    hypothesis["candidate_generated"] = False
    hypothesis["paper_or_live_side_effects_allowed"] = False
    hypothesis["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_schema_rejects_complete_hypothesis_v2_missing_forbidden_inventory() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    hypothesis = payload["requirements"]["btc_hypothesis_lab_v2_controlled_search"]
    hypothesis["status"] = "complete"
    hypothesis["forbidden_outputs"] = ["strategy_skeleton", "candidate_config"]
    hypothesis["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_objective_completion_audit_current_status_is_complete_after_okx_metadata_import() -> None:
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    requirements = payload["requirements"]

    assert payload["status"] == "complete"
    assert payload["goal_complete"] is True
    assert payload["next_required_action"] == "none"
    assert payload["incomplete_requirements"] == []
    assert payload["blockers"] == []
    assert requirements["manual_exchange_info_capture"]["status"] == "complete"
    assert requirements["manual_exchange_info_capture"]["verified"] is True
    assert requirements["manual_exchange_info_capture"]["evidence"]["manual_capture_operator_packet"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
    )
    assert requirements["manual_exchange_info_capture"]["evidence"]["manual_metadata_import_report"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    )
    assert requirements["manual_exchange_info_capture"]["operator_action"] == "no_manual_capture_required"
    assert "provider_metadata_verified=true" in (
        requirements["manual_exchange_info_capture"]["completion_criteria"]
    )
    assert "manual_metadata_import_report.schema_version=btc_manual_metadata_import_report_v1" in (
        requirements["manual_exchange_info_capture"]["completion_criteria"]
    )
    assert "manual_metadata_import_report.writes_performed=true" in (
        requirements["manual_exchange_info_capture"]["completion_criteria"]
    )
    assert requirements["manual_exchange_info_capture"]["import_status"] == "verified"
    assert requirements["manual_exchange_info_capture"]["import_writes_performed"] is True
    assert requirements["manual_exchange_info_capture"]["import_captured_at"].endswith("Z")
    assert requirements["manual_exchange_info_capture"]["import_bundle_dir"]["matches_selected_bundle"] is True
    assert "okx_swap" in requirements["manual_exchange_info_capture"]["import_bundle_dir"]["path"]
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["exchange_info_raw"]["http_status"] == 200
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["exchange_info_raw"]["current_file_verified"] is True
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["funding_info_raw"]["http_status"] == 200
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["funding_info_raw"]["current_file_verified"] is True
    assert requirements["manual_exchange_info_capture"]["last_capture_status"] in {"failed", "not_executed"}
    assert requirements["manual_exchange_info_capture"]["last_http_status"] in {451, None}
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "complete"
    assert requirements["funding_info_endpoint_policy_repair"]["verified"] is True
    assert requirements["funding_info_endpoint_policy_repair"]["endpoint_response_available"] is True
    assert requirements["funding_info_endpoint_policy_repair"]["evidence"]["manual_capture_operator_packet"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json"
    )
    assert requirements["funding_info_endpoint_policy_repair"]["evidence"]["manual_metadata_import_report"] == (
        "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    )
    assert requirements["funding_info_endpoint_policy_repair"]["operator_action"] == "no_manual_capture_required"
    assert "provider_metadata_verified=true" in (
        requirements["funding_info_endpoint_policy_repair"]["completion_criteria"]
    )
    assert "manual_metadata_import_report.schema_version=btc_manual_metadata_import_report_v1" in (
        requirements["funding_info_endpoint_policy_repair"]["completion_criteria"]
    )
    assert "manual_metadata_import_report.writes_performed=true" in (
        requirements["funding_info_endpoint_policy_repair"]["completion_criteria"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["import_status"] == "verified"
    assert requirements["funding_info_endpoint_policy_repair"]["import_writes_performed"] is True
    assert requirements["funding_info_endpoint_policy_repair"]["import_bundle_dir"]["matches_selected_bundle"] is True
    assert "okx_swap" in requirements["funding_info_endpoint_policy_repair"]["import_bundle_dir"]["path"]
    assert requirements["funding_info_endpoint_policy_repair"]["raw_input_files"]["exchange_info_raw"]["exists"] is True
    assert requirements["funding_info_endpoint_policy_repair"]["raw_input_files"]["exchange_info_raw"]["http_status"] == 200
    assert requirements["funding_info_endpoint_policy_repair"]["raw_input_files"]["funding_info_raw"]["exists"] is True
    assert requirements["funding_info_endpoint_policy_repair"]["raw_input_files"]["funding_info_raw"]["http_status"] == 200
    assert requirements["funding_info_endpoint_policy_repair"]["last_capture_status"] in {"failed", "not_executed"}
    assert requirements["funding_info_endpoint_policy_repair"]["last_http_status"] in {451, None}
    assert requirements["funding_ledger_net_pnl_integration"]["status"] == "complete"
    assert requirements["funding_ledger_net_pnl_integration"]["funding_payment_in_ledger"] is True
    assert requirements["funding_ledger_net_pnl_integration"]["funding_merged_into_net_ledger"] is True
    assert requirements["funding_ledger_net_pnl_integration"]["funding_events_count"] > 0
    assert requirements["funding_ledger_net_pnl_integration"]["funding_payment_count"] > 0
    assert requirements["funding_ledger_net_pnl_integration"]["funding_adjusted_net_pnl_reconciled"] is True
    assert requirements["funding_ledger_net_pnl_integration"]["funding_adjusted_net_pnl_reconciliation_delta"] == 0.0
    assert requirements["funding_ledger_net_pnl_integration"]["funding_adjusted_ledger_exists"] is True
    assert requirements["funding_ledger_net_pnl_integration"]["funding_adjusted_ledger_reconciled_to_report"] is True
    assert requirements["funding_ledger_net_pnl_integration"]["funding_adjusted_ledger_trade_count"] > 0
    assert requirements["funding_ledger_net_pnl_integration"]["expected_funding_adjusted_net_pnl_total"] is not None
    assert requirements["funding_ledger_net_pnl_integration"]["trade_ledger_net_pnl_total"] is not None
    assert requirements["funding_ledger_net_pnl_integration"]["funding_pnl_total"] is not None
    assert requirements["archive_compression_expansion_breakout"]["status"] == "complete"
    assert requirements["archive_compression_expansion_breakout"]["allowed_next_action"] == "archive_only"
    assert requirements["archive_compression_expansion_breakout"]["registry_next_action"] == (
        "do_not_retest_without_new_hypothesis"
    )
    assert requirements["archive_compression_expansion_breakout"]["archive_recommended"] is True
    assert requirements["archive_compression_expansion_breakout"]["limited_retest_allowed"] is False
    assert requirements["archive_compression_expansion_breakout"]["paper_review_pending_allowed"] is False
    assert requirements["archive_compression_expansion_breakout"]["paper_review_pending_created"] is False
    assert requirements["archive_compression_expansion_breakout"]["promotion_ready"] is False
    assert requirements["archive_compression_expansion_breakout"]["paper_queue"] == "LOCKED"
    assert requirements["archive_compression_expansion_breakout"]["live"] == "FROZEN"
    assert "compression_expansion_breakout" in (
        requirements["archive_compression_expansion_breakout"]["archived_or_rejected"]
    )
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["status"] == "complete"
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["allowed_output_level"] == "hypothesis"
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["strategy_skeleton_generation_allowed"] is False
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["strategy_skeleton_generated"] is False
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["strategy_skeleton_path"] == ""
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["candidate_generation_allowed"] is False
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["candidate_generated"] is False
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["paper_or_live_side_effects_allowed"] is False
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["paper_queue"] == "LOCKED"
    assert requirements["btc_hypothesis_lab_v2_controlled_search"]["live"] == "FROZEN"
    assert "strategy_skeleton" in requirements["btc_hypothesis_lab_v2_controlled_search"]["forbidden_outputs"]
    assert all(
        "skeleton" not in item
        for item in requirements["btc_hypothesis_lab_v2_controlled_search"]["generated_artifacts"]
    )
    assert payload["blockers"] == []


def test_btc_objective_completion_audit_builder_is_fail_closed() -> None:
    payload = build_btc_objective_completion_audit_report(generated_at="2026-05-22T00:00:00Z")

    assert payload["schema_version"] == "btc_objective_completion_audit_report_v1"
    assert payload["generated_at"] == "2026-05-22T00:00:00Z"
    assert payload["goal_complete"] is True
    assert payload["next_required_action"] == "none"


def test_btc_objective_completion_audit_requires_verified_write_import_even_if_provider_verified(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "funding_info_endpoint_response_available": True,
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json",
        {
            "exchange_info": {"manual_capture_required": False},
            "funding_info": {"manual_capture_required": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json",
        {
            "endpoint_results": {
                "exchange_info": {"capture_status": "captured", "http_status": 200, "blockers": []},
                "funding_info": {"capture_status": "captured", "http_status": 200, "blockers": []},
            },
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        {"operator_action": "no_manual_capture_required", "blockers": []},
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_report_missing" in requirements["manual_exchange_info_capture"]["blockers"]
    assert "btc_manual_metadata_import_report_missing" in requirements["funding_info_endpoint_policy_repair"]["blockers"]


def test_btc_objective_completion_audit_rejects_verified_dry_run_import_for_completion(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        {
            "schema_version": "btc_manual_metadata_import_report_v1",
            "status": "verified",
            "writes_performed": False,
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "bundle_dir": "data/external/btc_perpetual/binance_usdm/bundles/fixture",
            "captured_at": "2026-05-22T00:00:00Z",
            "raw_input_files": {
                "exchange_info_raw": {
                    "path": "exchange_info_raw.json",
                    "exists": True,
                    "size_bytes": 100,
                    "sha256": "a" * 64,
                    "http_status_file": "exchange_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
                },
                "funding_info_raw": {
                    "path": "funding_info_raw.json",
                    "exists": True,
                    "size_bytes": 2,
                    "sha256": "b" * 64,
                    "http_status_file": "funding_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
                },
            },
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        },
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["manual_exchange_info_capture"]["import_status"] == "verified"
    assert requirements["manual_exchange_info_capture"]["import_writes_performed"] is False
    assert "btc_manual_metadata_import_write_not_performed" in requirements["manual_exchange_info_capture"]["blockers"]
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert requirements["funding_info_endpoint_policy_repair"]["import_status"] == "verified"
    assert requirements["funding_info_endpoint_policy_repair"]["import_writes_performed"] is False
    assert "btc_manual_metadata_import_write_not_performed" in requirements["funding_info_endpoint_policy_repair"]["blockers"]


def test_btc_objective_completion_audit_metadata_complete_requires_import_hashes(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        _verified_import_report(raw_root=tmp_path),
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "complete"
    assert requirements["manual_exchange_info_capture"]["import_writes_performed"] is True
    assert requirements["manual_exchange_info_capture"]["import_captured_at"] == "2026-05-22T00:00:00Z"
    assert requirements["manual_exchange_info_capture"]["import_bundle_dir"][
        "exchange_info_output_hash_verified"
    ] is True
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["exchange_info_raw"]["current_file_verified"] is True
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "complete"
    assert requirements["funding_info_endpoint_policy_repair"]["import_bundle_dir"][
        "funding_info_output_hash_verified"
    ] is True
    assert requirements["funding_info_endpoint_policy_repair"]["raw_input_files"]["funding_info_raw"]["current_file_verified"] is True


def test_btc_objective_completion_audit_requires_import_validation_command(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report()
    report.pop("post_import_validation_command")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_validation_command_missing" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_validation_command_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_current_raw_file_to_match_import_report(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report(raw_root=tmp_path)
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)
    (tmp_path / "exchange_info_raw.json").write_text("changed after import", encoding="utf-8")

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["manual_exchange_info_capture"]["raw_input_files"]["exchange_info_raw"][
        "current_file_verified"
    ] is False
    assert "btc_exchange_info_raw_import_current_file_mismatch" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_exchange_info_raw_import_current_file_mismatch" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_import_output_hashes_to_match_bundle(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report(raw_root=tmp_path)
    report["exchange_info_output_sha256"] = "0" * 64
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["manual_exchange_info_capture"]["import_bundle_dir"][
        "exchange_info_output_hash_verified"
    ] is False
    assert "btc_manual_metadata_import_exchange_info_output_hash_mismatch" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_exchange_info_output_hash_mismatch" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_import_bundle_dir(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report(raw_root=tmp_path)
    report.pop("bundle_dir")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_bundle_dir_missing" in requirements["manual_exchange_info_capture"]["blockers"]
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_bundle_dir_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_import_bundle_dir_to_match_selected_bundle(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report(raw_root=tmp_path)
    report["bundle_dir"] = "data/external/btc_perpetual/binance_usdm/bundles/not_selected"
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["manual_exchange_info_capture"]["import_bundle_dir"]["matches_selected_bundle"] is False
    assert "btc_manual_metadata_import_bundle_dir_not_selected_bundle" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_bundle_dir_not_selected_bundle" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_metadata_files_in_import_bundle(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report(raw_root=tmp_path)
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)
    (tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/fixture/funding_info.json").unlink()

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["manual_exchange_info_capture"]["import_bundle_dir"]["funding_info_exists"] is False
    assert "btc_manual_metadata_import_bundle_funding_info_missing" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_bundle_funding_info_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_import_report_schema_version(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report()
    report.pop("schema_version")
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_schema_version_missing_or_invalid" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_schema_version_missing_or_invalid" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_hypothesis_v2_hypothesis_only_manifest(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle/run_manifest.json",
        {
            "controlled_search_policy": {
                "mode": "hypothesis_level_only",
                "strategy_skeleton_generation_allowed": False,
                "candidate_generation_allowed": False,
                "paper_or_live_side_effects_allowed": False,
            },
            "strategy_skeleton_generated": False,
            "strategy_skeleton_path": "configs/btc/hypotheses/leaked_skeleton.yaml",
            "candidate_generation_allowed": False,
            "candidate_generated": False,
            "allowed_output_level": "hypothesis",
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "generated_artifacts": ["hypothesis_decision_v2.json", "strategy_skeleton.yaml"],
            "forbidden_outputs": ["strategy_skeleton", "candidate_config", "paper_order", "live_order", "broker_call"],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_hypothesis/20260517T020000Z_hypothesis_lab_v2_lifecycle/hypothesis_decision_v2.json",
        {"decision": "hypothesis_rejected", "strategy_skeleton_generated": False, "strategy_skeleton_path": ""},
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    hypothesis = payload["requirements"]["btc_hypothesis_lab_v2_controlled_search"]

    assert hypothesis["status"] == "incomplete"
    assert "btc_hypothesis_lab_v2_strategy_skeleton_path_empty_failed" in hypothesis["blockers"]
    assert "btc_hypothesis_lab_v2_generated_artifacts_hypothesis_only_failed" in hypothesis["blockers"]


def test_btc_objective_completion_audit_requires_funding_endpoint_response_for_completion(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "funding_info_endpoint_response_available": False,
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        _verified_import_report(raw_root=tmp_path),
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "complete"
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert requirements["funding_info_endpoint_policy_repair"]["endpoint_response_available"] is False
    assert "btc_funding_info_endpoint_response_not_available" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_requires_reconciled_funding_net_pnl(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json",
        {
            "funding_payment_in_ledger": True,
            "funding_merged_into_net_ledger": True,
            "funding_events_count": 1,
            "funding_payment_count": 1,
            "funding_adjusted_net_pnl_reconciled": False,
            "funding_adjusted_net_pnl_reconciliation_delta": 12.5,
            "trade_ledger_net_pnl_total": 100.0,
            "funding_pnl_total": -10.0,
            "expected_funding_adjusted_net_pnl_total": 90.0,
            "funding_adjusted_net_pnl_total": 102.5,
            "funding_adjusted_ledger_path": "artifacts/btc_cost_model/latest/funding_adjusted_trade_ledger.csv",
        },
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    funding_ledger = payload["requirements"]["funding_ledger_net_pnl_integration"]

    assert funding_ledger["status"] == "incomplete"
    assert funding_ledger["funding_payment_in_ledger"] is True
    assert funding_ledger["funding_merged_into_net_ledger"] is True
    assert funding_ledger["funding_adjusted_net_pnl_reconciled"] is False
    assert funding_ledger["funding_adjusted_net_pnl_reconciliation_delta"] == 12.5
    assert "btc_funding_adjusted_net_pnl_reconciliation_failed" in funding_ledger["blockers"]


def test_btc_objective_completion_audit_requires_funding_adjusted_csv_to_match_report(tmp_path: Path) -> None:
    ledger_path = tmp_path / "artifacts/btc_cost_model/latest/funding_adjusted_trade_ledger.csv"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        "trade_id,funding_pnl,net_pnl_before_funding,net_pnl_after_funding\n"
        "t1,-2.0,10.0,8.0\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json",
        {
            "funding_payment_in_ledger": True,
            "funding_merged_into_net_ledger": True,
            "funding_events_count": 1,
            "funding_payment_count": 1,
            "funding_adjusted_net_pnl_reconciled": True,
            "funding_adjusted_net_pnl_reconciliation_delta": 0.0,
            "funding_adjusted_trade_count": 1,
            "trade_ledger_net_pnl_total": 10.0,
            "funding_pnl_total": -2.0,
            "expected_funding_adjusted_net_pnl_total": 8.0,
            "funding_adjusted_net_pnl_total": 9.0,
            "funding_adjusted_ledger_path": "artifacts/btc_cost_model/latest/funding_adjusted_trade_ledger.csv",
        },
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    funding_ledger = payload["requirements"]["funding_ledger_net_pnl_integration"]

    assert funding_ledger["status"] == "incomplete"
    assert funding_ledger["funding_adjusted_ledger_exists"] is True
    assert funding_ledger["funding_adjusted_ledger_reconciled_to_report"] is False
    assert funding_ledger["funding_adjusted_ledger_net_pnl_after_total"] == 8.0
    assert "btc_funding_adjusted_trade_ledger_report_mismatch" in funding_ledger["blockers"]


def test_btc_objective_completion_audit_requires_positive_funding_payment_count(tmp_path: Path) -> None:
    ledger_path = tmp_path / "artifacts/btc_cost_model/latest/funding_adjusted_trade_ledger.csv"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_text(
        "trade_id,funding_pnl,net_pnl_before_funding,net_pnl_after_funding\n"
        "t1,0.0,10.0,10.0\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json",
        {
            "funding_payment_in_ledger": True,
            "funding_merged_into_net_ledger": True,
            "funding_events_count": 0,
            "funding_payment_count": 0,
            "funding_adjusted_net_pnl_reconciled": True,
            "funding_adjusted_net_pnl_reconciliation_delta": 0.0,
            "funding_adjusted_trade_count": 1,
            "trade_ledger_net_pnl_total": 10.0,
            "funding_pnl_total": 0.0,
            "expected_funding_adjusted_net_pnl_total": 10.0,
            "funding_adjusted_net_pnl_total": 10.0,
            "funding_adjusted_ledger_path": "artifacts/btc_cost_model/latest/funding_adjusted_trade_ledger.csv",
        },
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    funding_ledger = payload["requirements"]["funding_ledger_net_pnl_integration"]

    assert funding_ledger["status"] == "incomplete"
    assert "btc_funding_events_missing_for_ledger_integration" in funding_ledger["blockers"]
    assert "btc_funding_payments_missing_for_ledger_integration" in funding_ledger["blockers"]


def test_btc_objective_completion_audit_requires_import_capture_timestamp(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        {
            "schema_version": "btc_manual_metadata_import_report_v1",
            "status": "verified",
        "writes_performed": True,
        "exchange_info_verified": True,
        "funding_info_verified": True,
        "bundle_dir": "data/external/btc_perpetual/binance_usdm/bundles/fixture",
        "raw_input_files": {
                "exchange_info_raw": {
                    "path": "exchange_info_raw.json",
                    "exists": True,
                    "size_bytes": 100,
                    "sha256": "a" * 64,
                    "http_status_file": "exchange_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
                },
                "funding_info_raw": {
                    "path": "funding_info_raw.json",
                    "exists": True,
                    "size_bytes": 2,
                    "sha256": "b" * 64,
                    "http_status_file": "funding_info_http_status.txt",
                    "http_status": 200,
                    "http_status_verified": True,
                },
            },
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        },
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert requirements["manual_exchange_info_capture"]["import_captured_at"] is None
    assert "btc_manual_metadata_import_captured_at_missing" in requirements["manual_exchange_info_capture"]["blockers"]
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert requirements["funding_info_endpoint_policy_repair"]["import_captured_at"] is None
    assert "btc_manual_metadata_import_captured_at_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_rejects_import_with_false_verified_flags(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        _verified_import_report(exchange_info_verified=False, funding_info_verified=False),
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_exchange_info_not_verified" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert "btc_manual_metadata_import_funding_info_not_verified" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_exchange_info_not_verified" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )
    assert "btc_manual_metadata_import_funding_info_not_verified" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_rejects_import_with_malformed_timestamp_or_provenance(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    report = _verified_import_report(raw_root=tmp_path, captured_at="2026-05-22T08:00:00+08:00")
    raw = report["raw_input_files"]
    raw["exchange_info_raw"]["size_bytes"] = 0
    raw["funding_info_raw"]["sha256"] = "z" * 64
    _write_json(tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json", report)

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_captured_at_missing" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert "btc_exchange_info_raw_import_provenance_missing" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert "btc_funding_info_raw_import_provenance_missing" in (
        requirements["manual_exchange_info_capture"]["blockers"]
    )
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "incomplete"
    assert "btc_manual_metadata_import_captured_at_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )
    assert "btc_exchange_info_raw_import_provenance_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )
    assert "btc_funding_info_raw_import_provenance_missing" in (
        requirements["funding_info_endpoint_policy_repair"]["blockers"]
    )


def test_btc_objective_completion_audit_complete_metadata_clears_stale_capture_blockers(tmp_path: Path) -> None:
    _write_verified_metadata_inputs(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json",
        {
            "endpoint_results": {
                "exchange_info": {
                    "capture_status": "not_executed",
                    "http_status": None,
                    "blockers": ["btc_public_metadata_exchange_info_capture_not_executed"],
                },
                "funding_info": {
                    "capture_status": "not_executed",
                    "http_status": None,
                    "blockers": ["btc_public_metadata_funding_info_capture_not_executed"],
                },
            },
            "blockers": ["btc_public_metadata_capture_not_executed"],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        {
            "operator_action": "manual_capture_from_allowed_network",
            "blockers": ["btc_public_metadata_capture_not_executed"],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        _verified_import_report(raw_root=tmp_path),
    )

    payload = build_btc_objective_completion_audit_report(
        repo_root=tmp_path,
        generated_at="2026-05-22T00:00:00Z",
    )
    requirements = payload["requirements"]

    assert requirements["manual_exchange_info_capture"]["status"] == "complete"
    assert requirements["manual_exchange_info_capture"]["blockers"] == []
    assert requirements["funding_info_endpoint_policy_repair"]["status"] == "complete"
    assert requirements["funding_info_endpoint_policy_repair"]["blockers"] == []
    assert "btc_public_metadata_capture_not_executed" not in payload["blockers"]
    assert "btc_public_metadata_exchange_info_capture_not_executed" not in payload["blockers"]
    assert "btc_public_metadata_funding_info_capture_not_executed" not in payload["blockers"]


def _write_verified_metadata_inputs(tmp_path: Path) -> None:
    _write_selected_bundle(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "funding_info_endpoint_response_available": True,
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_readiness_report.json",
        {
            "exchange_info": {"manual_capture_required": False},
            "funding_info": {"manual_capture_required": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_public_metadata_capture_attempt_report.json",
        {
            "endpoint_results": {
                "exchange_info": {"capture_status": "captured", "http_status": 200, "blockers": []},
                "funding_info": {"capture_status": "captured", "http_status": 200, "blockers": []},
            },
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        {"operator_action": "no_manual_capture_required", "blockers": []},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_selected_bundle(tmp_path: Path) -> None:
    config = tmp_path / "configs/data/btc_perpetual_sources.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "\n".join(
            [
                "providers:",
                "  binance_usdm:",
                "    root: data/external/btc_perpetual/binance_usdm/",
                "    selected_bundle_id: fixture",
            ]
        ),
        encoding="utf-8",
    )
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/fixture"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "exchange_info.json").write_text("{}", encoding="utf-8")
    (bundle / "funding_info.json").write_text("{}", encoding="utf-8")


def _verified_import_report(
    *,
    exchange_info_verified: bool = True,
    funding_info_verified: bool = True,
    captured_at: str = "2026-05-22T00:00:00Z",
    raw_root: Path | None = None,
) -> dict[str, object]:
    if raw_root is not None:
        _write_raw_input(raw_root / "exchange_info_raw.json", b"x" * 100)
        _write_raw_input(raw_root / "funding_info_raw.json", b"{}")
    exchange_path = "exchange_info_raw.json"
    funding_path = "funding_info_raw.json"
    exchange_size = (raw_root / exchange_path).stat().st_size if raw_root is not None else 100
    funding_size = (raw_root / funding_path).stat().st_size if raw_root is not None else 2
    exchange_sha = _sha256(raw_root / exchange_path) if raw_root is not None else "a" * 64
    funding_sha = _sha256(raw_root / funding_path) if raw_root is not None else "b" * 64
    bundle_dir = "data/external/btc_perpetual/binance_usdm/bundles/fixture"
    exchange_output_path = f"{bundle_dir}/exchange_info.json"
    funding_output_path = f"{bundle_dir}/funding_info.json"
    exchange_output_sha = _sha256(raw_root / exchange_output_path) if raw_root is not None else "c" * 64
    funding_output_sha = _sha256(raw_root / funding_output_path) if raw_root is not None else "d" * 64
    return {
        "schema_version": "btc_manual_metadata_import_report_v1",
        "status": "verified",
        "writes_performed": True,
        "exchange_info_verified": exchange_info_verified,
        "funding_info_verified": funding_info_verified,
        "bundle_dir": bundle_dir,
        "captured_at": captured_at,
        "raw_input_files": {
            "exchange_info_raw": {
                "path": exchange_path,
                "exists": True,
                "size_bytes": exchange_size,
                "sha256": exchange_sha,
                "http_status_file": "exchange_info_http_status.txt",
                "http_status": 200,
                "http_status_verified": True,
            },
            "funding_info_raw": {
                "path": funding_path,
                "exists": True,
                "size_bytes": funding_size,
                "sha256": funding_sha,
                "http_status_file": "funding_info_http_status.txt",
                "http_status": 200,
                "http_status_verified": True,
            },
        },
        "exchange_info_output_path": exchange_output_path,
        "exchange_info_output_sha256": exchange_output_sha,
        "funding_info_output_path": funding_output_path,
        "funding_info_output_sha256": funding_output_sha,
        "post_import_validation_command": "make validate-btc-public-data-bundle",
        "blockers": [],
    }


def _write_raw_input(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
