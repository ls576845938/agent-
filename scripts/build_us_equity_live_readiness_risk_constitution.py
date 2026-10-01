#!/usr/bin/env python3
"""Build US equity live-readiness and risk-constitution report.

This report is a fail-closed governance artifact. It records the hard rules
required before any small-capital live pilot can be discussed. It does not
unlock paper simulation or live trading.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "us_equity_live_readiness_risk_constitution_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 实盘前风控宪法.md")
DEFAULT_COMPAT_OUTPUT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json")
DEFAULT_STRATEGY_GATE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json")
DEFAULT_STRATEGY_EVIDENCE_AUDIT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json")
DEFAULT_FORWARD_EVALUATION = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json")
DEFAULT_FORWARD_ROLL = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json")
DEFAULT_MANUAL_REVIEW_PACKET = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json")
DEFAULT_PAPER_SIMULATION_EVALUATION = Path(
    "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json"
)
DEFAULT_PRODUCTION_LINE = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json")
DEFAULT_BLOCKER_TAXONOMY = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json")
DEFAULT_DATA_STATUS = Path("artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json")
DEFAULT_FORWARD_STATE = Path("data/forward_observation/us_etf_rotation_v1/validation_state.json")
DEFAULT_SMALL_ACCOUNT_PREFLIGHT = Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json")
DEFAULT_PRODUCTION_PIT_INTAKE_STATUS = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json")
DEFAULT_PIT_BUNDLE_ACCEPTANCE = Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json")
DEFAULT_EXECUTION_DRILL_EVIDENCE = Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json")
DEFAULT_RISK_LIMITS_CONFIG = Path("configs/risk/us_equity_live_risk_limits.json")


def build_us_equity_live_readiness_risk_constitution(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    compat_output: Path | None = DEFAULT_COMPAT_OUTPUT,
    strategy_gate: Path = DEFAULT_STRATEGY_GATE,
    strategy_evidence_audit: Path = DEFAULT_STRATEGY_EVIDENCE_AUDIT,
    forward_evaluation: Path = DEFAULT_FORWARD_EVALUATION,
    forward_roll: Path = DEFAULT_FORWARD_ROLL,
    manual_review_packet: Path = DEFAULT_MANUAL_REVIEW_PACKET,
    paper_simulation_evaluation: Path = DEFAULT_PAPER_SIMULATION_EVALUATION,
    production_line: Path = DEFAULT_PRODUCTION_LINE,
    blocker_taxonomy: Path = DEFAULT_BLOCKER_TAXONOMY,
    data_status: Path = DEFAULT_DATA_STATUS,
    forward_state: Path = DEFAULT_FORWARD_STATE,
    small_account_preflight: Path = DEFAULT_SMALL_ACCOUNT_PREFLIGHT,
    production_pit_intake_status: Path = DEFAULT_PRODUCTION_PIT_INTAKE_STATUS,
    pit_bundle_acceptance: Path = DEFAULT_PIT_BUNDLE_ACCEPTANCE,
    execution_drill_evidence: Path = DEFAULT_EXECUTION_DRILL_EVIDENCE,
    risk_limits_config: Path | None = DEFAULT_RISK_LIMITS_CONFIG,
    account_capital_usd: float = 10000.0,
    max_live_principal_usd: float = 0.0,
    manual_reviewer: str = "",
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    risk_limits = _read_json(_resolve(root, risk_limits_config)) if risk_limits_config is not None else {}
    account_capital_usd = _configured_number(account_capital_usd, 10000.0, risk_limits.get("account_capital_usd"))
    max_live_principal_usd = _configured_number(max_live_principal_usd, 0.0, risk_limits.get("max_live_principal_usd"))
    if not manual_reviewer:
        manual_reviewer = str(risk_limits.get("manual_reviewer", "") or "")
    paths = {
        "strategy_gate": _resolve(root, strategy_gate),
        "strategy_evidence_audit": _resolve(root, strategy_evidence_audit),
        "forward_evaluation": _resolve(root, forward_evaluation),
        "forward_roll": _resolve(root, forward_roll),
        "manual_review_packet": _resolve(root, manual_review_packet),
        "paper_simulation_evaluation": _resolve(root, paper_simulation_evaluation),
        "production_line": _resolve(root, production_line),
        "blocker_taxonomy": _resolve(root, blocker_taxonomy),
        "data_status": _resolve(root, data_status),
        "forward_state": _resolve(root, forward_state),
        "small_account_preflight": _resolve(root, small_account_preflight),
        "production_pit_intake_status": _resolve(root, production_pit_intake_status),
        "pit_bundle_acceptance": _resolve(root, pit_bundle_acceptance),
        "execution_drill_evidence": _resolve(root, execution_drill_evidence),
    }
    if risk_limits_config is not None:
        paths["risk_limits_config"] = _resolve(root, risk_limits_config)
    reports = {name: _read_json(path) for name, path in paths.items()}
    blockers: list[str] = []

    missing = [name for name, payload in reports.items() if not payload]
    blockers.extend([f"us_equity_live_readiness_missing_{name}" for name in missing])

    strategy_gate_payload = reports["strategy_gate"]
    strategy_evidence_audit_payload = reports["strategy_evidence_audit"]
    forward_eval = reports["forward_evaluation"]
    forward_roll_payload = reports["forward_roll"]
    manual_review_payload = reports["manual_review_packet"]
    paper_eval = reports["paper_simulation_evaluation"]
    production = reports["production_line"]
    taxonomy = reports["blocker_taxonomy"]
    data = reports["data_status"]
    state = reports["forward_state"]
    preflight = reports["small_account_preflight"]
    pit_status = reports["production_pit_intake_status"]
    pit_acceptance = reports["pit_bundle_acceptance"]
    execution_evidence = reports["execution_drill_evidence"]
    execution_drills = _execution_drill_statuses(execution_evidence)

    observation_days = int(
        _nested(forward_eval, "metrics.observation_days", default=0)
        or _nested(state, "days_completed", default=0)
        or 0
    )
    minimum_days = int(_nested(forward_eval, "minimum_complete_days", default=30) or 30)
    strategy_status = str(strategy_gate_payload.get("status", ""))
    forward_status = str(forward_eval.get("status", ""))
    paper_simulation_status = str(paper_eval.get("status", ""))
    data_status_value = str(data.get("status", ""))

    if strategy_status != "validation_passed_for_forward_observation":
        blockers.append("us_equity_live_readiness_strategy_validation_gate_not_passed")
    if str(strategy_evidence_audit_payload.get("status", "")) != "validation_evidence_audit_ready_for_forward_observation":
        blockers.append("us_equity_live_readiness_strategy_validation_evidence_audit_not_ready")
    if int(_nested(strategy_evidence_audit_payload, "summary.blocked_count", default=0) or 0) > 0:
        blockers.append("us_equity_live_readiness_strategy_validation_evidence_blocked")
    if int(_nested(strategy_evidence_audit_payload, "summary.incomplete_count", default=0) or 0) > 0:
        blockers.append("us_equity_live_readiness_strategy_validation_evidence_incomplete")
    if observation_days < minimum_days:
        blockers.append("us_equity_live_readiness_forward_observation_less_than_30_days")
    if forward_status != "forward_complete_for_manual_review":
        blockers.append("us_equity_live_readiness_forward_observation_not_complete_for_manual_review")
    if str(forward_roll_payload.get("status", "")) != "PASS":
        blockers.append("us_equity_live_readiness_forward_roll_not_pass")
    if str(manual_review_payload.get("status", "")) != "manual_review_ready":
        blockers.append("us_equity_live_readiness_manual_review_packet_not_ready")
    if _nested(manual_review_payload, "guardrails.manual_approval_recorded", default=False) is not True:
        blockers.append("us_equity_live_readiness_manual_approval_not_recorded")
    if _nested(manual_review_payload, "paper_or_live_unlock_decision.manual_review_can_unlock_live_by_itself", default=True) is not False:
        blockers.append("us_equity_live_readiness_manual_review_unlock_boundary_invalid")
    if paper_simulation_status != "paper_simulation_complete_for_manual_review":
        blockers.append("us_equity_live_readiness_paper_simulation_not_complete_for_manual_review")
    if data_status_value != "pass":
        blockers.append("us_equity_live_readiness_data_status_not_pass")
    if str(production.get("status", "")) != "production_line_manual_review_required":
        blockers.append("us_equity_live_readiness_production_line_not_at_manual_review")
    remediation_tickets = _remediation_ticket_summary(taxonomy)
    if remediation_tickets["ticket_count"] > 0:
        blockers.append("us_equity_live_readiness_remediation_tickets_open")
    if str(preflight.get("status", "")) != "pass_observation_only":
        blockers.append("us_equity_live_readiness_small_account_execution_preflight_not_pass")
    if str(pit_status.get("status", "")) != "production_pit_data_intake_ready":
        blockers.append("us_equity_live_readiness_production_pit_intake_not_ready")
    if str(pit_acceptance.get("status", "")) != "acceptance_ready_for_manual_config_apply":
        blockers.append("us_equity_live_readiness_pit_bundle_acceptance_not_ready")

    unsafe_flags = _unsafe_flags(reports)
    blockers.extend([f"us_equity_live_readiness_unsafe_flag:{item}" for item in unsafe_flags])

    if account_capital_usd <= 0.0:
        blockers.append("us_equity_live_readiness_account_capital_not_set")
    if max_live_principal_usd <= 0.0:
        blockers.append("us_equity_live_readiness_max_live_principal_usd_not_set")
    if max_live_principal_usd > account_capital_usd:
        blockers.append("us_equity_live_readiness_max_live_principal_exceeds_account_capital")
    if not manual_reviewer:
        blockers.append("us_equity_live_readiness_manual_reviewer_not_recorded")
    if execution_drills.get("broker_credentials_review") != "proven":
        blockers.append("us_equity_live_readiness_broker_credentials_not_configured")
    if execution_drills.get("order_reconciliation_drill") != "proven":
        blockers.append("us_equity_live_readiness_order_reconciliation_not_proven")
    if execution_drills.get("kill_switch_drill") != "proven":
        blockers.append("us_equity_live_readiness_kill_switch_not_proven")
    if execution_drills.get("monitoring_alerting_drill") != "proven":
        blockers.append("us_equity_live_readiness_monitoring_and_alerting_not_proven")

    constitution = {
        "constitution_version": "us_equity_live_risk_constitution_v1",
        "scope": "US equity multi-strategy infrastructure; current candidate is ETF rotation forward observation only.",
        "capital": {
            "account_capital_usd": _round(account_capital_usd),
            "max_live_principal_usd": _round(max_live_principal_usd),
            "default_until_manual_set": 0.0,
            "capital_must_be_segregated": True,
            "do_not_add_capital_after_win_streak": True,
        },
        "instrument_limits": {
            "allowed_instrument_type": "listed US ETFs only for the first pilot",
            "single_name_stocks_allowed": False,
            "options_allowed": False,
            "futures_allowed": False,
            "shorting_allowed": False,
            "initial_live_leverage_cap": 1.0,
            "research_max_leverage_seen": 1.5,
            "leverage_above_1x_requires_separate_manual_approval": True,
        },
        "execution_constraints": {
            "broker_private_endpoint_allowed_before_live_gate": False,
            "order_endpoint_allowed_before_live_gate": False,
            "manual_order_confirmation_required_for_first_live_pilot": True,
            "margin_and_financing_rate_preflight_required": True,
            "whole_or_fractional_share_rule_required": True,
            "minimum_trade_amount_rule_required": True,
            "monthly_or_daily_rebalance_calendar_must_be_explicit": True,
        },
        "strategy_limits": {
            "primary_candidate": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
            "forward_observation_is_not_alpha_validation": True,
            "strategy_validation_gate_required": True,
            "parameter_tuning_during_forward_observation_allowed": False,
            "unregistered_strategy_live_allowed": False,
        },
        "loss_limits": {
            "pilot_daily_loss_stop_pct_of_principal": 1.0,
            "pilot_total_drawdown_stop_pct_of_principal": 3.0,
            "consecutive_bad_reconciliation_stop_count": 1,
            "manual_reset_required_after_stop": True,
        },
        "review_required": {
            "forward_observation_days": minimum_days,
            "manual_strategy_review": True,
            "manual_risk_review": True,
            "manual_credentials_review": True,
            "manual_kill_switch_drill": True,
        },
    }
    gate_checks = {
        "strategy_validation_gate_passed": strategy_status == "validation_passed_for_forward_observation",
        "strategy_validation_evidence_audit_ready": (
            str(strategy_evidence_audit_payload.get("status", "")) == "validation_evidence_audit_ready_for_forward_observation"
            and int(_nested(strategy_evidence_audit_payload, "summary.blocked_count", default=0) or 0) == 0
            and int(_nested(strategy_evidence_audit_payload, "summary.incomplete_count", default=0) or 0) == 0
        ),
        "forward_observation_complete": observation_days >= minimum_days and forward_status == "forward_complete_for_manual_review",
        "forward_roll_pass": str(forward_roll_payload.get("status", "")) == "PASS",
        "manual_review_packet_ready": str(manual_review_payload.get("status", "")) == "manual_review_ready",
        "manual_approval_recorded": _nested(manual_review_payload, "guardrails.manual_approval_recorded", default=False) is True,
        "paper_simulation_complete_for_manual_review": (
            paper_simulation_status == "paper_simulation_complete_for_manual_review"
        ),
        "data_status_pass": data_status_value == "pass",
        "production_line_manual_review_required": str(production.get("status", "")) == "production_line_manual_review_required",
        "remediation_tickets_closed": remediation_tickets["ticket_count"] == 0,
        "no_unsafe_live_flags": not unsafe_flags,
        "account_capital_set": account_capital_usd > 0.0,
        "max_live_principal_set": max_live_principal_usd > 0.0,
        "manual_reviewer_recorded": bool(manual_reviewer),
        "broker_credentials_review_complete": execution_drills.get("broker_credentials_review") == "proven",
        "margin_and_financing_preflight_complete": execution_drills.get("margin_financing_share_rounding_preflight") == "proven",
        "share_rounding_rule_complete": execution_drills.get("margin_financing_share_rounding_preflight") == "proven",
        "small_account_execution_preflight_pass": str(preflight.get("status", "")) == "pass_observation_only",
        "production_pit_intake_ready": str(pit_status.get("status", "")) == "production_pit_data_intake_ready",
        "pit_bundle_acceptance_ready": str(pit_acceptance.get("status", "")) == "acceptance_ready_for_manual_config_apply",
        "order_reconciliation_proven": execution_drills.get("order_reconciliation_drill") == "proven",
        "kill_switch_drill_complete": execution_drills.get("kill_switch_drill") == "proven",
        "monitoring_and_alerting_proven": execution_drills.get("monitoring_alerting_drill") == "proven",
    }
    execution_readiness = _execution_readiness(gate_checks)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "live_readiness_blocked",
        "decision": "do_not_start_live_trading",
        "asset": "us_equity",
        "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
        "account_capital_usd": _round(account_capital_usd),
        "max_live_principal_usd": _round(max_live_principal_usd),
        "live_order_allowed": False,
        "paper_simulation_unlocked_by_this_report": False,
        "real_order_submitted": False,
        "forward_observation": {
            "status": forward_status,
            "observation_days": observation_days,
            "minimum_complete_days": minimum_days,
        },
        "paper_simulation_evaluation": {
            "status": paper_simulation_status,
            "paper_days": int(_nested(paper_eval, "metrics.paper_days", default=0) or 0),
            "minimum_complete_days": int(paper_eval.get("minimum_complete_days", 30) or 30),
        },
        "strategy_validation": {
            "status": strategy_status,
            "evidence_audit_status": strategy_evidence_audit_payload.get("status"),
            "evidence_complete_count": _nested(strategy_evidence_audit_payload, "summary.complete_count", default=0),
            "evidence_blocked_count": _nested(strategy_evidence_audit_payload, "summary.blocked_count", default=0),
            "evidence_incomplete_count": _nested(strategy_evidence_audit_payload, "summary.incomplete_count", default=0),
            "paper_simulation_allowed": strategy_gate_payload.get("paper_simulation_allowed"),
            "live_order_allowed": strategy_gate_payload.get("live_order_allowed"),
        },
        "manual_review": {
            "status": manual_review_payload.get("status"),
            "manual_approval_recorded": _nested(manual_review_payload, "guardrails.manual_approval_recorded", default=False),
            "manual_review_can_unlock_paper_by_itself": _nested(
                manual_review_payload,
                "paper_or_live_unlock_decision.manual_review_can_unlock_paper_by_itself",
                default=None,
            ),
            "manual_review_can_unlock_live_by_itself": _nested(
                manual_review_payload,
                "paper_or_live_unlock_decision.manual_review_can_unlock_live_by_itself",
                default=None,
            ),
        },
        "production_pit_data": {
            "intake_status": pit_status.get("status"),
            "current_blocking_stage": pit_status.get("current_blocking_stage"),
            "acceptance_status": pit_acceptance.get("status"),
            "acceptance_current_blocking_step": pit_acceptance.get("current_blocking_step"),
        },
        "remediation_tickets": remediation_tickets,
        "gate_checks": gate_checks,
        "risk_constitution": constitution,
        "execution_readiness": execution_readiness,
        "unsafe_flags": unsafe_flags,
        "blockers": _dedupe(blockers),
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "compat_json": _relpath(_resolve(root, compat_output), root) if compat_output is not None else None,
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
        "guardrails": {
            "research_only_until_live_gate_passes": True,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "manual_review_required": True,
        },
    }
    _write_json(_resolve(root, output), payload)
    if compat_output is not None:
        _write_json(_resolve(root, compat_output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    keys = {
        "live_order_allowed",
        "live_ready",
        "private_endpoint_used",
        "order_endpoint_used",
        "real_order_submitted",
        "real_orders_created",
        "broker_calls_used",
        "paper_simulation_allowed",
    }
    out = []
    for report_name, payload in reports.items():
        for path, value in _walk(payload):
            key = path.split(".")[-1]
            if key in keys and value is True:
                out.append(f"{report_name}.{path}=true")
    return out


def _remediation_ticket_summary(blocker_taxonomy: Mapping[str, Any]) -> dict[str, Any]:
    tickets = [dict(item) for item in _list(blocker_taxonomy.get("remediation_tickets")) if isinstance(item, Mapping)]
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


def _execution_drill_statuses(report: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item.get("drill_id", "")): str(item.get("status", ""))
        for item in _list(report.get("drills"))
        if isinstance(item, Mapping)
    }


def _execution_readiness(gate_checks: Mapping[str, bool]) -> dict[str, Any]:
    drills = [
        _execution_drill(
            "broker_credentials_review",
            "Broker credentials and account permission review",
            bool(gate_checks.get("broker_credentials_review_complete")),
            [
                "broker account is read-only or explicitly live-disabled until final manual gate",
                "API key scope excludes order placement before live approval",
                "account id and funding source are recorded outside source control",
            ],
            "us_equity_live_readiness_broker_credentials_not_configured",
        ),
        _execution_drill(
            "margin_financing_share_rounding_preflight",
            "Margin, financing, fractional/whole-share and minimum-trade preflight",
            bool(gate_checks.get("margin_and_financing_preflight_complete"))
            and bool(gate_checks.get("share_rounding_rule_complete"))
            and bool(gate_checks.get("small_account_execution_preflight_pass")),
            [
                "financing rate source is recorded",
                "initial and maintenance margin assumptions are explicit",
                "fractional-share support is known",
                "target weights can be converted to executable share quantities",
            ],
            "us_equity_live_readiness_margin_share_rounding_preflight_not_proven",
        ),
        _execution_drill(
            "order_reconciliation_drill",
            "Order, fill, cash, position and fee reconciliation drill",
            bool(gate_checks.get("order_reconciliation_proven")),
            [
                "target orders reconcile to simulated fills",
                "portfolio snapshots recompute from fills and prior cash",
                "partial fill, reject, cancel and stale order states have test evidence",
            ],
            "us_equity_live_readiness_order_reconciliation_not_proven",
        ),
        _execution_drill(
            "kill_switch_drill",
            "Manual and automated kill-switch drill",
            bool(gate_checks.get("kill_switch_drill_complete")),
            [
                "manual stop procedure is documented",
                "data stale, drawdown, reconciliation failure and broker outage stops are testable",
                "restart requires explicit manual reset",
            ],
            "us_equity_live_readiness_kill_switch_not_proven",
        ),
        _execution_drill(
            "monitoring_alerting_drill",
            "Monitoring, alerting and incident review drill",
            bool(gate_checks.get("monitoring_and_alerting_proven")),
            [
                "target/current position drift alerts are defined",
                "data freshness and missing observation alerts are defined",
                "incident review record has required fields and retention path",
            ],
            "us_equity_live_readiness_monitoring_and_alerting_not_proven",
        ),
    ]
    passed_count = sum(1 for item in drills if item["status"] == "proven")
    return {
        "status": "execution_readiness_proven" if passed_count == len(drills) else "execution_readiness_blocked",
        "drill_count": len(drills),
        "proven_count": passed_count,
        "blocked_count": len(drills) - passed_count,
        "drills": drills,
        "guardrails": {
            "readiness_only": True,
            "broker_calls_used": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
    }


def _execution_drill(
    drill_id: str,
    title: str,
    passed: bool,
    required_evidence: list[str],
    blocker: str,
) -> dict[str, Any]:
    return {
        "drill_id": drill_id,
        "title": title,
        "status": "proven" if passed else "blocked",
        "required_evidence": required_evidence,
        "blockers": [] if passed else [blocker],
    }


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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _nested(value: Any, dotted: str, default: Any = "") -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _round(value: float) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(out, 6) if math.isfinite(out) else 0.0


def _configured_number(explicit_value: float, default_value: float, config_value: Any) -> float:
    if explicit_value != default_value:
        return _round(explicit_value)
    try:
        configured = float(config_value)
    except (TypeError, ValueError):
        return _round(explicit_value)
    return _round(configured) if math.isfinite(configured) else _round(explicit_value)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _markdown(payload: Mapping[str, Any]) -> str:
    constitution = _mapping(payload.get("risk_constitution"))
    gate_checks = _mapping(payload.get("gate_checks"))
    remediation = _mapping(payload.get("remediation_tickets"))
    execution = _mapping(payload.get("execution_readiness"))
    paper_eval = _mapping(payload.get("paper_simulation_evaluation"))
    blockers = _list(payload.get("blockers"))
    lines = [
        "# US Equity 实盘前风控宪法",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        "## 当前结论",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- live_order_allowed：`{payload.get('live_order_allowed', False)}`",
        f"- 账户参考本金：`${payload.get('account_capital_usd', 0)}`",
        f"- 已授权实盘本金上限：`${payload.get('max_live_principal_usd', 0)}`",
        f"- paper simulation：`{paper_eval.get('status')}`，days=`{paper_eval.get('paper_days')}`/`{paper_eval.get('minimum_complete_days')}`",
        f"- remediation tickets：`{remediation.get('ticket_count')}`",
        "",
        "本文档是实盘前门禁和风控宪法，不是实盘授权。当前美股系统不得真实下单。",
        "",
        "## Gate 检查",
        "",
        "| 项目 | 结果 |",
        "| --- | --- |",
    ]
    for key, passed in gate_checks.items():
        lines.append(f"| `{key}` | `{'PASS' if passed else 'FAIL'}` |")
    lines += [
        "",
        "## 硬规则",
        "",
        f"- 范围：{constitution.get('scope', '')}",
        f"- 初始实盘杠杆上限：`{_nested(constitution, 'instrument_limits.initial_live_leverage_cap', 1.0)}x`。",
        "- 研究中出现的 `1.5x` 不等于初始实盘许可；超过 `1x` 必须单独人工审批。",
        "- 首次试运行只允许美股 ETF；不允许期权、期货、做空或未注册策略。",
        "- broker 私有接口、下单接口、融资利率、保证金、整股/碎股、最小成交额必须先通过 preflight。",
        f"- 试运行单日亏损停机线：`{_nested(constitution, 'loss_limits.pilot_daily_loss_stop_pct_of_principal', 0)}%`。",
        f"- 试运行总回撤停机线：`{_nested(constitution, 'loss_limits.pilot_total_drawdown_stop_pct_of_principal', 0)}%`。",
        "",
        "## 必须补齐后才能讨论实盘",
        "",
    ]
    if blockers:
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    else:
        lines.append("- 无")
    lines.extend(["", "## 执行演练门禁", ""])
    lines.append(
        f"- status: `{execution.get('status')}`，proven=`{execution.get('proven_count')}`/`{execution.get('drill_count')}`"
    )
    lines.extend(["", "| drill | status | first blocker |", "| --- | --- | --- |"])
    for drill in _list(execution.get("drills")):
        if not isinstance(drill, Mapping):
            continue
        drill_blockers = _list(drill.get("blockers"))
        lines.append(
            f"| `{drill.get('drill_id')}` | `{drill.get('status')}` | `{drill_blockers[0] if drill_blockers else ''}` |"
        )
    lines.extend(["", "## Remediation Tickets", ""])
    tickets = [item for item in _list(remediation.get("tickets")) if isinstance(item, Mapping)]
    if tickets:
        for ticket in tickets:
            lines.append(
                f"- `{ticket.get('ticket_id')}`：`{ticket.get('status')}`，owner=`{ticket.get('owner')}`，dependency=`{ticket.get('dependency_type')}`"
            )
    else:
        lines.append("- None")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build US equity live-readiness risk constitution.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--compat-output", default=str(DEFAULT_COMPAT_OUTPUT))
    parser.add_argument("--risk-limits-config", default=str(DEFAULT_RISK_LIMITS_CONFIG))
    parser.add_argument("--account-capital-usd", type=float, default=10000.0)
    parser.add_argument("--max-live-principal-usd", type=float, default=0.0)
    parser.add_argument("--manual-reviewer", default="")
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        compat_output=Path(args.compat_output) if args.compat_output else None,
        risk_limits_config=Path(args.risk_limits_config) if args.risk_limits_config else None,
        account_capital_usd=args.account_capital_usd,
        max_live_principal_usd=args.max_live_principal_usd,
        manual_reviewer=args.manual_reviewer,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
