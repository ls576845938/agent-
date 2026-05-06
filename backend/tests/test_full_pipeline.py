"""Integration tests for the backtest stage of run_full_pipeline.py.

Exercises the same code path as the pipeline's Stage 2 (event-driven backtest)
using fixture data — no network calls, no real data downloads.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestResult, UnifiedBacktestRunner
from quant_us.strategies.momentum_strategy import MomentumStrategy


def _make_bars_frame(n: int = 120, symbol: str = "AAPL") -> pd.DataFrame:
    """Deterministic OHLCV DataFrame with upward trend for reliable signals.

    Follows the pattern from test_unified_backtest.py's _deterministic_bars()
    but returns a DataFrame (as the pipeline consumes) instead of Bar objects.
    """
    np.random.seed(42)
    dates = pd.date_range("2024-01-02", periods=n, freq="D", tz="UTC")
    price = 150.0
    rows: list[dict] = []
    for ts in dates:
        price = price * (1.0 + 0.002)  # ~0.2% per day
        noise = 1.0 + np.random.uniform(-0.005, 0.005)
        rows.append({
            "timestamp_utc": ts,
            "symbol": symbol,
            "open": price * 0.999 * noise,
            "high": price * 1.01 * noise,
            "low": price * 0.99 * noise,
            "close": price * noise,
            "volume": 15000.0,
        })
    return pd.DataFrame(rows)


class FullPipelineBacktestTests(unittest.TestCase):
    """Integration tests for the pipeline's backtest stage."""

    # ── helpers ──────────────────────────────────────────────────────

    def _default_strategy(self) -> MomentumStrategy:
        return MomentumStrategy(
            strategy_id="momentum_us",
            lookback_bars=10,
            entry_threshold=0.005,
            allow_short=False,
        )

    def _default_config(self) -> UnifiedBacktestConfig:
        return UnifiedBacktestConfig(
            initial_cash=100_000.0,
            commission_rate=0.0001,
            slippage_bps=1.0,
            fill_ratio=0.95,
        )

    # ── happy path ───────────────────────────────────────────────────

    def test_backtest_stage_returns_expected_keys(self):
        """Backtest with fixture data returns a UnifiedBacktestResult with
        the keys the pipeline reads from the result dict."""
        frame = _make_bars_frame(120)
        strategy = self._default_strategy()
        config = self._default_config()
        runner = UnifiedBacktestRunner(config=config)
        result = runner.run(
            strategies=[strategy],
            frame=frame,
            data_version="test_v1.0",
        )

        self.assertIsInstance(result, UnifiedBacktestResult)
        self.assertIsNotNone(result.run_id)
        self.assertGreater(len(result.run_id), 0)
        self.assertEqual(result.data_version, "test_v1.0")

        # The pipeline prints result.summary keys after run (line 105-106)
        summary = result.summary
        self.assertIn("sharpe_ratio", summary)
        self.assertIn("total_return_pct", summary)
        self.assertIn("max_drawdown_pct", summary)
        self.assertIn("trade_count", summary)

        # The pipeline reads result.run_id and result.summary.sharpe_ratio
        # into the results dict (lines 108-109)
        self.assertIsNotNone(result.run_id)
        # Verify the result dict keys the pipeline relies on
        pipeline_result_keys = {"data_version", "run_id", "sharpe_ratio"}
        available = set(summary.keys()) | {"data_version", "run_id"}
        self.assertTrue(
            pipeline_result_keys.issubset(available),
            f"Pipeline expected keys {pipeline_result_keys} should be present",
        )

    def test_backtest_stage_produces_trades(self):
        """Upward-trending fixture generates non-zero trades via momentum strategy."""
        frame = _make_bars_frame(120)
        strategy = self._default_strategy()
        runner = UnifiedBacktestRunner(config=self._default_config())
        result = runner.run(
            strategies=[strategy],
            frame=frame,
            data_version="test_v1.0",
        )

        msg = "Momentum strategy on upward trend should generate trades"
        self.assertGreater(result.summary["trade_count"], 0, msg)
        # Pipeline logs: summary keys, equity_consistent flag
        self.assertTrue(result.equity_consistent)

    def test_backtest_stage_data_version_propagated(self):
        """data_version flows through the runner and appears on the result."""
        frame = _make_bars_frame(60)
        runner = UnifiedBacktestRunner()
        result = runner.run(
            strategies=[self._default_strategy()],
            frame=frame,
            data_version="my_data_ver_42",
        )
        self.assertEqual(result.data_version, "my_data_ver_42")

    # ── edge cases ──────────────────────────────────────────────────

    def test_backtest_stage_empty_data(self):
        """Empty DataFrame handled gracefully — 0 trades, no crash."""
        frame = pd.DataFrame(columns=[
            "timestamp_utc", "symbol", "open", "high", "low", "close", "volume",
        ])
        runner = UnifiedBacktestRunner()
        result = runner.run(
            strategies=[MomentumStrategy()],
            frame=frame,
            data_version="empty",
        )

        self.assertIsInstance(result, UnifiedBacktestResult)
        self.assertEqual(result.summary["trade_count"], 0)
        self.assertEqual(result.summary["total_return_pct"], 0.0)
        self.assertEqual(result.summary["sharpe_ratio"], 0.0)
        self.assertEqual(len(result.fills), 0)
        self.assertTrue(result.equity_consistent)

    def test_backtest_stage_missing_param_raises(self):
        """Missing both frame and bars_override raises ValueError."""
        runner = UnifiedBacktestRunner()
        with self.assertRaises(ValueError) as ctx:
            runner.run(strategies=[MomentumStrategy()])
        self.assertIn("Either frame or bars_override", str(ctx.exception))

    def test_backtest_stage_single_bar_no_signal(self):
        """Single bar cannot generate a signal (need > lookback_bars)."""
        frame = _make_bars_frame(5)  # too few bars for lookback_bars=10
        runner = UnifiedBacktestRunner()
        result = runner.run(
            strategies=[self._default_strategy()],
            frame=frame,
            data_version="too_few_bars",
        )
        self.assertEqual(result.summary["trade_count"], 0)

    # ── parquet round-trip ──────────────────────────────────────────

    def test_backtest_stage_with_parquet_roundtrip(self):
        """Write fixture to parquet, read back (mimicking pipeline Stage 2),
        run backtest — verifies the parquet-load-and-concat path works."""
        source, interval, symbol = "yfinance", "1d", "AAPL"
        frame = _make_bars_frame(120, symbol=symbol)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Build the hive-style directory tree the pipeline expects
            parquet_dir = (
                Path(tmpdir)
                / "raw"
                / f"vendor={source}"
                / "asset_class=equity"
                / f"bar_size={interval}"
                / f"symbol={symbol}"
            )
            parquet_dir.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(parquet_dir / "date=2024-01-01.parquet")

            # Reload as the pipeline does (lines 79-86)
            loaded_frames: list[pd.DataFrame] = []
            for pq in sorted(parquet_dir.glob("date=*.parquet")):
                loaded_frames.append(pd.read_parquet(pq))
            loaded = pd.concat(loaded_frames, ignore_index=True)

        self.assertEqual(len(loaded), len(frame))

        runner = UnifiedBacktestRunner()
        result = runner.run(
            strategies=[self._default_strategy()],
            frame=loaded,
            data_version="parquet_v1",
        )

        self.assertIsInstance(result, UnifiedBacktestResult)
        self.assertEqual(result.data_version, "parquet_v1")
        self.assertGreater(result.summary["trade_count"], 0)
        # Keys the pipeline reads from result (lines 105-109)
        self.assertIn("sharpe_ratio", result.summary)
        self.assertIsNotNone(result.run_id)

    def test_backtest_stage_parquet_empty_file(self):
        """Parquet file with no rows is handled gracefully."""
        empty_frame = pd.DataFrame(columns=[
            "timestamp_utc", "symbol", "open", "high", "low", "close", "volume",
        ])
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "empty.parquet"
            empty_frame.to_parquet(path)

            loaded = pd.read_parquet(path)
            runner = UnifiedBacktestRunner()
            result = runner.run(
                strategies=[MomentumStrategy()],
                frame=loaded,
                data_version="empty_parquet",
            )

        self.assertEqual(result.summary["trade_count"], 0)
        self.assertTrue(result.equity_consistent)


if __name__ == "__main__":
    unittest.main()
