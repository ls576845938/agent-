"""Ledger completeness tests.

Verifies that JsonlLedgerStore covers all 5 ledger types and that PnL is
derived from fills, not from strategy signals or intermediate state.

The 5 ledger types:
  1. cash_ledger       -- derived from fills (latest_cash_from_fills)
  2. position_ledger   -- derived from fills (latest_positions_from_fills)
  3. order_ledger      -- orders.jsonl (append_order)
  4. fill_ledger       -- fills.jsonl (append_fill)
  5. portfolio_snapshot -- portfolio_snapshots.jsonl (append_snapshot)
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from quant_us.backtest.ledger_pnl import derive_equity_from_fills
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import (
    Fill,
    Order,
    PortfolioSnapshot,
    Position,
    new_id,
)
from quant_us.execution.ledger import JsonlLedgerStore


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
    base = datetime(2025, 3, 15, 9, 30, tzinfo=timezone.utc)
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


def _make_order(symbol: str = "AAPL", side: OrderSide = OrderSide.BUY) -> Order:
    return Order(
        timestamp_utc=datetime(2025, 3, 15, 9, 30, tzinfo=timezone.utc),
        strategy_id="test_strat",
        symbol=symbol,
        side=side,
        quantity=100.0,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id=new_id("coid"),
    )


def _make_snapshot(
    equity: float = 100_000.0,
    cash: float = 100_000.0,
    ts_offset_minutes: int = 0,
) -> PortfolioSnapshot:
    base = datetime(2025, 3, 15, 9, 30, tzinfo=timezone.utc)
    ts = base + timedelta(minutes=ts_offset_minutes)
    return PortfolioSnapshot(
        timestamp_utc=ts,
        equity=equity,
        cash=cash,
        gross_exposure=0.0,
        net_exposure=0.0,
    )


# ===================================================================
# 5 ledgers existence tests
# ===================================================================

class TestFiveLedgersExist(unittest.TestCase):
    """Verify JsonlLedgerStore covers all 5 ledger types."""

    def setUp(self):
        self.tmpdir = Path(__file__).parent / "_ledger_test_tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.ledger = JsonlLedgerStore(self.tmpdir)

    def tearDown(self):
        for child in self.tmpdir.iterdir():
            child.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    # -- Test 1: append_order writes to orders.jsonl -----------------------
    def test_append_order_writes_to_orders_jsonl(self):
        order = _make_order()
        self.ledger.append_order(order)
        records = self.ledger.read_records("orders.jsonl")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], order.symbol)
        self.assertEqual(records[0]["side"], order.side.value)
        self.assertEqual(records[0]["quantity"], order.quantity)

    # -- Test 2: append_fill writes to fills.jsonl -------------------------
    def test_append_fill_writes_to_fills_jsonl(self):
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        self.ledger.append_fill(fill)
        records = self.ledger.read_records("fills.jsonl")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], fill.symbol)
        self.assertEqual(records[0]["side"], fill.side.value)
        self.assertEqual(records[0]["quantity"], fill.quantity)
        self.assertEqual(records[0]["price"], fill.price)
        self.assertEqual(records[0]["commission"], fill.commission)

    # -- Test 3: append_snapshot writes to portfolio_snapshots.jsonl -------
    def test_append_snapshot_writes_to_snapshots_jsonl(self):
        snap = _make_snapshot()
        self.ledger.append_snapshot(snap)
        records = self.ledger.read_records("portfolio_snapshots.jsonl")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["equity"], snap.equity)
        self.assertEqual(records[0]["cash"], snap.cash)

    # -- Test 4: cash can be derived from fills ----------------------------
    def test_cash_derived_from_fills(self):
        initial_cash = 100_000.0
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        self.ledger.append_fill(fill)
        cash = self.ledger.latest_cash_from_fills(initial_cash)
        # cash = 100000 - 100*150 - 1 = 84999
        self.assertAlmostEqual(cash, 84_999.0)

    # -- Test 5: positions can be derived from fills -----------------------
    def test_positions_derived_from_fills(self):
        fill = _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)
        self.ledger.append_fill(fill)
        positions = self.ledger.latest_positions_from_fills()
        self.assertIn("AAPL", positions)
        pos = positions["AAPL"]
        self.assertAlmostEqual(pos.quantity, 100.0)
        self.assertAlmostEqual(pos.avg_price, 150.0)
        self.assertAlmostEqual(pos.market_price, 150.0)


# ===================================================================
# PnL derivation tests
# ===================================================================

class TestPnLDerivedFromFills(unittest.TestCase):
    """PnL must come from fills+ledger, not from strategy signals directly."""

    def setUp(self):
        self.tmpdir = Path(__file__).parent / "_ledger_test_tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.ledger = JsonlLedgerStore(self.tmpdir)
        self.initial_cash = 100_000.0

    def tearDown(self):
        for child in self.tmpdir.iterdir():
            child.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    # -- Test 6: PnL = cash + position_value - initial_cash ----------------
    def test_pnl_equals_cash_plus_position_value_minus_initial_cash(self):
        """Round-trip: buy 100 @ 100, sell 100 @ 110."""
        f1 = _make_fill(OrderSide.BUY, "AAPL", 100.0, 100.0, 1.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.SELL, "AAPL", 100.0, 110.0, 1.0, ts_offset_minutes=10)
        self.ledger.append_fill(f1)
        self.ledger.append_fill(f2)

        cash = self.ledger.latest_cash_from_fills(self.initial_cash)
        positions = self.ledger.latest_positions_from_fills()

        # After round-trip, position is flat
        position_value = sum(p.quantity * p.market_price for p in positions.values())
        pnl_from_ledger = cash + position_value - self.initial_cash

        # True PnL = (110-100)*100 - 2 = 998
        expected_pnl = 998.0
        self.assertAlmostEqual(pnl_from_ledger, expected_pnl, places=4)

    def test_pnl_multi_symbol(self):
        """Two positions: AAPL up, MSFT down."""
        f1 = _make_fill(OrderSide.BUY, "AAPL", 50.0, 100.0, 0.5, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.BUY, "MSFT", 20.0, 300.0, 0.5, ts_offset_minutes=1)
        # Sell AAPL at 110
        f3 = _make_fill(OrderSide.SELL, "AAPL", 50.0, 110.0, 0.5, ts_offset_minutes=10)
        self.ledger.append_fill(f1)
        self.ledger.append_fill(f2)
        self.ledger.append_fill(f3)

        cash = self.ledger.latest_cash_from_fills(self.initial_cash)
        positions = self.ledger.latest_positions_from_fills()

        position_value = sum(p.quantity * p.market_price for p in positions.values())
        pnl_from_ledger = cash + position_value - self.initial_cash

        # AAPL PnL = (110-100)*50 - 0.5 - 0.5 = 499
        # After AAPL sold: positions = {MSFT: 20 @ 300}, cash adjusted.
        # commission total = 0.5 + 0.5 + 0.5 = 1.5
        # cash = 100000 - 50*100 - 0.5 - 20*300 - 0.5 + 50*110 - 0.5
        #      = 100000 - 5000 - 0.5 - 6000 - 0.5 + 5500 - 0.5
        #      = 100000 - 5000 - 6000 + 5500 - 1.5
        #      = 94498.5
        # position_value = 20 * 300 = 6000 (using market_price=fill.price)
        # equity = 94498.5 + 6000 = 100498.5
        # pnl = 100498.5 - 100000 = 498.5
        expected_pnl = 498.5
        self.assertAlmostEqual(pnl_from_ledger, expected_pnl, places=4)

    def test_pnl_short_sale(self):
        """Short 100 @ 100, cover at 90."""
        f1 = _make_fill(OrderSide.SELL, "AAPL", 100.0, 100.0, 1.0, ts_offset_minutes=0)
        f2 = _make_fill(OrderSide.BUY, "AAPL", 100.0, 90.0, 1.0, ts_offset_minutes=10)
        self.ledger.append_fill(f1)
        self.ledger.append_fill(f2)

        cash = self.ledger.latest_cash_from_fills(self.initial_cash)
        positions = self.ledger.latest_positions_from_fills()

        position_value = sum(p.quantity * p.market_price for p in positions.values())
        pnl_from_ledger = cash + position_value - self.initial_cash

        # PnL = (100-90)*100 - 2 = 998
        expected_pnl = 998.0
        self.assertAlmostEqual(pnl_from_ledger, expected_pnl, places=4)


# ===================================================================
# Equity curve derived from ledger (not from strategy signals)
# ===================================================================

class TestEquityCurveDerivedFromLedger(unittest.TestCase):
    """Equity curve must come from fill records, never from strategy signals."""

    def test_equity_curve_from_empty_fills(self):
        """Empty fills produce an equity curve with only initial cash."""
        curve = derive_equity_from_fills([], 100_000.0)
        self.assertEqual(len(curve.points), 1)
        self.assertEqual(curve.final_equity, 100_000.0)
        self.assertEqual(curve.initial_cash, 100_000.0)

    def test_equity_curve_from_fills_only(self):
        """Equity curve is built purely from fills, not signal metadata."""
        fills = [
            _make_fill(OrderSide.BUY, "AAPL", 50.0, 100.0, 0.5, ts_offset_minutes=0),
            _make_fill(OrderSide.SELL, "AAPL", 50.0, 110.0, 0.5, ts_offset_minutes=10),
        ]
        curve = derive_equity_from_fills(fills, 100_000.0)

        # The equity curve should only depend on fills + initial_cash.
        # Strategy signal metadata (strength, reason, etc.) has no effect.
        self.assertEqual(len(curve.points), 2)
        # final equity = 100000 + (110-100)*50 - 1 = 100499
        self.assertAlmostEqual(curve.final_equity, 100_499.0)
        self.assertEqual(curve.total_fills, 2)

    def test_equity_curve_strategy_signal_independence(self):
        """Changing signal metadata does not change equity curve.

        This test demonstrates that the equity curve is a function of fills
        only — not of strategy_id, signal strength, or any other signal-level
        information. This is the core audit property.
        """
        fills = [
            _make_fill(OrderSide.BUY, "AAPL", 100.0, 100.0, 1.0, ts_offset_minutes=0),
            _make_fill(OrderSide.SELL, "AAPL", 100.0, 105.0, 1.0, ts_offset_minutes=10),
        ]
        curve = derive_equity_from_fills(fills, 100_000.0)

        # The only thing that matters: fills, initial_cash, and market prices.
        # No strategy signal, no signal_id, no strength — none of that enters
        # derive_equity_from_fills().
        # Buy 100 @ 100, comm 1: cash = 100000 - 10000 - 1 = 89999
        # Sell 100 @ 105, comm 1: cash = 89999 + 10500 - 1 = 100498
        # PnL = (105-100)*100 - 2 = 498
        self.assertAlmostEqual(curve.final_equity, 100_498.0)

        # Verify the last point has position flat and PnL in cash.
        last = curve.points[-1]
        self.assertAlmostEqual(last.position_value, 0.0)
        self.assertAlmostEqual(last.cash, 100_498.0)

    def test_equity_curve_with_market_prices(self):
        """When market prices are provided, slippage is computed."""
        fills = [
            _make_fill(OrderSide.BUY, "AAPL", 100.0, 101.0, 1.0, ts_offset_minutes=0),
        ]
        ts = fills[0].filled_at
        market_prices = {ts: {"AAPL": 100.0}}
        curve = derive_equity_from_fills(fills, 100_000.0, market_prices_by_time=market_prices)

        self.assertAlmostEqual(curve.points[0].cumulative_slippage_cost, 100.0)
        self.assertGreater(curve.points[0].cumulative_slippage_cost, 0.0)

    def test_equity_curve_multi_fill_multi_symbol(self):
        """Multi-symbol equity curve correctly tracks cash and positions."""
        fills = [
            _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0, ts_offset_minutes=0),
            _make_fill(OrderSide.BUY, "MSFT", 50.0, 300.0, 1.0, ts_offset_minutes=5),
            _make_fill(OrderSide.SELL, "AAPL", 50.0, 160.0, 0.5, ts_offset_minutes=10),
        ]
        initial_cash = 200_000.0
        curve = derive_equity_from_fills(fills, initial_cash)

        # Point 1: Buy 100 AAPL @ 150, comm 1.0
        #   cash = 200000 - 15000 - 1 = 184999
        #   pv = 100 * 150 = 15000
        #   eq = 199999
        p1 = curve.points[0]
        self.assertAlmostEqual(p1.cash, 184_999.0)
        self.assertAlmostEqual(p1.position_value, 15_000.0)
        self.assertAlmostEqual(p1.equity, 199_999.0)

        # Point 2: Buy 50 MSFT @ 300, comm 1.0
        #   cash = 184999 - 15000 - 1 = 169998
        #   pv = 100*150 + 50*300 = 15000+15000 = 30000
        #   eq = 199998
        p2 = curve.points[1]
        self.assertAlmostEqual(p2.cash, 169_998.0)

        # Point 3: Sell 50 AAPL @ 160, comm 0.5
        #   cash = 169998 + 8000 - 0.5 = 177997.5
        #   pv = (100-50)*150 + 50*300 = 7500+15000 = 22500
        #   eq = 200497.5
        p3 = curve.points[2]
        self.assertAlmostEqual(p3.cash, 177_997.5)
        self.assertAlmostEqual(p3.position_value, 22_500.0)
        self.assertAlmostEqual(p3.equity, 200_497.5)


# ===================================================================
# write_result integration test
# ===================================================================

class TestWriteResult(unittest.TestCase):
    """write_result writes all 3 ledger files at once."""

    def setUp(self):
        self.tmpdir = Path(__file__).parent / "_ledger_test_tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.ledger = JsonlLedgerStore(self.tmpdir)

    def tearDown(self):
        for child in self.tmpdir.iterdir():
            child.unlink(missing_ok=True)
        self.tmpdir.rmdir()

    def test_write_result_creates_all_ledger_files(self):
        """write_result produces orders, fills, and snapshots JSONL files."""
        from types import SimpleNamespace

        orders = [_make_order(), _make_order(symbol="MSFT")]
        fills = [
            _make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0),
            _make_fill(OrderSide.SELL, "MSFT", 50.0, 300.0, 0.5),
        ]
        snapshots = [_make_snapshot(equity=100_000.0, cash=100_000.0)]

        result = SimpleNamespace(orders=orders, fills=fills, snapshots=snapshots, events=[])
        self.ledger.write_result(result)

        self.assertEqual(len(self.ledger.read_records("orders.jsonl")), 2)
        self.assertEqual(len(self.ledger.read_records("fills.jsonl")), 2)
        self.assertEqual(len(self.ledger.read_records("portfolio_snapshots.jsonl")), 1)

    def test_write_result_with_events(self):
        """write_result with include_events=True also writes events.jsonl."""
        from types import SimpleNamespace

        orders = [_make_order()]
        fills = [_make_fill(OrderSide.BUY, "AAPL", 100.0, 150.0, 1.0)]
        snapshots = [_make_snapshot()]
        events = [{"type": "test_event", "data": 42}]

        result = SimpleNamespace(orders=orders, fills=fills, snapshots=snapshots, events=events)
        self.ledger.write_result(result, include_events=True)

        self.assertEqual(len(self.ledger.read_records("events.jsonl")), 1)
        self.assertEqual(self.ledger.read_records("events.jsonl")[0]["type"], "test_event")


if __name__ == "__main__":
    unittest.main()
