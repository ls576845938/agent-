"""G5 Post-Trade: Reconciliation, Freeze, Execution Quality, and Dossier.

After the FIRST live order, the system freezes and produces a complete
post-trade review package. No second order is permitted.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g5_post_trade")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Post-Trade Reconciliation Result
# ---------------------------------------------------------------------------

POST_TRADE_STATUSES = frozenset({
    "CLEAN_FILLED",
    "CLEAN_PENDING",
    "PARTIAL_FILL",
    "REJECTED",
    "CANCELED",
    "BROKER_TIMEOUT",
    "MISMATCH",
    "MANUAL_REVIEW_REQUIRED",
})


@dataclass
class PostTradeReconciliationResult:
    ticket_id: str
    broker_order_status: str = "UNKNOWN"
    local_order_status: str = "UNKNOWN"
    fill_qty: float = 0.0
    fill_price: float = 0.0
    local_position: float = 0.0
    broker_position: float = 0.0
    cash_diff: float = 0.0
    commission: float = 0.0
    slippage_bps: float = 0.0
    open_order_remaining: float = 0.0
    unknown_order_state: bool = False
    status: str = "PENDING"
    requires_manual_review: bool = False
    reconciled_at: str = ""

    def __post_init__(self) -> None:
        if not self.reconciled_at:
            self.reconciled_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "broker_order_status": self.broker_order_status,
            "local_order_status": self.local_order_status,
            "fill_qty": self.fill_qty,
            "fill_price": self.fill_price,
            "local_position": self.local_position,
            "broker_position": self.broker_position,
            "cash_diff": self.cash_diff,
            "commission": self.commission,
            "slippage_bps": self.slippage_bps,
            "open_order_remaining": self.open_order_remaining,
            "unknown_order_state": self.unknown_order_state,
            "status": self.status,
            "requires_manual_review": self.requires_manual_review,
            "reconciled_at": self.reconciled_at,
        }


class PostTradeReconciler:
    """Reconcile the one-shot order against broker state."""

    def reconcile(
        self,
        ticket_id: str,
        broker_order_status: str = "filled",
        fill_qty: float = 1.0,
        fill_price: float = 500.0,
        submitted_qty: float = 1.0,
    ) -> PostTradeReconciliationResult:
        result = PostTradeReconciliationResult(
            ticket_id=ticket_id,
            broker_order_status=broker_order_status,
            fill_qty=fill_qty,
            fill_price=fill_price,
        )

        if broker_order_status == "filled":
            if fill_qty >= submitted_qty:
                result.status = "CLEAN_FILLED"
            else:
                result.status = "PARTIAL_FILL"
                result.open_order_remaining = submitted_qty - fill_qty
                result.requires_manual_review = True
        elif broker_order_status == "pending":
            result.status = "CLEAN_PENDING"
            result.requires_manual_review = True
        elif broker_order_status == "rejected":
            result.status = "REJECTED"
            result.requires_manual_review = True
        elif broker_order_status == "canceled":
            result.status = "CANCELED"
            result.requires_manual_review = True
        elif broker_order_status == "timeout":
            result.status = "BROKER_TIMEOUT"
            result.requires_manual_review = True
            result.unknown_order_state = True
        else:
            result.status = "MANUAL_REVIEW_REQUIRED"
            result.requires_manual_review = True

        result.local_order_status = result.status

        return result


# ---------------------------------------------------------------------------
# Live Pilot Freeze State
# ---------------------------------------------------------------------------

FREEZE_STATES = frozenset({
    "FROZEN_PENDING_REVIEW",
    "FROZEN_NEEDS_RECON",
    "FROZEN_NEEDS_MANUAL_ACTION",
    "FROZEN_CLEAN",
    "RELEASED_AFTER_REVIEW",
})


class LivePilotFreezeState:
    """Persisted freeze that prevents any second live order after the one-shot."""

    FREEZE_PATH = "data/live_pilot/freeze_state.json"

    def __init__(self, state_dir: str = "data/live_pilot") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.freeze_path = self.state_dir / "freeze_state.json"

    def freeze(self, ticket_id: str, run_id: str = "",
               state: str = "FROZEN_PENDING_REVIEW", reason: str = "ONE_SHOT_EXECUTED") -> dict[str, Any]:
        if state not in FREEZE_STATES:
            raise ValueError(f"Invalid freeze state: {state}")

        freeze_data = {
            "ticket_id": ticket_id,
            "run_id": run_id,
            "frozen_at": _utc_now().isoformat(),
            "state": state,
            "reason": reason,
        }
        self.freeze_path.write_text(json.dumps(freeze_data, indent=2, default=str))
        self._audit("FROZEN", freeze_data)
        _logger.warning("LIVE PILOT FROZEN: state=%s ticket=%s", state, ticket_id)
        return freeze_data

    def is_frozen(self) -> bool:
        data = self._load()
        if data is None:
            return False
        return data.get("state", "").startswith("FROZEN")

    def status(self) -> dict[str, Any]:
        data = self._load()
        if data is None:
            return {"frozen": False, "state": "NOT_FROZEN"}
        return {"frozen": self.is_frozen(), "state": data.get("state", "UNKNOWN"), "data": data}

    def release(self, released_by: str, reason: str) -> dict[str, Any]:
        data = self._load()
        if data is None:
            raise RuntimeError("No freeze state to release")
        data["state"] = "RELEASED_AFTER_REVIEW"
        data["released_at"] = _utc_now().isoformat()
        data["released_by"] = released_by
        data["release_reason"] = reason
        self.freeze_path.write_text(json.dumps(data, indent=2, default=str))
        self._audit("RELEASED", data)
        _logger.info("Freeze released by %s: %s", released_by, reason)
        return data

    def _load(self) -> dict[str, Any] | None:
        if not self.freeze_path.exists():
            return None
        try:
            return json.loads(self.freeze_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _audit(self, action: str, data: dict[str, Any]) -> None:
        audit_path = self.state_dir / "freeze_audit.jsonl"
        entry = {"timestamp": _utc_now().isoformat(), "action": action, "data": data}
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# Execution Quality Report
# ---------------------------------------------------------------------------


@dataclass
class ExecutionQualityReport:
    ticket_id: str
    broker_order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    limit_price: float = 0.0
    submitted_at: str = ""
    acknowledged_at: str = ""
    filled_at: str = ""
    fill_price: float = 0.0
    arrival_price: float = 0.0
    slippage_bps: float = 0.0
    commission: float = 0.0
    spread_estimate: float = 0.0
    latency_ms: float = 0.0
    partial_fill: bool = False
    reject_reason: str = ""
    execution_status: str = "UNKNOWN"
    lessons_learned: list[str] = field(default_factory=list)
    next_action: str = "STOP"
    generated_at: str = ""

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "broker_order_id": self.broker_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "submitted_at": self.submitted_at,
            "fill_price": self.fill_price,
            "arrival_price": self.arrival_price,
            "slippage_bps": self.slippage_bps,
            "commission": self.commission,
            "latency_ms": self.latency_ms,
            "partial_fill": self.partial_fill,
            "reject_reason": self.reject_reason,
            "execution_status": self.execution_status,
            "lessons_learned": self.lessons_learned,
            "next_action": self.next_action,
            "generated_at": self.generated_at,
        }


def generate_execution_quality(
    ticket_id: str,
    broker_order_id: str = "",
    symbol: str = "",
    side: str = "",
    quantity: float = 0.0,
    limit_price: float = 0.0,
    fill_price: float = 0.0,
    execution_status: str = "filled",
    partial_fill: bool = False,
    reject_reason: str = "",
) -> ExecutionQualityReport:
    slippage = 0.0
    if fill_price > 0 and limit_price > 0:
        slippage = abs(fill_price - limit_price) / limit_price * 10000

    report = ExecutionQualityReport(
        ticket_id=ticket_id,
        broker_order_id=broker_order_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        fill_price=fill_price,
        arrival_price=limit_price,
        slippage_bps=round(slippage, 2),
        partial_fill=partial_fill,
        reject_reason=reject_reason,
        execution_status=execution_status,
    )

    if execution_status == "filled" and not partial_fill:
        report.next_action = "STOP"
        report.lessons_learned.append("Order filled completely at expected price")
    elif execution_status == "filled" and partial_fill:
        report.next_action = "REVIEW"
        report.lessons_learned.append("Partial fill: review liquidity and limit price")
    elif execution_status == "rejected":
        report.next_action = "STOP"
        report.lessons_learned.append(f"Order rejected: {reject_reason}")
    elif execution_status == "timeout":
        report.next_action = "STOP"
        report.lessons_learned.append("Broker timeout: check connectivity and order state")
    else:
        report.next_action = "REVIEW"

    return report


# ---------------------------------------------------------------------------
# G5 Post-Trade Dossier
# ---------------------------------------------------------------------------


@dataclass
class G5PostTradeDossier:
    dossier_id: str = ""
    ticket_id: str = ""
    generated_at: str = ""
    pre_trade_evidence: dict[str, Any] = field(default_factory=dict)
    order_evidence: dict[str, Any] = field(default_factory=dict)
    safety_evidence: dict[str, Any] = field(default_factory=dict)
    execution_evidence: dict[str, Any] = field(default_factory=dict)
    decision: str = "NOT_READY"
    decision_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = _utc_now().isoformat()
        if not self.dossier_id:
            self.dossier_id = f"g5_dossier_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

    def determine_decision(self) -> str:
        reasons: list[str] = []

        if not self.ticket_id:
            self.decision = "NOT_READY"
            reasons.append("No ticket_id")
            self.decision_reasons = reasons
            return self.decision

        if not self.order_evidence:
            self.decision = "NOT_READY"
            reasons.append("No order evidence")
            self.decision_reasons = reasons
            return self.decision

        if not self.execution_evidence:
            self.decision = "NOT_READY"
            reasons.append("No execution quality report")
            self.decision_reasons = reasons
            return self.decision

        submit_once = self.safety_evidence.get("submit_once_active", False)
        if not submit_once:
            self.decision = "BLOCKED"
            reasons.append("Submit-once lock not active — possible second order")
            self.decision_reasons = reasons
            return self.decision

        second_order = self.safety_evidence.get("second_order_detected", True)
        if second_order:
            self.decision = "BLOCKED"
            reasons.append("Second order detected — one-shot violated")
            self.decision_reasons = reasons
            return self.decision

        frozen = self.safety_evidence.get("freeze_active", False)
        if not frozen:
            self.decision = "BLOCKED"
            reasons.append("Freeze not applied after one-shot")
            self.decision_reasons = reasons
            return self.decision

        exec_status = self.execution_evidence.get("execution_status", "")
        if exec_status == "filled":
            self.decision = "STOP_AND_REVIEW"
        elif exec_status == "pending":
            self.decision = "STOP_AND_REVIEW"
        else:
            self.decision = "STOP_AND_REVIEW"

        self.decision_reasons = reasons
        return self.decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "ticket_id": self.ticket_id,
            "generated_at": self.generated_at,
            "pre_trade_evidence": self.pre_trade_evidence,
            "order_evidence": self.order_evidence,
            "safety_evidence": self.safety_evidence,
            "execution_evidence": self.execution_evidence,
            "decision": self.decision,
            "decision_reasons": self.decision_reasons,
        }

    def to_markdown(self) -> str:
        d = self.to_dict()
        lines = [
            "# G5 Post-Trade Dossier",
            "",
            f"**Dossier ID**: `{d['dossier_id']}`",
            f"**Ticket ID**: `{d['ticket_id']}`",
            f"**Generated**: {d['generated_at'][:19]}",
            "",
            "---",
            "## 1. Pre-Trade Evidence",
            f"```json\n{json.dumps(d['pre_trade_evidence'], indent=2)}\n```",
            "",
            "## 2. Order Evidence",
            f"```json\n{json.dumps(d['order_evidence'], indent=2)}\n```",
            "",
            "## 3. Safety Evidence",
            f"| Measure | Status |",
            f"|---------|--------|",
            f"| Submit-Once Lock | {'ACTIVE' if d['safety_evidence'].get('submit_once_active') else 'MISSING'} |",
            f"| Freeze Applied | {'YES' if d['safety_evidence'].get('freeze_active') else 'NO'} |",
            f"| Second Order Detected | {'YES' if d['safety_evidence'].get('second_order_detected') else 'NO'} |",
            "",
            "## 4. Execution Evidence",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Status | {d['execution_evidence'].get('execution_status', '?')} |",
            f"| Fill Price | ${d['execution_evidence'].get('fill_price', 0):,.2f} |",
            f"| Slippage | {d['execution_evidence'].get('slippage_bps', 0):.1f} bps |",
            f"| Commission | ${d['execution_evidence'].get('commission', 0):,.2f} |",
            "",
            "---",
            f"## 5. Decision: **{d['decision']}**",
        ]
        if d["decision_reasons"]:
            for r in d["decision_reasons"]:
                lines.append(f"- {r}")
        return "\n".join(lines)
