from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from quant_us.data.storage.data_manifest import (
    DataManifest,
    DataManifestStore,
    build_manifest_from_quality,
    validate_manifest_for_promotion,
)


def _promotion_grade_manifest(**overrides) -> DataManifest:
    payload = {
        "data_version": "qs-yfinance-AAPL-1d-test",
        "source": "yfinance",
        "symbol": "AAPL",
        "interval": "1d",
        "asset_class": "equity",
        "timezone": "UTC",
        "adjustment": "raw",
        "adjustment_policy": "raw",
        "corporate_action_adjustment": "raw",
        "start": "2024-01-02T00:00:00+00:00",
        "end": "2024-12-31T00:00:00+00:00",
        "row_count": 252,
        "expected_rows": 252,
        "coverage_pct": 100.0,
        "fingerprint": "a" * 64,
        "checksum": "a" * 64,
        "quality_score": 99.0,
        "created_at": "2026-05-01T00:00:00+00:00",
        "cleaning": {
            "duplicate_timestamps_removed": 0,
            "invalid_ohlc_removed": 0,
            "non_positive_prices_removed": 0,
            "cleaning_loss_rows": 0,
            "missing_bars": 0,
        },
        "quality_summary": {
            "missing_bars": 0,
            "duplicate_bars": 0,
            "price_jump_bars": 0,
            "zero_volume_bars": 0,
            "corporate_action_flags": 0,
            "invalid_ohlc_rows": 0,
            "non_positive_price_rows": 0,
            "duplicate_timestamps_removed": 0,
            "cleaning_loss_rows": 0,
            "total_issue_count": 0,
        },
        "universe_id": "us-core-v2",
        "universe_source": "universe_builder:v2",
        "survivorship_bias_risk": "clean",
    }
    payload.update(overrides)
    return DataManifest(**payload)


def test_build_manifest_from_quality_populates_quality_summary() -> None:
    quality = {
        "data_version": "qs-yfinance-AAPL-1d-123456789abc",
        "first_timestamp": "2024-01-02T00:00:00+00:00",
        "last_timestamp": "2024-01-10T00:00:00+00:00",
        "row_count": 6,
        "expected_rows": 8,
        "coverage_pct": 75.0,
        "fingerprint": "b" * 64,
        "quality_score": 88.5,
        "duplicate_timestamps": 1,
        "invalid_ohlc": 2,
        "non_positive_prices": 3,
        "cleaning_loss_rows": 6,
        "missing_bars": 2,
        "issues": [
            {"report_type": "missing_bars", "issues_found": 2},
            {"report_type": "duplicate_bars", "issues_found": 1},
            {"report_type": "zero_volume", "issues_found": 4},
            {"report_type": "corporate_action", "issues_found": 1},
        ],
    }

    manifest = build_manifest_from_quality(
        quality=quality,
        source="yfinance",
        symbol="aapl",
        interval="1d",
        universe_id="us-core-v2",
        universe_source="universe_builder:v2",
        survivorship_bias_risk="clean",
        adjustment_policy="raw",
    )

    assert manifest.symbol == "AAPL"
    assert manifest.quality_summary == {
        "missing_bars": 2,
        "duplicate_bars": 1,
        "price_jump_bars": 0,
        "zero_volume_bars": 4,
        "corporate_action_flags": 1,
        "invalid_ohlc_rows": 2,
        "non_positive_price_rows": 3,
        "duplicate_timestamps_removed": 1,
        "cleaning_loss_rows": 6,
        "total_issue_count": 8,
    }


def test_strict_promotion_validation_blocks_bad_data_and_lineage() -> None:
    manifest = _promotion_grade_manifest(
        adjustment_policy="unknown",
        corporate_action_adjustment="unknown",
        cleaning={
            "duplicate_timestamps_removed": 1,
            "invalid_ohlc_removed": 2,
            "non_positive_prices_removed": 3,
            "cleaning_loss_rows": 6,
            "missing_bars": 4,
        },
        quality_summary={
            "missing_bars": 4,
            "duplicate_bars": 1,
            "price_jump_bars": 0,
            "zero_volume_bars": 2,
            "corporate_action_flags": 0,
            "invalid_ohlc_rows": 2,
            "non_positive_price_rows": 3,
            "duplicate_timestamps_removed": 1,
            "cleaning_loss_rows": 6,
            "total_issue_count": 7,
        },
        universe_id="",
        universe_source="",
        survivorship_bias_risk="unknown",
        checksum="c" * 64,
    )

    result = validate_manifest_for_promotion(
        manifest,
        strict=True,
        now=datetime(2026, 5, 9, tzinfo=timezone.utc),
    )

    assert result.ok is False
    assert "checksum_mismatch" in result.reasons
    assert "adjustment_policy:unknown" in result.reasons
    assert "universe_id_missing" in result.reasons
    assert "universe_source_missing" in result.reasons
    assert "survivorship_bias_risk_unmarked" in result.reasons
    assert "duplicate_timestamps:1" in result.reasons
    assert "invalid_ohlc:2" in result.reasons
    assert "non_positive_prices:3" in result.reasons
    assert "missing_bars:4" in result.reasons
    assert "zero_volume_bars:2" in result.reasons


def test_strict_promotion_validation_accepts_clean_manifest() -> None:
    result = validate_manifest_for_promotion(
        _promotion_grade_manifest(),
        strict=True,
        now=datetime(2026, 5, 9, tzinfo=timezone.utc),
    )

    assert result.ok is True
    assert result.reasons == []
    assert result.metrics["quality_summary"]["total_issue_count"] == 0


def test_manifest_round_trip_preserves_quality_summary(tmp_path: Path) -> None:
    store = DataManifestStore(root=tmp_path)
    manifest = _promotion_grade_manifest(
        quality_summary={
            "missing_bars": 0,
            "duplicate_bars": 0,
            "price_jump_bars": 1,
            "zero_volume_bars": 0,
            "corporate_action_flags": 1,
            "invalid_ohlc_rows": 0,
            "non_positive_price_rows": 0,
            "duplicate_timestamps_removed": 0,
            "cleaning_loss_rows": 0,
            "total_issue_count": 2,
        }
    )

    store.write(manifest)
    loaded = store.read(manifest.data_version)

    assert loaded is not None
    assert loaded.quality_summary == manifest.quality_summary


def test_build_manifest_is_stable_for_same_quality_payload() -> None:
    quality = {
        "data_version": "qs-yfinance-AAPL-1d-stable",
        "first_timestamp": "2024-01-02T00:00:00+00:00",
        "last_timestamp": "2024-01-03T00:00:00+00:00",
        "row_count": 2,
        "expected_rows": 2,
        "coverage_pct": 100.0,
        "fingerprint": "d" * 64,
        "quality_score": 97.0,
        "duplicate_timestamps": 0,
        "invalid_ohlc": 0,
        "non_positive_prices": 0,
        "cleaning_loss_rows": 0,
        "missing_bars": 0,
        "issues": [],
    }
    fixed_now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    with patch("quant_us.data.storage.data_manifest.utc_now", return_value=fixed_now):
        left = build_manifest_from_quality(
            quality=quality,
            source="yfinance",
            symbol="AAPL",
            interval="1d",
            universe_id="us-core-v2",
            universe_source="universe_builder:v2",
            survivorship_bias_risk="clean",
            adjustment_policy="raw",
        )
        right = build_manifest_from_quality(
            quality=quality,
            source="yfinance",
            symbol="AAPL",
            interval="1d",
            universe_id="us-core-v2",
            universe_source="universe_builder:v2",
            survivorship_bias_risk="clean",
            adjustment_policy="raw",
        )

    assert left == right
