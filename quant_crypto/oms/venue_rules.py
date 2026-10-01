from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any

from quant_shared.core.time import ensure_utc

from quant_crypto.trading_contracts import OrderIntent, OrderSide


BTC_VENUE_RULES_VERSION = "btc_venue_rules_v1"


@dataclass(frozen=True)
class BTCVenueRules:
    venue: str
    venue_symbol: str
    tick_size: float
    step_size: float
    min_quantity: float
    min_notional: float
    price_precision: int
    quantity_precision: int
    maker_fee_bps: float
    taker_fee_bps: float
    funding_interval_hours: float
    trading_calendar: str = "24/7"
    instrument_type: str = "perp"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in [
            "tick_size",
            "step_size",
            "min_quantity",
            "min_notional",
            "maker_fee_bps",
            "taker_fee_bps",
            "funding_interval_hours",
        ]:
            value = float(getattr(self, field_name))
            if value <= 0.0 and field_name not in {"maker_fee_bps", "taker_fee_bps"}:
                raise ValueError(f"{field_name} must be positive.")
            if value < 0.0:
                raise ValueError(f"{field_name} must be non-negative.")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "price_precision", int(self.price_precision))
        object.__setattr__(self, "quantity_precision", int(self.quantity_precision))
        if self.trading_calendar != "24/7":
            raise ValueError("BTC venue rules require 24/7 trading_calendar.")

    def to_metadata(self) -> dict[str, Any]:
        return {
            "venue_rules_version": BTC_VENUE_RULES_VERSION,
            "venue": self.venue,
            "venue_symbol": self.venue_symbol,
            "instrument_type": self.instrument_type,
            "tick_size": self.tick_size,
            "step_size": self.step_size,
            "min_quantity": self.min_quantity,
            "min_notional": self.min_notional,
            "price_precision": self.price_precision,
            "quantity_precision": self.quantity_precision,
            "maker_fee_bps": self.maker_fee_bps,
            "taker_fee_bps": self.taker_fee_bps,
            "funding_interval_hours": self.funding_interval_hours,
            "trading_calendar": self.trading_calendar,
            **dict(self.metadata),
        }


@dataclass(frozen=True)
class BTCVenueValidation:
    approved: bool
    blockers: list[str]
    normalized_quantity: float
    normalized_price: float | None
    notional: float
    fee_bps: float
    metadata: dict[str, Any]


def apply_btc_venue_rules(
    intent: OrderIntent,
    *,
    venue_rules: BTCVenueRules,
    reference_price: float,
    post_only: bool = False,
    decision_time_utc: datetime | None = None,
) -> BTCVenueValidation:
    if reference_price <= 0.0:
        raise ValueError("reference_price must be positive.")
    blockers: list[str] = []
    timestamp = ensure_utc(decision_time_utc or intent.timestamp_utc)
    if venue_rules.trading_calendar != "24/7":
        blockers.append("btc_calendar_not_24_7")

    normalized_price = normalize_btc_price(reference_price, venue_rules.tick_size, intent.side)
    normalized_quantity = normalize_btc_quantity(intent.quantity, venue_rules.step_size)
    notional = normalized_quantity * normalized_price
    if normalized_quantity <= 0.0:
        blockers.append("btc_quantity_below_step_size")
    if normalized_quantity < venue_rules.min_quantity:
        blockers.append("btc_quantity_below_min_quantity")
    if notional < venue_rules.min_notional:
        blockers.append("btc_notional_below_min_notional")

    fee_bps = venue_rules.maker_fee_bps if post_only else venue_rules.taker_fee_bps
    metadata = {
        **venue_rules.to_metadata(),
        "decision_time_utc": timestamp.isoformat(),
        "reference_price": float(reference_price),
        "normalized_price": normalized_price,
        "normalized_quantity": normalized_quantity,
        "notional": notional,
        "fee_side": "maker" if post_only else "taker",
        "fee_bps": fee_bps,
        "order_type": intent.order_type.value,
        "time_in_force": intent.time_in_force.value,
        "side": intent.side.value,
        "best_execution_basis": "venue_rules_tick_step_min_notional_fee_calendar",
        "venue_rule_blockers": _dedupe(blockers),
    }
    return BTCVenueValidation(
        approved=not blockers,
        blockers=_dedupe(blockers),
        normalized_quantity=normalized_quantity,
        normalized_price=normalized_price,
        notional=notional,
        fee_bps=fee_bps,
        metadata=metadata,
    )


def normalize_btc_price(price: float, tick_size: float, side: OrderSide) -> float:
    tick = Decimal(str(tick_size))
    value = Decimal(str(price))
    rounding = ROUND_CEILING if side == OrderSide.BUY else ROUND_FLOOR
    ticks = (value / tick).to_integral_value(rounding=rounding)
    return float(ticks * tick)


def normalize_btc_quantity(quantity: float, step_size: float) -> float:
    step = Decimal(str(step_size))
    value = Decimal(str(quantity))
    steps = (value / step).to_integral_value(rounding=ROUND_FLOOR)
    return float(steps * step)


def round_btc_quantity_to_precision(quantity: float, precision: int) -> float:
    quantum = Decimal("1").scaleb(-int(precision))
    return float(Decimal(str(quantity)).quantize(quantum, rounding=ROUND_HALF_UP))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
