"""Pure CN strategy contracts shared by research and offline backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.execution.models import SAFETY_FLAGS


DIRECTIONS = frozenset({"long", "flat"})


def _finite_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"decimal_required:{field_name}")
    if not value.is_finite():
        raise ValueError(f"finite_decimal_required:{field_name}")
    return value


@dataclass(frozen=True)
class DecisionSnapshot:
    snapshot_id: str
    stable_security_id: str
    decision_time: datetime
    available_time: datetime
    data_version: str
    feature_value: Decimal
    mark_price: Decimal

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "stable_security_id", "data_version"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        decision = ensure_aware_timestamp(self.decision_time, "decision_time")
        available = ensure_aware_timestamp(self.available_time, "available_time")
        if available > decision:
            raise ValueError("snapshot_not_visible_at_decision")
        object.__setattr__(self, "decision_time", decision)
        object.__setattr__(self, "available_time", available)
        _finite_decimal(self.feature_value, "feature_value")
        if _finite_decimal(self.mark_price, "mark_price") <= 0:
            raise ValueError("mark_price_must_be_positive")


@dataclass(frozen=True)
class Signal:
    signal_id: str
    strategy_id: str
    stable_security_id: str
    decision_time: datetime
    direction: str
    strength: Decimal
    horizon_sessions: int
    snapshot_id: str

    def __post_init__(self) -> None:
        for name in ("signal_id", "strategy_id", "stable_security_id", "snapshot_id"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(
            self, "decision_time", ensure_aware_timestamp(self.decision_time, "decision_time")
        )
        direction = require_non_empty(self.direction, "direction").lower()
        if direction not in DIRECTIONS:
            raise ValueError("signal_direction_unknown")
        object.__setattr__(self, "direction", direction)
        strength = _finite_decimal(self.strength, "strength")
        if strength < 0 or strength > 1:
            raise ValueError("signal_strength_out_of_range")
        if not isinstance(self.horizon_sessions, int) or self.horizon_sessions <= 0:
            raise ValueError("horizon_sessions_must_be_positive")

    @property
    def safety_flags(self) -> dict[str, bool]:
        return dict(SAFETY_FLAGS)


@dataclass(frozen=True)
class Forecast:
    forecast_id: str
    signal_id: str
    strategy_id: str
    stable_security_id: str
    decision_time: datetime
    expected_return: Decimal
    confidence: Decimal
    horizon_sessions: int
    model_version: str

    def __post_init__(self) -> None:
        for name in (
            "forecast_id",
            "signal_id",
            "strategy_id",
            "stable_security_id",
            "model_version",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(
            self, "decision_time", ensure_aware_timestamp(self.decision_time, "decision_time")
        )
        _finite_decimal(self.expected_return, "expected_return")
        confidence = _finite_decimal(self.confidence, "confidence")
        if confidence < 0 or confidence > 1:
            raise ValueError("forecast_confidence_out_of_range")
        if not isinstance(self.horizon_sessions, int) or self.horizon_sessions <= 0:
            raise ValueError("horizon_sessions_must_be_positive")


@dataclass(frozen=True)
class TargetPosition:
    target_id: str
    forecast_id: str
    signal_id: str
    strategy_id: str
    stable_security_id: str
    decision_time: datetime
    target_quantity: int
    forecast_confidence: Decimal
    capacity_quantity: int
    sizing_reason: str

    def __post_init__(self) -> None:
        for name in (
            "target_id",
            "forecast_id",
            "signal_id",
            "strategy_id",
            "stable_security_id",
            "sizing_reason",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(
            self, "decision_time", ensure_aware_timestamp(self.decision_time, "decision_time")
        )
        for name in ("target_quantity", "capacity_quantity"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"non_negative_integer_required:{name}")
        if self.target_quantity > self.capacity_quantity:
            raise ValueError("target_exceeds_capacity")
        confidence = _finite_decimal(self.forecast_confidence, "forecast_confidence")
        if confidence < 0 or confidence > 1:
            raise ValueError("target_confidence_out_of_range")


@dataclass(frozen=True)
class DecisionChain:
    snapshot: DecisionSnapshot
    signal: Signal
    forecast: Forecast
    target: TargetPosition

    def __post_init__(self) -> None:
        blockers = validate_decision_chain(self)
        if blockers:
            raise ValueError("decision_chain_invalid:" + ",".join(blockers))


def validate_decision_chain(chain: DecisionChain) -> tuple[str, ...]:
    blockers: list[str] = []
    times = {
        chain.snapshot.decision_time,
        chain.signal.decision_time,
        chain.forecast.decision_time,
        chain.target.decision_time,
    }
    if len(times) != 1:
        blockers.append("decision_time_mismatch")
    securities = {
        chain.snapshot.stable_security_id,
        chain.signal.stable_security_id,
        chain.forecast.stable_security_id,
        chain.target.stable_security_id,
    }
    if len(securities) != 1:
        blockers.append("security_identity_mismatch")
    strategies = {
        chain.signal.strategy_id,
        chain.forecast.strategy_id,
        chain.target.strategy_id,
    }
    if len(strategies) != 1:
        blockers.append("strategy_identity_mismatch")
    if chain.forecast.signal_id != chain.signal.signal_id:
        blockers.append("forecast_signal_link_mismatch")
    if chain.target.signal_id != chain.signal.signal_id:
        blockers.append("target_signal_link_mismatch")
    if chain.target.forecast_id != chain.forecast.forecast_id:
        blockers.append("target_forecast_link_mismatch")
    if chain.signal.snapshot_id != chain.snapshot.snapshot_id:
        blockers.append("signal_snapshot_link_mismatch")
    return tuple(sorted(set(blockers)))


class Strategy(Protocol):
    strategy_id: str
    strategy_version: str

    def generate_signal(self, snapshot: DecisionSnapshot) -> Signal: ...


class ForecastModel(Protocol):
    model_version: str

    def forecast(self, signal: Signal, snapshot: DecisionSnapshot) -> Forecast: ...


class TargetBuilder(Protocol):
    def build_target(
        self,
        forecast: Forecast,
        snapshot: DecisionSnapshot,
        *,
        current_quantity: int,
        capacity_quantity: int,
    ) -> TargetPosition: ...
