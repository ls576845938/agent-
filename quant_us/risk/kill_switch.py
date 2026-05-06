from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant_us.risk.risk_event_log import RiskEventLog


@dataclass(frozen=True)
class KillSwitchConfig:
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.12
    max_consecutive_order_failures: int = 3
    max_broker_disconnect_seconds: float = 120.0
    max_data_staleness_seconds: float = 600.0
    max_consecutive_recon_failures: int = 2
    max_slippage_bps: float = 200.0


@dataclass
class KillSwitch:
    config: KillSwitchConfig = field(default_factory=KillSwitchConfig)
    high_water_mark: float = 0.0
    day_start_equity: float = 0.0
    consecutive_order_failures: int = 0
    consecutive_recon_failures: int = 0
    last_broker_success: float = 0.0
    triggered: bool = False
    reason: str = ""
    risk_event_log: RiskEventLog | None = None

    def update_equity(self, equity: float) -> bool:
        if self.day_start_equity <= 0:
            self.day_start_equity = equity
        self.high_water_mark = max(self.high_water_mark, equity)
        if self.day_start_equity > 0 and equity / self.day_start_equity - 1.0 <= -self.config.max_daily_loss_pct:
            return self._trigger("daily_loss_limit")
        if self.high_water_mark > 0 and equity / self.high_water_mark - 1.0 <= -self.config.max_drawdown_pct:
            return self._trigger("drawdown_limit")
        return self.triggered

    def record_broker_success(self) -> None:
        self.last_broker_success = _time.monotonic()
        self.consecutive_order_failures = 0

    def record_broker_failure(self) -> bool:
        self.consecutive_order_failures += 1
        if self.consecutive_order_failures >= self.config.max_consecutive_order_failures:
            return self._trigger("order_failure_limit")
        now = _time.monotonic()
        if self.last_broker_success > 0 and (now - self.last_broker_success) > self.config.max_broker_disconnect_seconds:
            return self._trigger("broker_disconnect_timeout")
        return self.triggered

    def check_data_staleness(self, stale_seconds: float) -> bool:
        if stale_seconds > self.config.max_data_staleness_seconds:
            return self._trigger("data_staleness")
        return self.triggered

    def record_recon_failure(self) -> bool:
        self.consecutive_recon_failures += 1
        if self.consecutive_recon_failures >= self.config.max_consecutive_recon_failures:
            return self._trigger("reconciliation_failure_limit")
        return self.triggered

    def record_recon_success(self) -> None:
        self.consecutive_recon_failures = 0

    def check_slippage(self, slippage_bps: float) -> bool:
        if slippage_bps > self.config.max_slippage_bps:
            return self._trigger("slippage_limit")
        return self.triggered

    def record_order_failure(self) -> bool:
        return self.record_broker_failure()

    def reset_daily(self, equity: float) -> None:
        """Call at the start of each trading day to reset the daily loss window."""
        self.day_start_equity = equity

    def record_order_success(self) -> None:
        self.record_broker_success()

    def _trigger(self, reason: str) -> bool:
        self.triggered = True
        self.reason = reason
        if self.risk_event_log is not None:
            self.risk_event_log.record("kill_switch_triggered", {"reason": reason})
        return True
