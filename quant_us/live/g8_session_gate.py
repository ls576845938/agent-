"""G8 Session Gate.

Every order within a session MUST pass through this gate.
The gate defaults to BLOCKED. It NEVER auto-approves.

Order of checks (returns on first failure):
1. dry_run -> BLOCKED (dry_run_mode)
2. manual_confirm -> BLOCKED (missing_manual_confirm)
3. promotion manifest APPROVED_FOR_G8_REVIEW
4. session state ARMED/ACTIVE_MANUAL_SUPERVISION
5. not FROZEN (must resume after post-trade review)
6. daily cap (max orders per day)
7. session limits (orders, notional, loss)
8. emergency stop not triggered
9. reconciliation clean
10. ticket_id provided
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.g8_daily_cap import DailyTradingCapManager
from quant_us.live.g8_session_state import SessionRuntimeStateManager, SessionStatus

_logger = logging.getLogger("g8_session_gate")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Block reasons
# ---------------------------------------------------------------------------

BLOCK_REASONS = frozenset({
    "missing_promotion", "promotion_not_approved", "session_not_armed",
    "session_paused", "session_terminated", "session_frozen",
    "max_orders_per_day_exceeded", "max_orders_per_session_exceeded",
    "session_notional_exceeded", "session_loss_exceeded",
    "emergency_stop_triggered", "reconciliation_dirty",
    "missing_ticket", "missing_manual_confirm", "dry_run_mode",
})


# ---------------------------------------------------------------------------
# SessionGateDecision
# ---------------------------------------------------------------------------


@dataclass
class SessionGateDecision:
    decision: str  # APPROVED_FOR_SESSION_ONE_SHOT|BLOCKED|PAUSED|TERMINATED
    block_reasons: list[str]
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "block_reasons": self.block_reasons,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# SessionGate
# ---------------------------------------------------------------------------


class SessionGate:
    """Gate that checks all session-level conditions before every order.

    Default decision is BLOCKED. Every single check must pass.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.state_mgr = SessionRuntimeStateManager(data_root=data_root)
        self.cap_mgr = DailyTradingCapManager(data_root=data_root)
        self.promo_dir = Path(data_root) / "live_pilot" / "session" / "promotions"
        self.promo_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = Path(data_root) / "live_pilot" / "session" / "session_gate_audit.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def check(
        self,
        session_id: str = "",
        promotion_id: str = "",
        ticket_id: str = "",
        proposed_notional: float = 0.0,
        manual_confirm: bool = False,
        dry_run: bool = True,
    ) -> SessionGateDecision:
        """Check all session-level gates. Default BLOCKED.

        Order of checks (return on first failure):
        1. If dry_run -> BLOCKED (dry_run_mode)
        2. If not manual_confirm -> BLOCKED (missing_manual_confirm)
        3. Load promotion manifest, verify APPROVED_FOR_G8_REVIEW
        4. Load session state, verify ARMED/ACTIVE_MANUAL_SUPERVISION
        5. Check not FROZEN (must resume after post-trade review)
        6. Check daily cap (max orders per day)
        7. Check session limits (orders, notional, loss)
        8. Check emergency stop not triggered
        9. Check reconciliation clean
        10. Check ticket_id provided
        """
        state = self.state_mgr.load(session_id)

        # Check 1: dry_run -> BLOCKED
        if dry_run:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["dry_run_mode"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 2: manual_confirm
        if not manual_confirm:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["missing_manual_confirm"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 3: promotion
        if not promotion_id:
            # Fall back to session's promotion_id
            if state:
                promotion_id = state.promotion_id

        if not promotion_id:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["missing_promotion"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        promo = self._load_promotion(promotion_id)
        if promo is None:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["missing_promotion"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision
        if promo.get("status") != "APPROVED_FOR_G8_REVIEW":
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["promotion_not_approved"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 4: session state
        if state is None:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["session_not_armed"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        if state.status == SessionStatus.PAUSED:
            decision = SessionGateDecision(
                decision="PAUSED",
                block_reasons=["session_paused"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        if state.status == SessionStatus.TERMINATED:
            decision = SessionGateDecision(
                decision="TERMINATED",
                block_reasons=["session_terminated"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        if state.status == SessionStatus.FROZEN:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["session_frozen"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        if state.status not in (SessionStatus.ARMED, SessionStatus.ACTIVE_MANUAL_SUPERVISION):
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["session_not_armed"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 6: daily cap
        from datetime import date
        today = date.today().isoformat()
        cap_allowed, cap_reason = self.cap_mgr.check(
            session_id, today, proposed_notional=proposed_notional,
        )
        if not cap_allowed:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=[cap_reason],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 7: session limits
        session_blocks: list[str] = []
        if state.submitted_order_count >= state.max_orders_per_session:
            session_blocks.append("max_orders_per_session_exceeded")
        if state.real_submit_count >= state.max_orders_per_session:
            session_blocks.append("max_orders_per_session_exceeded")
        total_used_notional = self._estimate_used_notional(state)
        if total_used_notional + proposed_notional > state.max_session_notional:
            session_blocks.append("session_notional_exceeded")
        estimated_loss = self._estimate_session_pnl(state)
        if estimated_loss <= -state.max_session_loss:
            session_blocks.append("session_loss_exceeded")

        if session_blocks:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=session_blocks,
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 8: emergency stop
        if state.emergency_stop_count > 0:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["emergency_stop_triggered"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 9: reconciliation
        if state.recon_fail_count > 0:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["reconciliation_dirty"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # Check 10: ticket_id
        if not ticket_id:
            decision = SessionGateDecision(
                decision="BLOCKED",
                block_reasons=["missing_ticket"],
            )
            self._audit(decision, session_id, ticket_id)
            return decision

        # All checks passed
        decision = SessionGateDecision(
            decision="APPROVED_FOR_SESSION_ONE_SHOT",
            block_reasons=[],
        )
        self._audit(decision, session_id, ticket_id)
        _logger.info(
            "Session gate APPROVED: session=%s ticket=%s",
            session_id, ticket_id,
        )
        return decision

    # ------------------------------------------------------------------
    # Promotion manifest support
    # ------------------------------------------------------------------

    def create_promotion(self, promotion_id: str) -> dict[str, Any]:
        """Create a new promotion manifest (G8-level approval)."""
        manifest = {
            "promotion_id": promotion_id,
            "status": "DRAFT",
            "created_at": _utc_now().isoformat(),
            "updated_at": _utc_now().isoformat(),
        }
        self._save_promotion(manifest)
        _logger.info("Promotion created: %s", promotion_id)
        return manifest

    def approve_promotion(self, promotion_id: str) -> dict[str, Any]:
        """Mark a promotion as APPROVED_FOR_G8_REVIEW."""
        manifest = self._load_promotion(promotion_id)
        if manifest is None:
            raise ValueError(f"Promotion not found: {promotion_id}")
        manifest["status"] = "APPROVED_FOR_G8_REVIEW"
        manifest["updated_at"] = _utc_now().isoformat()
        self._save_promotion(manifest)
        _logger.info("Promotion approved for G8 review: %s", promotion_id)
        return manifest

    def get_promotion(self, promotion_id: str) -> dict[str, Any] | None:
        return self._load_promotion(promotion_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_promotion(self, promotion_id: str) -> dict[str, Any] | None:
        path = self.promo_dir / f"{promotion_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _save_promotion(self, manifest: dict[str, Any]) -> None:
        path = self.promo_dir / f"{manifest['promotion_id']}.json"
        path.write_text(json.dumps(manifest, indent=2, default=str))

    def _estimate_used_notional(self, state: "SessionRuntimeState") -> float:
        from quant_us.live.g8_session_state import SessionRuntimeState
        # Conservative estimate: number of tickets * average notional bound
        # Since we don't track exact notional per order in state,
        # use max_session_notional * (submitted_count / max_orders_per_session)
        if state.max_orders_per_session == 0:
            return 0.0
        ratio = min(state.submitted_order_count / state.max_orders_per_session, 1.0)
        return state.max_session_notional * ratio

    def _estimate_session_pnl(self, state: "SessionRuntimeState") -> float:
        from quant_us.live.g8_session_state import SessionRuntimeState
        # Conservative estimate based on max_session_loss
        if state.incident_count > 0:
            return -state.max_session_loss
        return 0.0

    def _audit(self, decision: SessionGateDecision, session_id: str, ticket_id: str) -> None:
        entry = {
            "timestamp": decision.checked_at,
            "decision": decision.decision,
            "block_reasons": decision.block_reasons,
            "session_id": session_id,
            "ticket_id": ticket_id,
        }
        with open(self.audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
