from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.monitoring.daily_monitoring import build_us_equity_daily_monitoring_report


SCHEMA = Path("schemas/us_equity_daily_monitoring_report.schema.json")


def test_daily_monitoring_report_blocks_missing_source_and_builds_operator_item(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, include_next_action=False)

    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )

    assert payload["status"] == "daily_monitoring_blocked"
    _validate_schema(payload)
    assert payload["summary"]["missing_source_count"] == 1
    assert payload["summary"]["operator_action_count"] >= 1
    assert payload["blocked_gate_coverage"]["uncovered_gate_count"] == 0
    assert payload["blocked_gate_coverage"]["covered_gate_count"] >= 1
    assert "us_equity_daily_monitoring_source_missing:next_action_queue" in payload["blockers"]
    replay_item = next(item for item in payload["operator_queue"] if item["item_id"] == "monitoring_replay_diff_next_action_queue")
    assert replay_item["owner"] == "quant_operator"
    assert replay_item["recommended_command"] == "python scripts/build_us_equity_next_action_queue_report.py"
    assert replay_item["blocked_gate_record_count"] == 1
    assert replay_item["blocked_gate_records"][0]["evidence_path"].endswith("us_equity_next_action_queue_report.json")
    assert payload["guardrails"]["live_order_allowed"] is False


def test_daily_monitoring_report_surfaces_gate_blockers_and_incident_template(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, daily_status="BLOCKED", next_actions=True)

    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )

    assert payload["status"] == "daily_monitoring_blocked"
    _validate_schema(payload)
    assert any(item["item_id"] == "us_equity_action_production_pit_data" for item in payload["operator_queue"])
    operator_item = next(item for item in payload["operator_queue"] if item["item_id"] == "us_equity_action_production_pit_data")
    assert operator_item["owner"] == "operator_data_vendor"
    assert operator_item["evidence_path"] == "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json"
    assert operator_item["blocked_gate_record_count"] == 1
    assert operator_item["blocked_gate_records"][0]["blocker"] == "source_universe_membership_events_file_missing"
    assert operator_item["blocked_gate_records"][0]["next_action"] == "Copy licensed PIT CSV files into incoming drop."
    assert payload["blocked_gate_coverage"]["uncovered_gate_count"] == 0
    assert any(row["source_id"] == "daily_production_line" for row in payload["blocked_gate_coverage"]["rows"])
    assert "us_equity_daily_monitoring_source_blocked:daily_production_line:BLOCKED" in payload["blockers"]
    template = payload["incident_review_template"]
    assert template["template_id"] == "us_equity_daily_monitoring_incident_review_v1"
    assert "timeline" in template["template_fields"]
    assert "regression_test" in template["required_template_fields"]
    assert template["retention_path"] == (
        "artifacts/us_equity_etf_macro_rotation/incidents/us_equity_daily_monitoring_incident_review_template.json"
    )
    assert template["operator_queue_item_count"] == len(payload["operator_queue"])
    assert template["replay_diff_count"] == payload["replay_diff"]["diff_count"]
    expected_action_items = sum(item["blocked_gate_record_count"] for item in payload["operator_queue"])
    assert template["incident_action_item_count"] == expected_action_items
    assert payload["summary"]["incident_action_item_count"] == expected_action_items
    assert len(template["incident_action_items"]) == expected_action_items
    action_item = next(
        row
        for row in template["incident_action_items"]
        if row["operator_item_id"] == "us_equity_action_production_pit_data"
    )
    assert action_item["owner"] == "operator_data_vendor"
    assert action_item["reason"] == "Blocked by source_universe_membership_events_file_missing"
    assert action_item["next_action"] == "Copy licensed PIT CSV files into incoming drop."
    assert action_item["recommended_command"] == operator_item["recommended_command"]
    assert action_item["evidence_path"] == "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json"
    assert action_item["regression_test_or_rule_update_required"] is True
    assert "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json" in template["source_evidence_paths"]
    assert template["incident_review_must_create_test_or_rule_update"] is True
    _assert_retained_artifacts_written(tmp_path, payload)
    for item in payload["operator_queue"]:
        assert item["owner"]
        assert item["reason"]
        assert item["next_action"]
        assert item["recommended_command"]
        assert item["evidence_path"]
        assert item["blocked_gate_record_count"] == len(item["blocked_gate_records"])


