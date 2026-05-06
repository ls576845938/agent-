from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Union

from quant_us.core.clock import ET, to_et
from quant_us.core.enums import SessionName
from quant_us.core.calendar import USEquityCalendar


class SessionClock:
    """Trading-hours scheduler wrapping a USEquityCalendar.

    Answers "is the market open right now?" and "how long until the
    next session boundary?".  All ``now`` arguments are assumed to be
    UTC-aware datetimes (the codebase convention).  Naive datetimes
    are treated as UTC.
    """

    def __init__(self, calendar: USEquityCalendar) -> None:
        self.calendar = calendar
        self._enabled = sorted(
            [r for r in calendar.rules if r.enabled],
            key=lambda r: r.start_et,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def is_market_open(self, now: datetime) -> bool:
        """True when *now* falls inside an enabled trading session."""
        return self.calendar.is_open(now)

    def current_session(self, now: datetime) -> SessionName:
        """Return the active SessionName, or CLOSED."""
        return self.calendar.session_for(now)

    # ------------------------------------------------------------------
    # Time-to-boundary
    # ------------------------------------------------------------------

    def time_until_next_session(self, now: datetime) -> float:
        """Seconds until the next enabled session *starts*.

        Returns ``inf`` when no enabled session exists or no future
        trading day is found within the look-ahead window (5 days).
        """
        if not self._enabled:
            return float("inf")

        now_et = to_et(now)

        # Scan forward up to 5 calendar days (covers weekends + holidays)
        for offset in range(5):
            check = now_et + timedelta(days=offset)
            check_date = check.date()
            if not self.calendar.is_trading_day(check_date):
                continue
            for rule in self._enabled:
                start_dt = datetime.combine(check_date, rule.start_et, tzinfo=ET)
                if start_dt > now_et:
                    return (start_dt - now_et).total_seconds()

        return float("inf")

    def time_until_session_close(self, now: datetime) -> float:
        """Seconds until the *current* session ends.

        Returns 0.0 when the market is closed (no active session).
        """
        session = self.current_session(now)
        if session == SessionName.CLOSED:
            return 0.0

        now_et = to_et(now)
        today = now_et.date()

        for rule in self._enabled:
            if rule.name != session:
                continue

            # Determine the closing time for this session
            if rule.name == SessionName.REGULAR and self.calendar.is_early_close(today):
                close_time = self.calendar.early_close_time
            else:
                close_time = rule.end_et

            # Wrapping sessions (overnight 21:00 -> 04:00) end on the next day
            if rule.start_et <= rule.end_et:
                close_dt = datetime.combine(today, close_time, tzinfo=ET)
            else:
                close_dt = datetime.combine(today + timedelta(days=1), close_time, tzinfo=ET)

            remaining = (close_dt - now_et).total_seconds()
            return max(remaining, 0.0)

        return 0.0

    def next_session_event(self, now: datetime) -> tuple[str, float]:
        """Nearest session boundary as (``"open"`` | ``"close"``, seconds).

        Returns ``("close", 0.0)`` when no future event exists.
        """
        next_open = self.time_until_next_session(now)
        next_close = (
            self.time_until_session_close(now)
            if self.current_session(now) != SessionName.CLOSED
            else float("inf")
        )

        # When close and open coincide (e.g. regular closes at 16:00 and
        # after-hours opens at 16:00), report "close" first.
        if next_close <= next_open:
            return ("close", next_close)
        return ("open", next_open)

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def should_be_running(self, now: datetime, warmup_minutes: float = 30.0) -> bool:
        """True if the market is open now or will open within *warmup_minutes*."""
        if self.is_market_open(now):
            return True
        return self.time_until_next_session(now) <= warmup_minutes * 60.0

    def should_shutdown(self, now: datetime, after_hours_grace_minutes: float = 15.0) -> bool:
        """True if the market is closed and the last close was longer ago than
        *after_hours_grace_minutes*.

        On non-trading days the method returns ``True`` (the system has no
        reason to stay running).
        """
        if self.is_market_open(now):
            return False

        now_et = to_et(now)
        today = now_et.date()

        # Walk backwards to find the most recent session close
        for lookback in range(10):
            check_date = today - timedelta(days=lookback)
            if not self.calendar.is_trading_day(check_date):
                continue

            # Iterate enabled rules in reverse chronological order so we
            # hit the *last* (latest-ending) session first.
            for rule in reversed(self._enabled):
                if rule.name == SessionName.OVERNIGHT:
                    end_dt = datetime.combine(check_date + timedelta(days=1), rule.end_et, tzinfo=ET)
                else:
                    if rule.name == SessionName.REGULAR and self.calendar.is_early_close(check_date):
                        end_et = self.calendar.early_close_time
                    else:
                        end_et = rule.end_et
                    end_dt = datetime.combine(check_date, end_et, tzinfo=ET)

                if end_dt <= now_et:
                    elapsed = (now_et - end_dt).total_seconds()
                    return elapsed > after_hours_grace_minutes * 60.0

        # No trading day found in lookback window
        return True
