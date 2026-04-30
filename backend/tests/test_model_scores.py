from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.backtest.runner import run_event_backtest_from_lake
from quant_us.data.cleaners.bar_cleaner import BarCleaner
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.research.experiments import ExperimentRegistry
from quant_us.research.model_scores import LinearModelScoreBuilder, LinearModelSpec


def synthetic_frame(symbol: str, count: int = 80) -> pd.DataFrame:
    timestamp = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    price = 100.0
    rows: list[dict[str, object]] = []
    while len(rows) < count:
        if timestamp.weekday() < 5:
            price *= 1.003
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


class ModelScoreTests(unittest.TestCase):
    def test_linear_model_scores_feed_factor_rank_backtest(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory)
            service = DataLakeService(DataLakeConfig(data_root=data_root))
            frames = {
                "AAPL": BarCleaner().clean(synthetic_frame("AAPL"), symbol="AAPL", source="unit").frame,
                "MSFT": BarCleaner().clean(synthetic_frame("MSFT"), symbol="MSFT", source="unit").frame,
            }
            for symbol, frame in frames.items():
                service.cleaned_store.write_bars(frame, vendor="yfinance", asset_class="equity", bar_size="1d", symbol=symbol)

            dataset_rows = []
            alpha_values = {"AAPL": 2.0, "MSFT": 1.0}
            for symbol, frame in frames.items():
                for timestamp in frame["timestamp_utc"]:
                    dataset_rows.append(
                        {
                            "date": timestamp.date(),
                            "symbol": symbol,
                            "alpha": alpha_values[symbol],
                            "split": "test",
                        }
                    )
            dataset_path = data_root / "unit_dataset.parquet"
            pd.DataFrame(dataset_rows).to_parquet(dataset_path, index=False)

            result = LinearModelScoreBuilder(
                feature_root=data_root / "features",
                model_root=data_root / "models",
                registry=ExperimentRegistry(data_root / "experiments"),
            ).score_dataset(
                dataset_path,
                LinearModelSpec(
                    model_id="linear_rank_v1",
                    feature_names=["alpha"],
                    weights={"alpha": 1.0},
                    intercept=0.0,
                    score_name="model_score",
                    score_version="linear_rank_v1",
                    feature_version="alpha_v1",
                    dataset_run_id="ds_unit",
                ),
                universe="core",
                split="test",
            )

            self.assertEqual(result.status, "completed")
            self.assertGreater(result.rows_written, 0)
            self.assertTrue(Path(result.model_path).exists())
            self.assertTrue(Path(result.model_manifest_path).exists())
            manifest = json.loads(Path(result.model_manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["model_id"], "linear_rank_v1")
            scores = ParquetFeatureStore(data_root / "features").read_factor_values("model_score", "linear_rank_v1")
            self.assertEqual(set(scores["symbol"]), {"AAPL", "MSFT"})

            backtest = run_event_backtest_from_lake(
                data_root=directory,
                symbol="AAPL",
                symbols=["AAPL", "MSFT"],
                start=datetime(2024, 1, 1, tzinfo=timezone.utc),
                end=datetime(2024, 6, 30, tzinfo=timezone.utc),
                strategy_id="factor_rank",
                strategy_params={"factor_name": "model_score", "top_n": 1, "min_symbols": 2},
                feature_version="linear_rank_v1",
                feature_universe="core",
            )

            self.assertEqual(backtest.metadata["feature_names"], ["model_score"])
            self.assertGreater(backtest.metadata["feature_rows"], 0)
            self.assertTrue({fill.symbol for fill in backtest.fills}.issubset({"AAPL"}))


if __name__ == "__main__":
    unittest.main()
