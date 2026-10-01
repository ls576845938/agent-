"""Tests for SessionClock (trading-hours scheduler).

Uses a calendar with only the "regular" session (09:30-16:00 ET) enabled, which
matches the default ``config/market_sessions.yaml`` (where pre-market,
after-hours and overnight all have ``allow_trading: false``).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from quant_us.core.calendar import SessionConfig, USEquityCalendar
from quant_us.core.clock import ET, to_et
from quant_us.core.enums import SessionName
from quant_us.live.session_clock import SessionClock

UTC = timezone.utc


class SessionClockTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        """Calendar with 2026 holidays and only regular session enabled."""
        cls.cal = USEquityCalendar.with_holidays(
            years=(2026,),
            session_config=SessionConfig(
                pre_market=False,
                regular=True,
                after_hours=False,
                overnight=False,
            ),
        )

    def setUp(self) -> None:
        self.clock = SessionClock(self.cal)

    # ------------------------------------------------------------------
    # is_market_open
    # ------------------------------------------------------------------

    def test_is_market_open_regular_hours(self) -> None:
        """10:30 ET on a regular Tuesday -> market is open."""
        # May 5, 2026 is a Tuesday, DST in effect (UTC-4)
        dt = datetime(2026, 5, 5, 14, 30, tzinfo=UTC)  # 10:30 ET
        self.assertTrue(self.clock.is_market_open(dt))

    def test_is_market_open_outside_hours(self) -> None:
        """21:00 ET (well after 16:00 close) -> market is closed."""
        # 21:00 ET on May 5 = May 6 01:00 UTC
        dt = datetime(2026, 5, 6, 1, 0, tzinfo=UTC)
        self.assertFalse(self.clock.is_market_open(dt))

    def test_is_market_open_weekend(self) -> None:
        """Sunday afternoon -> market is closed."""
        dt = datetime(2026, 5, 3, 16, 0, tzinfo=UTC)  # 12:00 ET Sunday
        self.assertFalse(self.clock.is_market_open(dt))

    def test_is_market_open_holiday(self) -> None:
        """July 3 (Friday, Independence Day observed) -> market is closed."""
        dt = datetime(2026, 7, 3, 14, 30, tzinfo=UTC)  # 10:30 ET
        self.assertFalse(self.clock.is_market_open(dt))

    def test_is_market_open_pre_market_disabled(self) -> None:
        """08:00 ET (in pre-market hours) but pre-market disabled -> closed."""
        dt = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)  # 08:00 ET
        self.assertFalse(self.clock.is_market_open(dt))

    def test_is_market_open_after_hours_disabled(self) -> None:
        """17:00 ET (in after-hours) but after-hours disabled -> closed."""
        dt = datetime(2026, 5, 5, 21, 0, tzinfo=UTC)  # 17:00 ET
        self.assertFalse(self.clock.is_market_open(dt))

    # ------------------------------------------------------------------
    # current_session
    # ------------------------------------------------------------------

    def test_current_session_regular(self) -> None:
        """10:30 ET on a regular Tuesday -> REGULAR."""
        dt = datetime(2026, 5, 5, 14, 30, tzinfo=UTC)
        self.assertEqual(self.clock.current_session(dt), SessionName.REGULAR)

    def test_current_session_closed_after_hours(self) -> None:
        """21:00 ET -> CLOSED (after-hours not enabled)."""
        dt = datetime(2026, 5, 6, 1, 0, tzinfo=UTC)
        self.assertEqual(self.clock.current_session(dt), SessionName.CLOSED)

    def test_current_session_weekend(self) -> None:
        """Sunday -> CLOSED."""
        dt = datetime(2026, 5, 3, 16, 0, tzinfo=UTC)
        self.assertEqual(self.clock.current_session(dt), SessionName.CLOSED)

    def test_current_session_holiday(self) -> None:
        """July 3 (holiday) -> CLOSED."""
        dt = datetime(2026, 7, 3, 14, 30, tzinfo=UTC)
        self.assertEqual(self.clock.current_session(dt), SessionName.CLOSED)

    # ------------------------------------------------------------------
    # time_until_next_session
    # ------------------------------------------------------------------

    def test_next_session_before_open(self) -> None:
        """03:00 ET -> next session at 09:30 ET same day (6.5 hours)."""
        # Jan 6 2026, Tuesday, standard time (UTC-5)
        now_utc = datetime(2026, 1, 6, 8, 0, tzinfo=UTC)  # 03:00 ET
        next_start_et = datetime(2026, 1, 6, 9, 30, tzinfo=ET)
        expected = (next_start_et - to_et(now_utc)).total_seconds()
        self.assertAlmostEqual(
            self.clock.time_until_next_session(now_utc), expected, delta=1
        )

    def test_next_session_after_close(self) -> None:
        """22:00 ET -> next session is next trading day at 09:30 ET."""
        # Jan 6 2026, Tuesday, 22:00 ET = Jan 7 03:00 UTC
        now_utc = datetime(2026, 1, 7, 3, 0, tzinfo=UTC)
        next_start_et = datetime(2026, 1, 7, 9, 30, tzinfo=ET)  # Wednesday
        expected = (next_start_et - to_et(now_utc)).total_seconds()
        self.assertAlmostEqual(
            self.clock.time_until_next_session(now_utc), expected, delta=1
        )

    def test_next_session_from_weekend(self) -> None:
        """Saturday midday -> next session is Monday 09:30 ET."""
        # May 2, 2026 is Saturday
        now_utc = datetime(2026, 5, 2, 16, 0, tzinfo=UTC)  # 12:00 ET
        next_start_et = datetime(2026, 5, 4, 9, 30, tzinfo=ET)  # Monday
        expected = (next_start_et - to_et(now_utc)).total_seconds()
        self.assertAlmostEqual(
            self.clock.time_until_next_session(now_utc), expected, delta=1
        )

    def test_next_session_from_holiday(self) -> None:
        """July 3 (Friday, holiday) -> next session is July 6 at 09:30 ET."""
        # July 3 is Friday (holiday). Next trading day is July 6 (Monday).
        now_utc = datetime(2026, 7, 3, 14, 0, tzinfo=UTC)  # 10:00 ET
        next_start_et = datetime(2026, 7, 6, 9, 30, tzinfo=ET)
        expected = (next_start_et - to_et(now_utc)).total_seconds()
        self.assertAlmostEqual(
            self.clock.time_until_next_session(now_utc), expected, delta=1
        )

    # ------------------------------------------------------------------
    # time_until_session_close
    # ------------------------------------------------------------------

    def test_session_close_during_regular(self) -> None:
        """10:30 ET on regular day -> 5.5 hours until 16:00 ET close."""
        now_utc = datetime(2026, 5, 5, 14, 30, tzinfo=UTC)  # 10:30 ET
        close_et = datetime(2026, 5, 5, 16, 0, tzinfo=ET)
        expected = (close_et - to_et(now_utc)).total_seconds()
        self.assertAlmostEqual(
            self.clock.time_until_session_close(now_utc), expected, delta=1
        )

    def test_session_close_when_closed(self) -> None:
        """After close -> returns 0.0."""
        dt = datetime(2026, 5, 6, 1, 0, tzinfo=UTC)  # 21:00 ET (post-close)
        self.assertEqual(self.clock.time_until_session_close(dt), 0.0)

    # ------------------------------------------------------------------
    # next_session_event
    # ------------------------------------------------------------------

    def test_next_event_during_session_is_close(self) -> None:
        """During regular -> nearest boundary is close (16:00 ET)."""
        now_utc = datetime(2026, 5, 5, 14, 30, tzinfo=UTC)  # 10:30 ET
        event, seconds = self.clock.next_session_event(now_utc)
        self.assertEqual(event, "close")
        self.assertGreater(seconds, 0)

    def test_next_event_after_close_is_open(self) -> None:
        """After close -> nearest boundary is next open."""
        now_utc = datetime(2026, 5, 6, 1, 0, tzinfo=UTC)  # 21:00 ET (closed)
        event, seconds = self.clock.next_session_event(now_utc)
        self.assertEqual(event, "open")
        self.assertGreater(seconds, 0)

    # ------------------------------------------------------------------
    # should_be_running
    # ------------------------------------------------------------------

    def test_should_be_running_during_market(self) -> None:
        """During regular hours -> should be running."""
        dt = datetime(2026, 5, 5, 14, 30, tzinfo=UTC)
        self.assertTrue(self.clock.should_be_running(dt))

    def test_should_be_running_within_warmup(self) -> None:
        """09:00 ET (30 min before regular open) with warmup=30 -> True."""
        dt = datetime(2026, 5, 5, 13, 0, tzinfo=UTC)  # 09:00 ET
        self.assertTrue(self.clock.should_be_running(dt, warmup_minutes=30))

    def test_should_be_running_outside_warmup(self) -> None:
        """08:00 ET (90 min before open) with warmup=30 -> False."""
        dt = datetime(2026, 5, 5, 12, 0, tzinfo=UTC)  # 08:00 ET
        self.assertFalse(self.clock.should_be_running(dt, warmup_minutes=30))

    def test_should_be_running_weekend(self) -> None:
        """Sunday -> False (far from next open)."""
        dt = datetime(2026, 5, 3, 16, 0, tzinfo=UTC)
        self.assertFalse(self.clock.should_be_running(dt))

    # ------------------------------------------------------------------
    # should_shutdown
    # ------------------------------------------------------------------

    def test_should_shutdown_during_market(self) -> None:
        """During market hours -> False."""
        dt = datetime(2026, 5, 5, 14, 30, tzinfo=UTC)
        self.assertFalse(self.clock.should_shutdown(dt))

    def test_should_shutdown_just_after_close(self) -> None:
        """16:05 ET (5 min after close) with grace=15 -> False."""
        dt = datetime(2026, 5, 5, 20, 5, tzinfo=UTC)  # 16:05 ET
        self.assertFalse(
            self.clock.should_shutdown(dt, after_hours_grace_minutes=15)
        )

    def test_should_shutdown_after_grace(self) -> None:
        """16:20 ET (20 min after close) with grace=15 -> True."""
        dt = datetime(2026, 5, 5, 20, 20, tzinfo=UTC)  # 16:20 ET
        self.assertTrue(
            self.clock.should_shutdown(dt, after_hours_grace_minutes=15)
        )

    def test_should_shutdown_weekend(self) -> None:
        """Saturday -> True (far from last close)."""
        dt = datetime(2026, 5, 2, 16, 0, tzinfo=UTC)  # Saturday noon ET
        self.assertTrue(self.clock.should_shutdown(dt))


if __name__ == "__main__":
    unittest.main()
