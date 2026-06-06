from __future__ import annotations

import json
from pathlib import Path

from scripts.build_us_equity_data_status_report import (
    build_us_equity_data_status,
    write_us_equity_data_status,
)


def test_us_equity_data_status_schema_files_exist() -> None:
    assert Path("schemas/us_equity_data_status_report.schema.json").exists()
    assert Path("schemas/us_equity_universe_manifest.schema.json").exists()
    assert Path("schemas/us_equity_corporate_action_report.schema.json").exists()
    assert Path("schemas/us_equity_universe_snapshot_manifest.schema.json").exists()
    assert Path("schemas/us_equity_corporate_action_status_report.schema.json").exists()
    assert Path("schemas/us_equity_survivorship_audit_report.schema.json").exists()
    assert Path("schemas/us_equity_provider_capability_matrix.schema.json").exists()
    assert Path("schemas/us_equity_production_bundle_preflight_report.schema.json").exists()
    assert Path("schemas/us_equity_provider_verification_report.schema.json").exists()


def test_us_equity_data_status_uses_only_us_equity_manifests(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json",
        data_version="qs-yfinance-AAPL-1d-fixture",
        source="yfinance",
        symbol="AAPL",
    )
    _write_manifest(
        tmp_path / "data/manifests/qs-yfinance-MSFT-1d-fixture.json",
        data_version="qs-yfinance-MSFT-1d-fixture",
        source="yfinance",
        symbol="MSFT",
    )
    _write_manifest(
        tmp_path / "data/manifests/qs-sqlite-BTCUSDT-1h-fixture.json",
        data_version="qs-sqlite-BTCUSDT-1h-fixture",
        source="sqlite",
        symbol="BTCUSDT",
        asset_class="crypto",
    )

    payload = build_us_equity_data_status(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )
    data_status = payload["data_status_report"]
    universe_manifest = payload["universe_manifest"]
    corporate_action_report = payload["corporate_action_report"]
    universe_snapshot_manifest = payload["universe_snapshot_manifest"]
    corporate_action_status_report = payload["corporate_action_status_report"]
    survivorship_audit_report = payload["survivorship_audit_report"]

    assert data_status["schema_version"] == "us_equity_data_status_report_v1"
    assert data_status["paper_queue_status"] == "locked"
    assert data_status["live_status"] == "frozen"
    assert data_status["manifest_count"] == 2
    assert data_status["symbols"] == ["AAPL", "MSFT"]
    assert all(not item.startswith("qs-sqlite-BTC") for item in data_status["data_versions"])
    assert data_status["quality_summary"]["min_coverage_pct"] == 100.0
    assert data_status["quality_summary"]["avg_quality_score"] == 99.0
    assert data_status["promotion_ready"] is False
    assert data_status["promotion_clean"] is False
    assert data_status["data_lineage_grade"]["value"] == "L1_sample_non_pit"
    assert data_status["data_lineage_maturity"]["point_in_time_universe_confirmed"] is False
    assert data_status["data_lineage_maturity"]["corporate_action_event_source_available"] is False
    assert data_status["data_lineage_maturity"]["delisting_coverage_confirmed"] is False
    assert data_status["data_lineage_maturity"]["identifier_mapping_available"] is False
    assert data_status["selected_provider"] == "yfinance"
    assert data_status["provider_verified_for_promotion"] is False
    assert "universe_snapshot_manifest_derived_only" in data_status["blockers"]
    assert "identifier_mapping_missing" in data_status["blockers"]
    assert "survivorship_status_not_clean" in data_status["blockers"]

    assert universe_manifest["schema_version"] == "us_equity_universe_manifest_v1"
    assert universe_manifest["symbol_count"] == 2
    assert universe_manifest["point_in_time"] is False
    assert "point_in_time_universe_not_confirmed" in universe_manifest["blockers"]
    assert corporate_action_report["schema_version"] == "us_equity_corporate_action_report_v1"
    assert corporate_action_report["status"] == "manifest_derived_only"
    assert "corporate_action_event_source_missing" in corporate_action_report["blockers"]
    assert universe_snapshot_manifest["source_type"] == "derived_from_bars"
    assert universe_snapshot_manifest["point_in_time_confirmed"] is False
    assert corporate_action_status_report["corporate_action_event_source_available"] is False
    assert survivorship_audit_report["survivorship_status"] == "not_clean"


