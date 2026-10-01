from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_completion_audit_report import build_us_equity_completion_audit_report


SCHEMA = Path("schemas/us_equity_completion_audit_report.schema.json")


def test_completion_audit_rules_live_in_monitoring_service() -> None:
    assert build_us_equity_completion_audit_report.__module__ == "quant_us.monitoring.completion_audit"


def test_completion_audit_blocks_on_pit_and_forward_window(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, all_complete=False)

    payload = build_us_equity_completion_audit_report(
        repo_root=tmp_path,
        output=Path("out/completion_audit.json"),
        markdown_output=Path("out/completion_audit.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "completion_blocked"
    assert payload["summary"]["phase_count"] == 12
    assert payload["summary"]["blocked_count"] >= 1
    assert payload["summary"]["first_incomplete_phase_id"] == "phase_1_data_hardening"
    assert payload["summary"]["first_incomplete_phase_status"] == "blocked"
    assert payload["summary"]["first_blocker"] == "pit_procurement_missing:universe_membership_events.csv"
    assert payload["summary"]["next_action"] == "Acquire licensed PIT bundle and keep daily data gates passing."
    assert payload["summary"]["operator_open_input_count"] == 5
    assert payload["summary"]["operator_external_input_count"] == 1
    assert payload["summary"]["operator_manual_input_count"] == 2
    assert payload["summary"]["operator_natural_time_count"] == 2
    assert payload["summary"]["completion_dependency_blocked_count"] == 10
    assert payload["summary"]["completion_claim_allowed"] is False
    assert payload["summary"]["paper_or_live_unlock_allowed"] is False
    assert payload["summary"]["paper_simulation_allowed"] is False
    assert payload["summary"]["live_order_allowed"] is False
    phases = {item["phase_id"]: item for item in payload["phases"]}
    assert phases["phase_0_candidate_freeze"]["status"] == "complete"
    assert phases["phase_1_data_hardening"]["status"] == "blocked"
    assert "source_universe_membership_events_file_missing" in phases["phase_1_data_hardening"]["blockers"]
    assert phases["phase_2_strategy_validation_gate"]["status"] == "blocked"
    assert "strategy_validation_requirement_incomplete:data_quality_pit" in phases["phase_2_strategy_validation_gate"]["blockers"]
    assert phases["phase_3_forward_observation_evaluation"]["status"] == "in_progress"
    assert "forward_observation_less_than_30_days" in phases["phase_3_forward_observation_evaluation"]["blockers"]
    assert phases["phase_4_portfolio_promotion_evidence"]["status"] == "blocked"
    assert "portfolio_event_ledger_not_passed:missing" in phases["phase_4_portfolio_promotion_evidence"]["blockers"]
    assert phases["phase_6_manual_review_and_decision_record"]["status"] == "blocked"
    assert "manual_review_not_ready" in phases["phase_6_manual_review_and_decision_record"]["blockers"]
    assert phases["phase_7_paper_simulation_ledger"]["status"] == "blocked"
    assert "us_equity_paper_readiness_manual_review_not_ready" in phases["phase_7_paper_simulation_ledger"]["blockers"]
    assert phases["phase_8_execution_and_broker_safety"]["status"] == "blocked"
    assert "broker_credentials_reviewer_missing" in phases["phase_8_execution_and_broker_safety"]["blockers"]
    assert phases["phase_9_monitoring_replay_incident"]["status"] == "blocked"
    assert "us_equity_daily_monitoring_operator_queue_open" in phases["phase_9_monitoring_replay_incident"]["blockers"]
    assert phases["phase_11_paper_live_readiness"]["status"] == "blocked"
    assert "manual_review_not_ready" in phases["phase_11_paper_live_readiness"]["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/completion_audit.json").exists()
    assert (tmp_path / "out/completion_audit.md").exists()


def test_completion_audit_complete_when_all_phase_evidence_passes(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, all_complete=True)

    payload = build_us_equity_completion_audit_report(
        repo_root=tmp_path,
        output=Path("out/completion_audit.json"),
        markdown_output=Path("out/completion_audit.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "completion_complete"
    assert payload["summary"]["complete_count"] == 12
    assert payload["summary"]["blocked_count"] == 0
    assert payload["summary"]["first_incomplete_phase_id"] == ""
    assert payload["summary"]["first_blocker"] == ""
    assert payload["summary"]["completion_claim_allowed"] is True
    assert payload["blockers"] == []


def test_completion_audit_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, all_complete=False)
    payload = build_us_equity_completion_audit_report(
        repo_root=tmp_path,
        output=Path("out/completion_audit.json"),
        markdown_output=Path("out/completion_audit.md"),
        generated_at="2026-06-28T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_common_sources(tmp_path: Path, *, all_complete: bool) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_completion_dependency_report.json",
        {
            "status": "completion_dependencies_ready" if all_complete else "completion_dependencies_blocked",
            "summary": {"blocked_count": 0 if all_complete else 10},
            "blockers": [] if all_complete else ["pit_procurement_missing:universe_membership_events.csv"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_operator_unblock_packet.json",
        {
            "status": "operator_unblock_clear" if all_complete else "operator_unblock_open",
            "summary": {
                "external_input_count": 0 if all_complete else 1,
                "manual_input_count": 0 if all_complete else 2,
                "natural_time_count": 0 if all_complete else 2,
                "open_count": 0 if all_complete else 5,
            },
        },
    )
    _write_text(tmp_path / "../学习资料/量化交易业务闭环/系统评估/US ETF 轮动 主候选策略卡.md", "# card")
    _write_json(tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_roll_report.json", {"status": "PASS"})
    _write_json(tmp_path / "data/forward_observation/us_etf_rotation_v1/validation_state.json", {"state": "ok"})
    _write_json(tmp_path / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json", {"status": "pass"})
    _write_json(tmp_path / "artifacts/us_equity_data_status/latest/us_equity_etf_kline_quality_daily_report.json", {"status": "warn"})
    _write_json(tmp_path / "artifacts/us_equity_data_status/latest/us_equity_fred_macro_preflight_report.json", {"status": "fred_macro_preflight_warn"})
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
        {"status": "production_pit_data_intake_ready" if all_complete else "production_pit_data_intake_blocked", "blockers": [] if all_complete else ["source_universe_membership_events_file_missing"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json",
        {
            "status": "pit_procurement_ready_for_manual_license_review" if all_complete else "pit_procurement_ready_for_vendor_order",
            "blockers": [] if all_complete else ["pit_procurement_missing:universe_membership_events.csv"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_gate_report.json",
        {"status": "validation_passed_for_forward_observation" if all_complete else "blocked_data_quality", "blockers": [] if all_complete else ["data_lineage_not_promotion_clean"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_strategy_validation_evidence_audit.json",
        {
            "status": "validation_evidence_audit_ready_for_forward_observation" if all_complete else "validation_evidence_audit_blocked_data_quality",
            "summary": {
                "requirement_count": 12,
                "complete_count": 12 if all_complete else 11,
                "blocked_count": 0 if all_complete else 1,
                "incomplete_count": 0,
                "paper_or_live_unlock_allowed": False,
                "live_order_allowed": False,
            },
            "incomplete_requirements": [] if all_complete else ["data_quality_pit"],
            "blockers": [] if all_complete else ["validation_gate_check_failed:data_coverage_and_quality"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_portfolio/latest/portfolio_promotion_evidence_report.json",
        {
            "status": "portfolio_promotion_evidence_pass" if all_complete else "portfolio_promotion_evidence_blocked",
            "blockers": [] if all_complete else ["portfolio_event_ledger_not_passed:missing"],
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {"status": "forward_complete_for_manual_review" if all_complete else "forward_observing", "blockers": [] if all_complete else ["forward_observation_less_than_30_days"]},
    )
    _write_json(tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_small_account_execution_preflight_report.json", {"status": "pass_observation_only", "blockers": []})
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_decision_record_report.json",
        {
            "status": "manual_decision_record_valid" if all_complete else "manual_decision_record_missing_or_invalid",
            "record_summary": {
                "decision": "paper_simulation_review_candidate" if all_complete else "",
                "reviewer_recorded": all_complete,
                "evidence_path_count": 1 if all_complete else 0,
            },
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
            "blockers": [] if all_complete else ["us_equity_manual_decision_record_reviewer_missing"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_manual_review_packet.json",
        {
            "status": "manual_review_ready" if all_complete else "manual_review_pending",
            "blockers": [] if all_complete else ["manual_review_not_ready"],
            "guardrails": {"manual_approval_recorded": all_complete, "live_order_allowed": False},
            "paper_or_live_unlock_decision": {
                "manual_review_can_unlock_paper_by_itself": False,
                "manual_review_can_unlock_live_by_itself": False,
            },
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        {
            "status": "paper_simulation_ready_for_manual_start" if all_complete else "paper_simulation_blocked",
            "blockers": [] if all_complete else ["us_equity_paper_readiness_manual_review_not_ready"],
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_roll_report.json",
        {
            "status": "PASS" if all_complete else "BLOCKED",
            "blockers": [] if all_complete else ["us_equity_paper_simulation_readiness_not_ready"],
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json",
        {
            "status": "paper_simulation_complete_for_manual_review" if all_complete else "paper_simulation_not_started",
            "blockers": [] if all_complete else ["us_equity_paper_simulation_roll_blocked"],
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json",
        {
            "status": "execution_drill_evidence_complete",
            "blockers": [],
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_review_report.json",
        {
            "status": "broker_credentials_review_proven" if all_complete else "broker_credentials_review_blocked",
            "blockers": [] if all_complete else ["broker_credentials_reviewer_missing"],
            "guardrails": {"order_endpoint_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_broker_credentials_operator_handoff.json",
        {
            "status": "broker_credentials_handoff_ready_for_manual_review" if all_complete else "broker_credentials_handoff_blocked",
            "blockers": [] if all_complete else ["broker_credentials_reviewer_missing"],
            "guardrails": {"order_endpoint_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_daily_monitoring_report.json",
        {
            "status": "daily_monitoring_clear" if all_complete else "daily_monitoring_blocked",
            "blockers": [] if all_complete else ["us_equity_daily_monitoring_operator_queue_open"],
            "guardrails": {"paper_simulation_allowed": False, "live_order_allowed": False},
        },
    )
    _write_json(tmp_path / "artifacts/us_equity_strategy_registry/latest/us_equity_strategy_registry_report.json", {"status": "pass", "blockers": []})
    live_status = "live_readiness_ready_for_manual_review" if all_complete else "live_readiness_blocked"
    _write_json(tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_report.json", {"status": live_status, "blockers": [] if all_complete else ["manual_signoff_missing"]})
    _write_json(tmp_path / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_live_readiness_risk_constitution_report.json", {"status": live_status, "blockers": [] if all_complete else ["manual_signoff_missing"]})


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
