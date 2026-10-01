from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_us_equity_pit_data_intake_status_report import (
    build_us_equity_pit_data_intake_status_report,
)


SCHEMA = Path("schemas/us_equity_pit_data_intake_status_report.schema.json")


def test_pit_intake_status_reports_missing_drop_as_current_blocker(tmp_path: Path) -> None:
    _write_ready_package(tmp_path)
    _write_incoming(tmp_path, ready=False)
    _write_import(tmp_path, imported=False)
    _write_intake(tmp_path)
    _write_activation(tmp_path, ready=False)
    _write_acceptance(tmp_path, ready=False)
    _write_onboarding(tmp_path, ready=False)
    _write_development_audit(tmp_path, complete=False)

    payload = build_us_equity_pit_data_intake_status_report(
        repo_root=tmp_path,
        output=Path("out/status.json"),
        markdown_output=Path("out/status.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_pit_data_intake_blocked"
    assert payload["current_blocking_stage"] == "incoming_drop_readiness"
    assert payload["next_action"]["first_blocker"] == "source_dir_missing"
    assert any("Create directory:" in item for item in payload["operator_next_actions"])
    assert any("licensed CSV files" in item for item in payload["operator_next_actions"])
    stages = {stage["stage_id"]: stage for stage in payload["stages"]}
    assert stages["manual_vendor_drop_package"]["status"] == "pass"
    assert stages["incoming_drop_readiness"]["status"] == "blocked"
    assert "pit_bundle_acceptance" in stages
    assert payload["guardrails"]["live_order_allowed"] is False
    assert (tmp_path / "out/status.json").exists()
    assert (tmp_path / "out/status.md").exists()


def test_pit_intake_status_blocks_missing_package_first(tmp_path: Path) -> None:
    payload = build_us_equity_pit_data_intake_status_report(
        repo_root=tmp_path,
        output=Path("out/status.json"),
        markdown_output=Path("out/status.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["current_blocking_stage"] == "manual_vendor_drop_package"
    assert "manual_vendor_drop_package_report_missing" in payload["blockers"]


def test_pit_intake_status_ready_when_all_stages_pass(tmp_path: Path) -> None:
    _write_ready_package(tmp_path)
    _write_incoming(tmp_path, ready=True)
    _write_import(tmp_path, imported=True)
    _write_intake(tmp_path)
    _write_activation(tmp_path, ready=True)
    _write_acceptance(tmp_path, ready=True)
    _write_onboarding(tmp_path, ready=True)
    _write_development_audit(tmp_path, complete=True)

    payload = build_us_equity_pit_data_intake_status_report(
        repo_root=tmp_path,
        output=Path("out/status.json"),
        markdown_output=Path("out/status.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_pit_data_intake_ready"
    assert payload["current_blocking_stage"] == "none"
    assert payload["blockers"] == []
    assert payload["operator_next_actions"] == [
        "Continue downstream manual review; this status panel does not unlock paper or live trading."
    ]
    assert all(stage["status"] == "pass" for stage in payload["stages"])


def test_pit_intake_status_does_not_circularly_block_on_development_audit(tmp_path: Path) -> None:
    _write_ready_package(tmp_path)
    _write_incoming(tmp_path, ready=True)
    _write_import(tmp_path, imported=True)
    _write_intake(tmp_path)
    _write_activation(tmp_path, ready=True)
    _write_acceptance(tmp_path, ready=True)
    _write_onboarding(tmp_path, ready=True)
    _write_development_audit(tmp_path, complete=False)

    payload = build_us_equity_pit_data_intake_status_report(
        repo_root=tmp_path,
        output=Path("out/status.json"),
        markdown_output=Path("out/status.md"),
        generated_at="2026-06-26T00:00:00Z",
    )

    _validate_schema(payload)
    assert payload["status"] == "production_pit_data_intake_ready"
    assert payload["current_blocking_stage"] == "none"
    stages = {stage["stage_id"]: stage for stage in payload["stages"]}
    assert stages["development_plan_audit"]["status"] == "pass"
    assert stages["development_plan_audit"]["report_status"] == "development_plan_blocked_by_production_pit_data"


def test_pit_intake_status_schema_rejects_live_flag(tmp_path: Path) -> None:
    payload = build_us_equity_pit_data_intake_status_report(
        repo_root=tmp_path,
        output=Path("out/status.json"),
        markdown_output=Path("out/status.md"),
        generated_at="2026-06-26T00:00:00Z",
    )
    payload["guardrails"]["live_order_allowed"] = True

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError:
        return
    raise AssertionError("schema accepted live_order_allowed=true")


def _write_ready_package(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_manual_vendor_drop_package_report.json",
        {"status": "manual_vendor_drop_package_ready", "template_files": [{"table": "x"}] * 6, "field_count": 51, "incoming_drop_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop"},
    )


def _write_incoming(root: Path, *, ready: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_incoming_drop_readiness_report.json",
        {
            "status": "incoming_drop_ready_for_import" if ready else "incoming_drop_blocked",
            "ready_file_count": 6 if ready else 0,
            "required_file_count": 6,
            "source_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "blockers": [] if ready else ["source_dir_missing"],
            "operator_next_actions": [
                "Create directory: data/external/us_equity_lineage/incoming/manual_vendor_drop",
                "Copy the six licensed CSV files into the incoming drop directory.",
            ],
        },
    )


def _write_import(root: Path, *, imported: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_local_csv_production_bundle_import_report.json",
        {"status": "production_bundle_imported" if imported else "production_bundle_import_blocked", "bundle_id": "manual_vendor_bundle_v1", "source_dir": "drop", "target_bundle_root": "bundle", "blockers": [] if imported else ["source_dir_missing"]},
    )


def _write_intake(root: Path) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_intake_packet.json",
        {"status": "intake_packet_ready_for_data_vendor_drop", "blockers": []},
    )


def _write_activation(root: Path, *, ready: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_activation_report.json",
        {
            "status": "activation_ready_for_manual_config_apply" if ready else "activation_blocked",
            "bundle_id": "manual_vendor_bundle_v1",
            "candidate_config_path": "candidate.yaml",
            "preflight_summary": {"production_bundle_preflight_pass": ready},
            "provider_verification_summary": {"promotion_clean": ready},
            "blockers": [] if ready else ["candidate_bundle_root_missing"],
        },
    )


def _write_acceptance(root: Path, *, ready: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_pit_bundle_acceptance_run_report.json",
        {
            "status": "acceptance_ready_for_manual_config_apply" if ready else "acceptance_blocked",
            "bundle_id": "manual_vendor_bundle_v1",
            "source_dir": "data/external/us_equity_lineage/incoming/manual_vendor_drop",
            "current_blocking_step": "none" if ready else "incoming_drop_readiness",
            "license_reviewed": ready,
            "blockers": [] if ready else ["source_dir_missing"],
        },
    )


def _write_onboarding(root: Path, *, ready: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_data_lineage/latest/us_equity_production_bundle_onboarding_report.json",
        {
            "status": "production_bundle_onboarding_ready_for_data_drop" if ready else "production_bundle_onboarding_blocked",
            "manual_vendor_drop_package": {"status": "manual_vendor_drop_package_ready"},
            "selected_bundle": {"selected_bundle_id": "manual_vendor_bundle_v1", "provider_promotion_clean": ready},
            "blockers": [] if ready else ["production_bundle_missing"],
        },
    )


def _write_development_audit(root: Path, *, complete: bool) -> None:
    _write_json(
        root / "artifacts/us_equity_strategy_production_line/latest/us_equity_development_plan_audit_report.json",
        {"status": "development_plan_complete" if complete else "development_plan_blocked_by_production_pit_data", "summary": {"complete_count": 10 if complete else 5, "blocked_count": 0 if complete else 2, "phase_count": 11}, "blockers": [] if complete else ["production_bundle_missing"]},
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _validate_schema(payload: dict[str, object]) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
