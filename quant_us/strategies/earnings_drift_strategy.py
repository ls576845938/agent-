from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.events import MarketEvent
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class EarningsDriftStrategy(Strategy):
    strategy_id: str = "earnings_drift"

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        return []
