from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_production_bundle_onboarding_report import (
    build_us_equity_production_bundle_onboarding_report,
)


SCHEMA = Path("schemas/us_equity_production_bundle_onboarding_report.schema.json")


def test_production_bundle_onboarding_reports_current_blockers_without_unlocking(tmp_path: Path) -> None:
    _write_scaffold(tmp_path)
    _write_preflight(tmp_path, pass_gate=False)
    _write_provider(tmp_path, promotion_clean=False)
    _write_data_status(tmp_path, promotion_clean=False)
    _write_remediation(tmp_path, required=True)
    _write_acquisition_plan(tmp_path, required=True)
    _write_manual_vendor_drop_package(tmp_path)

    payload = build_us_equity_production_bundle_onboarding_report(
        repo_root=tmp_path,
        output=Path("out/onboarding.json"),
        markdown_output=Path("out/onboarding.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    stages = {stage["stage_id"]: stage for stage in payload["stages"]}
    assert payload["schema_version"] == "us_equity_production_bundle_onboarding_report_v1"
    _validate_schema(payload)
    assert payload["status"] == "production_bundle_onboarding_blocked"
    assert stages["scaffold_ready"]["status"] == "pass"
    assert stages["manual_vendor_drop_package"]["status"] == "pass"
    assert stages["production_bundle_discovery"]["status"] == "blocked"
    assert stages["explicit_bundle_selection"]["status"] == "blocked"
    assert stages["provider_verification"]["status"] == "blocked"
    assert stages["data_status_promotion_clean"]["status"] == "blocked"
    assert stages["remaining_remediation"]["status"] == "blocked"
    assert payload["acquisition_plan"]["available"] is True
    assert payload["acquisition_plan"]["status"] == "production_data_acquisition_required"
    assert payload["manual_vendor_drop_package"]["available"] is True
    assert payload["manual_vendor_drop_package"]["status"] == "manual_vendor_drop_package_ready"
    assert payload["guardrails"]["configuration_mutated_by_this_report"] is False
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/onboarding.json").exists()
    assert (tmp_path / "out/onboarding.md").exists()


def test_production_bundle_onboarding_blocks_without_scaffold(tmp_path: Path) -> None:
    payload = build_us_equity_production_bundle_onboarding_report(
        repo_root=tmp_path,
        output=Path("out/onboarding.json"),
        markdown_output=Path("out/onboarding.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "production_bundle_onboarding_missing_scaffold"
    _validate_schema(payload)
    assert "production_bundle_scaffold_report_missing" in payload["blockers"]
    assert payload["guardrails"]["paper_simulation_allowed"] is False


def test_production_bundle_onboarding_passes_data_path_but_never_unlocks_live(tmp_path: Path) -> None:
    _write_scaffold(tmp_path)
    _write_preflight(tmp_path, pass_gate=True)
    _write_provider(tmp_path, promotion_clean=True)
    _write_data_status(tmp_path, promotion_clean=True)
    _write_remediation(tmp_path, required=False)
    _write_acquisition_plan(tmp_path, required=False)
    _write_manual_vendor_drop_package(tmp_path)

    payload = build_us_equity_production_bundle_onboarding_report(
        repo_root=tmp_path,
        output=Path("out/onboarding.json"),
        markdown_output=Path("out/onboarding.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    assert payload["status"] == "production_bundle_onboarding_ready_for_data_drop"
    _validate_schema(payload)
    assert payload["blockers"] == []
    assert all(row["done"] is True for row in payload["activation_checklist"])
    assert payload["selected_bundle"]["provider_promotion_clean"] is True
    assert payload["selected_bundle"]["data_promotion_clean"] is True
    assert payload["guardrails"]["promotion_clean_granted_by_this_report"] is False
    assert payload["guardrails"]["live_order_allowed"] is False


def test_production_bundle_onboarding_blocks_missing_manual_vendor_drop_package(tmp_path: Path) -> None:
    _write_scaffold(tmp_path)
    _write_preflight(tmp_path, pass_gate=True)
    _write_provider(tmp_path, promotion_clean=True)
    _write_data_status(tmp_path, promotion_clean=True)
    _write_remediation(tmp_path, required=False)
    _write_acquisition_plan(tmp_path, required=False)

    payload = build_us_equity_production_bundle_onboarding_report(
        repo_root=tmp_path,
        output=Path("out/onboarding.json"),
        markdown_output=Path("out/onboarding.md"),
        generated_at="2026-06-25T00:00:00Z",
    )

    stages = {stage["stage_id"]: stage for stage in payload["stages"]}
    assert payload["status"] == "production_bundle_onboarding_blocked"
    _validate_schema(payload)
    assert stages["manual_vendor_drop_package"]["status"] == "blocked"
    assert "manual_vendor_drop_package_report_missing" in payload["blockers"]


def test_production_bundle_onboarding_schema_rejects_provider_evidence_claim(tmp_path: Path) -> None:
    _write_scaffold(tmp_path)
    _write_preflight(tmp_path, pass_gate=True)
    _write_provider(tmp_path, promotion_clean=True)
    _write_data_status(tmp_path, promotion_clean=True)
    _write_remediation(tmp_path, required=False)
    _write_acquisition_plan(tmp_path, required=False)
    _write_manual_vendor_drop_package(tmp_path)
    payload = build_us_equity_production_bundle_onboarding_report(
        repo_root=tmp_path,
        output=Path("out/onboarding.json"),
        markdown_output=Path("out/onboarding.md"),
        generated_at="2026-06-25T00:00:00Z",
    )
    payload["guardrails"]["promotion_clean_granted_by_this_report"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted promotion_clean_granted_by_this_report=true")


def _write_scaffold(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_scaffold_report.json",
        {
            "status": "template_ready_not_provider_evidence",
            "scaffold_dir": "artifacts/us_equity_data_lineage/latest/production_bundle_scaffold/template",
            "required_tables": [{"table": "universe_membership_events"}],
        },
    )


def _write_preflight(root: Path, *, pass_gate: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/production_bundle_preflight_report.json",
        {
            "production_bundles_found": 1 if pass_gate else 0,
            "candidate_bundle_ids": ["bundle_a"] if pass_gate else [],
            "selected_bundle_id": "bundle_a" if pass_gate else None,
            "selected_bundle_source_type": "production" if pass_gate else None,
            "selected_bundle_manifest_path": "data/external/us_equity_lineage/bundles/bundle_a/provider_bundle_manifest.json"
            if pass_gate
            else None,
            "production_bundle_preflight_pass": pass_gate,
            "promotion_clean_allowed": pass_gate,
            "local_csv_enabled": pass_gate,
            "blockers": [] if pass_gate else ["production_bundle_missing", "explicit_bundle_selection_missing"],
        },
    )


def _write_provider(root: Path, *, promotion_clean: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/provider_verification_report.json",
        {
            "selected_provider": "local_csv",
            "source_type": "production" if promotion_clean else "none",
            "selected_bundle_id": "bundle_a" if promotion_clean else None,
            "selected_bundle_source_type": "production" if promotion_clean else None,
            "selected_bundle_manifest_path": "data/external/us_equity_lineage/bundles/bundle_a/provider_bundle_manifest.json"
            if promotion_clean
            else None,
            "promotion_clean": promotion_clean,
            "data_lineage_grade_candidate": "L4_promotion_clean" if promotion_clean else "L1_sample_non_pit",
            "blockers": [] if promotion_clean else ["provider_not_verified_for_promotion"],
        },
    )


def _write_data_status(root: Path, *, promotion_clean: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_status/latest/data_status_report.json",
        {
            "status": "pass" if promotion_clean else "partial",
            "source_type": "point_in_time_membership" if promotion_clean else "research_price_bars",
            "promotion_clean": promotion_clean,
            "data_lineage_grade": {"value": "L4_promotion_clean" if promotion_clean else "L1_sample_non_pit"},
            "blockers": [] if promotion_clean else ["data_lineage_not_promotion_clean"],
        },
    )


def _write_remediation(root: Path, *, required: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_data_lineage_remediation_report.json",
        {
            "status": "remediation_required" if required else "remediation_not_required",
            "remediation_groups": [{"group_id": "point_in_time_universe"}] if required else [],
        },
    )


def _write_acquisition_plan(root: Path, *, required: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_data_acquisition_plan.json",
        {
            "status": "production_data_acquisition_required" if required else "production_data_acquisition_ready_for_preflight",
            "acceptable_provider_ids": ["crsp", "sharadar", "norgate", "local_csv"],
            "missing_contract_groups": ["pit_universe"] if required else [],
        },
    )


def _write_manual_vendor_drop_package(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json",
        {
            "status": "manual_vendor_drop_package_ready",
            "incoming_drop_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "template_root": "docs/us_equity_manual_vendor_drop_templates",
            "field_dictionary": "docs/us_equity_manual_vendor_drop_field_dictionary.md",
            "handoff_doc": "docs/us_equity_manual_vendor_drop_handoff.md",
            "template_files": [{"table": "universe_membership_events"}] * 6,
            "required_table_count": 6,
            "field_count": 51,
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
