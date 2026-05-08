"""Factor evaluation and Information Coefficient (IC) analysis.

Provides cross-sectional IC, rank IC, quantile returns, IC decay, and
lookahead detection for any registered factor.

Usage:
    evaluator = FactorEvaluator(data_root="data")
    result = evaluator.evaluate("momentum_60d", symbols=["SPY","QQQ"],
                                start="2020-01-01", end="2025-12-31")
    print(result.ic_mean, result.rank_ic_mean)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_us.factors.definition import FactorLibrary
from quant_us.factors.pipeline import FactorPipeline, _load_bars


@dataclass
class FactorEvaluationResult:
    """Aggregated evaluation metrics for a single factor."""

    factor_id: str
    ic_mean: float = 0.0
    ic_std: float = 0.0
    icir: float = 0.0  # IC Information Ratio = mean / std
    rank_ic_mean: float = 0.0
    rank_ic_std: float = 0.0
    rank_icir: float = 0.0
    quantile_returns: dict[int, float] = field(default_factory=dict)  # q1..q5 → return
    long_short_spread: float = 0.0
    turnover: float = 0.0
    decay_half_life: float = 0.0  # IC decay rate in days
    hit_rate: float = 0.0
    monotonicity: float = 0.0  # correlation between quantile rank and return
    factor_correlations: dict[str, float] = field(default_factory=dict)
    n_observations: int = 0
    n_dates: int = 0


class FactorEvaluator:
    """Compute IC, rank IC, quantile returns, and decay for a factor."""

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root
        self._pipeline = FactorPipeline(data_root)
        self._lib = FactorLibrary()

    # ------------------------------------------------------------------
    # Main evaluation entry-point
    # ------------------------------------------------------------------

    def evaluate(
        self,
        factor_id: str,
        symbols: list[str],
        start: str,
        end: str,
        forward_period: int = 5,
    ) -> FactorEvaluationResult:
        """Full factor evaluation.

        Steps:
            1. Compute factor values for every (date, symbol).
            2. Compute forward returns for the same grid.
            3. Run cross-sectional IC, rank IC, quantile returns, and decay.
            4. Aggregate into a single FactorEvaluationResult.
        """
        definition = self._lib.get(factor_id)

        # 1. Compute factor values (extended lookback, then clipped to [start, end])
        df = self._pipeline.compute(
            factor_ids=[factor_id],
            symbols=symbols,
            start=start,
            end=end,
        )
        if df.empty or factor_id not in df.columns:
            return FactorEvaluationResult(factor_id=factor_id)

        # 2. Build forward returns
        bars = _load_bars(self.data_root, symbols, start, end)
        if bars.empty:
            return FactorEvaluationResult(factor_id=factor_id)
        forward_df = self._build_forward_returns(bars, period=forward_period)

        # Merge factor values with forward returns
        merged = df.merge(
            forward_df[["date", "symbol", "fwd_return"]],
            on=["date", "symbol"],
            how="inner",
        )
        if merged.empty:
            return FactorEvaluationResult(factor_id=factor_id)

        # 3. Daily IC time-series
        daily_ics: list[float] = []
        daily_rank_ics: list[float] = []
        all_quantile_returns: list[dict[int, float]] = []

        for dt, day_group in merged.groupby("date", sort=True):
            fvals = day_group[factor_id].dropna()
            fwd = day_group["fwd_return"].dropna()
            # Align indices
            common = fvals.index.intersection(fwd.index)
            if len(common) < 10:  # too few observations
                continue
            fv = fvals.loc[common]
            fr = fwd.loc[common]

            ic_val = fv.corr(fr)
            rank_ic_val = fv.corr(fr, method="spearman")

            if not pd.isna(ic_val):
                daily_ics.append(float(ic_val))
            if not pd.isna(rank_ic_val):
                daily_rank_ics.append(float(rank_ic_val))

            # Quantile returns
            qret = self._quantile_returns_single(fv, fr, n_quantiles=5)
            all_quantile_returns.append(qret)

        if not daily_ics:
            return FactorEvaluationResult(factor_id=factor_id)

        # 4. Aggregate
        ic_arr = np.array(daily_ics)
        rank_ic_arr = np.array(daily_rank_ics)

        ic_mean = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
        icir = ic_mean / ic_std if ic_std > 0 else 0.0

        rank_ic_mean = float(np.mean(rank_ic_arr))
        rank_ic_std = float(np.std(rank_ic_arr, ddof=1)) if len(rank_ic_arr) > 1 else 0.0
        rank_icir = rank_ic_mean / rank_ic_std if rank_ic_std > 0 else 0.0

        # Average quantile returns across all dates
        avg_quantile = self._average_quantile_returns(all_quantile_returns, n_quantiles=5)

        # Long-short spread (Q1 long - Q5 short, or Q5 long - Q1 short depending on sign)
        q_keys = sorted(avg_quantile.keys())
        if len(q_keys) >= 2:
            if avg_quantile[q_keys[0]] < avg_quantile[q_keys[-1]]:
                long_short = avg_quantile[q_keys[-1]] - avg_quantile[q_keys[0]]
            else:
                long_short = avg_quantile[q_keys[0]] - avg_quantile[q_keys[-1]]
        else:
            long_short = 0.0

        # Hit rate: fraction of dates with positive IC
        hit_rate = float(np.mean(ic_arr > 0)) if len(ic_arr) > 0 else 0.0

        # Monotonicity: correlation between quantile rank (1..5) and return
        monotonicity = self._compute_monotonicity(avg_quantile)

        # Decay half-life
        decay_hl = self._estimate_decay_half_life(merged, factor_id)

        result = FactorEvaluationResult(
            factor_id=factor_id,
            ic_mean=ic_mean,
            ic_std=ic_std,
            icir=icir,
            rank_ic_mean=rank_ic_mean,
            rank_ic_std=rank_ic_std,
            rank_icir=rank_icir,
            quantile_returns=avg_quantile,
            long_short_spread=long_short,
            turnover=0.0,  # requires portfolio-level data; left as 0.0
            decay_half_life=decay_hl,
            hit_rate=hit_rate,
            monotonicity=monotonicity,
            factor_correlations={},
            n_observations=len(merged),
            n_dates=len(daily_ics),
        )
        return result

    # ------------------------------------------------------------------
    # IC computation
    # ------------------------------------------------------------------

    def compute_ic(
        self,
        factor_values: dict[str, float],
        forward_returns: dict[str, float],
    ) -> float:
        """Cross-sectional Pearson IC between factor values and forward returns."""
        symbols = [s for s in factor_values if s in forward_returns]
        if len(symbols) < 5:
            return 0.0
        fv = pd.Series({s: factor_values[s] for s in symbols})
        fr = pd.Series({s: forward_returns[s] for s in symbols})
        corr = fv.corr(fr)
        return float(corr) if not pd.isna(corr) else 0.0

    def compute_rank_ic(
        self,
        factor_values: dict[str, float],
        forward_returns: dict[str, float],
    ) -> float:
        """Cross-sectional Spearman rank IC."""
        symbols = [s for s in factor_values if s in forward_returns]
        if len(symbols) < 5:
            return 0.0
        fv = pd.Series({s: factor_values[s] for s in symbols})
        fr = pd.Series({s: forward_returns[s] for s in symbols})
        corr = self._spearmanr(fv, fr)
        return float(corr) if not pd.isna(corr) else 0.0

    def compute_quantile_returns(
        self,
        factor_values: dict[str, float],
        forward_returns: dict[str, float],
        n_quantiles: int = 5,
    ) -> dict[int, float]:
        """Cross-sectional average forward return per factor quantile."""
        if len(factor_values) < n_quantiles:
            return {}
        fv = pd.Series(factor_values)
        fr = pd.Series({s: forward_returns.get(s, float("nan")) for s in fv.index})
        return self._quantile_returns_single(fv.dropna(), fr.dropna(), n_quantiles)

    def compute_decay(
        self,
        factor_values: dict[str, float],
        forward_returns: dict[str, float],
        horizons: list[int] | None = None,
    ) -> dict[int, float]:
        """IC across multiple forward horizons (placeholder stub)."""
        _ = factor_values, forward_returns
        horizons = horizons or [1, 5, 10, 20]
        return {h: 0.0 for h in horizons}

    # ------------------------------------------------------------------
    # Lookahead detection
    # ------------------------------------------------------------------

    def detect_lookahead(self, factor_id: str) -> tuple[bool, str]:
        """Heuristic lookahead detection.

        If the absolute mean IC exceeds 0.2, flag as potential lookahead.
        A truly predictive factor can have |IC| up to ~0.1 for equities;
        anything above 0.2 strongly suggests future data leaking in.
        """
        # Try to load cached evaluation, or run a quick sample
        try:
            symbols = self._lib.get(factor_id).required_fields
            result = self.evaluate(
                factor_id=factor_id,
                symbols=["SPY", "QQQ", "AAPL", "MSFT", "GOOGL"],
                start="2024-01-01",
                end="2024-06-30",
                forward_period=5,
            )
        except Exception as exc:
            return False, f"evaluation failed: {exc}"

        if abs(result.ic_mean) > 0.2:
            return (
                True,
                f"mean IC = {result.ic_mean:.4f} exceeds 0.2 threshold. "
                f"Rank IC = {result.rank_ic_mean:.4f}. Possible lookahead.",
            )
        return False, f"mean IC = {result.ic_mean:.4f} (below 0.2 threshold)"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_forward_returns(bars: pd.DataFrame, period: int) -> pd.DataFrame:
        """Compute forward *period*-day returns for each symbol.

        Returns a DataFrame with columns ``date``, ``symbol``, ``fwd_return``.
        """
        bars = bars.copy()
        bars["timestamp_utc"] = pd.to_datetime(bars["timestamp_utc"], utc=True)
        bars["date"] = bars["timestamp_utc"].dt.date.astype(str)
        bars = bars.sort_values(["symbol", "date"])

        # Forward close price
        bars["close_fwd"] = bars.groupby("symbol")["close"].transform(
            lambda s: s.shift(-period)
        )
        bars["fwd_return"] = bars["close_fwd"] / bars["close"] - 1.0
        # Remove rows where forward return is NaN (last *period* rows per symbol)
        result = bars.dropna(subset=["fwd_return"])[["date", "symbol", "fwd_return"]]
        return result

    @staticmethod
    def _quantile_returns_single(
        factor_vals: pd.Series,
        forward_ret: pd.Series,
        n_quantiles: int = 5,
    ) -> dict[int, float]:
        """Average forward return per quantile for a single cross-section."""
        if len(factor_vals) < n_quantiles:
            return {}
        labels = list(range(1, n_quantiles + 1))
        quantiles = pd.qcut(factor_vals, q=n_quantiles, labels=labels, duplicates="drop")
        grouped = forward_ret.groupby(quantiles).mean()
        return {int(k): float(v) for k, v in grouped.items() if not pd.isna(v)}

    @staticmethod
    def _spearmanr(a: pd.Series, b: pd.Series) -> float:
        """Compute Spearman rank correlation without scipy."""
        if len(a) < 3:
            return 0.0
        rank_a = a.rank()
        rank_b = b.rank()
        corr = rank_a.corr(rank_b)
        return float(corr) if not pd.isna(corr) else 0.0

    @staticmethod
    def _average_quantile_returns(
        all_quantiles: list[dict[int, float]],
        n_quantiles: int,
    ) -> dict[int, float]:
        """Average quantile returns across multiple dates."""
        accum: dict[int, list[float]] = {q: [] for q in range(1, n_quantiles + 1)}
        for qd in all_quantiles:
            for q, val in qd.items():
                accum.setdefault(q, []).append(val)
        return {q: float(np.mean(vals)) for q, vals in accum.items() if vals}

    @staticmethod
    def _compute_monotonicity(quantile_returns: dict[int, float]) -> float:
        """Spearman correlation between quantile rank (ascending) and return."""
        if len(quantile_returns) < 3:
            return 0.0
        ranks = sorted(quantile_returns.keys())
        returns = [quantile_returns[r] for r in ranks]
        corr = FactorEvaluator._spearmanr(pd.Series(ranks), pd.Series(returns))
        return float(corr) if not pd.isna(corr) else 0.0

    @staticmethod
    def _estimate_decay_half_life(
        merged: pd.DataFrame,
        factor_id: str,
        max_lag: int = 20,
    ) -> float:
        """Estimate IC decay half-life by computing IC at increasing lags.

        Returns the lag (in days) at which IC drops below half its initial
        value.  If decay is not detected within *max_lag*, returns *max_lag*.
        """
        try:
            # Compute IC at lag 0
            fv = merged[factor_id]
            fr = merged["fwd_return"]
            ic_lag0 = fv.corr(fr)
            if pd.isna(ic_lag0) or abs(ic_lag0) < 1e-8:
                return float(max_lag)

            half_target = abs(ic_lag0) / 2.0

            for lag in range(1, max_lag + 1):
                fv_shifted = merged.groupby("symbol")[factor_id].transform(
                    lambda s: s.shift(lag)
                )
                ic_lag = fv_shifted.corr(fr)
                if pd.isna(ic_lag) or abs(ic_lag) < half_target:
                    return float(lag)
            return float(max_lag)
        except Exception:
            return float(max_lag)
