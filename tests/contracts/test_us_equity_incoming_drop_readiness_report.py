from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema

from scripts.build_us_equity_incoming_drop_readiness_report import (
    build_us_equity_incoming_drop_readiness_report,
)
from tests.contracts.us_equity_local_csv_test_helpers import FIXTURE_ROOT


SCHEMA = Path("schemas/us_equity_incoming_drop_readiness_report.schema.json")


def test_incoming_drop_readiness_blocks_missing_source_dir(tmp_path: Path) -> None:
    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "source_dir_missing" in payload["blockers"]
    assert payload["ready_file_count"] == 0
    assert len(payload["files"]) == 6
    assert any("Create directory: missing_drop" in item for item in payload["operator_next_actions"])
    assert any("build_us_equity_manual_vendor_drop_package.py" in item for item in payload["operator_next_actions"])
    assert payload["guardrails"]["live_order_allowed"] is False


def test_incoming_drop_readiness_blocks_missing_required_csv(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    (source / "corporate_actions.csv").unlink()

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "source_corporate_actions_file_missing" in payload["blockers"]


def test_incoming_drop_readiness_blocks_missing_header(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    path = source / "macro_release_calendar.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("available_time_utc,", ""), encoding="utf-8")

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "source_macro_release_calendar_available_time_utc_missing" in payload["blockers"]


def test_incoming_drop_readiness_blocks_non_csv_substitution(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    (source / "vendor_prices.parquet").write_text("not accepted", encoding="utf-8")

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "unsupported_vendor_drop_file:vendor_prices.parquet" in payload["blockers"]
    assert payload["drop_file_contract"]["unexpected_files"] == ["vendor_prices.parquet"]
    assert payload["drop_file_contract"]["exactly_six_csv_files_required"] is True


def test_incoming_drop_readiness_blocks_unexpected_csv_and_directory(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    (source / "extra_notes.csv").write_text("not,part,of,contract\n", encoding="utf-8")
    (source / "archive").mkdir()

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "unexpected_vendor_drop_csv_file:extra_notes.csv" in payload["blockers"]
    assert "unexpected_vendor_drop_directory:archive" in payload["blockers"]
    assert payload["drop_file_contract"]["unexpected_file_count"] == 2
    assert payload["drop_file_contract"]["unexpected_files"] == ["archive", "extra_notes.csv"]


def test_incoming_drop_readiness_blocks_duplicate_source_record_id(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    path = source / "corporate_actions.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("fixture-action-1", "fixture-membership-1"), encoding="utf-8")

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "source_record_id_duplicate" in payload["blockers"]
    assert payload["row_validation_summary"]["issue_count"] == 1
    corporate_file = _file_report(payload, "corporate_actions")
    assert corporate_file["row_validation"]["issues"][0]["field"] == "source_record_id"
    assert corporate_file["row_validation"]["issues"][0]["blocker"] == "source_record_id_duplicate"


def test_incoming_drop_readiness_blocks_invalid_dates_and_event_types(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    path = source / "universe_membership_events.csv"
    text = path.read_text(encoding="utf-8")
    text = text.replace("list,2020-01-01", "bad_event,2020-13-01", 1)
    path.write_text(text, encoding="utf-8")

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "source_universe_membership_events_effective_date_invalid_date" in payload["blockers"]
    assert "source_universe_membership_events_event_type_invalid" in payload["blockers"]
    membership_file = _file_report(payload, "universe_membership_events")
    issues = membership_file["row_validation"]["issues"]
    assert {issue["field"] for issue in issues} >= {"effective_date", "event_type"}
    assert all(issue["row_number"] >= 2 for issue in issues)


def test_incoming_drop_readiness_blocks_invalid_macro_available_time(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)
    path = source / "macro_release_calendar.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("2020-02-03T13:00:00Z", "2020-02-03 13:00:00"), encoding="utf-8")

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_blocked"
    assert "source_macro_release_calendar_available_time_utc_invalid" in payload["blockers"]
    macro_file = _file_report(payload, "macro_release_calendar")
    assert macro_file["row_validation"]["issues"][0]["field"] == "available_time_utc"


def test_incoming_drop_readiness_ready_for_complete_fixture(tmp_path: Path) -> None:
    source = tmp_path / "drop"
    _copy_fixture_csvs(source)

    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=source,
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "incoming_drop_ready_for_import"
    assert payload["blockers"] == []
    assert payload["ready_file_count"] == 6
    assert payload["drop_file_contract"]["observed_file_count"] == 6
    assert payload["drop_file_contract"]["unexpected_file_count"] == 0
    assert payload["drop_file_contract"]["expected_filenames"] == [
        "universe_membership_events.csv",
        "delisted_symbols.csv",
        "corporate_actions.csv",
        "symbol_mapping.csv",
        "adjustment_replay.csv",
        "macro_release_calendar.csv",
    ]
    assert payload["row_validation_summary"]["checked_file_count"] == 6
    assert payload["row_validation_summary"]["checked_row_count"] > 0
    assert payload["row_validation_summary"]["issue_count"] == 0
    assert not any(item.startswith("Create directory:") for item in payload["operator_next_actions"])
    assert "import_us_equity_local_csv_production_bundle.py" in payload["preferred_import_command"]
    assert (tmp_path / "out/readiness.json").exists()
    assert (tmp_path / "out/readiness.md").exists()


def test_incoming_drop_readiness_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = build_us_equity_incoming_drop_readiness_report(
        repo_root=tmp_path,
        source_dir=Path("missing_drop"),
        output=Path("out/readiness.json"),
        markdown_output=Path("out/readiness.md"),
        generated_at="2026-06-26T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)


def _copy_fixture_csvs(target: Path) -> None:
    target.mkdir(parents=True)
    for path in FIXTURE_ROOT.glob("*.csv"):
        shutil.copy2(path, target / path.name)


def _file_report(payload: dict[str, object], table: str) -> dict[str, object]:
    for item in payload["files"]:
        if item["table"] == table:
            return item
    raise AssertionError(f"missing file report for {table}")
