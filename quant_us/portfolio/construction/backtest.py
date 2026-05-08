from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PortfolioBacktestResult:
    """Aggregate backtest results for a portfolio-level simulation."""
    portfolio_id: str
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    strategy_contributions: dict[str, float] = field(default_factory=dict)
    turnover_series: list[float] = field(default_factory=list)
    exposure_series: list[float] = field(default_factory=list)
    drawdown_attribution: dict[str, float] = field(default_factory=dict)


class PortfolioBacktestRunner:
    """Run portfolio-level backtests combining multiple strategies.

    This module simulates portfolio-level performance by combining
    strategy-level return series. It does NOT submit orders or interact
    with any broker/execution layer.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root

    def run(
        self,
        portfolio_id: str,
        start: str,
        end: str,
        strategy_returns: dict[str, list[float]] | None = None,
        weights: dict[str, float] | None = None,
        risk_free_rate: float = 0.02,
    ) -> PortfolioBacktestResult:
        """Run a portfolio-level backtest.

        Parameters
        ----------
        portfolio_id : str
        start : str
            Start date YYYY-MM-DD.
        end : str
            End date YYYY-MM-DD.
        strategy_returns : dict[str, list[float]] or None
            Strategy_id -> list of periodic returns. If None, uses
            synthetic data for demonstration.
        weights : dict[str, float] or None
            Strategy_id -> weight mapping. If None, equal weight.
        risk_free_rate : float
            Annual risk-free rate (used for Sharpe).

        Returns
        -------
        PortfolioBacktestResult
        """
        if not strategy_returns:
            strategy_returns = self._load_strategy_returns(portfolio_id)

        if not strategy_returns:
            return PortfolioBacktestResult(portfolio_id=portfolio_id)

        strategy_ids = list(strategy_returns.keys())
        n = len(strategy_ids)

        if weights is None:
            weights = {sid: 1.0 / n for sid in strategy_ids}

        # Normalize weights
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}

        # Compute combined portfolio returns
        portfolio_returns: list[float] = []
        max_len = max(len(r) for r in strategy_returns.values())

        for i in range(max_len):
            period_return = 0.0
            for sid in strategy_ids:
                r_list = strategy_returns.get(sid, [])
                if i < len(r_list):
                    period_return += weights.get(sid, 0.0) * r_list[i]
            portfolio_returns.append(period_return)

        # Compute CAGR
        n_periods = len(portfolio_returns)
        if n_periods > 0:
            cumulative = 1.0
            for r in portfolio_returns:
                cumulative *= 1.0 + r
            years = n_periods / 252.0  # assume daily returns
            cagr = (cumulative ** (1.0 / max(years, 0.01))) - 1.0 if years > 0 else 0.0

            # Sharpe
            avg_return = sum(portfolio_returns) / n_periods
            daily_rf = risk_free_rate / 252.0
            excess_returns = [r - daily_rf for r in portfolio_returns]
            std_returns = math.sqrt(
                sum(x * x for x in excess_returns) / max(n_periods, 1)
            )
            sharpe = (
                (avg_return - daily_rf) / max(std_returns, 1e-10) * math.sqrt(252.0)
                if std_returns > 0
                else 0.0
            )

            # Max drawdown
            peak = 1.0
            max_dd = 0.0
            for r in portfolio_returns:
                peak = max(peak, peak * (1.0 + r))
                dd = (peak - peak * (1.0 + r)) / peak
                if dd > max_dd:
                    max_dd = dd
        else:
            cagr = 0.0
            sharpe = 0.0
            max_dd = 0.0

        # Strategy contributions (attribution)
        contributions: dict[str, float] = {}
        for sid in strategy_ids:
            r_list = strategy_returns.get(sid, [])
            sid_cum = 1.0
            for r in r_list:
                sid_cum *= 1.0 + r
            contributions[sid] = sid_cum - 1.0

        # Drawdown attribution
        drawdown_attribution: dict[str, float] = {}
        for sid in strategy_ids:
            r_list = strategy_returns.get(sid, [])
            sid_peak = 1.0
            sid_max_dd = 0.0
            for r in r_list:
                sid_peak = max(sid_peak, sid_peak * (1.0 + r))
                dd_val = (sid_peak - sid_peak * (1.0 + r)) / sid_peak
                if dd_val > sid_max_dd:
                    sid_max_dd = dd_val
            drawdown_attribution[sid] = sid_max_dd

        return PortfolioBacktestResult(
            portfolio_id=portfolio_id,
            cagr=cagr,
            sharpe=sharpe,
            max_drawdown=max_dd,
            strategy_contributions=contributions,
            turnover_series=[],
            exposure_series=[],
            drawdown_attribution=drawdown_attribution,
        )

    def compute_attribution(
        self,
        portfolio_id: str,
        strategy_returns: dict[str, list[float]] | None = None,
        weights: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Compute strategy-level return attribution.

        Parameters
        ----------
        portfolio_id : str
        strategy_returns : dict[str, list[float]] or None
        weights : dict[str, float] or None

        Returns
        -------
        dict[str, float]
            Strategy_id -> contribution to total return.
        """
        if not strategy_returns:
            strategy_returns = self._load_strategy_returns(portfolio_id)

        if not strategy_returns:
            return {}

        if weights is None:
            n = len(strategy_returns)
            weights = {sid: 1.0 / n for sid in strategy_returns}

        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v / total_w for k, v in weights.items()}

        contributions: dict[str, float] = {}
        for sid, returns in strategy_returns.items():
            w = weights.get(sid, 0.0)
            cum = 1.0
            for r in returns:
                cum *= 1.0 + r
            contributions[sid] = w * (cum - 1.0)

        total_contrib = sum(contributions.values())
        if total_contrib > 0:
            contributions = {k: v / total_contrib for k, v in contributions.items()}

        return contributions

    def _load_strategy_returns(
        self, portfolio_id: str
    ) -> dict[str, list[float]]:
        """Load strategy return series from saved data."""
        p = Path(self.data_root) / "portfolio" / "returns" / f"{portfolio_id}.json"
        if p.exists():
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                return {k: list(v) for k, v in data.items()}
        return {}
