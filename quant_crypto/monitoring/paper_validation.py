from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash


BTC_PAPER_VALIDATION_ARTIFACT_VERSION = "btc_paper_validation_artifact_v1"


def build_btc_paper_validation_start_artifact(
    *,
    source_start_report: Mapping[str, Any],
    generated_at_utc: datetime,
) -> dict[str, Any]:
    blockers: list[str] = []
    if source_start_report.get("status") not in {"ready_to_start_paper_validation", "ready_to_resume_paper_validation"}:
        blockers.append("btc_paper_validation_start_source_not_ready")
    if source_start_report.get("paper_start_allowed") is not True:
        blockers.append("btc_paper_validation_start_not_allowed")
    if source_start_report.get("live_status") != "frozen":
        blockers.append("btc_paper_validation_live_not_frozen")
    ledger_session = _mapping(source_start_report.get("ledger_session"))
    ledger_hash = str(ledger_session.get("latest_reconciliation_artifact_hash") or "")
    if not ledger_hash:
        blockers.append("btc_paper_validation_ledger_hash_missing")
    payload = {
        "paper_validation_artifact_version": BTC_PAPER_VALIDATION_ARTIFACT_VERSION,
        "artifact_type": "start",
        "status": "complete" if not blockers else "blocked",
        "run_id": str(source_start_report.get("run_id") or source_start_report.get("paper_review_id") or "btc_paper_validation_start"),
        "strategy_id": str(_mapping(source_start_report.get("approved_paper_review")).get("strategy_manifest_id") or ""),
        "ledger_root": ledger_session.get("ledger_root"),
        "ledger_hash": ledger_hash,
        "paper_oms_lifecycle_required": True,
        "audit_dag_required": True,
        "replay_required": True,
        "allows_live_orders": False,
        "real_order_submitted": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "source_report_status": source_start_report.get("status"),
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="paper_validation_start_ready" if not blockers else "paper_validation_start_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=generated_at_utc,
        blockers=blockers,
        warnings=[],
        input_hashes={"source_start_report": stable_payload_hash(source_start_report)},
    )


def build_btc_paper_validation_runtime_artifact(
    *,
    run_id: str,
    generated_at_utc: datetime,
    ledger_hash: str = "",
    paper_oms_lifecycle_hash: str = "",
    audit_dag_hash: str = "",
    replay_hash: str = "",
    runtime_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    runtime = dict(runtime_report or {})
    blockers: list[str] = []
    if not run_id:
        blockers.append("btc_paper_validation_runtime_run_id_missing")
    if not ledger_hash:
        blockers.append("btc_paper_validation_runtime_ledger_hash_missing")
    if not paper_oms_lifecycle_hash:
        blockers.append("btc_paper_validation_runtime_paper_oms_lifecycle_hash_missing")
    if not audit_dag_hash:
        blockers.append("btc_paper_validation_runtime_audit_dag_hash_missing")
    if not replay_hash:
        blockers.append("btc_paper_validation_runtime_replay_hash_missing")
    if runtime.get("real_order_submitted") is True:
        blockers.append("btc_paper_validation_runtime_real_order_submitted")
    if runtime.get("order_endpoint_used") is True:
        blockers.append("btc_paper_validation_runtime_order_endpoint_used")
    if runtime.get("private_endpoint_used") is True:
        blockers.append("btc_paper_validation_runtime_private_endpoint_used")
    payload = {
        "paper_validation_artifact_version": BTC_PAPER_VALIDATION_ARTIFACT_VERSION,
        "artifact_type": "runtime",
        "status": "complete" if not blockers else "blocked",
        "run_id": run_id,
        "ledger_hash": ledger_hash,
        "paper_oms_lifecycle_hash": paper_oms_lifecycle_hash,
        "audit_dag_hash": audit_dag_hash,
        "replay_hash": replay_hash,
        "allows_live_orders": False,
        "real_order_submitted": bool(runtime.get("real_order_submitted", False)),
        "private_endpoint_used": bool(runtime.get("private_endpoint_used", False)),
        "order_endpoint_used": bool(runtime.get("order_endpoint_used", False)),
        "runtime_report": runtime,
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="paper_validation_runtime_complete" if not blockers else "paper_validation_runtime_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=generated_at_utc,
        blockers=blockers,
        warnings=[],
        input_hashes={
            "runtime_report": stable_payload_hash(runtime),
            "ledger": ledger_hash,
            "paper_oms_lifecycle": paper_oms_lifecycle_hash,
            "audit_dag": audit_dag_hash,
            "replay": replay_hash,
        },
    )


def build_btc_paper_validation_evaluation_artifact(
    *,
    source_evaluation_report: Mapping[str, Any],
    generated_at_utc: datetime,
    runtime_artifact_hash: str = "",
    runtime_artifact_status: str = "",
) -> dict[str, Any]:
    blockers: list[str] = []
    metrics = _mapping(source_evaluation_report.get("metrics"))
    conclusion = _mapping(source_evaluation_report.get("conclusion"))
    if metrics.get("system_passed") is not True:
        blockers.append("btc_paper_validation_evaluation_system_not_passed")
    if not runtime_artifact_hash:
        blockers.append("btc_paper_validation_evaluation_runtime_hash_missing")
    if runtime_artifact_status and runtime_artifact_status != "complete":
        blockers.append("btc_paper_validation_evaluation_runtime_not_complete")
    if source_evaluation_report.get("asset") != "btc":
        blockers.append("btc_paper_validation_evaluation_asset_not_btc")
    payload = {
        "paper_validation_artifact_version": BTC_PAPER_VALIDATION_ARTIFACT_VERSION,
        "artifact_type": "evaluation",
        "status": "complete" if not blockers else "blocked",
        "run_id": str(source_evaluation_report.get("run_id") or "btc_paper_validation_evaluation"),
        "days_completed": metrics.get("days_completed"),
        "total_orders": metrics.get("total_orders"),
        "total_fills": metrics.get("total_fills"),
        "total_rejected": metrics.get("total_rejected"),
        "system_conclusion": conclusion.get("system"),
        "profitability_conclusion": conclusion.get("profitability"),
        "runtime_artifact_hash": runtime_artifact_hash,
        "runtime_artifact_status": runtime_artifact_status,
        "allows_live_orders": False,
        "blockers": blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="paper_validation_evaluation_complete" if not blockers else "paper_validation_evaluation_blocked",
        generated_at_utc=generated_at_utc,
        as_of_utc=generated_at_utc,
        blockers=blockers,
        warnings=[],
        input_hashes={
            "source_evaluation_report": stable_payload_hash(source_evaluation_report),
            "runtime_artifact": runtime_artifact_hash,
        },
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
