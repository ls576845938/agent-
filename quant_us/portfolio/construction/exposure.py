from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quant_us.risk.exposure import gross_exposure, net_exposure


@dataclass(frozen=True)
class ExposureReport:
    """Aggregate exposure analysis for a portfolio."""
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    single_symbol_exposures: dict[str, float] = field(default_factory=dict)
    sector_exposures: dict[str, float] = field(default_factory=dict)
    strategy_exposures: dict[str, float] = field(default_factory=dict)
    correlation_clusters: list[list[str]] = field(default_factory=list)
    diversification_ratio: float = 1.0


class ExposureManager:
    """Analyze and constrain portfolio exposures.

    This module builds on ``quant_us.risk.exposure`` for low-level
    gross/net calculations and adds portfolio-level analysis.
    """

    def analyze(
        self,
        positions: dict[str, float],
        prices: dict[str, float],
        sectors: dict[str, str] | None = None,
        strategies: dict[str, str] | None = None,
    ) -> ExposureReport:
        """Analyze portfolio exposures.

        Parameters
        ----------
        positions : dict[str, float]
            Symbol -> net exposure (dollar amount).
        prices : dict[str, float]
            Symbol -> latest price (for gross calculation).
        sectors : dict[str, str] or None
            Symbol -> sector mapping.
        strategies : dict[str, str] or None
            Symbol -> strategy_id mapping.

        Returns
        -------
        ExposureReport
        """
        # Build Position objects for the risk module helpers
        from quant_us.core.types import Position as _Position

        pos_objects: dict[str, _Position] = {}
        for sym, val in positions.items():
            price = prices.get(sym, 1.0)
            quantity = val / max(price, 1e-10)
            pos_objects[sym] = _Position(
                symbol=sym,
                quantity=quantity,
                avg_price=price,
                market_price=price,
            )

        gross = gross_exposure(pos_objects)
        net = net_exposure(pos_objects)

        # Single symbol exposures (as fraction of gross)
        single_sym: dict[str, float] = {}
        for sym, pos in pos_objects.items():
            single_sym[sym] = abs(pos.market_value) / max(abs(gross), 1e-10)

        # Sector exposures
        sector_exps: dict[str, float] = {}
        sectors = sectors or {}
        for sym, pos in pos_objects.items():
            sector = sectors.get(sym, "unknown")
            sector_exps[sector] = sector_exps.get(sector, 0.0) + abs(pos.market_value)

        gross_sector = max(sum(sector_exps.values()), 1e-10)
        sector_exps = {k: v / gross_sector for k, v in sector_exps.items()}

        # Strategy exposures (as fraction of gross)
        strat_exps: dict[str, float] = {}
        for sym, pos in pos_objects.items():
            sid = strategies.get(sym, "unknown") if strategies else "unknown"
            strat_exps[sid] = strat_exps.get(sid, 0.0) + abs(pos.market_value)

        gross_strat = max(sum(strat_exps.values()), 1e-10)
        strat_exps = {k: v / gross_strat for k, v in strat_exps.items()}

        # Simplified diversification ratio
        avg_single = (
            sum(single_sym.values()) / max(len(single_sym), 1)
            if single_sym
            else 0.0
        )
        div_ratio = 1.0 / max(avg_single, 0.01) if avg_single > 0 else 1.0

        return ExposureReport(
            gross_exposure=gross,
            net_exposure=net,
            single_symbol_exposures=single_sym,
            sector_exposures=sector_exps,
            strategy_exposures=strat_exps,
            correlation_clusters=[],
            diversification_ratio=min(div_ratio, float(len(single_sym))),
        )

    @staticmethod
    def check_limits(
        report: ExposureReport,
        limits: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Check exposure report against constraints.

        Parameters
        ----------
        report : ExposureReport
        limits : dict
            Supported keys:
            - max_gross_exposure (float)
            - max_net_exposure (float)
            - max_single_weight (float)
            - max_sector_weight (float)

        Returns
        -------
        tuple[bool, list[str]]
            (passed, list of violation messages).
        """
        violations: list[str] = []

        max_gross = limits.get("max_gross_exposure", float("inf"))
        if abs(report.gross_exposure) > max_gross:
            violations.append(
                f"Gross exposure {report.gross_exposure:.2f} exceeds limit {max_gross:.2f}"
            )

        max_net = limits.get("max_net_exposure", float("inf"))
        if abs(report.net_exposure) > max_net:
            violations.append(
                f"Net exposure {report.net_exposure:.2f} exceeds limit {max_net:.2f}"
            )

        max_single = limits.get("max_single_weight", 0.25)
        for sym, exp in report.single_symbol_exposures.items():
            if exp > max_single:
                violations.append(
                    f"Symbol {sym} exposure {exp:.4f} exceeds limit {max_single:.4f}"
                )

        max_sector = limits.get("max_sector_weight", 0.40)
        for sector, exp in report.sector_exposures.items():
            if exp > max_sector:
                violations.append(
                    f"Sector {sector} exposure {exp:.4f} exceeds limit {max_sector:.4f}"
                )

        return (len(violations) == 0, violations)
