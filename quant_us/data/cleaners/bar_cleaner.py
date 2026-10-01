from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import ET
from quant_us.core.enums import SessionName


@dataclass(frozen=True)
class CleaningResult:
    frame: pd.DataFrame
    dropped_rows: int
    duplicate_rows: int


class BarCleaner:
    REQUIRED_COLUMNS = ["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"]

    def __init__(self, calendar: USEquityCalendar | None = None) -> None:
        self.calendar = calendar or USEquityCalendar()

    def clean(self, frame: pd.DataFrame, symbol: str = "", source: str = "") -> CleaningResult:
        if frame.empty:
            return CleaningResult(pd.DataFrame(columns=self.REQUIRED_COLUMNS), dropped_rows=0, duplicate_rows=0)

        working = frame.copy()
        working.columns = [str(column).strip().lower() for column in working.columns]

        if "timestamp_utc" not in working.columns:
            if "timestamp" in working.columns:
                working["timestamp_utc"] = working["timestamp"]
            else:
                working["timestamp_utc"] = working.index

        working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        if symbol:
            working["symbol"] = symbol.upper()
        elif "symbol" in working.columns:
            working["symbol"] = working["symbol"].astype(str).str.upper()
        else:
            working["symbol"] = ""

        for column in ["open", "high", "low", "close", "volume", "vwap", "trade_count"]:
            if column in working.columns:
                working[column] = pd.to_numeric(working[column], errors="coerce")

        before = len(working)
        duplicate_rows = int(working.duplicated(subset=["timestamp_utc", "symbol"]).sum())
        working = working.drop_duplicates(subset=["timestamp_utc", "symbol"], keep="last")
        working = working.dropna(subset=["timestamp_utc", "symbol", "open", "high", "low", "close", "volume"])
        working = working[
            (working["open"] > 0)
            & (working["high"] >= working[["open", "close", "low"]].max(axis=1))
            & (working["low"] <= working[["open", "close", "high"]].min(axis=1))
            & (working["close"] > 0)
            & (working["volume"] >= 0)
        ]

        working["timestamp_et"] = working["timestamp_utc"].dt.tz_convert(ET)
        session_values = working["timestamp_utc"].map(lambda value: self.calendar.session_for(value).value)
        working["session"] = session_values
        working["is_regular_session"] = session_values == SessionName.REGULAR.value
        working["is_pre_market"] = session_values == SessionName.PRE_MARKET.value
        working["is_after_hours"] = session_values == SessionName.AFTER_HOURS.value
        working["source"] = source or working.get("source", "")
        working["adjusted_flag"] = bool(working.get("adjusted_flag", False)) if "adjusted_flag" not in working.columns else working["adjusted_flag"].astype(bool)
        if "vwap" not in working.columns:
            working["vwap"] = pd.NA
        if "trade_count" not in working.columns:
            working["trade_count"] = pd.NA

        ordered_columns = [
            "timestamp_utc",
            "timestamp_et",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "vwap",
            "trade_count",
            "source",
            "session",
            "is_regular_session",
            "is_pre_market",
            "is_after_hours",
            "adjusted_flag",
        ]
        working = working.sort_values(["symbol", "timestamp_utc"]).reset_index(drop=True)
        return CleaningResult(working[ordered_columns], dropped_rows=before - len(working), duplicate_rows=duplicate_rows)
