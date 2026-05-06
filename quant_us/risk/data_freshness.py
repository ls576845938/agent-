from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.types import Bar


@dataclass(frozen=True)
class DataFreshnessDecision:
    fresh: bool
    delay_seconds: float
    stale_seconds: float
    reason: str


@dataclass(frozen=True)
class DataFreshnessConfig:
    max_delay_seconds: float = 300.0


class DataFreshnessGuard:
    def __init__(self, config: DataFreshnessConfig | None = None) -> None:
        self.config = config or DataFreshnessConfig()
        self.last_fresh_timestamp: datetime | None = None

    @property
    def block_new_orders(self) -> bool:
        """Return True when data has been stale beyond the configured threshold."""
        if self.last_fresh_timestamp is None:
            return True
        delay = (utc_now() - self.last_fresh_timestamp).total_seconds()
        return delay > self.config.max_delay_seconds

    def evaluate_bar(self, bar: Bar, now: datetime | None = None) -> DataFreshnessDecision:
        current = ensure_utc(now or utc_now())
        delay = max(0.0, (current - bar.timestamp_utc).total_seconds())
        if delay > self.config.max_delay_seconds:
            return DataFreshnessDecision(False, delay, delay, "market_data_stale")
        self.last_fresh_timestamp = bar.timestamp_utc
        return DataFreshnessDecision(True, delay, 0.0, "fresh")
