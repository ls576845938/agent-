"""Tests for quant_us.factors.feature_pipeline.FeaturePipeline.

Exercises FeaturePipeline.build_bar_factors with synthetic OHLCV data,
covering empty input, normal flow, multi-symbol, output structure,
factor value ranges, insufficient data, mock-verified store writes,
and exception handling.
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant_us.data.storage.feature_store import FeatureWriteResult
from quant_us.factors.feature_pipeline import FeaturePipeline, FeatureBuildResult


def _make_bars(
    n: int = 60,
    symbols: list[str] | None = None,
    seed: int = 42,
    drift: float = 0.001,
) -> pd.DataFrame:
    """Deterministic OHLCV DataFrame for testing.

    Parameters
    ----------
    n : int
        Number of daily bars per symbol.
    symbols : list[str] | None
        Symbol list (default ["AAPL"]).
    seed : int
        Random seed for reproducibility.
    drift : float
        Daily drift applied to price (e.g. 0.001 = 0.1 % / day).

    Returns
    -------
    pd.DataFrame
        Columns: timestamp_utc, symbol, open, high, low, close, volume.
    """
    if symbols is None:
        symbols = ["AAPL"]
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rows: list[dict] = []
    for symbol in symbols:
        price = 150.0
        for ts in dates:
            price *= 1.0 + drift + rng.uniform(-0.015, 0.015)
            rows.append(
                {
                    "timestamp_utc": ts,
                    "symbol": symbol,
                    "open": round(price * 0.998, 2),
                    "high": round(price * 1.005, 2),
                    "low": round(price * 0.995, 2),
                    "close": round(price, 2),
                    "volume": round(1_000_000.0 + rng.uniform(-50_000, 50_000), 0),
                }
            )
    return pd.DataFrame(rows)


class TestFeaturePipeline(unittest.TestCase):
    """Tests for FeaturePipeline.build_bar_factors."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.feature_root = self.tmpdir.name
        self.pipeline = FeaturePipeline(self.feature_root)

    def tearDown(self):
        self.tmpdir.cleanup()

    # -------------------------------------------------------------------
    # Tests
    # -------------------------------------------------------------------

    def test_build_bar_factors_empty_bars(self) -> None:
        """Empty DataFrame returns completed status with 0 rows."""
        result = self.pipeline.build_bar_factors(pd.DataFrame())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_written, 0)
        self.assertEqual(result.files_written, [])

    def test_build_bar_factors_normal_flow(self) -> None:
        """60 bars for 1 symbol yields completed status with rows > 0."""
        bars = _make_bars(n=60)
        result = self.pipeline.build_bar_factors(bars)
        self.assertEqual(result.status, "completed")
        self.assertGreater(result.rows_written, 0)
        self.assertGreater(len(result.files_written), 0)

        # Stored data has expected factor names
        for fname in ("realized_vol_20", "average_dollar_volume_20"):
            stored = self.pipeline.store.read_factor_values(fname, "v1")
            self.assertFalse(stored.empty, msg=f"factor {fname} missing from store")

    def test_build_bar_factors_multi_symbol(self) -> None:
        """2 symbols -- factors computed independently per symbol."""
        bars = _make_bars(n=120, symbols=["AAPL", "MSFT"])
        result = self.pipeline.build_bar_factors(bars)
        self.assertEqual(result.status, "completed")
        self.assertGreater(result.rows_written, 0)

        # Both symbols present in stored data
        stored = pd.concat(
            [
                self.pipeline.store.read_factor_values("momentum_score", "v1"),
                self.pipeline.store.read_factor_values("realized_vol_20", "v1"),
                self.pipeline.store.read_factor_values("average_dollar_volume_20", "v1"),
            ],
            ignore_index=True,
        )
        symbols_in_store = stored["symbol"].unique()
        self.assertIn("AAPL", symbols_in_store)
        self.assertIn("MSFT", symbols_in_store)

        # Both symbols have values
        aapl_count = (stored["symbol"] == "AAPL").sum()
        msft_count = (stored["symbol"] == "MSFT").sum()
        self.assertGreater(aapl_count, 0)
        self.assertGreater(msft_count, 0)

    def test_build_bar_factors_output_structure(self) -> None:
        """FeatureBuildResult has expected fields."""
        bars = _make_bars(n=120)
        result = self.pipeline.build_bar_factors(bars)
        self.assertEqual(result.status, "completed")
        self.assertIsInstance(result.rows_written, int)
        self.assertIsInstance(result.files_written, list)
        self.assertGreater(result.rows_written, 0)
        self.assertTrue(all(isinstance(f, str) for f in result.files_written))
        self.assertIsInstance(result.version, str)
        self.assertIsInstance(result.created_at, datetime)
        self.assertIsNone(result.error)

    def test_build_bar_factors_factor_values_range(self) -> None:
        """momentum_score in [-1, 1], realized_vol > 0, adv > 0."""
        bars = _make_bars(n=120, seed=42, drift=0.001)
        result = self.pipeline.build_bar_factors(bars, version="v_range")
        self.assertEqual(result.status, "completed")

        # Read back all factors
        stored = pd.concat(
            [
                self.pipeline.store.read_factor_values("momentum_score", "v_range"),
                self.pipeline.store.read_factor_values("realized_vol_20", "v_range"),
                self.pipeline.store.read_factor_values("average_dollar_volume_20", "v_range"),
            ],
            ignore_index=True,
        )

        self.assertIn("momentum_score", stored["factor_name"].values)
        self.assertIn("realized_vol_20", stored["factor_name"].values)
        self.assertIn("average_dollar_volume_20", stored["factor_name"].values)

        for fname in ("momentum_score", "realized_vol_20", "average_dollar_volume_20"):
            subset = stored[stored["factor_name"] == fname]
            self.assertFalse(subset.empty, msg=f"no rows for {fname}")
            vals = subset["factor_value"]

            if fname == "momentum_score":
                self.assertTrue(
                    (vals.abs() <= 1.0).all(),
                    f"momentum_score out of range: min={vals.min():.4f}, max={vals.max():.4f}",
                )
            elif fname == "realized_vol_20":
                self.assertTrue(
                    (vals > 0).all(),
                    f"realized_vol has non-positive values: min={vals.min():.6f}",
                )
            elif fname == "average_dollar_volume_20":
                self.assertTrue(
                    (vals > 0).all(),
                    f"adv has non-positive values: min={vals.min():.2f}",
                )

    def test_build_bar_factors_insufficient_data(self) -> None:
        """< 60 bars: momentum_score all NaN -> rows skipped, pipeline completes."""
        bars = _make_bars(n=59)
        result = self.pipeline.build_bar_factors(bars)

        self.assertEqual(result.status, "completed")
        self.assertGreater(result.rows_written, 0)

        # momentum_score has no rows (all NaN due to long_window=60)
        momentum = self.pipeline.store.read_factor_values("momentum_score", "v1")
        self.assertTrue(momentum.empty)

    def test_build_bar_factors_writes_to_store(self) -> None:
        """ParquetFeatureStore.write_factor_values is called during build."""
        bars = _make_bars(n=120)
        with patch.object(self.pipeline.store, "write_factor_values") as mock_write:
            mock_write.return_value = FeatureWriteResult(
                rows_written=999,
                files_written=[Path("dummy.parquet")],
            )
            result = self.pipeline.build_bar_factors(bars, version="v_mock")

        mock_write.assert_called_once()
        call_args, call_kwargs = mock_write.call_args
        self.assertIsInstance(call_args[0], pd.DataFrame)
        self.assertEqual(call_kwargs.get("version"), "v_mock")

        # Result reflects mocked write result
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_written, 999)

    def test_build_bar_factors_exception_handling(self) -> None:
        """Store exception returns failed status with error message."""
        bars = _make_bars(n=120)
        with patch.object(self.pipeline.store, "write_factor_values") as mock_write:
            mock_write.side_effect = RuntimeError("disk full")
            result = self.pipeline.build_bar_factors(bars)

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.error)
        self.assertIn("disk full", result.error)
        self.assertEqual(result.rows_written, 0)


if __name__ == "__main__":
    unittest.main()
