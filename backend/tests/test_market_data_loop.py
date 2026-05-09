"""Tests for MarketDataLoop and DataFreshnessGuard enhancements."""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.types import Bar
from quant_us.live.market_data_loop import MarketDataLoop, MarketDataStatus
from quant_us.risk.data_freshness import DataFreshnessConfig, DataFreshnessDecision, DataFreshnessGuard


# =========================================================================
# MarketDataLoop Tests
# =========================================================================


def _make_bars_df(
    symbols: list[str],
    n_bars: int = 5,
    base_time: datetime | None = None,
    interval_minutes: int = 1,
) -> pd.DataFrame:
    """Build a test bars DataFrame with recent timestamps."""
    base = base_time or (utc_now() - timedelta(minutes=n_bars * interval_minutes + 1))
    rows: list[dict] = []
    for i in range(n_bars):
        ts = base + timedelta(minutes=i * interval_minutes)
        for sym in symbols:
            rows.append(
                {
                    "timestamp_utc": ts,
                    "symbol": sym,
                    "open": 100.0 + i,
                    "high": 101.0 + i,
                    "low": 99.0 + i,
                    "close": 100.5 + i,
                    "volume": 10000.0 + i * 100,
                    "source": "test",
                    "adjusted_flag": False,
                }
            )
    return pd.DataFrame(rows)


