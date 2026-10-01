from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from quant_us.core.enums import SignalDirection
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass
class FactorRankStrategy(Strategy):
    strategy_id: str = "factor_rank"
    factor_name: str = "momentum_score"
    top_n: int = 5
    bottom_n: int = 0
    min_symbols: int = 5
    rank_descending: bool = True
    allow_short: bool = False
    emit_flats: bool = True

    def on_bar(self, event: MarketEvent, context: StrategyContext):
        bar = event.bar
        ranked = self._ranked_symbols(context)
        if len(ranked) < self.min_symbols:
            return []

        long_symbols = {symbol for symbol, _ in ranked[: max(0, self.top_n)]}
        short_symbols = set()
        if self.allow_short and self.bottom_n > 0:
            short_symbols = {symbol for symbol, _ in ranked[-self.bottom_n :]}

        if bar.symbol in long_symbols:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.LONG,
                    strength=1.0,
                    horizon="cross_sectional",
                    reason=f"top_{self.factor_name}",
                    metadata={"factor_name": self.factor_name, "factor_value": context.features[bar.symbol][self.factor_name]},
                )
            ]
        if bar.symbol in short_symbols:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.SHORT,
                    strength=1.0,
                    horizon="cross_sectional",
                    reason=f"bottom_{self.factor_name}",
                    metadata={"factor_name": self.factor_name, "factor_value": context.features[bar.symbol][self.factor_name]},
                )
            ]
        if self.emit_flats and bar.symbol in context.features:
            return [
                Signal(
                    timestamp_utc=bar.timestamp_utc,
                    strategy_id=self.strategy_id,
                    symbol=bar.symbol,
                    direction=SignalDirection.FLAT,
                    strength=1.0,
                    horizon="cross_sectional",
                    reason=f"not_selected_{self.factor_name}",
                    metadata={"factor_name": self.factor_name},
                )
            ]
        return []

    def _ranked_symbols(self, context: StrategyContext) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        tradable = set(context.universe or context.market_prices)
        for symbol, values in context.features.items():
            if tradable and symbol not in tradable:
                continue
            value = values.get(self.factor_name)
            if value is None:
                continue
            value = float(value)
            if isfinite(value):
                scored.append((symbol, value))
        return sorted(scored, key=lambda item: (item[1], item[0]), reverse=self.rank_descending)
