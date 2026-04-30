from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quant_us.core.clock import ensure_utc, utc_now
from quant_us.core.types import Bar


@dataclass(frozen=True)
class DataFreshnessDecision:
    fresh: bool
    delay_seconds: float
    reason: str


@dataclass(frozen=True)
class DataFreshnessConfig:
    max_delay_seconds: float = 300.0


class DataFreshnessGuard:
    def __init__(self, config: DataFreshnessConfig | None = None) -> None:
        self.config = config or DataFreshnessConfig()

    def evaluate_bar(self, bar: Bar, now: datetime | None = None) -> DataFreshnessDecision:
        current = ensure_utc(now or utc_now())
        delay = max(0.0, (current - bar.timestamp_utc).total_seconds())
        if delay > self.config.max_delay_seconds:
            return DataFreshnessDecision(False, delay, "market_data_stale")
        return DataFreshnessDecision(True, delay, "fresh")
