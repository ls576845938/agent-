"""Explicit base, conservative, and stress execution-cost assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_cn.market.rules import FeeComponent, FeePolicy


@dataclass(frozen=True)
class CostScenario:
    name: str
    commission_rate: Decimal
    sell_tax_rate: Decimal
    slippage_bps: Decimal
    market_impact_bps: Decimal
    capacity_fraction: Decimal
    version: str

    def __post_init__(self) -> None:
        if self.name not in {"base", "conservative", "stress"}:
            raise ValueError("cost_scenario_name_unknown")
        if not self.version.strip():
            raise ValueError("cost_scenario_version_required")
        for name in (
            "commission_rate",
            "sell_tax_rate",
            "slippage_bps",
            "market_impact_bps",
            "capacity_fraction",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"non_negative_decimal_required:{name}")
        if self.capacity_fraction <= 0 or self.capacity_fraction > 1:
            raise ValueError("capacity_fraction_out_of_range")

    @property
    def friction_score(self) -> Decimal:
        return (
            self.commission_rate
            + self.sell_tax_rate
            + (self.slippage_bps + self.market_impact_bps) / Decimal("10000")
        )

    def fee_policy(self) -> FeePolicy:
        commission = FeeComponent(
            name="commission",
            rate=self.commission_rate,
            minimum_amount=Decimal("0"),
            fixed_amount=Decimal("0"),
            rounding_quantum=Decimal("0.01"),
            rounding_mode="half_up",
        )
        tax = FeeComponent(
            name="sell_tax",
            rate=self.sell_tax_rate,
            minimum_amount=Decimal("0"),
            fixed_amount=Decimal("0"),
            rounding_quantum=Decimal("0.01"),
            rounding_mode="half_up",
        )
        return FeePolicy(buy=(commission,), sell=(commission, tax))

    def execution_price(self, *, side: str, reference_price: Decimal, tick_size: Decimal) -> Decimal:
        direction = Decimal("1") if side == "buy" else Decimal("-1")
        raw = reference_price * (
            Decimal("1")
            + direction
            * (self.slippage_bps + self.market_impact_bps)
            / Decimal("10000")
        )
        units = (raw / tick_size).quantize(Decimal("1"))
        return units * tick_size


def validate_cost_ladder(scenarios: tuple[CostScenario, ...]) -> tuple[str, ...]:
    by_name = {item.name: item for item in scenarios}
    blockers: list[str] = []
    if set(by_name) != {"base", "conservative", "stress"}:
        blockers.append("three_cost_scenarios_required")
        return tuple(blockers)
    if not (
        by_name["base"].friction_score
        < by_name["conservative"].friction_score
        < by_name["stress"].friction_score
    ):
        blockers.append("cost_scenario_order_invalid")
    for field_name in (
        "commission_rate",
        "sell_tax_rate",
        "slippage_bps",
        "market_impact_bps",
    ):
        if not (
            getattr(by_name["base"], field_name)
            <= getattr(by_name["conservative"], field_name)
            <= getattr(by_name["stress"], field_name)
        ):
            blockers.append(f"cost_component_order_invalid:{field_name}")
    if not (
        by_name["base"].capacity_fraction
        >= by_name["conservative"].capacity_fraction
        >= by_name["stress"].capacity_fraction
    ):
        blockers.append("capacity_stress_order_invalid")
    return tuple(blockers)
