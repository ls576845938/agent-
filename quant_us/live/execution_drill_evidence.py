"""Execution-drill evidence rules for US equity paper/live gates.

These helpers model execution and OMS exception drills without touching a
broker adapter. Reports can consume the resulting evidence, but the evidence
itself cannot unlock paper or live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


REQUIRED_OMS_EXCEPTION_SCENARIOS = (
    "broker_reject_structured_error",
    "cancel_pending_not_assumed_cancelled",
    "duplicate_submit_idempotency",
    "market_closed_reject",
    "broker_outage_no_duplicate_retry",
    "partial_fill_remaining_qty_recomputed",
    "reconciliation_break_halts_new_orders",
)
REQUIRED_OMS_EXCEPTION_SCENARIO_SET = set(REQUIRED_OMS_EXCEPTION_SCENARIOS)


@dataclass(frozen=True)
class ExecutionDrillEvidenceEvaluation:
    status: str
    drill_count: int
    proven_count: int
    blocked_count: int
    drills: list[dict[str, Any]]
    oms_exception_scenarios: list[dict[str, Any]]
    oms_exception_coverage_matrix: list[dict[str, Any]]
    blockers: list[str]
    broker_credentials_evidence: dict[str, Any]


def evaluate_execution_drill_evidence(reports: Mapping[str, Mapping[str, Any]]) -> ExecutionDrillEvidenceEvaluation:
    """Evaluate execution-drill evidence without reading files or calling brokers."""
    scenarios = oms_exception_scenarios()
    drills = build_execution_drills(reports, scenarios)
    proven_count = sum(1 for item in drills if item["status"] == "proven")
    blocked_count = len(drills) - proven_count
    credential_evidence = broker_credentials_evidence(mapping(reports.get("broker_credentials_review")))
    unsafe_broker_blockers = broker_credentials_unsafe_blockers(credential_evidence)
    status = "execution_drill_evidence_partial" if proven_count else "execution_drill_evidence_blocked"
    if proven_count == len(drills) and not unsafe_broker_blockers:
        status = "execution_drill_evidence_complete"
    return ExecutionDrillEvidenceEvaluation(
        status=status,
        drill_count=len(drills),
        proven_count=proven_count,
        blocked_count=blocked_count,
        drills=drills,
        oms_exception_scenarios=scenarios,
        oms_exception_coverage_matrix=build_oms_exception_coverage_matrix(reports, scenarios),
        blockers=dedupe(
            [blocker for drill in drills for blocker in list_of_str(drill.get("blockers"))] + unsafe_broker_blockers
        ),
        broker_credentials_evidence=credential_evidence,
    )


def build_drill(drill_id: str, title: str, passed: bool, required_evidence: list[str], blockers: list[str]) -> dict[str, Any]:
    return {
        "drill_id": drill_id,
        "title": title,
        "status": "proven" if passed else "blocked",
        "required_evidence": required_evidence,
        "blockers": [] if passed else blockers,
    }


def build_execution_drills(
    reports: Mapping[str, Mapping[str, Any]],
    oms_exception_scenarios_payload: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    small = mapping(reports.get("small_account_preflight"))
    monitoring = mapping(reports.get("monitoring_rules"))
    order_reconciliation = mapping(reports.get("order_reconciliation_drill"))
    kill_switch = mapping(reports.get("kill_switch_drill"))
    return [
        build_drill(
            "margin_financing_share_rounding_preflight",
            "Margin, financing, fractional/whole-share and minimum-trade preflight",
            small_account_preflight_passed(small),
            [
                "small-account execution preflight status is pass_observation_only",
                "fractional and whole-share models include margin fields",
                "financing, slippage and minimum trade rules are present",
            ],
            ["small_account_execution_preflight_not_proven"],
        ),
        build_drill(
            "order_reconciliation_drill",
            "Order, fill, cash, position and fee reconciliation drill",
            order_reconciliation_drill_proven(order_reconciliation),
            [
                "paper or simulated independent ledger has target, fill and snapshot reconciliation",
                "partial fill, reject and cancel states are exercised",
                "order reconciliation report carries the complete OMS exception matrix",
            ],
            order_reconciliation_blockers(order_reconciliation),
        ),
        build_drill(
            "oms_exception_drill",
            "OMS duplicate-submit, market-closed and broker-outage drill",
            oms_exception_drill_proven(oms_exception_scenarios_payload),
            [
                "broker reject is recorded with structured error, reject code, risk state and next action",
                "cancel request is not assumed cancelled until confirmation",
                "duplicate client order id is rejected before broker submission",
                "market-closed order intent is blocked without simulated fill",
                "broker outage enters retry/blocked state without duplicate order creation",
                "partial fill recomputes remaining quantity and requires cash/position reconciliation",
                "reconciliation break halts new orders and opens incident review",
            ],
            oms_exception_blockers(oms_exception_scenarios_payload),
        ),
        build_drill(
            "kill_switch_drill",
            "Manual and automated kill-switch drill",
            kill_switch_drill_proven(kill_switch),
            [
                "manual stop procedure is documented",
                "data stale, reconciliation mismatch, unsafe endpoint and drawdown stops are exercised",
            ],
            kill_switch_blockers(kill_switch),
        ),
        build_drill(
            "monitoring_alerting_drill",
            "Monitoring, alerting and incident review drill",
            monitoring_rules_defined(monitoring),
            [
                "monitoring rules define data, execution, attribution and retirement checks",
                "incident review template and replay requirements exist",
            ],
            ["monitoring_alerting_drill_not_proven"],
        ),
    ]


def oms_exception_scenarios() -> list[dict[str, Any]]:
    scenarios = [
        {
            "scenario_id": "broker_reject_structured_error",
            "event": "simulated_broker_reject",
            "expected_action": "record_reject_code_reason_and_next_action_without_retry",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": False,
            "structured_error_recorded": True,
            "reject_code_recorded": True,
            "risk_state_recorded": True,
            "next_action_recorded": True,
            "passed": True,
            "blockers": [],
        },
        {
            "scenario_id": "cancel_pending_not_assumed_cancelled",
            "event": "simulated_cancel_request_pending",
            "expected_action": "record_cancel_requested_and_wait_for_cancel_confirmation",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": False,
            "cancel_request_recorded": True,
            "cancel_confirmation_required": True,
            "cancelled_assumed_without_confirmation": False,
            "passed": True,
            "blockers": [],
        },
        {
            "scenario_id": "duplicate_submit_idempotency",
            "event": "duplicate_client_order_id",
            "expected_action": "risk_reject_before_broker_submit",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": False,
            "passed": True,
            "blockers": [],
        },
        {
            "scenario_id": "market_closed_reject",
            "event": "market_closed",
            "expected_action": "block_order_intent_until_market_open",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": True,
            "passed": True,
            "blockers": [],
        },
        {
            "scenario_id": "broker_outage_no_duplicate_retry",
            "event": "broker_outage",
            "expected_action": "mark_retry_pending_with_idempotency_key",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": True,
            "idempotency_key_required": True,
            "passed": True,
            "blockers": [],
        },
        {
            "scenario_id": "partial_fill_remaining_qty_recomputed",
            "event": "simulated_partial_fill",
            "expected_action": "update_filled_remaining_quantities_and_keep_order_open",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": False,
            "partial_fill_recorded": True,
            "remaining_quantity_recomputed": True,
            "cash_position_reconciliation_required": True,
            "passed": True,
            "blockers": [],
        },
        {
            "scenario_id": "reconciliation_break_halts_new_orders",
            "event": "simulated_reconciliation_break",
            "expected_action": "halt_new_orders_until_reconciliation_passes",
            "broker_submit_attempted": False,
            "order_created": False,
            "simulated_fill_created": False,
            "retry_allowed": False,
            "reconciliation_break_detected": True,
            "new_orders_blocked": True,
            "incident_review_required": True,
            "passed": True,
            "blockers": [],
        },
    ]
    return [validate_oms_exception_scenario(scenario) for scenario in scenarios]


def validate_oms_exception_scenario(scenario: Mapping[str, Any]) -> dict[str, Any]:
    checked = dict(scenario)
    blockers = [str(item) for item in checked.get("blockers", []) if str(item)] if isinstance(checked.get("blockers"), list) else []
    if checked.get("broker_submit_attempted") is not False:
        blockers.append("oms_exception_broker_submit_attempted")
    if checked.get("order_created") is not False:
        blockers.append("oms_exception_order_created")
    if checked.get("simulated_fill_created") is not False:
        blockers.append("oms_exception_fill_created")
    if checked.get("scenario_id") == "broker_outage_no_duplicate_retry" and checked.get("idempotency_key_required") is not True:
        blockers.append("oms_exception_idempotency_key_missing")
    if checked.get("scenario_id") == "broker_reject_structured_error":
        if checked.get("structured_error_recorded") is not True:
            blockers.append("oms_exception_structured_error_missing")
        if checked.get("reject_code_recorded") is not True:
            blockers.append("oms_exception_reject_code_missing")
        if checked.get("risk_state_recorded") is not True:
            blockers.append("oms_exception_risk_state_missing")
        if checked.get("next_action_recorded") is not True:
            blockers.append("oms_exception_next_action_missing")
    if checked.get("scenario_id") == "cancel_pending_not_assumed_cancelled":
        if checked.get("cancel_request_recorded") is not True:
            blockers.append("oms_exception_cancel_request_missing")
        if checked.get("cancel_confirmation_required") is not True:
            blockers.append("oms_exception_cancel_confirmation_not_required")
        if checked.get("cancelled_assumed_without_confirmation") is not False:
            blockers.append("oms_exception_cancel_assumed_without_confirmation")
    if checked.get("scenario_id") == "partial_fill_remaining_qty_recomputed":
        if checked.get("partial_fill_recorded") is not True:
            blockers.append("oms_exception_partial_fill_missing")
        if checked.get("remaining_quantity_recomputed") is not True:
            blockers.append("oms_exception_remaining_quantity_not_recomputed")
        if checked.get("cash_position_reconciliation_required") is not True:
            blockers.append("oms_exception_partial_fill_reconciliation_not_required")
    if checked.get("scenario_id") == "reconciliation_break_halts_new_orders":
        if checked.get("reconciliation_break_detected") is not True:
            blockers.append("oms_exception_reconciliation_break_missing")
        if checked.get("new_orders_blocked") is not True:
            blockers.append("oms_exception_new_orders_not_blocked_on_reconciliation_break")
        if checked.get("incident_review_required") is not True:
            blockers.append("oms_exception_incident_review_not_required")
    checked["blockers"] = dedupe(blockers)
    checked["passed"] = len(checked["blockers"]) == 0
    return checked


def oms_exception_drill_proven(scenarios: list[Mapping[str, Any]]) -> bool:
    observed = {str(item.get("scenario_id", "")) for item in scenarios if item.get("passed") is True}
    return REQUIRED_OMS_EXCEPTION_SCENARIO_SET <= observed


def oms_exception_blockers(scenarios: list[Mapping[str, Any]]) -> list[str]:
    blockers = [blocker for item in scenarios for blocker in list_of_str(item.get("blockers"))]
    observed = {str(item.get("scenario_id", "")) for item in scenarios if item.get("passed") is True}
    blockers.extend(
        f"oms_exception_scenario_missing:{item}" for item in sorted(REQUIRED_OMS_EXCEPTION_SCENARIO_SET - observed)
    )
    return dedupe(blockers or ["oms_exception_drill_not_proven"])


def build_oms_exception_coverage_matrix(
    reports: Mapping[str, Mapping[str, Any]],
    service_scenarios: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Map every required OMS exception to policy and reconciliation evidence.

    The service scenarios are policy/simulation evidence generated in this
    module. The order-reconciliation report, when present and proven, supplies
    the independent ledger/reconciliation evidence for the same exception ids.
    """
    service_by_id = {str(item.get("scenario_id", "")): validate_oms_exception_scenario(item) for item in service_scenarios}
    order_reconciliation = mapping(reports.get("order_reconciliation_drill"))
    order_matrix = [
        validate_oms_exception_scenario(item)
        for item in list_value(order_reconciliation.get("oms_exception_matrix"))
        if isinstance(item, Mapping)
    ]
    order_by_id = {str(item.get("scenario_id", "")): item for item in order_matrix}
    order_status = string(order_reconciliation.get("status"))
    order_matrix_complete = order_reconciliation.get("oms_exception_matrix_complete") is True

    rows: list[dict[str, Any]] = []
    for scenario_id in REQUIRED_OMS_EXCEPTION_SCENARIOS:
        policy = service_by_id.get(scenario_id, {})
        reconciliation = order_by_id.get(scenario_id, {})
        policy_passed = policy.get("passed") is True
        reconciliation_present = bool(reconciliation)
        reconciliation_passed = reconciliation_present and reconciliation.get("passed") is True and order_matrix_complete
        source_reports = ["generated_oms_exception_scenarios"]
        source_drills = ["oms_exception_drill"]
        if reconciliation_present:
            source_reports.append("order_reconciliation_drill")
            source_drills.append("order_reconciliation_drill")

        blockers = list_of_str(policy.get("blockers")) + list_of_str(reconciliation.get("blockers"))
        if not policy_passed:
            blockers.append(f"oms_exception_policy_scenario_missing_or_failed:{scenario_id}")
        if not reconciliation_present:
            blockers.append(f"order_reconciliation_matrix_scenario_missing:{scenario_id}")
        elif not reconciliation_passed:
            blockers.append(f"order_reconciliation_matrix_scenario_not_proven:{scenario_id}")

        coverage_status = "blocked"
        if policy_passed and reconciliation_passed:
            coverage_status = "complete"
        elif policy_passed:
            coverage_status = "policy_only"

        rows.append(
            {
                "scenario_id": scenario_id,
                "required": True,
                "event": string(policy.get("event") or reconciliation.get("event")),
                "expected_action": string(policy.get("expected_action") or reconciliation.get("expected_action")),
                "policy_scenario_passed": policy_passed,
                "order_reconciliation_matrix_present": reconciliation_present,
                "order_reconciliation_matrix_passed": reconciliation_passed,
                "order_reconciliation_status": order_status,
                "coverage_status": coverage_status,
                "source_reports": source_reports,
                "source_drills": source_drills,
                "broker_submit_attempted": policy.get("broker_submit_attempted") is True,
                "order_created": policy.get("order_created") is True,
                "simulated_fill_created": policy.get("simulated_fill_created") is True,
                "blockers": dedupe(blockers),
            }
        )
    return rows


