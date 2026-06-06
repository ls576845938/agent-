from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(frozen=True)
class FundingRateEvent:
    funding_time: datetime
    funding_rate: float
    mark_price: float
    source_record_id: str = ""


@dataclass(frozen=True)
class FundingFill:
    filled_at: datetime
    side: str
    quantity: float
    price: float
    fill_id: str = ""


@dataclass(frozen=True)
class FundingPayment:
    funding_time: datetime
    position_qty: float
    mark_price: float
    funding_rate: float
    funding_payment: float
    source_record_id: str = ""


def calculate_funding_payments(
    *,
    funding_rates: Iterable[FundingRateEvent],
    fills: Iterable[FundingFill],
) -> list[FundingPayment]:
    ordered_fills = sorted(fills, key=lambda row: _to_utc(row.filled_at))
    payments: list[FundingPayment] = []
    for event in sorted(funding_rates, key=lambda row: _to_utc(row.funding_time)):
        funding_time = _to_utc(event.funding_time)
        position_qty = position_at_time(ordered_fills, funding_time)
        payment = -position_qty * float(event.mark_price) * float(event.funding_rate)
        payments.append(
            FundingPayment(
                funding_time=funding_time,
                position_qty=round(position_qty, 12),
                mark_price=float(event.mark_price),
                funding_rate=float(event.funding_rate),
                funding_payment=round(payment, 12),
                source_record_id=event.source_record_id,
            )
        )
    return payments


def position_at_time(fills: Iterable[FundingFill], timestamp: datetime) -> float:
    ts = _to_utc(timestamp)
    position = 0.0
    for fill in fills:
        if _to_utc(fill.filled_at) > ts:
            continue
        side = fill.side.strip().lower()
        if side in {"buy", "long", "cover"}:
            position += float(fill.quantity)
        elif side in {"sell", "short"}:
            position -= float(fill.quantity)
        else:
            raise ValueError(f"Unsupported fill side for funding replay: {fill.side}")
    return position


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

