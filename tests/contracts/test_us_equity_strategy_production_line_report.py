from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_strategy_production_line_report import (
    STAGE_ORDER,
    build_us_equity_strategy_production_line_report,
)


SCHEMA = Path("schemas/us_equity_strategy_production_line_report.schema.json")


def test_strategy_production_line_rules_live_in_monitoring_service() -> None:
    assert build_us_equity_strategy_production_line_report.__module__ == "quant_us.monitoring.strategy_production_line"


def test_us_equity_production_line_blocks_without_registry(tmp_path: Path) -> None:
    payload = build_us_equity_strategy_production_line_report(
        repo_root=tmp_path,
        registry_path=Path("configs/strategies/missing.json"),
        output=Path("out/report.json"),
        markdown_output=Path("out/report.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "production_line_registry_missing"
    _validate_schema(payload)
    assert payload["production_line_order"] == STAGE_ORDER
    assert payload["paper_simulation_allowed"] is False
    assert payload["live_order_allowed"] is False
    assert payload["architecture_layer_contract"]["paper_or_live_unlock_allowed"] is False
    assert payload["architecture_layer_contract"]["guardrails"]["strategy_broker_adapter_allowed"] is False
    assert "us_equity_strategy_registry_missing" in payload["blockers"]
    assert payload["primary_evidence_chain"]["status"] == "missing_primary_strategy"
    assert payload["primary_evidence_chain"]["paper_or_live_unlock_allowed"] is False
    assert (tmp_path / "out/report.json").exists()
    assert (tmp_path / "out/report.md").exists()


def test_us_equity_production_line_keeps_forward_observation_separate_from_validation(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)

    payload = build_us_equity_strategy_production_line_report(
        repo_root=tmp_path,
        output=Path("out/report.json"),
        markdown_output=Path("out/report.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    primary = payload["strategies"][0]
    stages = {stage["stage_id"]: stage for stage in primary["stages"]}

    assert payload["schema_version"] == "us_equity_strategy_production_line_report_v1"
    _validate_schema(payload)
    assert payload["production_line_order"] == STAGE_ORDER
    assert payload["status"] == "production_line_blocked_before_paper_or_live"
    assert payload["guardrails"]["forward_observation_is_not_strategy_validation"] is True
    assert payload["paper_simulation_allowed"] is False
    assert payload["live_order_allowed"] is False
    assert payload["primary_evidence_chain"]["paper_or_live_unlock_allowed"] is False
    assert payload["primary_evidence_chain"]["status"] == "evidence_chain_incomplete"
    assert payload["primary_evidence_chain"]["chain_complete_for_manual_review"] is False
    assert payload["pipeline_progress"]["status"] == "production_line_blocked_before_paper_or_live"
    assert payload["pipeline_progress"]["strategy_count"] == payload["strategy_count"]
    assert payload["pipeline_progress"]["primary_strategy_id"] == payload["primary_strategy_id"]
    assert payload["pipeline_progress"]["primary_stage_counts"]["pass"] >= 1
    assert payload["pipeline_progress"]["primary_stage_counts"]["blocked"] >= 1
    phase_progress = {item["phase_id"]: item for item in payload["pipeline_progress"]["development_phase_progress"]}
    assert phase_progress["phase_1_data_lineage_hardening"]["status"] == "blocked_external_data"
    assert phase_progress["phase_1_data_lineage_hardening"]["first_blocker"] == "production_bundle_missing"
    assert phase_progress["phase_1_data_lineage_hardening"]["next_step_id"] == "copy_six_licensed_csv_files"
    assert phase_progress["phase_3_forward_observation_evaluation"]["status"] == "observing"
    assert phase_progress["phase_3_forward_observation_evaluation"]["observation_days"] == 1
    assert phase_progress["phase_3_forward_observation_evaluation"]["minimum_complete_days"] == 30
    assert payload["pipeline_progress"]["remediation_closure"]["ticket_count"] == 2
    assert payload["pipeline_progress"]["remediation_closure"]["open_count"] == 2
    assert payload["pipeline_progress"]["next_action"] == "acquire_or_build_production_pit_data_bundle"
    assert payload["pipeline_progress"]["paper_or_live_unlock_allowed"] is False
    assert payload["pipeline_progress"]["paper_simulation_allowed"] is False
    assert payload["pipeline_progress"]["live_order_allowed"] is False
    architecture_contract = payload["architecture_layer_contract"]
    assert architecture_contract["status"] == "defined_fail_closed"
    assert architecture_contract["allowed_flow"] == [
        "data",
        "signal",
        "portfolio",
        "risk",
        "order_intent",
        "simulated_fill",
        "ledger",
        "report",
    ]
    contract_layers = {layer["layer_id"]: layer for layer in architecture_contract["layers"]}
    assert set(contract_layers) == {"strategy", "portfolio", "risk", "backtest", "execution", "entrypoints"}
    assert contract_layers["strategy"]["allowed_outputs"] == ["Signal", "Forecast", "TargetPosition"]
    assert "broker adapter" in contract_layers["strategy"]["forbidden_dependencies"]
    assert contract_layers["portfolio"]["required_controls"] == [
        "volatility",
        "sector/style exposure",
        "turnover",
        "liquidity",
        "cost stress",
    ]
    assert contract_layers["risk"]["allowed_outputs"] == ["RiskDecision"]
    assert contract_layers["risk"]["required_position"] == "between target position and order intent"
    assert contract_layers["backtest"]["pnl_source"] == "fills_positions_cash_ledger"
    assert "partial fill" in contract_layers["execution"]["oms_responsibilities"]
    assert "core strategy rules" in contract_layers["entrypoints"]["forbidden_responsibilities"]
    assert architecture_contract["guardrails"] == {
        "strategy_broker_adapter_allowed": False,
        "portfolio_can_bypass_risk": False,
        "risk_decision_required_before_order_intent": True,
        "backtest_price_only_pnl_allowed": False,
        "execution_accepts_unapproved_intents": False,
        "scripts_own_core_business_rules": False,
    }
    chain_nodes = {node["node_id"]: node for node in payload["primary_evidence_chain"]["nodes"]}
    assert chain_nodes["strategy_card"]["status"] == "pass"
    assert chain_nodes["strategy_validation_gate"]["status"] == "blocked"
    assert chain_nodes["forward_observation"]["status"] == "observing"
    assert chain_nodes["forward_observation"]["evidence"]["not_alpha_validation"] is True
    assert chain_nodes["manual_review"]["status"] == "manual_review_required"
    assert payload["development_plan_audit"]["status"] == "development_plan_blocked_by_production_pit_data"
    assert payload["remediation_tickets"]["source_status"] == "blocked_external_and_time_dependencies"
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
    assert payload["remediation_ticket_closure"]["open_ticket_ids"] == [
        "us_equity_remediate_external_data",
        "us_equity_remediate_natural_time",
    ]
    tickets = {item["category"]: item for item in payload["remediation_tickets"]["tickets"]}
    assert tickets["external_data"]["owner"] == "operator_data_vendor"
    assert tickets["natural_time"]["status"] == "waiting_observation_window"
    assert "acquire_or_build_production_pit_data_bundle" in payload["next_actions"]
    assert stages["data_ingestion"]["status"] == "pass"
    assert stages["standardized_backtest"]["status"] == "pass"
    assert stages["cost_liquidity_capacity_stress"]["status"] == "pass"
    assert stages["walk_forward_parameter_stability"]["evidence"]["parameter_stability_status"] == "research_only_manual_review_required"
    assert stages["forward_observation"]["status"] == "observing"
    assert stages["forward_observation"]["evidence"]["scope"]["not_alpha_validation"] is True
    assert stages["forward_observation"]["evidence"]["alpha_validation"]["alpha_validated"] is False
    assert stages["forward_observation"]["evidence"]["operational_checks_status"] == "PASS"
    assert stages["forward_observation"]["evidence"]["evaluation_status"] == "forward_observing"
    assert stages["forward_observation"]["evidence"]["daily_health_status"] == "daily_health_pass"
    assert stages["data_quality_pit_check"]["status"] == "blocked"
    assert stages["data_quality_pit_check"]["evidence"]["freshness_status"] == "blocked"
    assert stages["data_quality_pit_check"]["evidence"]["etf_kline_quality_status"] == "warn"
    assert stages["data_quality_pit_check"]["evidence"]["fred_macro_preflight_status"] == "fred_macro_preflight_warn"
    assert stages["data_quality_pit_check"]["evidence"]["data_source_reconciliation_status"] == "research_reconciled_promotion_blocked"
    assert stages["data_quality_pit_check"]["evidence"]["data_source_selected_price_source"] == "tiingo_eod"
    assert stages["data_quality_pit_check"]["evidence"]["data_lineage_remediation_status"] == "remediation_required"
    assert "point_in_time_universe" in stages["data_quality_pit_check"]["evidence"]["data_lineage_remediation_groups"]
    assert stages["data_quality_pit_check"]["evidence"]["data_lineage_remediation_is_not_data_fix"] is True
    assert (
        stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_status"]
        == "production_data_acquisition_required"
    )
    assert "crsp" in stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_acceptable_provider_ids"]
    assert (
        "pit_universe"
        in stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_missing_contract_groups"]
    )
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_plan_is_not_provider_evidence"] is True
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_current_drop_status"] == "incoming_drop_blocked"
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_current_drop_ready_file_count"] == 0
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_current_drop_required_file_count"] == 6
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_current_drop_first_blocker"] == "source_dir_missing"
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_contract_ready_table_count"] == 0
    assert stages["data_quality_pit_check"]["evidence"]["production_data_acquisition_contract_blocked_table_count"] == 6
    assert stages["data_quality_pit_check"]["evidence"]["production_pit_intake_status"] == "production_pit_data_intake_blocked"
    assert stages["data_quality_pit_check"]["evidence"]["production_pit_current_blocking_stage"] == "incoming_drop_readiness"
    assert stages["data_quality_pit_check"]["evidence"]["pit_bundle_acceptance_status"] == "acceptance_blocked"
    assert stages["data_quality_pit_check"]["evidence"]["pit_bundle_acceptance_current_blocking_step"] == "incoming_drop_readiness"
    assert stages["data_quality_pit_check"]["evidence"]["macro_release_lag_policy_status"] == "research_lag_only_release_calendar_missing"
    assert stages["data_quality_pit_check"]["evidence"]["macro_lag_days"] == 2
    assert stages["data_quality_pit_check"]["evidence"]["macro_release_lag_research_proxy_only"] is True
    assert stages["strategy_validation_gate"]["status"] == "blocked"
    assert "dedicated_us_equity_strategy_validation_gate_blocked_by_data_quality" in stages["strategy_validation_gate"]["blockers"]
    assert stages["strategy_validation_gate"]["evidence"]["gate_status"] == "blocked_data_quality"
    assert stages["standardized_backtest"]["evidence"]["standard_report_schema_audit_status"] == "schema_audit_pass"
    assert stages["standardized_backtest"]["evidence"]["standard_report_schema_passed_field_count"] == 13
    assert stages["standardized_backtest"]["evidence"]["standard_report_schema_required_field_count"] == 13
    assert stages["small_capital_live_readiness"]["evidence"]["constitution_present"] is True
    assert stages["small_capital_live_readiness"]["evidence"]["live_readiness_status"] == "live_readiness_blocked"
    assert stages["manual_review"]["status"] == "manual_review_required"
    assert stages["manual_review"]["evidence"]["evidence_checklist_required_count"] == 2
    assert stages["manual_review"]["evidence"]["evidence_checklist_passed_count"] == 1
    assert stages["manual_review"]["evidence"]["review_milestones"][0]["days"] == 30
    assert stages["paper_simulation"]["evidence"]["readiness_status"] == "paper_simulation_blocked"
    assert stages["monitoring_attribution_retirement_iteration"]["status"] == "defined"
    assert (
        stages["monitoring_attribution_retirement_iteration"]["evidence"]["replay_readiness_status"]
        == "replay_readiness_pass"
    )
    assert primary["paper_ready"] is False
    assert primary["live_ready"] is False
    assert primary["allowed_next_action"] == "acquire_production_pit_data_bundle_and_continue_forward_observation"


def test_us_equity_placeholder_strategies_do_not_unlock_backtest_or_live(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)

    payload = build_us_equity_strategy_production_line_report(
        repo_root=tmp_path,
        output=Path("out/report.json"),
        markdown_output=Path("out/report.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    _validate_schema(payload)
    placeholders = [item for item in payload["strategies"] if not item["primary_candidate"]]
    assert placeholders
    for strategy in placeholders:
        stages = {stage["stage_id"]: stage for stage in strategy["stages"]}
        assert strategy["registry_status"] == "hypothesis_registered_only"
        assert stages["strategy_hypothesis_registration"]["status"] == "pass"
        assert stages["standardized_backtest"]["status"] == "blocked"
        assert strategy["paper_ready"] is False
        assert strategy["live_ready"] is False
        assert strategy["live_order_allowed"] is False


def test_us_equity_production_line_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)
    payload = build_us_equity_strategy_production_line_report(
        repo_root=tmp_path,
        output=Path("out/report.json"),
        markdown_output=Path("out/report.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_us_equity_production_line_schema_rejects_pipeline_progress_unlock(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)
    payload = build_us_equity_strategy_production_line_report(
        repo_root=tmp_path,
        output=Path("out/report.json"),
        markdown_output=Path("out/report.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["pipeline_progress"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted pipeline_progress.paper_or_live_unlock_allowed=true")


def test_us_equity_production_line_schema_rejects_architecture_unlock(tmp_path: Path) -> None:
    _write_fixture_project(tmp_path)
    payload = build_us_equity_strategy_production_line_report(
        repo_root=tmp_path,
        output=Path("out/report.json"),
        markdown_output=Path("out/report.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["architecture_layer_contract"]["guardrails"]["strategy_broker_adapter_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted strategy_broker_adapter_allowed=true")


def _write_fixture_project(root: Path) -> None:
    _write_json(
        root / "configs/strategies/us_equity_strategy_registry.json",
        {
            "schema_version": "us_equity_strategy_registry_v1",
            "asset": "us_equity",
            "policy": {
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "live_order_allowed": False,
            },
            "production_line_order": STAGE_ORDER,
            "strategies": [
                {
                    "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                    "family": "us_etf_macro_momentum_rotation",
                    "status": "forward_observation_only",
                    "current_stage": "forward_observation",
                    "primary_candidate": True,
                    "strategy_card": "docs/card.md",
                    "hypothesis": {
                        "alpha_sources": ["ETF cross-sectional momentum"],
                        "risk_premia_explanation": "Continuation across ETF sleeves.",
                    },
                    "source_reports": {
                        "data_ingestion": "artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json",
                        "data_freshness": "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
                        "etf_kline_quality_daily": "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json",
                        "fred_macro_preflight": "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json",
                        "data_source_reconciliation": "artifacts/us_equity_data_status/latest/us_equity_data_source_reconciliation_report.json",
                        "data_lineage_remediation": "artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json",
                        "production_data_acquisition_plan": "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json",
                        "production_pit_intake_status": "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
                        "pit_bundle_acceptance": "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
                        "macro_release_lag_policy": "artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json",
                        "research_backtest": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json",
                        "standard_report_schema_audit": "artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json",
                        "top_candidate_validation": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json",
                        "walk_forward_parameter_stability_gate": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_walk_forward_parameter_stability_gate_report.json",
                        "forward_observation": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json",
                        "forward_observation_evaluation": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
                        "forward_observation_daily_health": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json",
                        "strategy_validation_gate": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
                        "manual_review": "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
                        "paper_simulation_readiness": "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
                        "live_readiness": "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json",
                        "monitoring_rules": "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
                        "replay_readiness": "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json",
                    },
                    "guardrails": {
                        "paper_ready": False,
                        "live_ready": False,
                    },
                },
                {
                    "strategy_id": "placeholder",
                    "family": "future_family",
                    "status": "hypothesis_registered_only",
                    "current_stage": "strategy_hypothesis_registration",
                    "primary_candidate": False,
                    "hypothesis": {
                        "alpha_sources": ["future signal"],
                        "risk_premia_explanation": "Registered only.",
                    },
                    "source_reports": {},
                    "guardrails": {
                        "backtest_allowed_without_registration": False,
                        "paper_ready": False,
                        "live_ready": False,
                    },
                },
            ],
        },
    )
    (root / "docs/card.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "docs/card.md").write_text("# Card\n", encoding="utf-8")
    _write_json(
        root / "artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json",
        {
            "status": "pass",
            "provider": "tiingo",
            "symbol_count": 24,
            "missing_symbols": [],
            "blockers": [],
            "summary": {
                "available_symbol_count": 24,
                "latest_common_date": "2026-06-24",
            },
            "guardrails": {
                "live_order_allowed": False,
                "order_endpoint_used": False,
                "private_endpoint_used": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
        {
            "schema_version": "us_equity_data_freshness_daily_report_v1",
            "status": "blocked",
            "price_freshness": {
                "passed": True,
                "latest_common_date": "2026-06-24",
            },
            "macro_freshness": {
                "status": "missing",
                "passed": False,
            },
            "blockers": ["us_equity_freshness_fred_macro_data_missing"],
            "guardrails": {
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json",
        {
            "schema_version": "us_equity_fred_macro_preflight_report_v1",
            "status": "fred_macro_preflight_warn",
            "current_session_api_key_present": False,
            "import_report": {
                "source_type": "fred_api_observations",
                "latest_common_date": "2026-06-17",
            },
            "warnings": ["fred_api_key_missing_in_current_session"],
            "blockers": [],
            "guardrails": {
                "macro_preflight_only": True,
                "api_key_value_recorded": False,
                "token_written_to_artifacts": False,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json",
        {
            "schema_version": "us_equity_etf_kline_quality_daily_report_v1",
            "status": "warn",
            "promotion_clean": False,
            "symbol_count": 24,
            "available_symbol_count": 24,
            "missing_symbols": [],
            "summary": {
                "latest_common_date": "2026-06-24",
                "warn_symbol_count": 6,
                "blocked_symbol_count": 0,
            },
            "warnings": ["DBMF:zero_or_negative_volume_rows:26"],
            "blockers": [],
            "guardrails": {
                "kline_quality_gate_only": True,
                "api_key_value_recorded": False,
                "token_written_to_artifacts": False,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_data_source_reconciliation_report.json",
        {
            "schema_version": "us_equity_data_source_reconciliation_report_v1",
            "status": "research_reconciled_promotion_blocked",
            "selected_price_source": "tiingo_eod",
            "summary": {
                "available_symbol_count": 24,
                "required_symbol_count": 24,
                "missing_symbols": [],
                "data_promotion_clean": False,
            },
            "blockers": ["us_equity_data_lineage_not_promotion_clean"],
            "guardrails": {
                "reconciliation_report_is_not_production_clean_evidence": True,
                "promotion_clean_granted_by_this_report": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json",
        {
            "schema_version": "us_equity_data_lineage_remediation_report_v1",
            "status": "remediation_required",
            "remediation_groups": [
                {
                    "group_id": "point_in_time_universe",
                    "status": "required",
                    "matched_blockers": ["point_in_time_universe_not_confirmed"],
                    "accepted_evidence": ["Historical membership table."],
                    "paper_or_live_unlock_allowed": False,
                }
            ],
            "guardrails": {
                "remediation_report_is_not_data_fix": True,
                "promotion_clean_granted_by_this_report": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json",
        {
            "schema_version": "us_equity_production_data_acquisition_plan_v1",
            "status": "production_data_acquisition_required",
            "acceptable_provider_ids": ["crsp", "sharadar", "norgate", "local_csv"],
            "missing_contract_groups": [
                "pit_universe",
                "survivorship",
                "corporate_actions",
                "identifier_mapping",
                "adjustment_replay",
                "macro_release_calendar",
                "bundle_activation",
            ],
            "current_drop_readiness": {
                "status": "incoming_drop_blocked",
                "ready_file_count": 0,
                "required_file_count": 6,
                "first_blocker": "source_dir_missing",
            },
            "contract_status_by_table": [
                {"table": "universe_membership_events", "status": "blocked"},
                {"table": "delisted_symbols", "status": "blocked"},
                {"table": "corporate_actions", "status": "blocked"},
                {"table": "symbol_mapping", "status": "blocked"},
                {"table": "adjustment_replay", "status": "blocked"},
                {"table": "macro_release_calendar", "status": "blocked"},
            ],
            "blockers": ["production_bundle_missing", "provider_verification_required"],
            "guardrails": {
                "data_acquisition_plan_is_not_provider_evidence": True,
                "promotion_clean_granted_by_this_report": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
        {
            "status": "production_pit_data_intake_blocked",
            "current_blocking_stage": "incoming_drop_readiness",
            "blockers": ["source_dir_missing"],
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {
            "status": "acceptance_blocked",
            "current_blocking_step": "incoming_drop_readiness",
            "blockers": ["source_dir_missing"],
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json",
        {
            "schema_version": "us_equity_macro_release_lag_policy_report_v1",
            "status": "research_lag_only_release_calendar_missing",
            "macro_source": {
                "release_calendar_fields_present": False,
            },
            "policy": {
                "macro_lag_days": 2,
            },
            "blockers": [
                "fred_release_calendar_missing",
                "macro_revision_vintage_missing",
                "macro_release_lag_not_production_pit",
            ],
            "guardrails": {
                "research_lag_proxy_is_not_production_pit": True,
                "promotion_clean_granted_by_this_report": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_macro_rotation_research_report.json",
        {
            "status": "partial",
            "data": {
                "price_source": "tiingo_eod",
                "promotion_clean": False,
                "missing_symbols": [],
            },
            "backtest": {
                "status": "complete",
                "metrics": {
                    "cagr": 0.1,
                    "max_drawdown": -0.2,
                    "sharpe": 0.9,
                },
            },
            "signal_integrity": {
                "t_plus_1_execution": True,
                "no_private_endpoint": True,
                "no_order_endpoint": True,
                "live_order_allowed": False,
            },
            "architecture": {
                "separation_status": "signals_portfolio_execution_decoupled",
                "alpha_signal_module": "quant_us.signals.us_etf_rotation_alpha",
                "portfolio_construction_module": "quant_us.portfolio.us_etf_rotation_portfolio",
                "execution_simulation_module": "quant_us.execution.us_etf_rotation_execution",
            },
            "blockers": [
                "point_in_time_universe_not_confirmed",
                "corporate_action_event_source_missing",
                "data_lineage_not_promotion_clean",
            ],
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_top1_higher_vol_20pct_15x_validation_report.json",
        {
            "status": "research_only_manual_review_required",
            "paper_ready": False,
            "live_ready": False,
            "cost_stress": {
                "0bps": {},
                "10bps": {},
                "25bps": {},
                "50bps": {},
            },
            "constrained_tradability": {
                "reference_aum": 10000,
                "passes_reference_aum_liquidity_check": True,
            },
            "decision": {
                "constrained_tradability_pass": True,
                "paper_ready": False,
                "live_ready": False,
            },
            "walk_forward": {
                "fold_count": 8,
                "aggregate_oos": {
                    "cagr": 0.15,
                },
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json",
        {
            "schema_version": "us_equity_standard_report_schema_audit_v1",
            "status": "schema_audit_pass",
            "coverage_summary": {
                "required_field_count": 13,
                "passed_field_count": 13,
                "missing_input_count": 0,
                "unsafe_flag_count": 0,
            },
            "guardrails": {
                "schema_audit_only": True,
                "strategy_parameters_mutated": False,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "real_order_submitted": False,
            },
            "blockers": [],
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json",
        {
            "status": "PASS",
            "ledger_root": "data/forward_observation/us_etf_rotation_v1",
            "portfolio_snapshot": {
                "timestamp": "2026-06-24",
                "reconciliation_status": "clean",
            },
            "observation_scope": {
                "scope": "operational_quality_only",
                "not_alpha_validation": True,
                "cannot_prove_long_term_positive_expectancy": True,
                "cannot_auto_unlock_paper_or_live": True,
            },
            "alpha_validation": {
                "status": "not_evaluated",
                "alpha_validated": False,
                "long_term_positive_expectancy_proven": False,
                "unlock_effect": "none",
            },
            "operational_checks": {
                "status": "PASS",
                "scope": "operational_quality_only",
                "not_alpha_validation": True,
                "long_term_positive_expectancy_proven": False,
                "paper_or_live_unlock_allowed": False,
            },
            "guardrails": {
                "simulated_only": True,
                "forward_observation_is_not_alpha_validation": True,
                "long_term_positive_expectancy_proven": False,
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
                "order_endpoint_used": False,
                "private_endpoint_used": False,
                "forward_observation_min_days": 30,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_walk_forward_parameter_stability_gate_report.json",
        {
            "schema_version": "us_etf_walk_forward_parameter_stability_gate_v1",
            "status": "research_only_manual_review_required",
            "fold_count": 11,
            "candidate_count": 36,
            "alive_rate": 1.0,
            "guardrails": {
                "not_strategy_validation_pass": True,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
        {
            "schema_version": "us_etf_strategy_validation_gate_report_v1",
            "status": "blocked_data_quality",
            "live_order_allowed": False,
            "paper_simulation_allowed": False,
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {
            "schema_version": "us_etf_forward_observation_evaluation_v1",
            "status": "forward_observing",
            "metrics": {
                "observation_days": 1,
            },
            "guardrails": {
                "forward_evaluation_is_not_alpha_validation": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json",
        {
            "schema_version": "us_etf_forward_observation_daily_health_report_v1",
            "status": "daily_health_pass",
            "daily_run_status": "PASS",
            "roll_status": "PASS",
            "evaluation_status": "forward_observing",
            "observation_days": 1,
            "minimum_complete_days": 30,
            "latest_observation_date": "2026-06-24",
            "daily_run_generated_at": "2026-06-25T00:00:00Z",
            "warnings": [],
            "blockers": [],
            "guardrails": {
                "daily_health_is_not_alpha_validation": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json",
        {
            "schema_version": "us_equity_live_readiness_risk_constitution_v1",
            "status": "live_readiness_blocked",
            "decision": "do_not_start_live_trading",
            "account_capital_usd": 10000.0,
            "max_live_principal_usd": 0.0,
            "live_order_allowed": False,
            "real_order_submitted": False,
            "gate_checks": {
                "strategy_validation_gate_passed": False,
                "forward_observation_complete": False,
            },
            "guardrails": {
                "live_order_allowed": False,
                "private_endpoint_allowed": False,
                "order_endpoint_allowed": False,
                "manual_review_required": True,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
        {
            "schema_version": "us_equity_manual_review_packet_v1",
            "status": "manual_review_pending",
            "decision": "human_review_required",
            "evidence_checklist": [
                {"check_id": "strategy_validation_gate_passed", "passed": False},
                {"check_id": "data_freshness_passed", "passed": True},
            ],
            "review_milestones": [
                {"days": 30, "reached": False},
                {"days": 60, "reached": False},
                {"days": 90, "reached": False},
            ],
            "paper_or_live_unlock_decision": {
                "manual_review_can_unlock_paper_by_itself": False,
                "manual_review_can_unlock_live_by_itself": False,
            },
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "manual_approval_recorded": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        {
            "schema_version": "us_equity_paper_simulation_readiness_v1",
            "status": "paper_simulation_blocked",
            "paper_runner_allowed": False,
            "paper_ledger_root": "data/paper_ledger/us_equity_etf_rotation_v1",
            "decision": "do_not_start_paper_simulation",
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "order_endpoint_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
        {
            "schema_version": "us_equity_monitoring_rules_report_v1",
            "status": "monitoring_rules_defined",
            "required_before_paper_or_live": True,
            "rules": {
                "data_monitors": {},
                "attribution": {},
                "retirement_rules": {},
            },
            "guardrails": {
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json",
        {
            "schema_version": "us_etf_forward_observation_replay_readiness_report_v1",
            "status": "replay_readiness_pass",
            "latest_observation": {"timestamp": "2026-06-24", "target_weights": {"SPY": 1.0}},
            "guardrails": {
                "replay_readiness_only": True,
                "paper_or_live_unlock_allowed": False,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json",
        {
            "schema_version": "us_equity_development_plan_audit_v1",
            "status": "development_plan_blocked_by_production_pit_data",
            "summary": {
                "phase_count": 10,
                "complete_count": 5,
                "observing_count": 1,
                "blocked_count": 4,
                "action_required_count": 0,
            },
            "phase_checks": [
                {
                    "phase_id": "phase_1_data_lineage_hardening",
                    "title": "Data lineage hardening",
                    "status": "blocked_external_data",
                    "evidence": ["pit_intake", "vendor_drop_operator_progress"],
                    "blockers": ["production_bundle_missing"],
                    "metrics": {
                        "vendor_drop_operator_progress_next_step_id": "copy_six_licensed_csv_files",
                    },
                },
                {
                    "phase_id": "phase_3_forward_observation_evaluation",
                    "title": "Forward observation evaluation",
                    "status": "observing",
                    "evidence": ["forward_evaluation"],
                    "blockers": [],
                    "metrics": {
                        "observation_days": 1,
                        "minimum_complete_days": 30,
                    },
                },
            ],
            "blockers": ["production_bundle_missing"],
            "guardrails": {
                "audit_only": True,
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json",
        {
            "schema_version": "us_equity_blocker_taxonomy_report_v1",
            "status": "blocked_external_and_time_dependencies",
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
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_remediation_ticket_closure_report.json",
        {
            "schema_version": "us_equity_remediation_ticket_closure_report_v1",
            "status": "remediation_tickets_open",
            "ticket_count": 2,
            "open_count": 2,
            "closed_count": 0,
            "missing_sources": [],
            "closure_checks": [
                {
                    "ticket_id": "us_equity_remediate_external_data",
                    "category": "external_data",
                    "source_ticket_status": "waiting_external_input",
                    "closed": False,
                    "status": "open",
                    "blocking_evidence": ["pit intake ready"],
                    "acceptance_evidence": ["pit intake ready"],
                    "source_reports": ["pit_intake"],
                },
                {
                    "ticket_id": "us_equity_remediate_natural_time",
                    "category": "natural_time",
                    "source_ticket_status": "waiting_observation_window",
                    "closed": False,
                    "status": "open",
                    "blocking_evidence": ["30 observation days complete"],
                    "acceptance_evidence": ["30 observation days complete"],
                    "source_reports": ["forward_evaluation"],
                },
            ],
            "guardrails": {
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
