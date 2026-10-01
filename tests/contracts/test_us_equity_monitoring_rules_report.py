from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_monitoring_rules_report import build_us_equity_monitoring_rules_report


SCHEMA = Path("schemas/us_equity_monitoring_rules_report.schema.json")


def test_monitoring_rules_define_audit_replay_incident_and_guardrails(tmp_path: Path) -> None:
    payload = build_us_equity_monitoring_rules_report(
        repo_root=tmp_path,
        output=Path("out/monitoring.json"),
        markdown_output=Path("out/monitoring.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_monitoring_rules_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "monitoring_rules_defined"
    assert payload["required_before_paper_or_live"] is True
    assert payload["monitor_count"] >= 18
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["private_endpoint_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False

    rules = payload["rules"]
    assert rules["data_monitors"]["etf_price_stale_stop"]["severity"] == "block"
    assert rules["position_and_execution_monitors"]["kill_switch_required"]["severity"] == "block"
    assert rules["retirement_rules"]["forward_observation_failure"]["severity"] == "reset_or_new_strategy_id"

    audit = payload["audit_trail"]
    assert audit["required_chain"][0] == "data_snapshot"
    assert audit["required_chain"][-1] == "report"
    assert audit["manual_approval_requires_reviewer_time_reason"] is True

    incident = payload["incident_review"]
    assert "ledger_reconciliation_failure" in incident["triggers"]
    assert "regression_test" in incident["required_template_fields"]
    assert incident["incident_review_must_create_test_or_rule_update"] is True

    replay = payload["replay_requirements"]
    assert replay["must_not_access_current_realtime_data"] is True
    assert replay["fixed_clock_required"] is True
    assert "diff_vs_original_artifact" in replay["outputs"]

    logging = payload["logging_policy"]
    assert logging["secret_values_must_not_be_logged"] is True
    assert "run_id" in logging["required_fields"]
    assert "target_position" in logging["required_fields"]

    lifecycle = payload["strategy_lifecycle_review"]
    cadence = {item["review_id"]: item for item in lifecycle["cadence"]}
    assert "forward_30d_manual_review" in cadence
    assert "forward_60_90d_manual_review" in cadence
    assert "incident_forced_review" in cadence
    assert "manual_reviewer_decision_record" in lifecycle["required_evidence"]
    assert "parameter_or_strategy_id_change_required" in lifecycle["decision_record_fields"]
    assert "auto_live_enable" in lifecycle["forbidden_decisions"]
    assert "auto_paper_enable_without_manual_review" in lifecycle["forbidden_decisions"]
    assert lifecycle["parameter_change_requires_new_strategy_id"] is True
    assert lifecycle["retirement_requires_manual_reason"] is True
    assert lifecycle["live_unlock_allowed"] is False
    assert (tmp_path / "out/monitoring.md").exists()


def test_monitoring_rules_schema_rejects_live_order_allowed(tmp_path: Path) -> None:
    payload = build_us_equity_monitoring_rules_report(
        repo_root=tmp_path,
        output=Path("out/monitoring.json"),
        markdown_output=Path("out/monitoring.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_monitoring_rules_schema_rejects_auto_live_lifecycle_decision(tmp_path: Path) -> None:
    payload = build_us_equity_monitoring_rules_report(
        repo_root=tmp_path,
        output=Path("out/monitoring.json"),
        markdown_output=Path("out/monitoring.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["strategy_lifecycle_review"]["live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted strategy_lifecycle_review.live_unlock_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
