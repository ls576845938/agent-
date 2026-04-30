from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from quant_us.core.types import TargetPosition


@dataclass(frozen=True)
class AllocationConfig:
    max_symbol_weight: float = 0.1
    cash_reserve_weight: float = 0.05
    max_group_weight: float | None = None
    group_map: dict[str, str] = field(default_factory=dict)


class AllocationCombiner:
    def __init__(self, config: AllocationConfig | None = None) -> None:
        self.config = config or AllocationConfig()

    def combine(self, targets: list[TargetPosition]) -> list[TargetPosition]:
        if not targets:
            return []
        by_symbol: dict[str, float] = defaultdict(float)
        latest: dict[str, TargetPosition] = {}
        for target in targets:
            by_symbol[target.symbol] += target.target_weight
            latest[target.symbol] = target

        gross_cap = max(0.0, 1.0 - self.config.cash_reserve_weight)
        capped_weights: dict[str, float] = {}
        for symbol, raw_weight in by_symbol.items():
            capped = max(-self.config.max_symbol_weight, min(self.config.max_symbol_weight, raw_weight))
            capped = max(-gross_cap, min(gross_cap, capped))
            capped_weights[symbol] = capped

        capped_weights = self._scale_to_gross_cap(capped_weights, gross_cap)
        capped_weights = self._scale_group_exposure(capped_weights)
        capped_weights = self._scale_to_gross_cap(capped_weights, gross_cap)

        combined: list[TargetPosition] = []
        for symbol, capped in capped_weights.items():
            source = latest[symbol]
            combined.append(
                TargetPosition(
                    timestamp_utc=source.timestamp_utc,
                    strategy_id="portfolio",
                    symbol=symbol,
                    target_weight=capped,
                    signal_id=source.signal_id,
                    metadata={"raw_weight": by_symbol[symbol], "group": self._group_for(symbol)},
                )
            )
        return combined

    @staticmethod
    def _scale_to_gross_cap(weights: dict[str, float], gross_cap: float) -> dict[str, float]:
        gross = sum(abs(weight) for weight in weights.values())
        if gross <= gross_cap or gross <= 0:
            return weights
        scale = gross_cap / gross
        return {symbol: weight * scale for symbol, weight in weights.items()}

    def _scale_group_exposure(self, weights: dict[str, float]) -> dict[str, float]:
        if self.config.max_group_weight is None:
            return weights
        output = dict(weights)
        by_group: dict[str, list[str]] = defaultdict(list)
        for symbol in weights:
            by_group[self._group_for(symbol)].append(symbol)
        for symbols in by_group.values():
            exposure = sum(abs(output[symbol]) for symbol in symbols)
            if exposure > self.config.max_group_weight and exposure > 0:
                scale = self.config.max_group_weight / exposure
                for symbol in symbols:
                    output[symbol] *= scale
        return output

    def _group_for(self, symbol: str) -> str:
        return self.config.group_map.get(symbol.upper(), "ungrouped")
