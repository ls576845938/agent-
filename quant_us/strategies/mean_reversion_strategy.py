from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean, pstdev

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class MeanReversionStrategy(Strategy):
    strategy_id: str = "short_reversion"
    window: int = 20
    entry_zscore: float = 2.0
    exit_zscore: float = 0.2
    allow_short: bool = False
    _closes: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        closes = self._closes[bar.symbol]
        closes.append(float(bar.close))
        if len(closes) < self.window:
            return []

        sample = closes[-self.window :]
        sigma = pstdev(sample)
        if sigma <= 0:
            return []
        score = (bar.close - mean(sample)) / sigma
        if score <= -self.entry_zscore:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.LONG,
                    strength=min(1.0, abs(score) / self.entry_zscore - 0.5),
                    horizon=f"{self.window}b",
                    reason="oversold_reversion",
                    metadata={"zscore": score},
                )
            ]
        if self.allow_short and score >= self.entry_zscore:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.SHORT,
                    strength=min(1.0, abs(score) / self.entry_zscore - 0.5),
                    horizon=f"{self.window}b",
                    reason="overbought_reversion",
                    metadata={"zscore": score},
                )
            ]
        if abs(score) <= self.exit_zscore:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.FLAT,
                    strength=1.0,
                    horizon=f"{self.window}b",
                    reason="reversion_exit",
                    metadata={"zscore": score},
                )
            ]
        return []
