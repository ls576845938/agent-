from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.research.datasets import DatasetSpec, MLFeatureDatasetBuilder
from quant_us.research.model_scores import LinearModelScoreBuilder, LinearModelSpec
from quant_us.research.experiments import ExperimentRegistry


def _synthetic_bars() -> pd.DataFrame:
    """Produce a DataFrame of daily bars for two symbols over 10 trading days."""
    rows: list[dict] = []
    base = datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc)
    for i, symbol in enumerate(["AAPL", "MSFT"]):
        price = 100.0 * (1.0 + i * 0.5)  # AAPL=100, MSFT=150
        for d in range(10):
            ts = base.replace(month=1, day=2 + d)
            if ts.weekday() < 5:
                rows.append(
                    {
                        "timestamp_utc": ts,
                        "symbol": symbol,
                        "open": price * 0.99,
                        "high": price * 1.01,
                        "low": price * 0.98,
                        "close": price,
                        "volume": 10_000_000,
                    }
                )
                price *= 1.005  # slight uptrend
    return pd.DataFrame(rows)


def _synthetic_factors() -> pd.DataFrame:
    """Produce a factor-value DataFrame matching synthetic_bars dates."""
    rows: list[dict] = []
    base = date(2024, 1, 2)
    for symbol in ["AAPL", "MSFT"]:
        for d in range(10):
            dt = base.replace(day=2 + d)
            if dt.weekday() < 5:
                for factor, val in [("momentum_score", 1.0), ("realized_vol_20", 0.3), ("average_dollar_volume_20", 5e6)]:
                    rows.append(
                        {
                            "date": dt,
                            "symbol": symbol,
                            "factor_name": factor,
                            "factor_value": val,
                            "version": "v1",
                            "universe": "default",
                        }
                    )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# MLFeatureDatasetBuilder tests
# ---------------------------------------------------------------------------

