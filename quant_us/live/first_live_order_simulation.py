"""First Live Order One-Shot Simulator for G4.

Before ANY real live order, this simulator runs the complete pipeline
with real_submit=False and produces a manual confirmation checklist.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import new_id

_logger = logging.getLogger("first_live_order_simulation")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FirstOrderSimulationResult:
    simulation_id: str
    approval_id: str = ""
    envelope_id: str = ""
    suggested_symbol: str = ""
    suggested_side: str = "buy"
    suggested_qty: float = 1.0
    limit_price: float = 0.0
    notional: float = 0.0
    risk_decision: str = "NOT_CHECKED"
    gate_decision: str = "NOT_CHECKED"
    gate_block_reasons: list[str] = field(default_factory=list)
    real_submit: bool = False
    manual_checklist: list[str] = field(default_factory=list)
    no_real_submit_proof: str = ""
    readiness: str = "NOT_CHECKED"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()
        if not self.no_real_submit_proof:
            self.no_real_submit_proof = (
                "G4 first-order-simulate: real_submit=False. "
                "ReadOnlyLiveBrokerProxy blocks submit_order. "
                "This is a simulation only. No orders were submitted."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "approval_id": self.approval_id,
            "envelope_id": self.envelope_id,
            "suggested_symbol": self.suggested_symbol,
            "suggested_side": self.suggested_side,
            "suggested_qty": self.suggested_qty,
            "limit_price": self.limit_price,
            "notional": self.notional,
            "risk_decision": self.risk_decision,
            "gate_decision": self.gate_decision,
            "gate_block_reasons": self.gate_block_reasons,
            "real_submit": self.real_submit,
            "manual_checklist": self.manual_checklist,
            "no_real_submit_proof": self.no_real_submit_proof,
            "readiness": self.readiness,
            "created_at": self.created_at,
        }

    def to_markdown(self) -> str:
        d = self.to_dict()
        checklist = "\n".join(f"- [ ] {item}" for item in d["manual_checklist"])
        return f"""# First Live Order Simulation

**Simulation ID**: `{d['simulation_id']}`
**Created**: {d['created_at'][:19]}

## Suggested Order
| Field | Value |
|-------|-------|
| Symbol | {d['suggested_symbol']} |
| Side | {d['suggested_side']} |
| Qty | {d['suggested_qty']} |
| Limit Price | ${d['limit_price']:,.2f} |
| Notional | ${d['notional']:,.2f} |

## Risk & Gate Decisions
| Check | Result |
|-------|--------|
| Risk Decision | {d['risk_decision']} |
| Gate Decision | {d['gate_decision']} |
| Block Reasons | {', '.join(d.get('gate_block_reasons', [])) or 'none'} |

## Safety
- **Real Submit**: {"YES" if d['real_submit'] else "**NO**"}
- **No Real Submit Proof**: {d['no_real_submit_proof']}

## Manual Confirmation Checklist
{checklist}

