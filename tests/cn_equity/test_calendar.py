from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from quant_cn.market.calendar import (
    CALENDAR_OPEN,
    CALENDAR_PHASE_AMBIGUOUS,
    CALENDAR_PHASE_CLOSED,
    CALENDAR_SESSION_AMBIGUOUS,
    CALENDAR_SESSION_MISSING,
    CALENDAR_SESSION_NOT_AVAILABLE,
    InjectedCalendar,
    SessionPhase,
)

from .factories import AS_OF, UTC, dimensions_for, make_record, make_session


def _resolve(calendar: InjectedCalendar, *, as_of: datetime = AS_OF):
    dimensions = dimensions_for(make_record())
    return calendar.resolve(
        as_of=as_of,
        venue=dimensions.venue,
        board=dimensions.board,
        instrument=dimensions.instrument,
        security_type=dimensions.security_type,
    )


def test_calendar_never_infers_weekdays_or_weekends() -> None:
    empty = InjectedCalendar(())
    assert _resolve(empty, as_of=datetime(2025, 1, 2, 3, tzinfo=UTC)).status == (
        CALENDAR_SESSION_MISSING
    )
    assert _resolve(empty, as_of=datetime(2025, 1, 4, 3, tzinfo=UTC)).status == (
        CALENDAR_SESSION_MISSING
    )


def test_calendar_is_versioned_and_phase_boundaries_are_half_open() -> None:
    dimensions = dimensions_for(make_record())
    phases = (
        SessionPhase("auction", AS_OF - timedelta(hours=1), AS_OF, False),
        SessionPhase("continuous", AS_OF, AS_OF + timedelta(hours=1), True),
    )
    result = _resolve(
        InjectedCalendar((make_session(dimensions, version="calendar-v7", phases=phases),))
    )
    assert result.status == CALENDAR_OPEN
    assert result.calendar_version == "calendar-v7"
    assert result.phase_name == "continuous"


def test_calendar_blocks_invisible_session_without_version_leak() -> None:
    dimensions = dimensions_for(make_record())
    session = make_session(
        dimensions,
        version="future-calendar",
        available_time=AS_OF + timedelta(seconds=1),
        ingested_at=AS_OF + timedelta(seconds=2),
        processed_at=AS_OF + timedelta(seconds=3),
    )
    result = _resolve(InjectedCalendar((session,)))
    assert result.status == CALENDAR_SESSION_NOT_AVAILABLE
    assert result.calendar_version is None
    assert result.session_id is None


def test_calendar_blocks_overlapping_sessions_and_phases() -> None:
    dimensions = dimensions_for(make_record())
    sessions = (
        make_session(dimensions, session_id="one"),
        make_session(dimensions, session_id="two"),
    )
    assert _resolve(InjectedCalendar(sessions)).status == CALENDAR_SESSION_AMBIGUOUS

    phases = (
        SessionPhase("one", AS_OF - timedelta(hours=1), AS_OF + timedelta(hours=1), True),
        SessionPhase(
            "two",
            AS_OF - timedelta(minutes=30),
            AS_OF + timedelta(minutes=30),
            True,
        ),
    )
    assert _resolve(
        InjectedCalendar((make_session(dimensions, phases=phases),))
    ).status == CALENDAR_PHASE_AMBIGUOUS


def test_calendar_blocks_non_order_phase_and_naive_as_of() -> None:
    dimensions = dimensions_for(make_record())
    phase = SessionPhase(
        "break",
        AS_OF - timedelta(minutes=30),
        AS_OF + timedelta(minutes=30),
        False,
    )
    assert _resolve(
        InjectedCalendar((make_session(dimensions, phases=(phase,)),))
    ).status == CALENDAR_PHASE_CLOSED
    with pytest.raises(ValueError, match="^timestamp_must_be_timezone_aware:as_of$"):
        _resolve(InjectedCalendar(()), as_of=datetime(2025, 1, 2, 3, 0))


def test_calendar_metadata_order_and_checksum_are_strict() -> None:
    dimensions = dimensions_for(make_record())
    with pytest.raises(ValueError, match="^calendar_ingested_at_after_processed_at$"):
        make_session(
            dimensions,
            ingested_at=AS_OF,
            processed_at=AS_OF - timedelta(seconds=1),
        )
    with pytest.raises(
        ValueError,
        match="^checksum_must_be_lowercase_sha256:session.checksum$",
    ):
        make_session(dimensions, checksum="B" * 64)
