from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PercentCommission:
    rate: float = 0.0001
    minimum: float = 0.0

    def calculate(self, notional: float) -> float:
        return max(self.minimum, abs(notional) * self.rate)
