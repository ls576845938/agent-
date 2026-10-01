from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_development_plan_audit import build_us_equity_development_plan_audit


SCHEMA = Path("schemas/us_equity_development_plan_audit_report.schema.json")


def test_development_plan_audit_reports_current_pit_data_blocker(tmp_path: Path) -> None:
    payload = build_us_equity_development_plan_audit(
        repo_root=Path("."),
        output=tmp_path / "out/test_us_equity_development_plan_audit_report.json",
        markdown_output=tmp_path / "out/test_us_equity_development_plan_audit.md",
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_development_plan_audit_v1"
    _validate_schema(payload)
    assert payload["status"] == "development_plan_blocked_by_production_pit_data"
    phases = {item["phase_id"]: item for item in payload["phase_checks"]}
    assert phases["phase_0_candidate_freeze"]["status"] == "complete"
    assert phases["phase_1_data_lineage_hardening"]["status"] == "blocked_external_data"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["intake_packet_status"] == "intake_packet_ready_for_data_vendor_drop"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["manual_vendor_drop_package_status"] == "manual_vendor_drop_package_ready"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["manual_vendor_drop_template_count"] == 6
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["manual_vendor_drop_field_count"] == 51
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["activation_status"] == "activation_blocked"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["pit_bundle_acceptance_status"] == "acceptance_blocked"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["pit_bundle_acceptance_current_blocking_step"] == "incoming_drop_readiness"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["pit_operator_handoff_status"] == "handoff_blocked"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["pit_operator_handoff_blocking_stage"] == "incoming_drop_readiness"
    assert "US Equity PIT" in phases["phase_1_data_lineage_hardening"]["metrics"]["pit_operator_handoff_markdown"]
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["vendor_drop_operator_progress_status"] == "operator_drop_blocked"
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["vendor_drop_operator_progress_completed_count"] == 3
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["vendor_drop_operator_progress_blocked_count"] == 2
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["vendor_drop_operator_progress_pending_count"] == 2
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["vendor_drop_operator_progress_step_count"] == 7
    assert phases["phase_1_data_lineage_hardening"]["metrics"]["vendor_drop_operator_progress_next_step_id"] == "copy_six_licensed_csv_files"
    assert any(
        "data/external/us_equity_lineage/incoming/manual_vendor_drop" in item
        for item in phases["phase_1_data_lineage_hardening"]["metrics"]["operator_next_actions"]
    )
    assert phases["phase_2_strategy_validation_gate"]["status"] == "blocked_data_quality"
    assert phases["phase_3_forward_observation_evaluation"]["status"] == "observing"
    assert phases["phase_4_small_account_constraints"]["status"] == "complete"
    assert phases["phase_4_small_account_constraints"]["metrics"]["account_equity"] == 10000.0
    assert phases["phase_4_small_account_constraints"]["metrics"]["initial_margin_requirement"] == 0.5
    assert phases["phase_4_small_account_constraints"]["metrics"]["maintenance_margin_requirement"] == 0.25
    assert phases["phase_4_small_account_constraints"]["metrics"]["initial_live_leverage_default"] == 1.0
    assert phases["phase_4_small_account_constraints"]["metrics"]["research_cap_1_5x_not_live_default"] is True
    assert phases["phase_4_small_account_constraints"]["metrics"]["fractional_margin_fields_present"] is True
    assert phases["phase_4_small_account_constraints"]["metrics"]["whole_share_margin_fields_present"] is True
    assert set(phases["phase_4_small_account_constraints"]["metrics"]["scenario_ids"]) == {
        "one_x_cash_only",
        "low_leverage_1_25x_research",
        "research_cap_1_5x",
    }
    assert phases["phase_5_strategy_registry"]["status"] == "complete"
    assert phases["phase_6_live_readiness"]["status"] == "blocked_manual_review"
    assert phases["phase_6_live_readiness"]["metrics"]["live_readiness_status"] == "live_readiness_blocked"
    assert phases["phase_6_live_readiness"]["metrics"]["execution_readiness_status"] == "execution_readiness_blocked"
    assert phases["phase_6_live_readiness"]["metrics"]["execution_readiness_drill_count"] == 5
    assert phases["phase_6_live_readiness"]["metrics"]["execution_readiness_proven_count"] == 4
    assert phases["phase_6_live_readiness"]["metrics"]["execution_readiness_blocked_count"] == 1
    assert phases["phase_6_live_readiness"]["metrics"]["live_order_allowed"] is False
    assert phases["phase_6_live_readiness"]["metrics"]["real_order_submitted"] is False
    assert phases["blocker_taxonomy_governance"]["status"] == "complete"
    assert phases["blocker_taxonomy_governance"]["metrics"]["status"] == "blocked_external_and_time_dependencies"
    assert phases["blocker_taxonomy_governance"]["metrics"]["unsafe_flag_blocker_count"] == 0
    assert phases["standard_report_schema"]["status"] == "complete"
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_development_plan_audit_blocks_unsafe_live_flag(tmp_path: Path) -> None:
    _write_minimal_reports(tmp_path)
    live = tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json"
    payload = json.loads(live.read_text(encoding="utf-8"))
    payload["live_order_allowed"] = True
    live.write_text(json.dumps(payload), encoding="utf-8")

    audit = build_us_equity_development_plan_audit(
        repo_root=tmp_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert audit["status"] != "development_plan_complete"
    _validate_schema(audit)
    assert any(item.startswith("unsafe_flag:live_readiness.live_order_allowed=true") for item in audit["blockers"])


def test_development_plan_audit_schema_rejects_paper_or_live_unlock_flag(tmp_path: Path) -> None:
    payload = build_us_equity_development_plan_audit(
        repo_root=Path("."),
        output=tmp_path / "out/test_us_equity_development_plan_audit_report.json",
        markdown_output=tmp_path / "out/test_us_equity_development_plan_audit.md",
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def _write_minimal_reports(root: Path) -> None:
    _write_json(
        root / "configs/strategies/us_equity_strategy_registry.json",
        {
            "strategies": [
                {
                    "strategy_id": "us_etf_rotation_min_adv_10m_vol_target_20pct_cap1_5x",
                    "family": "us_etf_macro_momentum_rotation",
                    "status": "forward_observation_only",
                    "primary_candidate": True,
                    "hypothesis": {
                        "alpha_sources": ["momentum"],
                        "risk_premia_explanation": "Momentum risk premium.",
                    },
                    "parameter_space": {"lookback": [63]},
                    "data_dependencies": {"prices": "PIT"},
                    "cost_model": {"turnover_cost_bps": [10]},
                    "failure_conditions": ["data failure"],
                    "source_reports": {"production_data_acquisition_plan": "x"},
                },
                {
                    "strategy_id": "dual",
                    "family": "dual_momentum",
                    "hypothesis": {"alpha_sources": ["a"], "risk_premia_explanation": "b"},
                    "parameter_space": {"x": [1]},
                    "data_dependencies": {"x": "y"},
                    "cost_model": {"x": [1]},
                    "failure_conditions": ["x"],
                },
                {
                    "strategy_id": "abs",
                    "family": "absolute_momentum",
                    "hypothesis": {"alpha_sources": ["a"], "risk_premia_explanation": "b"},
                    "parameter_space": {"x": [1]},
                    "data_dependencies": {"x": "y"},
                    "cost_model": {"x": [1]},
                    "failure_conditions": ["x"],
                },
                {
                    "strategy_id": "topn",
                    "family": "topn_etf_rotation",
                    "hypothesis": {"alpha_sources": ["a"], "risk_premia_explanation": "b"},
                    "parameter_space": {"x": [1]},
                    "data_dependencies": {"x": "y"},
                    "cost_model": {"x": [1]},
                    "failure_conditions": ["x"],
                },
                {
                    "strategy_id": "regime",
                    "family": "regime_overlay",
                    "hypothesis": {"alpha_sources": ["a"], "risk_premia_explanation": "b"},
                    "parameter_space": {"x": [1]},
                    "data_dependencies": {"x": "y"},
                    "cost_model": {"x": [1]},
                    "failure_conditions": ["x"],
                },
                {
                    "strategy_id": "s151",
                    "family": "151_trading_strategies_migration",
                    "hypothesis": {"alpha_sources": ["a"], "risk_premia_explanation": "b"},
                    "parameter_space": {"x": [1]},
                    "data_dependencies": {"x": "y"},
                    "cost_model": {"x": [1]},
                    "failure_conditions": ["x"],
                },
            ]
        },
    )
    _write_json(root / "artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json", {"status": "production_line_blocked_before_paper_or_live", "blockers": []})
    _write_json(root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json", {"status": "validation_passed_for_forward_observation", "blockers": []})
    _write_json(root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json", {"status": "PASS"})
    _write_json(root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json", {"status": "forward_complete_for_manual_review", "minimum_complete_days": 30, "metrics": {"observation_days": 30}})
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json",
        _small_account_preflight_payload(),
    )
    _write_json(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json",
        {
            "status": "live_readiness_blocked",
            "blockers": [],
            "live_order_allowed": False,
            "real_order_submitted": False,
            "execution_readiness": {
                "status": "execution_readiness_blocked",
                "drill_count": 5,
                "proven_count": 4,
                "blocked_count": 1,
            },
        },
    )
    _write_json(root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_standard_report_schema_audit_report.json", {"status": "schema_audit_pass", "blockers": []})
    _write_json(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_blocker_taxonomy_report.json",
        {
            "status": "blocked_external_and_time_dependencies",
            "summary": {
                "total_blockers": 3,
                "categorized_blockers": 3,
                "uncategorized_blockers": 0,
                "waiting_category_count": 2,
                "actionable_category_count": 1,
            },
            "categories": [
                {"category": "external_data", "blocker_count": 1},
                {"category": "natural_time", "blocker_count": 1},
                {"category": "unsafe_flags", "blocker_count": 0},
            ],
            "guardrails": {
                "live_order_allowed": False,
                "paper_or_live_unlock_allowed": False,
            },
            "blockers": [],
        },
    )
    _write_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json", {"status": "production_data_acquisition_required", "blockers": ["production_bundle_missing"]})
    _write_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json", {"status": "intake_packet_ready_for_data_vendor_drop", "blockers": []})
    _write_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json", {"status": "manual_vendor_drop_package_ready", "required_table_count": 6, "field_count": 51, "template_files": [{"table": "x"}] * 6})
    _write_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json", {"status": "activation_blocked", "blockers": ["production_bundle_missing"], "candidate_config_path": "artifacts/us_equity_data_lineage/latest/activation_candidates/us_equity_provider_sources.missing.candidate.yaml"})
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {
            "status": "acceptance_blocked",
            "blockers": ["source_dir_missing"],
            "current_blocking_step": "incoming_drop_readiness",
            "source_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "steps": [
                {
                    "step_id": "incoming_drop_readiness",
                    "payload": {
                        "operator_next_actions": [
                            "Create directory: data/external/us_equity_lineage/incoming/manual_vendor_drop"
                        ]
                    },
                }
            ],
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json",
        {
            "status": "handoff_blocked",
            "current_blocking_stage": "incoming_drop_readiness",
            "blockers": ["source_dir_missing"],
            "operator_next_actions": [
                "Create directory: data/external/us_equity_lineage/incoming/manual_vendor_drop"
            ],
            "outputs": {
                "markdown": "../学习资料/量化交易业务闭环/系统评估/US Equity PIT 数据交付一页纸.md"
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_operator_progress_report.json",
        {
            "status": "operator_drop_blocked",
            "completed_count": 2,
            "blocked_count": 3,
            "pending_count": 2,
            "step_count": 7,
            "next_step_id": "create_incoming_drop_dir",
            "next_action": "New-Item -ItemType Directory -Force -Path data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "blockers": [
                "operator_drop_step_blocked:create_incoming_drop_dir:source_dir_missing",
            ],
            "guardrails": {
                "live_order_allowed": False,
                "paper_or_live_unlock_allowed": False,
            },
        },
    )
    _write_json(root / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json", {"status": "pass"})
    _write_json(root / "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json", {"status": "pass"})
    _write_json(root / "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json", {"status": "fred_macro_preflight_warn"})
    _write_json(root / "artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json", {"status": "research_lag_only_release_calendar_missing"})
    _write_json(root / "data/forward_observation/us_etf_rotation_v1/validation_state.json", {"days_completed": 30})
    (root / "../学习资料/量化交易业务闭环/系统评估").mkdir(parents=True, exist_ok=True)
    (root / "../学习资料/量化交易业务闭环/系统评估/US Equity 美股系统开发规划.md").write_text("# plan\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _small_account_preflight_payload() -> dict[str, object]:
    def model() -> dict[str, object]:
        return {
            "borrow_notional": 0.0,
            "estimated_financing_daily": 0.0,
            "initial_margin_required": 5000.0,
            "initial_margin_surplus": 5000.0,
            "maintenance_margin_required": 2500.0,
            "maintenance_margin_surplus": 7500.0,
        }

    return {
        "status": "pass_observation_only",
        "account_equity": 10000.0,
        "min_trade_amount_usd": 25.0,
        "slippage_bps": 10.0,
        "annual_financing_rate": 0.055,
        "initial_margin_requirement": 0.5,
        "maintenance_margin_requirement": 0.25,
        "blockers": [],
        "guardrails": {
            "initial_live_leverage_default": 1.0,
            "research_cap_1_5x_not_live_default": True,
            "live_order_allowed": False,
        },
        "scenarios": [
            {"scenario_id": "one_x_cash_only", "fractional_share_allowed_model": model(), "whole_share_model": model()},
            {"scenario_id": "low_leverage_1_25x_research", "fractional_share_allowed_model": model(), "whole_share_model": model()},
            {"scenario_id": "research_cap_1_5x", "fractional_share_allowed_model": model(), "whole_share_model": model()},
        ],
    }


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
