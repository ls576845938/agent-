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
            robustness_score=self._compute_robustness(metrics),
            overfit_risk=self._assess_overfit_risk(metrics),
        )

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

    @staticmethod
    def _compute_robustness(metrics: dict[str, Any]) -> float:
        """Compute a simple robustness score from Sharpe and drawdown."""
        sharpe = float(metrics.get("sharpe_ratio", 0.0))
        dd = abs(float(metrics.get("max_drawdown_pct", 0.0)))
        if dd > 0:
            return round(sharpe / (dd * 10), 4)
        return round(sharpe, 4)

    @staticmethod
    def _assess_overfit_risk(metrics: dict[str, Any]) -> str:
        """Heuristic overfit risk assessment based on Sharpe ratio.

        Very high Sharpe ratios often indicate overfitting in research.
        """
        sharpe = float(metrics.get("sharpe_ratio", 0.0))
        if sharpe > 3.0:
            return "HIGH"
        elif sharpe > 2.0:
            return "MODERATE"
        elif sharpe <= 0.0:
            return "NEGATIVE"
        return "LOW"

    def _save(self, scorecard: ResearchScorecard) -> None:
        path = self.scorecards_dir / f"{scorecard.candidate_id}.json"
        path.write_text(
            json.dumps(asdict(scorecard), indent=2, default=str), encoding="utf-8"
        )
