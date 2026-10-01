from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import jsonschema

from quant_us.data.pit_dataready_consumer import (
    PRODUCTION_FILES,
    PRODUCTION_TABLES,
    build_pit_dataready_consumption_report,
    evaluate_pit_lite_zero_event_proof,
    validate_production_pit_payload,
)


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "configs/data/us_equity_pit_dataready_consumer_v1.json"
SCHEMA_PATH = ROOT / "schemas/us_equity_pit_dataready_consumption_report.schema.json"
AS_OF = datetime(2026, 7, 24, tzinfo=timezone.utc)


def test_current_etf26_manifest_is_research_ready_but_never_promotion_evidence() -> None:
    report = build_pit_dataready_consumption_report(
        repo_root=ROOT,
        config=_config(),
        production_bundle_root=None,
        generated_at="2026-07-24T00:00:00Z",
    )

    _validate_report(report)
    assert report["status"] == "blocked_external_data"
    assert report["etf26_minute"]["state"] == "research_ready"
    assert report["etf26_minute"]["readiness_class"] == "research_ready"
    assert report["etf26_minute"]["immutable_resolution"] == {
        "status": "resolved",
        "consumer_read_only": True,
        "mode": "publication_marker_fast",
    }
    assert report["readiness"]["research_ready"] is True
    assert report["readiness"]["promotion_evidence_ready"] is False
    assert report["pit_lite"]["state"] == "not_supplied"
    assert set(report["production_pit"]["blockers"]) >= {
        f"production_pit_required_file_missing:{name}" for name in PRODUCTION_FILES
    }
    assert all(
        value is False
        for key, value in report["guardrails"].items()
        if key != "consumer_read_only"
    )


def test_valid_production_bundle_accepts_all_six_tables(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path)

    result = validate_production_pit_payload(
        repo_root=ROOT,
        bundle_root=root,
        manifest=manifest,
        config=_config(),
        as_of=AS_OF,
    )

    assert result["accepted"] is True
    assert result["state"] == "accepted"
    assert result["blockers"] == []
    assert len(result["validated_files"]) == len(PRODUCTION_TABLES)


def test_missing_bundle_is_blocked_external_data() -> None:
    report = build_pit_dataready_consumption_report(
        repo_root=ROOT,
        config=_config(),
        production_bundle_root=None,
        generated_at="2026-07-24T00:00:00Z",
    )

    assert report["status"] == "blocked_external_data"
    assert report["production_pit"]["state"] == "missing"
    assert report["next_handoff_contract"]["owner"] == "data_steward"


def test_stale_manifest_is_rejected(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path)
    manifest["published_at"] = "2026-01-01T00:00:00Z"

    result = _validate_bundle(root, manifest)

    assert result["accepted"] is False
    assert "production_pit_manifest_stale" in result["blockers"]


def test_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path)
    manifest["files"]["corporate_actions"]["sha256"] = "0" * 64

    result = _validate_bundle(root, manifest)

    assert "production_pit_corporate_actions_hash_mismatch" in result["blockers"]


def test_partial_coverage_is_rejected(tmp_path: Path) -> None:
    root, manifest = _bundle(tmp_path)
    manifest["coverage"]["start"] = "2020-01-01T00:00:00Z"

    result = _validate_bundle(root, manifest)

    assert "production_pit_partial_coverage" in result["blockers"]


def test_late_visibility_is_rejected(tmp_path: Path) -> None:
    root, manifest = _bundle(
        tmp_path,
        available_time="2026-07-20T00:00:00Z",
        ingested_at="2026-07-20T00:01:00Z",
        adjustment_available_time="2026-07-19T00:00:00Z",
    )

    result = _validate_bundle(root, manifest)

    assert any(blocker.endswith("_late_visibility") for blocker in result["blockers"])


def test_visibility_order_is_rejected(tmp_path: Path) -> None:
    root, manifest = _bundle(
        tmp_path,
        available_time="2026-07-10T14:00:00Z",
        ingested_at="2026-07-10T13:00:00Z",
    )

    result = _validate_bundle(root, manifest)

    assert any(
        blocker.endswith("_visibility_order_invalid")
        for blocker in result["blockers"]
    )


def test_pit_lite_zero_event_proof_never_substitutes_for_production() -> None:
    result = evaluate_pit_lite_zero_event_proof(
        {
            "schema_version": "us_equity_pit_lite_zero_event_proof_v1",
            "producer_role": "data_steward",
            "immutable_version": True,
            "membership_event_count": 0,
            "corporate_action_event_count": 0,
        }
    )

    assert result["state"] == "pit_lite_zero_event_proof"
    assert result["production_pit_substitute"] is False
    assert result["scope"] == "frozen_etf26_research_observation_only"


def test_artifact_identity_ignores_generation_time() -> None:
    first = build_pit_dataready_consumption_report(
        repo_root=ROOT,
        config=_config(),
        production_bundle_root=None,
        generated_at="2026-07-24T00:00:00Z",
    )
    second = build_pit_dataready_consumption_report(
        repo_root=ROOT,
        config=_config(),
        production_bundle_root=None,
        generated_at="2026-07-24T01:00:00Z",
    )

    assert first["artifact_identity_sha256"] == second["artifact_identity_sha256"]


def _validate_bundle(root: Path, manifest: dict[str, object]) -> dict[str, object]:
    return validate_production_pit_payload(
        repo_root=ROOT,
        bundle_root=root,
        manifest=manifest,
        config=_config(),
        as_of=AS_OF,
    )


def _bundle(
    tmp_path: Path,
    *,
    available_time: str = "2026-07-10T14:31:00Z",
    ingested_at: str = "2026-07-10T14:32:00Z",
    adjustment_available_time: str = "2026-07-10T14:30:30Z",
) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "immutable-production-pit-v1"
    root.mkdir()
    splice_id = "vendor-a-primary"
    files: dict[str, object] = {}
    for table in PRODUCTION_TABLES:
        path = root / f"{table}.csv"
        row = {
            "record_id": f"{table}-1",
            "event_time": "2026-07-10T14:30:00Z",
            "available_time": available_time,
            "ingested_at": ingested_at,
            "source_splice_id": splice_id,
        }
        if table == "adjustment_replay":
            row["adjustment_available_time"] = adjustment_available_time
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        files[table] = {
            "path": path.name,
            "sha256": _sha256(path),
            "record_count": 1,
        }
    manifest: dict[str, object] = {
        "schema_version": "us_equity_production_pit_bundle_v1",
        "bundle_id": "fixture-production-pit",
        "bundle_version": "fixture-production-pit-v1",
        "immutable_version": True,
        "producer_role": "data_steward",
        "producer_commit": _head(),
        "source_provider": "contract-fixture",
        "published_at": "2026-07-20T00:00:00Z",
        "coverage": {
            "start": "2000-01-01T00:00:00Z",
            "end": "2026-07-20T23:59:59Z",
        },
        "calendar": "XNYS",
        "source_splices": [
            {
                "splice_id": splice_id,
                "source": "contract-fixture",
                "start": "2000-01-01T00:00:00Z",
                "end": "2026-07-20T23:59:59Z",
            }
        ],
        "files": files,
    }
    (root / "provider_bundle_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return root, manifest


def _config() -> dict[str, object]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _validate_report(report: dict[str, object]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(report, schema, format_checker=jsonschema.FormatChecker())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
