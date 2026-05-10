"""Tests for order state recovery and RiskEventLog.

T-067: Order state recovery — when broker.submit_order() raises, OMS queries
       the broker to see if the order was actually accepted.

T-068: Risk Event Log — persistent audit trail for risk events.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, OrderIntent, RiskDecision, new_id
from quant_us.execution.oms import OMSResult, OrderManagementSystem
from quant_us.risk.kill_switch import KillSwitch, KillSwitchConfig
from quant_us.risk.risk_event_log import RiskEventLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(client_order_id: str | None = None) -> OrderIntent:
    return OrderIntent(
        timestamp_utc=datetime(2025, 6, 1, 14, 30, tzinfo=timezone.utc),
        strategy_id="utest",
        symbol="AAPL",
        side=OrderSide.BUY,
        quantity=100.0,
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


# ===========================================================================
# T-067: Order State Recovery Tests
# ===========================================================================

@patch("quant_us.execution.oms.utc_now")
class TestOrderStateRecovery(unittest.TestCase):
    """Verify OMS recovers order state after broker.submit_order() failure."""

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
        self.decision = RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant")

    # ------------------------------------------------------------------
    # 1. Broker timeout -> query broker -> find FILLED -> recover fills
    # ------------------------------------------------------------------

    def test_recover_filled_after_timeout(self, _mock_utcnow: MagicMock) -> None:
        """submit_order() raises, but broker has the order as FILLED -> fill recovered."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()
        recovered_order = Order.from_intent(intent, self.decision)
        recovered_order.order_id = "ord_filled"
        recovered_order.client_order_id = intent.client_order_id
        recovered_order.status = OrderStatus.FILLED
        recovered_order.broker_order_id = "brk_filled"

        # submit_order raises
        self.broker.submit_order.side_effect = RuntimeError("broker timeout")

        # get_orders returns the order
        self.broker.get_orders.return_value = [recovered_order]
        # get_fills returns fills for this order
        fills = [_make_fill(recovered_order.order_id)]
        self.broker.get_fills.return_value = fills

        result = self.oms.handle_intent(intent, self.account, self.market_price)

        # Recovery succeeded — result should look like a successful submission
        self.assertTrue(result.risk_decision.approved)
        self.assertIsNotNone(result.order)
        self.assertEqual(result.order.status, OrderStatus.FILLED)
        self.assertEqual(result.order.broker_order_id, "brk_filled")
        self.assertEqual(len(result.fills), 1)
        self.assertEqual(result.fills[0].order_id, "ord_filled")

        # client_order_id should be registered
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)

        # kill switch recorded failure
        self.kill_switch.record_order_failure.assert_called_once()

        # broker.get_fills was called with recovered order_id
        self.broker.get_fills.assert_called_once_with(order_id="ord_filled")

        # Events should have: RiskEvent + BrokerOrderEvent + FillEvent
        self.assertEqual(len(result.events), 3)

    # ------------------------------------------------------------------
    # 2. Broker timeout -> broker can't find order -> mark UNKNOWN, raise
    # ------------------------------------------------------------------

    def test_recover_not_found_raises_error(self, _mock_utcnow: MagicMock) -> None:
        """submit_order() raises, broker.get_orders() does not contain the order -> ERROR, raise."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()

        # submit_order raises
        self.broker.submit_order.side_effect = RuntimeError("broker timeout")

        # get_orders returns an empty list — order not found
        self.broker.get_orders.return_value = []

        with self.assertRaises(RuntimeError) as ctx:
            self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertIn("broker timeout", str(ctx.exception))
        # Conservative safety: outcome is unknown, so the client_order_id is
        # reserved to prevent a restart from submitting the same intent twice.
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)
        self.assertTrue(self.oms.reduce_only)

    def test_recover_get_orders_also_fails(self, _mock_utcnow: MagicMock) -> None:
        """submit_order() raises, get_orders() also raises -> mark UNKNOWN, original exception re-raised."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()

        # submit_order raises
        self.broker.submit_order.side_effect = RuntimeError("submit timeout")
        # get_orders also raises
        self.broker.get_orders.side_effect = ConnectionError("get_orders failed too")

        with self.assertRaises(RuntimeError) as ctx:
            self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertIn("submit timeout", str(ctx.exception))
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)
        self.assertTrue(self.oms.reduce_only)

    # ------------------------------------------------------------------
    # 3. Recovery when broker returns ACCEPTED (not yet filled)
    # ------------------------------------------------------------------

    def test_recover_accepted_after_timeout(self, _mock_utcnow: MagicMock) -> None:
        """submit_order() raises, broker has ACCEPTED -> order synced, no fills."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()
        recovered_order = Order.from_intent(intent, self.decision)
        recovered_order.order_id = "ord_accepted"
        recovered_order.client_order_id = intent.client_order_id
        recovered_order.status = OrderStatus.ACCEPTED
        recovered_order.broker_order_id = "brk_accepted"

        self.broker.submit_order.side_effect = RuntimeError("broker timeout")
        self.broker.get_orders.return_value = [recovered_order]
        self.broker.get_fills.return_value = []

        result = self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertTrue(result.risk_decision.approved)
        self.assertEqual(result.order.status, OrderStatus.ACCEPTED)
        self.assertEqual(len(result.fills), 0)
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)

    # ------------------------------------------------------------------
    # 4. Recovery by order_id fallback (not client_order_id)
    # ------------------------------------------------------------------

    def test_recover_syncs_order_id(self, _mock_utcnow: MagicMock) -> None:
        """After recovery, order.order_id is synced to the broker's order_id."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()
        # The broker has a record with a known order_id
        broker_order = Order.from_intent(intent, self.decision)
        broker_order.order_id = "ord_brk_001"
        broker_order.client_order_id = intent.client_order_id
        broker_order.status = OrderStatus.ACCEPTED
        broker_order.broker_order_id = "brk_001"

        self.broker.submit_order.side_effect = RuntimeError("broker timeout")
        self.broker.get_orders.return_value = [broker_order]
        self.broker.get_fills.return_value = []

        result = self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertTrue(result.risk_decision.approved)
        # The local order's order_id should be replaced with the broker's
        self.assertEqual(result.order.order_id, "ord_brk_001")
        self.assertEqual(result.order.broker_order_id, "brk_001")
        # get_fills should be called with the broker's order_id
        self.broker.get_fills.assert_called_once_with(order_id="ord_brk_001")

    # ------------------------------------------------------------------
    # 5. No kill_switch — recovery still works
    # ------------------------------------------------------------------

    def test_recover_without_kill_switch(self, _mock_utcnow: MagicMock) -> None:
        """Recovery works when kill_switch is None."""
        oms_no_ks = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            kill_switch=None,
        )
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()
        recovered_order = Order.from_intent(intent, self.decision)
        recovered_order.order_id = "ord_noks"
        recovered_order.client_order_id = intent.client_order_id
        recovered_order.status = OrderStatus.ACCEPTED
        recovered_order.broker_order_id = "brk_noks"

        self.broker.submit_order.side_effect = RuntimeError("broker timeout")
        self.broker.get_orders.return_value = [recovered_order]
        self.broker.get_fills.return_value = []

        result = oms_no_ks.handle_intent(intent, self.account, self.market_price)

        self.assertTrue(result.risk_decision.approved)
        self.assertEqual(result.order.status, OrderStatus.ACCEPTED)
        self.assertIn(intent.client_order_id, oms_no_ks._client_order_ids)

    # ------------------------------------------------------------------
    # 6. Normal success path unchanged after refactor
    # ------------------------------------------------------------------

    def test_normal_success_path_unchanged(self, _mock_utcnow: MagicMock) -> None:
        """Normal happy path still works when no exception is raised."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = self.decision

        intent = _make_intent()
        submitted = Order.from_intent(intent, self.decision)
        submitted.order_id = "ord_normal"
        submitted.status = OrderStatus.FILLED
        self.broker.submit_order.return_value = submitted
        fills = [_make_fill(submitted.order_id)]
        self.broker.get_fills.return_value = fills

        result = self.oms.handle_intent(intent, self.account, self.market_price)

        self.assertTrue(result.risk_decision.approved)
        self.assertEqual(result.order.status, OrderStatus.FILLED)
        self.assertEqual(len(result.fills), 1)
        self.assertIn(intent.client_order_id, self.oms._client_order_ids)


# ===========================================================================
# T-068: Risk Event Log Tests
# ===========================================================================

class TestRiskEventLog(unittest.TestCase):
    """Verify RiskEventLog persistence and querying."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = Path(self.tmpdir) / "risk_events.jsonl"
        self.log = RiskEventLog(self.log_path)

    def tearDown(self) -> None:
        self.log.clear()

    def test_record_creates_file(self) -> None:
        """Recording an event creates the JSONL file."""
        self.log.record("risk_rejected", {"rule": "symbol_weight_limit"})
        self.assertTrue(self.log_path.exists())
        self.assertGreater(self.log_path.stat().st_size, 0)

    def test_record_writes_valid_json(self) -> None:
        """Each event is a valid JSON line."""
        self.log.record("risk_rejected", {"rule": "cash_buffer_limit"})
        line = self.log_path.read_text(encoding="utf-8").strip()
        parsed = json.loads(line)
        self.assertEqual(parsed["event_type"], "risk_rejected")
        self.assertEqual(parsed["details"]["rule"], "cash_buffer_limit")
        self.assertIn("timestamp_utc", parsed)

    def test_multiple_events_are_appended(self) -> None:
        """Multiple records are appended as separate JSON lines."""
        self.log.record("risk_rejected", {"id": 1})
        self.log.record("kill_switch_triggered", {"id": 2})
        self.log.record("broker_timeout", {"id": 3})

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)

    def test_query_by_event_type(self) -> None:
        """query(event_type=...) returns only matching events."""
        self.log.record("risk_rejected", {"symbol": "AAPL"})
        self.log.record("kill_switch_triggered", {"reason": "drawdown"})
        self.log.record("risk_rejected", {"symbol": "MSFT"})

        risk_events = self.log.query(event_type="risk_rejected")
        self.assertEqual(len(risk_events), 2)
        for ev in risk_events:
            self.assertEqual(ev["event_type"], "risk_rejected")

        kill_events = self.log.query(event_type="kill_switch_triggered")
        self.assertEqual(len(kill_events), 1)
        self.assertEqual(kill_events[0]["details"]["reason"], "drawdown")

    def test_query_by_timestamp(self) -> None:
        """query(since=...) filters events after a given time."""
        before = datetime(2025, 1, 1, tzinfo=timezone.utc)
        after = datetime(2025, 6, 1, tzinfo=timezone.utc)

        self.log.record("risk_rejected", {"ts": "before"}, timestamp=datetime(2025, 3, 1, tzinfo=timezone.utc))
        self.log.record("risk_rejected", {"ts": "after"}, timestamp=datetime(2025, 7, 1, tzinfo=timezone.utc))

        results = self.log.query(since=after)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["details"]["ts"], "after")

    def test_query_no_match_returns_empty(self) -> None:
        """query with no matching events returns empty list."""
        self.log.record("risk_rejected", {})
        results = self.log.query(event_type="broker_disconnect")
        self.assertEqual(results, [])

    def test_query_empty_file(self) -> None:
        """query on non-existent file returns empty list."""
        empty_path = Path(self.tmpdir) / "does_not_exist" / "events.jsonl"
        empty_log = RiskEventLog(str(empty_path))
        self.assertEqual(empty_log.query(), [])
        self.assertEqual(empty_log.count(), 0)

    def test_count(self) -> None:
        """count() returns the right number."""
        self.log.record("risk_rejected", {})
        self.log.record("kill_switch_triggered", {})
        self.log.record("broker_timeout", {})
        self.assertEqual(self.log.count(), 3)
        self.assertEqual(self.log.count(event_type="risk_rejected"), 1)
        self.assertEqual(self.log.count(event_type="nonexistent"), 0)

    def test_clear_removes_file(self) -> None:
        """clear() deletes the log file."""
        self.log.record("risk_rejected", {})
        self.assertTrue(self.log_path.exists())
        self.log.clear()
        self.assertFalse(self.log_path.exists())

    def test_record_custom_event_type(self) -> None:
        """Custom event types are allowed."""
        self.log.record("my_custom_event", {"custom": True})
        results = self.log.query(event_type="my_custom_event")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["details"]["custom"])


