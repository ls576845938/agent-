from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


def _ema(values: list[float], window: int) -> float:
    if len(values) < 2:
        return values[-1] if values else 0.0
    alpha = 2.0 / (window + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = alpha * v + (1 - alpha) * ema_val
    return ema_val


@dataclass
class TrendMacdStrategy(Strategy):
    strategy_id: str = "trend_macd"
    fast_window: int = 20
    slow_window: int = 60
    signal_window: int = 9
    _closes: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _macd_line: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _signal_line: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    _state: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        bar = event.bar
        symbol = bar.symbol
        raw_series = context.state.payload.get("series", {})
        series = {
            str(key): dict(value)
            for key, value in raw_series.items()
        }
        current = dict(series.get(symbol, {}))
        count = int(current.get("count", 0))
        price = float(bar.close)
        if count == 0:
            fast_ema = price
            slow_ema = price
        else:
            fast_alpha = 2.0 / (self.fast_window + 1)
            slow_alpha = 2.0 / (self.slow_window + 1)
            fast_ema = fast_alpha * price + (1.0 - fast_alpha) * float(
                current["fast_ema"]
            )
            slow_ema = slow_alpha * price + (1.0 - slow_alpha) * float(
                current["slow_ema"]
            )
        count += 1
        dif = fast_ema - slow_ema
        threshold = self.slow_window + self.signal_window
        position = int(current.get("position", 0))
        dea = current.get("dea")
        signals: list[Signal] = []
        if count == threshold:
            dea = dif
        elif count > threshold:
            if dea is None:
                raise ValueError("trend_macd state missing dea after initialization")
            signal_alpha = 2.0 / (self.signal_window + 1)
            dea = signal_alpha * dif + (1.0 - signal_alpha) * float(dea)
            if dif > dea and fast_ema > slow_ema and position <= 0:
                position = 1
                signals.append(
                    Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        direction=SignalDirection.LONG,
                        strength=0.8,
                        horizon="1d",
                    )
                )
            elif dif < dea and fast_ema < slow_ema and position >= 0:
                position = -1
                signals.append(
                    Signal(
                        timestamp_utc=event.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=symbol,
                        direction=SignalDirection.SHORT,
                        strength=0.8,
                        horizon="1d",
                    )
                )
        series[symbol] = {
            "count": count,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "dea": dea,
            "position": position,
        }
        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {"series": series},
                reason="trend_macd_bar_applied",
            ),
        )

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        closes = self._closes[bar.symbol]
        closes.append(float(bar.close))

        if len(closes) < self.slow_window + self.signal_window:
            return []

        fast_ema = _ema(closes, self.fast_window)
        slow_ema = _ema(closes, self.slow_window)

        if len(closes) == self.slow_window + self.signal_window:
            dif = fast_ema - slow_ema
            self._macd_line[bar.symbol] = [dif]
            self._signal_line[bar.symbol] = [dif]
        else:
            dif = fast_ema - slow_ema
            macd_vals = self._macd_line[bar.symbol]
            macd_vals.append(dif)
            dea = _ema(macd_vals, self.signal_window)
            sig_vals = self._signal_line[bar.symbol]
            sig_vals.append(dea)
            prev_state = self._state[bar.symbol]

            if dif > dea and fast_ema > slow_ema and prev_state <= 0:
                self._state[bar.symbol] = 1
                return [Signal(
                    timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                    symbol=bar.symbol, direction=SignalDirection.LONG, strength=0.8, horizon="1d",
                )]
            elif dif < dea and fast_ema < slow_ema and prev_state >= 0:
                self._state[bar.symbol] = -1
                return [Signal(
                    timestamp_utc=event.timestamp_utc, strategy_id=self.strategy_id,
                    symbol=bar.symbol, direction=SignalDirection.SHORT, strength=0.8, horizon="1d",
                )]
        return []