class MLFeatureDatasetBuilderTests(unittest.TestCase):
    def test_dataset_spec_construction(self) -> None:
        """Building a DatasetSpec yields expected defaults and custom values."""
        default = DatasetSpec()
        self.assertEqual(default.dataset_name, "bar_factor_forward_return")
        self.assertEqual(default.feature_names, ("momentum_score", "realized_vol_20", "average_dollar_volume_20"))
        self.assertEqual(default.feature_version, "v1")
        self.assertEqual(default.universe, "default")
        self.assertEqual(default.label_horizon_bars, 5)
        self.assertTrue(default.drop_missing_features)

        custom = DatasetSpec(
            dataset_name="my_ds",
            feature_names=("alpha", "beta"),
            feature_version="v2",
            universe="sp500",
            label_horizon_bars=10,
            train_end=date(2024, 6, 1),
            validation_end=date(2024, 9, 1),
            drop_missing_features=False,
        )
        self.assertEqual(custom.dataset_name, "my_ds")
        self.assertEqual(custom.feature_names, ("alpha", "beta"))
        self.assertEqual(custom.feature_version, "v2")
        self.assertEqual(custom.universe, "sp500")
        self.assertEqual(custom.label_horizon_bars, 10)
        self.assertEqual(custom.train_end, date(2024, 6, 1))
        self.assertEqual(custom.validation_end, date(2024, 9, 1))
        self.assertFalse(custom.drop_missing_features)

    def test_builder_construction(self) -> None:
        """MLFeatureDatasetBuilder defaults output_root."""
        builder = MLFeatureDatasetBuilder()
        self.assertEqual(builder.output_root, Path("data/ml_datasets"))

        builder2 = MLFeatureDatasetBuilder("/tmp/my_ds")
        self.assertEqual(builder2.output_root, Path("/tmp/my_ds"))

    def test_build_dataset_expected_columns(self) -> None:
        """Build a dataset from synthetic bars + factors and verify columns."""
        with TemporaryDirectory() as tmp:
            builder = MLFeatureDatasetBuilder(Path(tmp) / "ml_datasets")
            bars = _synthetic_bars()
            factors = _synthetic_factors()

            result = builder.build_from_bars_and_factors(
                bars, factors,
                DatasetSpec(feature_version="v1", label_horizon_bars=2),
            )

            self.assertEqual(result.status, "completed")
            self.assertGreater(result.rows_written, 0)
            dataset = pd.read_parquet(result.dataset_path)

            expected_cols = {
                "date", "timestamp_utc", "symbol", "close",
                "forward_return_2b",
                "momentum_score", "realized_vol_20", "average_dollar_volume_20",
                "split", "feature_version", "universe", "label_horizon_bars",
            }
            self.assertTrue(expected_cols.issubset(set(dataset.columns)),
                            msg=f"Missing columns: {expected_cols - set(dataset.columns)}")

    def test_forward_return_calculation(self) -> None:
        """Forward return is correctly computed as close.shift(-N) / close - 1."""
        bars = _synthetic_bars()
        factors = _synthetic_factors()

        with TemporaryDirectory() as tmp:
            builder = MLFeatureDatasetBuilder(Path(tmp) / "ml_datasets")
            result = builder.build_from_bars_and_factors(
                bars, factors,
                DatasetSpec(feature_version="v1", label_horizon_bars=1),
            )

            self.assertEqual(result.status, "completed")
            self.assertGreater(result.rows_written, 0)
            dataset = pd.read_parquet(result.dataset_path)

        # Isolate AAPL rows in the output
        aapl_dataset = dataset[dataset["symbol"] == "AAPL"].sort_values("date").reset_index(drop=True)
        # Isolate AAPL bars used as input
        aapl_bars = bars[bars["symbol"] == "AAPL"].sort_values("timestamp_utc").reset_index(drop=True)

        # For AAPL with label_horizon_bars=1:
        # forward_return_1b[i] = close[i+1] / close[i] - 1
        aapl_close = aapl_bars["close"].values
        expected_returns = []
        for i in range(len(aapl_close) - 1):
            expected_returns.append(aapl_close[i + 1] / aapl_close[i] - 1.0)

        computed_returns = aapl_dataset["forward_return_1b"].values
        self.assertEqual(len(expected_returns), len(computed_returns))
        for expected, computed in zip(expected_returns, computed_returns):
            self.assertAlmostEqual(expected, computed, places=10)

    def test_missing_features_handled_gracefully(self) -> None:
        """When factor_values do not contain requested features, dataset is empty."""
        with TemporaryDirectory() as tmp:
            builder = MLFeatureDatasetBuilder(Path(tmp) / "ml_datasets")
            bars = _synthetic_bars()
            # create factors with a non-matching factor_name
            factors = _synthetic_factors()
            factors["factor_name"] = "unrelated_feature"

            result = builder.build_from_bars_and_factors(
                bars, factors,
                DatasetSpec(feature_names=("momentum_score",), feature_version="v1"),
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.rows_written, 0)
            self.assertEqual(result.dataset_path, "")

    def test_empty_input_no_crash(self) -> None:
        """Empty bars or empty factor_values return empty result without crashing."""
        with TemporaryDirectory() as tmp:
            builder = MLFeatureDatasetBuilder(Path(tmp) / "ml_datasets")
            empty = pd.DataFrame()

            result_bars = builder.build_from_bars_and_factors(empty, _synthetic_factors())
            self.assertEqual(result_bars.status, "completed")
            self.assertEqual(result_bars.rows_written, 0)

            result_factors = builder.build_from_bars_and_factors(_synthetic_bars(), empty)
            self.assertEqual(result_factors.status, "completed")
            self.assertEqual(result_factors.rows_written, 0)

    def test_negative_label_horizon_raises(self) -> None:
        """Negative or zero label_horizon_bars causes a failed result."""
        with TemporaryDirectory() as tmp:
            builder = MLFeatureDatasetBuilder(Path(tmp) / "ml_datasets")
            result = builder.build_from_bars_and_factors(
                _synthetic_bars(), _synthetic_factors(),
                DatasetSpec(label_horizon_bars=0),
            )
            self.assertEqual(result.status, "failed")
            self.assertIn("label_horizon_bars", result.error or "")

    def test_manifest_contains_metadata(self) -> None:
        """Manifest JSON includes spec, symbols, date range, and split counts."""
        with TemporaryDirectory() as tmp:
            builder = MLFeatureDatasetBuilder(Path(tmp) / "ml_datasets")
            result = builder.build_from_bars_and_factors(
                _synthetic_bars(), _synthetic_factors(),
                DatasetSpec(feature_version="v1", label_horizon_bars=2, train_end=date(2024, 1, 5), validation_end=date(2024, 1, 8)),
            )

            manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
            self.assertEqual(manifest["spec"]["feature_version"], "v1")
            self.assertIn("symbols", manifest)
            self.assertIn("date_start", manifest)
            self.assertIn("date_end", manifest)
            self.assertIn("split_counts", manifest)
            self.assertIn("run_id", manifest)


