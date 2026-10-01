from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash
from .btc_root_cause_dag import build_btc_root_cause_dag, root_cause_summary


BTC_GATE_DASHBOARD_VERSION = "btc_gate_dashboard_v1"
HARD_BLOCKER_ARTIFACTS = {
    "perpetual_execution_evidence",
}


def build_btc_gate_dashboard(
    *,
    generated_at_utc: datetime,
    current_status: Mapping[str, Any],
    registry: Mapping[str, Any],
    paper_readiness: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any] | None],
    aggregation_batch_id: str | None = None,
    promotion_gate_control: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    current = _status_text(current_status)
    readiness_status = str(paper_readiness.get("status") or "")
    live_status = str(current_status.get("live_status") or paper_readiness.get("live_status") or "")
    registry_btc = _mapping(_mapping(registry.get("assets")).get("btc"))
    source_summary = {
        "current_status": _source_summary(current_status, status=current),
        "paper_readiness": _source_summary(paper_readiness, status=readiness_status),
        "registry": _source_summary(registry, status=str(registry_btc.get("status", ""))),
    }
    if current != "paper_observing":
        blockers.append("btc_gate_dashboard_current_status_not_paper_observing")
    if readiness_status not in {"ready_for_paper_start", "APPROVED_FOR_PAPER_ONLY"}:
        blockers.append("btc_gate_dashboard_paper_readiness_not_ready")
    if live_status != "frozen":
        blockers.append("btc_gate_dashboard_live_status_not_frozen")
    if registry_btc and str(registry_btc.get("paper_queue_status", "")) != "approved":
        blockers.append("btc_gate_dashboard_registry_paper_queue_not_approved")
    artifact_summary: dict[str, Any] = {}
    for name, artifact in artifacts.items():
        if not artifact:
            artifact_summary[name] = _missing_artifact_summary()
            blockers.append(f"btc_gate_dashboard_artifact_missing:{name}")
            continue
        artifact_blockers = [str(item) for item in artifact.get("blockers", []) if item]
        artifact_summary[name] = _source_summary(artifact, blockers=artifact_blockers)
        if str(artifact.get("status", "")) == "blocked":
            blockers.append(f"btc_gate_dashboard_artifact_blocked:{name}")
        if name in HARD_BLOCKER_ARTIFACTS:
            blockers.extend(f"btc_gate_dashboard_artifact_blocker:{name}:{blocker}" for blocker in artifact_blockers)
        if name == "micro_live_preflight" and _micro_live_preflight_blocked(artifact):
            blockers.append("btc_gate_dashboard_micro_live_preflight_blocked")
        blockers.extend(f"btc_gate_dashboard_unsafe_flag:{name}.{flag}" for flag in _unsafe_flags(artifact))

    live_readiness = artifact_summary.get("live_readiness", {})
    micro_live_preflight = artifact_summary.get("micro_live_preflight", {})
    daily_observation = artifact_summary.get("daily_observation", {})
    api_key_audit = artifacts.get("api_key_permission_audit") or {}
    order_surface_audit = artifacts.get("order_surface_audit") or {}
    account_attestation = artifacts.get("account_attestation") or {}
    dashboard_blockers = _dedupe(blockers)
    root_cause_blockers = _root_cause_blockers(dashboard_blockers, artifact_summary)
    root_cause_dag = build_btc_root_cause_dag(
        {"gate_dashboard": root_cause_blockers},
        gate_sources={
            "gate_dashboard": [
                "current_status",
                "paper_readiness",
                "registry",
                *sorted(artifact_summary),
            ]
        },
        root_node_id="btc_gate_dashboard_blocked",
    )
    promotion_root_cause = _promotion_root_cause_overlay(promotion_gate_control)
    if promotion_gate_control:
        source_summary["promotion_gate_control"] = _source_summary(
            _mapping(promotion_gate_control),
            status=str(_mapping(promotion_gate_control).get("status", "")),
        )
    displayed_root_cause_dag = (
        promotion_root_cause["root_cause_dag"] if promotion_root_cause is not None else root_cause_dag
    )
    displayed_root_cause_matrix = (
        promotion_root_cause["root_cause_matrix"]
        if promotion_root_cause is not None
        else root_cause_dag["root_cause_matrix"]
    )
    displayed_root_cause_summary = (
        promotion_root_cause["root_cause_summary"]
        if promotion_root_cause is not None
        else root_cause_summary(root_cause_dag)
    )
    payload = {
        "gate_dashboard_version": BTC_GATE_DASHBOARD_VERSION,
        "aggregation_batch_id": aggregation_batch_id or "",
        "code_commit": _git_commit(),
        "status": "blocked" if dashboard_blockers else "complete",
        "coverage": {
            "current_status": "current_status" in source_summary,
            "paper_validation": all(
                key in artifact_summary
                for key in ["paper_validation_start", "paper_validation_runtime", "paper_validation_evaluation"]
            ),
            "daily_observation": "daily_observation" in artifact_summary,
            "cost_model": "cost_model" in artifact_summary,
            "funding_ledger": "funding_ledger" in artifact_summary,
            "perpetual_route_request": "perpetual_route_request" in artifact_summary,
            "perpetual_policy_status": "perpetual_policy_status" in artifact_summary,
            "perpetual_execution_evidence": "perpetual_execution_evidence" in artifact_summary,
            "live_readiness": "live_readiness" in artifact_summary,
            "micro_live_preflight": "micro_live_preflight" in artifact_summary,
            "api_key_permission_audit": "api_key_permission_audit" in artifact_summary,
            "order_surface_audit": "order_surface_audit" in artifact_summary,
            "account_attestation": "account_attestation" in artifact_summary,
            "exchange_runtime": "exchange_runtime_contract" in artifact_summary,
        },
        "research_state": current,
        "paper_state": {
            "readiness_status": readiness_status,
            "paper_queue_status": paper_readiness.get("paper_queue_status"),
            "paper_start_allowed": paper_readiness.get("paper_start_allowed"),
        },
        "live_state": {
            "live_status": live_status,
            "live_candidate": False,
            "live_order_allowed": False,
            "live_readiness_status": live_readiness.get("status", ""),
            "live_readiness_blockers": live_readiness.get("blockers", []),
            "micro_live_allowed": False,
            "micro_live_preflight_status": micro_live_preflight.get("status", ""),
            "micro_live_preflight_blocker_count": len(micro_live_preflight.get("blockers", [])),
        },
        "forward_observation": {
            "status": daily_observation.get("status", ""),
            "observation_days": _nested_int(artifacts.get("daily_observation") or {}, "forward_observation.observation_days"),
            "minimum_complete_days": _nested_int(artifacts.get("live_readiness") or {}, "forward_observation.minimum_complete_days"),
        },
        "registry_state": {
            "paper_queue_status": registry_btc.get("paper_queue_status"),
            "candidate_passed_internal_gate": registry_btc.get("candidate_passed_internal_gate"),
        },
        "perpetual_state": _perpetual_state(artifacts.get("perpetual_policy_status") or {}),
        "security_attestation_state": _security_attestation_state(
            api_key_audit=api_key_audit,
            order_surface_audit=order_surface_audit,
            account_attestation=account_attestation,
        ),
        "sources": source_summary,
        "artifacts": artifact_summary,
        "root_cause_source": "promotion_gate_control" if promotion_root_cause is not None else "gate_dashboard",
        "root_cause_summary": displayed_root_cause_summary,
        "root_cause_dag": displayed_root_cause_dag,
        "root_cause_matrix": displayed_root_cause_matrix,
        "root_cause_task_queue": (
            promotion_root_cause["root_cause_task_queue"]
            if promotion_root_cause is not None
            else root_cause_dag.get("task_queue", {})
        ),
        "dashboard_source_root_cause_summary": root_cause_summary(root_cause_dag),
        "dashboard_source_root_cause_dag": root_cause_dag,
        "dashboard_source_root_cause_matrix": root_cause_dag["root_cause_matrix"],
        "blockers": dashboard_blockers,
    }
    return apply_btc_artifact_schema(
        payload,
        decision="btc_gate_dashboard_complete" if not dashboard_blockers else "btc_gate_dashboard_blocked",
        generated_at_utc=ensure_utc(generated_at_utc),
        as_of_utc=ensure_utc(generated_at_utc),
        blockers=dashboard_blockers,
        warnings=[],
        input_hashes={
            "current_status": stable_payload_hash(current_status),
            "registry": stable_payload_hash(registry),
            "paper_readiness": stable_payload_hash(paper_readiness),
            "promotion_gate_control": stable_payload_hash(_mapping(promotion_gate_control)),
            "sources": stable_payload_hash(source_summary),
            "artifacts": stable_payload_hash(artifact_summary),
            "root_cause_dag": stable_payload_hash(displayed_root_cause_dag),
            "dashboard_source_root_cause_dag": stable_payload_hash(root_cause_dag),
        },
    )


