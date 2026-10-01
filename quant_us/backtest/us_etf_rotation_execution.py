from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from quant_us.portfolio.us_etf_rotation_portfolio import UsEtfPortfolioTargets


@dataclass(frozen=True)
class UsEtfBacktestExecutionResult:
    """Backtest-layer result for ETF rotation cost simulation."""

    strategy_returns: pd.Series
    gross_returns: pd.Series
    turnover: pd.Series
    execution_costs: pd.Series
    diagnostics: dict[str, Any] = field(default_factory=dict)


def simulate_us_etf_rotation_backtest_execution(
    portfolio: UsEtfPortfolioTargets,
    asset_returns: pd.DataFrame,
    cfg: Any,
) -> UsEtfBacktestExecutionResult:
    """Apply turnover costs to target weights without changing signal logic."""

    weights = portfolio.daily_target_weights
    gross_returns = (weights * asset_returns[weights.columns]).sum(axis=1)
    turnover = portfolio.turnover
    execution_costs = turnover * float(cfg.cost_per_turnover)
    net_returns = gross_returns - execution_costs
    return UsEtfBacktestExecutionResult(
        strategy_returns=net_returns,
        gross_returns=gross_returns,
        turnover=turnover,
        execution_costs=execution_costs,
        diagnostics={
            "layer": "execution_simulation",
            "architecture_layer": "backtest_execution_simulation",
            "turnover": float(turnover.sum()),
            "avg_rebalance_turnover": float(turnover[turnover > 0].mean()) if (turnover > 0).any() else 0.0,
            "cost_per_turnover": float(cfg.cost_per_turnover),
            "outputs": [
                "strategy_returns",
                "turnover",
                "execution_costs",
            ],
        },
    )
