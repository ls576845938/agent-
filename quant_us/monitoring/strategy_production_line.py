#!/usr/bin/env python3
"""Service rules for the US equity strategy production-line governance report.

This report deliberately fails closed. It records where each registered US
equity strategy sits in the research-to-live pipeline and prevents forward
observation from being confused with strategy validation or live readiness.

The CLI entrypoint should only parse arguments and call this module.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_strategy_production_line_report_v1"
DEFAULT_REGISTRY = Path("configs/strategies/us_equity_strategy_registry.json")
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 策略生产线状态报告.md")
DEFAULT_DEVELOPMENT_PLAN_AUDIT = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json"
)
DEFAULT_BLOCKER_TAXONOMY = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"
)
DEFAULT_REMEDIATION_TICKET_CLOSURE = Path(
    "artifacts/us_equity_strategy_production_line/latest/us_equity_remediation_ticket_closure_report.json"
)

STAGE_ORDER = [
    "data_ingestion",
    "data_quality_pit_check",
    "strategy_hypothesis_registration",
    "standardized_backtest",
    "cost_liquidity_capacity_stress",
    "walk_forward_parameter_stability",
    "strategy_validation_gate",
    "forward_observation",
    "manual_review",
    "paper_simulation",
    "small_capital_live_readiness",
    "monitoring_attribution_retirement_iteration",
]

STAGE_LABELS = {
    "data_ingestion": "Data ingestion",
    "data_quality_pit_check": "Data quality and point-in-time check",
    "strategy_hypothesis_registration": "Strategy hypothesis registration",
    "standardized_backtest": "Standardized backtest",
    "cost_liquidity_capacity_stress": "Cost, liquidity, and capacity stress",
    "walk_forward_parameter_stability": "Walk-forward and parameter stability",
    "strategy_validation_gate": "Strategy validation gate",
    "forward_observation": "Forward observation",
    "manual_review": "Manual review",
    "paper_simulation": "Paper simulation",
    "small_capital_live_readiness": "Small-capital live readiness",
    "monitoring_attribution_retirement_iteration": "Monitoring, attribution, retirement, and iteration",
}

UNSAFE_TRUE_KEYS = {
    "live_order_allowed",
    "live_ready",
    "paper_ready",
    "private_endpoint_used",
    "order_endpoint_used",
    "real_order_submitted",
    "real_orders_created",
    "broker_calls_used",
}

REQUIRED_COST_STRESS = {"0bps", "10bps", "25bps", "50bps"}


def build_us_equity_strategy_production_line_report(
    *,
    repo_root: Path | None = None,
    registry_path: Path = DEFAULT_REGISTRY,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    registry_abs = _resolve(root, registry_path)
    registry = _read_json(registry_abs)
    development_plan_audit_path = root / DEFAULT_DEVELOPMENT_PLAN_AUDIT
    development_plan_audit = _read_json(development_plan_audit_path)
    blocker_taxonomy_path = root / DEFAULT_BLOCKER_TAXONOMY
    blocker_taxonomy = _read_json(blocker_taxonomy_path)
    remediation_ticket_closure_path = root / DEFAULT_REMEDIATION_TICKET_CLOSURE
    remediation_ticket_closure = _read_json(remediation_ticket_closure_path)

    if not registry:
        payload = _blocked_missing_registry(root, registry_path, output, markdown_output, generated)
        _write_outputs(root, output, markdown_output, payload)
        return payload

    registry_blockers = _registry_blockers(registry)
    configured_order = _list_of_str(registry.get("production_line_order"))
    order_blockers = [] if configured_order == STAGE_ORDER else ["us_equity_strategy_registry_stage_order_mismatch"]
    strategies = []
    for entry in _list(registry.get("strategies")):
        if isinstance(entry, Mapping):
            strategies.append(_build_strategy_line(root, entry))

    unsafe_flags = []
    for strategy in strategies:
        unsafe_flags.extend(strategy.get("unsafe_flags", []))

    blockers = _dedupe(registry_blockers + order_blockers)
    for strategy in strategies:
        if strategy.get("primary_candidate"):
            blockers.extend(str(item) for item in strategy.get("blockers", []))
    if unsafe_flags:
        blockers.append("us_equity_strategy_production_line_unsafe_flags_detected")
    blockers = _dedupe(blockers)

    primary = [item for item in strategies if item.get("primary_candidate")]
    primary_stage_map = {stage["stage_id"]: stage for stage in primary[0]["stages"]} if primary else {}
    independent_gate_passed = primary_stage_map.get("strategy_validation_gate", {}).get("status") == "pass"
    paper_simulation_allowed = False
    live_order_allowed = False
    status = (
        "production_line_registry_blocked"
        if registry_blockers or order_blockers or not strategies
        else "production_line_blocked_before_paper_or_live"
    )
    if independent_gate_passed and not unsafe_flags:
        status = "production_line_observing_manual_review_required"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "keep_research_and_forward_observation_only",
        "architecture_layer_contract": _architecture_layer_contract(),
        "production_line_order": STAGE_ORDER,
        "stage_labels": STAGE_LABELS,
        "registry_path": _relpath(registry_abs, root),
        "strategy_count": len(strategies),
        "primary_strategy_id": primary[0]["strategy_id"] if primary else None,
        "primary_evidence_chain": _primary_evidence_chain(primary[0] if primary else {}),
        "paper_simulation_allowed": paper_simulation_allowed,
        "live_order_allowed": live_order_allowed,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
        "strategies": strategies,
        "unsafe_flags": _dedupe(unsafe_flags),
        "blockers": blockers,
        "pipeline_progress": _pipeline_progress(
            status=status,
            strategies=strategies,
            blockers=blockers,
            remediation_ticket_closure=remediation_ticket_closure,
            development_plan_audit=development_plan_audit,
        ),
        "development_plan_audit": _development_plan_audit_summary(development_plan_audit),
        "remediation_tickets": _remediation_ticket_summary(blocker_taxonomy),
        "remediation_ticket_closure": _remediation_ticket_closure_summary(remediation_ticket_closure),
        "next_actions": _production_line_next_actions(development_plan_audit),
        "guardrails": {
            "strategy_expansion_before_pipeline_gate_allowed": False,
            "unregistered_strategy_promotion_allowed": False,
            "forward_observation_is_not_strategy_validation": True,
            "paper_or_live_unlocked_by_this_report": False,
            "paper_simulation_allowed": paper_simulation_allowed,
            "live_order_allowed": live_order_allowed,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
            "development_plan_audit": _relpath(development_plan_audit_path, root),
            "blocker_taxonomy": _relpath(blocker_taxonomy_path, root),
            "remediation_ticket_closure": _relpath(remediation_ticket_closure_path, root),
        },
    }
    _write_outputs(root, output, markdown_output, payload)
    return payload


def _build_strategy_line(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    strategy_id = str(entry.get("strategy_id", ""))
    reports = _load_source_reports(root, _mapping(entry.get("source_reports")))
    source_reports = {name: _relpath(path, root) for name, (path, _) in reports.items()}
    unsafe_flags = _unsafe_flags(strategy_id, reports)
    stages = [
        _stage_data_ingestion(reports),
        _stage_data_quality(reports),
        _stage_hypothesis(root, entry),
        _stage_standardized_backtest(reports),
        _stage_cost_liquidity_capacity(reports),
        _stage_walk_forward_parameter_stability(reports),
        _stage_strategy_validation_gate(reports),
        _stage_forward_observation(reports),
        _stage_manual_review(reports),
        _stage_paper_simulation(reports),
        _stage_live_readiness(reports),
        _stage_monitoring(reports),
    ]
    stage_blockers = []
    for stage in stages:
        stage_blockers.extend(str(item) for item in stage.get("blockers", []))
    guardrails = _mapping(entry.get("guardrails"))
    if guardrails.get("paper_ready") is True or guardrails.get("live_ready") is True:
        stage_blockers.append("us_equity_strategy_registry_forbidden_ready_flag")

    return {
        "strategy_id": strategy_id,
        "family": str(entry.get("family", "")),
        "registry_status": str(entry.get("status", "")),
        "current_stage": str(entry.get("current_stage", "")),
        "primary_candidate": bool(entry.get("primary_candidate", False)),
        "stage_summary": _stage_summary(stages),
        "stages": stages,
        "source_reports": source_reports,
        "unsafe_flags": unsafe_flags,
        "blockers": _dedupe(stage_blockers + unsafe_flags),
        "paper_ready": False,
        "live_ready": False,
        "live_order_allowed": False,
        "allowed_next_action": _allowed_next_action(stages),
    }


def _stage_data_ingestion(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    report = reports.get("data_ingestion", (Path(), {}))[1]
    ok = (
        str(report.get("status", "")).lower() == "pass"
        and int(_nested(report, "summary.available_symbol_count", default=0) or report.get("symbol_count", 0) or 0) >= 20
        and not _list(report.get("missing_symbols"))
        and not _list(report.get("blockers"))
    )
    return _stage(
        "data_ingestion",
        "pass" if ok else "blocked",
        evidence={
            "provider": report.get("provider"),
            "available_symbol_count": _nested(report, "summary.available_symbol_count", default=report.get("symbol_count")),
            "latest_common_date": _nested(report, "summary.latest_common_date"),
        },
        blockers=[] if ok else ["us_equity_data_ingestion_not_pass"],
    )


def _stage_data_quality(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    research = reports.get("research_backtest", (Path(), {}))[1]
    freshness = reports.get("data_freshness", (Path(), {}))[1]
    kline_quality = reports.get("etf_kline_quality_daily", (Path(), {}))[1]
    fred_macro_preflight = reports.get("fred_macro_preflight", (Path(), {}))[1]
    reconciliation = reports.get("data_source_reconciliation", (Path(), {}))[1]
    remediation = reports.get("data_lineage_remediation", (Path(), {}))[1]
    acquisition = reports.get("production_data_acquisition_plan", (Path(), {}))[1]
    pit_intake = reports.get("production_pit_intake_status", (Path(), {}))[1]
    pit_acceptance = reports.get("pit_bundle_acceptance", (Path(), {}))[1]
    macro_lag = reports.get("macro_release_lag_policy", (Path(), {}))[1]
    data = _mapping(research.get("data"))
    blockers = []
    promotion_clean = bool(data.get("promotion_clean", False))
    research_blockers = _list_of_str(research.get("blockers"))
    if not promotion_clean:
        blockers.append("us_equity_data_not_promotion_clean")
    for key in (
        "point_in_time_universe_not_confirmed",
        "corporate_action_event_source_missing",
        "membership_events_missing",
        "delisting_coverage_missing",
        "data_lineage_not_promotion_clean",
    ):
        if key in research_blockers:
            blockers.append(key)
    freshness_blockers = _list_of_str(freshness.get("blockers"))
    if freshness and str(freshness.get("status", "")) != "pass":
        blockers.extend(freshness_blockers or ["us_equity_data_freshness_not_pass"])
    kline_quality_status = str(kline_quality.get("status", ""))
    if not kline_quality:
        blockers.append("us_equity_etf_kline_quality_daily_missing")
    elif kline_quality_status == "blocked":
        blockers.extend(_list_of_str(kline_quality.get("blockers")) or ["us_equity_etf_kline_quality_daily_blocked"])
    fred_macro_status = str(fred_macro_preflight.get("status", ""))
    if not fred_macro_preflight:
        blockers.append("us_equity_fred_macro_preflight_missing")
    elif fred_macro_status == "fred_macro_preflight_blocked":
        blockers.extend(_list_of_str(fred_macro_preflight.get("blockers")) or ["us_equity_fred_macro_preflight_blocked"])
    reconciliation_status = str(reconciliation.get("status", ""))
    if not reconciliation:
        blockers.append("us_equity_data_source_reconciliation_missing")
    elif reconciliation_status == "blocked":
        blockers.extend(_list_of_str(reconciliation.get("blockers")) or ["us_equity_data_source_reconciliation_blocked"])
    if remediation and not acquisition:
        blockers.append("us_equity_production_data_acquisition_plan_missing")
    acquisition_table_status = [
        item for item in _list(acquisition.get("contract_status_by_table")) if isinstance(item, Mapping)
    ]
    if str(pit_intake.get("status", "")) != "production_pit_data_intake_ready":
        blockers.append("us_equity_production_pit_intake_not_ready")
    if str(pit_acceptance.get("status", "")) != "acceptance_ready_for_manual_config_apply":
        blockers.append("us_equity_pit_bundle_acceptance_not_ready")
    macro_lag_status = str(macro_lag.get("status", ""))
    if not macro_lag:
        blockers.append("us_equity_macro_release_lag_policy_missing")
    elif macro_lag_status == "blocked":
        blockers.extend(_list_of_str(macro_lag.get("blockers")) or ["us_equity_macro_release_lag_policy_blocked"])
    return _stage(
        "data_quality_pit_check",
        "pass" if not blockers and research else "blocked",
        evidence={
            "price_source": data.get("price_source"),
            "promotion_clean": promotion_clean,
            "missing_symbols": data.get("missing_symbols", []),
            "freshness_status": freshness.get("status"),
            "price_freshness_passed": _nested(freshness, "price_freshness.passed"),
            "macro_freshness_status": _nested(freshness, "macro_freshness.status"),
            "etf_kline_quality_status": kline_quality.get("status"),
            "etf_kline_quality_promotion_clean": kline_quality.get("promotion_clean"),
            "etf_kline_quality_latest_common_date": _nested(kline_quality, "summary.latest_common_date"),
            "etf_kline_quality_warn_symbol_count": _nested(kline_quality, "summary.warn_symbol_count"),
            "etf_kline_quality_blocked_symbol_count": _nested(kline_quality, "summary.blocked_symbol_count"),
            "fred_macro_preflight_status": fred_macro_preflight.get("status"),
            "fred_macro_current_session_api_key_present": fred_macro_preflight.get("current_session_api_key_present"),
            "fred_macro_latest_common_date": _nested(fred_macro_preflight, "import_report.latest_common_date"),
            "fred_macro_source_type": _nested(fred_macro_preflight, "import_report.source_type"),
            "fred_macro_warnings": _list_of_str(fred_macro_preflight.get("warnings")),
            "data_source_reconciliation_status": reconciliation.get("status"),
            "data_source_selected_price_source": reconciliation.get("selected_price_source"),
            "data_source_reconciled_symbol_count": _nested(
                reconciliation,
                "summary.available_symbol_count",
            ),
            "data_lineage_remediation_status": remediation.get("status"),
            "data_lineage_remediation_groups": [
                item.get("group_id")
                for item in _list(remediation.get("remediation_groups"))
                if isinstance(item, Mapping)
            ],
            "data_lineage_remediation_is_not_data_fix": _nested(
                remediation,
                "guardrails.remediation_report_is_not_data_fix",
            ),
            "production_data_acquisition_status": acquisition.get("status"),
            "production_data_acquisition_acceptable_provider_ids": _list_of_str(
                acquisition.get("acceptable_provider_ids")
            ),
            "production_data_acquisition_missing_contract_groups": _list_of_str(
                acquisition.get("missing_contract_groups")
            ),
            "production_data_acquisition_plan_is_not_provider_evidence": _nested(
                acquisition,
                "guardrails.data_acquisition_plan_is_not_provider_evidence",
            ),
            "production_data_acquisition_current_drop_status": _nested(
                acquisition,
                "current_drop_readiness.status",
            ),
            "production_data_acquisition_current_drop_ready_file_count": _nested(
                acquisition,
                "current_drop_readiness.ready_file_count",
            ),
            "production_data_acquisition_current_drop_required_file_count": _nested(
                acquisition,
                "current_drop_readiness.required_file_count",
            ),
            "production_data_acquisition_current_drop_first_blocker": _nested(
                acquisition,
                "current_drop_readiness.first_blocker",
            ),
            "production_data_acquisition_contract_ready_table_count": sum(
                1 for item in acquisition_table_status if item.get("status") == "ready"
            ),
            "production_data_acquisition_contract_blocked_table_count": sum(
                1 for item in acquisition_table_status if item.get("status") == "blocked"
            ),
            "production_pit_intake_status": pit_intake.get("status"),
            "production_pit_current_blocking_stage": pit_intake.get("current_blocking_stage"),
            "pit_bundle_acceptance_status": pit_acceptance.get("status"),
            "pit_bundle_acceptance_current_blocking_step": pit_acceptance.get("current_blocking_step"),
            "macro_release_lag_policy_status": macro_lag.get("status"),
            "macro_lag_days": _nested(macro_lag, "policy.macro_lag_days"),
            "macro_release_calendar_fields_present": _nested(
                macro_lag,
                "macro_source.release_calendar_fields_present",
            ),
            "macro_release_lag_research_proxy_only": _nested(
                macro_lag,
                "guardrails.research_lag_proxy_is_not_production_pit",
            ),
        },
        blockers=blockers or ([] if research else ["us_equity_research_report_missing"]),
    )


def _stage_hypothesis(root: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    strategy_card = str(entry.get("strategy_card", ""))
    card_exists = bool(strategy_card) and _resolve(root, Path(strategy_card)).exists()
    hypothesis = _mapping(entry.get("hypothesis"))
    ok = bool(hypothesis.get("alpha_sources")) and bool(hypothesis.get("risk_premia_explanation")) and (
        card_exists or not bool(entry.get("primary_candidate", False))
    )
    blockers = []
    if not hypothesis.get("alpha_sources"):
        blockers.append("us_equity_strategy_hypothesis_alpha_sources_missing")
    if not hypothesis.get("risk_premia_explanation"):
        blockers.append("us_equity_strategy_hypothesis_risk_premia_missing")
    if bool(entry.get("primary_candidate", False)) and not card_exists:
        blockers.append("us_equity_primary_strategy_card_missing")
    return _stage(
        "strategy_hypothesis_registration",
        "pass" if ok else "blocked",
        evidence={
            "strategy_card": strategy_card or None,
            "strategy_card_exists": card_exists,
            "alpha_sources": hypothesis.get("alpha_sources", []),
        },
        blockers=blockers,
    )


def _stage_standardized_backtest(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    research = reports.get("research_backtest", (Path(), {}))[1]
    schema_audit = reports.get("standard_report_schema_audit", (Path(), {}))[1]
    backtest = _mapping(research.get("backtest"))
    signal = _mapping(research.get("signal_integrity"))
    architecture = _mapping(research.get("architecture"))
    blockers = []
    if schema_audit and schema_audit.get("status") != "schema_audit_pass":
        blockers.append("us_equity_standard_report_schema_audit_not_pass")
    elif not schema_audit:
        blockers.append("us_equity_standard_report_schema_audit_missing")
    ok = (
        str(backtest.get("status", "")) == "complete"
        and _nested(research, "data.price_source") == "tiingo_eod"
        and signal.get("t_plus_1_execution") is True
        and signal.get("no_private_endpoint") is True
        and signal.get("no_order_endpoint") is True
        and architecture.get("separation_status") == "signals_portfolio_execution_decoupled"
        and not blockers
    )
    return _stage(
        "standardized_backtest",
        "pass" if ok else "blocked",
        evidence={
            "backtest_status": backtest.get("status"),
            "price_source": _nested(research, "data.price_source"),
            "t_plus_1_execution": signal.get("t_plus_1_execution"),
            "architecture": architecture,
            "metrics": _mapping(backtest.get("metrics")),
            "standard_report_schema_audit_status": schema_audit.get("status"),
            "standard_report_schema_passed_field_count": _nested(
                schema_audit,
                "coverage_summary.passed_field_count",
            ),
            "standard_report_schema_required_field_count": _nested(
                schema_audit,
                "coverage_summary.required_field_count",
            ),
        },
        blockers=[] if ok else blockers or ["us_equity_standardized_backtest_not_pass"],
    )


def _stage_cost_liquidity_capacity(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    validation = reports.get("top_candidate_validation", (Path(), {}))[1]
    costs = set(_mapping(validation.get("cost_stress")).keys())
    constrained = _mapping(validation.get("constrained_tradability"))
    decision = _mapping(validation.get("decision"))
    blockers = []
    missing_cost = sorted(REQUIRED_COST_STRESS - costs)
    if missing_cost:
        blockers.append("us_equity_cost_stress_levels_missing:" + ",".join(missing_cost))
    if constrained.get("passes_reference_aum_liquidity_check") is not True:
        blockers.append("us_equity_10k_to_100k_constrained_liquidity_check_not_pass")
    if decision.get("constrained_tradability_pass") is not True:
        blockers.append("us_equity_constrained_tradability_decision_not_pass")
    return _stage(
        "cost_liquidity_capacity_stress",
        "pass" if validation and not blockers else "blocked",
        evidence={
            "cost_stress_levels": sorted(costs),
            "reference_aum": constrained.get("reference_aum"),
            "passes_reference_aum_liquidity_check": constrained.get("passes_reference_aum_liquidity_check"),
            "decision": decision,
        },
        blockers=blockers or ([] if validation else ["us_equity_top_candidate_validation_report_missing"]),
    )


def _stage_walk_forward_parameter_stability(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    validation = reports.get("top_candidate_validation", (Path(), {}))[1]
    gate = reports.get("walk_forward_parameter_stability_gate", (Path(), {}))[1]
    walk = _mapping(validation.get("walk_forward"))
    fold_count = int(walk.get("fold_count", 0) or 0)
    aggregate = _mapping(walk.get("aggregate_oos"))
    blockers = []
    if fold_count < 5:
        blockers.append("us_equity_walk_forward_fold_count_lt_5")
    if not aggregate:
        blockers.append("us_equity_walk_forward_aggregate_oos_missing")
    gate_ok = (
        str(gate.get("status", "")) == "research_only_manual_review_required"
        and gate.get("fold_count", 0)
        and _nested(gate, "guardrails.not_strategy_validation_pass") is True
        and _nested(gate, "guardrails.paper_simulation_allowed") is False
        and _nested(gate, "guardrails.live_order_allowed") is False
    )
    if not gate_ok:
        blockers.append("us_equity_parameter_neighborhood_independent_gate_missing_or_blocked")
    return _stage(
        "walk_forward_parameter_stability",
        "manual_review_required" if validation and fold_count >= 5 and aggregate else "blocked",
        evidence={
            "fold_count": fold_count,
            "aggregate_oos": aggregate,
            "parameter_stability_status": gate.get("status"),
            "parameter_stability_alive_rate": gate.get("alive_rate"),
            "parameter_stability_candidate_count": gate.get("candidate_count"),
        },
        blockers=blockers,
    )


def _stage_strategy_validation_gate(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    path, gate = reports.get("strategy_validation_gate", (Path(), {}))
    gate_status = str(gate.get("status", ""))
    ok_statuses = {
        "strategy_validated",
        "strategy_backtest_validated",
        "research_validation_passed_manual_review_required",
        "validation_passed_for_forward_observation",
    }
    ok = (
        bool(gate)
        and gate_status in ok_statuses
        and gate.get("live_order_allowed") is not True
        and gate.get("paper_simulation_allowed") is not True
    )
    blockers: list[str]
    if ok:
        blockers = []
    elif not gate:
        blockers = ["dedicated_us_equity_strategy_validation_gate_missing"]
    elif gate_status == "blocked_data_quality":
        blockers = ["dedicated_us_equity_strategy_validation_gate_blocked_by_data_quality"]
    else:
        blockers = ["dedicated_us_equity_strategy_validation_gate_not_passed"]
    return _stage(
        "strategy_validation_gate",
        "pass" if ok else "blocked",
        evidence={
            "gate_report": str(path) if path else None,
            "gate_status": gate.get("status"),
            "gate_blockers": _list_of_str(gate.get("blockers")),
            "strategy_validation_gate_is_not_execution_permission": gate.get(
                "strategy_validation_gate_is_not_execution_permission"
            ),
        },
        blockers=blockers,
    )


def _stage_forward_observation(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    forward = reports.get("forward_observation", (Path(), {}))[1]
    evaluation = reports.get("forward_observation_evaluation", (Path(), {}))[1]
    daily_health = reports.get("forward_observation_daily_health", (Path(), {}))[1]
    guardrails = _mapping(forward.get("guardrails"))
    scope = _mapping(forward.get("observation_scope"))
    alpha = _mapping(forward.get("alpha_validation"))
    operational = _mapping(forward.get("operational_checks"))
    evaluation_guardrails = _mapping(evaluation.get("guardrails"))
    daily_health_guardrails = _mapping(daily_health.get("guardrails"))
    evaluation_ok = (
        str(evaluation.get("status", "")) in {"forward_observing", "forward_complete_for_manual_review"}
        and evaluation_guardrails.get("forward_evaluation_is_not_alpha_validation") is True
        and evaluation_guardrails.get("paper_or_live_unlock_allowed") is False
        and evaluation_guardrails.get("live_order_allowed") is False
    )
    daily_health_ok = (
        str(daily_health.get("status", "")) in {"daily_health_pass", "daily_health_observing_stale"}
        and daily_health_guardrails.get("daily_health_is_not_alpha_validation") is True
        and daily_health_guardrails.get("paper_or_live_unlock_allowed") is False
        and daily_health_guardrails.get("paper_simulation_allowed") is False
        and daily_health_guardrails.get("live_order_allowed") is False
        and daily_health_guardrails.get("private_endpoint_allowed") is False
        and daily_health_guardrails.get("order_endpoint_allowed") is False
    )
    ok = (
        str(forward.get("status", "")) == "PASS"
        and guardrails.get("simulated_only") is True
        and guardrails.get("forward_observation_is_not_alpha_validation") is True
        and guardrails.get("long_term_positive_expectancy_proven") is False
        and guardrails.get("paper_or_live_unlock_allowed") is False
        and guardrails.get("live_order_allowed") is False
        and guardrails.get("order_endpoint_used") is False
        and guardrails.get("private_endpoint_used") is False
        and scope.get("not_alpha_validation") is True
        and scope.get("cannot_prove_long_term_positive_expectancy") is True
        and scope.get("cannot_auto_unlock_paper_or_live") is True
        and alpha.get("alpha_validated") is False
        and alpha.get("long_term_positive_expectancy_proven") is False
        and str(operational.get("status", "")) == "PASS"
        and evaluation_ok
        and daily_health_ok
    )
    return _stage(
        "forward_observation",
        "observing" if ok else "not_started",
        evidence={
            "status": forward.get("status"),
            "ledger_root": forward.get("ledger_root"),
            "timestamp": _nested(forward, "portfolio_snapshot.timestamp"),
            "reconciliation_status": _nested(forward, "portfolio_snapshot.reconciliation_status"),
            "forward_observation_min_days": guardrails.get("forward_observation_min_days"),
            "scope": scope,
            "alpha_validation": alpha,
            "operational_checks_status": operational.get("status"),
            "evaluation_status": evaluation.get("status"),
            "evaluation_observation_days": _nested(evaluation, "metrics.observation_days"),
            "daily_health_status": daily_health.get("status"),
            "daily_health_generated_at": daily_health.get("daily_run_generated_at"),
            "daily_health_latest_observation_date": daily_health.get("latest_observation_date"),
            "daily_health_warnings": _list_of_str(daily_health.get("warnings")),
        },
        blockers=[] if ok else ["us_equity_forward_observation_not_running"],
    )


def _stage_manual_review(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    report = reports.get("manual_review", (Path(), {}))[1]
    guardrails = _mapping(report.get("guardrails"))
    checklist = _list_of_mappings(report.get("evidence_checklist"))
    milestones = _list_of_mappings(report.get("review_milestones"))
    safe = (
        str(report.get("status", "")) in {"manual_review_pending", "manual_review_ready"}
        and guardrails.get("paper_simulation_allowed") is False
        and guardrails.get("live_order_allowed") is False
    )
    return _stage(
        "manual_review",
        "manual_review_required" if safe else "not_started",
        evidence={
            "required": True,
            "packet_status": report.get("status"),
            "decision": report.get("decision"),
            "manual_approval_recorded": guardrails.get("manual_approval_recorded"),
            "evidence_checklist_passed_count": sum(1 for item in checklist if item.get("passed") is True),
            "evidence_checklist_required_count": len(checklist),
            "review_milestones": milestones,
            "paper_or_live_unlock_decision": _mapping(report.get("paper_or_live_unlock_decision")),
        },
        blockers=[] if safe else ["us_equity_manual_review_packet_missing_or_unsafe"],
    )


def _stage_paper_simulation(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    report = reports.get("paper_simulation_readiness", (Path(), {}))[1]
    guardrails = _mapping(report.get("guardrails"))
    safe_blocked = (
        str(report.get("status", "")) == "paper_simulation_blocked"
        and report.get("paper_runner_allowed") is False
        and guardrails.get("paper_simulation_allowed") is False
        and guardrails.get("live_order_allowed") is False
        and guardrails.get("order_endpoint_allowed") is False
    )
    return _stage(
        "paper_simulation",
        "blocked",
        evidence={
            "readiness_status": report.get("status"),
            "paper_runner_allowed": False,
            "paper_ledger_root": report.get("paper_ledger_root"),
            "decision": report.get("decision"),
        },
        blockers=[] if safe_blocked else ["us_equity_paper_simulation_readiness_missing_or_unsafe"],
    )


def _stage_live_readiness(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    report = reports.get("live_readiness", (Path(), {}))[1]
    guardrails = _mapping(report.get("guardrails"))
    has_constitution = bool(report)
    safe_blocked = (
        str(report.get("status", "")) == "live_readiness_blocked"
        and report.get("live_order_allowed") is False
        and report.get("real_order_submitted") is False
        and guardrails.get("live_order_allowed") is False
        and guardrails.get("order_endpoint_allowed") is False
        and guardrails.get("private_endpoint_allowed") is False
        and guardrails.get("manual_review_required") is True
    )
    return _stage(
        "small_capital_live_readiness",
        "blocked",
        evidence={
            "constitution_present": has_constitution,
            "live_readiness_status": report.get("status"),
            "decision": report.get("decision"),
            "account_capital_usd": report.get("account_capital_usd"),
            "max_live_principal_usd": report.get("max_live_principal_usd"),
            "live_order_allowed": False,
            "initial_live_leverage_recommended": False,
            "gate_checks": _mapping(report.get("gate_checks")),
        },
        blockers=[] if safe_blocked else ["us_equity_small_capital_live_readiness_constitution_missing_or_unsafe"],
    )


def _stage_monitoring(reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> dict[str, Any]:
    report = reports.get("monitoring_rules", (Path(), {}))[1]
    replay = reports.get("replay_readiness", (Path(), {}))[1]
    guardrails = _mapping(report.get("guardrails"))
    replay_guardrails = _mapping(replay.get("guardrails"))
    safe = (
        str(report.get("status", "")) == "monitoring_rules_defined"
        and str(replay.get("status", "")) == "replay_readiness_pass"
        and report.get("required_before_paper_or_live") is True
        and guardrails.get("paper_simulation_allowed") is False
        and guardrails.get("live_order_allowed") is False
        and replay_guardrails.get("paper_or_live_unlock_allowed") is False
        and replay_guardrails.get("live_order_allowed") is False
    )
    return _stage(
        "monitoring_attribution_retirement_iteration",
        "defined" if safe else "not_started",
        evidence={
            "monitoring_required_before_live": True,
            "rules_status": report.get("status"),
            "replay_readiness_status": replay.get("status"),
            "replay_latest_observation": replay.get("latest_observation"),
            "required_before_paper_or_live": report.get("required_before_paper_or_live"),
            "rule_sections": sorted(_mapping(report.get("rules")).keys()),
        },
        blockers=[] if safe else ["us_equity_monitoring_replay_and_retirement_rules_not_implemented"],
    )


def _stage(stage_id: str, status: str, *, evidence: Mapping[str, Any], blockers: list[str]) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "label": STAGE_LABELS[stage_id],
        "status": status,
        "evidence": _jsonable(evidence),
        "blockers": _dedupe(blockers),
    }


def _stage_summary(stages: list[Mapping[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for stage in stages:
        status = str(stage.get("status", ""))
        out[status] = out.get(status, 0) + 1
    return out


def _primary_evidence_chain(strategy: Mapping[str, Any]) -> dict[str, Any]:
    if not strategy:
        return {
            "status": "missing_primary_strategy",
            "strategy_id": None,
            "chain_complete_for_manual_review": False,
            "paper_or_live_unlock_allowed": False,
            "nodes": [],
            "blockers": ["us_equity_primary_strategy_missing"],
        }
    stages = {str(stage.get("stage_id")): stage for stage in _list_of_mappings(strategy.get("stages"))}
    hypothesis = stages.get("strategy_hypothesis_registration", {})
    validation = stages.get("strategy_validation_gate", {})
    forward = stages.get("forward_observation", {})
    manual = stages.get("manual_review", {})
    nodes = [
        {
            "node_id": "strategy_card",
            "status": hypothesis.get("status"),
            "evidence": {
                "strategy_card": _nested(_mapping(hypothesis), "evidence.strategy_card"),
                "strategy_card_exists": _nested(_mapping(hypothesis), "evidence.strategy_card_exists"),
                "alpha_sources": _nested(_mapping(hypothesis), "evidence.alpha_sources", default=[]),
            },
            "blockers": _list_of_str(hypothesis.get("blockers")),
        },
        {
            "node_id": "strategy_validation_gate",
            "status": validation.get("status"),
            "evidence": {
                "gate_status": _nested(_mapping(validation), "evidence.gate_status"),
                "gate_report": _nested(_mapping(validation), "evidence.gate_report"),
                "gate_is_not_execution_permission": _nested(
                    _mapping(validation),
                    "evidence.strategy_validation_gate_is_not_execution_permission",
                ),
            },
            "blockers": _list_of_str(validation.get("blockers")),
        },
        {
            "node_id": "forward_observation",
            "status": forward.get("status"),
            "evidence": {
                "evaluation_status": _nested(_mapping(forward), "evidence.evaluation_status"),
                "observation_days": _nested(_mapping(forward), "evidence.evaluation_observation_days"),
                "ledger_root": _nested(_mapping(forward), "evidence.ledger_root"),
                "not_alpha_validation": _nested(_mapping(forward), "evidence.scope.not_alpha_validation"),
            },
            "blockers": _list_of_str(forward.get("blockers")),
        },
        {
            "node_id": "manual_review",
            "status": manual.get("status"),
            "evidence": {
                "packet_status": _nested(_mapping(manual), "evidence.packet_status"),
                "manual_approval_recorded": _nested(_mapping(manual), "evidence.manual_approval_recorded"),
                "required_count": _nested(_mapping(manual), "evidence.evidence_checklist_required_count"),
                "passed_count": _nested(_mapping(manual), "evidence.evidence_checklist_passed_count"),
            },
            "blockers": _list_of_str(manual.get("blockers")),
        },
    ]
    blockers = _dedupe([item for node in nodes for item in _list_of_str(node.get("blockers"))])
    manual_ready = manual.get("status") == "manual_review_required" and not _list_of_str(manual.get("blockers"))
    validation_passed = validation.get("status") == "pass"
    return {
        "status": "manual_review_required" if manual_ready and validation_passed else "evidence_chain_incomplete",
        "strategy_id": strategy.get("strategy_id"),
        "chain_complete_for_manual_review": manual_ready and validation_passed,
        "paper_or_live_unlock_allowed": False,
        "nodes": nodes,
        "blockers": blockers,
    }


def _development_plan_audit_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    if not report:
        return {
            "status": "missing",
            "summary": {},
            "blockers": ["us_equity_development_plan_audit_report_missing"],
        }
    return {
        "status": report.get("status"),
        "summary": _mapping(report.get("summary")),
        "blockers": _list_of_str(report.get("blockers"))[:12],
    }


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


def _remediation_ticket_closure_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    if not report:
        return {
            "status": "missing",
            "ticket_count": 0,
            "open_count": 0,
            "closed_count": 0,
            "missing_source_count": 0,
            "open_ticket_ids": [],
        }
    checks = [item for item in _list(report.get("closure_checks")) if isinstance(item, Mapping)]
    return {
        "status": str(report.get("status", "")),
        "ticket_count": int(report.get("ticket_count", 0) or 0),
        "open_count": int(report.get("open_count", 0) or 0),
        "closed_count": int(report.get("closed_count", 0) or 0),
        "missing_source_count": len(_list(report.get("missing_sources"))),
        "open_ticket_ids": [str(item.get("ticket_id", "")) for item in checks if item.get("closed") is not True],
    }


def _pipeline_progress(
    *,
    status: str,
    strategies: list[Mapping[str, Any]],
    blockers: list[str],
    remediation_ticket_closure: Mapping[str, Any],
    development_plan_audit: Mapping[str, Any],
) -> dict[str, Any]:
    stage_counts: dict[str, int] = {}
    primary_stage_counts: dict[str, int] = {}
    primary_strategy_id = None
    for strategy in strategies:
        if strategy.get("primary_candidate") is True:
            primary_strategy_id = str(strategy.get("strategy_id", ""))
        for stage in _list(strategy.get("stages")):
            if not isinstance(stage, Mapping):
                continue
            stage_status = str(stage.get("status", "unknown"))
            stage_counts[stage_status] = stage_counts.get(stage_status, 0) + 1
            if strategy.get("primary_candidate") is True:
                primary_stage_counts[stage_status] = primary_stage_counts.get(stage_status, 0) + 1
    closure = _remediation_ticket_closure_summary(remediation_ticket_closure)
    development_summary = _mapping(development_plan_audit.get("summary"))
    next_actions = _production_line_next_actions(development_plan_audit)
    return {
        "status": status,
        "strategy_count": len(strategies),
        "primary_strategy_id": primary_strategy_id,
        "stage_counts": dict(sorted(stage_counts.items())),
        "primary_stage_counts": dict(sorted(primary_stage_counts.items())),
        "development_plan_summary": {
            "phase_count": int(development_summary.get("phase_count", 0) or 0),
            "complete_count": int(development_summary.get("complete_count", 0) or 0),
            "blocked_count": int(development_summary.get("blocked_count", 0) or 0),
            "observing_count": int(development_summary.get("observing_count", 0) or 0),
            "action_required_count": int(development_summary.get("action_required_count", 0) or 0),
        },
        "development_phase_progress": _development_phase_progress(development_plan_audit),
        "remediation_closure": {
            "status": closure["status"],
            "ticket_count": closure["ticket_count"],
            "open_count": closure["open_count"],
            "closed_count": closure["closed_count"],
            "missing_source_count": closure["missing_source_count"],
            "open_ticket_ids": closure["open_ticket_ids"],
        },
        "blocker_count": len(blockers),
        "blocker_sample": blockers[:8],
        "next_action": next_actions[0] if next_actions else "",
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }


def _development_phase_progress(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    phases = []
    for item in _list(report.get("phase_checks")):
        if not isinstance(item, Mapping):
            continue
        blockers = _list_of_str(item.get("blockers"))
        metrics = _mapping(item.get("metrics"))
        phases.append(
            {
                "phase_id": str(item.get("phase_id", "")),
                "status": str(item.get("status", "")),
                "first_blocker": blockers[0] if blockers else "",
                "blocker_count": len(blockers),
                "evidence_count": len(_list(item.get("evidence"))),
                "observation_days": _safe_int(metrics.get("observation_days")),
                "minimum_complete_days": _safe_int(metrics.get("minimum_complete_days")),
                "next_step_id": str(
                    metrics.get("vendor_drop_operator_progress_next_step_id")
                    or metrics.get("operator_next_step_id")
                    or ""
                ),
            }
        )
    return phases


def _production_line_next_actions(development_plan_audit: Mapping[str, Any]) -> list[str]:
    status = str(development_plan_audit.get("status", ""))
    if status == "development_plan_blocked_by_production_pit_data":
        return [
            "acquire_or_build_production_pit_data_bundle",
            "rerun_provider_verification_and_data_lineage_gates",
            "continue_forward_observation_without_order_endpoints",
            "keep_paper_and_live_locked_until_manual_review",
        ]
    return [
        "build_or_refresh_us_equity_development_plan_audit",
        "continue_forward_observation_without_order_endpoints",
        "complete_point_in_time_universe_and_adjustment_reproducibility_checks",
        "write_manual_review_packet_before_any_paper_simulation",
    ]


def _allowed_next_action(stages: list[Mapping[str, Any]]) -> str:
    data_quality = next((stage for stage in stages if stage.get("stage_id") == "data_quality_pit_check"), {})
    gate = next((stage for stage in stages if stage.get("stage_id") == "strategy_validation_gate"), {})
    forward = next((stage for stage in stages if stage.get("stage_id") == "forward_observation"), {})
    if gate.get("status") != "pass":
        gate_blockers = set(_list_of_str(gate.get("blockers")))
        if "dedicated_us_equity_strategy_validation_gate_blocked_by_data_quality" in gate_blockers:
            evidence = _mapping(data_quality.get("evidence"))
            if evidence.get("production_data_acquisition_status") == "production_data_acquisition_required":
                return "acquire_production_pit_data_bundle_and_continue_forward_observation"
            return "repair_data_lineage_and_continue_forward_observation"
        if "dedicated_us_equity_strategy_validation_gate_missing" in gate_blockers:
            return "build_independent_strategy_validation_gate"
        if forward.get("status") == "observing":
            return "continue_forward_observation_and_repair_strategy_validation_evidence"
        return "build_missing_upstream_evidence"
    return "manual_review_required_before_paper_simulation"


def _load_source_reports(root: Path, reports: Mapping[str, Any]) -> dict[str, tuple[Path, Mapping[str, Any]]]:
    out: dict[str, tuple[Path, Mapping[str, Any]]] = {}
    for name, value in reports.items():
        path = _resolve(root, Path(str(value)))
        out[str(name)] = (path, _read_json(path))
    return out


def _unsafe_flags(strategy_id: str, reports: Mapping[str, tuple[Path, Mapping[str, Any]]]) -> list[str]:
    out = []
    for report_name, (_path, payload) in reports.items():
        for path, value in _walk(payload):
            key = path.split(".")[-1]
            if key in UNSAFE_TRUE_KEYS and value is True:
                if key == "paper_ready":
                    out.append(f"{strategy_id}.{report_name}.{path}=true")
                elif key == "live_ready":
                    out.append(f"{strategy_id}.{report_name}.{path}=true")
                else:
                    out.append(f"{strategy_id}.{report_name}.{path}=true")
    return _dedupe(out)


def _registry_blockers(registry: Mapping[str, Any]) -> list[str]:
    blockers = []
    if registry.get("schema_version") != "us_equity_strategy_registry_v1":
        blockers.append("us_equity_strategy_registry_schema_version_invalid")
    if registry.get("asset") != "us_equity":
        blockers.append("us_equity_strategy_registry_asset_invalid")
    policy = _mapping(registry.get("policy"))
    for key in ("private_endpoint_allowed", "order_endpoint_allowed", "live_order_allowed"):
        if policy.get(key) is True:
            blockers.append(f"us_equity_strategy_registry_forbidden_policy_{key}")
    if not _list(registry.get("strategies")):
        blockers.append("us_equity_strategy_registry_no_strategies")
    return blockers


def _blocked_missing_registry(
    root: Path,
    registry_path: Path,
    output: Path,
    markdown_output: Path,
    generated: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "status": "production_line_registry_missing",
        "decision": "do_not_expand_or_promote_strategies",
        "architecture_layer_contract": _architecture_layer_contract(),
        "production_line_order": STAGE_ORDER,
        "registry_path": str(registry_path),
        "strategy_count": 0,
        "primary_strategy_id": None,
        "primary_evidence_chain": _primary_evidence_chain({}),
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
        "strategies": [],
        "unsafe_flags": [],
        "blockers": ["us_equity_strategy_registry_missing"],
        "pipeline_progress": {
            "status": "production_line_registry_missing",
            "strategy_count": 0,
            "primary_strategy_id": None,
            "stage_counts": {},
            "primary_stage_counts": {},
            "development_plan_summary": {
                "phase_count": 0,
                "complete_count": 0,
                "blocked_count": 0,
                "observing_count": 0,
                "action_required_count": 0,
            },
            "development_phase_progress": [],
            "remediation_closure": _remediation_ticket_closure_summary({}),
            "blocker_count": 1,
            "blocker_sample": ["us_equity_strategy_registry_missing"],
            "next_action": "restore_or_create_us_equity_strategy_registry",
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
        },
        "development_plan_audit": {
            "status": "missing",
            "summary": {},
            "blockers": ["us_equity_development_plan_audit_report_missing"],
        },
        "remediation_tickets": _remediation_ticket_summary({}),
        "remediation_ticket_closure": _remediation_ticket_closure_summary({}),
        "next_actions": [
            "restore_or_create_us_equity_strategy_registry",
            "rebuild_development_plan_audit_and_blocker_taxonomy",
        ],
        "guardrails": {
            "strategy_expansion_before_pipeline_gate_allowed": False,
            "unregistered_strategy_promotion_allowed": False,
            "paper_or_live_unlocked_by_this_report": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }


def _architecture_layer_contract() -> dict[str, Any]:
    return {
        "status": "defined_fail_closed",
        "paper_or_live_unlock_allowed": False,
        "allowed_flow": [
            "data",
            "signal",
            "portfolio",
            "risk",
            "order_intent",
            "simulated_fill",
            "ledger",
            "report",
        ],
        "layers": [
            {
                "layer_id": "strategy",
                "module_roots": ["quant_us.signals", "quant_us.strategies", "quant_us.research"],
                "allowed_outputs": ["Signal", "Forecast", "TargetPosition"],
                "forbidden_dependencies": [
                    "broker adapter",
                    "private endpoint",
                    "order endpoint",
                    "OMS",
                    "live credentials",
                ],
                "contract": "Strategy code may express alpha only; it cannot create or submit broker orders.",
            },
            {
                "layer_id": "portfolio",
                "module_roots": ["quant_us.portfolio"],
                "allowed_inputs": ["Forecast", "Signal"],
                "allowed_outputs": ["TargetPosition"],
                "required_controls": [
                    "volatility",
                    "sector/style exposure",
                    "turnover",
                    "liquidity",
                    "cost stress",
                ],
                "contract": "Portfolio construction converts forecasts into target positions before risk review.",
            },
            {
                "layer_id": "risk",
                "module_roots": ["quant_us.risk"],
                "allowed_inputs": ["TargetPosition"],
                "allowed_outputs": ["RiskDecision"],
                "required_position": "between target position and order intent",
                "contract": "Risk is the only layer allowed to approve or block target positions before order intent.",
            },
            {
                "layer_id": "backtest",
                "module_roots": ["quant_us.backtest"],
                "required_sequence": [
                    "data",
                    "signal",
                    "portfolio",
                    "risk",
                    "order_intent",
                    "simulated_fill",
                    "ledger",
                    "report",
                ],
                "pnl_source": "fills_positions_cash_ledger",
                "contract": "Backtests must be event-driven and derive PnL from ledger replay, not price-only curves.",
            },
            {
                "layer_id": "execution",
                "module_roots": ["quant_us.execution", "quant_us.live"],
                "allowed_inputs": ["risk_approved_order_intent"],
                "oms_responsibilities": [
                    "order lifecycle",
                    "idempotency",
                    "cancel",
                    "reject",
                    "partial fill",
                    "reconciliation",
                ],
                "contract": "Execution accepts only risk-approved intents; OMS owns state transitions and reconciliation.",
            },
            {
                "layer_id": "entrypoints",
                "module_roots": ["scripts"],
                "allowed_responsibilities": ["report building", "orchestration", "artifact writing"],
                "forbidden_responsibilities": ["core strategy rules", "broker decision logic", "promotion shortcuts"],
                "contract": "Scripts are entrypoints only; durable business rules must move into quant_us domain/service modules.",
            },
        ],
        "guardrails": {
            "strategy_broker_adapter_allowed": False,
            "portfolio_can_bypass_risk": False,
            "risk_decision_required_before_order_intent": True,
            "backtest_price_only_pnl_allowed": False,
            "execution_accepts_unapproved_intents": False,
            "scripts_own_core_business_rules": False,
        },
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    progress = _mapping(payload.get("pipeline_progress"))
    lines = [
        "# US Equity 策略生产线状态报告",
        "",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- status: `{payload.get('status')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- primary_strategy_id: `{payload.get('primary_strategy_id')}`",
        f"- paper_simulation_allowed: `{payload.get('paper_simulation_allowed')}`",
        f"- live_order_allowed: `{payload.get('live_order_allowed')}`",
        f"- pipeline_next_action: `{progress.get('next_action', '')}`",
        f"- pipeline_blocker_count: `{progress.get('blocker_count', 0)}`",
        "",
        "## 生产线顺序",
        "",
    ]
    for index, stage_id in enumerate(_list_of_str(payload.get("production_line_order")), start=1):
        lines.append(f"{index}. `{stage_id}` - {STAGE_LABELS.get(stage_id, stage_id)}")
    lines.extend(["", "## 当前策略状态", ""])
    for strategy in _list(payload.get("strategies")):
        if not isinstance(strategy, Mapping):
            continue
        lines.append(f"### `{strategy.get('strategy_id')}`")
        lines.append("")
        lines.append(f"- family: `{strategy.get('family')}`")
        lines.append(f"- registry_status: `{strategy.get('registry_status')}`")
        lines.append(f"- allowed_next_action: `{strategy.get('allowed_next_action')}`")
        lines.append(f"- paper_ready: `{strategy.get('paper_ready')}`")
        lines.append(f"- live_ready: `{strategy.get('live_ready')}`")
        lines.append("")
        lines.append("| Stage | Status | Main blocker |")
        lines.append("|---|---:|---|")
        for stage in _list(strategy.get("stages")):
            if not isinstance(stage, Mapping):
                continue
            blockers = _list_of_str(stage.get("blockers"))
            lines.append(
                f"| `{stage.get('stage_id')}` | `{stage.get('status')}` | {blockers[0] if blockers else ''} |"
            )
        lines.append("")
    lines.extend(["## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    if blockers:
        lines.extend(f"- `{item}`" for item in blockers)
    else:
        lines.append("- None")
    remediation = _mapping(payload.get("remediation_tickets"))
    remediation_closure = _mapping(payload.get("remediation_ticket_closure"))
    lines.extend(["", "## Remediation Tickets", ""])
    lines.append(
        f"- closure status: `{remediation_closure.get('status')}`，open=`{remediation_closure.get('open_count')}`，closed=`{remediation_closure.get('closed_count')}`"
    )
    tickets = [item for item in _list(remediation.get("tickets")) if isinstance(item, Mapping)]
    if tickets:
        for ticket in tickets:
            lines.append(
                f"- `{ticket.get('ticket_id')}`：`{ticket.get('status')}`，owner=`{ticket.get('owner')}`，dependency=`{ticket.get('dependency_type')}`"
            )
    else:
        lines.append("- None")
    architecture = _mapping(payload.get("architecture_layer_contract"))
    architecture_layers = [item for item in _list(architecture.get("layers")) if isinstance(item, Mapping)]
    lines.extend(["", "## Architecture Layer Contract", ""])
    lines.append(f"- status: `{architecture.get('status')}`")
    lines.append(f"- allowed_flow: `{' -> '.join(_list_of_str(architecture.get('allowed_flow')))}`")
    lines.append(f"- paper_or_live_unlock_allowed: `{architecture.get('paper_or_live_unlock_allowed')}`")
    if architecture_layers:
        lines.append("")
        lines.append("| Layer | Module roots | Contract |")
        lines.append("|---|---|---|")
        for layer in architecture_layers:
            lines.append(
                f"| `{layer.get('layer_id')}` | `{', '.join(_list_of_str(layer.get('module_roots')))}` | {layer.get('contract', '')} |"
            )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Forward observation is operational-quality evidence only.",
            "- Forward observation is not Alpha validation and cannot prove long-term positive expectancy.",
            "- This report does not unlock paper simulation or live orders.",
            "- New strategies may be registered as hypotheses, but should not be optimized or promoted before the shared production line gate is implemented.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_outputs(root: Path, output: Path, markdown_output: Path, payload: Mapping[str, Any]) -> None:
    output_abs = _resolve(root, output)
    markdown_abs = _resolve(root, markdown_output)
    output_abs.parent.mkdir(parents=True, exist_ok=True)
    output_abs.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_abs.parent.mkdir(parents=True, exist_ok=True)
    markdown_abs.write_text(_markdown(payload), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, check=False, capture_output=True, text=True)
    except OSError:
        return "unknown"
    value = result.stdout.strip()
    return value or "unknown"


def _nested(payload: Mapping[str, Any], dotted: str, default: Any = None) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in _list(value) if isinstance(item, Mapping)]


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


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


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value
