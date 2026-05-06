from __future__ import annotations

import pytest

from quant_us.core.enums import OrderStatus
from quant_us.execution.order_polling import (
    OrderPollingLoop,
    OrderPollResult,
    OrderSyncAction,
)

from .conftest import make_fill, make_order


class TestOrderPollingLoop:
    """Tests for OrderPollingLoop."""

    def test_poll_no_orders(self, broker, ledger, oms, kill_switch):
        """Poll with no tracked orders returns empty result."""
        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()
        assert isinstance(result, OrderPollResult)
        assert result.total_processed == 0
        assert len(result.external) == 0

    def test_poll_submitted_to_filled(self, broker, ledger, oms, kill_switch):
        """LOCAL SUBMITTED, BROKER FILLED -> sync fill, return FILL_SYNCED."""
        local = make_order(status=OrderStatus.SUBMITTED)
        broker_order = make_order(status=OrderStatus.FILLED)
        fill = make_fill(order_id=broker_order.order_id)

        ledger.append_order(local)
        broker.orders.append(broker_order)
        broker.fills.append(fill)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()

        assert result.total_processed == 1
        assert result.filled == 1
        # Verify fill was written to ledger
        fills = ledger.read_records("fills.jsonl")
        assert len(fills) == 1

    def test_poll_submitted_not_found_on_broker(
        self, broker, ledger, oms, kill_switch, risk_event_log,
    ):
        """LOCAL SUBMITTED, BROKER NOT FOUND -> mark UNKNOWN, engage safety."""
        local = make_order(status=OrderStatus.SUBMITTED)
        ledger.append_order(local)

        loop = OrderPollingLoop(
            broker, ledger, oms, kill_switch, risk_event_log=risk_event_log,
        )
        result = loop.poll()

        assert result.total_processed == 1
        assert len(result.unknown) == 1
        assert result.unknown[0] == "coid_abc123"
        # Kill switch should have been triggered
        assert kill_switch.failures == 1
        # OMS should be in reduce-only mode
        assert oms.reduce_only is True
        # Event should be logged
        assert any(
            evt_type == "order_marked_unknown"
            for evt_type, _ in risk_event_log.events
        )

    def test_poll_cancel_pending_partial_fill(
        self, broker, ledger, oms, kill_switch,
    ):
        """LOCAL CANCEL_PENDING, BROKER PARTIALLY_FILLED -> sync partial fill."""
        local = make_order(
            client_order_id="coid_cancel",
            order_id="ord_cancel",
            status=OrderStatus.CANCEL_PENDING,
        )
        broker_order = make_order(
            client_order_id="coid_cancel",
            order_id="ord_cancel",
            status=OrderStatus.PARTIALLY_FILLED,
            quantity=50.0,
        )
        fill = make_fill(
            order_id=broker_order.order_id,
            fill_id="fill_partial",
            quantity=50.0,
            price=149.0,
        )

        ledger.append_order(local)
        broker.orders.append(broker_order)
        broker.fills.append(fill)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()

        assert result.total_processed == 1
        assert result.synced == 1  # PARTIAL_FILL counts as synced
        fills = ledger.read_records("fills.jsonl")
        assert len(fills) == 1
        assert fills[0]["fill_id"] == "fill_partial"

    def test_poll_external_order_alert(
        self, broker, ledger, oms, kill_switch, risk_event_log,
    ):
        """BROKER order exists, LOCAL doesn't -> external alert."""
        external = make_order(
            client_order_id="coid_external",
            order_id="ord_external",
            status=OrderStatus.ACCEPTED,
        )
        broker.orders.append(external)

        loop = OrderPollingLoop(
            broker, ledger, oms, kill_switch, risk_event_log=risk_event_log,
        )
        result = loop.poll()

        assert result.total_processed == 0
        assert len(result.external) == 1
        assert result.external[0].client_order_id == "coid_external"
        assert any(
            evt_type == "external_order_detected"
            for evt_type, _ in risk_event_log.events
        )

    def test_poll_skips_terminal_orders(
        self, broker, ledger, oms, kill_switch,
    ):
        """Terminal orders (FILLED, CANCELLED, etc.) are skipped."""
        filled_order = make_order(
            client_order_id="coid_filled",
            order_id="ord_filled",
            status=OrderStatus.FILLED,
        )
        cancelled_order = make_order(
            client_order_id="coid_cancelled",
            order_id="ord_cancelled",
            status=OrderStatus.CANCELLED,
        )
        ledger.append_order(filled_order)
        ledger.append_order(cancelled_order)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()

        assert result.total_processed == 0

    def test_sync_order_idempotent(self, broker, ledger, oms, kill_switch):
        """Calling sync_order twice with same args returns NOOP on second."""
        local = make_order(status=OrderStatus.SUBMITTED)
        broker_order = make_order(status=OrderStatus.FILLED)
        fill = make_fill(order_id=broker_order.order_id)

        ledger.append_order(local)
        broker.orders.append(broker_order)
        broker.fills.append(fill)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)

        action1 = loop.sync_order(local, broker_order)
        assert action1 == OrderSyncAction.FILL_SYNCED

        action2 = loop.sync_order(local, broker_order)
        assert action2 == OrderSyncAction.NOOP

    def test_poll_broker_error_graceful(
        self, broker, ledger, oms, kill_switch,
    ):
        """Broker failure during get_orders returns empty result."""
        local = make_order(status=OrderStatus.SUBMITTED)
        ledger.append_order(local)
        broker.raise_on_get_orders = RuntimeError("Broker down")

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()

        # The local order has no broker counterpart, and no broker data
        # Means it gets treated as NOT FOUND -> MARKED_UNKNOWN
        assert result.total_processed == 1
        assert len(result.unknown) == 1
        assert kill_switch.failures >= 1

    def test_poll_order_status_noop_when_same(
        self, broker, ledger, oms, kill_switch,
    ):
        """LOCAL and BROKER have same status -> NOOP."""
        local = make_order(status=OrderStatus.ACCEPTED)
        broker_order = make_order(status=OrderStatus.ACCEPTED)
        ledger.append_order(local)
        broker.orders.append(broker_order)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()

        assert result.total_processed == 1
        assert result.synced == 0
        assert result.filled == 0

    def test_poll_cancel_pending_to_cancelled(
        self, broker, ledger, oms, kill_switch,
    ):
        """LOCAL CANCEL_PENDING, BROKER CANCELLED -> CANCELLED."""
        local = make_order(
            client_order_id="coid_cancel",
            order_id="ord_cancel",
            status=OrderStatus.CANCEL_PENDING,
        )
        broker_order = make_order(
            client_order_id="coid_cancel",
            order_id="ord_cancel",
            status=OrderStatus.CANCELLED,
        )
        ledger.append_order(local)
        broker.orders.append(broker_order)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        result = loop.poll()

        assert result.total_processed == 1
        assert result.cancelled == 1

    def test_sync_order_explicit(self, broker, ledger, oms, kill_switch):
        """sync_order can be called directly with explicit orders."""
        local = make_order(status=OrderStatus.SUBMITTED)
        broker_order = make_order(status=OrderStatus.REJECTED)

        loop = OrderPollingLoop(broker, ledger, oms, kill_switch)
        action = loop.sync_order(local, broker_order)

        assert action == OrderSyncAction.REJECTED
        assert local.status == OrderStatus.REJECTED
