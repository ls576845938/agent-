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
    assert all(item["pit_contract"]["present"] is True for item in payload["files"])
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


def test_complete_production_bundle_can_be_quality_checked_without_promotion_clean(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="quality_checked_only_bundle",
        source_type="production",
        license_note="public market data",
        promotion_clean_allowed=False,
    )

    assert payload["promotion_clean_allowed"] is False
    assert "btc_perpetual_bundle_promotion_clean_not_allowed" not in payload["blockers"]
    assert validate_btc_perpetual_data_bundle_manifest(bundle, payload)["valid"] is True


def test_btc_perpetual_bundle_manifest_requires_pit_fields_for_gate_data(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)
    (bundle / "funding_rate.csv").write_text("timestamp,value\n2026-01-01T00:00:00Z,1\n", encoding="utf-8")

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="broken_pit_bundle",
        source_type="production",
        license_note="vendor export",
        promotion_clean_allowed=True,
    )
    by_path = {item["path"]: item for item in payload["files"]}

    assert by_path["funding_rate.csv"]["pit_contract"]["present"] is False
    assert by_path["funding_rate.csv"]["pit_contract"]["missing_fields"] == [
        "event_time",
        "available_time",
        "ingested_at",
        "processed_at",
    ]
    assert "btc_pit_contract_required_fields_missing:funding_rate.csv" in payload["blockers"]
    assert validate_btc_perpetual_data_bundle_manifest(bundle, payload)["valid"] is False


def test_btc_perpetual_bundle_manifest_rejects_future_visible_available_time(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)
    (bundle / "klines_1h.csv").write_text(
        "\n".join(
            [
                "event_time,available_time,ingested_at,processed_at,value",
                "2026-01-01T01:00:00Z,2026-01-01T00:59:00Z,2026-01-01T01:00:01Z,2026-01-01T01:00:02Z,1",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="future_visible_bundle",
        source_type="production",
        license_note="vendor export",
        promotion_clean_allowed=True,
    )
    by_path = {item["path"]: item for item in payload["files"]}

    assert by_path["klines_1h.csv"]["pit_contract"]["available_time_order_violation_count"] == 1
    assert "btc_pit_contract_available_time_before_event_time_violation:klines_1h.csv" in payload["blockers"]


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


def test_manifest_preserves_independent_component_coverage(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)
    (bundle / "klines_1h.csv").write_text(
        "event_time,available_time,ingested_at,processed_at,value\n"
        "2026-01-01T00:00:00Z,2026-01-01T01:00:00Z,2026-01-01T01:00:01Z,2026-01-01T01:00:02Z,1\n"
        "2026-01-01T01:00:00Z,2026-01-01T02:00:00Z,2026-01-01T02:00:01Z,2026-01-01T02:00:02Z,1\n",
        encoding="utf-8",
    )
    (bundle / "funding_rate.csv").write_text(
        "event_time,available_time,ingested_at,processed_at,value\n"
        "2026-01-01T01:00:00Z,2026-01-01T01:00:00Z,2026-01-01T01:00:01Z,2026-01-01T01:00:02Z,1\n",
        encoding="utf-8",
    )

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="independent_component_coverage",
        source_type="production",
        source_provider="okx_swap",
        license_note="public data fixture",
        promotion_clean_allowed=True,
    )
    by_role = {item["role"]: item for item in payload["files"]}

    assert by_role["klines_1h"]["record_count"] == 2
    assert by_role["klines_1h"]["sample_start"] == "2026-01-01T00:00:00Z"
    assert by_role["klines_1h"]["sample_end"] == "2026-01-01T01:00:00Z"
    assert by_role["funding_rate"]["record_count"] == 1
    assert by_role["funding_rate"]["sample_start"] == "2026-01-01T01:00:00Z"
    assert by_role["funding_rate"]["sample_end"] == "2026-01-01T01:00:00Z"


def test_microstructure_diagnostic_files_are_recorded_when_present(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _write_required_files(bundle)
    (bundle / "agg_trades.csv").write_text("timestamp,price,size\n2026-01-01T00:00:00Z,1,1\n", encoding="utf-8")
    (bundle / "order_book_depth.csv").write_text(
        "event_time,available_time,ingested_at,processed_at,side,level,price,size\n"
        "2026-01-01T00:00:00Z,2026-01-01T00:00:01Z,2026-01-01T00:00:02Z,2026-01-01T00:00:03Z,bid,1,1,1\n",
        encoding="utf-8",
    )

    payload = build_btc_perpetual_data_bundle_manifest(
        bundle_dir=bundle,
        bundle_id="fixture_bundle",
        source_type="fixture",
        source_provider="okx_swap",
        license_note="test fixture",
    )
    by_role = {item["role"]: item for item in payload["files"]}

    assert by_role["agg_trades"]["source_endpoint_or_archive"] == "/api/v5/market/history-trades"
    assert by_role["order_book_depth"]["source_endpoint_or_archive"] == "/api/v5/market/books"
    assert by_role["order_book_depth"]["record_count"] == 1


def _write_required_files(bundle: Path) -> None:
    bundle.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_FILES:
        path = bundle / filename
        if filename.endswith(".csv"):
            path.write_text(
                "event_time,available_time,ingested_at,processed_at,value\n"
                "2026-01-01T00:00:00Z,2026-01-01T00:00:01Z,"
                "2026-01-01T00:00:02Z,2026-01-01T00:00:03Z,1\n",
                encoding="utf-8",
            )
        else:
            path.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "event_time": "2026-01-01T00:00:00Z",
                                "available_time": "2026-01-01T00:00:01Z",
                                "ingested_at": "2026-01-01T00:00:02Z",
                                "processed_at": "2026-01-01T00:00:03Z",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
