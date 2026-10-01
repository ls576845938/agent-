from __future__ import annotations

from dataclasses import dataclass, field

from quant_us.live.modes import RuntimeMode


@dataclass(frozen=True)
class LiveRuntimeConfig:
    """Unified config boundary for paper, shadow-live, and guarded live.

    Defaults are deliberately safe:
    - mode is paper.
    - real live orders are disabled.
    - live confirmation is absent.
    """

    mode: RuntimeMode = RuntimeMode.PAPER
    symbols: list[str] = field(default_factory=list)
    strategy_id: str = ""
    data_root: str = "data"
    ledger_root: str = "data/paper_ledger"
    state_path: str = "data/runtime_state.json"
    validation_state_path: str = ""
    broker: str = "simulated"
    data_vendor: str = "yfinance"
    bar_size: str = "1m"
    poll_interval_seconds: float = 60.0
    max_runtime_hours: float = 8.0
    submit_orders: bool = False
    allow_live_orders: bool = False
    confirm_live: bool = False
    live_submission_enabled: bool = False
    require_readiness_gate: bool = True
    require_reconciliation_clean: bool = True

    def __post_init__(self) -> None:
        if self.mode == RuntimeMode.SHADOW_LIVE and self.allow_live_orders:
            raise ValueError("shadow_live cannot allow live orders")
        if self.mode == RuntimeMode.SHADOW_LIVE and self.submit_orders:
            # submit_orders means paper order submission in shadow mode, not real orders.
            object.__setattr__(self, "submit_orders", True)
        if self.mode == RuntimeMode.PAPER and self.allow_live_orders:
            raise ValueError("paper mode cannot allow live orders")

    @property
    def real_order_submission_enabled(self) -> bool:
        # VNEXT live execution remains frozen. These flags are retained as
        # review evidence only and must not become a submit capability.
        return False

    @property
    def paper_order_submission_enabled(self) -> bool:
        return (
            self.mode in {RuntimeMode.PAPER, RuntimeMode.SHADOW_LIVE}
            and self.submit_orders
            and not self.allow_live_orders
        )

    def runtime_audit_fields(
        self,
        *,
        broker_backend: str | None = None,
        adapter_contract: dict[str, object] | None = None,
    ) -> dict[str, object]:
        effective_broker_backend = broker_backend or self.broker
        return {
            "mode": self.mode.value,
            "runtime_mode": self.mode.value,
            "canonical_runtime": "PaperRuntime" if self.mode == RuntimeMode.PAPER else "LiveRuntime",
            "broker_backend": effective_broker_backend,
            "real_order_submission": self.real_order_submission_enabled,
            "paper_order_submission": self.paper_order_submission_enabled,
            "adapter_contract": adapter_contract
            if adapter_contract is not None
            else {
                "requested_backend": effective_broker_backend,
                "effective_backend": effective_broker_backend,
                "adapter_ready": False,
                "fail_closed": True,
                "reason": "adapter_contract_not_applicable_to_live_runtime_shell",
            },
        }

    def live_block_reasons(self, readiness_passed: bool = False) -> list[str]:
        reasons: list[str] = []
        if self.mode != RuntimeMode.LIVE:
            return reasons
        reasons.append("live_runtime_frozen")
        if not self.allow_live_orders:
            reasons.append("allow_live_orders_false")
        if not self.confirm_live:
            reasons.append("confirm_live_missing")
        if not self.live_submission_enabled:
            reasons.append("live_submission_disabled_by_config")
        if self.require_readiness_gate and not readiness_passed:
            reasons.append("live_readiness_gate_not_passed")
        return reasons