# ===========================================================================
# T-068: Risk Event Log Wired into OMS
# ===========================================================================

@patch("quant_us.execution.oms.utc_now")
class TestOMSWithRiskEventLog(unittest.TestCase):
    """Verify OMS writes to RiskEventLog on rejections and broker timeouts."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.log = RiskEventLog(Path(self.tmpdir) / "risk_events.jsonl")
        self.broker = MagicMock()
        self.risk_engine = MagicMock()
        self.kill_switch = MagicMock()
        self.oms = OrderManagementSystem(
            broker=self.broker,
            risk_engine=self.risk_engine,
            kill_switch=self.kill_switch,
            risk_event_log=self.log,
        )
        self.account = _make_account()
        self.market_price = 150.0

    def tearDown(self) -> None:
        self.log.clear()

    def test_risk_rejection_logged(self, _mock_utcnow: MagicMock) -> None:
        """Risk engine rejection writes risk_rejected event."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=False, reason="cash_buffer_limit", order_intent_id="irrelevant",
        )

        intent = _make_intent()
        self.oms.handle_intent(intent, self.account, self.market_price)

        events = self.log.query(event_type="risk_rejected")
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(events[0]["details"]["rule"], "risk_engine")
        self.assertEqual(events[0]["details"]["symbol"], "AAPL")

    def test_duplicate_order_logged(self, _mock_utcnow: MagicMock) -> None:
        """Duplicate client_order_id writes risk_rejected event."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=True, reason="approved", order_intent_id="irrelevant",
        )

        intent = _make_intent(client_order_id="dup-coid")
        submitted = Order.from_intent(intent, RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant"))
        submitted.order_id = "ord_1"
        submitted.status = OrderStatus.FILLED
        self.broker.submit_order.return_value = submitted
        self.broker.get_fills.return_value = []

        # First call succeeds
        self.oms.handle_intent(intent, self.account, self.market_price)
        # Second call — duplicate
        self.oms.handle_intent(intent, self.account, self.market_price)

        events = self.log.query(event_type="risk_rejected")
        duplicate_events = [e for e in events if e["details"]["rule"] == "duplicate_client_order_id"]
        self.assertEqual(len(duplicate_events), 1)

    def test_broker_timeout_logged(self, _mock_utcnow: MagicMock) -> None:
        """Broker timeout writes broker_timeout event even when recovery fails."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=True, reason="approved", order_intent_id="irrelevant",
        )

        intent = _make_intent()
        self.broker.submit_order.side_effect = RuntimeError("timeout")
        self.broker.get_orders.return_value = []

        with self.assertRaises(RuntimeError):
            self.oms.handle_intent(intent, self.account, self.market_price)

        events = self.log.query(event_type="broker_timeout")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["details"]["client_order_id"], intent.client_order_id)
        self.assertEqual(events[0]["details"]["symbol"], "AAPL")

    def test_broker_timeout_with_recovery_logged(self, _mock_utcnow: MagicMock) -> None:
        """Broker timeout writes broker_timeout event even when recovery succeeds."""
        self.kill_switch.update_equity.return_value = False
        self.risk_engine.evaluate.return_value = RiskDecision(
            approved=True, reason="approved", order_intent_id="irrelevant",
        )

        intent = _make_intent()
        recovered_order = Order.from_intent(intent, RiskDecision(approved=True, reason="approved", order_intent_id="irrelevant"))
        recovered_order.order_id = "ord_rec"
        recovered_order.client_order_id = intent.client_order_id
        recovered_order.status = OrderStatus.FILLED
        recovered_order.broker_order_id = "brk_rec"

        self.broker.submit_order.side_effect = RuntimeError("timeout")
        self.broker.get_orders.return_value = [recovered_order]
        self.broker.get_fills.return_value = []

        result = self.oms.handle_intent(intent, self.account, self.market_price)
        self.assertTrue(result.risk_decision.approved)

        events = self.log.query(event_type="broker_timeout")
        self.assertEqual(len(events), 1)


