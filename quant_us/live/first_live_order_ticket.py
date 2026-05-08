"""First Live Order Ticket & Final Human Confirmation Gate for G5.

Before the first real live order, a human-reviewable ticket must be
generated. The FinalHumanConfirmationGate enforces explicit confirmation
with the --i-understand-this-is-real-money flag.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quant_us.core.types import new_id

_logger = logging.getLogger("first_live_order_ticket")

TICKET_EXPIRY_MINUTES = 15


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# First Live Order Ticket
# ---------------------------------------------------------------------------


@dataclass
class FirstLiveOrderTicket:
    ticket_id: str
    run_id: str = ""
    approval_id: str = ""
    envelope_id: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    symbol: str = ""
    side: str = "buy"
    quantity: float = 0.0
    limit_price: float = 0.0
    estimated_notional: float = 0.0
    max_allowed_notional: float = 0.0
    account_cash: float = 0.0
    buying_power: float = 0.0
    current_position: float = 0.0
    target_position: float = 0.0
    order_intent_id: str = ""
    risk_check_id: str = ""
    oms_decision_id: str = ""
    gate_decision_id: str = ""
    market_session: str = "regular"
    latest_bar_timestamp: str = ""
    data_freshness_status: str = "pending"
    reconciliation_status: str = "pending"
    emergency_stop_status: str = "ARMED"
    created_at: str = ""
    expires_at: str = ""
    status: str = "DRAFT"

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()
        if not self.expires_at:
            self.expires_at = (_utc_now() + timedelta(minutes=TICKET_EXPIRY_MINUTES)).isoformat()

    @property
    def is_expired(self) -> bool:
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            return _utc_now() > expiry
        except (ValueError, TypeError):
            return True

    @property
    def is_executable(self) -> bool:
        return self.status == "APPROVED_FOR_ONE_SHOT" and not self.is_expired

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "run_id": self.run_id,
            "approval_id": self.approval_id,
            "envelope_id": self.envelope_id,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "estimated_notional": self.estimated_notional,
            "max_allowed_notional": self.max_allowed_notional,
            "account_cash": self.account_cash,
            "buying_power": self.buying_power,
            "current_position": self.current_position,
            "target_position": self.target_position,
            "order_intent_id": self.order_intent_id,
            "risk_check_id": self.risk_check_id,
            "gate_decision_id": self.gate_decision_id,
            "market_session": self.market_session,
            "latest_bar_timestamp": self.latest_bar_timestamp,
            "data_freshness_status": self.data_freshness_status,
            "reconciliation_status": self.reconciliation_status,
            "emergency_stop_status": self.emergency_stop_status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status,
        }

    def to_markdown(self) -> str:
        d = self.to_dict()
        return f"""# First Live Order Ticket

**Ticket ID**: `{d['ticket_id']}`
**Status**: {d['status']}
**Created**: {d['created_at'][:19]}
**Expires**: {d['expires_at'][:19]}
**Expired**: {'YES' if self.is_expired else 'NO'}

## Order Details
| Field | Value |
|-------|-------|
| Symbol | {d['symbol']} |
| Side | {d['side']} |
| Quantity | {d['quantity']} |
| Limit Price | ${d['limit_price']:,.2f} |
| Estimated Notional | ${d['estimated_notional']:,.2f} |
| Max Allowed Notional | ${d['max_allowed_notional']:,.2f} |

## Account State
| Field | Value |
|-------|-------|
| Cash | ${d['account_cash']:,.2f} |
| Buying Power | ${d['buying_power']:,.2f} |
| Current Position | {d['current_position']} |

## Gate Status
| Gate | Status |
|------|--------|
| Approval | {d['approval_id']} |
| Envelope | {d['envelope_id']} |
| Market Session | {d['market_session']} |
| Data Freshness | {d['data_freshness_status']} |
| Reconciliation | {d['reconciliation_status']} |
| Emergency Stop | {d['emergency_stop_status']} |

