from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.factors.feature_pipeline import FeaturePipeline
from quant_us.research.datasets import DatasetSpec, MLFeatureDatasetBuilder


def synthetic_frame(symbol: str, count: int = 110, drift: float = 1.003) -> pd.DataFrame:
    timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    price = 100.0
    rows: list[dict[str, object]] = []
    while len(rows) < count:
        if timestamp.weekday() < 5:
            price *= drift
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "open": price * 0.99,
                    "high": price * 1.01,
                    "low": price * 0.98,
                    "close": price,
                    "volume": 10_000_000,
                }
            )
        timestamp += timedelta(days=1)
    return pd.DataFrame(rows)


class ResearchDatasetTests(unittest.TestCase):
    def test_ml_dataset_builder_writes_time_split_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            bars = pd.concat(
                [
                    BarCleaner().clean(synthetic_frame("AAPL", drift=1.003), symbol="AAPL", source="unit").frame,
                    BarCleaner().clean(synthetic_frame("MSFT", drift=1.004), symbol="MSFT", source="unit").frame,
                ],
                ignore_index=True,
            )
            feature_result = FeaturePipeline(feature_root=Path(directory) / "features").build_bar_factors(
                bars,
                universe="core",
                version="test",
            )
            self.assertEqual(feature_result.status, "completed")

            factor_frames = [
                FeaturePipeline(feature_root=Path(directory) / "features").store.read_factor_values("momentum_score", "test"),
                FeaturePipeline(feature_root=Path(directory) / "features").store.read_factor_values("realized_vol_20", "test"),
                FeaturePipeline(feature_root=Path(directory) / "features").store.read_factor_values("average_dollar_volume_20", "test"),
            ]
            factor_values = pd.concat(factor_frames, ignore_index=True)
            result = MLFeatureDatasetBuilder(Path(directory) / "ml_datasets").build_from_bars_and_factors(
                bars,
                factor_values,
                DatasetSpec(
                    feature_version="test",
                    universe="core",
                    label_horizon_bars=5,
                    train_end=date(2024, 4, 15),
                    validation_end=date(2024, 5, 10),
                ),
            )

            self.assertEqual(result.status, "completed")
            self.assertGreater(result.rows_written, 0)
            dataset = pd.read_parquet(result.dataset_path)
            self.assertIn("forward_return_5b", dataset.columns)
            self.assertFalse(dataset["forward_return_5b"].isna().any())
            self.assertTrue({"train", "validation", "test"}.issubset(set(dataset["split"])))
            manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["spec"]["feature_version"], "test")
            self.assertEqual(manifest["symbols"], ["AAPL", "MSFT"])


if __name__ == "__main__":
    unittest.main()
