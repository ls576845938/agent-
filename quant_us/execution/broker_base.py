from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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

    def health_check(self) -> dict[str, Any]:
        try:
            self.get_account()
        except Exception as exc:
            return {
                "ok": False,
                "broker": getattr(self, "broker_name", self.__class__.__name__),
                "error": str(exc),
            }
        return {
            "ok": True,
            "broker": getattr(self, "broker_name", self.__class__.__name__),
        }
