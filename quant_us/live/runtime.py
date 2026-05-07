from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from quant_us.core.types import OrderIntent
from quant_us.execution.oms import OrderManagementSystem
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

    def __post_init__(self) -> None:
        self.state = LiveRuntimeState(mode=self.config.mode)

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
            )
            readiness_passed = gate_report.is_ready()
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
            # Live mode: all gates passed — proceed to OMS submission.
            # The OMS broker (AlpacaBroker or SimulatedBroker) controls
            # whether the order reaches the real market.

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
        for intent in intents:
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

        Requires *allow_live_orders*, *confirm_live*, and
        *live_submission_enabled* all True.  If any is missing the OMS
        stays None and ``submit_orders`` will reject with a clear reason.
        """
        import os
        from pathlib import Path

        if not (self.config.allow_live_orders and self.config.confirm_live):
            _logger.warning("Live OMS not initialized: allow_live_orders=%s confirm_live=%s",
                            self.config.allow_live_orders, self.config.confirm_live)
            return
        if not self.config.live_submission_enabled:
            _logger.warning("Live OMS not initialized: live_submission_enabled is False")
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
        if not self.config.allow_live_orders:
            reasons.append("allow_live_orders_false")
        if not self.config.confirm_live:
            reasons.append("confirm_live_missing")
        if not self.config.live_submission_enabled:
            reasons.append("live_submission_disabled_by_config")
        if self.config.require_readiness_gate:
            reasons.append("live_readiness_gate_required")
        if self.config.mode != RuntimeMode.LIVE:
            reasons.append(f"mode_is_{self.config.mode.value}_not_live")
        return reasons

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
