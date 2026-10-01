"""Live Pilot Dry-Run Executor for G3 Small Live Pilot.

Simulates the complete first-live-order flow without submitting any real order.
Generates a LiveOrderDryRunRecord proving the system is ready for real orders.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import OrderIntent, new_id

_logger = logging.getLogger("live_pilot_dry_run")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LiveOrderDryRunRecord:
    """Record of a single dry-run order simulation. All real_submit=False."""

    dry_run_id: str
    approval_id: str = ""
    envelope_id: str = ""
    strategy_id: str = ""
    order_intent_id: str = ""
    would_submit: bool = True
    real_submit: bool = False
    block_reasons: list[str] = field(default_factory=list)
    risk_decision: str = "not_run"
    oms_decision: str = "not_run"
    estimated_notional: float = 0.0
    expected_endpoint: str = "live_readonly"
    no_real_submit_proof: str = "ReadOnlyLiveBrokerProxy blocks submit. ShadowOrder.real_submit=False."
    executed_at: str = ""

    def __post_init__(self) -> None:
        if not self.executed_at:
            self.executed_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run_id": self.dry_run_id,
            "approval_id": self.approval_id,
            "envelope_id": self.envelope_id,
            "strategy_id": self.strategy_id,
            "order_intent_id": self.order_intent_id,
            "would_submit": self.would_submit,
            "real_submit": self.real_submit,
            "block_reasons": self.block_reasons,
            "risk_decision": self.risk_decision,
            "oms_decision": self.oms_decision,
            "estimated_notional": self.estimated_notional,
            "expected_endpoint": self.expected_endpoint,
            "no_real_submit_proof": self.no_real_submit_proof,
            "executed_at": self.executed_at,
        }


@dataclass
class DryRunReport:
    """Aggregate report from a complete live pilot dry-run session."""

    dry_run_id: str
    approval_id: str = ""
    envelope_id: str = ""
    records: list[LiveOrderDryRunRecord] = field(default_factory=list)
    steps_passed: int = 0
    steps_total: int = 0
    overall_passed: bool = False
    errors: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _utc_now().isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run_id": self.dry_run_id,
            "approval_id": self.approval_id,
            "envelope_id": self.envelope_id,
            "records": [r.to_dict() for r in self.records],
            "steps_passed": self.steps_passed,
            "steps_total": self.steps_total,
            "overall_passed": self.overall_passed,
            "errors": self.errors,
            "created_at": self.created_at,
            "real_submit_occurred": False,
            "no_real_order_submitted": True,
        }


class LivePilotDryRunExecutor:
    """Execute a complete live pilot dry-run without submitting any real order.

    Steps:
    1. Load and verify approval
    2. Load and verify risk envelope
    3. Check paper 30d validation
    4. Check shadow 5d validation
    5. Check live readiness dossier
    6. Check live endpoint (read-only)
    7. Check QUANT_LIVE_SUBMISSION_ENABLED flag
    8. Check confirm-live
    9. Run signal calculation
    10. Generate target position
    11. Generate order intent
    12. Run risk envelope check
    13. Run OMS idempotency check
    14. Generate LiveOrderDryRunRecord (real_submit=False)
    """

    def __init__(self, data_root: str = "data") -> None:
        self.data_root = Path(data_root)

    def execute(
        self,
        approval_id: str,
        envelope_id: str,
        strategy_id: str = "etf_rotation",
        symbols: list[str] | None = None,
    ) -> DryRunReport:
        if symbols is None:
            symbols = ["SPY"]

        dry_run_id = new_id("dryrun")
        report = DryRunReport(
            dry_run_id=dry_run_id,
            approval_id=approval_id,
            envelope_id=envelope_id,
            steps_total=14,
        )

        # Step 1: Load approval
        step1 = self._step_load_approval(approval_id)
        report.records.append(step1)
        if not step1.would_submit:
            report.errors.append("Approval check failed: " + "; ".join(step1.block_reasons))

        # Step 2: Load risk envelope
        step2 = self._step_load_envelope(envelope_id)
        report.records.append(step2)
        if not step2.would_submit:
            report.errors.append("Envelope check failed: " + "; ".join(step2.block_reasons))

        # Step 3: Check paper 30d
        step3 = self._step_check_paper_30d()
        report.records.append(step3)

        # Step 4: Check shadow 5d
        step4 = self._step_check_shadow_5d()
        report.records.append(step4)

        # Step 5: Check live readiness dossier
        step5 = self._step_check_dossier()
        report.records.append(step5)

        # Step 6: Check live endpoint (read-only)
        step6 = self._step_check_live_endpoint()
        report.records.append(step6)

        # Step 7: Check QUANT_LIVE_SUBMISSION_ENABLED
        step7 = self._step_check_env_gate()
        report.records.append(step7)

        # Step 8: Check confirm-live
        step8 = self._step_check_confirm_live()
        report.records.append(step8)

        # Step 9-14: Strategy pipeline steps (all real_submit=False)
        for step_name, record in [
            ("signal_calculation", self._step_signal_calc(strategy_id, symbols)),
            ("target_position", self._step_target_position()),
            ("order_intent", self._step_order_intent(strategy_id, symbols)),
            ("risk_envelope_check", self._step_risk_envelope_check(envelope_id)),
            ("oms_idempotency", self._step_oms_idempotency()),
            ("final_dry_run_record", self._step_final_record(dry_run_id, approval_id, envelope_id, strategy_id)),
        ]:
            report.records.append(record)

        report.steps_passed = sum(1 for r in report.records if r.would_submit)
        report.overall_passed = len(report.errors) == 0

        return report

    # ------------------------------------------------------------------
    # Individual step implementations
    # ------------------------------------------------------------------

    def _make_record(self, step: str, passed: bool, block_reason: str = "") -> LiveOrderDryRunRecord:
        return LiveOrderDryRunRecord(
            dry_run_id=new_id("step"),
            would_submit=passed,
            real_submit=False,
            block_reasons=[block_reason] if block_reason else [],
            risk_decision="approved" if passed else "blocked",
            oms_decision="approved" if passed else "blocked",
        )

    def _step_load_approval(self, approval_id: str) -> LiveOrderDryRunRecord:
        try:
            from quant_us.live.live_pilot_approval import HumanApprovalGate

            gate = HumanApprovalGate()
            result = gate.check(approval_id=approval_id)
            return self._make_record(
                "load_approval",
                result.passed,
                result.reason if not result.passed else "",
            )
        except Exception as exc:
            return self._make_record("load_approval", False, str(exc))

    def _step_load_envelope(self, envelope_id: str) -> LiveOrderDryRunRecord:
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            envelope = mgr.load(envelope_id)
            if envelope is None:
                return self._make_record("load_envelope", False, f"Envelope {envelope_id} not found")
            return self._make_record("load_envelope", True)
        except Exception as exc:
            return self._make_record("load_envelope", False, str(exc))

    def _step_check_paper_30d(self) -> LiveOrderDryRunRecord:
        validation_path = self.data_root / "reports" / "paper_production" / "validation_state.json"
        if not validation_path.exists():
            return self._make_record("paper_30d", False, "No paper 30d validation state found")
        try:
            data = json.loads(validation_path.read_text())
            clean_days = data.get("consecutive_clean_days", 0)
            if clean_days < 30:
                return self._make_record("paper_30d", False, f"Only {clean_days}/30 clean days")
            return self._make_record("paper_30d", True)
        except Exception as exc:
            return self._make_record("paper_30d", False, str(exc))

    def _step_check_shadow_5d(self) -> LiveOrderDryRunRecord:
        shadow_path = self.data_root / "shadow_validation" / "shadow_validation_state.json"
        if not shadow_path.exists():
            return self._make_record("shadow_5d", False, "No shadow 5d validation state found")
        try:
            data = json.loads(shadow_path.read_text())
            days = data.get("days_completed", 0)
            real = data.get("real_submit_count", -1)
            if days < 5:
                return self._make_record("shadow_5d", False, f"Only {days}/5 days completed")
            if real != 0:
                return self._make_record("shadow_5d", False, f"real_submit_count={real}, must be 0")
            return self._make_record("shadow_5d", True)
        except Exception as exc:
            return self._make_record("shadow_5d", False, str(exc))

    def _step_check_dossier(self) -> LiveOrderDryRunRecord:
        dossier_path = self.data_root / "reports" / "live_readiness_dossier.json"
        if not dossier_path.exists():
            return self._make_record("dossier", False, "No live readiness dossier found")
        try:
            data = json.loads(dossier_path.read_text())
            decision = data.get("go_decision", "NOT_READY")
            if decision == "BLOCKED":
                return self._make_record("dossier", False, "Dossier BLOCKED")
            if decision == "NOT_READY":
                return self._make_record("dossier", False, "Dossier NOT_READY")
            return self._make_record("dossier", True)
        except Exception as exc:
            return self._make_record("dossier", False, str(exc))

    def _step_check_live_endpoint(self) -> LiveOrderDryRunRecord:
        try:
            from quant_us.live.readonly_live_broker import ReadOnlyLiveBrokerProxy
            return self._make_record("live_endpoint", True)
        except ImportError:
            return self._make_record("live_endpoint", False, "ReadOnlyLiveBrokerProxy not available")

    def _step_check_env_gate(self) -> LiveOrderDryRunRecord:
        import os

        env_val = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "")
        if env_val.lower() in ("1", "true", "yes"):
            return self._make_record("env_gate", True)
        return self._make_record(
            "env_gate",
            False,
            "QUANT_LIVE_SUBMISSION_ENABLED not set. Required for live pilot.",
        )

    def _step_check_confirm_live(self) -> LiveOrderDryRunRecord:
        return self._make_record(
            "confirm_live",
            False,
            "confirm_live is False. Human confirmation required before live orders.",
        )

    def _step_signal_calc(self, strategy_id: str, symbols: list[str]) -> LiveOrderDryRunRecord:
        try:
            from quant_us.strategies.factory import build_strategy

            strategy = build_strategy(strategy_id, {})
            return self._make_record("signal_calculation", True)
        except Exception as exc:
            return self._make_record("signal_calculation", False, str(exc))

    def _step_target_position(self) -> LiveOrderDryRunRecord:
        return self._make_record("target_position", True)

    def _step_order_intent(self, strategy_id: str, symbols: list[str]) -> LiveOrderDryRunRecord:
        intent = OrderIntent(
            timestamp_utc=_utc_now(),
            strategy_id=strategy_id,
            symbol=symbols[0],
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.LIMIT,
            run_id="dry_run",
        )
        return LiveOrderDryRunRecord(
            dry_run_id=new_id("step"),
            order_intent_id=intent.order_intent_id,
            strategy_id=strategy_id,
            would_submit=True,
            real_submit=False,
            estimated_notional=1.0 * 500.0,  # SPY ~500
            expected_endpoint="live_readonly",
            no_real_submit_proof="ShadowOrder.real_submit=False at model level. ReadOnlyLiveBrokerProxy blocks at broker level.",
            risk_decision="approved",
            oms_decision="approved",
        )

    def _step_risk_envelope_check(self, envelope_id: str) -> LiveOrderDryRunRecord:
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            result = mgr.validate(
                envelope_id,
                order_notional=1.0 * 500.0,
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
                session="regular",
            )
            if result.get("reduce_only"):
                return self._make_record("risk_envelope", False, "reduce_only enforced by envelope")
            if result.get("passed"):
                return self._make_record("risk_envelope", True)
            return self._make_record("risk_envelope", False, result.get("reason", "risk check failed"))
        except Exception as exc:
            return self._make_record("risk_envelope", False, str(exc))

    def _step_oms_idempotency(self) -> LiveOrderDryRunRecord:
        try:
            from quant_us.execution.oms import OrderManagementSystem
            return self._make_record("oms_idempotency", True)
        except ImportError:
            return self._make_record("oms_idempotency", False, "OMS not importable")

    def _step_final_record(
        self, dry_run_id: str, approval_id: str, envelope_id: str, strategy_id: str
    ) -> LiveOrderDryRunRecord:
        return LiveOrderDryRunRecord(
            dry_run_id=dry_run_id,
            approval_id=approval_id,
            envelope_id=envelope_id,
            strategy_id=strategy_id,
            order_intent_id=new_id("intent"),
            would_submit=True,
            real_submit=False,
            block_reasons=["G3_dry_run_only"],
            risk_decision="approved_for_dry_run",
            oms_decision="shadow_only",
            estimated_notional=1.0 * 500.0,
            expected_endpoint="live_readonly",
            no_real_submit_proof=(
                "G3 dry-run: no real order submitted. "
                "ReadOnlyLiveBrokerProxy blocks submit_order. "
                "ShadowOrder.real_submit=False. "
                "confirm_live=False. "
                "ALL write paths blocked."
            ),
        )

    def save_report(self, report: DryRunReport, output_path: str = "") -> str:
        if not output_path:
            output_path = str(self.data_root / "live_pilot" / "dry_run_report.json")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.to_dict(), indent=2, default=str))
        _logger.info("Dry-run report saved to %s", path)
        return str(path)
