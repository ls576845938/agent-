from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from calendar import monthrange
from typing import Union

from quant_us.core.clock import ET, to_et
from quant_us.core.enums import SessionName
from quant_us.core.nyse_holidays import is_nyse_trading_day as _is_trading_day
from quant_us.core.nyse_holidays import nyse_early_closes, nyse_holidays


@dataclass(frozen=True)
class SessionRule:
    name: SessionName
    start_et: time
    end_et: time
    enabled: bool = True

    def contains(self, timestamp_et: datetime) -> bool:
        current = timestamp_et.time()
        if self.start_et <= self.end_et:
            return self.start_et <= current < self.end_et
        return current >= self.start_et or current < self.end_et


@dataclass(frozen=True)
class SessionConfig:
    pre_market: bool = True
    regular: bool = True
    after_hours: bool = True
    overnight: bool = False


def load_sessions_from_yaml(path: str | os.PathLike) -> tuple[SessionConfig, list[SessionRule], time]:
    """Load session rules and early-close time from a YAML market-sessions config.

    Returns
    -------
    (SessionConfig, list[SessionRule], early_close_time)
    """
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f)

    market = data["market"]
    session_data = market["sessions"]

    name_map: dict[str, SessionName] = {
        "pre_market": SessionName.PRE_MARKET,
        "regular": SessionName.REGULAR,
        "after_hours": SessionName.AFTER_HOURS,
        "overnight": SessionName.OVERNIGHT,
    }

    config_kwargs: dict[str, bool] = {}
    rules: list[SessionRule] = []

    for yaml_key, session_name in name_map.items():
        info = session_data[yaml_key]
        start = time.fromisoformat(info["start"])
        end = time.fromisoformat(info["end"])
        allow_trading = bool(info.get("allow_trading", False))
        rules.append(SessionRule(session_name, start, end, allow_trading))
        config_kwargs[yaml_key] = allow_trading

    config = SessionConfig(**config_kwargs)
    early_close_raw = market.get("early_close", {}).get("time", "13:00")
    early_close_time = time.fromisoformat(early_close_raw)

    return config, rules, early_close_time


@dataclass
class USEquityCalendar:
    """Session-aware US equity calendar with NYSE holiday database.

    Every trading decision asks this calendar/session layer first.
    Supports: pre-market, regular, after-hours, overnight sessions.
    Includes: NYSE holiday calendar, early-close days.
    """

    session_config: SessionConfig = field(default_factory=SessionConfig)
    holidays: dict[date, str] = field(default_factory=dict)
    early_closes: dict[date, str] = field(default_factory=dict)
    early_close_time: time = field(default_factory=lambda: time(13, 0))
    rules: list[SessionRule] | None = field(default=None, repr=False)
    calendar_provider: str = "builtin_nyse_rules"
    calendar_name: str = "XNYS"
    provider_diagnostics: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rules is None:
            object.__setattr__(self, "rules", [
                SessionRule(SessionName.OVERNIGHT, time(21, 0), time(4, 0), self.session_config.overnight),
                SessionRule(SessionName.PRE_MARKET, time(4, 0), time(9, 30), self.session_config.pre_market),
                SessionRule(SessionName.REGULAR, time(9, 30), time(16, 0), self.session_config.regular),
                SessionRule(SessionName.AFTER_HOURS, time(16, 0), time(20, 0), self.session_config.after_hours),
            ])

    @classmethod
    def with_holidays(
        cls,
        years: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030),
        session_config: SessionConfig | None = None,
        yaml_path: str | None = None,
        calendar_provider: str = "exchange_calendars",
    ) -> "USEquityCalendar":
        provider = calendar_provider.lower()
        all_holidays, all_early, diagnostics = _load_market_calendar_dates(years, provider)

        if yaml_path is not None:
            config, rules, early_close_time = load_sessions_from_yaml(yaml_path)
            return cls(
                session_config=config,
                holidays=all_holidays,
                early_closes=all_early,
                early_close_time=early_close_time,
                rules=rules,
                calendar_provider=diagnostics["calendar_provider"],
                provider_diagnostics=diagnostics,
            )
        return cls(
            session_config=session_config or SessionConfig(),
            holidays=all_holidays,
            early_closes=all_early,
            calendar_provider=diagnostics["calendar_provider"],
            provider_diagnostics=diagnostics,
        )

    @classmethod
    def with_exchange_calendars(
        cls,
        years: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030),
        session_config: SessionConfig | None = None,
    ) -> "USEquityCalendar":
        return cls.with_holidays(
            years=years,
            session_config=session_config,
            calendar_provider="exchange_calendars",
        )

    @classmethod
    def with_pandas_market_calendars(
        cls,
        years: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025, 2026, 2027, 2028, 2029, 2030),
        session_config: SessionConfig | None = None,
    ) -> "USEquityCalendar":
        return cls.with_holidays(
            years=years,
            session_config=session_config,
            calendar_provider="pandas_market_calendars",
        )

    @classmethod
    def from_yaml(cls, path: str | os.PathLike) -> "USEquityCalendar":
        """Build a calendar from a YAML market-sessions config without holiday data."""
        config, rules, early_close_time = load_sessions_from_yaml(path)
        return cls(
            session_config=config,
            rules=rules,
            early_close_time=early_close_time,
        )

    def is_trading_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        if self.holidays:
            return d not in self.holidays
        return _is_trading_day(d)

    def is_early_close(self, d: date) -> bool:
        if self.early_closes:
            return d in self.early_closes
        return d in nyse_early_closes(d.year)

    def session_for(self, timestamp: datetime) -> SessionName:
        timestamp_et = to_et(timestamp)
        ts_date = timestamp_et.date()
        if not self.is_trading_day(ts_date):
            return SessionName.CLOSED
        for rule in self.rules:
            if rule.enabled and rule.contains(timestamp_et):
                if rule.name == SessionName.REGULAR and self.is_early_close(ts_date):
                    if timestamp_et.time() >= self.early_close_time:
                        return SessionName.CLOSED
                return rule.name
        return SessionName.CLOSED

    def is_open(self, timestamp: datetime, allowed_sessions: set[SessionName] | None = None) -> bool:
        session = self.session_for(timestamp)
        if session == SessionName.CLOSED:
            return False
        return allowed_sessions is None or session in allowed_sessions

    def is_regular_session(self, timestamp: datetime) -> bool:
        return self.session_for(timestamp) == SessionName.REGULAR

    def next_trading_day(self, d: date) -> date:
        d = d + timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def previous_trading_day(self, d: date) -> date:
        d = d - timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def last_trading_day_of_month(self, year: int, month: int) -> date:
        """Return the actual last US equity trading day for a calendar month."""

        last_day = date(year, month, monthrange(year, month)[1])
        while not self.is_trading_day(last_day):
            last_day -= timedelta(days=1)
        return last_day

    def trading_days_between(self, start: date, end: date) -> list[date]:
        """Return inclusive trading dates between start and end."""

        if end < start:
            return []
        current = start
        days: list[date] = []
        while current <= end:
            if self.is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days


