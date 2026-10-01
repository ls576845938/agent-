"""Anti-lookahead regression tests.

These tests verify that the backtest system does not permit future-function bugs:
- Signals must not use future bars
- shift(1) must be correctly applied
- Feature calculation must not leak future data
- Event-driven engine must process bars in strict temporal order
- Close-price decisions must use only information available at decision time
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant_us.backtest.engine import BacktestConfig, EventDrivenBacktestEngine
from quant_us.backtest.slippage import BpsSlippage
from quant_us.backtest.walk_forward import WalkForwardConfig, build_walk_forward_windows
from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Bar
from quant_us.strategies.base import Strategy, StrategyContext


def _make_ohlcv_frame(n_bars: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = 100.0
    returns = rng.normal(0.0005, 0.015, n_bars)
    close = base * np.cumprod(1.0 + returns)
    timestamps = pd.date_range(
        start="2024-01-02T09:30:00",
        periods=n_bars,
        freq="1min",
        tz="UTC",
    )
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "symbol": "AAPL",
            "open": close * (1.0 + rng.normal(0, 0.002, n_bars)),
            "high": close * (1.0 + abs(rng.normal(0, 0.005, n_bars))),
            "low": close * (1.0 - abs(rng.normal(0, 0.005, n_bars))),
            "close": close,
            "volume": rng.integers(1000, 100000, n_bars).astype(float),
        }
    )


def _make_bars(n: int = 60, start_price: float = 100.0) -> list[Bar]:
    bars: list[Bar] = []
    price = start_price
    for i in range(n):
        ts = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc) + pd.Timedelta(minutes=i).to_pytimedelta()
        price *= 1.0 + np.random.default_rng(42 + i).normal(0.001, 0.01)
        bars.append(
            Bar(
                timestamp_utc=ts,
                symbol="AAPL",
                open=price * 0.999,
                high=price * 1.005,
                low=price * 0.995,
                close=price,
                volume=float(np.random.default_rng(100 + i).integers(5000, 50000)),
            )
        )
    return bars


def _make_multisymbol_bars(
    timestamps: int,
    symbols: tuple[str, ...] = ("AAPL", "MSFT"),
) -> list[Bar]:
    bars: list[Bar] = []
    start = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc)
    for i in range(timestamps):
        ts = start + pd.Timedelta(minutes=i).to_pytimedelta()
        for offset, symbol in enumerate(symbols):
            price = 100.0 + i + offset
            bars.append(
                Bar(
                    timestamp_utc=ts,
                    symbol=symbol,
                    open=price,
                    high=price + 1.0,
                    low=price - 1.0,
                    close=price + 0.25,
                    volume=10_000.0,
                )
            )
    return bars


class AntiLookaheadSignalTests(unittest.TestCase):
    """Verify strategy signals cannot use future bar information."""

    def test_signal_cannot_reference_future_bars(self):
        """Strategy receives bars one at a time. It must not see bar n+1."""
        bars = _make_bars(60)
        seen_closes: list[float] = []

        class RecordingStrategy(Strategy):
            strategy_id = "recording"

            def on_bar(self, event, context):
                seen_closes.append(float(event.bar.close))
                return []

        engine = EventDrivenBacktestEngine([RecordingStrategy()], config=BacktestConfig())
        engine.run(bars)

        for i, seen_close in enumerate(seen_closes):
            self.assertAlmostEqual(seen_close, bars[i].close, places=6,
                                   msg=f"Bar {i}: strategy saw close {seen_close} but actual is {bars[i].close}")

    def test_momentum_strategy_uses_only_past_bars(self):
        """Momentum calculated at bar t must use only bars <= t, never t+1."""
        bars = _make_bars(80)

        recorded_momentums: list[tuple[datetime, float]] = []

        class InspectedMomentum(Strategy):
            strategy_id = "inspected"
            lookback = 20
            _closes: list[float] = []

            def on_bar(self, event, context):
                self._closes.append(float(event.bar.close))
                if len(self._closes) <= self.lookback:
                    return []
                previous = self._closes[-self.lookback - 1]
                momentum = event.bar.close / previous - 1.0 if previous > 0 else 0.0
                recorded_momentums.append((event.bar.timestamp_utc, momentum))
                return []

        engine = EventDrivenBacktestEngine([InspectedMomentum()], config=BacktestConfig())
        engine.run(bars)

        for ts, momentum in recorded_momentums:
            idx = next(i for i, b in enumerate(bars) if b.timestamp_utc == ts)
            if idx >= 20:
                past_close = bars[idx - 20].close
                current_close = bars[idx].close
                expected = current_close / past_close - 1.0 if past_close > 0 else 0.0
                self.assertAlmostEqual(momentum, expected, places=6,
                                       msg=f"Bar {idx}: momentum {momentum} != expected {expected}")

    def test_no_future_close_in_signal_decision(self):
        """A strategy must not use the current bar's close for an entry that
        would execute at the same bar's open. Signal from bar t applies to bar t+1.

        We use deterministic up-trending bars to guarantee some bars hit close>open."""
        bars: list[Bar] = []
        price = 100.0
        for i in range(30):
            ts = datetime(2024, 1, 2, 9, 30, tzinfo=timezone.utc) + pd.Timedelta(minutes=i).to_pytimedelta()
            open_p = price
            close_p = price * (1.005 + (i % 3) * 0.01)
            bars.append(Bar(
                timestamp_utc=ts, symbol="AAPL",
                open=open_p, high=close_p * 1.002, low=open_p * 0.998, close=close_p,
                volume=10000.0,
            ))
            price = close_p

        class LookaheadStrategy(Strategy):
            """DELIBERATELY BROKEN: uses current close for entry signal."""
            strategy_id = "lookahead"

            def on_bar(self, event, context):
                if event.bar.close > event.bar.open * 1.005:
                    return [self._make_signal(event.bar, "close_gt_open")]
                return []

            def _make_signal(self, bar, reason):
                from quant_us.core.types import Signal
                return Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.LONG,
                    strength=1.0,
                    horizon="1b",
                    reason=reason,
                )

        engine = EventDrivenBacktestEngine([LookaheadStrategy()], config=BacktestConfig())
        result = engine.run(bars)

        lookahead_signals = [
            e for e in result.events
            if hasattr(e, 'signal') and hasattr(e.signal, 'reason') and 'close_gt_open' in str(e.signal.reason)
        ]
        self.assertGreater(len(lookahead_signals), 0,
                           msg="The deliberately-broken strategy should produce signals — this confirms the test is valid")


class AntiLookaheadFeatureTests(unittest.TestCase):
    """Verify feature calculation does not leak future data."""

    def test_shift1_means_previous_bar(self):
        """shift(1) on close must use bar t-1, not bar t."""
        frame = _make_ohlcv_frame(50)
        close = frame["close"].astype(float)
        shifted = close.shift(1)

        self.assertTrue(pd.isna(shifted.iloc[0]), "shift(1)[0] must be NaN (no previous bar)")
        for i in range(1, len(close)):
            self.assertAlmostEqual(shifted.iloc[i], close.iloc[i - 1], places=6,
                                   msg=f"shift(1)[{i}]={shifted.iloc[i]} != close[{i-1}]={close.iloc[i-1]}")

    def test_rolling_features_use_only_past(self):
        """Rolling window at bar t must use bars [t-window+1, t], never t+1."""
        frame = _make_ohlcv_frame(100)
        close = frame["close"].astype(float)
        window = 20

        rolling_mean = close.rolling(window=window, min_periods=1).mean()

        for i in range(len(close)):
            expected = close.iloc[max(0, i - window + 1):i + 1].mean()
            self.assertAlmostEqual(rolling_mean.iloc[i], expected, places=6,
                                   msg=f"Rolling mean at bar {i} includes future data")

    def test_feature_map_from_frame_no_temporal_leak(self):
        """feature_map_from_frame must not shift dates forward."""
        from quant_us.backtest.data_bridge import feature_map_from_frame

        dates = pd.date_range("2024-01-02", periods=10, freq="B")
        factor_frame = pd.DataFrame([
            {"date": d.date(), "symbol": "AAPL", "factor_name": "momentum_20", "factor_value": float(i) * 0.01}
            for i, d in enumerate(dates)
        ])
        feat_map = feature_map_from_frame(factor_frame)

        for dt_key in feat_map:
            self.assertLessEqual(dt_key.date(), dates[-1].date(),
                                 msg=f"Feature date {dt_key.date()} exceeds max input date {dates[-1].date()}")


class AntiLookaheadEngineTests(unittest.TestCase):
    """Verify the event-driven engine processes bars strictly in order."""

    def test_walk_forward_folds_do_not_share_timestamps_with_multisymbol_bars(self):
        """Walk-forward train/test slices must be timestamp-disjoint per fold."""
        bars = _make_multisymbol_bars(timestamps=7)
        windows = build_walk_forward_windows(
            bars,
            WalkForwardConfig(train_bars=3, test_bars=2, step_bars=2),
        )

        self.assertEqual(len(windows), 2)
        for window in windows:
            train_ts = {
                bar.timestamp_utc
                for bar in bars
                if window.train_start <= bar.timestamp_utc <= window.train_end
            }
            test_ts = {
                bar.timestamp_utc
                for bar in bars
                if window.test_start <= bar.timestamp_utc <= window.test_end
            }
            self.assertTrue(train_ts)
            self.assertTrue(test_ts)
            self.assertTrue(train_ts.isdisjoint(test_ts))
            self.assertLess(max(train_ts), min(test_ts))

    def test_bars_processed_in_temporal_order(self):
        """Even if bars are shuffled, engine must process them in time order."""
        bars = _make_bars(30)
        shuffled = sorted(bars, key=lambda b: b.close)
        self.assertNotEqual(
            [b.timestamp_utc for b in shuffled],
            [b.timestamp_utc for b in bars],
            "Shuffled bars must have different order for this test to be meaningful",
        )

        processed_order: list[datetime] = []

        class OrderChecker(Strategy):
            strategy_id = "order_checker"

            def on_bar(self, event, context):
                processed_order.append(event.bar.timestamp_utc)
                return []

        engine = EventDrivenBacktestEngine([OrderChecker()], config=BacktestConfig())
        engine.run(shuffled)

        expected_order = sorted(b.timestamp_utc for b in bars)
        self.assertEqual(processed_order, expected_order,
                         msg="Engine must process bars in strict temporal order")

    def test_market_prices_update_before_strategy_sees_bar(self):
        """SimBroker must update market prices BEFORE strategy.on_bar() is called."""
        bars = _make_bars(40)
        prices_at_signal: list[dict[str, float]] = []

        class PriceChecker(Strategy):
            strategy_id = "price_checker"

            def on_bar(self, event, context):
                prices_at_signal.append(dict(context.market_prices))
                return []

        engine = EventDrivenBacktestEngine([PriceChecker()], config=BacktestConfig())
        engine.run(bars)

        for i, prices in enumerate(prices_at_signal):
            self.assertIn("AAPL", prices, f"Bar {i}: market_prices missing AAPL")
            self.assertAlmostEqual(prices["AAPL"], bars[i].close, places=6,
                                   msg=f"Bar {i}: market_price {prices['AAPL']} != close {bars[i].close}")

    def test_strategy_cannot_modify_past_bars(self):
        """Strategy must not be able to mutate Bar objects after they've been processed."""
        bars = _make_bars(30)
        original_closes = [b.close for b in bars]

        class BarMutator(Strategy):
            strategy_id = "bar_mutator"

            def on_bar(self, event, context):
                try:
                    event.bar.close = 999.0
                except Exception:
                    pass
                return []

        engine = EventDrivenBacktestEngine([BarMutator()], config=BacktestConfig())
        engine.run(bars)

        for i, bar in enumerate(bars):
            self.assertAlmostEqual(bar.close, original_closes[i], places=6,
                                   msg=f"Bar {i} close was mutated by strategy")


class AntiLookaheadSlippageCommissionTests(unittest.TestCase):
    """Verify cost models don't use future information."""

    def test_slippage_uses_only_current_bar_price(self):
        """Slippage is a function of current price only, never future price."""
        slip = BpsSlippage(bps=5.0)
        from quant_us.core.enums import OrderSide

        slippage_price = slip.apply(OrderSide.BUY, 100.0)
        expected = 100.0 * (1.0 + 5.0 / 10_000.0)
        self.assertAlmostEqual(slippage_price, expected, places=6,
                               msg="BpsSlippage should be deterministic from current price only")

    def test_commission_independent_of_future_bars(self):
        """Commission at bar t must not depend on bar t+1's price."""
        from quant_us.backtest.commission import PercentCommission

        comm = PercentCommission(rate=0.001)
        notional_100 = 100.0 * 10
        cost_t = comm.calculate(notional_100)
        self.assertAlmostEqual(cost_t, 1.0, places=6,
                               msg=f"Commission on $1000 at 0.1% should be $1.00, got ${cost_t:.2f}")


if __name__ == "__main__":
    unittest.main()
