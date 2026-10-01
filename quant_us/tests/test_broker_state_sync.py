from __future__ import annotations

import pytest

from quant_us.core.enums import OrderStatus
from quant_us.core.types import Position
from quant_us.execution.broker_state_sync import BrokerStateSync

from .conftest import make_fill, make_order


class TestBrokerStateSync:
    """Tests for BrokerStateSync."""

    def test_full_sync_no_differences(self, broker, ledger, oms):
        """Identical local and broker state produces clean report."""
        order = make_order(status=OrderStatus.FILLED)
        fill = make_fill(order_id=order.order_id)
        ledger.append_order(order)
        ledger.append_fill(fill)
        broker.orders.append(order)
        broker.fills.append(fill)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert report.orders_matched == 1
        assert report.orders_status_synced == 0
        assert len(report.orders_missing_local) == 0
        assert len(report.orders_missing_broker) == 0

    def test_full_sync_status_mismatch(self, broker, ledger, oms):
        """Local and broker order status differ -> synced."""
        local = make_order(status=OrderStatus.SUBMITTED)
        broker_order = make_order(status=OrderStatus.ACCEPTED)
        ledger.append_order(local)
        broker.orders.append(broker_order)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert report.orders_matched == 1
        assert report.orders_status_synced == 1

    def test_full_sync_missing_local_order(self, broker, ledger, oms):
        """Broker has order not in ledger -> reported missing_local."""
        broker_order = make_order(
            client_order_id="coid_broker_only",
            order_id="ord_broker_only",
        )
        broker.orders.append(broker_order)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert len(report.orders_missing_local) == 1
        assert report.orders_missing_local[0].client_order_id == "coid_broker_only"
        # Order should have been written to ledger
        records = ledger.read_records("orders.jsonl")
        assert any(r["client_order_id"] == "coid_broker_only" for r in records)

    def test_full_sync_missing_broker_order(self, broker, ledger, oms):
        """Ledger has order not on broker -> reported missing_broker."""
        local = make_order(
            client_order_id="coid_local_only",
            order_id="ord_local_only",
        )
        ledger.append_order(local)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert len(report.orders_missing_broker) == 1
        assert report.orders_missing_broker[0].client_order_id == "coid_local_only"

    def test_full_sync_missing_fills(self, broker, ledger, oms):
        """Broker has fills not in ledger -> synced."""
        order = make_order(status=OrderStatus.FILLED)
        fill1 = make_fill(order_id=order.order_id, fill_id="fill_001")
        fill2 = make_fill(order_id=order.order_id, fill_id="fill_002")
        ledger.append_order(order)
        ledger.append_fill(fill1)  # fill1 already in ledger
        broker.orders.append(order)
        broker.fills.extend([fill1, fill2])

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert report.fills_synced == 1  # fill2 is new
        assert report.fills_duplicate == 1  # fill1 is duplicate

    def test_full_sync_position_divergence(self, broker, ledger, oms):
        """Position quantities differ between local and broker."""
        ledger.append_fill(make_fill(symbol="AAPL", quantity=100, fill_id="f1"))
        broker.positions["AAPL"] = Position(symbol="AAPL", quantity=90.0, market_price=150.0)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert report.positions_compared >= 1
        assert len(report.positions_diverge) >= 1
        assert report.positions_diverge[0][0] == "AAPL"
        # local from fills = 100, broker = 90
        assert abs(report.positions_diverge[0][1] - 100.0) < 1e-6
        assert abs(report.positions_diverge[0][2] - 90.0) < 1e-6

    def test_full_sync_broker_error_graceful(self, broker, ledger, oms):
        """Broker failure during full_sync returns report with errors."""
        broker.raise_on_get_orders = RuntimeError("Broker down")

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert len(report.errors) >= 1
        assert any("Broker down" in e for e in report.errors)

    def test_sync_after_restart(self, broker, ledger, oms):
        """Restart sync restores broker orders and fills to ledger."""
        broker_order = make_order(
            client_order_id="coid_restored",
            order_id="ord_restored",
            status=OrderStatus.FILLED,
        )
        broker_fill = make_fill(
            order_id=broker_order.order_id,
            fill_id="fill_restored",
        )
        broker.orders.append(broker_order)
        broker.fills.append(broker_fill)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.sync_after_restart()

        assert len(report.orders_missing_local) == 1
        assert report.fills_synced == 1
        # Verify ledger has the restored data
        orders = ledger.read_records("orders.jsonl")
        assert any(r["client_order_id"] == "coid_restored" for r in orders)
        fills = ledger.read_records("fills.jsonl")
        assert any(r["fill_id"] == "fill_restored" for r in fills)

    def test_sync_after_restart_no_duplicates(self, broker, ledger, oms):
        """Restart sync does not duplicate existing data."""
        existing_order = make_order(
            client_order_id="coid_existing",
            order_id="ord_existing",
            status=OrderStatus.FILLED,
        )
        existing_fill = make_fill(
            order_id=existing_order.order_id,
            fill_id="fill_existing",
        )
        ledger.append_order(existing_order)
        ledger.append_fill(existing_fill)
        broker.orders.append(existing_order)
        broker.fills.append(existing_fill)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.sync_after_restart()

        # No duplicate orders or fills
        assert report.fills_synced == 0
        assert report.fills_duplicate == 1  # fill already exists
        orders = ledger.read_records("orders.jsonl")
        assert len(orders) == 1  # no duplicate order written

    def test_sync_after_restart_broker_error(self, broker, ledger, oms):
        """Broker failure during restart sync returns report with errors."""
        broker.raise_on_get_orders = RuntimeError("Broker unavailable")

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.sync_after_restart()

        assert len(report.errors) >= 1

    def test_sync_mixed_scenario(self, broker, ledger, oms):
        """Full_sync handles mixed mismatches correctly."""
        # Local only
        local_only = make_order(
            client_order_id="coid_local",
            order_id="ord_local",
            status=OrderStatus.SUBMITTED,
        )
        # Broker only
        broker_only = make_order(
            client_order_id="coid_broker",
            order_id="ord_broker",
            status=OrderStatus.ACCEPTED,
        )
        # In both, status match
        both_match = make_order(
            client_order_id="coid_both",
            order_id="ord_both",
            status=OrderStatus.ACCEPTED,
        )

        ledger.append_order(local_only)
        ledger.append_order(both_match)
        broker.orders.append(broker_only)
        broker.orders.append(both_match)

        sync = BrokerStateSync(broker, ledger, oms)
        report = sync.full_sync()

        assert report.orders_matched == 1  # both_match
        assert len(report.orders_missing_local) == 1  # broker_only
        assert len(report.orders_missing_broker) == 1  # local_only
