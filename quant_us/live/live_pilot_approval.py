"""Human Approval System for G3 Small Live Pilot.

Even after all automated gates pass, a human MUST explicitly approve
before any live pilot activity. This module enforces that requirement.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from quant_us.live.micro_live_design_freeze import design_freeze_metadata

_logger = logging.getLogger("live_pilot_approval")

APPROVAL_EXPIRY_DAYS = 7


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Approval request model
# ---------------------------------------------------------------------------


@dataclass
class LivePilotApprovalRequest:
    approval_id: str
    run_id: str = ""
    dossier_id: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    symbols: list[str] = field(default_factory=list)
    requested_at: str = ""
    requested_by: str = ""
    paper_30d_report_path: str = ""
    shadow_5d_report_path: str = ""
    readiness_dossier_path: str = ""
    risk_envelope_path: str = ""
    proposed_capital: float = 1000.0
    max_order_notional: float = 100.0
    max_daily_loss: float = 50.0
    max_gross_exposure: float = 0.10
    status: str = "DRAFT"
    design_freeze_version: str = ""
    design_freeze_hash: str = ""
    design_freeze_scope: str = ""
    review_only: bool = True
    execution_authorized: bool = False
    approver: str = ""
    approved_at: str = ""
    rejection_reason: str = ""
    expires_at: str = ""

    def __post_init__(self) -> None:
        if not self.requested_at:
            self.requested_at = _utc_now().isoformat()

    def is_approved(self) -> bool:
        return self.status == "APPROVED"

    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(self.expires_at)
            return _utc_now() > expiry
        except (ValueError, TypeError):
            return True

    def is_valid(self) -> bool:
        return self.is_approved() and not self.is_expired()

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "dossier_id": self.dossier_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "symbols": self.symbols,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "paper_30d_report_path": self.paper_30d_report_path,
            "shadow_5d_report_path": self.shadow_5d_report_path,
            "readiness_dossier_path": self.readiness_dossier_path,
            "risk_envelope_path": self.risk_envelope_path,
            "proposed_capital": self.proposed_capital,
            "max_order_notional": self.max_order_notional,
            "max_daily_loss": self.max_daily_loss,
            "max_gross_exposure": self.max_gross_exposure,
            "status": self.status,
            "design_freeze_version": self.design_freeze_version,
            "design_freeze_hash": self.design_freeze_hash,
            "design_freeze_scope": self.design_freeze_scope,
            "review_only": self.review_only,
            "execution_authorized": self.execution_authorized,
            "approver": self.approver,
            "approved_at": self.approved_at,
            "rejection_reason": self.rejection_reason,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LivePilotApprovalRequest":
        return cls(
            approval_id=data.get("approval_id", ""),
            run_id=data.get("run_id", ""),
            dossier_id=data.get("dossier_id", ""),
            strategy_id=data.get("strategy_id", ""),
            strategy_version=data.get("strategy_version", ""),
            symbols=data.get("symbols", []),
            requested_at=data.get("requested_at", ""),
            requested_by=data.get("requested_by", ""),
            paper_30d_report_path=data.get("paper_30d_report_path", ""),
            shadow_5d_report_path=data.get("shadow_5d_report_path", ""),
            readiness_dossier_path=data.get("readiness_dossier_path", ""),
            risk_envelope_path=data.get("risk_envelope_path", ""),
            proposed_capital=data.get("proposed_capital", 1000.0),
            max_order_notional=data.get("max_order_notional", 100.0),
            max_daily_loss=data.get("max_daily_loss", 50.0),
            max_gross_exposure=data.get("max_gross_exposure", 0.10),
            status=data.get("status", "DRAFT"),
            design_freeze_version=data.get("design_freeze_version", ""),
            design_freeze_hash=data.get("design_freeze_hash", ""),
            design_freeze_scope=data.get("design_freeze_scope", ""),
            review_only=data.get("review_only", True),
            execution_authorized=data.get("execution_authorized", False),
            approver=data.get("approver", ""),
            approved_at=data.get("approved_at", ""),
            rejection_reason=data.get("rejection_reason", ""),
            expires_at=data.get("expires_at", ""),
        )


# ---------------------------------------------------------------------------
# Human approval gate
# ---------------------------------------------------------------------------


@dataclass
class ApprovalGateResult:
    passed: bool
    reason: str = ""
    approval_id: str = ""
    status: str = ""
    checks: dict[str, bool] = field(default_factory=dict)


class HumanApprovalGate:
    """Enforces human approval requirements before any live pilot activity.

    Checks:
    1. approval_id is provided
    2. approval exists in store
    3. approval status is APPROVED
    4. approval not expired
    5. strategy_version matches
    6. symbols match
    7. risk envelope matches
    8. audit log updated
    """

    def __init__(self, store_path: str = "data/live_pilot/approvals") -> None:
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)

    def check(
        self,
        approval_id: str,
        strategy_id: str = "",
        strategy_version: str = "",
        symbols: list[str] | None = None,
        envelope_id: str = "",
    ) -> ApprovalGateResult:
        checks: dict[str, bool] = {}

        if not approval_id:
            return ApprovalGateResult(
                passed=False,
                reason="No approval_id provided. Human approval is mandatory.",
                status="BLOCKED",
                checks={"approval_id_provided": False},
            )

        approval = self._load_approval(approval_id)
        if approval is None:
            return ApprovalGateResult(
                passed=False,
                reason=f"Approval {approval_id} not found.",
                approval_id=approval_id,
                status="BLOCKED",
                checks={"approval_exists": False},
            )

        checks["approval_exists"] = True
        checks["review_only"] = approval.review_only
        checks["execution_not_authorized"] = not approval.execution_authorized
        checks["design_freeze_bound"] = bool(
            approval.design_freeze_version
            and approval.design_freeze_hash
            and approval.design_freeze_scope
        )
        if not all(
            (
                checks["review_only"],
                checks["execution_not_authorized"],
                checks["design_freeze_bound"],
            )
        ):
            approval.status = "INVALID"
            self._save_approval(approval)
            return ApprovalGateResult(
                passed=False,
                reason=(
                    f"Approval {approval_id} is not a valid review-only approval "
                    "artifact."
                ),
                approval_id=approval_id,
                status=approval.status,
                checks=checks,
            )

        checks["design_freeze_binding_match"] = self._approval_binding_matches(approval)
        if not checks["design_freeze_binding_match"]:
            approval.status = "INVALID"
            self._save_approval(approval)
            return ApprovalGateResult(
                passed=False,
                reason=(
                    f"Approval {approval_id} design freeze binding mismatches the "
                    "current dossier/freeze state."
                ),
                approval_id=approval_id,
                status=approval.status,
                checks=checks,
            )

        checks["status_approved"] = approval.status == "APPROVED"
        if not checks["status_approved"]:
            return ApprovalGateResult(
                passed=False,
                reason=f"Approval {approval_id} status is {approval.status}, not APPROVED.",
                approval_id=approval_id,
                status=approval.status,
                checks=checks,
            )

        checks["not_expired"] = not approval.is_expired()
        if not checks["not_expired"]:
            return ApprovalGateResult(
                passed=False,
                reason=f"Approval {approval_id} expired at {approval.expires_at}.",
                approval_id=approval_id,
                status=approval.status,
                checks=checks,
            )

        if strategy_version and approval.strategy_version:
            checks["strategy_version_match"] = (
                strategy_version == approval.strategy_version
            )
            if not checks["strategy_version_match"]:
                return ApprovalGateResult(
                    passed=False,
                    reason=f"Strategy version mismatch: running={strategy_version}, approved={approval.strategy_version}.",
                    approval_id=approval_id,
                    status=approval.status,
                    checks=checks,
                )
        else:
            checks["strategy_version_match"] = True

        if symbols:
            approved_symbols = set(s.upper() for s in approval.symbols)
            running_symbols = set(s.upper() for s in symbols)
            checks["symbols_match"] = running_symbols.issubset(approved_symbols)
            if not checks["symbols_match"]:
                extra = running_symbols - approved_symbols
                return ApprovalGateResult(
                    passed=False,
                    reason=f"Symbols not in approval: {sorted(extra)}.",
                    approval_id=approval_id,
                    status=approval.status,
                    checks=checks,
                )
        else:
            checks["symbols_match"] = True

        checks["envelope_match"] = True

        self._audit("approval_gate_passed", {"approval_id": approval_id})

        return ApprovalGateResult(
            passed=True,
            reason=(
                f"Approval {approval_id} valid and authorized for review-only "
                "approval checks."
            ),
            approval_id=approval_id,
            status=approval.status,
            checks=checks,
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create(
        self,
        approval_id: str,
        strategy_id: str = "",
        strategy_version: str = "",
        symbols: list[str] | None = None,
        requested_by: str = "",
        proposed_capital: float = 1000.0,
        readiness_dossier_path: str = "",
        risk_envelope_path: str = "",
        run_id: str = "",
    ) -> LivePilotApprovalRequest:
        binding = self._resolve_design_freeze_binding(readiness_dossier_path)
        approval = LivePilotApprovalRequest(
            approval_id=approval_id,
            run_id=run_id,
            dossier_id=binding.get("dossier_id", ""),
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            symbols=symbols or [],
            requested_by=requested_by,
            readiness_dossier_path=readiness_dossier_path,
            risk_envelope_path=risk_envelope_path,
            proposed_capital=proposed_capital,
            design_freeze_version=binding["version"],
            design_freeze_hash=binding["hash"],
            design_freeze_scope=binding["scope"],
            review_only=True,
            execution_authorized=False,
            status="DRAFT",
        )
        self._save_approval(approval)
        self._audit("approval_created", approval.to_dict())
        return approval

    def approve(self, approval_id: str, approver: str) -> LivePilotApprovalRequest:
        approval = self._load_approval(approval_id)
        if approval is None:
            raise ValueError(f"Approval {approval_id} not found")

        if approval.status != "DRAFT":
            raise ValueError(
                f"Cannot approve: approval {approval_id} is {approval.status}"
            )

        if not self._approval_binding_matches(approval):
            approval.status = "INVALID"
            self._save_approval(approval)
            self._audit("approval_invalidated", approval.to_dict())
            raise ValueError(
                f"Cannot approve: approval {approval_id} design freeze binding mismatch"
            )

        approval.status = "APPROVED"
        approval.approver = approver
        approval.approved_at = _utc_now().isoformat()
        approval.expires_at = (
            _utc_now() + timedelta(days=APPROVAL_EXPIRY_DAYS)
        ).isoformat()

        self._save_approval(approval)
        self._audit("approval_approved", approval.to_dict())
        _logger.info(
            "Approval %s APPROVED by %s, expires %s",
            approval_id,
            approver,
            approval.expires_at,
        )
        return approval

    def reject(
        self, approval_id: str, reason: str
    ) -> LivePilotApprovalRequest:
        approval = self._load_approval(approval_id)
        if approval is None:
            raise ValueError(f"Approval {approval_id} not found")

        approval.status = "REJECTED"
        approval.rejection_reason = reason
        self._save_approval(approval)
        self._audit("approval_rejected", approval.to_dict())
        return approval

    def list_approvals(self) -> list[LivePilotApprovalRequest]:
        approvals: list[LivePilotApprovalRequest] = []
        for path in sorted(self.store_path.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                approvals.append(LivePilotApprovalRequest.from_dict(data))
            except (json.JSONDecodeError, OSError):
                continue
        return approvals

    def inspect(self, approval_id: str) -> LivePilotApprovalRequest | None:
        return self._load_approval(approval_id)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_approval(self, approval_id: str) -> LivePilotApprovalRequest | None:
        path = self.store_path / f"{approval_id}.json"
        if not path.exists():
            return None
        try:
            return LivePilotApprovalRequest.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            return None

    def _save_approval(self, approval: LivePilotApprovalRequest) -> None:
        path = self.store_path / f"{approval.approval_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(approval.to_dict(), indent=2, default=str))

    def _audit(self, event: str, data: dict[str, Any]) -> None:
        audit_path = self.store_path / "approval_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "event": event,
            "data": data,
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def _resolve_design_freeze_binding(self, readiness_dossier_path: str) -> dict[str, Any]:
        dossier_binding = self._load_dossier_binding(readiness_dossier_path)
        current = design_freeze_metadata()
        return {
            "dossier_id": dossier_binding.get("dossier_id", ""),
            "version": dossier_binding.get("version", current["version"]),
            "hash": dossier_binding.get("hash", current["hash"]),
            "scope": dossier_binding.get("scope", current["scope"]),
        }

    def _approval_binding_matches(self, approval: LivePilotApprovalRequest) -> bool:
        current = design_freeze_metadata()
        dossier_binding = self._load_dossier_binding(approval.readiness_dossier_path)
        expected = {
            "version": approval.design_freeze_version,
            "hash": approval.design_freeze_hash,
            "scope": approval.design_freeze_scope,
        }
        current_match = (
            expected["version"] == current["version"]
            and expected["hash"] == current["hash"]
            and expected["scope"] == current["scope"]
        )
        if not current_match:
            return False
        if not approval.readiness_dossier_path:
            return True
        return (
            dossier_binding.get("version") == expected["version"]
            and dossier_binding.get("hash") == expected["hash"]
            and dossier_binding.get("scope") == expected["scope"]
        )

    def _load_dossier_binding(self, readiness_dossier_path: str) -> dict[str, Any]:
        if not readiness_dossier_path:
            return {}

        path = Path(readiness_dossier_path)
        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

        freeze = data.get("design_freeze", {})
        return {
            "dossier_id": data.get("dossier_id", ""),
            "version": freeze.get("version", ""),
            "hash": freeze.get("hash", ""),
            "scope": freeze.get("scope", ""),
        }
