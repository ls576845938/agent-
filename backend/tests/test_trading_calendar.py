"""Tests for USQuantService.populate_trading_calendar."""

from __future__ import annotations

from datetime import date, time

import pytest

from backend.app.services.us_quant import USQuantService
from quant_us.core.nyse_holidays import nyse_holidays


class FakeCursor:
    """Minimal DB-API2 cursor that records SQL calls."""

    def __init__(self, calls: list) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: dict | None = None) -> None:
        self.calls.append(("execute", sql, params))

    def executemany(self, sql: str, rows: list[dict]) -> None:
        self.calls.append(("executemany", sql, rows))


class FakeConnection:
    """Minimal DB-API2 connection that records operations."""

    def __init__(self) -> None:
        self.calls: list = []
        self.commit_count = 0

    def cursor(self):
        return FakeCursor(self.calls)

    def commit(self):
        self.commit_count += 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_rows(calls: list) -> list[dict]:
    """Extract the row list from an executemany call."""
    for call in calls:
        if call[0] == "executemany":
            return call[2]
    return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPopulateTradingCalendar:
    """Tests for the populate_trading_calendar method."""

    def test_2024_row_count(self):
        """populate_trading_calendar(2024, 2024) returns 366 (leap year)."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        count = service.populate_trading_calendar(2024, 2024)
        assert count == 366

    def test_2025_row_count(self):
        """populate_trading_calendar(2025, 2025) returns 365."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        count = service.populate_trading_calendar(2025, 2025)
        assert count == 365

    def test_specific_holidays_2024(self):
        """Verify known NYSE holidays in 2024 are correctly flagged."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        service.populate_trading_calendar(2024, 2024)
        rows = _filter_rows(connection.calls)

        row_map = {row["date"]: row for row in rows}

        # New Year's Day
        ny = row_map[date(2024, 1, 1)]
        assert ny["is_trading_day"] is False
        assert ny["holiday_name"] == "New Year's Day"
        assert ny["session_hours"] == "00:00-00:00"

        # January 2 is a normal trading day
        jan2 = row_map[date(2024, 1, 2)]
        assert jan2["is_trading_day"] is True
        assert jan2["holiday_name"] is None
        assert jan2["session_hours"] == "09:30-16:00"
        assert jan2["early_close_time"] is None

        # Independence Day (July 4, 2024 = Thursday)
        jul4 = row_map[date(2024, 7, 4)]
        assert jul4["is_trading_day"] is False
        assert jul4["holiday_name"] == "Independence Day"
        assert jul4["session_hours"] == "00:00-00:00"

        # Thanksgiving (4th Thursday of November = Nov 28, 2024)
        tgiving = row_map[date(2024, 11, 28)]
        assert tgiving["is_trading_day"] is False
        assert tgiving["holiday_name"] == "Thanksgiving Day"
        assert tgiving["session_hours"] == "00:00-00:00"

        # Christmas (Dec 25, 2024 = Wednesday)
        xmas = row_map[date(2024, 12, 25)]
        assert xmas["is_trading_day"] is False
        assert xmas["holiday_name"] == "Christmas Day"
        assert xmas["session_hours"] == "00:00-00:00"

    def test_weekends_non_trading(self):
        """Verify weekends are non-trading (no holiday name)."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        service.populate_trading_calendar(2024, 2024)
        rows = _filter_rows(connection.calls)
        row_map = {row["date"]: row for row in rows}

        # 2024-01-06 = Saturday, 2024-01-07 = Sunday
        sat = row_map[date(2024, 1, 6)]
        sun = row_map[date(2024, 1, 7)]

        assert sat["is_trading_day"] is False
        assert sat["holiday_name"] is None
        assert sat["session_hours"] == "00:00-00:00"

        assert sun["is_trading_day"] is False
        assert sun["holiday_name"] is None
        assert sun["session_hours"] == "00:00-00:00"

    def test_early_closes_2024(self):
        """Verify known early-close days (Black Friday, Christmas Eve)."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        service.populate_trading_calendar(2024, 2024)
        rows = _filter_rows(connection.calls)
        row_map = {row["date"]: row for row in rows}

        # Black Friday 2024 = Nov 29 (Friday)
        bf = row_map[date(2024, 11, 29)]
        assert bf["is_trading_day"] is True
        assert bf["session_hours"] == "09:30-13:00"
        assert bf["early_close_time"] == time(13, 0)

        # Christmas Eve 2024 = Dec 24 (Tuesday)
        ce = row_map[date(2024, 12, 24)]
        assert ce["is_trading_day"] is True
        assert ce["session_hours"] == "09:30-13:00"
        assert ce["early_close_time"] == time(13, 0)

    def test_normal_trading_day_no_early_close(self):
        """Verify a regular trading day has full hours and no early close."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        service.populate_trading_calendar(2024, 2024)
        rows = _filter_rows(connection.calls)
        row_map = {row["date"]: row for row in rows}

        # 2024-03-15 (Friday, no holiday)
        d = row_map[date(2024, 3, 15)]
        assert d["is_trading_day"] is True
        assert d["session_hours"] == "09:30-16:00"
        assert d["early_close_time"] is None
        assert d["holiday_name"] is None

    def test_commits_after_batch(self):
        """Verify the service commits to the DB after executemany."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        service.populate_trading_calendar(2024, 2024)
        # One executemany call plus one commit
        executemany_count = sum(1 for call in connection.calls if call[0] == "executemany")
        assert executemany_count == 1
        assert connection.commit_count == 1

    def test_holiday_name_matches_nyse_holidays(self):
        """Verify holiday names match the nyse_holidays database."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        service.populate_trading_calendar(2024, 2024)
        rows = _filter_rows(connection.calls)
        row_map = {row["date"]: row for row in rows}

        expected = nyse_holidays(2024)
        for d, name in expected.items():
            assert row_map[d]["holiday_name"] == name
            assert row_map[d]["is_trading_day"] is False

    def test_multiple_year_range(self):
        """Populate 2023-2025 and verify correct total row count."""
        connection = FakeConnection()
        service = USQuantService(db_connection=connection)
        count = service.populate_trading_calendar(2023, 2025)
        # 2023 = 365, 2024 = 366, 2025 = 365
        assert count == 365 + 366 + 365

    def test_no_db_connection_raises(self):
        """populate_trading_calendar without db_connection raises RuntimeError."""
        service = USQuantService(db_connection=None)
        with pytest.raises(RuntimeError, match="Database connection required"):
            service.populate_trading_calendar(2024, 2024)
