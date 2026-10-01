from __future__ import annotations

import pandas as pd


def average_dollar_volume(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    return (close * volume).rolling(window=window, min_periods=window).mean()


def turnover(volume: pd.Series, shares_outstanding: float) -> pd.Series:
    if shares_outstanding <= 0:
        return pd.Series(0.0, index=volume.index)
    return volume / shares_outstanding
