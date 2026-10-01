from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES
from scripts.build_us_equity_local_pit_file_discovery_report import (
    build_us_equity_local_pit_file_discovery_report,
)


SCHEMA = Path("schemas/us_equity_local_pit_file_discovery_report.schema.json")


def test_local_pit_file_discovery_finds_complete_candidate_set(tmp_path: Path) -> None:
    vendor = tmp_path / "licensed_vendor"
    _write_required_files(vendor)
    _write_required_files(tmp_path / ".tmp/test_fixtures")

    payload = build_us_equity_local_pit_file_discovery_report(
        repo_root=tmp_path,
        search_roots=[vendor, tmp_path / ".tmp"],
        output=Path("out/discovery.json"),
        markdown_output=Path("out/discovery.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "pit_file_discovery_ready_for_copy"
    assert payload["ready_for_copy_count"] == 6
    assert payload["missing_filenames"] == []
    assert payload["guardrails"]["files_copied"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert all(item["ready_candidates"] for item in payload["files"])
    assert any(item["excluded_candidates"] for item in payload["files"])
    assert (tmp_path / "out/discovery.md").exists()


def test_local_pit_file_discovery_excludes_tmp_only_candidates(tmp_path: Path) -> None:
    _write_required_files(tmp_path / ".tmp/test_fixtures")

    payload = build_us_equity_local_pit_file_discovery_report(
        repo_root=tmp_path,
        search_roots=[tmp_path / ".tmp"],
        output=Path("out/discovery.json"),
        markdown_output=Path("out/discovery.md"),
        generated_at="2026-06-27T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "pit_file_discovery_no_complete_candidate_set"
    assert payload["ready_for_copy_count"] == 0
    assert sorted(payload["missing_filenames"]) == sorted(DEFAULT_FILENAMES.values())
    assert all(not item["ready_for_copy"] for item in payload["files"])
    assert all(item["excluded_candidates"] for item in payload["files"])


def test_local_pit_file_discovery_schema_rejects_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_local_pit_file_discovery_report(
        repo_root=tmp_path,
        search_roots=[tmp_path / "missing"],
        output=Path("out/discovery.json"),
        markdown_output=Path("out/discovery.md"),
        generated_at="2026-06-27T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_required_files(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        path = root / DEFAULT_FILENAMES[table]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(fields)
            writer.writerow([_sample_value(field) for field in fields])


def _sample_value(field: str) -> str:
    if field == "available_time_utc":
        return "2026-06-01T13:30:00Z"
    if field.endswith("_date") or field in {"date", "start_date", "end_date", "ex_date", "release_date", "last_trade_date"}:
        return "2026-06-01"
    if field in {"ratio", "cash_amount", "delisting_return", "raw_close", "adjusted_close", "split_factor", "dividend_adjustment", "total_adjustment_factor", "replay_adjusted_close", "replay_error"}:
        return "1.0"
    if field == "event_type":
        return "add"
    if field == "source_record_id":
        return "src_1"
    if field == "series_id":
        return "DGS10"
    return "SPY"


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
