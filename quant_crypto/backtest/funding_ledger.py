from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence


@dataclass(frozen=True)
class FundingRateEvent:
    funding_time: datetime
    funding_rate: float
    mark_price: float
    source_record_id: str = ""
    index_price: float | None = None
    instrument_id: str = "BTC-USDT-SWAP"
    settlement_asset: str = "USDT"


@dataclass(frozen=True)
class FundingFill:
    filled_at: datetime
    side: str
    quantity: float
    price: float
    fill_id: str = ""
    fee: float = 0.0


@dataclass(frozen=True)
class FundingPayment:
    funding_time: datetime
    position_qty: float
    mark_price: float
    funding_rate: float
    funding_payment: float
    source_record_id: str = ""
    index_price: float | None = None
    instrument_id: str = "BTC-USDT-SWAP"
    settlement_asset: str = "USDT"


@dataclass(frozen=True)
class PerpetualLedgerEntry:
    event_time: datetime
    event_type: str
    amount: float
    asset: str
    position_qty: float
    reference_price: float
    source_id: str


@dataclass(frozen=True)
class PerpetualPnL:
    position_qty: float
    cash_balance: float
    position_value: float
    price_pnl: float
    funding_pnl: float
    fee_pnl: float
    total_pnl: float
    ledger_entries: tuple[PerpetualLedgerEntry, ...]


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
                index_price=event.index_price,
                instrument_id=event.instrument_id,
                settlement_asset=event.settlement_asset,
            )
        )
    return payments


def replay_perpetual_fill_position_cash_ledger(
    *,
    fills: Sequence[FundingFill],
    funding_rates: Sequence[FundingRateEvent],
    valuation_mark_price: float,
    settlement_asset: str = "USDT",
) -> PerpetualPnL:
    """Derive position, cash, and PnL only from fills and funding cashflows."""

    if valuation_mark_price <= 0:
        raise ValueError("valuation_mark_price must be positive")
    ordered_fills = sorted(fills, key=lambda row: _to_utc(row.filled_at))
    entries: list[PerpetualLedgerEntry] = []
    position_qty = 0.0
    cash_balance = 0.0
    fee_pnl = 0.0
    trade_cashflow = 0.0
    for fill in ordered_fills:
        if fill.quantity <= 0 or fill.price <= 0:
            raise ValueError("fill quantity and price must be positive")
        side = fill.side.strip().lower()
        signed_qty = _signed_quantity(side, fill.quantity)
        gross_cash = -signed_qty * float(fill.price)
        fee_cash = -abs(float(fill.fee))
        position_qty += signed_qty
        trade_cashflow += gross_cash
        cash_balance += gross_cash + fee_cash
        fee_pnl += fee_cash
        entries.append(
            PerpetualLedgerEntry(
                event_time=_to_utc(fill.filled_at),
                event_type="fill_cashflow",
                amount=round(gross_cash, 12),
                asset=settlement_asset,
                position_qty=round(position_qty, 12),
                reference_price=float(fill.price),
                source_id=fill.fill_id,
            )
        )
        if fee_cash:
            entries.append(
                PerpetualLedgerEntry(
                    event_time=_to_utc(fill.filled_at),
                    event_type="fee_cashflow",
                    amount=round(fee_cash, 12),
                    asset=settlement_asset,
                    position_qty=round(position_qty, 12),
                    reference_price=float(fill.price),
                    source_id=fill.fill_id,
                )
            )
    payments = calculate_funding_payments(
        funding_rates=funding_rates, fills=ordered_fills
    )
    funding_pnl = 0.0
    for payment in payments:
        funding_pnl += payment.funding_payment
        cash_balance += payment.funding_payment
        entries.append(
            PerpetualLedgerEntry(
                event_time=_to_utc(payment.funding_time),
                event_type="funding_cashflow",
                amount=payment.funding_payment,
                asset=payment.settlement_asset,
                position_qty=payment.position_qty,
                reference_price=payment.mark_price,
                source_id=payment.source_record_id,
            )
        )
    position_value = position_qty * float(valuation_mark_price)
    price_pnl = trade_cashflow + position_value
    total_pnl = price_pnl + funding_pnl + fee_pnl
    reconciled_total = cash_balance + position_value
    if abs(total_pnl - reconciled_total) > 1e-9:
        raise ValueError("perpetual ledger reconciliation mismatch")
    return PerpetualPnL(
        position_qty=round(position_qty, 12),
        cash_balance=round(cash_balance, 12),
        position_value=round(position_value, 12),
        price_pnl=round(price_pnl, 12),
        funding_pnl=round(funding_pnl, 12),
        fee_pnl=round(fee_pnl, 12),
        total_pnl=round(total_pnl, 12),
        ledger_entries=tuple(entries),
    )


def position_at_time(fills: Iterable[FundingFill], timestamp: datetime) -> float:
    ts = _to_utc(timestamp)
    position = 0.0
    for fill in fills:
        if _to_utc(fill.filled_at) > ts:
            continue
        position += _signed_quantity(fill.side.strip().lower(), fill.quantity)
    return position


def _signed_quantity(side: str, quantity: float) -> float:
    if side in {"buy", "long", "cover"}:
        return float(quantity)
    if side in {"sell", "short"}:
        return -float(quantity)
    raise ValueError(f"Unsupported fill side for funding replay: {side}")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

