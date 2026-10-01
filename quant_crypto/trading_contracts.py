"""Stable BTC-owned strategy-to-execution contracts.

These types intentionally live in ``quant_crypto`` so official BTC sparse
worktrees and full checkouts use the same Python class identities.  Wire
values and fields remain compatible with the legacy asset-neutral records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from quant_shared.core.time import ensure_utc, utc_now


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class SignalDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


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
    signal_id: str = field(default_factory=lambda: _new_id("sig"))

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
    target_position_id: str = field(default_factory=lambda: _new_id("tgt"))

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
    client_order_id: str = field(default_factory=lambda: _new_id("coid"))
    order_intent_id: str = field(default_factory=lambda: _new_id("oint"))

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
    risk_check_id: str = field(default_factory=lambda: _new_id("risk"))
    adjusted_quantity: float | None = None
    risk_version: str = "risk_v0.1.0"
    rule_name: str = ""
    threshold: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", ensure_utc(self.checked_at))


__all__ = [
    "OrderIntent",
    "OrderSide",
    "OrderType",
    "RiskDecision",
    "Signal",
    "SignalDirection",
    "TargetPosition",
    "TimeInForce",
]
