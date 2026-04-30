from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from quant_us.core.clock import to_et
from quant_us.core.enums import SessionName


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


class USEquityCalendar:
    """Session-aware US equity calendar.

    This intentionally keeps holidays configurable later instead of baking a
    brittle calendar into trading logic. The important contract is that every
    decision asks the calendar/session layer first.
    """

    def __init__(self, session_config: SessionConfig | None = None) -> None:
        config = session_config or SessionConfig()
        self.rules = [
            SessionRule(SessionName.OVERNIGHT, time(21, 0), time(4, 0), config.overnight),
            SessionRule(SessionName.PRE_MARKET, time(4, 0), time(9, 30), config.pre_market),
            SessionRule(SessionName.REGULAR, time(9, 30), time(16, 0), config.regular),
            SessionRule(SessionName.AFTER_HOURS, time(16, 0), time(20, 0), config.after_hours),
        ]

    def session_for(self, timestamp: datetime) -> SessionName:
        timestamp_et = to_et(timestamp)
        if timestamp_et.weekday() >= 5:
            return SessionName.CLOSED
        for rule in self.rules:
            if rule.enabled and rule.contains(timestamp_et):
                return rule.name
        return SessionName.CLOSED

    def is_open(self, timestamp: datetime, allowed_sessions: set[SessionName] | None = None) -> bool:
        session = self.session_for(timestamp)
        if session == SessionName.CLOSED:
            return False
        return allowed_sessions is None or session in allowed_sessions

    def is_regular_session(self, timestamp: datetime) -> bool:
        return self.session_for(timestamp) == SessionName.REGULAR
