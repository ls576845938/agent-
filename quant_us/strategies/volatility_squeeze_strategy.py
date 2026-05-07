from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import sqrt

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class VolatilitySqueezeStrategy(Strategy):
    strategy_id: str = "volatility_squeeze"
    boll_window: int = 20
    boll_dev: float = 2.0
    width_threshold: float = 0.05
    _closes: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _state: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def _bollinger(self, values: list[float]) -> tuple[float, float, float]:
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        std = sqrt(var)
        return mean + self.boll_dev * std, mean, mean - self.boll_dev * std

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        sym = bar.symbol
        closes = self._closes[sym]
        closes.append(float(bar.close))

        if len(closes) < self.boll_window:
            return []

        upper, middle, lower = self._bollinger(closes[-self.boll_window:])
        width = (upper - lower) / middle if middle > 0 else 0.0
        prev_state = self._state[sym]
        squeeze = width < self.width_threshold
        expanded = width > self.width_threshold * 1.8

        if squeeze and bar.close > upper and prev_state <= 0:
            self._state[sym] = 1
            return [Signal(
                timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                symbol=sym, direction=SignalDirection.LONG, strength=0.7, horizon="1d",
            )]
        elif squeeze and bar.close < lower and prev_state >= 0:
            self._state[sym] = -1
            return [Signal(
                timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                symbol=sym, direction=SignalDirection.SHORT, strength=0.7, horizon="1d",
            )]
        elif expanded and prev_state > 0 and bar.close < middle:
            self._state[sym] = 0
        elif expanded and prev_state < 0 and bar.close > middle:
            self._state[sym] = 0
        return []
