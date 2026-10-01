from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from quant_us.core.clock import utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.paper_broker import PaperBroker


ALLOWED_IBKR_PAPER_PORTS: tuple[int, ...] = (4002, 7497)
IBKR_LIVE_PORTS: tuple[int, ...] = (4001, 7496)


def classify_ibkr_endpoint(port: int) -> str:
    if port in ALLOWED_IBKR_PAPER_PORTS:
        return "paper"
    if port in IBKR_LIVE_PORTS:
        return "live"
    return "unsupported"


@dataclass(frozen=True)
class IBKRBrokerConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    connect_timeout_seconds: float = 10.0


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _utc_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class IBKRBroker(PaperBroker):
    """IBKR paper-only, read-only adapter foundation.

    A client must be injected explicitly. Construction never imports an IBKR
    library and never opens a socket. The only enabled network surface is the
    caller-invoked ``connect()`` method, which enforces the two documented paper
    ports and requests a read-only session. Order submission and cancellation
    are permanently blocked in this foundation.
    """

    broker_name = "ibkr"

    def __init__(self, config: IBKRBrokerConfig, *, client: Any | None = None) -> None:
        endpoint_kind = classify_ibkr_endpoint(config.port)
        if endpoint_kind == "live":
            raise ValueError(f"ibkr_live_endpoint_forbidden:{config.port}")
        if endpoint_kind != "paper":
            raise ValueError(f"ibkr_paper_port_not_allowed:{config.port}")

        super().__init__(broker_name=self.broker_name)
        self.config = config
        self._client = client
        self.submit_call_count = 0
        self.cancel_call_count = 0
        self.submit_attempt_count = 0
        self.cancel_attempt_count = 0

    @classmethod
    def contract_capabilities(cls) -> dict[str, bool]:
        return {
            "submit_order": False,
            "cancel_order": False,
            "poll_orders": True,
            "sync_fills": True,
            "sync_account": True,
            "sync_positions": True,
            "readiness_report": True,
        }

    @property
    def endpoint_kind(self) -> str:
        return classify_ibkr_endpoint(self.config.port)

    @property
    def is_readonly(self) -> bool:
        return True

    def connect(self) -> None:
        if self._client is None:
            raise RuntimeError("ibkr_paper_client_not_injected")
        if self.is_connected():
            return

        result = self._client.connect(
            self.config.host,
            self.config.port,
            clientId=self.config.client_id,
            readonly=True,
            timeout=self.config.connect_timeout_seconds,
        )
        if result is False or not self.is_connected():
            raise RuntimeError("ibkr_paper_readonly_connect_failed")

    def disconnect(self) -> None:
        if self._client is None or not self.is_connected():
            return
        self._client.disconnect()

    def is_connected(self) -> bool:
        if self._client is None:
            return False
        checker = getattr(self._client, "isConnected", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def health_check(self) -> dict[str, Any]:
        connected = self.is_connected()
        return {
            "ok": connected,
            "broker": self.broker_name,
            "connected": connected,
            "endpoint_kind": self.endpoint_kind,
            "host": self.config.host,
            "port": self.config.port,
            "readonly": True,
            "submit_capable": False,
            "cancel_capable": False,
        }

    def readiness_report(self) -> dict[str, object]:
        health = self.health_check()
        return {
            "adapter": "ibkr_paper",
            "paper_only": True,
            "endpoint_kind": self.endpoint_kind,
            "host": self.config.host,
            "port": self.config.port,
            "allowed_ports": list(ALLOWED_IBKR_PAPER_PORTS),
            "connected": bool(health["connected"]),
            "readonly": True,
            "read_only_sync_capable": True,
            "submit_capable": False,
            "cancel_capable": False,
            "submit_blocked_reason": "ibkr_paper_submit_cancel_disabled_fail_closed",
        }

    def _require_connected_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("ibkr_paper_client_not_injected")
        if not self.is_connected():
            raise RuntimeError("ibkr_paper_readonly_client_not_connected")
        return self._client

    def _call_read(self, *names: str) -> Any:
        client = self._require_connected_client()
        for name in names:
            method = getattr(client, name, None)
            if callable(method):
                return method()
        raise RuntimeError("ibkr_paper_read_surface_missing:" + ",".join(names))

    def sync_account(self) -> AccountState:
        summary = list(self._call_read("accountSummary", "account_summary"))
        values: dict[str, float] = {}
        account_id = "ibkr_paper"
        for row in summary:
            tag = str(_field(row, "tag", ""))
            if tag:
                values[tag] = _float(_field(row, "value"))
            account_id = str(_field(row, "account", account_id) or account_id)
        positions = self.sync_positions()
        return AccountState(
            timestamp_utc=utc_now(),
            account_id=account_id,
            cash=values.get("TotalCashValue", values.get("CashBalance", 0.0)),
            equity=values.get("NetLiquidation", 0.0),
            buying_power=values.get("BuyingPower", 0.0),
            positions=positions,
        )

    def sync_positions(self) -> dict[str, Position]:
        rows = list(self._call_read("positions"))
        positions: dict[str, Position] = {}
        for row in rows:
            contract = _field(row, "contract")
            symbol = str(_field(contract, "symbol", _field(row, "symbol", ""))).upper()
            if not symbol:
                continue
            positions[symbol] = Position(
                symbol=symbol,
                quantity=_float(_field(row, "position", _field(row, "quantity", 0.0))),
                avg_price=_float(_field(row, "avgCost", _field(row, "avg_price", 0.0))),
                market_price=_float(_field(row, "marketPrice", _field(row, "market_price", 0.0))),
                unrealized_pnl=_float(
                    _field(row, "unrealizedPNL", _field(row, "unrealized_pnl", 0.0))
                ),
            )
        return positions

    def sync_open_orders(self) -> list[Order]:
        raw_orders = list(self._call_read("openTrades", "open_trades", "openOrders", "open_orders"))
        return [self._map_order(raw) for raw in raw_orders]

    def sync_fills(self, order_id: str | None = None) -> list[Fill]:
        raw_fills = list(self._call_read("fills"))
        fills = [self._map_fill(raw) for raw in raw_fills]
        if order_id is None:
            return fills
        expected = str(order_id)
        return [
            fill
            for fill in fills
            if fill.order_id == expected or fill.broker_order_id == expected
        ]

    def get_account(self) -> AccountState:
        if self._client is None:
            return super().get_account()
        return self.sync_account()

    def get_positions(self) -> dict[str, Position]:
        if self._client is None:
            return super().get_positions()
        return self.sync_positions()

    def get_open_orders(self) -> list[Order]:
        return self.sync_open_orders()

    def get_orders(self) -> list[Order]:
        if self._client is None:
            return super().get_orders()
        return self.sync_open_orders()

    def poll_orders(self) -> list[Order]:
        return self.sync_open_orders()

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        if self._client is None:
            return super().get_fills(order_id)
        return self.sync_fills(order_id)

    def submit_order(self, order: Order) -> Order:
        self.submit_attempt_count += 1
        raise NotImplementedError(
            "IBKR adapter boundary is present; "
            "ibkr_paper_submit_disabled_fail_closed"
        )

    def cancel_order(self, order_id: str) -> Order:
        self.cancel_attempt_count += 1
        raise RuntimeError("ibkr_paper_cancel_disabled_fail_closed")

    def _map_order(self, raw: Any) -> Order:
        if isinstance(raw, Order):
            return raw
        contract = _field(raw, "contract")
        source_order = _field(raw, "order", raw)
        source_status = _field(raw, "orderStatus", raw)
        broker_order_id = str(
            _field(source_order, "orderId", _field(source_order, "order_id", ""))
        )
        side_text = str(_field(source_order, "action", "BUY")).upper()
        order_type_text = str(_field(source_order, "orderType", "MKT")).upper()
        tif_text = str(_field(source_order, "tif", "DAY")).upper()
        status_text = str(_field(source_status, "status", "Unknown")).lower()
        return Order(
            timestamp_utc=utc_now(),
            strategy_id="ibkr_paper_readonly",
            symbol=str(_field(contract, "symbol", _field(raw, "symbol", ""))).upper(),
            side=OrderSide.SELL if side_text in {"SELL", "SLD"} else OrderSide.BUY,
            quantity=_float(
                _field(source_order, "totalQuantity", _field(source_order, "quantity", 0.0))
            ),
            order_type={
                "LMT": OrderType.LIMIT,
                "LIMIT": OrderType.LIMIT,
                "STP": OrderType.STOP,
                "STOP": OrderType.STOP,
            }.get(order_type_text, OrderType.MARKET),
            time_in_force={
                "GTC": TimeInForce.GTC,
                "IOC": TimeInForce.IOC,
                "FOK": TimeInForce.FOK,
            }.get(tif_text, TimeInForce.DAY),
            client_order_id=str(
                _field(source_order, "orderRef", "") or f"ibkr-{broker_order_id}"
            ),
            broker_order_id=broker_order_id,
            limit_price=(
                _float(_field(source_order, "lmtPrice"))
                if order_type_text in {"LMT", "LIMIT"}
                else None
            ),
            metadata={"source": "ibkr_paper_readonly"},
            status={
                "pendingsubmit": OrderStatus.SUBMITTED,
                "presubmitted": OrderStatus.SUBMITTED,
                "submitted": OrderStatus.SUBMITTED,
                "filled": OrderStatus.FILLED,
                "cancelled": OrderStatus.CANCELLED,
                "inactive": OrderStatus.REJECTED,
            }.get(status_text, OrderStatus.UNKNOWN),
        )

    def _map_fill(self, raw: Any) -> Fill:
        if isinstance(raw, Fill):
            return raw
        contract = _field(raw, "contract")
        execution = _field(raw, "execution", raw)
        commission_report = _field(raw, "commissionReport")
        broker_order_id = str(
            _field(execution, "orderId", _field(execution, "order_id", ""))
        )
        side_text = str(_field(execution, "side", "BOT")).upper()
        return Fill(
            order_id=broker_order_id,
            symbol=str(_field(contract, "symbol", _field(raw, "symbol", ""))).upper(),
            side=OrderSide.SELL if side_text in {"SELL", "SLD"} else OrderSide.BUY,
            quantity=_float(_field(execution, "shares", _field(execution, "quantity", 0.0))),
            price=_float(_field(execution, "price", 0.0)),
            commission=_float(_field(commission_report, "commission", 0.0)),
            filled_at=_utc_datetime(_field(execution, "time")),
            broker="ibkr_paper",
            broker_order_id=broker_order_id,
            fill_id=str(_field(execution, "execId", "") or f"ibkr-fill-{broker_order_id}"),
        )
