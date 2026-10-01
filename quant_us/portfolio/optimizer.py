from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StaticStrategyAllocation:
    weights: dict[str, float]

    def normalized(self) -> dict[str, float]:
        positive = {key: max(0.0, value) for key, value in self.weights.items()}
        total = sum(positive.values())
        if total <= 0:
            return {key: 0.0 for key in positive}
        return {key: value / total for key, value in positive.items()}


@dataclass(frozen=True)
class PyPortfolioOptCandidate:
    status: str
    method: str
    weights: dict[str, float] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    promotion_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "method": self.method,
            "weights": dict(self.weights),
            "blockers": list(self.blockers),
            "diagnostics": dict(self.diagnostics),
            "promotion_allowed": self.promotion_allowed,
        }


def build_pypfopt_portfolio_candidate(
    expected_returns: pd.Series,
    covariance: pd.DataFrame,
    *,
    method: str = "max_sharpe",
    max_weight: float = 0.35,
    optimizer_factory: Callable[..., Any] | None = None,
) -> PyPortfolioOptCandidate:
    """Build a research-only PyPortfolioOpt weight candidate.

    This function deliberately returns raw candidate weights, not
    ``TargetPosition`` or ``OrderIntent``. The local portfolio allocator and
    risk gates remain the production path.
    """

    symbols = [str(symbol).upper() for symbol in expected_returns.index]
    blockers = _validate_optimizer_inputs(symbols, covariance, max_weight, method)
    if blockers:
        return PyPortfolioOptCandidate(
            status="BLOCKED",
            method=method,
            blockers=blockers,
            diagnostics={"symbol_count": len(symbols), "max_weight": max_weight},
        )

    factory = optimizer_factory or _load_efficient_frontier()
    if factory is None:
        return PyPortfolioOptCandidate(
            status="DEPENDENCY_MISSING",
            method=method,
            blockers=["pypfopt_not_installed"],
            diagnostics={"symbol_count": len(symbols), "max_weight": max_weight},
        )

    aligned_returns = expected_returns.copy()
    aligned_returns.index = symbols
    aligned_covariance = covariance.copy()
    aligned_covariance.index = [str(symbol).upper() for symbol in covariance.index]
    aligned_covariance.columns = [str(symbol).upper() for symbol in covariance.columns]
    optimizer = factory(aligned_returns, aligned_covariance.loc[symbols, symbols], weight_bounds=(0.0, max_weight))
    if method == "max_sharpe":
        optimizer.max_sharpe()
    elif method == "min_volatility":
        optimizer.min_volatility()
    else:
        return PyPortfolioOptCandidate(
            status="BLOCKED",
            method=method,
            blockers=[f"unsupported_method:{method}"],
            diagnostics={"supported_methods": ["max_sharpe", "min_volatility"]},
        )

    weights = {str(symbol).upper(): round(float(weight), 8) for symbol, weight in optimizer.clean_weights().items()}
    return PyPortfolioOptCandidate(
        status="PASS",
        method=method,
        weights=weights,
        diagnostics={
            "symbol_count": len(symbols),
            "max_weight": max_weight,
            "weight_sum": round(sum(weights.values()), 8),
            "adapter_scope": "research_only_candidate_weights",
        },
        promotion_allowed=False,
    )


def _validate_optimizer_inputs(
    symbols: list[str],
    covariance: pd.DataFrame,
    max_weight: float,
    method: str,
) -> list[str]:
    blockers: list[str] = []
    if not symbols:
        blockers.append("missing_expected_returns")
    if not 0.0 < max_weight <= 1.0:
        blockers.append(f"invalid_max_weight:{max_weight}")
    if method not in {"max_sharpe", "min_volatility"}:
        blockers.append(f"unsupported_method:{method}")
    covariance_symbols = {str(symbol).upper() for symbol in covariance.index}
    covariance_columns = {str(symbol).upper() for symbol in covariance.columns}
    missing_index = sorted(set(symbols) - covariance_symbols)
    missing_columns = sorted(set(symbols) - covariance_columns)
    if missing_index:
        blockers.append(f"covariance_missing_index:{','.join(missing_index)}")
    if missing_columns:
        blockers.append(f"covariance_missing_columns:{','.join(missing_columns)}")
    return blockers


def _load_efficient_frontier() -> Any | None:
    try:
        from pypfopt.efficient_frontier import EfficientFrontier
    except Exception:
        return None
    return EfficientFrontier
