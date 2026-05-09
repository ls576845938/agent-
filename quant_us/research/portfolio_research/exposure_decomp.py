"""Exposure decomposition for multi-strategy portfolios.

Decomposes aggregate portfolio exposure into strategy-level, symbol-level,
sector-level, and factor-level components from strategy manifest data.
NEVER submits orders or triggers trading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExposureDecomposition:
    """Decomposed portfolio exposure across multiple dimensions."""

    strategy_exposure: dict[str, float]  # strategy_id -> weight
    symbol_exposure: dict[str, float]  # symbol -> net exposure
    sector_exposure: dict[str, float]  # sector -> weight (if data available)
    factor_exposure: dict[str, float]  # factor -> loading
    long_exposure: float = 0.0
    short_exposure: float = 0.0  # always 0 for long-only research
    cash_exposure: float = 0.0


class ExposureDecomposer:
    """Decompose portfolio exposure across strategies, symbols, sectors, and factors.

    Works with strategy manifests in the research layer only.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.manifests_dir = self.data_root / "research" / "manifests"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decompose(
        self,
        strategy_manifest_ids: list[str],
        weights: dict[str, float],
    ) -> ExposureDecomposition:
        """Decompose portfolio exposure from strategy manifests and weights.

        Args:
            strategy_manifest_ids: List of strategy manifest IDs.
            weights: Strategy ID -> weight mapping. Must cover all manifests.

        Returns:
            ExposureDecomposition with strategy, symbol, sector, and
            factor level exposures.

        Raises:
            ValueError: If manifest not found, weights don't sum to ~1.0,
                        or strategy IDs in weights don't match manifests.
        """
        if not strategy_manifest_ids:
            raise ValueError("At least one strategy manifest ID is required")

        total_weight = sum(weights.values())
        if total_weight <= 0:
            raise ValueError("Total weight must be positive")

        manifests = self._load_manifests(strategy_manifest_ids)

        # Map strategy candidate ID -> manifest
        manifest_map: dict[str, Any] = {}
        for m in manifests:
            manifest_map[m.strategy_candidate_id] = m

        # Verify all loaded strategy candidate IDs have weights
        missing = [sid for sid in manifest_map if sid not in weights]
        if missing:
            raise ValueError(
                f"Strategy IDs {missing} not found in weights. "
                f"Weights keys: {list(weights.keys())}"
            )

        # Normalize weights
        normalized_weights = {
            k: v / total_weight for k, v in weights.items()
        }

        # Strategy-level exposure
        strategy_exposure = dict(normalized_weights)

        # Symbol-level exposure -- aggregate holdings from manifests
        symbol_exposure: dict[str, float] = {}
        for m in manifests:
            sid = m.strategy_candidate_id
            w = normalized_weights.get(sid, 0.0)
            holdings = getattr(m, "scorecard", {}).get("holdings", {})
            if holdings:
                for sym, frac in holdings.items():
                    symbol_exposure[sym] = symbol_exposure.get(sym, 0.0) + w * frac

        # Sector exposure -- from manifest symbols if sector data available
        sector_exposure: dict[str, float] = self._build_sector_exposure(manifests, normalized_weights)

        # Factor exposure -- simplified estimate from scorecard metrics
        factor_exposure = self._build_factor_exposure(manifests, normalized_weights)

        long_exposure = sum(symbol_exposure.values()) if symbol_exposure else 1.0

        return ExposureDecomposition(
            strategy_exposure=strategy_exposure,
            symbol_exposure=symbol_exposure,
            sector_exposure=sector_exposure,
            factor_exposure=factor_exposure,
            long_exposure=long_exposure,
            short_exposure=0.0,
            cash_exposure=max(0.0, 1.0 - long_exposure),
        )

    def check_limits(
        self,
        decomp: ExposureDecomposition,
        max_symbol: float = 0.25,
        max_sector: float = 0.40,
    ) -> tuple[bool, list[str]]:
        """Check decomposed exposure against concentration limits.

        Args:
            decomp: ExposureDecomposition to check.
            max_symbol: Maximum fraction for any single symbol (default 0.25).
            max_sector: Maximum fraction for any single sector (default 0.40).

        Returns:
            Tuple of (passed, list of violation messages).
        """
        violations: list[str] = []

        for sym, exp in decomp.symbol_exposure.items():
            if exp > max_symbol:
                violations.append(
                    f"Symbol {sym} exposure {exp:.4f} exceeds limit {max_symbol:.4f}"
                )

        for sector, exp in decomp.sector_exposure.items():
            if exp > max_sector:
                violations.append(
                    f"Sector {sector} exposure {exp:.4f} exceeds limit {max_sector:.4f}"
                )

        return (len(violations) == 0, violations)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_manifests(self, manifest_ids: list[str]) -> list[Any]:
        """Load strategy manifests from disk."""
        from quant_us.research.strategy_manifest import StrategyManifestManager

        mgr = StrategyManifestManager(data_root=str(self.data_root))
        manifests: list[Any] = []
        for mid in manifest_ids:
            m = mgr.load(mid)
            if m is None:
                raise ValueError(f"Strategy manifest {mid} not found")
            manifests.append(m)
        return manifests

    def _build_sector_exposure(
        self,
        manifests: list[Any],
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Build sector exposure from manifest scorecard sector data.

        Falls back to 'unknown' if no sector data available.
        """
        sector_exposure: dict[str, float] = {}
        for m in manifests:
            sid = m.strategy_candidate_id
            w = weights.get(sid, 0.0)
            # Try to get sector data from scorecard or manifest symbols
            sector_map = getattr(m, "scorecard", {}).get("sector_exposures", {})
            if sector_map:
                for sector, frac in sector_map.items():
                    sector_exposure[sector] = sector_exposure.get(sector, 0.0) + w * frac
            else:
                # If no sector data, mark as unknown
                sector_exposure["unknown"] = sector_exposure.get("unknown", 0.0) + w

        return sector_exposure

    def _build_factor_exposure(
        self,
        manifests: list[Any],
        weights: dict[str, float],
    ) -> dict[str, float]:
        """Build factor exposure estimates from manifest scorecard metrics.

        Constructs a simplified factor profile from sharpe ratio, volatility,
        and drawdown characteristics.
        """
        factor_exposure: dict[str, float] = {
            "momentum": 0.0,
            "value": 0.0,
            "volatility": 0.0,
            "size": 0.0,
        }

        for m in manifests:
            sid = m.strategy_candidate_id
            w = weights.get(sid, 0.0)
            sc = getattr(m, "scorecard", {}) or {}

            strategy_template = getattr(m, "strategy_template", "")
            sharpe = sc.get("sharpe_ratio", 1.0)
            vol = sc.get("volatility", 0.15)

            # Heuristic: map strategy template to factor profile
            if "momentum" in strategy_template.lower():
                factor_exposure["momentum"] += w * 0.7
                factor_exposure["volatility"] += w * 0.3
            elif "value" in strategy_template.lower():
                factor_exposure["value"] += w * 0.7
                factor_exposure["size"] += w * 0.3
            elif "etf" in strategy_template.lower():
                factor_exposure["momentum"] += w * 0.4
                factor_exposure["volatility"] += w * 0.4
                factor_exposure["size"] += w * 0.2
            else:
                # Generic: infer from sharpe/vol profile
                mom_factor = min(max((sharpe - 0.5) / 2.0, 0.0), 1.0)
                factor_exposure["momentum"] += w * mom_factor * 0.5
                factor_exposure["volatility"] += w * (1.0 - mom_factor) * 0.5
                factor_exposure["value"] += w * 0.25
                factor_exposure["size"] += w * 0.25

        return factor_exposure
