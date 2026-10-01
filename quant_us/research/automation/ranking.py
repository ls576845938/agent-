"""Candidate ranking engine for research automation.

Scores candidates on multiple dimensions:
- Performance (CAGR, Sharpe)
- Risk (drawdown, volatility)
- Stability (walk-forward pass rate, OOS degradation)
- Cost robustness
- Regime robustness
- Turnover penalty
- Simplicity bonus
- Overfit penalty
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_us.research.lab.scorecard import ResearchScorecardBuilder


class CandidateRankingEngine:
    """Scores and ranks strategy candidates on multiple dimensions.

    Each candidate is scored 0-100 based on:
    - Performance (CAGR, Sharpe): 30 points max
    - Risk (drawdown, volatility): 20 points max
    - Stability (walk-forward, OOS degradation): 20 points max
    - Cost robustness: 10 points max
    - Regime robustness: 10 points max
    - Simplicity bonus: 5 points max
    - Turnover penalty: -5 points max
    - Overfit penalty: -10 points max
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self._scorecard_builder = ResearchScorecardBuilder(data_root=data_root)

    def rank(self, candidate_ids: list[str]) -> list[tuple[str, float, dict]]:
        """Rank candidates by total score, descending.

        Args:
            candidate_ids: List of candidate IDs to rank.

        Returns:
            List of (candidate_id, total_score, breakdown) sorted by score descending.
        """
        scored: list[tuple[str, float, dict]] = []
        for cid in candidate_ids:
            try:
                breakdown = self.score_breakdown(cid)
                total = sum(breakdown.values())
                scored.append((cid, total, breakdown))
            except (ValueError, FileNotFoundError, json.JSONDecodeError):
                continue

        return sorted(scored, key=lambda x: x[1], reverse=True)

    def score_breakdown(self, candidate_id: str) -> dict:
        """Detailed score breakdown for one candidate.

        Args:
            candidate_id: The candidate to score.

        Returns:
            Dict of score component name -> value.

        Raises:
            ValueError: If the candidate is not found.
        """
        scorecard = self._scorecard_builder.build(candidate_id)
        metrics = self._load_metrics(candidate_id)

        performance = self._score_performance(scorecard.sharpe, scorecard.cagr)
        risk = self._score_risk(scorecard.max_drawdown)
        stability = self._score_stability(
            scorecard.walk_forward_pass_rate, scorecard.oos_degradation
        )
        cost = self._score_cost_robustness(scorecard.cost_sensitivity)
        regime = self._score_regime_robustness(metrics)
        simplicity = self._score_simplicity(metrics)
        turnover = self._score_turnover(metrics)
        candidate_quality = self._score_candidate_quality(metrics, candidate_id)
        overfit = self._score_overfit_penalty(scorecard.overfit_risk)

        return {
            "performance": round(performance, 2),
            "risk": round(risk, 2),
            "stability": round(stability, 2),
            "cost_robustness": round(cost, 2),
            "regime_robustness": round(regime, 2),
            "simplicity_bonus": round(simplicity, 2),
            "turnover_penalty": round(turnover, 2),
            "candidate_quality_overlay": round(candidate_quality, 2),
            "overfit_penalty": round(overfit, 2),
        }

    # ------------------------------------------------------------------
    # Scoring helpers (each returns a float contribution to total)
    # ------------------------------------------------------------------

    @staticmethod
    def _score_performance(sharpe: float, cagr: float) -> float:
        """Score performance dimension (max 30 points)."""
        sharpe_score = min(max((sharpe / 3.0) * 20, 0), 20)
        cagr_score = min(max((cagr / 0.5) * 10, 0), 10)
        return sharpe_score + cagr_score

    @staticmethod
    def _score_risk(max_drawdown: float) -> float:
        """Score risk dimension (max 20 points)."""
        if max_drawdown <= 0:
            return 20.0
        if max_drawdown >= 0.5:
            return 0.0
        return max(20.0 * (1.0 - max_drawdown / 0.5), 0.0)

    @staticmethod
    def _score_stability(walk_forward_pass_rate: float, oos_degradation: float) -> float:
        """Score stability dimension (max 20 points)."""
        wf_score = walk_forward_pass_rate * 10.0
        oos_score = max(10.0 * (1.0 - oos_degradation), 0.0)
        return wf_score + oos_score

    @staticmethod
    def _score_cost_robustness(cost_sensitivity: float) -> float:
        """Score cost robustness (max 10 points)."""
        return max(10.0 * (1.0 - min(cost_sensitivity / 0.5, 1.0)), 0.0)

    @staticmethod
    def _score_regime_robustness(metrics: dict[str, Any]) -> float:
        """Score regime robustness (max 10 points).

        Uses sharpe_ratio across regimes from metrics if available,
        otherwise returns a neutral score.
        """
        regime_sharpes = metrics.get("regime_sharpes", {})
        if not regime_sharpes:
            return 5.0  # neutral

        values = [float(v) for v in regime_sharpes.values()]
        if not values:
            return 5.0

        # Penalize high variance across regimes
        mean_sharpe = sum(values) / len(values)
        variance = sum((v - mean_sharpe) ** 2 for v in values) / len(values)
        stability_penalty = min(variance * 10, 5.0)
        return max(10.0 - stability_penalty, 0.0)

    @staticmethod
    def _score_simplicity(metrics: dict[str, Any]) -> float:
        """Score simplicity bonus (max 5 points).

        Fewer parameters = higher simplicity score.
        """
        param_count = int(metrics.get("param_count", 0))
        if param_count <= 0:
            return 5.0  # unknown = benefit of doubt
        if param_count <= 3:
            return 5.0
        if param_count <= 5:
            return 3.0
        if param_count <= 10:
            return 1.0
        return 0.0

    @staticmethod
    def _score_turnover(metrics: dict[str, Any]) -> float:
        """Score turnover penalty (max -5 points).

        Higher turnover = larger penalty.
        """
        turnover = float(metrics.get("turnover", 0.0))
        if turnover <= 0:
            return 0.0
        if turnover <= 0.1:
            return 0.0
        if turnover <= 0.3:
            return -1.0
        if turnover <= 0.5:
            return -2.5
        return -5.0

    @staticmethod
    def _score_overfit_penalty(overfit_risk: str) -> float:
        """Score overfit penalty (max -10 points)."""
        if overfit_risk == "HIGH":
            return -10.0
        if overfit_risk == "MODERATE":
            return -5.0
        return 0.0

    def _score_candidate_quality(self, metrics: dict[str, Any], candidate_id: str) -> float:
        payload = self._load_candidate_quality(candidate_id)
        quality_score = float(
            payload.get("quality_score", metrics.get("candidate_quality_score", 0.0)) or 0.0
        )
        eligible = payload.get("eligible", metrics.get("candidate_quality_eligible"))
        warnings = list(payload.get("warnings", []) or [])
        rejection_reasons = list(payload.get("rejection_reasons", []) or [])

        score = quality_score * 5.0
        if eligible is False:
            score -= 3.0
        score -= min(len(warnings), 3) * 0.5
        score -= min(len(rejection_reasons), 2) * 1.0
        return score

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_metrics(self, candidate_id: str) -> dict[str, Any]:
        """Load raw metrics dict for a candidate."""
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
        return data.get("metrics", {})

    def _load_candidate_quality(self, candidate_id: str) -> dict[str, Any]:
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
        payload = data.get("candidate_quality", {})
        return payload if isinstance(payload, dict) else {}
