"""Research scorecard for evaluating strategy candidates.

Takes backtest results from a StrategyCandidate and computes a structured
ResearchScorecard with standard risk/return metrics and overfit assessment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class ResearchScorecard:
    """Standardized evaluation scorecard for a strategy candidate."""

    candidate_id: str
    cagr: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    turnover: float = 0.0
    avg_exposure: float = 0.0
    trade_count: int = 0
    avg_holding_period: float = 0.0
    cost_sensitivity: float = 0.0
    walk_forward_pass_rate: float = 0.0
    oos_degradation: float = 0.0
    robustness_score: float = 0.0
    overfit_risk: str = "UNKNOWN"
    overfit_risk_score: float = 0.0  # 0.0-1.0, from OverfitDetector
    stability_score: float = 0.0     # from walk-forward pass rate and OOS degradation


class ResearchScorecardBuilder:
    """Build scorecards from candidate backtest metrics.

    Scorecards are persisted as JSON under data/research/scorecards/.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.scorecards_dir = self.data_root / "research" / "scorecards"
        self.scorecards_dir.mkdir(parents=True, exist_ok=True)

    def build(self, candidate_id: str) -> ResearchScorecard:
        """Build a scorecard from the candidate's stored metrics.

        Loads the candidate JSON from data/research/candidates/<candidate_id>/candidate.json
        and maps the metrics onto a ResearchScorecard.

        Args:
            candidate_id: The candidate to evaluate.

        Returns:
            A fully populated ResearchScorecard.

        Raises:
            ValueError: If the candidate is not found.
        """
        candidate_path = (
            self.data_root / "research" / "candidates" / candidate_id / "candidate.json"
        )
        if not candidate_path.exists():
            raise ValueError(f"Candidate {candidate_id} not found")

        candidate_data = json.loads(candidate_path.read_text(encoding="utf-8"))
        metrics = candidate_data.get("metrics", {})

        scorecard = ResearchScorecard(
            candidate_id=candidate_id,
            cagr=metrics.get("cagr", metrics.get("total_return_pct", 0.0)),
            sharpe=metrics.get("sharpe_ratio", 0.0),
            sortino=metrics.get("sortino_ratio", 0.0),
            calmar=metrics.get("calmar_ratio", 0.0),
            max_drawdown=abs(metrics.get("max_drawdown_pct", 0.0)),
            win_rate=metrics.get("win_rate", 0.0),
            profit_factor=metrics.get("profit_factor", 0.0),
            turnover=metrics.get("turnover", 0.0),
            avg_exposure=metrics.get("avg_exposure", 0.0),
            trade_count=int(metrics.get("trade_count", 0)),
            avg_holding_period=metrics.get("avg_holding_period", 0.0),
            cost_sensitivity=self._compute_cost_sensitivity(metrics),
            walk_forward_pass_rate=metrics.get("walk_forward_pass_rate", 0.0),
            oos_degradation=metrics.get("oos_degradation", 0.0),
            robustness_score=0.0,  # computed below
            overfit_risk="UNKNOWN",
            overfit_risk_score=0.0,
            stability_score=0.0,
        )

        # Enrich with OverfitDetector and weighted robust scoring
        overfit_risk = self._assess_overfit_risk(candidate_id)
        scorecard.overfit_risk = overfit_risk
        scorecard.overfit_risk_score = self._compute_overfit_risk_score(metrics)
        scorecard.stability_score = self._compute_stability_score(
            scorecard.walk_forward_pass_rate, scorecard.oos_degradation
        )
        scorecard.robustness_score = self._compute_robust_score(scorecard)

        self._save(scorecard)
        return scorecard

    def rank_candidates(
        self, candidates: list[str]
    ) -> list[tuple[str, float]]:
        """Rank candidates by robustness score, descending.

        Args:
            candidates: List of candidate IDs to rank.

        Returns:
            List of (candidate_id, robustness_score) tuples sorted descending.
        """
        scored: list[tuple[str, float]] = []
        for cid in candidates:
            try:
                sc = self.build(cid)
                scored.append((cid, sc.robustness_score))
            except (ValueError, FileNotFoundError, json.JSONDecodeError):
                continue
        return sorted(scored, key=lambda x: x[1], reverse=True)

    def to_markdown(self, scorecard: ResearchScorecard) -> str:
        """Render the scorecard as a markdown table."""
        lines = [
            f"## Research Scorecard: {scorecard.candidate_id}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| CAGR | {scorecard.cagr:.2%} |",
            f"| Sharpe | {scorecard.sharpe:.2f} |",
            f"| Sortino | {scorecard.sortino:.2f} |",
            f"| Calmar | {scorecard.calmar:.2f} |",
            f"| Max Drawdown | {scorecard.max_drawdown:.2%} |",
            f"| Win Rate | {scorecard.win_rate:.2%} |",
            f"| Profit Factor | {scorecard.profit_factor:.2f} |",
            f"| Turnover | {scorecard.turnover:.2%} |",
            f"| Trade Count | {scorecard.trade_count} |",
            f"| Avg Holding Period | {scorecard.avg_holding_period:.1f} days |",
            f"| Cost Sensitivity | {scorecard.cost_sensitivity:.4f} |",
            f"| Walk-Forward Pass Rate | {scorecard.walk_forward_pass_rate:.2%} |",
            f"| OOS Degradation | {scorecard.oos_degradation:.2%} |",
            f"| Robustness Score | {scorecard.robustness_score:.2f} |",
            f"| Overfit Risk | {scorecard.overfit_risk} |",
            f"| Overfit Risk Score | {scorecard.overfit_risk_score:.4f} |",
            f"| Stability Score | {scorecard.stability_score:.4f} |",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Heuristic helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_cost_sensitivity(metrics: dict[str, Any]) -> float:
        """Placeholder: cost sensitivity from metrics."""
        return float(metrics.get("cost_sensitivity", 0.0))

    def _assess_overfit_risk(self, candidate_id: str) -> str:
        """Use OverfitDetector for real overfit assessment.

        Args:
            candidate_id: The candidate to check.

        Returns:
            One of HIGH | MODERATE | LOW | NEGATIVE.
        """
        from quant_us.research.automation.overfit import OverfitDetector

        detector = OverfitDetector(data_root=str(self.data_root))
        report = detector.check(candidate_id)
        if report.is_overfit:
            return "HIGH"
        if report.degradation_pct > 0.20:
            return "MODERATE"
        sharpe = report.in_sample_sharpe or report.out_of_sample_sharpe
        if sharpe <= 0:
            return "NEGATIVE"
        return "LOW"

    @staticmethod
    def _compute_overfit_risk_score(metrics: dict[str, Any]) -> float:
        """Compute a continuous overfit risk score 0.0-1.0 from metrics.

        Evaluates multiple overfit signals:
        - OOS degradation
        - Parameter sensitivity
        - Single-year concentration
        - Single-symbol concentration
        - Cost sensitivity
        - Low trade count

        Returns:
            Float 0.0 (no risk) to 1.0 (high risk).
        """
        triggers = 0
        checks = 6

        degradation = float(metrics.get("oos_degradation", 0.0))
        if degradation > 0.40:
            triggers += 1

        param_sens = float(metrics.get("param_sensitivity", 0.0))
        if param_sens > 0.5:
            triggers += 1

        trade_count = int(metrics.get("trade_count", 0))
        if 0 < trade_count < 10:
            triggers += 1

        year_conc = float(metrics.get("single_year_concentration", 0.0))
        if year_conc > 0.50:
            triggers += 1

        sym_conc = float(metrics.get("single_symbol_concentration", 0.0))
        if sym_conc > 0.60:
            triggers += 1

        cost_sens = float(metrics.get("cost_sensitivity", 0.0))
        if cost_sens > 0.5:
            triggers += 1

        return round(triggers / checks, 4)

    @staticmethod
    def _compute_stability_score(
        walk_forward_pass_rate: float, oos_degradation: float
    ) -> float:
        """Compute stability score 0.0-1.0 from walk-forward pass rate and OOS degradation.

        Args:
            walk_forward_pass_rate: Pass rate (0.0-1.0).
            oos_degradation: Out-of-sample degradation (0.0+).

        Returns:
            Float 0.0 (unstable) to 1.0 (highly stable).
        """
        wf_score = walk_forward_pass_rate  # already 0-1
        deg_score = max(1.0 - oos_degradation, 0.0)
        return round(0.6 * wf_score + 0.4 * deg_score, 4)

    def _compute_robust_score(self, scorecard: ResearchScorecard) -> float:
        """Compute weighted robust score.

        Weights:
            return   0.20
            risk     0.25
            stability 0.25
            cost     0.15
            robustness 0.15

        Each component is normalized to 0.0-1.0.

        Args:
            scorecard: The fully populated scorecard.

        Returns:
            Float 0.0-1.0 weighted score.
        """
        # Normalize CAGR: 0-1 based on 0-50% range
        ret_score = min(scorecard.cagr / 0.50, 1.0) if scorecard.cagr > 0 else 0.0

        # Risk: 1 - normalized max_drawdown (0-50% range)
        risk_score = max(1.0 - min(scorecard.max_drawdown / 0.50, 1.0), 0.0)

        # Stability: from walk-forward pass rate and OOS degradation
        stab_score = scorecard.stability_score

        # Cost: 1 - normalized cost_sensitivity
        cost_score = max(1.0 - min(scorecard.cost_sensitivity / 0.5, 1.0), 0.0)

        # Robustness: 1 - overfit_risk_score (inverted)
        rob_score = 1.0 - scorecard.overfit_risk_score

        return round(
            0.20 * ret_score
            + 0.25 * risk_score
            + 0.25 * stab_score
            + 0.15 * cost_score
            + 0.15 * rob_score,
            4,
        )

    def _save(self, scorecard: ResearchScorecard) -> None:
        path = self.scorecards_dir / f"{scorecard.candidate_id}.json"
        path.write_text(
            json.dumps(asdict(scorecard), indent=2, default=str), encoding="utf-8"
        )
