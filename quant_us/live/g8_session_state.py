"""G8 Session Runtime State.

Tracks the lifecycle state of a Supervised Micro Live Session.
States: DRAFT -> ARMED -> ACTIVE_MANUAL_SUPERVISION -> FROZEN -> (resume loop) -> COMPLETED|TERMINATED

Every order freezes the session. Manual review + resume required to continue.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g8_session_state")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SessionStatus constants
# ---------------------------------------------------------------------------


class SessionStatus:
    DRAFT = "DRAFT"
    ARMED = "ARMED"
    ACTIVE_MANUAL_SUPERVISION = "ACTIVE_MANUAL_SUPERVISION"
    PAUSED = "PAUSED"
    FROZEN = "FROZEN"  # after each order
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


VALID_TRANSITIONS: dict[str, set[str]] = {
    SessionStatus.DRAFT: {SessionStatus.ARMED, SessionStatus.TERMINATED},
    SessionStatus.ARMED: {SessionStatus.ACTIVE_MANUAL_SUPERVISION, SessionStatus.DRAFT, SessionStatus.TERMINATED},
    SessionStatus.ACTIVE_MANUAL_SUPERVISION: {SessionStatus.FROZEN, SessionStatus.PAUSED, SessionStatus.TERMINATED},
    SessionStatus.PAUSED: {SessionStatus.ACTIVE_MANUAL_SUPERVISION, SessionStatus.TERMINATED},
    SessionStatus.FROZEN: {SessionStatus.ACTIVE_MANUAL_SUPERVISION, SessionStatus.COMPLETED, SessionStatus.TERMINATED},
    SessionStatus.COMPLETED: set(),
    SessionStatus.TERMINATED: set(),
}


# ---------------------------------------------------------------------------
# SessionRuntimeState
# ---------------------------------------------------------------------------


@dataclass
class SessionRuntimeState:
    session_id: str
    promotion_id: str
    approval_id: str = ""
    envelope_id: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    symbols: list[str] = field(default_factory=list)
    started_at: str = ""
    updated_at: str = ""
    status: str = SessionStatus.DRAFT
    max_orders_per_session: int = 3
    max_orders_per_day: int = 1
    max_session_notional: float = 300.0
    max_session_loss: float = 10.0
    completed_order_count: int = 0
    submitted_order_count: int = 0
    real_submit_count: int = 0
    incident_count: int = 0
    recon_fail_count: int = 0
    emergency_stop_count: int = 0
    manual_review_required: bool = True
    order_ticket_ids: list[str] = field(default_factory=list)
    current_freeze_reason: str = ""
    terminated_reason: str = ""

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = _utc_now().isoformat()
        if not self.updated_at:
            self.updated_at = self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "promotion_id": self.promotion_id,
            "approval_id": self.approval_id,
            "envelope_id": self.envelope_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbols": self.symbols,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "max_orders_per_session": self.max_orders_per_session,
            "max_orders_per_day": self.max_orders_per_day,
            "max_session_notional": self.max_session_notional,
            "max_session_loss": self.max_session_loss,
            "completed_order_count": self.completed_order_count,
            "submitted_order_count": self.submitted_order_count,
            "real_submit_count": self.real_submit_count,
            "incident_count": self.incident_count,
            "recon_fail_count": self.recon_fail_count,
            "emergency_stop_count": self.emergency_stop_count,
            "manual_review_required": self.manual_review_required,
            "order_ticket_ids": self.order_ticket_ids,
            "current_freeze_reason": self.current_freeze_reason,
            "terminated_reason": self.terminated_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionRuntimeState":
        return cls(
            session_id=data.get("session_id", ""),
            promotion_id=data.get("promotion_id", ""),
            approval_id=data.get("approval_id", ""),
            envelope_id=data.get("envelope_id", ""),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            symbols=data.get("symbols", []),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
            status=data.get("status", SessionStatus.DRAFT),
            max_orders_per_session=data.get("max_orders_per_session", 3),
            max_orders_per_day=data.get("max_orders_per_day", 1),
            max_session_notional=data.get("max_session_notional", 300.0),
            max_session_loss=data.get("max_session_loss", 10.0),
            completed_order_count=data.get("completed_order_count", 0),
            submitted_order_count=data.get("submitted_order_count", 0),
            real_submit_count=data.get("real_submit_count", 0),
            incident_count=data.get("incident_count", 0),
            recon_fail_count=data.get("recon_fail_count", 0),
            emergency_stop_count=data.get("emergency_stop_count", 0),
            manual_review_required=data.get("manual_review_required", True),
            order_ticket_ids=data.get("order_ticket_ids", []),
            current_freeze_reason=data.get("current_freeze_reason", ""),
            terminated_reason=data.get("terminated_reason", ""),
        )


# ---------------------------------------------------------------------------
# SessionRuntimeStateManager
# ---------------------------------------------------------------------------


class SessionRuntimeStateManager:
    """Manages session runtime state persistence and lifecycle transitions.

    Sessions are stored at:
        data/live_pilot/session/sessions/{session_id}.json

    All state transitions are logged to:
        data/live_pilot/session/session_audit.jsonl
    """

    def __init__(self, data_root: str = "data") -> None:
        self.session_dir = Path(data_root) / "live_pilot" / "session" / "sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = Path(data_root) / "live_pilot" / "session" / "session_audit.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def create(self, promotion_id: str, **kwargs: Any) -> SessionRuntimeState:
        """Create a new session in DRAFT status."""
        from quant_us.core.types import new_id

        session_id = kwargs.pop("session_id", new_id("g8_session"))
        state = SessionRuntimeState(
            session_id=session_id,
            promotion_id=promotion_id,
            **kwargs,
        )
        self._save(state)
        self._audit("CREATE", session_id, {"promotion_id": promotion_id, "status": state.status})
        _logger.info("Session created: %s promotion=%s", session_id, promotion_id)
        return state

    def arm(self, session_id: str) -> SessionRuntimeState:
        """Arm a session (DRAFT -> ARMED). Requires manual action."""
        state = self._require_load(session_id)
        if state.status != SessionStatus.DRAFT:
            raise ValueError(
                f"Cannot arm session in status {state.status}. Must be DRAFT."
            )
        state.status = SessionStatus.ARMED
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("ARM", session_id, {"status": state.status})
        _logger.info("Session armed: %s", session_id)
        return state

    def activate(self, session_id: str) -> SessionRuntimeState:
        """Activate a session (ARMED -> ACTIVE_MANUAL_SUPERVISION)."""
        state = self._require_load(session_id)
        if state.status != SessionStatus.ARMED:
            raise ValueError(
                f"Cannot activate session in status {state.status}. Must be ARMED."
            )
        state.status = SessionStatus.ACTIVE_MANUAL_SUPERVISION
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("ACTIVATE", session_id, {"status": state.status})
        _logger.info("Session activated: %s", session_id)
        return state

    def freeze(self, session_id: str, reason: str = "ORDER_SUBMITTED") -> SessionRuntimeState:
        """Freeze session after an order (ACTIVE_MANUAL_SUPERVISION -> FROZEN)."""
        state = self._require_load(session_id)
        if state.status != SessionStatus.ACTIVE_MANUAL_SUPERVISION:
            raise ValueError(
                f"Cannot freeze session in status {state.status}. "
                f"Must be ACTIVE_MANUAL_SUPERVISION."
            )
        state.status = SessionStatus.FROZEN
        state.current_freeze_reason = reason
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("FREEZE", session_id, {"reason": reason})
        _logger.info("Session frozen: %s reason=%s", session_id, reason)
        return state

    def resume(self, session_id: str, reason: str = "POST_TRADE_REVIEW_COMPLETE") -> SessionRuntimeState:
        """Resume session after post-trade review (FROZEN -> ACTIVE_MANUAL_SUPERVISION)."""
        state = self._require_load(session_id)
        if state.status != SessionStatus.FROZEN:
            raise ValueError(
                f"Cannot resume session in status {state.status}. Must be FROZEN."
            )
        state.status = SessionStatus.ACTIVE_MANUAL_SUPERVISION
        state.current_freeze_reason = ""
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("RESUME", session_id, {"reason": reason})
        _logger.info("Session resumed: %s reason=%s", session_id, reason)
        return state

    def pause(self, session_id: str) -> SessionRuntimeState:
        """Pause session (ACTIVE_MANUAL_SUPERVISION -> PAUSED)."""
        state = self._require_load(session_id)
        if state.status not in (SessionStatus.ACTIVE_MANUAL_SUPERVISION, SessionStatus.FROZEN):
            raise ValueError(
                f"Cannot pause session in status {state.status}. "
                f"Must be ACTIVE_MANUAL_SUPERVISION or FROZEN."
            )
        state.status = SessionStatus.PAUSED
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("PAUSE", session_id, {"status": state.status})
        _logger.info("Session paused: %s", session_id)
        return state

    def terminate(self, session_id: str, reason: str) -> SessionRuntimeState:
        """Terminate session (any state -> TERMINATED)."""
        state = self._require_load(session_id)
        if state.status == SessionStatus.TERMINATED:
            raise ValueError(f"Session already terminated: {session_id}")
        state.status = SessionStatus.TERMINATED
        state.terminated_reason = reason
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("TERMINATE", session_id, {"reason": reason})
        _logger.warning("Session terminated: %s reason=%s", session_id, reason)
        return state

    def complete(self, session_id: str) -> SessionRuntimeState:
        """Complete session (FROZEN -> COMPLETED)."""
        state = self._require_load(session_id)
        if state.status != SessionStatus.FROZEN:
            raise ValueError(
                f"Cannot complete session in status {state.status}. Must be FROZEN."
            )
        state.status = SessionStatus.COMPLETED
        state.updated_at = _utc_now().isoformat()
        self._save(state)
        self._audit("COMPLETE", session_id, {"status": state.status})
        _logger.info("Session completed: %s", session_id)
        return state

    def load(self, session_id: str) -> SessionRuntimeState | None:
        """Load session state by ID."""
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return SessionRuntimeState.from_dict(data)
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load session %s: %s", session_id, exc)
            return None

    def status(self, session_id: str) -> dict[str, Any]:
        """Return a summary dict of session status."""
        state = self.load(session_id)
        if state is None:
            return {"session_id": session_id, "status": "NOT_FOUND", "exists": False}
        return {
            "session_id": state.session_id,
            "promotion_id": state.promotion_id,
            "status": state.status,
            "started_at": state.started_at,
            "updated_at": state.updated_at,
            "submitted_order_count": state.submitted_order_count,
            "completed_order_count": state.completed_order_count,
            "real_submit_count": state.real_submit_count,
            "incident_count": state.incident_count,
            "current_freeze_reason": state.current_freeze_reason,
            "manual_review_required": state.manual_review_required,
            "order_ticket_ids": state.order_ticket_ids,
            "exists": True,
        }

    def _session_path(self, session_id: str) -> Path:
        return self.session_dir / f"{session_id}.json"

    def _save(self, state: SessionRuntimeState) -> None:
        path = self._session_path(state.session_id)
        path.write_text(json.dumps(state.to_dict(), indent=2, default=str))

    def _require_load(self, session_id: str) -> SessionRuntimeState:
        state = self.load(session_id)
        if state is None:
            raise ValueError(f"Session not found: {session_id}")
        return state

    def _audit(self, action: str, session_id: str, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "session_id": session_id,
            "details": details,
        }
        with open(self.audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
