from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from scripts.run_us_equity_daily_production_line import run_us_equity_daily_production_line


SCHEMA = Path("schemas/us_equity_daily_production_line_run_report.schema.json")


def test_daily_production_line_passes_with_expected_external_pit_blocker(tmp_path: Path) -> None:
    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **_fake_fns(),
    )

    assert payload["schema_version"] == "us_equity_daily_production_line_run_v1"
    _validate_schema(payload)
    assert payload["status"] == "PASS"
    assert payload["expected_external_blocker"]["production_pit_data_required"] is True
    assert payload["strategy_registry_contract"]["status"] == "pass"
    assert payload["strategy_registry_contract"]["formal_candidate_count"] == 1
    assert payload["strategy_registry_contract"]["source_report_contract_passed"] is True
    assert payload["strategy_registry_contract"]["missing_required_keys_by_strategy"] == {}
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["private_endpoint_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["real_order_submitted"] is False
    assert payload["guardrails"]["broker_calls_used"] is False
    assert payload["forward_observation"]["daily_health_status"] == "daily_health_pass"
    assert payload["forward_observation"]["continuity_passed"] is True
    assert payload["forward_observation"]["unique_observation_days"] == 1
    assert payload["forward_observation"]["duplicate_target_date_count"] == 0
    assert payload["forward_observation"]["missing_snapshot_for_target_count"] == 0
    assert payload["remediation_tickets"]["ticket_count"] == 2
    assert payload["remediation_tickets"]["external_or_time_dependency_count"] == 2
    assert payload["remediation_tickets"]["by_dependency_type"] == {
        "external_user_action": 1,
        "natural_time": 1,
    }
    assert payload["remediation_ticket_closure"]["status"] == "remediation_tickets_open"
    assert payload["remediation_ticket_closure"]["ticket_count"] == 2
    assert payload["remediation_ticket_closure"]["open_count"] == 2
    assert payload["remediation_ticket_closure"]["closed_count"] == 0
    assert payload["production_pit_drop"]["status"] == "incoming_drop_blocked"
    assert payload["production_pit_drop"]["ready_file_count"] == 0
    assert payload["production_pit_drop"]["required_file_count"] == 6
    assert payload["production_pit_drop"]["first_blocker"] == "source_universe_membership_events_file_missing"
    assert payload["production_pit_drop"]["ready_table_count"] == 0
    assert payload["production_pit_drop"]["blocked_table_count"] == 6
    assert payload["vendor_drop_pipeline"] == {
        "status": "vendor_drop_pipeline_blocked",
        "current_blocking_step": "vendor_drop_preflight",
        "blocker_count": 2,
        "unsafe_flag_count": 0,
        "license_reviewed": False,
    }
    assert payload["production_pit_operator_inputs"]["next_action_id"] == "us_equity_action_production_pit_data"
    assert payload["production_pit_operator_inputs"]["owner"] == "operator_data_vendor"
    assert payload["production_pit_operator_inputs"]["missing_file_count"] == 2
    assert payload["production_pit_operator_inputs"]["required_inputs"] == [
        {
            "filename": "universe_membership_events.csv",
            "target_path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/universe_membership_events.csv",
            "table": "universe_membership_events",
            "blocker": "universe_membership_events_csv_missing",
            "required_fields": ["security_id", "ticker"],
        },
        {
            "filename": "delisted_symbols.csv",
            "target_path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/delisted_symbols.csv",
            "table": "delisted_symbols",
            "blocker": "delisted_symbols_csv_missing",
            "required_fields": ["security_id", "ticker", "delisting_date"],
        },
    ]
    assert payload["production_pit_operator_inputs"]["command_sequence"] == [
        "python scripts/build_us_equity_manual_vendor_drop_package.py",
        "copy licensed PIT CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop",
        "manually confirm license review for the copied PIT CSV files",
        "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
    ]
    assert payload["operator_drop_progress"]["status"] == "operator_drop_blocked"
    assert payload["operator_drop_progress"]["completed_count"] == 3
    assert payload["operator_drop_progress"]["blocked_count"] == 2
    assert payload["operator_drop_progress"]["pending_count"] == 2
    assert payload["operator_drop_progress"]["step_count"] == 7
    assert payload["operator_drop_progress"]["next_step_id"] == "copy_six_licensed_csv_files"
    assert payload["operator_unblock"] == {
        "status": "operator_unblock_open",
        "open_count": 5,
        "external_input_count": 1,
        "manual_input_count": 2,
        "natural_time_count": 2,
        "next_operator_item_id": "production_pit_csv_drop",
        "next_operator_owner": "operator_data_vendor",
        "paper_or_live_unlock_allowed": False,
        "live_order_allowed": False,
    }
    assert payload["completion_audit"] == {
        "status": "completion_blocked",
        "phase_count": 7,
        "complete_count": 3,
        "in_progress_count": 3,
        "blocked_count": 1,
        "first_blocked_phase_id": "phase_1_data_hardening",
        "first_incomplete_phase_id": "phase_1_data_hardening",
        "first_incomplete_phase_status": "blocked",
        "first_blocker": "pit_procurement_missing:universe_membership_events.csv",
        "next_action": "Acquire licensed PIT bundle and keep daily data gates passing.",
        "completion_claim_allowed": False,
        "completion_dependency_blocked_count": 10,
        "operator_open_input_count": 5,
        "operator_external_input_count": 1,
        "operator_manual_input_count": 2,
        "operator_natural_time_count": 2,
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
    }
    assert payload["production_control_health"] == {
        "health_status": "pass",
        "checked_count": 5,
        "schema_invalid_count": 0,
        "missing_count": 0,
        "stale_count": 0,
        "path_escape_count": 0,
        "blockers": [],
        "promotion_safe": False,
    }
    assert payload["live_execution_readiness"]["status"] == "execution_readiness_blocked"
    assert payload["live_execution_readiness"]["drill_count"] == 5
    assert payload["live_execution_readiness"]["proven_count"] == 4
    assert payload["live_execution_readiness"]["blocked_count"] == 1
    assert payload["live_execution_readiness"]["live_order_allowed"] is False
    assert payload["live_execution_readiness"]["real_order_submitted"] is False
    assert payload["run_progress"]["status"] == "PASS"
    assert payload["run_progress"]["step_count"] == len(payload["steps"])
    assert payload["run_progress"]["passed_step_count"] == len(payload["steps"])
    assert payload["run_progress"]["failed_step_count"] == 0
    assert payload["run_progress"]["failed_step_ids"] == []
    assert payload["run_progress"]["production_line_status"] == "production_line_blocked_before_paper_or_live"
    assert payload["run_progress"]["production_line_next_action"] == "acquire_or_build_production_pit_data_bundle"
    assert payload["run_progress"]["next_action_owner"] == "operator_data_vendor"
    assert payload["run_progress"]["next_action_dependency_type"] == "external_input"
    assert payload["run_progress"]["next_action_actionability"] == "waiting"
    assert payload["run_progress"]["actionable_engineering_count"] == 0
    assert payload["run_progress"]["blocked_until_upstream_count"] == 5
    assert payload["run_progress"]["forward_observation_days"] == 1
    assert payload["run_progress"]["forward_minimum_days"] == 30
    assert payload["run_progress"]["forward_days_until_minimum"] == 29
    assert payload["run_progress"]["remediation_open_count"] == 2
    assert payload["run_progress"]["production_pit_ready_file_count"] == 0
    assert payload["run_progress"]["production_pit_required_file_count"] == 6
    assert payload["run_progress"]["operator_next_step_id"] == "copy_six_licensed_csv_files"
    assert payload["run_progress"]["operator_unblock_open_count"] == 5
    assert payload["run_progress"]["operator_unblock_external_input_count"] == 1
    assert payload["run_progress"]["operator_unblock_manual_input_count"] == 2
    assert payload["run_progress"]["operator_unblock_natural_time_count"] == 2
    assert payload["run_progress"]["completion_phase_count"] == 7
    assert payload["run_progress"]["completion_complete_count"] == 3
    assert payload["run_progress"]["completion_in_progress_count"] == 3
    assert payload["run_progress"]["completion_blocked_count"] == 1
    assert payload["run_progress"]["completion_first_incomplete_phase_id"] == "phase_1_data_hardening"
    assert payload["run_progress"]["completion_first_incomplete_phase_status"] == "blocked"
    assert payload["run_progress"]["completion_first_blocker"] == "pit_procurement_missing:universe_membership_events.csv"
    assert payload["run_progress"]["completion_next_action"] == "Acquire licensed PIT bundle and keep daily data gates passing."
    assert payload["run_progress"]["completion_claim_allowed"] is False
    assert payload["run_progress"]["completion_dependency_blocked_count"] == 10
    assert payload["run_progress"]["paper_or_live_unlock_allowed"] is False
    assert payload["run_progress"]["paper_simulation_allowed"] is False
    assert payload["run_progress"]["live_order_allowed"] is False
    tickets = {item["category"]: item for item in payload["remediation_tickets"]["tickets"]}
    assert tickets["external_data"]["owner"] == "operator_data_vendor"
    assert tickets["natural_time"]["status"] == "waiting_observation_window"
    assert {step["step_id"] for step in payload["steps"]} == {
        "etf_kline_quality_daily",
        "data_freshness_daily",
        "fred_macro_preflight",
        "candidate_bundle_evidence",
        "local_pit_file_discovery",
        "pit_procurement_readiness",
        "incoming_drop_readiness",
        "production_data_acquisition_plan",
        "local_csv_production_bundle_import",
        "production_bundle_intake_packet",
        "production_bundle_activation",
        "pit_data_intake_status",
        "pit_bundle_acceptance",
        "vendor_drop_operator_progress",
        "pit_operator_handoff",
        "vendor_drop_workspace_preparation",
        "vendor_drop_preflight",
        "vendor_drop_pipeline",
        "strategy_registry",
        "research_start_gate",
        "dual_momentum_design_spec",
        "absolute_momentum_design_spec",
        "topn_etf_rotation_design_spec",
        "regime_overlay_design_spec",
        "factor_momentum_quality_design_spec",
        "trading_strategies_151_migration_design_spec",
        "research_design_queue",
        "strategy_validation_gate",
        "strategy_validation_evidence_audit",
        "forward_observation_daily",
        "forward_observation_daily_health",
        "forward_observation_evaluation",
        "small_account_execution_preflight",
        "manual_decision_record",
        "manual_review_packet",
        "paper_simulation_readiness",
        "paper_simulation_roll",
        "paper_simulation_evaluation",
        "monitoring_rules",
        "order_reconciliation_drill",
        "manual_stop_reset_drill",
        "kill_switch_drill",
        "broker_credentials_review",
        "broker_credentials_handoff",
        "execution_drill_evidence",
        "live_readiness_risk_constitution",
        "standard_report_schema_audit",
        "replay_readiness",
        "development_plan_audit",
        "blocker_taxonomy",
        "remediation_ticket_closure",
        "strategy_production_line",
        "completion_dependency",
        "next_action_queue",
        "operator_unblock_packet",
        "completion_audit",
        "daily_monitoring",
        "production_control_health",
    }
    assert (tmp_path / "out/daily.json").exists()
    assert (tmp_path / "out/daily.md").exists()
    paper_step = next(step for step in payload["steps"] if step["step_id"] == "paper_simulation_readiness")
    assert paper_step["passed"] is True
    assert paper_step["status"] == "paper_simulation_blocked"
    assert "us_equity_paper_readiness_production_pit_intake_not_ready" in paper_step["blockers"]
    live_step = next(step for step in payload["steps"] if step["step_id"] == "live_readiness_risk_constitution")
    assert live_step["passed"] is True
    assert live_step["status"] == "live_readiness_blocked"
    assert "us_equity_live_readiness_max_live_principal_usd_not_set" in live_step["blockers"]
    validation_step = next(step for step in payload["steps"] if step["step_id"] == "strategy_validation_gate")
    assert validation_step["passed"] is True
    assert validation_step["status"] == "blocked_data_quality"
    schema_step = next(step for step in payload["steps"] if step["step_id"] == "standard_report_schema_audit")
    assert schema_step["passed"] is True
    assert schema_step["status"] == "schema_audit_pass"
    acceptance_step = next(step for step in payload["steps"] if step["step_id"] == "pit_bundle_acceptance")
    assert acceptance_step["passed"] is True
    assert acceptance_step["status"] == "acceptance_blocked"
    assert "source_universe_membership_events_file_missing" in acceptance_step["blockers"]
    health_step = next(step for step in payload["steps"] if step["step_id"] == "production_control_health")
    assert health_step["passed"] is True
    assert health_step["status"] == "pass"
    step_ids = [step["step_id"] for step in payload["steps"]]
    assert step_ids.index("candidate_bundle_evidence") < step_ids.index("vendor_drop_workspace_preparation")
    assert step_ids.index("vendor_drop_workspace_preparation") < step_ids.index("incoming_drop_readiness")
    assert step_ids.index("vendor_drop_workspace_preparation") < step_ids.index("local_pit_file_discovery")
    assert step_ids.index("local_pit_file_discovery") < step_ids.index("incoming_drop_readiness")
    assert step_ids.index("local_pit_file_discovery") < step_ids.index("pit_procurement_readiness")
    assert step_ids.index("pit_procurement_readiness") < step_ids.index("incoming_drop_readiness")
    assert step_ids.index("incoming_drop_readiness") < step_ids.index("production_data_acquisition_plan")
    assert step_ids.index("production_data_acquisition_plan") < step_ids.index("local_csv_production_bundle_import")
    assert step_ids.index("pit_bundle_acceptance") < step_ids.index("pit_data_intake_status")
    assert step_ids.index("pit_data_intake_status") < step_ids.index("vendor_drop_operator_progress")
    assert step_ids.index("vendor_drop_operator_progress") < step_ids.index("pit_operator_handoff")
    assert step_ids.index("pit_data_intake_status") < step_ids.index("pit_operator_handoff")
    assert step_ids.index("pit_operator_handoff") < step_ids.index("vendor_drop_preflight")
    assert step_ids.index("vendor_drop_preflight") < step_ids.index("vendor_drop_pipeline")
    assert step_ids.index("vendor_drop_pipeline") < step_ids.index("strategy_registry")
    assert step_ids.index("strategy_registry") < step_ids.index("research_start_gate")
    assert step_ids.index("research_start_gate") < step_ids.index("dual_momentum_design_spec")
    assert step_ids.index("dual_momentum_design_spec") < step_ids.index("absolute_momentum_design_spec")
    assert step_ids.index("absolute_momentum_design_spec") < step_ids.index("topn_etf_rotation_design_spec")
    assert step_ids.index("topn_etf_rotation_design_spec") < step_ids.index("regime_overlay_design_spec")
    assert step_ids.index("regime_overlay_design_spec") < step_ids.index("factor_momentum_quality_design_spec")
    assert step_ids.index("factor_momentum_quality_design_spec") < step_ids.index("trading_strategies_151_migration_design_spec")
    assert step_ids.index("trading_strategies_151_migration_design_spec") < step_ids.index("research_design_queue")
    assert step_ids.index("research_design_queue") < step_ids.index("strategy_validation_gate")
    assert step_ids.index("strategy_validation_gate") < step_ids.index("strategy_validation_evidence_audit")
    assert step_ids.index("strategy_validation_evidence_audit") < step_ids.index("forward_observation_daily")
    assert step_ids.index("blocker_taxonomy") < step_ids.index("remediation_ticket_closure")
    assert step_ids.index("remediation_ticket_closure") < step_ids.index("strategy_production_line")
    assert step_ids.index("strategy_production_line") < step_ids.index("completion_dependency")
    assert step_ids.index("completion_dependency") < step_ids.index("next_action_queue")
    assert step_ids.index("next_action_queue") < step_ids.index("operator_unblock_packet")
    assert step_ids.index("operator_unblock_packet") < step_ids.index("completion_audit")
    assert step_ids.index("completion_audit") < step_ids.index("daily_monitoring")
    assert step_ids.index("daily_monitoring") < step_ids.index("production_control_health")
    assert step_ids.index("forward_observation_evaluation") < step_ids.index("small_account_execution_preflight")
    assert step_ids.index("small_account_execution_preflight") < step_ids.index("manual_decision_record")
    assert step_ids.index("manual_decision_record") < step_ids.index("manual_review_packet")
    assert step_ids.index("small_account_execution_preflight") < step_ids.index("manual_review_packet")
    assert step_ids.index("small_account_execution_preflight") < step_ids.index("paper_simulation_readiness")
    assert step_ids.index("paper_simulation_readiness") < step_ids.index("paper_simulation_roll")
    assert step_ids.index("paper_simulation_roll") < step_ids.index("paper_simulation_evaluation")
    assert step_ids.index("paper_simulation_evaluation") < step_ids.index("monitoring_rules")
    assert step_ids.index("monitoring_rules") < step_ids.index("order_reconciliation_drill")
    assert step_ids.index("order_reconciliation_drill") < step_ids.index("manual_stop_reset_drill")
    assert step_ids.index("manual_stop_reset_drill") < step_ids.index("kill_switch_drill")
    assert step_ids.index("kill_switch_drill") < step_ids.index("broker_credentials_review")
    assert step_ids.index("broker_credentials_review") < step_ids.index("broker_credentials_handoff")
    assert step_ids.index("broker_credentials_handoff") < step_ids.index("execution_drill_evidence")
    assert step_ids.index("paper_simulation_readiness") < step_ids.index("execution_drill_evidence")
    assert step_ids.index("paper_simulation_roll") < step_ids.index("execution_drill_evidence")
    assert step_ids.index("paper_simulation_evaluation") < step_ids.index("execution_drill_evidence")
    assert step_ids.index("execution_drill_evidence") < step_ids.index("live_readiness_risk_constitution")


def test_daily_production_line_blocks_when_data_freshness_fails(tmp_path: Path) -> None:
    fns = _fake_fns()
    fns["data_freshness_fn"] = _fn({"status": "blocked", "blockers": ["prices_stale"], "guardrails": _safe_guardrails()})

    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **fns,
    )

    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert "us_equity_daily_step_not_safe:data_freshness_daily:blocked" in payload["blockers"]
    assert "prices_stale" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_daily_production_line_surfaces_registry_source_report_contract_failure(tmp_path: Path) -> None:
    fns = _fake_fns()
    fns["strategy_registry_fn"] = _fn(
        {
            "status": "blocked",
            "blockers": ["us_equity_strategy_registry_formal_source_report_contract_failed:test_strategy"],
            "formal_candidate_count": 1,
            "formal_candidate_source_report_contract": {
                "passed": False,
                "missing_required_keys_by_strategy": {"test_strategy": ["data_ingestion"]},
                "missing_paths_by_strategy": {},
            },
            "guardrails": _safe_guardrails(),
        }
    )

    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **fns,
    )

    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert payload["strategy_registry_contract"]["source_report_contract_passed"] is False
    assert payload["strategy_registry_contract"]["missing_required_keys_by_strategy"] == {
        "test_strategy": ["data_ingestion"]
    }
    assert "us_equity_daily_step_not_safe:strategy_registry:blocked" in payload["blockers"]
    assert (
        "us_equity_strategy_registry_formal_source_report_contract_failed:test_strategy"
        in payload["blockers"]
    )
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_daily_production_line_blocks_unsafe_live_flag(tmp_path: Path) -> None:
    fns = _fake_fns()
    fns["forward_daily_fn"] = _fn({"status": "PASS", "blockers": [], "guardrails": {**_safe_guardrails(), "live_order_allowed": True}})

    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **fns,
    )

    assert payload["status"] == "BLOCKED"
    _validate_schema(payload)
    assert any(item.startswith("unsafe_flag:forward_observation_daily.guardrails.live_order_allowed=true") for item in payload["blockers"])


