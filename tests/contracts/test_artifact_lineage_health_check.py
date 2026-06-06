from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from scripts.check_artifact_lineage_health import (
    DEFAULT_ARTIFACT_SPECS,
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
