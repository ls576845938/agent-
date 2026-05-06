from __future__ import annotations

import pytest

from quant_us.execution.fill_sync import FillSync, FillSyncResult

from .conftest import make_fill, make_order


class TestFillSync:
    """Tests for FillSync."""

    def test_sync_fills_empty(self, broker, ledger):
        """No fills on broker returns zeros."""
        fs = FillSync(broker, ledger)
        result = fs.sync_fills()
        assert isinstance(result, FillSyncResult)
        assert result.fills_found == 0
        assert result.fills_new == 0
        assert result.fills_duplicate == 0

    def test_sync_new_fill(self, broker, ledger):
        """New fill from broker is written to ledger."""
        fill = make_fill(fill_id="fill_new_001")
        broker.fills.append(fill)

        fs = FillSync(broker, ledger)
        result = fs.sync_fills()

        assert result.fills_found == 1
        assert result.fills_new == 1
        assert result.fills_duplicate == 0
        records = ledger.read_records("fills.jsonl")
        assert len(records) == 1
        assert records[0]["fill_id"] == "fill_new_001"

    def test_sync_duplicate_fill(self, broker, ledger):
        """Fill already in ledger is detected as duplicate."""
        fill = make_fill(fill_id="fill_dup_001")
        ledger.append_fill(fill)
        broker.fills.append(fill)

        fs = FillSync(broker, ledger)
        result = fs.sync_fills()

        assert result.fills_found == 1
        assert result.fills_new == 0
        assert result.fills_duplicate == 1

    def test_sync_multiple_fills_mixed(self, broker, ledger):
        """Mix of new and duplicate fills."""
        fill1 = make_fill(order_id="ord_001", fill_id="fill_001")
        fill2 = make_fill(order_id="ord_002", fill_id="fill_002")
        fill3 = make_fill(order_id="ord_003", fill_id="fill_003")

        ledger.append_fill(fill1)  # Already in ledger
        broker.fills.extend([fill1, fill2, fill3])

        fs = FillSync(broker, ledger)
        result = fs.sync_fills()

        assert result.fills_found == 3
        assert result.fills_new == 2
        assert result.fills_duplicate == 1
        records = ledger.read_records("fills.jsonl")
        assert len(records) == 3  # 1 existing + 2 new

    def test_sync_fills_by_order_id(self, broker, ledger):
        """Filter fills by order_id."""
        fill1 = make_fill(order_id="ord_001", fill_id="fill_001")
        fill2 = make_fill(order_id="ord_002", fill_id="fill_002")
        broker.fills.extend([fill1, fill2])

        fs = FillSync(broker, ledger)
        result = fs.sync_fills(order_id="ord_001")

        assert result.fills_found == 1
        assert result.fills_new == 1
        records = ledger.read_records("fills.jsonl")
        assert len(records) == 1
        assert records[0]["fill_id"] == "fill_001"

    def test_sync_all_open_orders(self, broker, ledger):
        """Sync fills for all orders in ledger."""
        order1 = make_order(client_order_id="coid_001", order_id="ord_001")
        order2 = make_order(client_order_id="coid_002", order_id="ord_002")
        ledger.append_order(order1)
        ledger.append_order(order2)

        fill1 = make_fill(order_id="ord_001", fill_id="fill_001")
        fill2 = make_fill(order_id="ord_002", fill_id="fill_002")
        broker.fills.extend([fill1, fill2])

        fs = FillSync(broker, ledger)
        result = fs.sync_all_open_orders()

        assert result.fills_found == 2
        assert result.fills_new == 2

    def test_sync_all_open_orders_no_orders(self, broker, ledger):
        """No orders in ledger -> no fills synced."""
        fs = FillSync(broker, ledger)
        result = fs.sync_all_open_orders()
        assert result.fills_found == 0
        assert result.fills_new == 0

    def test_broker_error_graceful(self, broker, ledger):
        """Broker failure returns empty result with error."""
        broker.raise_on_get_fills = RuntimeError("Broker unreachable")

        fs = FillSync(broker, ledger)
        result = fs.sync_fills()

        assert result.fills_found == 0
        assert len(result.errors) == 1
        assert "Broker unreachable" in result.errors[0]

    def test_partial_fill_handling(self, broker, ledger):
        """Multiple partial fills for same order are all synced."""
        fill1 = make_fill(order_id="ord_partial", fill_id="fill_p1", quantity=30.0)
        fill2 = make_fill(order_id="ord_partial", fill_id="fill_p2", quantity=70.0)
        broker.fills.extend([fill1, fill2])

        fs = FillSync(broker, ledger)
        result = fs.sync_fills()

        assert result.fills_found == 2
        assert result.fills_new == 2
        records = ledger.read_records("fills.jsonl")
        assert len(records) == 2

    def test_fill_without_fill_id(self, broker, ledger):
        """Fill without fill_id is skipped."""
        fill = make_fill(fill_id="")
        broker.fills.append(fill)

        fs = FillSync(broker, ledger)
        result = fs.sync_fills()

        assert result.fills_found == 1
        assert result.fills_new == 0  # skipped due to missing fill_id
