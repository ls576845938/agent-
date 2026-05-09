from __future__ import annotations

import logging
import os
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
from quant_us.live.runtime_config import LiveRuntimeConfig
from quant_us.live.runtime_events import RuntimeEvent
from quant_us.live.runtime_state import LiveRuntimeState, RuntimeHealth, RuntimeLifecycleState
from quant_us.reports.live_readiness import LiveReadinessGate

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

    def load_config(self) -> LiveRuntimeConfig:
        return self.config

    def check_readiness(self) -> RuntimeHealth:
        checks: dict[str, bool] = {
            "mode_configured": True,
            "no_real_orders_by_default": not self.config.real_order_submission_enabled,
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
        Live mode: default-blocked; requires all 5 conditions.
        """
        results: dict[str, Any] = {
            "submitted": [],
            "rejected": [],
            "mode": self.config.mode.value,
            "audit_events": [],
        }

        if not intents:
            return results

        # --- Safety: live mode gate ---
        if self.config.mode == RuntimeMode.LIVE:
            block_reasons = self._live_order_block_reasons()
            if block_reasons:
                for intent in intents:
                    results["rejected"].append({
                        "intent_id": intent.client_order_id,
                        "reason": f"live_blocked: {', '.join(block_reasons)}",
                    })
                    results["audit_events"].append({
                        "event": "live_order_rejected",
                        "intent_id": intent.client_order_id,
                        "reasons": block_reasons,
                        "timestamp_utc": _utc_now().isoformat(),
                    })
                _logger.warning("Live order rejected: %s", block_reasons)
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
            if self.config.mode == RuntimeMode.LIVE:
                gate_decision = self._evaluate_live_submission_gate(
                    intent=intent,
                    market_price=market_price,
                    reconciliation_clean=reconciliation_clean,
                    kill_switch_active=kill_switch_triggered,
                )
                if not gate_decision.approved:
                    results["rejected"].append({
                        "intent_id": intent.client_order_id,
                        "reason": (
                            "live_submission_gate_blocked: "
                            + ", ".join(gate_decision.block_reasons or ["blocked"])
                        ),
                    })
                    results["audit_events"].append({
                        "event": "live_order_rejected_submission_gate",
                        "intent_id": intent.client_order_id,
                        "reasons": gate_decision.block_reasons,
                        "warnings": gate_decision.warnings,
                        "timestamp_utc": _utc_now().isoformat(),
                    })
                    _logger.warning(
                        "Live order rejected by submission gate: intent=%s reasons=%s",
                        intent.client_order_id,
                        gate_decision.block_reasons,
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
        """Initialize OMS with AlpacaBroker for live mode.

        Requires an explicit approved LiveOrderSubmissionGate decision in
        addition to the runtime live flags. If any prerequisite is missing,
        the OMS stays None and ``submit_orders`` will reject fail-closed.
        """
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

        try:
            from quant_us.execution.alpaca_broker import AlpacaBroker, AlpacaBrokerConfig
            from quant_us.execution.oms import OrderManagementSystem
            from quant_us.risk.pre_trade import PreTradeRiskConfig, PreTradeRiskEngine
            from quant_us.core.calendar import USEquityCalendar

            api_key = os.environ.get("APCA_API_KEY_ID", "")
            api_secret = os.environ.get("APCA_API_SECRET_KEY", "")
            if not api_key or not api_secret:
                _logger.error("Live OMS requires APCA_API_KEY_ID and APCA_API_SECRET_KEY")
                return

            broker_config = AlpacaBrokerConfig(
                api_key=api_key,
                api_secret=api_secret,
                paper=False,
            )
            broker = AlpacaBroker(broker_config)
            calendar = USEquityCalendar.with_holidays()
            risk_engine = PreTradeRiskEngine(PreTradeRiskConfig(), calendar=calendar)

            self.oms = OrderManagementSystem(
                broker=broker,
                risk_engine=risk_engine,
                calendar=calendar,
                idempotency_path=str(
                    Path(self.config.state_path).parent / ".idempotency_live.json"
                ),
            )
            _logger.info("Live OMS initialized with AlpacaBroker (real orders)")
        except Exception:
            _logger.exception("Failed to initialize live OMS")

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
        self._last_live_submission_gate_decision = decision
        self._live_submission_gate_completed = decision.approved
        return decision

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
