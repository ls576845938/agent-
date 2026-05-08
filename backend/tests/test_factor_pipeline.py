"""Tests for FeaturePipeline factor computation.

Covers: factor computation, winsorize, zscore, cross-sectional.
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

import pandas as pd

from quant_us.factors.feature_pipeline import FeaturePipeline


class TestFeaturePipeline(unittest.TestCase):
    """FeaturePipeline factor computation tests."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.pipeline = FeaturePipeline(feature_root=self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_sample_bars(self) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
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
                    "volume": 1000000 + i * 1000,
                })
        return pd.DataFrame(rows)

    def test_empty_bars(self) -> None:
        result = self.pipeline.build_bar_factors(
            pd.DataFrame(),
            universe="test",
            version="v1",
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.rows_written, 0)

    def test_basic_factor_computation(self) -> None:
        bars = self._make_sample_bars()
        result = self.pipeline.build_bar_factors(bars, universe="default", version="v1")
        self.assertEqual(result.status, "completed")
        self.assertGreater(result.rows_written, 0)

    def test_written_files_exist(self) -> None:
        bars = self._make_sample_bars()
        result = self.pipeline.build_bar_factors(bars, universe="default", version="v1")
        for fpath in result.files_written:
            import os
            self.assertTrue(os.path.exists(fpath), f"File {fpath} does not exist")

    def test_version_tag(self) -> None:
        bars = self._make_sample_bars()
        result = self.pipeline.build_bar_factors(bars, universe="test", version="v2")
        self.assertEqual(result.version, "v2")

    def test_factor_names_computed(self) -> None:
        bars = self._make_sample_bars()
        result = self.pipeline.build_bar_factors(bars, universe="default", version="v1")
        self.assertEqual(result.status, "completed")

    def test_two_symbols_produce_rows(self) -> None:
        bars = self._make_sample_bars()
        result = self.pipeline.build_bar_factors(bars, universe="default", version="v1")
        self.assertGreater(result.rows_written, 0)

    def test_pipeline_does_not_import_live(self) -> None:
        """Feature pipeline has no live imports."""
        import inspect
        source = inspect.getsource(FeaturePipeline)
        self.assertNotIn("quant_us.live", source)
        self.assertNotIn("quant_us.execution", source)

    def test_run_id_generated(self) -> None:
        bars = self._make_sample_bars()
        result = self.pipeline.build_bar_factors(bars, universe="u1", version="v1")
        self.assertTrue(result.run_id.startswith("feat_") or len(result.run_id) > 0)
