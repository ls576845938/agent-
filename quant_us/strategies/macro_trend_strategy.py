from __future__ import annotations

from collections import deque

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


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

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        closes = [float(value) for value in context.state.payload.get("closes", ())]
        closes.append(float(event.bar.close))
        closes = closes[-self.long_ma :]
        previous_direction = float(context.state.payload.get("previous_direction", 0.0))
        direction = previous_direction
        signals: list[Signal] = []
        if len(closes) >= self.long_ma:
            short_value = _sma(closes, self.short_ma)
            medium_value = _sma(closes, self.medium_ma)
            long_value = _sma(closes, self.long_ma)
            if short_value > medium_value > long_value:
                next_direction = 1.0
            elif short_value < medium_value < long_value:
                next_direction = -1.0
            else:
                next_direction = 0.0
            if next_direction != previous_direction:
                direction = next_direction
                if direction > 0:
                    signals.append(Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=event.bar.symbol,
                        direction=SignalDirection.LONG,
                        strength=0.3,
                        horizon="1d",
                        reason="trend_bullish",
                    ))
                elif direction < 0:
                    signals.append(Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=event.bar.symbol,
                        direction=SignalDirection.SHORT,
                        strength=0.3,
                        horizon="1d",
                        reason="trend_bearish",
                    ))
                else:
                    signals.append(Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=event.bar.symbol,
                        direction=SignalDirection.FLAT,
                        strength=0.0,
                        horizon="1d",
                        reason="trend_neutral",
                    ))
        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {"closes": closes, "previous_direction": direction},
                reason="macro_trend_bar_applied",
            ),
        )

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
            return [Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=0.3,
                horizon="1d",
                reason="trend_bullish",
            )]
        elif direction < 0:
            return [Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.SHORT,
                strength=0.3,
                horizon="1d",
                reason="trend_bearish",
            )]
        return [Signal(
            timestamp_utc=event.timestamp_utc,
            strategy_id=self.strategy_id,
            symbol=event.bar.symbol,
            direction=SignalDirection.FLAT,
            strength=0.0,
            horizon="1d",
            reason="trend_neutral",
        )]
