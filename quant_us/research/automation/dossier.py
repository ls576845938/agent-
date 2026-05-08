"""Research dossier generation for strategy candidates.

Generates complete markdown dossiers covering:
- Strategy description, params
- Backtest results
- Walk-forward results
- Factor exposure
- Regime behavior
- Cost stress
- Failure cases
- Recommendation
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_us.research.automation.overfit import OverfitDetector
from quant_us.research.lab.scorecard import ResearchScorecardBuilder


# Recommendation levels (ordered from worst to best)
RECOMMENDATION_LEVELS = [
    "REJECT",
    "RESEARCH_MORE",
    "PAPER_ELIGIBLE",
    "PORTFOLIO_CANDIDATE",
]


class ResearchDossierBuilder:
    """Generates complete research dossiers for strategy candidates.

    Dossiers are markdown reports covering all aspects of a candidate's
    evaluation. The builder also provides recommendation logic.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self._scorecard_builder = ResearchScorecardBuilder(data_root=data_root)
        self._overfit_detector = OverfitDetector(data_root=data_root)

    def build(self, candidate_id: str) -> str:
        """Generate a complete research dossier as markdown.

        Args:
            candidate_id: The candidate to document.

        Returns:
            Markdown string with the full dossier.

        Raises:
            ValueError: If the candidate is not found.
        """
        candidate_data = self._load_candidate(candidate_id)
        scorecard = self._scorecard_builder.build(candidate_id)
        overfit_report = self._overfit_detector.check(candidate_id)
        recommendation = self.recommend(candidate_id)

        sections: list[str] = [
            self._header(candidate_data),
            "",
            self._strategy_section(candidate_data),
            "",
            self._params_section(candidate_data),
            "",
            self._backtest_section(scorecard),
            "",
            self._walk_forward_section(scorecard),
            "",
            self._risk_section(scorecard, overfit_report),
            "",
            self._cost_stress_section(scorecard),
            "",
            self._regime_section(candidate_data),
            "",
            self._failure_cases_section(overfit_report),
            "",
            self._recommendation_section(recommendation, overfit_report, scorecard),
            "",
        ]
        markdown = "\n".join(sections)

        # Persist the dossier
        self._save_dossier(candidate_id, markdown)

        return markdown

    def recommend(self, candidate_id: str) -> str:
        """Generate a recommendation for a candidate.

        Args:
            candidate_id: The candidate to evaluate.

        Returns:
            One of: REJECT | RESEARCH_MORE | PAPER_ELIGIBLE | PORTFOLIO_CANDIDATE
        """
        try:
            scorecard = self._scorecard_builder.build(candidate_id)
            overfit_report = self._overfit_detector.check(candidate_id)
        except (ValueError, FileNotFoundError, json.JSONDecodeError):
            return "RESEARCH_MORE"

        # Overfit → REJECT
        if overfit_report.is_overfit:
            return "REJECT"

        # Negative Sharpe → REJECT
        if scorecard.sharpe <= 0:
            return "REJECT"

        # Low Sharpe → RESEARCH_MORE
        if scorecard.sharpe < 0.5:
            return "RESEARCH_MORE"

        # Low trade count → RESEARCH_MORE (not statistically significant)
        if scorecard.trade_count < 10:
            return "RESEARCH_MORE"

        # High overfit risk → RESEARCH_MORE
        if scorecard.overfit_risk == "HIGH":
            return "RESEARCH_MORE"

        # High drawdown → RESEARCH_MORE
        if scorecard.max_drawdown > 0.30:
            return "RESEARCH_MORE"

        # Good Sharpe with reasonable risk → PAPER_ELIGIBLE
        if scorecard.sharpe >= 1.0 and scorecard.max_drawdown <= 0.20:
            return "PORTFOLIO_CANDIDATE"

        if scorecard.sharpe >= 0.5 and scorecard.max_drawdown <= 0.25:
            return "PAPER_ELIGIBLE"

        return "RESEARCH_MORE"

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    @staticmethod
    def _header(candidate_data: dict[str, Any]) -> str:
        return (
            f"# Research Dossier: {candidate_data.get('candidate_id', 'unknown')}\n"
            f"\n"
            f"**Strategy:** {candidate_data.get('strategy_id', 'unknown')}  \n"
            f"**Experiment:** {candidate_data.get('experiment_id', 'unknown')}  \n"
            f"**Created:** {candidate_data.get('created_at', 'unknown')}  \n"
            f"**Data Version:** {candidate_data.get('data_version', 'N/A')}  \n"
        )

    @staticmethod
    def _strategy_section(candidate_data: dict[str, Any]) -> str:
        strategy_id = candidate_data.get("strategy_id", "unknown")
        return (
            f"## Strategy Description\n"
            f"\n"
            f"Strategy `{strategy_id}` evaluated through the research automation pipeline.\n"
            f"\n"
            f"- **Promotion Status:** {candidate_data.get('promotion_status', 'RESEARCH_ONLY')}\n"
            f"- **Params Hash:** {candidate_data.get('params_hash', 'N/A')}\n"
        )

    @staticmethod
    def _params_section(candidate_data: dict[str, Any]) -> str:
        return (
            f"## Parameters\n"
            f"\n"
            f"```json\n"
            f"{json.dumps(candidate_data.get('metrics', {}), indent=2, default=str)[:1000]}\n"
            f"```\n"
        )

    @staticmethod
    def _backtest_section(scorecard: Any) -> str:
        return (
            f"## Backtest Results\n"
            f"\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| CAGR | {scorecard.cagr:.2%} |\n"
            f"| Sharpe | {scorecard.sharpe:.2f} |\n"
            f"| Sortino | {scorecard.sortino:.2f} |\n"
            f"| Calmar | {scorecard.calmar:.2f} |\n"
            f"| Max Drawdown | {scorecard.max_drawdown:.2%} |\n"
            f"| Win Rate | {scorecard.win_rate:.2%} |\n"
            f"| Profit Factor | {scorecard.profit_factor:.2f} |\n"
            f"| Trade Count | {scorecard.trade_count} |\n"
        )

    @staticmethod
    def _walk_forward_section(scorecard: Any) -> str:
        return (
            f"## Walk-Forward Analysis\n"
            f"\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Pass Rate | {scorecard.walk_forward_pass_rate:.2%} |\n"
            f"| OOS Degradation | {scorecard.oos_degradation:.2%} |\n"
            f"| Robustness Score | {scorecard.robustness_score:.2f} |\n"
        )

    @staticmethod
    def _risk_section(scorecard: Any, overfit_report: Any) -> str:
        return (
            f"## Risk Assessment\n"
            f"\n"
            f"| Metric | Value |\n"
            f"|--------|-------|\n"
            f"| Max Drawdown | {scorecard.max_drawdown:.2%} |\n"
            f"| Turnover | {scorecard.turnover:.2%} |\n"
            f"| Avg Exposure | {scorecard.avg_exposure:.2%} |\n"
            f"| Overfit Risk | {scorecard.overfit_risk} |\n"
            f"| Param Sensitivity | {overfit_report.param_sensitivity:.4f} |\n"
            f"| Single-Symbol Concentration | {overfit_report.single_symbol_concentration:.1%} |\n"
            f"| Single-Year Concentration | {overfit_report.single_year_concentration:.1%} |\n"
        )

    @staticmethod
    def _cost_stress_section(scorecard: Any) -> str:
        return (
            f"## Cost Stress Analysis\n"
            f"\n"
            f"Cost sensitivity: {scorecard.cost_sensitivity:.4f}\n"
            f"\n"
            f"Interpretation: Lower values indicate greater robustness to trading costs.\n"
        )

    @staticmethod
    def _regime_section(candidate_data: dict[str, Any]) -> str:
        metrics = candidate_data.get("metrics", {})
        regime_sharpes = metrics.get("regime_sharpes", {})
        if regime_sharpes:
            lines = ["## Regime Behavior\n", ""]
            lines.append("| Regime | Sharpe |\n|--------|-------|\n")
            for regime, sharpe_val in regime_sharpes.items():
                lines.append(f"| {regime} | {float(sharpe_val):.2f} |\n")
            return "".join(lines)
        return "## Regime Behavior\n\nNo regime-specific data available.\n"

    @staticmethod
    def _failure_cases_section(overfit_report: Any) -> str:
        reasons = overfit_report.reasons
        if reasons:
            lines = [
                "## Failure Cases\n",
                "",
                "The following overfit/risk concerns were identified:\n",
            ]
            for i, reason in enumerate(reasons, 1):
                lines.append(f"{i}. {reason}\n")
            return "\n".join(lines)
        return "## Failure Cases\n\nNo failure cases identified.\n"

    @staticmethod
    def _recommendation_section(
        recommendation: str,
        overfit_report: Any,
        scorecard: Any,
    ) -> str:
        return (
            f"## Recommendation\n"
            f"\n"
            f"**{recommendation}**\n"
            f"\n"
            f"### Rationale\n"
            f"\n"
            f"- Sharpe Ratio: {scorecard.sharpe:.2f}\n"
            f"- Max Drawdown: {scorecard.max_drawdown:.2%}\n"
            f"- Overfit Risk: {scorecard.overfit_risk}\n"
            f"- Overfit Flag: {overfit_report.is_overfit} ({len(overfit_report.reasons)} reason(s))\n"
            f"\n"
            f"---\n"
            f"*Generated by Research Automation Pipeline — no live promotion implied.*\n"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_candidate(self, candidate_id: str) -> dict[str, Any]:
        path = (
            self.data_root
            / "research"
            / "candidates"
            / candidate_id
            / "candidate.json"
        )
        if not path.exists():
            raise ValueError(f"Candidate {candidate_id} not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_dossier(self, candidate_id: str, markdown: str) -> None:
        dossier_dir = self.data_root / "research" / "dossiers"
        dossier_dir.mkdir(parents=True, exist_ok=True)
        path = dossier_dir / f"{candidate_id}.md"
        path.write_text(markdown, encoding="utf-8")
