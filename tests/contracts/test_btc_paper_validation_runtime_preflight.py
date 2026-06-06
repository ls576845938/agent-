from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import json
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import jsonschema
import pytest

import scripts.run_btc_paper_validation as btc_paper_runner
from quant_us.backtest.ledger_pnl import compute_ledger_reconciliation_artifact_hash
from scripts.check_btc_paper_validation_readiness import check_btc_paper_validation_readiness
from scripts.import_btc_manual_metadata_capture import MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
from scripts.run_btc_paper_validation import run_btc_paper_validation


MAKEFILE = Path("Makefile")
START_ATTEMPT_SCHEMA = Path("schemas/btc_paper_validation_start_attempt.schema.json")
RUN_REPORT_SCHEMA = Path("schemas/btc_paper_validation_run_report.schema.json")
SESSION_MANIFEST_SCHEMA = Path("schemas/btc_paper_validation_session_manifest.schema.json")


def test_current_btc_paper_validation_preflight_is_blocked() -> None:
    payload = check_btc_paper_validation_readiness(generated_at="2026-05-23T00:00:00Z")

    assert payload["schema_version"] == "btc_paper_validation_preflight_v1"
    assert payload["status"] == "BLOCKED"
    assert payload["execution_constraints"]["allows_live_orders"] is False
    assert payload["execution_constraints"]["real_order_submission"] is False
    assert "btc_paper_validation_readiness_report_blocked" in payload["blocking_reasons"]
    assert "btc_paper_validation_start_report_blocked" in payload["blocking_reasons"]
    assert "btc_paper_validation_candidate_metric_repair_blocked" in payload["blocking_reasons"]


