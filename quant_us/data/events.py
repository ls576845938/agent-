from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    event_date: date
    source: str = ""


@dataclass(frozen=True)
class EventFilterResult:
    frame: pd.DataFrame
    removed_rows: int
    blocked_symbols: list[str]


class EarningsBlackoutFilter:
    def __init__(self, days_before: int = 1, days_after: int = 1) -> None:
        self.days_before = days_before
        self.days_after = days_after

    def filter_bars(self, bars: pd.DataFrame, events: list[EarningsEvent]) -> EventFilterResult:
        if bars.empty or not events:
            return EventFilterResult(bars.copy(), 0, [])
        working = bars.copy()
        working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        working["symbol"] = working["symbol"].astype(str).str.upper()
        keep = pd.Series(True, index=working.index)
        blocked: set[str] = set()
        for event in events:
            start = event.event_date - timedelta(days=self.days_before)
            end = event.event_date + timedelta(days=self.days_after)
            mask = (
                (working["symbol"] == event.symbol.upper())
                & (working["timestamp_utc"].dt.date >= start)
                & (working["timestamp_utc"].dt.date <= end)
            )
            if bool(mask.any()):
                blocked.add(event.symbol.upper())
                keep &= ~mask
        filtered = working[keep].reset_index(drop=True)
        return EventFilterResult(filtered, removed_rows=len(working) - len(filtered), blocked_symbols=sorted(blocked))
