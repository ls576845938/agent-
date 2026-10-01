from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


@dataclass
class DonchianBreakoutStrategy(Strategy):
    strategy_id: str = "donchian_breakout"
    channel_window: int = 20
    _highs: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _lows: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _state: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        bar = event.bar
        sym = bar.symbol
        highs = {
            str(symbol): [float(value) for value in values]
            for symbol, values in context.state.payload.get("highs", {}).items()
        }
        lows = {
            str(symbol): [float(value) for value in values]
            for symbol, values in context.state.payload.get("lows", {}).items()
        }
        positions = {
            str(symbol): int(value)
            for symbol, value in context.state.payload.get("positions", {}).items()
        }
        symbol_highs = highs.setdefault(sym, [])
        symbol_lows = lows.setdefault(sym, [])
        symbol_highs.append(float(bar.high))
        symbol_lows.append(float(bar.low))
        highs[sym] = symbol_highs[-self.channel_window :]
        lows[sym] = symbol_lows[-self.channel_window :]
        signals: list[Signal] = []
        next_position = positions.get(sym, 0)
        if len(symbol_highs) >= self.channel_window:
            upper = max(symbol_highs[-self.channel_window :])
            lower = min(symbol_lows[-self.channel_window :])
            middle = (upper + lower) / 2.0
            if bar.close > upper and next_position <= 0:
                next_position = 1
                signals.append(Signal(
                    timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                    symbol=sym, direction=SignalDirection.LONG, strength=0.7, horizon="1d",
                ))
            elif bar.close < lower and next_position >= 0:
                next_position = -1
                signals.append(Signal(
                    timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                    symbol=sym, direction=SignalDirection.SHORT, strength=0.7, horizon="1d",
                ))
            elif next_position > 0 and bar.close < middle:
                next_position = 0
            elif next_position < 0 and bar.close > middle:
                next_position = 0
        positions[sym] = next_position
        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {"highs": highs, "lows": lows, "positions": positions},
                reason="donchian_bar_applied",
            ),
        )

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
