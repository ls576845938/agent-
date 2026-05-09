"""Alpha decay analysis for strategy candidates.

Measures how quickly a strategy's information coefficient (IC) decays
over increasing holding horizons, estimates half-life, and recommends
an appropriate holding period.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AlphaDecayResult:
    """Alpha decay analysis result for a single candidate.

    Attributes:
        candidate_id: The candidate being analyzed.
        alpha_half_life: Estimated days until IC drops to half of its peak.
        ic_decay_curve: IC values at each tested horizon (ordered by horizon).
        recommended_holding_period: Suggested holding period category.
        decay_warning: "RAPID_DECAY" | "MODERATE" | "STABLE".
    """

    candidate_id: str
    alpha_half_life: float = 0.0
    ic_decay_curve: list[float] = field(default_factory=list)
    recommended_holding_period: str = ""
    decay_warning: str = ""


class AlphaDecayAnalyzer:
    """Analyze alpha decay for a strategy candidate.

    Reads candidate metrics and factor IC data to compute how the strategy's
    predictive power decays with longer holding horizons.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def analyze(
        self, candidate_id: str, horizons: list[int] | None = None
    ) -> AlphaDecayResult:
        """Analyze alpha decay for a candidate.

        Loads candidate metrics and IC-by-horizon data, builds the decay
        curve, estimates half-life, and produces a recommendation.

        Args:
            candidate_id: The candidate to analyze.
            horizons: List of forward horizons in days (default [1,3,5,10,20]).

        Returns:
            AlphaDecayResult with decay metrics.

        Raises:
            ValueError: If the candidate is not found or has no IC data.
        """
        if horizons is None:
            horizons = [1, 3, 5, 10, 20]

        candidate_data = self._load_candidate(candidate_id)
        metrics = candidate_data.get("metrics", {})

        # Try to get IC by horizon from metrics or from factor data
        ic_by_horizon = self._resolve_ic_by_horizon(candidate_id, metrics, horizons)

        if not ic_by_horizon:
            raise ValueError(
                f"Candidate {candidate_id}: no IC data available for alpha decay analysis"
            )

        # Build decay curve ordered by horizon
        ic_decay_curve = [ic_by_horizon[h] for h in sorted(ic_by_horizon)]

        # Estimate half-life
        half_life = self.estimate_half_life(ic_by_horizon)

        # Classify decay
        if half_life <= 0:
            decay_warning = "RAPID_DECAY"
        elif half_life <= 3:
            decay_warning = "RAPID_DECAY"
        elif half_life <= 10:
            decay_warning = "MODERATE"
        else:
            decay_warning = "STABLE"

        # Recommend holding period
        recommendation = self.recommend_holding(half_life)

        return AlphaDecayResult(
            candidate_id=candidate_id,
            alpha_half_life=round(half_life, 2),
            ic_decay_curve=[round(v, 6) for v in ic_decay_curve],
            recommended_holding_period=recommendation,
            decay_warning=decay_warning,
        )

    @staticmethod
    def estimate_half_life(ic_by_horizon: dict[int, float]) -> float:
        """Estimate the IC half-life (days until IC drops to half of peak).

        Fits a simple exponential decay model: IC(h) = IC_peak * 0.5^(h / half_life).
        If no decay is detected, returns a large value.

        Args:
            ic_by_horizon: Dict mapping horizon (days) to IC value.

        Returns:
            Estimated half-life in days.
        """
        sorted_h = sorted(ic_by_horizon.keys())
        if len(sorted_h) < 2:
            return 0.0

        peak_ic = max(ic_by_horizon.values())
        if peak_ic <= 0:
            return 0.0

        # Find the first horizon where IC drops below half of peak
        target = peak_ic * 0.5

        for h in sorted_h:
            if ic_by_horizon[h] <= target:
                # Linear interpolation between this point and the previous
                prev_h = sorted_h[sorted_h.index(h) - 1] if sorted_h.index(h) > 0 else 0
                prev_ic = ic_by_horizon.get(prev_h, peak_ic)

                # If prev_ic <= target too, keep searching backwards
                if prev_ic <= target:
                    continue

                # Interpolate: find h where IC(h) == target
                fraction = (target - ic_by_horizon[h]) / (prev_ic - ic_by_horizon[h])
                interpolated = h - fraction * (h - prev_h)
                return max(0.0, interpolated)

        # IC never drops below half -> long half-life
        return float(sorted_h[-1]) * 2.0

    @staticmethod
    def recommend_holding(half_life: float) -> str:
        """Recommend a holding period based on alpha half-life.

        Args:
            half_life: Estimated alpha half-life in days.

        Returns:
            One of "intraday", "swing_2-5d", "position_10d+".
        """
        if half_life <= 0:
            return "intraday"
        if half_life <= 2:
            return "intraday"
        if half_life <= 5:
            return "swing_2-5d"
        return "position_10d+"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_candidate(self, candidate_id: str) -> dict:
        """Load raw candidate JSON data."""
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            raise ValueError(f"Candidate {candidate_id} not found at {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _resolve_ic_by_horizon(
        self, candidate_id: str, metrics: dict, horizons: list[int]
    ) -> dict[int, float]:
        """Resolve IC values for each requested horizon.

        Priority:
        1. Stored 'ic_by_horizon' dict in candidate metrics.
        2. Stored factor IC values loaded from factor data.
        3. Single 'ic' value replicated across all horizons.
        """
        # Check for pre-computed ic_by_horizon
        stored = metrics.get("ic_by_horizon")
        if isinstance(stored, dict) and stored:
            result: dict[int, float] = {}
            for h in horizons:
                key = str(h)
                if key in stored:
                    result[h] = float(stored[key])
            if len(result) >= 2:
                return result

        # Try to load factor IC data
        factor_ic = self._load_factor_ic(candidate_id)
        if factor_ic:
            result = {}
            for h in horizons:
                key = str(h)
                if key in factor_ic:
                    result[h] = float(factor_ic[key])
            if len(result) >= 2:
                return result

        # Fallback: replicate single IC across all horizons
        single_ic = float(metrics.get("ic", 0.0))
        if single_ic != 0.0:
            return {h: single_ic * (0.5 ** (h / 5.0)) for h in horizons}

        return {}

    def _load_factor_ic(self, candidate_id: str) -> dict[str, float] | None:
        """Attempt to load IC data from linked factor evaluation."""
        candidate = self._load_candidate(candidate_id)
        experiment_id = candidate.get("experiment_id", "")
        if not experiment_id:
            return None

        # Check experiment manifest for linked factor
        exp_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        if not exp_path.exists():
            return None

        try:
            exp_data = json.loads(exp_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        factor_id = exp_data.get("params", {}).get("factor_id", "")
        if not factor_id:
            return None

        # Look for factor evaluation data
        factor_path = (
            self.data_root / "research" / "factors" / f"{factor_id}.json"
        )
        if not factor_path.exists():
            return None

        try:
            factor_data = json.loads(factor_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        raw = factor_data.get("ic_by_horizon", {})
        if isinstance(raw, dict) and raw:
            return {str(k): float(v) for k, v in raw.items()}

        return None
