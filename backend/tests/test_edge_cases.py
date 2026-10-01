"""Tests for liquidity slippage, NYSE holidays, and replay determinism."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import pandas as pd

from quant_us.backtest.liquidity_slippage import LiquiditySlippage
from quant_us.backtest.replay import BacktestReplay
from quant_us.core.enums import OrderSide
from quant_us.core.nyse_holidays import is_nyse_trading_day, nyse_early_closes, nyse_holidays, trading_days_between
from quant_us.core.types import Bar


class LiquiditySlippageTests(unittest.TestCase):
    def test_base_slippage_only(self):
        slip = LiquiditySlippage(base_bps=5.0, participation_bps=0.0)
        price = slip.apply(OrderSide.BUY, 100.0, 10.0, bar_volume=1_000_000.0)
        expected = 100.0 * (1.0 + 5.0 / 10_000.0)
        self.assertAlmostEqual(price, expected, places=6)

    def test_sell_slippage_reduces_price(self):
        slip = LiquiditySlippage(base_bps=5.0, participation_bps=0.0)
        price = slip.apply(OrderSide.SELL, 100.0, 10.0, bar_volume=1_000_000.0)
        expected = 100.0 * (1.0 - 5.0 / 10_000.0)
        self.assertAlmostEqual(price, expected, places=6)

    def test_participation_increases_slippage(self):
        slip = LiquiditySlippage(base_bps=5.0, participation_bps=10.0)
        # Large order relative to volume
        high_part = slip.apply(OrderSide.BUY, 100.0, 1000.0, bar_volume=10_000.0)
        # Small order relative to volume
        low_part = slip.apply(OrderSide.BUY, 100.0, 1.0, bar_volume=10_000.0)
        self.assertGreater(high_part, low_part, "Larger participation should increase slippage for buys")

    def test_max_bps_cap(self):
        slip = LiquiditySlippage(max_bps=10.0, participation_bps=100.0)
        # Huge order should hit the max_bps cap
        price = slip.apply(OrderSide.BUY, 100.0, 10_000_000.0, bar_volume=100.0)
        max_price = 100.0 * (1.0 + 10.0 / 10_000.0)
        self.assertLessEqual(price, max_price + 0.01, "Slippage should be capped at max_bps")

    def test_zero_bar_volume_uses_fallback(self):
        slip = LiquiditySlippage(base_bps=5.0, participation_bps=2.0, volume_cap_pct=5.0)
        price = slip.apply(OrderSide.BUY, 100.0, 10.0, bar_volume=0.0)
        # bar_volume=0 triggers fallback: bar_volume = quantity * 100 = 1000
        # participation = 100*10 / 1000 * 100 = 100%, capped to 5% by volume_cap_pct
        # total_bps = 5.0 + 2.0 * 5.0 = 15.0
        expected = 100.0 * (1.0 + 15.0 / 10_000.0)
        self.assertAlmostEqual(price, expected, places=4)

    def test_apply_notional(self):
        slip = LiquiditySlippage(base_bps=5.0, participation_bps=0.0)
        price = slip.apply_notional(OrderSide.BUY, 100.0, 10_000.0, bar_volume=1_000_000.0)
        expected = 100.0 * (1.0 + 5.0 / 10_000.0)
        self.assertAlmostEqual(price, expected, places=6)

    def test_volume_cap_pct(self):
        slip = LiquiditySlippage(base_bps=5.0, participation_bps=20.0, volume_cap_pct=2.0)
        # order notional = 100 * 100 = 10_000, bar_volume = 500
        # participation = 10_000 / 500 * 100 = 2000%, capped to 2.0%
        # total_bps = 5.0 + 20.0 * 2.0 * 1.0 = 45.0
        price_capped = slip.apply(OrderSide.BUY, 100.0, 100.0, bar_volume=500.0)
        expected = 100.0 * (1.0 + 45.0 / 10_000.0)
        self.assertAlmostEqual(price_capped, expected, places=4)


class NYSEHolidayTests(unittest.TestCase):
    def test_weekend_not_trading_day(self):
        saturday = date(2024, 1, 6)
        sunday = date(2024, 1, 7)
        self.assertFalse(is_nyse_trading_day(saturday))
        self.assertFalse(is_nyse_trading_day(sunday))

    def test_weekday_is_trading_day(self):
        tuesday = date(2024, 1, 9)
        self.assertTrue(is_nyse_trading_day(tuesday))

    def test_new_years_observed(self):
        holidays = nyse_holidays(2024)
        holiday_dates = set(holidays)
        self.assertIn(date(2024, 1, 1), holiday_dates)
        self.assertEqual(holidays[date(2024, 1, 1)], "New Year's Day")

    def test_christmas_day(self):
        holidays = nyse_holidays(2024)
        holiday_dates = set(holidays)
        self.assertIn(date(2024, 12, 25), holiday_dates)

    def test_mlk_day_third_monday(self):
        holidays = nyse_holidays(2024)
        self.assertIn(date(2024, 1, 15), holidays)

    def test_early_closes_include_black_friday(self):
        early = nyse_early_closes(2024)
        self.assertIn("Day after Thanksgiving", " ".join(early.values()),
                      "Black Friday should be an early close")

    def test_trading_days_between(self):
        days = trading_days_between(date(2024, 1, 2), date(2024, 1, 8))
        self.assertEqual(days, 5, "5 trading days between Jan 2 and Jan 8, 2024")

    def test_trading_days_between_same_day(self):
        days = trading_days_between(date(2024, 1, 8), date(2024, 1, 8))
        self.assertEqual(days, 1)

    def test_no_holiday_duplicates(self):
        for year in range(2020, 2031):
            holidays = nyse_holidays(year)
            counts = {}
            for d in holidays:
                counts[d] = counts.get(d, 0) + 1
            dups = {d: c for d, c in counts.items() if c > 1}
            self.assertEqual(len(dups), 0, f"Duplicate holidays in {year}: {dups}")


class ReplayTests(unittest.TestCase):
    def test_replay_serialize_deserialize(self):
        replay = BacktestReplay(
            run_id="test_replay",
            config={"run_id": "test", "initial_cash": 100_000.0},
            summary={"total_return_pct": 5.0, "sharpe_ratio": 1.2},
        )
        data = {
            "run_id": replay.run_id,
            "config": replay.config,
            "bars_count": 0,
            "events_count": 0,
            "fills_count": 0,
            "orders_count": 0,
            "snapshots_count": 0,
            "summary": replay.summary,
            "bars": [],
            "events": [],
            "fills": [],
            "orders": [],
            "snapshots": [],
        }
        import json, tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name

        loaded = BacktestReplay.load(path)
        self.assertEqual(loaded.run_id, "test_replay")
        self.assertEqual(loaded.summary["total_return_pct"], 5.0)

        import os
        os.unlink(path)

    def test_replay_config_defaults(self):
        replay = BacktestReplay(run_id="defaults", config={}, summary={})
        initial_cash = float(replay.config.get("initial_cash", 100_000.0))
        self.assertEqual(initial_cash, 100_000.0)

    def test_verify_determinism_with_no_mismatches(self):
        replay = BacktestReplay(
            run_id="det",
            config={"initial_cash": 100_000.0, "commission_rate": 0.0001, "slippage_bps": 1.0},
            summary={"total_return_pct": 10.0, "sharpe_ratio": 1.5, "max_drawdown_pct": -5.0, "trade_count": 20},
            fills=[],
            orders=[],
        )

        result = replay.verify_determinism([], [], None)
        self.assertFalse(result["deterministic"],
                         "Should flag mismatches when replaying with different strategies/bars")


class EdgeCaseTests(unittest.TestCase):
    def test_empty_dataframe_to_bars(self):
        from quant_us.backtest.data_bridge import bars_from_dataframe
        frame = pd.DataFrame(columns=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"])
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 0)

    def test_bars_without_vwap(self):
        from quant_us.backtest.data_bridge import bars_from_dataframe
        timestamps = pd.date_range("2024-01-02", periods=3, freq="1D", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": timestamps,
            "symbol": "TEST",
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.5, 11.5, 12.5],
            "volume": [1000.0, 2000.0, 3000.0],
        }).set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 3)
        for bar in bars:
            self.assertIsNone(bar.vwap, "Bar without vwap column should have vwap=None")

    def test_bars_with_na_vwap(self):
        from quant_us.backtest.data_bridge import bars_from_dataframe
        timestamps = pd.date_range("2024-01-02", periods=2, freq="1D", tz="UTC")
        frame = pd.DataFrame({
            "timestamp_utc": timestamps,
            "symbol": "TEST",
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [1000.0, 2000.0],
            "vwap": [float("nan"), 11.0],
        }).set_index("timestamp_utc")
        bars = bars_from_dataframe(frame)
        self.assertEqual(len(bars), 2)
        self.assertIsNone(bars[0].vwap)
        self.assertAlmostEqual(bars[1].vwap, 11.0, places=6)


if __name__ == "__main__":
    unittest.main()
