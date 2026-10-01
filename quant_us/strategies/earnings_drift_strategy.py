from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


@dataclass
class EarningsDriftStrategy(Strategy):
    """Post-earnings announcement drift (PEAD) strategy.

    Enters positions on earnings event dates in the direction of the
    immediate price reaction and holds for drift_period_days. This
    captures the well-documented tendency of stocks to drift in the
    direction of earnings surprises for weeks after the announcement.
    """

    strategy_id: str = "earnings_drift"
    drift_period_days: int = 30
    min_price: float = 5.0
    max_positions: int = 10
    allow_short: bool = True
    reaction_lookback_days: int = 2

    _earnings_dates: dict[str, set[date]] = field(default_factory=dict)
    _active_positions: dict[str, dict] = field(default_factory=dict)
    _entry_prices: dict[str, list[float]] = field(default_factory=dict)
    _pending_entry: dict[str, Signal] = field(default_factory=dict)

    def set_earnings_dates(self, symbol: str, dates: set[date]) -> None:
        self._earnings_dates[symbol] = dates

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        bar = event.bar
        if bar.close <= 0 or bar.close < self.min_price:
            return StrategyDecision()
        bar_date = bar.timestamp_utc.date()
        symbol = bar.symbol
        prices = {
            str(key): [float(value) for value in values]
            for key, values in context.state.payload.get("prices", {}).items()
        }
        active_positions = {
            str(key): dict(value)
            for key, value in context.state.payload.get("active_positions", {}).items()
        }
        pending_entries = {
            str(key): dict(value)
            for key, value in context.state.payload.get("pending_entries", {}).items()
        }
        symbol_prices = prices.setdefault(symbol, [])
        symbol_prices.append(float(bar.close))
        prices[symbol] = symbol_prices[-(self.reaction_lookback_days + 1) :]
        signals: list[Signal] = []

        pending = pending_entries.pop(symbol, None)
        if pending is not None:
            signals.append(Signal(
                timestamp_utc=bar.timestamp_utc,
                strategy_id=str(pending["strategy_id"]),
                symbol=str(pending["symbol"]),
                direction=SignalDirection(str(pending["direction"])),
                strength=float(pending["strength"]),
                horizon=str(pending["horizon"]),
                reason=str(pending["reason"]),
                metadata=dict(pending.get("metadata", {})),
            ))

        exits: list[Signal] = []
        for active_symbol, position in list(active_positions.items()):
            if str(position.get("symbol")) != symbol:
                continue
            entry_date = date.fromisoformat(str(position["entry_date"]))
            holding_days = (bar_date - entry_date).days
            if holding_days >= self.drift_period_days:
                exits.append(Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=active_symbol,
                    direction=SignalDirection.FLAT,
                    strength=1.0,
                    horizon=f"{self.drift_period_days}d",
                    reason="drift_period_expired",
                    metadata={"holding_days": holding_days},
                ))
                del active_positions[active_symbol]
        signals.extend(exits)

        if not exits and pending is None:
            earnings_dates = self._earnings_dates.get(symbol, set())
            if (
                bar_date in earnings_dates
                and len(active_positions) < self.max_positions
            ):
                pre_prices = (
                    symbol_prices[-self.reaction_lookback_days - 1 : -1]
                    if len(symbol_prices) > self.reaction_lookback_days
                    else []
                )
                if pre_prices:
                    pre_average = sum(pre_prices) / len(pre_prices)
                    reaction = (
                        bar.close / pre_average - 1.0 if pre_average > 0 else 0.0
                    )
                    if reaction > 0.005:
                        direction = SignalDirection.LONG
                        reason = "positive_earnings_reaction"
                    elif self.allow_short and reaction < -0.005:
                        direction = SignalDirection.SHORT
                        reason = "negative_earnings_reaction"
                    else:
                        direction = None
                        reason = ""
                    if direction is not None:
                        active_positions[symbol] = {
                            "symbol": symbol,
                            "entry_date": bar_date.isoformat(),
                            "entry_price": float(bar.close),
                            "direction": direction.value,
                        }
                        pending_entries[symbol] = {
                            "strategy_id": self.strategy_id,
                            "symbol": symbol,
                            "direction": direction.value,
                            "strength": min(1.0, abs(reaction) * 50),
                            "horizon": f"{self.drift_period_days}d",
                            "reason": reason,
                            "metadata": {
                                "reaction_pct": round(reaction * 100, 2),
                                "drift_period_days": self.drift_period_days,
                            },
                        }

        return StrategyDecision(
            signals=tuple(signals),
            state_transition=context.state.transition(
                {
                    "prices": prices,
                    "active_positions": active_positions,
                    "pending_entries": pending_entries,
                },
                reason="earnings_drift_bar_applied",
            ),
        )

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        if bar.close <= 0 or bar.close < self.min_price:
            return []

        bar_date = bar.timestamp_utc.date()
        symbol = bar.symbol

        prices = self._entry_prices.setdefault(symbol, [])
        prices.append(float(bar.close))

        # Emit any pending entry from a previous bar (one-bar delay to avoid
        # using the same bar's close for both signal generation and fill price).
        signals: list[Signal] = []
        if symbol in self._pending_entry:
            pending = self._pending_entry.pop(symbol)
            signals.append(Signal(
                timestamp_utc=bar.timestamp_utc,
                strategy_id=pending.strategy_id,
                symbol=pending.symbol,
                direction=pending.direction,
                strength=pending.strength,
                horizon=pending.horizon,
                reason=pending.reason,
                metadata=pending.metadata,
            ))

        exits: list[Signal] = []
        for sym, pos in list(self._active_positions.items()):
            if pos["symbol"] != symbol:
                continue
            holding_days = (bar_date - pos["entry_date"]).days
            if holding_days >= self.drift_period_days:
                exits.append(
                    Signal(
                        timestamp_utc=bar.timestamp_utc,
                        strategy_id=self.strategy_id,
                        symbol=sym,
                        direction=SignalDirection.FLAT,
                        strength=1.0,
                        horizon=f"{self.drift_period_days}d",
                        reason="drift_period_expired",
                        metadata={"holding_days": holding_days},
                    )
                )
                del self._active_positions[sym]
        if exits:
            return signals + exits

        # If we just emitted a pending entry, don't also check for new entries
        # this bar — the pending entry was already counted against max_positions.
        if signals:
            return signals

        earnings_dates = self._earnings_dates.get(symbol, set())
        if bar_date not in earnings_dates:
            return signals

        if len(self._active_positions) >= self.max_positions:
            return signals

        pre_prices = prices[-self.reaction_lookback_days - 1 : -1] if len(prices) > self.reaction_lookback_days else []
        if not pre_prices:
            return signals

        pre_avg = sum(pre_prices) / len(pre_prices)
        reaction = bar.close / pre_avg - 1.0 if pre_avg > 0 else 0.0

        if reaction > 0.005:
            direction = SignalDirection.LONG
            reason = "positive_earnings_reaction"
        elif self.allow_short and reaction < -0.005:
            direction = SignalDirection.SHORT
            reason = "negative_earnings_reaction"
        else:
            return signals

        self._active_positions[symbol] = {
            "symbol": symbol,
            "entry_date": bar_date,
            "entry_price": float(bar.close),
            "direction": direction,
        }

        # Buffer the entry signal for the next bar — the close-based reaction
        # decision cannot be executed at the same close it was derived from.
        self._pending_entry[symbol] = Signal(
            timestamp_utc=bar.timestamp_utc,
            strategy_id=self.strategy_id,
            symbol=symbol,
            direction=direction,
            strength=min(1.0, abs(reaction) * 50),
            horizon=f"{self.drift_period_days}d",
            reason=reason,
            metadata={"reaction_pct": round(reaction * 100, 2), "drift_period_days": self.drift_period_days},
        )
        return signals
