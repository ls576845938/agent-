from __future__ import annotations

import logging
import os
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quant_us.core.enums import OrderSide
from quant_us.core.types import OrderIntent
from quant_us.execution.oms import OrderManagementSystem
from quant_us.live.live_order_submission_gate import (
    LiveOrderSubmissionGate,
    SubmissionGateDecision,
)
from quant_us.live.modes import RuntimeMode
from quant_us.live.alpaca_paper_adapter import ALPACA_PAPER_NETWORK_SUBMIT_ENV
from quant_us.live.paper_adapter_contract import audit_apca_paper_credentials
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.live.runtime_events import RuntimeEvent
from quant_us.live.runtime_state import LiveRuntimeState, RuntimeHealth, RuntimeLifecycleState
from quant_us.reports.live_readiness import LiveReadinessGate
from quant_us.research.evidence_registry import project_saved_paper_review_evidence

_logger = logging.getLogger("live_runtime")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_client_order_id(strategy_id: str, order_intent_id: str) -> str:
    return f"{strategy_id}_{order_intent_id}_{_utc_now().strftime('%Y%m%d%H%M%S%f')}"


@dataclass
class LiveRuntime:
    """Unified lifecycle shell for paper, shadow-live, and guarded live modes.

    Centralizes safety checks and order submission across all three modes.
    Paper orders go through OMS to the configured broker. Shadow mode marks
    orders explicitly and never touches the real broker. Live mode is gated
    by multiple conditions and remains default-blocked.
    """

    config: LiveRuntimeConfig = field(default_factory=LiveRuntimeConfig)
    events: list[RuntimeEvent] = field(default_factory=list)
    oms: OrderManagementSystem | None = None
    _submitted_order_ids: set[str] = field(default_factory=set)
    _last_live_readiness_passed: bool = False
    _live_submission_gate_context: dict[str, Any] = field(default_factory=dict)
    _live_submission_gate_completed: bool = False
    _last_live_submission_gate_decision: SubmissionGateDecision | None = None
    _paper_submission_gate_context: dict[str, Any] = field(default_factory=dict)
    _paper_submission_gate_completed: bool = False
    _last_paper_submission_gate_decision: dict[str, Any] | None = None
    _live_submission_gate: LiveOrderSubmissionGate = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.state = LiveRuntimeState(mode=self.config.mode)
        self._live_submission_gate = LiveOrderSubmissionGate(
            audit_dir=str(Path(self.config.data_root) / "live_pilot" / "audit")
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bootstrap(self) -> RuntimeHealth:
        self.state.transition(RuntimeLifecycleState.BOOTSTRAPPED)
        health = self.check_readiness()
        self.state.health = health
        if health.ok:
            self.state.transition(RuntimeLifecycleState.READY)
            if self.config.mode == RuntimeMode.LIVE:
                self._init_live_oms()
        else:
            self.state.transition(RuntimeLifecycleState.BLOCKED)
        self.events.append(RuntimeEvent("bootstrap", self.config.mode, health.status))
        return health

    def configure_live_submission_gate(self, **gate_context: Any) -> SubmissionGateDecision:
        """Record explicit live gate context and evaluate it fail-closed."""
        self._live_submission_gate_context = dict(gate_context)
        decision = self._evaluate_live_submission_gate(context_override=gate_context)
        self._live_submission_gate_completed = decision.approved
        return decision

    def configure_paper_submission_gate(self, **gate_context: Any) -> dict[str, Any]:
        """Record explicit Alpaca paper submit context and evaluate it fail-closed."""
        self._paper_submission_gate_context = dict(gate_context)
        decision = self._evaluate_paper_submission_gate(context_override=gate_context)
        self._paper_submission_gate_completed = bool(decision["approved"])
        return decision

    def load_config(self) -> LiveRuntimeConfig:
        return self.config

    def check_readiness(self) -> RuntimeHealth:
        checks: dict[str, bool] = {
            "mode_configured": True,
            "no_real_orders_by_default": not self.config.real_order_submission_enabled,
            "paper_order_submission_default_closed": not self.config.paper_order_submission_enabled,
            "live_runtime_is_safety_shell": True,
        }
        errors: list[str] = []

        if self.config.mode == RuntimeMode.PAPER:
            checks["paper_mode"] = True
            checks["allow_live_orders_false"] = not self.config.allow_live_orders
            if self.config.allow_live_orders:
                errors.append("paper_mode_cannot_allow_live_orders")
        elif self.config.mode == RuntimeMode.SHADOW_LIVE:
            checks["shadow_live_no_real_orders"] = not self.config.allow_live_orders
            if self.config.allow_live_orders:
                errors.append("shadow_live_cannot_submit_real_orders")
        elif self.config.mode == RuntimeMode.LIVE:
            gate_report = LiveReadinessGate().check_all(
                validation_state_path=self.config.validation_state_path or None,
                profile="live",
            )
            readiness_passed = gate_report.is_ready(profile="live")
            self._last_live_readiness_passed = readiness_passed
            checks["live_readiness_gate"] = readiness_passed
            for reason in self.config.live_block_reasons(readiness_passed=readiness_passed):
                errors.append(reason)
        else:
            errors.append("unknown_runtime_mode")

        status = "ready" if not errors else "blocked"
        return RuntimeHealth(status=status, checks=checks, errors=errors)

    def reconcile_on_start(self) -> RuntimeHealth:
        return self.state.health

    def start_market_data(self) -> None:
        self.events.append(RuntimeEvent("start_market_data", self.config.mode))

    def run_cycle(self) -> None:
        self.state.cycles += 1
        self.events.append(RuntimeEvent("run_cycle", self.config.mode))

    def readiness_artifact(self) -> dict[str, Any]:
        """Return a structured readiness/audit snapshot without starting execution."""
        health = self.state.health
        artifact = self.config.runtime_audit_fields()
        if self.config.mode == RuntimeMode.LIVE:
            artifact["real_order_submission"] = False
        artifact.update({
            "status": health.status,
            "checks": dict(health.checks),
            "errors": list(health.errors),
            "live_readiness_passed": self._last_live_readiness_passed,
            "production_loop_started": False,
        })
        return artifact

    # ------------------------------------------------------------------
    # Order submission — central safety gate
    # ------------------------------------------------------------------

    def submit_orders(
        self,
        intents: list[OrderIntent],
        account: Any = None,
        market_price: float = 0.0,
        kill_switch_triggered: bool = False,
        reconciliation_clean: bool = True,
        reduce_only: bool = False,
    ) -> dict[str, Any]:
        """Submit order intents through OMS, gated by mode and safety checks.

        Returns a dict with keys: ``submitted`` (list of OMSResult),
        ``rejected`` (list of dict with reason), ``mode``, ``audit_events``.

        Paper mode: full OMS submission to paper/simulated broker.
        Shadow mode: paper submission, explicitly marked, never touches real broker.
        Live mode: safety shell only; order execution is always fail-closed.
        """
        results: dict[str, Any] = {
            "submitted": [],
            "rejected": [],
            "mode": self.config.mode.value,
            "audit_events": [],
        }

        if not intents:
            return results

        # --- Safety: LiveRuntime is a safety shell only ---
        if self.config.mode == RuntimeMode.LIVE:
            reason = "live_runtime_safety_shell_no_order_execution"
            for intent in intents:
                results["rejected"].append({
                    "intent_id": intent.client_order_id,
                    "reason": reason,
                })
                results["audit_events"].append({
                    "event": "live_order_rejected",
                    "intent_id": intent.client_order_id,
                    "reason": reason,
                    "timestamp_utc": _utc_now().isoformat(),
                })
            _logger.warning("Live order rejected: %s", reason)
            return results

        # --- Safety: no OMS configured ---
        if self.oms is None:
            for intent in intents:
                results["rejected"].append({
                    "intent_id": intent.client_order_id,
                    "reason": "oms_not_configured",
                })
            return results

        # --- Safety: kill switch active ---
        if kill_switch_triggered:
            for intent in intents:
                results["rejected"].append({
                    "intent_id": intent.client_order_id,
                    "reason": "kill_switch_active",
                })
                results["audit_events"].append({
                    "event": "order_rejected_kill_switch",
                    "intent_id": intent.client_order_id,
                    "timestamp_utc": _utc_now().isoformat(),
                })
            _logger.warning("Orders rejected: kill switch active")
            return results

        # --- Safety: reconciliation not clean ---
        if self.config.require_reconciliation_clean and not reconciliation_clean:
            for intent in intents:
                results["rejected"].append({
                    "intent_id": intent.client_order_id,
                    "reason": "reconciliation_not_clean",
                })
                results["audit_events"].append({
                    "event": "order_rejected_reconciliation",
                    "intent_id": intent.client_order_id,
                    "timestamp_utc": _utc_now().isoformat(),
                })
            _logger.warning("Orders rejected: reconciliation not clean")
            return results

        # --- Submit through OMS ---
        reduce_only_projection = (
            self._reduce_only_projected_positions(account)
            if reduce_only
            else None
        )
        for intent in intents:
            if self._paper_submit_requires_gate():
                paper_gate_decision = self._evaluate_paper_submission_gate(
                    intent=intent,
                    account=account,
                    reduce_only=reduce_only,
                    context_override={
                        "reconciliation_clean": reconciliation_clean,
                        "kill_switch_active": kill_switch_triggered,
                    },
                )
                if not paper_gate_decision["approved"]:
                    results["rejected"].append({
                        "intent_id": intent.client_order_id,
                        "reason": (
                            "paper_submission_gate_blocked: "
                            + ", ".join(paper_gate_decision["block_reasons"] or ["blocked"])
                        ),
                    })
                    results["audit_events"].append({
                        "event": "paper_order_rejected_submission_gate",
                        "intent_id": intent.client_order_id,
                        "reasons": paper_gate_decision["block_reasons"],
                        "checks": paper_gate_decision["checks"],
                        "timestamp_utc": _utc_now().isoformat(),
                    })
                    _logger.warning(
                        "Alpaca paper order rejected by submission gate: intent=%s reasons=%s",
                        intent.client_order_id,
                        paper_gate_decision["block_reasons"],
                    )
                    continue

            if reduce_only:
                allowed, reason = self._reduce_only_allows(
                    intent,
                    account,
                    projected_positions=reduce_only_projection,
                )
                if not allowed:
                    results["rejected"].append({
                        "intent_id": intent.client_order_id,
                        "reason": reason,
                    })
                    results["audit_events"].append({
                        "event": "order_rejected_reduce_only",
                        "intent_id": intent.client_order_id,
                        "reason": reason,
                        "timestamp_utc": _utc_now().isoformat(),
                    })
                    _logger.warning(
                        "Order rejected by reduce-only gate: intent=%s reason=%s",
                        intent.client_order_id,
                        reason,
                    )
                    continue

            # Idempotency: skip duplicate client_order_ids
            if intent.client_order_id in self._submitted_order_ids:
                results["rejected"].append({
                    "intent_id": intent.client_order_id,
                    "reason": "duplicate_client_order_id",
                })
                results["audit_events"].append({
                    "event": "order_rejected_duplicate",
                    "intent_id": intent.client_order_id,
                    "timestamp_utc": _utc_now().isoformat(),
                })
                continue

            # Shadow mode: enforce paper-only path
            if self.config.mode == RuntimeMode.SHADOW_LIVE:
                results["audit_events"].append({
                    "event": "shadow_order_submitted",
                    "intent_id": intent.client_order_id,
                    "note": "paper broker only, real broker untouched",
                    "timestamp_utc": _utc_now().isoformat(),
                })

            # Submit via OMS
            oms_result = self.oms.handle_intent(
                intent,
                account,
                market_price=market_price,
                timestamp=_utc_now(),
            )

            if oms_result.risk_decision.approved:
                self._submitted_order_ids.add(intent.client_order_id)
                self._apply_reduce_only_projection(intent, reduce_only_projection)
                results["submitted"].append(oms_result)
                results["audit_events"].append({
                    "event": "order_submitted",
                    "strategy_id": intent.strategy_id,
                    "symbol": intent.symbol,
                    "client_order_id": intent.client_order_id,
                    "order_id": oms_result.order.order_id if oms_result.order else "",
                    "timestamp_utc": _utc_now().isoformat(),
                })
            else:
                results["rejected"].append({
                    "intent_id": intent.client_order_id,
                    "reason": oms_result.risk_decision.reason,
                })
                results["audit_events"].append({
                    "event": "order_rejected_risk",
                    "intent_id": intent.client_order_id,
                    "reason": oms_result.risk_decision.reason,
                    "timestamp_utc": _utc_now().isoformat(),
                })

        self.events.append(
            RuntimeEvent(
                "submit_orders",
                self.config.mode,
                f"submitted={len(results['submitted'])} rejected={len(results['rejected'])}",
            )
        )
        return results

    def _init_live_oms(self) -> None:
        """Keep live OMS construction disabled in the runtime safety shell."""
        if not (self.config.allow_live_orders and self.config.confirm_live):
            _logger.warning(
                "Live OMS not initialized: allow_live_orders=%s confirm_live=%s",
                self.config.allow_live_orders,
                self.config.confirm_live,
            )
            return
        if not self.config.live_submission_enabled:
            _logger.warning("Live OMS not initialized: live_submission_enabled is False")
            return
        if not self._live_submission_gate_completed:
            _logger.warning("Live OMS not initialized: explicit live submission gate not completed")
            return

        _logger.warning(
            "Live OMS construction disabled: LiveRuntime is safety shell/live gate only"
        )

    def _live_order_block_reasons(self) -> list[str]:
        """Return reasons why live order submission is blocked."""
        reasons: list[str] = []
        if self.config.mode != RuntimeMode.LIVE:
            reasons.append(f"mode_is_{self.config.mode.value}_not_live")
            return reasons
        if not self.config.allow_live_orders:
            reasons.append("allow_live_orders_false")
        if not self.config.confirm_live:
            reasons.append("confirm_live_missing")
        if not self.config.live_submission_enabled:
            reasons.append("live_submission_disabled_by_config")
        if self.config.require_readiness_gate and not self._last_live_readiness_passed:
            reasons.append("live_readiness_gate_not_passed")
        if not self._has_broker_credentials():
            reasons.append("broker_credentials_missing")
        if not self._live_submission_gate_completed:
            reasons.append("live_submission_gate_not_completed")
        return reasons

    @staticmethod
    def _has_broker_credentials() -> bool:
        return bool(os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY"))

    def _evaluate_live_submission_gate(
        self,
        *,
        intent: OrderIntent | None = None,
        market_price: float = 0.0,
        reconciliation_clean: bool | None = None,
        kill_switch_active: bool = False,
        context_override: dict[str, Any] | None = None,
    ) -> SubmissionGateDecision:
        gate_kwargs = dict(self._live_submission_gate_context)
        if context_override:
            gate_kwargs.update(context_override)

        order_type = gate_kwargs.get("order_type", "")
        if intent is not None:
            raw_order_type = getattr(intent, "order_type", "") or ""
            order_type = str(getattr(raw_order_type, "value", raw_order_type)).lower()

        order_notional = float(gate_kwargs.get("order_notional", 0.0))
        if intent is not None and market_price > 0:
            order_notional = abs(float(intent.quantity) * float(market_price))

        gate_kwargs.update({
            "env_enabled": self.config.live_submission_enabled,
            "confirm_live": self.config.confirm_live,
            "allow_live": self.config.allow_live_orders,
            "execute_live_pilot": self.config.allow_live_orders,
            "is_dry_run": False,
            "order_type": order_type,
            "order_notional": order_notional,
            "oms_idempotency_ok": gate_kwargs.get(
                "oms_idempotency_ok",
                intent is None or intent.client_order_id not in self._submitted_order_ids,
            ),
            "kill_switch_active": kill_switch_active,
        })
        if reconciliation_clean is not None:
            gate_kwargs["reconciliation_clean"] = reconciliation_clean
        if "allowed_order_types" not in gate_kwargs and order_type:
            gate_kwargs["allowed_order_types"] = [order_type]

        decision = self._live_submission_gate.check(**gate_kwargs)
        if decision.approved:
            decision = SubmissionGateDecision(
                decision="REQUIRES_MANUAL_REVIEW",
                block_reasons=list(decision.block_reasons),
                warnings=[
                    *decision.warnings,
                    "live_runtime_frozen_no_automatic_submission",
                ],
                checked_at=decision.checked_at,
                gate_version=decision.gate_version,
            )
        self._last_live_submission_gate_decision = decision
        self._live_submission_gate_completed = decision.approved
        return decision

    def _paper_submit_requires_gate(self) -> bool:
        broker = str(self.config.broker or "").strip().lower()
        return self.config.mode == RuntimeMode.PAPER and broker in {"alpaca", "alpaca_paper"}

    def _evaluate_paper_submission_gate(
        self,
        *,
        intent: OrderIntent | None = None,
        account: Any = None,
        reduce_only: bool = False,
        context_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        gate_kwargs = dict(self._paper_submission_gate_context)
        if context_override:
            gate_kwargs.update(context_override)

        checks: dict[str, Any] = {
            "mode_is_paper": self.config.mode == RuntimeMode.PAPER,
            "broker_is_alpaca_paper": self._paper_submit_requires_gate(),
            "submit_orders_enabled": bool(self.config.submit_orders),
            "allow_live_orders_false": not self.config.allow_live_orders,
            "real_order_submission_disabled": not self.config.real_order_submission_enabled,
            "paper_network_submit_confirmation": self._alpaca_paper_network_submit_confirmed(),
            "explicit_paper_submit_selected": bool(
                gate_kwargs.get("paper_submit_selected")
                or gate_kwargs.get("confirm_paper_submit")
                or gate_kwargs.get("explicit_paper_submit")
            ),
        }
        block_reasons: list[str] = []

        def require(check_name: str, reason: str) -> None:
            if not checks.get(check_name):
                block_reasons.append(reason)

        require("mode_is_paper", "runtime_mode_not_paper")
        require("broker_is_alpaca_paper", "paper_broker_not_alpaca")
        require("submit_orders_enabled", "paper_submit_orders_not_enabled")
        require("allow_live_orders_false", "paper_runtime_cannot_allow_live_orders")
        require("real_order_submission_disabled", "real_order_submission_enabled")
        require(
            "paper_network_submit_confirmation",
            "alpaca_paper_network_submit_confirmation_missing",
        )
        require("explicit_paper_submit_selected", "explicit_paper_submit_not_selected")

        credential_audit = audit_apca_paper_credentials()
        credentials_present = bool(credential_audit.get("credentials_present", False))
        base_url_present = bool(credential_audit.get("base_url", ""))
        base_url_valid = bool(credential_audit.get("base_url_valid", False))
        checks["paper_credentials_present"] = credentials_present
        checks["paper_base_url_present"] = base_url_present
        checks["paper_base_url_valid"] = base_url_valid
        checks["paper_endpoint_kind"] = str(credential_audit.get("endpoint_kind", "unset"))
        checks["paper_allowed_base_urls"] = list(credential_audit.get("allowed_base_urls", []))
        if not credentials_present:
            block_reasons.append("apca_paper_credentials_missing")
        elif not base_url_present:
            block_reasons.append("apca_base_url_missing")
        elif not base_url_valid:
            block_reasons.append("apca_base_url_not_allowed")

        evidence = self._paper_submit_registry_evidence(gate_kwargs)
        checks["saved_registry_evidence_allowed"] = bool(evidence.get("allowed"))
        checks["saved_registry_status"] = evidence.get("registry_status", "")
        checks["saved_registry_integrity_status"] = evidence.get("registry_integrity_status", "")
        checks["paper_review_path"] = evidence.get("review_path", "")
        if not checks["saved_registry_evidence_allowed"]:
            block_reasons.append(str(evidence.get("reason", "paper_review_evidence_missing")))

        startup_sync = self._paper_submit_startup_sync_status(gate_kwargs)
        checks["startup_sync_passed"] = startup_sync["passed"]
        checks["startup_sync_status"] = startup_sync["status"]
        checks["startup_sync_no_submit"] = startup_sync["no_submit"]
        checks["startup_sync_artifact_path"] = startup_sync["artifact_path"]
        if not startup_sync["passed"]:
            block_reasons.append(str(startup_sync["reason"]))

        broker_recovery = self._paper_submit_broker_recovery_status(gate_kwargs)
        checks["broker_recovery_passed"] = broker_recovery["passed"]
        checks["broker_recovery_status"] = broker_recovery["status"]
        checks["broker_recovery_artifact_path"] = broker_recovery["artifact_path"]
        checks["broker_recovery_operationally_complete"] = broker_recovery[
            "operationally_complete"
        ]
        if not broker_recovery["passed"]:
            block_reasons.append(str(broker_recovery["reason"]))

        idempotency_ok = intent is None or intent.client_order_id not in self._submitted_order_ids
        checks["oms_idempotency_ok"] = idempotency_ok
        if not idempotency_ok:
            block_reasons.append("duplicate_client_order_id")

        reduce_only_ok = True
        reduce_only_reason = "ok"
        if reduce_only and intent is not None:
            reduce_only_ok, reduce_only_reason = self._reduce_only_allows(intent, account)
        checks["reduce_only_ok"] = reduce_only_ok
        checks["reduce_only_reason"] = reduce_only_reason
        if not reduce_only_ok:
            block_reasons.append(reduce_only_reason)

        decision = {
            "approved": not block_reasons,
            "block_reasons": block_reasons,
            "checks": checks,
            "evidence": evidence,
            "startup_sync": startup_sync,
            "broker_recovery": broker_recovery,
        }
        self._last_paper_submission_gate_decision = decision
        self._paper_submission_gate_completed = bool(decision["approved"])
        return decision

    @staticmethod
    def _alpaca_paper_network_submit_confirmed() -> bool:
        return os.environ.get(ALPACA_PAPER_NETWORK_SUBMIT_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
        }

    def _paper_submit_registry_evidence(self, gate_kwargs: dict[str, Any]) -> dict[str, Any]:
        data_root = gate_kwargs.get("promotion_data_root") or gate_kwargs.get("data_root") or self.config.data_root
        paper_review_id = str(gate_kwargs.get("paper_review_id", "") or "")
        paper_review_path = str(gate_kwargs.get("paper_review_path", "") or "")
        try:
            return project_saved_paper_review_evidence(
                data_root,
                paper_review_id=paper_review_id,
                paper_review_path=paper_review_path,
            )
        except Exception as exc:
            return {
                "allowed": False,
                "reason": f"paper_review_registry_error:{exc}",
                "registry_status": "error",
                "registry_integrity_status": "error",
                "review": {},
                "review_path": paper_review_path,
                "evidence_pack_path": "",
            }

    def _paper_submit_startup_sync_status(self, gate_kwargs: dict[str, Any]) -> dict[str, Any]:
        artifact_path = Path(
            str(
                gate_kwargs.get("startup_sync_artifact_path")
                or Path(self.config.ledger_root) / "audit" / "paper_broker_adapter_startup_sync.json"
            )
        )
        status = {
            "passed": False,
            "artifact_path": str(artifact_path),
            "status": "missing",
            "reason": "startup_sync_artifact_missing",
            "no_submit": False,
        }
        if not artifact_path.exists():
            return status
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            status.update({
                "status": "conflict",
                "reason": f"startup_sync_artifact_unreadable:{exc}",
            })
            return status

        proof = dict(artifact.get("no_submit_proof", {}))
        no_submit = (
            bool(proof.get("submit_call_count_available", False))
            and not bool(proof.get("submit_order_invoked", True))
            and not bool(proof.get("write_method_invoked", False))
            and proof.get("submit_call_count_delta") == 0
        )
        artifact_status = str(artifact.get("status", "missing"))
        backend = str(artifact.get("backend", artifact.get("broker_backend", "")))
        passed = artifact_status == "ok" and backend == "alpaca_paper" and no_submit
        reason = "ok" if passed else "startup_sync_not_passed"
        status.update({
            "passed": passed,
            "status": artifact_status,
            "backend": backend,
            "reason": reason,
            "no_submit": no_submit,
            "submit_call_count_delta": proof.get("submit_call_count_delta"),
        })
        return status

    def _paper_submit_broker_recovery_status(self, gate_kwargs: dict[str, Any]) -> dict[str, Any]:
        artifact_path = Path(
            str(
                gate_kwargs.get("broker_recovery_artifact_path")
                or gate_kwargs.get("broker_state_recovery_artifact_path")
                or Path(self.config.ledger_root) / "audit" / "paper_broker_state_recovery.json"
            )
        )
        status = {
            "passed": False,
            "artifact_path": str(artifact_path),
            "status": "missing",
            "reason": "broker_state_recovery_missing",
            "operationally_complete": False,
            "broker_state_verified": False,
        }
        if not artifact_path.exists():
            return status
        try:
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            status.update({
                "status": "conflict",
                "reason": f"broker_state_recovery_unreadable:{exc}",
            })
            return status

        artifact_status = str(artifact.get("status", "missing"))
        backend = str(artifact.get("broker_backend", artifact.get("backend", "")))
        operationally_complete = bool(artifact.get("operationally_complete", False))
        broker_state_verified = bool(artifact.get("broker_state_verified", False))
        passed = (
            artifact_status in {"clean_start", "restored", "verified"}
            and backend == "alpaca_paper"
            and operationally_complete
            and broker_state_verified
        )
        status.update({
            "passed": passed,
            "status": artifact_status,
            "backend": backend,
            "reason": "ok" if passed else "broker_state_recovery_not_passed",
            "operationally_complete": operationally_complete,
            "broker_state_verified": broker_state_verified,
        })
        return status

    @staticmethod
    def _reduce_only_projected_positions(account: Any) -> dict[str, float] | None:
        if account is None:
            return None
        positions = getattr(account, "positions", {}) or {}
        return {
            str(symbol): float(getattr(position, "quantity", 0.0))
            for symbol, position in positions.items()
        }

    @staticmethod
    def _intent_quantity_delta(intent: OrderIntent) -> float:
        return intent.quantity if intent.side == OrderSide.BUY else -intent.quantity

    @classmethod
    def _apply_reduce_only_projection(
        cls,
        intent: OrderIntent,
        projected_positions: dict[str, float] | None,
    ) -> None:
        if projected_positions is None:
            return
        projected_qty = projected_positions.get(intent.symbol, 0.0) + cls._intent_quantity_delta(intent)
        if abs(projected_qty) <= 1e-9:
            projected_positions.pop(intent.symbol, None)
        else:
            projected_positions[intent.symbol] = projected_qty

    @classmethod
    def _reduce_only_allows(
        cls,
        intent: OrderIntent,
        account: Any,
        *,
        projected_positions: dict[str, float] | None = None,
    ) -> tuple[bool, str]:
        if account is None and projected_positions is None:
            return False, "reduce_only_account_required"

        if projected_positions is not None:
            current_qty = projected_positions.get(intent.symbol, 0.0)
        else:
            positions = getattr(account, "positions", {}) or {}
            position = positions.get(intent.symbol)
            current_qty = getattr(position, "quantity", 0.0) if position else 0.0
        delta = cls._intent_quantity_delta(intent)
        projected_qty = current_qty + delta

        if abs(current_qty) <= 1e-9:
            return False, "reduce_only_no_existing_position"
        if current_qty > 0 and (projected_qty < -1e-9 or projected_qty > current_qty + 1e-9):
            return False, "reduce_only_would_increase_or_reverse_long"
        if current_qty < 0 and (projected_qty > 1e-9 or projected_qty < current_qty - 1e-9):
            return False, "reduce_only_would_increase_or_reverse_short"
        return True, "ok"

    # ------------------------------------------------------------------
    # Remaining lifecycle methods
    # ------------------------------------------------------------------

    def poll_orders(self) -> None:
        self.events.append(RuntimeEvent("poll_orders", self.config.mode))

    def sync_fills(self) -> None:
        self.events.append(RuntimeEvent("sync_fills", self.config.mode))

    def update_ledger(self) -> None:
        self.events.append(RuntimeEvent("update_ledger", self.config.mode))

    def emit_metrics(self) -> None:
        self.events.append(RuntimeEvent("emit_metrics", self.config.mode))

    def reconcile_on_close(self) -> RuntimeHealth:
        return self.state.health

    def shutdown(self) -> None:
        self.state.transition(RuntimeLifecycleState.STOPPED)
        self.events.append(RuntimeEvent("shutdown", self.config.mode))
