from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class DonchianBreakoutStrategy(Strategy):
    strategy_id: str = "donchian_breakout"
    channel_window: int = 20
    _highs: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lows: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _state: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        sym = bar.symbol
        self._highs[sym].append(float(bar.high))
        self._lows[sym].append(float(bar.low))

        if len(self._highs[sym]) < self.channel_window:
            return []

        upper = max(self._highs[sym][-self.channel_window:])
        lower = min(self._lows[sym][-self.channel_window:])
        middle = (upper + lower) / 2.0
        prev_state = self._state[sym]

        if bar.close > upper and prev_state <= 0:
            self._state[sym] = 1
            return [Signal(
                timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                symbol=sym, direction=SignalDirection.LONG, strength=0.7, horizon="1d",
            )]
        elif bar.close < lower and prev_state >= 0:
            self._state[sym] = -1
            return [Signal(
                timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                symbol=sym, direction=SignalDirection.SHORT, strength=0.7, horizon="1d",
            )]
        elif prev_state > 0 and bar.close < middle:
            self._state[sym] = 0
        elif prev_state < 0 and bar.close > middle:
            self._state[sym] = 0
        return []
