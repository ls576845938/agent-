from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.check_artifact_lineage_health import (
    DEFAULT_ARTIFACT_SPECS,
    US_EQUITY_PRODUCTION_CONTROL_ARTIFACT_SPECS,
    _artifact_specs_for_scope,
    build_artifact_lineage_health_report,
    write_artifact_lineage_health_report,
)


def test_missing_critical_artifact_fails_health(tmp_path: Path) -> None:
    schema_path = _write_schema(tmp_path)
    report = build_artifact_lineage_health_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("missing", "missing.json", str(schema_path.relative_to(tmp_path)), True)],
    )

    assert report["health_status"] == "fail"
    assert report["missing_artifacts"] == ["missing.json"]
    assert "critical_artifact_missing" in report["blockers"]
    assert report["promotion_safe"] is False


def test_schema_invalid_artifact_fails_health(tmp_path: Path) -> None:
    schema_path = _write_schema(tmp_path)
    _write_json(tmp_path / "artifact.json", {"schema_version": "wrong"})

    report = build_artifact_lineage_health_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("artifact", "artifact.json", str(schema_path.relative_to(tmp_path)), True)],
    )

    assert report["health_status"] == "fail"
    assert report["schema_invalid_artifacts"]
    assert "schema_invalid_artifact" in report["blockers"]


def test_path_escape_and_hash_mismatch_fail_health(tmp_path: Path) -> None:
    schema_path = _write_schema(tmp_path)
    _write_json(
        tmp_path / "artifact.json",
        {
            "schema_version": "test_v1",
            "generated_at": "2026-05-19T00:00:00+00:00",
            "source_path": "../outside.csv",
            "file": {"path": "inside.csv", "sha256": "a", "actual_sha256": "b"},
        },
    )

    report = build_artifact_lineage_health_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("artifact", "artifact.json", str(schema_path.relative_to(tmp_path)), True)],
    )

    assert report["health_status"] == "fail"
    assert report["path_escape_risks"]
    assert report["hash_mismatch_artifacts"]


def test_workspace_parent_paths_require_explicit_allowance(tmp_path: Path) -> None:
    repo = tmp_path / "workspace" / "agent-"
    repo.mkdir(parents=True)
    schema_path = _write_schema(repo)
    evidence = tmp_path / "workspace" / "学习资料" / "report.md"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("# report", encoding="utf-8")
    _write_json(
        repo / "artifact.json",
        {
            "schema_version": "test_v1",
            "generated_at": "2026-05-19T00:00:00+00:00",
            "source_report": "../学习资料/report.md",
        },
    )

    strict_report = build_artifact_lineage_health_report(
        repo_root=repo,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("artifact", "artifact.json", str(schema_path.relative_to(repo)), True)],
    )
    allowed_report = build_artifact_lineage_health_report(
        repo_root=repo,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("artifact", "artifact.json", str(schema_path.relative_to(repo)), True)],
        allow_workspace_parent_paths=True,
    )

    assert strict_report["health_status"] == "fail"
    assert strict_report["path_escape_risks"]
    assert allowed_report["health_status"] == "pass"
    assert allowed_report["path_escape_risks"] == []


def test_valid_artifact_can_pass_health_but_not_promotion_safe(tmp_path: Path) -> None:
    schema_path = _write_schema(tmp_path)
    _write_json(
        tmp_path / "artifact.json",
        {"schema_version": "test_v1", "generated_at": "2026-05-19T00:00:00+00:00"},
    )

    report = build_artifact_lineage_health_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("artifact", "artifact.json", str(schema_path.relative_to(tmp_path)), True)],
    )

    assert report["health_status"] == "pass"
    assert report["generated_at"] == "2026-05-19T00:00:00Z"
    assert report["promotion_safe"] is False
    assert report["blockers"] == []


