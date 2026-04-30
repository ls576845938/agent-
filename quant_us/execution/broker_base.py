from __future__ import annotations

from abc import ABC, abstractmethod

from quant_us.core.types import AccountState, Fill, Order, Position


class BrokerBase(ABC):
    broker_name: str

    @abstractmethod
    def get_account(self) -> AccountState:
        raise NotImplementedError

    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        raise NotImplementedError

    @abstractmethod
    def get_orders(self) -> list[Order]:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order:
        raise NotImplementedError

    @abstractmethod
    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        raise NotImplementedError
