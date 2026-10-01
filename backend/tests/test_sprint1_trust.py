"""Tests for Sprint 1 trust-building modules: survivorship, turnover, gap, cost stress, corporate actions ledger."""
from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from quant_us.backtest.corporate_actions_ledger import (
    BorrowFeeEvent,
    DividendEvent,
    LedgerAdjustment,
    LedgerAdjustmentLog,
    apply_dividend_to_cash,
    compute_borrow_fee,
    reconstruct_equity_with_adjustments,
)
from quant_us.backtest.cost_stress_scanner import MULTIPLIERS, CostStressLevel, CostStressReport, run_cost_stress
from quant_us.backtest.engine import BacktestConfig
from quant_us.backtest.gap_session import (
    GapConfig,
    SessionConfig,
    apply_order_delay,
    classify_session,
    detect_gap,
    gap_adjusted_fill_price,
    is_bar_tradable,
    is_extreme_gap,
)
from quant_us.backtest.turnover import TurnoverReport, compute_turnover
from quant_us.core.enums import OrderSide
from quant_us.core.types import Bar, Fill, Order, new_id
from quant_us.data.universe.survivorship import (
    SurvivorshipBiasDetector,
    SurvivorshipReport,
    TickerChange,
    build_instruments_from_yfinance,
    lookup_industry,
    lookup_sector,
)


def _bars(n: int = 30, symbol: str = "AAPL") -> list[Bar]:
    bars: list[Bar] = []
    price = 150.0
    for i in range(n):
        ts = datetime(2024, 1, 2, 10, i % 390, tzinfo=timezone.utc)
        price *= 1.0 + np.random.default_rng(42 + i).normal(0.0005, 0.01)
        bars.append(
            Bar(
                timestamp_utc=ts, symbol=symbol,
                open=price * 0.999, high=price * 1.01, low=price * 0.99, close=price,
                volume=float(np.random.default_rng(100 + i).integers(5000, 50000)),
            )
        )
    return bars


def _fills(n: int = 5) -> list[Fill]:
    fills: list[Fill] = []
    for i in range(n):
        ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc) + pd.Timedelta(minutes=i * 10).to_pytimedelta()
        fills.append(
            Fill(
                order_id=new_id("ord"), symbol="AAPL", side=OrderSide.BUY,
                quantity=10.0, price=100.0 + i, commission=0.1,
                filled_at=ts, broker="test",
            )
        )
    return fills


