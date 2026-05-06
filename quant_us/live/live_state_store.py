"""Persistent state management for live trading sessions.

Stores session start/end times, daily P&L tracking, order counts by status,
kill switch state, reconciliation status per day, idempotency keys, and
last processed bar timestamps per symbol.

Supports recovery across process restarts via atomic JSON writes
(write to temp file, then rename).

Usage::

    store = LiveStateStore("data/live_state.json")

    # Save on every poll cycle
    store.save_state(current_state)

    # Mark end-of-day
    result = DayResult(date=today, ...)
    store.mark_day_complete(today, result)

    # Recover on restart
    prev_state = store.load_state()
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from quant_us.core.clock import ensure_utc

_logger = logging.getLogger("live_state_store")


class LiveSessionRunner(str, Enum):
    """Tracked session state for persistence and recovery."""

    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    ERROR = "error"


@dataclass
class DayResult:
    """Result for a single trading day within a live or shadow-live session.

    Attributes:
        date: Trading date.
        equity_start: Equity value at start of the session day.
        equity_end: Equity value at end of the session day (or last poll).
        pnl: Realised + unrealised P&L for the day.
        orders_submitted: Number of orders submitted to broker.
        orders_filled: Number of orders fully filled.
        reconciliation_passed: True when all four-dimension checks passed.
        errors: Human-readable error messages accumulated during the day.
    """

    date: date
    equity_start: float
    equity_end: float
    pnl: float
    orders_submitted: int
    orders_filled: int
    reconciliation_passed: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class LiveSessionState:
    """Complete snapshot of a live trading session.

    Attributes:
        session_id: Unique session identifier.
        started_at: UTC timestamp when the session began.
        last_cycle_at: UTC timestamp of the most recent poll cycle.
        state: Current lifecycle state of the runner.
        daily_results: Ordered list of day-level results.
        kill_switch_triggered: Whether the kill switch has fired.
        last_bar_timestamps: Per-symbol UTC datetime of the last processed bar.
    """

    session_id: str
    started_at: datetime
    last_cycle_at: datetime
    state: LiveSessionRunner
    daily_results: list[DayResult] = field(default_factory=list)
    kill_switch_triggered: bool = False
    last_bar_timestamps: dict[str, datetime] = field(default_factory=dict)


class LiveStateStore:
    """Persists and recovers live trading session state across restarts.

    Uses atomic file writes (write to temp file, then rename) to prevent
    corruption on crash.  All datetime values are serialised as ISO-8601
    strings with timezone information.
    """

    def __init__(self, state_path: str | Path = "data/live_state.json") -> None:
        self._path = Path(state_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger("live_state_store")

    # ------------------------------------------------------------------
    # Full-state operations
    # ------------------------------------------------------------------

    def save_state(self, state: LiveSessionState) -> None:
        """Persist the full session state to disk (atomic write)."""
        data = _state_to_jsonable(state)
        self._atomic_write(data)

    def load_state(self) -> LiveSessionState | None:
        """Deserialize session state from disk.

        Returns ``None`` when the file does not exist or is corrupt.
        Malformed files are logged and return ``None`` rather than raising.
        """
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return _state_from_jsonable(raw)
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
            self._logger.warning(
                "Failed to load state from %s: %s", self._path, exc,
            )
            return None

    # ------------------------------------------------------------------
    # Day-level operations
    # ------------------------------------------------------------------

    def mark_day_complete(self, date_: date, result: DayResult) -> None:
        """Record a completed day result in the persisted state.

        If an entry for *date_* already exists it is replaced in-place.
        """
        state = self.load_state()
        if state is None:
            self._logger.warning("No state loaded; cannot mark day %s complete", date_)
            return
        for idx, dr in enumerate(state.daily_results):
            if dr.date == date_:
                state.daily_results[idx] = result
                break
        else:
            state.daily_results.append(result)
        self.save_state(state)

    def get_days_completed(self) -> int:
        """Return the total number of completed trading days on record."""
        state = self.load_state()
        return len(state.daily_results) if state is not None else 0

    def is_day_complete(self, date_: date) -> bool:
        """Return ``True`` when *date_* already has a ``DayResult``."""
        state = self.load_state()
        if state is None:
            return False
        return any(dr.date == date_ for dr in state.daily_results)

    def get_consecutive_clean_days(self) -> int:
        """Return the count of consecutive clean days (reconciliation passed,
        no errors).

        Counts backwards from the most recent day.  A "dirty" day
        (reconciliation failed, or errors recorded) resets the counter to
        zero.
        """
        state = self.load_state()
        if state is None:
            return 0
        count = 0
        for dr in reversed(state.daily_results):
            if dr.reconciliation_passed and not dr.errors:
                count += 1
            else:
                break
        return count

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _atomic_write(self, data: dict[str, Any]) -> None:
        """Atomically write JSON via temp-file rename.

        Writes to a temporary file in the same directory, then renames
        (atomic on POSIX).  The temp file is cleaned up in the ``finally``
        block in case of failure.
        """
        tmp_path = self._path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            tmp_path.replace(self._path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def new_session_id() -> str:
        """Generate a unique session identifier."""
        return f"session_{uuid4().hex[:16]}"


# ------------------------------------------------------------------
# JSON serialisation helpers
# ------------------------------------------------------------------


def _state_to_jsonable(state: LiveSessionState) -> dict[str, Any]:
    """Convert a ``LiveSessionState`` to a plain JSON-compatible dict.

    All ``datetime`` and ``date`` values are converted to ISO-8601 strings.
    Enum values are converted to their string representation.
    """
    return {
        "session_id": state.session_id,
        "started_at": state.started_at.isoformat(),
        "last_cycle_at": state.last_cycle_at.isoformat(),
        "state": state.state.value if isinstance(state.state, Enum) else str(state.state),
        "kill_switch_triggered": bool(state.kill_switch_triggered),
        "daily_results": [
            {
                "date": dr.date.isoformat(),
                "equity_start": float(dr.equity_start),
                "equity_end": float(dr.equity_end),
                "pnl": float(dr.pnl),
                "orders_submitted": int(dr.orders_submitted),
                "orders_filled": int(dr.orders_filled),
                "reconciliation_passed": bool(dr.reconciliation_passed),
                "errors": [str(e) for e in dr.errors],
            }
            for dr in state.daily_results
        ],
        "last_bar_timestamps": {
            str(sym): ts.isoformat() for sym, ts in state.last_bar_timestamps.items()
        },
    }


def _state_from_jsonable(data: dict[str, Any]) -> LiveSessionState:
    """Reconstruct a ``LiveSessionState`` from a JSON-deserialised dict.

    Raises ``KeyError`` or ``ValueError`` on malformed input so callers
    can catch and handle corruption gracefully.
    """
    daily_results_raw: list[dict[str, Any]] = data.get("daily_results", [])
    daily_results = [
        DayResult(
            date=_parse_date(dr["date"]),
            equity_start=float(dr.get("equity_start", 0.0)),
            equity_end=float(dr.get("equity_end", 0.0)),
            pnl=float(dr.get("pnl", 0.0)),
            orders_submitted=int(dr.get("orders_submitted", 0)),
            orders_filled=int(dr.get("orders_filled", 0)),
            reconciliation_passed=bool(dr.get("reconciliation_passed", True)),
            errors=[str(e) for e in dr.get("errors", [])],
        )
        for dr in daily_results_raw
    ]

    last_bar_timestamps_raw: dict[str, str] = data.get("last_bar_timestamps", {})
    last_bar_timestamps: dict[str, datetime] = {}
    for sym, ts_str in last_bar_timestamps_raw.items():
        try:
            last_bar_timestamps[str(sym)] = _parse_datetime(ts_str)
        except (ValueError, TypeError):
            _logger.warning("Skipping malformed bar timestamp for %s: %s", sym, ts_str)

    return LiveSessionState(
        session_id=str(data["session_id"]),
        started_at=_parse_datetime(data["started_at"]),
        last_cycle_at=_parse_datetime(data["last_cycle_at"]),
        state=LiveSessionRunner(str(data["state"])),
        daily_results=daily_results,
        kill_switch_triggered=bool(data.get("kill_switch_triggered", False)),
        last_bar_timestamps=last_bar_timestamps,
    )


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime string, ensuring UTC timezone."""
    parsed = datetime.fromisoformat(str(value))
    return ensure_utc(parsed)


def _parse_date(value: str) -> date:
    """Parse an ISO-8601 date string."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))
