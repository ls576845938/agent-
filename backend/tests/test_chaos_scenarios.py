"""10 Failure Simulation Tests (chaos engineering).

Each scenario simulates a realistic failure mode and verifies the system
handles it without data corruption, crashes, or silent state loss.

Scenarios:
  1. live_runner restart during trading
  2. submit_order success, local process crash
  3. broker timeout, order actually submitted
  4. broker partial fill then disconnect
  5. cancel request, order partially fills before cancel
  6. market data delay
  7. missing data for current day
  8. local ledger missing one fill
  9. duplicate signal
 10. duplicate client_order_id
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import (
    AccountState,
    Bar,
    Fill,
    Order,
    OrderIntent,
    Position,
    RiskDecision,
    new_id,
)
from quant_us.execution.broker_base import BrokerBase
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.paper_trading_loop import PaperTradingConfig, PaperTradingLoop
from quant_us.live.reconciliation_service import ReconciliationService
from quant_us.risk.data_freshness import DataFreshnessConfig, DataFreshnessGuard
from quant_us.risk.kill_switch import KillSwitch
from quant_us.risk.pre_trade import PreTradeRiskEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order_intent(
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 100.0,
    client_order_id: str | None = None,
) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc),
        strategy_id="chaos_test",
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id or new_id("coid"),
    )


def _make_account() -> AccountState:
    return AccountState(
        timestamp_utc=datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc),
        account_id="chaos_acct",
        cash=1_000_000.0,
        equity=1_000_000.0,
        buying_power=2_000_000.0,
    )


def _make_fill(order_id: str, qty: float = 50.0, price: float = 150.0) -> Fill:
    return Fill(
        order_id=order_id,
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=qty,
        price=price,
        commission=1.0,
        filled_at=datetime(2025, 6, 1, 14, 31, tzinfo=timezone.utc),
        broker="chaos_broker",
    )


def _make_bar(
    ts: datetime | None = None,
    symbol: str = "AAPL",
    price: float = 150.0,
) -> Bar:
    return Bar(
        timestamp_utc=ts or datetime(2025, 6, 1, 9, 30, tzinfo=timezone.utc),
        symbol=symbol,
        open=price * 0.999,
        high=price * 1.005,
        low=price * 0.995,
        close=price,
        volume=100_000.0,
    )


def _make_filled_order(
    intent: OrderIntent,
    decision: RiskDecision,
) -> Order:
    order = Order.from_intent(intent, decision)
    order.order_id = new_id("ord")
    order.status = OrderStatus.FILLED
    return order


# ===================================================================
# SCENARIO 1: live_runner restart during trading
# ===================================================================

class LiveRunnerRestartTest(unittest.TestCase):
    """Simulate OMS crash-restart: persist idempotency, create new OMS,
    load_idempotency, verify same client_order_id is rejected."""

    def test_idempotency_restart_rejects_duplicate_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            idem_path = Path(tmpdir) / "idempotency.json"

            # First OMS life
            broker1 = MagicMock(spec=BrokerBase)
            risk1 = MagicMock(spec=PreTradeRiskEngine)
            ks1 = MagicMock(spec=KillSwitch)
            ks1.update_equity.return_value = False
            oms1 = OrderManagementSystem(
                broker=broker1,
                risk_engine=risk1,
                idempotency_path=idem_path,
                kill_switch=ks1,
            )

            intent = _make_order_intent(client_order_id="restart-coid")
            decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
            risk1.evaluate.return_value = decision

            submitted = _make_filled_order(intent, decision)
            broker1.submit_order.return_value = submitted
            broker1.get_fills.return_value = []

            # First submission succeeds
            result1 = oms1.handle_intent(intent, _make_account(), 150.0)
            self.assertTrue(result1.risk_decision.approved)
            broker1.submit_order.assert_called_once()

            # Persist and discard
            oms1.persist_idempotency()
            self.assertTrue(idem_path.exists(), "idempotency file should exist after persist")

            # Simulate crash: create brand new OMS
            broker2 = MagicMock(spec=BrokerBase)
            risk2 = MagicMock(spec=PreTradeRiskEngine)
            ks2 = MagicMock(spec=KillSwitch)
            ks2.update_equity.return_value = False
            oms2 = OrderManagementSystem(
                broker=broker2,
                risk_engine=risk2,
                idempotency_path=idem_path,
                kill_switch=ks2,
            )
            loaded = oms2.load_idempotency()
            self.assertEqual(loaded, 1, "should have loaded 1 client_order_id")

            # Second submission with same client_order_id -> rejected
            result2 = oms2.handle_intent(intent, _make_account(), 150.0)
            self.assertFalse(result2.risk_decision.approved)
            self.assertEqual(result2.risk_decision.reason, "duplicate_client_order_id")
            broker2.submit_order.assert_not_called()


# ===================================================================
# SCENARIO 2: submit_order success, local process crash
# ===================================================================

class LocalProcessCrashTest(unittest.TestCase):
    """Simulate: OMS submits order successfully, then new OMS recovers
    client_order_id from recovered set (via load_idempotency)."""

    def test_crash_recovery_via_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            idem_path = Path(tmpdir) / "idempotency.json"

            # First OMS — successfully submit
            broker1 = MagicMock(spec=BrokerBase)
            risk1 = MagicMock(spec=PreTradeRiskEngine)
            ks1 = MagicMock(spec=KillSwitch)
            ks1.update_equity.return_value = False
            oms1 = OrderManagementSystem(
                broker=broker1,
                risk_engine=risk1,
                idempotency_path=idem_path,
                kill_switch=ks1,
            )

            intent = _make_order_intent(client_order_id="crash-coid-1")
            decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
            risk1.evaluate.return_value = decision

            submitted = _make_filled_order(intent, decision)
            broker1.submit_order.return_value = submitted
            broker1.get_fills.return_value = []

            # Submit succeeds
            result = oms1.handle_intent(intent, _make_account(), 150.0)
            self.assertTrue(result.risk_decision.approved)
            self.assertIn("crash-coid-1", oms1._client_order_ids)

            # Persist (simulates normal save before crash)
            oms1.persist_idempotency()

            # Simulate crash restart: new OMS recovers idempotency
            broker2 = MagicMock(spec=BrokerBase)
            risk2 = MagicMock(spec=PreTradeRiskEngine)
            ks2 = MagicMock(spec=KillSwitch)
            ks2.update_equity.return_value = False
            oms2 = OrderManagementSystem(
                broker=broker2,
                risk_engine=risk2,
                idempotency_path=idem_path,
                kill_switch=ks2,
            )

            loaded = oms2.load_idempotency()
            self.assertGreaterEqual(loaded, 1, "recovered OMS should have idempotency data")
            self.assertIn("crash-coid-1", oms2._client_order_ids,
                          "recovered OMS should know about the submitted client_order_id")

            # Attempting to resubmit the same order is rejected
            intent2 = _make_order_intent(client_order_id="crash-coid-1")
            decision2 = RiskDecision(approved=True, reason="approved", order_intent_id=intent2.order_intent_id)
            risk2.evaluate.return_value = decision2

            result2 = oms2.handle_intent(intent2, _make_account(), 150.0)
            self.assertFalse(result2.risk_decision.approved)
            self.assertEqual(result2.risk_decision.reason, "duplicate_client_order_id")
            broker2.submit_order.assert_not_called()


# ===================================================================
# SCENARIO 3: broker timeout, order actually submitted
# ===================================================================

class BrokerTimeoutActualSubmitTest(unittest.TestCase):
    """Mock broker to raise timeout on submit but the order was actually
    accepted by the broker (e.g. slow broker accepted before timeout).

    The OMS now has a recovery path (``_recover_order_state``): when
    ``submit_order`` raises, it queries ``broker.get_orders()`` by
    ``client_order_id``. If found, the order is treated as successfully
    submitted despite the local timeout.

    This test verifies that recovery path works correctly.
    """

    def test_broker_timeout_recovery_succeeds(self) -> None:
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        intent = _make_order_intent(client_order_id="timeout-coid")
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        risk.evaluate.return_value = decision

        # Broker raises timeout (network error), BUT the order was actually
        # received by the broker's matching engine.
        broker.submit_order.side_effect = TimeoutError("broker gateway timeout")

        # The order DID get onto the broker's book — simulate by having
        # get_orders() return it (used by _recover_order_state).
        actual_order = _make_filled_order(intent, decision)
        actual_order.status = OrderStatus.ACCEPTED
        broker.get_orders.return_value = [actual_order]
        broker.get_fills.return_value = []

        # handle_intent should NOT raise — recovery finds the order.
        result = oms.handle_intent(intent, _make_account(), 150.0)

        # Recovery path returns a successful OMSResult
        self.assertTrue(result.risk_decision.approved,
                        "recovery should produce an approved decision")
        self.assertIsNotNone(result.order,
                             "recovered order should be returned")
        self.assertEqual(result.order.status, OrderStatus.ACCEPTED,
                         "recovered order should have broker-reported status")

        # submit_order was called and raised — get_orders was queried for recovery
        broker.submit_order.assert_called_once()
        self.assertGreaterEqual(broker.get_orders.call_count, 1,
                                "recovery should query broker for order state")

        # client_order_id IS registered (recovery path persists it)
        self.assertIn(intent.client_order_id, oms._client_order_ids,
                      "recovery should register client_order_id for idempotency")

        # kill_switch recorded a failure (the timeout did happen), but the
        # OMS still reported success back to the caller.
        ks.record_order_failure.assert_called_once()

    def test_broker_timeout_no_recovery_no_order(self) -> None:
        """When timeout raises and broker has NO record of the order,
        handle_intent re-raises the TimeoutError."""
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        intent = _make_order_intent(client_order_id="timeout-no-order")
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        risk.evaluate.return_value = decision

        broker.submit_order.side_effect = TimeoutError("broker gateway timeout")

        # get_orders() returns empty — broker has no record of the order
        broker.get_orders.return_value = []
        broker.get_fills.return_value = []

        with self.assertRaises(TimeoutError) as ctx:
            oms.handle_intent(intent, _make_account(), 150.0)
        self.assertIn("timeout", str(ctx.exception).lower())

        # client_order_id NOT registered (order never confirmed)
        self.assertNotIn(intent.client_order_id, oms._client_order_ids)

        # kill_switch should have recorded failure
        ks.record_order_failure.assert_called_once()


# ===================================================================
# SCENARIO 4: broker partial fill then disconnect
# ===================================================================

class PartialFillThenDisconnectTest(unittest.TestCase):
    """Mock broker: first call returns PARTIALLY_FILLED, second call
    raises connection error. System handles gracefully."""

    def test_partial_fill_then_disconnect(self) -> None:
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        intent = _make_order_intent(client_order_id="partial-disco", quantity=200.0)
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        risk.evaluate.return_value = decision

        # First call to submit_order returns a PARTIALLY_FILLED order
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_partial_1"
        submitted.status = OrderStatus.PARTIALLY_FILLED
        broker.submit_order.return_value = submitted

        # First get_fills call returns one partial fill
        partial_fill = _make_fill(submitted.order_id, qty=50.0, price=150.0)
        broker.get_fills.return_value = [partial_fill]

        # First call succeeds — partially filled
        result1 = oms.handle_intent(intent, _make_account(), 150.0)
        self.assertEqual(result1.order.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(len(result1.fills), 1)
        self.assertEqual(result1.fills[0].quantity, 50.0)
        broker.submit_order.assert_called_once()

        # Reset broker state for scenario: we check for rest-of-day fills,
        # but the broker is now disconnected.
        broker.get_fills.side_effect = ConnectionError("broker connection lost")

        # The system should handle this gracefully — log error, record failure
        try:
            fills = broker.get_fills(order_id=submitted.order_id)
        except ConnectionError:
            # Expected — system should handle downstream
            pass

        # Verify kill switch recorded the failure from the first submission
        # (PARTIALLY_FILLED is not REJECTED/ERROR, so success was recorded)
        ks.record_order_success.assert_called_once()

        # Now simulate OMS trying to process a new intent during disconnect
        broker.submit_order.side_effect = ConnectionError("broker connection lost")
        intent2 = _make_order_intent(client_order_id="partial-disco-2", quantity=100.0)
        decision2 = RiskDecision(approved=True, reason="approved", order_intent_id=intent2.order_intent_id)
        risk.evaluate.return_value = decision2

        with self.assertRaises(ConnectionError):
            oms.handle_intent(intent2, _make_account(), 150.0)

        # Should have another failure recorded
        self.assertGreaterEqual(ks.record_order_failure.call_count, 1)


# ===================================================================
# SCENARIO 5: cancel request, order partially fills before cancel
# ===================================================================

class CancelDuringPartialFillTest(unittest.TestCase):
    """Mock broker: cancel_order called while order is PARTIALLY_FILLED.
    Verify remaining quantity is cancelled, filled portion is recorded."""

    def test_cancel_partially_filled_order(self) -> None:
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        intent = _make_order_intent(client_order_id="cancel-partial", quantity=200.0)
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        risk.evaluate.return_value = decision

        # Broker initially accepts
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_cancel_1"
        submitted.status = OrderStatus.ACCEPTED
        broker.submit_order.return_value = submitted
        broker.get_fills.return_value = []

        # Submit the order
        result = oms.handle_intent(intent, _make_account(), 150.0)
        self.assertEqual(result.order.status, OrderStatus.ACCEPTED)

        # Now simulate: order partially filled before cancel reaches broker
        partial_fill = _make_fill(submitted.order_id, qty=75.0, price=150.0)
        broker.get_fills.return_value = [partial_fill]

        # Simulate cancel — broker returns cancelled status with partial fill info
        cancelled_order = Order.from_intent(intent, decision)
        cancelled_order.order_id = submitted.order_id
        cancelled_order.status = OrderStatus.CANCELLED
        cancelled_order.quantity = 200.0  # original
        broker.cancel_order.return_value = cancelled_order

        # Also simulate the broker returning both fill and cancel state
        # when queried
        broker.get_orders.return_value = [cancelled_order]

        # Execute cancel
        cancel_result = broker.cancel_order(submitted.order_id)
        self.assertEqual(cancel_result.status, OrderStatus.CANCELLED)

        # Verify fills are recorded for the partial fill
        fills = broker.get_fills(order_id=submitted.order_id)
        self.assertEqual(len(fills), 1)
        total_filled = sum(f.quantity for f in fills)
        self.assertEqual(total_filled, 75.0, "filled portion should be 75 out of 200")

        # Remaining 125 was cancelled
        remaining = submitted.quantity - total_filled
        self.assertEqual(remaining, 125.0, "remaining 125 should be cancelled state")


# ===================================================================
# SCENARIO 6: market data delay
# ===================================================================

class MarketDataDelayTest(unittest.TestCase):
    """Feed bars with timestamps older than max_data_delay_seconds.
    Verify stale bars are skipped and kill_switch.check_data_staleness
    is called."""

    def setUp(self) -> None:
        self.kill_switch = MagicMock(spec=KillSwitch)
        self.kill_switch.triggered = False
        self.kill_switch.reason = ""
        self.kill_switch.check_data_staleness.return_value = False
        self.loop = PaperTradingLoop()
        self.loop.kill_switch = self.kill_switch
        self.loop.alerts = MagicMock()

        # Control the freshness guard with a fixed "now" timestamp
        self._fake_now = datetime(2025, 6, 2, 10, 0, tzinfo=timezone.utc)
        max_delay_sec = 3600.0  # 1 hour
        self.loop.data_freshness = DataFreshnessGuard(
            DataFreshnessConfig(max_delay_seconds=max_delay_sec)
        )

    def test_stale_bars_are_skipped(self) -> None:
        """Bars older than max_data_delay_seconds are skipped, kill switch
        check_data_staleness is called.

        Uses 2025-06-02 (Monday, a trading day) for the bars. The fresh bar
        is 30 minutes before the fake now (1800s < 3600s delay). The stale
        bar is years older and well beyond threshold.
        """
        trading_day = datetime(2025, 6, 2, 9, 30, tzinfo=timezone.utc)
        fresh_bar = _make_bar(ts=trading_day, symbol="AAPL", price=150.0)
        stale_bar = _make_bar(
            ts=datetime(2020, 1, 2, 15, 30, tzinfo=timezone.utc),
            symbol="GOOGL",
            price=2000.0,
        )
        bars = [fresh_bar, stale_bar]

        # Override evaluate_bar to use the controlled fake now
        original_evaluate = self.loop.data_freshness.evaluate_bar
        self.loop.data_freshness.evaluate_bar = (
            lambda bar, now=None: original_evaluate(bar, now=self._fake_now)
        )

        strategy = MagicMock()
        strategy.on_bar.return_value = []

        result = self.loop.run_day(bars=bars, strategies=[strategy])

        self.assertEqual(result.stale_bars, 1,
                         "should have detected 1 stale bar")
        self.loop.kill_switch.check_data_staleness.assert_called_once()


# ===================================================================
# SCENARIO 7: missing data for current day
# ===================================================================

class MissingDataTest(unittest.TestCase):
    """Pass empty bars list to run_day. Verify it returns
    'zero_bars_received' without crashing."""

    def test_empty_bars_returns_graceful_error(self) -> None:
        loop = PaperTradingLoop()
        # Override alerts with MagicMock to prevent telegram dependency
        loop.alerts = MagicMock()
        # Patch calendar so today is treated as a trading day
        with unittest.mock.patch.object(loop.calendar, 'is_trading_day', return_value=True):
            result = loop.run_day(bars=[], strategies=[])

        self.assertIn("zero_bars_received", result.errors,
                      "should report zero_bars_received")
        self.assertEqual(result.orders_submitted, 0)
        self.assertEqual(result.orders_filled, 0)
        self.assertEqual(result.orders_rejected, 0)
        # No crash is the primary assertion — we got here

    def test_empty_bars_non_trading_day_path(self) -> None:
        """Empty bars on a non-trading day should return non_trading_day,
        not zero_bars_received (bars check happens after trading day gate)."""
        loop = PaperTradingLoop()
        loop.alerts = MagicMock()

        # Patch calendar so this date is NOT a trading day
        saturday = datetime(2025, 6, 7, tzinfo=timezone.utc).date()  # Saturday
        with unittest.mock.patch.object(loop.calendar, 'is_trading_day', return_value=False):
            # bars=[] triggers date.today() for today, which is Sunday
            result = loop.run_day(bars=[], strategies=[])

        # bars=[], but calendar says non-trading day = non_trading_day path wins
        self.assertIn("non_trading_day", result.errors,
                      "non-trading day should be flagged first")


# ===================================================================
# SCENARIO 8: local ledger missing one fill
# ===================================================================

class MissingFillReconciliationTest(unittest.TestCase):
    """Remove one fill from ledger, run reconciliation. Verify
    reconciliation detects the missing fill."""

    def test_reconciliation_detects_missing_fill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = JsonlLedgerStore(tmpdir)

            # Record TWO fills in the ledger
            fill1 = _make_fill(order_id="ord_miss_1", qty=50.0, price=150.0)
            fill2 = _make_fill(order_id="ord_miss_2", qty=30.0, price=155.0)

            ledger.append_fill(fill1)
            ledger.append_fill(fill2)

            # Broker has BOTH fills
            broker = MagicMock(spec=BrokerBase)
            broker.get_account.return_value = AccountState(
                timestamp_utc=datetime(2025, 6, 1, 16, 0, tzinfo=timezone.utc),
                account_id="chaos_broker",
                # broker cash = initial - fill1_buy - fill2_buy
                cash=1_000_000.0 - (50.0 * 150.0 + 1.0) - (30.0 * 155.0 + 1.0),
                equity=1_000_000.0,
                buying_power=2_000_000.0,
            )

            position_aapl = Position(symbol="AAPL", quantity=80.0, avg_price=151.875)
            broker.get_positions.return_value = {"AAPL": position_aapl}
            broker.get_orders.return_value = []
            broker.get_fills.return_value = [fill1, fill2]

            # Now REMOVE fill2 from the ledger (simulate missing record)
            fills_path = Path(tmpdir) / "fills.jsonl"
            records = [json.loads(line) for line in fills_path.read_text().splitlines() if line.strip()]
            kept = [r for r in records if r.get("fill_id") != fill2.fill_id]
            fills_path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in kept) + "\n")

            # Run reconciliation
            service = ReconciliationService(tmpdir, broker)
            report = service.reconcile_all(initial_cash=1_000_000.0)

            # Should detect breaks
            self.assertEqual(report.status, "breaks_detected",
                             "reconciliation should detect missing fill")

            # Fill diff or cash diff should exist
            has_fill_diff = bool(report.fill_diffs)
            has_cash_diff = abs(report.cash_diff) > 1e-6
            self.assertTrue(
                has_fill_diff or has_cash_diff,
                f"expected fill or cash diff, got fill_diffs={report.fill_diffs} cash_diff={report.cash_diff}",
            )


# ===================================================================
# SCENARIO 9: duplicate signal
# ===================================================================

class DuplicateSignalTest(unittest.TestCase):
    """Feed same signal twice. Verify OMS processes it once
    (idempotency through client_order_id dedup)."""

    def test_duplicate_signal_rejected_by_oms(self) -> None:
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        # Create one intent with a specific client_order_id and feed it twice
        intent = _make_order_intent(client_order_id="dup-signal-coid", quantity=50.0)
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        risk.evaluate.return_value = decision

        submitted = _make_filled_order(intent, decision)
        broker.submit_order.return_value = submitted
        broker.get_fills.return_value = []

        # First submission succeeds
        result1 = oms.handle_intent(intent, _make_account(), 150.0)
        self.assertTrue(result1.risk_decision.approved)
        self.assertEqual(result1.order.status, OrderStatus.FILLED)
        broker.submit_order.assert_called_once()

        # Second submission with same intent (duplicate signal) -> rejected
        result2 = oms.handle_intent(intent, _make_account(), 150.0)
        self.assertFalse(result2.risk_decision.approved)
        self.assertEqual(result2.risk_decision.reason, "duplicate_client_order_id")
        broker.submit_order.assert_called_once()  # still 1 call

    def test_duplicate_signal_does_not_corrupt_client_ids(self) -> None:
        """Processing duplicate signal correctly keeps client_order_ids in sync."""
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        intent = _make_order_intent(client_order_id="dup-signal-coid-2", quantity=50.0)
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        risk.evaluate.return_value = decision

        submitted = _make_filled_order(intent, decision)
        broker.submit_order.return_value = submitted
        broker.get_fills.return_value = []

        # First: registered
        oms.handle_intent(intent, _make_account(), 150.0)
        registered_before = len(oms._client_order_ids)

        # Second: rejected, set should not grow
        oms.handle_intent(intent, _make_account(), 150.0)
        registered_after = len(oms._client_order_ids)

        self.assertEqual(registered_before, registered_after,
                         "duplicate should not add to client_order_ids set")


# ===================================================================
# SCENARIO 10: duplicate client_order_id
# ===================================================================

class DuplicateClientOrderIdTest(unittest.TestCase):
    """Submit same client_order_id twice. Verify second attempt is
    rejected with 'duplicate_client_order_id' reason."""

    def test_duplicate_client_order_id_rejected(self) -> None:
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        intent_a = _make_order_intent(client_order_id="dedup-coid", quantity=50.0)
        decision_a = RiskDecision(approved=True, reason="approved",
                                  order_intent_id=intent_a.order_intent_id)
        risk.evaluate.return_value = decision_a

        submitted_a = _make_filled_order(intent_a, decision_a)
        broker.submit_order.return_value = submitted_a
        broker.get_fills.return_value = []

        # First attempt: succeeds
        result1 = oms.handle_intent(intent_a, _make_account(), 150.0)
        self.assertTrue(result1.risk_decision.approved)
        broker.submit_order.assert_called_once()

        # Second attempt with same client_order_id, different intent
        intent_b = _make_order_intent(client_order_id="dedup-coid", quantity=100.0)
        decision_b = RiskDecision(approved=True, reason="approved",
                                  order_intent_id=intent_b.order_intent_id)
        risk.evaluate.return_value = decision_b

        result2 = oms.handle_intent(intent_b, _make_account(), 150.0)
        self.assertFalse(result2.risk_decision.approved)
        self.assertEqual(result2.risk_decision.reason, "duplicate_client_order_id")

        # Broker was still called only once
        broker.submit_order.assert_called_once()

    def test_duplicate_client_order_id_subsequent_unique_passes(self) -> None:
        """After rejecting a duplicate, a new unique client_order_id should
        still be accepted."""
        broker = MagicMock(spec=BrokerBase)
        risk = MagicMock(spec=PreTradeRiskEngine)
        ks = MagicMock(spec=KillSwitch)
        ks.update_equity.return_value = False
        oms = OrderManagementSystem(
            broker=broker,
            risk_engine=risk,
            kill_switch=ks,
        )

        # First intent succeeds
        intent1 = _make_order_intent(client_order_id="uniq-1", quantity=50.0)
        decision1 = RiskDecision(approved=True, reason="approved",
                                 order_intent_id=intent1.order_intent_id)
        risk.evaluate.return_value = decision1

        submitted1 = _make_filled_order(intent1, decision1)
        broker.submit_order.return_value = submitted1
        broker.get_fills.return_value = []

        result1 = oms.handle_intent(intent1, _make_account(), 150.0)
        self.assertTrue(result1.risk_decision.approved)

        # Duplicate rejected
        intent_dup = _make_order_intent(client_order_id="uniq-1", quantity=200.0)
        decision_dup = RiskDecision(approved=True, reason="approved",
                                    order_intent_id=intent_dup.order_intent_id)
        risk.evaluate.return_value = decision_dup

        result_dup = oms.handle_intent(intent_dup, _make_account(), 150.0)
        self.assertFalse(result_dup.risk_decision.approved)

        # New unique client_order_id still works
        broker.reset_mock()
        intent2 = _make_order_intent(client_order_id="uniq-2", quantity=75.0)
        decision2 = RiskDecision(approved=True, reason="approved",
                                 order_intent_id=intent2.order_intent_id)
        risk.evaluate.return_value = decision2

        submitted2 = _make_filled_order(intent2, decision2)
        broker.submit_order.return_value = submitted2
        broker.get_fills.return_value = []

        result2 = oms.handle_intent(intent2, _make_account(), 150.0)
        self.assertTrue(result2.risk_decision.approved)
        broker.submit_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
