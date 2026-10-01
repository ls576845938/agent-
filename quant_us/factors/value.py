from __future__ import annotations

import pandas as pd


def earnings_yield_score(earnings_yield: pd.Series) -> pd.Series:
    return earnings_yield.rank(pct=True)
