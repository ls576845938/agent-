from __future__ import annotations

import json
from pathlib import Path

from scripts.build_us_equity_local_csv_bundle_manifest import build_local_csv_bundle_manifest
from tests.contracts.us_equity_local_csv_test_helpers import copy_fixture_bundle


def test_local_csv_bundle_manifest_schema_exists() -> None:
    assert Path("schemas/us_equity_local_csv_provider_bundle_manifest.schema.json").exists()


def test_bundle_manifest_records_hashes_counts_and_fixture_blocker(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="fixture")

    manifest = json.loads((bundle_root / "provider_bundle_manifest.json").read_text(encoding="utf-8"))

    assert manifest["source_type"] == "fixture"
    assert manifest["promotion_clean_allowed"] is False
    assert manifest["files"]["universe_membership_events"]["record_count"] == 3
    assert len(manifest["files"]["corporate_actions"]["sha256"]) == 64
    assert "fixture_source_not_promotion_ready" in manifest["blockers"]


def test_missing_manifest_metadata_fails_closed(tmp_path: Path) -> None:
    bundle_root = copy_fixture_bundle(tmp_path, source_type="sample")

    manifest = build_local_csv_bundle_manifest(
        bundle_root=bundle_root,
        bundle_id="",
        source_provider="local_csv",
        source_type="production",
        sample_start="",
        sample_end="",
        license_note="",
        promotion_clean_allowed=False,
    )

    assert "bundle_id_missing" in manifest["blockers"]
    assert "sample_start_missing" in manifest["blockers"]
    assert "sample_end_missing" in manifest["blockers"]
    assert "license_note_missing" in manifest["blockers"]
    assert "promotion_clean_not_allowed" in manifest["blockers"]
