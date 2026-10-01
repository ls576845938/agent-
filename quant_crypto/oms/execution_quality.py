from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from quant_shared.core.time import ensure_utc

from .lifecycle import BTCPaperOrderLifecycle, BTCPaperOrderStatus


BTC_EXECUTION_QUALITY_VERSION = "btc_execution_quality_v1"


@dataclass(frozen=True)
class BTCExecutionFill:
    client_order_id: str
    fill_id: str
    filled_quantity: float
    arrival_price: float
    fill_price: float
    benchmark_price: float
    submitted_at_utc: datetime
    filled_at_utc: datetime
    fee: float = 0.0
    spread_cost: float = 0.0
    market_impact_cost: float = 0.0
    delay_cost: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "filled_quantity", float(self.filled_quantity))
        object.__setattr__(self, "arrival_price", float(self.arrival_price))
        object.__setattr__(self, "fill_price", float(self.fill_price))
        object.__setattr__(self, "benchmark_price", float(self.benchmark_price))
        object.__setattr__(self, "submitted_at_utc", ensure_utc(self.submitted_at_utc))
        object.__setattr__(self, "filled_at_utc", ensure_utc(self.filled_at_utc))
        for field_name in ["fee", "spread_cost", "market_impact_cost", "delay_cost"]:
            object.__setattr__(self, field_name, float(getattr(self, field_name)))
        if self.filled_quantity <= 0.0:
            raise ValueError("filled_quantity must be positive.")

    @property
    def latency_ms(self) -> float:
        return max(0.0, (self.filled_at_utc - self.submitted_at_utc).total_seconds() * 1000.0)

    @property
    def implementation_shortfall(self) -> float:
        return (self.fill_price - self.arrival_price) * self.filled_quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "fill_id": self.fill_id,
            "filled_quantity": self.filled_quantity,
            "arrival_price": self.arrival_price,
            "fill_price": self.fill_price,
            "benchmark_price": self.benchmark_price,
            "submitted_at_utc": self.submitted_at_utc.isoformat(),
            "filled_at_utc": self.filled_at_utc.isoformat(),
            "latency_ms": self.latency_ms,
            "implementation_shortfall": self.implementation_shortfall,
            "fee": self.fee,
            "spread_cost": self.spread_cost,
            "market_impact_cost": self.market_impact_cost,
            "delay_cost": self.delay_cost,
        }


@dataclass(frozen=True)
class BTCExecutionQualityReport:
    order_count: int
    filled_order_count: int
    rejected_order_count: int
    cancelled_order_count: int
    expired_order_count: int
    requested_quantity: float
    filled_quantity: float
    unfilled_quantity: float
    fill_rate: float
    reject_rate: float
    cancel_rate: float
    average_latency_ms: float
    implementation_shortfall: float
    unfilled_opportunity_cost: float
    fee: float
    spread_cost: float
    market_impact_cost: float
    delay_cost: float
    lifecycle_version: str = BTC_EXECUTION_QUALITY_VERSION
    blocker_reasons: list[str] = field(default_factory=list)
    fill_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_quality_version": self.lifecycle_version,
            "order_count": self.order_count,
            "filled_order_count": self.filled_order_count,
            "rejected_order_count": self.rejected_order_count,
            "cancelled_order_count": self.cancelled_order_count,
            "expired_order_count": self.expired_order_count,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "unfilled_quantity": self.unfilled_quantity,
            "fill_rate": self.fill_rate,
            "reject_rate": self.reject_rate,
            "cancel_rate": self.cancel_rate,
            "average_latency_ms": self.average_latency_ms,
            "implementation_shortfall": self.implementation_shortfall,
            "unfilled_opportunity_cost": self.unfilled_opportunity_cost,
            "fee": self.fee,
            "spread_cost": self.spread_cost,
            "market_impact_cost": self.market_impact_cost,
            "delay_cost": self.delay_cost,
            "blocker_reasons": list(self.blocker_reasons),
            "fill_details": list(self.fill_details),
        }


