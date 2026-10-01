from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_live_readiness_risk_constitution import (
    build_us_equity_live_readiness_risk_constitution,
)


SCHEMA = Path("schemas/us_equity_live_readiness_risk_constitution_report.schema.json")
COMPAT_SCHEMA = Path("schemas/us_equity_live_readiness_report.schema.json")


def test_live_readiness_blocks_current_observing_forward_record(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=1, strategy_status="blocked_data_quality")

    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        compat_output=tmp_path / "us_equity_live_readiness_report.json",
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_live_readiness_risk_constitution_v1"
    _validate_schema(payload)
    assert payload["status"] == "live_readiness_blocked"
    assert payload["decision"] == "do_not_start_live_trading"
    assert payload["account_capital_usd"] == 10000.0
    assert payload["max_live_principal_usd"] == 0.0
    assert payload["live_order_allowed"] is False
    assert payload["paper_simulation_unlocked_by_this_report"] is False
    assert payload["forward_observation"]["observation_days"] == 1
    assert "us_equity_live_readiness_strategy_validation_gate_not_passed" in payload["blockers"]
    assert "us_equity_live_readiness_forward_observation_less_than_30_days" in payload["blockers"]
    assert "us_equity_live_readiness_max_live_principal_usd_not_set" in payload["blockers"]
    assert "us_equity_live_readiness_production_pit_intake_not_ready" in payload["blockers"]
    assert "us_equity_live_readiness_pit_bundle_acceptance_not_ready" in payload["blockers"]
    assert payload["gate_checks"]["strategy_validation_gate_passed"] is False
    assert payload["gate_checks"]["strategy_validation_evidence_audit_ready"] is False
    assert payload["gate_checks"]["forward_observation_complete"] is False
    assert payload["gate_checks"]["manual_review_packet_ready"] is False
    assert payload["gate_checks"]["manual_approval_recorded"] is False
    assert payload["gate_checks"]["paper_simulation_complete_for_manual_review"] is False
    assert payload["gate_checks"]["production_pit_intake_ready"] is False
    assert payload["gate_checks"]["pit_bundle_acceptance_ready"] is False
    assert payload["paper_simulation_evaluation"]["status"] == "paper_simulation_not_started"
    assert payload["manual_review"]["status"] == "manual_review_pending"
    assert payload["manual_review"]["manual_review_can_unlock_live_by_itself"] is False
    assert "us_equity_live_readiness_strategy_validation_evidence_audit_not_ready" in payload["blockers"]
    assert "us_equity_live_readiness_strategy_validation_evidence_blocked" in payload["blockers"]
    assert "us_equity_live_readiness_manual_review_packet_not_ready" in payload["blockers"]
    assert "us_equity_live_readiness_manual_approval_not_recorded" in payload["blockers"]
    assert "us_equity_live_readiness_paper_simulation_not_complete_for_manual_review" in payload["blockers"]
    assert payload["gate_checks"]["remediation_tickets_closed"] is False
    assert payload["remediation_tickets"]["ticket_count"] == 2
    assert payload["remediation_tickets"]["external_or_time_dependency_count"] == 2
    tickets = {item["category"]: item for item in payload["remediation_tickets"]["tickets"]}
    assert tickets["external_data"]["owner"] == "operator_data_vendor"
    assert tickets["natural_time"]["status"] == "waiting_observation_window"
    assert "us_equity_live_readiness_remediation_tickets_open" in payload["blockers"]
    assert payload["production_pit_data"]["intake_status"] == "production_pit_data_intake_blocked"
    assert payload["production_pit_data"]["acceptance_status"] == "acceptance_blocked"
    assert payload["risk_constitution"]["instrument_limits"]["initial_live_leverage_cap"] == 1.0
    assert payload["risk_constitution"]["instrument_limits"]["research_max_leverage_seen"] == 1.5
    assert payload["risk_constitution"]["execution_constraints"]["margin_and_financing_rate_preflight_required"] is True
    assert payload["risk_constitution"]["execution_constraints"]["whole_or_fractional_share_rule_required"] is True
    assert payload["gate_checks"]["small_account_execution_preflight_pass"] is True
    assert payload["execution_readiness"]["status"] == "execution_readiness_blocked"
    assert payload["execution_readiness"]["drill_count"] == 5
    assert payload["execution_readiness"]["proven_count"] == 2
    assert payload["execution_readiness"]["blocked_count"] == 3
    drills = {item["drill_id"]: item for item in payload["execution_readiness"]["drills"]}
    assert set(drills) == {
        "broker_credentials_review",
        "margin_financing_share_rounding_preflight",
        "order_reconciliation_drill",
        "kill_switch_drill",
        "monitoring_alerting_drill",
    }
    assert drills["broker_credentials_review"]["status"] == "blocked"
    assert "us_equity_live_readiness_broker_credentials_not_configured" in drills["broker_credentials_review"]["blockers"]
    assert drills["margin_financing_share_rounding_preflight"]["status"] == "proven"
    assert drills["monitoring_alerting_drill"]["status"] == "proven"
    assert payload["execution_readiness"]["guardrails"]["broker_calls_used"] is False
    assert payload["execution_readiness"]["guardrails"]["order_endpoint_allowed"] is False
    assert payload["execution_readiness"]["guardrails"]["real_order_submitted"] is False
    assert (tmp_path / "live.md").exists()
    markdown = (tmp_path / "live.md").read_text(encoding="utf-8")
    assert "# US Equity 实盘前风控宪法" in markdown
    assert "当前美股系统不得真实下单" in markdown
    assert "## Gate 检查" in markdown
    assert "## 执行演练门禁" in markdown
    compat = json.loads((tmp_path / "us_equity_live_readiness_report.json").read_text(encoding="utf-8"))
    assert compat["schema_version"] == payload["schema_version"]
    _validate_compat_schema(compat)
    assert compat["live_order_allowed"] is False
    assert compat["outputs"]["compat_json"].endswith("us_equity_live_readiness_report.json")


