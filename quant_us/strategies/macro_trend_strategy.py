from __future__ import annotations

from collections import deque

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


def _sma(values: list[float], window: int) -> float:
    return sum(values[-window:]) / window


class MacroTrendStrategy(Strategy):
    """Multi-MA trend-stack strategy.

    Long when short MA > medium MA > long MA (stacked bullish).
    Short when short MA < medium MA < long MA (stacked bearish).
    """

    strategy_id = "macro_trend"

    def __init__(
        self,
        short_ma: int = 20,
        medium_ma: int = 60,
        long_ma: int = 120,
    ) -> None:
        self.short_ma = short_ma
        self.medium_ma = medium_ma
        self.long_ma = long_ma
        self._closes: deque[float] = deque(maxlen=long_ma)
        self._prev_direction: float = 0.0

    def on_bar(self, event: MarketEvent, context: StrategyContext) -> list[Signal]:
        self._closes.append(event.bar.close)

        if len(self._closes) < self.long_ma:
            return []

        closes = list(self._closes)
        short_val = _sma(closes, self.short_ma)
        medium_val = _sma(closes, self.medium_ma)
        long_val = _sma(closes, self.long_ma)

        if short_val > medium_val > long_val:
            direction = 1.0
        elif short_val < medium_val < long_val:
            direction = -1.0
        else:
            direction = 0.0

        if direction == self._prev_direction:
            return []

        self._prev_direction = direction

        if direction > 0:
            return [Signal.from_event(event, self.strategy_id, SignalDirection.LONG, 0.3, "trend_bullish")]
        elif direction < 0:
            return [Signal.from_event(event, self.strategy_id, SignalDirection.SHORT, 0.3, "trend_bearish")]
        return [Signal.from_event(event, self.strategy_id, SignalDirection.FLAT, 0.0, "trend_neutral")]
