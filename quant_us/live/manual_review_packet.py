"""Manual-review packet rules for US equity paper governance.

The packet aggregates already-built evidence for a human reviewer. It can mark
the evidence packet ready for human review, but it must never approve paper
simulation or live trading by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


REVIEW_MILESTONES = [30, 60, 90]
STRATEGY_ID = "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"


@dataclass(frozen=True)
class ManualReviewPacketEvaluation:
    status: str
    decision: str
    review_items: dict[str, Any]
    remediation_tickets: dict[str, Any]
    forward_review_progress: dict[str, Any]
    review_milestones: list[dict[str, Any]]
    evidence_checklist: list[dict[str, Any]]
    signoff_requirements: list[dict[str, Any]]
    paper_or_live_unlock_decision: dict[str, Any]
    blockers: list[str]
    unsafe_flags: list[str]
    guardrails: dict[str, Any]


def evaluate_manual_review_packet(reports: Mapping[str, Mapping[str, Any]]) -> ManualReviewPacketEvaluation:
    blockers: list[str] = []
    missing = [name for name, payload in reports.items() if not payload]
    blockers.extend([f"us_equity_manual_review_missing_{name}" for name in missing])

    strategy_gate = mapping(reports.get("strategy_gate"))
    strategy_evidence_audit = mapping(reports.get("strategy_evidence_audit"))
    forward_evaluation = mapping(reports.get("forward_evaluation"))
    data_freshness = mapping(reports.get("data_freshness"))
    small_account = mapping(reports.get("small_account_preflight"))
    live_readiness = mapping(reports.get("live_readiness"))
    manual_decision_record = mapping(reports.get("manual_decision_record"))
    production_pit_intake = mapping(reports.get("production_pit_intake_status"))
    pit_bundle_acceptance = mapping(reports.get("pit_bundle_acceptance"))
    blocker_taxonomy = mapping(reports.get("blocker_taxonomy"))

    if str(strategy_gate.get("status", "")) != "validation_passed_for_forward_observation":
        blockers.append("us_equity_manual_review_strategy_validation_not_passed")
    if str(strategy_evidence_audit.get("status", "")) != "validation_evidence_audit_ready_for_forward_observation":
        blockers.append("us_equity_manual_review_strategy_validation_evidence_audit_not_ready")
    if nested(strategy_evidence_audit, "summary.incomplete_count", 0) not in {0, "0"}:
        blockers.append("us_equity_manual_review_strategy_validation_evidence_incomplete")
    if nested(strategy_evidence_audit, "summary.blocked_count", 0) not in {0, "0"}:
        blockers.append("us_equity_manual_review_strategy_validation_evidence_blocked")
    if str(forward_evaluation.get("status", "")) != "forward_complete_for_manual_review":
        blockers.append("us_equity_manual_review_forward_observation_not_complete")
    if int(nested(forward_evaluation, "daily_data_gate.blocked_count", 0) or 0) > 0:
        blockers.append("us_equity_manual_review_forward_data_gate_had_blocked_runs")
    if nested(forward_evaluation, "observation_continuity.passed", False) is not True:
        blockers.append("us_equity_manual_review_forward_observation_continuity_not_passed")
    if str(data_freshness.get("status", "")) != "pass":
        blockers.append("us_equity_manual_review_data_freshness_not_pass")
    if str(small_account.get("status", "")) != "pass_observation_only":
        blockers.append("us_equity_manual_review_small_account_preflight_not_pass")
    if str(production_pit_intake.get("status", "")) != "production_pit_data_intake_ready":
        blockers.append("us_equity_manual_review_production_pit_intake_not_ready")
    if str(pit_bundle_acceptance.get("status", "")) != "acceptance_ready_for_manual_config_apply":
        blockers.append("us_equity_manual_review_pit_bundle_acceptance_not_ready")

    remediation_tickets = remediation_ticket_summary(blocker_taxonomy)
    if remediation_tickets["ticket_count"] > 0:
        blockers.append("us_equity_manual_review_remediation_tickets_open")
    if str(live_readiness.get("status", "")) != "live_readiness_blocked":
        blockers.append("us_equity_manual_review_live_readiness_not_fail_closed")

    manual_decision_valid = str(manual_decision_record.get("status", "")) == "manual_decision_record_valid"
    manual_decision = str(nested(manual_decision_record, "record_summary.decision", ""))
    if not manual_decision_valid:
        blockers.append("us_equity_manual_review_decision_record_not_valid")
    if manual_decision_valid and manual_decision != "paper_simulation_review_candidate":
        blockers.append("us_equity_manual_review_decision_record_not_paper_candidate")

    unsafe = unsafe_flags(reports)
    blockers.extend([f"us_equity_manual_review_unsafe_flag:{item}" for item in unsafe])

    observation_days = int(nested(forward_evaluation, "metrics.observation_days", 0) or 0)
    forward_progress = forward_review_progress(forward_evaluation, observation_days)
    milestones = review_milestones(observation_days)
    checklist = evidence_checklist(reports, milestones)
    signoffs = signoff_requirements()
    ready = not blockers and all(item["passed"] for item in checklist)
    return ManualReviewPacketEvaluation(
        status="manual_review_ready" if ready else "manual_review_pending",
        decision="human_review_required",
        review_items=review_items(reports, remediation_tickets, observation_days, manual_decision),
        remediation_tickets=remediation_tickets,
        forward_review_progress=forward_progress,
        review_milestones=milestones,
        evidence_checklist=checklist,
        signoff_requirements=signoffs,
        paper_or_live_unlock_decision={
            "manual_review_can_unlock_paper_by_itself": False,
            "manual_review_can_unlock_live_by_itself": False,
            "required_next_gate_for_paper": "paper_simulation_readiness",
            "required_next_gate_for_live": "live_readiness_risk_constitution_and_explicit_human_approval",
        },
        blockers=dedupe(blockers),
        unsafe_flags=unsafe,
        guardrails={
            "manual_review_packet_only": True,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "manual_approval_recorded": ready
            and manual_decision_valid
            and manual_decision == "paper_simulation_review_candidate",
        },
    )


def review_items(
    reports: Mapping[str, Mapping[str, Any]],
    remediation_tickets: Mapping[str, Any],
    observation_days: int,
    manual_decision: str,
) -> dict[str, Any]:
    strategy_gate = mapping(reports.get("strategy_gate"))
    strategy_evidence_audit = mapping(reports.get("strategy_evidence_audit"))
    forward = mapping(reports.get("forward_evaluation"))
    data_freshness = mapping(reports.get("data_freshness"))
    small_account = mapping(reports.get("small_account_preflight"))
    live_readiness = mapping(reports.get("live_readiness"))
    manual_decision_record = mapping(reports.get("manual_decision_record"))
    production_pit = mapping(reports.get("production_pit_intake_status"))
    pit_acceptance = mapping(reports.get("pit_bundle_acceptance"))
    return {
        "strategy_evidence": {
            "status": strategy_gate.get("status"),
            "evidence_audit_status": strategy_evidence_audit.get("status"),
            "evidence_requirement_count": nested(strategy_evidence_audit, "summary.requirement_count", 0),
            "evidence_complete_count": nested(strategy_evidence_audit, "summary.complete_count", 0),
            "evidence_blocked_count": nested(strategy_evidence_audit, "summary.blocked_count", 0),
            "evidence_incomplete_count": nested(strategy_evidence_audit, "summary.incomplete_count", 0),
            "required_action": "review data-quality blockers, benchmark coverage, attribution, walk-forward, parameter stability",
        },
        "forward_observation": {
            "status": forward.get("status"),
            "observation_days": observation_days,
            "review_milestones": review_milestones(observation_days),
            "data_gate_status": nested(forward, "checks.daily_data_gate.passed", False),
            "data_gate_blocked_count": nested(forward, "daily_data_gate.blocked_count", 0),
            "continuity_passed": nested(forward, "observation_continuity.passed", False),
            "continuity": nested(forward, "observation_continuity", {}),
            "required_action": "review ledger continuity, repeated dates, target changes, fills, fees, and rule consistency",
        },
        "data_freshness": {
            "status": data_freshness.get("status"),
            "macro_status": nested(data_freshness, "macro_freshness.status", ""),
            "required_action": "confirm ETF and FRED freshness before any downstream runner",
        },
        "account_constraints": {
            "status": small_account.get("status"),
            "required_action": "review 1x, low leverage, and 1.5x research-only order models",
        },
        "production_pit_data": {
            "intake_status": production_pit.get("status"),
            "current_blocking_stage": production_pit.get("current_blocking_stage"),
            "acceptance_status": pit_acceptance.get("status"),
            "acceptance_current_blocking_step": pit_acceptance.get("current_blocking_step"),
            "required_action": "confirm production PIT data intake and acceptance before human review can proceed",
        },
        "remediation_tickets": {
            "status": reports.get("blocker_taxonomy", {}).get("status", "missing"),
            "ticket_count": remediation_tickets["ticket_count"],
            "by_dependency_type": remediation_tickets["by_dependency_type"],
            "by_status": remediation_tickets["by_status"],
            "tickets": remediation_tickets["tickets"],
            "required_action": "close or explicitly defer all remediation tickets before manual review can be ready",
        },
        "live_readiness": {
            "status": live_readiness.get("status"),
            "required_action": "keep live blocked until explicit human approval and broker preflight",
        },
        "manual_decision_record": {
            "status": manual_decision_record.get("status"),
            "decision": manual_decision,
            "reviewer_recorded": nested(manual_decision_record, "record_summary.reviewer_recorded", False),
            "evidence_path_count": nested(manual_decision_record, "record_summary.evidence_path_count", 0),
            "traceable_evidence_path_count": traceable_evidence_path_count(manual_decision_record),
            "required_action": "validate human decision record before any paper simulation readiness gate can pass",
        },
    }


def review_milestones(observation_days: int) -> list[dict[str, Any]]:
    return [
        {
            "days": days,
            "reached": observation_days >= days,
            "required_status": "forward_complete_for_manual_review" if days == 30 else "continued_manual_review",
        }
        for days in REVIEW_MILESTONES
    ]


def forward_review_progress(forward: Mapping[str, Any], observation_days: int) -> dict[str, Any]:
    source = mapping(forward.get("review_progress"))
    minimum_days = int(source.get("minimum_complete_days", 30) or 30)
    milestones = source.get("review_milestones")
    if not isinstance(milestones, list) or not milestones:
        milestones = REVIEW_MILESTONES
    completed = source.get("completed_milestones")
    if not isinstance(completed, list):
        completed = [days for days in milestones if isinstance(days, int) and observation_days >= days]
    next_milestone = source.get("next_milestone")
    if next_milestone is None:
        next_milestone = next((days for days in milestones if isinstance(days, int) and observation_days < days), None)
    observed_days = int(source.get("observation_days", observation_days) or 0)
    return {
        "observation_days": observed_days,
        "minimum_complete_days": minimum_days,
        "review_milestones": milestones,
        "completed_milestones": completed,
        "next_milestone": next_milestone,
        "days_until_minimum": max(0, minimum_days - observed_days),
        "manual_review_required": bool(
            source.get("manual_review_required", str(forward.get("status", "")) == "forward_complete_for_manual_review")
        ),
        "manual_review_only_no_paper_or_live_unlock": bool(
            source.get("manual_review_only_no_paper_or_live_unlock", False)
        ),
        "alpha_validation_claim_allowed": bool(source.get("alpha_validation_claim_allowed", False)),
        "paper_or_live_unlock_allowed": bool(source.get("paper_or_live_unlock_allowed", False)),
    }


def evidence_checklist(reports: Mapping[str, Mapping[str, Any]], milestones: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    strategy_gate = mapping(reports.get("strategy_gate"))
    strategy_evidence_audit = mapping(reports.get("strategy_evidence_audit"))
    forward = mapping(reports.get("forward_evaluation"))
    data = mapping(reports.get("data_freshness"))
    small = mapping(reports.get("small_account_preflight"))
    live = mapping(reports.get("live_readiness"))
    manual_decision = mapping(reports.get("manual_decision_record"))
    pit = mapping(reports.get("production_pit_intake_status"))
    acceptance = mapping(reports.get("pit_bundle_acceptance"))
    remediation = remediation_ticket_summary(mapping(reports.get("blocker_taxonomy")))
    thirty_day_reached = any(item.get("days") == 30 and item.get("reached") is True for item in milestones)
    progress = forward_review_progress(forward, int(nested(forward, "metrics.observation_days", 0) or 0))
    return [
        check("strategy_validation_gate_passed", str(strategy_gate.get("status", "")) == "validation_passed_for_forward_observation", strategy_gate.get("status")),
        check(
            "strategy_validation_evidence_audit_ready",
            str(strategy_evidence_audit.get("status", "")) == "validation_evidence_audit_ready_for_forward_observation"
            and int(nested(strategy_evidence_audit, "summary.complete_count", 0) or 0)
            == int(nested(strategy_evidence_audit, "summary.requirement_count", -1) or -1)
            and int(nested(strategy_evidence_audit, "summary.blocked_count", 0) or 0) == 0
            and int(nested(strategy_evidence_audit, "summary.incomplete_count", 0) or 0) == 0
            and nested(strategy_evidence_audit, "guardrails.paper_or_live_unlock_allowed") is False
            and nested(strategy_evidence_audit, "guardrails.live_order_allowed") is False,
            {
                "status": strategy_evidence_audit.get("status"),
                "summary": nested(strategy_evidence_audit, "summary", {}),
                "incomplete_requirements": strategy_evidence_audit.get("incomplete_requirements", []),
            },
        ),
        check("forward_observation_30_day_complete", thirty_day_reached and str(forward.get("status", "")) == "forward_complete_for_manual_review", forward.get("status")),
        check(
            "forward_review_progress_manual_only",
            thirty_day_reached
            and progress["manual_review_required"] is True
            and progress["manual_review_only_no_paper_or_live_unlock"] is True
            and progress["alpha_validation_claim_allowed"] is False
            and progress["paper_or_live_unlock_allowed"] is False,
            progress,
        ),
        check("forward_ledger_recalculation_passed", nested(forward, "checks.ledger_recalculation.passed") is True, nested(forward, "checks.ledger_recalculation")),
        check("forward_target_fill_consistency_passed", nested(forward, "checks.target_fill_consistency.passed") is True, nested(forward, "checks.target_fill_consistency")),
        check(
            "forward_data_gate_no_blocked_runs",
            nested(forward, "checks.daily_data_gate.passed") is True
            and int(nested(forward, "daily_data_gate.blocked_count", 0) or 0) == 0,
            {"daily_data_gate": nested(forward, "daily_data_gate", {}), "check": nested(forward, "checks.daily_data_gate", {})},
        ),
        check("forward_observation_continuity_passed", nested(forward, "observation_continuity.passed") is True, nested(forward, "observation_continuity", {})),
        check("data_freshness_passed", str(data.get("status", "")) == "pass", data.get("status")),
        check("small_account_constraints_passed", str(small.get("status", "")) == "pass_observation_only", small.get("status")),
        check("production_pit_intake_ready", str(pit.get("status", "")) == "production_pit_data_intake_ready", pit.get("status")),
        check("pit_bundle_acceptance_ready", str(acceptance.get("status", "")) == "acceptance_ready_for_manual_config_apply", acceptance.get("status")),
        check("remediation_tickets_closed", remediation["ticket_count"] == 0, remediation),
        check("live_readiness_fail_closed", str(live.get("status", "")) == "live_readiness_blocked", live.get("status")),
        check(
            "manual_decision_record_valid",
            str(manual_decision.get("status", "")) == "manual_decision_record_valid"
            and nested(manual_decision, "record_summary.decision") == "paper_simulation_review_candidate"
            and traceable_evidence_path_count(manual_decision)
            >= int(nested(manual_decision, "record_summary.evidence_path_count", 0) or 0)
            and traceable_evidence_path_count(manual_decision) > 0
            and nested(manual_decision, "guardrails.paper_simulation_allowed") is False
            and nested(manual_decision, "guardrails.live_order_allowed") is False,
            {
                "status": manual_decision.get("status"),
                "decision": nested(manual_decision, "record_summary.decision"),
                "reviewer_recorded": nested(manual_decision, "record_summary.reviewer_recorded"),
                "evidence_path_count": nested(manual_decision, "record_summary.evidence_path_count"),
                "traceable_evidence_path_count": traceable_evidence_path_count(manual_decision),
            },
        ),
        check("no_unsafe_flags", not unsafe_flags(reports), []),
    ]


def check(check_id: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {"check_id": check_id, "passed": bool(passed), "evidence": evidence}


def remediation_ticket_summary(blocker_taxonomy: Mapping[str, Any]) -> dict[str, Any]:
    tickets = [dict(item) for item in list_value(blocker_taxonomy.get("remediation_tickets")) if isinstance(item, Mapping)]
    by_dependency: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for ticket in tickets:
        dependency = str(ticket.get("dependency_type", "unknown"))
        status = str(ticket.get("status", "unknown"))
        by_dependency[dependency] = by_dependency.get(dependency, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "source_status": blocker_taxonomy.get("status", "missing"),
        "ticket_count": len(tickets),
        "external_or_time_dependency_count": sum(1 for item in tickets if item.get("dependency_type") in {"external_user_action", "natural_time"}),
        "engineering_dependency_count": sum(1 for item in tickets if str(item.get("dependency_type", "")).startswith("engineering")),
        "manual_dependency_count": sum(1 for item in tickets if item.get("dependency_type") == "manual_review"),
        "by_dependency_type": dict(sorted(by_dependency.items())),
        "by_status": dict(sorted(by_status.items())),
        "tickets": tickets,
    }


def signoff_requirements() -> list[dict[str, Any]]:
    return [
        {
            "signoff_id": "strategy_research_review",
            "required": True,
            "recorded": False,
            "description": "Reviewer confirms strategy evidence, benchmark comparison, attribution, cost stress, and parameter stability.",
        },
        {
            "signoff_id": "data_lineage_review",
            "required": True,
            "recorded": False,
            "description": "Reviewer confirms production PIT data lineage or explicitly documents why the strategy remains research/observation only.",
        },
        {
            "signoff_id": "forward_observation_review",
            "required": True,
            "recorded": False,
            "description": "Reviewer confirms ledger continuity, simulated fills, target changes, and no future-function evidence.",
        },
        {
            "signoff_id": "risk_constitution_review",
            "required": True,
            "recorded": False,
            "description": "Reviewer confirms 10,000 USD account constraints, leverage policy, stale-data stops, and kill-switch rules.",
        },
    ]


def traceable_evidence_path_count(manual_decision_record: Mapping[str, Any]) -> int:
    return sum(
        1
        for item in list_value(manual_decision_record.get("evidence_path_details"))
        if isinstance(item, Mapping) and item.get("traceable_report_artifact") is True
    )


def unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    keys = {
        "live_order_allowed",
        "live_ready",
        "paper_ready",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "paper_simulation_allowed",
    }
    out = []
    for name, payload in reports.items():
        for path, value in walk(payload):
            if path.split(".")[-1] in keys and value is True:
                out.append(f"{name}.{path}=true")
    return out


def walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(walk(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            out.extend(walk(item, f"{prefix}.{index}"))
    else:
        out.append((prefix, value))
    return out


def nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