def build_btc_execution_quality_report(
    orders: Iterable[BTCPaperOrderLifecycle],
    fills: Iterable[BTCExecutionFill],
    *,
    opportunity_benchmark_price: float,
) -> BTCExecutionQualityReport:
    orders_list = list(orders)
    fills_list = list(fills)
    fill_by_client_id: dict[str, list[BTCExecutionFill]] = {}
    for fill in fills_list:
        fill_by_client_id.setdefault(fill.client_order_id, []).append(fill)

    order_count = len(orders_list)
    requested_quantity = sum(float(order.order_intent.quantity) for order in orders_list)
    filled_quantity = sum(fill.filled_quantity for fill in fills_list)
    unfilled_quantity = max(0.0, requested_quantity - filled_quantity)
    filled_order_count = sum(_has_status(order, BTCPaperOrderStatus.FILLED) for order in orders_list)
    rejected_order_count = sum(_has_status(order, BTCPaperOrderStatus.REJECTED) for order in orders_list)
    cancelled_order_count = sum(_has_status(order, BTCPaperOrderStatus.CANCELLED) for order in orders_list)
    expired_order_count = sum(_has_status(order, BTCPaperOrderStatus.EXPIRED) for order in orders_list)
    fill_rate = _safe_ratio(filled_quantity, requested_quantity)
    reject_rate = _safe_ratio(rejected_order_count, order_count)
    cancel_rate = _safe_ratio(cancelled_order_count, order_count)
    latencies = [fill.latency_ms for fill in fills_list]
    implementation_shortfall = sum(fill.implementation_shortfall for fill in fills_list)
    unfilled_opportunity_cost = _unfilled_opportunity_cost(orders_list, fill_by_client_id, opportunity_benchmark_price)
    blockers: list[str] = []
    if order_count == 0:
        blockers.append("btc_execution_quality_no_orders")
    if any(order.status != BTCPaperOrderStatus.RECONCILED for order in orders_list):
        blockers.append("btc_execution_quality_unreconciled_orders")
    if fills_list and any(fill.client_order_id not in {order.client_order_id for order in orders_list} for fill in fills_list):
        blockers.append("btc_execution_quality_fill_without_order")

    return BTCExecutionQualityReport(
        order_count=order_count,
        filled_order_count=filled_order_count,
        rejected_order_count=rejected_order_count,
        cancelled_order_count=cancelled_order_count,
        expired_order_count=expired_order_count,
        requested_quantity=round(requested_quantity, 12),
        filled_quantity=round(filled_quantity, 12),
        unfilled_quantity=round(unfilled_quantity, 12),
        fill_rate=round(fill_rate, 8),
        reject_rate=round(reject_rate, 8),
        cancel_rate=round(cancel_rate, 8),
        average_latency_ms=round(sum(latencies) / len(latencies), 8) if latencies else 0.0,
        implementation_shortfall=round(implementation_shortfall, 12),
        unfilled_opportunity_cost=round(unfilled_opportunity_cost, 12),
        fee=round(sum(fill.fee for fill in fills_list), 12),
        spread_cost=round(sum(fill.spread_cost for fill in fills_list), 12),
        market_impact_cost=round(sum(fill.market_impact_cost for fill in fills_list), 12),
        delay_cost=round(sum(fill.delay_cost for fill in fills_list), 12),
        blocker_reasons=_dedupe(blockers),
        fill_details=[fill.to_dict() for fill in fills_list],
    )


def _has_status(order: BTCPaperOrderLifecycle, status: BTCPaperOrderStatus) -> bool:
    return any(event.status == status for event in order.events)


def _safe_ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else float(numerator) / float(denominator)


def _unfilled_opportunity_cost(
    orders: list[BTCPaperOrderLifecycle],
    fill_by_client_id: dict[str, list[BTCExecutionFill]],
    opportunity_benchmark_price: float,
) -> float:
    cost = 0.0
    for order in orders:
        fills = fill_by_client_id.get(order.client_order_id, [])
        filled_qty = sum(fill.filled_quantity for fill in fills)
        unfilled_qty = max(0.0, float(order.order_intent.quantity) - filled_qty)
        if unfilled_qty == 0.0:
            continue
        arrival_price = _arrival_price(order, fills)
        if order.order_intent.side.value == "buy":
            cost += max(0.0, float(opportunity_benchmark_price) - arrival_price) * unfilled_qty
        else:
            cost += max(0.0, arrival_price - float(opportunity_benchmark_price)) * unfilled_qty
    return cost


def _arrival_price(order: BTCPaperOrderLifecycle, fills: list[BTCExecutionFill]) -> float:
    if fills:
        return fills[0].arrival_price
    value = order.order_intent.metadata.get("arrival_price") or order.order_intent.metadata.get("reference_price")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
