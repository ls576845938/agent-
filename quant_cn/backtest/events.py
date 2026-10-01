"""Injected PIT market events for deterministic CN backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quant_cn.application.market_semantics_preflight import MarketSemanticsPreflight
from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.market.rules import BoardLotPolicy
from quant_cn.strategy.contracts import DecisionSnapshot


@dataclass(frozen=True)
class BacktestEvent:
    event_id: str
    stable_security_id: str
    event_time: datetime
    available_time: datetime
    decision_time: datetime
    order_created_time: datetime
    execution_time: datetime
    feature_value: Decimal
    reference_price: Decimal
    mark_price: Decimal
    lower_limit_price: Decimal
    upper_limit_price: Decimal
    tick_size: Decimal
    available_liquidity: int
    capacity_quantity: int
    session_sequence: int
    phase: str
    accepts_orders: bool
    suspended: bool
    data_version: str
    rule_versions: tuple[tuple[str, str], ...]
    rule_sources: tuple[tuple[str, str], ...]
    preflight: MarketSemanticsPreflight
    board_lot_policy: BoardLotPolicy

    def __post_init__(self) -> None:
        for name in ("event_id", "stable_security_id", "data_version", "phase"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        for name in (
            "event_time",
            "available_time",
            "decision_time",
            "order_created_time",
            "execution_time",
        ):
            object.__setattr__(
                self, name, ensure_aware_timestamp(getattr(self, name), name)
            )
        if not (
            self.event_time
            <= self.available_time
            <= self.decision_time
            < self.order_created_time
            <= self.execution_time
        ):
            raise ValueError("event_visibility_execution_order_invalid")
        for name in (
            "feature_value",
            "reference_price",
            "mark_price",
            "lower_limit_price",
            "upper_limit_price",
            "tick_size",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"finite_decimal_required:{name}")
        if (
            self.reference_price <= 0
            or self.mark_price <= 0
            or self.lower_limit_price <= 0
            or self.upper_limit_price < self.lower_limit_price
            or self.tick_size <= 0
        ):
            raise ValueError("event_price_state_invalid")
        for name in ("available_liquidity", "capacity_quantity", "session_sequence"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"non_negative_integer_required:{name}")
        if not self.rule_versions or not self.rule_sources:
            raise ValueError("versioned_market_rules_required")
        if not isinstance(self.preflight, MarketSemanticsPreflight):
            raise TypeError("market_semantics_preflight_required")
        if not isinstance(self.board_lot_policy, BoardLotPolicy):
            raise TypeError("board_lot_policy_required")

    def decision_snapshot(self) -> DecisionSnapshot:
        return DecisionSnapshot(
            snapshot_id=self.event_id,
            stable_security_id=self.stable_security_id,
            decision_time=self.decision_time,
            available_time=self.available_time,
            data_version=self.data_version,
            feature_value=self.feature_value,
            mark_price=self.mark_price,
        )
