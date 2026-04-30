from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class MomentumStrategy(Strategy):
    strategy_id: str = "trend_momentum"
    lookback_bars: int = 20
    entry_threshold: float = 0.03
    exit_threshold: float = 0.0
    allow_short: bool = False
    _closes: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        closes = self._closes[bar.symbol]
        closes.append(float(bar.close))
        if len(closes) <= self.lookback_bars:
            return []

        previous = closes[-self.lookback_bars - 1]
        momentum = bar.close / previous - 1.0 if previous > 0 else 0.0
        if momentum >= self.entry_threshold:
            strength = min(1.0, momentum / max(self.entry_threshold, 1e-9))
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.LONG,
                    strength=strength,
                    horizon=f"{self.lookback_bars}b",
                    reason="momentum_breakout",
                    metadata={"momentum": momentum},
                )
            ]
        if self.allow_short and momentum <= -self.entry_threshold:
            strength = min(1.0, abs(momentum) / max(self.entry_threshold, 1e-9))
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.SHORT,
                    strength=strength,
                    horizon=f"{self.lookback_bars}b",
                    reason="negative_momentum",
                    metadata={"momentum": momentum},
                )
            ]
        if momentum <= self.exit_threshold:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.FLAT,
                    strength=1.0,
                    horizon=f"{self.lookback_bars}b",
                    reason="momentum_exit",
                    metadata={"momentum": momentum},
                )
            ]
        return []
