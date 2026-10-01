from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.enums import SessionName


pytest.importorskip("exchange_calendars")
pytest.importorskip("pandas_market_calendars")


def test_exchange_calendars_backed_calendar_handles_holidays_and_early_closes() -> None:
    calendar = USEquityCalendar.with_exchange_calendars(years=(2026,))

    assert calendar.calendar_provider == "exchange_calendars"
    assert calendar.is_trading_day(date(2026, 1, 1)) is False
    assert calendar.is_trading_day(date(2026, 11, 26)) is False
    assert calendar.is_trading_day(date(2026, 11, 27)) is True
    assert calendar.is_early_close(date(2026, 11, 27)) is True

    before_early_close = datetime(2026, 11, 27, 17, 59, tzinfo=timezone.utc)
    after_early_close = datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)
    assert calendar.session_for(before_early_close) == SessionName.REGULAR
    assert calendar.session_for(after_early_close) == SessionName.CLOSED


def test_pandas_market_calendars_matches_exchange_calendars_for_key_2026_sessions() -> None:
    exchange_calendar = USEquityCalendar.with_exchange_calendars(years=(2026,))
    pandas_calendar = USEquityCalendar.with_pandas_market_calendars(years=(2026,))

    probe_days = [
        date(2026, 1, 1),
        date(2026, 7, 3),
        date(2026, 11, 26),
        date(2026, 11, 27),
        date(2026, 12, 24),
        date(2026, 12, 25),
    ]
    for trading_day in probe_days:
        assert pandas_calendar.is_trading_day(trading_day) == exchange_calendar.is_trading_day(trading_day)
        assert pandas_calendar.is_early_close(trading_day) == exchange_calendar.is_early_close(trading_day)


def test_last_trading_day_of_month_uses_actual_us_equity_sessions() -> None:
    calendar = USEquityCalendar.with_exchange_calendars(years=(2026,))

    assert calendar.last_trading_day_of_month(2026, 2) == date(2026, 2, 27)
    assert calendar.last_trading_day_of_month(2026, 5) == date(2026, 5, 29)
    assert calendar.last_trading_day_of_month(2026, 7) == date(2026, 7, 31)
    assert calendar.last_trading_day_of_month(2026, 11) == date(2026, 11, 30)


def test_trading_days_between_is_inclusive_and_skips_market_holidays() -> None:
    calendar = USEquityCalendar.with_exchange_calendars(years=(2026,))

    days = calendar.trading_days_between(date(2026, 11, 25), date(2026, 11, 30))

    assert days == [date(2026, 11, 25), date(2026, 11, 27), date(2026, 11, 30)]
