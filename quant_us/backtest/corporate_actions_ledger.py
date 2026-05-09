"""Corporate action and dividend tracking for the ledger.

Ensures dividends, splits, borrow fees, and corporate adjustments are
recorded in the ledger and reflected in PnL — not silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill


@dataclass(frozen=True)
class DividendEvent:
    symbol: str
    ex_date: date
    pay_date: date
    amount_per_share: float
    currency: str = "USD"


@dataclass(frozen=True)
class BorrowFeeEvent:
    symbol: str
    date: date
    rate_annual_pct: float
    quantity: float
    fee_amount: float


@dataclass
class LedgerAdjustment:
    timestamp_utc: datetime
    symbol: str
    adjustment_type: str
    amount: float
    description: str = ""
    quantity_multiplier: float = 1.0
    avg_price_multiplier: float | None = None

    def normalized_symbol(self) -> str:
        return self.symbol.upper()

    def effective_avg_price_multiplier(self) -> float:
        if self.avg_price_multiplier is not None:
            return float(self.avg_price_multiplier)
        if self.adjustment_type == "split":
            if self.quantity_multiplier == 0:
                raise ValueError("Split quantity_multiplier must be non-zero")
            return 1.0 / float(self.quantity_multiplier)
        return 1.0

    def has_position_impact(self) -> bool:
        avg_multiplier = self.effective_avg_price_multiplier()
        return (
            self.adjustment_type == "split"
            or abs(float(self.quantity_multiplier) - 1.0) > 1e-12
            or abs(avg_multiplier - 1.0) > 1e-12
        )

    def key(self) -> tuple[str, str, str, float, float, float]:
        return (
            self.timestamp_utc.isoformat(),
            self.normalized_symbol(),
            self.adjustment_type,
            float(self.amount),
            float(self.quantity_multiplier),
            float(self.effective_avg_price_multiplier()),
        )


@dataclass
class LedgerAdjustmentLog:
    adjustments: list[LedgerAdjustment] = field(default_factory=list)

    def total_dividends(self) -> float:
        return sum(a.amount for a in self.adjustments if a.adjustment_type == "dividend")

    def total_borrow_fees(self) -> float:
        return sum(a.amount for a in self.adjustments if a.adjustment_type == "borrow_fee")

    def total_corporate_adjustments(self) -> float:
        return sum(a.amount for a in self.adjustments if a.adjustment_type == "corporate_action")

    def split_event_count(self) -> int:
        return sum(1 for adjustment in self.adjustments if adjustment.has_position_impact())

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_dividends": round(self.total_dividends(), 4),
            "total_borrow_fees": round(self.total_borrow_fees(), 4),
            "total_corporate_adjustments": round(self.total_corporate_adjustments(), 4),
            "adjustment_count": len(self.adjustments),
            "split_event_count": self.split_event_count(),
        }


def apply_dividend_to_cash(
    cash: float,
    positions: dict[str, float],
    dividend: DividendEvent,
    as_of_date: date,
) -> float:
    """Add dividend income to cash for held positions on ex_date."""
    if as_of_date < dividend.ex_date:
        return cash
    qty = positions.get(dividend.symbol.upper(), 0.0)
    if qty <= 0:
        return cash
    return cash + qty * dividend.amount_per_share


def compute_borrow_fee(
    short_positions: dict[str, float],
    market_prices: dict[str, float],
    annual_rate_pct: float = 0.5,
    days: int = 1,
) -> float:
    """Compute borrow fee for short positions."""
    total_fee = 0.0
    for symbol, qty in short_positions.items():
        if qty < 0:
            price = market_prices.get(symbol, 0.0)
            notional = abs(qty) * price
            daily_rate = annual_rate_pct / 100.0 / 365.0
            total_fee += notional * daily_rate * days
    return total_fee


def reconstruct_equity_with_adjustments(
    fills: list[Fill],
    adjustments: LedgerAdjustmentLog,
    initial_cash: float,
    market_prices: dict[str, float],
) -> float:
    """Reconstruct final equity including corporate action adjustments.

    equity = cash_from_fills + position_value + total_adjustments
    """
    cash = initial_cash
    positions: dict[str, float] = {}

    events: list[tuple[datetime, int, int, LedgerAdjustment | Fill]] = []
    for index, adjustment in enumerate(adjustments.adjustments):
        events.append((adjustment.timestamp_utc, 0, index, adjustment))
    for index, fill in enumerate(fills):
        events.append((fill.filled_at, 1, index, fill))

    for _, priority, _, item in sorted(events, key=lambda event: (event[0], event[1], event[2])):
        if priority == 0:
            adjustment = item
            assert isinstance(adjustment, LedgerAdjustment)
            cash += adjustment.amount
            if adjustment.has_position_impact():
                symbol = adjustment.normalized_symbol()
                qty = positions.get(symbol, 0.0)
                if abs(qty) <= 1e-10:
                    continue
                qty_multiplier = float(adjustment.quantity_multiplier)
                if qty_multiplier <= 0:
                    raise ValueError(f"Position adjustment quantity multiplier must be positive for {symbol}")
                positions[symbol] = round(qty * qty_multiplier, 8)
        else:
            fill = item
            assert isinstance(fill, Fill)
            signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
            cash -= fill.quantity * fill.price if fill.side == OrderSide.BUY else -fill.quantity * fill.price
            cash -= fill.commission
            symbol = fill.symbol.upper()
            positions[symbol] = positions.get(symbol, 0.0) + signed_qty

    position_value = sum(
        qty * market_prices.get(sym, 0.0)
        for sym, qty in positions.items()
    )
    return cash + position_value