def test_daily_monitoring_report_can_be_clear_without_unlocking_live(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, next_actions=False)

    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )

    assert payload["status"] == "daily_monitoring_clear"
    _validate_schema(payload)
    assert payload["operator_queue"] == []
    assert payload["blockers"] == []
    assert payload["summary"]["paper_or_live_unlock_allowed"] is False
    assert payload["blocked_gate_coverage"]["gate_count"] == 0
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    _assert_retained_artifacts_written(tmp_path, payload)
    assert (tmp_path / "out/daily_monitoring.json").exists()
    assert (tmp_path / "out/daily_monitoring.md").exists()


def test_daily_monitoring_schema_rejects_live_order_allowed_true(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, next_actions=False)
    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_daily_monitoring_schema_rejects_unactionable_operator_item(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, daily_status="BLOCKED", next_actions=True)
    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )
    payload["operator_queue"][0]["evidence_path"] = ""

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted operator item without evidence_path")


def test_daily_monitoring_report_creates_operator_item_for_expected_but_blocked_gate(tmp_path: Path) -> None:
    _write_common_sources(tmp_path, next_actions=False, paper_readiness_status="paper_simulation_blocked")

    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "daily_monitoring_blocked"
    assert payload["blocked_gate_coverage"]["uncovered_gate_count"] == 0
    assert payload["summary"]["blocked_gate_record_count"] >= 1
    coverage = next(row for row in payload["blocked_gate_coverage"]["rows"] if row["source_id"] == "paper_simulation_readiness")
    assert coverage["owner"] == "execution_engineering"
    assert coverage["operator_item_id"] == "monitoring_blocked_gate_paper_simulation_readiness"
    item = next(row for row in payload["operator_queue"] if row["item_id"] == "monitoring_blocked_gate_paper_simulation_readiness")
    assert item["reason"] == "paper_simulation_not_reviewed"
    assert item["recommended_command"] == "python scripts/build_us_equity_paper_simulation_readiness_report.py"
    assert "us_equity_daily_monitoring_source_blocked:paper_simulation_readiness:paper_simulation_blocked" in payload["blockers"]


