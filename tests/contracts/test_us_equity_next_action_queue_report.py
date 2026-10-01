from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.monitoring.next_action_queue import build_us_equity_next_action_queue_report


SCHEMA = Path("schemas/us_equity_next_action_queue_report.schema.json")


def test_next_action_queue_orders_blocked_milestones(tmp_path: Path) -> None:
    _write_completion(
        tmp_path / "completion.json",
        [
            _milestone("forward_observation_30d", False, ["forward_observation_less_than_30_days"]),
            _milestone("production_pit_data", False, ["source_dir_missing"]),
            _milestone("paper_simulation_evaluation", False, ["us_equity_paper_simulation_ledger_root_missing"]),
            _milestone("broker_credentials_review", False, ["broker_credentials_local_review_missing"]),
        ],
    )
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")

    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "next_actions_open"
    assert payload["summary"]["action_count"] == 4
    assert payload["summary"]["external_input_count"] == 1
    assert payload["summary"]["natural_time_count"] == 2
    assert payload["summary"]["actionable_engineering_count"] == 0
    assert payload["summary"]["blocked_until_upstream_count"] == 0
    assert payload["summary"]["blocked_gate_record_count"] == 4
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["next_action"]["action_id"] == "us_equity_action_production_pit_data"
    assert payload["next_action"]["recommended_command"] == "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed"
    assert payload["next_action"]["blocked_gate_records"] == [
        {
            "record_id": "production_pit_data:1",
            "milestone_id": "production_pit_data",
            "gate_id": "production_pit_data",
            "blocker": "source_dir_missing",
            "owner": "operator_data_vendor",
            "reason": "Blocked by source_dir_missing",
            "next_action": "Resolve production_pit_data",
            "evidence_path": "artifacts/production_pit_data.json",
            "source_report": "production_pit_data",
            "actionability": "waiting",
            "dependency_type": "external_input",
        }
    ]
    assert payload["next_action"]["evidence"]["missing_file_count"] == 2
    assert payload["next_action"]["evidence"]["missing_required_filenames"] == [
        "universe_membership_events.csv",
        "delisted_symbols.csv",
    ]
    assert payload["next_action"]["evidence"]["required_operator_inputs"][0] == {
        "filename": "universe_membership_events.csv",
        "target_path": "data/external/us_equity_lineage/incoming/manual_vendor_drop/universe_membership_events.csv",
        "table": "universe_membership_events",
        "blocker": "universe_membership_events_csv_missing",
        "required_fields": ["security_id", "ticker"],
    }
    assert payload["next_action"]["evidence"]["operator_command_sequence"] == [
        "python scripts/build_us_equity_manual_vendor_drop_package.py",
        "copy licensed PIT CSV files into data/external/us_equity_lineage/incoming/manual_vendor_drop",
        "manually confirm license review for the copied PIT CSV files",
        "python scripts/run_us_equity_vendor_drop_pipeline.py --license-reviewed",
    ]
    assert payload["next_action"]["evidence"]["local_pit_file_discovery"]["status"] == "missing"
    assert payload["next_action"]["evidence"]["local_pit_file_discovery"]["next_command"] == "python scripts/build_us_equity_local_pit_file_discovery_report.py"
    assert payload["next_action"]["evidence"]["blocker_count"] == 1
    assert payload["next_action"]["evidence"]["actionability"] == "waiting"
    assert payload["next_action"]["actionability"] == "waiting"
    assert [item["milestone_id"] for item in payload["actions"]] == [
        "production_pit_data",
        "forward_observation_30d",
        "paper_simulation_evaluation",
        "broker_credentials_review",
    ]
    tracks = {item["track_id"]: item for item in payload["parallel_tracks"]}
    assert tracks["external_input_waiting"]["action_ids"] == ["us_equity_action_production_pit_data"]
    assert tracks["natural_time_waiting"]["action_ids"] == [
        "us_equity_action_forward_observation_30d",
        "us_equity_action_paper_simulation_evaluation",
    ]
    assert tracks["manual_required"]["action_ids"] == [
        "us_equity_action_production_pit_data",
        "us_equity_action_broker_credentials_review",
    ]
    assert tracks["actionable_engineering"]["action_ids"] == []
    actions = {item["milestone_id"]: item for item in payload["actions"]}
    assert actions["forward_observation_30d"]["evidence"]["blocker_count"] == 1
    assert actions["forward_observation_30d"]["evidence"]["first_blocker"] == "forward_observation_less_than_30_days"
    assert actions["paper_simulation_evaluation"]["recommended_command"] == "python scripts/run_us_equity_daily_production_line.py"
    assert actions["paper_simulation_evaluation"]["owner"] == "paper_simulation_scheduler"
    assert actions["paper_simulation_evaluation"]["evidence"]["first_blocker"] == "us_equity_paper_simulation_ledger_root_missing"
    assert actions["paper_simulation_evaluation"]["blocked_gate_records"][0]["owner"] == "paper_simulation_scheduler"
    assert actions["paper_simulation_evaluation"]["blocked_gate_records"][0]["evidence_path"] == "artifacts/paper_simulation_evaluation.json"
    assert actions["broker_credentials_review"]["evidence"]["source_reports"] == ["broker_credentials_review"]
    assert actions["broker_credentials_review"]["recommended_command"] == "python scripts/init_us_equity_broker_credentials_local_review.py"


