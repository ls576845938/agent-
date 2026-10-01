"""Lazy ib_insync facade for the paper-only IBKR adapters.

Importing this module does not import ib_insync, construct a socket, or connect
to Gateway.  ``from_installed_sdk`` is the only SDK-loading boundary and still
returns a disconnected client until the paper runtime explicitly connects it.
"""

from __future__ import annotations

from typing import Any, Callable

from quant_us.execution.ibkr_paper_execution_adapter import (
    IBKRCancelPayload,
    IBKRContractPayload,
    IBKROrderPayload,
)


class IBInsyncClientFacade:
    """Translate SDK-neutral payloads into ib_insync objects."""

    offline_replay = False
    network_access = True

    def __init__(
        self,
        *,
        ib: Any,
        stock_factory: Callable[..., Any],
        order_factory: Callable[..., Any],
    ) -> None:
        self._ib = ib
        self._stock_factory = stock_factory
        self._order_factory = order_factory
        self.market_data_type = 0

    @classmethod
    def from_installed_sdk(cls) -> "IBInsyncClientFacade":
        from ib_insync import IB, Order, Stock  # type: ignore

        return cls(ib=IB(), stock_factory=Stock, order_factory=Order)

    def make_contract(self, symbol: str) -> Any:
        return self._stock_factory(str(symbol).upper(), "SMART", "USD")

    def connect(self, host: str, port: int, **kwargs: Any) -> Any:
        return self._ib.connect(host, port, **kwargs)

    def disconnect(self) -> Any:
        return self._ib.disconnect()

    def isConnected(self) -> bool:  # noqa: N802
        return bool(self._ib.isConnected())

    def accountSummary(self) -> Any:  # noqa: N802
        return self._ib.accountSummary()

    def managedAccounts(self) -> Any:  # noqa: N802
        return self._ib.managedAccounts()

    def positions(self) -> Any:
        return self._ib.positions()

    def openTrades(self) -> Any:  # noqa: N802
        return self._ib.openTrades()

    def openOrders(self) -> Any:  # noqa: N802
        return self._ib.openOrders()

    def fills(self) -> Any:
        return self._ib.fills()

    def reqMarketDataType(self, market_data_type: int) -> Any:  # noqa: N802
        return self._ib.reqMarketDataType(market_data_type)

    def qualifyContracts(self, *contracts: Any) -> Any:  # noqa: N802
        return self._ib.qualifyContracts(*contracts)

    def reqMktData(self, contract: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        return self._ib.reqMktData(self._contract(contract), *args, **kwargs)

    def cancelMktData(self, contract: Any) -> Any:  # noqa: N802
        return self._ib.cancelMktData(self._contract(contract))

    def reqHistoricalData(self, contract: Any, **kwargs: Any) -> Any:  # noqa: N802
        return self._ib.reqHistoricalData(self._contract(contract), **kwargs)

    def reqRealTimeBars(self, contract: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: N802
        return self._ib.reqRealTimeBars(self._contract(contract), *args, **kwargs)

    def cancelRealTimeBars(self, handle: Any) -> Any:  # noqa: N802
        return self._ib.cancelRealTimeBars(handle)

    def waitOnUpdate(self, timeout: float = 1.0) -> Any:  # noqa: N802
        return self._ib.waitOnUpdate(timeout=timeout)

    def placeOrder(self, contract: Any, payload: Any) -> Any:  # noqa: N802
        return self._ib.placeOrder(self._contract(contract), self._order(payload))

    def cancelOrder(self, payload: Any) -> Any:  # noqa: N802
        if hasattr(payload, "order"):
            return self._ib.cancelOrder(payload.order)
        order_id = getattr(payload, "orderId", None)
        if order_id is None and isinstance(payload, IBKRCancelPayload):
            order_id = payload.orderId
        for trade in self._ib.openTrades():
            order = getattr(trade, "order", None)
            if str(getattr(order, "orderId", "")) == str(order_id):
                return self._ib.cancelOrder(order)
        return self._ib.cancelOrder(self._order_factory(orderId=int(order_id)))

    def reqGlobalCancel(self) -> Any:  # noqa: N802
        """Expose IBKR's emergency-only global cancel surface explicitly.

        The facade never invokes this method as a disconnect side effect; the
        adapter requires separate policy/operator authorization, audit,
        confirmation, and reconciliation before it can call the surface.
        """

        return self._ib.reqGlobalCancel()

    globalCancel = reqGlobalCancel

    def _contract(self, value: Any) -> Any:
        if isinstance(value, IBKRContractPayload):
            return self._stock_factory(value.symbol, value.exchange, value.currency)
        if isinstance(value, dict):
            return self._stock_factory(
                str(value.get("symbol", "")).upper(),
                str(value.get("exchange", "SMART")),
                str(value.get("currency", "USD")),
            )
        return value

    def _order(self, value: Any) -> Any:
        if not isinstance(value, IBKROrderPayload):
            return value
        kwargs: dict[str, Any] = {
            "action": value.action,
            "totalQuantity": value.totalQuantity,
            "orderType": value.orderType,
            "tif": value.tif,
            "orderRef": value.orderRef,
        }
        if value.lmtPrice is not None:
            kwargs["lmtPrice"] = value.lmtPrice
        return self._order_factory(**kwargs)


def build_disconnected_ib_insync_facade() -> IBInsyncClientFacade:
    """Return a disconnected facade; never connect as a factory side effect."""

    return IBInsyncClientFacade.from_installed_sdk()