## Readiness
**{d['readiness']}**
"""


class FirstLiveOrderSimulation:
    """Generate a one-shot simulation of the first live order.

    This does NOT submit any real order. It runs all gates and produces
    a manual confirmation checklist for human review.
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def simulate(
        self,
        approval_id: str,
        envelope_id: str,
        symbols: list[str] | None = None,
        strategy_id: str = "etf_rotation",
    ) -> FirstOrderSimulationResult:
        if symbols is None:
            symbols = ["SPY"]

        result = FirstOrderSimulationResult(
            simulation_id=new_id("first_order_sim"),
            approval_id=approval_id,
            envelope_id=envelope_id,
            suggested_symbol=symbols[0],
            suggested_side="buy",
            suggested_qty=1.0,
            notional=1.0 * 500.0,
            limit_price=500.0,
        )

        # Check approval
        result = self._check_approval(result)

        # Check envelope
        result = self._check_envelope(result)

        # Check dossier
        result = self._check_dossier(result)

        # Check env gate
        result = self._check_env(result)

        # Run submission gate
        result = self._run_gate(result)

        # Build checklist
        result.manual_checklist = [
            "Verify the suggested symbol, side, qty, and notional above.",
            f"Confirm approval {approval_id} is APPROVED and not expired.",
            f"Confirm risk envelope {envelope_id} allows this order.",
            "Confirm emergency stop is ARMED (required for live pilot).",
            "Confirm QUANT_LIVE_SUBMISSION_ENABLED=true in environment.",
            "Confirm --confirm-live flag will be passed explicitly.",
            "Confirm this is a regular market session.",
            "Confirm limit order type (market orders blocked).",
            "Confirm max notional is within envelope limits.",
            "Review all gate block reasons above — fix any issues.",
            "After human review, run: live-pilot execute --execute-live-pilot --confirm-live",
        ]

        result.readiness = self._determine_readiness(result)
        result.real_submit = False

        return result

    def _check_approval(self, result: FirstOrderSimulationResult) -> FirstOrderSimulationResult:
        try:
            from quant_us.live.live_pilot_approval import HumanApprovalGate

            gate = HumanApprovalGate()
            check = gate.check(approval_id=result.approval_id)
            if not check.passed:
                result.gate_block_reasons.append(f"approval: {check.reason}")
        except Exception as exc:
            result.gate_block_reasons.append(f"approval_error: {exc}")
        return result

    def _check_envelope(self, result: FirstOrderSimulationResult) -> FirstOrderSimulationResult:
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            envelope = mgr.load(result.envelope_id)
            if envelope is None:
                result.gate_block_reasons.append("envelope_not_found")
            else:
                if result.notional > envelope.max_order_notional:
                    result.gate_block_reasons.append(
                        f"notional_exceeded: ${result.notional:,.2f} > ${envelope.max_order_notional:,.2f}"
                    )
        except Exception as exc:
            result.gate_block_reasons.append(f"envelope_error: {exc}")
        return result

    def _check_dossier(self, result: FirstOrderSimulationResult) -> FirstOrderSimulationResult:
        path = self.data_root / "reports" / "live_pilot_go_no_go.json"
        if not path.exists():
            result.gate_block_reasons.append("dossier_not_found")
        else:
            try:
                data = json.loads(path.read_text())
                if data.get("decision") not in (
                    "GO_FOR_SMALL_LIVE_REVIEW",
                    "READY_FOR_HUMAN_REVIEW",
                ):
                    result.gate_block_reasons.append(
                        f"dossier_decision: {data.get('decision')}"
                    )
            except Exception as exc:
                result.gate_block_reasons.append(f"dossier_error: {exc}")
        return result

    def _check_env(self, result: FirstOrderSimulationResult) -> FirstOrderSimulationResult:
        import os

        if not os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in (
            "1", "true", "yes"
        ):
            result.gate_block_reasons.append("env_gate_not_enabled")
        return result

    def _run_gate(self, result: FirstOrderSimulationResult) -> FirstOrderSimulationResult:
        try:
            from quant_us.live.live_order_submission_gate import LiveOrderSubmissionGate

            gate = LiveOrderSubmissionGate()
            decision = gate.check(
                approval_id=result.approval_id,
                envelope_id=result.envelope_id,
                is_dry_run=True,
                order_notional=result.notional,
                order_type="limit",
            )
            result.gate_decision = decision.decision
            result.gate_block_reasons.extend(decision.block_reasons)
        except Exception as exc:
            result.gate_block_reasons.append(f"gate_error: {exc}")
        return result

    def _determine_readiness(self, result: FirstOrderSimulationResult) -> str:
        if not result.gate_block_reasons:
            return "READY_FOR_MANUAL_CONFIRMATION"
        critical = [r for r in result.gate_block_reasons if "error" in r.lower()]
        if critical:
            return "BLOCKED"
        return "BLOCKED_BY_GATES"

    def save_result(
        self, result: FirstOrderSimulationResult, output_path: str = ""
    ) -> str:
        if not output_path:
            output_path = str(
                self.data_root
                / "live_pilot"
                / f"first_order_sim_{result.simulation_id}.md"
            )
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(result.to_markdown())
        json_path = path.with_suffix(".json")
        json_path.write_text(json.dumps(result.to_dict(), indent=2, default=str))

        _logger.info("First order simulation saved: %s", path)
        return str(path)
