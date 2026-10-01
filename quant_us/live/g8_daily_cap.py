"""G8 Daily Trading Cap.

Tracks per-day trading limits within a Supervised Micro Live Session.
Limits: max orders per day, max notional per day, max loss per day.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g8_daily_cap")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# DailyTradingCap
# ---------------------------------------------------------------------------


@dataclass
class DailyTradingCap:
    cap_id: str
    session_id: str
    date: str  # YYYY-MM-DD
    max_orders_today: int = 1
    orders_submitted_today: int = 0
    max_notional_today: float = 100.0
    notional_used_today: float = 0.0
    max_loss_today: float = 10.0
    realized_pnl_today: float = 0.0
    status: str = "PASS"  # PASS|BLOCKED|DAILY_LIMIT_REACHED

    def to_dict(self) -> dict[str, Any]:
        return {
            "cap_id": self.cap_id,
            "session_id": self.session_id,
            "date": self.date,
            "max_orders_today": self.max_orders_today,
            "orders_submitted_today": self.orders_submitted_today,
            "max_notional_today": self.max_notional_today,
            "notional_used_today": self.notional_used_today,
            "max_loss_today": self.max_loss_today,
            "realized_pnl_today": self.realized_pnl_today,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DailyTradingCap":
        return cls(
            cap_id=data.get("cap_id", ""),
            session_id=data.get("session_id", ""),
            date=data.get("date", ""),
            max_orders_today=data.get("max_orders_today", 1),
            orders_submitted_today=data.get("orders_submitted_today", 0),
            max_notional_today=data.get("max_notional_today", 100.0),
            notional_used_today=data.get("notional_used_today", 0.0),
            max_loss_today=data.get("max_loss_today", 10.0),
            realized_pnl_today=data.get("realized_pnl_today", 0.0),
            status=data.get("status", "PASS"),
        )


# ---------------------------------------------------------------------------
# DailyTradingCapManager
# ---------------------------------------------------------------------------


class DailyTradingCapManager:
    """Manages daily trading caps for sessions.

    Loads and persists per-session, per-date cap files at:
        data/live_pilot/session/daily_caps/{session_id}_{date}.json
    """

    def __init__(self, data_root: str = "data") -> None:
        self.cap_dir = Path(data_root) / "live_pilot" / "session" / "daily_caps"
        self.cap_dir.mkdir(parents=True, exist_ok=True)

    def check(self, session_id: str, date: str, proposed_notional: float = 0.0) -> tuple[bool, str]:
        """Check if a new trade is allowed today.

        Returns (allowed, reason).
        """
        cap = self.load(session_id, date)
        if cap is None:
            # No cap yet today — always allowed
            return True, ""

        # Check order count
        if cap.orders_submitted_today >= cap.max_orders_today:
            return False, "max_orders_per_day_exceeded"

        # Check notional
        if cap.notional_used_today + proposed_notional > cap.max_notional_today:
            return False, "daily_notional_exceeded"

        # Check loss
        if cap.realized_pnl_today <= -cap.max_loss_today:
            return False, "daily_loss_exceeded"

        return True, ""

    def record_order(
        self,
        session_id: str,
        date: str,
        notional: float,
        pnl: float = 0.0,
    ) -> DailyTradingCap:
        """Record an executed order against daily limits."""
        cap = self.get_or_create(session_id, date)
        cap.orders_submitted_today += 1
        cap.notional_used_today += notional
        cap.realized_pnl_today += pnl

        # Re-evaluate status
        if (cap.orders_submitted_today >= cap.max_orders_today
                or cap.notional_used_today >= cap.max_notional_today
                or cap.realized_pnl_today <= -cap.max_loss_today):
            cap.status = "DAILY_LIMIT_REACHED"
        else:
            cap.status = "PASS"

        self._save(cap)
        _logger.info(
            "Daily cap updated: session=%s date=%s orders=%d/%d notional=%.2f/%.2f",
            session_id, date,
            cap.orders_submitted_today, cap.max_orders_today,
            cap.notional_used_today, cap.max_notional_today,
        )
        return cap

    def get_or_create(self, session_id: str, date: str) -> DailyTradingCap:
        """Load existing cap or create a fresh one for the given session+date."""
        existing = self.load(session_id, date)
        if existing is not None:
            return existing
        from quant_us.core.types import new_id
        cap = DailyTradingCap(
            cap_id=new_id("dcap"),
            session_id=session_id,
            date=date,
        )
        self._save(cap)
        _logger.info("New daily cap created: session=%s date=%s", session_id, date)
        return cap

    def load(self, session_id: str, date: str) -> DailyTradingCap | None:
        """Load daily cap for a session on a given date."""
        path = self._cap_path(session_id, date)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return DailyTradingCap.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load daily cap %s: %s", path, exc)
            return None

    def delete(self, session_id: str, date: str) -> None:
        path = self._cap_path(session_id, date)
        if path.exists():
            path.unlink()

    def _cap_path(self, session_id: str, date: str) -> Path:
        return self.cap_dir / f"{session_id}_{date}.json"

    def _save(self, cap: DailyTradingCap) -> None:
        path = self._cap_path(cap.session_id, cap.date)
        path.write_text(json.dumps(cap.to_dict(), indent=2, default=str))
