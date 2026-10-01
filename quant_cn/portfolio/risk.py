"""Deterministic, injected-input risk decisions for the CN offline chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quant_cn.application.market_semantics_preflight import MarketSemanticsPreflight
from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.execution.models import OrderIntent, SAFETY_FLAGS
from quant_cn.market.rules import BoardLotPolicy, QUANTITY_VALID


@dataclass(frozen=True)
class TargetPosition:
    target_id: str
    run_id: str
    stable_security_id: str
    target_quantity: int
    current_quantity: int
    decision_time: datetime
    evidence_hash: str

    def __post_init__(self) -> None:
        for name in ("target_id", "run_id", "stable_security_id", "evidence_hash"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        for name in ("target_quantity", "current_quantity"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"non_negative_integer_required:{name}")
        object.__setattr__(
            self, "decision_time", ensure_aware_timestamp(self.decision_time, "decision_time")
        )


@dataclass(frozen=True)
class RiskInputs:
    preflight: MarketSemanticsPreflight
    board_lot_policy: BoardLotPolicy
    rule_versions: tuple[tuple[str, str], ...]
    limit_price: Decimal
    available_cash: Decimal
    sellable_quantity: int
    estimated_fee: Decimal
    max_order_notional: Decimal
    session_sequence: int
    order_type: str = "limit"
    time_in_force: str = "day"

    def __post_init__(self) -> None:
        if not isinstance(self.preflight, MarketSemanticsPreflight):
            raise TypeError("market_preflight_required")
        if not isinstance(self.board_lot_policy, BoardLotPolicy):
            raise TypeError("board_lot_policy_required")
        for name in ("limit_price", "available_cash", "estimated_fee", "max_order_notional"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"non_negative_decimal_required:{name}")
        if self.limit_price <= 0 or self.max_order_notional <= 0:
            raise ValueError("positive_price_and_limit_required")
        if not isinstance(self.sellable_quantity, int) or self.sellable_quantity < 0:
            raise ValueError("sellable_quantity_invalid")
        if not isinstance(self.session_sequence, int) or self.session_sequence < 0:
            raise ValueError("session_sequence_invalid")
        versions = tuple(sorted(self.rule_versions))
        if not versions:
            raise ValueError("rule_versions_required")
        object.__setattr__(self, "rule_versions", versions)


@dataclass(frozen=True)
class RiskDecision:
    decision_id: str
    target_id: str
    approved: bool
    side: str | None
    quantity: int
    blockers: tuple[str, ...]
    decided_at: datetime
    rule_versions: tuple[tuple[str, str], ...]

    @property
    def safety_flags(self) -> dict[str, bool]:
        return dict(SAFETY_FLAGS)


def evaluate_target(
    target: TargetPosition,
    inputs: RiskInputs,
    *,
    decision_id: str,
) -> RiskDecision:
    """Fail closed unless all market, sizing, cash, and sellability checks pass."""

    require_non_empty(decision_id, "decision_id")
    delta = target.target_quantity - target.current_quantity
    side = "buy" if delta > 0 else "sell" if delta < 0 else None
    quantity = abs(delta)
    blockers = list(inputs.preflight.blockers)
    if side is None:
        blockers.append("zero_target_delta")
    else:
        quantity_status = inputs.board_lot_policy.validate_quantity(
            side=side,
            quantity=quantity,
            current_position=target.current_quantity,
        )
        if quantity_status != QUANTITY_VALID:
            blockers.append(quantity_status)
        notional = inputs.limit_price * quantity
        if notional > inputs.max_order_notional:
            blockers.append("max_order_notional_exceeded")
        if side == "buy" and notional + inputs.estimated_fee > inputs.available_cash:
            blockers.append("cash_insufficient")
        if side == "sell" and quantity > inputs.sellable_quantity:
            blockers.append("t_plus_one_sellability_blocked")
    canonical = tuple(sorted(set(blockers)))
    return RiskDecision(
        decision_id=decision_id,
        target_id=target.target_id,
        approved=not canonical,
        side=side,
        quantity=quantity,
        blockers=canonical,
        decided_at=target.decision_time,
        rule_versions=inputs.rule_versions,
    )


def build_order_intent(
    target: TargetPosition,
    decision: RiskDecision,
    inputs: RiskInputs,
    *,
    order_id: str,
    client_order_id: str,
    created_at: datetime,
) -> OrderIntent:
    if not decision.approved or decision.side is None:
        raise ValueError("risk_decision_not_approved")
    if decision.target_id != target.target_id:
        raise ValueError("risk_decision_target_mismatch")
    return OrderIntent(
        order_id=order_id,
        client_order_id=client_order_id,
        risk_decision_id=decision.decision_id,
        target_id=target.target_id,
        run_id=target.run_id,
        stable_security_id=target.stable_security_id,
        side=decision.side,
        quantity=decision.quantity,
        limit_price=inputs.limit_price,
        order_type=inputs.order_type,
        time_in_force=inputs.time_in_force,
        decision_time=target.decision_time,
        created_at=created_at,
        session_sequence=inputs.session_sequence,
        rule_versions=inputs.rule_versions,
        evidence_hash=target.evidence_hash,
    )
