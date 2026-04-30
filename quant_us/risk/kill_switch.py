from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KillSwitchConfig:
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.12
    max_consecutive_order_failures: int = 3


@dataclass
class KillSwitch:
    config: KillSwitchConfig = field(default_factory=KillSwitchConfig)
    high_water_mark: float = 0.0
    day_start_equity: float = 0.0
    consecutive_order_failures: int = 0
    triggered: bool = False
    reason: str = ""

    def update_equity(self, equity: float) -> bool:
        if self.day_start_equity <= 0:
            self.day_start_equity = equity
        self.high_water_mark = max(self.high_water_mark, equity)
        if self.day_start_equity > 0 and equity / self.day_start_equity - 1.0 <= -self.config.max_daily_loss_pct:
            return self._trigger("daily_loss_limit")
        if self.high_water_mark > 0 and equity / self.high_water_mark - 1.0 <= -self.config.max_drawdown_pct:
            return self._trigger("drawdown_limit")
        return self.triggered

    def record_order_failure(self) -> bool:
        self.consecutive_order_failures += 1
        if self.consecutive_order_failures >= self.config.max_consecutive_order_failures:
            return self._trigger("order_failure_limit")
        return self.triggered

    def record_order_success(self) -> None:
        self.consecutive_order_failures = 0

    def _trigger(self, reason: str) -> bool:
        self.triggered = True
        self.reason = reason
        return True
