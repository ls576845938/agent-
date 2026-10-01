#!/usr/bin/env python3
"""Audit implementation progress against the US Equity development plan."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "us_equity_development_plan_audit_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 开发规划执行审计.md")
PLAN_PATH = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 美股系统开发规划.md")

REPORTS = {
    "strategy_registry": Path("configs/strategies/us_equity_strategy_registry.json"),
    "daily_production_line": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"),
    "production_line": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json"),
    "strategy_validation_gate": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"),
    "forward_roll": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json"),
    "forward_evaluation": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json"),
    "small_account_preflight": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"),
    "live_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json"),
    "monitoring_rules": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json"),
    "replay_readiness": Path("artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json"),
    "blocker_taxonomy": Path("artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"),
    "schema_audit": Path("artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json"),
    "production_data_acquisition": Path("artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json"),
    "production_bundle_intake_packet": Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json"),
    "manual_vendor_drop_package": Path("artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json"),
    "production_bundle_activation": Path("artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json"),
    "pit_bundle_acceptance": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json"),
    "pit_operator_handoff": Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json"),
    "vendor_drop_operator_progress": Path("artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_operator_progress_report.json"),
    "data_freshness": Path("artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json"),
    "kline_quality": Path("artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json"),
    "fred_preflight": Path("artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json"),
    "macro_lag_policy": Path("artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json"),
    "validation_state": Path("data/forward_observation/us_etf_rotation_v1/validation_state.json"),
}


def build_us_equity_development_plan_audit(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    paths = {name: _resolve(root, path) for name, path in REPORTS.items()}
    reports = {name: _read_json(path) for name, path in paths.items()}
    plan_exists = _resolve(root, PLAN_PATH).exists()

    checks = _phase_checks(root, paths, reports, plan_exists)
    blockers = []
    for check in checks:
        blockers.extend(check["blockers"])
    unsafe = _unsafe_flags(reports)
    blockers.extend(f"unsafe_flag:{item}" for item in unsafe)
    status = (
        "development_plan_complete"
        if checks and all(item["status"] == "complete" for item in checks) and not blockers
        else "development_plan_in_progress"
    )
    if _nested(reports["production_data_acquisition"], "status") == "production_data_acquisition_required":
        status = "development_plan_blocked_by_production_pit_data"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "us_equity",
        "status": status,
        "decision": "continue_building_production_line_do_not_unlock_live",
        "plan_path": _relpath(_resolve(root, PLAN_PATH), root),
        "plan_exists": plan_exists,
        "phase_checks": checks,
        "summary": {
            "phase_count": len(checks),
            "complete_count": sum(1 for item in checks if item["status"] == "complete"),
            "observing_count": sum(1 for item in checks if item["status"] == "observing"),
            "blocked_count": sum(1 for item in checks if item["status"].startswith("blocked")),
            "action_required_count": sum(1 for item in checks if item["status"] == "action_required"),
        },
        "blockers": _dedupe(blockers),
        "unsafe_flags": unsafe,
        "source_reports": {name: _relpath(path, root) for name, path in paths.items()},
        "guardrails": {
            "audit_only": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _phase_checks(root: Path, paths: Mapping[str, Path], reports: Mapping[str, Mapping[str, Any]], plan_exists: bool) -> list[dict[str, Any]]:
    registry = reports["strategy_registry"]
    daily = reports["daily_production_line"]
    production = reports["production_line"]
    validation = reports["strategy_validation_gate"]
    forward_eval = reports["forward_evaluation"]
    live = reports["live_readiness"]
    monitoring = reports["monitoring_rules"]
    replay = reports["replay_readiness"]
    blocker_taxonomy = reports["blocker_taxonomy"]
    small_account = reports["small_account_preflight"]
    acquisition = reports["production_data_acquisition"]
    intake = reports["production_bundle_intake_packet"]
    manual_package = reports["manual_vendor_drop_package"]
    activation = reports["production_bundle_activation"]
    acceptance = reports["pit_bundle_acceptance"]
    handoff = reports["pit_operator_handoff"]
    operator_progress = reports["vendor_drop_operator_progress"]
    state = reports["validation_state"]
    primary = _primary_strategy(registry)
    phase0_ok = bool(
        primary.get("strategy_id") == "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x"
        and primary.get("status") == "forward_observation_only"
        and paths["forward_roll"].exists()
        and paths["validation_state"].exists()
        and daily.get("status") == "PASS"
    )
    phase0_blockers = _dedupe(
        ([] if primary else ["primary_strategy_missing"])
        + ([] if daily.get("status") == "PASS" else ["daily_production_line_not_pass"])
    )
    return [
        _check(
            "phase_0_candidate_freeze",
            "冻结当前主候选定义",
            "complete" if phase0_ok else "action_required",
            [
                "configs/strategies/us_equity_strategy_registry.json",
                "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json",
                "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json",
                "data/forward_observation/us_etf_rotation_v1/validation_state.json",
            ],
            phase0_blockers,
            metrics={
                "daily_production_line_status": daily.get("status"),
                "forward_daily_health_status": _nested(daily, "forward_observation.daily_health_status"),
            },
        ),
        _check(
            "phase_1_data_lineage_hardening",
            "数据链路硬化与 PIT 生产数据包",
            "blocked_external_data"
            if acquisition.get("status") == "production_data_acquisition_required"
            else ("complete" if acquisition.get("status") == "production_data_acquisition_ready_for_preflight" else "action_required"),
            [
                "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
                "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json",
                "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json",
                "artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_operator_progress_report.json",
            ],
            _dedupe(
                _list_of_str(acquisition.get("blockers"))
                + _list_of_str(intake.get("blockers"))
                + _manual_vendor_drop_package_blockers(manual_package)
                + _list_of_str(activation.get("blockers"))
                + _list_of_str(acceptance.get("blockers"))
                + _list_of_str(handoff.get("blockers"))
            )[:12],
            metrics={
                "intake_packet_status": intake.get("status"),
                "manual_vendor_drop_package_status": manual_package.get("status"),
                "manual_vendor_drop_template_count": len(_list(manual_package.get("template_files"))),
                "manual_vendor_drop_field_count": manual_package.get("field_count"),
                "activation_status": activation.get("status"),
                "activation_candidate_config_path": activation.get("candidate_config_path"),
                "pit_bundle_acceptance_status": acceptance.get("status"),
                "pit_bundle_acceptance_current_blocking_step": acceptance.get("current_blocking_step"),
                "pit_bundle_acceptance_source_dir": acceptance.get("source_dir"),
                "pit_operator_handoff_status": handoff.get("status"),
                "pit_operator_handoff_blocking_stage": handoff.get("current_blocking_stage"),
                "pit_operator_handoff_markdown": _nested(handoff, "outputs.markdown"),
                "vendor_drop_operator_progress_status": operator_progress.get("status"),
                "vendor_drop_operator_progress_completed_count": operator_progress.get("completed_count"),
                "vendor_drop_operator_progress_blocked_count": operator_progress.get("blocked_count"),
                "vendor_drop_operator_progress_pending_count": operator_progress.get("pending_count"),
                "vendor_drop_operator_progress_step_count": operator_progress.get("step_count"),
                "vendor_drop_operator_progress_next_step_id": operator_progress.get("next_step_id"),
                "vendor_drop_operator_progress_next_action": operator_progress.get("next_action"),
                "operator_next_actions": _operator_next_actions(handoff, acceptance),
            },
        ),
        _check(
            "phase_2_strategy_validation_gate",
            "独立策略验证门槛",
            "blocked_data_quality" if validation.get("status") == "blocked_data_quality" else _status_complete(validation.get("status"), "validation_passed_for_forward_observation"),
            ["artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json"],
            _list_of_str(validation.get("blockers")),
        ),
        _check(
            "phase_3_forward_observation_evaluation",
            "Forward observation 30/60/90 日评估",
            "observing" if forward_eval.get("status") == "forward_observing" else _status_complete(forward_eval.get("status"), "forward_complete_for_manual_review"),
            [
                "scripts/run_us_etf_rotation_forward_observation.py",
                "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
            ],
            [] if forward_eval else ["forward_observation_evaluation_missing"],
            metrics={
                "observation_days": _nested(forward_eval, "metrics.observation_days", 0),
                "minimum_complete_days": forward_eval.get("minimum_complete_days", 30),
                "days_completed": state.get("days_completed"),
            },
        ),
        _check(
            "phase_4_small_account_constraints",
            "组合构建与 10,000 美元小账户约束",
            "complete" if not _small_account_constraint_blockers(small_account) else "action_required",
            ["artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json"],
            _small_account_constraint_blockers(small_account),
            metrics=_small_account_constraint_metrics(small_account),
        ),
        _check(
            "phase_5_strategy_registry",
            "策略池注册表",
            "complete" if _strategy_registry_complete(registry) else "action_required",
            ["configs/strategies/us_equity_strategy_registry.json"],
            [] if _strategy_registry_complete(registry) else ["strategy_registry_incomplete"],
            metrics={"strategy_count": len(_list(registry.get("strategies")))},
        ),
        _check(
            "phase_6_live_readiness",
            "纸面模拟与实盘前风控门禁",
            "blocked_manual_review" if live.get("status") == "live_readiness_blocked" else _status_complete(live.get("status"), "live_readiness_ready_for_manual_review"),
            [
                "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json",
                "../学习资料/量化交易业务闭环/系统评估/US Equity 实盘前风控宪法.md",
            ],
            _list_of_str(live.get("blockers"))[:12],
            metrics={
                "live_readiness_status": live.get("status"),
                "execution_readiness_status": _nested(live, "execution_readiness.status"),
                "execution_readiness_drill_count": _nested(live, "execution_readiness.drill_count"),
                "execution_readiness_proven_count": _nested(live, "execution_readiness.proven_count"),
                "execution_readiness_blocked_count": _nested(live, "execution_readiness.blocked_count"),
                "live_order_allowed": live.get("live_order_allowed"),
                "real_order_submitted": live.get("real_order_submitted"),
            },
        ),
        _check(
            "monitoring_attribution_retirement",
            "监控、归因、停用与 replay 审计",
            "complete" if _monitoring_rules_complete(monitoring) and replay.get("status") == "replay_readiness_pass" else "action_required",
            [
                "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
                "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json",
            ],
            []
            if _monitoring_rules_complete(monitoring) and replay.get("status") == "replay_readiness_pass"
            else ["monitoring_replay_incident_contract_incomplete"],
            metrics={
                "monitor_count": monitoring.get("monitor_count"),
                "status": monitoring.get("status"),
                "replay_readiness_status": replay.get("status"),
            },
        ),
        _check(
            "blocker_taxonomy_governance",
            "阻断项分层治理",
            "complete" if _blocker_taxonomy_complete(blocker_taxonomy) else "action_required",
            ["artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json"],
            [] if _blocker_taxonomy_complete(blocker_taxonomy) else ["blocker_taxonomy_report_missing_or_incomplete"],
            metrics={
                "status": blocker_taxonomy.get("status"),
                "total_blockers": _nested(blocker_taxonomy, "summary.total_blockers"),
                "categorized_blockers": _nested(blocker_taxonomy, "summary.categorized_blockers"),
                "uncategorized_blockers": _nested(blocker_taxonomy, "summary.uncategorized_blockers"),
                "waiting_category_count": _nested(blocker_taxonomy, "summary.waiting_category_count"),
                "actionable_category_count": _nested(blocker_taxonomy, "summary.actionable_category_count"),
                "unsafe_flag_blocker_count": _category_count(blocker_taxonomy, "unsafe_flags"),
            },
        ),
        _check(
            "standard_report_schema",
            "统一报告 Schema",
            "complete" if reports["schema_audit"].get("status") == "schema_audit_pass" else "action_required",
            ["artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json"],
            _list_of_str(reports["schema_audit"].get("blockers")),
        ),
        _check(
            "production_line_summary",
            "生产线总门禁",
            "blocked_external_data"
            if production.get("status") == "production_line_blocked_before_paper_or_live"
            and _nested(primary, "source_reports.production_data_acquisition_plan")
            else _status_complete(production.get("status"), "production_line_manual_review_required"),
            ["artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json"],
            _list_of_str(production.get("blockers"))[:12],
        ),
        _check(
            "plan_document",
            "开发规划文档",
            "complete" if plan_exists else "action_required",
            ["../学习资料/量化交易业务闭环/系统评估/US Equity 美股系统开发规划.md"],
            [] if plan_exists else ["development_plan_markdown_missing"],
        ),
    ]


def _check(phase_id: str, title: str, status: str, evidence: list[str], blockers: list[str], metrics: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "phase_id": phase_id,
        "title": title,
        "status": status,
        "evidence": evidence,
        "blockers": _dedupe(blockers),
        "metrics": dict(metrics or {}),
    }


def _operator_next_actions(handoff: Mapping[str, Any], acceptance: Mapping[str, Any]) -> list[str]:
    handoff_actions = _list_of_str(handoff.get("operator_next_actions"))
    if handoff_actions:
        return handoff_actions
    for step in _list(acceptance.get("steps")):
        if not isinstance(step, Mapping):
            continue
        payload = _mapping(step.get("payload"))
        actions = _list_of_str(payload.get("operator_next_actions"))
        if actions:
            return actions
    return [
        "Run python scripts/run_us_equity_pit_bundle_acceptance.py after placing the licensed CSV drop.",
    ]


def _primary_strategy(registry: Mapping[str, Any]) -> dict[str, Any]:
    for item in _list(registry.get("strategies")):
        if isinstance(item, Mapping) and item.get("primary_candidate") is True:
            return dict(item)
    return {}


def _strategy_registry_complete(registry: Mapping[str, Any]) -> bool:
    strategies = [item for item in _list(registry.get("strategies")) if isinstance(item, Mapping)]
    required_families = {
        "us_etf_macro_momentum_rotation",
        "dual_momentum",
        "absolute_momentum",
        "topn_etf_rotation",
        "regime_overlay",
        "151_trading_strategies_migration",
    }
    families = {str(item.get("family", "")) for item in strategies}
    for item in strategies:
        hypothesis = _mapping(item.get("hypothesis"))
        if not hypothesis.get("alpha_sources") or not hypothesis.get("risk_premia_explanation"):
            return False
        if not item.get("parameter_space") or not item.get("data_dependencies") or not item.get("cost_model"):
            return False
        if not item.get("failure_conditions"):
            return False
    return required_families <= families


def _manual_vendor_drop_package_blockers(report: Mapping[str, Any]) -> list[str]:
    if not report:
        return ["manual_vendor_drop_package_missing"]
    blockers = []
    if report.get("status") != "manual_vendor_drop_package_ready":
        blockers.append("manual_vendor_drop_package_not_ready")
    if int(report.get("required_table_count", 0) or 0) < 6:
        blockers.append("manual_vendor_drop_required_tables_incomplete")
    if int(report.get("field_count", 0) or 0) <= 0:
        blockers.append("manual_vendor_drop_field_dictionary_empty")
    return blockers


def _monitoring_rules_complete(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "monitoring_rules_defined":
        return False
    if report.get("required_before_paper_or_live") is not True:
        return False
    if _nested(report, "guardrails.paper_simulation_allowed") is not False:
        return False
    if _nested(report, "guardrails.live_order_allowed") is not False:
        return False
    rules = _mapping(report.get("rules"))
    for section in ("data_monitors", "position_and_execution_monitors", "attribution", "retirement_rules"):
        if not _mapping(rules.get(section)):
            return False
    if not _list(report.get("minimum_required_before_paper")):
        return False
    if not _list(_nested(report, "audit_trail.required_chain", [])):
        return False
    if not _list(_nested(report, "incident_review.required_template_fields", [])):
        return False
    if not _list(_nested(report, "replay_requirements.inputs", [])):
        return False
    if not _list(_nested(report, "logging_policy.required_fields", [])):
        return False
    return True


def _small_account_constraint_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = [item for item in _list(report.get("scenarios")) if isinstance(item, Mapping)]
    scenario_ids = [str(item.get("scenario_id", "")) for item in scenarios]
    return {
        "status": report.get("status"),
        "account_equity": report.get("account_equity"),
        "min_trade_amount_usd": report.get("min_trade_amount_usd"),
        "slippage_bps": report.get("slippage_bps"),
        "annual_financing_rate": report.get("annual_financing_rate"),
        "initial_margin_requirement": report.get("initial_margin_requirement"),
        "maintenance_margin_requirement": report.get("maintenance_margin_requirement"),
        "scenario_count": len(scenarios),
        "scenario_ids": scenario_ids,
        "initial_live_leverage_default": _nested(report, "guardrails.initial_live_leverage_default"),
        "research_cap_1_5x_not_live_default": _nested(report, "guardrails.research_cap_1_5x_not_live_default"),
        "fractional_margin_fields_present": _execution_models_have_margin_fields(scenarios, "fractional_share_allowed_model"),
        "whole_share_margin_fields_present": _execution_models_have_margin_fields(scenarios, "whole_share_model"),
    }


def _small_account_constraint_blockers(report: Mapping[str, Any]) -> list[str]:
    blockers = _list_of_str(report.get("blockers"))
    if report.get("status") != "pass_observation_only":
        blockers.append("small_account_preflight_not_pass_observation_only")
    if _number_or(report.get("account_equity"), 0.0) != 10000.0:
        blockers.append("small_account_equity_not_10000_usd")
    if _nested(report, "guardrails.initial_live_leverage_default") != 1.0:
        blockers.append("small_account_initial_live_leverage_not_1x")
    if _nested(report, "guardrails.research_cap_1_5x_not_live_default") is not True:
        blockers.append("small_account_research_cap_1_5x_not_locked")
    if report.get("initial_margin_requirement") is None:
        blockers.append("small_account_initial_margin_requirement_missing")
    if report.get("maintenance_margin_requirement") is None:
        blockers.append("small_account_maintenance_margin_requirement_missing")

    scenarios = [item for item in _list(report.get("scenarios")) if isinstance(item, Mapping)]
    expected_scenarios = {"one_x_cash_only", "low_leverage_1_25x_research", "research_cap_1_5x"}
    scenario_ids = {str(item.get("scenario_id", "")) for item in scenarios}
    if scenario_ids != expected_scenarios:
        blockers.append("small_account_leverage_scenarios_incomplete")
    if not _execution_models_have_margin_fields(scenarios, "fractional_share_allowed_model"):
        blockers.append("small_account_fractional_margin_model_incomplete")
    if not _execution_models_have_margin_fields(scenarios, "whole_share_model"):
        blockers.append("small_account_whole_share_margin_model_incomplete")
    return _dedupe(blockers)


def _blocker_taxonomy_complete(report: Mapping[str, Any]) -> bool:
    if report.get("status") not in {
        "blocked_external_and_time_dependencies",
        "actionable_engineering_review",
        "no_blockers_detected",
    }:
        return False
    if _nested(report, "guardrails.live_order_allowed") is not False:
        return False
    if _nested(report, "guardrails.paper_or_live_unlock_allowed") is not False:
        return False
    if _category_count(report, "unsafe_flags") != 0:
        return False
    if _nested(report, "summary.total_blockers") is None:
        return False
    return True


def _category_count(report: Mapping[str, Any], category: str) -> int:
    for item in _list(report.get("categories")):
        if isinstance(item, Mapping) and item.get("category") == category:
            try:
                return int(item.get("blocker_count", 0) or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _execution_models_have_margin_fields(scenarios: list[Mapping[str, Any]], model_key: str) -> bool:
    required = {
        "borrow_notional",
        "estimated_financing_daily",
        "initial_margin_required",
        "initial_margin_surplus",
        "maintenance_margin_required",
        "maintenance_margin_surplus",
    }
    if not scenarios:
        return False
    for scenario in scenarios:
        model = _mapping(scenario.get(model_key))
        if not required <= set(model):
            return False
    return True


def _status_complete(actual: Any, target: str) -> str:
    return "complete" if str(actual or "") == target else "action_required"


def _unsafe_flags(reports: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out = []
    unsafe_keys = {
        "live_order_allowed",
        "order_endpoint_allowed",
        "private_endpoint_allowed",
        "paper_or_live_unlock_allowed",
        "real_order_submitted",
        "broker_calls_used",
    }
    for report_name, report in reports.items():
        for key, value in _walk(report):
            if key.split(".")[-1] in unsafe_keys and value is True:
                out.append(f"{report_name}.{key}=true")
    return _dedupe(out)


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, Mapping):
        out = []
        for key, item in value.items():
            out.extend(_walk(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    if isinstance(value, list):
        out = []
        for index, item in enumerate(value):
            out.extend(_walk(item, f"{prefix}.{index}"))
        return out
    return [(prefix, value)]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# US Equity 开发规划执行审计",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        "",
        "| 阶段 | 状态 | 主要阻断 |",
        "| --- | --- | --- |",
    ]
    for item in _list(payload.get("phase_checks")):
        blockers = _list_of_str(item.get("blockers")) if isinstance(item, Mapping) else []
        lines.append(
            f"| `{item.get('phase_id')}` | `{item.get('status')}` | {', '.join(f'`{b}`' for b in blockers[:3]) if blockers else '无'} |"
        )
    lines.extend(["", "## 总阻断", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend(f"- `{item}`" for item in blockers) if blockers else lines.append("- 无")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 本报告只审计规划执行状态。",
            "- 不修改策略参数。",
            "- 不解锁 paper/live。",
        ]
    )
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


def _nested(value: Any, dotted: str, default: Any = None) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return default
        current = current[part]
    return current


def _number_or(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--generated-at", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_us_equity_development_plan_audit(
        repo_root=args.repo_root,
        output=args.output,
        markdown_output=args.markdown_output,
        generated_at=args.generated_at or None,
    )
    print(json.dumps({"status": payload["status"], "output": payload["outputs"]["json"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
