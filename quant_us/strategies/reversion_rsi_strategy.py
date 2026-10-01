from __future__ import annotations

from collections import deque

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


class ReversionRsiStrategy(Strategy):
    """RSI + Bollinger bands mean-reversion strategy.

    Long when RSI oversold AND price below lower Bollinger band.
    Short when RSI overbought AND price above upper Bollinger band.
    Exit when RSI returns to neutral zone.
    """

    strategy_id = "reversion_rsi"

    def __init__(
        self,
        rsi_window: int = 14,
        boll_window: int = 20,
        boll_dev: float = 2.0,
        rsi_long: float = 30.0,
        rsi_short: float = 70.0,
        rsi_exit_low: float = 45.0,
        rsi_exit_high: float = 55.0,
    ) -> None:
        self.rsi_window = rsi_window
        self.boll_window = boll_window
        self.boll_dev = boll_dev
        self.rsi_long = rsi_long
        self.rsi_short = rsi_short
        self.rsi_exit_low = rsi_exit_low
        self.rsi_exit_high = rsi_exit_high
        self._closes: deque[float] = deque(maxlen=max(rsi_window + 1, boll_window))
        self._gains: deque[float] = deque(maxlen=rsi_window)
        self._losses: deque[float] = deque(maxlen=rsi_window)
        self._prev_direction: float = 0.0

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        maximum_closes = max(self.rsi_window + 1, self.boll_window)
        closes = [float(value) for value in context.state.payload.get("closes", ())]
        gains = [float(value) for value in context.state.payload.get("gains", ())]
        losses = [float(value) for value in context.state.payload.get("losses", ())]
        previous_direction = float(
            context.state.payload.get("previous_direction", 0.0)
        )
        price = float(event.bar.close)
        closes.append(price)
        closes = closes[-maximum_closes:]
        direction = previous_direction
        signals: list[Signal] = []
        if len(closes) >= maximum_closes:
            delta = price - closes[-2]
            gains.append(delta if delta > 0 else 0.0)
            losses.append(-delta if delta < 0 else 0.0)
            gains = gains[-self.rsi_window :]
            losses = losses[-self.rsi_window :]
            if len(gains) >= self.rsi_window:
                average_gain = sum(gains) / self.rsi_window
                average_loss = sum(losses) / self.rsi_window
                rsi = (
                    100.0 - (100.0 / (1.0 + average_gain / average_loss))
                    if average_loss > 0
                    else 100.0
                )
                recent = closes[-self.boll_window :]
                average = sum(recent) / self.boll_window
                variance = sum((value - average) ** 2 for value in recent) / self.boll_window
                deviation = variance ** 0.5
                upper = average + self.boll_dev * deviation
                lower = average - self.boll_dev * deviation
                if rsi < self.rsi_long and price <= lower:
                    direction = 1.0
                elif rsi > self.rsi_short and price >= upper:
                    direction = -1.0
                elif previous_direction > 0 and rsi >= self.rsi_exit_high:
                    direction = 0.0
                elif previous_direction < 0 and rsi <= self.rsi_exit_low:
                    direction = 0.0
                if direction > 0:
                    signals.append(Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=event.bar.symbol,
                        direction=SignalDirection.LONG,
                        strength=0.5,
                        horizon="1d",
                        reason="reversion_long",
                    ))
                elif direction < 0:
                    signals.append(Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=event.bar.symbol,
                        direction=SignalDirection.SHORT,
                        strength=0.5,
                        horizon="1d",
                        reason="reversion_short",
                    ))
                else:
                    signals.append(Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=event.bar.symbol,
                        direction=SignalDirection.FLAT,
                        strength=0.0,
                        horizon="1d",
                        reason="reversion_exit",
                    ))
        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {
                    "closes": closes,
                    "gains": gains,
                    "losses": losses,
                    "previous_direction": direction,
                },
                reason="reversion_rsi_bar_applied",
            ),
        )

    def on_bar(self, event: MarketEvent, context: StrategyContext) -> list[Signal]:
        price = event.bar.close
        self._closes.append(price)

        if len(self._closes) < max(self.rsi_window + 1, self.boll_window):
            return []

        # Compute RSI
        prev_close = self._closes[-2]
        delta = price - prev_close
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        self._gains.append(gain)
        self._losses.append(loss)
        if len(self._gains) < self.rsi_window:
            return []
        avg_gain = sum(self._gains) / self.rsi_window
        avg_loss = sum(self._losses) / self.rsi_window
        rsi = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss)) if avg_loss > 0 else 100.0

        # Compute Bollinger bands
        closes_list = list(self._closes)
        if len(closes_list) < self.boll_window:
            return []
        recent = closes_list[-self.boll_window:]
        mean = sum(recent) / self.boll_window
        variance = sum((x - mean) ** 2 for x in recent) / self.boll_window
        std = variance ** 0.5
        upper = mean + self.boll_dev * std
        lower = mean - self.boll_dev * std

        direction = 0.0

        if rsi < self.rsi_long and price <= lower:
            direction = 1.0
        elif rsi > self.rsi_short and price >= upper:
            direction = -1.0
        elif self._prev_direction > 0 and rsi >= self.rsi_exit_high:
            direction = 0.0
        elif self._prev_direction < 0 and rsi <= self.rsi_exit_low:
            direction = 0.0
        else:
            direction = self._prev_direction

        self._prev_direction = direction

        if direction > 0:
            return [Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.LONG,
                strength=0.5,
                horizon="1d",
                reason="reversion_long",
            )]
        elif direction < 0:
            return [Signal(
                timestamp_utc=event.timestamp_utc,
                strategy_id=self.strategy_id,
                symbol=event.bar.symbol,
                direction=SignalDirection.SHORT,
                strength=0.5,
                horizon="1d",
                reason="reversion_short",
            )]
        return [Signal(
            timestamp_utc=event.timestamp_utc,
            strategy_id=self.strategy_id,
            symbol=event.bar.symbol,
            direction=SignalDirection.FLAT,
            strength=0.0,
            horizon="1d",
            reason="reversion_exit",
        )]
