"""Versioned, caller-injected China-market calendar resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from quant_cn.data.contracts import (
    ensure_aware_timestamp,
    ensure_sha256_checksum,
    require_non_empty,
)


CALENDAR_OPEN = "open"
CALENDAR_SESSION_MISSING = "session_missing"
CALENDAR_SESSION_NOT_AVAILABLE = "session_not_available"
CALENDAR_SESSION_AMBIGUOUS = "session_ambiguous"
CALENDAR_SESSION_CLOSED = "session_closed"
CALENDAR_PHASE_MISSING = "phase_missing"
CALENDAR_PHASE_AMBIGUOUS = "phase_ambiguous"
CALENDAR_PHASE_CLOSED = "phase_closed"


@dataclass(frozen=True)
class SessionPhase:
    name: str
    starts_at: datetime
    ends_at: datetime
    accepts_orders: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "phase.name"))
        start = ensure_aware_timestamp(self.starts_at, "phase.starts_at")
        end = ensure_aware_timestamp(self.ends_at, "phase.ends_at")
        if end <= start:
            raise ValueError("calendar_phase_interval_invalid")
        if not isinstance(self.accepts_orders, bool):
            raise TypeError("calendar_phase_accepts_orders_must_be_bool")
        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)


@dataclass(frozen=True)
class TradingSession:
    session_id: str
    calendar_version: str
    venue: str
    board: str
    instrument: str
    security_type: str
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    source: str
    checksum: str
    starts_at: datetime
    ends_at: datetime
    is_open: bool
    phases: tuple[SessionPhase, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "calendar_version",
            "venue",
            "board",
            "instrument",
            "security_type",
            "source",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )

        start = ensure_aware_timestamp(self.starts_at, "session.starts_at")
        end = ensure_aware_timestamp(self.ends_at, "session.ends_at")
        available = ensure_aware_timestamp(self.available_time, "session.available_time")
        ingested = ensure_aware_timestamp(self.ingested_at, "session.ingested_at")
        processed = ensure_aware_timestamp(self.processed_at, "session.processed_at")
        if end <= start:
            raise ValueError("calendar_session_interval_invalid")
        if available > ingested:
            raise ValueError("calendar_available_time_after_ingested_at")
        if ingested > processed:
            raise ValueError("calendar_ingested_at_after_processed_at")
        if not isinstance(self.is_open, bool):
            raise TypeError("calendar_session_is_open_must_be_bool")

        phases = tuple(self.phases)
        if any(not isinstance(phase, SessionPhase) for phase in phases):
            raise TypeError("calendar_session_phase_type_invalid")
        if any(phase.starts_at < start or phase.ends_at > end for phase in phases):
            raise ValueError("calendar_phase_outside_session")

        object.__setattr__(self, "starts_at", start)
        object.__setattr__(self, "ends_at", end)
        object.__setattr__(self, "available_time", available)
        object.__setattr__(self, "ingested_at", ingested)
        object.__setattr__(self, "processed_at", processed)
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "session.checksum"),
        )
        object.__setattr__(self, "phases", phases)

    def matches(
        self,
        *,
        venue: str,
        board: str,
        instrument: str,
        security_type: str,
    ) -> bool:
        return (
            self.venue == venue
            and self.board == board
            and self.instrument == instrument
            and self.security_type == security_type
        )


@dataclass(frozen=True)
class CalendarResolution:
    status: str
    calendar_version: str | None = None
    session_id: str | None = None
    phase_name: str | None = None


class InjectedCalendar:
    """Resolve injected sessions only; never infer, fetch, or read latest state."""

    def __init__(self, sessions: Iterable[TradingSession]) -> None:
        self._sessions = tuple(sessions)
        if any(not isinstance(session, TradingSession) for session in self._sessions):
            raise TypeError("calendar_session_type_invalid")

    @property
    def sessions(self) -> tuple[TradingSession, ...]:
        return self._sessions

    def resolve(
        self,
        *,
        as_of: datetime,
        venue: str,
        board: str,
        instrument: str,
        security_type: str,
    ) -> CalendarResolution:
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        candidates = tuple(
            session
            for session in self._sessions
            if session.matches(
                venue=venue,
                board=board,
                instrument=instrument,
                security_type=security_type,
            )
            and session.starts_at <= timestamp < session.ends_at
        )
        if not candidates:
            return CalendarResolution(CALENDAR_SESSION_MISSING)

        visible = tuple(item for item in candidates if item.available_time <= timestamp)
        if not visible:
            return CalendarResolution(CALENDAR_SESSION_NOT_AVAILABLE)
        if len(visible) > 1:
            return CalendarResolution(CALENDAR_SESSION_AMBIGUOUS)

        session = visible[0]
        if not session.is_open:
            return CalendarResolution(
                CALENDAR_SESSION_CLOSED,
                calendar_version=session.calendar_version,
                session_id=session.session_id,
            )

        phases = tuple(
            phase
            for phase in session.phases
            if phase.starts_at <= timestamp < phase.ends_at
        )
        if not phases:
            return CalendarResolution(
                CALENDAR_PHASE_MISSING,
                calendar_version=session.calendar_version,
                session_id=session.session_id,
            )
        if len(phases) > 1:
            return CalendarResolution(
                CALENDAR_PHASE_AMBIGUOUS,
                calendar_version=session.calendar_version,
                session_id=session.session_id,
            )

        phase = phases[0]
        if not phase.accepts_orders:
            return CalendarResolution(
                CALENDAR_PHASE_CLOSED,
                calendar_version=session.calendar_version,
                session_id=session.session_id,
                phase_name=phase.name,
            )
        return CalendarResolution(
            CALENDAR_OPEN,
            calendar_version=session.calendar_version,
            session_id=session.session_id,
            phase_name=phase.name,
        )
