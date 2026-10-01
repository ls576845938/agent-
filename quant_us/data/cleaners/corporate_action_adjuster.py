from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: str
    ex_date: date
    ratio: float = 1.0
    cash_amount: float = 0.0
    source: str = ""


class CorporateActionAdjuster:
    """Backward-adjust OHLCV bars for split and cash-dividend actions."""

    def adjust_bars(self, bars: pd.DataFrame, actions: list[CorporateAction]) -> pd.DataFrame:
        if bars.empty or not actions:
            result = bars.copy()
            if not result.empty and "adjusted_flag" not in result.columns:
                result["adjusted_flag"] = False
            return result

        working = bars.copy()
        working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        working["symbol"] = working["symbol"].astype(str).str.upper()
        working["adjustment_factor"] = 1.0

        for action in sorted(actions, key=lambda item: item.ex_date):
            symbol = action.symbol.upper()
            before_ex_date = (working["symbol"] == symbol) & (working["timestamp_utc"].dt.date < action.ex_date)
            if action.action_type == "split" and action.ratio > 0:
                working.loc[before_ex_date, "adjustment_factor"] *= 1.0 / action.ratio
            elif action.action_type == "dividend" and action.cash_amount:
                pre_rows = working[before_ex_date].sort_values("timestamp_utc")
                if pre_rows.empty:
                    continue
                reference_close = float(pre_rows.iloc[-1]["close"])
                if reference_close > 0:
                    dividend_factor = max(0.0, (reference_close - action.cash_amount) / reference_close)
                    working.loc[before_ex_date, "adjustment_factor"] *= dividend_factor

        for column in ["open", "high", "low", "close", "vwap"]:
            if column in working.columns:
                working[column] = pd.to_numeric(working[column], errors="coerce") * working["adjustment_factor"]
        if "volume" in working.columns:
            factor = working["adjustment_factor"].replace(0, pd.NA)
            working["volume"] = pd.to_numeric(working["volume"], errors="coerce") / factor

        working["adjusted_flag"] = True
        return working.drop(columns=["adjustment_factor"])
