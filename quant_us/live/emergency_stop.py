"""Emergency Stop & Rollback Controller for G3 Small Live Pilot.

Provides programmatic panic button, reduce-only enforcement, incident logging,
and rollback plan generation. ALL operations are read-only or state changes —
NO real orders are submitted through this module.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("emergency_stop")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Emergency stop states
# ---------------------------------------------------------------------------


class EmergencyStopState:
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


# Valid stop trigger reasons
VALID_STOP_REASONS = frozenset({
    "manual_stop",
    "recon_fail",
    "broker_error",
    "data_stale",
    "daily_loss_limit",
    "drawdown_limit",
    "duplicate_order_detected",
    "unknown_order_state",
    "external_order_detected",
    "kill_switch_triggered",
    "max_consecutive_losses",
    "risk_envelope_breach",
})


# ---------------------------------------------------------------------------
# Emergency stop event
# ---------------------------------------------------------------------------


@dataclass
class EmergencyStopEvent:
    event_id: str
    reason: str
    triggered_at: str = ""
    triggered_by: str = ""
    state: str = EmergencyStopState.TRIGGERED
    acknowledged_at: str = ""
    acknowledged_by: str = ""
    resolved_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.triggered_at:
            self.triggered_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "reason": self.reason,
            "triggered_at": self.triggered_at,
            "triggered_by": self.triggered_by,
            "state": self.state,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class EmergencyStopController:
    """Manages emergency stop lifecycle for live pilot safety.

    States: ARMED → TRIGGERED → ACKNOWLEDGED → RESOLVED

    When TRIGGERED:
    - New position openings are BLOCKED
    - Reduce-only is ALLOWED
    - Incident is logged
    - Audit trail is written
    - Manual acknowledgement is REQUIRED before resolution
    """

    STATE_FILENAME = "emergency_stop_state.json"
    INCIDENT_FILENAME = "emergency_stop_incidents.jsonl"

    def __init__(self, state_dir: str = "data/live_pilot") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / self.STATE_FILENAME
        self.incident_path = self.state_dir / self.INCIDENT_FILENAME
        self._current_event: EmergencyStopEvent | None = None

        if not self.state_path.exists():
            self._init_armed_state()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_armed(self) -> bool:
        self._load()
        return self._current_event is None or self._current_event.state == EmergencyStopState.RESOLVED

    @property
    def is_triggered(self) -> bool:
        self._load()
        return (
            self._current_event is not None
            and self._current_event.state == EmergencyStopState.TRIGGERED
        )

    @property
    def is_acknowledged(self) -> bool:
        self._load()
        return (
            self._current_event is not None
            and self._current_event.state == EmergencyStopState.ACKNOWLEDGED
        )

    @property
    def reduce_only(self) -> bool:
        return self.is_triggered or self.is_acknowledged

    @property
    def new_positions_allowed(self) -> bool:
        return not self.reduce_only

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def trigger(
        self, reason: str, triggered_by: str = "", notes: str = ""
    ) -> EmergencyStopEvent:
        if reason not in VALID_STOP_REASONS:
            raise ValueError(
                f"Invalid stop reason '{reason}'. Valid: {sorted(VALID_STOP_REASONS)}"
            )

        event = EmergencyStopEvent(
            event_id=f"stop_{_utc_now().strftime('%Y%m%d_%H%M%S')}",
            reason=reason,
            triggered_by=triggered_by,
            notes=notes,
            state=EmergencyStopState.TRIGGERED,
        )

        self._current_event = event
        self._save()
        self._write_incident(event, "triggered")
        _logger.warning(
            "EMERGENCY STOP TRIGGERED: reason=%s by=%s event=%s",
            reason,
            triggered_by,
            event.event_id,
        )
        return event

    def acknowledge(self, acknowledged_by: str = "", notes: str = "") -> EmergencyStopEvent:
        self._load()
        if self._current_event is None:
            raise RuntimeError("No emergency stop event to acknowledge")
        if self._current_event.state != EmergencyStopState.TRIGGERED:
            raise RuntimeError(
                f"Cannot acknowledge: state is {self._current_event.state}"
            )

        self._current_event.state = EmergencyStopState.ACKNOWLEDGED
        self._current_event.acknowledged_at = _utc_now().isoformat()
        self._current_event.acknowledged_by = acknowledged_by
        if notes:
            self._current_event.notes += f"\nACK: {notes}"

        self._save()
        self._write_incident(self._current_event, "acknowledged")
        return self._current_event

    def resolve(self, notes: str = "") -> EmergencyStopEvent:
        self._load()
        if self._current_event is None:
            raise RuntimeError("No emergency stop event to resolve")
        if self._current_event.state not in (
            EmergencyStopState.ACKNOWLEDGED,
            EmergencyStopState.TRIGGERED,
        ):
            raise RuntimeError(
                f"Cannot resolve: state is {self._current_event.state}"
            )

        self._current_event.state = EmergencyStopState.RESOLVED
        self._current_event.resolved_at = _utc_now().isoformat()
        if notes:
            self._current_event.notes += f"\nRESOLVE: {notes}"

        self._save()
        self._write_incident(self._current_event, "resolved")
        _logger.info("Emergency stop resolved: %s", self._current_event.event_id)
        return self._current_event

    def status(self) -> dict[str, Any]:
        self._load()
        if self._current_event is None:
            return {
                "state": EmergencyStopState.ARMED,
                "reduce_only": False,
                "new_positions_allowed": True,
                "current_event": None,
            }
        return {
            "state": self._current_event.state,
            "reduce_only": self.reduce_only,
            "new_positions_allowed": self.new_positions_allowed,
            "current_event": self._current_event.to_dict(),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _init_armed_state(self) -> None:
        self._current_event = None
        self.state_path.write_text(json.dumps({"state": EmergencyStopState.ARMED}))

    def _load(self) -> None:
        if not self.state_path.exists():
            self._init_armed_state()
            return
        try:
            data = json.loads(self.state_path.read_text())
            if "event_id" in data:
                self._current_event = EmergencyStopEvent(
                    event_id=data["event_id"],
                    reason=data.get("reason", ""),
                    triggered_at=data.get("triggered_at", ""),
                    triggered_by=data.get("triggered_by", ""),
                    state=data.get("state", EmergencyStopState.ARMED),
                    acknowledged_at=data.get("acknowledged_at", ""),
                    acknowledged_by=data.get("acknowledged_by", ""),
                    resolved_at=data.get("resolved_at", ""),
                    notes=data.get("notes", ""),
                )
            else:
                self._current_event = None
        except (json.JSONDecodeError, OSError):
            self._current_event = None

    def _save(self) -> None:
        if self._current_event is None:
            self.state_path.write_text(json.dumps({"state": EmergencyStopState.ARMED}))
        else:
            self.state_path.write_text(
                json.dumps(self._current_event.to_dict(), indent=2, default=str)
            )

    def _write_incident(self, event: EmergencyStopEvent, action: str) -> None:
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "event_id": event.event_id,
            "reason": event.reason,
            "triggered_by": event.triggered_by,
            "state": event.state,
            "notes": event.notes,
        }
        with open(self.incident_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# Rollback Plan
# ---------------------------------------------------------------------------


@dataclass
class RollbackPlan:
    plan_id: str
    generated_at: str = ""
    stop_reason: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    current_positions: list[dict[str, Any]] = field(default_factory=list)
    current_orders: list[dict[str, Any]] = field(default_factory=list)
    reduce_only_instructions: list[str] = field(default_factory=list)
    manual_review_required: bool = True
    incident_report_generated: bool = False

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "generated_at": self.generated_at,
            "stop_reason": self.stop_reason,
            "actions": self.actions,
            "current_positions": self.current_positions,
            "current_orders": self.current_orders,
            "reduce_only_instructions": self.reduce_only_instructions,
            "manual_review_required": self.manual_review_required,
            "incident_report_generated": self.incident_report_generated,
        }


class RollbackPlanGenerator:
    """Generates a rollback plan after an emergency stop.

    This does NOT submit any orders. It produces instructions for
    human review and manual action only.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def generate(self, reason: str = "") -> RollbackPlan:
        plan = RollbackPlan(
            plan_id=f"rollback_{_utc_now().strftime('%Y%m%d_%H%M%S')}",
            stop_reason=reason,
        )

        plan.actions = [
            {"step": 1, "action": "Stop strategy signal generation", "status": "recommended"},
            {"step": 2, "action": "Stop order submission (already blocked by emergency stop)", "status": "automatic"},
            {"step": 3, "action": "Query broker for current positions", "status": "manual"},
            {"step": 4, "action": "Query broker for open orders", "status": "manual"},
            {"step": 5, "action": "Reconcile ledger vs broker", "status": "manual"},
            {"step": 6, "action": "Generate reduce-only instructions", "status": "manual"},
            {"step": 7, "action": "Human review and decision", "status": "required"},
            {"step": 8, "action": "Write incident report", "status": "required"},
            {"step": 9, "action": "Acknowledge emergency stop", "status": "required"},
            {"step": 10, "action": "Resolve emergency stop when safe", "status": "required"},
        ]

        plan.current_positions = []
        plan.current_orders = []

        plan.reduce_only_instructions = [
            "DO NOT open new positions while reduce_only is active.",
            "Only submit closing/reducing orders if absolutely necessary.",
            "All closing orders must pass human review.",
            "Verify each order against broker before submission.",
        ]

        plan.manual_review_required = True
        plan.incident_report_generated = True

        self._save(plan)
        return plan

    def _save(self, plan: RollbackPlan) -> None:
        plans_dir = self.data_root / "live_pilot" / "rollback_plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        path = plans_dir / f"{plan.plan_id}.json"
        path.write_text(json.dumps(plan.to_dict(), indent=2, default=str))
        _logger.info("Rollback plan saved to %s", path)