def load_json_or_none(path: Path) -> Mapping[str, Any] | None:
    import json

    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else None


def _root_cause_blockers(blockers: list[str], artifact_summary: Mapping[str, Any]) -> list[str]:
    root_blockers = list(blockers)
    for name, summary in artifact_summary.items():
        if not isinstance(summary, Mapping):
            continue
        for blocker in summary.get("blockers", []):
            if blocker:
                root_blockers.append(f"artifact:{name}:{blocker}")
    return _dedupe(root_blockers)


def _promotion_root_cause_overlay(promotion_gate_control: Mapping[str, Any] | None) -> dict[str, Any] | None:
    promotion = _mapping(promotion_gate_control)
    if not promotion:
        return None
    dag = _mapping(promotion.get("root_cause_dag"))
    if not dag:
        return None
    matrix = _list_of_mappings(promotion.get("root_cause_matrix"))
    if not matrix:
        matrix = _list_of_mappings(dag.get("root_cause_matrix"))
    summary = _mapping(promotion.get("root_cause_summary")) or root_cause_summary(dag)
    task_queue = _mapping(promotion.get("root_cause_task_queue")) or _mapping(dag.get("task_queue"))
    return {
        "root_cause_dag": dict(dag),
        "root_cause_matrix": matrix,
        "root_cause_summary": dict(summary),
        "root_cause_task_queue": dict(task_queue),
    }