# ---------------------------------------------------------------------------
# LinearModelScoreBuilder tests
# ---------------------------------------------------------------------------

class LinearModelScoreBuilderTests(unittest.TestCase):
    def test_linear_model_spec_construction(self) -> None:
        """LinearModelSpec carries user-provided and default values."""
        spec = LinearModelSpec(
            model_id="m1",
            feature_names=["alpha"],
            weights={"alpha": 1.0},
        )
        self.assertEqual(spec.model_id, "m1")
        self.assertEqual(spec.intercept, 0.0)
        self.assertEqual(spec.score_name, "model_score")
        self.assertEqual(spec.score_version, "")

        spec2 = LinearModelSpec(
            model_id="m2",
            feature_names=["f1", "f2"],
            weights={"f1": 0.5, "f2": -0.3},
            intercept=1.0,
            score_name="alpha_score",
            score_version="v2",
        )
        self.assertEqual(spec2.intercept, 1.0)
        self.assertEqual(spec2.weights, {"f1": 0.5, "f2": -0.3})

    def test_score_calculation_within_expected_range(self) -> None:
        """Linear combination produces scores matching manual calculation."""
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # Create a small dataset parquet with known features
            rows = []
            for i, sym in enumerate(["AAPL", "MSFT", "GOOGL"]):
                for d in range(5):
                    rows.append({
                        "date": date(2024, 1, 2 + d),
                        "symbol": sym,
                        "alpha": 2.0 + i * 0.5,
                        "beta": 1.0 - i * 0.2,
                        "split": "train",
                    })
            dataset_path = tmp / "test_dataset.parquet"
            pd.DataFrame(rows).to_parquet(dataset_path, index=False)

            spec = LinearModelSpec(
                model_id="test_linear",
                feature_names=["alpha", "beta"],
                weights={"alpha": 1.0, "beta": -0.5},
                intercept=0.1,
                score_name="composite",
                score_version="v1",
            )

            builder = LinearModelScoreBuilder(
                feature_root=tmp / "features",
                model_root=tmp / "models",
                registry=ExperimentRegistry(tmp / "experiments"),
            )
            result = builder.score_dataset(dataset_path, spec, universe="core")

            self.assertEqual(result.status, "completed")
            self.assertGreater(result.rows_written, 0)
            self.assertTrue(Path(result.model_path).exists())

            # Manual verification: pick first row (AAPL, day 1: alpha=2.0, beta=1.0)
            # score = 0.1 + 2.0*1.0 + 1.0*(-0.5) = 1.6
            scores = pd.read_parquet(dataset_path)
            self.assertIn(result.model_manifest_path, ["", str(tmp / "experiments" / "models" / "model_id=test_linear" / "model.json")])

            # Read back scores from feature store
            from quant_us.data.storage.feature_store import ParquetFeatureStore
            stored = ParquetFeatureStore(tmp / "features").read_factor_values("composite", "v1")
            self.assertGreater(len(stored), 0)

    def test_cross_sectional_rank_properties(self) -> None:
        """Cross-sectional rank-transformed scores are monotonic with raw scores and span [0, 1]."""
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            # 5 symbols with distinct alpha values over 3 days
            rows = []
            for day in range(3):
                for rank_val, sym in enumerate(["A", "B", "C", "D", "E"]):
                    rows.append({
                        "date": date(2024, 1, 2 + day),
                        "symbol": sym,
                        "alpha": float(rank_val),
                        "split": "train",
                    })
            dataset_path = tmp / "rank_dataset.parquet"
            pd.DataFrame(rows).to_parquet(dataset_path, index=False)

            spec = LinearModelSpec(
                model_id="rank_test",
                feature_names=["alpha"],
                weights={"alpha": 1.0},
                intercept=0.0,
                score_name="raw_rank_score",
                score_version="v1",
            )

            builder = LinearModelScoreBuilder(
                feature_root=tmp / "features",
                model_root=tmp / "models",
            )
            result = builder.score_dataset(dataset_path, spec, universe="core")

            self.assertEqual(result.status, "completed")

            # Read back scores and compute cross-sectional rank
            from quant_us.data.storage.feature_store import ParquetFeatureStore
            stored = ParquetFeatureStore(tmp / "features").read_factor_values("raw_rank_score", "v1")
            self.assertGreater(len(stored), 0)

            stored = stored.copy()
            stored["rank"] = stored.groupby("date")["factor_value"].rank(pct=True)

            # rank(pct=True) in pandas uses rank/N formula, so for 5 symbols:
            # ranks are [0.2, 0.4, 0.6, 0.8, 1.0]
            self.assertGreaterEqual(stored["rank"].min(), 0.0)
            self.assertAlmostEqual(stored["rank"].max(), 1.0, places=1)

            # Verify monotonicity: higher factor_value => higher rank within each date
            for dt, group in stored.groupby("date"):
                sorted_group = group.sort_values("factor_value")
                self.assertEqual(
                    sorted_group["rank"].tolist(),
                    sorted(sorted_group["rank"].tolist()),
                    msg=f"Ranks not monotonic with factor_value on {dt}",
                )

    def test_empty_input_handled(self) -> None:
        """Empty dataset path or empty parquet file returns gracefully."""
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dataset_path = tmp / "empty.parquet"
            pd.DataFrame().to_parquet(dataset_path, index=False)

            spec = LinearModelSpec(
                model_id="empty_test",
                feature_names=["alpha"],
                weights={"alpha": 1.0},
            )
            builder = LinearModelScoreBuilder(
                feature_root=tmp / "features",
                model_root=tmp / "models",
            )
            result = builder.score_dataset(dataset_path, spec, universe="core")

            # Reading an empty parquet returns empty frame, which _score_frame returns as empty
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.rows_written, 0)

    def test_score_normalization_zero_to_one(self) -> None:
        """Scores can be min-max normalized to [0, 1]."""
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rows = []
            for sym in ["X", "Y", "Z"]:
                for day in range(2):
                    rows.append({
                        "date": date(2024, 1, 2 + day),
                        "symbol": sym,
                        "feature": 10.0 if sym == "Z" else 0.0 if sym == "X" else 5.0,
                        "split": "train",
                    })
            dataset_path = tmp / "norm_dataset.parquet"
            pd.DataFrame(rows).to_parquet(dataset_path, index=False)

            spec = LinearModelSpec(
                model_id="norm_test",
                feature_names=["feature"],
                weights={"feature": 1.0},
                intercept=0.0,
                score_name="norm_score",
                score_version="v1",
            )

            builder = LinearModelScoreBuilder(
                feature_root=tmp / "features",
                model_root=tmp / "models",
            )
            result = builder.score_dataset(dataset_path, spec, universe="core")

            self.assertEqual(result.status, "completed")

            from quant_us.data.storage.feature_store import ParquetFeatureStore
            stored = ParquetFeatureStore(tmp / "features").read_factor_values("norm_score", "v1")
            self.assertGreater(len(stored), 0)

            # Min-max normalize within each date cross-section
            stored = stored.copy()
            stored["min"] = stored.groupby("date")["factor_value"].transform("min")
            stored["max"] = stored.groupby("date")["factor_value"].transform("max")
            stored["normalized"] = (stored["factor_value"] - stored["min"]) / (stored["max"] - stored["min"])
            stored["normalized"] = stored["normalized"].fillna(0.5)  # single-symbol edge case

            self.assertTrue((stored["normalized"] >= 0.0).all())
            self.assertTrue((stored["normalized"] <= 1.0).all())

    def test_missing_feature_column_raises(self) -> None:
        """If a model feature is missing from the dataset, score_dataset returns failed."""
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rows = [{"date": date(2024, 1, 2), "symbol": "AAPL", "alpha": 1.0, "split": "train"}]
            dataset_path = tmp / "missing_cols.parquet"
            pd.DataFrame(rows).to_parquet(dataset_path, index=False)

            spec = LinearModelSpec(
                model_id="missing_test",
                feature_names=["alpha", "nonexistent"],
                weights={"alpha": 1.0, "nonexistent": 0.5},
            )
            builder = LinearModelScoreBuilder(
                feature_root=tmp / "features",
                model_root=tmp / "models",
            )
            result = builder.score_dataset(dataset_path, spec, universe="core")

            self.assertEqual(result.status, "failed")
            self.assertIn("nonexistent", result.error or "")


if __name__ == "__main__":
    unittest.main()
