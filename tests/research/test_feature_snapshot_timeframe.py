from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_us.factors.feature_pipeline import FeaturePipeline
from quant_us.research.features.snapshot import FeatureSnapshotManager


def test_feature_pipeline_preserves_intraday_timeframe_columns(tmp_path: Path) -> None:
    bars = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-02 14:30:00+00:00", periods=80, freq="5min"),
            "symbol": ["AAPL"] * 80,
            "close": [100.0 + i * 0.1 for i in range(80)],
            "volume": [1_000_000 + i for i in range(80)],
        }
    )

    pipeline = FeaturePipeline(feature_root=tmp_path / "features")
    result = pipeline.build_bar_factors(bars, bar_size="5m")

    assert result.status == "completed"
    stored = pipeline.store.read_factor_values("momentum_score", "v1")
    assert not stored.empty
    assert "timestamp_utc" in stored.columns
    assert set(stored["bar_size"]) == {"5m"}
    assert set(stored["timeframe"]) == {"5m"}


def test_feature_snapshot_manager_records_bar_size_and_timeframe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    def mock_compute(self, factor_ids, symbols, start, end, *, bar_size="1d", timeframe=None):
        captured["bar_size"] = bar_size
        captured["timeframe"] = timeframe or ""
        return pd.DataFrame(
            {
                "timestamp_utc": [datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)],
                "date": ["2024-01-02"],
                "symbol": ["AAPL"],
                factor_ids[0]: [0.42],
            }
        )

    monkeypatch.setattr("quant_us.research.features.snapshot.FactorPipeline.compute", mock_compute)

    manager = FeatureSnapshotManager(data_root=str(tmp_path))
    snapshot = manager.build(
        feature_id="momentum_20d",
        version="v1",
        symbols=["AAPL"],
        start="2024-01-01",
        end="2024-01-31",
        bar_size="15m",
    )

    assert captured["bar_size"] == "15m"
    assert captured["timeframe"] == "15m"
    assert snapshot.bar_size == "15m"
    assert snapshot.timeframe == "15m"
    assert "_15m_" in snapshot.snapshot_id

    manifest_path = Path(snapshot.path).parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["bar_size"] == "15m"
    assert manifest["timeframe"] == "15m"