def test_live_readiness_blocks_unsafe_live_flags_even_after_complete_observation(tmp_path: Path) -> None:
    reports = _write_reports(
        tmp_path,
        observation_days=30,
        forward_status="forward_complete_for_manual_review",
        paper_status="paper_simulation_complete_for_manual_review",
        strategy_status="validation_passed_for_forward_observation",
        production_status="production_line_manual_review_required",
    )
    strategy_gate = Path(reports["strategy_gate"])
    payload = json.loads(strategy_gate.read_text(encoding="utf-8"))
    payload["guardrails"]["live_order_allowed"] = True
    strategy_gate.write_text(json.dumps(payload), encoding="utf-8")

    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        max_live_principal_usd=1000.0,
        manual_reviewer="manual-review",
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "live_readiness_blocked"
    _validate_schema(payload)
    assert payload["gate_checks"]["strategy_validation_gate_passed"] is True
    assert payload["gate_checks"]["strategy_validation_evidence_audit_ready"] is True
    assert payload["gate_checks"]["forward_observation_complete"] is True
    assert payload["gate_checks"]["manual_review_packet_ready"] is True
    assert payload["gate_checks"]["manual_approval_recorded"] is True
    assert payload["gate_checks"]["no_unsafe_live_flags"] is False
    assert any("live_order_allowed=true" in item for item in payload["unsafe_flags"])
    assert any(item.startswith("us_equity_live_readiness_unsafe_flag:") for item in payload["blockers"])
    assert payload["live_order_allowed"] is False
    assert payload["real_order_submitted"] is False


def test_live_readiness_blocks_principal_above_account_capital(tmp_path: Path) -> None:
    reports = _write_reports(
        tmp_path,
        observation_days=30,
        forward_status="forward_complete_for_manual_review",
        paper_status="paper_simulation_complete_for_manual_review",
        strategy_status="validation_passed_for_forward_observation",
        production_status="production_line_manual_review_required",
    )

    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        account_capital_usd=10000.0,
        max_live_principal_usd=15000.0,
        manual_reviewer="manual-review",
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "live_readiness_blocked"
    _validate_schema(payload)
    assert payload["gate_checks"]["max_live_principal_set"] is True
    assert "us_equity_live_readiness_max_live_principal_exceeds_account_capital" in payload["blockers"]
    assert payload["guardrails"]["order_endpoint_allowed"] is False