def test_next_action_queue_separates_broker_manual_input_from_actionable_engineering(tmp_path: Path) -> None:
    _write_completion(
        tmp_path / "completion.json",
        [
            _milestone("production_pit_data", False, ["source_files_missing"]),
            _milestone("execution_infra_evidence", False, ["broker_credentials_manual_review_not_recorded"]),
            _milestone("live_readiness_risk_constitution", False, ["manual_signoff_missing"]),
        ],
    )
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")

    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["next_action"]["action_id"] == "us_equity_action_production_pit_data"
    assert payload["summary"]["actionable_engineering_count"] == 0
    assert payload["summary"]["blocked_until_upstream_count"] == 2
    tracks = {item["track_id"]: item for item in payload["parallel_tracks"]}
    assert tracks["actionable_engineering"]["action_ids"] == []
    assert tracks["blocked_until_manual_input"]["action_ids"] == ["us_equity_action_execution_infra_evidence"]
    assert tracks["blocked_until_upstream"]["action_ids"] == [
        "us_equity_action_execution_infra_evidence",
        "us_equity_action_live_readiness_risk_constitution",
    ]


def test_next_action_queue_keeps_non_broker_execution_blocker_actionable(tmp_path: Path) -> None:
    _write_completion(
        tmp_path / "completion.json",
        [
            _milestone("execution_infra_evidence", False, ["order_reconciliation_drill_not_proven"]),
        ],
    )
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")

    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["summary"]["actionable_engineering_count"] == 1
    tracks = {item["track_id"]: item for item in payload["parallel_tracks"]}
    assert tracks["actionable_engineering"]["action_ids"] == ["us_equity_action_execution_infra_evidence"]
    assert tracks["blocked_until_manual_input"]["action_ids"] == []


def test_next_action_queue_complete_when_no_open_milestones(tmp_path: Path) -> None:
    _write_completion(
        tmp_path / "completion.json",
        [
            _milestone("production_pit_data", True, []),
            _milestone("strategy_validation_gate", True, []),
        ],
    )
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")

    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "next_actions_complete"
    assert payload["next_action"] is None
    assert payload["actions"] == []
    assert payload["summary"]["live_order_allowed"] is False


def test_next_action_queue_has_actionable_command_for_portfolio_promotion_evidence(tmp_path: Path) -> None:
    _write_completion(
        tmp_path / "completion.json",
        [
            _milestone(
                "portfolio_promotion_evidence",
                False,
                ["strategy_validation_gate_not_passed:blocked_data_quality"],
            ),
        ],
    )
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")

    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    action = payload["actions"][0]
    assert action["milestone_id"] == "portfolio_promotion_evidence"
    assert action["owner"] == "portfolio_engineering"
    assert action["priority"] == 25
    assert action["recommended_command"] == "python scripts/build_us_equity_portfolio_promotion_evidence_report.py"
    assert action["blocked_gate_records"][0]["next_action"] == "Resolve portfolio_promotion_evidence"


