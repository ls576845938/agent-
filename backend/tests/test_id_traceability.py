"""ID traceability tests.

Verifies the full chain: Fill -> Order -> Signal -> Strategy,
and Order -> RiskDecision, including risk versioning fields.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from quant_us.core.enums import OrderSide, OrderType, SignalDirection, TimeInForce
from quant_us.core.types import Fill, Order, OrderIntent, RiskDecision, Signal


class TestIDTraceability(unittest.TestCase):
    """Verify every Fill can trace back through the full chain."""

    def setUp(self) -> None:
        self.ts = datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc)

        # Build Signal -> OrderIntent -> RiskDecision -> Order -> Fill chain
        self.signal = Signal(
            timestamp_utc=self.ts,
            strategy_id="momentum_v2",
            symbol="AAPL",
            direction=SignalDirection.LONG,
            strength=0.75,
            horizon="1d",
            reason="trend_breakout",
        )

        self.intent = OrderIntent(
            timestamp_utc=self.ts,
            strategy_id="momentum_v2",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            signal_id=self.signal.signal_id,
        )

        self.risk_decision = RiskDecision(
            approved=True,
            reason="approved",
            order_intent_id=self.intent.order_intent_id,
            risk_version="risk_v0.1.0",
            rule_name="",
            threshold=0.0,
        )

        self.order = Order.from_intent(self.intent, self.risk_decision)
        self.order.broker_order_id = "broker_abc123"

        self.fill = Fill(
            order_id=self.order.order_id,
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100.0,
            price=150.0,
            commission=1.50,
            filled_at=self.ts,
            broker="paper_broker",
            broker_order_id=self.order.broker_order_id,
        )

    # ------------------------------------------------------------------
    # Chain: Fill -> Order -> Signal -> Strategy
    # ------------------------------------------------------------------

    def test_fill_carries_order_id(self) -> None:
        """Fill.order_id must match the originating Order.order_id."""
        self.assertEqual(self.fill.order_id, self.order.order_id)

    def test_fill_carries_broker_order_id(self) -> None:
        """Fill.broker_order_id must match Order.broker_order_id."""
        self.assertEqual(self.fill.broker_order_id, self.order.broker_order_id)

    def test_order_carries_signal_id(self) -> None:
        """Order.signal_id must match the originating Signal.signal_id."""
        self.assertEqual(self.order.signal_id, self.signal.signal_id)

    def test_signal_carries_strategy_id(self) -> None:
        """Signal.strategy_id must be populated."""
        self.assertEqual(self.signal.strategy_id, "momentum_v2")
        self.assertTrue(self.signal.signal_id.startswith("sig_"))

    def test_full_trace_is_consistent(self) -> None:
        """Verify the full chain: Fill -> Order -> Signal -> Strategy.
        All IDs in the chain should be non-empty and link correctly."""
        # Step 1: Fill -> Order
        self.assertEqual(self.fill.order_id, self.order.order_id)

        # Step 2: Order -> Signal
        self.assertEqual(self.order.signal_id, self.signal.signal_id)

        # Step 3: Signal -> Strategy
        self.assertEqual(self.signal.strategy_id, "momentum_v2")

        # All IDs must be non-empty
        self.assertTrue(self.fill.fill_id)
        self.assertTrue(self.order.order_id)
        self.assertTrue(self.signal.signal_id)

    # ------------------------------------------------------------------
    # Chain: Order -> RiskDecision
    # ------------------------------------------------------------------

    def test_order_carries_risk_check_id(self) -> None:
        """Order.risk_check_id must match RiskDecision.risk_check_id."""
        self.assertEqual(self.order.risk_check_id, self.risk_decision.risk_check_id)

    def test_risk_decision_has_risk_check_id(self) -> None:
        """RiskDecision.risk_check_id must be non-empty."""
        self.assertTrue(self.risk_decision.risk_check_id.startswith("risk_"))

    def test_risk_decision_carries_version_rule_threshold(self) -> None:
        """RiskDecision must have risk_version, rule_name, and threshold populated."""
        self.assertEqual(self.risk_decision.risk_version, "risk_v0.1.0")
        self.assertEqual(self.risk_decision.rule_name, "")
        self.assertEqual(self.risk_decision.threshold, 0.0)

    # ------------------------------------------------------------------
    # Order fields
    # ------------------------------------------------------------------

    def test_order_carries_client_order_id(self) -> None:
        """Order.client_order_id must be populated from the intent."""
        self.assertEqual(self.order.client_order_id, self.intent.client_order_id)
        self.assertTrue(self.order.client_order_id.startswith("coid_"))

    def test_order_carries_broker_order_id(self) -> None:
        """Order.broker_order_id must be settable."""
        self.assertEqual(self.order.broker_order_id, "broker_abc123")


class TestRiskDecisionRejectionRuleNames(unittest.TestCase):
    """Verify rejected RiskDecision instances carry correct rule_name."""

    def _make_intent(self) -> OrderIntent:
        return OrderIntent(
            timestamp_utc=datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc),
            strategy_id="utest",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100.0,
        )

    def test_rejected_decision_has_rule_name_reason(self) -> None:
        """A rejected RiskDecision should have rule_name matching the reason."""
        decision = RiskDecision(
            approved=False,
            reason="cash_buffer_limit",
            order_intent_id="irrelevant",
            risk_version="risk_v0.1.0",
            rule_name="cash_buffer_limit",
            threshold=0.02,
        )
        self.assertFalse(decision.approved)
        self.assertEqual(decision.rule_name, "cash_buffer_limit")
        self.assertEqual(decision.reason, "cash_buffer_limit")
        self.assertEqual(decision.threshold, 0.02)

    def test_rejected_decision_with_zero_threshold(self) -> None:
        """Rule checks without a numeric threshold should have threshold=0.0."""
        decision = RiskDecision(
            approved=False,
            reason="symbol_blacklisted",
            order_intent_id="irrelevant",
            risk_version="risk_v0.1.0",
            rule_name="symbol_blacklisted",
            threshold=0.0,
        )
        self.assertFalse(decision.approved)
        self.assertEqual(decision.rule_name, "symbol_blacklisted")
        self.assertEqual(decision.threshold, 0.0)


class TestRiskDecisionDefaultValues(unittest.TestCase):
    """Verify RiskDecision default values for versioning fields."""

    def test_default_risk_version(self) -> None:
        """Default risk_version should be 'risk_v0.1.0'."""
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="test")
        self.assertEqual(decision.risk_version, "risk_v0.1.0")

    def test_default_rule_name(self) -> None:
        """Default rule_name should be empty string."""
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="test")
        self.assertEqual(decision.rule_name, "")

    def test_default_threshold(self) -> None:
        """Default threshold should be 0.0."""
        decision = RiskDecision(approved=True, reason="approved", order_intent_id="test")
        self.assertEqual(decision.threshold, 0.0)

    def test_defaults_do_not_break_positional_construction(self) -> None:
        """Positional construction (approved, reason, order_intent_id) must still work."""
        decision = RiskDecision(False, "symbol_blacklisted", "intent_123")
        self.assertFalse(decision.approved)
        self.assertEqual(decision.reason, "symbol_blacklisted")
        self.assertEqual(decision.order_intent_id, "intent_123")
        # New fields should be at defaults
        self.assertEqual(decision.risk_version, "risk_v0.1.0")
        self.assertEqual(decision.rule_name, "")
        self.assertEqual(decision.threshold, 0.0)
        # Existing defaults still work
        self.assertTrue(decision.risk_check_id.startswith("risk_"))


if __name__ == "__main__":
    unittest.main()
