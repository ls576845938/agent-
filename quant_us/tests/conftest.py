from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import Fill, Order, Position


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _utc(val: str) -> datetime:
    return datetime.fromisoformat(val).replace(tzinfo=timezone.utc)


def make_order(
    client_order_id: str = "coid_abc123",
    symbol: str = "AAPL",
    side: OrderSide = OrderSide.BUY,
    quantity: float = 100.0,
    status: OrderStatus = OrderStatus.SUBMITTED,
    order_id: str = "ord_001",
    broker_order_id: str = "",
    **overrides: Any,
) -> Order:
    kwargs: dict[str, Any] = {
        "timestamp_utc": _utc("2026-05-04T14:00:00+00:00"),
        "strategy_id": "test_strat",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "client_order_id": client_order_id,
        "order_id": order_id,
        "broker_order_id": broker_order_id or f"broker_{order_id}",
        "status": status,
    }
    kwargs.update(overrides)
    return Order(**kwargs)


def make_fill(
    order_id: str = "ord_001",
    symbol: str = "AAPL",
    quantity: float = 100.0,
    price: float = 150.0,
    fill_id: str = "fill_001",
    broker_order_id: str = "",
) -> Fill:
    return Fill(
        order_id=order_id,
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        price=price,
        commission=0.0,
        filled_at=utc_now(),
        fill_id=fill_id,
        broker_order_id=broker_order_id or f"broker_{order_id}",
    )


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class MockBroker:
    """Mock broker with configurable return values."""

    def __init__(self) -> None:
        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self.positions: dict[str, Position] = {}
        self.raise_on_get_orders: Exception | None = None
        self.raise_on_get_fills: Exception | None = None
        self.raise_on_get_positions: Exception | None = None

    def get_orders(self) -> list[Order]:
        if self.raise_on_get_orders:
            raise self.raise_on_get_orders
        return list(self.orders)

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        if self.raise_on_get_fills:
            raise self.raise_on_get_fills
        if order_id is None:
            return list(self.fills)
        return [f for f in self.fills if f.order_id == order_id]

    def get_positions(self) -> dict[str, Position]:
        if self.raise_on_get_positions:
            raise self.raise_on_get_positions
        return dict(self.positions)

    def submit_order(self, order: Order) -> Order:
        return order

    def cancel_order(self, order_id: str) -> Order:
        return make_order(status=OrderStatus.CANCELLED)


class MockLedger:
    """In-memory ledger mock with same interface as JsonlLedgerStore."""

    def __init__(self) -> None:
        self.records: dict[str, list[dict[str, Any]]] = {
            "orders.jsonl": [],
            "fills.jsonl": [],
        }

    def append_order(self, order: Order) -> None:
        self.records["orders.jsonl"].append(_dataclass_to_dict(order))

    def append_fill(self, fill: Fill) -> None:
        self.records["fills.jsonl"].append(_dataclass_to_dict(fill))

    def read_records(self, name: str) -> list[dict[str, Any]]:
        return list(self.records.get(name, []))

    def latest_positions_from_fills(self) -> dict[str, Position]:
        positions: dict[str, Position] = {}
        for row in self.records["fills.jsonl"]:
            fill = _dict_to_fill(row)
            pos = positions.get(fill.symbol, Position(symbol=fill.symbol, market_price=fill.price))
            signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            old_qty = pos.quantity
            new_qty = old_qty + signed_qty
            if new_qty == 0:
                pos.quantity = 0.0
                pos.avg_price = 0.0
            elif signed_qty > 0:
                pos.avg_price = ((old_qty * pos.avg_price) + (fill.quantity * fill.price)) / new_qty
                pos.quantity = new_qty
            else:
                pos.quantity = new_qty
            pos.market_price = fill.price
            pos.unrealized_pnl = (pos.market_price - pos.avg_price) * pos.quantity if pos.avg_price else 0.0
            positions[fill.symbol] = pos
        return positions


class MockOMS:
    """Mock OMS with just the attributes the polling loop touches."""

    def __init__(self) -> None:
        self.reduce_only: bool = False


class MockKillSwitch:
    """Mock KillSwitch tracking calls."""

    def __init__(self) -> None:
        self.failures: int = 0
        self.triggered: bool = False
        self.reason: str = ""

    def record_order_failure(self) -> bool:
        self.failures += 1
        self.triggered = True
        self.reason = "order_failure"
        return True

    def record_order_success(self) -> None:
        pass


class MockRiskEventLog:
    """Mock risk event log capturing records."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def record(self, event_type: str, details: dict[str, Any]) -> None:
        self.events.append((event_type, details))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    d = asdict(obj)
    for k, v in d.items():
        if hasattr(v, "value"):
            d[k] = v.value
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _dict_to_fill(d: dict[str, Any]) -> Fill:
    return Fill(
        order_id=str(d.get("order_id", "")),
        symbol=str(d.get("symbol", "")),
        side=OrderSide(str(d.get("side", "buy"))),
        quantity=float(d.get("quantity", 0.0)),
        price=float(d.get("price", 0.0)),
        commission=float(d.get("commission", 0.0)),
        filled_at=datetime.fromisoformat(str(d.get("filled_at", "")).replace("Z", "+00:00")),
        broker=str(d.get("broker", "")),
        broker_order_id=str(d.get("broker_order_id", "")),
        fill_id=str(d.get("fill_id", "")),
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def broker() -> MockBroker:
    return MockBroker()


@pytest.fixture
def ledger() -> MockLedger:
    return MockLedger()


@pytest.fixture
def oms() -> MockOMS:
    return MockOMS()


@pytest.fixture
def kill_switch() -> MockKillSwitch:
    return MockKillSwitch()


@pytest.fixture
def risk_event_log() -> MockRiskEventLog:
    return MockRiskEventLog()
