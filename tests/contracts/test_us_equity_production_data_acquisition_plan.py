from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_production_data_acquisition_plan import (
    build_us_equity_production_data_acquisition_plan,
)


SCHEMA = Path("schemas/us_equity_production_data_acquisition_plan.schema.json")


def test_production_data_acquisition_plan_maps_blockers_to_required_tables(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path)

    payload = build_us_equity_production_data_acquisition_plan(
        repo_root=tmp_path,
        output=Path("out/acquisition.json"),
        markdown_output=Path("out/acquisition.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_production_data_acquisition_plan_v1"
    _validate_schema(payload)
    assert payload["status"] == "production_data_acquisition_required"
    assert {"crsp", "sharadar", "norgate", "local_csv"} <= set(payload["acceptable_provider_ids"])
    assert {row["table"] for row in payload["required_tables"]} == {
        "universe_membership_events",
        "delisted_symbols",
        "corporate_actions",
        "symbol_mapping",
        "adjustment_replay",
        "macro_release_calendar",
    }
    assert {"pit_universe", "survivorship", "corporate_actions", "adjustment_replay", "macro_release_calendar"} <= set(
        payload["missing_contract_groups"]
    )
    assert any(item["provider_id"] == "tiingo" for item in payload["non_substitutes"])
    assert payload["local_csv_drop_contract"]["incoming_drop_dir"] == "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    assert payload["local_csv_drop_contract"]["default_bundle_id"] == "manual_vendor_bundle_v1"
    assert "macro_release_calendar.csv" in payload["local_csv_drop_contract"]["required_filenames"]
    assert "import_us_equity_local_csv_production_bundle.py" in payload["local_csv_drop_contract"]["preferred_import_command"]
    assert payload["current_drop_readiness"]["status"] == "incoming_drop_blocked"
    assert payload["current_drop_readiness"]["ready_file_count"] == 0
    assert payload["current_drop_readiness"]["required_file_count"] == 6
    assert payload["current_drop_readiness"]["first_blocker"] == "source_dir_missing"
    table_status = {row["table"]: row for row in payload["contract_status_by_table"]}
    assert table_status["universe_membership_events"]["status"] == "blocked"
    assert table_status["universe_membership_events"]["exists"] is False
    assert "source_universe_membership_events_file_missing" in table_status["universe_membership_events"]["blockers"]
    assert any("import_us_equity_local_csv_production_bundle.py" in item for item in payload["acceptance_commands"])
    assert any("build_us_equity_production_bundle_activation_report.py" in item for item in payload["acceptance_commands"])
    assert payload["promotion_acceptance_criteria"]["paper_or_live_unlock_allowed_by_this_plan"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/acquisition.json").exists()
    assert (tmp_path / "out/acquisition.md").exists()


def test_production_data_acquisition_plan_does_not_grant_promotion_when_clean(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, blockers=[])
    _write_incoming_readiness(tmp_path, ready=True)

    payload = build_us_equity_production_data_acquisition_plan(
        repo_root=tmp_path,
        output=Path("out/acquisition.json"),
        markdown_output=Path("out/acquisition.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "production_data_acquisition_ready_for_preflight"
    _validate_schema(payload)
    assert payload["current_drop_readiness"]["status"] == "incoming_drop_ready_for_import"
    assert payload["current_drop_readiness"]["ready_file_count"] == 6
    assert {row["status"] for row in payload["contract_status_by_table"]} == {"ready"}
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_production_data_acquisition_plan_schema_rejects_plan_unlock(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path)
    payload = build_us_equity_production_data_acquisition_plan(
        repo_root=tmp_path,
        output=Path("out/acquisition.json"),
        markdown_output=Path("out/acquisition.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["promotion_acceptance_criteria"]["paper_or_live_unlock_allowed_by_this_plan"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed_by_this_plan=true")


def _write_fixture_reports(tmp_path: Path, blockers: list[str] | None = None) -> None:
    if blockers is None:
        blockers = [
            "point_in_time_universe_not_confirmed",
            "membership_events_missing",
            "delisting_coverage_missing",
            "corporate_action_event_source_missing",
            "adjustment_reproducibility_missing",
            "fred_release_calendar_missing",
            "production_bundle_missing",
        ]
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/provider_capability_matrix.json",
        {
            "providers": [
                {"provider_id": "tiingo", "provider_name": "Tiingo", "configured": True},
                {"provider_id": "ibkr", "provider_name": "IBKR", "configured": False},
                {"provider_id": "crsp", "provider_name": "CRSP", "configured": False},
                {"provider_id": "sharadar", "provider_name": "Sharadar", "configured": False},
                {"provider_id": "norgate", "provider_name": "Norgate", "configured": False},
                {"provider_id": "local_csv", "provider_name": "Local CSV", "configured": False},
            ],
            "blockers": ["promotion_clean_provider_not_verified"] if blockers else [],
        },
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_onboarding_report.json",
        {"blockers": blockers},
    )
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json",
        {"blockers": blockers},
    )
    _write_incoming_readiness(tmp_path, ready=False)


def _write_incoming_readiness(tmp_path: Path, *, ready: bool) -> None:
    files = [
        _file_row("universe_membership_events", "universe_membership_events.csv", ready),
        _file_row("delisted_symbols", "delisted_symbols.csv", ready),
        _file_row("corporate_actions", "corporate_actions.csv", ready),
        _file_row("symbol_mapping", "symbol_mapping.csv", ready),
        _file_row("adjustment_replay", "adjustment_replay.csv", ready),
        _file_row("macro_release_calendar", "macro_release_calendar.csv", ready),
    ]
    _write_json(
        tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json",
        {
            "status": "incoming_drop_ready_for_import" if ready else "incoming_drop_blocked",
            "source_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "bundle_id": "manual_vendor_bundle_v1",
            "ready_file_count": 6 if ready else 0,
            "required_file_count": 6,
            "files": files,
            "blockers": [] if ready else ["source_dir_missing"],
        },
    )


def _file_row(table: str, filename: str, ready: bool) -> dict[str, object]:
    required_fields = ["source_record_id"]
    return {
        "table": table,
        "filename": filename,
        "exists": ready,
        "non_empty": ready,
        "record_count": 1 if ready else 0,
        "required_fields": required_fields,
        "missing_fields": [] if ready else required_fields,
        "blockers": [] if ready else [f"source_{table}_file_missing"],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