def test_btc_paper_validation_preflight_passes_with_full_ready_fixture(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "PASS"
    assert payload["blocking_reasons"] == []
    assert payload["inputs"]["bundle_dir"].endswith("bundles/btc_ready_bundle")
    assert payload["bundle"]["interval_file"]["row_count"] == 2


def test_btc_paper_validation_preflight_blocks_stale_approved_review_evidence_hash(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    evidence = tmp_path / "data/research/evidence_packs/btc_review_001/evidence_pack.json"
    evidence.write_text(json.dumps({"paper_review_id": "btc_review_001", "mutated": True}), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    integrity_check = next(check for check in payload["checks"] if check["name"] == "approved_paper_review_integrity")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_approved_paper_review_integrity_blocked" in payload["blocking_reasons"]
    assert integrity_check["status"] == "BLOCKED"
    assert "btc_approved_paper_review_source_sha256_mismatch" in integrity_check["detail"]


def test_btc_paper_validation_preflight_blocks_approved_review_semantic_mismatch(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    readiness_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    review = readiness["approved_paper_review"]
    review["status"] = "APPROVED_FOR_LIVE"
    review["proposed_symbols"] = ["ETHUSDT"]
    review["approval"]["candidate_id"] = "btc_candidate_v2"
    review["approval"]["gate_snapshot"]["paper_execution_authorized"] = True
    review["approval"]["gate_snapshot"]["authorization_scope"] = "paper_execution"
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    integrity_check = next(check for check in payload["checks"] if check["name"] == "approved_paper_review_integrity")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_approved_paper_review_integrity_blocked" in payload["blocking_reasons"]
    assert "btc_approved_paper_review_status_not_paper_only" in integrity_check["detail"]
    assert "btc_approved_paper_review_symbol_scope_mismatch" in integrity_check["detail"]
    assert "btc_approved_paper_review_candidate_snapshot_mismatch" in integrity_check["detail"]
    assert "btc_approved_paper_review_scope_not_record_only" in integrity_check["detail"]
    assert "btc_approved_paper_review_scope_not_human_review_only" in integrity_check["detail"]


def test_btc_paper_validation_preflight_accepts_cli_style_approved_review_utc_offset(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    readiness_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["approved_paper_review"]["approval"]["timestamp"] = "2026-05-23T00:00:00+00:00"
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    integrity_check = next(check for check in payload["checks"] if check["name"] == "approved_paper_review_integrity")

    assert payload["status"] == "PASS"
    assert integrity_check["status"] == "PASS"


def test_btc_paper_validation_preflight_blocks_approved_review_evidence_outside_allowed_root(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    outside = tmp_path / "tmp/outside_evidence_pack.json"
    _write_json(outside, {"paper_review_id": "btc_review_001", "outside": True})
    readiness_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    review = readiness["approved_paper_review"]
    review["evidence_pack_path"] = str(outside)
    review["approval"]["source"] = str(outside)
    review["approval"]["source_sha256"] = _sha256(outside)
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    integrity_check = next(check for check in payload["checks"] if check["name"] == "approved_paper_review_integrity")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_approved_paper_review_integrity_blocked" in payload["blocking_reasons"]
    assert "btc_approved_paper_review_evidence_pack_path_outside_allowed_root" in integrity_check["detail"]
    assert "btc_approved_paper_review_source_path_outside_allowed_root" in integrity_check["detail"]


def test_btc_paper_validation_preflight_blocks_manual_metadata_import_marker_with_stale_ready_reports(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    marker = (
        tmp_path
        / "data/external/btc_perpetual/binance_usdm/bundles/btc_ready_bundle"
        / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
    )
    _write_json(
        marker,
        {
            "schema_version": "btc_manual_metadata_import_in_progress_v1",
            "generated_at": "2026-05-23T00:00:00Z",
            "bundle_id": "btc_ready_bundle",
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    marker_check = next(check for check in payload["checks"] if check["name"] == "manual_metadata_import_marker")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_manual_metadata_import_marker_blocked" in payload["blocking_reasons"]
    assert marker_check["status"] == "BLOCKED"
    assert marker_check["artifact_path"] == str(marker)


def test_btc_paper_validation_preflight_blocks_stale_manual_metadata_lineage_with_stale_ready_reports(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    exchange_info = (
        tmp_path
        / "data/external/btc_perpetual/binance_usdm/bundles/btc_ready_bundle/exchange_info.json"
    )
    _write_json(exchange_info, {"symbol": "BTCUSDT", "stale": "changed_after_report"})

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    lineage_check = next(check for check in payload["checks"] if check["name"] == "manual_metadata_import_lineage")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_manual_metadata_import_lineage_blocked" in payload["blocking_reasons"]
    assert lineage_check["status"] == "BLOCKED"
    assert "btc_manual_metadata_import_exchange_info_output_hash_mismatch" in lineage_check["detail"]


def test_btc_paper_validation_preflight_blocks_manual_metadata_import_without_raw_http_evidence(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    report_path = tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["raw_input_files"]["funding_info_raw"]["http_status"] = 451
    report["raw_input_files"]["funding_info_raw"]["http_status_verified"] = False
    status_path = tmp_path / report["raw_input_files"]["funding_info_raw"]["http_status_file"]
    status_path.write_text("451\n", encoding="utf-8")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    lineage_check = next(check for check in payload["checks"] if check["name"] == "manual_metadata_import_lineage")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_manual_metadata_import_lineage_blocked" in payload["blocking_reasons"]
    assert lineage_check["status"] == "BLOCKED"
    assert "btc_funding_info_raw_http_status_not_200" in lineage_check["detail"]


def test_btc_paper_validation_preflight_blocks_manual_metadata_import_without_post_import_validation(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    report_path = tmp_path / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["post_import_validation_command"] = "python3 scripts/build_btc_perpetual_provider_verification_report.py"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    lineage_check = next(check for check in payload["checks"] if check["name"] == "manual_metadata_import_lineage")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_manual_metadata_import_lineage_blocked" in payload["blocking_reasons"]
    assert lineage_check["status"] == "BLOCKED"
    assert "btc_manual_metadata_import_validation_command_missing" in lineage_check["detail"]


def test_btc_paper_validation_preflight_rejects_minimal_pass_shaped_dependency_reports(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "perpetual_evidence_ready": True,
            "exchange_info_verified": True,
            "funding_info_verified": True,
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {
            "status": "pass",
            "fee_model": {"fee_tier_verified": True, "taker_fee_bps": 4.0},
            "slippage_model": {"slippage_bps": 4.0},
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
        {"status": "pass", "candidate_passed_internal_gate": 1},
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_perpetual_provider_blocked" in payload["blocking_reasons"]
    assert "btc_paper_validation_cost_model_blocked" in payload["blocking_reasons"]
    assert "btc_paper_validation_candidate_gate_blocked" in payload["blocking_reasons"]


def test_btc_paper_validation_runner_does_not_start_with_manual_metadata_import_marker(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    marker = (
        tmp_path
        / "data/external/btc_perpetual/binance_usdm/bundles/btc_ready_bundle"
        / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
    )
    _write_json(
        marker,
        {
            "schema_version": "btc_manual_metadata_import_in_progress_v1",
            "generated_at": "2026-05-23T00:00:00Z",
            "bundle_id": "btc_ready_bundle",
        },
    )
    ledger = tmp_path / "data/paper_ledger/btc"

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))

    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_preflight_blocked"
    assert "btc_paper_validation_manual_metadata_import_marker_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not _ledger_start_lock_active(ledger)
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))


def test_btc_paper_validation_runner_does_not_start_with_stale_manual_metadata_lineage(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    exchange_info = (
        tmp_path
        / "data/external/btc_perpetual/binance_usdm/bundles/btc_ready_bundle/exchange_info.json"
    )
    _write_json(exchange_info, {"symbol": "BTCUSDT", "stale": "changed_after_report"})

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))

    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_preflight_blocked"
    assert "btc_paper_validation_manual_metadata_import_lineage_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()
    assert not _ledger_start_lock_active(ledger)


def test_btc_paper_validation_static_preflight_can_ignore_start_report_gate(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report["status"] = "blocked"
    start_report["paper_start_allowed"] = False
    start_report["paper_execution_authorized"] = False
    start_report["commands"] = {"start_command": ""}
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        require_start_report_ready=False,
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "PASS"
    assert payload["require_start_report_ready"] is False
    assert start_check["status"] == "PASS"
    assert "required=False" in start_check["detail"]


def test_btc_paper_validation_static_preflight_can_pass_without_start_report_file(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_path.unlink()

    static_payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        require_start_report_ready=False,
        generated_at="2026-05-23T00:00:00Z",
    )
    default_payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    static_start_check = next(check for check in static_payload["checks"] if check["name"] == "start_report")
    default_start_check = next(check for check in default_payload["checks"] if check["name"] == "start_report")

    assert static_payload["status"] == "PASS"
    assert static_payload["require_start_report_ready"] is False
    assert static_payload["blocking_reasons"] == []
    assert static_start_check["status"] == "PASS"
    assert "required=False" in static_start_check["detail"]
    assert "status=missing" in static_start_check["detail"]
    assert default_payload["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_blocked" in default_payload["blocking_reasons"]
    assert default_start_check["status"] == "BLOCKED"


def test_btc_paper_validation_preflight_rejects_wrapped_start_command(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report["commands"]["start_command"] = (
        "bash -lc 'python3 scripts/run_btc_paper_validation.py --symbols BTCUSDT "
        "--market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data'"
    )
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_blocked" in payload["blocking_reasons"]
    assert start_check["status"] == "BLOCKED"


def test_btc_paper_validation_preflight_rejects_ready_start_report_missing_safety_contract(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report.pop("safety")
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_blocked" in payload["blocking_reasons"]
    assert start_check["status"] == "BLOCKED"
    assert "status=ready_to_start_paper_validation" in start_check["detail"]
    assert "paper_start_allowed=True" in start_check["detail"]
    assert "btc_paper_validation_start_report_safety_missing" in start_check["detail"]


def test_btc_paper_validation_preflight_rejects_ready_start_report_with_unsafe_operator_contract(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report["operator_manual_unblock"]["safety"]["order_endpoints_allowed"] = True
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_blocked" in payload["blocking_reasons"]
    assert start_check["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_operator_safety_order_endpoints_allowed_not_false" in start_check["detail"]


def test_btc_paper_validation_preflight_rejects_ready_start_report_with_wrong_identity(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report["symbol"] = "ETHUSDT"
    start_report["market_type"] = "spot"
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_blocked" in payload["blocking_reasons"]
    assert start_check["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_symbol_invalid" in start_check["detail"]
    assert "btc_paper_validation_start_report_market_type_invalid" in start_check["detail"]


def test_btc_paper_validation_preflight_rejects_ready_start_report_with_internal_blockers(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report["blockers"] = ["btc_paper_validation_operator_packet_order_endpoints_allowed"]
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_blocked" in payload["blocking_reasons"]
    assert start_check["status"] == "BLOCKED"
    assert "btc_paper_validation_start_report_has_blockers" in start_check["detail"]


def test_btc_paper_validation_preflight_accepts_resume_ready_start_report(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    start_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json"
    start_report = json.loads(start_path.read_text(encoding="utf-8"))
    start_report["commands"]["start_command"] = ""
    start_report["commands"]["resume_command"] = (
        "python3 scripts/run_btc_paper_validation.py --repo-root . --symbols BTCUSDT "
        "--market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data --resume"
    )
    start_report["next_required_action"] = "resume_paper_validation"
    start_path.write_text(json.dumps(start_report, indent=2, sort_keys=True), encoding="utf-8")
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 0,
                    "fills": 0,
                }
            ],
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )
    start_check = next(check for check in payload["checks"] if check["name"] == "start_report")

    assert payload["status"] == "PASS"
    assert start_check["status"] == "PASS"
    assert payload["blocking_reasons"] == []


def test_btc_paper_validation_preflight_requires_bound_cost_model(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    cost_path = tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json"
    _write_json(cost_path, {"status": "pass"})

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert cost_path.exists()
    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_cost_model_blocked" in payload["blocking_reasons"]
    cost_check = next(check for check in payload["checks"] if check["name"] == "cost_model")
    assert "fee_tier_verified=False" in cost_check["detail"]
    assert "slippage_bps=missing" in cost_check["detail"]


def test_btc_paper_validation_preflight_requires_candidate_metric_repair_pass(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    repair_path = tmp_path / "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json"
    _write_json(
        repair_path,
        {
            "status": "needs_metric_repair",
            "promotion_allowed": False,
            "paper_review_pending_allowed": False,
            "failed_metrics": ["event_profit_factor"],
            "blockers": ["btc_candidate_metric_repair_event_profit_factor_failed"],
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_candidate_metric_repair_blocked" in payload["blocking_reasons"]
    repair_check = next(check for check in payload["checks"] if check["name"] == "candidate_metric_repair")
    assert "status=needs_metric_repair" in repair_check["detail"]
    assert "failed_metrics=event_profit_factor" in repair_check["detail"]
    assert repair_check["facts"] == {
        "schema_version": "missing",
        "status": "needs_metric_repair",
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "failed_metrics": ["event_profit_factor"],
        "blockers": ["btc_candidate_metric_repair_event_profit_factor_failed"],
    }


def test_btc_paper_validation_preflight_blocks_unclean_previous_reconciliation(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 0,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": False,
                    "equity_consistent": False,
                    "reconciliation_status": "breaks_detected",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 1,
                    "fills": 1,
                }
            ],
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    recon_check = next(check for check in payload["checks"] if check["name"] == "ledger_reconciliation")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_reconciliation_blocked" in payload["blocking_reasons"]
    assert recon_check["status"] == "BLOCKED"
    assert "reconciliation_status=breaks_detected" in recon_check["detail"]


def test_btc_paper_validation_preflight_blocks_unclean_history_even_when_latest_clean(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    unclean_recon_path, unclean_recon_hash = _write_reconciliation_artifact(ledger, passed=False)
    clean_recon_path, clean_recon_hash = _write_reconciliation_artifact(ledger, passed=True)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 2,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["unclean_cycle", "clean_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_unclean",
                    "cycle_key": "unclean_cycle",
                    "clean": False,
                    "equity_consistent": False,
                    "reconciliation_status": "breaks_detected",
                    "ledger_reconciliation_artifact_path": str(unclean_recon_path),
                    "ledger_reconciliation_artifact_hash": unclean_recon_hash,
                    "orders": 1,
                    "fills": 1,
                },
                {
                    "run_id": "btc_paper_clean",
                    "cycle_key": "clean_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(clean_recon_path),
                    "ledger_reconciliation_artifact_hash": clean_recon_hash,
                    "orders": 0,
                    "fills": 0,
                },
            ],
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    recon_check = next(check for check in payload["checks"] if check["name"] == "ledger_reconciliation")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_reconciliation_blocked" in payload["blocking_reasons"]
    assert recon_check["status"] == "BLOCKED"
    assert "history_blockers=" in recon_check["detail"]
    assert "unclean_cycle" in recon_check["facts"]["failed_cycle_keys"]
    assert "btc_validation_state_daily_not_clean" in recon_check["facts"]["history_blockers"]
    assert "btc_ledger_reconciliation_artifact_integrity_not_pass" in recon_check["facts"]["history_blockers"]


def test_btc_paper_validation_preflight_blocks_validation_state_cycle_count_mismatch(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 30,
            "consecutive_clean_days": 30,
            "completed_cycle_keys": ["only_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_clean",
                    "cycle_key": "only_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 0,
                    "fills": 0,
                }
            ],
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    recon_check = next(check for check in payload["checks"] if check["name"] == "ledger_reconciliation")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_reconciliation_blocked" in payload["blocking_reasons"]
    assert "btc_validation_state_cycle_counts_mismatch" in recon_check["facts"]["history_blockers"]


def test_btc_paper_validation_preflight_blocks_clean_state_with_missing_reconciliation_artifact(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    missing_artifact = ledger / "reconciliation/ledger_recon_artifact_missing.json"
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(missing_artifact),
                    "ledger_reconciliation_artifact_hash": "0" * 64,
                    "orders": 0,
                    "fills": 0,
                }
            ],
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    recon_check = next(check for check in payload["checks"] if check["name"] == "ledger_reconciliation")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_reconciliation_blocked" in payload["blocking_reasons"]
    assert "btc_ledger_reconciliation_artifact_file_missing" in recon_check["detail"]
    assert recon_check["facts"]["artifact_path"].endswith("reconciliation/ledger_recon_artifact_missing.json")
    assert recon_check["facts"]["artifact_hash"] == "0" * 64
    assert recon_check["facts"]["artifact_blockers"] == ["btc_ledger_reconciliation_artifact_file_missing"]


def test_btc_paper_validation_preflight_blocks_unsafe_ledger(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    ledger.mkdir(parents=True)
    (ledger / "orders.jsonl").write_text(
        json.dumps({"symbol": "ETHUSDT", "broker": "live"}) + "\n",
        encoding="utf-8",
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_root_blocked" in payload["blocking_reasons"]


def test_btc_paper_validation_preflight_blocks_in_progress_cycle_marker(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    marker = ledger / "audit/paper_validation_in_progress/btc_paper_partial.json"
    _write_json(
        marker,
        {
            "schema_version": "btc_paper_validation_in_progress_cycle_v1",
            "run_id": "btc_paper_partial",
            "cycle_key": "partial_cycle",
            "status": "ledger_write_pending",
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    ledger_check = next(check for check in payload["checks"] if check["name"] == "ledger_root")

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_root_blocked" in payload["blocking_reasons"]
    assert ledger_check["status"] == "BLOCKED"
    assert "in_progress_cycle_markers=btc_paper_partial.json" in ledger_check["detail"]
    assert "in_progress_cycle_marker_statuses=btc_paper_partial.json:parse_ok:ledger_write_pending" in ledger_check["detail"]
    assert "run_id=btc_paper_partial" in ledger_check["detail"]
    assert "cycle_key=partial_cycle" in ledger_check["detail"]
    assert ledger_check["facts"]["in_progress_cycle_markers"] == ["btc_paper_partial.json"]
    assert ledger_check["facts"]["in_progress_cycle_marker_statuses"] == [
        "btc_paper_partial.json:parse_ok:ledger_write_pending:run_id=btc_paper_partial:cycle_key=partial_cycle"
    ]
    assert ledger_check["facts"]["start_lock"] == ""


def test_btc_paper_validation_preflight_blocks_ledger_root_start_lock(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    start_lock = btc_paper_runner._claim_ledger_start_lock(
        ledger=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    assert start_lock is not None

    try:
        payload = check_btc_paper_validation_readiness(
            repo_root=tmp_path,
            ledger_root=ledger,
            generated_at="2026-05-23T00:00:00Z",
        )
        ledger_check = next(check for check in payload["checks"] if check["name"] == "ledger_root")
    finally:
        btc_paper_runner._clear_ledger_start_lock(start_lock)

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_root_blocked" in payload["blocking_reasons"]
    assert ledger_check["status"] == "BLOCKED"
    assert f"start_lock={btc_paper_runner.LEDGER_START_LOCK_NAME}" in ledger_check["detail"]


def test_btc_paper_validation_preflight_ignores_stale_ledger_root_start_lock_file(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    _write_json(
        ledger / "audit" / btc_paper_runner.LEDGER_START_LOCK_NAME,
        {
            "schema_version": "btc_paper_validation_ledger_start_lock_v1",
            "claim_id": "stale-start",
            "owner_pid": 999999999,
            "status": "start_claimed",
        },
    )

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    ledger_check = next(check for check in payload["checks"] if check["name"] == "ledger_root")

    assert payload["status"] == "PASS"
    assert ledger_check["status"] == "PASS"
    assert "start_lock=(none)" in ledger_check["detail"]


def test_btc_paper_validation_preflight_blocks_review_without_recorded_approval(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    readiness_path = tmp_path / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    readiness["approved_paper_review"].pop("approval", None)
    readiness_path.write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")

    payload = check_btc_paper_validation_readiness(
        repo_root=tmp_path,
        ledger_root=tmp_path / "data/paper_ledger/btc",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "BLOCKED"
    assert "btc_paper_validation_approved_paper_review_blocked" in payload["blocking_reasons"]


def test_btc_paper_validation_runner_writes_blocked_attempt_without_starting(tmp_path: Path) -> None:
    ledger = tmp_path / "paper_ledger/btc"

    payload = run_btc_paper_validation(
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )

    attempt_path = ledger / "audit/btc_paper_validation_start_attempt.json"
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_preflight_blocked"
    assert attempt["paper_broker"] == "simulated"
    assert attempt["broker_backend"] == "simulated"
    assert attempt["real_order_submission"] is False
    assert attempt["allows_live_orders"] is False
    assert attempt["orders_require_risk_engine"] is True
    assert attempt["pnl_source"] == "fills_and_ledger"
    assert attempt["network_required"] is False
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert not _ledger_start_lock_active(ledger)


def test_btc_paper_validation_start_attempt_schema_rejects_execution_claims(tmp_path: Path) -> None:
    ledger = tmp_path / "paper_ledger/btc"
    run_btc_paper_validation(
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))
    attempt["real_order_submission"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(attempt, schema)


def test_btc_paper_validation_start_attempt_schema_rejects_missing_blockers(tmp_path: Path) -> None:
    ledger = tmp_path / "paper_ledger/btc"
    run_btc_paper_validation(
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))
    attempt["preflight_blocking_reasons"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(attempt, schema)


def test_btc_paper_validation_start_attempt_schema_allows_non_preflight_block_with_clean_preflight(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    ledger.mkdir(parents=True)
    (ledger / "orders.jsonl").write_text(
        json.dumps({"symbol": "BTCUSDT", "broker": "simulated"}) + "\n",
        encoding="utf-8",
    )

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_ledger_not_empty_without_resume"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []


def test_btc_paper_validation_runner_rejects_unapproved_strategy_override_before_ledger_write(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        strategy_id="unapproved_btc_strategy",
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_strategy_binding_failed"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_rejects_unapproved_strategy_params_before_ledger_write(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        strategy_params={"fast_window": 12},
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_strategy_binding_failed"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_blocks_resume_without_existing_state(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        resume=True,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_resume_without_existing_state"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()


def test_btc_paper_validation_runner_blocks_resume_with_malformed_validation_state(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    _write_json(ledger / "validation_state.json", {"foo": "bar"})

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        resume=True,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_reconciliation_not_clean"
    assert attempt["preflight_status"] == "BLOCKED"
    assert "btc_paper_validation_ledger_reconciliation_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_blocks_start_when_existing_session_requires_resume(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 0,
                    "fills": 0,
                }
            ],
        },
    )

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_existing_session_requires_resume"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()


def test_btc_paper_validation_runner_resume_allows_existing_state_and_counts_next_cycle(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 1,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": True,
                    "equity_consistent": True,
                    "reconciliation_status": "clean",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 0,
                    "fills": 0,
                }
            ],
        },
    )

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
        resume=True,
        generated_at="2026-05-23T00:00:00Z",
    )
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    report = json.loads((ledger / "validation_report.json").read_text(encoding="utf-8"))

    jsonschema.validate(report, json.loads(RUN_REPORT_SCHEMA.read_text(encoding="utf-8")))
    assert payload["status"] == "IN_PROGRESS"
    assert state["days_completed"] == 2
    assert state["consecutive_clean_days"] == 2
    assert len(state["completed_cycle_keys"]) == 2
    assert not (ledger / "audit/btc_paper_validation_start_attempt.json").exists()


def test_btc_paper_validation_runner_blocks_resume_after_unclean_reconciliation(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    recon_path, recon_hash = _write_reconciliation_artifact(ledger)
    _write_json(
        ledger / "validation_state.json",
        {
            "schema_version": "btc_paper_validation_state_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "days_required": 30,
            "days_completed": 1,
            "consecutive_clean_days": 0,
            "completed_cycle_keys": ["previous_cycle"],
            "daily_results": [
                {
                    "run_id": "btc_paper_previous",
                    "cycle_key": "previous_cycle",
                    "clean": False,
                    "equity_consistent": False,
                    "reconciliation_status": "breaks_detected",
                    "ledger_reconciliation_artifact_path": str(recon_path),
                    "ledger_reconciliation_artifact_hash": recon_hash,
                    "orders": 1,
                    "fills": 1,
                }
            ],
        },
    )
    counts_before = _jsonl_line_counts(ledger)

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        resume=True,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_reconciliation_not_clean"
    assert "btc_paper_validation_ledger_reconciliation_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == counts_before
    assert not (ledger / "validation_report.json").exists()


def test_btc_paper_validation_runner_does_not_start_with_in_progress_cycle_marker(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    _write_json(
        ledger / "audit/paper_validation_in_progress/btc_paper_partial.json",
        {
            "schema_version": "btc_paper_validation_in_progress_cycle_v1",
            "run_id": "btc_paper_partial",
            "cycle_key": "partial_cycle",
            "status": "ledger_write_pending",
        },
    )

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        resume=True,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_preflight_blocked"
    assert "btc_paper_validation_ledger_root_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()


def test_btc_paper_validation_runner_claims_cycle_before_backtest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledBacktestCrash(RuntimeError):
        pass

    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    def fake_backtest(**_kwargs: object) -> SimpleNamespace:
        markers = sorted((ledger / "audit/paper_validation_in_progress").glob("*.json"))
        assert len(markers) == 1
        marker = json.loads(markers[0].read_text(encoding="utf-8"))
        assert marker["status"] == "backtest_running"
        raise ControlledBacktestCrash("stop before ledger write")

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", fake_backtest)

    with pytest.raises(ControlledBacktestCrash):
        run_btc_paper_validation(
            repo_root=tmp_path,
            ledger_root=ledger,
            generated_at="2026-05-23T00:00:00Z",
        )

    markers = sorted((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert len(markers) == 1
    assert json.loads(markers[0].read_text(encoding="utf-8"))["status"] == "backtest_running"
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_releases_start_lock_on_pre_backtest_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledBundleLoadCrash(RuntimeError):
        pass

    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    def fake_load_bundle_frame(*_args: object, **_kwargs: object) -> object:
        assert _ledger_start_lock_active(ledger)
        raise ControlledBundleLoadCrash("stop after start lock before cycle marker")

    monkeypatch.setattr(btc_paper_runner, "_load_bundle_frame", fake_load_bundle_frame)

    with pytest.raises(ControlledBundleLoadCrash):
        run_btc_paper_validation(
            repo_root=tmp_path,
            ledger_root=ledger,
            generated_at="2026-05-23T00:00:00Z",
        )

    assert not _ledger_start_lock_active(ledger)
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()


def test_btc_paper_validation_runner_allows_only_one_atomic_cycle_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    cycle_start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc)
    original_preflight = btc_paper_runner.check_btc_paper_validation_readiness
    original_backtest = btc_paper_runner.run_crypto_event_backtest
    preflight_barrier = Barrier(2)
    backtest_calls: list[int] = []

    def gated_preflight(**kwargs: object) -> dict[str, object]:
        payload = original_preflight(**kwargs)
        preflight_barrier.wait(timeout=5)
        return payload

    def counted_backtest(**kwargs: object) -> object:
        backtest_calls.append(1)
        return original_backtest(**kwargs)

    monkeypatch.setattr(btc_paper_runner, "check_btc_paper_validation_readiness", gated_preflight)
    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", counted_backtest)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                run_btc_paper_validation,
                repo_root=tmp_path,
                ledger_root=ledger,
                start=cycle_start,
                end=cycle_end,
                generated_at="2026-05-23T00:00:00Z",
            )
            for _ in range(2)
        ]
        payloads = [future.result(timeout=10) for future in futures]

    blocked = [payload for payload in payloads if payload["status"] == "BLOCKED"]
    started = [payload for payload in payloads if payload["status"] in {"IN_PROGRESS", "PASS"}]
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    history = sorted((ledger / "audit/paper_session_manifests").glob("*.json"))

    assert len(started) == 1
    assert len(blocked) == 1
    assert blocked[0]["reason"] in {
        "btc_paper_validation_ledger_root_start_lock_held",
        "btc_paper_validation_concurrent_start_claimed",
        "btc_paper_validation_incomplete_cycle_recovery_required",
    }
    assert len(backtest_calls) == 1
    assert len(state["completed_cycle_keys"]) == 1
    assert len(state["daily_results"]) == 1
    assert len(history) == 1
    assert _jsonl_line_counts(ledger)["orders.jsonl"] == int(started[0]["diagnostics"]["orders"])
    assert _jsonl_line_counts(ledger)["fills.jsonl"] == int(started[0]["diagnostics"]["fills"])
    assert not (ledger / "audit/paper_validation_in_progress" / f"{started[0]['run_id']}.json").exists()


def test_btc_paper_validation_runner_allows_only_one_ledger_root_start_across_cycles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    bundle = tmp_path / "data/external/btc_perpetual/binance_usdm/bundles/btc_ready_bundle"
    (bundle / "klines_1h.csv").write_text(
        "\n".join(
            [
                "timestamp,open_time_ms,open,high,low,close,volume",
                "2026-05-22T00:00:00Z,1779408000000,100,110,90,105,10",
                "2026-05-22T01:00:00Z,1779411600000,105,111,101,108,12",
                "2026-05-22T02:00:00Z,1779415200000,108,112,104,109,13",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    windows = [
        (
            datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 22, 2, 0, tzinfo=timezone.utc),
        ),
    ]
    original_preflight = btc_paper_runner.check_btc_paper_validation_readiness
    original_backtest = btc_paper_runner.run_crypto_event_backtest
    preflight_barrier = Barrier(2)
    backtest_entered = Barrier(2)
    backtest_calls: list[str] = []

    def gated_preflight(**kwargs: object) -> dict[str, object]:
        payload = original_preflight(**kwargs)
        preflight_barrier.wait(timeout=5)
        return payload

    def blocking_backtest(**kwargs: object) -> object:
        backtest_calls.append(str(kwargs.get("run_id", "")))
        backtest_entered.wait(timeout=5)
        backtest_entered.wait(timeout=5)
        return original_backtest(**kwargs)

    monkeypatch.setattr(btc_paper_runner, "check_btc_paper_validation_readiness", gated_preflight)
    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", blocking_backtest)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                run_btc_paper_validation,
                repo_root=tmp_path,
                ledger_root=ledger,
                start=window_start,
                end=window_end,
                generated_at="2026-05-23T00:00:00Z",
            )
            for window_start, window_end in windows
        ]
        backtest_entered.wait(timeout=5)
        done, _pending = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
        assert len(done) == 1
        blocked_payload = next(iter(done)).result(timeout=1)
        assert blocked_payload["status"] == "BLOCKED"
        assert blocked_payload["reason"] == "btc_paper_validation_ledger_root_start_lock_held"
        backtest_entered.wait(timeout=5)
        payloads = [future.result(timeout=10) for future in futures]

    blocked = [payload for payload in payloads if payload["status"] == "BLOCKED"]
    started = [payload for payload in payloads if payload["status"] in {"IN_PROGRESS", "PASS"}]
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    history = sorted((ledger / "audit/paper_session_manifests").glob("*.json"))

    assert len(started) == 1
    assert len(blocked) == 1
    assert len(backtest_calls) == 1
    assert len(state["completed_cycle_keys"]) == 1
    assert len(state["daily_results"]) == 1
    assert len(history) == 1
    assert _jsonl_line_counts(ledger)["orders.jsonl"] == int(started[0]["diagnostics"]["orders"])
    assert _jsonl_line_counts(ledger)["fills.jsonl"] == int(started[0]["diagnostics"]["fills"])
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert not _ledger_start_lock_active(ledger)


def test_btc_paper_validation_runner_writes_schema_valid_simulated_cycle_artifacts(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    report = json.loads((ledger / "validation_report.json").read_text(encoding="utf-8"))
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    manifest = json.loads((ledger / "audit/paper_session_manifest.json").read_text(encoding="utf-8"))
    history = json.loads(
        (ledger / "audit/paper_session_manifests" / f"{payload['run_id']}.json").read_text(encoding="utf-8")
    )
    startup_sync = json.loads((ledger / "audit/paper_broker_adapter_startup_sync.json").read_text(encoding="utf-8"))

    jsonschema.validate(report, json.loads(RUN_REPORT_SCHEMA.read_text(encoding="utf-8")))
    jsonschema.validate(manifest, json.loads(SESSION_MANIFEST_SCHEMA.read_text(encoding="utf-8")))
    jsonschema.validate(history, json.loads(SESSION_MANIFEST_SCHEMA.read_text(encoding="utf-8")))
    assert payload["status"] == "IN_PROGRESS"
    assert report["execution"]["real_order_submission"] is False
    assert report["execution"]["allows_live_orders"] is False
    assert report["execution"]["cost_model_report"].endswith("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
    assert report["execution"]["commission_rate"] == 0.0004
    assert report["execution"]["slippage_bps"] == 4.0
    assert report["preflight"]["status"] == "PASS"
    assert report["risk_gate"]["enforced"] is True
    assert report["risk_gate"]["risk_check_count"] >= report["risk_gate"]["order_count"]
    assert report["risk_gate"]["all_orders_created_by_oms"] is True
    assert report["risk_gate"]["all_orders_have_risk_check_id"] is True
    assert report["diagnostics"]["ledger_equity_consistent"] is True
    assert report["diagnostics"]["reconciliation"]["passed"] is True
    assert state["days_completed"] == 1
    assert state["consecutive_clean_days"] == 1
    assert state["daily_results"][0]["reconciliation_status"] == "clean"
    daily_recon_path = Path(state["daily_results"][0]["ledger_reconciliation_artifact_path"])
    daily_recon_hash = state["daily_results"][0]["ledger_reconciliation_artifact_hash"]
    daily_recon = json.loads(daily_recon_path.read_text(encoding="utf-8"))
    assert daily_recon_path == Path(report["ledger_reconciliation_artifact_path"])
    assert daily_recon["artifact_hash"] == daily_recon_hash
    assert compute_ledger_reconciliation_artifact_hash(daily_recon) == daily_recon_hash
    assert manifest == history
    assert manifest["cost_model_report"].endswith("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
    assert manifest["commission_rate"] == 0.0004
    assert manifest["slippage_bps"] == 4.0
    assert manifest["risk_gate"] == report["risk_gate"]
    assert manifest["no_real_order_submission_proof"]["order_endpoint_used"] is False
    assert startup_sync["paper_broker"] == "simulated"
    assert startup_sync["real_order_submission"] is False
    assert not (ledger / "audit/paper_validation_in_progress" / f"{payload['run_id']}.json").exists()
    assert not (ledger / "audit/btc_paper_validation_start_attempt.json").exists()


def test_btc_paper_validation_runner_blocks_cost_override_mismatch(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        commission_rate=0.0,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_cost_override_mismatch"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert not (ledger / "validation_report.json").exists()


def test_btc_paper_validation_runner_blocks_unenforced_risk_gate_before_ledger_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    def fake_backtest(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            unified=SimpleNamespace(
                evidence={
                    "orders": {
                        "count": 1,
                        "all_orders_created_by_oms": True,
                        "all_orders_have_risk_check_id": False,
                    },
                    "risk": {
                        "risk_check_count": 0,
                        "approved": 0,
                        "rejected": 0,
                        "rejection_reasons": {},
                    },
                },
            ),
        )

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", fake_backtest)

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_risk_gate_not_enforced"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))


def test_btc_paper_validation_runner_allows_clean_retry_after_risk_gate_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    original_backtest = btc_paper_runner.run_crypto_event_backtest

    def fake_unenforced_backtest(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            unified=SimpleNamespace(
                evidence={
                    "orders": {
                        "count": 1,
                        "all_orders_created_by_oms": True,
                        "all_orders_have_risk_check_id": False,
                    },
                    "risk": {
                        "risk_check_count": 0,
                        "approved": 0,
                        "rejected": 0,
                        "rejection_reasons": {},
                    },
                },
            ),
        )

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", fake_unenforced_backtest)
    blocked = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt_path = ledger / "audit/btc_paper_validation_start_attempt.json"
    attempt = json.loads(attempt_path.read_text(encoding="utf-8"))

    assert blocked["status"] == "BLOCKED"
    assert blocked["reason"] == "btc_paper_validation_risk_gate_not_enforced"
    assert attempt["reason"] == "btc_paper_validation_risk_gate_not_enforced"
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", original_backtest)
    retry = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:01:00Z",
    )
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))

    assert retry["status"] == "IN_PROGRESS"
    assert state["days_completed"] == 1
    assert len(state["completed_cycle_keys"]) == 1
    assert len(state["daily_results"]) == 1
    assert _jsonl_line_counts(ledger)["orders.jsonl"] == int(retry["diagnostics"]["orders"])
    assert _jsonl_line_counts(ledger)["fills.jsonl"] == int(retry["diagnostics"]["fills"])
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert not attempt_path.exists()


def test_btc_paper_validation_runner_overwrites_stale_clean_block_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    def fake_unenforced_backtest(**_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            unified=SimpleNamespace(
                evidence={
                    "orders": {
                        "count": 1,
                        "all_orders_created_by_oms": True,
                        "all_orders_have_risk_check_id": False,
                    },
                    "risk": {
                        "risk_check_count": 0,
                        "approved": 0,
                        "rejected": 0,
                        "rejection_reasons": {},
                    },
                },
            ),
        )

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", fake_unenforced_backtest)
    first = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt_path = ledger / "audit/btc_paper_validation_start_attempt.json"
    first_attempt = json.loads(attempt_path.read_text(encoding="utf-8"))

    second = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        commission_rate=0.0,
        generated_at="2026-05-23T00:01:00Z",
    )
    second_attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(second_attempt, schema)
    assert first["status"] == "BLOCKED"
    assert first_attempt["reason"] == "btc_paper_validation_risk_gate_not_enforced"
    assert second["status"] == "BLOCKED"
    assert second["reason"] == "btc_paper_validation_cost_override_mismatch"
    assert second_attempt["generated_at"] == "2026-05-23T00:01:00Z"
    assert second_attempt["reason"] == "btc_paper_validation_cost_override_mismatch"
    assert second_attempt["preflight_status"] == "PASS"
    assert second_attempt["preflight_blocking_reasons"] == []
    assert "btc_paper_validation_risk_gate_not_enforced" not in json.dumps(second_attempt, sort_keys=True)
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert not _ledger_start_lock_active(ledger)
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()


def test_btc_paper_validation_start_attempt_write_is_atomic_on_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledAtomicReplaceCrash(RuntimeError):
        pass

    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    first = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        strategy_id="unapproved_btc_strategy",
        generated_at="2026-05-23T00:00:00Z",
    )
    attempt_path = ledger / "audit/btc_paper_validation_start_attempt.json"
    original_attempt_text = attempt_path.read_text(encoding="utf-8")
    original_attempt = json.loads(original_attempt_text)
    original_replace = btc_paper_runner.os.replace

    def crash_attempt_replace(src: object, dst: object) -> None:
        if Path(dst).name == "btc_paper_validation_start_attempt.json":
            raise ControlledAtomicReplaceCrash("stop before atomic attempt replace")
        original_replace(src, dst)

    monkeypatch.setattr(btc_paper_runner.os, "replace", crash_attempt_replace)

    with pytest.raises(ControlledAtomicReplaceCrash):
        run_btc_paper_validation(
            repo_root=tmp_path,
            ledger_root=ledger,
            commission_rate=0.0,
            generated_at="2026-05-23T00:01:00Z",
        )

    assert first["status"] == "BLOCKED"
    assert original_attempt["reason"] == "btc_paper_validation_strategy_binding_failed"
    assert attempt_path.read_text(encoding="utf-8") == original_attempt_text
    assert json.loads(attempt_path.read_text(encoding="utf-8")) == original_attempt
    assert not list((ledger / "audit").glob(".btc_paper_validation_start_attempt.json.*.tmp"))
    assert _jsonl_line_counts(ledger) == {
        "orders.jsonl": 0,
        "fills.jsonl": 0,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not list((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert not _ledger_start_lock_active(ledger)
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()


def test_btc_paper_validation_runner_blocks_partial_crash_replay_before_ledger_write(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    cycle_start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc)
    partial_run_id = "btc_paper_20260522T000000Z_20260522T010000Z_btc_perp_dual_trend"
    _append_jsonl(
        ledger / "orders.jsonl",
        {
            "timestamp_utc": "2026-05-22T00:00:00Z",
            "strategy_id": "btc_perp_dual_trend",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.1,
            "order_type": "market",
            "time_in_force": "day",
            "client_order_id": "partial_crash_order",
            "run_id": partial_run_id,
            "broker": "simulated",
            "status": "risk_checked",
            "risk_check_id": "risk_partial_crash",
            "order_id": "partial_crash_order",
        },
    )
    _append_jsonl(
        ledger / "fills.jsonl",
        {
            "order_id": "partial_crash_order",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.1,
            "price": 105.0,
            "commission": 0.0042,
            "filled_at": "2026-05-22T01:00:00Z",
            "broker": "simulated",
            "fill_id": "partial_crash_fill",
        },
    )
    counts_before = _jsonl_line_counts(ledger)

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=cycle_start,
        end=cycle_end,
        resume=True,
        generated_at="2026-05-24T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_incomplete_cycle_recovery_required"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == counts_before
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_blocks_restart_after_ledger_write_pending_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledPostLedgerWriteCrash(RuntimeError):
        pass

    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    cycle_start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc)
    backtest_calls: list[str] = []

    def fake_backtest(**kwargs: object) -> SimpleNamespace:
        run_id = str(kwargs["run_id"])
        backtest_calls.append(run_id)
        return SimpleNamespace(
            unified=SimpleNamespace(
                event_driven=SimpleNamespace(
                    orders=[
                        {
                            "timestamp_utc": "2026-05-22T00:00:00Z",
                            "strategy_id": "btc_perp_dual_trend",
                            "symbol": "BTCUSDT",
                            "side": "buy",
                            "quantity": 0.1,
                            "order_type": "market",
                            "time_in_force": "day",
                            "client_order_id": f"{run_id}:order",
                            "run_id": run_id,
                            "broker": "simulated",
                            "status": "risk_checked",
                            "risk_check_id": f"{run_id}:risk",
                            "order_id": f"{run_id}:order",
                        }
                    ],
                    fills=[
                        {
                            "order_id": f"{run_id}:order",
                            "symbol": "BTCUSDT",
                            "side": "buy",
                            "quantity": 0.1,
                            "price": 105.0,
                            "commission": 0.0042,
                            "filled_at": "2026-05-22T01:00:00Z",
                            "broker": "simulated",
                            "fill_id": f"{run_id}:fill",
                        }
                    ],
                    snapshots=[{"timestamp_utc": "2026-05-22T01:00:00Z", "cash": 24989.4958, "run_id": run_id}],
                    events=[{"timestamp_utc": "2026-05-22T01:00:00Z", "event_type": "fill", "run_id": run_id}],
                ),
                evidence={
                    "orders": {
                        "count": 1,
                        "all_orders_created_by_oms": True,
                        "all_orders_have_risk_check_id": True,
                    },
                    "risk": {
                        "risk_check_count": 1,
                        "approved": 1,
                        "rejected": 0,
                        "rejection_reasons": {},
                    },
                },
                equity_consistent=True,
            ),
            summary={},
            diagnostics={},
        )

    def crash_after_write_result(*_args: object, **_kwargs: object) -> object:
        raise ControlledPostLedgerWriteCrash("stop after ledger write_result")

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", fake_backtest)
    monkeypatch.setattr(btc_paper_runner, "build_ledger_reconciliation_artifact", crash_after_write_result)

    with pytest.raises(ControlledPostLedgerWriteCrash):
        run_btc_paper_validation(
            repo_root=tmp_path,
            ledger_root=ledger,
            start=cycle_start,
            end=cycle_end,
            generated_at="2026-05-23T00:00:00Z",
        )

    markers = sorted((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert len(markers) == 1
    marker = json.loads(markers[0].read_text(encoding="utf-8"))
    counts_after_crash = _jsonl_line_counts(ledger)
    assert marker["status"] == "ledger_write_pending"
    assert marker["run_id"] == backtest_calls[0]
    assert counts_after_crash == {
        "orders.jsonl": 1,
        "fills.jsonl": 1,
        "portfolio_snapshots.jsonl": 1,
        "events.jsonl": 1,
    }
    assert not _ledger_start_lock_active(ledger)
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=cycle_start,
        end=cycle_end,
        resume=True,
        generated_at="2026-05-24T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_preflight_blocked"
    assert "btc_paper_validation_ledger_root_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == counts_after_crash
    assert len(backtest_calls) == 1
    assert json.loads(markers[0].read_text(encoding="utf-8"))["status"] == "ledger_write_pending"
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_blocks_restart_after_partial_write_result_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ControlledPartialLedgerWriteCrash(RuntimeError):
        pass

    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    cycle_start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc)
    backtest_calls: list[str] = []

    def fake_backtest(**kwargs: object) -> SimpleNamespace:
        run_id = str(kwargs["run_id"])
        backtest_calls.append(run_id)
        return _fake_guarded_paper_backtest_result(run_id)

    def crash_on_append_snapshot(*_args: object, **_kwargs: object) -> None:
        raise ControlledPartialLedgerWriteCrash("stop inside write_result after first fill")

    monkeypatch.setattr(btc_paper_runner, "run_crypto_event_backtest", fake_backtest)
    monkeypatch.setattr(btc_paper_runner.JsonlLedgerStore, "append_snapshot", crash_on_append_snapshot)

    with pytest.raises(ControlledPartialLedgerWriteCrash):
        run_btc_paper_validation(
            repo_root=tmp_path,
            ledger_root=ledger,
            start=cycle_start,
            end=cycle_end,
            generated_at="2026-05-23T00:00:00Z",
        )

    markers = sorted((ledger / "audit/paper_validation_in_progress").glob("*.json"))
    assert len(markers) == 1
    marker = json.loads(markers[0].read_text(encoding="utf-8"))
    counts_after_crash = _jsonl_line_counts(ledger)
    assert marker["status"] == "ledger_write_pending"
    assert marker["run_id"] == backtest_calls[0]
    assert counts_after_crash == {
        "orders.jsonl": 1,
        "fills.jsonl": 1,
        "portfolio_snapshots.jsonl": 0,
        "events.jsonl": 0,
    }
    assert not _ledger_start_lock_active(ledger)
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()

    payload = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=cycle_start,
        end=cycle_end,
        resume=True,
        generated_at="2026-05-24T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert payload["status"] == "BLOCKED"
    assert payload["reason"] == "btc_paper_validation_preflight_blocked"
    assert "btc_paper_validation_ledger_root_blocked" in attempt["preflight_blocking_reasons"]
    assert _jsonl_line_counts(ledger) == counts_after_crash
    assert len(backtest_calls) == 1
    assert json.loads(markers[0].read_text(encoding="utf-8"))["status"] == "ledger_write_pending"
    assert not (ledger / "validation_report.json").exists()
    assert not (ledger / "validation_state.json").exists()
    assert not (ledger / "audit/paper_session_manifest.json").exists()


def test_btc_paper_validation_runner_blocks_duplicate_completed_cycle_before_ledger_write(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    cycle_start = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)
    cycle_end = datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc)

    first = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=cycle_start,
        end=cycle_end,
        generated_at="2026-05-23T00:00:00Z",
    )
    counts_before = _jsonl_line_counts(ledger)
    state_before = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))

    second = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=cycle_start,
        end=cycle_end,
        resume=True,
        generated_at="2026-05-24T00:00:00Z",
    )
    attempt = json.loads((ledger / "audit/btc_paper_validation_start_attempt.json").read_text(encoding="utf-8"))
    state_after = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    schema = json.loads(START_ATTEMPT_SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(attempt, schema)
    assert first["status"] == "IN_PROGRESS"
    assert second["status"] == "BLOCKED"
    assert second["reason"] == "btc_paper_validation_cycle_already_completed"
    assert attempt["preflight_status"] == "PASS"
    assert attempt["preflight_blocking_reasons"] == []
    assert _jsonl_line_counts(ledger) == counts_before
    assert state_after["days_completed"] == state_before["days_completed"]
    assert state_after["completed_cycle_keys"] == state_before["completed_cycle_keys"]


def test_btc_paper_validation_runner_resume_counts_next_clean_cycle_with_existing_simulated_ledger(
    tmp_path: Path,
) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"

    first = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    _append_jsonl(
        ledger / "orders.jsonl",
        {
            "timestamp_utc": "2026-05-22T00:00:00Z",
            "strategy_id": "btc_perp_dual_trend",
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.0,
            "order_type": "market",
            "time_in_force": "day",
            "client_order_id": "resume_guard_order",
            "run_id": first["run_id"],
            "broker": "simulated",
            "status": "created",
            "order_id": "resume_guard_order",
        },
    )

    second = run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        start=datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 22, 1, 0, tzinfo=timezone.utc),
        resume=True,
        generated_at="2026-05-24T00:00:00Z",
    )
    report = json.loads((ledger / "validation_report.json").read_text(encoding="utf-8"))
    state = json.loads((ledger / "validation_state.json").read_text(encoding="utf-8"))
    first_history = ledger / "audit/paper_session_manifests" / f"{first['run_id']}.json"
    second_history = ledger / "audit/paper_session_manifests" / f"{second['run_id']}.json"

    jsonschema.validate(report, json.loads(RUN_REPORT_SCHEMA.read_text(encoding="utf-8")))
    assert first["status"] == "IN_PROGRESS"
    assert second["status"] == "IN_PROGRESS"
    assert first["run_id"] != second["run_id"]
    assert second["days_completed"] == 2
    assert second["consecutive_clean_days"] == 2
    assert state["days_completed"] == 2
    assert state["consecutive_clean_days"] == 2
    assert report["cycle"]["start"] == "2026-05-22T00:00:00Z"
    assert report["cycle"]["end"] == "2026-05-22T01:00:00Z"
    assert first_history.exists()
    assert second_history.exists()
    assert not (ledger / "audit/btc_paper_validation_start_attempt.json").exists()


def test_btc_paper_validation_run_report_schema_rejects_live_execution_claim(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    report = json.loads((ledger / "validation_report.json").read_text(encoding="utf-8"))
    schema = json.loads(RUN_REPORT_SCHEMA.read_text(encoding="utf-8"))
    report["execution"]["real_order_submission"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema)


def test_btc_paper_validation_run_report_schema_rejects_unenforced_risk_gate(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    report = json.loads((ledger / "validation_report.json").read_text(encoding="utf-8"))
    schema = json.loads(RUN_REPORT_SCHEMA.read_text(encoding="utf-8"))
    report["risk_gate"]["enforced"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema)


def test_btc_paper_validation_session_manifest_schema_rejects_order_endpoint_claim(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    manifest = json.loads((ledger / "audit/paper_session_manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(SESSION_MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    manifest["no_real_order_submission_proof"]["order_endpoint_used"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_btc_paper_validation_session_manifest_schema_rejects_missing_risk_ids(tmp_path: Path) -> None:
    _write_ready_fixture(tmp_path)
    ledger = tmp_path / "data/paper_ledger/btc"
    run_btc_paper_validation(
        repo_root=tmp_path,
        ledger_root=ledger,
        generated_at="2026-05-23T00:00:00Z",
    )
    manifest = json.loads((ledger / "audit/paper_session_manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(SESSION_MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    manifest["risk_gate"]["all_orders_have_risk_check_id"] = False

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(manifest, schema)


def test_btc_paper_validation_make_targets_are_guarded_operator_entrypoints() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")
    static_body = _target_body(makefile, "check-btc-paper-validation-static-preflight")
    check_body = _target_body(makefile, "check-btc-paper-validation-readiness")
    start_body = _target_body(makefile, "start-btc-paper-validation")
    resume_body = _target_body(makefile, "resume-btc-paper-validation")
    validate_body = _target_body(makefile, "validate-btc-evidence")

    assert "check-btc-paper-validation-static-preflight" in makefile
    assert "check-btc-paper-validation-readiness start-btc-paper-validation" in makefile
    assert "resume-btc-paper-validation" in makefile
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" in static_body
    assert "scripts/check_btc_paper_validation_readiness.py" in static_body
    assert static_body.index("$(MAKE) rebuild-btc-paper-readiness-chain") < static_body.index(
        "scripts/check_btc_paper_validation_readiness.py"
    )
    assert "--repo-root \".\"" in static_body
    assert "--no-start-report-ready-required" in static_body
    assert "--json" in static_body
    assert "scripts/run_btc_paper_validation.py" not in static_body
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" in check_body
    assert "scripts/check_btc_paper_validation_readiness.py" in check_body
    assert check_body.index("$(MAKE) rebuild-btc-paper-readiness-chain") < check_body.index(
        "scripts/check_btc_paper_validation_readiness.py"
    )
    assert "--repo-root \".\"" in check_body
    assert "--symbols \"$(BTC_PAPER_SYMBOLS)\"" in check_body
    assert "--market-type \"$(BTC_PAPER_MARKET_TYPE)\"" in check_body
    assert "--ledger-root \"$(BTC_PAPER_LEDGER_ROOT)\"" in check_body
    assert "--data-root \"$(BTC_PAPER_DATA_ROOT)\"" in check_body
    assert "--json" in check_body
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" in start_body
    assert start_body.index("$(MAKE) rebuild-btc-paper-readiness-chain") < start_body.index(
        "scripts/run_btc_paper_validation.py"
    )
    assert "--repo-root \".\"" in start_body
    assert "--symbols \"$(BTC_PAPER_SYMBOLS)\"" in start_body
    assert "--market-type \"$(BTC_PAPER_MARKET_TYPE)\"" in start_body
    assert "--ledger-root \"$(BTC_PAPER_LEDGER_ROOT)\"" in start_body
    assert "--data-root \"$(BTC_PAPER_DATA_ROOT)\"" in start_body
    assert "--days-required \"$(BTC_PAPER_DAYS_REQUIRED)\"" in start_body
    assert "--cycle-hours \"$(BTC_PAPER_CYCLE_HOURS)\"" in start_body
    assert "--start \"$(BTC_PAPER_START)\"" in start_body
    assert "--end \"$(BTC_PAPER_END)\"" in start_body
    assert "--resume" not in start_body
    assert "$(MAKE) rebuild-btc-paper-readiness-chain" in resume_body
    assert resume_body.index("$(MAKE) rebuild-btc-paper-readiness-chain") < resume_body.index(
        "scripts/run_btc_paper_validation.py"
    )
    assert "--repo-root \".\"" in resume_body
    assert "--symbols \"$(BTC_PAPER_SYMBOLS)\"" in resume_body
    assert "--market-type \"$(BTC_PAPER_MARKET_TYPE)\"" in resume_body
    assert "--ledger-root \"$(BTC_PAPER_LEDGER_ROOT)\"" in resume_body
    assert "--data-root \"$(BTC_PAPER_DATA_ROOT)\"" in resume_body
    assert "--days-required \"$(BTC_PAPER_DAYS_REQUIRED)\"" in resume_body
    assert "--cycle-hours \"$(BTC_PAPER_CYCLE_HOURS)\"" in resume_body
    assert "--start \"$(BTC_PAPER_START)\"" in resume_body
    assert "--end \"$(BTC_PAPER_END)\"" in resume_body
    assert "--resume" in resume_body
    assert "--json" in start_body
    assert "--json" in resume_body
    assert "scripts/run_btc_paper_validation.py" not in validate_body


def _write_ready_fixture(root: Path) -> None:
    evidence_pack = root / "data/research/evidence_packs/btc_review_001/evidence_pack.json"
    _write_json(evidence_pack, {"paper_review_id": "btc_review_001"})
    _write_json(
        root / "data/research/paper_reviews/btc_review_001/review.json",
        {
            "paper_review_id": "btc_review_001",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "strategy_manifest_id": "btc_perp_dual_trend",
            "proposed_symbols": ["BTCUSDT"],
            "proposed_capital": 25000.0,
            "evidence_pack_path": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
        },
    )
    _write_json(
        root / "artifacts/btc_paper_readiness/latest/btc_paper_readiness_report.json",
        {
            "schema_version": "btc_paper_readiness_report_v1",
            "status": "ready_for_paper_start",
            "paper_start_allowed": True,
            "paper_execution_authorized": True,
            "live_status": "frozen",
            "approved_paper_review": {
                "approved": True,
                "paper_review_id": "btc_review_001",
                "status": "APPROVED_FOR_PAPER_ONLY",
                "path": "data/research/paper_reviews/btc_review_001/review.json",
                "strategy_manifest_id": "btc_perp_dual_trend",
                "proposed_symbols": ["BTCUSDT"],
                "proposed_capital": 25000.0,
                "evidence_pack_path": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
                "evidence_pack_exists": True,
                "approval": {
                    "valid": True,
                    "schema_version": "paper_review_approval_v1",
                    "reviewer": "risk_reviewer",
                    "reason": "paper validation approval only",
                    "timestamp": "2026-05-23T00:00:00Z",
                    "candidate_id": "btc_candidate_v1",
                    "commit_hash": "fixture",
                    "source": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
                    "source_sha256": _sha256(evidence_pack),
                    "gate_snapshot": {
                        "candidate_id": "btc_candidate_v1",
                        "decision": "READY_FOR_PAPER_REVIEW",
                        "paper_execution_authorized": False,
                        "authorization_scope": "human_review_only",
                    },
                    "blockers": [],
                },
            },
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/btc_paper_readiness/latest/btc_paper_validation_start_report.json",
        {
            "schema_version": "btc_paper_validation_start_report_v1",
            "asset": "btc",
            "symbol": "BTCUSDT",
            "market_type": "usds_m_perpetual",
            "status": "ready_to_start_paper_validation",
            "paper_start_allowed": True,
            "paper_execution_authorized": True,
            "live_status": "frozen",
            "next_required_action": "start_paper_validation",
            "blockers": [],
            "operator_manual_unblock": {
                "blockers": [],
                "safety": {
                    "api_key_required": False,
                    "private_endpoints_allowed": False,
                    "order_endpoints_allowed": False,
                    "paper_or_live_unlock_allowed": False,
                },
            },
            "commands": {
                "report_rebuild_command": "python3 scripts/build_btc_paper_validation_start_report.py",
                "preflight_command": "python3 scripts/check_btc_paper_validation_readiness.py --repo-root . --symbols BTCUSDT --market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data --json",
                "start_command": "python3 scripts/run_btc_paper_validation.py --repo-root . --symbols BTCUSDT --market-type usds_m_perpetual --ledger-root data/paper_ledger/btc --data-root data",
                "resume_command": "",
            },
            "safety": {
                "report_only": True,
                "requires_readiness_report": True,
                "requires_approved_review": True,
                "requires_evidence_pack": True,
                "strategy_direct_broker_forbidden": True,
                "all_orders_must_pass_risk_engine": True,
                "allows_live_orders": False,
                "paper_auto_start": False,
            },
        },
    )
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_data_status_report.json",
        {
            "schema_version": "btc_data_status_report_v1",
            "status": "pass",
            "instrument": {"market_type": "usds_m_perpetual"},
        },
    )
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "schema_version": "btc_perpetual_provider_verification_report_v1",
            "perpetual_evidence_ready": True,
            "exchange_info_verified": True,
            "funding_info_verified": True,
        },
    )
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json",
        {"schema_version": "btc_perpetual_bundle_preflight_report_v1", "preflight_pass": True},
    )
    _write_json(
        root / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {
            "schema_version": "btc_cost_model_contract_v1",
            "status": "pass",
            "fee_model": {
                "fee_tier_verified": True,
                "taker_fee_bps": 4.0,
            },
            "slippage_model": {
                "slippage_bps": 4.0,
            },
        },
    )
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
        {
            "schema_version": "btc_candidate_gate_audit_report_v1",
            "status": "pass",
            "candidate_passed_internal_gate": 1,
        },
    )
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json",
        {
            "schema_version": "btc_candidate_metric_repair_report_v1",
            "status": "candidate_metric_gate_passed",
            "promotion_allowed": True,
            "paper_review_pending_allowed": True,
            "failed_metrics": [],
            "blockers": [],
        },
    )
    _write_json(
        root / "configs/data/btc_perpetual_sources.yaml",
        {
            "providers": {
                "binance_usdm": {
                    "enabled": True,
                    "root": "data/external/btc_perpetual/binance_usdm/",
                    "selected_bundle_id": "btc_ready_bundle",
                }
            }
        },
    )
    bundle = root / "data/external/btc_perpetual/binance_usdm/bundles/btc_ready_bundle"
    _write_json(
        bundle / "btc_perpetual_bundle_manifest.json",
        {"source_type": "production", "promotion_clean_allowed": True},
    )
    bundle.mkdir(parents=True, exist_ok=True)
    _write_json(
        bundle / "exchange_info.json",
        {
            "source_method": "manual_offline_capture",
            "captured_at": "2026-05-22T00:00:00Z",
            "symbol": "BTCUSDT",
        },
    )
    _write_json(
        bundle / "funding_info.json",
        {
            "source_method": "manual_offline_capture",
            "captured_at": "2026-05-22T00:00:00Z",
            "symbol": "BTCUSDT",
        },
    )
    raw_dir = root / "artifacts/btc_data_status/raw/manual_metadata"
    exchange_raw = raw_dir / "exchange_info_raw.json"
    funding_raw = raw_dir / "funding_info_raw.json"
    exchange_http_status = raw_dir / "exchange_info_http_status.txt"
    funding_http_status = raw_dir / "funding_info_http_status.txt"
    _write_json(exchange_raw, {"server_time": 1779408000000, "symbols": [{"symbol": "BTCUSDT"}]})
    _write_json(funding_raw, {"symbols": [{"symbol": "BTCUSDT", "adjustedFundingRateCap": "0.003"}]})
    exchange_http_status.write_text("200\n", encoding="utf-8")
    funding_http_status.write_text("200\n", encoding="utf-8")
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_manual_metadata_import_report.json",
        {
            "schema_version": "btc_manual_metadata_import_report_v1",
            "status": "verified",
            "generated_at": "2026-05-22T00:01:00Z",
            "dry_run": False,
            "captured_at": "2026-05-22T00:00:00Z",
            "writes_performed": True,
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "raw_input_files": {
                "exchange_info_raw": {
                    "path": str(exchange_raw.relative_to(root)),
                    "exists": True,
                    "size_bytes": exchange_raw.stat().st_size,
                    "sha256": _sha256(exchange_raw),
                    "http_status_file": str(exchange_http_status.relative_to(root)),
                    "http_status": 200,
                    "http_status_verified": True,
                },
                "funding_info_raw": {
                    "path": str(funding_raw.relative_to(root)),
                    "exists": True,
                    "size_bytes": funding_raw.stat().st_size,
                    "sha256": _sha256(funding_raw),
                    "http_status_file": str(funding_http_status.relative_to(root)),
                    "http_status": 200,
                    "http_status_verified": True,
                },
            },
            "exchange_info_output_path": str((bundle / "exchange_info.json").relative_to(root)),
            "exchange_info_output_sha256": _sha256(bundle / "exchange_info.json"),
            "funding_info_output_path": str((bundle / "funding_info.json").relative_to(root)),
            "funding_info_output_sha256": _sha256(bundle / "funding_info.json"),
            "bundle_dir": str(bundle.relative_to(root)),
            "post_import_validation_command": "make validate-btc-public-data-bundle",
            "blockers": [],
        },
    )
    (bundle / "klines_1h.csv").write_text(
        "\n".join(
            [
                "timestamp,open_time_ms,open,high,low,close,volume",
                "2026-05-22T00:00:00Z,1779408000000,100,110,90,105,10",
                "2026-05-22T01:00:00Z,1779411600000,105,111,101,108,12",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _jsonl_line_counts(ledger: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in ("orders.jsonl", "fills.jsonl", "portfolio_snapshots.jsonl", "events.jsonl"):
        path = ledger / name
        counts[name] = len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0
    return counts


def _fake_guarded_paper_backtest_result(run_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        unified=SimpleNamespace(
            event_driven=SimpleNamespace(
                orders=[
                    {
                        "timestamp_utc": "2026-05-22T00:00:00Z",
                        "strategy_id": "btc_perp_dual_trend",
                        "symbol": "BTCUSDT",
                        "side": "buy",
                        "quantity": 0.1,
                        "order_type": "market",
                        "time_in_force": "day",
                        "client_order_id": f"{run_id}:order",
                        "run_id": run_id,
                        "broker": "simulated",
                        "status": "risk_checked",
                        "risk_check_id": f"{run_id}:risk",
                        "order_id": f"{run_id}:order",
                    }
                ],
                fills=[
                    {
                        "order_id": f"{run_id}:order",
                        "symbol": "BTCUSDT",
                        "side": "buy",
                        "quantity": 0.1,
                        "price": 105.0,
                        "commission": 0.0042,
                        "filled_at": "2026-05-22T01:00:00Z",
                        "broker": "simulated",
                        "fill_id": f"{run_id}:fill",
                    }
                ],
                snapshots=[{"timestamp_utc": "2026-05-22T01:00:00Z", "cash": 24989.4958, "run_id": run_id}],
                events=[{"timestamp_utc": "2026-05-22T01:00:00Z", "event_type": "fill", "run_id": run_id}],
            ),
            evidence={
                "orders": {
                    "count": 1,
                    "all_orders_created_by_oms": True,
                    "all_orders_have_risk_check_id": True,
                },
                "risk": {
                    "risk_check_count": 1,
                    "approved": 1,
                    "rejected": 0,
                    "rejection_reasons": {},
                },
            },
            equity_consistent=True,
        ),
        summary={},
        diagnostics={},
    )


def _ledger_start_lock_active(ledger: Path) -> bool:
    lock = ledger / "audit" / btc_paper_runner.LEDGER_START_LOCK_NAME
    if not lock.exists():
        return False
    fd = os.open(lock, os.O_RDWR)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            return True
        return False
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_reconciliation_artifact(ledger: Path, *, passed: bool = True) -> tuple[Path, str]:
    payload: dict[str, object] = {
        "artifact_version": "ledger_reconciliation_v1",
        "generated_at": "2026-05-22T01:00:00+00:00",
        "as_of_utc": "2026-05-22T01:00:00+00:00",
        "initial_cash": 25000.0,
        "orders": {},
        "fills": {},
        "positions": {},
        "cash": {},
        "fees": {},
        "slippage": {},
        "pnl": {},
        "hashes": {},
        "integrity": {"passed": passed},
        "reconciliation": {"summary": {"passed": passed, "snapshot_count": 1}},
    }
    artifact_hash = compute_ledger_reconciliation_artifact_hash(payload)
    payload["artifact_hash"] = artifact_hash
    path = ledger / "reconciliation" / f"ledger_recon_artifact_{artifact_hash[:16]}.json"
    _write_json(path, payload)
    return path, artifact_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_body(makefile: str, target: str) -> str:
    marker = f"\n{target}:"
    start = makefile.index(marker)
    rest = makefile[start + 1 :]
    next_target = rest.find("\n\n")
    return rest if next_target == -1 else rest[:next_target]
