from __future__ import annotations

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


class TimeWindowStrategy(Strategy):
    """Calendar-based time-window seasonality strategy.

    Long early-week (Monday 0-4h UTC).
    Short late-week (Friday 14-20h UTC).
    """

    strategy_id = "time_window"

    def __init__(
        self,
        long_day: int = 0,
        long_hour_start: int = 0,
        long_hour_end: int = 4,
        short_day: int = 4,
        short_hour_start: int = 14,
        short_hour_end: int = 20,
    ) -> None:
        self.long_day = long_day
        self.long_hour_start = long_hour_start
        self.long_hour_end = long_hour_end
        self.short_day = short_day
        self.short_hour_start = short_hour_start
        self.short_hour_end = short_hour_end
        self._prev_direction: float = 0.0

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        timestamp = event.timestamp_utc
        if (
            timestamp.weekday() == self.long_day
            and self.long_hour_start <= timestamp.hour <= self.long_hour_end
        ):
            direction = 1.0
        elif (
            timestamp.weekday() == self.short_day
            and self.short_hour_start <= timestamp.hour <= self.short_hour_end
        ):
            direction = -1.0
        else:
            direction = 0.0
        previous_direction = float(
            context.state.payload.get("previous_direction", 0.0)
        )
        signals: list[Signal] = []
        if direction != previous_direction:
            if direction > 0:
                signals.append(Signal(
                    timestamp_utc=event.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=event.bar.symbol,
                    direction=SignalDirection.LONG,
                    strength=0.2,
                    horizon="1d",
                    reason="time_long",
                ))
            elif direction < 0:
                signals.append(Signal(
                    timestamp_utc=event.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=event.bar.symbol,
                    direction=SignalDirection.SHORT,
                    strength=0.2,
                    horizon="1d",
                    reason="time_short",
                ))
            else:
                signals.append(Signal(
                    timestamp_utc=event.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=event.bar.symbol,
                    direction=SignalDirection.FLAT,
                    strength=0.0,
                    horizon="1d",
                    reason="time_neutral",
                ))
        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {"previous_direction": direction},
                reason="time_window_bar_applied",
            ),
        )

    def on_bar(self, event: MarketEvent, context: StrategyContext) -> list[Signal]:
        ts = event.timestamp_utc
        weekday = ts.weekday()
        hour = ts.hour

        if weekday == self.long_day and self.long_hour_start <= hour <= self.long_hour_end:
            direction = 1.0
        elif weekday == self.short_day and self.short_hour_start <= hour <= self.short_hour_end:
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
                strength=0.2,
                horizon="1d",
                reason="time_long",
            )]
        elif direction < 0:
            return [Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.SHORT,
                strength=0.2,
                horizon="1d",
                reason="time_short",
            )]
        return [Signal(
            timestamp_utc=event.timestamp_utc,
            strategy_id=self.strategy_id,
            symbol=event.bar.symbol,
            direction=SignalDirection.FLAT,
            strength=0.0,
            horizon="1d",
            reason="time_neutral",
        )]