def _load_market_calendar_dates(
    years: tuple[int, ...],
    provider: str,
) -> tuple[dict[date, str], dict[date, str], dict[str, object]]:
    if provider == "builtin_nyse_rules":
        return _load_builtin_dates(years, fallback_reason="")
    if provider == "exchange_calendars":
        try:
            return _load_exchange_calendars_dates(years)
        except Exception as exc:
            return _load_builtin_dates(years, fallback_reason=f"exchange_calendars_unavailable:{type(exc).__name__}")
    if provider == "pandas_market_calendars":
        try:
            return _load_pandas_market_calendars_dates(years)
        except Exception as exc:
            return _load_builtin_dates(years, fallback_reason=f"pandas_market_calendars_unavailable:{type(exc).__name__}")
    raise ValueError(f"unsupported_calendar_provider:{provider}")


def _load_builtin_dates(
    years: tuple[int, ...],
    *,
    fallback_reason: str,
) -> tuple[dict[date, str], dict[date, str], dict[str, object]]:
    holidays: dict[date, str] = {}
    early: dict[date, str] = {}
    for year in years:
        holidays.update(nyse_holidays(year))
        early.update(nyse_early_closes(year))
    diagnostics: dict[str, object] = {
        "calendar_provider": "builtin_nyse_rules",
        "calendar_name": "XNYS",
        "year_start": min(years),
        "year_end": max(years),
        "holiday_count": len(holidays),
        "early_close_count": len(early),
    }
    if fallback_reason:
        diagnostics["fallback_reason"] = fallback_reason
    return holidays, early, diagnostics


def _iter_weekdays_for_years(years: tuple[int, ...]) -> list[date]:
    days: list[date] = []
    for year in years:
        current = date(year, 1, 1)
        end = date(year, 12, 31)
        while current <= end:
            if current.weekday() < 5:
                days.append(current)
            current += timedelta(days=1)
    return days


def _load_exchange_calendars_dates(
    years: tuple[int, ...],
) -> tuple[dict[date, str], dict[date, str], dict[str, object]]:
    import exchange_calendars as xcals

    calendar = xcals.get_calendar("XNYS")
    holidays: dict[date, str] = {}
    early: dict[date, str] = {}
    for d in _iter_weekdays_for_years(years):
        session_label = d.isoformat()
        if not calendar.is_session(session_label):
            holidays[d] = "XNYS closed session"
            continue
        close_utc = calendar.session_close(session_label)
        close_et = close_utc.to_pydatetime().astimezone(ET)
        if close_et.time() < time(16, 0):
            early[d] = f"XNYS early close {close_et.time().isoformat(timespec='minutes')} ET"
    return holidays, early, {
        "calendar_provider": "exchange_calendars",
        "calendar_name": "XNYS",
        "year_start": min(years),
        "year_end": max(years),
        "holiday_count": len(holidays),
        "early_close_count": len(early),
    }


def _load_pandas_market_calendars_dates(
    years: tuple[int, ...],
) -> tuple[dict[date, str], dict[date, str], dict[str, object]]:
    import pandas_market_calendars as pmc

    calendar = pmc.get_calendar("XNYS")
    start = date(min(years), 1, 1)
    end = date(max(years), 12, 31)
    schedule = calendar.schedule(start_date=start.isoformat(), end_date=end.isoformat())
    open_by_day = {idx.date(): row for idx, row in schedule.iterrows()}
    holidays: dict[date, str] = {}
    early: dict[date, str] = {}
    for d in _iter_weekdays_for_years(years):
        row = open_by_day.get(d)
        if row is None:
            holidays[d] = "XNYS closed session"
            continue
        close_et = row["market_close"].to_pydatetime().astimezone(ET)
        if close_et.time() < time(16, 0):
            early[d] = f"XNYS early close {close_et.time().isoformat(timespec='minutes')} ET"
    return holidays, early, {
        "calendar_provider": "pandas_market_calendars",
        "calendar_name": "XNYS",
        "year_start": min(years),
        "year_end": max(years),
        "holiday_count": len(holidays),
        "early_close_count": len(early),
    }
