"""Monte Carlo robustness simulation for strategy candidates.

Provides:
- MonteCarloRobustness: Three simulation modes (shuffle trades, bootstrap returns,
  stress scenarios) plus CVaR 95% tail risk computation.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class MonteCarloResult:
    """Aggregated result from a Monte Carlo simulation.

    Attributes:
        candidate_id: The candidate being simulated.
        n_simulations: Number of simulation runs.
        survival_rate: Fraction of simulations that did not exceed -50% peak-to-trough.
        median_return: Median total return across all simulations.
        p5_return: 5th percentile total return (worst-case).
        p95_drawdown: 95th percentile max drawdown (worst-case).
        tail_risk_score: CVaR 95% scaled to 0-1 (higher = worse).
    """

    candidate_id: str
    n_simulations: int = 500
    survival_rate: float = 0.0
    median_return: float = 0.0
    p5_return: float = 0.0
    p95_drawdown: float = 0.0
    tail_risk_score: float = 0.0  # 0-1, higher = worse


class MonteCarloRobustness:
    """Run Monte Carlo simulations to assess strategy robustness.

    All methods accept lists of returns and return a MonteCarloResult.
    Uses deterministic seed for reproducibility (default 42).
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    # ------------------------------------------------------------------
    # Public simulation methods
    # ------------------------------------------------------------------

    def shuffle_trades(
        self, trade_returns: list[float], n: int = 500
    ) -> MonteCarloResult:
        """Randomly permute trade returns to test dependence on ordering.

        Each simulation randomly shuffles the trade return sequence and
        computes the resulting equity curve.

        Args:
            trade_returns: Individual trade returns (e.g. from backtest fills).
            n: Number of simulations to run.

        Returns:
            MonteCarloResult with survival, return, drawdown, and tail risk stats.
        """
        rng = random.Random(self._seed)
        n_sim = max(n, 10)

        if not trade_returns:
            return MonteCarloResult(candidate_id="", n_simulations=n_sim)

        total_returns: list[float] = []
        max_drawdowns: list[float] = []

        for _ in range(n_sim):
            shuffled = trade_returns[:]
            rng.shuffle(shuffled)

            equity = 1.0
            peak = 1.0
            running_dd = 0.0

            for r in shuffled:
                equity *= 1.0 + r
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak
                if dd > running_dd:
                    running_dd = dd

            total_returns.append(equity - 1.0)
            max_drawdowns.append(running_dd)

        return self._build_result(
            candidate_id="",
            n_simulations=n_sim,
            total_returns=total_returns,
            max_drawdowns=max_drawdowns,
        )

    def bootstrap_returns(
        self, daily_returns: list[float], n: int = 500
    ) -> MonteCarloResult:
        """Bootstrap resample daily return series.

        Each simulation draws len(daily_returns) samples WITH replacement
        from the observed daily returns, then computes the equity curve.

        Args:
            daily_returns: Observed daily returns (decimal, not %).
            n: Number of bootstrap iterations.

        Returns:
            MonteCarloResult aggregated over all bootstrap runs.
        """
        rng = random.Random(self._seed)
        n_sim = max(n, 10)

        if not daily_returns:
            return MonteCarloResult(candidate_id="", n_simulations=n_sim)

        n_days = len(daily_returns)
        total_returns: list[float] = []
        max_drawdowns: list[float] = []

        for _ in range(n_sim):
            equity = 1.0
            peak = 1.0
            running_dd = 0.0

            for _ in range(n_days):
                r = rng.choice(daily_returns)
                equity *= 1.0 + r
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak
                if dd > running_dd:
                    running_dd = dd

            total_returns.append(equity - 1.0)
            max_drawdowns.append(running_dd)

        return self._build_result(
            candidate_id="",
            n_simulations=n_sim,
            total_returns=total_returns,
            max_drawdowns=max_drawdowns,
        )

    def stress_scenarios(
        self,
        returns: list[float],
        cost_mult: float = 1.0,
        slippage_mult: float = 1.0,
        delay_bars: int = 0,
    ) -> MonteCarloResult:
        """Apply cost/slippage/delay stress to returns and bootstrap.

        Modifies each return by increased trading costs, slippage, or
        signal delay before running the bootstrap simulation.

        Args:
            returns: List of decimal returns.
            cost_mult: Multiplier on existing costs (e.g. 3.0 = 3x costs).
            slippage_mult: Multiplier on existing slippage (e.g. 2.0 = 2x slippage).
            delay_bars: Extra bars of delay to apply (returns shifted).

        Returns:
            MonteCarloResult for the stressed scenario.
        """
        if not returns:
            return MonteCarloResult(candidate_id="")

        stressed = list(returns)

        # Apply cost stress: scale down positive returns, scale up negatives
        if cost_mult != 1.0:
            cost_penalty = (cost_mult - 1.0) * 0.001  # 10 bps per multiplier unit
            stressed = [r - cost_penalty for r in stressed]

        # Apply slippage stress: add small negative slippage drag
        if slippage_mult != 1.0:
            slippage_drag = (slippage_mult - 1.0) * 0.0005  # 5 bps per multiplier
            stressed = [r - slippage_drag for r in stressed]

        # Apply delay: shift returns by delay_bars (forward-fill with last value)
        if delay_bars > 0 and len(stressed) > delay_bars:
            stressed = stressed[delay_bars:] + stressed[-delay_bars:]

        # Bootstrap on stressed returns
        return self.bootstrap_returns(stressed, n=500)

    @staticmethod
    def compute_tail_risk(returns: list[float]) -> float:
        """Compute CVaR 95% as a 0-1 scaled tail risk score.

        CVaR 95% is the average of returns below the 5th percentile.
        The result is scaled so that CVaR <= -0.05 maps to 1.0 (worst),
        CVaR >= 0.0 maps to 0.0 (best).

        Args:
            returns: List of portfolio / simulation total returns.

        Returns:
            Float 0.0 (low risk) to 1.0 (high tail risk).
        """
        if not returns:
            return 0.0

        sorted_ret = sorted(returns)
        n = len(sorted_ret)
        cutoff = max(1, int(math.ceil(n * 0.05)))
        tail = sorted_ret[:cutoff]
        cvar = sum(tail) / len(tail)

        # Scale: CVaR of -0.05 or worse -> 1.0; CVaR of 0.0 -> 0.0
        clipped = min(0.0, cvar)
        score = max(0.0, min(1.0, abs(clipped) / 0.05))
        return round(score, 4)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        candidate_id: str,
        n_simulations: int,
        total_returns: list[float],
        max_drawdowns: list[float],
    ) -> MonteCarloResult:
        """Build a MonteCarloResult from simulation outputs."""
        sorted_ret = sorted(total_returns)
        n = len(sorted_ret)

        # Survival: return > -50% (did not lose more than half)
        survival_count = sum(1 for r in sorted_ret if r > -0.50)
        survival_rate = survival_count / n

        # Median (50th percentile)
        median_idx = n // 2
        median_return = sorted_ret[median_idx] if n > 0 else 0.0

        # 5th percentile
        p5_idx = max(0, int(n * 0.05) - 1)
        p5_return = sorted_ret[p5_idx] if n > 0 else 0.0

        # 95th percentile drawdown
        sorted_dd = sorted(max_drawdowns)
        p95_idx = min(n - 1, int(n * 0.95))
        p95_drawdown = sorted_dd[p95_idx] if n > 0 else 0.0

        tail_risk_score = self.compute_tail_risk(sorted_ret)

        return MonteCarloResult(
            candidate_id=candidate_id,
            n_simulations=n_simulations,
            survival_rate=round(survival_rate, 4),
            median_return=round(median_return, 6),
            p5_return=round(p5_return, 6),
            p95_drawdown=round(p95_drawdown, 6),
            tail_risk_score=tail_risk_score,
        )
