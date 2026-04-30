from __future__ import annotations

from quant_us.core.types import PortfolioSnapshot


def daily_report(snapshot: PortfolioSnapshot) -> dict[str, float]:
    return {
        "equity": round(snapshot.equity, 2),
        "cash": round(snapshot.cash, 2),
        "gross_exposure": round(snapshot.gross_exposure, 2),
        "net_exposure": round(snapshot.net_exposure, 2),
        "daily_pnl": round(snapshot.daily_pnl, 2),
        "drawdown_pct": round(snapshot.drawdown * 100.0, 4),
    }
