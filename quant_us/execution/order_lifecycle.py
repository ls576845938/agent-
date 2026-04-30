from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import OrderStatus
from quant_us.core.types import Order
from quant_us.execution.broker_base import BrokerBase


OPEN_ORDER_STATUSES = {
    OrderStatus.CREATED,
    OrderStatus.RISK_CHECKED,
    OrderStatus.SUBMITTED,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
}


@dataclass(frozen=True)
class OrderLifecycleConfig:
    max_open_seconds: float = 300.0
    cancellable_statuses: set[OrderStatus] = field(default_factory=lambda: set(OPEN_ORDER_STATUSES))


@dataclass(frozen=True)
class OrderLifecycleAction:
    order_id: str
    action: str
    reason: str
    age_seconds: float


class OrderLifecycleManager:
    def __init__(self, config: OrderLifecycleConfig | None = None) -> None:
        self.config = config or OrderLifecycleConfig()

    def stale_orders(self, orders: list[Order], now: datetime | None = None) -> list[tuple[Order, float]]:
        current = ensure_utc(now or utc_now())
        stale: list[tuple[Order, float]] = []
        for order in orders:
            if order.status not in self.config.cancellable_statuses:
                continue
            age = max(0.0, (current - ensure_utc(order.updated_at)).total_seconds())
            if age >= self.config.max_open_seconds:
                stale.append((order, age))
        return stale

    def cancel_stale_orders(self, broker: BrokerBase, now: datetime | None = None) -> list[OrderLifecycleAction]:
        actions: list[OrderLifecycleAction] = []
        for order, age in self.stale_orders(broker.get_orders(), now=now):
            broker.cancel_order(order.order_id)
            actions.append(
                OrderLifecycleAction(
                    order_id=order.order_id,
                    action="cancel",
                    reason="order_timeout",
                    age_seconds=age,
                )
            )
        return actions