def test_daily_monitoring_report_tracks_strategy_production_line_as_first_class_gate(tmp_path: Path) -> None:
    _write_common_sources(
        tmp_path,
        next_actions=False,
        strategy_production_line_status="production_line_blocked_before_paper_or_live",
    )

    payload = build_us_equity_daily_monitoring_report(
        repo_root=tmp_path,
        output=Path("out/daily_monitoring.json"),
        markdown_output=Path("out/daily_monitoring.md"),
        generated_at="2026-07-08T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "daily_monitoring_blocked"
    assert payload["source_reports"]["strategy_production_line"]["path"] == (
        "artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json"
    )
    assert payload["blocked_gate_coverage"]["uncovered_gate_count"] == 0
    item = next(
        row for row in payload["operator_queue"]
        if row["item_id"] == "monitoring_blocked_gate_strategy_production_line"
    )
    assert item["owner"] == "quant_architect"
    assert item["recommended_command"] == "python scripts/build_us_equity_strategy_production_line_report.py"
    assert item["evidence_path"].endswith("us_equity_strategy_production_line_report.json")
    assert item["blocked_gate_records"][0]["next_action"] == (
        "Rebuild or inspect strategy_production_line before paper/live review."
    )
    assert "us_equity_daily_monitoring_source_blocked:strategy_production_line:production_line_blocked_before_paper_or_live" in payload["blockers"]


def _assert_retained_artifacts_written(root: Path, payload: dict) -> None:
    retained = payload["retained_artifacts"]
    expected = {
        "replay_diff": "artifacts/us_equity_etf_macro_rotation/replay/us_equity_daily_monitoring_replay_diff.json",
        "incident_review_template": "artifacts/us_equity_etf_macro_rotation/incidents/us_equity_daily_monitoring_incident_review_template.json",
        "operator_queue_snapshot": "artifacts/us_equity_etf_macro_rotation/operator/us_equity_daily_monitoring_operator_queue.json",
    }
    for artifact_id, expected_path in expected.items():
        row = retained[artifact_id]
        assert row["artifact_id"] == artifact_id
        assert row["path"] == expected_path
        assert row["written"] is True
        retained_path = root / expected_path
        assert retained_path.exists()
        retained_payload = json.loads(retained_path.read_text(encoding="utf-8"))
        assert retained_payload["generated_at"] == payload["generated_at"]
        assert retained_payload["artifact_id"] == artifact_id
        assert retained_payload["guardrails"]["monitoring_only"] is True
        assert retained_payload["guardrails"]["paper_or_live_unlock_allowed"] is False
        assert retained_payload["guardrails"]["live_order_allowed"] is False
        assert retained_payload["guardrails"]["order_endpoint_allowed"] is False
        if artifact_id == "replay_diff":
            assert retained_payload["schema_version"] == "us_equity_daily_monitoring_replay_diff_v1"
            assert retained_payload["replay_diff"]["mode"] == "fixed_clock_no_realtime_access"
        if artifact_id == "incident_review_template":
            assert retained_payload["schema_version"] == "us_equity_daily_monitoring_incident_review_template_v1"
            assert retained_payload["incident_review_template"]["template_id"] == "us_equity_daily_monitoring_incident_review_v1"
            assert retained_payload["incident_review_template"]["incident_action_item_count"] == len(
                retained_payload["incident_review_template"]["incident_action_items"]
            )
        if artifact_id == "operator_queue_snapshot":
            assert retained_payload["schema_version"] == "us_equity_daily_monitoring_operator_queue_snapshot_v1"
            assert retained_payload["item_count"] == len(retained_payload["operator_queue"])


def _write_common_sources(
    root: Path,
    *,
    include_next_action: bool = True,
    next_actions: bool = False,
    daily_status: str = "PASS",
    strategy_production_line_status: str = "production_line_observing_manual_review_required",
    paper_readiness_status: str = "paper_simulation_ready_for_manual_start",
) -> None:
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_monitoring_rules_report.json",
        {
            "status": "monitoring_rules_defined",
            "monitor_count": 18,
            "incident_review": {
                "required_template_fields": [
                    "timeline",
                    "impact_scope",
                    "direct_cause",
                    "root_cause",
                    "gate_that_failed_to_block",
                    "remediation",
                    "regression_test",
                    "pause_or_retire_decision",
                ],
                "triggers": ["ledger_reconciliation_failure"],
                "incident_review_must_create_test_or_rule_update": True,
            },
            "blockers": [],
        },
    )
    _write(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json",
        {"status": daily_status, "blockers": ["production_pit_data_not_ready"] if daily_status == "BLOCKED" else []},
    )
    _write(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_strategy_production_line_report.json",
        {
            "status": strategy_production_line_status,
            "blockers": ["primary_evidence_chain_incomplete"]
            if strategy_production_line_status == "production_line_blocked_before_paper_or_live"
            else [],
        },
    )
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_daily_health_report.json",
        {"status": "daily_health_pass", "blockers": []},
    )
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_evaluation_report.json",
        {"status": "forward_observing", "blockers": []},
    )
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_readiness_report.json",
        {
            "status": paper_readiness_status,
            "blockers": ["paper_simulation_not_reviewed"] if paper_readiness_status == "paper_simulation_blocked" else [],
        },
    )
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_paper_simulation_evaluation_report.json",
        {"status": "paper_simulation_observing", "blockers": []},
    )
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_equity_execution_drill_evidence_report.json",
        {"status": "execution_drill_evidence_complete", "blockers": []},
    )
    _write(
        root / "artifacts/us_equity_etf_macro_rotation/latest/us_etf_forward_observation_replay_readiness_report.json",
        {"status": "replay_readiness_pass", "blockers": []},
    )
    if include_next_action:
        actions = [
            {
                "action_id": "us_equity_action_production_pit_data",
                "owner": "operator_data_vendor",
                "dependency_type": "external_input",
                "status": "open",
                "first_blocker": "source_universe_membership_events_file_missing",
                "title": "Prepare production PIT vendor drop",
                "instruction": "Copy licensed PIT CSV files into incoming drop.",
                "recommended_command": "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
                "source_reports": ["completion_dependency"],
                "blocked_gate_records": [
                    {
                        "record_id": "production_pit_data:1",
                        "milestone_id": "production_pit_data",
                        "gate_id": "production_pit_data",
                        "blocker": "source_universe_membership_events_file_missing",
                        "owner": "operator_data_vendor",
                        "reason": "Blocked by source_universe_membership_events_file_missing",
                        "next_action": "Copy licensed PIT CSV files into incoming drop.",
                        "evidence_path": "artifacts/us_equity_data_lineage/latest/us_equity_pit_procurement_readiness_report.json",
                        "source_report": "pit_procurement_readiness",
                        "actionability": "waiting",
                        "dependency_type": "external_input",
                    }
                ],
            }
        ] if next_actions else []
        _write(
            root / "artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json",
            {"status": "next_actions_open" if actions else "next_actions_complete", "actions": actions, "blockers": []},
        )


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
