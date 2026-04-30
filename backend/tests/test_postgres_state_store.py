from __future__ import annotations

import unittest
from datetime import datetime, timezone

from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Fill, Order, PortfolioSnapshot
from quant_us.data.storage.postgres_store import PostgresConfig, PostgresStateStore


class FakeCursor:
    def __init__(self, calls) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def executemany(self, sql, rows):
        self.calls.append((sql, rows))


class FakeConnection:
    def __init__(self) -> None:
        self.calls = []
        self.commit_count = 0

    def cursor(self):
        return FakeCursor(self.calls)

    def commit(self):
        self.commit_count += 1


class PostgresStateStoreTests(unittest.TestCase):
    def test_writes_orders_fills_and_snapshots(self) -> None:
        connection = FakeConnection()
        store = PostgresStateStore(PostgresConfig(dsn="postgresql://test", schema="quant"), connection=connection)
        order = Order(
            timestamp_utc=datetime(2024, 1, 2, 15, 30, tzinfo=timezone.utc),
            strategy_id="portfolio",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="client_1",
            status=OrderStatus.FILLED,
        )
        fill = Fill(
            order_id=order.order_id,
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=1.0,
            price=100.0,
            commission=0.0,
            filled_at=datetime(2024, 1, 2, 15, 31, tzinfo=timezone.utc),
        )
        snapshot = PortfolioSnapshot(
            timestamp_utc=datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc),
            equity=100_100.0,
            cash=90_000.0,
            gross_exposure=10_000.0,
            net_exposure=10_000.0,
            daily_pnl=100.0,
            drawdown=0.0,
        )

        counts = store.write_result(type("Result", (), {"orders": [order], "fills": [fill], "snapshots": [snapshot]})())

        self.assertEqual(counts, {"orders": 1, "fills": 1, "snapshots": 1})
        self.assertEqual(connection.commit_count, 3)
        self.assertEqual(len(connection.calls), 3)
        self.assertIn("insert into quant.orders", connection.calls[0][0])
        self.assertEqual(connection.calls[0][1][0]["side"], "buy")
        self.assertEqual(connection.calls[0][1][0]["status"], "filled")


if __name__ == "__main__":
    unittest.main()
