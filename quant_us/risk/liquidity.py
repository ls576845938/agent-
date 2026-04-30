from __future__ import annotations

from dataclasses import dataclass

from quant_us.core.types import OrderIntent, RiskDecision


@dataclass(frozen=True)
class LiquidityRule:
    max_adv_participation: float = 0.01


class LiquidityGuard:
    def __init__(self, rule: LiquidityRule | None = None) -> None:
        self.rule = rule or LiquidityRule()

    def evaluate(self, intent: OrderIntent, average_daily_volume: float) -> RiskDecision:
        if average_daily_volume <= 0:
            return RiskDecision(False, "missing_liquidity", intent.order_intent_id)
        if intent.quantity / average_daily_volume > self.rule.max_adv_participation:
            return RiskDecision(False, "adv_participation_limit", intent.order_intent_id)
        return RiskDecision(True, "approved", intent.order_intent_id)
