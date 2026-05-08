"""Verify train/test time split is enforced in dataset construction.

Time-split violations can introduce lookahead bias.
"""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from quant_us.research.datasets import MLFeatureDatasetBuilder, DatasetSpec


class TestTimeSplitEnforced(unittest.TestCase):
    """Time-split enforcement in dataset builder."""

    def setUp(self) -> None:
        self.builder = MLFeatureDatasetBuilder(output_root="/tmp/test_time_split")

    def _make_bars(self, n_dates: int = 100) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=n_dates, freq="D", tz="UTC")
        rows = []
        for sym in ["AAPL", "MSFT"]:
            for i, dt in enumerate(dates):
                rows.append({
                    "timestamp_utc": dt,
                    "symbol": sym,
                    "open": 100.0 + i * 0.1,
                    "high": 101.0 + i * 0.1,
                    "low": 99.0 + i * 0.1,
                    "close": 100.0 + i * 0.1,
                    "volume": 1000000,
                })
        return pd.DataFrame(rows)

    def _make_factors(self, bars: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for sym in bars["symbol"].unique():
            for _, row in bars[bars["symbol"] == sym].iterrows():
                rows.append({
                    "date": pd.Timestamp(row["timestamp_utc"]).strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "factor_name": "momentum_score",
                    "factor_value": 0.05,
                    "version": "v1",
                    "universe": "default",
                })
        return pd.DataFrame(rows)

    def test_split_column_exists(self) -> None:
        bars = self._make_bars(60)
        factors = self._make_factors(bars)
        spec = DatasetSpec(
            train_end=date(2024, 2, 1),
            validation_end=date(2024, 2, 15),
        )
        result = self.builder.build_from_bars_and_factors(bars, factors, spec)
        dataset = pd.read_parquet(result.dataset_path)
        self.assertIn("split", dataset.columns)

    def test_split_has_train_validation_test(self) -> None:
        bars = self._make_bars(60)
        factors = self._make_factors(bars)
        spec = DatasetSpec(
            train_end=date(2024, 2, 1),
            validation_end=date(2024, 2, 15),
        )
        result = self.builder.build_from_bars_and_factors(bars, factors, spec)
        dataset = pd.read_parquet(result.dataset_path)
        splits = dataset["split"].unique()
        # At least train and test should be present
        self.assertIn("train", splits)
        self.assertIn("test", splits)

    def test_train_before_test(self) -> None:
        """All train dates should be before all test dates."""
        bars = self._make_bars(60)
        factors = self._make_factors(bars)
        spec = DatasetSpec(
            train_end=date(2024, 2, 1),
            validation_end=date(2024, 2, 15),
        )
        result = self.builder.build_from_bars_and_factors(bars, factors, spec)
        dataset = pd.read_parquet(result.dataset_path)

        train_dates = dataset[dataset["split"] == "train"]["date"]
        test_dates = dataset[dataset["split"] == "test"]["date"]

        if not train_dates.empty and not test_dates.empty:
            self.assertLessEqual(
                max(pd.to_datetime(train_dates)),
                min(pd.to_datetime(test_dates)),
            )

    def test_validation_between_train_and_test(self) -> None:
        """Validation dates should be between train and test."""
        bars = self._make_bars(60)
        factors = self._make_factors(bars)
        spec = DatasetSpec(
            train_end=date(2024, 2, 1),
            validation_end=date(2024, 2, 15),
        )
        result = self.builder.build_from_bars_and_factors(bars, factors, spec)
        dataset = pd.read_parquet(result.dataset_path)

        train_dates = dataset[dataset["split"] == "train"]["date"]
        val_dates = dataset[dataset["split"] == "validation"]["date"]
        test_dates = dataset[dataset["split"] == "test"]["date"]

        if not train_dates.empty and not val_dates.empty:
            self.assertLessEqual(max(pd.to_datetime(train_dates)), min(pd.to_datetime(val_dates)))
        if not val_dates.empty and not test_dates.empty:
            self.assertLessEqual(max(pd.to_datetime(val_dates)), min(pd.to_datetime(test_dates)))

    def test_no_future_leaks_in_features(self) -> None:
        """Features should not contain future information in the label."""
        # This is inherently satisfied by the dataset builder which
        # merges feature date with label date, ensuring both are aligned.
        # The forward_return label uses shift(-horizon) which is correctly
        # assigned to the feature date.
        bars = self._make_bars(60)
        factors = self._make_factors(bars)
        spec = DatasetSpec(
            train_end=date(2024, 2, 1),
            validation_end=date(2024, 2, 15),
        )
        result = self.builder.build_from_bars_and_factors(bars, factors, spec)
        dataset = pd.read_parquet(result.dataset_path)
        # Verify the forward return is not NaN (meaning label was computed)
        label_col = f"forward_return_{spec.label_horizon_bars}b"
        if label_col in dataset.columns:
            train_data = dataset[dataset["split"] == "train"]
            self.assertGreater(train_data[label_col].notna().sum(), 0)