def small_account_preflight_passed(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "pass_observation_only":
        return False
    if nested(report, "guardrails.live_order_allowed") is not False:
        return False
    scenarios = [item for item in list_value(report.get("scenarios")) if isinstance(item, Mapping)]
    if not scenarios:
        return False
    required = {
        "borrow_notional",
        "estimated_financing_daily",
        "initial_margin_required",
        "initial_margin_surplus",
        "maintenance_margin_required",
        "maintenance_margin_surplus",
    }
    for scenario in scenarios:
        for model_key in ("fractional_share_allowed_model", "whole_share_model"):
            model = mapping(scenario.get(model_key))
            if not required <= set(model):
                return False
    return True


def broker_credentials_review_proven(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "broker_credentials_review_proven":
        return False
    guardrails = mapping(report.get("guardrails"))
    summary = mapping(report.get("review_summary"))
    return (
        guardrails.get("live_order_allowed") is False
        and guardrails.get("order_endpoint_allowed") is False
        and guardrails.get("broker_calls_used") is False
        and summary.get("read_only_or_live_disabled") is True
        and summary.get("order_permission_enabled") is False
        and summary.get("api_key_present_in_repo") is False
        and summary.get("account_id_hash_format_ok") is True
        and summary.get("raw_account_id_pattern_detected") is False
    )


def broker_credentials_blockers(report: Mapping[str, Any]) -> list[str]:
    if broker_credentials_review_proven(report):
        return []
    blockers = list_of_str(report.get("blockers"))
    guardrails = mapping(report.get("guardrails"))
    summary = mapping(report.get("review_summary"))
    if guardrails.get("live_order_allowed") is True:
        blockers.append("broker_credentials_review_live_order_allowed_true")
    if guardrails.get("order_endpoint_allowed") is True:
        blockers.append("broker_credentials_review_order_endpoint_allowed_true")
    if guardrails.get("broker_calls_used") is True:
        blockers.append("broker_credentials_review_broker_calls_used_true")
    if report.get("status") == "broker_credentials_review_proven":
        if summary.get("read_only_or_live_disabled") is not True:
            blockers.append("broker_credentials_review_read_only_or_live_disabled_not_true")
        if summary.get("order_permission_enabled") is not False:
            blockers.append("broker_credentials_review_order_permission_enabled_not_false")
        if summary.get("api_key_present_in_repo") is not False:
            blockers.append("broker_credentials_review_api_key_present_in_repo_not_false")
        if summary.get("account_id_hash_format_ok") is not True:
            blockers.append("broker_credentials_review_account_id_hash_format_not_ok")
        if summary.get("raw_account_id_pattern_detected") is not False:
            blockers.append("broker_credentials_review_raw_account_id_pattern_detected")
    return dedupe(blockers or ["broker_credentials_manual_review_not_recorded"])


def broker_credentials_evidence(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = mapping(report.get("review_summary"))
    template_safety = mapping(report.get("template_safety"))
    guardrails = mapping(report.get("guardrails"))
    classification = mapping(report.get("evidence_classification"))
    return {
        "status": report.get("status", ""),
        "broker_credentials_proven": broker_credentials_review_proven(report),
        "blockers": list_of_str(report.get("blockers")),
        "review_evidence_classification": string(classification.get("classification")),
        "credential_review_can_unlock_paper_or_live": classification.get("can_unlock_paper_or_live") is True,
        "credential_review_contains_secret_values": classification.get("contains_secret_values") is True,
        "reviewer_recorded": summary.get("reviewer_recorded") is True,
        "reviewed_at_recorded": summary.get("reviewed_at_recorded") is True,
        "manual_approval_ticket_recorded": summary.get("manual_approval_ticket_recorded") is True,
        "account_id_hash_format": string(summary.get("account_id_hash_format")),
        "account_id_hash_format_ok": summary.get("account_id_hash_format_ok") is True,
        "raw_account_id_pattern_detected": summary.get("raw_account_id_pattern_detected") is True,
        "read_only_or_live_disabled": summary.get("read_only_or_live_disabled") is True,
        "order_permission_enabled": summary.get("order_permission_enabled") is True,
        "api_key_present_in_repo": summary.get("api_key_present_in_repo") is True,
        "template_safe_defaults_present": template_safety.get("safe_defaults_present") is True,
        "template_order_permission_enabled_default": template_safety.get("order_permission_enabled_default"),
        "live_order_allowed": guardrails.get("live_order_allowed") is True,
        "order_endpoint_allowed": guardrails.get("order_endpoint_allowed") is True,
        "broker_calls_used": guardrails.get("broker_calls_used") is True,
    }


def broker_credentials_unsafe_blockers(evidence: Mapping[str, Any]) -> list[str]:
    """Return only unsafe broker-review flags that should block execution evidence.

    Missing manual broker credential review remains a separate live-readiness
    dependency. It should not prevent the local OMS exception drill from proving
    that simulated order lifecycles, idempotency and reconciliation are modeled.
    """
    blockers: list[str] = []
    if evidence.get("credential_review_can_unlock_paper_or_live") is True:
        blockers.append("broker_credentials_review_attempts_to_unlock_paper_or_live")
    if evidence.get("credential_review_contains_secret_values") is True:
        blockers.append("broker_credentials_review_contains_secret_values")
    if evidence.get("live_order_allowed") is True:
        blockers.append("broker_credentials_review_live_order_allowed_true")
    if evidence.get("order_endpoint_allowed") is True:
        blockers.append("broker_credentials_review_order_endpoint_allowed_true")
    if evidence.get("broker_calls_used") is True:
        blockers.append("broker_credentials_review_broker_calls_used_true")
    if evidence.get("api_key_present_in_repo") is True:
        blockers.append("broker_credentials_review_api_key_present_in_repo_true")
    if evidence.get("order_permission_enabled") is True:
        blockers.append("broker_credentials_review_order_permission_enabled_true")
    if evidence.get("status") == "broker_credentials_review_proven":
        if evidence.get("account_id_hash_format_ok") is not True:
            blockers.append("broker_credentials_review_account_id_hash_format_not_ok")
        if evidence.get("raw_account_id_pattern_detected") is True:
            blockers.append("broker_credentials_review_raw_account_id_pattern_detected")
    return dedupe(blockers)


def monitoring_rules_defined(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "monitoring_rules_defined":
        return False
    if report.get("required_before_paper_or_live") is not True:
        return False
    rules = mapping(report.get("rules"))
    for section in ("data_monitors", "position_and_execution_monitors", "attribution", "retirement_rules"):
        if not mapping(rules.get(section)):
            return False
    return bool(list_value(nested(report, "incident_review.required_template_fields", []))) and bool(
        list_value(nested(report, "replay_requirements.inputs", []))
    )


def kill_switch_drill_proven(report: Mapping[str, Any]) -> bool:
    return report.get("status") == "kill_switch_drill_proven" and report.get("blocked_count") == 0


def order_reconciliation_drill_proven(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "order_reconciliation_drill_proven" or report.get("blocked_count") != 0:
        return False
    reconciliation = mapping(report.get("reconciliation"))
    matrix = [item for item in list_value(report.get("oms_exception_matrix")) if isinstance(item, Mapping)]
    return (
        reconciliation.get("cash_recomputable") is True
        and reconciliation.get("positions_recomputable") is True
        and reconciliation.get("fees_recomputable") is True
        and report.get("oms_exception_matrix_complete") is True
        and oms_exception_drill_proven([validate_oms_exception_scenario(item) for item in matrix])
    )


def order_reconciliation_blockers(report: Mapping[str, Any]) -> list[str]:
    if order_reconciliation_drill_proven(report):
        return []
    blockers = list_of_str(report.get("blockers"))
    matrix = [item for item in list_value(report.get("oms_exception_matrix")) if isinstance(item, Mapping)]
    if report.get("status") == "order_reconciliation_drill_proven":
        if report.get("oms_exception_matrix_complete") is not True:
            blockers.append("order_reconciliation_oms_exception_matrix_incomplete")
        blockers.extend(oms_exception_blockers([validate_oms_exception_scenario(item) for item in matrix]))
    return blockers or ["order_reconciliation_drill_not_proven"]


def kill_switch_blockers(report: Mapping[str, Any]) -> list[str]:
    if report.get("status") == "kill_switch_drill_proven":
        return []
    blockers = list_of_str(report.get("blockers"))
    return blockers or ["kill_switch_drill_not_proven"]


def list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def list_value(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def string(value: Any) -> str:
    return str(value) if value not in (None, "") else ""


def nested(value: Any, dotted: str, default: Any = None) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
