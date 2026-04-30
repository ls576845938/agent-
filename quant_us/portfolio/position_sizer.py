from __future__ import annotations

from dataclasses import dataclass, field

from quant_us.core.enums import SignalDirection
from quant_us.core.types import Signal, TargetPosition


@dataclass(frozen=True)
class PositionSizerConfig:
    strategy_allocations: dict[str, float] = field(default_factory=dict)
    default_strategy_weight: float = 0.1
    max_symbol_weight: float = 0.1
    long_only: bool = True


class PercentOfEquitySizer:
    def __init__(self, config: PositionSizerConfig | None = None) -> None:
        self.config = config or PositionSizerConfig()

    def size(self, signals: list[Signal]) -> list[TargetPosition]:
        targets: list[TargetPosition] = []
        for signal in signals:
            base_weight = self.config.strategy_allocations.get(signal.strategy_id, self.config.default_strategy_weight)
            if signal.direction == SignalDirection.FLAT:
                target_weight = 0.0
            elif signal.direction == SignalDirection.LONG:
                target_weight = base_weight * signal.strength
            elif self.config.long_only:
                target_weight = 0.0
            else:
                target_weight = -base_weight * signal.strength

            target_weight = max(-self.config.max_symbol_weight, min(self.config.max_symbol_weight, target_weight))
            targets.append(
                TargetPosition(
                    timestamp_utc=signal.timestamp_utc,
                    strategy_id=signal.strategy_id,
                    symbol=signal.symbol,
                    target_weight=target_weight,
                    signal_id=signal.signal_id,
                    metadata={"signal_reason": signal.reason},
                )
            )
        return targets
