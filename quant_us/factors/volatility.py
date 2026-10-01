from __future__ import annotations

import pandas as pd


def realized_volatility(close: pd.Series, window: int = 20, periods_per_year: float = 252.0) -> pd.Series:
    returns = close.pct_change()
    return returns.rolling(window=window, min_periods=window).std(ddof=0) * periods_per_year**0.5


def zscore(series: pd.Series, window: int = 20) -> pd.Series:
    mean = series.rolling(window=window, min_periods=window).mean()
    std = series.rolling(window=window, min_periods=window).std(ddof=0)
    return (series - mean) / std.replace(0, pd.NA)
