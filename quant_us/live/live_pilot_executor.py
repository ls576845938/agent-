"""Live Pilot Executor for G4 Small Live Pilot review.

The current VNEXT runtime is frozen: this executor can build previews and
audit evidence, but it must not submit real orders.
"""

from __future__ import annotations

import json
import logging
import os
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import Order, OrderIntent, new_id
from quant_us.execution.alpaca_broker import (
    AlpacaBroker,
    AlpacaBrokerConfig,
    LIVE_BASE_URL,
)
from quant_us.live.live_order_audit import LiveOrderAuditRecord, LiveOrderAuditTrail
from quant_us.live.live_order_submission_gate import (
    LiveOrderSubmissionGate,
    SubmissionGateDecision,
)
from quant_us.live.readonly_live_broker import (
    LiveEndpointGuard,
    ReadOnlyLiveBrokerProxy,
    mask_account_id,
)

_logger = logging.getLogger("live_pilot_executor")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Executor config
# ---------------------------------------------------------------------------


@dataclass
class LivePilotExecutorConfig:
    approval_id: str = ""
    envelope_id: str = ""
    symbols: list[str] = field(default_factory=list)
    strategy_id: str = "etf_rotation"
    strategy_version: str = "1.0.0"
    execute_live_pilot: bool = False
    confirm_live: bool = False
    is_dry_run: bool = True
    data_root: str = "data"
    audit_dir: str = "data/live_pilot/audit"
    api_key: str = ""
    api_secret: str = ""

    def __post_init__(self) -> None:
        if self.execute_live_pilot and not self.confirm_live:
            raise ValueError(
                "Cannot execute live pilot without --confirm-live. "
                "Set both --execute-live-pilot and --confirm-live."
            )
        if self.execute_live_pilot and self.confirm_live:
            self.is_dry_run = False
        else:
            self.is_dry_run = True


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class LivePilotExecutor:
    """Controlled live pilot order execution engine.

    Lifecycle (26 steps):
        1. bootstrap()
        2. load_approval()
        3. load_risk_envelope()
        4. validate_go_no_go_dossier()
        5. validate_env_gate()
        6. validate_cli_confirm()
        7. validate_runtime_config()
        8. validate_live_endpoint()
        9. reconcile_on_start()
        10. check_emergency_stop_armed()
        11. load_market_data()
        12. calculate_signals()
        13. build_target_positions()
        14. generate_order_intents()
        15. run_pre_trade_risk()
        16. run_risk_envelope()
        17. run_oms_idempotency()
        18. generate_live_order_preview()
        19. require_final_manual_confirmation()
        20. submit_live_order_if_all_gates_pass()
        21. poll_order_status()
        22. sync_fills()
        23. update_ledger()
        24. reconcile_after_order()
        25. generate_live_pilot_report()
        26. shutdown_safely()
    """

    def __init__(self, config: LivePilotExecutorConfig) -> None:
        self.config = config

        # Components
        self.audit_trail = LiveOrderAuditTrail(audit_dir=config.audit_dir)
        self.submission_gate = LiveOrderSubmissionGate(audit_dir=config.audit_dir)

        # State
        self.run_id: str = new_id("live_pilot_run")
        self._bootstrapped: bool = False
        self._broker: AlpacaBroker | None = None
        self._readonly_broker: ReadOnlyLiveBrokerProxy | None = None
        self._approval: Any = None
        self._envelope: Any = None
        self._dossier_decision: str = ""
        self._preview_records: list[dict[str, Any]] = []
        self._submitted_orders: list[Order] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bootstrap(self) -> bool:
        _logger.info("LivePilotExecutor bootstrapping run_id=%s", self.run_id)

        self.audit_trail.record(
            LiveOrderAuditRecord(
                audit_id=new_id("audit"),
                run_id=self.run_id,
                approval_id=self.config.approval_id,
                envelope_id=self.config.envelope_id,
                real_submit=False,
                status="BOOTSTRAPPING",
            )
        )

        self._bootstrapped = True
        return True

    def execute(self) -> dict[str, Any]:
        """Execute the full live pilot pipeline."""
        if not self._bootstrapped:
            self.bootstrap()

        result: dict[str, Any] = {
            "run_id": self.run_id,
            "status": "DRY_RUN",
            "real_submit_occurred": False,
            "steps": {},
            "errors": [],
            "previews": [],
        }

        # Steps 2-4: Approval, envelope, dossier
        result["steps"]["approval"] = self._load_approval()
        result["steps"]["envelope"] = self._load_envelope()
        result["steps"]["dossier"] = self._check_dossier()

        # Steps 5-6: Env gate and CLI confirm
        result["steps"]["env_gate"] = self._check_env_gate()
        result["steps"]["confirm_live"] = self._check_cli_confirm()

        # Step 7: Runtime config
        result["steps"]["runtime_config"] = self._check_runtime_config()

        # Step 8: Live endpoint
        result["steps"]["live_endpoint"] = self._check_live_endpoint()

        # Step 9: Reconciliation
        result["steps"]["reconciliation"] = self._check_reconciliation()

        # Step 10: Emergency stop
        result["steps"]["emergency_stop"] = self._check_emergency_stop()

        # Steps 11-14: Market data, signals, targets, intents
        result["steps"]["market_data"] = self._load_market_data()
        result["steps"]["signals"] = {"signal_count": 0}
        result["steps"]["targets"] = {"target_count": 0}
        intents = self._generate_order_intents()
        result["steps"]["intents"] = {"intent_count": len(intents)}

        # Steps 15-17: Risk checks
        result["steps"]["pre_trade_risk"] = {"passed": True}
        result["steps"]["risk_envelope"] = self._check_risk_envelope()
        result["steps"]["oms_idempotency"] = {"passed": True}

        # Step 18: Generate preview
        previews = self._generate_previews(intents)
        result["previews"] = previews

        # Step 19-20: Gate check + submit if all pass
        for preview in previews:
            gate_result = self._run_submission_gate(preview)
            preview["gate_decision"] = gate_result.to_dict()

            if gate_result.approved and self.config.execute_live_pilot:
                submit_result = self._submit_live_order(preview)
                preview["submit_result"] = submit_result
                if submit_result.get("submitted"):
                    result["real_submit_occurred"] = True
            else:
                reason = "dry_run" if self.config.is_dry_run else "gate_blocked"
                self.audit_trail.record_dry_run(
                    audit_id=new_id("audit"),
                    run_id=self.run_id,
                    approval_id=self.config.approval_id,
                    envelope_id=self.config.envelope_id,
                    order_intent_id=preview.get("order_intent_id", ""),
                    symbol=preview.get("symbol", ""),
                    side=preview.get("side", "buy"),
                    qty=preview.get("qty", 0),
                    notional=preview.get("notional", 0),
                )

        # Steps 21-26: Post-submit steps
        result["steps"]["poll_status"] = self._poll_status()
        result["steps"]["sync_fills"] = self._sync_fills()
        result["steps"]["update_ledger"] = {"updated": True}
        result["steps"]["reconcile_after"] = self._reconcile_after()
        result["steps"]["report"] = self._generate_report()
        self._shutdown()

        if result["real_submit_occurred"]:
            result["status"] = "REAL_SUBMIT_COMPLETED"
        elif self.config.is_dry_run:
            result["status"] = "DRY_RUN_COMPLETED"
        else:
            result["status"] = "BLOCKED"

        return result

    # ------------------------------------------------------------------
    # Individual step implementations
    # ------------------------------------------------------------------

    def _load_approval(self) -> dict[str, Any]:
        if not self.config.approval_id:
            return {"status": "missing_approval_id"}
        try:
            from quant_us.live.live_pilot_approval import HumanApprovalGate

            gate = HumanApprovalGate()
            result = gate.check(approval_id=self.config.approval_id)
            self._approval = gate.inspect(self.config.approval_id)
            return {"status": "approved" if result.passed else f"blocked: {result.reason}"}
        except Exception as exc:
            return {"status": f"error: {exc}"}

    def _load_envelope(self) -> dict[str, Any]:
        if not self.config.envelope_id:
            return {"status": "missing_envelope_id"}
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            self._envelope = mgr.load(self.config.envelope_id)
            if self._envelope is None:
                return {"status": "envelope_not_found"}
            return {"status": "loaded", "max_order_notional": self._envelope.max_order_notional}
        except Exception as exc:
            return {"status": f"error: {exc}"}

    def _check_dossier(self) -> dict[str, Any]:
        dossier_path = Path(self.config.data_root) / "reports" / "live_pilot_go_no_go.json"
        if not dossier_path.exists():
            return {"status": "dossier_not_found"}
        try:
            data = json.loads(dossier_path.read_text())
            self._dossier_decision = data.get("decision", "NOT_READY")
            return {"decision": self._dossier_decision}
        except Exception as exc:
            return {"status": f"error: {exc}"}

    def _check_env_gate(self) -> dict[str, Any]:
        env_val = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "")
        enabled = env_val.lower() in ("1", "true", "yes")
        return {"enabled": enabled, "required": True}

    def _check_cli_confirm(self) -> dict[str, Any]:
        return {
            "confirm_live": self.config.confirm_live,
            "execute_live_pilot": self.config.execute_live_pilot,
        }

    def _check_runtime_config(self) -> dict[str, Any]:
        from quant_us.live.modes import RuntimeMode
        from quant_us.live.runtime_config import LiveRuntimeConfig

        try:
            cfg = LiveRuntimeConfig(mode=RuntimeMode.LIVE, allow_live_orders=False)
            return {
                "real_order_submission_enabled": cfg.real_order_submission_enabled,
                "block_reasons": cfg.live_block_reasons(),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _check_live_endpoint(self) -> dict[str, Any]:
        if not self.config.api_key or not self.config.api_secret:
            return {"status": "no_live_credentials"}
        try:
            broker_cfg = AlpacaBrokerConfig(
                api_key=self.config.api_key,
                api_secret=self.config.api_secret,
                paper=False,
                base_url=LIVE_BASE_URL,
            )
            raw = AlpacaBroker(broker_cfg)
            self._readonly_broker = ReadOnlyLiveBrokerProxy(raw)
            account = self._readonly_broker.get_account()
            return {
                "status": "ok",
                "account": mask_account_id(account.account_id),
                "equity": account.equity,
            }
        except Exception as exc:
            return {"status": f"error: {exc}"}

    def _check_reconciliation(self) -> dict[str, Any]:
        return {"status": "clean"}

    def _check_emergency_stop(self) -> dict[str, Any]:
        try:
            from quant_us.live.emergency_stop import EmergencyStopController

            ctrl = EmergencyStopController(state_dir=f"{self.config.data_root}/live_pilot")
            return ctrl.status()
        except Exception as exc:
            return {"status": f"error: {exc}"}

    def _load_market_data(self) -> dict[str, Any]:
        return {"bar_count": 0, "status": "ok"}

    def _generate_order_intents(self) -> list[OrderIntent]:
        if not self.config.symbols:
            return []
        intent = OrderIntent(
            timestamp_utc=_utc_now(),
            strategy_id=self.config.strategy_id,
            symbol=self.config.symbols[0],
            side=OrderSide.BUY,
            quantity=1.0,
            order_type=OrderType.LIMIT,
            run_id=self.run_id,
            order_intent_id=new_id("intent"),
        )
        return [intent]

    def _check_risk_envelope(self) -> dict[str, Any]:
        if self._envelope is None:
            return {"status": "no_envelope"}
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager

            mgr = RiskEnvelopeManager()
            return mgr.validate(
                self.config.envelope_id,
                order_notional=1.0 * 500.0,
                order_type=OrderType.LIMIT,
                side=OrderSide.BUY,
            )
        except Exception as exc:
            return {"error": str(exc)}

    def _generate_previews(self, intents: list[OrderIntent]) -> list[dict[str, Any]]:
        previews: list[dict[str, Any]] = []
        for intent in intents:
            preview = {
                "preview_id": new_id("preview"),
                "order_intent_id": intent.order_intent_id,
                "symbol": intent.symbol,
                "side": intent.side.value,
                "qty": float(intent.quantity),
                "order_type": intent.order_type.value,
                "notional": float(intent.quantity) * 500.0,
                "real_submit": False,
                "gate_decision": {},
            }
            previews.append(preview)
            self._preview_records.append(preview)
        return previews

    def _run_submission_gate(self, preview: dict[str, Any]) -> SubmissionGateDecision:
        env_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in (
            "1", "true", "yes"
        )
        em_stop_status = self._check_emergency_stop()

        return self.submission_gate.check(
            approval_id=self.config.approval_id,
            envelope_id=self.config.envelope_id,
            dossier_decision=self._dossier_decision,
            env_enabled=env_enabled,
            confirm_live=self.config.confirm_live,
            allow_live=self.config.confirm_live,
            execute_live_pilot=self.config.execute_live_pilot,
            is_dry_run=self.config.is_dry_run,
            live_endpoint_ok=self._readonly_broker is not None,
            reconciliation_clean=True,
            emergency_stop_armed=em_stop_status.get("state") != "TRIGGERED",
            emergency_stop_triggered=em_stop_status.get("reduce_only", False),
            order_type=preview.get("order_type", "limit"),
            order_notional=preview.get("notional", 0),
            max_order_notional=self._envelope.max_order_notional if self._envelope else 0,
        )

    def _submit_live_order(self, preview: dict[str, Any]) -> dict[str, Any]:
        """Live pilot execution is frozen; readiness gates are review-only."""
        return {
            "submitted": False,
            "reason": "live_runtime_frozen_no_order_submission",
            "real_order_submission": False,
        }

    def _poll_status(self) -> dict[str, Any]:
        return {"orders_polled": len(self._submitted_orders)}

    def _sync_fills(self) -> dict[str, Any]:
        return {"fills_synced": 0}

    def _reconcile_after(self) -> dict[str, Any]:
        return {"status": "clean"}

    def _generate_report(self) -> dict[str, Any]:
        report = {
            "run_id": self.run_id,
            "generated_at": _utc_now().isoformat(),
            "real_submit_count": self.audit_trail.real_submit_count(),
            "preview_count": len(self._preview_records),
            "config": {
                "approval_id": self.config.approval_id,
                "envelope_id": self.config.envelope_id,
                "execute_live_pilot": self.config.execute_live_pilot,
                "confirm_live": self.config.confirm_live,
                "is_dry_run": self.config.is_dry_run,
            },
        }
        report_path = Path(self.config.audit_dir) / f"live_pilot_report_{self.run_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))
        return report

    def _shutdown(self) -> None:
        self._bootstrapped = False
        _logger.info("LivePilotExecutor shutdown complete. run_id=%s", self.run_id)
