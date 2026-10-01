"""G6 Live Position Exit Plan Generator for Micro Pilot Episodes.

Generates exit plans for any open live positions. Does NOT execute orders.
All exit plans are reduce-only by design — no option to set reduce_only=False.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("g6_exit_plan")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Live Position Exit Plan (DRAFT-only; NEVER auto-executing)
# ---------------------------------------------------------------------------


EXIT_REASONS = frozenset({
    "manual_exit",
    "risk_limit",
    "episode_end",
    "emergency_stop",
    "stale_data",
    "recon_issue",
})

EXIT_PLAN_STATUSES = frozenset({
    "DRAFT",
    "READY_FOR_REVIEW",
    "APPROVED",
    "EXECUTED",
    "CANCELED",
})


@dataclass
class LivePositionExitPlan:
    exit_plan_id: str
    episode_id: str = ""
    ticket_id: str = ""
    symbol: str = ""
    current_qty: float = 0.0  # positive = long, negative = short
    current_market_price: float = 0.0
    average_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    exit_reason: str = "manual_exit"
    suggested_order_type: str = "limit"
    suggested_limit_price: float = 0.0
    suggested_qty: float = 0.0  # ALWAYS absolute value, ALWAYS reduce-only
    suggested_side: str = "sell"  # sell for long positions, buy for short
    reduce_only: bool = True  # ALWAYS True, no option to set False
    estimated_slippage_bps: float = 0.0
    manual_approval_required: bool = True
    status: str = "DRAFT"  # DRAFT|READY_FOR_REVIEW|APPROVED|EXECUTED|CANCELED
    created_at: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    @property
    def is_reduce_only(self) -> bool:
        return self.reduce_only and self.suggested_qty <= abs(self.current_qty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_plan_id": self.exit_plan_id,
            "episode_id": self.episode_id,
            "ticket_id": self.ticket_id,
            "symbol": self.symbol,
            "current_qty": self.current_qty,
            "current_market_price": self.current_market_price,
            "average_entry_price": self.average_entry_price,
            "unrealized_pnl": self.unrealized_pnl,
            "exit_reason": self.exit_reason,
            "suggested_order_type": self.suggested_order_type,
            "suggested_limit_price": self.suggested_limit_price,
            "suggested_qty": self.suggested_qty,
            "suggested_side": self.suggested_side,
            "reduce_only": self.reduce_only,
            "estimated_slippage_bps": self.estimated_slippage_bps,
            "manual_approval_required": self.manual_approval_required,
            "status": self.status,
            "created_at": self.created_at,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Live Position Exit Plan Builder
# ---------------------------------------------------------------------------


class LivePositionExitPlanBuilder:
    """Generates exit plans for live positions.

    All generated plans:
    - Have reduce_only=True (FIXED, no option to change)
    - suggested_qty = abs(current_qty) (zero out position)
    - suggested_side is opposite of position
    """

    def __init__(self, data_root: str = "data") -> None:
        self.plans_dir = Path(data_root) / "live_pilot" / "exit_plans"
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        episode_id: str,
        ticket_id: str,
        symbol: str,
        current_qty: float,
        entry_price: float,
        exit_reason: str = "manual_exit",
        current_market_price: float = 0.0,
    ) -> LivePositionExitPlan:
        """Generate an exit plan.

        Always enforces reduce-only invariants:
        - reduce_only=True (no option to set False)
        - suggested_qty = abs(current_qty) to bring position to zero
        - If long (qty > 0): suggested_side = "sell"
        - If short (qty < 0): suggested_side = "buy"
        - suggested_qty can NEVER exceed abs(current_qty)
        """
        if exit_reason not in EXIT_REASONS:
            raise ValueError(
                f"Invalid exit_reason '{exit_reason}'. "
                f"Valid: {sorted(EXIT_REASONS)}"
            )

        abs_qty = abs(current_qty)

        # Determine exit side (opposite of position)
        if current_qty > 0:
            side = "sell"
        elif current_qty < 0:
            side = "buy"
        else:
            side = "sell"  # default for zero position (edge case)

        # Calculate unrealized PnL
        if current_market_price > 0 and entry_price > 0:
            unrealized = (current_market_price - entry_price) * abs_qty
            if current_qty < 0:
                unrealized = -unrealized
        else:
            unrealized = 0.0

        plan_id = f"exit_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

        plan = LivePositionExitPlan(
            exit_plan_id=plan_id,
            episode_id=episode_id,
            ticket_id=ticket_id,
            symbol=symbol,
            current_qty=current_qty,
            current_market_price=current_market_price,
            average_entry_price=entry_price,
            unrealized_pnl=round(unrealized, 2),
            exit_reason=exit_reason,
            suggested_qty=abs_qty,
            suggested_side=side,
            reduce_only=True,  # ALWAYS True
            status="DRAFT",
        )

        # Set suggested limit price with small offset for reduce-only safety
        if current_market_price > 0:
            if side == "sell":
                # Slightly below market to fill
                plan.suggested_limit_price = round(current_market_price * 0.998, 2)
            else:
                # Slightly above market to fill
                plan.suggested_limit_price = round(current_market_price * 1.002, 2)
        else:
            plan.suggested_limit_price = entry_price

        # Estimate slippage
        if current_market_price > 0 and entry_price > 0:
            slippage = abs(current_market_price - entry_price) / entry_price * 10000
            plan.estimated_slippage_bps = round(slippage, 2)

        _logger.info(
            "Exit plan built: %s symbol=%s qty=%s side=%s reason=%s",
            plan_id, symbol, abs_qty, side, exit_reason,
        )

        return plan

    def approve(self, plan: LivePositionExitPlan, approved_by: str = "") -> LivePositionExitPlan:
        """Mark an exit plan as APPROVED (human review step)."""
        if plan.status != "READY_FOR_REVIEW":
            raise ValueError(
                f"Cannot approve plan in status '{plan.status}'. "
                "Must be READY_FOR_REVIEW first."
            )
        plan.status = "APPROVED"
        plan.notes += f"\nApproved by: {approved_by}" if approved_by else "\nApproved"
        self.save(plan)
        self._audit("APPROVED", plan)
        return plan

    def mark_ready(self, plan: LivePositionExitPlan) -> LivePositionExitPlan:
        """Move plan from DRAFT to READY_FOR_REVIEW."""
        if plan.status != "DRAFT":
            raise ValueError(
                f"Cannot mark ready: status is '{plan.status}'. Must be DRAFT."
            )
        plan.status = "READY_FOR_REVIEW"
        self.save(plan)
        self._audit("READY_FOR_REVIEW", plan)
        return plan

    def cancel(self, plan: LivePositionExitPlan, reason: str = "") -> LivePositionExitPlan:
        """Cancel an exit plan."""
        plan.status = "CANCELED"
        if reason:
            plan.notes += f"\nCanceled: {reason}"
        self.save(plan)
        self._audit("CANCELED", plan)
        return plan

    def save(self, plan: LivePositionExitPlan) -> str:
        """Save to data/live_pilot/exit_plans/{exit_plan_id}.json"""
        path = self.plans_dir / f"{plan.exit_plan_id}.json"
        path.write_text(json.dumps(plan.to_dict(), indent=2, default=str))
        _logger.info("Exit plan saved: %s", path)
        return str(path)

    def load(self, exit_plan_id: str) -> LivePositionExitPlan | None:
        path = self.plans_dir / f"{exit_plan_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return LivePositionExitPlan(
                exit_plan_id=data.get("exit_plan_id", exit_plan_id),
                episode_id=data.get("episode_id", ""),
                ticket_id=data.get("ticket_id", ""),
                symbol=data.get("symbol", ""),
                current_qty=data.get("current_qty", 0.0),
                current_market_price=data.get("current_market_price", 0.0),
                average_entry_price=data.get("average_entry_price", 0.0),
                unrealized_pnl=data.get("unrealized_pnl", 0.0),
                exit_reason=data.get("exit_reason", "manual_exit"),
                suggested_order_type=data.get("suggested_order_type", "limit"),
                suggested_limit_price=data.get("suggested_limit_price", 0.0),
                suggested_qty=data.get("suggested_qty", 0.0),
                suggested_side=data.get("suggested_side", "sell"),
                reduce_only=data.get("reduce_only", True),
                estimated_slippage_bps=data.get("estimated_slippage_bps", 0.0),
                manual_approval_required=data.get("manual_approval_required", True),
                status=data.get("status", "DRAFT"),
                created_at=data.get("created_at", ""),
                notes=data.get("notes", ""),
            )
        except (json.JSONDecodeError, OSError) as exc:
            _logger.warning("Failed to load exit plan %s: %s", exit_plan_id, exc)
            return None

    def list_plans(self, episode_id: str = "") -> list[LivePositionExitPlan]:
        """List all exit plans, optionally filtered by episode_id."""
        plans: list[LivePositionExitPlan] = []
        if not self.plans_dir.exists():
            return plans
        for f in sorted(self.plans_dir.glob("exit_*.json")):
            plan = self.load(f.stem)
            if plan is not None:
                if not episode_id or plan.episode_id == episode_id:
                    plans.append(plan)
        return plans

    def _audit(self, action: str, plan: LivePositionExitPlan) -> None:
        audit_path = self.plans_dir / "exit_plan_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "exit_plan_id": plan.exit_plan_id,
            "episode_id": plan.episode_id,
            "symbol": plan.symbol,
            "current_qty": plan.current_qty,
            "suggested_qty": plan.suggested_qty,
            "reduce_only": plan.reduce_only,
            "status": plan.status,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
