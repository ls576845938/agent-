from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Union

from quant_us.core.clock import to_et
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
    ) -> "USEquityCalendar":
        all_holidays: dict[date, str] = {}
        all_early: dict[date, str] = {}
        for year in years:
            all_holidays.update(nyse_holidays(year))
            all_early.update(nyse_early_closes(year))

        if yaml_path is not None:
            config, rules, early_close_time = load_sessions_from_yaml(yaml_path)
            return cls(
                session_config=config,
                holidays=all_holidays,
                early_closes=all_early,
                early_close_time=early_close_time,
                rules=rules,
            )
        return cls(
            session_config=session_config or SessionConfig(),
            holidays=all_holidays,
            early_closes=all_early,
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
