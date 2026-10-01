from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.enums import OrderSide


@dataclass(frozen=True)
class LiquiditySlippage:
    """Slippage model that scales with order size relative to bar volume.

    Larger orders relative to volume get proportionally more slippage.
    Base bps applied to all orders. Participation-aware bps scale with
    the order's share of bar volume.

    slippage = base_bps + participation_bps * (order_notional / bar_volume * volume_impact_scale)
    """

    base_bps: float = 0.5
    participation_bps: float = 2.0
    volume_impact_scale: float = 1.0
    volume_cap_pct: float = 5.0
    max_bps: float = 50.0

    def apply(self, side: OrderSide, price: float, quantity: float, bar_volume: float = 0.0) -> float:
        if bar_volume <= 0:
            bar_volume = quantity * 100

        participation = (abs(quantity * price) / bar_volume * 100.0) if bar_volume > 0 else 0.0
        capped = min(participation, self.volume_cap_pct)
        total_bps = self.base_bps + self.participation_bps * capped * self.volume_impact_scale
        total_bps = min(total_bps, self.max_bps)

        multiplier = 1.0 + total_bps / 10_000.0 if side == OrderSide.BUY else 1.0 - total_bps / 10_000.0
        return price * multiplier

    def apply_notional(self, side: OrderSide, price: float, notional: float, bar_volume: float = 0.0) -> float:
        quantity = notional / price if price > 0 else 0.0
        return self.apply(side, price, quantity, bar_volume)
