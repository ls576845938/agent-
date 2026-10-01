"""Tests for data_bridge.py edge cases — bars_from_dataframe, feature_map_from_frame, EventDrivenBacktestRunner."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant_us.backtest.data_bridge import (
    bars_from_dataframe,
    EventDrivenBacktestRunner,
    feature_map_from_frame,
)


class BarsFromDataFrameEdgeCases(unittest.TestCase):
    """Edge cases for bars_from_dataframe."""

    # ── Empty DataFrame ──────────────────────────────────────────────────

    def test_empty_dataframe_returns_empty_list(self):
        """Empty DataFrame with correct columns -> empty list."""
        frame = pd.DataFrame(columns=[
            "timestamp_utc", "symbol", "open", "high", "low", "close", "volume",
        ])
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 0)

    def test_empty_dataframe_no_columns_raises_key_error(self):
        """Totally empty DataFrame -> KeyError (no timestamp column)."""
        frame = pd.DataFrame()
        with self.assertRaises(KeyError):
            bars_from_dataframe(frame)

    # ── Missing required columns ─────────────────────────────────────────

    def test_missing_open_raises_key_error(self):
        """Missing 'open' column -> KeyError."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
        })
        with self.assertRaises(KeyError):
            bars_from_dataframe(frame)

    def test_missing_close_raises_key_error(self):
        """Missing 'close' column -> KeyError."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
        })
        with self.assertRaises(KeyError):
            bars_from_dataframe(frame)

    # ── Non-UTC timestamps ───────────────────────────────────────────────

    def test_non_utc_timezone_converted_to_utc(self):
        """US/Eastern timestamps are converted to UTC."""
        timestamps = pd.date_range(
            "2024-01-02T09:30:00", periods=3, freq="1min", tz="US/Eastern",
        )
        frame = pd.DataFrame({
            "timestamp_utc": timestamps,
            "symbol": "AAPL",
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 10_000,
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        for bar in bars:
            self.assertEqual(str(bar.timestamp_utc.tzinfo), "UTC")
        # US/Eastern 09:30 = UTC 14:30 (EST, no DST in Jan)
        self.assertEqual(bars[0].timestamp_utc.hour, 14)
        self.assertEqual(bars[0].timestamp_utc.minute, 30)

    def test_no_timezone_gets_utc_assigned(self):
        """Naive timestamps get UTC assigned (not converted, since they are already UTC-valued)."""
        timestamps = pd.date_range("2024-01-02T09:30:00", periods=2, freq="1min")
        frame = pd.DataFrame({
            "timestamp_utc": timestamps,
            "symbol": "AAPL",
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 2)
        for i, bar in enumerate(bars):
            self.assertIsNotNone(bar.timestamp_utc.tzinfo)
            self.assertEqual(str(bar.timestamp_utc.tzinfo), "UTC")
            self.assertEqual(bar.timestamp_utc.hour, 9)
            self.assertEqual(bar.timestamp_utc.minute, 30 + i)

    # ── NaN values in OHLCV ──────────────────────────────────────────────

    def test_nan_in_open_does_not_crash(self):
        """np.nan in 'open' column -> Bar created with nan, no crash."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [np.nan, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 2)
        self.assertTrue(np.isnan(bars[0].open))
        self.assertEqual(bars[1].open, 101.0)

    def test_all_ohlcv_nan_does_not_crash(self):
        """All OHLCV values are np.nan -> Bars created with nan, no crash."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=1, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [np.nan],
            "high": [np.nan],
            "low": [np.nan],
            "close": [np.nan],
            "volume": [np.nan],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 1)
        self.assertTrue(np.isnan(bars[0].open))
        self.assertTrue(np.isnan(bars[0].high))
        self.assertTrue(np.isnan(bars[0].low))
        self.assertTrue(np.isnan(bars[0].close))
        self.assertTrue(np.isnan(bars[0].volume))

    # ── Duplicate timestamps ─────────────────────────────────────────────

    def test_duplicate_timestamps_all_rows_returned(self):
        """Duplicate timestamps -> both rows are returned as separate Bars."""
        ts = pd.Timestamp("2024-01-02T09:30:00", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": [ts, ts],
            "symbol": ["AAPL", "AAPL"],
            "open": [100.0, 100.5],
            "high": [101.0, 101.5],
            "low": [99.0, 99.5],
            "close": [100.5, 101.0],
            "volume": [10_000, 11_000],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(
            len(bars), 2,
            "Both duplicate-timestamp rows should be returned",
        )
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[1].open, 100.5)

    # ── Single row ───────────────────────────────────────────────────────

    def test_single_row_returns_one_bar(self):
        """Single-row DataFrame -> one Bar returned with correct values."""
        frame = pd.DataFrame({
            "timestamp_utc": [pd.Timestamp("2024-01-02T09:30:00", tz="UTC")],
            "symbol": "AAPL",
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 10_000,
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].symbol, "AAPL")
        self.assertEqual(bars[0].open, 100.0)
        self.assertEqual(bars[0].high, 101.0)
        self.assertEqual(bars[0].low, 99.0)
        self.assertEqual(bars[0].close, 100.5)
        self.assertEqual(bars[0].volume, 10_000.0)

    # ── Column name fallback ─────────────────────────────────────────────

    def test_fallback_to_timestamp_column(self):
        """When 'timestamp_utc' is absent, fallback to 'timestamp' column."""
        frame = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
        })
        frame = frame.set_index("timestamp")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 2)
        for bar in bars:
            self.assertIsNotNone(bar.timestamp_utc.tzinfo)

    def test_missing_timestamp_column_raises_key_error(self):
        """When neither 'timestamp_utc' nor 'timestamp' exists -> KeyError."""
        frame = pd.DataFrame({
            "symbol": "AAPL",
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [10_000],
        })
        with self.assertRaises(KeyError):
            bars_from_dataframe(frame)

    # ── Pre-existing named DatetimeIndex ─────────────────────────────────

    def test_pre_existing_named_datetimeindex(self):
        """DataFrame with a named DatetimeIndex works correctly (skip column-to-index)."""
        index = pd.DatetimeIndex(
            pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            name="timestamp_utc",
        )
        frame = pd.DataFrame({
            "symbol": "AAPL",
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
        }, index=index)
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 2)
        for bar in bars:
            self.assertEqual(str(bar.timestamp_utc.tzinfo), "UTC")
        self.assertEqual(bars[0].symbol, "AAPL")
        self.assertEqual(bars[0].close, 100.5)

    # ── Optional columns (vwap, trade_count) ─────────────────────────────

    def test_vwap_and_trade_count_optional(self):
        """VWAP and trade_count columns are optional; result fields set to None."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertIsNone(bars[0].vwap)
        self.assertIsNone(bars[0].trade_count)

    def test_vwap_with_nan_sets_none(self):
        """VWAP column present but NaN -> vwap field set to None."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=1, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 10_000, "vwap": [np.nan],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertIsNone(bars[0].vwap)

    def test_trade_count_with_nan_sets_none(self):
        """trade_count column present but NaN -> trade_count field set to None."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=1, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 10_000, "trade_count": [np.nan],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertIsNone(bars[0].trade_count)

    # ── Source and session propagation ───────────────────────────────────

    def test_source_and_session_propagated(self):
        """source and session kwargs are propagated to each Bar."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=1, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 10_000,
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame, source="test_source", session="regular")
        self.assertEqual(bars[0].source, "test_source")
        self.assertEqual(bars[0].session, "regular")

    def test_adjusted_flag_propagated(self):
        """adjusted_flag column -> Bar.adjusted set correctly."""
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=2, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10_000, 11_000],
            "adjusted_flag": [True, False],
        })
        frame = frame.set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertTrue(bars[0].adjusted)
        self.assertFalse(bars[1].adjusted)


class FeatureMapFromFrameEdgeCases(unittest.TestCase):
    """Edge cases for the data_bridge.feature_map_from_frame wrapper."""

    def test_empty_frame_returns_empty_dict(self):
        """Empty DataFrame -> empty dict."""
        frame = pd.DataFrame()
        result = feature_map_from_frame(frame)
        self.assertEqual(result, {})

    def test_basic_feature_map(self):
        """Standard feature frame -> dict with naive-datetime keys."""
        frame = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["AAPL", "MSFT"],
            "factor_name": ["momentum", "momentum"],
            "factor_value": [0.5, 0.3],
        })
        result = feature_map_from_frame(frame)
        expected_date = datetime(2024, 1, 2)  # naive datetime (wrapper creates naive)
        self.assertIn(expected_date, result)
        self.assertIn("AAPL", result[expected_date])
        self.assertEqual(result[expected_date]["AAPL"]["momentum"], 0.5)
        self.assertEqual(result[expected_date]["MSFT"]["momentum"], 0.3)

    def test_nan_factor_value_skipped(self):
        """NaN factor_value -> row omitted from result."""
        frame = pd.DataFrame({
            "date": ["2024-01-02"],
            "symbol": ["AAPL"],
            "factor_name": ["momentum"],
            "factor_value": [np.nan],
        })
        result = feature_map_from_frame(frame)
        self.assertEqual(result, {})

    def test_fallback_to_value_column(self):
        """When 'factor_value' is absent, fallback to 'value' column."""
        frame = pd.DataFrame({
            "date": ["2024-01-02"],
            "symbol": ["AAPL"],
            "factor_name": ["momentum"],
            "value": [0.5],
        })
        result = feature_map_from_frame(frame)
        expected_date = datetime(2024, 1, 2)
        self.assertEqual(result[expected_date]["AAPL"]["momentum"], 0.5)

    def test_multi_factor_same_date(self):
        """Multiple factors for the same date and symbol -> merged correctly."""
        frame = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["AAPL", "AAPL"],
            "factor_name": ["momentum", "volatility"],
            "factor_value": [0.5, 0.2],
        })
        result = feature_map_from_frame(frame)
        expected_date = datetime(2024, 1, 2)
        self.assertEqual(result[expected_date]["AAPL"]["momentum"], 0.5)
        self.assertEqual(result[expected_date]["AAPL"]["volatility"], 0.2)


class EventDrivenBacktestRunnerEdgeCases(unittest.TestCase):
    """Edge cases for EventDrivenBacktestRunner.run_from_dataframe."""

    def test_empty_dataframe_no_crash(self):
        """Empty DataFrame -> no crash, trivial results."""
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        runner = EventDrivenBacktestRunner(strategies=[strategy])
        frame = pd.DataFrame(columns=[
            "timestamp_utc", "symbol", "open", "high", "low", "close", "volume",
        ])
        result = runner.run_from_dataframe(frame)
        self.assertEqual(len(result.snapshots), 0)
        self.assertEqual(len(result.fills), 0)
        self.assertEqual(len(result.orders), 0)
        self.assertEqual(result.summary["trade_count"], 0)

    def test_single_bar_no_crash(self):
        """Single-bar DataFrame -> completes with one snapshot, no trades."""
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        runner = EventDrivenBacktestRunner(strategies=[strategy])
        frame = pd.DataFrame({
            "timestamp_utc": [pd.Timestamp("2024-01-02T09:30:00", tz="UTC")],
            "symbol": "AAPL",
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 10_000,
        })
        frame = frame.set_index("timestamp_utc")
        result = runner.run_from_dataframe(frame)
        self.assertEqual(len(result.snapshots), 1)
        self.assertEqual(result.summary["trade_count"], 0)

    def test_empty_features_frame(self):
        """features_frame=None and features_frame=empty behave identically."""
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        runner = EventDrivenBacktestRunner(strategies=[strategy])
        frame = pd.DataFrame({
            "timestamp_utc": pd.date_range("2024-01-02", periods=5, freq="h", tz="UTC"),
            "symbol": "AAPL",
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.5] * 5,
            "volume": [10_000] * 5,
        })
        frame = frame.set_index("timestamp_utc")
        result_without = runner.run_from_dataframe(frame, features_frame=None)
        result_with_empty = runner.run_from_dataframe(frame, features_frame=pd.DataFrame())
        self.assertEqual(len(result_without.snapshots), 5)
        self.assertEqual(len(result_with_empty.snapshots), 5)

    def test_multi_symbol_no_crash(self):
        """run_from_dataframe_multi_symbol handles multi-symbol frame."""
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        strategy = MomentumStrategy(lookback_bars=5, entry_threshold=0.003)
        runner = EventDrivenBacktestRunner(strategies=[strategy])
        n = 10
        timestamps = pd.date_range("2024-01-02", periods=n, freq="h", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": timestamps,
            "symbol": "AAPL",
            "open": [100.0 + i * 0.5 for i in range(n)],
            "high": [101.0 + i * 0.5 for i in range(n)],
            "low": [99.0 + i * 0.5 for i in range(n)],
            "close": [100.5 + i * 0.5 for i in range(n)],
            "volume": [10_000] * n,
        })
        frame = frame.set_index("timestamp_utc")
        result = runner.run_from_dataframe_multi_symbol(frame)
        self.assertGreaterEqual(len(result.snapshots), 1)


if __name__ == "__main__":
    unittest.main()
