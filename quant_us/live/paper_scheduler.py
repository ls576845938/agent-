"""Paper scheduler: runs PaperRuntime on a daily schedule.

PaperScheduler loops day by day:
  wait for market open → run session → close → wait for next trading day

Handles weekend/holiday skipping via SessionClock.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from quant_us.core.calendar import USEquityCalendar
from quant_us.core.clock import utc_now
from quant_us.core.enums import SessionName
from quant_us.live.paper_runtime import PaperRuntime, PaperRuntimeConfig
from quant_us.live.session_clock import SessionClock
from quant_us.strategies.base import Strategy

_logger = logging.getLogger("paper_scheduler")


@dataclass
class PaperSchedulerConfig:
    """Configuration for the daily paper scheduler.

    Attributes:
        runtime_config: Configuration passed to each ``PaperRuntime`` instance.
        warmup_minutes: How many minutes before market open to start.
        after_hours_grace_minutes: How long after close before shutdown.
        poll_during_close_seconds: How often to check for market open when
                                   the market is closed.
        max_daily_sessions: Maximum number of daily sessions before the
                            scheduler stops (0 = unlimited).
    """

    runtime_config: PaperRuntimeConfig = field(default_factory=PaperRuntimeConfig)
    warmup_minutes: float = 30.0
    after_hours_grace_minutes: float = 15.0
    poll_during_close_seconds: float = 300.0
    max_daily_sessions: int = 0  # 0 = unlimited


class PaperScheduler:
    """Day-by-day scheduler that runs ``PaperRuntime`` on trading days.

    Typical usage::

        scheduler = PaperScheduler(config, strategy=my_strategy)
        scheduler.start()
    """

    def __init__(
        self,
        config: PaperSchedulerConfig | None = None,
        strategy: Strategy | None = None,
        calendar: USEquityCalendar | None = None,
    ) -> None:
        self.config = config or PaperSchedulerConfig()
        self.strategy = strategy
        self.calendar = calendar or USEquityCalendar.with_holidays()
        self.clock = SessionClock(self.calendar)
        self.sessions_run: int = 0
        self._running: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Enter the daily scheduling loop.

        Blocks until ``max_daily_sessions`` is reached or an unrecoverable
        kill-switch trigger stops the scheduler.
        """
        self._running = True
        _logger.info(
            "PaperScheduler started: warmup=%.0fm grace=%.0fm max_sessions=%d",
            self.config.warmup_minutes,
            self.config.after_hours_grace_minutes,
            self.config.max_daily_sessions,
        )

        while self._running:
            # 1. Check max daily sessions first so a completed session
            #    does not re-enter _wait_for_market_open after the limit
            #    is reached.
            if self._max_sessions_reached():
                _logger.info("max_daily_sessions (%d) reached", self.config.max_daily_sessions)
                break

            # 2. Wait until the market should be running (includes warmup)
            if not self._wait_for_market_open():
                _logger.info("Scheduler stopping (wait for market open returned False)")
                break

            # 3. Create and run a PaperRuntime session
            today = utc_now().astimezone(PaperScheduler._et()).date()
            _logger.info("Starting paper session for %s", today.isoformat())

            runtime = PaperRuntime(config=self.config.runtime_config)
            try:
                runtime.bootstrap(strategy=self.strategy)
                runtime.run_market_session()
                runtime.on_session_close()
            except Exception:
                _logger.exception("Unhandled error in paper session for %s", today.isoformat())
            finally:
                try:
                    runtime.shutdown()
                except Exception:
                    _logger.exception("Error during runtime shutdown")

            self.sessions_run += 1

            # 4. Wait until the next trading day
            if not self._max_sessions_reached():
                self._wait_for_next_day()

        _logger.info("PaperScheduler stopped after %d sessions", self.sessions_run)

    def stop(self) -> None:
        """Signal the scheduler loop to stop after the current session."""
        self._running = False
        _logger.info("PaperScheduler stop requested")

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    def _wait_for_market_open(self) -> bool:
        """Block until the market opens (within warmup window).

        Returns False if the scheduler should stop (stop requested).
        """
        while self._running:
            now = utc_now()
            if self.clock.should_be_running(now, warmup_minutes=self.config.warmup_minutes):
                return True

            # Log how long until next open
            next_open_seconds = self.clock.time_until_next_session(now)
            if next_open_seconds < float("inf"):
                next_open_minutes = next_open_seconds / 60.0
                _logger.debug(
                    "Market closed; next open in %.1f minutes. Polling...",
                    next_open_minutes,
                )
            else:
                _logger.debug("No upcoming session found; polling...")

            self._time_sleep(self.config.poll_during_close_seconds)

        return False

    def _wait_for_next_day(self) -> None:
        """Block until the next trading day's market open window.

        Handles weekends, holidays, and overnight periods.
        """
        while self._running:
            now = utc_now()
            # After close with grace -> wait full day, then wait again for open
            if self.clock.should_shutdown(now, after_hours_grace_minutes=self.config.after_hours_grace_minutes):
                # Market has been closed long enough — figure out when next
                # trading day starts
                now_et = now.astimezone(PaperScheduler._et())
                today = now_et.date()

                # Find the next trading day
                next_day = self.calendar.next_trading_day(today)
                _logger.debug("Next trading day: %s", next_day.isoformat())

                # Sleep until we are close to next open
                next_open = datetime.combine(
                    next_day,
                    time(9, 30),
                    tzinfo=PaperScheduler._et(),
                )
                now_et_dt = now_et
                sleep_seconds = max(
                    self.config.poll_during_close_seconds,
                    (next_open - now_et_dt).total_seconds()
                    - self.config.warmup_minutes * 60.0
                    - 60.0,  # 1-minute buffer
                )
                _logger.info(
                    "Waiting until next trading day %s (~%.0f minutes)",
                    next_day.isoformat(),
                    sleep_seconds / 60.0,
                )
                self._time_sleep(sleep_seconds)

                # Now loop back to _wait_for_market_open
                return

            # Market still in after-hours grace period
            self._time_sleep(self.config.poll_during_close_seconds)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _max_sessions_reached(self) -> bool:
        return 0 < self.config.max_daily_sessions <= self.sessions_run

    @staticmethod
    def _time_sleep(seconds: float) -> None:
        _time.sleep(seconds)

    @staticmethod
    def _et():
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/New_York")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a snapshot of scheduler state."""
        return {
            "running": self._running,
            "sessions_run": self.sessions_run,
            "max_daily_sessions": self.config.max_daily_sessions,
            "warmup_minutes": self.config.warmup_minutes,
            "after_hours_grace_minutes": self.config.after_hours_grace_minutes,
        }
