from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quant_us.core.types import AccountState, Fill, Order, Position
from quant_us.execution.paper_broker import PaperBroker


PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"


@dataclass
class AlpacaBrokerConfig:
    api_key: str
    api_secret: str
    paper: bool = True
    base_url: str = PAPER_BASE_URL
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if self.paper and PAPER_BASE_URL not in self.base_url:
            raise ValueError(
                f"SAFETY: paper=True but base_url={self.base_url} does not point to paper endpoint. "
                f"Expected {PAPER_BASE_URL}"
            )
        if not self.paper and LIVE_BASE_URL not in self.base_url:
            raise ValueError(
                f"SAFETY: paper=False but base_url={self.base_url} does not point to live endpoint. "
                f"Expected {LIVE_BASE_URL}"
            )


class AlpacaBroker(PaperBroker):
    broker_name = "alpaca"

    def __init__(self, config: AlpacaBrokerConfig, session: Any | None = None) -> None:
        super().__init__(broker_name="alpaca")
        self.config = config
        self.base_url = config.base_url.rstrip("/")
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def get_account(self) -> AccountState:
        payload = self._request("GET", "/v2/account")
        positions = self.get_positions()
        return AccountState(
            timestamp_utc=utc_now(),
            account_id=str(payload.get("id") or payload.get("account_number") or "alpaca"),
            cash=_float(payload.get("cash")),
            equity=_float(payload.get("equity")),
            buying_power=_float(payload.get("buying_power")),
            positions=positions,
        )

    def get_positions(self) -> dict[str, Position]:
        rows = self._request("GET", "/v2/positions")
        positions: dict[str, Position] = {}
        for row in rows or []:
            symbol = str(row.get("symbol", "")).upper()
            if not symbol:
                continue
            positions[symbol] = Position(
                symbol=symbol,
                quantity=_float(row.get("qty")),
                avg_price=_float(row.get("avg_entry_price")),
                market_price=_float(row.get("current_price")),
                unrealized_pnl=_float(row.get("unrealized_pl")),
            )
        return positions

    def get_orders(self) -> list[Order]:
        rows = self._request("GET", "/v2/orders", params={"status": "all", "nested": "false", "limit": 500})
        return [self._order_from_payload(row) for row in rows or []]

    def submit_order(self, order: Order) -> Order:
        payload = {
            "symbol": order.symbol,
            "qty": str(order.quantity),
            "side": order.side.value,
            "type": order.order_type.value,
            "time_in_force": order.time_in_force.value,
            "client_order_id": order.client_order_id,
        }
        if order.limit_price is not None:
            payload["limit_price"] = str(order.limit_price)
        try:
            response = self._request("POST", "/v2/orders", json=payload)
        except RuntimeError as exc:
            if _is_duplicate_client_order_error(str(exc)):
                existing = self._find_order_by_client_order_id(order.client_order_id)
                if existing is not None:
                    self._apply_mapped_order(order, existing)
                    return order
            raise
        mapped = self._order_from_payload(response, fallback=order)
        self._apply_mapped_order(order, mapped)
        return order

    def _find_order_by_client_order_id(self, client_order_id: str) -> Order | None:
        if not client_order_id:
            return None
        for existing in self.get_orders():
            if existing.client_order_id == client_order_id:
                return existing
        return None

    @staticmethod
    def _apply_mapped_order(order: Order, mapped: Order) -> None:
        order.broker_order_id = mapped.broker_order_id
        order.order_id = mapped.order_id
        order.status = mapped.status
        order.updated_at = mapped.updated_at

    def cancel_order(self, order_id: str) -> Order:
        self._request("DELETE", f"/v2/orders/{order_id}")
        return Order(
            timestamp_utc=utc_now(),
            strategy_id="broker",
            symbol="",
            side=OrderSide.BUY,
            quantity=0.0,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            client_order_id="",
            broker_order_id=order_id,
            status=OrderStatus.CANCELLED,
        )

    def get_fills(self, order_id: str | None = None) -> list[Fill]:
        params: dict[str, str] = {"activity_types": "FILL"}
        rows = self._request("GET", "/v2/account/activities", params=params)
        fills = [self._fill_from_payload(row) for row in rows or []]
        if order_id is None:
            return fills
        return [fill for fill in fills if fill.order_id == order_id or fill.broker_order_id == order_id]

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(
            {
                "APCA-API-KEY-ID": self.config.api_key,
                "APCA-API-SECRET-KEY": self.config.api_secret,
            }
        )
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=self.config.timeout_seconds,
            **kwargs,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Alpaca API error {response.status_code}: {getattr(response, 'text', '')}")
        if response.status_code == 204:
            return {}
        return response.json()

    def health_check(self) -> dict[str, Any]:
        try:
            payload = self._request("GET", "/v2/account")
        except Exception as exc:
            return {"ok": False, "broker": self.broker_name, "error": str(exc)}
        return {
            "ok": True,
            "broker": self.broker_name,
            "account_id": str(payload.get("id") or payload.get("account_number") or ""),
            "paper": self.config.paper,
        }

    @staticmethod
    def _order_from_payload(payload: dict[str, Any], fallback: Order | None = None) -> Order:
        timestamp = _parse_time(payload.get("created_at")) or (fallback.timestamp_utc if fallback else utc_now())
        order = Order(
            timestamp_utc=timestamp,
            strategy_id=fallback.strategy_id if fallback else "broker",
            symbol=str(payload.get("symbol") or (fallback.symbol if fallback else "")).upper(),
            side=_order_side(payload.get("side"), fallback.side if fallback else OrderSide.BUY),
            quantity=_float(payload.get("qty") or payload.get("filled_qty") or (fallback.quantity if fallback else 0.0)),
            order_type=_order_type(payload.get("type"), fallback.order_type if fallback else OrderType.MARKET),
            time_in_force=_time_in_force(payload.get("time_in_force"), fallback.time_in_force if fallback else TimeInForce.DAY),
            client_order_id=str(payload.get("client_order_id") or (fallback.client_order_id if fallback else "")),
            run_id=fallback.run_id if fallback else "",
            signal_id=fallback.signal_id if fallback else "",
            risk_check_id=fallback.risk_check_id if fallback else "",
            broker_order_id=str(payload.get("id") or ""),
            limit_price=_optional_float(payload.get("limit_price")),
            status=_order_status(payload.get("status")),
            created_at=timestamp,
            updated_at=_parse_time(payload.get("updated_at")) or utc_now(),
            order_id=fallback.order_id if fallback else str(payload.get("client_order_id") or payload.get("id") or ""),
        )
        return order

    @staticmethod
    def _fill_from_payload(payload: dict[str, Any]) -> Fill:
        side = _order_side(payload.get("side"), OrderSide.BUY)
        return Fill(
            order_id=str(payload.get("order_id") or payload.get("id") or ""),
            symbol=str(payload.get("symbol") or "").upper(),
            side=side,
            quantity=_float(payload.get("qty")),
            price=_float(payload.get("price")),
            commission=_float(payload.get("commission")),
            filled_at=_parse_time(payload.get("transaction_time")) or utc_now(),
            broker="alpaca",
            broker_order_id=str(payload.get("order_id") or ""),
            fill_id=str(payload.get("id") or ""),
        )


