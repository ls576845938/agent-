from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quant_crypto.trading_contracts import (
    OrderIntent,
    OrderSide,
    OrderType,
    TargetPosition,
    TimeInForce,
)


BTC_COST_AWARE_ORDER_INTENT_VERSION = "btc_cost_aware_order_intent_v1"


@dataclass(frozen=True)
class BTCExecutionCostEstimate:
    fee_bps: float | None
    spread_bps: float | None
    slippage_bps: float | None
    funding_bps: float | None
    impact_bps: float | None
    source: str = ""

    def __post_init__(self) -> None:
        for field_name in ["fee_bps", "spread_bps", "slippage_bps", "funding_bps", "impact_bps"]:
            value = getattr(self, field_name)
            if value is None:
                continue
            if float(value) < 0.0:
                raise ValueError(f"{field_name} must be non-negative.")
            object.__setattr__(self, field_name, float(value))

    @property
    def missing_components(self) -> list[str]:
        return [
            field_name
            for field_name in ["fee_bps", "spread_bps", "slippage_bps", "funding_bps", "impact_bps"]
            if getattr(self, field_name) is None
        ]

    @property
    def total_cost_bps(self) -> float:
        if self.missing_components:
            raise ValueError("Cannot total BTC execution cost with missing components.")
        return sum(
            float(getattr(self, field_name))
            for field_name in ["fee_bps", "spread_bps", "slippage_bps", "funding_bps", "impact_bps"]
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "fee_bps": self.fee_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "funding_bps": self.funding_bps,
            "impact_bps": self.impact_bps,
            "missing_components": self.missing_components,
            "total_cost_bps": None if self.missing_components else self.total_cost_bps,
            "source": self.source,
        }


@dataclass(frozen=True)
class BTCOrderIntentDecision:
    approved: bool
    blockers: list[str]
    order_intent: OrderIntent | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def btc_target_to_cost_aware_order_intent(
    target: TargetPosition,
    *,
    current_quantity: float,
    cost_estimate: BTCExecutionCostEstimate,
    min_quantity: float = 0.0,
    min_alpha_to_cost_ratio: float = 1.0,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.IOC,
) -> BTCOrderIntentDecision:
    blockers: list[str] = []
    metadata: dict[str, Any] = {
        "order_intent_construction_version": BTC_COST_AWARE_ORDER_INTENT_VERSION,
        "target_position_id": target.target_position_id,
        "forecast_id": target.metadata.get("forecast_id"),
        "source_signal_id": target.signal_id,
        "cost_estimate": cost_estimate.to_metadata(),
        "source_boundary": "cost_gate_to_order_intent_no_broker_submit",
    }
    if target.metadata.get("order_generation_allowed") is False:
        blockers.append("target_blocks_order_generation")
    if cost_estimate.missing_components:
        blockers.append("execution_cost_estimate_incomplete")

    target_quantity = target.target_quantity
    if target_quantity is None:
        blockers.append("target_quantity_missing")
        target_quantity = current_quantity
    delta_quantity = float(target_quantity) - float(current_quantity)
    metadata["current_quantity"] = float(current_quantity)
    metadata["target_quantity"] = float(target_quantity)
    metadata["delta_quantity"] = delta_quantity
    metadata["min_quantity"] = float(min_quantity)
    if abs(delta_quantity) <= float(min_quantity):
        blockers.append("delta_quantity_below_minimum")

    expected_return_bps = _optional_float(target.metadata.get("forecast_expected_return_bps"))
    if expected_return_bps is None:
        blockers.append("forecast_expected_return_missing")
        expected_return_bps = 0.0
    if not cost_estimate.missing_components:
        total_cost_bps = cost_estimate.total_cost_bps
        required_alpha_bps = total_cost_bps * float(min_alpha_to_cost_ratio)
        cost_adjusted_alpha_bps = abs(expected_return_bps) - required_alpha_bps
        metadata["alpha_cost_gate"] = {
            "expected_return_bps": expected_return_bps,
            "absolute_expected_return_bps": abs(expected_return_bps),
            "total_cost_bps": total_cost_bps,
            "min_alpha_to_cost_ratio": float(min_alpha_to_cost_ratio),
            "required_alpha_bps": required_alpha_bps,
            "cost_adjusted_alpha_bps": cost_adjusted_alpha_bps,
        }
        if cost_adjusted_alpha_bps <= 0.0:
            blockers.append("alpha_increment_not_cost_effective")
    else:
        metadata["alpha_cost_gate"] = {
            "expected_return_bps": expected_return_bps,
            "absolute_expected_return_bps": abs(expected_return_bps),
            "total_cost_bps": None,
            "min_alpha_to_cost_ratio": float(min_alpha_to_cost_ratio),
            "required_alpha_bps": None,
            "cost_adjusted_alpha_bps": None,
        }

    if blockers:
        return BTCOrderIntentDecision(approved=False, blockers=_dedupe(blockers), metadata=metadata)

    side = OrderSide.BUY if delta_quantity > 0.0 else OrderSide.SELL
    intent = OrderIntent(
        timestamp_utc=target.timestamp_utc,
        strategy_id=target.strategy_id,
        symbol=target.symbol,
        side=side,
        quantity=abs(delta_quantity),
        order_type=order_type,
        time_in_force=time_in_force,
        signal_id=target.signal_id,
        target_position_id=target.target_position_id,
        metadata=metadata,
    )
    return BTCOrderIntentDecision(approved=True, blockers=[], order_intent=intent, metadata=metadata)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