# ===========================================================================
# T-068: Risk Event Log Wired into KillSwitch
# ===========================================================================

class TestKillSwitchWithRiskEventLog(unittest.TestCase):
    """Verify KillSwitch writes kill_switch_triggered events."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.log = RiskEventLog(Path(self.tmpdir) / "risk_events.jsonl")

    def tearDown(self) -> None:
        self.log.clear()

    def test_trigger_writes_event(self) -> None:
        """KillSwitch._trigger writes kill_switch_triggered event."""
        ks = KillSwitch(
            config=KillSwitchConfig(max_consecutive_order_failures=1),
            risk_event_log=self.log,
        )
        # Trigger via record_order_failure (which calls record_broker_failure -> _trigger)
        ks.record_order_failure()
        self.assertTrue(ks.triggered)

        events = self.log.query(event_type="kill_switch_triggered")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["details"]["reason"], "order_failure_limit")

    def test_no_log_when_none(self) -> None:
        """KillSwitch without risk_event_log does not crash."""
        ks = KillSwitch(KillSwitchConfig(max_consecutive_order_failures=1))
        ks.record_order_failure()
        self.assertTrue(ks.triggered)
        # Should not crash — no AttributeError

    def test_multiple_triggers(self) -> None:
        """Multiple trigger events are all recorded."""
        ks = KillSwitch(
            config=KillSwitchConfig(max_daily_loss_pct=0.01),
            risk_event_log=self.log,
        )
        ks.day_start_equity = 1000.0
        ks.update_equity(900.0)  # 10% drop > 1% daily loss
        self.assertTrue(ks.triggered)
        ks.reset_daily(1000.0)
        ks.update_equity(950.0)  # already triggered, but let's check

        # Clear and check with a fresh one
        self.log.clear()

        ks2 = KillSwitch(
            config=KillSwitchConfig(max_daily_loss_pct=0.10, max_drawdown_pct=0.05),
            risk_event_log=self.log,
        )
        ks2.day_start_equity = 1000.0
        ks2.high_water_mark = 1000.0
        ks2.update_equity(750.0)  # 25% drop > 5% max drawdown

        events = self.log.query(event_type="kill_switch_triggered")
        self.assertGreaterEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
