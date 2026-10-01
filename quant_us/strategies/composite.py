from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from quant_shared.strategy_runtime import (
    StrategyStateKey,
    StrategyStateSnapshot,
)
from quant_us.core.events import MarketEvent
from quant_us.core.types import Signal, TargetPosition
from quant_us.strategies.base import Strategy, StrategyContext, StrategyDecision


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
        decision = self._decide_children(event, context, allow_state_transition=False)
        return decision.signals

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        return self._decide_children(event, context, allow_state_transition=True)

    def _decide_children(
        self,
        event: MarketEvent,
        context: StrategyContext,
        *,
        allow_state_transition: bool,
    ) -> StrategyDecision:
        signals: list[Signal] = []
        target_positions: list[TargetPosition] = []
        parent_payload = dict(context.state.payload)
        raw_children = parent_payload.get("children", {})
        children_payload = dict(raw_children) if hasattr(raw_children, "items") else {}
        state_changed = False
        for strategy, spec in self._strategy_spec_pairs():
            event_timeframe = str(getattr(event.bar, "bar_size", "") or "").lower()
            spec_timeframe = str(spec.timeframe or "").lower() if spec is not None else ""
            if event_timeframe and spec_timeframe and event_timeframe != spec_timeframe:
                continue
            child_id = str(getattr(strategy, "strategy_id", "") or type(strategy).__name__)
            child_version = str(
                getattr(strategy, "version", "") or "unbound_strategy_version"
            )
            child_identity = replace(
                context.identity,
                strategy_id=child_id,
                strategy_version=child_version,
            )
            child_key = StrategyStateKey(
                run_id=child_identity.run_id,
                strategy_id=child_id,
                identity_digest=child_identity.digest,
            )
            raw_child_state = children_payload.get(child_id)
            if hasattr(raw_child_state, "get"):
                child_state = StrategyStateSnapshot(
                    key=child_key,
                    schema_version=str(
                        raw_child_state.get("schema_version") or "strategy_state_v1"
                    ),
                    revision=int(raw_child_state.get("revision", 0)),
                    payload=raw_child_state.get("payload") or {},
                    digest=str(raw_child_state.get("digest") or ""),
                )
            else:
                child_state = StrategyStateSnapshot.empty(child_key)
            child_context = StrategyContext(
                identity=child_identity,
                clock=context.clock,
                exposure=context.exposure,
                state=child_state,
                capabilities=context.capabilities,
                parameters={
                    **dict(context.parameters),
                    "strategy_id": child_id,
                    "strategy_timeframe": spec_timeframe,
                    "bar_size": event_timeframe,
                },
                market=context.market,
                features=context.features,
                universe=context.universe,
            )
            child_decision = strategy.decide(event, child_context)
            for signal in child_decision.signals:
                metadata = dict(signal.metadata)
                if event_timeframe:
                    metadata.setdefault("bar_size", event_timeframe)
                if spec_timeframe:
                    metadata.setdefault("strategy_timeframe", spec_timeframe)
                signals.append(replace(signal, metadata=metadata))
            target_positions.extend(child_decision.target_positions)
            transition = child_decision.state_transition
            if transition is not None:
                if not allow_state_transition:
                    raise RuntimeError(
                        "composite child state transition requires Strategy.decide service"
                    )
                if transition.key != child_key:
                    raise ValueError("composite child transition identity mismatch")
                if transition.expected_revision != child_state.revision:
                    raise ValueError("composite child transition revision mismatch")
                if transition.previous_digest != child_state.digest:
                    raise ValueError("composite child transition digest mismatch")
                next_child_state = transition.to_snapshot()
                children_payload[child_id] = {
                    "schema_version": next_child_state.schema_version,
                    "revision": next_child_state.revision,
                    "payload": dict(next_child_state.payload),
                    "digest": next_child_state.digest,
                }
                state_changed = True
        parent_transition = None
        if state_changed:
            parent_payload["children"] = children_payload
            parent_transition = context.state.transition(
                parent_payload,
                reason="composite_child_state_transitions",
            )
        return StrategyDecision(
            signals=tuple(signals),
            target_positions=tuple(target_positions),
            state_transition=parent_transition,
        )

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
