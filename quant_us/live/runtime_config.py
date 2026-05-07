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
        return (
            self.mode == RuntimeMode.LIVE
            and self.allow_live_orders
            and self.confirm_live
            and self.live_submission_enabled
        )

    def live_block_reasons(self, readiness_passed: bool = False) -> list[str]:
        reasons: list[str] = []
        if self.mode != RuntimeMode.LIVE:
            return reasons
        if not self.allow_live_orders:
            reasons.append("allow_live_orders_false")
        if not self.confirm_live:
            reasons.append("confirm_live_missing")
        if not self.live_submission_enabled:
            reasons.append("live_submission_disabled_by_config")
        if self.require_readiness_gate and not readiness_passed:
            reasons.append("live_readiness_gate_not_passed")
        return reasons