def test_us_equity_data_status_writer_persists_three_artifacts(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json",
        data_version="qs-yfinance-AAPL-1d-fixture",
        source="yfinance",
        symbol="AAPL",
    )
    payload = build_us_equity_data_status(
        repo_root=tmp_path,
        generated_at="2026-05-18T00:00:00Z",
    )

    paths = write_us_equity_data_status(payload, tmp_path / "artifacts/us_equity_data_status/latest")

    data_status = json.loads(Path(paths["data_status_report"]).read_text(encoding="utf-8"))
    universe_manifest = json.loads(Path(paths["universe_manifest"]).read_text(encoding="utf-8"))
    corporate_action_report = json.loads(Path(paths["corporate_action_report"]).read_text(encoding="utf-8"))
    universe_snapshot_manifest = json.loads(Path(paths["universe_snapshot_manifest"]).read_text(encoding="utf-8"))
    corporate_action_status_report = json.loads(Path(paths["corporate_action_status_report"]).read_text(encoding="utf-8"))
    survivorship_audit_report = json.loads(Path(paths["survivorship_audit_report"]).read_text(encoding="utf-8"))
    provider_capability_matrix = json.loads(Path(paths["provider_capability_matrix"]).read_text(encoding="utf-8"))
    production_bundle_preflight_report = json.loads(
        Path(paths["production_bundle_preflight_report"]).read_text(encoding="utf-8")
    )
    provider_verification_report = json.loads(Path(paths["provider_verification_report"]).read_text(encoding="utf-8"))

    assert data_status["universe_manifest_path"].endswith("universe_manifest.json")
    assert data_status["corporate_action_report_path"].endswith("corporate_action_report.json")
    assert data_status["universe_snapshot_manifest_path"].endswith("universe_snapshot_manifest.json")
    assert data_status["corporate_action_status_report_path"].endswith("corporate_action_status_report.json")
    assert data_status["survivorship_audit_report_path"].endswith("survivorship_audit_report.json")
    assert data_status["provider_capability_matrix_path"].endswith("provider_capability_matrix.json")
    assert data_status["production_bundle_preflight_report_path"].endswith("production_bundle_preflight_report.json")
    assert data_status["provider_verification_report_path"].endswith("provider_verification_report.json")
    assert universe_manifest["symbols"] == ["AAPL"]
    assert corporate_action_report["symbols"] == ["AAPL"]
    assert universe_snapshot_manifest["symbol_count"] == 1
    assert corporate_action_status_report["promotion_clean"] is False
    assert survivorship_audit_report["promotion_clean"] is False
    assert provider_capability_matrix["promotion_clean_provider_available"] is False
    assert production_bundle_preflight_report["production_bundle_preflight_pass"] is False
    assert provider_verification_report["promotion_clean"] is False


def _write_manifest(
    path: Path,
    *,
    data_version: str,
    source: str,
    symbol: str,
    asset_class: str = "equity",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "data_version": data_version,
        "source": source,
        "symbol": symbol,
        "interval": "1d",
        "asset_class": asset_class,
        "timezone": "UTC",
        "adjustment_policy": "raw",
        "corporate_action_adjustment": "raw",
        "start": "2024-01-02T00:00:00+00:00",
        "end": "2024-01-03T00:00:00+00:00",
        "row_count": 2,
        "expected_rows": 2,
        "coverage_pct": 100.0,
        "quality_score": 99.0,
        "fingerprint": "a" * 64,
        "checksum": "a" * 64,
        "quality_summary": {
            "missing_bars": 0,
            "duplicate_bars": 0,
            "invalid_ohlc_rows": 0,
            "non_positive_price_rows": 0,
            "zero_volume_bars": 0,
            "total_issue_count": 0,
        },
        "universe_id": "us-core-fixture",
        "universe_source": "fixture",
        "survivorship_bias_risk": "clean",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
