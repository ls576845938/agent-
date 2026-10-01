from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import jsonschema

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_local_csv_bundle_manifest import DEFAULT_FILENAMES
from scripts.build_us_equity_manual_vendor_drop_package import (
    build_us_equity_manual_vendor_drop_package,
)


SCHEMA = Path("schemas/us_equity_manual_vendor_drop_package_report.schema.json")


def test_manual_vendor_drop_package_writes_templates_and_docs(tmp_path: Path) -> None:
    payload = build_us_equity_manual_vendor_drop_package(
        repo_root=tmp_path,
        output=Path("out/package.json"),
        markdown_output=Path("out/package.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "manual_vendor_drop_package_ready"
    assert payload["incoming_drop_dir"] == "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    assert payload["default_bundle_id"] == "manual_vendor_bundle_v1"
    assert payload["required_table_count"] == 6
    assert [item["check_id"] for item in payload["copy_readiness_checks"]] == [
        "incoming_dir_exists",
        "all_required_filenames_present",
        "no_header_only_templates",
        "run_contract_preflight",
    ]
    assert all(item["blocks_import"] is True for item in payload["copy_readiness_checks"])
    assert all("live" not in item["expected_result"].lower() for item in payload["copy_readiness_checks"])
    boundaries = payload["source_boundary_rules"]
    assert {item["route_id"] for item in boundaries["acceptable_routes"]} >= {"crsp", "curated_local_csv"}
    assert all(item["must_normalize_to_local_csv_contract"] is True for item in boundaries["acceptable_routes"])
    supplemental = {item["route_id"]: item for item in boundaries["supplemental_only_routes"]}
    assert {"tiingo_eod", "ibkr_market_data", "fred"} <= set(supplemental)
    assert "standalone L4 promotion-clean approval" in supplemental["tiingo_eod"]["not_sufficient_for"]
    assert "yfinance_only_exports" in boundaries["rejected_routes"]
    assert "promotion-clean" in boundaries["promotion_clean_rule"]
    assert [item["step_id"] for item in payload["operator_checklist"]] == [
        "build_handoff_package",
        "create_incoming_drop_dir",
        "copy_six_licensed_csv_files",
        "run_incoming_drop_readiness",
        "import_local_csv_bundle",
        "run_acceptance_and_activation",
        "rerun_daily_production_line",
    ]
    assert all("paper" not in item["unlocks"] and "live" not in item["unlocks"] for item in payload["operator_checklist"])
    assert payload["guardrails"]["contains_vendor_data"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / payload["field_dictionary"]).exists()
    assert (tmp_path / payload["handoff_doc"]).exists()
    assert (tmp_path / "out/package.json").exists()
    assert (tmp_path / "out/package.md").exists()


def test_manual_vendor_drop_templates_match_provider_contract(tmp_path: Path) -> None:
    payload = build_us_equity_manual_vendor_drop_package(
        repo_root=tmp_path,
        output=Path("out/package.json"),
        markdown_output=Path("out/package.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    assert {item["table"] for item in payload["template_files"]} == set(REQUIRED_LOCAL_CSV_FILES)
    for item in payload["template_files"]:
        table = item["table"]
        assert item["filename"] == DEFAULT_FILENAMES[table]
        assert len(item["header_sha256"]) == 64
        assert len(item["template_file_sha256"]) == 64
        assert item["header_sha256"] == hashlib.sha256(",".join(REQUIRED_LOCAL_CSV_FILES[table]).encode("utf-8")).hexdigest()
        path = tmp_path / item["path"]
        with path.open("r", encoding="utf-8", newline="") as handle:
            headers = next(csv.reader(handle))
            remaining = list(csv.reader(handle))
        assert headers == REQUIRED_LOCAL_CSV_FILES[table]
        assert remaining == []
        assert item["template_file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_manual_vendor_drop_field_dictionary_includes_macro_release_calendar(tmp_path: Path) -> None:
    payload = build_us_equity_manual_vendor_drop_package(
        repo_root=tmp_path,
        output=Path("out/package.json"),
        markdown_output=Path("out/package.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    dictionary = (tmp_path / payload["field_dictionary"]).read_text(encoding="utf-8")
    handoff = (tmp_path / payload["handoff_doc"]).read_text(encoding="utf-8")
    assert "`macro_release_calendar`" in dictionary
    assert "`available_time_utc`" in dictionary
    assert "UTC timestamp ending with Z" in dictionary
    assert "Source Boundary Rules" in handoff
    assert "`tiingo_eod`" in handoff
    assert payload["field_count"] == sum(len(fields) for fields in REQUIRED_LOCAL_CSV_FILES.values())


def test_manual_vendor_drop_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = build_us_equity_manual_vendor_drop_package(
        repo_root=tmp_path,
        output=Path("out/package.json"),
        markdown_output=Path("out/package.md"),
        generated_at="2026-06-26T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def test_manual_vendor_drop_schema_rejects_checklist_live_unlock(tmp_path: Path) -> None:
    payload = build_us_equity_manual_vendor_drop_package(
        repo_root=tmp_path,
        output=Path("out/package.json"),
        markdown_output=Path("out/package.md"),
        generated_at="2026-06-26T00:00:00Z",
    )
    payload["operator_checklist"][0]["unlocks"] = "live_permission"

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted checklist live unlock")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
