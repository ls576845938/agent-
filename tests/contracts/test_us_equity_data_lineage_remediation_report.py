from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_data_lineage_remediation_report import (
    build_us_equity_data_lineage_remediation_report,
)


SCHEMA = Path("schemas/us_equity_data_lineage_remediation_report.schema.json")


def test_data_lineage_remediation_groups_current_blockers_without_unlocking(tmp_path: Path) -> None:
    _write_fixture_inputs(tmp_path)

    payload = build_us_equity_data_lineage_remediation_report(
        repo_root=tmp_path,
        output=Path("out/remediation.json"),
        markdown_output=Path("out/remediation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    groups = {group["group_id"]: group for group in payload["remediation_groups"]}
    assert payload["schema_version"] == "us_equity_data_lineage_remediation_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "remediation_required"
    assert groups["point_in_time_universe"]["status"] == "required"
    assert "point_in_time_universe_not_confirmed" in groups["point_in_time_universe"]["matched_blockers"]
    assert "corporate_action_event_source_missing" in groups["corporate_actions_and_adjustments"]["matched_blockers"]
    assert "delisting_coverage_missing" in groups["delisting_and_survivorship"]["matched_blockers"]
    assert "identifier_mapping_missing" in groups["provider_and_identifier_lineage"]["matched_blockers"]
    assert "fred_release_calendar_missing" in groups["macro_release_lag"]["matched_blockers"]
    assert payload["current_evidence"]["tiingo_eod_status"] == "pass"
    assert payload["current_evidence"]["fred_macro_status"] == "pass"
    assert payload["current_evidence"]["macro_release_lag_policy_status"] == "research_lag_only_release_calendar_missing"
    assert payload["current_evidence"]["promotion_clean"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/remediation.json").exists()
    assert (tmp_path / "out/remediation.md").exists()


def test_data_lineage_remediation_blocks_when_data_status_missing(tmp_path: Path) -> None:
    payload = build_us_equity_data_lineage_remediation_report(
        repo_root=tmp_path,
        output=Path("out/remediation.json"),
        markdown_output=Path("out/remediation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "blocked_missing_data_status"
    _validate_schema(payload)
    assert "us_equity_data_status_report_missing" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_data_lineage_remediation_can_report_no_required_work_but_still_no_live_unlock(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {
            "status": "pass",
            "blockers": [],
            "data_lineage_maturity": {
                "price_data_available": True,
                "promotion_clean": True,
            },
        },
    )

    payload = build_us_equity_data_lineage_remediation_report(
        repo_root=tmp_path,
        output=Path("out/remediation.json"),
        markdown_output=Path("out/remediation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "remediation_not_required"
    _validate_schema(payload)
    assert payload["remediation_groups"] == []
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_data_lineage_remediation_schema_rejects_data_fix_claim(tmp_path: Path) -> None:
    _write_fixture_inputs(tmp_path)
    payload = build_us_equity_data_lineage_remediation_report(
        repo_root=tmp_path,
        output=Path("out/remediation.json"),
        markdown_output=Path("out/remediation.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["promotion_clean_granted_by_this_report"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_clean_granted_by_this_report=true")


def _write_fixture_inputs(root: Path) -> None:
    blockers = [
        "point_in_time_universe_not_confirmed",
        "corporate_action_event_source_missing",
        "membership_events_missing",
        "delisting_coverage_missing",
        "identifier_mapping_missing",
        "adjustment_reproducibility_missing",
        "data_lineage_not_promotion_clean",
    ]
    _write_json(
        root / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {
            "status": "partial",
            "blockers": blockers,
            "data_lineage_maturity": {
                "price_data_available": True,
                "point_in_time_universe_confirmed": False,
                "corporate_action_event_source_available": False,
                "delisting_coverage_confirmed": False,
                "identifier_mapping_available": False,
                "adjustment_reproducibility_confirmed": False,
                "promotion_clean": False,
            },
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/provider_verification_report.json",
        {
            "selected_provider": "yfinance",
            "promotion_clean": False,
            "blockers": [
                "selected_provider_not_promotion_clean_capable",
                "provider_required_tables_missing",
            ],
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json",
        {
            "blockers": ["production_bundle_missing", "explicit_bundle_selection_missing"],
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/tiingo_eod_import_report.json",
        {
            "status": "pass",
            "provider": "tiingo",
            "source_type": "market_data_eod",
            "summary": {"available_symbol_count": 24},
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/fred_macro_import_report.json",
        {
            "status": "pass",
            "provider": "FRED",
            "latest_common_date": "2026-06-17",
            "token_written_to_artifacts": False,
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_status/latest/us_equity_data_freshness_daily_report.json",
        {"status": "pass"},
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_macro_release_lag_policy_report.json",
        {
            "status": "research_lag_only_release_calendar_missing",
            "policy": {"macro_lag_days": 2},
            "macro_source": {"release_calendar_fields_present": False},
            "blockers": [
                "fred_release_calendar_missing",
                "macro_revision_vintage_missing",
                "macro_release_lag_not_production_pit",
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