def _status_text(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status") or payload.get("current_status") or payload.get("btc_current_status") or "")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _source_summary(
    payload: Mapping[str, Any],
    *,
    status: str | None = None,
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    payload_blockers = blockers if blockers is not None else [str(item) for item in payload.get("blockers", []) if item]
    return {
        "status": _summary_status(payload, status=status, blockers=payload_blockers),
        "decision": str(payload.get("decision", "")),
        "generated_at": _first_text(payload, "generated_at", "generated_at_utc", "as_of_utc"),
        "as_of_utc": _first_text(payload, "as_of_utc", "generated_at_utc", "generated_at"),
        "blockers": payload_blockers,
        "artifact_hash": str(payload.get("artifact_hash") or stable_payload_hash(payload)),
        "next_action": _next_action(payload),
    }


def _summary_status(payload: Mapping[str, Any], *, status: str | None, blockers: list[str]) -> str:
    if status is not None:
        return status
    for key in ("status", "current_status", "decision", "ledger_status"):
        value = payload.get(key)
        if value:
            return str(value)
    if blockers:
        return "blocked"
    if payload.get("funding_adjusted_net_pnl_reconciled") is True and payload.get("funding_payment_in_ledger") is True:
        return "funding_ledger_reconciled"
    return "present" if payload else "missing"


def _missing_artifact_summary() -> dict[str, Any]:
    return {
        "status": "missing",
        "decision": "",
        "generated_at": "",
        "as_of_utc": "",
        "blockers": ["artifact_missing"],
        "artifact_hash": "",
        "next_action": "restore_or_generate_missing_artifact",
    }


def _first_text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _next_action(payload: Mapping[str, Any]) -> str:
    for key in ("next_required_action", "next_action", "allowed_next_action"):
        value = payload.get(key)
        if value:
            return str(value)
    readiness = _mapping(payload.get("readiness_summary"))
    if readiness.get("next_required_action"):
        return str(readiness["next_required_action"])
    return ""


def _unsafe_flags(payload: Mapping[str, Any]) -> list[str]:
    unsafe_keys = {
        "live_order_allowed",
        "micro_live_allowed",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "real_orders_created",
        "paper_or_live_unlock_allowed",
        "live_unlock_allowed",
    }
    flags: list[str] = []
    for path, value in _walk(payload):
        if value is True and path.split(".")[-1] in unsafe_keys:
            flags.append(f"{path}=true")
    return flags


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def _nested_int(payload: Mapping[str, Any], path: str) -> int:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return 0
        value = value.get(part)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _perpetual_state(payload: Mapping[str, Any]) -> dict[str, Any]:
    gate = _mapping(payload.get("gate"))
    return {
        "status": str(payload.get("status") or ""),
        "policy_decision": str(payload.get("policy_decision") or payload.get("decision") or ""),
        "current_route": str(payload.get("current_route") or ""),
        "current_strategy_uses_perpetual": bool(payload.get("current_strategy_uses_perpetual", False)),
        "perpetual_allowed": bool(gate.get("perpetual_allowed", False)),
        "live_unlock_allowed": bool(gate.get("live_unlock_allowed", False)),
        "blockers": [str(item) for item in payload.get("blockers", []) if item],
    }


def _security_attestation_state(
    *,
    api_key_audit: Mapping[str, Any],
    order_surface_audit: Mapping[str, Any],
    account_attestation: Mapping[str, Any],
) -> dict[str, Any]:
    account_gate = _mapping(account_attestation.get("gate"))
    order_surface_findings = order_surface_audit.get("findings", [])
    order_surface_finding_count = len(order_surface_findings) if isinstance(order_surface_findings, list) else 0
    order_surface_blockers = [str(item) for item in order_surface_audit.get("blockers", []) if item]
    order_surface_clean = (
        str(order_surface_audit.get("decision") or "") == "non_oms_order_surface_clean"
        and not order_surface_blockers
        and order_surface_finding_count == 0
    )
    return {
        "api_key_audit_status": str(api_key_audit.get("status") or ""),
        "api_key_audit_decision": str(api_key_audit.get("decision") or ""),
        "api_key_audit_blocker_count": len(api_key_audit.get("blockers", [])),
        "order_surface_audit_status": str(order_surface_audit.get("status") or ""),
        "order_surface_audit_decision": str(order_surface_audit.get("decision") or ""),
        "order_surface_audit_clean": order_surface_clean,
        "order_surface_finding_count": order_surface_finding_count,
        "order_surface_non_blocking_match_count": order_surface_audit.get("non_blocking_match_count", 0),
        "account_attestation_status": str(account_attestation.get("status") or ""),
        "account_attestation_current": account_attestation.get("attestation_current") is True,
        "account_attestation_manual_only": account_gate.get("manual_attestation_only") is True,
        "credential_permissions_verified": account_attestation.get("credential_permissions_verified") is True,
        "credential_separation_verified": account_attestation.get("credential_separation_verified") is True,
        "manual_approval_recorded": account_attestation.get("manual_approval_recorded") is True,
        "paper_queue_write_allowed": False,
        "paper_order_intake_allowed": False,
        "live_unlock_allowed": False,
        "blockers": [
            *[f"api_key_audit:{item}" for item in api_key_audit.get("blockers", []) if item],
            *[f"order_surface_audit:{item}" for item in order_surface_blockers],
            *[f"account_attestation:{item}" for item in account_attestation.get("blockers", []) if item],
        ],
    }


def _micro_live_preflight_blocked(payload: Mapping[str, Any]) -> bool:
    status = str(payload.get("status") or "").lower()
    decision = str(payload.get("decision") or "").lower()
    return bool(
        payload.get("blockers")
        or status.startswith("blocked")
        or status.startswith("fail_closed")
        or "blocked" in decision
        or "fail_closed" in decision
    )


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path.cwd(),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    return result.stdout.strip()
