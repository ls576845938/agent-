from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal
from quant_us.strategies.base import Strategy, StrategyContext


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    timeframe: str = "1d"


@dataclass
class CompositeStrategy(Strategy):
    """Run multiple strategies behind the existing Strategy interface."""

    strategies: list[Strategy]
    strategy_id: str = "multi_strategy"
    version: str = "multi_strategy_v1"
    specs: list[StrategySpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.specs:
            return
        spec_ids = [spec.strategy_id for spec in self.specs]
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError("CompositeStrategy specs must have unique strategy_id values")
        missing = [
            str(getattr(strategy, "strategy_id", ""))
            for strategy in self.strategies
            if str(getattr(strategy, "strategy_id", "")) not in set(spec_ids)
        ]
        if missing:
            raise ValueError(f"CompositeStrategy missing specs for strategies: {missing}")

    def on_bar(self, event: MarketEvent, context: StrategyContext) -> Iterable[Signal]:
        signals: list[Signal] = []
        for strategy, spec in self._strategy_spec_pairs():
            event_timeframe = str(getattr(event.bar, "bar_size", "") or "").lower()
            spec_timeframe = str(spec.timeframe or "").lower() if spec is not None else ""
            if event_timeframe and spec_timeframe and event_timeframe != spec_timeframe:
                continue
            child_context = StrategyContext(
                run_id=context.run_id,
                account=context.account,
                parameters={
                    **dict(context.parameters),
                    "strategy_id": str(getattr(strategy, "strategy_id", "")),
                    "strategy_timeframe": spec_timeframe,
                    "bar_size": event_timeframe,
                },
                market_prices=dict(context.market_prices),
                features=dict(context.features),
                universe=list(context.universe),
            )
            for signal in strategy.on_bar(event, child_context):
                metadata = dict(signal.metadata)
                if event_timeframe:
                    metadata.setdefault("bar_size", event_timeframe)
                if spec_timeframe:
                    metadata.setdefault("strategy_timeframe", spec_timeframe)
                signals.append(replace(signal, metadata=metadata))
        return signals

    @property
    def strategy_weights(self) -> dict[str, float]:
        if not self.specs:
            return {
                str(getattr(strategy, "strategy_id", "")): 1.0
                for strategy in self.strategies
                if getattr(strategy, "strategy_id", "")
            }
        return {spec.strategy_id: spec.weight for spec in self.specs}

    @property
    def timeframes(self) -> dict[str, str]:
        return {spec.strategy_id: spec.timeframe for spec in self.specs}

    def _strategy_spec_pairs(self) -> list[tuple[Strategy, StrategySpec | None]]:
        if not self.specs:
            return [(strategy, None) for strategy in self.strategies]
        specs_by_id = {spec.strategy_id: spec for spec in self.specs}
        return [
            (strategy, specs_by_id.get(str(getattr(strategy, "strategy_id", ""))))
            for strategy in self.strategies
        ]
