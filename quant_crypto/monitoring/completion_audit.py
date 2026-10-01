from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from quant_shared.core.time import ensure_utc

from .artifact_schema import apply_btc_artifact_schema, stable_payload_hash
from .gate_dashboard import load_json_or_none


BTC_COMPLETION_AUDIT_VERSION = "btc_completion_audit_v1"


@dataclass(frozen=True)
class BTCCompletionRequirement:
    requirement_id: str
    priority: str
    title: str
    evidence_artifacts: tuple[str, ...]
    required_statuses: tuple[str, ...] = ("complete",)


BTC_COMPLETION_REQUIREMENTS: tuple[BTCCompletionRequirement, ...] = (
    BTCCompletionRequirement(
        requirement_id="P0-1",
        priority="P0",
        title="BTC exchange runtime contract artifact covers server time, rate budget, WS gapfill, cancel-only and fail-closed state",
        evidence_artifacts=("exchange_runtime_contract",),
    ),
    BTCCompletionRequirement(
        requirement_id="P0-2",
        priority="P0",
        title="mark/index/liquidation risk engine is enforced inside Forecast to Target/Risk",
        evidence_artifacts=("liquidation_risk_contract",),
    ),
    BTCCompletionRequirement(
        requirement_id="P0-3",
        priority="P0",
        title="paper validation start/runtime/evaluation artifacts bind run_id, ledger, OMS lifecycle, audit DAG and replay",
        evidence_artifacts=("paper_validation_start", "paper_validation_runtime", "paper_validation_evaluation", "paper_validation_audit_dag", "paper_validation_replay"),
        required_statuses=("complete", "replay_pass"),
    ),
    BTCCompletionRequirement(
        requirement_id="P0-4",
        priority="P0",
        title="API key permission audit proves data/paper/live key separation, withdraw disabled, IP allowlist and mode match without secrets",
        evidence_artifacts=("api_key_permission_audit",),
    ),
    BTCCompletionRequirement(
        requirement_id="P0-5",
        priority="P0",
        title="trend v0 emits Signal to Forecast to Target to Cost Gate to OrderIntent to Paper OMS without broker/order endpoints",
        evidence_artifacts=("trend_boundary",),
    ),
    BTCCompletionRequirement(
        requirement_id="P1-1",
        priority="P1",
        title="BTC source role report covers PIT, finalization and gapfill state",
        evidence_artifacts=("source_role_contract",),
    ),
    BTCCompletionRequirement(
        requirement_id="P1-2",
        priority="P1",
        title="BTC paper OMS session reconciliation binds lifecycle, fills, ledger hash and execution quality",
        evidence_artifacts=("paper_oms_session_contract",),
    ),
    BTCCompletionRequirement(
        requirement_id="P1-3",
        priority="P1",
        title="incident and replay drill covers data outage, funding gap, order reject and ledger mismatch",
        evidence_artifacts=("incident_replay_drill_contract",),
    ),
    BTCCompletionRequirement(
        requirement_id="P2-1",
        priority="P2",
        title="BTC gate dashboard aggregates research, paper, live and blocker state",
        evidence_artifacts=("gate_dashboard",),
        required_statuses=("complete", "blocked"),
    ),
)


def build_btc_completion_audit(
    *,
    generated_at_utc: datetime,
    artifacts: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, Any]:
    item_results = [_evaluate_requirement(requirement, artifacts) for requirement in BTC_COMPLETION_REQUIREMENTS]
    blockers: list[str] = []
    for item in item_results:
        if item["status"] != "complete":
            blockers.append(f"btc_completion_requirement_not_complete:{item['requirement_id']}")
            blockers.extend(item["blockers"])
    payload = {
        "completion_audit_version": BTC_COMPLETION_AUDIT_VERSION,
        "status": "complete" if not blockers else "blocked",
        "scope": "btc_attachment_p0_p1_p2_requirements",
        "allows_live_orders": False,
        "completion_claim_allowed": not blockers,
        "requirements": item_results,
        "summary": {
            "total": len(item_results),
            "complete": sum(1 for item in item_results if item["status"] == "complete"),
            "blocked": sum(1 for item in item_results if item["status"] == "blocked"),
            "missing": sum(1 for item in item_results if item["status"] == "missing"),
        },
        "blockers": _dedupe(blockers),
    }
    return apply_btc_artifact_schema(
        payload,
        decision="btc_attachment_requirements_complete" if not blockers else "btc_attachment_requirements_blocked",
        generated_at_utc=ensure_utc(generated_at_utc),
        as_of_utc=ensure_utc(generated_at_utc),
        blockers=_dedupe(blockers),
        warnings=[],
        input_hashes={"artifacts": stable_payload_hash(_summarize_artifacts(artifacts))},
    )


def load_completion_artifacts(paths: Mapping[str, Path]) -> dict[str, Mapping[str, Any] | None]:
    return {name: load_json_or_none(path) for name, path in paths.items()}


def _evaluate_requirement(
    requirement: BTCCompletionRequirement,
    artifacts: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, Any]:
    blockers: list[str] = []
    evidence: dict[str, Any] = {}
    for artifact_name in requirement.evidence_artifacts:
        artifact = artifacts.get(artifact_name)
        if not artifact:
            blockers.append(f"btc_completion_evidence_missing:{requirement.requirement_id}:{artifact_name}")
            evidence[artifact_name] = {"status": "missing", "artifact_hash": ""}
            continue
        artifact_status = str(artifact.get("status", ""))
        artifact_blockers = [str(item) for item in artifact.get("blockers", []) if item]
        evidence[artifact_name] = {
            "status": artifact_status,
            "decision": str(artifact.get("decision", "")),
            "artifact_hash": str(artifact.get("artifact_hash", "")),
            "blockers": artifact_blockers,
        }
        if artifact_status not in requirement.required_statuses:
            blockers.append(f"btc_completion_evidence_status_invalid:{requirement.requirement_id}:{artifact_name}:{artifact_status}")
            blockers.extend(f"{artifact_name}:{blocker}" for blocker in artifact_blockers)
    status = "complete" if not blockers else "blocked"
    if any(evidence_item["status"] == "missing" for evidence_item in evidence.values()):
        status = "missing"
    return {
        "requirement_id": requirement.requirement_id,
        "priority": requirement.priority,
        "title": requirement.title,
        "status": status,
        "evidence": evidence,
        "blockers": _dedupe(blockers),
    }


def _summarize_artifacts(artifacts: Mapping[str, Mapping[str, Any] | None]) -> dict[str, Any]:
    return {
        name: None if artifact is None else {
            "status": artifact.get("status"),
            "decision": artifact.get("decision"),
            "artifact_hash": artifact.get("artifact_hash"),
            "blockers": artifact.get("blockers"),
        }
        for name, artifact in artifacts.items()
    }


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
