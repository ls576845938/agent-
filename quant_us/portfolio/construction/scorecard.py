from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PortfolioScorecard:
    """Aggregated performance and risk summary for a portfolio."""
    portfolio_id: str
    cagr: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    strategy_contributions: dict[str, float] = field(default_factory=dict)
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    turnover_pct: float = 0.0
    capital_efficiency: float = 0.0
    diversification_ratio: float = 1.0
    marginal_risk_contributions: dict[str, float] = field(default_factory=dict)


class PortfolioScorecardBuilder:
    """Build and render portfolio scorecards.

    Scorecards are diagnostic summaries — they do not submit orders or
    interact with any broker.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root

    def build(
        self,
        portfolio_id: str,
        strategy_scorecards: list[dict[str, Any]] | None = None,
        portfolio_weights: dict[str, float] | None = None,
    ) -> PortfolioScorecard:
        """Build a portfolio scorecard from strategy-level data.

        Parameters
        ----------
        portfolio_id : str
        strategy_scorecards : list[dict] or None
            Each dict should contain: id, cagr, sharpe, max_drawdown, volatility.
        portfolio_weights : dict[str, float] or None
            Current strategy_id -> weight mapping.

        Returns
        -------
        PortfolioScorecard
        """
        strategy_scorecards = strategy_scorecards or []
        portfolio_weights = portfolio_weights or {}

        if not strategy_scorecards or not portfolio_weights:
            return PortfolioScorecard(portfolio_id=portfolio_id)

        # Weighted portfolio metrics
        total_weight = sum(portfolio_weights.values())
        if total_weight <= 0:
            return PortfolioScorecard(portfolio_id=portfolio_id)

        norm_weights = {k: v / total_weight for k, v in portfolio_weights.items()}

        cagr = 0.0
        sharpe_num = 0.0
        max_dd = 0.0
        contributions: dict[str, float] = {}
        marginal_risk: dict[str, float] = {}
        vols: list[float] = []

        for sc in strategy_scorecards:
            sid = sc["id"]
            w = norm_weights.get(sid, 0.0)
            cagr += w * sc.get("cagr", 0.0)
            sharpe_num += w * sc.get("sharpe", 0.0)
            dd = sc.get("max_drawdown", 0.0)
            if dd > max_dd:
                max_dd = dd
            contributions[sid] = w * sc.get("cagr", 0.0)
            vol = sc.get("volatility", 0.0)
            vols.append(vol)
            marginal_risk[sid] = w * vol

        # Capital efficiency: return per unit of max drawdown
        capital_efficiency = cagr / max(max_dd, 0.01) if max_dd > 0.01 else 0.0

        # Simplified diversification ratio
        avg_vol = sum(vols) / max(len(vols), 1) if vols else 0.0
        div_ratio = 1.0
        if avg_vol > 0:
            portfolio_vol = (
                sum(
                    norm_weights.get(sc["id"], 0.0) * sc.get("volatility", 0.0)
                    for sc in strategy_scorecards
                )
            )
            div_ratio = avg_vol / max(portfolio_vol, 1e-10)

        return PortfolioScorecard(
            portfolio_id=portfolio_id,
            cagr=cagr,
            sharpe=sharpe_num,
            max_drawdown=max_dd,
            strategy_contributions=contributions,
            correlation_matrix={},
            turnover_pct=0.0,
            capital_efficiency=capital_efficiency,
            diversification_ratio=div_ratio,
            marginal_risk_contributions=marginal_risk,
        )

    @staticmethod
    def to_markdown(scorecard: PortfolioScorecard) -> str:
        """Render a PortfolioScorecard as a markdown report."""
        lines: list[str] = []
        lines.append(f"## Portfolio Scorecard: {scorecard.portfolio_id}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| CAGR | {scorecard.cagr:.2%} |")
        lines.append(f"| Sharpe | {scorecard.sharpe:.3f} |")
        lines.append(f"| Max Drawdown | {scorecard.max_drawdown:.2%} |")
        lines.append(f"| Turnover | {scorecard.turnover_pct:.1%} |")
        lines.append(f"| Capital Efficiency | {scorecard.capital_efficiency:.3f} |")
        lines.append(f"| Diversification Ratio | {scorecard.diversification_ratio:.3f} |")
        lines.append("")

        if scorecard.strategy_contributions:
            lines.append("### Strategy Contributions")
            lines.append("")
            lines.append("| Strategy | Contribution | Marginal Risk |")
            lines.append("|----------|-------------|---------------|")
            for sid in sorted(scorecard.strategy_contributions):
                contrib = scorecard.strategy_contributions.get(sid, 0.0)
                mrc = scorecard.marginal_risk_contributions.get(sid, 0.0)
                lines.append(f"| {sid} | {contrib:.4f} | {mrc:.4f} |")

        return "\n".join(lines) + "\n"
