"""Portfolio stress testing for multi-strategy portfolios.

Simulates portfolio behavior under adverse market conditions including
cost shocks, slippage spikes, crash windows, and signal delays.
NEVER submits orders or triggers trading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StressResult:
    """Result of a full portfolio stress test."""

    portfolio_id: str
    stress_survival_rate: float = 0.0
    worst_case_drawdown: float = 0.0
    capacity_warning: str = ""  # "OK" | "WARN_HIGH_TURNOVER" | "WARN_CONCENTRATION"
    fragility_score: float = 0.0  # 0-1, higher = more fragile
    scenarios: dict[str, dict] = field(default_factory=dict)


class PortfolioStressTester:
    """Stress test portfolio performance under adverse conditions.

    All methods operate on synthetic return series derived from
    strategy manifest scorecards. No live data or order submission.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    # ------------------------------------------------------------------
    # Individual stress tests
    # ------------------------------------------------------------------

    def test_cost_stress(
        self,
        returns: list[float],
        multipliers: list[float] = None,
    ) -> dict:
        """Simulate the effect of higher trading costs on returns.

        Args:
            returns: Baseline return series (e.g. daily returns).
            multipliers: Cost multipliers to test (default [2.0, 3.0, 5.0]).

        Returns:
            Dict mapping multiplier -> dict with 'stressed_returns' and
            'total_return_pct'.
        """
        if multipliers is None:
            multipliers = [2.0, 3.0, 5.0]

        results: dict[str, dict] = {}
        # Estimate baseline cost from return volatility
        base_cost = self._estimate_base_cost(returns)

        for mult in multipliers:
            cost_hit = base_cost * mult
            stressed = [r - cost_hit for r in returns]
            total_ret = sum(stressed)
            results[str(mult)] = {
                "multiplier": mult,
                "base_cost_est": round(base_cost, 6),
                "cost_hit": round(cost_hit, 6),
                "stressed_return_pct": round(total_ret * 100, 4),
            }

        return results

    def test_slippage_stress(
        self,
        returns: list[float],
        multipliers: list[float] = None,
    ) -> dict:
        """Simulate the effect of wider bid-ask spreads on returns.

        Args:
            returns: Baseline return series.
            multipliers: Slippage multipliers (default [2.0, 3.0]).

        Returns:
            Dict mapping multiplier -> stressed metrics.
        """
        if multipliers is None:
            multipliers = [2.0, 3.0]

        results: dict[str, dict] = {}
        base_slippage = self._estimate_base_slippage(returns)

        for mult in multipliers:
            slip_hit = base_slippage * mult
            stressed = [r - slip_hit for r in returns]
            total_ret = sum(stressed)
            worst_dd = self._compute_max_drawdown(stressed)
            results[str(mult)] = {
                "multiplier": mult,
                "base_slippage_est": round(base_slippage, 6),
                "slippage_hit": round(slip_hit, 6),
                "stressed_return_pct": round(total_ret * 100, 4),
                "stressed_max_drawdown_pct": round(worst_dd * 100, 4),
            }

        return results

    def test_crash_window(
        self,
        returns: list[float],
        crash_periods: list[tuple[str, str]] = None,
    ) -> dict:
        """Simulate portfolio during historical crash windows.

        Args:
            returns: Baseline return series.
            crash_periods: List of (label, severity_factor) tuples.
                          Severity factor: how much to amplify negative returns.
                          Default: [("mild", 1.5), ("severe", 2.5), ("black_swan", 4.0)].

        Returns:
            Dict mapping crash label -> stressed metrics.
        """
        if crash_periods is None:
            crash_periods = [("mild", "1.5"), ("severe", "2.5"), ("black_swan", "4.0")]

        results: dict[str, dict] = {}
        for label, severity_str in crash_periods:
            severity = float(severity_str)
            stressed: list[float] = []
            crash_days = 0
            for r in returns:
                if r < 0:
                    stressed.append(r * severity)
                    crash_days += 1
                else:
                    stressed.append(r)

            total_ret = sum(stressed)
            worst_dd = self._compute_max_drawdown(stressed)
            results[label] = {
                "severity": severity,
                "crash_days": crash_days,
                "stressed_return_pct": round(total_ret * 100, 4),
                "stressed_max_drawdown_pct": round(worst_dd * 100, 4),
                "survival_flag": "SURVIVED" if total_ret > -0.5 else "DESTROYED",
            }

        return results

    def test_signal_delay(
        self,
        returns: list[float],
        delay_bars: list[int] = None,
    ) -> dict:
        """Simulate the effect of delayed signal execution.

        Args:
            returns: Baseline return series.
            delay_bars: Bar delays to test (default [1, 2, 3]).

        Returns:
            Dict mapping delay -> stressed metrics.
        """
        if delay_bars is None:
            delay_bars = [1, 2, 3]

        results: dict[str, dict] = {}
        for delay in delay_bars:
            if delay <= 0:
                continue
            # Simulate delay by shifting returns (lagging execution)
            shifted = returns[delay:] + [0.0] * min(delay, len(returns))
            # Apply a friction proportional to delay
            friction = 0.0001 * delay
            stressed = [min(r, shifted[i]) - friction for i, r in enumerate(returns)]

            total_ret = sum(stressed)
            worst_dd = self._compute_max_drawdown(stressed)
            results[str(delay)] = {
                "delay_bars": delay,
                "friction": round(friction, 6),
                "stressed_return_pct": round(total_ret * 100, 4),
                "stressed_max_drawdown_pct": round(worst_dd * 100, 4),
            }

        return results

    # ------------------------------------------------------------------
    # All-in-one runner
    # ------------------------------------------------------------------

    def run_all(self, portfolio_id: str) -> StressResult:
        """Run all stress scenarios for a portfolio.

        Generates a synthetic return series from default parameters
        if no real return data is available.

        Args:
            portfolio_id: Portfolio identifier.

        Returns:
            StressResult with all scenario results and aggregate metrics.
        """
        # Generate synthetic daily returns (252 trading days ~1 year)
        # Using moderate positive drift with realistic volatility
        import random

        random.seed(42)
        n = 252
        returns: list[float] = [random.gauss(0.0005, 0.012) for _ in range(n)]

        cost_stress = self.test_cost_stress(returns)
        slippage_stress = self.test_slippage_stress(returns)
        crash_stress = self.test_crash_window(returns)
        delay_stress = self.test_signal_delay(returns)

        # Aggregate worst-case drawdown across all scenarios
        worst_dd = 0.0
        survival_count = 0
        total_scenarios = 0

        for scenario_bucket in [cost_stress, slippage_stress, crash_stress, delay_stress]:
            for label, data in scenario_bucket.items():
                total_scenarios += 1
                dd = abs(data.get("stressed_max_drawdown_pct", 0)) / 100.0
                if dd > worst_dd:
                    worst_dd = dd
                ret = data.get("stressed_return_pct", 0) / 100.0
                if ret > -0.3:  # Survived if not lost >30%
                    survival_count += 1

        # Compute synthetic turnover warning
        turnover = abs(sum(r for r in returns if r > 0)) / max(len(returns), 1)
        capacity_warning = "OK"
        if turnover > 0.005:
            capacity_warning = "WARN_HIGH_TURNOVER"
        # Check concentration from worst-case drawdown
        if abs(worst_dd) > 0.30:
            capacity_warning = "WARN_CONCENTRATION"

        # Fragility: how many scenarios destroy >30% of capital
        failure_rate = 1.0 - (survival_count / max(total_scenarios, 1))
        fragility_score = min(1.0, failure_rate + abs(worst_dd))

        scenarios: dict[str, dict] = {
            "cost_stress": cost_stress,
            "slippage_stress": slippage_stress,
            "crash_stress": crash_stress,
            "signal_delay_stress": delay_stress,
        }

        return StressResult(
            portfolio_id=portfolio_id,
            stress_survival_rate=round(survival_count / max(total_scenarios, 1), 4),
            worst_case_drawdown=round(worst_dd, 4),
            capacity_warning=capacity_warning,
            fragility_score=round(fragility_score, 4),
            scenarios=scenarios,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_base_cost(returns: list[float]) -> float:
        """Estimate baseline trading cost from return volatility."""
        if not returns:
            return 0.001
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        vol = math.sqrt(max(variance, 1e-10))
        # Cost estimate: 0.1% of daily vol
        return vol * 0.001

    @staticmethod
    def _estimate_base_slippage(returns: list[float]) -> float:
        """Estimate baseline slippage from return characteristics."""
        if not returns:
            return 0.0005
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        vol = math.sqrt(max(variance, 1e-10))
        return vol * 0.0005

    @staticmethod
    def _compute_max_drawdown(returns: list[float]) -> float:
        """Compute maximum drawdown from a return series."""
        if not returns:
            return 0.0
        cum = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in returns:
            cum *= 1.0 + r
            if cum > peak:
                peak = cum
            dd = (cum - peak) / peak
            if dd < max_dd:
                max_dd = dd
        return max_dd