def _float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _order_side(value: Any, default: OrderSide) -> OrderSide:
    try:
        return OrderSide(str(value).lower())
    except ValueError:
        return default


def _order_type(value: Any, default: OrderType) -> OrderType:
    try:
        return OrderType(str(value).lower())
    except ValueError:
        return default


def _time_in_force(value: Any, default: TimeInForce) -> TimeInForce:
    try:
        return TimeInForce(str(value).lower())
    except ValueError:
        return default


def _order_status(value: Any) -> OrderStatus:
    lookup = {
        "new": OrderStatus.ACCEPTED,
        "accepted": OrderStatus.ACCEPTED,
        "pending_new": OrderStatus.SUBMITTED,
        "partially_filled": OrderStatus.PARTIALLY_FILLED,
        "filled": OrderStatus.FILLED,
        "canceled": OrderStatus.CANCELLED,
        "cancelled": OrderStatus.CANCELLED,
        "expired": OrderStatus.EXPIRED,
        "rejected": OrderStatus.REJECTED,
        "stopped": OrderStatus.ERROR,
        "suspended": OrderStatus.ERROR,
    }
    return lookup.get(str(value).lower(), OrderStatus.SUBMITTED)


def _is_duplicate_client_order_error(message: str) -> bool:
    text = message.lower()
    duplicate_markers = ("duplicate", "already exists", "already been used")
    return "client_order_id" in text and any(marker in text for marker in duplicate_markers)
