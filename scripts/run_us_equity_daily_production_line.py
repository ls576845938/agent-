#!/usr/bin/env python3
"""Run the daily US equity research production-line loop.

This entrypoint composes existing gates and reports. It does not fetch broker
data, call private/order endpoints, mutate strategy parameters, or unlock
paper/live trading.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_us_equity_data_freshness_daily_report import (  # noqa: E402
    build_us_equity_data_freshness_daily_report,
)
from scripts.build_us_equity_candidate_bundle_evidence_report import (  # noqa: E402
    build_us_equity_candidate_bundle_evidence_report,
)
from scripts.build_us_equity_development_plan_audit import build_us_equity_development_plan_audit  # noqa: E402
from scripts.build_us_equity_blocker_taxonomy_report import build_us_equity_blocker_taxonomy_report  # noqa: E402
from scripts.build_us_equity_remediation_ticket_closure_report import (  # noqa: E402
    build_us_equity_remediation_ticket_closure_report,
)
from scripts.build_us_equity_etf_kline_quality_daily_report import (  # noqa: E402
    build_us_equity_etf_kline_quality_daily_report,
)
from scripts.build_us_equity_manual_decision_record_report import (  # noqa: E402
    build_us_equity_manual_decision_record_report,
)
from scripts.build_us_equity_fred_macro_preflight_report import (  # noqa: E402
    build_us_equity_fred_macro_preflight_report,
)
from scripts.build_us_equity_incoming_drop_readiness_report import (  # noqa: E402
    build_us_equity_incoming_drop_readiness_report,
)
from scripts.build_us_equity_local_pit_file_discovery_report import (  # noqa: E402
    build_us_equity_local_pit_file_discovery_report,
)
from scripts.build_us_equity_pit_procurement_readiness_report import (  # noqa: E402
    build_us_equity_pit_procurement_readiness_report,
)
from scripts.import_us_equity_local_csv_production_bundle import (  # noqa: E402
    import_us_equity_local_csv_production_bundle,
)
from scripts.build_us_equity_manual_review_packet import build_us_equity_manual_review_packet  # noqa: E402
from scripts.build_us_equity_live_readiness_risk_constitution import (  # noqa: E402
    build_us_equity_live_readiness_risk_constitution,
)
from scripts.build_us_equity_execution_drill_evidence_report import (  # noqa: E402
    build_us_equity_execution_drill_evidence_report,
)
from scripts.build_us_equity_broker_credentials_review_report import (  # noqa: E402
    build_us_equity_broker_credentials_review_report,
)
from scripts.build_us_equity_broker_credentials_operator_handoff import (  # noqa: E402
    build_us_equity_broker_credentials_operator_handoff,
)
from scripts.build_us_equity_kill_switch_drill_report import (  # noqa: E402
    build_us_equity_kill_switch_drill_report,
)
from scripts.build_us_equity_order_reconciliation_drill_report import (  # noqa: E402
    build_us_equity_order_reconciliation_drill_report,
)
from scripts.build_us_equity_manual_stop_reset_drill_report import (  # noqa: E402
    build_us_equity_manual_stop_reset_drill_report,
)
from scripts.build_us_equity_monitoring_rules_report import build_us_equity_monitoring_rules_report  # noqa: E402
from scripts.build_us_equity_daily_monitoring_report import build_us_equity_daily_monitoring_report  # noqa: E402
from scripts.build_us_equity_paper_simulation_readiness_report import (  # noqa: E402
    build_us_equity_paper_simulation_readiness_report,
)
from scripts.run_us_equity_paper_simulation_roll import run_us_equity_paper_simulation_roll  # noqa: E402
from scripts.build_us_equity_paper_simulation_evaluation_report import (  # noqa: E402
    build_us_equity_paper_simulation_evaluation_report,
)
from scripts.build_us_equity_production_bundle_activation_report import (  # noqa: E402
    build_us_equity_production_bundle_activation_report,
)
from scripts.build_us_equity_production_bundle_intake_packet import (  # noqa: E402
    build_us_equity_production_bundle_intake_packet,
)
from scripts.build_us_equity_production_data_acquisition_plan import (  # noqa: E402
    build_us_equity_production_data_acquisition_plan,
)
from scripts.build_us_equity_pit_data_intake_status_report import (  # noqa: E402
    build_us_equity_pit_data_intake_status_report,
)
from scripts.build_us_equity_pit_operator_handoff_summary import (  # noqa: E402
    build_us_equity_pit_operator_handoff_summary,
)
from scripts.build_us_equity_vendor_drop_operator_progress_report import (  # noqa: E402
    build_us_equity_vendor_drop_operator_progress_report,
)
from scripts.build_us_equity_vendor_drop_preflight_report import (  # noqa: E402
    build_us_equity_vendor_drop_preflight_report,
)
from scripts.prepare_us_equity_vendor_drop_workspace import (  # noqa: E402
    prepare_us_equity_vendor_drop_workspace,
)
from scripts.run_us_equity_pit_bundle_acceptance import run_us_equity_pit_bundle_acceptance  # noqa: E402
from scripts.run_us_equity_vendor_drop_pipeline import run_us_equity_vendor_drop_pipeline  # noqa: E402
from scripts.build_us_equity_standard_report_schema_audit import (  # noqa: E402
    build_us_equity_standard_report_schema_audit,
)
from scripts.build_us_equity_strategy_registry_report import (  # noqa: E402
    build_us_equity_strategy_registry_report,
)
from scripts.build_us_equity_research_start_gate_report import (  # noqa: E402
    build_us_equity_research_start_gate_report,
)
from scripts.build_us_equity_dual_momentum_design_spec_report import (  # noqa: E402
    build_us_equity_dual_momentum_design_spec_report,
)
from scripts.build_us_equity_absolute_momentum_design_spec_report import (  # noqa: E402
    build_us_equity_absolute_momentum_design_spec_report,
)
from scripts.build_us_equity_topn_etf_rotation_design_spec_report import (  # noqa: E402
    build_us_equity_topn_etf_rotation_design_spec_report,
)
from scripts.build_us_equity_regime_overlay_design_spec_report import (  # noqa: E402
    build_us_equity_regime_overlay_design_spec_report,
)
from scripts.build_us_equity_factor_momentum_quality_design_spec_report import (  # noqa: E402
    build_us_equity_factor_momentum_quality_design_spec_report,
)
from scripts.build_us_equity_151_trading_strategies_migration_design_spec_report import (  # noqa: E402
    build_us_equity_151_trading_strategies_migration_design_spec_report,
)
from scripts.build_us_equity_research_design_queue_report import (  # noqa: E402
    build_us_equity_research_design_queue_report,
)
from scripts.build_us_equity_strategy_production_line_report import (  # noqa: E402
    build_us_equity_strategy_production_line_report,
)
from scripts.build_us_equity_completion_dependency_report import (  # noqa: E402
    build_us_equity_completion_dependency_report,
)
from scripts.build_us_equity_next_action_queue_report import (  # noqa: E402
    build_us_equity_next_action_queue_report,
)
from scripts.build_us_equity_operator_unblock_packet import (  # noqa: E402
    build_us_equity_operator_unblock_packet,
)
from scripts.build_us_equity_completion_audit_report import (  # noqa: E402
    build_us_equity_completion_audit_report,
)
from scripts.build_us_etf_strategy_validation_gate_report import (  # noqa: E402
    build_us_etf_strategy_validation_gate_report,
)
from scripts.build_us_etf_strategy_validation_evidence_audit import (  # noqa: E402
    build_us_etf_strategy_validation_evidence_audit,
)
from scripts.build_us_etf_forward_observation_evaluation_report import (  # noqa: E402
    build_us_etf_forward_observation_evaluation_report,
)
from scripts.build_us_etf_forward_observation_replay_readiness_report import (  # noqa: E402
    build_us_etf_forward_observation_replay_readiness_report,
)
from scripts.build_us_etf_forward_observation_daily_health_report import (  # noqa: E402
    build_us_etf_forward_observation_daily_health_report,
)
from scripts.build_us_etf_small_account_execution_preflight_report import (  # noqa: E402
    build_us_etf_small_account_execution_preflight_report,
)
from scripts.run_us_etf_forward_observation_daily import run_us_etf_forward_observation_daily  # noqa: E402
from scripts.check_artifact_lineage_health import (  # noqa: E402
    US_EQUITY_PRODUCTION_CONTROL_ARTIFACT_SPECS,
    build_artifact_lineage_health_report,
    write_artifact_lineage_health_report,
)


SCHEMA_VERSION = "us_equity_daily_production_line_run_v1"
DEFAULT_OUTPUT = Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/US Equity 日更生产线运行报告.md")
DEFAULT_PRODUCTION_CONTROL_HEALTH_OUTPUT = Path(
    "artifacts/artifact_health/latest/us_equity_production_control_health_report.json"
)
ALLOWED_STATUSES = {"PASS", "BLOCKED"}

StepFn = Callable[..., Mapping[str, Any]]


def run_us_equity_daily_production_line(
    *,
    repo_root: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
    kline_quality_fn: StepFn = build_us_equity_etf_kline_quality_daily_report,
    data_freshness_fn: StepFn = build_us_equity_data_freshness_daily_report,
    fred_preflight_fn: StepFn = build_us_equity_fred_macro_preflight_report,
    candidate_bundle_evidence_fn: StepFn = build_us_equity_candidate_bundle_evidence_report,
    incoming_drop_readiness_fn: StepFn = build_us_equity_incoming_drop_readiness_report,
    local_pit_file_discovery_fn: StepFn = build_us_equity_local_pit_file_discovery_report,
    pit_procurement_readiness_fn: StepFn = build_us_equity_pit_procurement_readiness_report,
    local_csv_bundle_import_fn: StepFn = import_us_equity_local_csv_production_bundle,
    production_bundle_intake_fn: StepFn = build_us_equity_production_bundle_intake_packet,
    production_bundle_activation_fn: StepFn = build_us_equity_production_bundle_activation_report,
    pit_data_intake_status_fn: StepFn = build_us_equity_pit_data_intake_status_report,
    pit_bundle_acceptance_fn: StepFn = run_us_equity_pit_bundle_acceptance,
    vendor_drop_operator_progress_fn: StepFn = build_us_equity_vendor_drop_operator_progress_report,
    pit_operator_handoff_fn: StepFn = build_us_equity_pit_operator_handoff_summary,
    vendor_drop_workspace_fn: StepFn = prepare_us_equity_vendor_drop_workspace,
    vendor_drop_preflight_fn: StepFn = build_us_equity_vendor_drop_preflight_report,
    vendor_drop_pipeline_fn: StepFn = run_us_equity_vendor_drop_pipeline,
    production_data_acquisition_fn: StepFn = build_us_equity_production_data_acquisition_plan,
    strategy_registry_fn: StepFn = build_us_equity_strategy_registry_report,
    research_start_gate_fn: StepFn = build_us_equity_research_start_gate_report,
    dual_momentum_design_spec_fn: StepFn = build_us_equity_dual_momentum_design_spec_report,
    absolute_momentum_design_spec_fn: StepFn = build_us_equity_absolute_momentum_design_spec_report,
    topn_etf_rotation_design_spec_fn: StepFn = build_us_equity_topn_etf_rotation_design_spec_report,
    regime_overlay_design_spec_fn: StepFn = build_us_equity_regime_overlay_design_spec_report,
    factor_momentum_quality_design_spec_fn: StepFn = build_us_equity_factor_momentum_quality_design_spec_report,
    trading_strategies_151_migration_design_spec_fn: StepFn = build_us_equity_151_trading_strategies_migration_design_spec_report,
    research_design_queue_fn: StepFn = build_us_equity_research_design_queue_report,
    strategy_validation_gate_fn: StepFn = build_us_etf_strategy_validation_gate_report,
    strategy_validation_evidence_audit_fn: StepFn = build_us_etf_strategy_validation_evidence_audit,
    forward_daily_fn: StepFn = run_us_etf_forward_observation_daily,
    forward_health_fn: StepFn = build_us_etf_forward_observation_daily_health_report,
    forward_evaluation_fn: StepFn = build_us_etf_forward_observation_evaluation_report,
    small_account_preflight_fn: StepFn = build_us_etf_small_account_execution_preflight_report,
    manual_decision_record_fn: StepFn = build_us_equity_manual_decision_record_report,
    manual_review_fn: StepFn = build_us_equity_manual_review_packet,
    paper_simulation_readiness_fn: StepFn = build_us_equity_paper_simulation_readiness_report,
    paper_simulation_roll_fn: StepFn = run_us_equity_paper_simulation_roll,
    paper_simulation_evaluation_fn: StepFn = build_us_equity_paper_simulation_evaluation_report,
    monitoring_rules_fn: StepFn = build_us_equity_monitoring_rules_report,
    order_reconciliation_drill_fn: StepFn = build_us_equity_order_reconciliation_drill_report,
    manual_stop_reset_drill_fn: StepFn = build_us_equity_manual_stop_reset_drill_report,
    kill_switch_drill_fn: StepFn = build_us_equity_kill_switch_drill_report,
    broker_credentials_review_fn: StepFn = build_us_equity_broker_credentials_review_report,
    broker_credentials_handoff_fn: StepFn = build_us_equity_broker_credentials_operator_handoff,
    execution_drill_evidence_fn: StepFn = build_us_equity_execution_drill_evidence_report,
    live_readiness_fn: StepFn = build_us_equity_live_readiness_risk_constitution,
    standard_schema_audit_fn: StepFn = build_us_equity_standard_report_schema_audit,
    replay_readiness_fn: StepFn = build_us_etf_forward_observation_replay_readiness_report,
    development_plan_audit_fn: StepFn = build_us_equity_development_plan_audit,
    blocker_taxonomy_fn: StepFn = build_us_equity_blocker_taxonomy_report,
    remediation_ticket_closure_fn: StepFn = build_us_equity_remediation_ticket_closure_report,
    production_line_fn: StepFn = build_us_equity_strategy_production_line_report,
    completion_dependency_fn: StepFn = build_us_equity_completion_dependency_report,
    next_action_queue_fn: StepFn = build_us_equity_next_action_queue_report,
    operator_unblock_packet_fn: StepFn = build_us_equity_operator_unblock_packet,
    completion_audit_fn: StepFn = build_us_equity_completion_audit_report,
    daily_monitoring_fn: StepFn = build_us_equity_daily_monitoring_report,
    production_control_health_fn: StepFn | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    steps: list[dict[str, Any]] = []

    steps.append(_run_step("etf_kline_quality_daily", kline_quality_fn, root, generated))
    steps.append(_run_step("data_freshness_daily", data_freshness_fn, root, generated))
    steps.append(_run_step("fred_macro_preflight", fred_preflight_fn, root, generated))
    steps.append(_run_step("candidate_bundle_evidence", candidate_bundle_evidence_fn, root, generated))
    steps.append(_run_step("vendor_drop_workspace_preparation", vendor_drop_workspace_fn, root, generated))
    steps.append(_run_step("local_pit_file_discovery", local_pit_file_discovery_fn, root, generated))
    steps.append(_run_step("pit_procurement_readiness", pit_procurement_readiness_fn, root, generated))
    steps.append(_run_step("incoming_drop_readiness", incoming_drop_readiness_fn, root, generated))
    steps.append(_run_step("production_data_acquisition_plan", production_data_acquisition_fn, root, generated))
    steps.append(_run_step("local_csv_production_bundle_import", local_csv_bundle_import_fn, root, generated))
    steps.append(_run_step("production_bundle_intake_packet", production_bundle_intake_fn, root, generated))
    steps.append(_run_step("production_bundle_activation", production_bundle_activation_fn, root, generated))
    steps.append(_run_step("pit_bundle_acceptance", pit_bundle_acceptance_fn, root, generated))
    steps.append(_run_step("pit_data_intake_status", pit_data_intake_status_fn, root, generated))
    steps.append(_run_step("vendor_drop_operator_progress", vendor_drop_operator_progress_fn, root, generated))
    steps.append(_run_step("pit_operator_handoff", pit_operator_handoff_fn, root, generated))
    steps.append(_run_step("vendor_drop_preflight", vendor_drop_preflight_fn, root, generated))
    steps.append(_run_step("vendor_drop_pipeline", vendor_drop_pipeline_fn, root, generated))
    steps.append(_run_step("strategy_registry", strategy_registry_fn, root, generated))
    steps.append(_run_step("research_start_gate", research_start_gate_fn, root, generated))
    steps.append(_run_step("dual_momentum_design_spec", dual_momentum_design_spec_fn, root, generated))
    steps.append(_run_step("absolute_momentum_design_spec", absolute_momentum_design_spec_fn, root, generated))
    steps.append(_run_step("topn_etf_rotation_design_spec", topn_etf_rotation_design_spec_fn, root, generated))
    steps.append(_run_step("regime_overlay_design_spec", regime_overlay_design_spec_fn, root, generated))
    steps.append(_run_step("factor_momentum_quality_design_spec", factor_momentum_quality_design_spec_fn, root, generated))
    steps.append(_run_step("trading_strategies_151_migration_design_spec", trading_strategies_151_migration_design_spec_fn, root, generated))
    steps.append(_run_step("research_design_queue", research_design_queue_fn, root, generated))
    steps.append(_run_step("strategy_validation_gate", strategy_validation_gate_fn, root, generated))
    steps.append(_run_step("strategy_validation_evidence_audit", strategy_validation_evidence_audit_fn, root, generated))
    steps.append(_run_step("forward_observation_daily", forward_daily_fn, root, generated))
    steps.append(_run_step("forward_observation_daily_health", forward_health_fn, root, generated))
    steps.append(_run_step("forward_observation_evaluation", forward_evaluation_fn, root, generated))
    steps.append(_run_step("small_account_execution_preflight", small_account_preflight_fn, root, generated))
    steps.append(_run_step("manual_decision_record", manual_decision_record_fn, root, generated))
    steps.append(_run_step("manual_review_packet", manual_review_fn, root, generated))
    steps.append(_run_step("paper_simulation_readiness", paper_simulation_readiness_fn, root, generated))
    steps.append(_run_step("paper_simulation_roll", paper_simulation_roll_fn, root, generated))
    steps.append(_run_step("paper_simulation_evaluation", paper_simulation_evaluation_fn, root, generated))
    steps.append(_run_step("monitoring_rules", monitoring_rules_fn, root, generated))
    steps.append(_run_step("order_reconciliation_drill", order_reconciliation_drill_fn, root, generated))
    steps.append(_run_step("manual_stop_reset_drill", manual_stop_reset_drill_fn, root, generated))
    steps.append(_run_step("kill_switch_drill", kill_switch_drill_fn, root, generated))
    steps.append(_run_step("broker_credentials_review", broker_credentials_review_fn, root, generated))
    steps.append(_run_step("broker_credentials_handoff", broker_credentials_handoff_fn, root, generated))
    steps.append(_run_step("execution_drill_evidence", execution_drill_evidence_fn, root, generated))
    steps.append(_run_step("live_readiness_risk_constitution", live_readiness_fn, root, generated))
    steps.append(_run_step("standard_report_schema_audit", standard_schema_audit_fn, root, generated))
    steps.append(_run_step("replay_readiness", replay_readiness_fn, root, generated))
    steps.append(_run_step("development_plan_audit", development_plan_audit_fn, root, generated))
    steps.append(_run_step("blocker_taxonomy", blocker_taxonomy_fn, root, generated))
    steps.append(_run_step("remediation_ticket_closure", remediation_ticket_closure_fn, root, generated))
    steps.append(_run_step("strategy_production_line", production_line_fn, root, generated))
    steps.append(_run_step("completion_dependency", completion_dependency_fn, root, generated))
    steps.append(_run_step("next_action_queue", next_action_queue_fn, root, generated))
    steps.append(_run_step("operator_unblock_packet", operator_unblock_packet_fn, root, generated))
    steps.append(_run_step("completion_audit", completion_audit_fn, root, generated))
    steps.append(_run_step("daily_monitoring", daily_monitoring_fn, root, generated))
    health_fn = production_control_health_fn or build_us_equity_production_control_health_report
    steps.append(_run_step("production_control_health", health_fn, root, generated))

    blockers = _daily_blockers(steps)
    unsafe = _unsafe_flags(steps)
    blockers.extend(f"unsafe_flag:{item}" for item in unsafe)
    status = "BLOCKED" if blockers else "PASS"
    production_line = _payload_for_step(steps, "strategy_production_line")
    development_audit = _payload_for_step(steps, "development_plan_audit")
    forward_health = _payload_for_step(steps, "forward_observation_daily_health")
    live_readiness = _payload_for_step(steps, "live_readiness_risk_constitution")
    strategy_registry = _payload_for_step(steps, "strategy_registry")
    blocker_taxonomy = _payload_for_step(steps, "blocker_taxonomy")
    remediation_tickets = _remediation_ticket_summary(blocker_taxonomy)
    remediation_closure = _payload_for_step(steps, "remediation_ticket_closure")
    next_action_queue = _payload_for_step(steps, "next_action_queue")
    operator_unblock_packet = _payload_for_step(steps, "operator_unblock_packet")
    completion_audit = _payload_for_step(steps, "completion_audit")
    production_control_health = _payload_for_step(steps, "production_control_health")
    production_pit_drop = _production_pit_drop_summary(production_line)
    vendor_drop_pipeline = _payload_for_step(steps, "vendor_drop_pipeline")
    production_pit_operator_inputs = _production_pit_operator_inputs_summary(next_action_queue)
    operator_drop_progress = _operator_drop_progress_summary(_payload_for_step(steps, "vendor_drop_operator_progress"))
    live_execution_readiness = _live_execution_readiness_summary(live_readiness)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "asset": "us_equity",
        "pipeline": "us_equity_daily_production_line",
        "status": status,
        "allowed_statuses": sorted(ALLOWED_STATUSES),
        "decision": "continue_forward_observation_and_keep_paper_live_locked" if status == "PASS" else "repair_daily_production_line",
        "expected_external_blocker": {
            "production_pit_data_required": _status(development_audit) == "development_plan_blocked_by_production_pit_data",
            "production_line_status": _status(production_line),
            "development_plan_status": _status(development_audit),
        },
        "strategy_registry_contract": {
            "status": _status(strategy_registry),
            "formal_candidate_count": _nested(strategy_registry, "formal_candidate_count"),
            "source_report_contract_passed": _nested(
                strategy_registry,
                "formal_candidate_source_report_contract.passed",
            ),
            "missing_required_keys_by_strategy": _nested(
                strategy_registry,
                "formal_candidate_source_report_contract.missing_required_keys_by_strategy",
                default={},
            ),
            "missing_paths_by_strategy": _nested(
                strategy_registry,
                "formal_candidate_source_report_contract.missing_paths_by_strategy",
                default={},
            ),
        },
        "forward_observation": {
            "daily_health_status": _status(forward_health),
            "observation_days": _nested(forward_health, "observation_days"),
            "minimum_complete_days": _nested(forward_health, "minimum_complete_days"),
            "latest_observation_date": _nested(forward_health, "latest_observation_date"),
            "continuity_passed": _nested(forward_health, "observation_continuity.passed"),
            "unique_observation_days": _nested(forward_health, "observation_continuity.unique_observation_days"),
            "max_calendar_gap_days": _nested(forward_health, "observation_continuity.max_calendar_gap_days"),
            "duplicate_target_date_count": len(
                _list(_nested(forward_health, "observation_continuity.duplicate_target_dates", default=[]))
            ),
            "duplicate_snapshot_date_count": len(
                _list(_nested(forward_health, "observation_continuity.duplicate_snapshot_dates", default=[]))
            ),
            "missing_snapshot_for_target_count": len(
                _list(_nested(forward_health, "observation_continuity.missing_snapshot_for_target", default=[]))
            ),
            "missing_target_for_snapshot_count": len(
                _list(_nested(forward_health, "observation_continuity.missing_target_for_snapshot", default=[]))
            ),
        },
        "remediation_tickets": remediation_tickets,
        "remediation_ticket_closure": {
            "status": _status(remediation_closure),
            "ticket_count": _nested(remediation_closure, "ticket_count"),
            "open_count": _nested(remediation_closure, "open_count"),
            "closed_count": _nested(remediation_closure, "closed_count"),
            "missing_source_count": len(_list(_nested(remediation_closure, "missing_sources", default=[]))),
        },
        "production_pit_drop": production_pit_drop,
        "vendor_drop_pipeline": {
            "status": _status(vendor_drop_pipeline),
            "current_blocking_step": _nested(vendor_drop_pipeline, "current_blocking_step"),
            "blocker_count": len(_list(vendor_drop_pipeline.get("blockers"))),
            "unsafe_flag_count": len(_list(vendor_drop_pipeline.get("unsafe_flags"))),
            "license_reviewed": vendor_drop_pipeline.get("license_reviewed"),
        },
        "production_pit_operator_inputs": production_pit_operator_inputs,
        "operator_drop_progress": operator_drop_progress,
        "operator_unblock": _operator_unblock_summary(operator_unblock_packet),
        "completion_audit": _completion_audit_summary(completion_audit),
        "production_control_health": _production_control_health_summary(production_control_health),
        "live_execution_readiness": live_execution_readiness,
        "run_progress": _run_progress(
            status=status,
            steps=steps,
            production_line=production_line,
            forward_health=forward_health,
            remediation_closure=remediation_closure,
            production_pit_drop=production_pit_drop,
            operator_drop_progress=operator_drop_progress,
            operator_unblock_packet=operator_unblock_packet,
            completion_audit=completion_audit,
            live_execution_readiness=live_execution_readiness,
            next_action_queue=next_action_queue,
        ),
        "steps": steps,
        "blockers": _dedupe(blockers),
        "unsafe_flags": unsafe,
        "guardrails": {
            "daily_orchestration_only": True,
            "strategy_parameters_mutated": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {
            "json": _relpath(_resolve(root, output), root),
            "markdown": _relpath(_resolve(root, markdown_output), root),
        },
    }
    if payload["status"] not in ALLOWED_STATUSES:
        raise AssertionError(f"invalid daily production-line status: {payload['status']}")
    _write_json(_resolve(root, output), payload)
    _write_text(_resolve(root, markdown_output), _markdown(payload))
    return payload


def _run_step(step_id: str, fn: StepFn, root: Path, generated_at: str) -> dict[str, Any]:
    try:
        payload = dict(fn(repo_root=root, generated_at=generated_at))
        step_status = _payload_status(payload)
        return {
            "step_id": step_id,
            "status": step_status,
            "passed": _step_status_is_safe(step_id, payload),
            "blockers": _list_of_str(payload.get("blockers")),
            "warnings": _list_of_str(payload.get("warnings")),
            "output": _nested(payload, "outputs.json"),
            "payload": payload,
        }
    except Exception as exc:  # noqa: BLE001 - fail closed and preserve audit trail
        return {
            "step_id": step_id,
            "status": "EXCEPTION",
            "passed": False,
            "blockers": [f"{step_id}_exception:{type(exc).__name__}"],
            "warnings": [],
            "output": None,
            "payload": {"error": str(exc)},
        }


def _payload_status(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status") or payload.get("health_status") or "")


def build_us_equity_production_control_health_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
    output: Path = DEFAULT_PRODUCTION_CONTROL_HEALTH_OUTPUT,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    payload = build_artifact_lineage_health_report(
        repo_root=root,
        generated_at=generated_at,
        artifact_specs=US_EQUITY_PRODUCTION_CONTROL_ARTIFACT_SPECS,
        stale_after_hours=1_000_000,
        allow_workspace_parent_paths=True,
    )
    write_artifact_lineage_health_report(payload, _resolve(root, output))
    payload["outputs"] = {"json": _relpath(_resolve(root, output), root)}
    return payload


def _step_status_is_safe(step_id: str, payload: Mapping[str, Any]) -> bool:
    status = _payload_status(payload)
    allowed = {
        "etf_kline_quality_daily": {"pass", "warn"},
        "data_freshness_daily": {"pass"},
        "fred_macro_preflight": {"fred_macro_preflight_pass", "fred_macro_preflight_warn"},
        "candidate_bundle_evidence": {"candidate_evidence_ready_for_manual_bundle_build"},
        "incoming_drop_readiness": {
            "incoming_drop_ready_for_import",
            "incoming_drop_blocked",
        },
        "local_csv_production_bundle_import": {
            "production_bundle_imported",
            "production_bundle_import_blocked",
        },
        "production_bundle_intake_packet": {"intake_packet_ready_for_data_vendor_drop"},
        "production_bundle_activation": {"activation_blocked", "activation_ready_for_manual_config_apply"},
        "pit_data_intake_status": {
            "production_pit_data_intake_ready",
            "production_pit_data_intake_blocked",
        },
        "pit_bundle_acceptance": {
            "acceptance_ready_for_manual_config_apply",
            "acceptance_blocked",
        },
        "pit_operator_handoff": {
            "handoff_ready_for_operator_drop",
            "handoff_blocked",
        },
        "vendor_drop_operator_progress": {
            "operator_drop_blocked",
            "operator_drop_ready_for_import",
            "operator_drop_complete_for_manual_review",
        },
        "vendor_drop_preflight": {
            "vendor_drop_preflight_blocked",
            "vendor_drop_preflight_waiting_for_vendor_files",
            "vendor_drop_preflight_ready_for_readiness_check",
        },
        "vendor_drop_pipeline": {
            "vendor_drop_pipeline_blocked",
            "vendor_drop_pipeline_ready_for_manual_config_review",
        },
        "vendor_drop_workspace_preparation": {"vendor_drop_workspace_prepared"},
        "local_pit_file_discovery": {
            "pit_file_discovery_ready_for_copy",
            "pit_file_discovery_no_complete_candidate_set",
        },
        "pit_procurement_readiness": {
            "pit_procurement_blocked",
            "pit_procurement_ready_for_vendor_order",
            "pit_procurement_ready_for_manual_license_review",
        },
        "production_data_acquisition_plan": {
            "production_data_acquisition_required",
            "production_data_acquisition_ready_for_preflight",
        },
        "strategy_registry": {"pass"},
        "research_start_gate": {
            "research_design_only",
            "research_start_ready",
            "research_start_blocked",
        },
        "dual_momentum_design_spec": {"design_spec_ready"},
        "absolute_momentum_design_spec": {"design_spec_ready"},
        "topn_etf_rotation_design_spec": {"design_spec_ready"},
        "regime_overlay_design_spec": {"design_spec_ready"},
        "factor_momentum_quality_design_spec": {"design_spec_ready"},
        "trading_strategies_151_migration_design_spec": {"design_spec_ready"},
        "research_design_queue": {
            "research_design_queue_ready",
            "research_design_queue_waiting_for_data",
            "research_design_queue_blocked",
        },
        "strategy_validation_gate": {
            "blocked_data_quality",
            "research_only",
            "validation_passed_for_forward_observation",
            "rejected",
        },
        "strategy_validation_evidence_audit": {
            "validation_evidence_audit_incomplete",
            "validation_evidence_audit_blocked_data_quality",
            "validation_evidence_audit_ready_for_forward_observation",
        },
        "forward_observation_daily": {"PASS"},
        "forward_observation_daily_health": {"daily_health_pass", "daily_health_observing_stale"},
        "forward_observation_evaluation": {
            "forward_observing",
            "forward_complete_for_manual_review",
        },
        "small_account_execution_preflight": {
            "pass_observation_only",
            "blocked",
        },
        "manual_decision_record": {
            "manual_decision_record_missing_or_invalid",
            "manual_decision_record_valid",
        },
        "manual_review_packet": {"manual_review_pending", "manual_review_ready"},
        "paper_simulation_readiness": {
            "paper_simulation_blocked",
            "paper_simulation_ready_for_manual_start",
        },
        "paper_simulation_roll": {"PASS", "BLOCKED"},
        "paper_simulation_evaluation": {
            "paper_simulation_not_started",
            "paper_simulation_observing",
            "paper_simulation_complete_for_manual_review",
            "paper_simulation_blocked",
        },
        "execution_drill_evidence": {
            "execution_drill_evidence_blocked",
            "execution_drill_evidence_partial",
            "execution_drill_evidence_complete",
        },
        "kill_switch_drill": {
            "kill_switch_drill_blocked",
            "kill_switch_drill_partial",
            "kill_switch_drill_proven",
        },
        "order_reconciliation_drill": {
            "order_reconciliation_drill_blocked",
            "order_reconciliation_drill_proven",
        },
        "manual_stop_reset_drill": {
            "manual_stop_reset_blocked",
            "manual_stop_reset_proven",
        },
        "broker_credentials_review": {
            "broker_credentials_review_blocked",
            "broker_credentials_review_proven",
        },
        "broker_credentials_handoff": {
            "broker_credentials_handoff_blocked",
            "broker_credentials_handoff_ready_for_manual_review",
        },
        "live_readiness_risk_constitution": {"live_readiness_blocked"},
        "standard_report_schema_audit": {"schema_audit_pass"},
        "monitoring_rules": {"monitoring_rules_defined"},
        "replay_readiness": {"replay_readiness_pass"},
        "development_plan_audit": {
            "development_plan_in_progress",
            "development_plan_blocked_by_production_pit_data",
        },
        "blocker_taxonomy": {
            "blocked_external_and_time_dependencies",
            "actionable_engineering_review",
            "no_blockers_detected",
        },
        "remediation_ticket_closure": {
            "remediation_tickets_open",
            "remediation_tickets_closed",
            "remediation_ticket_closure_source_missing",
        },
        "strategy_production_line": {
            "production_line_blocked_before_paper_or_live",
            "production_line_observing_manual_review_required",
        },
        "completion_dependency": {
            "completion_dependencies_blocked",
            "completion_dependencies_satisfied",
        },
        "next_action_queue": {
            "next_actions_open",
            "next_actions_complete",
        },
        "operator_unblock_packet": {
            "operator_unblock_open",
            "operator_unblock_complete",
        },
        "completion_audit": {
            "completion_blocked",
            "completion_in_progress",
            "completion_complete",
        },
        "daily_monitoring": {
            "daily_monitoring_blocked",
            "daily_monitoring_observing",
            "daily_monitoring_clear",
        },
        "production_control_health": {"pass", "warn"},
    }
    return status in allowed.get(step_id, set())


def _daily_blockers(steps: list[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for step in steps:
        if step.get("passed") is not True:
            blockers.append(f"us_equity_daily_step_not_safe:{step.get('step_id')}:{step.get('status')}")
            blockers.extend(_list_of_str(step.get("blockers")))
    return _dedupe(blockers)


def _payload_for_step(steps: list[Mapping[str, Any]], step_id: str) -> Mapping[str, Any]:
    for step in steps:
        if step.get("step_id") == step_id:
            return _mapping(step.get("payload"))
    return {}


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


def _production_pit_drop_summary(production_line: Mapping[str, Any]) -> dict[str, Any]:
    evidence: Mapping[str, Any] = {}
    primary_id = production_line.get("primary_strategy_id")
    for strategy in _list(production_line.get("strategies")):
        if not isinstance(strategy, Mapping):
            continue
        if strategy.get("strategy_id") != primary_id:
            continue
        for stage in _list(strategy.get("stages")):
            if isinstance(stage, Mapping) and stage.get("stage_id") == "data_quality_pit_check":
                evidence = _mapping(stage.get("evidence"))
                break
    return {
        "status": evidence.get("production_data_acquisition_current_drop_status"),
        "ready_file_count": evidence.get("production_data_acquisition_current_drop_ready_file_count"),
        "required_file_count": evidence.get("production_data_acquisition_current_drop_required_file_count"),
        "first_blocker": evidence.get("production_data_acquisition_current_drop_first_blocker"),
        "ready_table_count": evidence.get("production_data_acquisition_contract_ready_table_count"),
        "blocked_table_count": evidence.get("production_data_acquisition_contract_blocked_table_count"),
    }


def _operator_drop_progress_summary(progress: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": progress.get("status"),
        "completed_count": progress.get("completed_count"),
        "blocked_count": progress.get("blocked_count"),
        "pending_count": progress.get("pending_count"),
        "step_count": progress.get("step_count"),
        "next_step_id": progress.get("next_step_id"),
        "next_action": progress.get("next_action"),
    }


def _production_pit_operator_inputs_summary(next_action_queue: Mapping[str, Any]) -> dict[str, Any]:
    next_action = _mapping(next_action_queue.get("next_action"))
    evidence = _mapping(next_action.get("evidence"))
    inputs = [
        {
            "filename": str(item.get("filename", "")),
            "target_path": str(item.get("target_path", "")),
            "table": str(item.get("table", "")),
            "blocker": str(item.get("blocker", "")),
            "required_fields": _list_of_str(item.get("required_fields")),
        }
        for item in _list(evidence.get("required_operator_inputs"))
        if isinstance(item, Mapping)
    ]
    return {
        "next_action_id": str(next_action.get("action_id", "")),
        "owner": str(next_action.get("owner", "")),
        "missing_file_count": int(evidence.get("missing_file_count", len(inputs)) or 0),
        "required_inputs": inputs,
        "command_sequence": _list_of_str(evidence.get("operator_command_sequence")),
    }


def _live_execution_readiness_summary(live_readiness: Mapping[str, Any]) -> dict[str, Any]:
    execution = _mapping(live_readiness.get("execution_readiness"))
    return {
        "status": execution.get("status"),
        "drill_count": execution.get("drill_count"),
        "proven_count": execution.get("proven_count"),
        "blocked_count": execution.get("blocked_count"),
        "live_order_allowed": live_readiness.get("live_order_allowed"),
        "real_order_submitted": live_readiness.get("real_order_submitted"),
    }


def _operator_unblock_summary(operator_unblock: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(operator_unblock.get("summary"))
    next_action = _mapping(operator_unblock.get("next_operator_action"))
    return {
        "status": _status(operator_unblock),
        "open_count": summary.get("open_count"),
        "external_input_count": summary.get("external_input_count"),
        "manual_input_count": summary.get("manual_input_count"),
        "natural_time_count": summary.get("natural_time_count"),
        "next_operator_item_id": str(next_action.get("item_id", "")),
        "next_operator_owner": str(next_action.get("owner", "")),
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }


def _completion_audit_summary(completion_audit: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(completion_audit.get("summary"))
    phases = [item for item in _list(completion_audit.get("phases")) if isinstance(item, Mapping)]
    blocked = [item for item in phases if item.get("status") == "blocked"]
    incomplete = [item for item in phases if item.get("status") != "complete"]
    first_incomplete = incomplete[0] if incomplete else {}
    blockers = _list_of_str(first_incomplete.get("blockers")) or _list_of_str(completion_audit.get("blockers"))
    return {
        "status": _status(completion_audit),
        "phase_count": summary.get("phase_count"),
        "complete_count": summary.get("complete_count"),
        "in_progress_count": summary.get("in_progress_count"),
        "blocked_count": summary.get("blocked_count"),
        "first_blocked_phase_id": str(blocked[0].get("phase_id", "")) if blocked else "",
        "first_incomplete_phase_id": str(summary.get("first_incomplete_phase_id") or first_incomplete.get("phase_id", "")),
        "first_incomplete_phase_status": str(summary.get("first_incomplete_phase_status") or first_incomplete.get("status", "")),
        "first_blocker": str(summary.get("first_blocker") or (blockers[0] if blockers else "")),
        "next_action": str(summary.get("next_action") or first_incomplete.get("next_action", "")),
        "completion_claim_allowed": bool(summary.get("completion_claim_allowed", False)),
        "completion_dependency_blocked_count": summary.get("completion_dependency_blocked_count"),
        "operator_open_input_count": summary.get("operator_open_input_count"),
        "operator_external_input_count": summary.get("operator_external_input_count"),
        "operator_manual_input_count": summary.get("operator_manual_input_count"),
        "operator_natural_time_count": summary.get("operator_natural_time_count"),
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }


def _production_control_health_summary(health: Mapping[str, Any]) -> dict[str, Any]:
    checked = [item for item in _list(health.get("checked_artifacts")) if isinstance(item, Mapping)]
    return {
        "health_status": str(health.get("health_status", "")),
        "checked_count": len(checked),
        "schema_invalid_count": len(_list(health.get("schema_invalid_artifacts"))),
        "missing_count": len(_list(health.get("missing_artifacts"))),
        "stale_count": len(_list(health.get("stale_artifacts"))),
        "path_escape_count": len(_list(health.get("path_escape_risks"))),
        "blockers": _list_of_str(health.get("blockers")),
        "promotion_safe": False,
    }


def _run_progress(
    *,
    status: str,
    steps: list[Mapping[str, Any]],
    production_line: Mapping[str, Any],
    forward_health: Mapping[str, Any],
    remediation_closure: Mapping[str, Any],
    production_pit_drop: Mapping[str, Any],
    operator_drop_progress: Mapping[str, Any],
    operator_unblock_packet: Mapping[str, Any],
    completion_audit: Mapping[str, Any],
    live_execution_readiness: Mapping[str, Any],
    next_action_queue: Mapping[str, Any],
) -> dict[str, Any]:
    failed_step_ids = [str(step.get("step_id", "")) for step in steps if step.get("passed") is not True]
    production_progress = _mapping(production_line.get("pipeline_progress"))
    next_action = _mapping(next_action_queue.get("next_action"))
    next_action_summary = _mapping(next_action_queue.get("summary"))
    operator_unblock_summary = _mapping(operator_unblock_packet.get("summary"))
    completion_audit_summary = _mapping(completion_audit.get("summary"))
    observation_days = _nested(forward_health, "observation_days")
    minimum_days = _nested(forward_health, "minimum_complete_days")
    return {
        "status": status,
        "step_count": len(steps),
        "passed_step_count": sum(1 for step in steps if step.get("passed") is True),
        "failed_step_count": len(failed_step_ids),
        "failed_step_ids": failed_step_ids,
        "production_line_status": _status(production_line),
        "production_line_next_action": str(production_progress.get("next_action") or next_action.get("action_id") or ""),
        "next_action_owner": str(next_action.get("owner", "")),
        "next_action_dependency_type": str(next_action.get("dependency_type", "")),
        "next_action_actionability": str(next_action.get("actionability", "")),
        "actionable_engineering_count": next_action_summary.get("actionable_engineering_count"),
        "blocked_until_upstream_count": next_action_summary.get("blocked_until_upstream_count"),
        "forward_observation_days": observation_days,
        "forward_minimum_days": minimum_days,
        "forward_days_until_minimum": _days_until_minimum(observation_days, minimum_days),
        "remediation_ticket_count": _nested(remediation_closure, "ticket_count"),
        "remediation_open_count": _nested(remediation_closure, "open_count"),
        "production_pit_ready_file_count": production_pit_drop.get("ready_file_count"),
        "production_pit_required_file_count": production_pit_drop.get("required_file_count"),
        "operator_next_step_id": operator_drop_progress.get("next_step_id"),
        "operator_unblock_open_count": operator_unblock_summary.get("open_count"),
        "operator_unblock_external_input_count": operator_unblock_summary.get("external_input_count"),
        "operator_unblock_manual_input_count": operator_unblock_summary.get("manual_input_count"),
        "operator_unblock_natural_time_count": operator_unblock_summary.get("natural_time_count"),
        "completion_phase_count": completion_audit_summary.get("phase_count"),
        "completion_complete_count": completion_audit_summary.get("complete_count"),
        "completion_in_progress_count": completion_audit_summary.get("in_progress_count"),
        "completion_blocked_count": completion_audit_summary.get("blocked_count"),
        "completion_first_incomplete_phase_id": completion_audit_summary.get("first_incomplete_phase_id"),
        "completion_first_incomplete_phase_status": completion_audit_summary.get("first_incomplete_phase_status"),
        "completion_first_blocker": completion_audit_summary.get("first_blocker"),
        "completion_next_action": completion_audit_summary.get("next_action"),
        "completion_claim_allowed": bool(completion_audit_summary.get("completion_claim_allowed", False)),
        "completion_dependency_blocked_count": completion_audit_summary.get("completion_dependency_blocked_count"),
        "live_execution_status": live_execution_readiness.get("status"),
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }


def _days_until_minimum(current: Any, minimum: Any) -> int | None:
    if current is None or minimum is None:
        return None
    try:
        return max(0, int(minimum) - int(current))
    except (TypeError, ValueError):
        return None


def _unsafe_flags(steps: list[Mapping[str, Any]]) -> list[str]:
    unsafe = []
    for step in steps:
        step_id = str(step.get("step_id", "unknown_step"))
        for path, value in _walk(step.get("payload")):
            key = path.split(".")[-1]
            if key in {
                "live_order_allowed",
                "paper_or_live_unlock_allowed",
                "paper_simulation_allowed",
                "private_endpoint_allowed",
                "private_endpoint_used",
                "order_endpoint_allowed",
                "order_endpoint_used",
                "real_order_submitted",
                "broker_calls_used",
            } and value is True:
                unsafe.append(f"{step_id}.{path}=true")
    return _dedupe(unsafe)


def _markdown(payload: Mapping[str, Any]) -> str:
    run_progress = _mapping(payload.get("run_progress"))
    expected = _mapping(payload.get("expected_external_blocker"))
    forward = _mapping(payload.get("forward_observation"))
    remediation = _mapping(payload.get("remediation_tickets"))
    remediation_closure = _mapping(payload.get("remediation_ticket_closure"))
    production_pit_drop = _mapping(payload.get("production_pit_drop"))
    vendor_drop_pipeline = _mapping(payload.get("vendor_drop_pipeline"))
    production_pit_inputs = _mapping(payload.get("production_pit_operator_inputs"))
    operator_drop_progress = _mapping(payload.get("operator_drop_progress"))
    operator_unblock = _mapping(payload.get("operator_unblock"))
    completion_audit = _mapping(payload.get("completion_audit"))
    production_control_health = _mapping(payload.get("production_control_health"))
    live_execution = _mapping(payload.get("live_execution_readiness"))
    lines = [
        "# US Equity 日更生产线运行报告",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        f"- 状态：`{payload.get('status')}`",
        f"- run progress：passed=`{run_progress.get('passed_step_count')}`/`{run_progress.get('step_count')}`，next=`{run_progress.get('production_line_next_action')}`",
        f"- production PIT data required：`{expected.get('production_pit_data_required')}`",
        f"- production line status：`{expected.get('production_line_status')}`",
        f"- development plan status：`{expected.get('development_plan_status')}`",
        f"- forward daily health：`{forward.get('daily_health_status')}`",
        f"- observation days：`{forward.get('observation_days')}` / `{forward.get('minimum_complete_days')}`",
        f"- remediation tickets：`{remediation.get('ticket_count')}`",
        f"- remediation ticket closure：`{remediation_closure.get('status')}`，open=`{remediation_closure.get('open_count')}`",
        f"- production PIT drop：`{production_pit_drop.get('status')}`，ready=`{production_pit_drop.get('ready_file_count')}`/`{production_pit_drop.get('required_file_count')}`",
        f"- vendor drop pipeline：`{vendor_drop_pipeline.get('status')}`，blocking_step=`{vendor_drop_pipeline.get('current_blocking_step')}`",
        f"- production PIT operator inputs：missing=`{production_pit_inputs.get('missing_file_count')}`，owner=`{production_pit_inputs.get('owner')}`",
        f"- next action：owner=`{run_progress.get('next_action_owner')}`，dependency=`{run_progress.get('next_action_dependency_type')}`，actionability=`{run_progress.get('next_action_actionability')}`，actionable_engineering=`{run_progress.get('actionable_engineering_count')}`，blocked_until_upstream=`{run_progress.get('blocked_until_upstream_count')}`",
        f"- operator drop progress：`{operator_drop_progress.get('status')}`，completed=`{operator_drop_progress.get('completed_count')}`/`{operator_drop_progress.get('step_count')}`，next=`{operator_drop_progress.get('next_step_id')}`",
        f"- operator unblock：`{operator_unblock.get('status')}`，open=`{operator_unblock.get('open_count')}`，next=`{operator_unblock.get('next_operator_item_id')}`",
        f"- completion audit：`{completion_audit.get('status')}`，complete=`{completion_audit.get('complete_count')}`/`{completion_audit.get('phase_count')}`，blocked=`{completion_audit.get('blocked_count')}`",
        f"- completion first blocker：`{completion_audit.get('first_blocker')}`，claim_allowed=`{completion_audit.get('completion_claim_allowed')}`",
        f"- production control health：`{production_control_health.get('health_status')}`，checked=`{production_control_health.get('checked_count')}`，blockers=`{len(_list(production_control_health.get('blockers')))}`",
        f"- live execution readiness：`{live_execution.get('status')}`，proven=`{live_execution.get('proven_count')}`/`{live_execution.get('drill_count')}`",
        "",
        "## Steps",
        "",
        "| step | status | passed | first blocker |",
        "| --- | --- | --- | --- |",
    ]
    for step in _list(payload.get("steps")):
        if not isinstance(step, Mapping):
            continue
        blockers = _list_of_str(step.get("blockers"))
        lines.append(
            f"| `{step.get('step_id')}` | `{step.get('status')}` | `{step.get('passed')}` | `{blockers[0] if blockers else ''}` |"
        )
    lines.extend(["", "## Blockers", ""])
    blockers = _list_of_str(payload.get("blockers"))
    lines.extend([f"- `{item}`" for item in blockers] if blockers else ["- None"])
    lines.extend(["", "## Remediation Tickets", ""])
    tickets = [item for item in _list(remediation.get("tickets")) if isinstance(item, Mapping)]
    if tickets:
        for ticket in tickets:
            lines.append(
                f"- `{ticket.get('ticket_id')}`：`{ticket.get('status')}`，owner=`{ticket.get('owner')}`，dependency=`{ticket.get('dependency_type')}`"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- 本报告只是日更编排健康检查。",
            "- 本报告不能解锁 paper/live。",
            "- 本报告不调用 broker/private/order endpoint。",
            "",
        ]
    )
    return "\n".join(lines)


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


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _status(payload: Mapping[str, Any]) -> str:
    return str(payload.get("status", ""))


def _nested(payload: Any, dotted: str, default: Any = None) -> Any:
    current = payload
    for key in dotted.split("."):
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _walk(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_walk(child, path))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(_walk(child, f"{prefix}[{idx}]"))
    else:
        out.append((prefix, value))
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the US equity daily production-line loop.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_us_equity_daily_production_line(
        repo_root=Path(args.repo_root),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