## Manual Confirmation Checklist
- [ ] Verify symbol: {d['symbol']}
- [ ] Verify side: {d['side']}
- [ ] Verify quantity: {d['quantity']}
- [ ] Verify limit price: ${d['limit_price']:,.2f}
- [ ] Notional ({d['estimated_notional']}) within envelope limit ({d['max_allowed_notional']})
- [ ] Emergency stop is ARMED
- [ ] Rollback plan is ready
- [ ] Reconciliation is clean
- [ ] I understand this is REAL MONEY
- [ ] I understand only ONE order will be submitted
- [ ] I understand the system will FREEZE after execution
"""


class FirstLiveOrderTicketBuilder:
    """Builds a FirstLiveOrderTicket from current system state."""

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def build(
        self,
        approval_id: str,
        envelope_id: str,
        symbol: str = "SPY",
        side: str = "buy",
        quantity: float = 1.0,
        limit_price: float = 500.0,
    ) -> FirstLiveOrderTicket:
        ticket = FirstLiveOrderTicket(
            ticket_id=new_id("ticket"),
            approval_id=approval_id,
            envelope_id=envelope_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            estimated_notional=quantity * limit_price,
            status="DRAFT",
        )

        # Load envelope for max notional
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            env = mgr.load(envelope_id)
            if env:
                ticket.max_allowed_notional = env.max_order_notional
                if ticket.estimated_notional > env.max_order_notional:
                    ticket.status = "REJECTED"
        except Exception:
            pass

        # Check approval
        try:
            from quant_us.live.live_pilot_approval import HumanApprovalGate

            gate = HumanApprovalGate()
            result = gate.check(approval_id=approval_id)
            if not result.passed:
                ticket.status = "REJECTED"
        except Exception:
            pass

        # Check emergency stop
        try:
            from quant_us.live.emergency_stop import EmergencyStopController

            ctrl = EmergencyStopController(state_dir=f"{self.data_root}/live_pilot")
            ticket.emergency_stop_status = ctrl.status()["state"]
            if ctrl.is_triggered:
                ticket.status = "REJECTED"
        except Exception:
            pass

        return ticket

    def save_ticket(self, ticket: FirstLiveOrderTicket, output_path: str = "") -> str:
        if not output_path:
            output_path = str(self.data_root / "live_pilot" / f"ticket_{ticket.ticket_id}.md")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ticket.to_markdown())
        json_path = path.with_suffix(".json")
        json_path.write_text(json.dumps(ticket.to_dict(), indent=2, default=str))
        return str(path)


# ---------------------------------------------------------------------------
# Final Human Confirmation Gate
# ---------------------------------------------------------------------------


@dataclass
class FinalConfirmationResult:
    passed: bool
    reason: str = ""
    ticket_id: str = ""
    checks: dict[str, bool] = field(default_factory=dict)


class FinalHumanConfirmationGate:
    """The LAST gate before a real one-shot live order.

    Requires explicit human confirmation of:
    - Ticket ID
    - Understanding this is real money
    - Confirm-live flag
    - Execute-one-shot flag
    """

    def __init__(self, audit_dir: str = "data/live_pilot/audit") -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def check(
        self,
        ticket_id: str = "",
        i_understand_real_money: bool = False,
        confirm_live: bool = False,
        execute_one_shot: bool = False,
        confirm_ticket: str = "",
    ) -> FinalConfirmationResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []

        checks["ticket_id_provided"] = bool(ticket_id)
        if not checks["ticket_id_provided"]:
            reasons.append("No ticket_id provided")

        checks["confirm_ticket_matches"] = confirm_ticket == ticket_id if confirm_ticket else False
        if not checks["confirm_ticket_matches"]:
            reasons.append(f"--confirm-ticket {confirm_ticket} does not match ticket {ticket_id}")

        checks["understand_real_money"] = i_understand_real_money
        if not checks["understand_real_money"]:
            reasons.append("--i-understand-this-is-real-money not set")

        checks["confirm_live"] = confirm_live
        if not checks["confirm_live"]:
            reasons.append("--confirm-live not set")

        checks["execute_one_shot"] = execute_one_shot
        if not checks["execute_one_shot"]:
            reasons.append("--execute-one-shot not set")

        # Check ticket expiry
        if ticket_id:
            ticket_path = Path(f"data/live_pilot/ticket_{ticket_id}.json")
            if ticket_path.exists():
                try:
                    data = json.loads(ticket_path.read_text())
                    exp = data.get("expires_at", "")
                    if exp:
                        try:
                            expiry = datetime.fromisoformat(exp)
                            checks["ticket_not_expired"] = _utc_now() <= expiry
                            if not checks["ticket_not_expired"]:
                                reasons.append(f"Ticket {ticket_id} expired at {exp}")
                        except (ValueError, TypeError):
                            checks["ticket_not_expired"] = False
                            reasons.append("Cannot parse ticket expiry")
                    checks["ticket_status_executable"] = data.get("status") in (
                        "APPROVED_FOR_ONE_SHOT", "DRAFT", "READY_FOR_REVIEW"
                    )
                except (json.JSONDecodeError, OSError):
                    checks["ticket_not_expired"] = False

        passed = len(reasons) == 0

        result = FinalConfirmationResult(
            passed=passed,
            reason="; ".join(reasons) if reasons else "All confirmations received",
            ticket_id=ticket_id,
            checks=checks,
        )

        self._audit(result)
        return result

    def _audit(self, result: FinalConfirmationResult) -> None:
        audit_path = self.audit_dir / "final_confirmation_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "ticket_id": result.ticket_id,
            "passed": result.passed,
            "reason": result.reason,
            "checks": result.checks,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
