from __future__ import annotations

import json
from pathlib import Path

from scripts.build_us_equity_provider_verification_report import (
    build_provider_verification_report,
    write_provider_verification_report,
)


def test_provider_verification_schema_exists() -> None:
    assert Path("schemas/us_equity_provider_verification_report.schema.json").exists()


def test_yfinance_verification_is_research_only_not_promotion_clean(tmp_path: Path) -> None:
    _write_yfinance_manifest(tmp_path / "data/manifests/qs-yfinance-AAPL-1d-fixture.json")

    report = build_provider_verification_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["selected_provider"] == "yfinance"
    assert report["local_data_available"] is True
    assert report["point_in_time_universe_confirmed"] is False
    assert report["identifier_mapping_available"] is False
    assert report["promotion_clean"] is False
    assert report["data_lineage_grade_candidate"] == "L1_sample_non_pit"
    assert "provider_capability_not_verification" in report["blockers"]


def test_missing_provider_verification_fails_closed(tmp_path: Path) -> None:
    report = build_provider_verification_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    assert report["selected_provider"] == "none"
    assert report["promotion_clean"] is False
    assert "selected_provider_missing" in report["blockers"]


def test_provider_verification_writer_persists_artifact(tmp_path: Path) -> None:
    report = build_provider_verification_report(
        repo_root=tmp_path,
        generated_at="2026-05-19T00:00:00Z",
    )

    output = write_provider_verification_report(
        report,
        tmp_path / "artifacts/us_equity_data_lineage/latest/provider_verification_report.json",
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == "us_equity_provider_verification_report_v1"


def _write_yfinance_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "data_version": path.stem,
                "source": "yfinance",
                "symbol": "AAPL",
                "interval": "1d",
                "asset_class": "equity",
                "start": "2024-01-02T00:00:00+00:00",
                "end": "2024-01-03T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