def test_next_action_queue_includes_local_pit_file_discovery_evidence(tmp_path: Path) -> None:
    _write_completion(tmp_path / "completion.json", [_milestone("production_pit_data", False, ["source_files_missing"])])
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")
    _write_json(
        tmp_path / "discovery.json",
        {
            "status": "pit_file_discovery_ready_for_copy",
            "ready_for_copy_count": 6,
            "required_file_count": 6,
            "ready_filenames": [
                "universe_membership_events.csv",
                "delisted_symbols.csv",
                "corporate_actions.csv",
                "symbol_mapping.csv",
                "adjustment_replay.csv",
                "macro_release_calendar.csv",
            ],
            "missing_filenames": [],
            "files": [
                {"filename": "universe_membership_events.csv", "excluded_candidate_count": 2}
            ],
        },
    )

    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        pit_file_discovery=Path("discovery.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    discovery = payload["next_action"]["evidence"]["local_pit_file_discovery"]
    assert discovery["status"] == "pit_file_discovery_ready_for_copy"
    assert discovery["ready_for_copy_count"] == 6
    assert discovery["excluded_candidate_count"] == 2
    assert discovery["next_command"].startswith("copy manually license-reviewed")
    assert payload["source_reports"]["pit_file_discovery"] == "discovery.json"


def test_next_action_queue_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _write_completion(tmp_path / "completion.json", [_milestone("production_pit_data", False, ["source_dir_missing"])])
    _write_vendor_preflight(tmp_path / "vendor_preflight.json")
    payload = build_us_equity_next_action_queue_report(
        repo_root=tmp_path,
        completion_dependency=Path("completion.json"),
        vendor_drop_preflight=Path("vendor_preflight.json"),
        output=Path("out/queue.json"),
        markdown_output=Path("out/queue.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _milestone(milestone_id: str, passed: bool, blockers: list[str]) -> dict[str, object]:
    actionability = {
        "production_pit_data": "waiting",
        "strategy_validation_gate": "blocked_until_data",
        "portfolio_promotion_evidence": "blocked_until_upstream",
        "forward_observation_30d": "waiting",
        "manual_review_signoff": "manual",
        "paper_simulation_readiness": "blocked_until_review",
        "paper_simulation_evaluation": "waiting",
        "execution_infra_evidence": "actionable",
        "broker_credentials_review": "manual",
        "live_readiness_risk_constitution": "blocked_until_upstream",
        "remediation_ticket_closure": "blocked_until_upstream",
    }.get(milestone_id, "manual")
    dependency_type = {
        "production_pit_data": "external_input",
        "strategy_validation_gate": "engineering_after_data",
        "portfolio_promotion_evidence": "research_evidence",
        "forward_observation_30d": "natural_time",
        "manual_review_signoff": "manual_review",
        "paper_simulation_readiness": "engineering_after_review",
        "paper_simulation_evaluation": "natural_time",
        "execution_infra_evidence": "engineering",
        "broker_credentials_review": "manual_review",
        "live_readiness_risk_constitution": "governance",
        "remediation_ticket_closure": "governance",
    }.get(milestone_id, "manual_triage")
    return {
        "milestone_id": milestone_id,
        "label": milestone_id,
        "passed": passed,
        "actionability": actionability,
        "dependency_type": dependency_type,
        "blockers": blockers,
        "source_reports": [milestone_id],
        "next_action": f"Resolve {milestone_id}",
    }


def _write_completion(path: Path, milestones: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "us_equity_completion_dependency_report_v1",
                "status": "completion_dependencies_blocked",
                "milestones": milestones,
                "source_reports": {
                    str(item["milestone_id"]): f"artifacts/{item['milestone_id']}.json"
                    for item in milestones
                },
            }
        ),
        encoding="utf-8",
    )


def _write_vendor_preflight(path: Path) -> None:
    path.write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
