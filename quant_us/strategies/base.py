from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from quant_shared.strategy_runtime import (
    StrategyClock,
    StrategyDecisionCapability,
    StrategyDecisionContext,
    StrategyIdentity,
    StrategyRuntimeMode,
    StrategyStateTransition,
)

from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Signal, TargetPosition


StrategyContext = StrategyDecisionContext


@dataclass(frozen=True)
class StrategyDecision:
    signals: tuple[Signal, ...] = ()
    target_positions: tuple[TargetPosition, ...] = ()
    state_transition: StrategyStateTransition | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", tuple(self.signals))
        object.__setattr__(self, "target_positions", tuple(self.target_positions))


def build_strategy_context(
    *,
    run_id: str,
    strategy_id: str,
    strategy_version: str,
    code_version: str,
    data_version: str,
    runtime_mode: StrategyRuntimeMode,
    event_time: datetime,
    decision_time: datetime | None = None,
    available_time: datetime | None = None,
    is_new_bar: bool = True,
    is_final: bool = True,
    account: AccountState | Any | None = None,
    market_prices: Mapping[str, Any] | None = None,
    features: Mapping[str, Any] | None = None,
    universe: list[str] | tuple[str, ...] = (),
    parameters: Mapping[str, Any] | None = None,
    capabilities: tuple[StrategyDecisionCapability, ...] = (
        StrategyDecisionCapability.SIGNAL,
    ),
) -> StrategyContext:
    """Build the same point-in-time contract in every runtime mode."""

    resolved_decision_time = decision_time or event_time
    resolved_available_time = available_time or event_time
    return StrategyContext(
        identity=StrategyIdentity(
            run_id=run_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            code_version=code_version,
            data_version=data_version,
        ),
        clock=StrategyClock(
            mode=runtime_mode,
            decision_time=resolved_decision_time,
            event_time=event_time,
            available_time=resolved_available_time,
            is_new_bar=is_new_bar,
            is_final=is_final,
        ),
        account=account,
        market_prices=market_prices,
        features=features,
        universe=universe,
        parameters=parameters,
        capabilities=capabilities,
    )


class Strategy(ABC):
    """Strategy only emits Signal[] or TargetPosition[]. Never Order, never broker calls.

    - on_bar() receives MarketEvent + StrategyContext and returns Iterable[Signal].
    - Strategies do NOT import broker, OMS, execution, or account modules.
    - Strategies do NOT call data sources directly — all market data arrives via MarketEvent.
    - Strategies do NOT calculate PnL or account for slippage/commission.
    """

    strategy_id: str
    version: str = "0.1.0"

    @abstractmethod
    def on_bar(self, event: MarketEvent, context: StrategyContext) -> Iterable[Signal]:
        raise NotImplementedError

    def on_market_event(self, event: MarketEvent, context: StrategyContext) -> Iterable[Signal]:
        """Streaming adapter entry point.

        Existing strategies only need ``on_bar``. Runtime/engine code can call
        this method for market-event streams and get the same behavior without
        touching alpha logic.
        """
        return self.on_bar(event, context)

    def decide(self, event: MarketEvent, context: StrategyContext) -> StrategyDecision:
        """Return immutable decision outputs plus an optional state transition.

        Existing stateless strategies remain compatible through ``on_bar``.
        Stateful strategies override this method and return a transition built
        from ``context.state``; the runtime service, never the strategy, commits
        that transition.
        """

        return StrategyDecision(signals=tuple(self.on_market_event(event, context)))

    def on_tick(self, event: MarketEvent, context: StrategyContext) -> Iterable[Signal]:
        """Optional tick adapter; defaults to market-event/bar behavior."""
        return self.on_market_event(event, context)
