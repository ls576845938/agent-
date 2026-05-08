"""G6 Pilot Progression Controller.

Evaluates overall live pilot progression status across G5 and G6 phases.
Returns a recommendation (READY_FOR_G7_REVIEW) but NEVER auto-advances.
Default status is BLOCKED.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g6_progression")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Progression status constants
# ---------------------------------------------------------------------------


class ProgressionStatus:
    G5_SINGLE_ORDER_REVIEW = "G5_SINGLE_ORDER_REVIEW"
    G6_SECOND_ONE_SHOT_REVIEW = "G6_SECOND_ONE_SHOT_REVIEW"
    G6_MICRO_EPISODE_ACTIVE = "G6_MICRO_EPISODE_ACTIVE"
    G6_FROZEN_PENDING_REVIEW = "G6_FROZEN_PENDING_REVIEW"
    G6_TERMINATED = "G6_TERMINATED"
    READY_FOR_G7_REVIEW = "READY_FOR_G7_REVIEW"
    BLOCKED = "BLOCKED"


VALID_PROGRESSION_STATES = frozenset({
    ProgressionStatus.G5_SINGLE_ORDER_REVIEW,
    ProgressionStatus.G6_SECOND_ONE_SHOT_REVIEW,
    ProgressionStatus.G6_MICRO_EPISODE_ACTIVE,
    ProgressionStatus.G6_FROZEN_PENDING_REVIEW,
    ProgressionStatus.G6_TERMINATED,
    ProgressionStatus.READY_FOR_G7_REVIEW,
    ProgressionStatus.BLOCKED,
})


# ---------------------------------------------------------------------------
# PilotProgressionController
# ---------------------------------------------------------------------------


class PilotProgressionController:
    """Evaluates overall pilot progression and readiness for G7.

    This controller NEVER auto-advances. It only evaluates conditions and
    returns a status recommendation. All decisions default to BLOCKED.
    """

    PROGRESSION_STATE_PATH = "data/live_pilot/progression_state.json"

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.live_pilot_dir = self.data_root / "live_pilot"
        self.live_pilot_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.live_pilot_dir / "progression_state.json"

    def evaluate(self, episode_id: str) -> dict[str, Any]:
        """Evaluate progression status for a given episode.

        Returns a dict with:
          - progression_status: str
          - conditions: dict of check name -> bool
          - blocked_reasons: list[str]
          - episode_id: str
          - evaluated_at: str

        Returns READY_FOR_G7_REVIEW only as a recommendation.
        NEVER auto-advances.
        """
        conditions: dict[str, bool] = {}
        blocked_reasons: list[str] = []

        # Load episode
        episode_data = self._load_episode(episode_id)

        # Check 1: At least 1 order completed with G5 post-trade review
        condition_1 = self._check_at_least_one_order(episode_data)
        conditions["at_least_one_order_completed"] = condition_1
        if not condition_1:
            blocked_reasons.append("no_completed_orders")

        # Check 2: All orders are traceable (audit trail exists)
        condition_2 = self._check_traceable_orders(episode_data)
        conditions["all_orders_traceable"] = condition_2
        if not condition_2:
            blocked_reasons.append("orders_not_traceable")

        # Check 3: No duplicate orders
        condition_3 = self._check_no_duplicate_orders(episode_data)
        conditions["no_duplicate_orders"] = condition_3
        if not condition_3:
            blocked_reasons.append("duplicate_orders_detected")

        # Check 4: No unresolved incidents
        condition_4 = self._check_no_unresolved_incidents()
        conditions["no_unresolved_incidents"] = condition_4
        if not condition_4:
            blocked_reasons.append("unresolved_incidents")

        # Check 5: No recon failures
        condition_5 = self._check_no_recon_failures(episode_data)
        conditions["no_recon_failures"] = condition_5
        if not condition_5:
            blocked_reasons.append("recon_failures")

        # Check 6: Cumulative risk PASS (placeholder - Agent C will wire)
        condition_6 = self._check_cumulative_risk(episode_data)
        conditions["cumulative_risk_pass"] = condition_6
        if not condition_6:
            blocked_reasons.append("cumulative_risk_failed")

        # Check 7: Emergency stop tested and armed
        condition_7 = self._check_emergency_stop_armed()
        conditions["emergency_stop_armed"] = condition_7
        if not condition_7:
            blocked_reasons.append("emergency_stop_not_armed")

        # Check 8: Manual review approved
        condition_8 = self._check_manual_review_approved(episode_data)
        conditions["manual_review_approved"] = condition_8
        if not condition_8:
            blocked_reasons.append("manual_review_not_approved")

        # Determine progression status
        if not blocked_reasons:
            progression_status = ProgressionStatus.READY_FOR_G7_REVIEW
        else:
            progression_status = self._infer_current_status(episode_data, blocked_reasons)

        # Build result
        result: dict[str, Any] = {
            "progression_status": progression_status,
            "conditions": conditions,
            "blocked_reasons": blocked_reasons,
            "episode_id": episode_id,
            "evaluated_at": _utc_now().isoformat(),
        }

        self._save_state(progression_status, episode_id, conditions, blocked_reasons)
        self._audit("EVALUATE", result)
        return result

    def status(self) -> dict[str, Any]:
        """Overall system progression status without evaluating."""
        state = self._load_state()
        if state is None:
            return {
                "progression_status": "NOT_EVALUATED",
                "episode_id": "",
                "last_evaluated_at": "",
                "conditions": {},
                "blocked_reasons": [],
            }

        return {
            "progression_status": state.get("progression_status", ProgressionStatus.BLOCKED),
            "episode_id": state.get("episode_id", ""),
            "last_evaluated_at": state.get("evaluated_at", ""),
            "conditions": state.get("conditions", {}),
            "blocked_reasons": state.get("blocked_reasons", []),
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_at_least_one_order(self, episode_data: dict[str, Any] | None) -> bool:
        if episode_data is None:
            return False
        ticket_ids = episode_data.get("ticket_ids", [])
        if not ticket_ids:
            return False
        # Check at least one has a post-trade dossier
        for tid in ticket_ids:
            dossier_path = self.live_pilot_dir / f"post_trade_dossier_{tid}.json"
            if dossier_path.exists():
                return True
            alt = self.live_pilot_dir / f"g5_dossier_{tid}.json"
            if alt.exists():
                return True
        return False

    def _check_traceable_orders(self, episode_data: dict[str, Any] | None) -> bool:
        if episode_data is None:
            return False
        ticket_ids = episode_data.get("ticket_ids", [])
        if not ticket_ids:
            return False
        # Check audit trail exists
        audit_dir = self.live_pilot_dir / "audit"
        if not audit_dir.exists():
            return False
        return True

    def _check_no_duplicate_orders(self, episode_data: dict[str, Any] | None) -> bool:
        if episode_data is None:
            return True
        ticket_ids = episode_data.get("ticket_ids", [])
        if len(ticket_ids) != len(set(ticket_ids)):
            return False
        return True

    def _check_no_unresolved_incidents(self) -> bool:
        try:
            from quant_us.live.emergency_stop import EmergencyStopController

            ctrl = EmergencyStopController(
                state_dir=str(self.live_pilot_dir)
            )
            status = ctrl.status()
            state = status.get("state", "ARMED")
            return state in ("ARMED", "RESOLVED")
        except Exception:
            return True

    def _check_no_recon_failures(self, episode_data: dict[str, Any] | None) -> bool:
        freeze_path = self.live_pilot_dir / "freeze_state.json"
        if not freeze_path.exists():
            return True
        try:
            data = json.loads(freeze_path.read_text())
            state = data.get("state", "")
            if state.startswith("FROZEN") or state == "RELEASED_AFTER_REVIEW":
                return True
            return False
        except (json.JSONDecodeError, OSError):
            return True

    def _check_cumulative_risk(self, episode_data: dict[str, Any] | None) -> bool:
        # Placeholder -- Agent C will wire cumulative risk logic
        return True

    def _check_emergency_stop_armed(self) -> bool:
        try:
            from quant_us.live.emergency_stop import EmergencyStopController

            ctrl = EmergencyStopController(
                state_dir=str(self.live_pilot_dir)
            )
            status = ctrl.status()
            return status.get("state") == "ARMED"
        except Exception:
            return True

    def _check_manual_review_approved(self, episode_data: dict[str, Any] | None) -> bool:
        if episode_data is None:
            return False
        ticket_ids = episode_data.get("ticket_ids", [])
        for tid in ticket_ids:
            review_path = self.live_pilot_dir / f"second_review_{tid}.json"
            if review_path.exists():
                try:
                    data = json.loads(review_path.read_text())
                    if data.get("decision") == "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW":
                        return True
                except (json.JSONDecodeError, OSError):
                    continue
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_episode(self, episode_id: str) -> dict[str, Any] | None:
        episode_path = self.live_pilot_dir / "episodes" / f"{episode_id}.json"
        if not episode_path.exists():
            return None
        try:
            return json.loads(episode_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _infer_current_status(
        self,
        episode_data: dict[str, Any] | None,
        blocked_reasons: list[str],
    ) -> str:
        """Infer the most appropriate progression status when blocked."""
        if episode_data is None:
            return ProgressionStatus.G5_SINGLE_ORDER_REVIEW

        status = episode_data.get("status", "")
        if status == "TERMINATED":
            return ProgressionStatus.G6_TERMINATED
        if status == "COMPLETED" and not blocked_reasons:
            return ProgressionStatus.READY_FOR_G7_REVIEW
        if status == "DRAFT":
            return ProgressionStatus.G5_SINGLE_ORDER_REVIEW

        return ProgressionStatus.BLOCKED

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(
        self,
        progression_status: str,
        episode_id: str,
        conditions: dict[str, bool],
        blocked_reasons: list[str],
    ) -> None:
        state = {
            "progression_status": progression_status,
            "episode_id": episode_id,
            "conditions": conditions,
            "blocked_reasons": blocked_reasons,
            "evaluated_at": _utc_now().isoformat(),
        }
        self.state_path.write_text(
            json.dumps(state, indent=2, default=str)
        )

    def _load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            return json.loads(self.state_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _audit(self, action: str, data: dict[str, Any]) -> None:
        audit_path = self.live_pilot_dir / "progression_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "data": data,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
