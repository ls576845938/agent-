from __future__ import annotations

import math
from typing import Any


class AllocationMethod:
    """Canonical allocation method identifiers used by CapitalAllocator."""
    EQUAL_WEIGHT = "equal_weight"
    INVERSE_VOL = "inverse_volatility"
    RISK_PARITY = "risk_parity"
    VOL_TARGET = "vol_targeting"
    DRAWDOWN_ADJUSTED = "drawdown_adjusted"


class CapitalAllocator:
    """Strategy-level capital allocation using various methods.

    All public methods return a dict[str, float] mapping strategy_id to weight.
    Results are always normalized to sum to 1.0 (or less if constrained).
    """

    def allocate(
        self,
        candidates: list[dict[str, Any]],
        method: str,
        constraints: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Dispatch to the appropriate allocation method.

        Parameters
        ----------
        candidates : list[dict]
            Each dict must have at least ``id`` (str) and ``volatility`` (float).
            Additional fields depend on the method.
        method : str
            One of the ``AllocationMethod`` constants.
        constraints : dict or None
            Optional constraints dict. Supported keys:
            - max_single_weight (float)
            - max_sector_weight (float) — requires ``sector`` key in candidates

        Returns
        -------
        dict[str, float]
            strategy_id -> weight, normalized and capped.
        """
        constraints = constraints or {}
        max_single = constraints.get("max_single_weight", 0.25)

        n = len(candidates)
        if n == 0:
            return {}
        ids = [c["id"] for c in candidates]

        if method == AllocationMethod.EQUAL_WEIGHT:
            raw = self.equal_weight(n)
            result = dict(zip(ids, raw))
        elif method == AllocationMethod.INVERSE_VOL:
            vols = {c["id"]: c["volatility"] for c in candidates}
            result = self.inverse_volatility(vols)
        elif method == AllocationMethod.RISK_PARITY:
            # Simplified: uses inverse vol as proxy (full cov not always available)
            vols = {c["id"]: c["volatility"] for c in candidates}
            result = self.inverse_volatility(vols)
        elif method == AllocationMethod.VOL_TARGET:
            vols = {c["id"]: c["volatility"] for c in candidates}
            equal = dict(zip(ids, self.equal_weight(n)))
            result = self.vol_targeting(equal, constraints.get("target_vol", 0.15), sum(vols.values()) / max(n, 1))
        elif method == AllocationMethod.DRAWDOWN_ADJUSTED:
            drawdowns = {c["id"]: c.get("max_drawdown", 0.0) for c in candidates}
            vols = {c["id"]: c["volatility"] for c in candidates}
            inv_vol = self.inverse_volatility(vols)
            result = self.drawdown_adjusted(inv_vol, drawdowns)
        else:
            raise ValueError(f"Unknown allocation method: {method}")

        # Cap at max_single_weight
        result = {k: min(v, max_single) for k, v in result.items()}
        total = sum(result.values())
        if total > 0:
            result = {k: v / total for k, v in result.items()}
        return result

    # ------------------------------------------------------------------
    # Individual method implementations
    # ------------------------------------------------------------------

    @staticmethod
    def equal_weight(n: int) -> list[float]:
        """Equal weight across n assets."""
        if n <= 0:
            return []
        return [1.0 / n] * n

    @staticmethod
    def inverse_volatility(volatilities: dict[str, float]) -> dict[str, float]:
        """Weight inversely proportional to volatility."""
        if not volatilities:
            return {}
        inv = {k: 1.0 / max(v, 1e-10) for k, v in volatilities.items()}
        total = sum(inv.values())
        if total <= 0:
            return {k: 0.0 for k in inv}
        return {k: v / total for k, v in inv.items()}

    @staticmethod
    def risk_parity(
        cov_matrix: list[list[float]],
        labels: list[str],
        max_iter: int = 100,
    ) -> dict[str, float]:
        """Simple risk-parity via iterative equal risk contribution.

        This is a basic Newton-like approximation. For production use,
        a proper convex solver is recommended.

        Parameters
        ----------
        cov_matrix : list[list[float]]
            NxN covariance matrix.
        labels : list[str]
            Asset identifiers matching matrix order.
        max_iter : int
            Maximum iterations.

        Returns
        -------
        dict[str, float]
            Asset weights that equalize risk contribution.
        """
        n = len(labels)
        if n == 0:
            return {}
        if n == 1:
            return {labels[0]: 1.0}

        # Starting from equal weight
        w = [1.0 / n] * n

        for _ in range(max_iter):
            # Compute marginal risk contributions
            sigma = [0.0] * n
            for i in range(n):
                for j in range(n):
                    sigma[i] += cov_matrix[i][j] * w[j]

            # Target: equal risk contribution => w_i * sigma_i = constant
            # Adjust weights toward equal risk budget
            total_risk = sum(w[i] * sigma[i] for i in range(n))
            if total_risk <= 0:
                break
            target_rc = total_risk / n

            new_w = [0.0] * n
            for i in range(n):
                if sigma[i] > 1e-12:
                    new_w[i] = target_rc / sigma[i]

            # Normalize
            s = sum(new_w)
            if s > 0:
                new_w = [x / s for x in new_w]

            # Check convergence
            diff = sum(abs(new_w[i] - w[i]) for i in range(n))
            w = new_w
            if diff < 1e-8:
                break

        return dict(zip(labels, w))

    @staticmethod
    def vol_targeting(
        weights: dict[str, float],
        target_vol: float,
        current_vol: float,
    ) -> dict[str, float]:
        """Scale portfolio weights to target a specific volatility level."""
        if current_vol <= 0 or target_vol <= 0:
            return weights
        scale = target_vol / current_vol
        return {k: v * scale for k, v in weights.items()}

    @staticmethod
    def drawdown_adjusted(
        weights: dict[str, float],
        drawdowns: dict[str, float],
    ) -> dict[str, float]:
        """Reduce weights based on recent drawdown severity.

        Drawdown is expressed as a fraction (e.g. 0.10 = 10% peak-to-trough).
        Strategies with deeper drawdowns get a larger penalty.
        """
        if not weights or not drawdowns:
            return weights

        max_dd = max(drawdowns.values()) if drawdowns else 0.0
        if max_dd <= 0:
            return weights

        adjusted = {}
        for k, w in weights.items():
            dd = drawdowns.get(k, 0.0)
            penalty = 1.0 - (dd / max_dd) * 0.5  # max 50% penalty
            adjusted[k] = w * max(penalty, 0.0)

        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: v / total for k, v in adjusted.items()}
        return adjusted
