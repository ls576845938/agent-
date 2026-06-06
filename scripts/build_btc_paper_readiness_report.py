#!/usr/bin/env python3
"""Build a fail-closed BTC paper-readiness report from persisted evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from quant_crypto.data.btc_perpetual_provider_config import selected_btc_perpetual_bundle_dir


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_paper_readiness/latest")
DEFAULT_DATA_ROOT = Path("data")
DEFAULT_CONFIG = Path("configs/data/btc_perpetual_sources.yaml")
OBJECTIVE_AUDIT = Path("artifacts/btc_data_status/latest/btc_objective_completion_audit_report.json")
BUNDLE_PREFLIGHT = Path("artifacts/btc_data_status/latest/btc_perpetual_bundle_preflight_report.json")
PROVIDER_VERIFICATION = Path("artifacts/btc_data_status/latest/btc_perpetual_provider_verification_report.json")
DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
FUNDING_LEDGER = Path("artifacts/btc_cost_model/latest/btc_funding_ledger_report.json")
TAIL_DEPENDENCY = Path("artifacts/btc_tail_dependency/latest/tail_dependency_report.json")
CANDIDATE_GATE = Path("artifacts/btc_candidate_gate/latest/candidate_gate_audit_report.json")
CANDIDATE_METRIC_REPAIR = Path("artifacts/btc_candidate_gate/latest/candidate_metric_repair_report.json")
BTC_REGISTRY = Path("artifacts/btc_research_registry/research_registry.json")
GLOBAL_REGISTRY = Path("artifacts/global_research_registry/research_registry.json")
OPERATOR_PACKET = Path("artifacts/btc_data_status/latest/btc_manual_metadata_capture_operator_packet.json")
MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER = ".btc_manual_metadata_import_in_progress.json"
DIAGNOSTIC_ONLY_WARNINGS = {
    "btc_open_interest_history_not_verified_diagnostic_partial",
    "btc_agg_trades_missing",
    "btc_liquidation_snapshot_missing_diagnostic_only",
    "btc_liquidation_snapshots_missing_diagnostic_only",
    "diagnostic_only_not_gate_evidence",
}


def build_btc_paper_readiness_report(
    *,
    repo_root: Path | None = None,
    data_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    paper_data_root = _resolve(root, data_root or DEFAULT_DATA_ROOT)
    evidence = {
        "objective_audit": _read_json(root / OBJECTIVE_AUDIT),
        "bundle_preflight": _read_json(root / BUNDLE_PREFLIGHT),
        "provider_verification": _read_json(root / PROVIDER_VERIFICATION),
        "data_status": _read_json(root / DATA_STATUS),
        "cost_model": _read_json(root / COST_MODEL),
        "funding_ledger": _read_json(root / FUNDING_LEDGER),
        "tail_dependency": _read_json(root / TAIL_DEPENDENCY),
        "candidate_gate": _read_json(root / CANDIDATE_GATE),
        "candidate_metric_repair": _read_json(root / CANDIDATE_METRIC_REPAIR),
        "btc_registry": _read_json(root / BTC_REGISTRY),
        "global_registry": _read_json(root / GLOBAL_REGISTRY),
        "operator_packet": _read_json(root / OPERATOR_PACKET),
    }
    generated = generated_at or _utc_z_now()
    approved_review = _latest_approved_btc_paper_review(paper_data_root)
    manual_inputs = _manual_inputs_summary(evidence["operator_packet"])
    requirements = {
        "manual_input_gate": _manual_input_gate(evidence, root, manual_inputs),
        "data_source_gate": _data_source_gate(evidence, root),
        "cost_ledger_gate": _cost_ledger_gate(evidence, root),
        "candidate_gate": _candidate_gate(evidence, root),
        "paper_review_gate": _paper_review_gate(approved_review),
        "runtime_boundary_gate": _runtime_boundary_gate(evidence),
    }
    blockers = _dedupe([item for gate in requirements.values() for item in gate["blockers"]])
    hard_ready = all(
        requirements[name]["status"] == "complete"
        for name in (
            "manual_input_gate",
            "data_source_gate",
            "cost_ledger_gate",
            "candidate_gate",
            "runtime_boundary_gate",
        )
    )
    paper_review_complete = requirements["paper_review_gate"]["status"] == "complete"
    if hard_ready and paper_review_complete:
        status = "ready_for_paper_start"
        next_required_action = "start_paper_validation"
        paper_queue_status = "approved"
        paper_start_allowed = True
    elif hard_ready:
        status = "ready_for_manual_paper_review"
        next_required_action = "human_paper_review_approval"
        paper_queue_status = "pending_review"
        paper_start_allowed = False
    else:
        status = "blocked"
        next_required_action = _next_required_action(requirements)
        paper_queue_status = "locked"
        paper_start_allowed = False

    return {
        "schema_version": "btc_paper_readiness_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "status": status,
        "paper_queue_status": paper_queue_status,
        "paper_start_allowed": paper_start_allowed,
        "paper_execution_authorized": paper_start_allowed,
        "live_status": "frozen",
        "next_required_action": next_required_action,
        "manual_inputs_status": manual_inputs["manual_inputs_status"],
        "paper_gate_manual_inputs_complete": manual_inputs["paper_gate_manual_inputs_complete"],
        "required_manual_inputs": manual_inputs["required_manual_inputs"],
        "fee_tier_status": manual_inputs["fee_tier_status"],
        "requirements": requirements,
        "approved_paper_review": approved_review,
        "blockers": blockers if status == "blocked" else ([] if paper_start_allowed else requirements["paper_review_gate"]["blockers"]),
        "evidence": _evidence_paths(root),
    }


def write_btc_paper_readiness_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_paper_readiness_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_paper_readiness_report(
        repo_root=Path(args.repo_root),
        data_root=Path(args.data_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_paper_readiness_report(payload, Path(args.output_root)))


def _data_source_gate(evidence: Mapping[str, Mapping[str, Any]], root: Path) -> dict[str, Any]:
    objective = evidence["objective_audit"]
    preflight = evidence["bundle_preflight"]
    provider = evidence["provider_verification"]
    data_status = evidence["data_status"]
    manual_import_marker = _manual_metadata_import_marker(root)
    checks = {
        "objective_goal_complete": bool(objective.get("goal_complete", False)),
        "bundle_preflight_pass": bool(preflight.get("preflight_pass", False)),
        "provider_perpetual_evidence_ready": bool(provider.get("perpetual_evidence_ready", False)),
        "exchange_info_verified": bool(provider.get("exchange_info_verified", False)),
        "funding_info_verified": bool(provider.get("funding_info_verified", False)),
        "funding_info_endpoint_response_available": bool(
            provider.get("funding_info_endpoint_response_available", False)
        ),
        "data_status_pass": str(data_status.get("status", "missing")) == "pass",
        "manual_metadata_import_not_in_progress": manual_import_marker is None,
    }
    blockers: list[str] = []
    if not checks["objective_goal_complete"]:
        blockers.append("btc_paper_readiness_objective_audit_incomplete")
    if not checks["bundle_preflight_pass"]:
        blockers.append("btc_paper_readiness_bundle_preflight_not_pass")
    if not checks["provider_perpetual_evidence_ready"]:
        blockers.append("btc_paper_readiness_provider_not_ready")
    if not checks["exchange_info_verified"]:
        blockers.append("btc_paper_readiness_exchange_info_not_verified")
    if not checks["funding_info_verified"]:
        blockers.append("btc_paper_readiness_funding_info_not_verified")
    if not checks["funding_info_endpoint_response_available"]:
        blockers.append("btc_paper_readiness_funding_info_endpoint_response_missing")
    if not checks["data_status_pass"]:
        blockers.append("btc_paper_readiness_data_status_not_pass")
    if manual_import_marker is not None:
        blockers.append("btc_paper_readiness_manual_metadata_import_in_progress")
    blockers.extend(_hard_blockers(_list_of_strings(objective.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(preflight.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(provider.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(data_status.get("blockers"))))
    return _requirement(
        "complete" if not blockers else "blocked",
        checks=checks,
        blockers=blockers,
        evidence={
            "objective_audit": _relpath(root / OBJECTIVE_AUDIT, root),
            "bundle_preflight": _relpath(root / BUNDLE_PREFLIGHT, root),
            "provider_verification": _relpath(root / PROVIDER_VERIFICATION, root),
            "data_status": _relpath(root / DATA_STATUS, root),
            "manual_metadata_import_marker": _relpath(manual_import_marker, root) if manual_import_marker else "",
        },
    )


def _manual_input_gate(
    evidence: Mapping[str, Mapping[str, Any]],
    root: Path,
    manual_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    operator_packet = evidence["operator_packet"]
    fee_tier = _mapping(manual_inputs.get("fee_tier_status"))
    required_inputs = [
        item for item in manual_inputs.get("required_manual_inputs", []) if isinstance(item, Mapping)
    ]
    checks = {
        "operator_packet_status": str(operator_packet.get("status", "missing") or "missing"),
        "manual_inputs_status": str(manual_inputs.get("manual_inputs_status", "awaiting_manual_inputs")),
        "paper_gate_manual_inputs_complete": bool(manual_inputs.get("paper_gate_manual_inputs_complete", False)),
        "required_manual_input_count": len(required_inputs),
        "exchange_info_input_verified": _manual_input_verified(required_inputs, "exchange_info"),
        "funding_info_input_verified": _manual_input_verified(required_inputs, "funding_info"),
        "fee_tier_input_verified": _manual_input_verified(required_inputs, "fee_tier_overlay"),
        "fee_tier_verified": bool(fee_tier.get("fee_tier_verified", False)),
    }
    blockers: list[str] = []
    if not checks["paper_gate_manual_inputs_complete"]:
        blockers.append("btc_paper_readiness_manual_inputs_incomplete")
    if checks["required_manual_input_count"] < 3:
        blockers.append("btc_paper_readiness_required_manual_inputs_missing")
    if not checks["exchange_info_input_verified"]:
        blockers.append("btc_paper_readiness_exchange_info_manual_input_missing")
    if not checks["funding_info_input_verified"]:
        blockers.append("btc_paper_readiness_funding_info_manual_input_missing")
    if not checks["fee_tier_input_verified"]:
        blockers.append("btc_paper_readiness_fee_tier_manual_input_missing")
    blockers.extend(_list_of_strings(operator_packet.get("blockers")))
    return _requirement(
        "complete" if not blockers else "blocked",
        checks=checks,
        blockers=blockers,
        evidence={"operator_packet": _relpath(root / OPERATOR_PACKET, root)},
    )


def _cost_ledger_gate(evidence: Mapping[str, Mapping[str, Any]], root: Path) -> dict[str, Any]:
    cost = evidence["cost_model"]
    funding = evidence["funding_ledger"]
    tail = evidence["tail_dependency"]
    fee_model = _mapping(cost.get("fee_model"))
    fee_blockers = _list_of_strings(fee_model.get("fee_blockers"))
    maker_fee_bps = _non_negative_float_or_none(fee_model.get("maker_fee_bps"))
    taker_fee_bps = _non_negative_float_or_none(fee_model.get("taker_fee_bps"))
    checks = {
        "cost_model_pass": str(cost.get("status", "missing")) == "pass",
        "fee_tier_verified": bool(fee_model.get("fee_tier_verified", False)),
        "fee_tier_import_report_verified": bool(fee_model.get("fee_tier_import_report_verified", False)),
        "fee_tier_overlay_present": bool(str(fee_model.get("fee_tier_overlay", "") or "").strip()),
        "fee_tier_import_report_present": bool(str(fee_model.get("fee_tier_import_report", "") or "").strip()),
        "maker_fee_bps_present": maker_fee_bps is not None,
        "taker_fee_bps_present": taker_fee_bps is not None,
        "fee_blockers_empty": not fee_blockers,
        "funding_payment_in_ledger": bool(funding.get("funding_payment_in_ledger", False)),
        "funding_merged_into_net_ledger": bool(funding.get("funding_merged_into_net_ledger", False)),
        "funding_adjusted_net_pnl_reconciled": bool(
            funding.get("funding_adjusted_net_pnl_reconciled", False)
        )
        and _float_or_default(funding.get("funding_adjusted_net_pnl_reconciliation_delta"), 1.0) == 0.0,
        "tail_dependency_pass": bool(tail.get("tail_dependency_pass", False)),
    }
    blockers: list[str] = []
    if not checks["cost_model_pass"]:
        blockers.append("btc_paper_readiness_cost_model_not_pass")
    if not all(
        checks[name]
        for name in (
            "fee_tier_verified",
            "fee_tier_import_report_verified",
            "fee_tier_overlay_present",
            "fee_tier_import_report_present",
            "maker_fee_bps_present",
            "taker_fee_bps_present",
            "fee_blockers_empty",
        )
    ):
        blockers.append("btc_paper_readiness_fee_tier_cost_model_not_verified")
    if not checks["funding_payment_in_ledger"]:
        blockers.append("btc_paper_readiness_funding_payment_not_in_ledger")
    if not checks["funding_merged_into_net_ledger"]:
        blockers.append("btc_paper_readiness_funding_not_merged_into_net_ledger")
    if not checks["funding_adjusted_net_pnl_reconciled"]:
        blockers.append("btc_paper_readiness_funding_adjusted_net_pnl_not_reconciled")
    if not checks["tail_dependency_pass"]:
        blockers.append("btc_paper_readiness_tail_dependency_not_pass")
    blockers.extend(_hard_blockers(fee_blockers))
    blockers.extend(_hard_blockers(_list_of_strings(cost.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(funding.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(tail.get("blockers"))))
    return _requirement(
        "complete" if not blockers else "blocked",
        checks=checks,
        blockers=blockers,
        evidence={
            "cost_model": _relpath(root / COST_MODEL, root),
            "funding_ledger": _relpath(root / FUNDING_LEDGER, root),
            "tail_dependency": _relpath(root / TAIL_DEPENDENCY, root),
        },
    )


def _candidate_gate(evidence: Mapping[str, Mapping[str, Any]], root: Path) -> dict[str, Any]:
    candidate = evidence["candidate_gate"]
    metric_repair = evidence["candidate_metric_repair"]
    btc_registry = _mapping(evidence["btc_registry"].get("btc"))
    global_registry = evidence["global_registry"]
    candidate_count = int(
        candidate.get(
            "candidate_passed_internal_gate",
            btc_registry.get("candidate_passed_internal_gate", global_registry.get("candidate_passed_internal_gate", 0)),
        )
        or 0
    )
    paper_allowed = bool(candidate.get("paper_review_pending_allowed", False))
    metric_repair_status = str(metric_repair.get("status", "missing") or "missing")
    metric_repair_failed_metrics = _list_of_strings(metric_repair.get("failed_metrics"))
    registry_current_candidates = _list_of_strings(btc_registry.get("current_candidates"))
    checks = {
        "candidate_gate_pass": str(candidate.get("status", "missing")) == "pass",
        "candidate_passed_internal_gate": candidate_count,
        "paper_review_pending_allowed": paper_allowed,
        "candidate_metric_repair_status": metric_repair_status,
        "candidate_metric_repair_promotion_allowed": bool(metric_repair.get("promotion_allowed", False)),
        "candidate_metric_repair_paper_review_pending_allowed": bool(
            metric_repair.get("paper_review_pending_allowed", False)
        ),
        "candidate_metric_repair_failed_metrics": metric_repair_failed_metrics,
        "registry_current_candidate_count": len(registry_current_candidates),
        "global_paper_queue_unlocked": str(global_registry.get("paper_queue_status", "locked")) != "locked",
    }
    blockers: list[str] = []
    if not checks["candidate_gate_pass"]:
        blockers.append("btc_paper_readiness_candidate_gate_not_pass")
    if candidate_count <= 0:
        blockers.append("btc_paper_readiness_no_candidate_passed_internal_gate")
    if not paper_allowed:
        blockers.append("btc_paper_readiness_paper_review_pending_not_allowed")
    if len(registry_current_candidates) <= 0:
        blockers.append("btc_paper_readiness_no_current_candidate_registered")
    if not (root / CANDIDATE_METRIC_REPAIR).exists():
        blockers.append("btc_paper_readiness_candidate_metric_repair_report_missing")
    if metric_repair_status != "candidate_metric_gate_passed":
        blockers.append("btc_paper_readiness_candidate_metric_repair_not_pass")
    if not checks["candidate_metric_repair_promotion_allowed"]:
        blockers.append("btc_paper_readiness_candidate_metric_repair_promotion_not_allowed")
    if not checks["candidate_metric_repair_paper_review_pending_allowed"]:
        blockers.append("btc_paper_readiness_candidate_metric_repair_review_not_allowed")
    for metric in metric_repair_failed_metrics:
        blockers.append(f"btc_paper_readiness_candidate_metric_repair_{metric}_failed")
    blockers.extend(_hard_blockers(_list_of_strings(candidate.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(metric_repair.get("blockers"))))
    blockers.extend(_hard_blockers(_list_of_strings(btc_registry.get("blockers"))))
    return _requirement(
        "complete" if not blockers else "blocked",
        checks=checks,
        blockers=blockers,
        evidence={
            "candidate_gate": _relpath(root / CANDIDATE_GATE, root),
            "candidate_metric_repair": _relpath(root / CANDIDATE_METRIC_REPAIR, root),
            "btc_registry": _relpath(root / BTC_REGISTRY, root),
            "global_registry": _relpath(root / GLOBAL_REGISTRY, root),
        },
    )


def _paper_review_gate(approved_review: Mapping[str, Any]) -> dict[str, Any]:
    approval = _mapping(approved_review.get("approval"))
    checks = {
        "approved_review_found": bool(approved_review.get("approved")),
        "review_status": str(approved_review.get("status", "")),
        "review_path": str(approved_review.get("path", "")),
        "evidence_pack_exists": bool(approved_review.get("evidence_pack_exists", False)),
        "approval_valid": bool(approval.get("valid", False)),
        "approval_reviewer": str(approval.get("reviewer", "")),
        "approval_timestamp": str(approval.get("timestamp", "")),
        "approval_candidate_id": str(approval.get("candidate_id", "")),
        "approval_source": str(approval.get("source", "")),
    }
    blockers: list[str] = []
    if not checks["approved_review_found"]:
        blockers.append("btc_paper_readiness_approved_paper_review_missing")
    if checks["approved_review_found"] and not checks["evidence_pack_exists"]:
        blockers.append("btc_paper_readiness_approved_paper_review_evidence_pack_missing")
    if checks["approved_review_found"]:
        blockers.extend(_list_of_strings(approval.get("blockers")))
    return _requirement(
        (
            "complete"
            if checks["approved_review_found"]
            and checks["evidence_pack_exists"]
            and checks["approval_valid"]
            else "pending_review"
        ),
        checks=checks,
        blockers=blockers,
        evidence={"paper_review": str(approved_review.get("path", ""))},
    )


def _runtime_boundary_gate(evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    candidate = evidence["candidate_gate"]
    btc_registry = _mapping(evidence["btc_registry"].get("btc"))
    global_registry = evidence["global_registry"]
    checks = {
        "live_status_frozen": str(
            candidate.get("live_status", btc_registry.get("live_status", global_registry.get("live_status", "frozen")))
        ).lower()
        == "frozen",
        "paper_auto_start_disabled": bool(candidate.get("paper_auto_start", False)) is False,
        "paper_start_requires_human_review": True,
        "strategy_direct_broker_forbidden": True,
        "real_order_submission_authorized": False,
    }
    blockers: list[str] = []
    if not checks["live_status_frozen"]:
        blockers.append("btc_paper_readiness_live_status_not_frozen")
    if not checks["paper_auto_start_disabled"]:
        blockers.append("btc_paper_readiness_paper_auto_start_enabled")
    if not checks["paper_start_requires_human_review"]:
        blockers.append("btc_paper_readiness_human_review_gate_missing")
    return _requirement("complete" if not blockers else "blocked", checks=checks, blockers=blockers, evidence={})


def _latest_approved_btc_paper_review(data_root: Path) -> dict[str, Any]:
    reviews_dir = data_root / "research" / "paper_reviews"
    rows: list[dict[str, Any]] = []
    if reviews_dir.exists():
        for path in sorted(reviews_dir.glob("*/review.json")):
            payload = _read_json(path)
            symbols = _normalized_symbols(payload.get("proposed_symbols", []))
            status = str(payload.get("status", ""))
            if status != "APPROVED_FOR_PAPER_ONLY" or "BTCUSDT" not in symbols:
                continue
            evidence_pack_raw = str(payload.get("evidence_pack_path", "")).strip()
            evidence_pack_path: Path | None = None
            if evidence_pack_raw:
                evidence_pack_path = _resolve_review_artifact_path(data_root, evidence_pack_raw)
            approval = _approval_summary(
                payload,
                data_root=data_root,
                evidence_pack_path=evidence_pack_path,
            )
            rows.append(
                {
                    "approved": True,
                    "paper_review_id": str(payload.get("paper_review_id", path.parent.name)),
                    "status": status,
                    "path": str(path),
                    "strategy_manifest_id": str(payload.get("strategy_manifest_id", "")),
                    "proposed_symbols": symbols,
                    "proposed_capital": float(payload.get("proposed_capital", 0.0) or 0.0),
                    "evidence_pack_path": str(evidence_pack_path) if evidence_pack_path is not None else "",
                    "evidence_pack_exists": bool(evidence_pack_path is not None and evidence_pack_path.exists()),
                    "approval": approval,
                }
            )
    if rows:
        return rows[-1]
    return {
        "approved": False,
        "paper_review_id": "",
        "status": "missing",
        "path": "",
        "strategy_manifest_id": "",
        "proposed_symbols": [],
        "proposed_capital": 0.0,
        "evidence_pack_path": "",
        "evidence_pack_exists": False,
        "approval": _missing_approval_summary(),
    }


def _approval_summary(
    payload: Mapping[str, Any],
    *,
    data_root: Path,
    evidence_pack_path: Path | None,
) -> dict[str, Any]:
    approval_present = isinstance(payload.get("approval"), Mapping)
    approval = _mapping(payload.get("approval"))
    gate_snapshot = _mapping(approval.get("gate_snapshot"))
    reviewer = str(approval.get("reviewer") or payload.get("reviewer", "") or "").strip()
    timestamp = str(approval.get("timestamp") or payload.get("reviewed_at", "") or "").strip()
    candidate_id = str(approval.get("candidate_id", "") or "").strip()
    source = str(approval.get("source", "") or payload.get("evidence_pack_path", "") or "").strip()
    source_sha256 = str(approval.get("source_sha256", "") or "").strip()
    schema_version = str(approval.get("schema_version", "") or "").strip()
    blockers: list[str] = []
    if not approval_present:
        blockers.append("btc_paper_readiness_approved_paper_review_approval_missing")
    if schema_version != "paper_review_approval_v1":
        blockers.append("btc_paper_readiness_approved_paper_review_approval_schema_invalid")
    if not reviewer:
        blockers.append("btc_paper_readiness_approved_paper_review_reviewer_missing")
    if not timestamp or not _is_utc_timestamp(timestamp):
        blockers.append("btc_paper_readiness_approved_paper_review_timestamp_invalid")
    if not candidate_id:
        blockers.append("btc_paper_readiness_approved_paper_review_candidate_missing")
    if not source:
        blockers.append("btc_paper_readiness_approved_paper_review_source_missing")
    source_path = _resolve_review_artifact_path(data_root, source) if source else None
    if source_path is not None and evidence_pack_path is not None and not _same_resolved_path(source_path, evidence_pack_path):
        blockers.append("btc_paper_readiness_approved_paper_review_source_not_evidence_pack")
    if not _is_sha256(source_sha256):
        blockers.append("btc_paper_readiness_approved_paper_review_source_sha256_invalid")
    elif evidence_pack_path is not None:
        if not evidence_pack_path.exists():
            blockers.append("btc_paper_readiness_approved_paper_review_source_file_missing")
        elif _sha256(evidence_pack_path) != source_sha256:
            blockers.append("btc_paper_readiness_approved_paper_review_source_sha256_mismatch")
    if not gate_snapshot:
        blockers.append("btc_paper_readiness_approved_paper_review_gate_snapshot_missing")
    if gate_snapshot and gate_snapshot.get("paper_execution_authorized") is not False:
        blockers.append("btc_paper_readiness_approved_paper_review_scope_not_record_only")
    return {
        "valid": not blockers,
        "schema_version": schema_version,
        "reviewer": reviewer,
        "reason": str(approval.get("reason", "") or payload.get("review_notes", "") or ""),
        "timestamp": timestamp,
        "candidate_id": candidate_id,
        "commit_hash": str(approval.get("commit_hash", "") or ""),
        "source": source,
        "source_sha256": source_sha256,
        "gate_snapshot": gate_snapshot,
        "blockers": blockers,
    }


def _missing_approval_summary() -> dict[str, Any]:
    return {
        "valid": False,
        "schema_version": "",
        "reviewer": "",
        "reason": "",
        "timestamp": "",
        "candidate_id": "",
        "commit_hash": "",
        "source": "",
        "source_sha256": "",
        "gate_snapshot": {},
        "blockers": ["btc_paper_readiness_approved_paper_review_approval_missing"],
    }


def _resolve_review_artifact_path(data_root: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    candidates: list[Path] = []
    if path.parts and path.parts[0] == data_root.name:
        candidates.append(data_root.parent / path)
    candidates.append(data_root / path)
    candidates.append(data_root.parent / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _same_resolved_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def _is_sha256(raw: str) -> bool:
    return len(raw) == 64 and all(char in "0123456789abcdefABCDEF" for char in raw)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_utc_timestamp(raw: str) -> bool:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _next_required_action(requirements: Mapping[str, Mapping[str, Any]]) -> str:
    if requirements["manual_input_gate"]["status"] != "complete":
        return "complete_btc_manual_paper_gate_inputs"
    if requirements["data_source_gate"]["status"] != "complete":
        return "repair_btc_data_source_metadata"
    if requirements["cost_ledger_gate"]["status"] != "complete":
        return "repair_btc_cost_ledger_evidence"
    if requirements["candidate_gate"]["status"] != "complete":
        return "produce_candidate_that_passes_internal_gate"
    if requirements["paper_review_gate"]["status"] != "complete":
        return "human_paper_review_approval"
    return "none"


def _requirement(
    status: str,
    *,
    checks: Mapping[str, Any],
    blockers: list[str],
    evidence: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "status": status,
        "checks": dict(checks),
        "blockers": _dedupe(blockers),
        "evidence": dict(evidence),
    }


def _evidence_paths(root: Path) -> dict[str, str | None]:
    paths = {
        "objective_audit": OBJECTIVE_AUDIT,
        "bundle_preflight": BUNDLE_PREFLIGHT,
        "provider_verification": PROVIDER_VERIFICATION,
        "data_status": DATA_STATUS,
        "operator_packet": OPERATOR_PACKET,
        "cost_model": COST_MODEL,
        "funding_ledger": FUNDING_LEDGER,
        "tail_dependency": TAIL_DEPENDENCY,
        "candidate_gate": CANDIDATE_GATE,
        "candidate_metric_repair": CANDIDATE_METRIC_REPAIR,
        "btc_registry": BTC_REGISTRY,
        "global_registry": GLOBAL_REGISTRY,
    }
    return {key: _relpath(root / path, root) if (root / path).exists() else None for key, path in paths.items()}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _manual_metadata_import_marker(root: Path) -> Path | None:
    bundle_dir = _selected_bundle_dir(root)
    if bundle_dir is None:
        return None
    marker = bundle_dir / MANUAL_METADATA_IMPORT_IN_PROGRESS_MARKER
    return marker if marker.exists() else None


def _selected_bundle_dir(root: Path) -> Path | None:
    config = root / DEFAULT_CONFIG
    return selected_btc_perpetual_bundle_dir(root, config)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _hard_blockers(values: list[str]) -> list[str]:
    return _dedupe([value for value in _list_of_strings(values) if value not in DIAGNOSTIC_ONLY_WARNINGS])


def _manual_inputs_summary(operator_packet: Mapping[str, Any]) -> dict[str, Any]:
    required_inputs = _manual_input_statuses(operator_packet.get("required_manual_inputs"))
    fee_tier = _mapping(operator_packet.get("fee_tier_status"))
    return {
        "manual_inputs_status": str(
            operator_packet.get("manual_inputs_status", "awaiting_manual_inputs") or "awaiting_manual_inputs"
        ),
        "paper_gate_manual_inputs_complete": bool(
            operator_packet.get("paper_gate_manual_inputs_complete", False)
        ),
        "required_manual_inputs": required_inputs,
        "fee_tier_status": {
            "cost_model_report": fee_tier.get("cost_model_report"),
            "cost_model_status": str(fee_tier.get("cost_model_status", "missing") or "missing"),
            "fee_tier_verified": bool(fee_tier.get("fee_tier_verified", False)),
            "manual_capture_required": bool(fee_tier.get("manual_capture_required", True)),
            "maker_fee_bps": _float_or_none(fee_tier.get("maker_fee_bps")),
            "taker_fee_bps": _float_or_none(fee_tier.get("taker_fee_bps")),
            "fee_tier_import_report_verified": bool(fee_tier.get("fee_tier_import_report_verified", False)),
            "fee_blockers": _list_of_strings(fee_tier.get("fee_blockers")),
        },
    }


def _manual_input_statuses(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        result.append(
            {
                "name": str(item.get("name", "")),
                "required_for": str(item.get("required_for", "")),
                "status": str(item.get("status", "awaiting_capture") or "awaiting_capture"),
                "action": str(
                    item.get("action", "manual_capture_from_allowed_network") or "manual_capture_from_allowed_network"
                ),
                "blockers": _list_of_strings(item.get("blockers")),
            }
        )
    return result


def _manual_input_verified(inputs: list[Mapping[str, Any]], name: str) -> bool:
    return any(str(item.get("name", "")) == name and str(item.get("status", "")) == "verified" for item in inputs)


def _float_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _non_negative_float_or_none(value: object) -> float | None:
    number = _float_or_none(value)
    if number is None or number < 0:
        return None
    return number


def _normalized_symbols(value: object) -> list[str]:
    return sorted({str(item).strip().upper() for item in _list_of_strings(value) if str(item).strip()})


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _float_or_default(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
