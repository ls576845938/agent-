from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.enums import OrderSide


@dataclass(frozen=True)
class BpsSlippage:
    bps: float = 1.0

    def apply(self, side: OrderSide, price: float) -> float:
        multiplier = 1.0 + self.bps / 10_000.0 if side == OrderSide.BUY else 1.0 - self.bps / 10_000.0
        return price * multiplier