def test_artifact_health_schema_rejects_non_utc_generated_at() -> None:
    schema = json.loads(Path("schemas/artifact_health_report.schema.json").read_text(encoding="utf-8"))
    report = build_artifact_lineage_health_report(generated_at="2026-05-19T00:00:00Z", artifact_specs=[])
    report["generated_at"] = "2026-05-19T08:00:00+08:00"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(report, schema)


def test_artifact_health_writer_persists_report(tmp_path: Path) -> None:
    report = build_artifact_lineage_health_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[],
    )
    output = write_artifact_lineage_health_report(
        report,
        tmp_path / "artifacts/artifact_health/latest/artifact_health_report.json",
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "artifact_health_report_v1"


def test_artifact_health_includes_btc_objective_metadata_artifacts() -> None:
    names = {name for name, *_ in DEFAULT_ARTIFACT_SPECS}

    assert "btc_registry" in names
    assert "btc_public_metadata_capture_attempt" in names
    assert "btc_manual_metadata_capture_readiness" in names
    assert "btc_manual_metadata_capture_operator_packet" in names
    assert "btc_manual_metadata_import_report" in names
    assert "btc_objective_completion_audit" in names

    specs = {name: critical for name, _, _, critical in DEFAULT_ARTIFACT_SPECS}
    assert specs["btc_registry"] is True
    assert specs["btc_manual_metadata_import_report"] is False


def test_artifact_health_includes_us_equity_portfolio_promotion_evidence() -> None:
    names = {name for name, *_ in DEFAULT_ARTIFACT_SPECS}
    specs = {name: critical for name, _, _, critical in DEFAULT_ARTIFACT_SPECS}

    assert "portfolio_canonical" in names
    assert "portfolio_promotion_evidence" in names
    assert "portfolio_fixture_ledger" in names
    assert specs["portfolio_promotion_evidence"] is True
    assert specs["portfolio_fixture_ledger"] is False


def test_artifact_health_includes_us_equity_production_control_artifacts() -> None:
    names = {name for name, *_ in DEFAULT_ARTIFACT_SPECS}

    assert "us_equity_daily_production_line" in names
    assert "us_equity_completion_dependency" in names
    assert "us_equity_completion_audit" in names
    assert "us_equity_next_action_queue" in names
    assert "us_equity_standard_report_schema_audit" in names

    specs = {name: critical for name, _, _, critical in DEFAULT_ARTIFACT_SPECS}
    assert specs["us_equity_daily_production_line"] is True
    assert specs["us_equity_completion_dependency"] is True
    assert specs["us_equity_completion_audit"] is True
    assert specs["us_equity_next_action_queue"] is True
    assert specs["us_equity_standard_report_schema_audit"] is True


def test_artifact_health_us_equity_scope_is_only_production_control() -> None:
    scoped = _artifact_specs_for_scope("us_equity_production_control")

    assert scoped == US_EQUITY_PRODUCTION_CONTROL_ARTIFACT_SPECS
    assert {name for name, *_ in scoped} == {
        "us_equity_daily_production_line",
        "us_equity_completion_dependency",
        "us_equity_completion_audit",
        "us_equity_next_action_queue",
        "us_equity_standard_report_schema_audit",
    }
    assert all(critical is True for _, _, _, critical in scoped)


def test_optional_manual_metadata_import_report_missing_does_not_fail_health(tmp_path: Path) -> None:
    schema_path = _write_schema(tmp_path)
    report = build_artifact_lineage_health_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00+00:00",
        artifact_specs=[("optional_import", "missing_import.json", str(schema_path.relative_to(tmp_path)), False)],
    )

    assert report["health_status"] == "pass"
    assert report["missing_artifacts"] == []
    assert report["checked_artifacts"][0]["critical"] is False
    assert report["checked_artifacts"][0]["blockers"] == ["artifact_missing"]
    assert report["blockers"] == []


def _write_schema(tmp_path: Path) -> Path:
    path = tmp_path / "schema.json"
    _write_json(
        path,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["schema_version"],
            "properties": {"schema_version": {"const": "test_v1"}},
            "additionalProperties": True,
        },
    )
    return path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
