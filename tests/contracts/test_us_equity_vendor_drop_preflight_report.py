from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES
from scripts.build_us_equity_manual_vendor_drop_package import build_us_equity_manual_vendor_drop_package
from scripts.build_us_equity_vendor_drop_preflight_report import build_us_equity_vendor_drop_preflight_report


SCHEMA = Path("schemas/us_equity_vendor_drop_preflight_report.schema.json")


def test_vendor_drop_preflight_blocks_when_package_missing(tmp_path: Path) -> None:
    payload = build_us_equity_vendor_drop_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "vendor_drop_preflight_blocked"
    assert "manual_vendor_drop_package_report_missing" in payload["blockers"]
    assert payload["guardrails"]["source_vendor_data_modified"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_vendor_drop_preflight_waits_for_files_after_package_ready(tmp_path: Path) -> None:
    build_us_equity_manual_vendor_drop_package(repo_root=tmp_path, generated_at="2026-06-27T00:00:00Z")

    payload = build_us_equity_vendor_drop_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "vendor_drop_preflight_waiting_for_vendor_files"
    assert "source_dir_missing" in payload["blockers"]
    assert payload["ready_file_count"] == 0
    assert payload["missing_file_count"] == len(REQUIRED_LOCAL_CSV_FILES)
    assert len(payload["required_files"]) == len(REQUIRED_LOCAL_CSV_FILES)
    assert len(payload["missing_required_files"]) == len(REQUIRED_LOCAL_CSV_FILES)
    assert payload["ready_required_files"] == []
    assert len(payload["file_copy_plan"]) == len(REQUIRED_LOCAL_CSV_FILES)
    assert {item["filename"] for item in payload["required_files"]} == set(DEFAULT_FILENAMES.values())
    assert {item["filename"] for item in payload["file_copy_plan"]} == set(DEFAULT_FILENAMES.values())
    assert all(item["ready"] is False for item in payload["required_files"])
    assert all(item["current_state"] in {"missing", "header_mismatch"} for item in payload["file_copy_plan"])
    assert all(item["ready_after_action_requires_rerun"] is True for item in payload["file_copy_plan"])
    assert all(item["template_path"].startswith("docs/us_equity_manual_vendor_drop_templates/") for item in payload["file_copy_plan"])
    assert all(item["operator_action"] in {"copy_licensed_csv_with_exact_header_to_target_path", "replace_file_or_reexport_with_exact_template_header"} for item in payload["file_copy_plan"])
    metadata = payload["import_metadata_requirements"]
    assert metadata["bundle_id"] == "manual_vendor_bundle_v1"
    assert metadata["source_type_required"] == "production"
    assert "--license-note" in metadata["required_cli_args"]
    assert "--promotion-clean-allowed" in metadata["required_cli_args"]
    assert "<licensed provider scope>" in metadata["preferred_import_command_template"]
    assert any("Copy the licensed CSV files" in item for item in payload["operator_next_actions"])


def test_vendor_drop_preflight_ready_when_all_csv_headers_and_rows_exist(tmp_path: Path) -> None:
    build_us_equity_manual_vendor_drop_package(repo_root=tmp_path, generated_at="2026-06-27T00:00:00Z")
    source = tmp_path / "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    source.mkdir(parents=True)
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        with (source / DEFAULT_FILENAMES[table]).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerow([_sample_value(field) for field in fields])

    payload = build_us_equity_vendor_drop_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "vendor_drop_preflight_ready_for_readiness_check"
    assert payload["blockers"] == []
    assert payload["ready_file_count"] == len(REQUIRED_LOCAL_CSV_FILES)
    assert payload["missing_file_count"] == 0
    assert payload["missing_required_files"] == []
    assert len(payload["ready_required_files"]) == len(REQUIRED_LOCAL_CSV_FILES)
    assert all(item["exists"] is True for item in payload["required_files"])
    assert all(item["header_matches"] is True for item in payload["required_files"])
    assert all(item["data_row_count"] == 1 for item in payload["required_files"])
    assert all(item["current_state"] == "ready" for item in payload["file_copy_plan"])
    assert all(item["operator_action"] == "no_action_required" for item in payload["file_copy_plan"])
    assert all(item["ready_after_action_requires_rerun"] is False for item in payload["file_copy_plan"])
    assert payload["guardrails"]["production_bundle_written"] is False


def test_vendor_drop_preflight_file_copy_plan_identifies_header_only_templates(tmp_path: Path) -> None:
    build_us_equity_manual_vendor_drop_package(repo_root=tmp_path, generated_at="2026-06-27T00:00:00Z")
    source = tmp_path / "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    source.mkdir(parents=True)
    table = "universe_membership_events"
    with (source / DEFAULT_FILENAMES[table]).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(REQUIRED_LOCAL_CSV_FILES[table])

    payload = build_us_equity_vendor_drop_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    plan = {item["table"]: item for item in payload["file_copy_plan"]}
    missing = {item["table"]: item for item in payload["missing_required_files"]}
    assert plan[table]["current_state"] == "header_only"
    assert plan[table]["current_blocker"] == "universe_membership_events_csv_header_only"
    assert plan[table]["operator_action"] == "replace_template_with_licensed_vendor_rows"
    assert plan[table]["ready_after_action_requires_rerun"] is True
    assert missing[table]["blocker"] == "universe_membership_events_csv_header_only"


def test_vendor_drop_preflight_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = build_us_equity_vendor_drop_preflight_report(
        repo_root=tmp_path,
        output=Path("out/preflight.json"),
        markdown_output=Path("out/preflight.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _sample_value(field: str) -> str:
    if field.endswith("_utc") or field in {"effective_date", "as_of_date", "observation_date", "release_date"}:
        return "2026-01-01T00:00:00Z"
    if field in {"symbol", "old_symbol", "new_symbol"}:
        return "SPY"
    if field in {"series_id", "event_type", "action_type", "adjustment_type", "source_provider", "source_type"}:
        return "sample"
    return "1"


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