class SurvivorshipBiasDetectionTests(unittest.TestCase):
    def test_active_symbols_at_past_date_excludes_delisted(self):
        instruments = pd.DataFrame([
            {"symbol": "AAPL", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
            {"symbol": "DEAD", "listing_date": date(2000, 1, 1), "delisting_date": date(2022, 6, 1), "is_active": False},
            {"symbol": "NEW", "listing_date": date(2023, 1, 1), "delisting_date": None, "is_active": True},
        ])
        detector = SurvivorshipBiasDetector(instruments)
        active_2021 = detector.active_symbols_at(date(2021, 6, 15))
        self.assertIn("AAPL", active_2021)
        self.assertIn("DEAD", active_2021)
        self.assertNotIn("NEW", active_2021)

        active_2023 = detector.active_symbols_at(date(2023, 6, 15))
        self.assertIn("AAPL", active_2023)
        self.assertNotIn("DEAD", active_2023)
        self.assertIn("NEW", active_2023)

    def test_survivorship_bias_detected(self):
        instruments = pd.DataFrame([
            {"symbol": "AAPL", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
            {"symbol": "DEAD", "listing_date": date(2000, 1, 1), "delisting_date": date(2022, 1, 1), "is_active": False},
        ])
        detector = SurvivorshipBiasDetector(instruments)
        report = detector.check_backtest_universe(
            universe_symbols=["AAPL", "DEAD"],
            backtest_end=date(2023, 12, 31),
        )
        self.assertTrue(report.survivorship_bias_detected)
        self.assertIn("DEAD", report.delisted_tickers)
        self.assertGreater(report.bias_pct, 0)

    def test_no_bias_when_all_active(self):
        instruments = pd.DataFrame([
            {"symbol": "AAPL", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
            {"symbol": "MSFT", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
        ])
        detector = SurvivorshipBiasDetector(instruments)
        report = detector.check_backtest_universe(["AAPL", "MSFT"], backtest_end=date(2023, 12, 31))
        self.assertFalse(report.survivorship_bias_detected)

    def test_point_in_time_filter(self):
        instruments = pd.DataFrame([
            {"symbol": "AAPL", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
            {"symbol": "OLD", "listing_date": date(2000, 1, 1), "delisting_date": date(2020, 6, 1), "is_active": False},
        ])
        detector = SurvivorshipBiasDetector(instruments)
        filtered = detector.point_in_time_symbols(["AAPL", "OLD"], date(2019, 1, 1))
        self.assertIn("AAPL", filtered)
        self.assertIn("OLD", filtered)

        filtered_2021 = detector.point_in_time_symbols(["AAPL", "OLD"], date(2021, 1, 1))
        self.assertIn("AAPL", filtered_2021)
        self.assertNotIn("OLD", filtered_2021)

    def test_ticker_change_tracking(self):
        instruments = pd.DataFrame([
            {"symbol": "AAPL", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
            {"symbol": "META", "listing_date": date(2000, 1, 1), "delisting_date": None, "is_active": True},
        ])
        changes = [TickerChange(old_symbol="FB", new_symbol="META", effective_date=date(2022, 6, 9), reason="rebrand")]
        detector = SurvivorshipBiasDetector(instruments, changes)
        filtered = detector.point_in_time_symbols(["AAPL", "FB"], date(2023, 1, 1))
        self.assertIn("META", filtered)

    def test_sector_lookup(self):
        self.assertEqual(lookup_sector("AAPL"), "Technology")
        self.assertEqual(lookup_sector("JPM"), "Financials")
        self.assertEqual(lookup_sector("XLF"), "Financials")
        self.assertEqual(lookup_sector("UNKNOWN"), "")

    def test_industry_lookup(self):
        self.assertEqual(lookup_industry("AAPL"), "Software & Services")
        self.assertEqual(lookup_industry("JPM"), "Banking & Finance")
        self.assertEqual(lookup_industry("UNKNOWN"), "")

    def test_build_instruments_fallback(self):
        frame = build_instruments_from_yfinance(["AAPL", "MSFT"])
        self.assertEqual(len(frame), 2)
        self.assertIn("symbol", frame.columns)
        self.assertIn("sector", frame.columns)
        self.assertIn("is_active", frame.columns)


class TurnoverTests(unittest.TestCase):
    def test_compute_turnover_basic(self):
        fills = _fills(5)
        equity = [100_000.0] * 10
        report = compute_turnover(fills, equity)
        self.assertGreater(report.total_notional_traded, 0)
        self.assertGreater(report.average_equity, 0)

    def test_empty_fills(self):
        report = compute_turnover([], [100_000.0])
        self.assertEqual(report.total_turnover, 0.0)

    def test_excessive_turnover_detection(self):
        fills = _fills(10)
        equity = [1000.0] * 5
        report = compute_turnover(fills, equity, max_daily_turnover_pct=5.0)
        self.assertGreater(report.excessive_turnover_days, 0)


class GapSessionTests(unittest.TestCase):
    def test_classify_regular_session(self):
        bar = _bars(1)[0]
        bar2 = Bar(
            timestamp_utc=datetime(2024, 1, 2, 10, 30, tzinfo=timezone.utc),
            symbol="AAPL", open=150.0, high=151.0, low=149.0, close=150.5, volume=10000.0,
        )
        from quant_us.core.enums import SessionName
        self.assertEqual(classify_session(bar2), SessionName.REGULAR)

    def test_detect_gap(self):
        bar = _bars(1)[0]
        gap = detect_gap(prev_close=100.0, bar=bar)
        self.assertGreater(gap, 0)

    def test_extreme_gap_detection(self):
        cfg = GapConfig(max_gap_pct=20.0)
        self.assertTrue(is_extreme_gap(25.0, cfg))
        self.assertFalse(is_extreme_gap(15.0, cfg))

    def test_gap_adjusted_fill_on_extreme(self):
        bar = Bar(
            timestamp_utc=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
            symbol="AAPL", open=150.0, high=151.0, low=149.0, close=150.5, volume=10000.0,
        )
        order = Order(
            timestamp_utc=bar.timestamp_utc, strategy_id="test", symbol="AAPL",
            side=OrderSide.BUY, quantity=10.0, order_type="MARKET", time_in_force="DAY",
            client_order_id=new_id("coid"),
        )
        cfg = GapConfig(max_gap_pct=20.0, reject_on_extreme_gap=True)
        price = gap_adjusted_fill_price(order, bar, prev_close=100.0, config=cfg)
        self.assertIsNone(price)

    def test_is_bar_tradable(self):
        bar = _bars(1)[0]
        tradable, reason = is_bar_tradable(bar)
        self.assertTrue(tradable, f"Should be tradable, got reason: {reason}")

        zero_vol = Bar(
            timestamp_utc=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
            symbol="AAPL", open=150.0, high=151.0, low=149.0, close=150.5, volume=0.0,
        )
        tradable2, _ = is_bar_tradable(zero_vol)
        self.assertFalse(tradable2)

    def test_no_price_movement(self):
        flat = Bar(
            timestamp_utc=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
            symbol="AAPL", open=150.0, high=150.0, low=150.0, close=150.0, volume=1000.0,
        )
        tradable, reason = is_bar_tradable(flat)
        self.assertFalse(tradable)
        self.assertEqual(reason, "no_price_movement")


class CostStressScannerTests(unittest.TestCase):
    def test_run_cost_stress_multilevel(self):
        from quant_us.strategies.momentum_strategy import MomentumStrategy
        bars = _bars(60)
        strategy = MomentumStrategy(lookback_bars=10, entry_threshold=0.005)
        config = BacktestConfig(initial_cash=100_000.0, commission_rate=0.0001, slippage_bps=1.0)
        report = run_cost_stress([strategy], bars, config)
        self.assertIsInstance(report, CostStressReport)
        self.assertEqual(len(report.levels), 4)
        self.assertTrue(report.survival_rate_pct >= 0)

    def test_all_levels_have_decay(self):
        from quant_us.strategies.momentum_strategy import MomentumStrategy
        bars = _bars(60)
        strategy = MomentumStrategy(lookback_bars=10, entry_threshold=0.005)
        config = BacktestConfig(initial_cash=100_000.0, commission_rate=0.0001, slippage_bps=1.0)
        report = run_cost_stress([strategy], bars, config)
        for lv in report.levels:
            self.assertIsInstance(lv.return_decay_pct, float)
            self.assertIsInstance(lv.sharpe_decay, float)

    def test_summary_dict(self):
        report = CostStressReport(
            strategy_id="test", symbol="AAPL",
            baseline=CostStressLevel(label="1x", commission_multiplier=1.0, slippage_multiplier=1.0, commission_rate=0.0001, slippage_bps=1.0),
            levels=[CostStressLevel(label="2x", commission_multiplier=2.0, slippage_multiplier=2.0, commission_rate=0.0002, slippage_bps=2.0)],
        )
        summary = report.summary
        self.assertEqual(summary["strategy_id"], "test")
        self.assertEqual(len(summary["levels"]), 1)


class CorporateActionsLedgerTests(unittest.TestCase):
    def test_dividend_income_added_to_cash(self):
        positions = {"AAPL": 100.0}
        dividend = DividendEvent(symbol="AAPL", ex_date=date(2024, 6, 15), pay_date=date(2024, 6, 20), amount_per_share=0.25)
        new_cash = apply_dividend_to_cash(10000.0, positions, dividend, as_of_date=date(2024, 6, 16))
        self.assertAlmostEqual(new_cash, 10000.0 + 100.0 * 0.25, places=6)

    def test_dividend_before_ex_date_not_applied(self):
        positions = {"AAPL": 100.0}
        dividend = DividendEvent(symbol="AAPL", ex_date=date(2024, 6, 15), pay_date=date(2024, 6, 20), amount_per_share=0.25)
        new_cash = apply_dividend_to_cash(10000.0, positions, dividend, as_of_date=date(2024, 6, 14))
        self.assertEqual(new_cash, 10000.0)

    def test_borrow_fee_computation(self):
        short_positions = {"AAPL": -50.0}
        market_prices = {"AAPL": 150.0}
        fee = compute_borrow_fee(short_positions, market_prices, annual_rate_pct=1.0, days=1)
        expected = 50.0 * 150.0 * (0.01 / 365.0) * 1.0
        self.assertAlmostEqual(fee, expected, places=6)

    def test_no_borrow_fee_for_long(self):
        long_positions = {"AAPL": 50.0}
        market_prices = {"AAPL": 150.0}
        fee = compute_borrow_fee(long_positions, market_prices)
        self.assertEqual(fee, 0.0)

    def test_reconstruct_equity_with_adjustments(self):
        fills = _fills(3)
        log = LedgerAdjustmentLog(adjustments=[
            LedgerAdjustment(
                timestamp_utc=datetime(2024, 1, 3, tzinfo=timezone.utc),
                symbol="AAPL", adjustment_type="dividend", amount=25.0, description="Q1 dividend",
            ),
        ])
        market_prices = {"AAPL": 105.0}
        equity = reconstruct_equity_with_adjustments(fills, log, 100_000.0, market_prices)
        self.assertGreater(equity, 0)

    def test_ledger_adjustment_log_totals(self):
        log = LedgerAdjustmentLog(adjustments=[
            LedgerAdjustment(datetime(2024, 1, 1, tzinfo=timezone.utc), "AAPL", "dividend", 10.0, ""),
            LedgerAdjustment(datetime(2024, 1, 2, tzinfo=timezone.utc), "MSFT", "borrow_fee", -5.0, ""),
            LedgerAdjustment(datetime(2024, 1, 3, tzinfo=timezone.utc), "AAPL", "corporate_action", 3.0, ""),
        ])
        self.assertAlmostEqual(log.total_dividends(), 10.0)
        self.assertAlmostEqual(log.total_borrow_fees(), -5.0)
        self.assertAlmostEqual(log.total_corporate_adjustments(), 3.0)
        self.assertEqual(len(log.adjustments), 3)


if __name__ == "__main__":
    unittest.main()
