"""Markdown report builder for regime analysis.

Produces human-readable reports from regime detection and backtest results.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_us.regime.backtest import RegimeBacktestResult
from quant_us.regime.detector import MarketRegimeDetector


class RegimeReportBuilder:
    """Build human-readable (Markdown) regime reports.

    Parameters
    ----------
    data_root : str
        Data root directory passed to the detector.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root

    def build_timeline(
        self,
        symbol: str = "SPY",
        start: str = "",
        end: str = "",
    ) -> str:
        """Produce a Markdown timeline of regime changes for *symbol*.

        Parameters
        ----------
        symbol : str
            Ticker symbol.
        start : str, optional
            ISO start date.
        end : str, optional
            ISO end date.

        Returns
        -------
        str
            Markdown report.
        """
        detector = MarketRegimeDetector(self.data_root)
        regime_df = detector.detect_all(symbol)
        if regime_df.empty:
            return f"# Regime Timeline: {symbol}\n\nNo regime data available.\n"

        if start:
            regime_df = regime_df[regime_df["date"] >= start]
        if end:
            regime_df = regime_df[regime_df["date"] <= end]

        # Build transition summary
        regimes = regime_df["regime"].tolist()
        dates = regime_df["date"].tolist()

        lines: list[str] = [
            f"# Regime Timeline: {symbol}",
            f"**Period:** {dates[0]} to {dates[-1]}",
            f"**Total trading days:** {len(dates)}",
            "",
            "## Regime Summary",
            "",
        ]

        # Frequency table
        freq = regime_df["regime"].value_counts()
        lines.append("| Regime | Days | % of Period |")
        lines.append("|--------|-----:|------------:|")
        for regime, count in freq.items():
            pct = count / len(dates) * 100.0
            lines.append(f"| {regime} | {count} | {pct:.1f}% |")

        lines.append("")
        lines.append("## Regime Transitions")
        lines.append("")

        # Show regime runs
        transitions: list[str] = []
        current = regimes[0]
        run_start = dates[0]
        for i in range(1, len(regimes)):
            if regimes[i] != current:
                transitions.append(
                    f"- **{dates[i]}**: {current} ({run_start} to {dates[i-1]}) "
                    f"→ **{regimes[i]}**"
                )
                current = regimes[i]
                run_start = dates[i]

        if not transitions:
            lines.append(f"No regime changes — stayed in **{current}** throughout.")
        else:
            lines.extend(transitions)
            lines.append("")
            lines.append(f"Total transitions: **{len(transitions)}**")

        lines.append("")
        latest = regime_df.iloc[-1]
        lines.append("## Current Regime")
        lines.append("")
        lines.append(
            f"- **{latest['regime']}** "
            f"(confidence: {latest['confidence']:.2f}, "
            f"date: {latest['date']})"
        )

        return "\n".join(lines)

    def build_strategy_report(
        self,
        strategy_id: str,
        regime_result: RegimeBacktestResult,
    ) -> str:
        """Build a Markdown report for strategy performance by regime.

        Parameters
        ----------
        strategy_id : str
            Strategy identifier.
        regime_result : RegimeBacktestResult
            Result from :class:`RegimeAwareBacktest`.

        Returns
        -------
        str
            Markdown report.
        """
        lines: list[str] = [
            f"# Regime-Aware Strategy Report: {strategy_id}",
            f"**Symbol:** {regime_result.symbol}",
            f"**Regime transitions observed:** {regime_result.regime_transitions}",
            "",
            "## Performance by Regime",
            "",
            "| Regime | CAGR (%) | Sharpe | Max DD (%) | Trades |",
            "|--------|--------:|-------:|----------:|------:|",
        ]

        for regime, perf in sorted(regime_result.regime_performance.items()):
            lines.append(
                f"| {regime} | {perf.get('cagr_pct', 0):.2f} | "
                f"{perf.get('sharpe_ratio', 0):.2f} | "
                f"{perf.get('max_drawdown_pct', 0):.2f} | "
                f"{perf.get('trade_count', 0)} |"
            )

        lines.append("")
        lines.append("## Regime Rankings")
        lines.append("")

        # Best and worst
        if regime_result.best_regime:
            lines.append(f"- **Best regime:** {regime_result.best_regime}")
        if regime_result.worst_regime:
            lines.append(f"- **Worst regime:** {regime_result.worst_regime}")

        lines.append("")
        lines.append("## Recommendations")
        lines.append("")

        if regime_result.recommended_filter:
            lines.append("**Avoid trading in these regimes:**")
            for r in regime_result.recommended_filter:
                lines.append(f"- {r}")
        else:
            lines.append("No regime filters recommended.")

        return "\n".join(lines)

    def recommend_filter(
        self,
        regime_result: RegimeBacktestResult,
    ) -> list[str]:
        """Recommend which regimes to avoid based on negative returns or deep drawdown.

        A regime is flagged for filtering if:
        - CAGR is negative, OR
        - Max drawdown exceeds -15%.

        Parameters
        ----------
        regime_result : RegimeBacktestResult
            Result from :class:`RegimeAwareBacktest`.

        Returns
        -------
        list[str]
            Regime labels to avoid.
        """
        avoid: list[str] = []
        for regime, perf in regime_result.regime_performance.items():
            cagr = perf.get("cagr_pct", 0.0)
            max_dd = perf.get("max_drawdown_pct", 0.0)
            if cagr < 0 or max_dd < -15.0:
                avoid.append(regime)
        return sorted(set(avoid))
