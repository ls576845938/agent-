"""Live Order Audit Trail for G4 Small Live Pilot Execution.

Every live order intent — whether blocked, dry-run, or submitted —
produces an immutable audit record. Secrets are never logged.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.live.readonly_live_broker import mask_secret, mask_account_id

_logger = logging.getLogger("live_order_audit")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LiveOrderAuditRecord:
    """Immutable audit record for every live order attempt."""

    audit_id: str
    run_id: str = ""
    approval_id: str = ""
    envelope_id: str = ""
    dossier_id: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    signal_id: str = ""
    target_position_id: str = ""
    order_intent_id: str = ""
    risk_check_id: str = ""
    oms_decision_id: str = ""
    gate_decision: str = "BLOCKED"
    gate_block_reasons: list[str] = field(default_factory=list)
    live_order_preview_id: str = ""
    client_order_id: str = ""
    broker_order_id: str = ""  # masked in output
    symbol: str = ""
    side: str = ""
    qty: float = 0.0
    limit_price: float = 0.0
    notional: float = 0.0
    real_submit: bool = False
    submitted_at: str = ""
    status: str = "DRAFT"
    fill_status: str = "NONE"
    reconciliation_status: str = "PENDING"
    emergency_stop_status: str = "ARMED"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "run_id": self.run_id,
            "approval_id": self.approval_id,
            "envelope_id": self.envelope_id,
            "dossier_id": self.dossier_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "signal_id": self.signal_id,
            "target_position_id": self.target_position_id,
            "order_intent_id": self.order_intent_id,
            "risk_check_id": self.risk_check_id,
            "oms_decision_id": self.oms_decision_id,
            "gate_decision": self.gate_decision,
            "gate_block_reasons": self.gate_block_reasons,
            "live_order_preview_id": self.live_order_preview_id,
            "client_order_id": self.client_order_id,
            "broker_order_id": mask_secret(self.broker_order_id) if self.broker_order_id else "",
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "limit_price": self.limit_price,
            "notional": self.notional,
            "real_submit": self.real_submit,
            "submitted_at": self.submitted_at,
            "status": self.status,
            "fill_status": self.fill_status,
            "reconciliation_status": self.reconciliation_status,
            "emergency_stop_status": self.emergency_stop_status,
            "created_at": self.created_at,
        }

    def to_summary_line(self) -> str:
        icon = "REAL" if self.real_submit else "DRY"
        return (
            f"[{icon}] {self.created_at[:19]} {self.symbol} {self.side} "
            f"qty={self.qty} notional=${self.notional:,.2f} "
            f"gate={self.gate_decision} status={self.status}"
        )


class LiveOrderAuditTrail:
    """Append-only audit trail for all live order attempts.

    Dry-run, blocked, and submitted orders all produce records.
    Records are written as JSONL — never overwritten.
    """

    def __init__(self, audit_dir: str = "data/live_pilot/audit") -> None:
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.audit_dir / "live_order_audit.jsonl"

    def record(self, record: LiveOrderAuditRecord) -> None:
        with open(self.audit_path, "a") as f:
            f.write(json.dumps(record.to_dict(), default=str) + "\n")
        _logger.info("Audit recorded: %s", record.to_summary_line())

    def record_blocked(
        self,
        audit_id: str,
        reasons: list[str],
        order_intent_id: str = "",
        symbol: str = "",
        notional: float = 0.0,
    ) -> None:
        record = LiveOrderAuditRecord(
            audit_id=audit_id,
            gate_decision="BLOCKED",
            gate_block_reasons=reasons,
            order_intent_id=order_intent_id,
            symbol=symbol,
            notional=notional,
            real_submit=False,
            status="BLOCKED",
        )
        self.record(record)

    def record_dry_run(
        self,
        audit_id: str,
        run_id: str = "",
        approval_id: str = "",
        envelope_id: str = "",
        order_intent_id: str = "",
        symbol: str = "",
        side: str = "",
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> None:
        record = LiveOrderAuditRecord(
            audit_id=audit_id,
            run_id=run_id,
            approval_id=approval_id,
            envelope_id=envelope_id,
            gate_decision="BLOCKED",
            gate_block_reasons=["dry_run_mode"],
            order_intent_id=order_intent_id,
            symbol=symbol,
            side=side,
            qty=qty,
            notional=notional,
            real_submit=False,
            status="DRY_RUN",
        )
        self.record(record)

    def record_submitted(
        self,
        audit_id: str,
        run_id: str = "",
        approval_id: str = "",
        envelope_id: str = "",
        order_intent_id: str = "",
        client_order_id: str = "",
        broker_order_id: str = "",
        symbol: str = "",
        side: str = "",
        qty: float = 0.0,
        notional: float = 0.0,
    ) -> None:
        record = LiveOrderAuditRecord(
            audit_id=audit_id,
            run_id=run_id,
            approval_id=approval_id,
            envelope_id=envelope_id,
            gate_decision="APPROVED_FOR_SUBMIT",
            order_intent_id=order_intent_id,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            notional=notional,
            real_submit=True,
            submitted_at=_utc_now().isoformat(),
            status="SUBMITTED",
        )
        self.record(record)

    def read_all(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        with open(self.audit_path) as f:
            for line in f:
                try:
                    entries.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    continue
        return entries[-limit:]

    def read_by_run(self, run_id: str) -> list[dict[str, Any]]:
        return [e for e in self.read_all(limit=10000) if e.get("run_id") == run_id]

    def real_submit_count(self) -> int:
        return sum(1 for e in self.read_all(limit=10000) if e.get("real_submit"))

    def to_markdown(self, limit: int = 50) -> str:
        entries = self.read_all(limit=limit)
        lines = [
            "# Live Order Audit Trail",
            "",
            f"**Total entries**: {len(entries)}",
            f"**Real submits**: {self.real_submit_count()}",
            "",
            "| Time | Symbol | Side | Qty | Notional | Gate | Real | Status |",
            "|------|--------|------|-----|----------|------|------|--------|",
        ]
        for e in entries:
            lines.append(
                f"| {e.get('created_at', '')[:19]} "
                f"| {e.get('symbol', '')} "
                f"| {e.get('side', '')} "
                f"| {e.get('qty', 0)} "
                f"| ${e.get('notional', 0):,.0f} "
                f"| {e.get('gate_decision', '')} "
                f"| {'YES' if e.get('real_submit') else 'no'} "
                f"| {e.get('status', '')} |"
            )
        return "\n".join(lines)
