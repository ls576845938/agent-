from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_pit_procurement_readiness_report import (
    build_us_equity_pit_procurement_readiness_report,
)


SCHEMA = Path("schemas/us_equity_pit_procurement_readiness_report.schema.json")


def test_procurement_readiness_requires_discovery_before_review(tmp_path: Path) -> None:
    payload = build_us_equity_pit_procurement_readiness_report(
        repo_root=tmp_path,
        discovery_report=Path("missing.json"),
        output=Path("out/procurement.json"),
        markdown_output=Path("out/procurement.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "pit_procurement_blocked"
    assert payload["summary"]["required_file_count"] == 6
    assert payload["summary"]["missing_file_count"] == 6
    assert payload["blockers"] == ["local_pit_file_discovery_report_missing_or_unreadable"]
    assert payload["guardrails"]["files_copied"] is False
    assert payload["guardrails"]["vendor_data_imported"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/procurement.json").exists()
    assert (tmp_path / "out/procurement.md").exists()


def test_procurement_readiness_lists_missing_vendor_files(tmp_path: Path) -> None:
    discovery = {
        "status": "pit_file_discovery_no_complete_candidate_set",
        "ready_for_copy_count": 0,
        "required_file_count": 6,
        "files": [],
    }
    discovery_path = tmp_path / "discovery.json"
    discovery_path.write_text(json.dumps(discovery), encoding="utf-8")

    payload = build_us_equity_pit_procurement_readiness_report(
        repo_root=tmp_path,
        discovery_report=discovery_path,
        output=Path("out/procurement.json"),
        markdown_output=Path("out/procurement.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "pit_procurement_ready_for_vendor_order"
    assert payload["summary"]["missing_file_count"] == 6
    assert payload["missing_filenames"] == [
        "universe_membership_events.csv",
        "delisted_symbols.csv",
        "corporate_actions.csv",
        "symbol_mapping.csv",
        "adjustment_replay.csv",
        "macro_release_calendar.csv",
    ]
    assert "fixtures" in payload["unacceptable_sources"]
    assert "yfinance_only_exports" in payload["unacceptable_sources"]
    assert {item["route_id"] for item in payload["acceptable_source_routes"]} >= {
        "crsp",
        "sharadar_nasdaq_data_link",
        "polygon_massive",
        "norgate",
        "curated_local_csv",
    }
    supplemental = {item["route_id"]: item for item in payload["supplemental_source_routes"]}
    assert {"tiingo_eod", "ibkr_market_data", "fred"} <= set(supplemental)
    assert "standalone L4 promotion-clean approval" in supplemental["tiingo_eod"]["not_sufficient_for"]
    assert "survivorship-bias-free research universe" in supplemental["ibkr_market_data"]["not_sufficient_for"]
    assert "equity universe membership" in supplemental["fred"]["not_sufficient_for"]
    assert any("supplemental inputs" in item for item in payload["operator_next_actions"])


def test_procurement_readiness_ready_candidates_still_do_not_unlock(tmp_path: Path) -> None:
    files = []
    for filename in (
        "universe_membership_events.csv",
        "delisted_symbols.csv",
        "corporate_actions.csv",
        "symbol_mapping.csv",
        "adjustment_replay.csv",
        "macro_release_calendar.csv",
    ):
        files.append(
            {
                "filename": filename,
                "ready_for_copy": True,
                "ready_candidates": [{"path": f"D:/vendor/{filename}"}],
                "excluded_candidate_count": 0,
            }
        )
    discovery_path = tmp_path / "discovery.json"
    discovery_path.write_text(
        json.dumps(
            {
                "status": "pit_file_discovery_ready_for_copy",
                "ready_for_copy_count": 6,
                "required_file_count": 6,
                "files": files,
            }
        ),
        encoding="utf-8",
    )

    payload = build_us_equity_pit_procurement_readiness_report(
        repo_root=tmp_path,
        discovery_report=discovery_path,
        output=Path("out/procurement.json"),
        markdown_output=Path("out/procurement.md"),
        generated_at="2026-06-28T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "pit_procurement_ready_for_manual_license_review"
    assert payload["summary"]["ready_for_manual_license_review_count"] == 6
    assert payload["blockers"] == []
    assert payload["guardrails"]["license_reviewed_by_this_report"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_procurement_schema_rejects_live_unlock() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = {
        "schema_version": "us_equity_pit_procurement_readiness_report_v1",
        "generated_at": "2026-06-28T00:00:00Z",
        "asset": "us_equity",
        "status": "pit_procurement_ready_for_vendor_order",
        "allowed_statuses": [
            "pit_procurement_blocked",
            "pit_procurement_ready_for_vendor_order",
            "pit_procurement_ready_for_manual_license_review",
        ],
        "decision": "x",
        "summary": {
            "required_file_count": 6,
            "ready_for_manual_license_review_count": 0,
            "missing_file_count": 6,
            "acceptable_source_route_count": 1,
            "supplemental_source_route_count": 1,
            "unacceptable_source_count": 1,
            "paper_or_live_unlock_allowed": False,
            "live_order_allowed": True,
        },
        "required_files": [
            {
                "table": f"table_{i}",
                "filename": f"file_{i}.csv",
                "required_fields": ["security_id"],
                "target_path": "x",
                "readiness_status": "missing_vendor_export",
                "ready_candidate_count": 0,
                "excluded_candidate_count": 0,
                "first_ready_candidate_path": None,
            }
            for i in range(6)
        ],
        "missing_filenames": ["x"],
        "ready_filenames": [],
        "acceptable_source_routes": [{"route_id": "x", "label": "x", "mapping_doc": "x"}],
        "supplemental_source_routes": [
            {
                "route_id": "tiingo_eod",
                "label": "x",
                "usable_for": ["research price refresh"],
                "not_sufficient_for": ["standalone L4 promotion-clean approval"],
            }
        ],
        "unacceptable_sources": ["fixtures"],
        "minimum_delivery_requirements": ["x"],
        "source_reports": {"x": "x"},
        "blockers": [],
        "operator_next_actions": ["x"],
        "guardrails": {
            "procurement_readiness_only": True,
            "files_copied": False,
            "vendor_data_imported": False,
            "configuration_mutated_by_this_report": False,
            "license_reviewed_by_this_report": False,
            "promotion_clean_granted_by_this_report": False,
            "paper_or_live_unlock_allowed": False,
            "paper_simulation_allowed": False,
            "live_order_allowed": False,
            "private_endpoint_allowed": False,
            "order_endpoint_allowed": False,
            "real_order_submitted": False,
            "broker_calls_used": False,
        },
        "outputs": {"json": "x", "markdown": "x"},
    }

    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted summary.live_order_allowed=true")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