def test_daily_production_line_schema_rejects_paper_or_live_unlock_flag(tmp_path: Path) -> None:
    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **_fake_fns(),
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def test_daily_production_line_schema_rejects_live_order_flag(tmp_path: Path) -> None:
    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **_fake_fns(),
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_daily_production_line_schema_rejects_run_progress_unlock(tmp_path: Path) -> None:
    payload = run_us_equity_daily_production_line(
        repo_root=tmp_path,
        output=Path("out/daily.json"),
        markdown_output=Path("out/daily.md"),
        generated_at="2026-06-25T00:00:00Z",
        **_fake_fns(),
    )
    payload["run_progress"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted run_progress.paper_or_live_unlock_allowed=true")


def _fake_fns() -> dict[str, Any]:
    return {
        "kline_quality_fn": _fn({"status": "warn", "warnings": ["DBMF:thin_volume"], "blockers": [], "guardrails": _safe_guardrails()}),
        "data_freshness_fn": _fn({"status": "pass", "blockers": [], "guardrails": _safe_guardrails()}),
        "fred_preflight_fn": _fn({"status": "fred_macro_preflight_warn", "warnings": ["fred_release_calendar_missing"], "blockers": [], "guardrails": _safe_guardrails()}),
        "candidate_bundle_evidence_fn": _fn({"status": "candidate_evidence_ready_for_manual_bundle_build", "blockers": ["research_data_not_point_in_time_bundle"], "guardrails": _safe_guardrails()}),
        "local_pit_file_discovery_fn": _fn(
            {
                "status": "pit_file_discovery_no_complete_candidate_set",
                "ready_for_copy_count": 0,
                "required_file_count": 6,
                "missing_filenames": [
                    "universe_membership_events.csv",
                    "delisted_symbols.csv",
                    "corporate_actions.csv",
                    "symbol_mapping.csv",
                    "adjustment_replay.csv",
                    "macro_release_calendar.csv",
                ],
                "blockers": [],
                "guardrails": {
                    **_safe_guardrails(),
                    "discovery_only": True,
                    "files_copied": False,
                    "vendor_data_imported": False,
                    "configuration_mutated_by_this_report": False,
                    "license_reviewed_by_this_report": False,
                    "promotion_clean_granted_by_this_report": False,
                },
            }
        ),
        "pit_procurement_readiness_fn": _fn(
            {
                "status": "pit_procurement_ready_for_vendor_order",
                "summary": {
                    "required_file_count": 6,
                    "ready_for_manual_license_review_count": 0,
                    "missing_file_count": 6,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                },
                "missing_filenames": [
                    "universe_membership_events.csv",
                    "delisted_symbols.csv",
                    "corporate_actions.csv",
                    "symbol_mapping.csv",
                    "adjustment_replay.csv",
                    "macro_release_calendar.csv",
                ],
                "blockers": [
                    "pit_procurement_missing:universe_membership_events.csv",
                    "pit_procurement_missing:delisted_symbols.csv",
                ],
                "guardrails": {
                    **_safe_guardrails(),
                    "procurement_readiness_only": True,
                    "files_copied": False,
                    "vendor_data_imported": False,
                    "configuration_mutated_by_this_report": False,
                    "license_reviewed_by_this_report": False,
                    "promotion_clean_granted_by_this_report": False,
                },
            }
        ),
        "incoming_drop_readiness_fn": _fn({"status": "incoming_drop_blocked", "blockers": ["source_universe_membership_events_file_missing"], "guardrails": _safe_guardrails()}),
        "production_data_acquisition_fn": _fn(
            {
                "status": "production_data_acquisition_required",
                "blockers": ["point_in_time_universe_not_confirmed"],
                "current_drop_readiness": {
                    "status": "incoming_drop_blocked",
                    "ready_file_count": 0,
                    "required_file_count": 6,
                    "first_blocker": "source_universe_membership_events_file_missing",
                },
                "guardrails": _safe_guardrails(),
            }
        ),
        "local_csv_bundle_import_fn": _fn({"status": "production_bundle_import_blocked", "blockers": ["source_universe_membership_events_file_missing"], "guardrails": _safe_guardrails()}),
        "production_bundle_intake_fn": _fn({"status": "intake_packet_ready_for_data_vendor_drop", "blockers": [], "guardrails": _safe_guardrails()}),
        "production_bundle_activation_fn": _fn({"status": "activation_blocked", "blockers": ["production_bundle_missing"], "guardrails": _safe_guardrails()}),
        "pit_data_intake_status_fn": _fn({"status": "production_pit_data_intake_blocked", "blockers": ["source_universe_membership_events_file_missing"], "guardrails": _safe_guardrails()}),
        "pit_bundle_acceptance_fn": _fn({"status": "acceptance_blocked", "blockers": ["source_universe_membership_events_file_missing"], "guardrails": _safe_guardrails()}),
        "vendor_drop_operator_progress_fn": _fn(
            {
                "status": "operator_drop_blocked",
                "completed_count": 3,
                "blocked_count": 2,
                "pending_count": 2,
                "step_count": 7,
                "next_step_id": "copy_six_licensed_csv_files",
                "next_action": "manual_file_copy",
                "blockers": [
                    "operator_drop_step_blocked:copy_six_licensed_csv_files:required_csv_files_not_ready",
                    "operator_drop_step_blocked:run_incoming_drop_readiness:required_csv_files_not_ready",
                ],
                "guardrails": _safe_guardrails(),
            }
        ),
        "pit_operator_handoff_fn": _fn({"status": "handoff_blocked", "blockers": ["source_universe_membership_events_file_missing"], "operator_next_actions": ["Copy six licensed CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop"], "guardrails": _safe_guardrails()}),
        "vendor_drop_workspace_fn": _fn(
            {
                "status": "vendor_drop_workspace_prepared",
                "blockers": [],
                "guardrails": _safe_guardrails(),
            }
        ),
        "vendor_drop_preflight_fn": _fn(
            {
                "status": "vendor_drop_preflight_waiting_for_vendor_files",
                "blockers": ["universe_membership_events_csv_missing"],
                "guardrails": _safe_guardrails(),
            }
        ),
        "vendor_drop_pipeline_fn": _fn(
            {
                "status": "vendor_drop_pipeline_blocked",
                "current_blocking_step": "vendor_drop_preflight",
                "license_reviewed": False,
                "blockers": [
                    "vendor_drop_pipeline_step_not_passed:vendor_drop_preflight:vendor_drop_preflight_waiting_for_vendor_files",
                    "universe_membership_events_csv_missing",
                ],
                "unsafe_flags": [],
                "guardrails": _safe_guardrails(),
            }
        ),
        "strategy_registry_fn": _fn(
            {
                "status": "pass",
                "blockers": [],
                "formal_candidate_count": 1,
                "formal_candidate_source_report_contract": {
                    "passed": True,
                    "missing_required_keys_by_strategy": {},
                    "missing_paths_by_strategy": {},
                },
                "guardrails": _safe_guardrails(),
            }
        ),
        "research_start_gate_fn": _fn(
            {
                "status": "research_design_only",
                "blockers": [
                    "us_equity_research_start_production_pit_intake_not_ready",
                    "us_equity_research_start_pit_bundle_acceptance_not_ready",
                ],
                "formal_research_allowed_count": 0,
                "hypothesis_design_only_count": 6,
                "guardrails": _safe_guardrails(),
            }
        ),
        "dual_momentum_design_spec_fn": _fn(
            {
                "status": "design_spec_ready",
                "blockers": [],
                "registry_strategy_id": "us_equity_dual_momentum_research_placeholder",
                "guardrails": _safe_guardrails(),
            }
        ),
        "absolute_momentum_design_spec_fn": _fn(
            {
                "status": "design_spec_ready",
                "blockers": [],
                "registry_strategy_id": "us_equity_absolute_momentum_research_placeholder",
                "guardrails": _safe_guardrails(),
            }
        ),
        "topn_etf_rotation_design_spec_fn": _fn(
            {
                "status": "design_spec_ready",
                "blockers": [],
                "registry_strategy_id": "us_equity_etf_topn_rotation_research_placeholder",
                "guardrails": _safe_guardrails(),
            }
        ),
        "regime_overlay_design_spec_fn": _fn(
            {
                "status": "design_spec_ready",
                "blockers": [],
                "registry_strategy_id": "us_equity_regime_overlay_research_placeholder",
                "guardrails": _safe_guardrails(),
            }
        ),
        "factor_momentum_quality_design_spec_fn": _fn(
            {
                "status": "design_spec_ready",
                "blockers": [],
                "registry_strategy_id": "us_equity_factor_momentum_quality_research_placeholder",
                "guardrails": _safe_guardrails(),
            }
        ),
        "trading_strategies_151_migration_design_spec_fn": _fn(
            {
                "status": "design_spec_ready",
                "blockers": [],
                "registry_strategy_id": "us_equity_151_trading_strategies_candidate_research_placeholder",
                "guardrails": _safe_guardrails(),
            }
        ),
        "research_design_queue_fn": _fn(
            {
                "status": "research_design_queue_ready",
                "blockers": [],
                "design_ready_count": 6,
                "waiting_for_production_data_count": 1,
                "guardrails": _safe_guardrails(),
            }
        ),
        "strategy_validation_gate_fn": _fn({"status": "blocked_data_quality", "blockers": ["us_etf_strategy_validation_data_coverage_and_quality_failed"], "guardrails": _safe_guardrails(), "live_order_allowed": False, "real_order_submitted": False}),
        "strategy_validation_evidence_audit_fn": _fn(
            {
                "status": "validation_evidence_audit_blocked_data_quality",
                "gate_status": "blocked_data_quality",
                "summary": {
                    "requirement_count": 12,
                    "complete_count": 11,
                    "blocked_count": 1,
                    "incomplete_count": 0,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                },
                "blockers": ["validation_gate_check_failed:data_coverage_and_quality"],
                "guardrails": {
                    **_safe_guardrails(),
                    "audit_only": True,
                    "validation_evidence_audit_is_not_execution_permission": True,
                    "strategy_parameters_mutated": False,
                },
            }
        ),
        "forward_daily_fn": _fn({"status": "PASS", "blockers": [], "guardrails": _safe_guardrails(), "forward_observation": {"observation_days": 1}}),
        "forward_health_fn": _fn(
            {
                "status": "daily_health_pass",
                "blockers": [],
                "observation_days": 1,
                "minimum_complete_days": 30,
                "latest_observation_date": "2026-06-24",
                "observation_continuity": {
                    "passed": True,
                    "unique_observation_days": 1,
                    "max_calendar_gap_days": 0,
                    "duplicate_target_dates": [],
                    "duplicate_snapshot_dates": [],
                    "missing_snapshot_for_target": [],
                    "missing_target_for_snapshot": [],
                },
                "guardrails": _safe_guardrails(),
            }
        ),
        "forward_evaluation_fn": _fn({"status": "forward_observing", "blockers": [], "metrics": {"observation_days": 1}, "guardrails": _safe_guardrails()}),
        "small_account_preflight_fn": _fn(
            {
                "status": "pass_observation_only",
                "blockers": [],
                "account_equity": 10000.0,
                "guardrails": {
                    **_safe_guardrails(),
                    "simulated_only": True,
                    "not_a_broker_order": True,
                    "initial_live_leverage_default": 1.0,
                    "research_cap_1_5x_not_live_default": True,
                },
            }
        ),
        "manual_decision_record_fn": _fn(
            {
                "status": "manual_decision_record_missing_or_invalid",
                "blockers": ["us_equity_manual_decision_record_missing"],
                "guardrails": {
                    **_safe_guardrails(),
                    "decision_record_validator_only": True,
                    "secrets_allowed": False,
                },
            }
        ),
        "manual_review_fn": _fn({"status": "manual_review_pending", "blockers": ["forward_not_complete"], "guardrails": _safe_guardrails()}),
        "paper_simulation_readiness_fn": _fn({"status": "paper_simulation_blocked", "blockers": ["us_equity_paper_readiness_production_pit_intake_not_ready"], "guardrails": _safe_guardrails()}),
        "paper_simulation_roll_fn": _fn(
            {
                "status": "BLOCKED",
                "cycle_status": "NOT_RUN",
                "blockers": ["us_equity_paper_simulation_readiness_not_ready"],
                "guardrails": _safe_guardrails(),
            }
        ),
        "paper_simulation_evaluation_fn": _fn(
            {
                "status": "paper_simulation_not_started",
                "blockers": ["us_equity_paper_simulation_ledger_root_missing"],
                "guardrails": _safe_guardrails(),
            }
        ),
        "monitoring_rules_fn": _fn({"status": "monitoring_rules_defined", "blockers": [], "guardrails": _safe_guardrails()}),
        "order_reconciliation_drill_fn": _fn(
            {
                "status": "order_reconciliation_drill_proven",
                "blocked_count": 0,
                "reconciliation": {
                    "cash_recomputable": True,
                    "positions_recomputable": True,
                    "fees_recomputable": True,
                },
                "blockers": [],
                "guardrails": _safe_guardrails(),
            }
        ),
        "manual_stop_reset_drill_fn": _fn(
            {
                "status": "manual_stop_reset_proven",
                "event_count": 4,
                "checklist_count": 6,
                "blockers": [],
                "guardrails": _safe_guardrails(),
            }
        ),
        "kill_switch_drill_fn": _fn(
            {
                "status": "kill_switch_drill_proven",
                "scenario_count": 5,
                "proven_count": 5,
                "blocked_count": 0,
                "blockers": [],
                "guardrails": _safe_guardrails(),
            }
        ),
        "broker_credentials_review_fn": _fn(
            {
                "status": "broker_credentials_review_blocked",
                "blockers": ["broker_credentials_review_input_missing"],
                "guardrails": _safe_guardrails(),
            }
        ),
        "broker_credentials_handoff_fn": _fn(
            {
                "status": "broker_credentials_handoff_blocked",
                "blockers": ["broker_credentials_local_review_missing"],
                "guardrails": _safe_guardrails(),
            }
        ),
        "execution_drill_evidence_fn": _fn(
            {
                "status": "execution_drill_evidence_partial",
                "drill_count": 5,
                "proven_count": 4,
                "blocked_count": 1,
                "blockers": [
                    "broker_credentials_manual_review_not_recorded",
                ],
                "guardrails": _safe_guardrails(),
            }
        ),
        "live_readiness_fn": _fn(
            {
                "status": "live_readiness_blocked",
                "blockers": ["us_equity_live_readiness_max_live_principal_usd_not_set"],
                "live_order_allowed": False,
                "real_order_submitted": False,
                "execution_readiness": {
                    "status": "execution_readiness_blocked",
                    "drill_count": 5,
                    "proven_count": 4,
                    "blocked_count": 1,
                },
                "guardrails": _safe_guardrails(),
            }
        ),
        "standard_schema_audit_fn": _fn({"status": "schema_audit_pass", "blockers": [], "guardrails": _safe_guardrails()}),
        "replay_readiness_fn": _fn({"status": "replay_readiness_pass", "blockers": [], "guardrails": _safe_guardrails()}),
        "development_plan_audit_fn": _fn({"status": "development_plan_blocked_by_production_pit_data", "blockers": ["production_bundle_missing"], "guardrails": _safe_guardrails()}),
        "blocker_taxonomy_fn": _fn(
            {
                "status": "blocked_external_and_time_dependencies",
                "blockers": [],
                "remediation_tickets": [
                    {
                        "ticket_id": "us_equity_remediate_external_data",
                        "category": "external_data",
                        "owner": "operator_data_vendor",
                        "dependency_type": "external_user_action",
                        "status": "waiting_external_input",
                        "blocker_count": 3,
                        "source_reports": ["development_audit", "pit_handoff"],
                        "next_action": "Place production PIT files into the manual vendor drop.",
                        "acceptance_evidence": ["pit intake ready"],
                    },
                    {
                        "ticket_id": "us_equity_remediate_natural_time",
                        "category": "natural_time",
                        "owner": "daily_forward_observation_scheduler",
                        "dependency_type": "natural_time",
                        "status": "waiting_observation_window",
                        "blocker_count": 1,
                        "source_reports": ["live_readiness"],
                        "next_action": "Keep forward observation running.",
                        "acceptance_evidence": ["30 observation days complete"],
                    },
                ],
                "guardrails": _safe_guardrails(),
            }
        ),
        "remediation_ticket_closure_fn": _fn(
            {
                "status": "remediation_tickets_open",
                "ticket_count": 2,
                "open_count": 2,
                "closed_count": 0,
                "missing_sources": [],
                "blockers": [
                    "us_equity_remediation_ticket_open:us_equity_remediate_external_data",
                    "us_equity_remediation_ticket_open:us_equity_remediate_natural_time",
                ],
                "guardrails": _safe_guardrails(),
            }
        ),
        "production_line_fn": _fn(
            {
                "status": "production_line_blocked_before_paper_or_live",
                "primary_strategy_id": "primary",
                "strategies": [
                    {
                        "strategy_id": "primary",
                        "stages": [
                            {
                                "stage_id": "data_quality_pit_check",
                                "evidence": {
                                    "production_data_acquisition_current_drop_status": "incoming_drop_blocked",
                                    "production_data_acquisition_current_drop_ready_file_count": 0,
                                    "production_data_acquisition_current_drop_required_file_count": 6,
                                    "production_data_acquisition_current_drop_first_blocker": "source_universe_membership_events_file_missing",
                                    "production_data_acquisition_contract_ready_table_count": 0,
                                    "production_data_acquisition_contract_blocked_table_count": 6,
                                },
                            }
                        ],
                    }
                ],
                "blockers": ["data_lineage_not_promotion_clean"],
                "pipeline_progress": {
                    "next_action": "acquire_or_build_production_pit_data_bundle",
                },
                "guardrails": _safe_guardrails(),
            }
        ),
        "completion_dependency_fn": _fn(
            {
                "status": "completion_dependencies_blocked",
                "blockers": ["production_pit_data_not_ready"],
                "guardrails": _safe_guardrails(),
            }
        ),
        "next_action_queue_fn": _fn(
            {
                "status": "next_actions_open",
                "summary": {
                    "actionable_engineering_count": 0,
                    "blocked_until_upstream_count": 5,
                },
                "next_action": {
                    "action_id": "us_equity_action_production_pit_data",
                    "owner": "operator_data_vendor",
                    "dependency_type": "external_input",
                    "actionability": "waiting",
                    "evidence": {
                        "missing_file_count": 2,
                        "required_operator_inputs": [
                            {
                                "filename": "universe_membership_events.csv",
                                "target_path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/universe_membership_events.csv",
                                "table": "universe_membership_events",
                                "blocker": "universe_membership_events_csv_missing",
                                "required_fields": ["security_id", "ticker"],
                            },
                            {
                                "filename": "delisted_symbols.csv",
                                "target_path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/delisted_symbols.csv",
                                "table": "delisted_symbols",
                                "blocker": "delisted_symbols_csv_missing",
                                "required_fields": ["security_id", "ticker", "delisting_date"],
                            },
                        ],
                        "operator_command_sequence": [
                            "python scripts/build_us_equity_manual_vendor_drop_package.py",
                            "copy licensed PIT CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop",
                            "manually confirm license review for the copied PIT CSV files",
                            "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
                        ],
                    },
                },
                "blockers": [],
                "guardrails": _safe_guardrails(),
            }
        ),
        "operator_unblock_packet_fn": _fn(
            {
                "status": "operator_unblock_open",
                "summary": {
                    "open_count": 5,
                    "external_input_count": 1,
                    "manual_input_count": 2,
                    "natural_time_count": 2,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                },
                "next_operator_action": {
                    "item_id": "production_pit_csv_drop",
                    "owner": "operator_data_vendor",
                },
                "blockers": [],
                "guardrails": {
                    **_safe_guardrails(),
                    "operator_packet_only": True,
                    "files_copied": False,
                    "local_review_mutated": False,
                    "strategy_parameters_mutated": False,
                },
            }
        ),
        "completion_audit_fn": _fn(
            {
                "status": "completion_blocked",
                "summary": {
                    "phase_count": 7,
                    "complete_count": 3,
                    "in_progress_count": 3,
                    "blocked_count": 1,
                    "first_incomplete_phase_id": "phase_1_data_hardening",
                    "first_incomplete_phase_status": "blocked",
                    "first_blocker": "pit_procurement_missing:universe_membership_events.csv",
                    "next_action": "Acquire licensed PIT bundle and keep daily data gates passing.",
                    "completion_claim_allowed": False,
                    "completion_dependency_blocked_count": 10,
                    "operator_open_input_count": 5,
                    "operator_external_input_count": 1,
                    "operator_manual_input_count": 2,
                    "operator_natural_time_count": 2,
                    "paper_or_live_unlock_allowed": False,
                    "paper_simulation_allowed": False,
                    "live_order_allowed": False,
                },
                "phases": [
                    {
                        "phase_id": "phase_1_data_hardening",
                        "status": "blocked",
                        "blockers": ["pit_procurement_missing:universe_membership_events.csv"],
                        "next_action": "Acquire licensed PIT bundle and keep daily data gates passing.",
                    }
                ],
                "blockers": ["source_universe_membership_events_file_missing"],
                "guardrails": {
                    **_safe_guardrails(),
                    "audit_only": True,
                    "strategy_parameters_mutated": False,
                },
            }
        ),
        "daily_monitoring_fn": _fn(
            {
                "status": "daily_monitoring_blocked",
                "summary": {
                    "operator_action_count": 5,
                    "status_diff_count": 1,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                },
                "operator_queue": [
                    {
                        "item_id": "us_equity_action_production_pit_data",
                        "owner": "operator_data_vendor",
                        "severity": "block",
                        "reason": "source_universe_membership_events_file_missing",
                        "next_action": "Place production PIT files into the manual vendor drop.",
                        "recommended_command": "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
                        "evidence_path": "completion_dependency",
                        "source_report": "next_action_queue",
                    }
                ],
                "blockers": ["us_equity_daily_monitoring_operator_queue_open"],
                "guardrails": {
                    **_safe_guardrails(),
                    "monitoring_only": True,
                    "strategy_parameters_mutated": False,
                },
            }
        ),
        "production_control_health_fn": _fn(
            {
                "schema_version": "artifact_health_report_v1",
                "generated_at": "2026-06-25T00:00:00Z",
                "health_status": "pass",
                "checked_artifacts": [
                    {"name": "us_equity_daily_production_line", "schema_valid": True, "blockers": []},
                    {"name": "us_equity_completion_dependency", "schema_valid": True, "blockers": []},
                    {"name": "us_equity_completion_audit", "schema_valid": True, "blockers": []},
                    {"name": "us_equity_next_action_queue", "schema_valid": True, "blockers": []},
                    {"name": "us_equity_standard_report_schema_audit", "schema_valid": True, "blockers": []},
                ],
                "missing_artifacts": [],
                "schema_invalid_artifacts": [],
                "stale_artifacts": [],
                "path_escape_risks": [],
                "hash_mismatch_artifacts": [],
                "promotion_safe": False,
                "blockers": [],
                "outputs": {
                    "json": "artifacts/artifact_health/latest/us_equity_production_control_health_report.json"
                },
            }
        ),
    }


def _fn(payload: dict[str, Any]):
    def inner(**_: Any) -> dict[str, Any]:
        return payload

    return inner


def _safe_guardrails() -> dict[str, bool]:
    return {
        "paper_or_live_unlock_allowed": False,
        "paper_simulation_allowed": False,
        "live_order_allowed": False,
        "private_endpoint_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_allowed": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "broker_calls_used": False,
    }


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
