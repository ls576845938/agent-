from __future__ import annotations

from math import isfinite
from math import sqrt

import pandas as pd

from quant_us.core.types import Fill, PortfolioSnapshot


def compute_performance(
    snapshots: list[PortfolioSnapshot],
    fills: list[Fill],
    periods_per_year: float = 252.0,
) -> dict[str, float | int]:
    if not snapshots:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "annual_return_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar_ratio": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "turnover_pct": 0.0,
            "trade_count": len(fills),
        }
    equity = pd.Series([snapshot.equity for snapshot in snapshots], index=[snapshot.timestamp_utc for snapshot in snapshots])
    returns = equity.pct_change().fillna(0.0)
    total_return = equity.iloc[-1] / equity.iloc[0] - 1.0 if equity.iloc[0] else 0.0
    annual_return = (equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / max(1, len(equity))) - 1.0 if equity.iloc[0] > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    std = float(returns.std(ddof=0))
    annual_volatility = std * sqrt(periods_per_year)
    sharpe = float(returns.mean() / std * sqrt(periods_per_year)) if std > 0 else 0.0
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=0))
    sortino = float(returns.mean() / downside_std * sqrt(periods_per_year)) if downside_std > 0 else 0.0
    max_drawdown = float(drawdown.min())
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    active_returns = returns[returns != 0]
    win_rate = float((active_returns > 0).mean()) if len(active_returns) else 0.0
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = abs(float(returns[returns < 0].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
    notional_traded = sum(abs(fill.quantity * fill.price) for fill in fills)
    average_equity = float(equity.mean()) if len(equity) else 0.0
    turnover = notional_traded / average_equity if average_equity > 0 else 0.0
    return {
        "total_return_pct": round(float(total_return) * 100.0, 4),
        "cagr_pct": round(float(annual_return) * 100.0, 4),
        "annual_return_pct": round(float(annual_return) * 100.0, 4),
        "annual_volatility_pct": round(float(annual_volatility) * 100.0, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "calmar_ratio": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100.0, 4),
        "profit_factor": round(profit_factor, 4) if isfinite(profit_factor) else 0.0,
        "turnover_pct": round(turnover * 100.0, 4),
        "trade_count": len(fills),
    }