def test_live_readiness_can_load_conservative_principal_from_risk_config(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=1, strategy_status="blocked_data_quality")
    config = tmp_path / "configs/risk/us_equity_live_risk_limits.json"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "schema_version": "us_equity_live_risk_limits_v1",
                "account_capital_usd": 10000.0,
                "max_live_principal_usd": 1000.0,
                "manual_reviewer": "",
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        risk_limits_config=Path("configs/risk/us_equity_live_risk_limits.json"),
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "live_readiness_blocked"
    _validate_schema(payload)
    assert payload["account_capital_usd"] == 10000.0
    assert payload["max_live_principal_usd"] == 1000.0
    assert payload["gate_checks"]["max_live_principal_set"] is True
    assert "us_equity_live_readiness_max_live_principal_usd_not_set" not in payload["blockers"]
    assert "us_equity_live_readiness_manual_reviewer_not_recorded" in payload["blockers"]
    assert payload["live_order_allowed"] is False
    assert payload["source_reports"]["risk_limits_config"] == "configs/risk/us_equity_live_risk_limits.json"


def test_live_readiness_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=1, strategy_status="blocked_data_quality")
    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        compat_output=tmp_path / "us_equity_live_readiness_report.json",
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_live_readiness_compat_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=1, strategy_status="blocked_data_quality")
    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        compat_output=tmp_path / "us_equity_live_readiness_report.json",
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["order_endpoint_allowed"] = True

    schema = json.loads(COMPAT_SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("compat schema accepted order_endpoint_allowed=true")


def test_live_readiness_schema_rejects_execution_readiness_order_endpoint(tmp_path: Path) -> None:
    reports = _write_reports(tmp_path, observation_days=1, strategy_status="blocked_data_quality")
    payload = build_us_equity_live_readiness_risk_constitution(
        repo_root=tmp_path,
        output=tmp_path / "live.json",
        markdown_output=tmp_path / "live.md",
        compat_output=tmp_path / "us_equity_live_readiness_report.json",
        **reports,
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["execution_readiness"]["guardrails"]["order_endpoint_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted execution readiness order_endpoint_allowed=true")


def _write_reports(
    tmp_path: Path,
    *,
    observation_days: int,
    forward_status: str = "forward_observing",
    paper_status: str = "paper_simulation_not_started",
    strategy_status: str = "blocked_data_quality",
    production_status: str = "production_line_blocked_before_paper_or_live",
) -> dict[str, Path]:
    strategy_gate = tmp_path / "strategy_gate.json"
    strategy_evidence_audit = tmp_path / "strategy_evidence_audit.json"
    forward_evaluation = tmp_path / "forward_eval.json"
    manual_review_packet = tmp_path / "manual_review.json"
    paper_simulation_evaluation = tmp_path / "paper_eval.json"
    forward_roll = tmp_path / "forward_roll.json"
    production_line = tmp_path / "production_line.json"
    blocker_taxonomy = tmp_path / "blocker_taxonomy.json"
    data_status = tmp_path / "data_status.json"
    forward_state = tmp_path / "state.json"
    small_account_preflight = tmp_path / "small_account_preflight.json"
    production_pit_intake_status = tmp_path / "pit_status.json"
    pit_bundle_acceptance = tmp_path / "pit_acceptance.json"
    execution_drill_evidence = tmp_path / "execution_drills.json"
    strategy_gate.write_text(
        json.dumps(
            {
                "status": strategy_status,
                "paper_simulation_allowed": False,
                "live_order_allowed": False,
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "paper_or_live_unlock_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    strategy_evidence_ready = strategy_status == "validation_passed_for_forward_observation"
    strategy_evidence_audit.write_text(
        json.dumps(
            {
                "status": (
                    "validation_evidence_audit_ready_for_forward_observation"
                    if strategy_evidence_ready
                    else "validation_evidence_audit_blocked_data_quality"
                ),
                "summary": {
                    "requirement_count": 12,
                    "complete_count": 12 if strategy_evidence_ready else 11,
                    "blocked_count": 0 if strategy_evidence_ready else 1,
                    "incomplete_count": 0,
                    "paper_or_live_unlock_allowed": False,
                    "live_order_allowed": False,
                },
                "guardrails": {
                    "paper_or_live_unlock_allowed": False,
                    "paper_simulation_allowed": False,
                    "live_order_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    forward_evaluation.write_text(
        json.dumps(
            {
                "status": forward_status,
                "minimum_complete_days": 30,
                "metrics": {"observation_days": observation_days},
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                    "paper_or_live_unlock_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    paper_simulation_evaluation.write_text(
        json.dumps(
            {
                "status": paper_status,
                "minimum_complete_days": 30,
                "metrics": {"paper_days": 30 if paper_status == "paper_simulation_complete_for_manual_review" else 0},
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                    "paper_or_live_unlock_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    forward_roll.write_text(
        json.dumps(
            {
                "status": "PASS",
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                    "paper_or_live_unlock_allowed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    manual_ready = (
        strategy_status == "validation_passed_for_forward_observation"
        and forward_status == "forward_complete_for_manual_review"
    )
    manual_review_packet.write_text(
        json.dumps(
            {
                "status": "manual_review_ready" if manual_ready else "manual_review_pending",
                "paper_or_live_unlock_decision": {
                    "manual_review_can_unlock_paper_by_itself": False,
                    "manual_review_can_unlock_live_by_itself": False,
                },
                "guardrails": {
                    "manual_approval_recorded": manual_ready,
                    "paper_simulation_allowed": False,
                    "live_order_allowed": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    production_line.write_text(json.dumps({"status": production_status, "live_order_allowed": False}), encoding="utf-8")
    blocker_taxonomy.write_text(
        json.dumps(
            {
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
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    data_status.write_text(
        json.dumps(
            {
                "status": "pass",
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_used": False,
                    "order_endpoint_used": False,
                },
            }
        ),
        encoding="utf-8",
    )
    forward_state.write_text(json.dumps({"days_completed": observation_days, "live_order_allowed": False}), encoding="utf-8")
    small_account_preflight.write_text(
        json.dumps(
            {
                "status": "pass_observation_only",
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                    "real_order_submitted": False,
                    "not_a_broker_order": True,
                },
            }
        ),
        encoding="utf-8",
    )
    production_pit_intake_status.write_text(
        json.dumps(
            {
                "status": "production_pit_data_intake_blocked",
                "current_blocking_stage": "incoming_drop_readiness",
                "blockers": ["source_dir_missing"],
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    pit_bundle_acceptance.write_text(
        json.dumps(
            {
                "status": "acceptance_blocked",
                "current_blocking_step": "incoming_drop_readiness",
                "blockers": ["source_dir_missing"],
                "guardrails": {"live_order_allowed": False},
            }
        ),
        encoding="utf-8",
    )
    execution_drill_evidence.write_text(
        json.dumps(
            {
                "status": "execution_drill_evidence_partial",
                "drills": [
                    {"drill_id": "broker_credentials_review", "status": "blocked"},
                    {"drill_id": "margin_financing_share_rounding_preflight", "status": "proven"},
                    {"drill_id": "order_reconciliation_drill", "status": "blocked"},
                    {"drill_id": "kill_switch_drill", "status": "blocked"},
                    {"drill_id": "monitoring_alerting_drill", "status": "proven"},
                ],
                "guardrails": {
                    "live_order_allowed": False,
                    "private_endpoint_allowed": False,
                    "order_endpoint_allowed": False,
                    "real_order_submitted": False,
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "strategy_gate": strategy_gate,
        "strategy_evidence_audit": strategy_evidence_audit,
        "forward_evaluation": forward_evaluation,
        "manual_review_packet": manual_review_packet,
        "paper_simulation_evaluation": paper_simulation_evaluation,
        "forward_roll": forward_roll,
        "production_line": production_line,
        "blocker_taxonomy": blocker_taxonomy,
        "data_status": data_status,
        "forward_state": forward_state,
        "small_account_preflight": small_account_preflight,
        "production_pit_intake_status": production_pit_intake_status,
        "pit_bundle_acceptance": pit_bundle_acceptance,
        "execution_drill_evidence": execution_drill_evidence,
    }


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def _validate_compat_schema(payload: dict[str, object]) -> None:
    schema = json.loads(COMPAT_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
