"""Paper-simulation readiness rules for US equity governance.

This module contains the domain/service rules for deciding whether the paper
simulation runner may be manually started. It is intentionally read-only and
does not start the runner, submit orders, or unlock live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PAPER_LEDGER_ROOT = Path("data/paper_ledger/us_equity_etf_rotation_v1")
STRATEGY_ID = "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"


@dataclass(frozen=True)
class PaperSimulationReadinessEvaluation:
    status: str
    decision: str
    blockers: list[str]
    unsafe_flags: list[str]
    manual_review_evidence: dict[str, Any]
    remediation_tickets: dict[str, Any]
    paper_start_gate_matrix: list[dict[str, Any]]
    required_runner_contract: dict[str, Any]
    required_ledger_evidence_contract: dict[str, Any]
    guardrails: dict[str, Any]


def evaluate_paper_simulation_readiness(
    reports: Mapping[str, Mapping[str, Any]],
) -> PaperSimulationReadinessEvaluation:
    blockers: list[str] = []
    blockers.extend([f"us_equity_paper_readiness_missing_{name}" for name, payload in reports.items() if not payload])
    if str(reports["manual_review"].get("status", "")) != "manual_review_ready":
        blockers.append("us_equity_paper_readiness_manual_review_not_ready")
    if nested(reports["manual_review"], "guardrails.manual_approval_recorded", False) is not True:
        blockers.append("us_equity_paper_readiness_manual_approval_not_recorded")

    manual_decision_status = str(reports["manual_decision_record"].get("status", ""))
    manual_decision = str(nested(reports["manual_decision_record"], "record_summary.decision", ""))
    if manual_decision_status != "manual_decision_record_valid":
        blockers.append("us_equity_paper_readiness_manual_decision_record_not_valid")
    if manual_decision_status == "manual_decision_record_valid" and manual_decision != "paper_simulation_review_candidate":
        blockers.append("us_equity_paper_readiness_manual_decision_not_paper_candidate")

    if str(reports["strategy_gate"].get("status", "")) != "validation_passed_for_forward_observation":
        blockers.append("us_equity_paper_readiness_strategy_validation_not_passed")
    if str(reports["forward_evaluation"].get("status", "")) != "forward_complete_for_manual_review":
        blockers.append("us_equity_paper_readiness_forward_evaluation_not_complete")
    if str(reports["small_account_preflight"].get("status", "")) != "pass_observation_only":
        blockers.append("us_equity_paper_readiness_small_account_preflight_not_pass")
    if str(reports["production_pit_intake_status"].get("status", "")) != "production_pit_data_intake_ready":
        blockers.append("us_equity_paper_readiness_production_pit_intake_not_ready")
    if str(reports["pit_bundle_acceptance"].get("status", "")) != "acceptance_ready_for_manual_config_apply":
        blockers.append("us_equity_paper_readiness_pit_bundle_acceptance_not_ready")

    remediation_tickets = remediation_ticket_summary(reports["blocker_taxonomy"])
    if remediation_tickets["ticket_count"] > 0:
        blockers.append("us_equity_paper_readiness_remediation_tickets_open")

    manual_evidence = manual_review_evidence(reports["manual_review"])
    manual_evidence.update(manual_decision_evidence(reports["manual_decision_record"]))
    if manual_decision_status == "manual_decision_record_valid" and (
        int(manual_evidence.get("manual_decision_traceable_evidence_path_count", 0) or 0)
        < int(manual_evidence.get("manual_decision_evidence_path_count", 0) or 0)
        or int(manual_evidence.get("manual_decision_traceable_evidence_path_count", 0) or 0) <= 0
    ):
        blockers.append("us_equity_paper_readiness_manual_decision_evidence_not_traceable")
    if manual_evidence["forward_data_gate_no_blocked_runs"] is not True or manual_evidence["forward_data_gate_blocked_count"] > 0:
        blockers.append("us_equity_paper_readiness_forward_data_gate_not_clean")
    if manual_evidence["forward_observation_continuity_passed"] is not True:
        blockers.append("us_equity_paper_readiness_forward_observation_continuity_not_passed")

    unsafe_flags = unsafe_flags_from_reports(reports)
    blockers.extend([f"us_equity_paper_readiness_unsafe_flag:{item}" for item in unsafe_flags])
    gate_matrix = paper_start_gate_matrix(
        reports=reports,
        manual_evidence=manual_evidence,
        remediation_tickets=remediation_tickets,
        unsafe_flags=unsafe_flags,
    )
    blockers = dedupe(blockers)
    return PaperSimulationReadinessEvaluation(
        status="paper_simulation_blocked" if blockers else "paper_simulation_ready_for_manual_start",
        decision="do_not_start_paper_simulation" if blockers else "manual_start_required",
        blockers=blockers,
        unsafe_flags=unsafe_flags,
        manual_review_evidence=manual_evidence,
        remediation_tickets=remediation_tickets,
        paper_start_gate_matrix=gate_matrix,
        required_runner_contract=required_runner_contract(),
        required_ledger_evidence_contract=required_ledger_evidence_contract(),
        guardrails=readiness_guardrails(),
    )


def required_runner_contract() -> dict[str, Any]:
    return {
        "independent_ledger_root": PAPER_LEDGER_ROOT.as_posix(),
        "must_not_reuse_forward_observation_ledger": True,
        "target_ledger_recalculation_required": True,
        "fills_and_snapshots_required": True,
        "broker_private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
    }


def required_ledger_evidence_contract() -> dict[str, Any]:
    return {
        "ledger_root": PAPER_LEDGER_ROOT.as_posix(),
        "forward_observation_source_only": True,
        "required_files": [
            "target_positions.jsonl",
            "fills.jsonl",
            "positions.jsonl",
            "cash_ledger.jsonl",
            "portfolio_snapshots.jsonl",
            "validation_state.json",
        ],
        "required_reconciliation_checks": [
            "ledger_completeness",
            "snapshot_reconciliation",
            "target_fill_consistency",
            "trade_reconciliation",
            "position_cash_consistency",
        ],
        "required_fill_fields": [
            "timestamp",
            "strategy_id",
            "candidate_variant",
            "symbol",
            "side",
            "quantity",
            "price",
            "notional",
            "simulated_only",
            "broker_order_id",
            "exchange_order_id",
        ],
        "required_snapshot_fields": [
            "timestamp",
            "equity",
            "prior_equity",
            "estimated_slippage",
            "estimated_financing_daily",
            "reconciliation_status",
            "simulated_only",
        ],
        "simulated_fills_only": True,
        "broker_order_ids_must_be_absent": True,
        "exchange_order_ids_must_be_absent": True,
        "live_ready_claim_allowed": False,
    }


def readiness_guardrails() -> dict[str, Any]:
    return {
        "readiness_report_only": True,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
    }


def paper_start_gate_matrix(
    *,
    reports: Mapping[str, Mapping[str, Any]],
    manual_evidence: Mapping[str, Any],
    remediation_tickets: Mapping[str, Any],
    unsafe_flags: list[str],
) -> list[dict[str, Any]]:
    return [
        gate(
            "manual_review_ready",
            reports["manual_review"].get("status") == "manual_review_ready",
            "us_equity_paper_readiness_manual_review_not_ready",
            {"status": reports["manual_review"].get("status", "")},
        ),
        gate(
            "manual_approval_recorded",
            manual_evidence.get("manual_approval_recorded") is True,
            "us_equity_paper_readiness_manual_approval_not_recorded",
            {"manual_approval_recorded": manual_evidence.get("manual_approval_recorded")},
        ),
        gate(
            "manual_decision_record_valid",
            manual_evidence.get("manual_decision_record_status") == "manual_decision_record_valid",
            "us_equity_paper_readiness_manual_decision_record_not_valid",
            {
                "status": manual_evidence.get("manual_decision_record_status"),
                "decision": manual_evidence.get("manual_decision"),
                "reviewer_recorded": manual_evidence.get("manual_decision_reviewer_recorded"),
                "evidence_path_count": manual_evidence.get("manual_decision_evidence_path_count"),
                "traceable_evidence_path_count": manual_evidence.get("manual_decision_traceable_evidence_path_count"),
            },
        ),
        gate(
            "manual_decision_is_paper_candidate",
            manual_evidence.get("manual_decision") == "paper_simulation_review_candidate",
            "us_equity_paper_readiness_manual_decision_not_paper_candidate",
            {
                "status": manual_evidence.get("manual_decision_record_status"),
                "decision": manual_evidence.get("manual_decision"),
            },
        ),
        gate(
            "manual_decision_evidence_traceable",
            int(manual_evidence.get("manual_decision_traceable_evidence_path_count", 0) or 0)
            >= int(manual_evidence.get("manual_decision_evidence_path_count", 0) or 0)
            and int(manual_evidence.get("manual_decision_traceable_evidence_path_count", 0) or 0) > 0,
            "us_equity_paper_readiness_manual_decision_evidence_not_traceable",
            {
                "evidence_path_count": manual_evidence.get("manual_decision_evidence_path_count"),
                "traceable_evidence_path_count": manual_evidence.get("manual_decision_traceable_evidence_path_count"),
            },
        ),
        gate(
            "strategy_validation_passed",
            reports["strategy_gate"].get("status") == "validation_passed_for_forward_observation",
            "us_equity_paper_readiness_strategy_validation_not_passed",
            {"status": reports["strategy_gate"].get("status", "")},
        ),
        gate(
            "forward_evaluation_complete",
            reports["forward_evaluation"].get("status") == "forward_complete_for_manual_review",
            "us_equity_paper_readiness_forward_evaluation_not_complete",
            {
                "status": reports["forward_evaluation"].get("status", ""),
                "observation_days": nested(reports["forward_evaluation"], "metrics.observation_days", 0),
            },
        ),
        gate(
            "small_account_preflight_pass",
            reports["small_account_preflight"].get("status") == "pass_observation_only",
            "us_equity_paper_readiness_small_account_preflight_not_pass",
            {"status": reports["small_account_preflight"].get("status", "")},
        ),
        gate(
            "production_pit_intake_ready",
            reports["production_pit_intake_status"].get("status") == "production_pit_data_intake_ready",
            "us_equity_paper_readiness_production_pit_intake_not_ready",
            {"status": reports["production_pit_intake_status"].get("status", "")},
        ),
        gate(
            "pit_bundle_acceptance_ready",
            reports["pit_bundle_acceptance"].get("status") == "acceptance_ready_for_manual_config_apply",
            "us_equity_paper_readiness_pit_bundle_acceptance_not_ready",
            {"status": reports["pit_bundle_acceptance"].get("status", "")},
        ),
        gate(
            "remediation_tickets_closed",
            int(remediation_tickets.get("ticket_count", 0) or 0) == 0,
            "us_equity_paper_readiness_remediation_tickets_open",
            {"ticket_count": remediation_tickets.get("ticket_count", 0)},
        ),
        gate(
            "forward_data_gate_clean",
            manual_evidence.get("forward_data_gate_no_blocked_runs") is True
            and int(manual_evidence.get("forward_data_gate_blocked_count", 0) or 0) == 0,
            "us_equity_paper_readiness_forward_data_gate_not_clean",
            {
                "forward_data_gate_no_blocked_runs": manual_evidence.get("forward_data_gate_no_blocked_runs"),
                "forward_data_gate_blocked_count": manual_evidence.get("forward_data_gate_blocked_count"),
            },
        ),
        gate(
            "forward_observation_continuity_passed",
            manual_evidence.get("forward_observation_continuity_passed") is True,
            "us_equity_paper_readiness_forward_observation_continuity_not_passed",
            {"forward_observation_continuity_passed": manual_evidence.get("forward_observation_continuity_passed")},
        ),
        gate(
            "unsafe_flags_absent",
            not unsafe_flags,
            "us_equity_paper_readiness_unsafe_flags_present",
            {"unsafe_flag_count": len(unsafe_flags)},
        ),
    ]


def gate(gate_id: str, passed: bool, blocker: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "passed": bool(passed),
        "blocker": "" if passed else blocker,
        "evidence": dict(evidence),
    }


def unsafe_flags_from_reports(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    keys = {
        "live_order_allowed",
        "live_ready",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "real_orders_created",
    }
    out = []
    for name, payload in reports.items():
        for path, value in walk(payload):
            if path.split(".")[-1] in keys and value is True:
                out.append(f"{name}.{path}=true")
    return out


def manual_review_evidence(manual_review: Mapping[str, Any]) -> dict[str, Any]:
    checklist_passed = 0
    checklist_total = 0
    forward_data_gate_check: bool | None = None
    forward_continuity_check: bool | None = None
    checklist_items = list_value(manual_review.get("evidence_checklist"))
    if not checklist_items:
        checklist_items = list_value(manual_review.get("checklist"))
    for item in checklist_items:
        if not isinstance(item, Mapping):
            continue
        checklist_total += 1
        passed = item.get("passed") is True
        checklist_passed += int(passed)
        if str(item.get("check_id", "")) == "forward_data_gate_no_blocked_runs":
            forward_data_gate_check = passed
        if str(item.get("check_id", "")) == "forward_observation_continuity_passed":
            forward_continuity_check = passed
    blocked_count = as_int(nested(manual_review, "review_items.forward_observation.data_gate_blocked_count", 0))
    if forward_data_gate_check is None:
        forward_data_gate_check = blocked_count == 0
    if forward_continuity_check is None:
        forward_continuity_check = nested(manual_review, "review_items.forward_observation.continuity_passed", False) is True
    return {
        "status": manual_review.get("status", ""),
        "manual_approval_recorded": nested(manual_review, "guardrails.manual_approval_recorded", False) is True,
        "forward_data_gate_no_blocked_runs": forward_data_gate_check,
        "forward_data_gate_blocked_count": blocked_count,
        "forward_observation_continuity_passed": forward_continuity_check,
        "checklist_passed_count": checklist_passed,
        "checklist_total": checklist_total,
    }


def manual_decision_evidence(manual_decision_record: Mapping[str, Any]) -> dict[str, Any]:
    details = [item for item in list_value(manual_decision_record.get("evidence_path_details")) if isinstance(item, Mapping)]
    return {
        "manual_decision_record_status": manual_decision_record.get("status", ""),
        "manual_decision": nested(manual_decision_record, "record_summary.decision", ""),
        "manual_decision_reviewer_recorded": nested(
            manual_decision_record,
            "record_summary.reviewer_recorded",
            False,
        )
        is True,
        "manual_decision_evidence_path_count": as_int(
            nested(manual_decision_record, "record_summary.evidence_path_count", 0)
        ),
        "manual_decision_traceable_evidence_path_count": sum(
            1 for item in details if item.get("traceable_report_artifact") is True
        ),
    }


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
        "external_or_time_dependency_count": sum(
            1 for item in tickets if item.get("dependency_type") in {"external_user_action", "natural_time"}
        ),
        "engineering_dependency_count": sum(
            1 for item in tickets if str(item.get("dependency_type", "")).startswith("engineering")
        ),
        "manual_dependency_count": sum(1 for item in tickets if item.get("dependency_type") == "manual_review"),
        "by_dependency_type": dict(sorted(by_dependency.items())),
        "by_status": dict(sorted(by_status.items())),
        "tickets": tickets,
    }


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


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def dedupe(items: list[str]) -> list[str]:
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
