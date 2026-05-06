"""Tests for LiveStateStore and related dataclasses."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from quant_us.core.clock import utc_now
from quant_us.live.live_state_store import (
    DayResult,
    LiveSessionRunner,
    LiveSessionState,
    LiveStateStore,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def tmp_state_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_state.json")


@pytest.fixture
def store(tmp_state_path: str) -> LiveStateStore:
    return LiveStateStore(tmp_state_path)


@pytest.fixture
def sample_state() -> LiveSessionState:
    return LiveSessionState(
        session_id="session_test_1234",
        started_at=utc_now(),
        last_cycle_at=utc_now(),
        state=LiveSessionRunner.RUNNING,
        daily_results=[
            DayResult(
                date=date(2026, 4, 1),
                equity_start=100_000.0,
                equity_end=101_200.0,
                pnl=1200.0,
                orders_submitted=5,
                orders_filled=4,
                reconciliation_passed=True,
                errors=[],
            ),
            DayResult(
                date=date(2026, 4, 2),
                equity_start=101_200.0,
                equity_end=102_500.0,
                pnl=1300.0,
                orders_submitted=3,
                orders_filled=3,
                reconciliation_passed=True,
                errors=[],
            ),
            DayResult(
                date=date(2026, 4, 3),
                equity_start=102_500.0,
                equity_end=101_800.0,
                pnl=-700.0,
                orders_submitted=4,
                orders_filled=2,
                reconciliation_passed=False,
                errors=["slippage_exceeded"],
            ),
        ],
        kill_switch_triggered=False,
        last_bar_timestamps={
            "SPY": datetime(2026, 4, 3, 20, 0, 0, tzinfo=timezone.utc),
            "QQQ": datetime(2026, 4, 3, 19, 59, 0, tzinfo=timezone.utc),
        },
    )


# ===========================================================================
# LiveSessionState serialisation round-trip
# ===========================================================================


class TestLiveSessionStateRoundTrip:
    def test_round_trip(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """save_state then load_state returns an equivalent object."""
        store.save_state(sample_state)
        loaded = store.load_state()
        assert loaded is not None
        assert loaded.session_id == sample_state.session_id
        assert loaded.state == LiveSessionRunner.RUNNING
        assert loaded.kill_switch_triggered == sample_state.kill_switch_triggered
        assert len(loaded.daily_results) == len(sample_state.daily_results)
        assert len(loaded.last_bar_timestamps) == len(sample_state.last_bar_timestamps)
        assert loaded.last_bar_timestamps["SPY"] == sample_state.last_bar_timestamps["SPY"]

    def test_round_trip_daily_results(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """DayResult fields survive a save/load round trip."""
        store.save_state(sample_state)
        loaded = store.load_state()
        assert loaded is not None
        clean_day = loaded.daily_results[0]
        assert clean_day.date == date(2026, 4, 1)
        assert clean_day.equity_start == 100_000.0
        assert clean_day.pnl == 1200.0
        assert clean_day.reconciliation_passed is True
        assert clean_day.errors == []
        dirty_day = loaded.daily_results[2]
        assert dirty_day.reconciliation_passed is False
        assert dirty_day.errors == ["slippage_exceeded"]

    def test_load_nonexistent(self, tmp_state_path: str) -> None:
        """load_state returns None when the file does not exist."""
        store = LiveStateStore(tmp_state_path)
        assert store.load_state() is None


# ===========================================================================
# LiveStateStore day-level operations
# ===========================================================================


class TestLiveStateStoreDayOperations:
    def test_mark_day_complete_new(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """mark_day_complete appends a new day result."""
        store.save_state(sample_state)
        new_result = DayResult(
            date=date(2026, 4, 4),
            equity_start=101_800.0,
            equity_end=103_000.0,
            pnl=1200.0,
            orders_submitted=2,
            orders_filled=2,
            reconciliation_passed=True,
            errors=[],
        )
        store.mark_day_complete(date(2026, 4, 4), new_result)
        loaded = store.load_state()
        assert loaded is not None
        assert len(loaded.daily_results) == 4
        assert loaded.daily_results[-1].date == date(2026, 4, 4)

    def test_mark_day_complete_replace(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """mark_day_complete replaces an existing entry for the same date."""
        store.save_state(sample_state)
        replacement = DayResult(
            date=date(2026, 4, 1),
            equity_start=100_000.0,
            equity_end=105_000.0,
            pnl=5000.0,
            orders_submitted=10,
            orders_filled=10,
            reconciliation_passed=True,
            errors=[],
        )
        store.mark_day_complete(date(2026, 4, 1), replacement)
        loaded = store.load_state()
        assert loaded is not None
        assert len(loaded.daily_results) == 3  # same count, not appended
        matching = [dr for dr in loaded.daily_results if dr.date == date(2026, 4, 1)]
        assert len(matching) == 1
        assert matching[0].pnl == 5000.0

    def test_get_days_completed(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """get_days_completed returns the correct count."""
        store.save_state(sample_state)
        assert store.get_days_completed() == 3

    def test_get_days_completed_empty(self, store: LiveStateStore) -> None:
        """get_days_completed returns 0 when no state exists."""
        assert store.get_days_completed() == 0

    def test_is_day_complete(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """is_day_complete returns True for existing days, False otherwise."""
        store.save_state(sample_state)
        assert store.is_day_complete(date(2026, 4, 1)) is True
        assert store.is_day_complete(date(2026, 4, 2)) is True
        assert store.is_day_complete(date(2026, 4, 4)) is False

    def test_is_day_complete_no_state(self, store: LiveStateStore) -> None:
        """is_day_complete returns False when no state is loaded."""
        assert store.is_day_complete(date(2026, 4, 1)) is False


# ===========================================================================
# Consecutive clean days
# ===========================================================================


class TestConsecutiveCleanDays:
    def test_consecutive_clean_days(self, store: LiveStateStore, sample_state: LiveSessionState) -> None:
        """get_consecutive_clean_days counts backwards from most recent day,
        stopping at the first dirty day."""
        # 3 days: clean(day1), clean(day2), dirty(day3) -> 0 (last is dirty)
        assert store.get_consecutive_clean_days() == 0

    def test_consecutive_clean_days_all_clean(self, store: LiveStateStore) -> None:
        """All clean days in order."""
        state = LiveSessionState(
            session_id="test",
            started_at=utc_now(),
            last_cycle_at=utc_now(),
            state=LiveSessionRunner.RUNNING,
            daily_results=[
                DayResult(date(2026, 4, 1), 100_000, 101_000, 1000, 2, 2, True, []),
                DayResult(date(2026, 4, 2), 101_000, 102_000, 1000, 2, 2, True, []),
                DayResult(date(2026, 4, 3), 102_000, 103_000, 1000, 2, 2, True, []),
            ],
        )
        store.save_state(state)
        assert store.get_consecutive_clean_days() == 3

    def test_consecutive_clean_days_partial(self, store: LiveStateStore) -> None:
        """Only the trailing clean days count."""
        state = LiveSessionState(
            session_id="test",
            started_at=utc_now(),
            last_cycle_at=utc_now(),
            state=LiveSessionRunner.RUNNING,
            daily_results=[
                DayResult(date(2026, 4, 1), 100_000, 99_000, -1000, 2, 2, False, ["loss"]),
                DayResult(date(2026, 4, 2), 99_000, 100_000, 1000, 2, 2, True, []),
                DayResult(date(2026, 4, 3), 100_000, 101_000, 1000, 2, 2, True, []),
            ],
        )
        store.save_state(state)
        assert store.get_consecutive_clean_days() == 2  # day1 is dirty, day2+3 are clean

    def test_consecutive_clean_days_no_state(self, store: LiveStateStore) -> None:
        """Empty store returns 0."""
        assert store.get_consecutive_clean_days() == 0


# ===========================================================================
# Atomic write
# ===========================================================================


class TestAtomicWrite:
    def test_atomic_write_no_corruption(self, tmp_state_path: str) -> None:
        """save_state produces a valid JSON file at the target path."""
        store = LiveStateStore(tmp_state_path)
        state = LiveSessionState(
            session_id="atomic_test",
            started_at=utc_now(),
            last_cycle_at=utc_now(),
            state=LiveSessionRunner.RUNNING,
        )
        store.save_state(state)
        # Verify the file exists and is valid JSON
        path = Path(tmp_state_path)
        assert path.exists()
        raw = json.loads(path.read_text())
        assert raw["session_id"] == "atomic_test"

    def test_load_corrupted_state(self, tmp_state_path: str) -> None:
        """Loading a corrupt JSON file returns None."""
        path = Path(tmp_state_path)
        path.write_text("{invalid json!!!}", encoding="utf-8")
        store = LiveStateStore(tmp_state_path)
        assert store.load_state() is None


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_empty_daily_results(self, store: LiveStateStore) -> None:
        """State with no daily_results round-trips correctly."""
        state = LiveSessionState(
            session_id="empty",
            started_at=utc_now(),
            last_cycle_at=utc_now(),
            state=LiveSessionRunner.RUNNING,
        )
        store.save_state(state)
        loaded = store.load_state()
        assert loaded is not None
        assert loaded.daily_results == []

    def test_empty_bar_timestamps(self, store: LiveStateStore) -> None:
        """State with no bar timestamps round-trips correctly."""
        state = LiveSessionState(
            session_id="no_bars",
            started_at=utc_now(),
            last_cycle_at=utc_now(),
            state=LiveSessionRunner.RUNNING,
        )
        store.save_state(state)
        loaded = store.load_state()
        assert loaded is not None
        assert loaded.last_bar_timestamps == {}

    def test_kill_switch_triggered_flag(self, store: LiveStateStore) -> None:
        """kill_switch_triggered flag survives round-trip."""
        state = LiveSessionState(
            session_id="ks",
            started_at=utc_now(),
            last_cycle_at=utc_now(),
            state=LiveSessionRunner.RUNNING,
            kill_switch_triggered=True,
        )
        store.save_state(state)
        loaded = store.load_state()
        assert loaded is not None
        assert loaded.kill_switch_triggered is True

    def test_mark_day_complete_no_state(self, store: LiveStateStore) -> None:
        """mark_day_complete does not crash when no state is saved."""
        result = DayResult(
            date=date(2026, 4, 1),
            equity_start=100_000.0,
            equity_end=101_000.0,
            pnl=1000.0,
            orders_submitted=2,
            orders_filled=2,
            reconciliation_passed=True,
            errors=[],
        )
        # Should not raise, just log a warning
        store.mark_day_complete(date(2026, 4, 1), result)
        assert store.load_state() is None
