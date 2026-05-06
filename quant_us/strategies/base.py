from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

from quant_us.core.events import MarketEvent
from quant_us.core.types import AccountState, Signal


@dataclass
class StrategyContext:
    run_id: str
    account: AccountState | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    market_prices: dict[str, float] = field(default_factory=dict)
    features: dict[str, dict[str, float]] = field(default_factory=dict)
    universe: list[str] = field(default_factory=list)


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
