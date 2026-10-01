"""Factor report generation — markdown summaries with IC, quantile, and decay.

Usage:
    from quant_us.factors.evaluation import FactorEvaluator
    from quant_us.factors.report import FactorReportBuilder

    evaluator = FactorEvaluator()
    result = evaluator.evaluate("momentum_60d", symbols=["SPY","QQQ"],
                                start="2020-01-01", end="2025-12-31")
    builder = FactorReportBuilder()
    md = builder.build_report("momentum_60d", result)
    print(md)
"""

from __future__ import annotations

from datetime import datetime, timezone

from quant_us.factors.evaluation import FactorEvaluationResult


class FactorReportBuilder:
    """Generate human-readable factor evaluation reports in markdown."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_report(
        self,
        factor_id: str,
        eval_result: FactorEvaluationResult,
    ) -> str:
        """Generate a full markdown factor report.

        Includes IC summary table, quantile performance, IC decay analysis,
        key metrics, and a recommendation.
        """
        lines: list[str] = []
        lines.append(f"# Factor Report: {factor_id}")
        lines.append("")
        lines.append(f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # -- Summary table --
        lines.append("## IC Summary")
        lines.append("")
        lines.append(self._summary_table(eval_result))
        lines.append("")

        # -- Quantile returns --
        lines.append("## Quantile Performance (forward return by factor quantile)")
        lines.append("")
        lines.append(self._quantile_table(eval_result))
        lines.append("")

        # -- Key metrics --
        lines.append("## Key Metrics")
        lines.append("")
        lines.append(self._metrics_table(eval_result))
        lines.append("")

        # -- Decay analysis --
        lines.append("## IC Decay")
        lines.append("")
        lines.append(f"Decay half-life: **{eval_result.decay_half_life:.1f} days**")
        lines.append("")
        lines.append(
            "IC decay measures how quickly the predictive power of the factor "
            "diminishes over time. A longer half-life indicates a more persistent signal."
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # -- Recommendation --
        lines.append("## Recommendation")
        lines.append("")
        lines.append(f"**{self.recommend(eval_result)}**")
        lines.append("")

        return "\n".join(lines)

    def recommend(self, eval_result: FactorEvaluationResult) -> str:
        """Classify factor quality.

        Returns one of:
            - ``usable``: |IC| > 0.03, ICIR > 0.5, monotonicity > 0.7, decay_half_life > 10
            - ``unstable``: passes some but not all thresholds
            - ``redundant``: low IC, low ICIR, weak quantile spread
            - ``rejected``: negative ICIR or counter-monotonic
        """
        score = 0
        reasons: list[str] = []

        # IC magnitude
        if abs(eval_result.ic_mean) > 0.03:
            score += 1
        else:
            reasons.append(f"low |IC| ({eval_result.ic_mean:.4f})")

        # ICIR
        if eval_result.icir > 0.5:
            score += 1
        else:
            reasons.append(f"low ICIR ({eval_result.icir:.2f})")

        # Monotonicity
        if eval_result.monotonicity > 0.7:
            score += 1
        else:
            reasons.append(f"weak monotonicity ({eval_result.monotonicity:.2f})")

        # Decay half-life
        if eval_result.decay_half_life > 10:
            score += 1
        else:
            reasons.append(f"fast decay ({eval_result.decay_half_life:.1f}d)")

        # Hit rate
        if eval_result.hit_rate > 0.55:
            score += 1
        else:
            reasons.append(f"low hit rate ({eval_result.hit_rate:.1%})")

        if score >= 4:
            verdict = "usable"
        elif score >= 2:
            verdict = "unstable"
        elif eval_result.icir < 0 or eval_result.monotonicity < -0.3:
            verdict = "rejected"
            reasons.append("negative ICIR or counter-monotonic")
        else:
            verdict = "redundant"

        if reasons:
            return f"{verdict} — {'; '.join(reasons)}"
        return verdict

    # ------------------------------------------------------------------
    # Internal formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summary_table(result: FactorEvaluationResult) -> str:
        headers = ["Metric", "Value"]
        rows = [
            ("Observations", str(result.n_observations)),
            ("Number of Dates", str(result.n_dates)),
            ("Pearson IC (mean)", f"{result.ic_mean:.4f}"),
            ("Pearson IC (std)", f"{result.ic_std:.4f}"),
            ("ICIR", f"{result.icir:.2f}"),
            ("Rank IC (mean)", f"{result.rank_ic_mean:.4f}"),
            ("Rank IC (std)", f"{result.rank_ic_std:.4f}"),
            ("Rank ICIR", f"{result.rank_icir:.2f}"),
            ("Hit Rate", f"{result.hit_rate:.1%}"),
            ("Monotonicity", f"{result.monotonicity:.2f}"),
            ("Long/Short Spread", f"{result.long_short_spread:.4f}"),
            ("Turnover", f"{result.turnover:.2f}"),
            ("Decay Half-Life", f"{result.decay_half_life:.1f}d"),
        ]
        col_widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(2)]
        sep = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |"
        div = "|-" + "-|-".join("-" * w for w in col_widths) + "-|"
        lines = [sep, div]
        for row in rows:
            lines.append("| " + " | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)) + " |")
        return "\n".join(lines)

    @staticmethod
    def _quantile_table(result: FactorEvaluationResult) -> str:
        if not result.quantile_returns:
            return "*No quantile data available.*"

        headers = ["Quantile", "Avg Forward Return"]
        rows = [
            (f"Q{q}", f"{ret:.4f}")
            for q, ret in sorted(result.quantile_returns.items())
        ]
        col_widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(2)]
        sep = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |"
        div = "|-" + "-|-".join("-" * w for w in col_widths) + "-|"
        lines = [sep, div]
        for row in rows:
            lines.append("| " + " | ".join(str(v).ljust(w) for v, w in zip(row, col_widths)) + " |")
        return "\n".join(lines)

    @staticmethod
    def _metrics_table(result: FactorEvaluationResult) -> str:
        lines = [
            f"- **Hit Rate**: {result.hit_rate:.1%} — fraction of days with positive IC",
            f"- **Monotonicity**: {result.monotonicity:.2f} — Spearman correlation between "
            f"quantile rank and forward return",
            f"- **Long/Short Spread**: {result.long_short_spread:.4f} — return difference "
            f"between best and worst quantile",
            f"- **ICIR (Information Ratio)**: {result.icir:.2f} — IC mean / IC std; "
            f"measures consistency of predictive power",
            f"- **Decay Half-Life**: {result.decay_half_life:.1f} days — how quickly IC "
            f"drops to half its original value",
        ]
        return "\n".join(lines)
