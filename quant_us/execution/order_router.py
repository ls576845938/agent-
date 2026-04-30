from __future__ import annotations

from quant_us.core.types import Order
from quant_us.execution.broker_base import BrokerBase


class OrderRouter:
    def __init__(self, broker: BrokerBase) -> None:
        self.broker = broker

    def route(self, order: Order) -> Order:
        return self.broker.submit_order(order)
