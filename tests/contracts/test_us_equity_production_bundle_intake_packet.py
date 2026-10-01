from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from quant_us.data.lineage.local_csv_provider import REQUIRED_LOCAL_CSV_FILES
from scripts.build_us_equity_production_bundle_intake_packet import (
    build_us_equity_production_bundle_intake_packet,
)


SCHEMA = Path("schemas/us_equity_production_bundle_intake_packet.schema.json")


def test_intake_packet_records_required_tables_commands_and_guardrails(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path)

    payload = build_us_equity_production_bundle_intake_packet(
        repo_root=tmp_path,
        output=Path("out/intake.json"),
        markdown_output=Path("out/intake.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_production_bundle_intake_packet_v1"
    _validate_schema(payload)
    assert payload["status"] == "intake_packet_ready_for_data_vendor_drop"
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["configuration_mutated_by_this_report"] is False
    assert payload["bundle_contract"]["accepted_source_type"] == "production"
    assert payload["bundle_contract"]["incoming_drop_dir"] == "data/external/us_equity_lineage/incoming/manual_vendor_drop"
    assert payload["bundle_contract"]["default_import_bundle_id"] == "manual_vendor_bundle_v1"
    assert payload["bundle_contract"]["must_include_sha256_and_record_count"] is True
    assert payload["bundle_contract"]["must_use_explicit_bundle_selection"] is True
    assert "import_us_equity_local_csv_production_bundle.py" in payload["bundle_contract"]["preferred_import_command"]

    tables = {row["table"]: row for row in payload["bundle_contract"]["required_tables"]}
    assert set(tables) == set(REQUIRED_LOCAL_CSV_FILES)
    for table, fields in REQUIRED_LOCAL_CSV_FILES.items():
        assert tables[table]["required_fields"] == fields
        assert tables[table]["minimum_record_count"] == 1

    commands = "\n".join(payload["validation_commands"])
    assert "build_us_equity_production_bundle_activation_report.py --bundle-id <bundle_id> --license-reviewed" in commands
    assert "build_us_equity_production_bundle_preflight_report.py --strict" in commands
    assert "build_us_equity_provider_verification_report.py" in commands
    assert "build_us_equity_strategy_production_line_report.py" in commands
    assert "import_us_equity_local_csv_production_bundle.py" in commands
    assert any(step["step_id"] == "prepare_incoming_drop" for step in payload["operator_steps"])
    assert any("import_us_equity_local_csv_production_bundle.py" in step["command"] for step in payload["operator_steps"])
    assert "production_bundle_missing" in payload["current_state"]["current_blockers"]

    md = tmp_path / "out/intake.md"
    assert md.exists()
    assert "US Equity 生产数据包导入验收包" in md.read_text(encoding="utf-8")


def test_intake_packet_blocks_when_scaffold_is_missing(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path, include_scaffold=False)

    payload = build_us_equity_production_bundle_intake_packet(
        repo_root=tmp_path,
        output=Path("out/intake.json"),
        markdown_output=Path("out/intake.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "intake_packet_action_required"
    _validate_schema(payload)
    assert "production_bundle_scaffold_report_missing_or_not_ready" in payload["blockers"]
    assert payload["guardrails"]["live_order_allowed"] is False


def test_intake_packet_schema_rejects_live_flag(tmp_path: Path) -> None:
    _write_fixture_reports(tmp_path)
    payload = build_us_equity_production_bundle_intake_packet(
        repo_root=tmp_path,
        output=Path("out/intake.json"),
        markdown_output=Path("out/intake.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_fixture_reports(root: Path, *, include_scaffold: bool = True) -> None:
    if include_scaffold:
        _write_json(
            root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_scaffold_report.json",
            {
                "schema_version": "us_equity_production_bundle_scaffold_report_v1",
                "status": "template_ready_not_provider_evidence",
                "scaffold_dir": "artifacts/us_equity_data_lineage/latest/production_bundle_scaffold/us_equity_production_bundle_TEMPLATE",
                "required_tables": [{"table": table} for table in REQUIRED_LOCAL_CSV_FILES],
            },
        )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json",
        {
            "schema_version": "us_equity_production_bundle_preflight_report_v1",
            "production_bundle_preflight_pass": False,
            "selected_bundle_id": None,
            "production_bundles_found": 0,
            "blockers": ["production_bundle_missing", "explicit_bundle_selection_missing"],
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/provider_verification_report.json",
        {
            "schema_version": "us_equity_provider_verification_report_v1",
            "promotion_clean": False,
            "blockers": ["provider_required_tables_missing"],
        },
    )
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json",
        {
            "schema_version": "us_equity_production_data_acquisition_plan_v1",
            "status": "production_data_acquisition_required",
            "missing_contract_groups": ["pit_universe", "survivorship"],
            "blockers": ["production_bundle_missing"],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
