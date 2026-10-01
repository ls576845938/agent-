"""G6 Second One-Shot Review Gate.

After G5 post-trade completes with STOP_AND_REVIEW, this gate determines
whether a second one-shot order is permitted. ALL checks must pass for
APPROVED_FOR_SECOND_ONE_SHOT_REVIEW. The default decision is BLOCKED.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g6_second_review")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Block reasons enum
# ---------------------------------------------------------------------------

BLOCK_REASONS = frozenset({
    "missing_g5_dossier",
    "missing_execution_quality",
    "missing_post_trade_reconciliation",
    "unresolved_incident",
    "recon_not_clean",
    "unknown_broker_order",
    "freeze_not_clean",
    "submit_once_lock_missing",
    "second_order_detected",
    "manual_review_missing",
    "manual_review_rejected",
    "cumulative_loss_exceeded",
})


# ---------------------------------------------------------------------------
# SecondReviewDecision
# ---------------------------------------------------------------------------


@dataclass
class SecondReviewDecision:
    decision: str  # APPROVED_FOR_SECOND_ONE_SHOT_REVIEW | BLOCKED | REQUIRES_MORE_REVIEW
    block_reasons: list[str]
    passed_checks: list[str]
    checked_at: str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "block_reasons": self.block_reasons,
            "passed_checks": self.passed_checks,
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# SecondOneShotReviewGate
# ---------------------------------------------------------------------------


class SecondOneShotReviewGate:
    """Reviews G5 post-trade results before allowing a second one-shot ticket.

    ALL checks must pass for APPROVED_FOR_SECOND_ONE_SHOT_REVIEW.
    Default decision is BLOCKED.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)
        self.live_pilot_dir = self.data_root / "live_pilot"
        self.audit_dir = self.live_pilot_dir / "audit"
        self.live_pilot_dir.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def review(
        self,
        g5_ticket_id: str = "",
        g5_dossier_path: str = "",
        manual_review_decision: str = "",
        manual_reviewer: str = "",
    ) -> SecondReviewDecision:
        """Run all checks and return a SecondReviewDecision.

        ALL checks must pass for APPROVED_FOR_SECOND_ONE_SHOT_REVIEW.
        """
        if not g5_ticket_id:
            return SecondReviewDecision(
                decision="BLOCKED",
                block_reasons=["missing_g5_dossier"],
                passed_checks=[],
            )

        passed: list[str] = []
        blocked: list[str] = []

        # Check 1: G5 PostTradeDossier exists
        dossier_found = self._check_dossier_exists(g5_ticket_id)
        if dossier_found:
            passed.append("g5_dossier_exists")
        else:
            blocked.append("missing_g5_dossier")

        # Check 2: G5 dossier decision is STOP_AND_REVIEW
        dossier_decision_ok = self._check_dossier_decision(
            g5_ticket_id, g5_dossier_path
        )
        if dossier_decision_ok:
            passed.append("g5_dossier_decision_stop_and_review")
        elif dossier_found:
            # Dossier exists but decision is not STOP_AND_REVIEW
            blocked.append("g5_dossier_decision_not_stop_and_review")

        # Check 3: Execution quality report exists at data/live_pilot/audit/
        eq_exists = self._check_execution_quality()
        if eq_exists:
            passed.append("execution_quality_report_exists")
        else:
            blocked.append("missing_execution_quality")

        # Check 4: Post-trade reconciliation exists and is CLEAN
        recon_status = self._check_reconciliation()
        if recon_status == "clean":
            passed.append("post_trade_reconciliation_clean")
        elif recon_status == "exists_not_clean":
            passed.append("post_trade_reconciliation_exists")
            blocked.append("recon_not_clean")
        else:
            blocked.append("missing_post_trade_reconciliation")

        # Check 5: SubmitOnceLock exists (traceable, even if released)
        lock_exists = self._check_submit_once_lock()
        if lock_exists:
            passed.append("submit_once_lock_exists")
        else:
            blocked.append("submit_once_lock_missing")

        # Check 6: No second_order_detected evidence
        no_second = self._check_no_second_order()
        if no_second:
            passed.append("no_second_order_detected")
        else:
            blocked.append("second_order_detected")

        # Check 7: No unresolved incident (emergency stop status)
        no_incident = self._check_unresolved_incident()
        if no_incident:
            passed.append("no_unresolved_incident")
        else:
            blocked.append("unresolved_incident")

        # Check 8: No unknown broker orders
        no_unknown = self._check_unknown_broker_orders()
        if no_unknown:
            passed.append("no_unknown_broker_orders")
        else:
            blocked.append("unknown_broker_order")

        # Check 9: Manual review decision is explicitly "approve"
        if manual_review_decision == "approve":
            passed.append("manual_review_approved")
        elif manual_review_decision == "reject":
            blocked.append("manual_review_rejected")
        else:
            blocked.append("manual_review_missing")

        # Check 10: Manual reviewer name is provided
        if manual_reviewer:
            passed.append("manual_reviewer_provided")
        elif manual_review_decision == "approve" and not manual_reviewer:
            blocked.append("manual_review_missing")

        # Determine decision
        if not blocked:
            decision = "APPROVED_FOR_SECOND_ONE_SHOT_REVIEW"
        elif set(blocked) <= {"manual_review_missing", "manual_reviewer_provided"}:
            decision = "REQUIRES_MORE_REVIEW"
        else:
            decision = "BLOCKED"

        result = SecondReviewDecision(
            decision=decision,
            block_reasons=blocked,
            passed_checks=passed,
        )

        self._save(result, g5_ticket_id)
        self._audit("SECOND_REVIEW", g5_ticket_id, result)
        _logger.info(
            "Second review for ticket=%s: %s (blocked=%s)",
            g5_ticket_id,
            decision,
            blocked,
        )
        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_dossier_exists(self, ticket_id: str) -> bool:
        path = self.live_pilot_dir / f"post_trade_dossier_{ticket_id}.json"
        if path.exists():
            return True
        alt = self.live_pilot_dir / f"g5_dossier_{ticket_id}.json"
        return alt.exists()

    def _check_dossier_decision(
        self, ticket_id: str, dossier_path: str = ""
    ) -> bool:
        if dossier_path:
            p = Path(dossier_path)
        else:
            p = self.live_pilot_dir / f"post_trade_dossier_{ticket_id}.json"
            if not p.exists():
                p = self.live_pilot_dir / f"g5_dossier_{ticket_id}.json"
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text())
            return data.get("decision") == "STOP_AND_REVIEW"
        except (json.JSONDecodeError, OSError):
            return False

    def _check_execution_quality(self) -> bool:
        # Check for any execution quality files in audit dir
        if not self.audit_dir.exists():
            return False
        patterns = list(self.audit_dir.glob("exec_quality_*.json"))
        patterns += list(self.audit_dir.glob("execution_quality_*.json"))
        if patterns:
            return True
        # Also check in live_pilot dir
        patterns2 = list(self.live_pilot_dir.glob("exec_quality_*.json"))
        patterns2 += list(self.live_pilot_dir.glob("execution_quality_*.json"))
        return bool(patterns2)

    def _check_reconciliation(self) -> str:
        """Returns 'clean', 'exists_not_clean', or 'missing'."""
        freeze_path = self.live_pilot_dir / "freeze_state.json"
        if not freeze_path.exists():
            return "missing"
        try:
            data = json.loads(freeze_path.read_text())
            state = data.get("state", "")
            if state.startswith("FROZEN") or state == "RELEASED_AFTER_REVIEW":
                return "clean"
            return "exists_not_clean"
        except (json.JSONDecodeError, OSError):
            return "missing"

    def _check_submit_once_lock(self) -> bool:
        lock_path = self.live_pilot_dir / "submit_once_lock.json"
        if not lock_path.exists():
            return False
        try:
            data = json.loads(lock_path.read_text())
            return bool(data.get("lock_id"))
        except (json.JSONDecodeError, OSError):
            return False

    def _check_no_second_order(self) -> bool:
        # Check dossier files for second_order_detected flag
        for p in self.live_pilot_dir.glob("post_trade_dossier_*.json"):
            try:
                data = json.loads(p.read_text())
                if data.get("safety_evidence", {}).get(
                    "second_order_detected", False
                ):
                    return False
            except (json.JSONDecodeError, OSError):
                continue
        for p in self.live_pilot_dir.glob("g5_dossier_*.json"):
            try:
                data = json.loads(p.read_text())
                if data.get("safety_evidence", {}).get(
                    "second_order_detected", False
                ):
                    return False
            except (json.JSONDecodeError, OSError):
                continue
        return True

    def _check_unresolved_incident(self) -> bool:
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

    def _check_unknown_broker_orders(self) -> bool:
        freeze_path = self.live_pilot_dir / "freeze_state.json"
        if not freeze_path.exists():
            return True
        try:
            data = json.loads(freeze_path.read_text())
            return not data.get("unknown_order_state", False)
        except (json.JSONDecodeError, OSError):
            return True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self, result: SecondReviewDecision, ticket_id: str) -> None:
        path = self.live_pilot_dir / f"second_review_{ticket_id}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2, default=str))
        _logger.info("Second review saved to %s", path)

    def load(self, ticket_id: str) -> SecondReviewDecision | None:
        """Load a previously saved review decision."""
        path = self.live_pilot_dir / f"second_review_{ticket_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return SecondReviewDecision(
                decision=data.get("decision", "BLOCKED"),
                block_reasons=data.get("block_reasons", []),
                passed_checks=data.get("passed_checks", []),
                checked_at=data.get("checked_at", ""),
            )
        except (json.JSONDecodeError, OSError):
            return None

    def _audit(self, action: str, ticket_id: str, result: SecondReviewDecision) -> None:
        audit_path = self.live_pilot_dir / "second_review_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "ticket_id": ticket_id,
            "decision": result.decision,
            "block_reasons": result.block_reasons,
            "passed_checks": result.passed_checks,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
