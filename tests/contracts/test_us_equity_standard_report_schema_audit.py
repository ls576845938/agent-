from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_standard_report_schema_audit import (
    REQUIRED_STANDARD_FIELDS,
    build_us_equity_standard_report_schema_audit,
)


SOURCE_ROOT = Path("artifacts/us_equity_etf_macro_rotation/latest")
SCHEMA = Path("schemas/us_equity_standard_report_schema_audit_report.schema.json")


def test_standard_report_schema_audit_passes_current_evidence_packet(tmp_path: Path) -> None:
    markdown_output = tmp_path / "out/test_us_equity_standard_report_schema_audit.md"
    payload = build_us_equity_standard_report_schema_audit(
        repo_root=Path("."),
        output=tmp_path / "out/test_us_equity_standard_report_schema_audit_report.json",
        markdown_output=markdown_output,
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["schema_version"] == "us_equity_standard_report_schema_audit_v1"
    _validate_schema(payload)
    assert payload["status"] == "schema_audit_pass"
    assert payload["required_fields"] == REQUIRED_STANDARD_FIELDS
    assert payload["coverage_summary"]["passed_field_count"] == len(REQUIRED_STANDARD_FIELDS)
    assert payload["field_checks"]["pit_operator_handoff_schema"]["passed"] is True
    assert payload["field_checks"]["production_control_schema"]["passed"] is True
    assert payload["field_checks"]["production_control_schema"]["schema_versions"]["daily_production_line_report"] == "us_equity_daily_production_line_run_v1"
    assert payload["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert payload["guardrails"]["strategy_parameters_mutated"] is False
    assert markdown_output.exists()


def test_standard_report_schema_audit_blocks_missing_cash_benchmark(tmp_path: Path) -> None:
    _copy_reports(tmp_path)
    validation_path = tmp_path / SOURCE_ROOT / "us_etf_top1_higher_vol_20pct_15x_validation_report.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    validation["standardized_report_schema"]["rows"] = [
        row for row in validation["standardized_report_schema"]["rows"] if row.get("id") != "SHV"
    ]
    validation_path.write_text(json.dumps(validation), encoding="utf-8")

    payload = build_us_equity_standard_report_schema_audit(
        repo_root=tmp_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "schema_audit_action_required"
    _validate_schema(payload)
    assert payload["field_checks"]["benchmarks"]["passed"] is False
    assert "us_equity_standard_schema_field_missing:benchmarks" in payload["blockers"]


def test_standard_report_schema_audit_blocks_unsafe_live_flag(tmp_path: Path) -> None:
    _copy_reports(tmp_path)
    gate_path = tmp_path / SOURCE_ROOT / "us_etf_strategy_validation_gate_report.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["live_order_allowed"] = True
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    payload = build_us_equity_standard_report_schema_audit(
        repo_root=tmp_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "schema_audit_action_required"
    _validate_schema(payload)
    assert "us_equity_standard_schema_unsafe_flag:strategy_gate_report.live_order_allowed" in payload["blockers"]


def test_standard_report_schema_audit_blocks_invalid_pit_handoff_schema(tmp_path: Path) -> None:
    _copy_reports(tmp_path)
    handoff_path = tmp_path / "artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["guardrails"]["live_order_allowed"] = True
    handoff_path.write_text(json.dumps(handoff), encoding="utf-8")

    payload = build_us_equity_standard_report_schema_audit(
        repo_root=tmp_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "schema_audit_action_required"
    _validate_schema(payload)
    assert payload["field_checks"]["pit_operator_handoff_schema"]["passed"] is False
    assert "us_equity_standard_schema_field_missing:pit_operator_handoff_schema" in payload["blockers"]
    assert "us_equity_standard_schema_unsafe_flag:pit_operator_handoff_report.guardrails.live_order_allowed" in payload["blockers"]


def test_standard_report_schema_audit_schema_rejects_live_unlock(tmp_path: Path) -> None:
    _copy_reports(tmp_path)
    payload = build_us_equity_standard_report_schema_audit(
        repo_root=tmp_path,
        output=Path("out/audit.json"),
        markdown_output=Path("out/audit.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["paper_or_live_unlock_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted paper_or_live_unlock_allowed=true")


def _copy_reports(tmp_path: Path) -> None:
    files = [
        "us_etf_macro_rotation_research_report.json",
        "us_etf_top1_higher_vol_20pct_15x_validation_report.json",
        "us_etf_macro_rotation_walk_forward_stability_report.json",
        "us_etf_strategy_validation_gate_report.json",
        "us_etf_forward_observation_evaluation_report.json",
        "us_etf_small_account_execution_preflight_report.json",
        "us_equity_live_readiness_risk_constitution_report.json",
    ]
    for name in files:
        source = SOURCE_ROOT / name
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    lineage_files = [
        Path("artifacts/us_equity_data_lineage/latest/us_equity_pit_operator_handoff_summary.json"),
        Path("schemas/us_equity_pit_operator_handoff_summary.schema.json"),
    ]
    production_line_files = [
        Path("artifacts/us_equity_strategy_production_line/latest/us_equity_daily_production_line_run_report.json"),
        Path("schemas/us_equity_daily_production_line_run_report.schema.json"),
        Path("artifacts/us_equity_strategy_production_line/latest/us_equity_completion_dependency_report.json"),
        Path("schemas/us_equity_completion_dependency_report.schema.json"),
        Path("artifacts/us_equity_strategy_production_line/latest/us_equity_completion_audit_report.json"),
        Path("schemas/us_equity_completion_audit_report.schema.json"),
        Path("artifacts/us_equity_strategy_production_line/latest/us_equity_next_action_queue_report.json"),
        Path("schemas/us_equity_next_action_queue_report.schema.json"),
    ]
    for source in [*lineage_files, *production_line_files]:
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _validate_schema(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(f"schema validation failed: {exc.message}") from exc
