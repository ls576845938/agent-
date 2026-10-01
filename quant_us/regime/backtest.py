"""Regime-aware backtest analysis — split performance by market regime.

This module works with already-computed backtest results. It does **not**
run new backtests. It never imports from ``quant_us.live`` or
``quant_us.execution``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from quant_us.regime.detector import RegimeState


@dataclass
class RegimeBacktestResult:
    """Aggregated backtest performance split by regime."""

    symbol: str
    strategy_id: str
    regime_performance: dict[str, dict[str, float]] = field(default_factory=dict)
    best_regime: str = ""
    worst_regime: str = ""
    regime_transitions: int = 0
    recommended_filter: list[str] = field(default_factory=list)


class RegimeAwareBacktest:
    """Analyse backtest results through the lens of market regimes.

    Parameters
    ----------
    data_root : str
        Root for backtest result storage (default ``data``).
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = data_root

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def split_by_regime(
        self,
        backtest_result_path: str,
        regime_data: pd.DataFrame,
    ) -> dict[str, dict[str, float]]:
        """Split backtest performance by regime.

        Parameters
        ----------
        backtest_result_path : str
            Path to a directory containing backtest result files
            (``summary.json``, ``fills.parquet``, ``portfolio_snapshots.parquet``).
        regime_data : pd.DataFrame
            Must contain columns ``date`` and ``regime``. Used to label each
            snapshot's regime.

        Returns
        -------
        dict[str, dict[str, float]]
            Mapping of regime label -> performance metrics (cagr_pct,
            sharpe_ratio, max_drawdown_pct, trade_count).
        """
        snapshots = self._load_snapshots(backtest_result_path)
        fills = self._load_fills(backtest_result_path)

        if snapshots.empty:
            return self._empty_regime_map("no_snapshots")

        labelled = self._label_snapshots(snapshots, regime_data)
        if labelled.empty:
            return self._empty_regime_map("no_label")

        result: dict[str, dict[str, float]] = {}
        for regime in labelled["regime"].unique():
            subset = labelled[labelled["regime"] == regime]
            fills_in_regime = self._fills_in_range(
                fills, subset["timestamp_utc"].min(), subset["timestamp_utc"].max()
            )
            perf = self._compute_perf(subset, fills_in_regime)
            result[regime] = perf

        return result

    def filter_by_regime(
        self,
        backtest_result_path: str,
        allowed_regimes: list[str],
    ) -> dict[str, float]:
        """Compute backtest stats using only periods in *allowed_regimes*.

        Parameters
        ----------
        backtest_result_path : str
            Path to backtest result directory.
        allowed_regimes : list[str]
            Regime labels to include.

        Returns
        -------
        dict[str, float]
            Performance metrics computed on the subset of snapshots that fall
            in an allowed regime period.
        """
        snapshots = self._load_snapshots(backtest_result_path)
        fills = self._load_fills(backtest_result_path)

        # We need regime data to know which periods are allowed.
        # Try to detect from SPY, then filter.
        from quant_us.regime.detector import MarketRegimeDetector

        detector = MarketRegimeDetector(self.data_root)
        spy_prices = detector._load_prices("SPY")
        if spy_prices.empty:
            return self._empty_perf()

        regime_df = detector.detect(spy_prices)
        if regime_df.empty:
            return self._empty_perf()

        labelled = self._label_snapshots(snapshots, regime_df)
        if labelled.empty:
            return self._empty_perf()

        filtered = labelled[labelled["regime"].isin(allowed_regimes)]
        if filtered.empty:
            return self._empty_perf()

        fills_in_range = self._fills_in_range(
            fills, filtered["timestamp_utc"].min(), filtered["timestamp_utc"].max()
        )
        return self._compute_perf(filtered, fills_in_range)

    def transition_analysis(self, regime_data: pd.DataFrame) -> dict[str, Any]:
        """Compute regime transition matrix and summary statistics.

        Parameters
        ----------
        regime_data : pd.DataFrame
            Must contain columns ``date`` and ``regime``, sorted by date.

        Returns
        -------
        dict
            Keys:
            - ``transitions``: total number of regime changes.
            - ``transition_matrix``: dict of ``from_regime -> to_regime -> count``.
            - ``regime_frequency``: dict of ``regime -> days_in_regime``.
            - ``avg_days_per_regime``: average consecutive days in each regime.
        """
        if regime_data.empty or "regime" not in regime_data.columns:
            return {
                "transitions": 0,
                "transition_matrix": {},
                "regime_frequency": {},
                "avg_days_per_regime": {},
            }

        df = regime_data.sort_values("date").reset_index(drop=True)
        regimes = df["regime"].tolist()
        dates = df["date"].tolist()

        transitions = 0
        transition_matrix: dict[str, dict[str, int]] = {}
        regime_runs: dict[str, list[int]] = {}
        current_regime = regimes[0]
        current_run = 1

        for i in range(1, len(regimes)):
            r = regimes[i]
            if r != current_regime:
                transitions += 1
                from_r = current_regime
                to_r = r
                transition_matrix.setdefault(from_r, {}).setdefault(to_r, 0)
                transition_matrix[from_r][to_r] += 1
                regime_runs.setdefault(current_regime, []).append(current_run)
                current_regime = r
                current_run = 1
            else:
                current_run += 1

        # Final run
        regime_runs.setdefault(current_regime, []).append(current_run)

        frequency = df["regime"].value_counts().to_dict()
        avg_days = {
            r: round(sum(runs) / len(runs), 1) if runs else 0
            for r, runs in regime_runs.items()
        }

        return {
            "transitions": transitions,
            "transition_matrix": transition_matrix,
            "regime_frequency": {str(k): int(v) for k, v in frequency.items()},
            "avg_days_per_regime": avg_days,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_snapshots(self, result_path: str) -> pd.DataFrame:
        base = Path(result_path)
        snap_file = base / "portfolio_snapshots.parquet"
        if not snap_file.exists():
            return pd.DataFrame()
        df = pd.read_parquet(str(snap_file))
        if "timestamp_utc" in df.columns:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        return df

    def _load_fills(self, result_path: str) -> pd.DataFrame:
        base = Path(result_path)
        fills_file = base / "fills.parquet"
        if not fills_file.exists():
            return pd.DataFrame()
        df = pd.read_parquet(str(fills_file))
        if "filled_at" in df.columns:
            df["filled_at"] = pd.to_datetime(df["filled_at"], utc=True)
        if "timestamp_utc" in df.columns:
            df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        return df

    def _label_snapshots(
        self,
        snapshots: pd.DataFrame,
        regime_data: pd.DataFrame,
    ) -> pd.DataFrame:
        """Merge regime labels onto snapshot timestamps."""
        if snapshots.empty or regime_data.empty:
            return pd.DataFrame()

        regime_lookup = regime_data[["date", "regime"]].copy()
        regime_lookup["date"] = pd.to_datetime(regime_lookup["date"])
        snapshots["date"] = snapshots["timestamp_utc"].dt.date
        label_map = dict(
            zip(regime_lookup["date"].dt.date, regime_lookup["regime"])
        )
        snapshots["regime"] = snapshots["date"].map(label_map)
        return snapshots.dropna(subset=["regime"]).reset_index(drop=True)

    def _fills_in_range(
        self,
        fills: pd.DataFrame,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        if fills.empty:
            return pd.DataFrame()
        ts_col = "filled_at" if "filled_at" in fills.columns else "timestamp_utc"
        ts = pd.to_datetime(fills[ts_col]).dt.tz_localize(None)
        s = pd.Timestamp(start).tz_localize(None)
        e = pd.Timestamp(end).tz_localize(None)
        return fills[(ts >= s) & (ts <= e)]

    def _compute_perf(
        self,
        snapshots: pd.DataFrame,
        fills: pd.DataFrame,
    ) -> dict[str, float]:
        """Compute performance metrics for a snapshot subset."""
        if snapshots.empty:
            return {
                "cagr_pct": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "trade_count": 0,
            }

        equity_col = "equity" if "equity" in snapshots.columns else "total_equity"
        if equity_col not in snapshots.columns:
            return {
                "cagr_pct": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "trade_count": 0,
            }

        equity = snapshots[equity_col].astype(float)
        initial = equity.iloc[0]
        final = equity.iloc[-1]
        n = len(equity)

        total_return = (final / initial - 1.0) if initial > 0 else 0.0
        periods_per_year = 252.0
        cagr = (
            (final / initial) ** (periods_per_year / max(1, n)) - 1.0
            if initial > 0
            else 0.0
        )

        returns = equity.pct_change().fillna(0.0)
        std = float(returns.std(ddof=0))
        sharpe = float(returns.mean() / std * (periods_per_year**0.5)) if std > 0 else 0.0

        rolling_max = equity.cummax()
        drawdown = (equity / rolling_max - 1.0).min()
        max_dd = float(drawdown) if not pd.isna(drawdown) else 0.0

        trade_count = len(fills) if not fills.empty else 0

        return {
            "cagr_pct": round(cagr * 100.0, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown_pct": round(max_dd * 100.0, 4),
            "trade_count": trade_count,
        }

    @staticmethod
    def _empty_regime_map(reason: str) -> dict[str, dict[str, float]]:
        return {"__empty__": {"reason": reason}}

    @staticmethod
    def _empty_perf() -> dict[str, float]:
        return {
            "cagr_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_count": 0,
        }
