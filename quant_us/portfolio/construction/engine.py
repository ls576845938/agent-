from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.portfolio.construction.allocator import AllocationMethod, CapitalAllocator
from quant_us.portfolio.construction.exposure import ExposureManager, ExposureReport


@dataclass(frozen=True)
class PortfolioConfig:
    """Configuration for a constructed portfolio."""
    portfolio_id: str
    candidate_ids: list[str] = field(default_factory=list)
    capital: float = 100000.0
    max_gross_exposure: float = 1.0
    max_net_exposure: float = 1.0
    max_single_weight: float = 0.25
    max_sector_weight: float = 0.40
    target_volatility: float = 0.15
    allocation_method: str = AllocationMethod.INVERSE_VOL
    rebalance_frequency: str = "monthly"
    risk_free_rate: float = 0.02


@dataclass(frozen=True)
class PortfolioTarget:
    """Output of portfolio construction — target allocations only, never orders."""
    portfolio_id: str
    date: str
    strategy_weights: dict[str, float] = field(default_factory=dict)
    symbol_exposures: dict[str, float] = field(default_factory=dict)
    total_capital: float = 0.0
    expected_return: float = 0.0
    expected_volatility: float = 0.0


class PortfolioConstructionEngine:
    """Construct and rebalance strategy portfolios.

    This is the top-level portfolio construction entry point.
    It outputs ``PortfolioTarget`` (allocation targets) — never orders.
    No imports from ``quant_us.live`` or any broker module.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self._allocator = CapitalAllocator()
        self._exposure_mgr = ExposureManager()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def construct(
        self,
        config: PortfolioConfig,
        candidate_scorecards: list[dict[str, Any]],
    ) -> PortfolioTarget:
        """Construct a portfolio from candidate strategy scorecards.

        Parameters
        ----------
        config : PortfolioConfig
            Portfolio-level configuration including capital, constraints.
        candidate_scorecards : list[dict]
            Each dict must contain at minimum:
            - id (str): strategy identifier
            - volatility (float): expected volatility
            - expected_return (float): expected annual return

        Returns
        -------
        PortfolioTarget
        """
        if not candidate_scorecards:
            return PortfolioTarget(
                portfolio_id=config.portfolio_id,
                date=date.today().isoformat(),
            )

        constraints = {
            "max_single_weight": config.max_single_weight,
            "max_sector_weight": config.max_sector_weight,
            "target_vol": config.target_volatility,
        }

        strategy_weights = self._allocator.allocate(
            candidates=candidate_scorecards,
            method=config.allocation_method,
            constraints=constraints,
        )

        # Compute expected portfolio metrics
        expected_return = 0.0
        expected_vol = 0.0
        for sc in candidate_scorecards:
            sid = sc["id"]
            w = strategy_weights.get(sid, 0.0)
            expected_return += w * sc.get("expected_return", 0.0)
            expected_vol += w * sc.get("volatility", 0.0)

        # Simplified symbol-level exposure (map from strategy-level)
        symbol_exposures: dict[str, float] = {}
        for sc in candidate_scorecards:
            sid = sc["id"]
            w = strategy_weights.get(sid, 0.0)
            capital_amount = w * config.capital
            holdings = sc.get("holdings", {})
            if holdings:
                for sym, frac in holdings.items():
                    symbol_exposures[sym] = (
                        symbol_exposures.get(sym, 0.0) + capital_amount * frac
                    )

        return PortfolioTarget(
            portfolio_id=config.portfolio_id,
            date=date.today().isoformat(),
            strategy_weights=strategy_weights,
            symbol_exposures=symbol_exposures,
            total_capital=config.capital,
            expected_return=expected_return,
            expected_volatility=expected_vol,
        )

    # ------------------------------------------------------------------
    # Rebalance
    # ------------------------------------------------------------------

    def rebalance(
        self,
        portfolio_id: str,
        current_weights: dict[str, float],
        candidate_scorecards: list[dict[str, Any]] | None = None,
        config: PortfolioConfig | None = None,
    ) -> PortfolioTarget:
        """Rebalance an existing portfolio toward target weights.

        Parameters
        ----------
        portfolio_id : str
        current_weights : dict[str, float]
            Current strategy_id -> weight mapping.
        candidate_scorecards : list[dict] or None
            Latest scorecards for re-optimization.
        config : PortfolioConfig or None
            If provided, constraints are re-applied.

        Returns
        -------
        PortfolioTarget
        """
        if config is None:
            config = PortfolioConfig(portfolio_id=portfolio_id)

        if candidate_scorecards:
            # Re-optimize using fresh scorecards
            return self.construct(config, candidate_scorecards)

        # Simple rebalance: re-normalize and apply exposure constraints
        total = sum(current_weights.values())
        if total <= 0:
            return PortfolioTarget(
                portfolio_id=portfolio_id,
                date=date.today().isoformat(),
            )

        # Normalize without changing relative proportions
        normalized = {k: v / total for k, v in current_weights.items()}

        # Apply max_single_weight: if any exceed, cap and re-normalize
        any_capped = any(w > config.max_single_weight for w in normalized.values())
        if any_capped:
            capped = {k: min(v, config.max_single_weight) for k, v in normalized.items()}
            capped_total = sum(capped.values())
            if capped_total > 0:
                normalized = {k: v / capped_total for k, v in capped.items()}

        return PortfolioTarget(
            portfolio_id=portfolio_id,
            date=date.today().isoformat(),
            strategy_weights=normalized,
            total_capital=config.capital,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_target(self, target: PortfolioTarget, path: str | None = None) -> str:
        """Save a PortfolioTarget as JSON.

        Parameters
        ----------
        target : PortfolioTarget
        path : str or None
            If None, saves to ``<data_root>/portfolio/targets/<portfolio_id>.json``.

        Returns
        -------
        str
            Path to the saved file.
        """
        if path is None:
            target_dir = self.data_root / "portfolio" / "targets"
            target_dir.mkdir(parents=True, exist_ok=True)
            path = str(target_dir / f"{target.portfolio_id}.json")

        data = {
            "portfolio_id": target.portfolio_id,
            "date": target.date,
            "strategy_weights": target.strategy_weights,
            "symbol_exposures": target.symbol_exposures,
            "total_capital": target.total_capital,
            "expected_return": target.expected_return,
            "expected_volatility": target.expected_volatility,
        }
        Path(path).write_text(json.dumps(data, indent=2))
        return path

    def load_target(self, portfolio_id: str, path: str | None = None) -> PortfolioTarget | None:
        """Load a saved PortfolioTarget from JSON.

        Parameters
        ----------
        portfolio_id : str
        path : str or None
            If None, loads from ``<data_root>/portfolio/targets/<portfolio_id>.json``.

        Returns
        -------
        PortfolioTarget or None
        """
        if path is None:
            path = str(self.data_root / "portfolio" / "targets" / f"{portfolio_id}.json")

        p = Path(path)
        if not p.exists():
            return None

        data = json.loads(p.read_text())
        return PortfolioTarget(
            portfolio_id=data["portfolio_id"],
            date=data["date"],
            strategy_weights=data.get("strategy_weights", {}),
            symbol_exposures=data.get("symbol_exposures", {}),
            total_capital=data.get("total_capital", 0.0),
            expected_return=data.get("expected_return", 0.0),
            expected_volatility=data.get("expected_volatility", 0.0),
        )