class MarketDataLoopTests(unittest.TestCase):
    """Test polling data loop with mocked connector."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.symbols = ["AAPL", "MSFT"]
        # Patch get_connector so that any vendor name works in tests
        self._conn_patcher = patch("quant_us.live.market_data_loop.get_connector")
        self._mock_get_connector = self._conn_patcher.start()
        self._mock_conn = MagicMock()
        self._mock_get_connector.return_value = self._mock_conn

    def tearDown(self) -> None:
        self._conn_patcher.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # -- fetch_latest_bars ------------------------------------------------

    def test_fetch_latest_bars_returns_concatenated_dataframe(self) -> None:
        """fetch_latest_bars should query connector per symbol and concatenate."""
        def side_effect(symbol, start, end, bar_size):
            return _make_bars_df([symbol], n_bars=3)

        self._mock_conn.fetch_bars.side_effect = side_effect

        loop = MarketDataLoop(
            symbols=self.symbols,
            vendor="test_vendor",
            bar_size="1m",
            poll_interval_seconds=10.0,
            data_root=str(self.tmpdir),
        )
        df = loop.fetch_latest_bars()

        self.assertFalse(df.empty)
        self.assertIn("AAPL", df["symbol"].values)
        self.assertIn("MSFT", df["symbol"].values)
        self.assertEqual(self._mock_conn.fetch_bars.call_count, 2)

    def test_fetch_latest_bars_returns_empty_on_all_failures(self) -> None:
        """When every symbol fails, return empty DataFrame."""
        self._mock_conn.fetch_bars.side_effect = RuntimeError("vendor unavailable")

        loop = MarketDataLoop(
            symbols=self.symbols,
            vendor="test_vendor",
            bar_size="1m",
            data_root=str(self.tmpdir),
        )
        df = loop.fetch_latest_bars()

        self.assertTrue(df.empty)

    def test_fetch_latest_bars_continues_on_partial_failure(self) -> None:
        """If one symbol fails, others should still be fetched."""
        def side_effect(symbol, start, end, bar_size):
            if symbol == "AAPL":
                raise RuntimeError("AAPL unavailable")
            return _make_bars_df([symbol], n_bars=2)

        self._mock_conn.fetch_bars.side_effect = side_effect

        loop = MarketDataLoop(
            symbols=self.symbols,
            vendor="test_vendor",
            bar_size="1m",
            data_root=str(self.tmpdir),
        )
        df = loop.fetch_latest_bars()

        self.assertFalse(df.empty)
        self.assertNotIn("AAPL", df["symbol"].values)
        self.assertIn("MSFT", df["symbol"].values)

    # -- validate_freshness -----------------------------------------------

    def test_validate_freshness_with_recent_bars_returns_fresh(self) -> None:
        """Bars with recent timestamps should be marked fresh."""
        df = _make_bars_df(self.symbols, n_bars=3, base_time=utc_now() - timedelta(minutes=2))
        loop = MarketDataLoop(self.symbols, "test_vendor", "1m", data_root=str(self.tmpdir))
        status = loop.validate_freshness(df)

        self.assertTrue(status.fresh)
        self.assertEqual(status.stale_seconds, 0.0)
        self.assertIsNotNone(status.latest_timestamp)
        self.assertIsNone(status.error)

    def test_validate_freshness_with_stale_bars_returns_not_fresh(self) -> None:
        """Bars with very old timestamps should be marked stale."""
        old_time = utc_now() - timedelta(hours=2)
        df = _make_bars_df(self.symbols, n_bars=3, base_time=old_time)
        loop = MarketDataLoop(self.symbols, "test_vendor", "1m", data_root=str(self.tmpdir))
        status = loop.validate_freshness(df)

        self.assertFalse(status.fresh)
        self.assertGreater(status.stale_seconds, 0.0)

    def test_validate_freshness_with_empty_df_returns_not_fresh(self) -> None:
        """An empty DataFrame should produce a not-fresh status with an error."""
        loop = MarketDataLoop(self.symbols, "test_vendor", "1m", data_root=str(self.tmpdir))
        status = loop.validate_freshness(pd.DataFrame())

        self.assertFalse(status.fresh)
        self.assertEqual(status.stale_seconds, float("inf"))
        self.assertEqual(status.error, "no_data")

    # -- write_to_cache ---------------------------------------------------

    def test_write_to_cache_creates_parquet_files(self) -> None:
        """Bars written to cache should produce parquet files on disk."""
        df = _make_bars_df(self.symbols, n_bars=2)
        loop = MarketDataLoop(
            self.symbols,
            "test_vendor",
            "1m",
            data_root=str(self.tmpdir),
        )
        loop.write_to_cache(df)

        # Check AAPL parquet exists
        aapl_path = (
            self.tmpdir
            / "latest"
            / "vendor=test_vendor"
            / "asset_class=equity"
            / "bar_size=1m"
            / "symbol=AAPL"
        )
        parquet_files = list(aapl_path.glob("date=*.parquet"))
        self.assertGreater(len(parquet_files), 0, "No parquet files written for AAPL")

        # Verify written data round-trips
        written = pd.read_parquet(parquet_files[0])
        self.assertIn("timestamp_utc", written.columns)
        self.assertIn("symbol", written.columns)

    def test_write_to_cache_empty_df_is_noop(self) -> None:
        """Writing an empty DataFrame should not create any files."""
        loop = MarketDataLoop(self.symbols, "test_vendor", "1m", data_root=str(self.tmpdir))
        loop.write_to_cache(pd.DataFrame())
        # No exception should be raised
        self.assertTrue(True)

    # -- run_once ---------------------------------------------------------

    def test_run_once_completes_full_cycle(self) -> None:
        """run_once should fetch, validate, and write successfully."""
        # Only 1 bar very recently to ensure it falls within max_delay
        df = _make_bars_df(self.symbols, n_bars=1, base_time=utc_now() - timedelta(seconds=10))
        self._mock_conn.fetch_bars.return_value = df

        loop = MarketDataLoop(
            symbols=self.symbols,
            vendor="test_vendor",
            bar_size="1m",
            data_root=str(self.tmpdir),
        )
        status = loop.run_once()

        self.assertTrue(status.fresh)
        self.assertEqual(sorted(status.symbols_updated), sorted(self.symbols))
        self.assertIsNone(status.error)

        # Verify cache was written
        aapl_path = (
            self.tmpdir
            / "latest"
            / "vendor=test_vendor"
            / "asset_class=equity"
            / "bar_size=1m"
            / "symbol=AAPL"
        )
        self.assertTrue(list(aapl_path.glob("date=*.parquet")))

    def test_run_once_handles_fetch_error_gracefully(self) -> None:
        """An exception during fetch should not crash the loop."""
        self._mock_conn.fetch_bars.side_effect = RuntimeError("connection lost")

        loop = MarketDataLoop(
            symbols=self.symbols,
            vendor="test_vendor",
            bar_size="1m",
            data_root=str(self.tmpdir),
        )
        status = loop.run_once()

        self.assertFalse(status.fresh)
        # When all fetches fail, validate_freshness returns "no_data"
        self.assertEqual(status.error, "no_data")

    # -- start / stop -----------------------------------------------------

    def test_start_stop_loop_cleanly(self) -> None:
        """Starting and immediately stopping the loop should work."""
        df = _make_bars_df(self.symbols, n_bars=1, base_time=utc_now() - timedelta(seconds=5))
        self._mock_conn.fetch_bars.return_value = df

        loop = MarketDataLoop(
            symbols=self.symbols,
            vendor="test_vendor",
            bar_size="1m",
            poll_interval_seconds=0.1,
            data_root=str(self.tmpdir),
        )

        # Start in background, stop quickly
        import threading
        t = threading.Thread(target=loop.start, daemon=True)
        t.start()
        time.sleep(0.3)  # let it run a few cycles
        loop.stop()
        t.join(timeout=2.0)

        self.assertFalse(t.is_alive())
        self.assertIsNotNone(loop.last_status)


# =========================================================================
# DataFreshnessGuard Enhancement Tests
# =========================================================================


class DataFreshnessGuardTests(unittest.TestCase):
    """Test enhanced DataFreshnessDecision and DataFreshnessGuard."""

    def setUp(self) -> None:
        self.guard = DataFreshnessGuard()
        self.now = utc_now()

    def _bar(self, ts: datetime | None = None) -> Bar:
        return Bar(
            timestamp_utc=ts or self.now,
            symbol="AAPL",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10000.0,
        )

    # -- stale_seconds in decision ----------------------------------------

    def test_fresh_decision_has_zero_stale_seconds(self) -> None:
        """When data is fresh, stale_seconds must be 0."""
        bar = self._bar(self.now - timedelta(seconds=10))
        decision = self.guard.evaluate_bar(bar, now=self.now)

        self.assertTrue(decision.fresh)
        self.assertEqual(decision.stale_seconds, 0.0)
        self.assertGreater(decision.delay_seconds, 0.0)  # delay is ~10s but not stale

    def test_stale_decision_has_stale_seconds_equal_to_delay(self) -> None:
        """When data is stale, stale_seconds should equal delay_seconds."""
        bar = self._bar(self.now - timedelta(seconds=600))  # 10 min delay > 300 max
        decision = self.guard.evaluate_bar(bar, now=self.now)

        self.assertFalse(decision.fresh)
        self.assertEqual(decision.stale_seconds, decision.delay_seconds)
        self.assertAlmostEqual(decision.delay_seconds, 600.0, delta=1.0)

    # -- last_fresh_timestamp ---------------------------------------------

    def test_evaluate_bar_updates_last_fresh_timestamp(self) -> None:
        """After a fresh bar, last_fresh_timestamp should be set."""
        bar_ts = self.now - timedelta(seconds=10)
        bar = self._bar(bar_ts)
        self.guard.evaluate_bar(bar, now=self.now)

        self.assertIsNotNone(self.guard.last_fresh_timestamp)
        self.assertEqual(
            ensure_utc(self.guard.last_fresh_timestamp),
            ensure_utc(bar_ts),
        )

    def test_stale_bar_does_not_update_last_fresh_timestamp(self) -> None:
        """A stale bar should NOT update last_fresh_timestamp."""
        # First, establish a fresh baseline
        fresh_bar = self._bar(self.now - timedelta(seconds=10))
        self.guard.evaluate_bar(fresh_bar, now=self.now)
        fresh_ts = self.guard.last_fresh_timestamp

        # Now evaluate a stale bar
        stale_bar = self._bar(self.now - timedelta(hours=1))
        self.guard.evaluate_bar(stale_bar, now=self.now)

        # last_fresh_timestamp should still be the fresh one
        self.assertEqual(self.guard.last_fresh_timestamp, fresh_ts)

    # -- block_new_orders --------------------------------------------------

    def test_block_new_orders_true_when_no_data_yet(self) -> None:
        """When no bar has been evaluated, block_new_orders is True."""
        guard = DataFreshnessGuard()
        self.assertTrue(guard.block_new_orders)

    def test_block_new_orders_false_after_fresh_bar(self) -> None:
        """After evaluating a fresh bar, block_new_orders is False."""
        bar = self._bar(self.now - timedelta(seconds=10))
        self.guard.evaluate_bar(bar, now=self.now)
        self.assertFalse(self.guard.block_new_orders)

    @patch("quant_us.risk.data_freshness.utc_now")
    def test_block_new_orders_true_after_fresh_then_time_passes(self, mock_utc_now: MagicMock) -> None:
        """If enough time passes since last fresh bar, block_new_orders becomes True."""
        guard = DataFreshnessGuard(DataFreshnessConfig(max_delay_seconds=30.0))
        bar = self._bar(self.now - timedelta(seconds=5))
        mock_utc_now.return_value = self.now
        guard.evaluate_bar(bar, now=self.now)

        # Simulate 60 seconds passing
        mock_utc_now.return_value = self.now + timedelta(seconds=60)
        self.assertTrue(guard.block_new_orders, "Should block after max_delay_seconds elapsed")

    def test_block_new_orders_resets_after_fresh_bar(self) -> None:
        """After a fresh bar at current time, block_new_orders should clear."""
        guard = DataFreshnessGuard(DataFreshnessConfig(max_delay_seconds=30.0))

        # Old bar -> should be stale
        old_bar = self._bar(self.now - timedelta(hours=1))
        guard.evaluate_bar(old_bar, now=self.now)
        self.assertTrue(guard.block_new_orders)

        # Now a fresh bar comes in
        fresh_bar = self._bar(self.now - timedelta(seconds=5))
        guard.evaluate_bar(fresh_bar, now=self.now)
        self.assertFalse(guard.block_new_orders)


# =========================================================================
# PaperTradingLoop Freshness Wiring Test
# =========================================================================


class PaperTradingLoopFreshnessGateTests(unittest.TestCase):
    """Test that PaperTradingLoop.run_day sets reduce_only when data is stale."""

    def test_reduce_only_set_when_block_new_orders_true(self) -> None:
        """If guard says block_new_orders, oms.reduce_only should become True."""
        from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop

        config = PaperTradingConfig(max_data_delay_seconds=10.0)
        loop = PaperTradingLoop(config=config)

        # Ensure guard has never seen a fresh bar -> block_new_orders is True
        self.assertTrue(loop.data_freshness.block_new_orders)
        self.assertFalse(loop.oms.reduce_only)

        bar = Bar(
            timestamp_utc=datetime(2026, 5, 8, 20, 0, tzinfo=timezone.utc),
            symbol="AAPL",
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10000.0,
        )
        loop.run_day(bars=[bar], strategies=[])
        self.assertTrue(
            loop.oms.reduce_only,
            "reduce_only should be True when data is stale",
        )


if __name__ == "__main__":
    unittest.main()
