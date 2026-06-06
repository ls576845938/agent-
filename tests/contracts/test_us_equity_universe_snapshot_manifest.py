from __future__ import annotations

import json
from pathlib import Path

from scripts.build_us_equity_data_status_report import (
    build_us_equity_data_status,
    write_us_equity_data_status,
)


def test_us_equity_universe_snapshot_manifest_schema_exists() -> None:
    assert Path("schemas/us_equity_universe_snapshot_manifest.schema.json").exists()


def test_derived_from_bars_universe_snapshot_fails_pit_and_survivorship(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json", "AAPL")
    _write_manifest(tmp_path / "data/manifests/qs-yfinance-MSFT-1d-fixture.json", "MSFT")

    payload = build_us_equity_data_status(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )
    manifest = payload["universe_snapshot_manifest"]

    assert manifest["schema_version"] == "us_equity_universe_snapshot_manifest_v1"
    assert manifest["source_type"] == "derived_from_bars"
    assert manifest["point_in_time_confirmed"] is False
    assert manifest["membership_events_available"] is False
    assert manifest["delisted_symbols_included"] is False
    assert manifest["survivorship_risk"] == "likely"
    assert "universe_snapshot_manifest_derived_only" in manifest["blockers"]
    assert "point_in_time_universe_not_confirmed" in manifest["blockers"]
    assert "delisting_coverage_missing" in manifest["blockers"]


def test_universe_snapshot_manifest_writer_persists_lineage_artifact(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json", "AAPL")
    payload = build_us_equity_data_status(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    paths = write_us_equity_data_status(payload, tmp_path / "artifacts/us_equity_data_status/latest")

    persisted = json.loads(Path(paths["universe_snapshot_manifest"]).read_text(encoding="utf-8"))
    data_status = json.loads(Path(paths["data_status_report"]).read_text(encoding="utf-8"))
    assert persisted["source_type"] == "derived_from_bars"
    assert data_status["universe_snapshot_manifest_path"].endswith("universe_snapshot_manifest.json")


def _write_manifest(path: Path, symbol: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "data_version": path.stem,
        "source": "yfinance",
        "symbol": symbol,
        "interval": "1d",
        "asset_class": "equity",
        "timezone": "UTC",
        "adjustment_policy": "raw",
        "start": "2024-01-02T00:00:00+00:00",
        "end": "2024-01-03T00:00:00+00:00",
        "coverage_pct": 100.0,
        "quality_score": 99.0,
        "quality_summary": {},
        "survivorship_bias_risk": "clean",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
