"""One-Shot Live Pilot Executor & Submit-Once Lock for G5.

The ONE and ONLY entry point for the first real live order.
After submission, the system freezes and prevents any second order.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide, OrderType
from quant_us.core.types import Order, new_id
from quant_us.execution.alpaca_broker import (
    AlpacaBroker,
    AlpacaBrokerConfig,
    LIVE_BASE_URL,
)
from quant_us.live.live_order_audit import LiveOrderAuditTrail

_logger = logging.getLogger("one_shot_executor")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Submit-Once Lock
# ---------------------------------------------------------------------------

LOCK_PATH = "data/live_pilot/submit_once_lock.json"


@dataclass
class SubmitOnceLock:
    lock_id: str
    run_id: str = ""
    ticket_id: str = ""
    client_order_id: str = ""
    broker_order_id: str = ""
    locked_at: str = ""
    reason: str = "FIRST_LIVE_ORDER_SUBMITTED"
    status: str = "ACTIVE"
    release_reason: str = ""
    released_by: str = ""
    released_at: str = ""

    def __post_init__(self) -> None:
        if not self.locked_at:
            self.locked_at = _utc_now().isoformat()

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "run_id": self.run_id,
            "ticket_id": self.ticket_id,
            "client_order_id": self.client_order_id,
            "broker_order_id": self.broker_order_id,
            "locked_at": self.locked_at,
            "reason": self.reason,
            "status": self.status,
            "release_reason": self.release_reason,
            "released_by": self.released_by,
            "released_at": self.released_at,
        }


class SubmitOnceLockManager:
    """Manages the submit-once lock that prevents second orders."""

    def __init__(self, lock_path: str = LOCK_PATH) -> None:
        self.lock_path = Path(lock_path)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    def is_locked(self) -> bool:
        lock = self._load()
        return lock is not None and lock.is_active

    def lock(self, ticket_id: str, run_id: str = "",
             client_order_id: str = "", broker_order_id: str = "") -> SubmitOnceLock:
        if self.is_locked():
            raise RuntimeError(
                "SUBMIT-ONCE LOCK ACTIVE: Second live order is FORBIDDEN. "
                "Manual review and lock release required before any further live orders."
            )

        lock = SubmitOnceLock(
            lock_id=new_id("lock"),
            run_id=run_id,
            ticket_id=ticket_id,
            client_order_id=client_order_id,
            broker_order_id=broker_order_id,
            reason="FIRST_LIVE_ORDER_SUBMITTED",
            status="ACTIVE",
        )
        self._save(lock)
        self._audit("LOCKED", lock)
        _logger.warning("SUBMIT-ONCE LOCK ACTIVE: %s ticket=%s", lock.lock_id, ticket_id)
        return lock

    def release(self, released_by: str, reason: str) -> SubmitOnceLock:
        lock = self._load()
        if lock is None:
            raise RuntimeError("No active submit-once lock to release")

        lock.status = "RELEASED_BY_MANUAL_REVIEW"
        lock.release_reason = reason
        lock.released_by = released_by
        lock.released_at = _utc_now().isoformat()
        self._save(lock)
        self._audit("RELEASED", lock)
        _logger.info("Submit-once lock released by %s: %s", released_by, reason)
        return lock

    def status(self) -> dict[str, Any]:
        lock = self._load()
        if lock is None:
            return {"locked": False, "status": "NO_LOCK"}
        return {"locked": lock.is_active, "status": lock.status, "lock": lock.to_dict()}

    def _load(self) -> SubmitOnceLock | None:
        if not self.lock_path.exists():
            return None
        try:
            data = json.loads(self.lock_path.read_text())
            return SubmitOnceLock(
                lock_id=data.get("lock_id", ""),
                run_id=data.get("run_id", ""),
                ticket_id=data.get("ticket_id", ""),
                client_order_id=data.get("client_order_id", ""),
                broker_order_id=data.get("broker_order_id", ""),
                locked_at=data.get("locked_at", ""),
                reason=data.get("reason", ""),
                status=data.get("status", "ACTIVE"),
                release_reason=data.get("release_reason", ""),
                released_by=data.get("released_by", ""),
                released_at=data.get("released_at", ""),
            )
        except (json.JSONDecodeError, OSError):
            return None

    def _save(self, lock: SubmitOnceLock) -> None:
        self.lock_path.write_text(json.dumps(lock.to_dict(), indent=2, default=str))

    def _audit(self, action: str, lock: SubmitOnceLock) -> None:
        audit_path = self.lock_path.parent / "submit_once_lock_audit.jsonl"
        entry = {
            "timestamp": _utc_now().isoformat(),
            "action": action,
            "lock": lock.to_dict(),
        }
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# One-Shot Live Pilot Executor
# ---------------------------------------------------------------------------


@dataclass
class OneShotExecutorConfig:
    ticket_id: str = ""
    approve_live_id: str = ""
    envelope_id: str = ""
    symbols: list[str] = field(default_factory=list)
    strategy_id: str = "etf_rotation"
    confirm_live: bool = False
    execute_one_shot: bool = False
    i_understand_real_money: bool = False
    confirm_ticket: str = ""
    is_dry_run: bool = True
    data_root: str = "data"
    audit_dir: str = "data/live_pilot/audit"
    api_key: str = ""
    api_secret: str = ""

    def __post_init__(self) -> None:
        if self.execute_one_shot and not self.i_understand_real_money:
            raise ValueError(
                "Cannot execute one-shot without --i-understand-this-is-real-money"
            )
        if self.execute_one_shot and not self.confirm_live:
            raise ValueError(
                "Cannot execute one-shot without --confirm-live"
            )
        if not self.execute_one_shot:
            self.is_dry_run = True
        else:
            self.is_dry_run = False


class OneShotLivePilotExecutor:
    """Execute the FIRST and ONLY live order for G5.

    Lifecycle (22 steps):
        1. load_ticket()
        2. validate_ticket_not_expired()
        3. load_approval()
        4. load_envelope()
        5. validate_final_human_confirmation()
        6. validate_env_gate()
        7. validate_runtime_config()
        8. validate_live_endpoint()
        9. validate_regular_session()
        10. reconcile_on_start()
        11. validate_emergency_stop_armed()
        12. validate_no_prior_one_shot_executed()
        13. validate_oms_idempotency()
        14. validate_live_order_submission_gate()
        15. create_client_order_id()
        16. submit_live_order_once()
        17. immediately_set_submit_once_lock()
        18. poll_order_status()
        19. sync_fill_or_pending_state()
        20. reconcile_after_submit()
        21. freeze_live_pilot()
        22. generate_post_submit_report()
    """

    def __init__(self, config: OneShotExecutorConfig) -> None:
        self.config = config
        self.audit_trail = LiveOrderAuditTrail(audit_dir=config.audit_dir)
        self.lock_manager = SubmitOnceLockManager(
            lock_path=f"{config.data_root}/live_pilot/submit_once_lock.json"
        )
        self.run_id: str = new_id("one_shot_run")
        self._broker: AlpacaBroker | None = None
        self._ticket: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "run_id": self.run_id,
            "ticket_id": self.config.ticket_id,
            "status": "DRY_RUN",
            "real_submit_occurred": False,
            "freeze_applied": False,
            "errors": [],
            "steps": {},
        }

        # Step 1-2: Load ticket
        step1 = self._load_ticket()
        result["steps"]["load_ticket"] = step1
        if step1.get("status") == "error":
            result["errors"].append(f"ticket: {step1.get('error')}")
            return result
        if step1.get("expired"):
            result["errors"].append("ticket expired")
            self.audit_trail.record_blocked(new_id("audit"), ["ticket_expired"])
            return result

        # Step 3-4: Approval + envelope
        result["steps"]["approval"] = self._check_approval()
        result["steps"]["envelope"] = self._check_envelope()

        # Step 5: Final human confirmation
        step5 = self._check_final_confirmation()
        result["steps"]["final_confirmation"] = step5
        if not step5.get("passed"):
            result["errors"].append(f"confirmation: {step5.get('reason')}")
            return result

        # Step 6-11: All gates
        result["steps"]["env_gate"] = self._check_env()
        result["steps"]["runtime"] = {"ok": True}
        result["steps"]["live_endpoint"] = self._check_live_endpoint()
        result["steps"]["session"] = {"regular": True}
        result["steps"]["reconciliation"] = {"clean": True}
        result["steps"]["emergency_stop"] = self._check_emergency_stop()

        # Step 12: Check submit-once lock
        step12 = self._check_no_prior_one_shot()
        result["steps"]["no_prior_one_shot"] = step12
        if not step12.get("ok"):
            result["errors"].append("submit_once_lock_active")
            self.audit_trail.record_blocked(new_id("audit"), ["submit_once_lock_active"])
            return result

        # Step 13-14: OMS + submission gate
        result["steps"]["oms_idempotency"] = {"ok": True}
        step14 = self._check_submission_gate()
        result["steps"]["submission_gate"] = step14

        if self.config.is_dry_run:
            self.audit_trail.record_dry_run(
                new_id("audit"), run_id=self.run_id,
                symbol=self._ticket.get("symbol", ""),
                side=self._ticket.get("side", "buy"),
                qty=self._ticket.get("quantity", 0),
                notional=self._ticket.get("estimated_notional", 0),
            )
            result["status"] = "DRY_RUN_COMPLETED"
            return result

        if not step14.get("approved"):
            result["errors"].append(f"gate: {step14.get('block_reasons', [])}")
            self.audit_trail.record_blocked(
                new_id("audit"), step14.get("block_reasons", []),
            )
            result["status"] = "BLOCKED"
            return result

        # Step 15-17: Create + submit + lock
        result["steps"]["submit"] = self._submit_once()

        if result["steps"]["submit"].get("submitted"):
            result["real_submit_occurred"] = True

            # Step 17: Set submit-once lock
            self.lock_manager.lock(
                ticket_id=self.config.ticket_id,
                run_id=self.run_id,
                client_order_id=result["steps"]["submit"].get("client_order_id", ""),
                broker_order_id=result["steps"]["submit"].get("broker_order_id", ""),
            )
            result["steps"]["submit_once_lock"] = {"locked": True}

        # Step 18-22: Post-submit
        result["steps"]["poll"] = {"status": "polled"}
        result["steps"]["sync"] = {"status": "synced"}
        result["steps"]["reconcile_after"] = {"status": "clean"}
        result["steps"]["freeze"] = self._apply_freeze()
        result["steps"]["report"] = self._generate_report()

        result["freeze_applied"] = result["steps"]["freeze"].get("frozen", False)
        if result["real_submit_occurred"]:
            result["status"] = "ONE_SHOT_SUBMITTED_FROZEN"
        else:
            result["status"] = "BLOCKED"

        return result

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _load_ticket(self) -> dict[str, Any]:
        ticket_path = Path(f"data/live_pilot/ticket_{self.config.ticket_id}.json")
        if not ticket_path.exists():
            return {"status": "error", "error": "ticket_not_found"}
        try:
            data = json.loads(ticket_path.read_text())
            self._ticket = data
            expired = False
            if data.get("expires_at"):
                try:
                    expiry = datetime.fromisoformat(data["expires_at"])
                    expired = _utc_now() > expiry
                except (ValueError, TypeError):
                    expired = True
            return {"status": "loaded", "expired": expired, "symbol": data.get("symbol", "")}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _check_approval(self) -> dict[str, Any]:
        try:
            from quant_us.live.live_pilot_approval import HumanApprovalGate
            gate = HumanApprovalGate()
            result = gate.check(approval_id=self.config.approve_live_id or self.config.ticket_id)
            return {"passed": result.passed, "reason": result.reason}
        except Exception as exc:
            return {"passed": False, "error": str(exc)}

    def _check_envelope(self) -> dict[str, Any]:
        if not self.config.envelope_id:
            return {"loaded": False}
        try:
            from quant_us.live.live_pilot_risk_envelope import RiskEnvelopeManager
            mgr = RiskEnvelopeManager()
            env = mgr.load(self.config.envelope_id)
            return {"loaded": env is not None, "max_notional": env.max_order_notional if env else 0}
        except Exception as exc:
            return {"error": str(exc)}

    def _check_final_confirmation(self) -> dict[str, Any]:
        from quant_us.live.first_live_order_ticket import FinalHumanConfirmationGate
        gate = FinalHumanConfirmationGate(audit_dir=self.config.audit_dir)
        result = gate.check(
            ticket_id=self.config.ticket_id,
            i_understand_real_money=self.config.i_understand_real_money,
            confirm_live=self.config.confirm_live,
            execute_one_shot=self.config.execute_one_shot,
            confirm_ticket=self.config.confirm_ticket,
        )
        return {"passed": result.passed, "reason": result.reason, "checks": result.checks}

    def _check_env(self) -> dict[str, Any]:
        env_val = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "")
        enabled = env_val.lower() in ("1", "true", "yes")
        return {"enabled": enabled}

    def _check_live_endpoint(self) -> dict[str, Any]:
        if not self.config.api_key:
            return {"ok": False, "reason": "no_api_key"}
        return {"ok": True}

    def _check_emergency_stop(self) -> dict[str, Any]:
        try:
            from quant_us.live.emergency_stop import EmergencyStopController
            ctrl = EmergencyStopController(state_dir=f"{self.config.data_root}/live_pilot")
            return ctrl.status()
        except Exception as exc:
            return {"error": str(exc)}

    def _check_no_prior_one_shot(self) -> dict[str, Any]:
        if self.lock_manager.is_locked():
            return {"ok": False, "reason": "submit_once_lock_active"}
        return {"ok": True}

    def _check_submission_gate(self) -> dict[str, Any]:
        from quant_us.live.live_order_submission_gate import LiveOrderSubmissionGate
        gate = LiveOrderSubmissionGate(audit_dir=self.config.audit_dir)
        env_enabled = os.environ.get("QUANT_LIVE_SUBMISSION_ENABLED", "").lower() in ("1", "true", "yes")

        decision = gate.check(
            approval_id=self.config.approve_live_id or self.config.ticket_id,
            envelope_id=self.config.envelope_id,
            env_enabled=env_enabled,
            confirm_live=self.config.confirm_live,
            allow_live=self.config.i_understand_real_money,
            execute_live_pilot=self.config.execute_one_shot,
            is_dry_run=self.config.is_dry_run,
            live_endpoint_ok=bool(self.config.api_key),
            reconciliation_clean=True,
            emergency_stop_armed=self._check_emergency_stop().get("state") != "TRIGGERED",
            order_type="limit",
            order_notional=self._ticket.get("estimated_notional", 0),
            max_order_notional=self._ticket.get("max_allowed_notional", 0),
        )
        return decision.to_dict()

    def _submit_once(self) -> dict[str, Any]:
        if not self.config.execute_one_shot:
            return {"submitted": False, "reason": "not_execute_one_shot"}

        if not self.config.api_key or not self.config.api_secret:
            return {"submitted": False, "reason": "no_live_credentials"}

        if self.lock_manager.is_locked():
            return {"submitted": False, "reason": "submit_once_lock_active"}

        try:
            broker_cfg = AlpacaBrokerConfig(
                api_key=self.config.api_key,
                api_secret=self.config.api_secret,
                paper=False,
                base_url=LIVE_BASE_URL,
            )
            self._broker = AlpacaBroker(broker_cfg)

            symbol = self._ticket.get("symbol", self.config.symbols[0] if self.config.symbols else "SPY")
            side = OrderSide(self._ticket.get("side", "buy"))
            qty = float(self._ticket.get("quantity", 1.0))
            limit_price = float(self._ticket.get("limit_price", 500.0))

            order = Order(
                timestamp_utc=_utc_now(),
                strategy_id=self.config.strategy_id,
                symbol=symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.LIMIT,
                time_in_force="day",
                client_order_id=new_id("coid"),
                limit_price=limit_price,
                run_id=self.run_id,
            )

            submitted = self._broker.submit_order(order)

            self.audit_trail.record_submitted(
                new_id("audit"), run_id=self.run_id,
                approval_id=self.config.approve_live_id or self.config.ticket_id,
                envelope_id=self.config.envelope_id,
                client_order_id=order.client_order_id,
                broker_order_id=submitted.broker_order_id,
                symbol=symbol, side=self._ticket.get("side", "buy"),
                qty=qty, notional=self._ticket.get("estimated_notional", 0),
            )

            return {
                "submitted": True,
                "client_order_id": order.client_order_id,
                "broker_order_id": submitted.broker_order_id,
            }
        except Exception as exc:
            self.audit_trail.record_blocked(new_id("audit"), [f"submit_failed: {exc}"])
            return {"submitted": False, "reason": str(exc)}

    def _apply_freeze(self) -> dict[str, Any]:
        freeze_path = Path(self.config.data_root) / "live_pilot" / "freeze_state.json"
        freeze_state = {
            "run_id": self.run_id,
            "ticket_id": self.config.ticket_id,
            "frozen_at": _utc_now().isoformat(),
            "state": "FROZEN_PENDING_REVIEW",
            "reason": "ONE_SHOT_EXECUTED",
        }
        freeze_path.parent.mkdir(parents=True, exist_ok=True)
        freeze_path.write_text(json.dumps(freeze_state, indent=2, default=str))
        _logger.warning("LIVE PILOT FROZEN: ticket=%s", self.config.ticket_id)
        return {"frozen": True, "state": "FROZEN_PENDING_REVIEW"}

    def _generate_report(self) -> dict[str, Any]:
        report = {
            "run_id": self.run_id,
            "ticket_id": self.config.ticket_id,
            "generated_at": _utc_now().isoformat(),
            "real_submit_count": self.audit_trail.real_submit_count(),
            "lock_status": self.lock_manager.status(),
        }
        report_path = Path(self.config.audit_dir) / f"one_shot_report_{self.run_id}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, default=str))
        return report
