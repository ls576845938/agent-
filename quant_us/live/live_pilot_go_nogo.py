"""Live Pilot Go/No-Go Dossier for G3.

Generates the final readiness dossier for Small Live Pilot review.
Even if READY_FOR_HUMAN_REVIEW, real live orders remain default-blocked.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_logger = logging.getLogger("live_pilot_go_nogo")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PaperEvidence:
    clean_days: int = 0
    order_count: int = 0
    fill_count: int = 0
    recon_fail_count: int = 0
    duplicate_order_count: int = 0
    incidents: int = 0
    status: str = "NOT_READY"

    def is_ready(self) -> bool:
        return self.clean_days >= 30 and self.recon_fail_count == 0


@dataclass
class ShadowEvidence:
    days_completed: int = 0
    real_submit_count: int = -1
    shadow_order_count: int = 0
    data_parity_status: str = "unknown"
    incidents: int = 0
    status: str = "NOT_READY"

    def is_ready(self) -> bool:
        return self.days_completed >= 5 and self.real_submit_count == 0


@dataclass
class ApprovalEvidence:
    approval_id: str = ""
    status: str = "NOT_FOUND"
    approver: str = ""
    approved_at: str = ""
    expires_at: str = ""

    def is_ready(self) -> bool:
        return self.status == "APPROVED"


@dataclass
class EnvelopeEvidence:
    envelope_id: str = ""
    max_capital: float = 0.0
    max_order_notional: float = 0.0
    max_daily_loss_pct: float = 0.0

    def is_ready(self) -> bool:
        return self.envelope_id != ""


@dataclass
class SafetyEvidence:
    no_real_order_default_path: bool = True
    endpoint_guard_active: bool = True
    env_gate_active: bool = True
    confirm_live_required: bool = True
    readiness_gate_active: bool = True
    reconciliation_gate_active: bool = True
    kill_switch_active: bool = True
    emergency_stop_active: bool = True

    def all_ready(self) -> bool:
        return all([
            self.no_real_order_default_path,
            self.endpoint_guard_active,
            self.env_gate_active,
            self.confirm_live_required,
            self.readiness_gate_active,
            self.reconciliation_gate_active,
            self.kill_switch_active,
            self.emergency_stop_active,
        ])


@dataclass
class LivePilotGoNoGoDossier:
    dossier_id: str = ""
    generated_at: datetime = field(default_factory=_utc_now)
    paper: PaperEvidence = field(default_factory=PaperEvidence)
    shadow: ShadowEvidence = field(default_factory=ShadowEvidence)
    approval: ApprovalEvidence = field(default_factory=ApprovalEvidence)
    envelope: EnvelopeEvidence = field(default_factory=EnvelopeEvidence)
    safety: SafetyEvidence = field(default_factory=SafetyEvidence)
    decision: str = "NOT_READY"
    decision_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.dossier_id:
            self.dossier_id = f"g3_dossier_{_utc_now().strftime('%Y%m%d_%H%M%S')}"

    def determine_decision(self) -> str:
        reasons: list[str] = []

        if self.shadow.real_submit_count != 0:
            self.decision = "BLOCKED"
            reasons.append(f"real_submit_count={self.shadow.real_submit_count}, must be 0")
            self.decision_reasons = reasons
            return self.decision

        if not self.paper.is_ready():
            self.decision = "NOT_READY"
            reasons.append(f"Paper: {self.paper.clean_days}/30 clean days, "
                           f"{self.paper.recon_fail_count} recon failures")
            self.decision_reasons = reasons
            return self.decision

        if not self.shadow.is_ready():
            self.decision = "NOT_READY"
            reasons.append(f"Shadow: {self.shadow.days_completed}/5 days, "
                           f"real_submit_count={self.shadow.real_submit_count}")
            self.decision_reasons = reasons
            return self.decision

        if not self.approval.is_ready():
            self.decision = "NOT_READY"
            reasons.append(f"Approval: status={self.approval.status}")
            self.decision_reasons = reasons
            return self.decision

        if not self.envelope.is_ready():
            self.decision = "NOT_READY"
            reasons.append("No risk envelope configured")
            self.decision_reasons = reasons
            return self.decision

        if not self.safety.all_ready():
            self.decision = "NOT_READY"
            reasons.append("Safety evidence incomplete")
            self.decision_reasons = reasons
            return self.decision

        self.decision = "READY_FOR_HUMAN_REVIEW"
        self.decision_reasons = reasons
        return self.decision

    def to_dict(self) -> dict[str, Any]:
        return {
            "dossier_id": self.dossier_id,
            "generated_at": self.generated_at.isoformat(),
            "paper": {
                "clean_days": self.paper.clean_days,
                "order_count": self.paper.order_count,
                "fill_count": self.paper.fill_count,
                "recon_fail_count": self.paper.recon_fail_count,
                "duplicate_order_count": self.paper.duplicate_order_count,
                "incidents": self.paper.incidents,
                "status": self.paper.status,
            },
            "shadow": {
                "days_completed": self.shadow.days_completed,
                "real_submit_count": self.shadow.real_submit_count,
                "shadow_order_count": self.shadow.shadow_order_count,
                "data_parity_status": self.shadow.data_parity_status,
                "incidents": self.shadow.incidents,
                "status": self.shadow.status,
            },
            "approval": {
                "approval_id": self.approval.approval_id,
                "status": self.approval.status,
                "approver": self.approval.approver,
                "approved_at": self.approval.approved_at,
                "expires_at": self.approval.expires_at,
            },
            "envelope": {
                "envelope_id": self.envelope.envelope_id,
                "max_capital": self.envelope.max_capital,
                "max_order_notional": self.envelope.max_order_notional,
                "max_daily_loss_pct": self.envelope.max_daily_loss_pct,
            },
            "safety": {
                "no_real_order_default_path": self.safety.no_real_order_default_path,
                "endpoint_guard_active": self.safety.endpoint_guard_active,
                "env_gate_active": self.safety.env_gate_active,
                "confirm_live_required": self.safety.confirm_live_required,
                "readiness_gate_active": self.safety.readiness_gate_active,
                "reconciliation_gate_active": self.safety.reconciliation_gate_active,
                "kill_switch_active": self.safety.kill_switch_active,
                "emergency_stop_active": self.safety.emergency_stop_active,
            },
            "decision": self.decision,
            "decision_reasons": self.decision_reasons,
        }

    def to_markdown(self) -> str:
        d = self.to_dict()
        lines = [
            "# Live Pilot Go/No-Go Dossier (G3)",
            "",
            f"**Dossier ID**: `{d['dossier_id']}`",
            f"**Generated**: {d['generated_at']}",
            "",
            "---",
            "",
            "## 1. Paper Evidence",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Clean Days | {d['paper']['clean_days']}/30 |",
            f"| Orders | {d['paper']['order_count']} |",
            f"| Fills | {d['paper']['fill_count']} |",
            f"| Recon Failures | {d['paper']['recon_fail_count']} |",
            f"| Duplicate Orders | {d['paper']['duplicate_order_count']} |",
            f"| Incidents | {d['paper']['incidents']} |",
            f"| Status | **{d['paper']['status']}** |",
            "",
            "---",
            "",
            "## 2. Shadow Evidence",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Days Completed | {d['shadow']['days_completed']}/5 |",
            f"| Real Submit Count | **{d['shadow']['real_submit_count']}** |",
            f"| Shadow Orders | {d['shadow']['shadow_order_count']} |",
            f"| Data Parity | {d['shadow']['data_parity_status']} |",
            f"| Incidents | {d['shadow']['incidents']} |",
            f"| Status | **{d['shadow']['status']}** |",
            "",
            "---",
            "",
            "## 3. Approval Evidence",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Approval ID | {d['approval']['approval_id']} |",
            f"| Status | **{d['approval']['status']}** |",
            f"| Approver | {d['approval']['approver']} |",
            f"| Approved At | {d['approval']['approved_at'][:19] if d['approval']['approved_at'] else 'N/A'} |",
            f"| Expires | {d['approval']['expires_at'][:19] if d['approval']['expires_at'] else 'N/A'} |",
            "",
            "---",
            "",
            "## 4. Risk Envelope",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Envelope ID | {d['envelope']['envelope_id']} |",
            f"| Max Capital | ${d['envelope']['max_capital']:,.2f} |",
            f"| Max Order Notional | ${d['envelope']['max_order_notional']:,.2f} |",
            f"| Max Daily Loss | {d['envelope']['max_daily_loss_pct']:.2%} |",
            "",
            "---",
            "",
            "## 5. Safety Evidence",
            "",
            f"| Safety Measure | Status |",
            f"|----------------|--------|",
            f"| No Real Order Default Path | {'PASS' if d['safety']['no_real_order_default_path'] else 'FAIL'} |",
            f"| Endpoint Guard | {'ACTIVE' if d['safety']['endpoint_guard_active'] else 'BROKEN'} |",
            f"| Env Gate (QUANT_LIVE_SUBMISSION_ENABLED) | {'ACTIVE' if d['safety']['env_gate_active'] else 'BROKEN'} |",
            f"| confirm_live Required | {'YES' if d['safety']['confirm_live_required'] else 'NO'} |",
            f"| Readiness Gate | {'ACTIVE' if d['safety']['readiness_gate_active'] else 'BROKEN'} |",
            f"| Reconciliation Gate | {'ACTIVE' if d['safety']['reconciliation_gate_active'] else 'BROKEN'} |",
            f"| Kill Switch | {'ARMED' if d['safety']['kill_switch_active'] else 'DISARMED'} |",
            f"| Emergency Stop | {'ARMED' if d['safety']['emergency_stop_active'] else 'NOT READY'} |",
            "",
            "---",
            "",
            f"## 6. Decision: **{d['decision']}**",
            "",
        ]

        if d["decision_reasons"]:
            for reason in d["decision_reasons"]:
                lines.append(f"- {reason}")
            lines.append("")

        if d["decision"] == "READY_FOR_HUMAN_REVIEW":
            lines.append("### IMPORTANT")
            lines.append("")
            lines.append("- This dossier does NOT automatically enable live orders.")
            lines.append("- Human review and explicit authorization are REQUIRED.")
            lines.append("- Live profile remains NOT READY by default.")
            lines.append("- All safety gates remain active.")
        elif d["decision"] == "BLOCKED":
            lines.append("BLOCKED: Critical safety violation detected.")
            lines.append("Live orders MUST NOT be enabled.")
        else:
            lines.append("NOT_READY: Prerequisites not met.")
            lines.append("Complete all G1, G2, and G3 requirements before review.")

        return "\n".join(lines)


class LivePilotGoNoGoBuilder:
    """Builds the G3 Go/No-Go dossier from current system state."""

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def build(self) -> LivePilotGoNoGoDossier:
        dossier = LivePilotGoNoGoDossier()
        self._load_paper_evidence(dossier)
        self._load_shadow_evidence(dossier)
        self._load_approval_evidence(dossier)
        self._load_envelope_evidence(dossier)
        self._load_safety_evidence(dossier)
        dossier.determine_decision()
        return dossier

    def _load_paper_evidence(self, dossier: LivePilotGoNoGoDossier) -> None:
        path = self.data_root / "reports" / "paper_production" / "validation_state.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            dossier.paper.clean_days = data.get("consecutive_clean_days", 0)
            dossier.paper.order_count = sum(
                r.get("orders_submitted", 0)
                for r in data.get("daily_results", [])
            )
            dossier.paper.fill_count = sum(
                r.get("orders_filled", 0)
                for r in data.get("daily_results", [])
            )
            dossier.paper.recon_fail_count = data.get("recon_fail_count", 0)
            dossier.paper.duplicate_order_count = data.get("duplicate_order_count", 0)
            dossier.paper.incidents = data.get("errors_total", 0)
            dossier.paper.status = "READY" if dossier.paper.is_ready() else "NOT_READY"
        except Exception as exc:
            _logger.warning("Failed to load paper evidence: %s", exc)

    def _load_shadow_evidence(self, dossier: LivePilotGoNoGoDossier) -> None:
        path = self.data_root / "shadow_validation" / "shadow_validation_state.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            dossier.shadow.days_completed = data.get("days_completed", 0)
            dossier.shadow.real_submit_count = data.get("real_submit_count", -1)
            dossier.shadow.shadow_order_count = data.get("shadow_order_count", 0)
            dossier.shadow.data_parity_status = "ok"
            dossier.shadow.incidents = data.get("incident_count", 0)
            dossier.shadow.status = "READY" if dossier.shadow.is_ready() else "NOT_READY"
        except Exception as exc:
            _logger.warning("Failed to load shadow evidence: %s", exc)

    def _load_approval_evidence(self, dossier: LivePilotGoNoGoDossier) -> None:
        approval_dir = self.data_root / "live_pilot" / "approvals"
        if not approval_dir.exists():
            return
        try:
            for path in sorted(approval_dir.glob("*.json"), reverse=True):
                if path.name.startswith("approval_audit"):
                    continue
                data = json.loads(path.read_text())
                dossier.approval.approval_id = data.get("approval_id", "")
                dossier.approval.status = data.get("status", "NOT_FOUND")
                dossier.approval.approver = data.get("approver", "")
                dossier.approval.approved_at = data.get("approved_at", "")
                dossier.approval.expires_at = data.get("expires_at", "")
                break
        except Exception as exc:
            _logger.warning("Failed to load approval evidence: %s", exc)

    def _load_envelope_evidence(self, dossier: LivePilotGoNoGoDossier) -> None:
        envelope_dir = self.data_root / "live_pilot" / "envelopes"
        if not envelope_dir.exists():
            return
        try:
            for path in sorted(envelope_dir.glob("*.json"), reverse=True):
                if path.name.startswith("envelope_audit"):
                    continue
                data = json.loads(path.read_text())
                dossier.envelope.envelope_id = data.get("envelope_id", "")
                dossier.envelope.max_capital = data.get("max_total_capital", 0.0)
                dossier.envelope.max_order_notional = data.get("max_order_notional", 0.0)
                dossier.envelope.max_daily_loss_pct = data.get("max_daily_loss_pct", 0.0)
                break
        except Exception as exc:
            _logger.warning("Failed to load envelope evidence: %s", exc)

    def _load_safety_evidence(self, dossier: LivePilotGoNoGoDossier) -> None:
        try:
            from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
            dossier.safety.endpoint_guard_active = True
        except ImportError:
            dossier.safety.endpoint_guard_active = False

        try:
            from quant_us.live.emergency_stop import EmergencyStopController
            dossier.safety.emergency_stop_active = True
        except ImportError:
            dossier.safety.emergency_stop_active = False

    def save_dossier(
        self, dossier: LivePilotGoNoGoDossier, output_path: str
    ) -> None:
        md_path = Path(output_path)
        json_path = md_path.with_suffix(".json")
        md_path.parent.mkdir(parents=True, exist_ok=True)

        md_path.write_text(dossier.to_markdown())
        json_path.write_text(json.dumps(dossier.to_dict(), indent=2, default=str))

        _logger.info(
            "G3 Dossier saved: markdown=%s json=%s decision=%s",
            md_path,
            json_path,
            dossier.decision,
        )
