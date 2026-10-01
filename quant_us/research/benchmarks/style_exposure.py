from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StyleExposureResult:
    """Linear benchmark-factor exposure report for a strategy return stream."""

    observations: int
    alpha_period: float
    alpha_annualized: float
    betas: dict[str, float] = field(default_factory=dict)
    r_squared: float = 0.0
    residual_volatility_annualized: float = 0.0
    benchmark_columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_style_exposure(
    strategy_returns: pd.Series,
    benchmark_returns: pd.DataFrame,
    *,
    annualization: int = 252,
    min_observations: int = 20,
) -> StyleExposureResult:
    """Estimate alpha/beta exposure versus external benchmark factors.

    The caller supplies already-clean point-in-time return series.  This module
    deliberately does not download Fama/French or AQR data; it provides the
    deterministic regression core that those adapters can feed.
    """
    if strategy_returns.empty or benchmark_returns.empty:
        return StyleExposureResult(
            observations=0,
            alpha_period=0.0,
            alpha_annualized=0.0,
            warnings=["empty_input"],
        )

    y = pd.to_numeric(strategy_returns.rename("strategy"), errors="coerce")
    x = benchmark_returns.apply(pd.to_numeric, errors="coerce")
    frame = pd.concat([y, x], axis=1, join="inner").dropna()
    benchmark_columns = [str(column) for column in x.columns]
    if len(frame) < min_observations:
        return StyleExposureResult(
            observations=int(len(frame)),
            alpha_period=0.0,
            alpha_annualized=0.0,
            benchmark_columns=benchmark_columns,
            warnings=[f"insufficient_observations:{len(frame)}<{min_observations}"],
        )

    y_values = frame["strategy"].to_numpy(dtype=float)
    x_values = frame[benchmark_columns].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(frame)), x_values])
    coef, *_ = np.linalg.lstsq(design, y_values, rcond=None)
    fitted = design @ coef
    residuals = y_values - fitted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y_values - float(np.mean(y_values))) ** 2))
    r_squared = 0.0 if ss_tot <= 0 else max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    alpha_period = float(coef[0])
    residual_vol = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0

    return StyleExposureResult(
        observations=int(len(frame)),
        alpha_period=alpha_period,
        alpha_annualized=float(alpha_period * annualization),
        betas={
            str(column): float(value)
            for column, value in zip(benchmark_columns, coef[1:])
        },
        r_squared=r_squared,
        residual_volatility_annualized=float(residual_vol * np.sqrt(annualization)),
        benchmark_columns=benchmark_columns,
    )
