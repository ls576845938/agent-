from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_pit_operator_handoff_summary import (
    build_us_equity_pit_operator_handoff_summary,
)


SCHEMA = Path("schemas/us_equity_pit_operator_handoff_summary.schema.json")


def test_pit_operator_handoff_blocks_missing_reports_fail_closed(tmp_path: Path) -> None:
    payload = build_us_equity_pit_operator_handoff_summary(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_pit_operator_handoff_summary_v1"
    _validate_schema(payload)
    assert payload["status"] == "handoff_blocked"
    assert "missing_source_report:manual_vendor_drop_package" in payload["blockers"]
    assert "missing_source_report:vendor_drop_operator_progress" in payload["blockers"]
    assert "production_pit_data_intake_not_ready" in payload["blockers"]
    assert "pit_bundle_acceptance_not_ready" in payload["blockers"]
    assert payload["required_table_count"] == 6
    assert payload["incoming_drop_dir"] == "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    assert [item["step_id"] for item in payload["operator_checklist"]] == [
        "build_handoff_package",
        "run_incoming_drop_readiness",
        "rerun_daily_production_line",
    ]
    assert all("paper" not in item["unlocks"] and "live" not in item["unlocks"] for item in payload["operator_checklist"])
    assert any("Create directory: data/external/us_equity_lineage/incoming/manual_vendor_drop" in item for item in payload["operator_next_actions"])
    assert payload["guardrails"]["operator_handoff_only"] is True
    assert payload["guardrails"]["contains_vendor_data"] is False
    assert payload["guardrails"]["production_bundle_written"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["private_endpoint_allowed"] is False
    assert payload["guardrails"]["order_endpoint_allowed"] is False
    assert payload["guardrails"]["real_order_submitted"] is False
    assert payload["guardrails"]["broker_calls_used"] is False
    assert payload["operator_progress"]["status"] == "operator_progress_report_missing"
    assert payload["operator_progress"]["next_action"] == "run vendor drop operator progress report"
    assert payload["copy_readiness_checks"] == []
    assert payload["acceptance_step_summary"] == []
    assert (tmp_path / "out/handoff.json").exists()
    assert (tmp_path / "out/handoff.md").exists()


def test_pit_operator_handoff_summarizes_current_incoming_drop_blocker(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json",
        {
            "status": "manual_vendor_drop_package_ready",
            "incoming_drop_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "default_bundle_id": "manual_vendor_bundle_v1",
            "operator_commands": [
                "python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1 --promotion-clean-allowed"
            ],
            "operator_checklist": [
                {
                    "step_id": "build_handoff_package",
                    "label": "Build package",
                    "command": "python scripts/build_us_equity_manual_vendor_drop_package.py",
                    "expected_evidence": "package ready",
                    "unlocks": "operator_drop_preparation_only",
                },
                {
                    "step_id": "run_incoming_drop_readiness",
                    "label": "Run readiness",
                    "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py",
                    "expected_evidence": "readiness ready",
                    "unlocks": "local_csv_import_only",
                },
                {
                    "step_id": "rerun_daily_production_line",
                    "label": "Rerun daily",
                    "command": "python scripts/run_us_equity_daily_production_line.py",
                    "expected_evidence": "daily refreshed",
                    "unlocks": "status_refresh_only_no_execution_permission",
                },
            ],
            "acceptance_rules": ["Use the exact six CSV filenames."],
            "copy_readiness_checks": [
                {
                    "check_id": "run_contract_preflight",
                    "command": "python scripts/build_us_equity_vendor_drop_preflight_report.py",
                    "expected_result": "preflight ready",
                    "failure_means": "preflight blocked",
                    "blocks_import": True,
                }
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json",
        {
            "status": "incoming_drop_blocked",
            "blockers": ["source_dir_missing"],
            "operator_next_actions": [
                "Create directory: data/external/us_equity_lineage/incoming/manual_vendor_drop",
                "Copy the six licensed CSV files into the incoming drop directory.",
            ],
            "preferred_import_command": "python scripts/import_us_equity_local_csv_production_bundle.py --source-dir data/external/us_equity_lineage/incoming/manual_vendor_drop --bundle-id manual_vendor_bundle_v1 --promotion-clean-allowed",
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {
            "status": "acceptance_blocked",
            "current_blocking_step": "incoming_drop_readiness",
            "blockers": ["source_dir_missing"],
            "steps": [
                {"step_id": "manual_vendor_drop_package", "status": "manual_vendor_drop_package_ready", "passed": True, "blockers": []},
                {"step_id": "incoming_drop_readiness", "status": "incoming_drop_blocked", "passed": False, "blockers": ["source_dir_missing"]},
                {
                    "step_id": "local_csv_production_bundle_import",
                    "status": "SKIPPED",
                    "passed": False,
                    "blockers": ["local_csv_production_bundle_import_skipped_until_incoming_drop_readiness_passes"],
                    "skipped_due_to_step_id": "incoming_drop_readiness",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_data_intake_status_report.json",
        {
            "status": "production_pit_data_intake_blocked",
            "current_blocking_stage": "incoming_drop_readiness",
            "blockers": ["source_dir_missing"],
            "operator_next_actions": ["Run: python scripts/build_us_equity_manual_vendor_drop_package.py"],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json",
        {
            "status": "development_plan_blocked_by_production_pit_data",
            "phases": [
                {
                    "phase_id": "production_pit_data",
                    "evidence": {
                        "operator_next_actions": [
                            "Copy the six licensed CSV files into the incoming drop directory using docs/us_equity_manual_vendor_drop_templates headers."
                        ]
                    },
                }
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_vendor_drop_operator_progress_report.json",
        {
            "status": "operator_drop_blocked",
            "completed_count": 2,
            "blocked_count": 3,
            "pending_count": 2,
            "step_count": 7,
            "next_step_id": "create_incoming_drop_dir",
            "next_action": "mkdir drop",
            "copy_readiness_checks": [
                {
                    "check_id": "incoming_dir_exists",
                    "command": "Test-Path drop",
                    "expected_result": "True",
                    "failure_means": "directory missing",
                    "blocks_import": True,
                }
            ],
        },
    )

    payload = build_us_equity_pit_operator_handoff_summary(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    assert payload["status"] == "handoff_blocked"
    _validate_schema(payload)
    assert payload["current_blocking_stage"] == "incoming_drop_readiness"
    assert payload["current_blocking_step"] == "incoming_drop_readiness"
    assert payload["blockers"].count("source_dir_missing") == 1
    assert payload["commands"]["preferred_import"].endswith("--promotion-clean-allowed")
    assert payload["operator_checklist"][1]["step_id"] == "run_incoming_drop_readiness"
    assert len(payload["operator_next_actions"]) >= 4
    assert payload["source_reports"]["pit_bundle_acceptance"]["status"] == "acceptance_blocked"
    assert payload["source_reports"]["vendor_drop_operator_progress"]["status"] == "operator_drop_blocked"
    assert payload["operator_progress"]["completed_count"] == 2
    assert payload["operator_progress"]["next_step_id"] == "create_incoming_drop_dir"
    assert payload["copy_readiness_checks"][0]["check_id"] == "incoming_dir_exists"
    acceptance_steps = {item["step_id"]: item for item in payload["acceptance_step_summary"]}
    assert acceptance_steps["local_csv_production_bundle_import"]["status"] == "SKIPPED"
    assert acceptance_steps["local_csv_production_bundle_import"]["skipped_due_to_step_id"] == "incoming_drop_readiness"
    assert payload["guardrails"]["live_order_allowed"] is False


def test_pit_operator_handoff_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = build_us_equity_pit_operator_handoff_summary(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-26T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_pit_operator_handoff_schema_rejects_checklist_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_pit_operator_handoff_summary(
        repo_root=tmp_path,
        output=Path("out/handoff.json"),
        markdown_output=Path("out/handoff.md"),
        generated_at="2026-06-26T00:00:00Z",
    )
    payload["operator_checklist"][0]["unlocks"] = "live_permission"

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted checklist live unlock")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
