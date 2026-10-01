from __future__ import annotations

import pandas as pd


def gross_margin_score(gross_margin: pd.Series) -> pd.Series:
    return gross_margin.rank(pct=True)
