"""Manual decision-record rules for US equity paper governance.

The local decision record is a human-review artifact. A valid record can prove
that an operator reviewed evidence and selected a next decision, but it must
never unlock paper simulation or live trading by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from quant_us.live.broker_credentials_review import normalize_gitignore_patterns, relpath


RECORD_SCHEMA_VERSION = "us_equity_manual_decision_record_v1"
DEFAULT_RECORD = Path("configs/reviews/us_equity_manual_decision_record.local.json")
DEFAULT_TEMPLATE = Path("configs/reviews/us_equity_manual_decision_record.template.json")
ALLOWED_DECISIONS = {
    "continue_observation",
    "freeze_strategy",
    "retire_strategy",
    "new_strategy_id_required",
    "paper_simulation_review_candidate",
}
REQUIRED_TEXT_FIELDS = ("strategy_id", "review_id", "reviewed_at", "reviewer", "decision", "reason")
FORBIDDEN_TRUE_DEFAULTS = {
    "paper_or_live_unlock_allowed",
    "paper_simulation_allowed",
    "live_order_allowed",
}


@dataclass(frozen=True)
class ManualDecisionRecordEvaluation:
    status: str
    decision: str
    blockers: list[str]
    record_readiness: dict[str, Any]
    record_summary: dict[str, Any]
    evidence_path_details: list[dict[str, Any]]
    local_record_write_policy: dict[str, Any]
    evidence_classification: dict[str, Any]
    operator_decision_guidance: dict[str, Any]
    paper_start_dependency: dict[str, Any]


@dataclass(frozen=True)
class ManualDecisionLocalInitEvaluation:
    status: str
    blockers: list[str]
    actions: list[str]
    guardrails: dict[str, Any]
    operator_next_actions: list[str]


def evaluate_manual_decision_local_init(
    *,
    template: Mapping[str, Any],
    template_exists: bool,
    local_record_exists: bool,
    force: bool,
) -> ManualDecisionLocalInitEvaluation:
    blockers: list[str] = []
    if not template_exists:
        blockers.append("manual_decision_template_missing")
    if template.get("schema_version") != RECORD_SCHEMA_VERSION:
        blockers.append("manual_decision_template_schema_invalid")
    for field in sorted(FORBIDDEN_TRUE_DEFAULTS):
        if template.get(field) is True:
            blockers.append(f"manual_decision_template_forbidden_true_default:{field}")
    if local_record_exists and not force:
        blockers.append("manual_decision_local_record_already_exists")
    blockers = dedupe(blockers)
    return ManualDecisionLocalInitEvaluation(
        status="manual_decision_local_initialized" if not blockers else "manual_decision_local_init_blocked",
        blockers=blockers,
        actions=["manual_decision_template_copied"] if not blockers else [],
        guardrails=manual_decision_local_init_guardrails(),
        operator_next_actions=[
            "Open configs/reviews/us_equity_manual_decision_record.local.json locally.",
            "Fill review_id, reviewed_at, reviewer, decision, reason, and evidence_paths after the required evidence is ready.",
            "Keep paper_or_live_unlock_allowed=false, paper_simulation_allowed=false, and live_order_allowed=false.",
            "Run: python scripts/build_us_equity_manual_decision_record_report.py",
        ],
    )


def evaluate_manual_decision_record(
    *,
    record: Mapping[str, Any],
    record_path: Path,
    record_exists: bool,
    template: Mapping[str, Any],
    template_path: Path,
    template_exists: bool,
    gitignore_patterns: list[str],
    repo_root: Path,
) -> ManualDecisionRecordEvaluation:
    del template_path
    evidence_paths = list_of_str(record.get("evidence_paths"))
    evidence_details = evidence_path_details(evidence_paths, repo_root)
    missing_evidence = [item["path"] for item in evidence_details if item["exists"] is not True]
    non_traceable_evidence = [item["path"] for item in evidence_details if item["traceable_report_artifact"] is not True]
    outside_repo_evidence = [item["path"] for item in evidence_details if item["within_repo"] is not True]
    missing_required_text = [field for field in REQUIRED_TEXT_FIELDS if not str(record.get(field, "")).strip()]
    blockers = manual_decision_blockers(
        record=record,
        record_exists=record_exists,
        template_exists=template_exists,
        template=template,
        missing_required_text=missing_required_text,
        evidence_paths=evidence_paths,
        missing_evidence=missing_evidence,
        non_traceable_evidence=non_traceable_evidence,
        outside_repo_evidence=outside_repo_evidence,
        local_policy=local_record_write_policy(record_path, repo_root, gitignore_patterns),
    )
    status = "manual_decision_record_valid" if not blockers else "manual_decision_record_missing_or_invalid"
    decision = "manual_decision_record_validated_no_unlock" if status == "manual_decision_record_valid" else "manual_decision_record_required"
    return ManualDecisionRecordEvaluation(
        status=status,
        decision=decision,
        blockers=dedupe(blockers),
        record_readiness=record_readiness(
            record=record,
            record_exists=record_exists,
            template_exists=template_exists,
            missing_required_text=missing_required_text,
            evidence_paths=evidence_paths,
            missing_evidence=missing_evidence,
            status=status,
        ),
        record_summary=record_summary(record, evidence_paths, missing_evidence),
        evidence_path_details=evidence_details,
        local_record_write_policy=local_record_write_policy(record_path, repo_root, gitignore_patterns),
        evidence_classification=evidence_classification(status),
        operator_decision_guidance=operator_decision_guidance(
            record=record,
            record_exists=record_exists,
            blockers=blockers,
            missing_required_text=missing_required_text,
            evidence_paths=evidence_paths,
            evidence_details=evidence_details,
            local_policy=local_record_write_policy(record_path, repo_root, gitignore_patterns),
        ),
        paper_start_dependency=paper_start_dependency(status=status, record=record),
    )


def manual_decision_blockers(
    *,
    record: Mapping[str, Any],
    record_exists: bool,
    template_exists: bool,
    template: Mapping[str, Any],
    missing_required_text: list[str],
    evidence_paths: list[str],
    missing_evidence: list[str],
    non_traceable_evidence: list[str],
    outside_repo_evidence: list[str],
    local_policy: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if local_policy.get("local_record_gitignore_present") is not True:
        blockers.append("us_equity_manual_decision_local_record_not_gitignored")
    if not record_exists:
        blockers.append("us_equity_manual_decision_record_missing")
    if not template_exists or not template:
        blockers.append("us_equity_manual_decision_template_missing")
    if record and record.get("schema_version") != RECORD_SCHEMA_VERSION:
        blockers.append("us_equity_manual_decision_record_schema_version_invalid")
    for field in missing_required_text:
        blockers.append(f"us_equity_manual_decision_record_{field}_missing")
    decision = str(record.get("decision", ""))
    if decision and decision not in ALLOWED_DECISIONS:
        blockers.append("us_equity_manual_decision_record_decision_not_allowed")
    if not evidence_paths:
        blockers.append("us_equity_manual_decision_record_evidence_paths_missing")
    if missing_evidence:
        blockers.append("us_equity_manual_decision_record_evidence_path_missing")
    if outside_repo_evidence:
        blockers.append("us_equity_manual_decision_record_evidence_path_outside_repo")
    if non_traceable_evidence:
        blockers.append("us_equity_manual_decision_record_evidence_path_not_us_equity_report_artifact")
    for key in ("paper_or_live_unlock_allowed", "paper_simulation_allowed", "live_order_allowed"):
        if record.get(key) is True:
            blockers.append(f"us_equity_manual_decision_record_forbidden_{key}")
    return blockers


def record_readiness(
    *,
    record: Mapping[str, Any],
    record_exists: bool,
    template_exists: bool,
    missing_required_text: list[str],
    evidence_paths: list[str],
    missing_evidence: list[str],
    status: str,
) -> dict[str, Any]:
    decision = str(record.get("decision", ""))
    return {
        "record_exists": record_exists,
        "template_exists": template_exists,
        "schema_version_valid": record.get("schema_version") == RECORD_SCHEMA_VERSION,
        "missing_required_fields": missing_required_text,
        "decision_allowed": bool(decision and decision in ALLOWED_DECISIONS),
        "paper_candidate_decision_recorded": decision == "paper_simulation_review_candidate",
        "evidence_paths_recorded": bool(evidence_paths),
        "evidence_paths_missing_count": len(missing_evidence),
        "forbidden_unlock_flags_present": any(
            record.get(key) is True
            for key in ("paper_or_live_unlock_allowed", "paper_simulation_allowed", "live_order_allowed")
        ),
        "ready_for_manual_review_packet": status == "manual_decision_record_valid"
        and decision == "paper_simulation_review_candidate",
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }


def evidence_path_details(evidence_paths: list[str], root: Path) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    root_resolved = root.resolve()
    for path_text in evidence_paths:
        raw_path = Path(path_text)
        abs_path = raw_path if raw_path.is_absolute() else root_resolved / raw_path
        resolved = _safe_resolve(abs_path)
        within_repo = _is_relative_to(resolved, root_resolved)
        rel = relpath(resolved, root_resolved).replace("\\", "/") if within_repo else path_text.replace("\\", "/")
        exists = resolved.exists()
        is_json = resolved.suffix.lower() == ".json"
        is_us_equity_artifact = rel.startswith("artifacts/us_equity") and is_json
        reported_status = _json_status(resolved) if exists and is_us_equity_artifact else ""
        traceable = within_repo and exists and is_us_equity_artifact
        details.append(
            {
                "path": rel,
                "exists": exists,
                "within_repo": within_repo,
                "is_json_report": is_json,
                "is_us_equity_artifact": is_us_equity_artifact,
                "traceable_report_artifact": traceable,
                "reported_status": reported_status,
            }
        )
    return details


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _json_status(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    return str(payload.get("status", "")) if isinstance(payload, Mapping) else ""


def record_summary(record: Mapping[str, Any], evidence_paths: list[str], missing_evidence: list[str]) -> dict[str, Any]:
    return {
        "strategy_id": str(record.get("strategy_id", "")),
        "review_id": str(record.get("review_id", "")),
        "reviewed_at": str(record.get("reviewed_at", "")),
        "reviewer_recorded": bool(str(record.get("reviewer", "")).strip()),
        "decision": str(record.get("decision", "")),
        "reason_recorded": bool(str(record.get("reason", "")).strip()),
        "evidence_path_count": len(evidence_paths),
        "missing_evidence_paths": missing_evidence,
        "follow_up_ticket_ids": list_of_str(record.get("follow_up_ticket_ids")),
        "parameter_or_strategy_id_change_required": record.get("parameter_or_strategy_id_change_required") is True,
    }


def local_record_write_policy(record_path: Path, root: Path, gitignore_patterns: list[str]) -> dict[str, Any]:
    local_path = relpath(record_path, root).replace("\\", "/")
    return {
        "local_record_path": local_path,
        "should_not_commit_local_record": True,
        "local_record_gitignore_present": local_path in gitignore_patterns or "configs/reviews/*.local.json" in gitignore_patterns,
        "allowed_template_path": "configs/reviews/us_equity_manual_decision_record.template.json",
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "secrets_allowed": False,
    }


def evidence_classification(status: str) -> dict[str, Any]:
    return {
        "classification": "manual_decision_metadata_only",
        "status": status,
        "manual_record_can_unlock_paper_by_itself": False,
        "manual_record_can_unlock_live_by_itself": False,
        "required_next_gate_for_paper": "manual_review_packet_then_paper_simulation_readiness",
        "contains_secret_values": False,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
    }


def paper_start_dependency(*, status: str, record: Mapping[str, Any]) -> dict[str, Any]:
    decision = str(record.get("decision", ""))
    paper_candidate = decision == "paper_simulation_review_candidate"
    valid = status == "manual_decision_record_valid"
    return {
        "manual_record_valid": valid,
        "paper_candidate_decision_recorded": paper_candidate,
        "manual_record_can_start_paper_by_itself": False,
        "manual_record_can_unlock_live_by_itself": False,
        "paper_start_dependency_status": "ready_for_next_gate" if valid and paper_candidate else "blocked",
        "required_next_gate_for_paper": "manual_review_packet_then_paper_simulation_readiness",
        "required_next_reports": [
            "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
            "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
            "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json",
        ],
        "required_runner_condition": "run_us_equity_paper_simulation_roll(..., manual_start_approved=True)",
        "required_evidence_traceability": "all evidence_paths must be existing JSON reports under artifacts/us_equity*",
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }


def operator_decision_guidance(
    *,
    record: Mapping[str, Any],
    record_exists: bool,
    blockers: list[str],
    missing_required_text: list[str],
    evidence_paths: list[str],
    evidence_details: list[Mapping[str, Any]],
    local_policy: Mapping[str, Any],
) -> dict[str, Any]:
    missing_evidence = [str(item.get("path", "")) for item in evidence_details if item.get("exists") is not True]
    non_traceable_evidence = [
        str(item.get("path", "")) for item in evidence_details if item.get("traceable_report_artifact") is not True
    ]
    outside_repo_evidence = [str(item.get("path", "")) for item in evidence_details if item.get("within_repo") is not True]
    forbidden_unlock_flags = [
        key for key in ("paper_or_live_unlock_allowed", "paper_simulation_allowed", "live_order_allowed") if record.get(key) is True
    ]
    decision = str(record.get("decision", ""))
    actions: list[str] = []
    if not record_exists:
        actions.append("copy configs/reviews/us_equity_manual_decision_record.template.json to configs/reviews/us_equity_manual_decision_record.local.json")
    if missing_required_text:
        actions.append(f"fill missing required fields in the local decision record: {', '.join(missing_required_text)}")
    if decision and decision not in ALLOWED_DECISIONS:
        actions.append("replace decision with one allowed value from allowed_decisions")
    if not evidence_paths:
        actions.append("add traceable artifacts/us_equity*.json evidence paths after upstream evidence is ready")
    if missing_evidence:
        actions.append("refresh or create every referenced evidence artifact before recording approval")
    if non_traceable_evidence:
        actions.append("replace evidence_paths with existing JSON reports under artifacts/us_equity*")
    if outside_repo_evidence:
        actions.append("remove evidence paths outside the repository")
    if forbidden_unlock_flags:
        actions.append("keep paper_or_live_unlock_allowed=false, paper_simulation_allowed=false, and live_order_allowed=false")
    if local_policy.get("local_record_gitignore_present") is not True:
        actions.append("add configs/reviews/us_equity_manual_decision_record.local.json to .gitignore before recording the review")
    if not blockers:
        actions.append("rerun manual review packet and paper simulation readiness; this record still cannot unlock paper or live by itself")
    return {
        "status": "record_complete" if not blockers else "manual_decision_required",
        "local_record_path": str(local_policy.get("local_record_path") or "configs/reviews/us_equity_manual_decision_record.local.json"),
        "template_path": str(local_policy.get("allowed_template_path") or "configs/reviews/us_equity_manual_decision_record.template.json"),
        "missing_required_fields": missing_required_text,
        "allowed_decisions": sorted(ALLOWED_DECISIONS),
        "required_evidence_path_rules": {
            "must_exist": True,
            "must_be_within_repo": True,
            "required_prefix": "artifacts/us_equity",
            "required_suffix": ".json",
        },
        "missing_evidence_paths": missing_evidence,
        "non_traceable_evidence_paths": non_traceable_evidence,
        "outside_repo_evidence_paths": outside_repo_evidence,
        "forbidden_unlock_flags": forbidden_unlock_flags,
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
        "operator_next_actions": actions or ["rerun manual decision record report and keep paper/live locked"],
    }


def manual_decision_local_init_guardrails() -> dict[str, bool]:
    return {
        "local_template_init_only": True,
        "local_record_should_not_be_committed": True,
        "manual_approval_recorded_by_this_report": False,
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "broker_calls_used": False,
        "real_order_submitted": False,
    }


def gitignore_patterns(root: Path) -> list[str]:
    path = root / ".gitignore"
    if not path.exists():
        return []
    return normalize_gitignore_patterns(path.read_text(encoding="utf-8"))


def list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
