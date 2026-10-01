from __future__ import annotations

import pandas as pd


def rate_of_change(close: pd.Series, window: int) -> pd.Series:
    return close.pct_change(window)


def rolling_momentum_score(close: pd.Series, short_window: int = 20, long_window: int = 120) -> pd.Series:
    short = rate_of_change(close, short_window)
    long = rate_of_change(close, long_window)
    return (short + long) / 2.0
