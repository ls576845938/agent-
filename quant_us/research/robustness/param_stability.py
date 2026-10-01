"""Parameter stability analysis for strategy candidates.

Detects parameter cliffs (small param changes causing large performance drops)
and estimates the size of robust parameter regions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ParamStabilityResult:
    """Parameter stability analysis result.

    Attributes:
        candidate_id: The candidate being analyzed.
        stability_score: Overall stability score 0-1 (higher = more stable).
        cliff_count: Number of detected parameter cliffs.
        robust_region_ratio: Fraction of neighbor configs above threshold.
        best_params: Parameters that achieved the highest score.
        robust_params: Parameters that produced above-threshold scores.
    """

    candidate_id: str
    stability_score: float = 0.0
    cliff_count: int = 0
    robust_region_ratio: float = 0.0
    best_params: dict = field(default_factory=dict)
    robust_params: dict = field(default_factory=dict)


class ParameterStabilityAnalyzer:
    """Analyze parameter stability for a strategy candidate.

    Evaluates how sensitive a candidate's performance is to small changes
    in its parameters by examining neighbor configurations.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def analyze(
        self, candidate_id: str, param_neighbors: list[dict[str, Any]]
    ) -> ParamStabilityResult:
        """Analyze parameter stability for a candidate.

        Args:
            candidate_id: The candidate being analyzed.
            param_neighbors: List of dicts, each with param values and at least
                a "score" or "sharpe_ratio" key for performance.

        Returns:
            ParamStabilityResult with stability metrics.

        Raises:
            ValueError: If param_neighbors is empty.
        """
        if not param_neighbors:
            raise ValueError(
                f"Cannot analyze {candidate_id}: param_neighbors is empty"
            )

        # Extract scores from neighbors
        scores = []
        param_configs = []
        for neighbor in param_neighbors:
            score = float(neighbor.get("score", neighbor.get("sharpe_ratio", 0.0)))
            scores.append(score)
            # Extract params (everything except score keys)
            params = {
                k: v
                for k, v in neighbor.items()
                if k not in ("score", "sharpe_ratio", "candidate_id")
            }
            param_configs.append(params)

        # Detect cliffs across all param names
        all_param_names = set()
        for p in param_configs:
            all_param_names.update(p.keys())

        total_cliffs = 0
        for pname in sorted(all_param_names):
            values = [p.get(pname, 0) for p in param_configs]
            cliffs = self.detect_cliffs(pname, values, scores)
            total_cliffs += len(cliffs)

        # Estimate robust region ratio
        robust_ratio = self.estimate_robust_region(
            {}, scores, threshold=0.8
        )

        # Find best config
        best_idx = max(range(len(scores)), key=lambda i: scores[i])
        best_params = param_configs[best_idx] if param_configs else {}

        # Find robust configs (score >= 80% of max)
        max_score = max(scores) if scores else 0.0
        robust_threshold = max_score * 0.8
        robust_indices = [
            i for i, s in enumerate(scores) if s >= robust_threshold
        ]
        robust_params = (
            param_configs[robust_indices[0]] if robust_indices else best_params
        )

        # Stability score: based on CV of scores, cliff count penalty
        if len(scores) > 1:
            mean_score = sum(scores) / len(scores)
            if mean_score > 0:
                variance = sum((s - mean_score) ** 2 for s in scores) / len(scores)
                cv = (variance ** 0.5) / abs(mean_score)
                # Lower CV is better, 0 CV -> 1.0, scale so CV of 1.0 -> 0.0
                stability_cv = max(0.0, 1.0 - cv)
            else:
                stability_cv = 0.0
        else:
            stability_cv = 1.0

        # Penalize cliffs (each cliff reduces score by 0.05)
        cliff_penalty = min(1.0, total_cliffs * 0.05)
        stability_score = max(0.0, min(1.0, stability_cv - cliff_penalty))

        return ParamStabilityResult(
            candidate_id=candidate_id,
            stability_score=round(stability_score, 4),
            cliff_count=total_cliffs,
            robust_region_ratio=round(robust_ratio, 4),
            best_params=best_params,
            robust_params=robust_params,
        )

    @staticmethod
    def detect_cliffs(
        param_name: str, values: list[float], scores: list[float]
    ) -> list[int]:
        """Detect parameter cliffs: positions where a small change in param
        value causes a large drop in score (>= 50% drop from max).

        A cliff is defined as a point where:
        - The normalized score change between adjacent sorted param values
          exceeds a threshold (50% drop in score relative to max).

        Args:
            param_name: Name of the parameter (for reporting).
            values: Parameter values for each neighbor config.
            scores: Corresponding performance scores.

        Returns:
            List of indices (in the sorted-by-value order) where cliffs occur.
        """
        if len(values) < 3:
            return []

        # Sort by parameter value
        paired = sorted(zip(values, scores), key=lambda x: x[0])
        sorted_scores = [p[1] for p in paired]
        max_score = max(sorted_scores)

        if max_score <= 0:
            return []

        cliff_indices: list[int] = []
        for i in range(1, len(sorted_scores)):
            score_change = (sorted_scores[i - 1] - sorted_scores[i]) / max_score
            # If score drops by >= 50% of max between adjacent points
            if score_change >= 0.50:
                cliff_indices.append(i)

        return cliff_indices

    @staticmethod
    def estimate_robust_region(
        param_grid: dict[str, list[float]],
        scores: list[float],
        threshold: float = 0.8,
    ) -> float:
        """Estimate the fraction of parameter combinations that are robust.

        Robust means the score >= threshold * max_score.

        Args:
            param_grid: Dict mapping param names to list of tested values.
                May be empty if scores directly represent the grid evaluations.
            scores: Performance scores for each parameter combination.
            threshold: Fraction of max score required to be "robust" (default 0.8).

        Returns:
            Robust region ratio: fraction of scores above threshold.
        """
        if not scores:
            return 0.0

        max_score = max(scores)
        if max_score <= 0:
            return 0.0

        cutoff = max_score * threshold
        robust_count = sum(1 for s in scores if s >= cutoff)
        return robust_count / len(scores)

    # ------------------------------------------------------------------
    # Candidate loader for CLI convenience
    # ------------------------------------------------------------------

    def load_candidate_params(self, candidate_id: str) -> dict:
        """Load the candidate's own parameters from stored data.

        Args:
            candidate_id: The candidate to load.

        Returns:
            Dict of parameter name -> value.

        Raises:
            ValueError: If candidate not found.
        """
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            raise ValueError(f"Candidate {candidate_id} not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("params", {})
