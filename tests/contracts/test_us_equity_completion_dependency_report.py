from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_completion_dependency_report import build_us_equity_completion_dependency_report


SCHEMA = Path("schemas/us_equity_completion_dependency_report.schema.json")


def test_completion_dependency_rules_live_in_monitoring_service() -> None:
    assert build_us_equity_completion_dependency_report.__module__ == "quant_us.monitoring.completion_dependency"


def test_completion_dependency_report_blocks_until_all_milestones_pass(tmp_path: Path) -> None:
    _write_json(tmp_path / "pit_status.json", {"status": "production_pit_data_intake_blocked", "blockers": ["source_dir_missing"]})
    _write_json(tmp_path / "pit_procurement.json", {"status": "pit_procurement_ready_for_vendor_order", "blockers": ["pit_procurement_missing:universe_membership_events.csv"]})
    _write_json(tmp_path / "pit_acceptance.json", {"status": "acceptance_blocked", "blockers": ["source_dir_missing"]})
    _write_json(tmp_path / "validation.json", {"status": "blocked_data_quality", "blockers": ["data_lineage_not_promotion_clean"]})
    _write_json(
        tmp_path / "validation_audit.json",
        {
            "status": "validation_evidence_audit_blocked_data_quality",
            "blockers": ["validation_gate_check_failed:data_coverage_and_quality"],
            "incomplete_requirements": ["data_quality_pit"],
        },
    )
    _write_json(
        tmp_path / "portfolio_promotion.json",
        {
            "status": "promotion_evidence_blocked",
            "promotion_ready": False,
            "blockers": ["portfolio_event_ledger_not_passed:missing"],
        },
    )
    _write_json(tmp_path / "forward.json", {"status": "forward_observing", "blockers": []})
    _write_json(tmp_path / "manual.json", {"status": "manual_review_pending", "blockers": ["forward_not_complete"]})
    _write_json(tmp_path / "paper.json", {"status": "paper_simulation_blocked", "blockers": ["paper_readiness_remediation_tickets_open"]})
    _write_json(
        tmp_path / "paper_eval.json",
        {"status": "paper_simulation_not_started", "blockers": ["us_equity_paper_simulation_ledger_root_missing"]},
    )
    _write_json(tmp_path / "execution.json", {"status": "execution_drill_evidence_partial", "blockers": ["broker_credentials_review_input_missing"]})
    _write_json(tmp_path / "broker_handoff.json", {"status": "broker_credentials_handoff_blocked", "blockers": ["broker_credentials_local_review_missing"]})
    _write_json(tmp_path / "broker_review.json", {"status": "broker_credentials_review_blocked", "blockers": ["broker_credentials_review_input_missing"]})
    _write_json(tmp_path / "live.json", {"status": "live_readiness_blocked", "blockers": ["max_live_principal_not_set"]})
    _write_json(tmp_path / "taxonomy.json", {"status": "blocked_external_and_time_dependencies", "blockers": []})
    _write_json(tmp_path / "closure.json", {"status": "remediation_tickets_open", "blockers": ["ticket_open"]})
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")

    payload = build_us_equity_completion_dependency_report(
        repo_root=tmp_path,
        output=Path("out/completion.json"),
        markdown_output=Path("out/completion.md"),
        pit_procurement_readiness=Path("pit_procurement.json"),
        pit_status=Path("pit_status.json"),
        pit_acceptance=Path("pit_acceptance.json"),
        strategy_validation=Path("validation.json"),
        strategy_validation_evidence_audit=Path("validation_audit.json"),
        portfolio_promotion=Path("portfolio_promotion.json"),
        forward_evaluation=Path("forward.json"),
        manual_review=Path("manual.json"),
        paper_readiness=Path("paper.json"),
        paper_evaluation=Path("paper_eval.json"),
        execution_evidence=Path("execution.json"),
        broker_handoff=Path("broker_handoff.json"),
        broker_review=Path("broker_review.json"),
        live_readiness=Path("live.json"),
        blocker_taxonomy=Path("taxonomy.json"),
        remediation_closure=Path("closure.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "completion_dependencies_blocked"
    assert payload["summary"]["blocked_count"] == 11
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    milestones = {item["milestone_id"]: item for item in payload["milestones"]}
    assert milestones["production_pit_data"]["dependency_type"] == "external_input"
    assert milestones["production_pit_data"]["actionability"] == "waiting"
    assert milestones["forward_observation_30d"]["dependency_type"] == "natural_time"
    assert milestones["paper_simulation_evaluation"]["dependency_type"] == "natural_time"
    assert milestones["execution_infra_evidence"]["actionability"] == "actionable"
    assert milestones["production_pit_data"]["passed"] is False
    assert milestones["production_pit_data"]["source_reports"] == ["pit_procurement_readiness", "pit_status", "pit_acceptance"]
    assert "pit_procurement_missing:universe_membership_events.csv" in milestones["production_pit_data"]["blockers"]
    assert milestones["strategy_validation_gate"]["source_reports"] == ["strategy_validation", "strategy_validation_evidence_audit"]
    assert milestones["strategy_validation_gate"]["blockers"] == [
        "data_lineage_not_promotion_clean",
        "validation_gate_check_failed:data_coverage_and_quality",
        "strategy_validation_requirement_incomplete:data_quality_pit",
    ]
    assert milestones["portfolio_promotion_evidence"]["source_reports"] == ["portfolio_promotion"]
    assert milestones["portfolio_promotion_evidence"]["dependency_type"] == "engineering_after_data"
    assert milestones["portfolio_promotion_evidence"]["actionability"] == "blocked_until_data"
    assert milestones["portfolio_promotion_evidence"]["blockers"] == ["portfolio_event_ledger_not_passed:missing"]
    assert milestones["forward_observation_30d"]["blockers"] == ["forward_observation_less_than_30_days"]
    assert milestones["paper_simulation_evaluation"]["blockers"] == ["us_equity_paper_simulation_ledger_root_missing"]
    assert milestones["broker_credentials_review"]["blockers"] == [
        "broker_credentials_local_review_missing",
        "broker_credentials_review_input_missing",
    ]
    groups = {item["dependency_type"]: item for item in payload["dependency_groups"]}
    assert groups["external_input"]["actionability"] == "waiting"
    assert groups["external_input"]["milestone_ids"] == ["production_pit_data"]
    assert groups["natural_time"]["milestone_ids"] == ["forward_observation_30d", "paper_simulation_evaluation"]
    assert groups["engineering"]["milestone_ids"] == ["execution_infra_evidence"]
    assert groups["engineering_after_data"]["milestone_ids"] == ["strategy_validation_gate", "portfolio_promotion_evidence"]
    assert "pit_procurement_missing:universe_membership_events.csv" in groups["external_input"]["first_blockers"]
    assert payload["primary_next_action"] == {
        "milestone_id": "production_pit_data",
        "dependency_type": "external_input",
        "actionability": "waiting",
        "first_blocker": "pit_procurement_missing:universe_membership_events.csv",
        "next_action": "Place licensed production PIT files, confirm license review, and run the fail-closed vendor-drop pipeline.",
        "source_reports": ["pit_procurement_readiness", "pit_status", "pit_acceptance"],
    }
    assert "fail-closed vendor-drop pipeline" in payload["operator_next_actions"][0]
    assert payload["external_input_summary"]["missing_file_count"] == 2
    assert payload["external_input_summary"]["operator_action"] == "place_licensed_pit_csv_files_and_rerun_readiness"
    assert payload["external_input_summary"]["missing_required_filenames"] == [
        "universe_membership_events.csv",
        "delisted_symbols.csv",
    ]
    assert payload["external_input_summary"]["required_operator_inputs"] == [
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
    assert payload["external_input_summary"]["operator_command_sequence"] == [
        "python scripts/build_us_equity_manual_vendor_drop_package.py",
        "copy licensed PIT CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop",
        "manually confirm license review for the copied PIT CSV files",
        "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
    ]


def test_completion_dependency_report_satisfied_still_does_not_unlock_live(tmp_path: Path) -> None:
    _write_json(tmp_path / "pit_status.json", {"status": "production_pit_data_intake_ready", "blockers": []})
    _write_json(tmp_path / "pit_procurement.json", {"status": "pit_procurement_ready_for_manual_license_review", "blockers": []})
    _write_json(tmp_path / "pit_acceptance.json", {"status": "acceptance_ready_for_manual_config_apply", "blockers": []})
    _write_json(tmp_path / "validation.json", {"status": "validation_passed_for_forward_observation", "blockers": []})
    _write_json(
        tmp_path / "validation_audit.json",
        {
            "status": "validation_evidence_audit_ready_for_forward_observation",
            "blockers": [],
            "incomplete_requirements": [],
        },
    )
    _write_json(tmp_path / "portfolio_promotion.json", {"status": "promotion_evidence_ready", "promotion_ready": True, "blockers": []})
    _write_json(tmp_path / "forward.json", {"status": "forward_complete_for_manual_review", "blockers": []})
    _write_json(
        tmp_path / "manual.json",
        {
            "status": "manual_review_ready",
            "blockers": [],
            "guardrails": {"manual_approval_recorded": True},
            "paper_or_live_unlock_decision": {"manual_review_can_unlock_live_by_itself": False},
        },
    )
    _write_json(tmp_path / "paper.json", {"status": "paper_simulation_ready_for_manual_start", "blockers": []})
    _write_json(tmp_path / "paper_eval.json", {"status": "paper_simulation_complete_for_manual_review", "blockers": []})
    _write_json(tmp_path / "execution.json", {"status": "execution_drill_evidence_complete", "blockers": []})
    _write_json(tmp_path / "broker_handoff.json", {"status": "broker_credentials_handoff_ready_for_manual_review", "blockers": []})
    _write_json(tmp_path / "broker_review.json", {"status": "broker_credentials_review_proven", "blockers": []})
    _write_json(tmp_path / "live.json", {"status": "live_readiness_ready_for_manual_review", "blockers": []})
    _write_json(tmp_path / "taxonomy.json", {"status": "no_blockers_detected", "blockers": []})
    _write_json(tmp_path / "closure.json", {"status": "remediation_tickets_closed", "blockers": []})
    _write_json(
        tmp_path / "vendor_preflight.json",
        {
            "status": "vendor_drop_preflight_ready_for_readiness_check",
            "required_file_count": 6,
            "missing_file_count": 0,
            "ready_file_count": 6,
            "missing_required_files": [],
            "ready_required_files": [{"filename": "all_ready.csv"}],
        },
    )

    payload = build_us_equity_completion_dependency_report(
        repo_root=tmp_path,
        output=Path("out/completion.json"),
        markdown_output=Path("out/completion.md"),
        pit_procurement_readiness=Path("pit_procurement.json"),
        pit_status=Path("pit_status.json"),
        pit_acceptance=Path("pit_acceptance.json"),
        strategy_validation=Path("validation.json"),
        strategy_validation_evidence_audit=Path("validation_audit.json"),
        portfolio_promotion=Path("portfolio_promotion.json"),
        forward_evaluation=Path("forward.json"),
        manual_review=Path("manual.json"),
        paper_readiness=Path("paper.json"),
        paper_evaluation=Path("paper_eval.json"),
        execution_evidence=Path("execution.json"),
        broker_handoff=Path("broker_handoff.json"),
        broker_review=Path("broker_review.json"),
        live_readiness=Path("live.json"),
        blocker_taxonomy=Path("taxonomy.json"),
        remediation_closure=Path("closure.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "completion_dependencies_satisfied"
    assert payload["summary"]["passed_count"] == payload["summary"]["milestone_count"]
    assert payload["summary"]["paper_or_live_unlock_allowed"] is False
    assert payload["summary"]["live_order_allowed"] is False
    assert payload["blockers"] == []
    assert payload["primary_next_action"] is None
    assert all(group["blocked_count"] == 0 for group in payload["dependency_groups"])
    assert payload["external_input_summary"]["missing_file_count"] == 0
    assert payload["external_input_summary"]["operator_action"] == "rerun_incoming_drop_readiness"
    assert payload["external_input_summary"]["required_operator_inputs"] == []
    assert payload["external_input_summary"]["operator_command_sequence"] == [
        "manually confirm license review for the copied PIT CSV files",
        "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
    ]


def test_completion_dependency_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_completion_dependency_report(
        repo_root=tmp_path,
        output=Path("out/completion.json"),
        markdown_output=Path("out/completion.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_vendor_preflight(path: Path) -> None:
    _write_json(
        path,
        {
            "status": "vendor_drop_preflight_waiting_for_vendor_files",
            "required_file_count": 6,
            "missing_file_count": 2,
            "ready_file_count": 4,
            "missing_required_files": [
                {
                    "filename": "universe_membership_events.csv",
                    "path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/universe_membership_events.csv",
                    "table": "universe_membership_events",
                    "blocker": "universe_membership_events_csv_missing",
                    "required_fields": ["security_id", "ticker"],
                },
                {
                    "filename": "delisted_symbols.csv",
                    "path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/delisted_symbols.csv",
                    "table": "delisted_symbols",
                    "blocker": "delisted_symbols_csv_missing",
                    "required_fields": ["security_id", "ticker", "delisting_date"],
                },
            ],
            "ready_required_files": [
                {"filename": "corporate_actions.csv"},
                {"filename": "symbol_mapping.csv"},
                {"filename": "adjustment_replay.csv"},
                {"filename": "macro_release_calendar.csv"},
            ],
        },
    )


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
