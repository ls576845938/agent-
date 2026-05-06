"""Edge case tests for ledger_pnl.py.

Tests derive_equity_from_fills() and verify_equity_consistency()
with empty fills, single fills, short sales, multi-symbol, round-trips,
short covers, partial fills, snapshot consistency, zero commission,
and adjustment logistics.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from quant_us.backtest.corporate_actions_ledger import (
    LedgerAdjustmentLog,
)
from quant_us.backtest.ledger_pnl import (
    LedgerEquityCurve,
    derive_equity_from_fills,
    verify_equity_consistency,
)
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, PortfolioSnapshot, new_id


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_fill(
    side: OrderSide,
    symbol: str,
    quantity: float,
    price: float,
    commission: float,
    ts_offset_minutes: int = 0,
) -> Fill:
    """Build a Fill with a deterministic UTC timestamp.

    All fills share the base timestamp 2024-06-03 09:30 UTC; *ts_offset_minutes*
    is added so the test can rely on ordering.
    """
    base = datetime(2024, 6, 3, 9, 30, tzinfo=timezone.utc)
    ts = base + timedelta(minutes=ts_offset_minutes)
    return Fill(
        order_id=new_id("ord"),
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        filled_at=ts,
        broker="test_ledger",
    )


# ===================================================================
# derive_equity_from_fills
# ===================================================================

class DeriveEquityFromFillsTests(unittest.TestCase):
    """derive_equity_from_fills() edge cases."""

    # -- 1. empty fills ------------------------------------------------

    def test_empty_fills_returns_initial_cash(self):
        curve = derive_equity_from_fills([], 100_000.0)
        self.assertEqual(len(curve.points), 1)
        self.assertEqual(curve.initial_cash, 100_000.0)
        self.assertEqual(curve.total_fills, 0)
        self.assertEqual(curve.final_equity, 100_000.0)
        self.assertEqual(curve.total_fees, 0.0)
        p = curve.points[0]
        self.assertAlmostEqual(p.cash, 100_000.0)
        self.assertEqual(p.position_value, 0.0)
        self.assertEqual(p.equity, 100_000.0)
        self.assertEqual(p.cumulative_fees, 0.0)
        self.assertEqual(p.cumulative_slippage_cost, 0.0)

    # -- 2. single BUY -------------------------------------------------

    def test_single_buy_fill(self):
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        curve = derive_equity_from_fills([fill], 100_000.0)
        self.assertEqual(len(curve.points), 1)
        p = curve.points[0]

        # cash = 100000 - 100*150 - 1 = 84999
        self.assertAlmostEqual(p.cash, 84_999.0)

        # position_value uses avg_price as fallback: 100 * 150 = 15000
        self.assertAlmostEqual(p.position_value, 15_000.0)

        # equity = 84999 + 15000 = 99999
        self.assertAlmostEqual(p.equity, 99_999.0)
        self.assertAlmostEqual(p.cumulative_fees, 1.0)
        self.assertAlmostEqual(p.cumulative_slippage_cost, 0.0)

    # -- 3. single SELL (short) ----------------------------------------

    def test_single_sell_short(self):
        fill = _make_fill(OrderSide.SELL, "AAPL", 100.0, 150.0, 1.0)
        curve = derive_equity_from_fills([fill], 100_000.0)
        self.assertEqual(len(curve.points), 1)
        p = curve.points[0]

        # cash = 100000 + 100*150 - 1 = 114999
        self.assertAlmostEqual(p.cash, 114_999.0)

        # position_value = -100 * 150 = -15000
        self.assertAlmostEqual(p.position_value, -15_000.0)

        # equity = 114999 - 15000 = 99999
        self.assertAlmostEqual(p.equity, 99_999.0)
        self.assertAlmostEqual(p.cumulative_fees, 1.0)

    # -- 4. multi-symbol -----------------------------------------------

    def test_multi_symbol_fills(self):
        f1 = _make_fill(OrderSide.BUY, "AAPL", 50.0, 150.0, 1.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.BUY, "MSFT", 100.0, 400.0, 1.5, ts_offset_minutes=5)
        curve = derive_equity_from_fills([f1, f2], 100_000.0)
        self.assertEqual(len(curve.points), 2)
        p1, p2 = curve.points

        # After AAPL buy: cash=100000-7500-1=92499, pv=50*150=7500, eq=92499+7500=99999
        self.assertAlmostEqual(p1.cash, 92_499.0)
        self.assertAlmostEqual(p1.position_value, 7_500.0)
        self.assertAlmostEqual(p1.equity, 99_999.0)

        # After MSFT buy: cash=92499-40000-1.5=52497.5
        self.assertAlmostEqual(p2.cash, 52_497.5)
        # pv = 50*150 + 100*400 = 7500+40000 = 47500
        self.assertAlmostEqual(p2.position_value, 47_500.0)
        # eq = 52497.5 + 47500 = 99997.5
        self.assertAlmostEqual(p2.equity, 99_997.5)
        self.assertAlmostEqual(p2.cumulative_fees, 2.5)

    # -- 5. buy-then-sell round-trip -----------------------------------

    def test_round_trip_pnl(self):
        f1 = _make_fill(OrderSide.BUY, "AAPL", 100.0, 100.0, 1.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.SELL, "AAPL", 100.0, 110.0, 1.0, ts_offset_minutes=10)
        curve = derive_equity_from_fills([f1, f2], 100_000.0)
        self.assertEqual(len(curve.points), 2)

        # PnL = (110-100)*100 - 2 = 998  =>  final equity = 100998
        self.assertAlmostEqual(curve.final_equity, 100_998.0)
        self.assertAlmostEqual(curve.total_fees, 2.0)
        self.assertEqual(curve.total_fills, 2)

        # Verify the last point (position flat, PnL in cash)
        last = curve.points[-1]
        self.assertAlmostEqual(last.position_value, 0.0)

    # -- 6. short-cover sequence ---------------------------------------

    def test_short_cover_pnl(self):
        f1 = _make_fill(OrderSide.SELL, "AAPL", 100.0, 100.0, 1.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.BUY, "AAPL", 100.0, 90.0, 1.0, ts_offset_minutes=10)
        curve = derive_equity_from_fills([f1, f2], 100_000.0)
        self.assertEqual(len(curve.points), 2)

        # PnL = (100-90)*100 - 2 = 998  =>  final equity = 100998
        self.assertAlmostEqual(curve.final_equity, 100_998.0)
        self.assertAlmostEqual(curve.total_fees, 2.0)

        # Verify the last point (position flat, PnL in cash)
        last = curve.points[-1]
        self.assertAlmostEqual(last.position_value, 0.0)

    # -- 7. partial fills ----------------------------------------------

    def test_partial_fills(self):
        f1 = _make_fill(OrderSide.BUY, "AAPL", 50.0, 150.0, 0.5, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.BUY, "AAPL", 50.0, 151.0, 0.5, ts_offset_minutes=5)
        curve = derive_equity_from_fills([f1, f2], 100_000.0)
        self.assertEqual(len(curve.points), 2)
        p1, p2 = curve.points

        # After first partial: cash=100000-7500-0.5=92499.5, pv=50*150=7500, eq=92499.5+7500=99999.5
        self.assertAlmostEqual(p1.cash, 92_499.5)
        self.assertAlmostEqual(p1.position_value, 7_500.0)
        self.assertAlmostEqual(p1.equity, 99_999.5)

        # After second partial: cash=92499.5-7550-0.5=84949.0
        self.assertAlmostEqual(p2.cash, 84_949.0)

        # avg price = (50*150 + 50*151)/100 = 150.5, pv = 100*150.5 = 15050
        self.assertAlmostEqual(p2.position_value, 15_050.0)
        self.assertAlmostEqual(p2.equity, 99_999.0)
        self.assertAlmostEqual(p2.cumulative_fees, 1.0)

    # -- 10. zero commission -------------------------------------------

    def test_zero_commission(self):
        f1 = _make_fill(OrderSide.BUY, "AAPL", 100.0, 100.0, 0.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.SELL, "AAPL", 100.0, 110.0, 0.0, ts_offset_minutes=10)
        curve = derive_equity_from_fills([f1, f2], 100_000.0)
        # PnL = (110-100)*100 = 1000  =>  final equity = 101000
        self.assertAlmostEqual(curve.final_equity, 101_000.0)
        self.assertAlmostEqual(curve.total_fees, 0.0)

    # -- 11. adjustments=None vs adjustments=LedgerAdjustmentLog() -----

    def test_adjustments_none_vs_empty(self):
        f1 = _make_fill(OrderSide.BUY, "AAPL", 100.0, 100.0, 1.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.SELL, "AAPL", 100.0, 110.0, 1.0, ts_offset_minutes=10)
        fills = [f1, f2]

        curve_none = derive_equity_from_fills(fills, 100_000.0, adjustments=None)
        curve_empty = derive_equity_from_fills(fills, 100_000.0, adjustments=LedgerAdjustmentLog())

        self.assertAlmostEqual(curve_none.final_equity, curve_empty.final_equity)
        self.assertEqual(len(curve_none.points), len(curve_empty.points))
        for pn, pe in zip(curve_none.points, curve_empty.points):
            self.assertAlmostEqual(pn.cash, pe.cash)
            self.assertAlmostEqual(pn.equity, pe.equity)
            self.assertAlmostEqual(pn.cumulative_fees, pe.cumulative_fees)


# ===================================================================
# verify_equity_consistency
# ===================================================================

class VerifyEquityConsistencyTests(unittest.TestCase):
    """verify_equity_consistency() edge cases."""

    # -- 8. matching snapshots -----------------------------------------

    def test_matching_snapshots(self):
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        ts = fill.filled_at
        curve = derive_equity_from_fills([fill], 100_000.0)

        # Snapshot that matches the ledger exactly.
        snapshot = PortfolioSnapshot(
            timestamp_utc=ts,
            equity=99_999.0,
            cash=84_999.0,
            gross_exposure=15_000.0,
            net_exposure=15_000.0,
        )
        market_prices = {ts: {"AAPL": 150.0}}

        consistent, msg = verify_equity_consistency(
            [snapshot],
            curve,
            fills=[fill],
            market_prices_by_time=market_prices,
        )
        self.assertTrue(consistent, msg)

    # -- 9. mismatched snapshots ---------------------------------------

    def test_mismatched_snapshots(self):
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        ts = fill.filled_at
        curve = derive_equity_from_fills([fill], 100_000.0)

        # Snapshot with equity 10% higher than the ledger truth.
        snapshot = PortfolioSnapshot(
            timestamp_utc=ts,
            equity=110_000.0,  # true ledger says 99999
            cash=84_999.0,
            gross_exposure=15_000.0,
            net_exposure=15_000.0,
        )
        market_prices = {ts: {"AAPL": 150.0}}

        consistent, msg = verify_equity_consistency(
            [snapshot],
            curve,
            fills=[fill],
            market_prices_by_time=market_prices,
        )
        self.assertFalse(consistent)
        self.assertIn("exceeds tolerance", msg)

    # -- edge: no fills / no market_prices -----------------------------

    def test_verify_no_fills_provided(self):
        """Fallback timestamp-matching path when fills are not provided."""
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        ts = fill.filled_at
        curve = derive_equity_from_fills([fill], 100_000.0)

        snapshot = PortfolioSnapshot(
            timestamp_utc=ts,
            equity=99_999.0,
            cash=84_999.0,
            gross_exposure=15_000.0,
            net_exposure=15_000.0,
        )

        # No fills+market_prices argument → uses timestamp-matching path.
        consistent, msg = verify_equity_consistency([snapshot], curve)
        self.assertTrue(consistent, msg)

    # -- edge: empty snapshots or empty curve --------------------------

    def test_verify_empty_snapshots(self):
        curve = derive_equity_from_fills([], 100_000.0)
        consistent, msg = verify_equity_consistency([], curve)
        self.assertTrue(consistent)
        self.assertIn("No data to compare", msg)

    def test_verify_empty_curve(self):
        empty_curve = LedgerEquityCurve(points=[], initial_cash=100_000.0)
        snapshot = PortfolioSnapshot(
            timestamp_utc=datetime(2024, 6, 3, 9, 30, tzinfo=timezone.utc),
            equity=100_000.0,
            cash=100_000.0,
            gross_exposure=0.0,
            net_exposure=0.0,
        )
        consistent, msg = verify_equity_consistency(
            [snapshot], empty_curve
        )
        self.assertTrue(consistent)
        self.assertIn("No data to compare", msg)


if __name__ == "__main__":
    unittest.main()
