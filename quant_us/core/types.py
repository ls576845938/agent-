from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import uuid4

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.enums import AssetClass, OrderSide, OrderStatus, OrderType, SignalDirection, TimeInForce


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    asset_id: str = ""
    exchange: str = ""
    name: str = ""
    asset_type: AssetClass = AssetClass.EQUITY
    currency: str = "USD"
    listing_date: date | None = None
    delisting_date: date | None = None
    is_active: bool = True
    sector: str = ""
    industry: str = ""


@dataclass(frozen=True)
class Bar:
    timestamp_utc: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None
    source: str = ""
    session: str = ""
    adjusted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
        object.__setattr__(self, "symbol", self.symbol.upper())


@dataclass(frozen=True)
class Signal:
    timestamp_utc: datetime
    strategy_id: str
    symbol: str
    direction: SignalDirection
    strength: float
    horizon: str
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: new_id("sig"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "strength", max(0.0, min(1.0, float(self.strength))))


@dataclass(frozen=True)
class TargetPosition:
    timestamp_utc: datetime
    strategy_id: str
    symbol: str
    target_weight: float
    target_quantity: float | None = None
    signal_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    target_position_id: str = field(default_factory=lambda: new_id("tgt"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
        object.__setattr__(self, "symbol", self.symbol.upper())


@dataclass(frozen=True)
class OrderIntent:
    timestamp_utc: datetime
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.DAY
    run_id: str = ""
    signal_id: str = ""
    target_position_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    client_order_id: str = field(default_factory=lambda: new_id("coid"))
    order_intent_id: str = field(default_factory=lambda: new_id("oint"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
        object.__setattr__(self, "symbol", self.symbol.upper())
        object.__setattr__(self, "quantity", float(self.quantity))


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    order_intent_id: str
    checked_at: datetime = field(default_factory=utc_now)
    risk_check_id: str = field(default_factory=lambda: new_id("risk"))
    adjusted_quantity: float | None = None
    risk_version: str = "risk_v0.1.0"
    rule_name: str = ""
    threshold: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", ensure_utc(self.checked_at))


@dataclass
class Order:
    timestamp_utc: datetime
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType
    time_in_force: TimeInForce
    client_order_id: str
    run_id: str = ""
    signal_id: str = ""
    risk_check_id: str = ""
    broker_order_id: str = ""
    limit_price: float | None = None
    status: OrderStatus = OrderStatus.CREATED
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    order_id: str = field(default_factory=lambda: new_id("ord"))

    @classmethod
    def from_intent(cls, intent: OrderIntent, risk_decision: RiskDecision) -> "Order":
        quantity = risk_decision.adjusted_quantity if risk_decision.adjusted_quantity is not None else intent.quantity
        return cls(
            timestamp_utc=intent.timestamp_utc,
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=quantity,
            order_type=intent.order_type,
            time_in_force=intent.time_in_force,
            client_order_id=intent.client_order_id,
            run_id=intent.run_id,
            signal_id=intent.signal_id,
            risk_check_id=risk_decision.risk_check_id,
            limit_price=intent.limit_price,
            status=OrderStatus.RISK_CHECKED,
        )


@dataclass(frozen=True)
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    commission: float
    filled_at: datetime
    broker: str = ""
    broker_order_id: str = ""
    fill_id: str = field(default_factory=lambda: new_id("fill"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "filled_at", ensure_utc(self.filled_at))
        object.__setattr__(self, "symbol", self.symbol.upper())


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    market_price: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.market_price


@dataclass(frozen=True)
class AccountState:
    timestamp_utc: datetime
    account_id: str
    cash: float
    equity: float
    buying_power: float
    positions: dict[str, Position] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))


@dataclass(frozen=True)
class PortfolioSnapshot:
    timestamp_utc: datetime
    equity: float
    cash: float
    gross_exposure: float
    net_exposure: float
    daily_pnl: float = 0.0
    drawdown: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))
