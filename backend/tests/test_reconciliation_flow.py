"""Tests for the full stop-alert-report reconciliation flow.

Covers:
- Clean reconciliation (all four dimensions match)
- Cash mismatch (halt + alert)
- Position mismatch (halt + diff report)
- Order mismatch (detected)
- Fill mismatch (detected)

Uses SimulatedBroker and in-memory ledger -- no connection to real Alpaca.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from quant_us.backtest.broker_simulator import SimulatedBroker
from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import Bar, Fill, Order, new_id
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.live.reconciliation_service import ReconciliationReport, ReconciliationService
from quant_us.monitoring.telegram_alerts import TelegramAlertService


def _make_bar(price: float = 100.0, symbol: str = "AAPL") -> Bar:
    return Bar(
        timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
        symbol=symbol,
        open=price * 0.99,
        high=price * 1.01,
        low=price * 0.98,
        close=price,
        volume=100_000,
    )


def _buy_order(
    bar: Bar,
    qty: float = 100.0,
    client_order_id: str | None = None,
) -> Order:
    return Order(
        timestamp_utc=bar.timestamp_utc,
        strategy_id="test",
        symbol=bar.symbol,
        side=OrderSide.BUY,
        quantity=qty,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id or new_id("coid"),
    )


class TestReconciliationFlow(unittest.TestCase):
    """Test the full stop-alert-report reconciliation flow."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.ledger_dir = self.tmpdir.name
        self.initial_cash = 100_000.0
        self.broker = SimulatedBroker(initial_cash=self.initial_cash)
        self.ledger = JsonlLedgerStore(self.ledger_dir)
        self.service = ReconciliationService(self.ledger_dir, self.broker)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _buy_sync(self, bar: Bar, qty: float = 100.0) -> tuple[Order, list[Fill]]:
        """Submit a buy order to the broker and return (order, fills).

        Does NOT touch the ledger -- caller decides what to record.
        """
        self.broker.update_market(bar)
        order = _buy_order(bar, qty=qty)
        submitted = self.broker.submit_order(order)
        fills = self.broker.get_fills(order_id=submitted.order_id)
        return submitted, fills

    def _record_to_ledger(self, order: Order, fills: list[Fill]) -> None:
        """Record order and fills to the in-memory ledger."""
        self.ledger.append_order(order)
        for fill in fills:
            self.ledger.append_fill(fill)

    # ------------------------------------------------------------------
    # Test: Clean reconciliation  --  all four dimensions match
    # ------------------------------------------------------------------

    def test_clean_reconciliation(self):
        """All four dimensions match between broker and ledger -> status clean."""
        bar = _make_bar(price=150.0)
        order, fills = self._buy_sync(bar, qty=50.0)
        self._record_to_ledger(order, fills)

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "clean")
        self.assertFalse(report.halt_new_orders)
        self.assertFalse(report.alert_sent)
        self.assertAlmostEqual(report.cash_diff, 0.0, places=6)
        self.assertEqual(len(report.position_diffs), 0)
        self.assertEqual(len(report.order_diffs), 0)
        self.assertEqual(len(report.fill_diffs), 0)

        # Verify JSON report file exists and contains correct status
        self.assertTrue(report.report_path.endswith(".json"))
        self.assertTrue(report.report_path.startswith(self.ledger_dir))
        with open(report.report_path) as f:
            data = json.load(f)
        self.assertEqual(data["status"], "clean")
        self.assertFalse(data["halt_new_orders"])

    def test_clean_multiple_symbols(self):
        """Multiple symbols all matching produce clean report."""
        for sym, price in [("AAPL", 150.0), ("MSFT", 300.0), ("GOOGL", 140.0)]:
            bar = _make_bar(price=price, symbol=sym)
            order, fills = self._buy_sync(bar, qty=30.0)
            self._record_to_ledger(order, fills)

        report = self.service.reconcile_all(initial_cash=self.initial_cash)
        self.assertEqual(report.status, "clean")

    # ------------------------------------------------------------------
    # Test: Cash mismatch  --  triggers halt + alert
    # ------------------------------------------------------------------

    def test_cash_mismatch_halt_and_alert(self):
        """Broker cash differs from ledger-derived cash -> halt, alert sent."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=100.0)
        # Record order but NOT fills to the ledger.
        # Broker cash has been reduced by the fills; local cash stays at initial_cash.
        self._record_to_ledger(order, [])

        mock_alerts = MagicMock(spec=TelegramAlertService)

        report = self.service.reconcile_all(
            initial_cash=self.initial_cash,
            telegram_alerts=mock_alerts,
        )

        self.assertEqual(report.status, "breaks_detected")
        self.assertTrue(report.halt_new_orders)
        self.assertTrue(report.alert_sent)
        self.assertNotEqual(report.cash_diff, 0.0)

        # Alert was dispatched with CRITICAL priority
        mock_alerts.send.assert_called_once()
        call_args, call_kwargs = mock_alerts.send.call_args
        message = call_args[0] if call_args else call_kwargs.get("message", "")
        priority = call_kwargs.get("priority", "")
        self.assertIn("critical", str(priority))

    def test_cash_mismatch_no_alert_when_not_configured(self):
        """When telegram_alerts is None, alert_sent stays False."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=50.0)
        self._record_to_ledger(order, [])  # no fills recorded

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "breaks_detected")
        self.assertFalse(report.alert_sent)  # no alert service passed

    # ------------------------------------------------------------------
    # Test: Position mismatch  --  triggers halt + diff report
    # ------------------------------------------------------------------

    def test_position_mismatch_halt_and_report(self):
        """Position quantity differs -> halt, report file generated, diffs present."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=100.0)
        # Record order but NOT fills -- broker has position, ledger does not
        self._record_to_ledger(order, [])

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "breaks_detected")
        self.assertTrue(report.halt_new_orders)
        self.assertIn("AAPL", report.position_diffs)
        self.assertEqual(report.position_diffs["AAPL"]["broker_quantity"], 100.0)
        self.assertEqual(report.position_diffs["AAPL"]["local_quantity"], 0.0)
        self.assertAlmostEqual(
            report.position_diffs["AAPL"]["quantity_diff"], 100.0, places=6,
        )

        # Report file on disk matches
        with open(report.report_path) as f:
            data = json.load(f)
        self.assertIn("AAPL", data["position_diffs"])
        self.assertTrue(data["halt_new_orders"])

    def test_position_mismatch_wrong_qty(self):
        """Broker and ledger both have a symbol but quantities differ."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=100.0)
        # Record with wrong fill quantity
        if fills:
            modified_fill = Fill(
                order_id=fills[0].order_id,
                symbol=fills[0].symbol,
                side=fills[0].side,
                quantity=fills[0].quantity - 30,  # 70 vs 100
                price=fills[0].price,
                commission=fills[0].commission,
                filled_at=fills[0].filled_at,
                fill_id=fills[0].fill_id,
            )
            self._record_to_ledger(order, [modified_fill])
        else:
            self._record_to_ledger(order, [])

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "breaks_detected")
        self.assertIn("AAPL", report.position_diffs)
        self.assertAlmostEqual(
            report.position_diffs["AAPL"]["quantity_diff"], 30.0, delta=1.0,
        )

    # ------------------------------------------------------------------
    # Test: Order mismatch  --  detected in report
    # ------------------------------------------------------------------

    def test_order_mismatch_detected(self):
        """Order missing in ledger is detected."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=50.0)
        # Do NOT record order to ledger -- broker has it, ledger does not
        # (fills also not recorded)

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "breaks_detected")
        self.assertGreater(len(report.order_diffs), 0)

        # At least one order diff reports "MISSING" on local side
        missing_found = any(
            d.get("local_status") == "MISSING"
            for d in report.order_diffs.values()
        )
        self.assertTrue(
            missing_found,
            f"Expected at least one order diff with local_status='MISSING', "
            f"got: {report.order_diffs}",
        )

    def test_order_mismatch_same_status_different_quantity_detected(self):
        """Same order_id and status with conflicting local qty is a reconciliation break."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, _fills = self._buy_sync(bar, qty=50.0)
        local_order_1 = Order(
            timestamp_utc=order.timestamp_utc,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=45.0,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            status=order.status,
            created_at=order.created_at,
            updated_at=order.updated_at,
            order_id=order.order_id,
        )
        local_order_2 = Order(
            timestamp_utc=order.timestamp_utc,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=50.0,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            client_order_id=order.client_order_id,
            broker_order_id=order.broker_order_id,
            status=order.status,
            created_at=order.created_at,
            updated_at=order.updated_at,
            order_id=order.order_id,
        )

        self.ledger.append_order(local_order_1)
        self.ledger.append_order(local_order_2)
        diffs = self.service._compare_orders(
            self.ledger.read_records("orders.jsonl"),
            [order],
        )

        self.assertIn(order.order_id, diffs)
        self.assertTrue(diffs[order.order_id]["local_conflict"])
        self.assertEqual(diffs[order.order_id]["local_statuses"], [order.status.value])
        self.assertEqual(diffs[order.order_id]["local_quantities"], [45.0, 50.0])

    def test_compare_orders_accepts_plain_string_broker_status(self):
        """Broker adapters may return string status values, not only enums."""
        diffs = self.service._compare_orders(
            [{"order_id": "ord_plain", "status": "filled", "quantity": 25.0}],
            [SimpleNamespace(order_id="ord_plain", status="filled", quantity=25.0)],
        )

        self.assertEqual(diffs, {})

    # ------------------------------------------------------------------
    # Test: Fill mismatch  --  detected in report
    # ------------------------------------------------------------------

    def test_fill_mismatch_detected(self):
        """Fill quantity recorded in ledger differs from broker fill."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=100.0)
        # Record order, then record fills with modified quantity
        modified_fills = []
        for fill in fills:
            modified = Fill(
                order_id=fill.order_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity - 10,  # differ by 10
                price=fill.price,
                commission=fill.commission,
                filled_at=fill.filled_at,
                fill_id=fill.fill_id,  # same fill_id for direct comparison
            )
            modified_fills.append(modified)
        self._record_to_ledger(order, modified_fills)

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "breaks_detected")
        self.assertGreater(len(report.fill_diffs), 0)
        # At least one diff has a quantity difference
        qty_diff_found = any(
            "quantity_diff" in d
            for d in report.fill_diffs.values()
        )
        self.assertTrue(
            qty_diff_found,
            f"Expected at least one fill diff with quantity_diff, "
            f"got: {report.fill_diffs}",
        )

    def test_fill_mismatch_same_fill_id_different_price_or_commission_detected(self):
        """Same fill_id with conflicting local price/commission is a break."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=100.0)
        self.assertTrue(fills)
        broker_fill = fills[0]
        local_fill_1 = Fill(
            order_id=broker_fill.order_id,
            symbol=broker_fill.symbol,
            side=broker_fill.side,
            quantity=broker_fill.quantity,
            price=broker_fill.price - 1.5,
            commission=broker_fill.commission + 0.25,
            filled_at=broker_fill.filled_at,
            fill_id=broker_fill.fill_id,
        )
        local_fill_2 = Fill(
            order_id=broker_fill.order_id,
            symbol=broker_fill.symbol,
            side=broker_fill.side,
            quantity=broker_fill.quantity,
            price=broker_fill.price,
            commission=broker_fill.commission,
            filled_at=broker_fill.filled_at,
            fill_id=broker_fill.fill_id,
        )
        self.ledger.append_fill(local_fill_1)
        self.ledger.append_fill(local_fill_2)

        diffs = self.service._compare_fills(
            self.ledger.read_records("fills.jsonl"),
            [broker_fill],
        )

        self.assertIn(broker_fill.fill_id, diffs)
        self.assertTrue(diffs[broker_fill.fill_id]["local_conflict"])
        self.assertEqual(
            diffs[broker_fill.fill_id]["local_quantities"],
            [broker_fill.quantity],
        )
        self.assertEqual(
            diffs[broker_fill.fill_id]["local_prices"],
            [broker_fill.price - 1.5, broker_fill.price],
        )
        self.assertEqual(
            diffs[broker_fill.fill_id]["local_commissions"],
            [broker_fill.commission, broker_fill.commission + 0.25],
        )

    def test_compare_fills_uses_order_id_fallback_for_broker_fill_without_fill_id(self):
        """A broker fill without fill_id must still match the local order_id fallback."""
        local = {
            "order_id": "ord_fallback",
            "fill_id": "",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 12.0,
            "price": 150.0,
            "commission": 0.05,
        }
        broker_fill = SimpleNamespace(
            order_id="ord_fallback",
            fill_id="",
            symbol="AAPL",
            side="buy",
            quantity=12.0,
            price=150.0,
            commission=0.05,
        )

        diffs = self.service._compare_fills([local], [broker_fill])

        self.assertEqual(diffs, {})

    def test_fill_missing_from_ledger_detected(self):
        """Fill exists in broker but not in ledger -> detected."""
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=50.0)
        # Record order but not fills
        self._record_to_ledger(order, [])

        report = self.service.reconcile_all(initial_cash=self.initial_cash)

        self.assertEqual(report.status, "breaks_detected")
        # Should have "broker_only" entries in fill diffs
        broker_only_found = any(
            d.get("broker_only")
            for d in report.fill_diffs.values()
        )
        self.assertTrue(
            broker_only_found,
            f"Expected at least one fill diff marked broker_only, "
            f"got: {report.fill_diffs}",
        )

    # ------------------------------------------------------------------
    # Test: PaperTradingLoop integration  --  halt flag
    # ------------------------------------------------------------------

    def test_paper_loop_halt_on_reconciliation_break(self):
        """PaperTradingLoop sets halt and is_healthy() returns False after break."""
        from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop

        config = PaperTradingConfig(ledger_root=self.ledger_dir)
        loop = PaperTradingLoop(config=config)
        # Override broker with our pre-configured one that has a trade
        loop.broker = self.broker
        loop.ledger = self.ledger
        loop._reconciliation_service = self.service

        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=50.0)
        # Record order but NOT fills to create a mismatch
        self._record_to_ledger(order, [])

        recon_result = loop._reconcile()

        self.assertFalse(recon_result["passed"])
        self.assertTrue(loop._halt_reconciliation)
        self.assertFalse(loop.is_healthy())

    def test_paper_loop_clean_recon_clears_halt(self):
        """After a clean reconciliation, halt is cleared and is_healthy() OK."""
        from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop

        config = PaperTradingConfig(ledger_root=self.ledger_dir)
        loop = PaperTradingLoop(config=config)
        loop.broker = self.broker
        loop.ledger = self.ledger
        loop._reconciliation_service = self.service

        # First cause a break
        bar = _make_bar(price=150.0, symbol="AAPL")
        order, fills = self._buy_sync(bar, qty=50.0)
        self._record_to_ledger(order, [])
        loop._reconcile()
        self.assertTrue(loop._halt_reconciliation)
        self.assertFalse(loop.is_healthy())

        # Then fix by recording fills and re-reconciling
        for fill in fills:
            self.ledger.append_fill(fill)
        loop._reconcile()
        self.assertFalse(loop._halt_reconciliation)
        self.assertTrue(loop.is_healthy())


if __name__ == "__main__":
    unittest.main()
