from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_vendor_drop_operator_progress_report import (
    build_us_equity_vendor_drop_operator_progress_report,
)


SCHEMA = Path("schemas/us_equity_vendor_drop_operator_progress_report.schema.json")


def test_vendor_drop_operator_progress_blocks_missing_drop_dir(tmp_path: Path) -> None:
    _write_sources(tmp_path, incoming_ready=False)

    payload = build_us_equity_vendor_drop_operator_progress_report(
        repo_root=tmp_path,
        output=Path("out/progress.json"),
        markdown_output=Path("out/progress.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "operator_drop_blocked"
    assert payload["completed_count"] == 2
    assert payload["blocked_count"] == 3
    assert payload["pending_count"] == 2
    assert payload["next_step_id"] == "create_incoming_drop_dir"
    assert payload["required_file_progress"] == {
        "required_file_count": 6,
        "ready_file_count": 0,
        "missing_file_count": 6,
        "blocked_file_count": 6,
    }
    copy_contract = payload["operator_copy_contract"]
    assert copy_contract["incoming_drop_dir"] == "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    assert copy_contract["required_file_count"] == 6
    assert copy_contract["required_filenames"] == [
        "universe_membership_events.csv",
        "delisted_symbols.csv",
        "corporate_actions.csv",
        "symbol_mapping.csv",
        "adjustment_replay.csv",
        "macro_release_calendar.csv",
    ]
    assert "parquet" in copy_contract["forbidden_substitutes"]
    assert "xlsx" in copy_contract["forbidden_substitutes"]
    assert copy_contract["guardrails"]["contains_vendor_data"] is False
    assert copy_contract["guardrails"]["empty_templates_are_not_valid_evidence"] is True
    assert [item["check_id"] for item in payload["copy_readiness_checks"]] == [
        "incoming_dir_exists",
        "all_required_filenames_present",
        "no_header_only_templates",
        "run_contract_preflight",
    ]
    assert all(item["blocks_import"] is True for item in payload["copy_readiness_checks"])
    assert len(payload["missing_required_files"]) == 6
    assert payload["ready_required_files"] == []
    steps = {item["step_id"]: item for item in payload["steps"]}
    assert steps["build_handoff_package"]["status"] == "completed"
    assert steps["create_incoming_drop_dir"]["status"] == "blocked"
    assert steps["create_incoming_drop_dir"]["first_blocker"] == "source_dir_missing"
    assert steps["run_incoming_drop_readiness"]["status"] == "blocked"
    assert steps["import_local_csv_bundle"]["status"] == "pending"
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/progress.json").exists()
    assert (tmp_path / "out/progress.md").exists()


def test_vendor_drop_operator_progress_ready_for_import_after_readiness(tmp_path: Path) -> None:
    (tmp_path / "data/external/us_equity_lineage/incoming/manual_vendor_drop").mkdir(parents=True)
    _write_sources(tmp_path, incoming_ready=True)

    payload = build_us_equity_vendor_drop_operator_progress_report(
        repo_root=tmp_path,
        output=Path("out/progress.json"),
        markdown_output=Path("out/progress.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "operator_drop_ready_for_import"
    assert payload["next_step_id"] == "import_local_csv_bundle"
    assert payload["required_file_progress"] == {
        "required_file_count": 6,
        "ready_file_count": 6,
        "missing_file_count": 0,
        "blocked_file_count": 0,
    }
    assert payload["missing_required_files"] == []
    assert len(payload["ready_required_files"]) == 6
    steps = {item["step_id"]: item for item in payload["steps"]}
    assert steps["copy_six_licensed_csv_files"]["status"] == "completed"
    assert steps["run_incoming_drop_readiness"]["status"] == "completed"
    assert steps["import_local_csv_bundle"]["status"] == "blocked"


def test_vendor_drop_operator_progress_complete_after_acceptance_and_daily(tmp_path: Path) -> None:
    (tmp_path / "data/external/us_equity_lineage/incoming/manual_vendor_drop").mkdir(parents=True)
    _write_sources(tmp_path, incoming_ready=True, imported=True, accepted=True, daily_refreshed=True)

    payload = build_us_equity_vendor_drop_operator_progress_report(
        repo_root=tmp_path,
        output=Path("out/progress.json"),
        markdown_output=Path("out/progress.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "operator_drop_complete_for_manual_review"
    assert payload["completed_count"] == payload["step_count"]
    assert payload["next_step_id"] == ""
    assert payload["blockers"] == []


def test_vendor_drop_operator_progress_schema_rejects_live_flag(tmp_path: Path) -> None:
    _write_sources(tmp_path, incoming_ready=False)
    payload = build_us_equity_vendor_drop_operator_progress_report(
        repo_root=tmp_path,
        output=Path("out/progress.json"),
        markdown_output=Path("out/progress.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_vendor_drop_operator_progress_schema_rejects_copy_contract_vendor_data_flag(tmp_path: Path) -> None:
    _write_sources(tmp_path, incoming_ready=False)
    payload = build_us_equity_vendor_drop_operator_progress_report(
        repo_root=tmp_path,
        output=Path("out/progress.json"),
        markdown_output=Path("out/progress.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["operator_copy_contract"]["guardrails"]["contains_vendor_data"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted operator_copy_contract containing vendor data")


def _write_sources(
    tmp_path: Path,
    *,
    incoming_ready: bool,
    imported: bool = False,
    accepted: bool = False,
    daily_refreshed: bool = True,
) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json",
        {
            "status": "manual_vendor_drop_package_ready",
            "required_tables": [
                {"table": "universe_membership_events", "filename": "universe_membership_events.csv", "minimum_record_count": 1, "required_fields": ["security_id", "ticker"], "empty_template_is_not_valid_drop": True},
                {"table": "delisted_symbols", "filename": "delisted_symbols.csv", "minimum_record_count": 1, "required_fields": ["security_id", "ticker"], "empty_template_is_not_valid_drop": True},
                {"table": "corporate_actions", "filename": "corporate_actions.csv", "minimum_record_count": 1, "required_fields": ["security_id", "ticker"], "empty_template_is_not_valid_drop": True},
                {"table": "symbol_mapping", "filename": "symbol_mapping.csv", "minimum_record_count": 1, "required_fields": ["security_id", "ticker"], "empty_template_is_not_valid_drop": True},
                {"table": "adjustment_replay", "filename": "adjustment_replay.csv", "minimum_record_count": 1, "required_fields": ["security_id", "ticker"], "empty_template_is_not_valid_drop": True},
                {"table": "macro_release_calendar", "filename": "macro_release_calendar.csv", "minimum_record_count": 1, "required_fields": ["series_id", "release_date"], "empty_template_is_not_valid_drop": True},
            ],
            "operator_checklist": [
                {"step_id": "build_handoff_package", "label": "Build package", "command": "python scripts/build_us_equity_manual_vendor_drop_package.py", "expected_evidence": "package ready", "unlocks": "operator_drop_preparation_only"},
                {"step_id": "create_incoming_drop_dir", "label": "Create drop dir", "command": "mkdir drop", "expected_evidence": "drop dir exists", "unlocks": "csv_copy_step_only"},
                {"step_id": "copy_six_licensed_csv_files", "label": "Copy CSV files", "command": "manual_file_copy", "expected_evidence": "six files", "unlocks": "incoming_drop_readiness_check"},
                {"step_id": "run_incoming_drop_readiness", "label": "Run readiness", "command": "python scripts/build_us_equity_incoming_drop_readiness_report.py", "expected_evidence": "readiness ready", "unlocks": "local_csv_import_only"},
                {"step_id": "import_local_csv_bundle", "label": "Import bundle", "command": "python scripts/import_us_equity_local_csv_production_bundle.py", "expected_evidence": "imported", "unlocks": "activation_preflight_only"},
                {"step_id": "run_acceptance_and_activation", "label": "Run acceptance", "command": "python scripts/run_us_equity_pit_bundle_acceptance.py", "expected_evidence": "accepted", "unlocks": "manual_config_apply_review_only"},
                {"step_id": "rerun_daily_production_line", "label": "Rerun daily", "command": "python scripts/run_us_equity_daily_production_line.py", "expected_evidence": "daily refreshed", "unlocks": "status_refresh_only_no_execution_permission"},
            ],
            "copy_readiness_checks": [
                {"check_id": "incoming_dir_exists", "command": "Test-Path drop", "expected_result": "True", "failure_means": "directory missing", "blocks_import": True},
                {"check_id": "all_required_filenames_present", "command": "check names", "expected_result": "No output", "failure_means": "file missing", "blocks_import": True},
                {"check_id": "no_header_only_templates", "command": "check rows", "expected_result": "No output", "failure_means": "empty file", "blocks_import": True},
                {"check_id": "run_contract_preflight", "command": "python scripts/build_us_equity_vendor_drop_preflight_report.py", "expected_result": "preflight ready", "failure_means": "preflight blocked", "blocks_import": True},
            ],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json",
        {
            "status": "incoming_drop_ready_for_import" if incoming_ready else "incoming_drop_blocked",
            "ready_file_count": 6 if incoming_ready else 0,
            "required_file_count": 6,
            "blockers": [] if incoming_ready else ["source_dir_missing"],
            "files": _readiness_files(incoming_ready),
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_local_csv_production_bundle_import_report.json",
        {"status": "production_bundle_imported" if imported else "production_bundle_import_blocked", "blockers": [] if imported else ["local_csv_import_not_complete"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {"status": "acceptance_ready_for_manual_config_apply" if accepted else "acceptance_blocked", "blockers": [] if accepted else ["pit_acceptance_not_ready"]},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json",
        {"status": "PASS", "production_pit_drop": {"status": "incoming_drop_ready_for_import"} if daily_refreshed else {}},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def _readiness_files(incoming_ready: bool) -> list[dict[str, object]]:
    tables = [
        "universe_membership_events",
        "delisted_symbols",
        "corporate_actions",
        "symbol_mapping",
        "adjustment_replay",
        "macro_release_calendar",
    ]
    return [
        {
            "table": table,
            "filename": f"{table}.csv",
            "exists": incoming_ready,
            "record_count": 10 if incoming_ready else 0,
            "blockers": [] if incoming_ready else [f"source_{table}_file_missing"],
        }
        for table in tables
    ]
