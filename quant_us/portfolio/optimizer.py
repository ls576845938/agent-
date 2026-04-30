from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StaticStrategyAllocation:
    weights: dict[str, float]

    def normalized(self) -> dict[str, float]:
        positive = {key: max(0.0, value) for key, value in self.weights.items()}
        total = sum(positive.values())
        if total <= 0:
            return {key: 0.0 for key in positive}
        return {key: value / total for key, value in positive.items()}
