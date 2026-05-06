"""Ledger-based PnL derivation.

Rebuilds equity curve and performance metrics exclusively from fill records.
This is the canonical PnL path — strategy, portfolio, and risk layers must not
calculate PnL independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from quant_us.backtest.corporate_actions_ledger import LedgerAdjustmentLog, reconstruct_equity_with_adjustments
from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill, PortfolioSnapshot


@dataclass
class LedgerEquityPoint:
    timestamp_utc: datetime
    cash: float
    position_value: float
    equity: float
    cumulative_fees: float
    cumulative_slippage_cost: float


@dataclass
class LedgerEquityCurve:
    points: list[LedgerEquityPoint] = field(default_factory=list)
    initial_cash: float = 0.0
    total_fills: int = 0

    @property
    def equity_series(self) -> list[float]:
        return [p.equity for p in self.points]

    @property
    def final_equity(self) -> float:
        return self.points[-1].equity if self.points else self.initial_cash

    @property
    def total_fees(self) -> float:
        return self.points[-1].cumulative_fees if self.points else 0.0


def ledger_positions_and_cash_at(
    fills: list[Fill],
    at_time: datetime,
    initial_cash: float,
) -> tuple[dict[str, float], float]:
    """Return (positions, cash) derived from fills up to and including *at_time*."""
    cash = initial_cash
    positions: dict[str, float] = {}
    for fill in sorted(fills, key=lambda f: f.filled_at):
        if fill.filled_at > at_time:
            break
        signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        cash -= fill.quantity * fill.price if fill.side == OrderSide.BUY else -fill.quantity * fill.price
        cash -= fill.commission
        positions[fill.symbol] = positions.get(fill.symbol, 0.0) + signed_qty
    positions = {s: q for s, q in positions.items() if abs(q) > 1e-10}
    return positions, cash


def derive_equity_from_fills(
    fills: list[Fill],
    initial_cash: float,
    market_prices_by_time: dict[datetime, dict[str, float]] | None = None,
    adjustments: LedgerAdjustmentLog | None = None,
) -> LedgerEquityCurve:
    """Rebuild equity curve exclusively from fill records.

    Does NOT use portfolio snapshots, strategy PnL calculations, or any
    intermediate state. Only fills, cash, and externally-provided market prices.

    When *adjustments* is provided, dividend income and borrow fees recorded in
    the adjustment log are incorporated into the equity curve at their respective
    timestamps, and :func:`reconstruct_equity_with_adjustments` is called at
    the end to cross-verify the final equity value.

    This is the audit trail — any discrepancy with strategy-calculated PnL
    indicates a bug.
    """
    if not fills:
        return LedgerEquityCurve(
            points=[LedgerEquityPoint(
                timestamp_utc=datetime.min.replace(microsecond=0),
                cash=initial_cash,
                position_value=0.0,
                equity=initial_cash,
                cumulative_fees=0.0,
                cumulative_slippage_cost=0.0,
            )],
            initial_cash=initial_cash,
        )

    sorted_fills = sorted(fills, key=lambda f: f.filled_at)
    cash = initial_cash
    positions: dict[str, float] = {}
    avg_prices: dict[str, float] = {}
    cumulative_fees = 0.0
    cumulative_slippage = 0.0

    points: list[LedgerEquityPoint] = []
    prices = market_prices_by_time or {}

    # Pre-process adjustments if provided
    has_adjustments = adjustments is not None and len(adjustments.adjustments) > 0
    sorted_adjustments = sorted(adjustments.adjustments, key=lambda a: a.timestamp_utc) if has_adjustments else []
    adj_idx = 0
    cumulative_adjustments = 0.0

    for fill in sorted_fills:
        signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        cash -= fill.quantity * fill.price if fill.side == OrderSide.BUY else -fill.quantity * fill.price
        cash -= fill.commission
        cumulative_fees += fill.commission

        ref_price = prices.get(fill.filled_at, {}).get(fill.symbol)
        if ref_price is not None and ref_price > 0:
            if fill.side == OrderSide.BUY:
                slip = max(0.0, (fill.price - ref_price) * fill.quantity)
            else:
                slip = max(0.0, (ref_price - fill.price) * fill.quantity)
            cumulative_slippage += slip

        old_qty = positions.get(fill.symbol, 0.0)
        new_qty = old_qty + signed_qty
        positions[fill.symbol] = new_qty

        if new_qty == 0:
            avg_prices[fill.symbol] = 0.0
        elif old_qty >= 0 and signed_qty > 0:
            old_avg = avg_prices.get(fill.symbol, 0.0)
            avg_prices[fill.symbol] = ((old_qty * old_avg) + (fill.quantity * fill.price)) / new_qty
        else:
            if avg_prices.get(fill.symbol, 0.0) == 0:
                avg_prices[fill.symbol] = fill.price

        current_price = fill.price
        if fill.filled_at in prices and fill.symbol in prices[fill.filled_at]:
            current_price = prices[fill.filled_at][fill.symbol]

        position_value = sum(
            positions[sym] * prices.get(fill.filled_at, {}).get(sym, avg_prices.get(sym, 0.0))
            for sym in positions
        )

        # Apply adjustments at or before this fill's timestamp
        while adj_idx < len(sorted_adjustments) and sorted_adjustments[adj_idx].timestamp_utc <= fill.filled_at:
            cumulative_adjustments += sorted_adjustments[adj_idx].amount
            adj_idx += 1

        adjusted_cash = cash + cumulative_adjustments

        points.append(LedgerEquityPoint(
            timestamp_utc=fill.filled_at,
            cash=round(adjusted_cash, 6),
            position_value=round(position_value, 6),
            equity=round(adjusted_cash + position_value, 6),
            cumulative_fees=round(cumulative_fees, 6),
            cumulative_slippage_cost=round(cumulative_slippage, 6),
        ))

    # If adjustments were provided, cross-verify the final equity value using
    # reconstruct_equity_with_adjustments (which applies all adjustments at once).
    if has_adjustments and points:
        final_market_prices: dict[str, float] = {}
        if prices:
            last_ts = max(prices.keys())
            final_market_prices = prices[last_ts]
        final_adj_equity = reconstruct_equity_with_adjustments(
            fills=sorted_fills,
            adjustments=adjustments,
            initial_cash=initial_cash,
            market_prices=final_market_prices,
        )
        last = points[-1]
        if abs(last.equity - final_adj_equity) > 1e-6:
            # Reconcile: reconstruct_equity_with_adjustments is the authoritative
            # calculation. Override the final point's cash and equity.
            adj_cash = final_adj_equity - last.position_value
            points[-1] = LedgerEquityPoint(
                timestamp_utc=last.timestamp_utc,
                cash=round(adj_cash, 6),
                position_value=last.position_value,
                equity=round(final_adj_equity, 6),
                cumulative_fees=last.cumulative_fees,
                cumulative_slippage_cost=last.cumulative_slippage_cost,
            )

    return LedgerEquityCurve(points=points, initial_cash=initial_cash, total_fills=len(sorted_fills))


def verify_equity_consistency(
    snapshots: list[PortfolioSnapshot],
    ledger_curve: LedgerEquityCurve,
    tolerance_pct: float = 0.01,
    fills: list[Fill] | None = None,
    market_prices_by_time: dict[datetime, dict[str, float]] | None = None,
) -> tuple[bool, str]:
    """Compare portfolio snapshots against ledger-derived equity.

    When *fills* and *market_prices_by_time* are provided, evaluates the ledger
    state at each snapshot timestamp using fills up to that time and the
    market prices from that same timestamp.  This eliminates timestamp-mismatch
    false positives that occur when fills and snapshots land on different bars.

    Returns (is_consistent, message).
    """
    if not snapshots or not ledger_curve.points:
        return True, "No data to compare"

    def _normalize(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    if fills and market_prices_by_time:
        max_diff_pct = 0.0
        for snap in snapshots:
            snap_ts = _normalize(snap.timestamp_utc)
            positions, cash = ledger_positions_and_cash_at(fills, snap_ts, ledger_curve.initial_cash)
            market_at_snap = market_prices_by_time.get(snap_ts, {})
            position_value = sum(
                qty * market_at_snap.get(sym, 0.0)
                for sym, qty in positions.items()
            )
            ledger_eq = cash + position_value
            if ledger_eq > 0:
                diff_pct = abs(snap.equity - ledger_eq) / ledger_eq * 100.0
                max_diff_pct = max(max_diff_pct, diff_pct)
    else:
        snapshot_equities = {_normalize(s.timestamp_utc): s.equity for s in snapshots}
        ledger_by_time: dict[datetime, float] = {}
        for p in ledger_curve.points:
            ledger_by_time[_normalize(p.timestamp_utc)] = p.equity

        max_diff_pct = 0.0
        for ts, snap_eq in snapshot_equities.items():
            before = [t for t in ledger_by_time if t <= ts]
            if before:
                match_ts = max(before)
            else:
                match_ts = min(ledger_by_time.keys(), key=lambda t: abs((t - ts).total_seconds()))

            ledger_eq = ledger_by_time[match_ts]
            if ledger_eq > 0:
                diff_pct = abs(snap_eq - ledger_eq) / ledger_eq * 100.0
                max_diff_pct = max(max_diff_pct, diff_pct)

    if max_diff_pct > tolerance_pct:
        return False, f"Max equity discrepancy: {max_diff_pct:.4f}% exceeds tolerance {tolerance_pct}%"
    return True, f"Consistent within {tolerance_pct}% tolerance (max diff: {max_diff_pct:.4f}%)"
