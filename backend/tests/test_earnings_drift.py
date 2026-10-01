"""Tests for EarningsDriftStrategy."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import pandas as pd

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.core.enums import SignalDirection
from quant_us.core.types import Bar
from quant_us.strategies.earnings_drift_strategy import EarningsDriftStrategy


def _make_bars(n: int = 60, start_price: float = 100.0, start_date: date | None = None) -> list[Bar]:
    bars: list[Bar] = []
    price = start_price
    base_date = start_date or date(2024, 1, 2)
    for i in range(n):
        ts = datetime.combine(base_date, datetime.min.time(), tzinfo=timezone.utc) + pd.Timedelta(days=i).to_pytimedelta()
        price *= 1.0 + 0.003 * ((i % 3) + 1)
        bars.append(
            Bar(
                timestamp_utc=ts,
                symbol="AAPL",
                open=price * 0.999,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                volume=10000.0,
            )
        )
    return bars


class EarningsDriftStrategyTests(unittest.TestCase):
    def test_empty_without_earnings_dates(self):
        strategy = EarningsDriftStrategy()
        bars = _make_bars(30)
        engine = EventDrivenBacktestEngine([strategy], config=BacktestConfig())
        result = engine.run(bars)

        signal_events = [e for e in result.events if hasattr(e, "signal")]
        earnings_signals = [
            e for e in signal_events
            if "earnings" in str(getattr(e.signal, "reason", ""))
        ]
        self.assertEqual(len(earnings_signals), 0, "Should produce no signals without earnings dates")

    def test_generates_signal_on_earnings_date(self):
        strategy = EarningsDriftStrategy(drift_period_days=5, reaction_lookback_days=3)
        strategy.set_earnings_dates("AAPL", {date(2024, 1, 5)})
        bars = _make_bars(20, start_date=date(2024, 1, 1))
        engine = EventDrivenBacktestEngine([strategy], config=BacktestConfig())
        result = engine.run(bars)

        signal_events = [e for e in result.events if hasattr(e, "signal")]
        earnings_signals = [
            e for e in signal_events
            if "earnings" in str(getattr(e.signal, "reason", ""))
            and getattr(e.signal, "direction", None) != SignalDirection.FLAT
        ]
        self.assertGreater(len(earnings_signals), 0, "Should generate signal on earnings date with positive reaction")

    def test_exits_after_drift_period(self):
        strategy = EarningsDriftStrategy(drift_period_days=5, reaction_lookback_days=3)
        strategy.set_earnings_dates("AAPL", {date(2024, 1, 5)})
        bars = _make_bars(30, start_date=date(2024, 1, 1))
        engine = EventDrivenBacktestEngine([strategy], config=BacktestConfig())
        result = engine.run(bars)

        exit_signals = [
            e for e in result.events
            if hasattr(e, "signal") and getattr(e.signal, "direction", None) == SignalDirection.FLAT
        ]
        self.assertGreater(len(exit_signals), 0, "Should generate exit signal after drift period")

    def test_respects_max_positions(self):
        strategy = EarningsDriftStrategy(max_positions=1, drift_period_days=60, reaction_lookback_days=3)
        strategy.set_earnings_dates("AAPL", {date(2024, 1, 5), date(2024, 1, 12)})
        bars = _make_bars(20, start_date=date(2024, 1, 1))
        engine = EventDrivenBacktestEngine([strategy], config=BacktestConfig())
        result = engine.run(bars)

        signal_events = [e for e in result.events if hasattr(e, "signal")]
        entry_signals = [
            e for e in signal_events
            if "earnings" in str(getattr(e.signal, "reason", ""))
            and getattr(e.signal, "direction", None) != SignalDirection.FLAT
        ]
        self.assertLessEqual(len(entry_signals), 1, "Should respect max_positions limit")

    def test_min_price_filter(self):
        strategy = EarningsDriftStrategy(min_price=50.0, reaction_lookback_days=3)
        strategy.set_earnings_dates("PENNY", {date(2024, 1, 5)})
        bars: list[Bar] = []
        for i in range(10):
            ts = datetime(2024, 1, 1, tzinfo=timezone.utc) + pd.Timedelta(days=i).to_pytimedelta()
            bars.append(
                Bar(
                    timestamp_utc=ts,
                    symbol="PENNY",
                    open=3.0,
                    high=3.2,
                    low=2.9,
                    close=3.1,
                    volume=5000.0,
                )
            )
        engine = EventDrivenBacktestEngine([strategy], config=BacktestConfig())
        result = engine.run(bars)
        signal_events = [e for e in result.events if hasattr(e, "signal")]
        earnings_signals = [
            e for e in signal_events
            if "earnings" in str(getattr(e.signal, "reason", ""))
        ]
        self.assertEqual(len(earnings_signals), 0, "Should filter out stocks below min_price")

    def test_factory_registration(self):
        from quant_us.strategies.factory import build_strategy, available_strategies
        self.assertIn("earnings_drift", available_strategies())
        strategy = build_strategy("earnings_drift", {"drift_period_days": 20})
        self.assertIsInstance(strategy, EarningsDriftStrategy)
        self.assertEqual(strategy.drift_period_days, 20)


if __name__ == "__main__":
    unittest.main()
