from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderStatus
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.broker_base import BrokerBase


@dataclass
class PaperBroker(BrokerBase):
    initial_cash: float = 100_000.0
    broker_name: str = "paper"
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    def get_account(self) -> AccountState:
        with self._lock:
            cash = self.cash
            equity = self.cash + sum(position.market_value for position in self.positions.values())
            positions = dict(self.positions)
        return AccountState(
            timestamp_utc=utc_now(),
            account_id=self.broker_name,
            cash=cash,
            equity=equity,
            buying_power=cash,
            positions=positions,
        )

    def get_positions(self) -> dict[str, Position]:
        with self._lock:
            return dict(self.positions)

    def get_orders(self) -> list[Order]:
        with self._lock:
            return list(self.orders)

    def submit_order(self, order: Order) -> Order:
        with self._lock:
            for existing in self.orders:
                if existing.client_order_id and existing.client_order_id == order.client_order_id:
                    return existing
            order.status = OrderStatus.ACCEPTED
            order.updated_at = utc_now()
            self.orders.append(order)
            return order

    def cancel_order(self, order_id: str) -> Order:
        with self._lock:
            for order in self.orders:
                if order.order_id == order_id:
                    order.status = OrderStatus.CANCELLED
                    order.updated_at = utc_now()
                    return order
        raise KeyError(order_id)

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        with self._lock:
            if order_id is None:
                return list(self.fills)
            return [fill for fill in self.fills if fill.order_id == order_id]

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "broker": self.broker_name}
