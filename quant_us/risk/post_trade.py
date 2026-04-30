from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.types import Fill


@dataclass(frozen=True)
class PostTradeAlert:
    fill_id: str
    reason: str
    observed_value: float


class PostTradeRiskEngine:
    def __init__(self, max_slippage_bps: float = 50.0) -> None:
        self.max_slippage_bps = max_slippage_bps

    def check_slippage(self, fill: Fill, expected_price: float) -> list[PostTradeAlert]:
        if expected_price <= 0:
            return [PostTradeAlert(fill.fill_id, "missing_expected_price", 0.0)]
        slippage_bps = abs(fill.price / expected_price - 1.0) * 10_000.0
        if slippage_bps > self.max_slippage_bps:
            return [PostTradeAlert(fill.fill_id, "slippage_limit", slippage_bps)]
        return []
