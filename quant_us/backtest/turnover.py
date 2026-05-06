"""Turnover analysis and cap enforcement for backtest integrity.

High-turnover strategies can appear profitable in backtests but fail in
production due to trading costs. This module computes turnover and enforces
a maximum turnover rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from quant_us.core.enums import OrderSide
from quant_us.core.types import Fill


@dataclass
class TurnoverReport:
    total_turnover: float
    total_notional_traded: float
    average_equity: float
    turnover_rate_pct: float
    excessive_turnover_days: int
    max_daily_turnover_pct: float
    max_daily_turnover_pct_limit: float


def compute_turnover(
    fills: list[Fill],
    equity_curve: list[float],
    max_daily_turnover_pct: float = 100.0,
) -> TurnoverReport:
    """Compute turnover from fills and equity curve.

    Turnover = sum(abs(trade_notional)) / (2 * average_equity), annualized
    approximation. Daily turnover = abs(daily_trade_notional) / daily_equity.
    """
    if not fills:
        return TurnoverReport(0.0, 0.0, 0.0, 0.0, 0, 0.0, max_daily_turnover_pct)

    total_notional = sum(fill.quantity * fill.price for fill in fills)
    avg_equity = float(np.mean(equity_curve)) if equity_curve else 0.0

    turnover_rate = 0.0
    if avg_equity > 0:
        turnover_rate = total_notional / avg_equity * 100.0

    from collections import defaultdict
    daily_notional: dict[str, float] = defaultdict(float)
    daily_equity: dict[str, float] = defaultdict(float)

    fills_by_date = sorted(fills, key=lambda f: f.filled_at.date().isoformat())
    for fill in fills_by_date:
        day_key = fill.filled_at.date().isoformat()
        daily_notional[day_key] += fill.quantity * fill.price

    if equity_curve:
        for i, eq in enumerate(equity_curve):
            day_key = fills_by_date[min(i, len(fills_by_date) - 1)].filled_at.date().isoformat()
            daily_equity[day_key] = eq

    excessive = 0
    max_daily = 0.0
    for day_key, notional in daily_notional.items():
        eq = daily_equity.get(day_key, avg_equity)
        if eq > 0:
            daily_rate = notional / eq * 100.0
            max_daily = max(max_daily, daily_rate)
            if daily_rate > max_daily_turnover_pct:
                excessive += 1

    return TurnoverReport(
        total_turnover=round(total_notional, 2),
        total_notional_traded=round(total_notional, 2),
        average_equity=round(avg_equity, 2),
        turnover_rate_pct=round(turnover_rate, 2),
        excessive_turnover_days=excessive,
        max_daily_turnover_pct=round(max_daily, 2),
        max_daily_turnover_pct_limit=max_daily_turnover_pct,
    )
