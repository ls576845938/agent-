from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts.build_btc_perpetual_data_bundle_manifest import (
    REQUIRED_FILES,
    build_btc_perpetual_data_bundle_manifest,
    validate_btc_perpetual_data_bundle_manifest,
)


SCHEMA = Path("schemas/btc_perpetual_data_bundle_manifest.schema.json")


def test_btc_perpetual_bundle_manifest_schema_valid_for_complete_fixture(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        source_type="fixture",
        license_note="test fixture",
    )
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    jsonschema.validate(payload, schema)
    assert payload["source_type"] == "fixture"
    assert payload["promotion_clean_allowed"] is False
    assert payload["sample_start"] == "2026-01-01T00:00:00Z"
    assert all("sha256" in item and "record_count" in item for item in payload["files"])
    assert validate_btc_perpetual_data_bundle_manifest(bundle, payload)["valid"] is True


def test_btc_perpetual_bundle_manifest_fails_when_required_file_missing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)
    (bundle / "funding_rate.csv").unlink()

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="broken_bundle",
        source_type="production",
        license_note="vendor export",
        promotion_clean_allowed=True,
    )

    assert "btc_perpetual_bundle_required_file_missing:funding_rate.csv" in payload["blockers"]


def test_sample_bundle_cannot_be_promotion_clean(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="sample_bundle",
        source_type="sample",
        license_note="sample",
        promotion_clean_allowed=True,
    )

    assert "btc_perpetual_bundle_non_production_promotion_clean_allowed" in payload["blockers"]


def test_open_interest_and_liquidation_are_diagnostic_not_required(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        source_type="fixture",
        license_note="test fixture",
    )

    roles = {item["role"] for item in payload["files"]}
    assert "open_interest_hist_1h" not in roles
    assert "liquidation_snapshots" not in roles
    assert validate_btc_perpetual_data_bundle_manifest(bundle, payload)["valid"] is True
    assert "btc_open_interest_history_not_verified_diagnostic_partial" in payload["blockers"]
    assert "btc_liquidation_snapshots_missing_diagnostic_only" in payload["blockers"]


def _write_required_files(bundle: Path) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_FILES:
        path = bundle / filename
        if filename.endswith(".csv"):
            path.write_text("timestamp,value\n2026-01-01T00:00:00Z,1\n", encoding="utf-8")
        else:
            path.write_text(json.dumps({"rows": [{"timestamp": "2026-01-01T00:00:00Z"}]}), encoding="utf-8")
