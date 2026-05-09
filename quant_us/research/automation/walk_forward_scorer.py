"""Walk-forward analysis scorer for research automation.

Scores and evaluates walk-forward performance for strategy candidates:
- Computes pass/fail rates across folds
- Measures OOS stability (variance across folds)
- Flags candidates that need more data (too few trades per fold)
- Produces a structured WalkForwardResult for use in promotion gates
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WalkForwardResult:
    """Structured result of a walk-forward scoring evaluation.

    Attributes:
        candidate_id: The candidate being evaluated.
        fold_count: Number of walk-forward folds processed.
        pass_count: Number of folds that passed performance threshold.
        fail_count: Number of folds that failed.
        avg_oos_return: Average out-of-sample return across folds.
        avg_oos_sharpe: Average out-of-sample Sharpe ratio across folds.
        worst_fold_drawdown: Maximum drawdown in the worst fold.
        fold_stability: Std of fold returns / mean return — lower is more stable.
        pass_rate: Fraction of folds that passed (pass_count / fold_count).
        status: PASS | FAIL | NEEDS_MORE_DATA | NOT_RUN.
    """

    candidate_id: str
    fold_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    avg_oos_return: float = 0.0
    avg_oos_sharpe: float = 0.0
    worst_fold_drawdown: float = 0.0
    fold_stability: float = 0.0
    pass_rate: float = 0.0
    status: str = "NOT_RUN"


class WalkForwardScorer:
    """Score walk-forward performance for strategy candidates.

    Reads fold results (each a dict with at least sharpe_ratio, total_return_pct,
    trade_count, max_drawdown_pct) and produces a WalkForwardResult.

    Criteria:
    - pass_rate < 0.50 -> status FAIL
    - trade_count per fold < 5 -> status NEEDS_MORE_DATA
    - otherwise status PASS
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def score(
        self, candidate_id: str, fold_results: list[dict[str, Any]]
    ) -> WalkForwardResult:
        """Score walk-forward performance for a candidate.

        Args:
            candidate_id: The candidate being evaluated.
            fold_results: List of fold result dicts. Each dict should contain:
                - sharpe_ratio (float): OOS Sharpe for this fold
                - total_return_pct (float): OOS return
                - trade_count (int): Number of trades in this fold
                - max_drawdown_pct (float): Max drawdown for this fold

        Returns:
            WalkForwardResult with scoring summary.

        Raises:
            ValueError: If fold_results is empty.
        """
        if not fold_results:
            raise ValueError(
                f"Cannot score {candidate_id}: fold_results is empty"
            )

        fold_count = len(fold_results)
        oos_returns: list[float] = []
        oos_sharpes: list[float] = []
        drawdowns: list[float] = []
        trade_counts: list[int] = []

        for fold in fold_results:
            oos_returns.append(float(fold.get("total_return_pct", 0.0)))
            oos_sharpes.append(float(fold.get("sharpe_ratio", 0.0)))
            drawdowns.append(abs(float(fold.get("max_drawdown_pct", 0.0))))
            trade_counts.append(int(fold.get("trade_count", 0)))

        # Count passes: Sharpe > 0.5 in a fold is a pass
        pass_count = sum(1 for s in oos_sharpes if s > 0.5)
        fail_count = fold_count - pass_count

        avg_oos_return = sum(oos_returns) / fold_count
        avg_oos_sharpe = sum(oos_sharpes) / fold_count
        worst_fold_drawdown = max(drawdowns) if drawdowns else 0.0

        # Fold stability: std of returns / mean (lower = more stable)
        if avg_oos_return != 0:
            mean_ret = avg_oos_return
            variance = sum((r - mean_ret) ** 2 for r in oos_returns) / fold_count
            fold_stability = round((variance ** 0.5) / abs(mean_ret), 4)
        else:
            fold_stability = 0.0

        pass_rate = pass_count / fold_count

        # Determine status
        min_trades = min(trade_counts) if trade_counts else 0
        if min_trades < 5:
            status = "NEEDS_MORE_DATA"
        elif pass_rate < 0.50:
            status = "FAIL"
        else:
            status = "PASS"

        return WalkForwardResult(
            candidate_id=candidate_id,
            fold_count=fold_count,
            pass_count=pass_count,
            fail_count=fail_count,
            avg_oos_return=avg_oos_return,
            avg_oos_sharpe=avg_oos_sharpe,
            worst_fold_drawdown=worst_fold_drawdown,
            fold_stability=fold_stability,
            pass_rate=pass_rate,
            status=status,
        )
