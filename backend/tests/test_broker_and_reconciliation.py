from __future__ import annotations

import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from quant_us.core.enums import OrderSide, OrderType, TimeInForce
from quant_us.core.types import Fill, Order
from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
from quant_us.execution.ledger import JsonlLedgerStore
from quant_us.execution.paper_broker import PaperBroker
from quant_us.live.reconciliation_service import ReconciliationService


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/v2/account"):
            return FakeResponse({"id": "acct_1", "cash": "1000.00", "equity": "1100.00", "buying_power": "1000.00"})
        if url.endswith("/v2/positions"):
            return FakeResponse(
                [
                    {
                        "symbol": "AAPL",
                        "qty": "2",
                        "avg_entry_price": "100",
                        "current_price": "110",
                        "unrealized_pl": "20",
                    }
                ]
            )
        if url.endswith("/v2/orders") and method == "POST":
            return FakeResponse(
                {
                    "id": "broker_order_1",
                    "client_order_id": kwargs["json"]["client_order_id"],
                    "symbol": kwargs["json"]["symbol"],
                    "qty": kwargs["json"]["qty"],
                    "side": kwargs["json"]["side"],
                    "type": kwargs["json"]["type"],
                    "time_in_force": kwargs["json"]["time_in_force"],
                    "status": "accepted",
                    "created_at": "2024-01-02T15:30:00Z",
                    "updated_at": "2024-01-02T15:30:01Z",
                }
            )
        if url.endswith("/v2/account/activities"):
            return FakeResponse(
                [
                    {
                        "id": "fill_1",
                        "order_id": "broker_order_1",
                        "symbol": "AAPL",
                        "side": "buy",
                        "qty": "2",
                        "price": "100",
                        "commission": "0",
                        "transaction_time": "2024-01-02T15:30:02Z",
                    }
                ]
            )
        return FakeResponse({})


class BrokerAndReconciliationTests(unittest.TestCase):
    def test_alpaca_adapter_maps_account_positions_orders_and_fills(self) -> None:
        broker = AlpacaBroker(
            AlpacaBrokerConfig(api_key="key", api_secret="secret"),
            session=FakeSession(),
        )
        account = broker.get_account()
        self.assertEqual(account.account_id, "acct_1")
        self.assertEqual(account.positions["AAPL"].quantity, 2.0)

        order = Order(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            strategy_id="portfolio",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=2.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="client_1",
        )
        submitted = broker.submit_order(order)
        self.assertEqual(submitted.broker_order_id, "broker_order_1")
        self.assertEqual(submitted.status.value, "accepted")

        fills = broker.get_fills()
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0].symbol, "AAPL")

    def test_reconciliation_reports_clean_and_break_states(self) -> None:
        with TemporaryDirectory() as directory:
            ledger = JsonlLedgerStore(directory)
            ledger.append_fill(
                Fill(
                    order_id="order_1",
                    symbol="AAPL",
                    side=OrderSide.BUY,
                    quantity=2.0,
                    price=100.0,
                    commission=0.0,
                    filled_at=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
                )
            )
            broker = PaperBroker()
            broker.positions = ledger.latest_positions_from_fills()
            clean = ReconciliationService(directory, broker).reconcile_positions()
            self.assertEqual(clean["status"], "clean")

            broker.positions["AAPL"].quantity = 1.0
            broken = ReconciliationService(directory, broker).reconcile_positions()
            self.assertEqual(broken["status"], "breaks_detected")
            self.assertEqual(broken["break_count"], 1)


if __name__ == "__main__":
    unittest.main()
