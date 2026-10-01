from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from scripts.build_btc_paper_readiness_report import build_btc_paper_readiness_report
from scripts.import_btc_manual_metadata_capture import MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
from quant_crypto.application.btc_current_head_gate_rebuild import _build_supporting_artifacts


SCHEMA = Path("schemas/btc_paper_readiness_report.schema.json")


def test_btc_paper_readiness_blocked_fixture_schema_valid(tmp_path: Path) -> None:
    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)


def test_current_head_blocked_paper_readiness_uses_canonical_schema() -> None:
    current_head = "a" * 40
    supporting = _build_supporting_artifacts(
        current_head=current_head,
        generated=datetime(2026, 7, 26, 1, 2, 3, 456000, tzinfo=timezone.utc),
        run_id="btc-gate-fixture",
        evaluation={
            "blockers": [
                "btc_okx_native:historical_timestamp_aligned_depth_fill_mapping_missing"
            ]
        },
        existing_manual={},
    )
    payload = supporting["paper_readiness"]
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "blocked"
    assert payload["commit"] == current_head
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["promotion_evidence_ready"] is False


def test_current_btc_paper_readiness_stale_review_only_approval_fails_closed(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    _write_stale_packet_review_only_approval(tmp_path)

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "manual_inputs_ready_but_current_packet_unapproved"
    assert payload["paper_queue_status"] == "current_packet_unapproved"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["live_status"] == "frozen"
    assert payload["next_required_action"] == "sign_current_packet_manual_review_approval"
    assert payload["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["paper_gate_manual_inputs_complete"] is True
    assert payload["requirements"]["manual_input_gate"]["status"] == "complete"
    assert payload["requirements"]["data_source_gate"]["status"] == "complete"
    assert payload["requirements"]["cost_ledger_gate"]["status"] == "complete"
    assert payload["requirements"]["candidate_gate"]["status"] == "complete"
    assert payload["requirements"]["paper_review_gate"]["status"] == "pending_review"
    assert payload["approved_paper_review"]["status"] == "CURRENT_PACKET_UNAPPROVED"
    assert payload["approved_paper_review"]["approval"]["valid"] is False
    assert payload["approved_paper_review"]["approval_current_packet_hash_match"] is False
    assert "btc_paper_readiness_current_packet_unapproved" in payload["blockers"]
    assert "btc_paper_readiness_current_packet_approval_hash_not_current" in payload["blockers"]
    assert "btc_manual_paper_review_approval_packet_sha256_mismatch" in payload["approved_paper_review"]["approval"]["blockers"]
    assert "btc_paper_readiness_manual_inputs_incomplete" not in payload["blockers"]
    assert "btc_paper_readiness_exchange_info_manual_input_missing" not in payload["blockers"]
    assert "btc_paper_readiness_funding_info_manual_input_missing" not in payload["blockers"]
    assert "btc_maker_taker_fee_tier_missing" not in payload["blockers"]
    assert payload["requirements"]["cost_ledger_gate"]["checks"]["fee_blockers_empty"] is True
    assert "btc_paper_readiness_objective_audit_incomplete" not in payload["blockers"]
    assert "btc_regime_contract_not_pass" not in payload["blockers"]
    assert "btc_paper_readiness_no_candidate_passed_internal_gate" not in payload["blockers"]
    assert "btc_paper_readiness_candidate_metric_repair_not_pass" not in payload["blockers"]
    assert "btc_paper_readiness_candidate_metric_repair_event_profit_factor_failed" not in payload["blockers"]


def test_btc_paper_readiness_records_current_review_only_approval_without_auto_paper(
    tmp_path: Path,
) -> None:
    _write_passing_inputs(tmp_path)
    _write_current_packet_review_only_approval(tmp_path)

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "current_packet_review_only_approved_promotion_blocked"
    assert payload["paper_queue_status"] == "current_packet_review_only_approved_promotion_blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["live_status"] == "frozen"
    assert payload["next_required_action"] == "wait_for_promotion_gate_clearance_after_review_only_approval"
    assert payload["requirements"]["paper_review_gate"]["status"] == "pending_review"
    assert payload["approved_paper_review"]["status"] == "APPROVED_REVIEW_ONLY_NO_AUTO_PAPER_NO_LIVE"
    assert payload["approved_paper_review"]["approved"] is True
    assert payload["approved_paper_review"]["approval"]["valid"] is True
    assert payload["approved_paper_review"]["approval_current_packet_hash_match"] is True
    assert payload["approved_paper_review"]["approval"]["source_sha256"] == "b" * 64
    assert payload["blockers"] == []


def test_btc_paper_readiness_missing_inputs_blocks_at_data_gate(tmp_path: Path) -> None:
    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["next_required_action"] == "complete_btc_manual_paper_gate_inputs"
    assert payload["requirements"]["manual_input_gate"]["status"] == "blocked"
    assert payload["requirements"]["data_source_gate"]["status"] == "blocked"
    assert "btc_paper_readiness_manual_inputs_incomplete" in payload["blockers"]
    assert "btc_paper_readiness_provider_not_ready" in payload["blockers"]


def test_btc_paper_readiness_ready_for_manual_review_before_human_approval(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_for_manual_paper_review"
    assert payload["paper_queue_status"] == "pending_review"
    assert payload["paper_start_allowed"] is False
    assert payload["next_required_action"] == "human_paper_review_approval"
    assert payload["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["paper_gate_manual_inputs_complete"] is True
    assert payload["requirements"]["manual_input_gate"]["status"] == "complete"
    assert payload["requirements"]["paper_review_gate"]["status"] == "pending_review"
    assert payload["blockers"] == ["btc_paper_readiness_approved_paper_review_missing"]


def test_btc_paper_readiness_ready_for_paper_start_requires_approved_review(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    _write_approved_btc_review(tmp_path / "data")

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["status"] == "ready_for_paper_start"
    assert payload["paper_queue_status"] == "approved"
    assert payload["paper_start_allowed"] is True
    assert payload["paper_execution_authorized"] is True
    assert payload["manual_inputs_status"] == "manual_inputs_verified"
    assert payload["paper_gate_manual_inputs_complete"] is True
    assert payload["approved_paper_review"]["status"] == "APPROVED_FOR_PAPER_ONLY"
    assert payload["approved_paper_review"]["evidence_pack_exists"] is True
    assert payload["approved_paper_review"]["approval"]["valid"] is True
    assert payload["requirements"]["paper_review_gate"]["checks"]["approval_valid"] is True
    assert payload["blockers"] == []


def test_btc_paper_readiness_allows_review_when_only_diagnostic_market_microstructure_gaps_missing(
    tmp_path: Path,
) -> None:
    _write_passing_inputs(tmp_path)
    diagnostic_codes = [
        "btc_open_interest_history_not_verified_diagnostic_partial",
        "btc_agg_trades_missing",
        "btc_liquidation_snapshot_missing_diagnostic_only",
    ]
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "perpetual_evidence_ready": True,
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "funding_info_endpoint_response_available": True,
            "diagnostic_warnings": diagnostic_codes,
            "blockers": ["btc_open_interest_history_not_verified_diagnostic_partial"],
        },
    )
    _write_json(
        tmp_path / "artifacts/btc_data_status/latest/btc_data_status_report.json",
        {
            "status": "pass",
            "diagnostic_warnings": diagnostic_codes,
            "blockers": diagnostic_codes,
        },
    )

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_for_manual_paper_review"
    assert payload["paper_start_allowed"] is False
    assert payload["requirements"]["data_source_gate"]["status"] == "complete"
    for code in diagnostic_codes:
        assert code not in payload["requirements"]["data_source_gate"]["blockers"]
        assert code not in payload["blockers"]


def test_btc_paper_readiness_approved_review_requires_matching_evidence_pack_hash(
    tmp_path: Path,
) -> None:
    _write_passing_inputs(tmp_path)
    data_root = tmp_path / "data"
    evidence = data_root / "research/evidence_packs/btc_review_hash/evidence_pack.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"paper_review_id": "btc_review_hash"}), encoding="utf-8")
    _write_json(
        data_root / "research/paper_reviews/btc_review_hash/review.json",
        {
            "paper_review_id": "btc_review_hash",
            "strategy_manifest_id": "btc_candidate_v1",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "proposed_symbols": ["BTCUSDT"],
            "proposed_capital": 25_000.0,
            "evidence_pack_path": "data/research/evidence_packs/btc_review_hash/evidence_pack.json",
            "approval": _valid_approval(
                source="data/research/evidence_packs/btc_review_hash/evidence_pack.json",
                source_sha256="0" * 64,
            ),
        },
    )

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=data_root,
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_for_manual_paper_review"
    assert payload["paper_start_allowed"] is False
    assert payload["approved_paper_review"]["approval"]["valid"] is False
    assert "btc_paper_readiness_approved_paper_review_source_sha256_mismatch" in payload["blockers"]


def test_btc_paper_readiness_blocks_manual_metadata_import_marker_even_with_stale_provider_pass(
    tmp_path: Path,
) -> None:
    _write_passing_inputs(tmp_path)
    _write_approved_btc_review(tmp_path / "data")
    _write_json(
        tmp_path / "configs/data/btc_perpetual_sources.yaml",
        {
            "providers": {
                "binance_usdm": {
                    "root": "data/external/btc_perpetual/binance_usdm/",
                    "selected_bundle_id": "btc_ready_bundle",
                }
            }
        },
    )
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

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["requirements"]["data_source_gate"]["status"] == "blocked"
    assert payload["requirements"]["data_source_gate"]["checks"]["manual_metadata_import_not_in_progress"] is False
    assert "btc_paper_readiness_manual_metadata_import_in_progress" in payload["blockers"]


def test_btc_paper_readiness_blocks_pass_cost_model_without_fee_tier_evidence(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    _write_approved_btc_review(tmp_path / "data")
    cost_report = tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json"
    _write_json(cost_report, {"status": "pass", "blockers": []})

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["paper_start_allowed"] is False
    assert payload["paper_execution_authorized"] is False
    assert payload["requirements"]["cost_ledger_gate"]["status"] == "blocked"
    assert payload["requirements"]["cost_ledger_gate"]["checks"]["cost_model_pass"] is True
    assert payload["requirements"]["cost_ledger_gate"]["checks"]["fee_tier_verified"] is False
    assert "btc_paper_readiness_fee_tier_cost_model_not_verified" in payload["blockers"]


def test_btc_paper_readiness_propagates_fee_tier_cost_model_blockers(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    _write_approved_btc_review(tmp_path / "data")
    _write_json(
        tmp_path / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {
            "status": "pass",
            "fee_model": {
                "fee_tier_verified": False,
                "fee_tier_import_report_verified": True,
                "fee_tier_overlay": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json",
                "fee_tier_import_report": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json",
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 4.0,
                "fee_blockers": ["btc_fee_tier_overlay_import_report_hash_mismatch"],
            },
            "blockers": [],
        },
    )

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "blocked"
    assert payload["requirements"]["cost_ledger_gate"]["status"] == "blocked"
    assert "btc_paper_readiness_fee_tier_cost_model_not_verified" in payload["blockers"]
    assert "btc_fee_tier_overlay_import_report_hash_mismatch" in payload["blockers"]


def test_btc_paper_readiness_schema_rejects_start_without_approved_review(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload["status"] = "ready_for_paper_start"
    payload["paper_queue_status"] = "approved"
    payload["paper_start_allowed"] = True
    payload["paper_execution_authorized"] = True
    payload["next_required_action"] = "start_paper_validation"
    payload["blockers"] = []

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_btc_paper_readiness_approved_review_requires_evidence_pack_path(tmp_path: Path) -> None:
    _write_passing_inputs(tmp_path)
    _write_json(
        tmp_path / "data/research/paper_reviews/btc_review_missing_pack/review.json",
        {
            "paper_review_id": "btc_review_missing_pack",
            "strategy_manifest_id": "btc_candidate_v1",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "proposed_symbols": ["BTCUSDT"],
            "proposed_capital": 25_000.0,
            "evidence_pack_path": "",
            "approval": _valid_approval(source="manual_review_without_pack"),
        },
    )

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_for_manual_paper_review"
    assert payload["approved_paper_review"]["approved"] is True
    assert payload["approved_paper_review"]["evidence_pack_exists"] is False
    assert payload["approved_paper_review"]["approval"]["valid"] is True
    assert payload["requirements"]["paper_review_gate"]["blockers"] == [
        "btc_paper_readiness_approved_paper_review_evidence_pack_missing"
    ]


def test_btc_paper_readiness_approved_status_without_approval_object_is_not_start_authorized(
    tmp_path: Path,
) -> None:
    _write_passing_inputs(tmp_path)
    evidence = tmp_path / "data/research/evidence_packs/btc_review_legacy/evidence_pack.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"paper_review_id": "btc_review_legacy"}), encoding="utf-8")
    _write_json(
        tmp_path / "data/research/paper_reviews/btc_review_legacy/review.json",
        {
            "paper_review_id": "btc_review_legacy",
            "strategy_manifest_id": "btc_candidate_v1",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "proposed_symbols": ["BTCUSDT"],
            "proposed_capital": 25_000.0,
            "evidence_pack_path": "research/evidence_packs/btc_review_legacy/evidence_pack.json",
        },
    )

    payload = build_btc_paper_readiness_report(
        repo_root=tmp_path,
        data_root=tmp_path / "data",
        generated_at="2026-05-23T00:00:00Z",
    )

    assert payload["status"] == "ready_for_manual_paper_review"
    assert payload["paper_start_allowed"] is False
    assert payload["approved_paper_review"]["approved"] is True
    assert payload["approved_paper_review"]["approval"]["valid"] is False
    assert "btc_paper_readiness_approved_paper_review_approval_missing" in payload["blockers"]


def _write_passing_inputs(root: Path) -> None:
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json",
        {"goal_complete": True, "blockers": []},
    )
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json",
        {"preflight_pass": True, "blockers": []},
    )
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json",
        {
            "perpetual_evidence_ready": True,
            "exchange_info_verified": True,
            "funding_info_verified": True,
            "funding_info_endpoint_response_available": True,
            "blockers": [],
        },
    )
    _write_json(root / "artifacts/btc_data_status/latest/btc_data_status_report.json", {"status": "pass", "blockers": []})
    _write_json(
        root / "artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json",
        {
            "status": "metadata_verified",
            "manual_inputs_status": "manual_inputs_verified",
            "paper_gate_manual_inputs_complete": True,
            "required_manual_inputs": [
                {
                    "name": "exchange_info",
                    "required_for": "exchange_info_verification",
                    "status": "verified",
                    "action": "none",
                    "blockers": [],
                },
                {
                    "name": "funding_info",
                    "required_for": "funding_info_endpoint_verification",
                    "status": "verified",
                    "action": "none",
                    "blockers": [],
                },
                {
                    "name": "fee_tier_overlay",
                    "required_for": "maker_taker_fee_tier_verification",
                    "status": "verified",
                    "action": "none",
                    "blockers": [],
                },
            ],
            "fee_tier_status": {
                "cost_model_report": "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
                "cost_model_status": "pass",
                "fee_tier_verified": True,
                "manual_capture_required": False,
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 4.0,
                "fee_tier_import_report_verified": True,
                "fee_blockers": [],
            },
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/btc_cost_model/latest/btc_cost_model_report.json",
        {
            "status": "pass",
            "fee_model": {
                "fee_tier_verified": True,
                "fee_tier_import_report_verified": True,
                "fee_tier_overlay": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay.json",
                "fee_tier_import_report": "artifacts/btc_cost_model/latest/btc_fee_tier_overlay_import_report.json",
                "maker_fee_bps": 2.0,
                "taker_fee_bps": 4.0,
                "fee_blockers": [],
            },
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/btc_cost_model/latest/btc_funding_ledger_report.json",
        {
            "funding_payment_in_ledger": True,
            "funding_merged_into_net_ledger": True,
            "funding_adjusted_net_pnl_reconciled": True,
            "funding_adjusted_net_pnl_reconciliation_delta": 0.0,
            "blockers": [],
        },
    )
    _write_json(root / "artifacts/btc_tail_dependency/latest/tail_dependency_report.json", {"tail_dependency_pass": True, "blockers": []})
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json",
        {
            "status": "pass",
            "candidate_passed_internal_gate": 1,
            "paper_review_pending_allowed": True,
            "live_status": "frozen",
            "paper_auto_start": False,
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json",
        {
            "status": "candidate_metric_gate_passed",
            "promotion_allowed": True,
            "paper_review_pending_allowed": True,
            "failed_metrics": [],
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/btc_research_registry/research_registry.json",
        {
            "btc": {
                "candidate_passed_internal_gate": 1,
                "current_candidates": ["btc_candidate_v1"],
                "live_status": "frozen",
                "blockers": [],
            }
        },
    )
    _write_json(
        root / "artifacts/global_research_registry/research_registry.json",
        {
            "candidate_passed_internal_gate": 1,
            "paper_queue_status": "pending_review",
            "live_status": "frozen",
        },
    )


def _write_current_packet_review_only_approval(root: Path) -> None:
    packet_sha256 = "b" * 64
    packet_relpath = "artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"
    _write_current_packet(root, packet_relpath=packet_relpath, packet_sha256=packet_sha256)
    _write_manual_packet_approval(
        root,
        packet_relpath=packet_relpath,
        packet_sha256=packet_sha256,
        record_sha256=packet_sha256,
        recorded=True,
    )


def _write_stale_packet_review_only_approval(root: Path) -> None:
    packet_sha256 = "b" * 64
    stale_record_sha256 = "c" * 64
    packet_relpath = "artifacts/btc_paper_candidate_packet/latest/btc_paper_candidate_packet_report.json"
    _write_current_packet(root, packet_relpath=packet_relpath, packet_sha256=packet_sha256)
    _write_manual_packet_approval(
        root,
        packet_relpath=packet_relpath,
        packet_sha256=packet_sha256,
        record_sha256=stale_record_sha256,
        recorded=False,
    )


def _write_current_packet(root: Path, *, packet_relpath: str, packet_sha256: str) -> None:
    _write_json(
        root / packet_relpath,
        {
            "schema_version": "btc_paper_candidate_packet_v1",
            "status": "complete_research_only",
            "decision": "btc_paper_candidate_packet_not_ready_no_paper_queue_write_no_live",
            "code_commit": "fixture",
            "paper_candidate_packet": {
                "packet_id": "btc_current_packet_fixture",
                "packet_status": "not_ready",
                "strategy_version": {"value": "stable_long_short"},
            },
            "reviewed_packet_hash": {
                "schema_version": "btc_paper_candidate_packet_review_hash_v1",
                "hash_method": "canonical_report_content_excluding_runtime_batch_fields_v1",
                "sha256": packet_sha256,
            },
            "gate": {
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
        },
    )


def _write_manual_packet_approval(
    root: Path,
    *,
    packet_relpath: str,
    packet_sha256: str,
    record_sha256: str,
    recorded: bool,
) -> None:
    _write_json(
        root / "artifacts/btc_manual_paper_review_approval/latest/btc_manual_paper_review_approval_report.json",
        {
            "schema_version": "btc_manual_paper_review_approval_report_v1",
            "status": "recorded_research_only" if recorded else "missing_or_invalid_research_only",
            "manual_approval_recorded": recorded,
            "manual_review_missing_cleared": recorded,
            "code_commit": "fixture",
            "blockers": [] if recorded else ["btc_manual_paper_review_approval_packet_sha256_mismatch"],
            "approval_record": {
                "reviewer": "contract-test-reviewer",
                "decision_date_utc": "2026-07-06T00:00:00Z",
                "approval_scope": "review_only_no_auto_paper_no_live",
                "reviewed_packet_hash": {"sha256": record_sha256},
            },
            "reviewed_packet": {
                "path": packet_relpath,
                "sha256": packet_sha256,
            },
            "paper_queue_write_allowed": False,
            "live_unlock_allowed": False,
            "gate": {
                "paper_queue_write_allowed": False,
                "live_unlock_allowed": False,
            },
        },
    )


def _write_approved_btc_review(data_root: Path) -> None:
    evidence = data_root / "research/evidence_packs/btc_review_001/evidence_pack.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps({"paper_review_id": "btc_review_001"}), encoding="utf-8")
    _write_json(
        data_root / "research/paper_reviews/btc_review_001/review.json",
        {
            "paper_review_id": "btc_review_001",
            "strategy_manifest_id": "btc_candidate_v1",
            "status": "APPROVED_FOR_PAPER_ONLY",
            "proposed_symbols": ["BTCUSDT"],
            "proposed_capital": 25_000.0,
            "evidence_pack_path": "data/research/evidence_packs/btc_review_001/evidence_pack.json",
            "approval": _valid_approval(
                source="data/research/evidence_packs/btc_review_001/evidence_pack.json",
                source_sha256=_sha256(evidence),
            ),
        },
    )


def _valid_approval(*, source: str, source_sha256: str = "0" * 64) -> dict[str, object]:
    return {
        "schema_version": "paper_review_approval_v1",
        "reviewer": "risk_reviewer",
        "reason": "paper validation approval only",
        "timestamp": "2026-05-23T00:00:00Z",
        "candidate_id": "btc_candidate_v1",
        "commit_hash": "fixture",
        "source": source,
        "source_sha256": source_sha256,
        "gate_snapshot": {
            "candidate_id": "btc_candidate_v1",
            "decision": "READY_FOR_PAPER_REVIEW",
            "paper_execution_authorized": False,
            "authorization_scope": "human_review_only",
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
