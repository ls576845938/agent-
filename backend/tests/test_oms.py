"""Unit tests for OrderManagementSystem (OMS).

Covers kill switch block, duplicate detection, risk rejection,
successful submission, broker exceptions, and broker rejections.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, OrderIntent, Position, RiskDecision, new_id
from quant_us.execution.oms import OMSResult, OrderManagementSystem


def _make_intent(
    client_order_id: str | None = None,
    side: OrderSide = OrderSide.BUY,
    quantity: float = 100.0,
) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc),
        strategy_id="utest",
        symbol="AAPL",
        side=side,
        quantity=quantity,
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        client_order_id=client_order_id or new_id("coid"),
    )


def _make_account() -> AccountState:
    return AccountState(
        timestamp_utc=datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc),
        account_id="test_acct",
        cash=1_000_000.0,
        equity=1_000_000.0,
        buying_power=2_000_000.0,
    )


def _make_account_with_position(quantity: float) -> AccountState:
    account = _make_account()
    account.positions["AAPL"] = Position(
        symbol="AAPL",
        quantity=quantity,
        avg_price=150.0,
        market_price=150.0,
    )
    return account


def _make_fill(order_id: str) -> Fill:
    return Fill(
        order_id=order_id,
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=100.0,
        price=150.0,
        commission=1.0,
        filled_at=datetime(2025, 6, 1, 14, 31, tzinfo=timezone.utc),
        broker="mock_broker",
    )


class TestOMSResultFields(unittest.TestCase):
    """Verify OMSResult dataclass basic construction."""

    def test_oms_result_fields_populated(self) -> None:
        intent = _make_intent()
        decision = RiskDecision(approved=True, reason="approved", order_intent_id=intent.order_intent_id)
        order = Order.from_intent(intent, decision)
        fills = [_make_fill(order.order_id)]

        result = OMSResult(intent=intent, risk_decision=decision, order=order, fills=fills, events=[])

        self.assertIs(result.intent, intent)
        self.assertIs(result.risk_decision, decision)
        self.assertIs(result.order, order)
        self.assertEqual(result.fills, fills)


@patch("quant_us.execution.oms.utc_now")
class TestOrderManagementSystem(unittest.TestCase):
    """OMS handle_intent behaviour for all paths."""

    def setUp(self) -> None:
        self.broker = MagicMock()
        self.risk_engine = MagicMock()
        self.kill_switch = MagicMock()
        self.oms = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            kill_switch=self.kill_switch,
        )
        self.account = _make_account()
        self.market_price = 150.0

    # ------------------------------------------------------------------
    # Kill switch path
    # ------------------------------------------------------------------

    def test_handle_intent_kill_switch_blocks(self, _mock_utcnow: MagicMock) -> None:
        """Kill switch triggered -> rejected, no broker call, client_order_id not registered."""
        self.kill_switch.update_equity.return_value = True
        self.kill_switch.reason = "daily_loss_limit"

        intent = _make_intent()
        result = self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertFalse(result.risk_decision.approved)
        self.assertIn("kill_switch", result.risk_decision.reason)
        self.broker.submit_order.assert_not_called()
        self.assertNotIn(intent.client_order_id, self.oms._client_order_ids)
        # Exactly one event: the RiskEvent
        self.assertEqual(len(result.events), 1)
        self.assertEqual(intent.order_intent_id, result.risk_decision.order_intent_id)

    # ------------------------------------------------------------------
    # Duplicate client_order_id path
    # ------------------------------------------------------------------

    def test_handle_intent_duplicate_client_order_id(self, _mock_utcnow: MagicMock) -> None:
        """Same client_order_id twice -> second is rejected without broker call."""
        self.kill_switch.update_equity.return_value = False
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent(client_order_id="dup-coid")
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_1"
        submitted.status = OrderStatus.FILLED
        self.broker.submit_order.return_value = submitted
        self.broker.get_fills.return_value = []

        # First call succeeds
        result1 = self.oms.handle_intent(intent, self.account, self.market_price)
        self.assertTrue(result1.risk_decision.approved)

        # Second call with same client_order_id -> duplicate
        result2 = self.oms.handle_intent(intent, self.account, self.market_price)
        self.assertFalse(result2.risk_decision.approved)
        self.assertEqual(result2.risk_decision.reason, "duplicate_client_order_id")
        self.broker.submit_order.assert_called_once()  # only first call reached broker

    # ------------------------------------------------------------------
    # Risk rejection path
    # ------------------------------------------------------------------

    def test_handle_intent_risk_rejects(self, _mock_utcnow: MagicMock) -> None:
        """Risk engine denies -> OMSResult with rejected decision, no broker call."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=False, reason="cash_buffer_limit", order_intent_id="irrelevant",
        )

        intent = _make_intent()
        result = self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertFalse(result.risk_decision.approved)
        self.assertEqual(result.risk_decision.reason, "cash_buffer_limit")
        self.assertIsNone(result.order)
        self.assertEqual(result.fills, [])
        self.broker.submit_order.assert_not_called()
        self.assertNotIn(intent.client_order_id, self.oms._client_order_ids)

    # ------------------------------------------------------------------
    # Successful path
    # ------------------------------------------------------------------

    def test_handle_intent_successful(self, _mock_utcnow: MagicMock) -> None:
        """Risk approves, broker returns FILLED order -> fills and success event recorded."""
        self.kill_switch.update_equity.return_value = False
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent()
        # The OMS creates an Order from intent, submits it, then the broker returns a submitted Order
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_abc"
        submitted.status = OrderStatus.FILLED
        self.broker.submit_order.return_value = submitted

        fills = [_make_fill(submitted.order_id)]
        self.broker.get_fills.return_value = fills

        result = self.oms.handle_intent(intent, self.account, self.market_price)

        # Verify risk decision
        self.assertTrue(result.risk_decision.approved)

        # Verify order returned
        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.order_id, "ord_abc")
        self.assertEqual(result.order.status, OrderStatus.FILLED)

        # Verify fills
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].order_id, "ord_abc")
        self.assertEqual(result.fills[0].symbol, "AAPL")

        # Verify events: RiskEvent + BrokerOrderEvent + FillEvent
        self.assertEqual(len(result.events), 3)

        # Verify broker interactions
        self.broker.submit_order.assert_called_once()
        self.broker.get_fills.assert_called_once_with(order_id="ord_abc")

        # Verify client_order_id was registered
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)

        # Verify kill switch recorded success
        self.kill_switch.record_order_success.assert_called_once()

    # ------------------------------------------------------------------
    # Broker exception path
    # ------------------------------------------------------------------

    def test_handle_intent_broker_exception(self, _mock_utcnow: MagicMock) -> None:
        """Broker raises -> order status ERROR, kill_switch records failure, exception re-raised."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=True, reason="approved", order_intent_id="irrelevant",
        )

        self.broker.submit_order.side_effect = RuntimeError("connection lost")

        intent = _make_intent()
        with self.assertRaises(RuntimeError):
            self.oms.handle_intent(intent, self.account, self.market_price)

        # kill_switch should have recorded failure
        self.kill_switch.record_order_failure.assert_called_once()
        # Conservative safety: outcome is unknown, so the id is reserved to
        # prevent a restart from resubmitting the same intent.
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)
        self.assertTrue(self.oms.reduce_only)

    def test_handle_intent_broker_exception_without_kill_switch(self, _mock_utcnow: MagicMock) -> None:
        """Broker raises when kill_switch is None -> no AttributeError, exception still re-raised."""
        oms_no_ks = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            kill_switch=None,
        )
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=True, reason="approved", order_intent_id="irrelevant",
        )
        self.broker.submit_order.side_effect = RuntimeError("connection lost")

        intent = _make_intent()
        with self.assertRaises(RuntimeError):
            oms_no_ks.handle_intent(intent, self.account, self.market_price)

        # No kill_switch -> no failure record needed (would AttributeError if code tried)

    # ------------------------------------------------------------------
    # Broker rejection path
    # ------------------------------------------------------------------

    def test_handle_intent_broker_rejects_order(self, _mock_utcnow: MagicMock) -> None:
        """Broker returns REJECTED -> kill_switch records failure, order has REJECTED status."""
        self.kill_switch.update_equity.return_value = False
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent()
        rejected_order = Order.from_intent(intent, decision)
        rejected_order.order_id = "ord_rej"
        rejected_order.status = OrderStatus.REJECTED
        self.broker.submit_order.return_value = rejected_order
        self.broker.get_fills.return_value = []

        result = self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertEqual(result.order.status, OrderStatus.REJECTED)
        self.kill_switch.record_order_failure.assert_called_once()
        self.kill_switch.record_order_success.assert_not_called()
        # client_order_id IS registered (it was added before the check)
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)

    # ------------------------------------------------------------------
    # Kill switch success recording
    # ------------------------------------------------------------------

    def test_kill_switch_records_success_on_fill(self, _mock_utcnow: MagicMock) -> None:
        """Filled order -> kill_switch.record_order_success() called."""
        self.kill_switch.update_equity.return_value = False
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent()
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_succ"
        submitted.status = OrderStatus.FILLED
        self.broker.submit_order.return_value = submitted
        self.broker.get_fills.return_value = [_make_fill(submitted.order_id)]

        self.oms.handle_intent(intent, self.account, self.market_price)

        self.kill_switch.record_order_success.assert_called_once()
        self.kill_switch.record_order_failure.assert_not_called()

    # ------------------------------------------------------------------
    # Kill switch success for non-fill statuses (ACCEPTED, PARTIALLY_FILLED)
    # ------------------------------------------------------------------

    def test_kill_switch_records_success_on_accepted(self, _mock_utcnow: MagicMock) -> None:
        """Accepted (but not yet filled) order -> still counts as success for kill switch."""
        self.kill_switch.update_equity.return_value = False
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent()
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_acc"
        submitted.status = OrderStatus.ACCEPTED
        self.broker.submit_order.return_value = submitted
        self.broker.get_fills.return_value = []

        self.oms.handle_intent(intent, self.account, self.market_price)

        self.kill_switch.record_order_success.assert_called_once()
        self.kill_switch.record_order_failure.assert_not_called()

    # ------------------------------------------------------------------
    # handle_intent with kill_switch = None
    # ------------------------------------------------------------------

    def test_handle_intent_no_kill_switch(self, _mock_utcnow: MagicMock) -> None:
        """No kill_switch configured -> proceeds past equity check safely."""
        oms_no_ks = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            kill_switch=None,
        )
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent()
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_noks"
        submitted.status = OrderStatus.FILLED
        self.broker.submit_order.return_value = submitted
        self.broker.get_fills.return_value = []

        intent = _make_intent()
        result = oms_no_ks.handle_intent(intent, self.account, self.market_price)

        self.assertTrue(result.risk_decision.approved)
        self.broker.submit_order.assert_called_once()

    # ------------------------------------------------------------------
    # Reduce-only path
    # ------------------------------------------------------------------

    def test_reduce_only_blocks_long_position_reversal(self, _mock_utcnow: MagicMock) -> None:
        """Reduce-only must not allow a sell that crosses long exposure into short."""
        self.kill_switch.update_equity.return_value = False
        self.oms.reduce_only = True

        intent = _make_intent(side=OrderSide.SELL, quantity=20.0)
        result = self.oms.handle_intent(
            intent,
            _make_account_with_position(10.0),
            self.market_price,
        )

        self.assertFalse(result.risk_decision.approved)
        self.assertEqual(result.risk_decision.reason, "reduce_only_would_reverse_long")
        self.risk_engine.evaluate.assert_not_called()
        self.broker.submit_order.assert_not_called()

    def test_reduce_only_allows_long_position_reduction(self, _mock_utcnow: MagicMock) -> None:
        """Reduce-only still allows a sell that reduces an existing long."""
        self.kill_switch.update_equity.return_value = False
        self.oms.reduce_only = True
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent(side=OrderSide.SELL, quantity=5.0)
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_reduce"
        submitted.status = OrderStatus.ACCEPTED
        self.broker.submit_order.return_value = submitted

        result = self.oms.handle_intent(
            intent,
            _make_account_with_position(10.0),
            self.market_price,
        )

        self.assertTrue(result.risk_decision.approved)
        self.risk_engine.evaluate.assert_called_once()
        self.broker.submit_order.assert_called_once()

    def test_reduce_only_blocks_short_position_reversal(self, _mock_utcnow: MagicMock) -> None:
        """Reduce-only must not allow a buy that crosses short exposure into long."""
        self.kill_switch.update_equity.return_value = False
        self.oms.reduce_only = True

        intent = _make_intent(side=OrderSide.BUY, quantity=20.0)
        result = self.oms.handle_intent(
            intent,
            _make_account_with_position(-10.0),
            self.market_price,
        )

        self.assertFalse(result.risk_decision.approved)
        self.assertEqual(result.risk_decision.reason, "reduce_only_would_reverse_short")
        self.risk_engine.evaluate.assert_not_called()
        self.broker.submit_order.assert_not_called()

    def test_reduce_only_allows_short_position_reduction(self, _mock_utcnow: MagicMock) -> None:
        """Reduce-only allows a buy-to-cover that reduces an existing short."""
        self.kill_switch.update_equity.return_value = False
        self.oms.reduce_only = True
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")
        self.risk_engine.evaluate.return_value = decision

        intent = _make_intent(side=OrderSide.BUY, quantity=5.0)
        submitted = Order.from_intent(intent, decision)
        submitted.order_id = "ord_cover"
        submitted.status = OrderStatus.ACCEPTED
        self.broker.submit_order.return_value = submitted
        self.broker.get_fills.return_value = []

        result = self.oms.handle_intent(
            intent,
            _make_account_with_position(-10.0),
            self.market_price,
        )

        self.assertTrue(result.risk_decision.approved)
        self.risk_engine.evaluate.assert_called_once()
        self.broker.submit_order.assert_called_once()


if __name__ == "__main__":
    unittest.main()
