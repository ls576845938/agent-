"""Ledger-based PnL derivation.

Rebuilds equity curve and performance metrics exclusively from fill records.
This is the canonical PnL path — strategy, portfolio, and risk layers must not
calculate PnL independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from quant_us.backtest.corporate_actions_ledger import LedgerAdjustment, LedgerAdjustmentLog, reconstruct_equity_with_adjustments
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
    adjustment_cross_check: LedgerAdjustmentCrossCheck | None = None

    @property
    def equity_series(self) -> list[float]:
        return [p.equity for p in self.points]

    @property
    def final_equity(self) -> float:
        return self.points[-1].equity if self.points else self.initial_cash

    @property
    def total_fees(self) -> float:
        return self.points[-1].cumulative_fees if self.points else 0.0


@dataclass
class _LedgerReplayState:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    avg_prices: dict[str, float] = field(default_factory=dict)
    cumulative_fees: float = 0.0
    cumulative_slippage: float = 0.0


@dataclass
class LedgerAdjustmentCrossCheck:
    replay_final_equity: float
    reconstructed_final_equity: float
    equity_diff: float
    passed: bool
    timestamp_utc: datetime | None = None

    def to_dict(self) -> dict[str, float | bool | str | None]:
        return {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat() if self.timestamp_utc else None,
            "replay_final_equity": round(self.replay_final_equity, 6),
            "reconstructed_final_equity": round(self.reconstructed_final_equity, 6),
            "equity_diff": round(self.equity_diff, 6),
            "passed": self.passed,
        }


@dataclass
class LedgerReconciliationSnapshot:
    timestamp_utc: datetime
    ledger_cash: float
    ledger_equity: float
    snapshot_cash: float
    snapshot_equity: float
    cash_diff: float
    equity_diff: float
    max_abs_diff: float
    max_pct_diff: float
    passed: bool

    def to_dict(self) -> dict[str, float | bool | str]:
        return {
            "timestamp_utc": self.timestamp_utc.astimezone(timezone.utc).isoformat(),
            "ledger_cash": round(self.ledger_cash, 6),
            "ledger_equity": round(self.ledger_equity, 6),
            "snapshot_cash": round(self.snapshot_cash, 6),
            "snapshot_equity": round(self.snapshot_equity, 6),
            "diff": {
                "cash": round(self.cash_diff, 6),
                "equity": round(self.equity_diff, 6),
            },
            "max_abs_diff": round(self.max_abs_diff, 6),
            "max_pct_diff": round(self.max_pct_diff, 6),
            "passed": self.passed,
        }


@dataclass
class LedgerReconciliationReport:
    snapshots: list[LedgerReconciliationSnapshot] = field(default_factory=list)
    tolerance_pct: float = 0.01
    absolute_tolerance: float = 1e-6
    max_abs_diff: float = 0.0
    max_pct_diff: float = 0.0
    passed: bool = True
    message: str = "No data to compare"
    adjustment_cross_check: LedgerAdjustmentCrossCheck | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": {
                "snapshot_count": len(self.snapshots),
                "tolerance_pct": self.tolerance_pct,
                "absolute_tolerance": self.absolute_tolerance,
                "max_abs_diff": round(self.max_abs_diff, 6),
                "max_pct_diff": round(self.max_pct_diff, 6),
                "passed": self.passed,
                "message": self.message,
            },
            "snapshots": [snapshot.to_dict() for snapshot in self.snapshots],
            "adjustment_cross_check": self.adjustment_cross_check.to_dict() if self.adjustment_cross_check else None,
        }


def _sorted_ledger_events(
    fills: list[Fill],
    adjustments: LedgerAdjustmentLog | None = None,
    *,
    at_time: datetime | None = None,
) -> list[tuple[datetime, int, int, Fill | LedgerAdjustment]]:
    events: list[tuple[datetime, int, int, Fill | LedgerAdjustment]] = []
    if adjustments is not None:
        for index, adjustment in enumerate(adjustments.adjustments):
            if at_time is not None and adjustment.timestamp_utc > at_time:
                continue
            events.append((adjustment.timestamp_utc, 0, index, adjustment))
    for index, fill in enumerate(fills):
        if at_time is not None and fill.filled_at > at_time:
            continue
        events.append((fill.filled_at, 1, index, fill))
    return sorted(events, key=lambda event: (event[0], event[1], event[2]))


def _apply_fill_to_state(
    state: _LedgerReplayState,
    fill: Fill,
    prices: dict[datetime, dict[str, float]],
) -> None:
    signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
    state.cash -= fill.quantity * fill.price if fill.side == OrderSide.BUY else -fill.quantity * fill.price
    state.cash -= fill.commission
    state.cumulative_fees += fill.commission

    ref_price = prices.get(fill.filled_at, {}).get(fill.symbol)
    if ref_price is not None and ref_price > 0:
        if fill.side == OrderSide.BUY:
            state.cumulative_slippage += max(0.0, (fill.price - ref_price) * fill.quantity)
        else:
            state.cumulative_slippage += max(0.0, (ref_price - fill.price) * fill.quantity)

    old_qty = state.positions.get(fill.symbol, 0.0)
    new_qty = round(old_qty + signed_qty, 8)
    if abs(new_qty) <= 1e-10:
        state.positions.pop(fill.symbol, None)
        state.avg_prices[fill.symbol] = 0.0
        return

    state.positions[fill.symbol] = new_qty
    if old_qty >= 0 and signed_qty > 0:
        old_avg = state.avg_prices.get(fill.symbol, 0.0)
        state.avg_prices[fill.symbol] = round(((old_qty * old_avg) + (fill.quantity * fill.price)) / new_qty, 8)
    elif state.avg_prices.get(fill.symbol, 0.0) == 0:
        state.avg_prices[fill.symbol] = round(fill.price, 8)


def _apply_adjustment_to_state(state: _LedgerReplayState, adjustment: LedgerAdjustment) -> None:
    state.cash += adjustment.amount
    if not adjustment.has_position_impact():
        return

    symbol = adjustment.normalized_symbol()
    qty = state.positions.get(symbol, 0.0)
    if abs(qty) <= 1e-10:
        return

    qty_multiplier = float(adjustment.quantity_multiplier)
    avg_multiplier = adjustment.effective_avg_price_multiplier()
    if qty_multiplier <= 0 or avg_multiplier <= 0:
        raise ValueError(f"Position adjustment multipliers must be positive for {symbol}")

    new_qty = round(qty * qty_multiplier, 8)
    if abs(new_qty) <= 1e-10:
        state.positions.pop(symbol, None)
        state.avg_prices[symbol] = 0.0
        return

    state.positions[symbol] = new_qty
    if state.avg_prices.get(symbol, 0.0) != 0:
        state.avg_prices[symbol] = round(state.avg_prices[symbol] * avg_multiplier, 8)


def _position_value_at(
    positions: dict[str, float],
    avg_prices: dict[str, float],
    market_prices: dict[datetime, dict[str, float]],
    at_time: datetime,
) -> float:
    return sum(
        qty * market_prices.get(at_time, {}).get(symbol, avg_prices.get(symbol, 0.0))
        for symbol, qty in positions.items()
    )


def _prices_at_or_before(
    market_prices: dict[datetime, dict[str, float]],
    at_time: datetime,
) -> dict[str, float]:
    eligible = [timestamp for timestamp in market_prices if timestamp <= at_time]
    if not eligible:
        return {}
    return market_prices[max(eligible)]


def _normalize_timestamp(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _diff_pct(diff: float, reference: float, absolute_tolerance: float) -> float:
    if abs(diff) <= absolute_tolerance:
        return 0.0
    return abs(diff) / max(abs(reference), absolute_tolerance) * 100.0


def _latest_curve_point_before(
    ledger_curve: LedgerEquityCurve,
    at_time: datetime,
) -> LedgerEquityPoint:
    if not ledger_curve.points:
        raise ValueError("Ledger curve has no points")

    normalized_points = [(_normalize_timestamp(point.timestamp_utc), point) for point in ledger_curve.points]
    eligible = [point for point_ts, point in normalized_points if point_ts <= at_time]
    if eligible:
        return eligible[-1]

    return min(
        ledger_curve.points,
        key=lambda point: abs((_normalize_timestamp(point.timestamp_utc) - at_time).total_seconds()),
    )


def ledger_adjustments_total_at(
    adjustments: LedgerAdjustmentLog | None,
    at_time: datetime,
) -> float:
    """Return cumulative cash adjustments booked up to and including *at_time*."""
    if adjustments is None or not adjustments.adjustments:
        return 0.0
    return sum(adj.amount for adj in adjustments.adjustments if adj.timestamp_utc <= at_time)


def ledger_positions_and_cash_at(
    fills: list[Fill],
    at_time: datetime,
    initial_cash: float,
    adjustments: LedgerAdjustmentLog | None = None,
) -> tuple[dict[str, float], float]:
    """Return (positions, cash) derived from fills up to and including *at_time*."""
    state = _LedgerReplayState(cash=initial_cash)
    for _, priority, _, item in _sorted_ledger_events(fills, adjustments, at_time=at_time):
        if priority == 0:
            adjustment = item
            assert isinstance(adjustment, LedgerAdjustment)
            _apply_adjustment_to_state(state, adjustment)
        else:
            fill = item
            assert isinstance(fill, Fill)
            _apply_fill_to_state(state, fill, {})
    return {s: q for s, q in state.positions.items() if abs(q) > 1e-10}, state.cash


def ledger_state_at_time(
    fills: list[Fill],
    at_time: datetime,
    initial_cash: float,
    market_prices: dict[str, float] | None = None,
    adjustments: LedgerAdjustmentLog | None = None,
) -> tuple[dict[str, float], float, float, float]:
    """Return (positions, cash, position_value, equity) at a specific timestamp."""
    positions, cash = ledger_positions_and_cash_at(fills, at_time, initial_cash, adjustments=adjustments)
    position_value = sum(
        qty * (market_prices or {}).get(symbol, 0.0)
        for symbol, qty in positions.items()
    )
    return positions, cash, position_value, cash + position_value


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
    event_stream = _sorted_ledger_events(fills, adjustments)
    if not event_stream:
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
            total_fills=0,
        )

    sorted_fills = sorted(fills, key=lambda f: f.filled_at)
    state = _LedgerReplayState(cash=initial_cash)
    points: list[LedgerEquityPoint] = []
    prices = market_prices_by_time or {}
    has_adjustments = adjustments is not None and len(adjustments.adjustments) > 0

    for timestamp_utc, priority, _, item in event_stream:
        if priority == 0:
            adjustment = item
            assert isinstance(adjustment, LedgerAdjustment)
            _apply_adjustment_to_state(state, adjustment)
        else:
            fill = item
            assert isinstance(fill, Fill)
            _apply_fill_to_state(state, fill, prices)

        position_value = _position_value_at(state.positions, state.avg_prices, prices, timestamp_utc)
        points.append(LedgerEquityPoint(
            timestamp_utc=timestamp_utc,
            cash=round(state.cash, 6),
            position_value=round(position_value, 6),
            equity=round(state.cash + position_value, 6),
            cumulative_fees=round(state.cumulative_fees, 6),
            cumulative_slippage_cost=round(state.cumulative_slippage, 6),
        ))

    # If adjustments were provided, cross-verify the final equity value using
    # reconstruct_equity_with_adjustments (which applies all adjustments at once).
    adjustment_cross_check: LedgerAdjustmentCrossCheck | None = None
    if has_adjustments and points:
        final_market_prices: dict[str, float] = {}
        if prices:
            final_market_prices = _prices_at_or_before(prices, points[-1].timestamp_utc)
        final_adj_equity = reconstruct_equity_with_adjustments(
            fills=sorted_fills,
            adjustments=adjustments,
            initial_cash=initial_cash,
            market_prices=final_market_prices,
        )
        last = points[-1]
        equity_diff = round(last.equity - final_adj_equity, 6)
        adjustment_cross_check = LedgerAdjustmentCrossCheck(
            replay_final_equity=last.equity,
            reconstructed_final_equity=final_adj_equity,
            equity_diff=equity_diff,
            passed=abs(equity_diff) <= 1e-6,
            timestamp_utc=last.timestamp_utc,
        )

    return LedgerEquityCurve(
        points=points,
        initial_cash=initial_cash,
        total_fills=len(sorted_fills),
        adjustment_cross_check=adjustment_cross_check,
    )


def build_reconciliation_report(
    snapshots: list[PortfolioSnapshot],
    ledger_curve: LedgerEquityCurve,
    tolerance_pct: float = 0.01,
    fills: list[Fill] | None = None,
    market_prices_by_time: dict[datetime, dict[str, float]] | None = None,
    adjustments: LedgerAdjustmentLog | None = None,
    absolute_tolerance: float = 1e-6,
) -> LedgerReconciliationReport:
    report = LedgerReconciliationReport(
        tolerance_pct=tolerance_pct,
        absolute_tolerance=absolute_tolerance,
        adjustment_cross_check=ledger_curve.adjustment_cross_check,
    )
    if not snapshots or not ledger_curve.points:
        report.message = "No data to compare"
        if report.adjustment_cross_check is not None and not report.adjustment_cross_check.passed:
            report.passed = False
            report.message = (
                f"{report.message}; adjustment cross-check discrepancy: "
                f"{report.adjustment_cross_check.equity_diff:.6f}"
            )
        return report

    for snap in snapshots:
        snap_ts = _normalize_timestamp(snap.timestamp_utc)
        if fills and market_prices_by_time:
            _, ledger_cash, _, ledger_equity = ledger_state_at_time(
                fills,
                snap_ts,
                ledger_curve.initial_cash,
                market_prices=market_prices_by_time.get(snap_ts, {}),
                adjustments=adjustments,
            )
        else:
            matched_point = _latest_curve_point_before(ledger_curve, snap_ts)
            ledger_cash = matched_point.cash
            ledger_equity = matched_point.equity

        cash_diff = snap.cash - ledger_cash
        equity_diff = snap.equity - ledger_equity
        cash_pct_diff = _diff_pct(cash_diff, ledger_cash, absolute_tolerance)
        equity_pct_diff = _diff_pct(equity_diff, ledger_equity, absolute_tolerance)
        max_abs_diff = max(abs(cash_diff), abs(equity_diff))
        max_pct_diff = max(cash_pct_diff, equity_pct_diff)
        passed = (
            (abs(cash_diff) <= absolute_tolerance or cash_pct_diff <= tolerance_pct)
            and (abs(equity_diff) <= absolute_tolerance or equity_pct_diff <= tolerance_pct)
        )
        report.snapshots.append(
            LedgerReconciliationSnapshot(
                timestamp_utc=snap_ts,
                ledger_cash=ledger_cash,
                ledger_equity=ledger_equity,
                snapshot_cash=snap.cash,
                snapshot_equity=snap.equity,
                cash_diff=cash_diff,
                equity_diff=equity_diff,
                max_abs_diff=max_abs_diff,
                max_pct_diff=max_pct_diff,
                passed=passed,
            )
        )
        report.max_abs_diff = max(report.max_abs_diff, max_abs_diff)
        report.max_pct_diff = max(report.max_pct_diff, max_pct_diff)
        report.passed = report.passed and passed

    if report.adjustment_cross_check is not None and not report.adjustment_cross_check.passed:
        report.passed = False

    if not report.snapshots:
        report.message = "No data to compare"
    elif report.passed:
        report.message = (
            f"Consistent within {tolerance_pct}% tolerance "
            f"(max diff: {report.max_pct_diff:.4f}%, max abs: {report.max_abs_diff:.6f})"
        )
    elif report.max_pct_diff > tolerance_pct:
        report.message = (
            f"Max equity discrepancy: {report.max_pct_diff:.4f}% exceeds tolerance {tolerance_pct}% "
            f"(max abs diff: {report.max_abs_diff:.6f})"
        )
    else:
        report.message = (
            f"Snapshot cash/equity reconciliation failed "
            f"(max abs diff: {report.max_abs_diff:.6f}, max pct diff: {report.max_pct_diff:.4f}%)"
        )

    if report.adjustment_cross_check is not None and not report.adjustment_cross_check.passed:
        discrepancy = report.adjustment_cross_check.equity_diff
        report.message = (
            f"{report.message}; adjustment cross-check discrepancy: {discrepancy:.6f}"
            if report.snapshots
            else f"Adjustment cross-check discrepancy: {discrepancy:.6f}"
        )

    return report


def verify_equity_consistency(
    snapshots: list[PortfolioSnapshot],
    ledger_curve: LedgerEquityCurve,
    tolerance_pct: float = 0.01,
    fills: list[Fill] | None = None,
    market_prices_by_time: dict[datetime, dict[str, float]] | None = None,
    adjustments: LedgerAdjustmentLog | None = None,
) -> tuple[bool, str]:
    """Compare portfolio snapshots against ledger-derived equity.

    When *fills* and *market_prices_by_time* are provided, evaluates the ledger
    state at each snapshot timestamp using fills up to that time and the
    market prices from that same timestamp.  This eliminates timestamp-mismatch
    false positives that occur when fills and snapshots land on different bars.

    Returns (is_consistent, message).
    """
    report = build_reconciliation_report(
        snapshots,
        ledger_curve,
        tolerance_pct=tolerance_pct,
        fills=fills,
        market_prices_by_time=market_prices_by_time,
        adjustments=adjustments,
    )
    return report.passed, report.message
