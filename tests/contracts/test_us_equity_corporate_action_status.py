from __future__ import annotations

import json
from pathlib import Path

from scripts.build_us_equity_data_status_report import (
    build_us_equity_data_status,
    write_us_equity_data_status,
)


def test_us_equity_corporate_action_status_schema_exists() -> None:
    assert Path("schemas/us_equity_corporate_action_status_report.schema.json").exists()


def test_missing_corporate_action_events_fail_promotion_clean(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json", "AAPL")

    payload = build_us_equity_data_status(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )
    report = payload["corporate_action_status_report"]

    assert report["schema_version"] == "us_equity_corporate_action_status_report_v1"
    assert report["price_source"] == "yfinance"
    assert report["adjustment_mode"] == "raw"
    assert report["split_events_available"] is False
    assert report["dividend_events_available"] is False
    assert report["delisting_events_available"] is False
    assert report["corporate_action_event_source_available"] is False
    assert report["adjustment_reproducible"] is False
    assert report["promotion_clean"] is False
    assert "corporate_action_event_source_missing" in report["blockers"]


def test_corporate_action_status_writer_persists_lineage_artifact(tmp_path: Path) -> None:
    _write_manifest(tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json", "AAPL")
    payload = build_us_equity_data_status(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    paths = write_us_equity_data_status(payload, tmp_path / "artifacts/us_equity_data_status/latest")

    persisted = json.loads(Path(paths["corporate_action_status_report"]).read_text(encoding="utf-8"))
    data_status = json.loads(Path(paths["data_status_report"]).read_text(encoding="utf-8"))
    assert persisted["promotion_clean"] is False
    assert data_status["corporate_action_status_report_path"].endswith("corporate_action_status_report.json")


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
        "corporate_action_adjustment": "raw",
        "adjustment": "raw",
        "start": "2024-01-02T00:00:00+00:00",
        "end": "2024-01-03T00:00:00+00:00",
        "coverage_pct": 100.0,
        "quality_score": 99.0,
        "quality_summary": {},
        "survivorship_bias_risk": "clean",
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
