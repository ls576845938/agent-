"""Research promotion gate for evaluating candidate readiness.

Determines whether a strategy candidate is ready to proceed to
human paper-review evaluation. This is a research-layer gate only;
it NEVER triggers paper trading or live trading.

Decision outcomes:
- BLOCKED: Missing required evidence or fatal risk.
- WATCHLIST: Some checks passed but needs more data or analysis.
- NEED_MORE_RESEARCH: Additional research required before promotion
  (e.g., high correlation redundancy).
- READY_FOR_PAPER_REVIEW: All checks pass. Candidate enters
  the human review pool for paper trading consideration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PromotionGateResult:
    """Result of a promotion gate evaluation.

    Attributes:
        candidate_id: The evaluated candidate.
        decision: BLOCKED | WATCHLIST | NEED_MORE_RESEARCH | READY_FOR_PAPER_REVIEW.
        reasons: Blocking reasons (fatal issues).
        warnings: Non-blocking concerns.
        needs_more_research: Items requiring additional research before promotion.
        evidence: Dict of evidence collected during evaluation, e.g.
            {"manifest_exists": True, "scorecard_exists": True, ...}.
    """

    candidate_id: str
    decision: str = "BLOCKED"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_more_research: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


class ResearchPromotionGate:
    """Evaluate candidates for promotion from research to paper review.

    The gate checks REQUIRED evidence:
    - ExperimentManifest exists
    - RobustScorecard exists
    - OverfitDetector report (no overfit)
    - WalkForward result (must be run)
    - Trade count > 10
    - Cost stress passed
    - Max drawdown < 50%
    - Monte Carlo survival rate > 80%  (R6)
    - Alpha decay half-life > 5 days  (R6)
    - Param stability score > 0.5     (R6)
    - Correlation redundancy < 0.70   (R7)
    - Stress survival rate > 70%       (R8)

    READY_FOR_PAPER_REVIEW means the candidate is ready for HUMAN REVIEW
    only. It does NOT enter paper trading automatically.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def evaluate(self, candidate_id: str) -> PromotionGateResult:
        """Evaluate a candidate for promotion readiness.

        Args:
            candidate_id: The candidate to evaluate.

        Returns:
            PromotionGateResult with decision, reasons, warnings, and evidence.
        """
        reasons: list[str] = []
        warnings: list[str] = []
        evidence: dict[str, Any] = {}

        needs_more_research: list[str] = []

        # Evidence 1: Candidate file exists
        candidate_data = self._load_candidate(candidate_id)
        manifest_exists = candidate_data is not None
        evidence["manifest_exists"] = manifest_exists
        if not manifest_exists:
            reasons.append("missing_manifest: candidate file not found")
            return PromotionGateResult(
                candidate_id=candidate_id,
                decision="BLOCKED",
                reasons=reasons,
                warnings=warnings,
                needs_more_research=needs_more_research,
                evidence=evidence,
            )

        # Evidence 2: Experiment manifest exists
        experiment_id = candidate_data.get("experiment_id", "")
        experiment_path = (
            self.data_root
            / "research"
            / "experiments"
            / experiment_id
            / "manifest.json"
        )
        manifest_ok = experiment_path.exists()
        evidence["experiment_manifest_exists"] = manifest_ok
        if not manifest_ok:
            reasons.append("missing_manifest: experiment manifest not found")

        # Evidence 3: Scorecard exists
        scorecard_path = (
            self.data_root
            / "research"
            / "scorecards"
            / f"{candidate_id}.json"
        )
        scorecard_exists = scorecard_path.exists()
        evidence["scorecard_exists"] = scorecard_exists
        if not scorecard_exists:
            reasons.append("missing_scorecard: robust scorecard not found")

        # Evidence 4: OverfitDetector report
        from quant_us.research.automation.overfit import OverfitDetector

        detector = OverfitDetector(data_root=str(self.data_root))
        try:
            report = detector.check(candidate_id)
            evidence["overfit_report"] = {
                "is_overfit": report.is_overfit,
                "degradation_pct": report.degradation_pct,
                "reason_count": len(report.reasons),
            }
            if report.is_overfit:
                reasons.append("overfit_risk_high: " + "; ".join(report.reasons))
        except ValueError:
            evidence["overfit_report"] = {"error": "candidate_not_found"}
            reasons.append("missing_data: cannot run overfit check")

        # Evidence 5: WalkForward result
        metrics = candidate_data.get("metrics", {})
        wf_pass_rate = float(metrics.get("walk_forward_pass_rate", -1.0))
        wf_run = wf_pass_rate >= 0.0
        evidence["walk_forward_run"] = wf_run
        if not wf_run:
            warnings.append("needs_walk_forward: walk-forward analysis not run")

        # Evidence 6: Trade count > 10
        trade_count = int(metrics.get("trade_count", 0))
        evidence["trade_count"] = trade_count
        if trade_count <= 10:
            warnings.append(
                f"trade_count_too_low: only {trade_count} trades "
                f"(need > 10 for statistical significance)"
            )

        # Evidence 7: Cost stress passed
        # Cost sensitivity > 0.5 implies failure at 5x costs
        cost_sensitivity = float(metrics.get("cost_sensitivity", 0.0))
        evidence["cost_sensitivity"] = cost_sensitivity
        if cost_sensitivity > 0.5:
            reasons.append(
                f"cost_impact_too_high: cost_sensitivity={cost_sensitivity:.3f} "
                "(> 0.5 threshold)"
            )

        # Evidence 8: Max drawdown < 0.50
        max_dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
        evidence["max_drawdown"] = max_dd
        if max_dd >= 0.50:
            reasons.append(
                f"max_drawdown_too_high: {max_dd:.1%} "
                "(>= 50% threshold)"
            )

        # --- R6: Alpha Robustness Checks ---

        # Evidence 9: Monte Carlo survival_rate > 0.80
        monte_carlo_survival = float(metrics.get("monte_carlo_survival_rate", 0.0))
        evidence["monte_carlo_survival_rate"] = monte_carlo_survival
        if monte_carlo_survival <= 0.80:
            reasons.append(
                f"monte_carlo_survival_low: survival_rate={monte_carlo_survival:.3f} "
                "(<= 0.80 threshold)"
            )

        # Evidence 10: Alpha decay half-life > 5 days
        alpha_decay_half_life = float(metrics.get("alpha_decay_half_life_days", 0.0))
        evidence["alpha_decay_half_life_days"] = alpha_decay_half_life
        if alpha_decay_half_life <= 5.0:
            warnings.append(
                f"rapid_alpha_decay: half_life={alpha_decay_half_life:.1f} days "
                "(<= 5 days threshold)"
            )

        # Evidence 11: Param stability score > 0.5
        param_stability = float(metrics.get("param_stability_score", 0.0))
        evidence["param_stability_score"] = param_stability
        if param_stability <= 0.5:
            reasons.append(
                f"param_unstable: stability_score={param_stability:.3f} "
                "(<= 0.5 threshold)"
            )

        # --- R7: Multi-Strategy Portfolio Checks ---

        # Evidence 12: Correlation redundancy < 0.70
        correlation_redundancy = float(metrics.get("correlation_redundancy", 0.0))
        evidence["correlation_redundancy"] = correlation_redundancy
        if correlation_redundancy >= 0.70:
            needs_more_research.append(
                f"high_redundancy: correlation_redundancy={correlation_redundancy:.3f} "
                "(>= 0.70 threshold)"
            )

        # --- R8: Stress Test Checks ---

        # Evidence 13: Stress survival_rate > 0.70
        stress_survival_rate = float(metrics.get("stress_survival_rate", 0.0))
        evidence["stress_survival_rate"] = stress_survival_rate
        if stress_survival_rate <= 0.70:
            reasons.append(
                f"stress_survival_low: survival_rate={stress_survival_rate:.3f} "
                "(<= 0.70 threshold)"
            )

        # Determine decision: BLOCKED > NEED_MORE_RESEARCH > WATCHLIST > READY_FOR_PAPER_REVIEW
        if reasons:
            decision = "BLOCKED"
        elif needs_more_research:
            decision = "NEED_MORE_RESEARCH"
        elif warnings:
            decision = "WATCHLIST"
        else:
            decision = "READY_FOR_PAPER_REVIEW"

        return PromotionGateResult(
            candidate_id=candidate_id,
            decision=decision,
            reasons=reasons,
            warnings=warnings,
            needs_more_research=needs_more_research,
            evidence=evidence,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        """Load a candidate's persisted data. Returns None if not found."""
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
