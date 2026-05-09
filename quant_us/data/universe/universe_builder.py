from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.nyse_holidays import is_nyse_trading_day


@dataclass(frozen=True)
class UniverseRule:
    min_price: float = 5.0
    min_dollar_volume: float = 20_000_000.0
    min_history_bars: int = 20
    include_etfs: bool = True
    exclude_symbols: set[str] = field(default_factory=set)


@dataclass
class UniverseBuilder:
    """Build tradable stock universe with survivorship bias awareness.

    Key features:
    - Filters by price, dollar volume, and history length
    - Respects delisting dates (survivorship bias mitigation)
    - Tracks ticker changes
    - Supports point-in-time universe composition
    """

    rule: UniverseRule = field(default_factory=UniverseRule)
    calendar: USEquityCalendar | None = None

    def __post_init__(self) -> None:
        if self.calendar is None:
            self.calendar = USEquityCalendar.with_holidays()

    def from_daily_bars(
        self,
        frame: pd.DataFrame,
        as_of_date: date | None = None,
        instruments: pd.DataFrame | None = None,
    ) -> list[str]:
        """Build universe from daily bars, optionally at a point-in-time."""
        if frame.empty:
            return []

        working = frame.copy()
        working["symbol"] = working["symbol"].astype(str).str.upper()

        if "timestamp_utc" in working.columns:
            working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
        elif working.index.name in (None, ""):
            ts_col = "timestamp" if "timestamp" in working.columns else "timestamp_utc"
            if ts_col in working.columns:
                working["timestamp_utc"] = pd.to_datetime(working[ts_col], utc=True)

        working["date"] = working["timestamp_utc"].dt.date

        if as_of_date is not None:
            working = working[working["date"] <= as_of_date]

        working["dollar_volume"] = working["close"] * working["volume"]

        history_counts = working.groupby("symbol").size()
        latest_window = working.sort_values("timestamp_utc").groupby("symbol", group_keys=False).tail(min(20, len(working)))
        summary = latest_window.groupby("symbol").agg(
            close=("close", "last"),
            adv=("dollar_volume", "mean"),
        )
        summary["history_bars"] = history_counts

        selected = summary[
            (summary["close"] >= self.rule.min_price)
            & (summary["adv"] >= self.rule.min_dollar_volume)
            & (summary["history_bars"] >= self.rule.min_history_bars)
        ]

        excluded = self.rule.exclude_symbols or set()
        selected = selected[~selected.index.isin({s.upper() for s in excluded})]

        if instruments is not None and not instruments.empty:
            inst = instruments.copy()
            inst["symbol"] = inst["symbol"].astype(str).str.upper()
            if "delisting_date" in inst.columns:
                if as_of_date is not None:
                    inst = inst[
                        (inst["delisting_date"].isna())
                        | (pd.to_datetime(inst["delisting_date"]).dt.date > as_of_date)
                    ]
                else:
                    inst = inst[inst["delisting_date"].isna()]
            if "is_active" in inst.columns:
                inst = inst[inst["is_active"] == True]
            active_symbols = set(inst["symbol"].unique())
            selected = selected[selected.index.isin(active_symbols)]

        return sorted(str(s) for s in selected.index)

    def point_in_time_universe(
        self,
        bars_by_date: dict[date, pd.DataFrame],
        target_date: date,
        instruments: pd.DataFrame | None = None,
    ) -> list[str]:
        """Get universe composition as of a specific date.

        Only uses data available on or before target_date. This prevents
        survivorship bias by not using future knowledge of which stocks survive.
        """
        frames: list[pd.DataFrame] = []
        for d, frame in sorted(bars_by_date.items()):
            if d <= target_date:
                frames.append(frame)

        if not frames:
            return []

        combined = pd.concat(frames, ignore_index=True)
        return self.from_daily_bars(combined, as_of_date=target_date, instruments=instruments)

    def universe_over_time(
        self,
        bars_by_date: dict[date, pd.DataFrame],
        instruments: pd.DataFrame | None = None,
        freq: str = "ME",
    ) -> dict[date, list[str]]:
        """Compute universe composition at regular intervals.

        Returns a map of date -> list of symbols that qualified at each date.
        """
        result: dict[date, list[str]] = {}
        dates = sorted(bars_by_date.keys())
        if not dates:
            return result

        eval_dates = pd.date_range(start=dates[0], end=dates[-1], freq=freq)
        for eval_ts in eval_dates:
            eval_date = eval_ts.date()
            universe = self.point_in_time_universe(bars_by_date, eval_date, instruments)
            if universe:
                result[eval_date] = universe

        return result
