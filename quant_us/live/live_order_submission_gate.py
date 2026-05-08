"""Live Order Submission Gate for G4 Small Live Pilot Execution.

The SINGLE non-bypassable gate that must return APPROVED_FOR_SUBMIT
before any real live order reaches AlpacaBroker.submit_order().

Every block reason produces an audit record. Nothing is silent.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("live_order_submission_gate")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Gate decision
# ---------------------------------------------------------------------------


@dataclass
class SubmissionGateDecision:
    decision: str  # APPROVED_FOR_SUBMIT | BLOCKED | REQUIRES_MANUAL_REVIEW
    block_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_at: str = ""
    gate_version: str = "g4_v1.0.0"

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = _utc_now().isoformat()

    @property
    def approved(self) -> bool:
        return self.decision == "APPROVED_FOR_SUBMIT"

    @property
    def blocked(self) -> bool:
        return self.decision == "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "block_reasons": self.block_reasons,
            "warnings": self.warnings,
            "checked_at": self.checked_at,
            "gate_version": self.gate_version,
        }


# ---------------------------------------------------------------------------
# All possible block reasons
# ---------------------------------------------------------------------------

BLOCK_REASONS = frozenset({
    "missing_approval",
    "approval_not_approved",
    "approval_expired",
    "missing_envelope",
    "envelope_mismatch",
    "dossier_not_ready",
    "env_gate_disabled",
    "missing_confirm_live",
    "allow_live_orders_false",
    "live_endpoint_mismatch",
    "reconciliation_not_clean",
    "emergency_stop_not_armed",
    "emergency_stop_triggered",
    "outside_regular_session",
    "order_type_not_allowed",
    "notional_exceeded",
    "exposure_exceeded",
    "daily_loss_limit_exceeded",
    "oms_idempotency_failed",
    "kill_switch_active",
    "execute_live_pilot_not_set",
    "dry_run_mode",
})


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class LiveOrderSubmissionGate:
    """Centralized, non-bypassable gate for live order submission.

    Must return APPROVED_FOR_SUBMIT before AlpacaBroker.submit_order() is called.
    Every check failure produces an audit record.
    """

    def __init__(self, audit_dir: str = "data/live_pilot/audit") -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def check(
        self,
        approval_id: str = "",
        envelope_id: str = "",
        dossier_decision: str = "",
        env_enabled: bool = False,
        confirm_live: bool = False,
        allow_live: bool = False,
        execute_live_pilot: bool = False,
        is_dry_run: bool = True,
        live_endpoint_ok: bool = False,
        reconciliation_clean: bool = False,
        emergency_stop_armed: bool = False,
        emergency_stop_triggered: bool = False,
        in_regular_session: bool = False,
        order_type: str = "",
        allowed_order_types: list[str] | None = None,
        order_notional: float = 0.0,
        max_order_notional: float = 0.0,
        daily_notional_used: float = 0.0,
        max_daily_notional: float = 0.0,
        oms_idempotency_ok: bool = False,
        kill_switch_active: bool = False,
        strategy_version: str = "",
        approved_version: str = "",
    ) -> SubmissionGateDecision:
        reasons: list[str] = []
        warnings: list[str] = []

        if allowed_order_types is None:
            allowed_order_types = ["limit"]

        # --- Hard gates (order matters: cheapest first) ---

        if is_dry_run:
            reasons.append("dry_run_mode")
            self._audit("BLOCKED", reasons)
            return SubmissionGateDecision(decision="BLOCKED", block_reasons=reasons)

        if not execute_live_pilot:
            reasons.append("execute_live_pilot_not_set")
            self._audit("BLOCKED", reasons)
            return SubmissionGateDecision(decision="BLOCKED", block_reasons=reasons)

        if not approval_id:
            reasons.append("missing_approval")
        else:
            from quant_us.live.live_pilot_approval import HumanApprovalGate

            gate = HumanApprovalGate()
            approval_result = gate.check(
                approval_id=approval_id,
                strategy_version=strategy_version,
            )
            if not approval_result.passed:
                for check_name, passed in approval_result.checks.items():
                    if not passed:
                        if check_name == "status_approved":
                            reasons.append("approval_not_approved")
                        elif check_name == "not_expired":
                            reasons.append("approval_expired")
                        elif check_name == "strategy_version_match":
                            warnings.append("strategy_version_mismatch")
                        else:
                            reasons.append(f"approval_{check_name}_failed")

        if not envelope_id:
            reasons.append("missing_envelope")
        else:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            envelope = mgr.load(envelope_id)
            if envelope is None:
                reasons.append("missing_envelope")
            else:
                if not envelope.allow_market_order and order_type == "market":
                    reasons.append("order_type_not_allowed")
                if order_notional > envelope.max_order_notional:
                    reasons.append("notional_exceeded")
                if (daily_notional_used + order_notional) > envelope.max_daily_notional:
                    reasons.append("notional_exceeded")

        if dossier_decision not in ("GO_FOR_SMALL_LIVE_REVIEW", "READY_FOR_HUMAN_REVIEW"):
            reasons.append("dossier_not_ready")

        if not env_enabled:
            reasons.append("env_gate_disabled")

        if not confirm_live:
            reasons.append("missing_confirm_live")

        if not allow_live:
            reasons.append("allow_live_orders_false")

        if not live_endpoint_ok:
            reasons.append("live_endpoint_mismatch")

        if not reconciliation_clean:
            reasons.append("reconciliation_not_clean")

        if not emergency_stop_armed:
            reasons.append("emergency_stop_not_armed")

        if emergency_stop_triggered:
            reasons.append("emergency_stop_triggered")

        if not in_regular_session:
            reasons.append("outside_regular_session")

        if order_type not in allowed_order_types:
            reasons.append("order_type_not_allowed")

        if order_notional > max_order_notional > 0:
            reasons.append("notional_exceeded")

        if not oms_idempotency_ok:
            reasons.append("oms_idempotency_failed")

        if kill_switch_active:
            reasons.append("kill_switch_active")

        # Decision
        if reasons:
            self._audit("BLOCKED", reasons)
            return SubmissionGateDecision(
                decision="BLOCKED",
                block_reasons=reasons,
                warnings=warnings,
            )

        if warnings:
            self._audit("APPROVED_FOR_SUBMIT_WITH_WARNINGS", warnings)
            return SubmissionGateDecision(
                decision="APPROVED_FOR_SUBMIT",
                warnings=warnings,
            )

        self._audit("APPROVED_FOR_SUBMIT", [])
        return SubmissionGateDecision(decision="APPROVED_FOR_SUBMIT")

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def _audit(self, decision: str, reasons: list[str]) -> None:
        entry = {
            "timestamp": _utc_now().isoformat(),
            "gate_version": "g4_v1.0.0",
            "decision": decision,
            "reasons": reasons,
        }
        audit_path = self.audit_dir / "submission_gate_audit.jsonl"
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def read_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        audit_path = self.audit_dir / "submission_gate_audit.jsonl"
        if not audit_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with open(audit_path) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]
