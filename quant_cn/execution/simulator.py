"""Deterministic offline fill simulator with explicit CN market constraints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quant_cn.application.market_semantics_preflight import MarketSemanticsPreflight
from quant_cn.data.contracts import ensure_aware_timestamp, require_non_empty
from quant_cn.execution.models import Fill, OrderIntent
from quant_cn.market.rules import BoardLotPolicy, FeePolicy, QUANTITY_VALID


@dataclass(frozen=True)
class SimulationSnapshot:
    snapshot_id: str
    as_of: datetime
    phase: str
    accepts_orders: bool
    suspended: bool
    lower_limit_price: Decimal
    upper_limit_price: Decimal
    tick_size: Decimal
    available_liquidity: int
    available_cash: Decimal
    current_position: int
    sellable_quantity: int
    execution_price: Decimal
    rule_source_versions: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", require_non_empty(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "phase", require_non_empty(self.phase, "phase").lower())
        object.__setattr__(self, "as_of", ensure_aware_timestamp(self.as_of, "as_of"))
        if not isinstance(self.accepts_orders, bool) or not isinstance(self.suspended, bool):
            raise TypeError("market_flags_must_be_bool")
        for name in (
            "lower_limit_price",
            "upper_limit_price",
            "tick_size",
            "available_cash",
            "execution_price",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
                raise ValueError(f"non_negative_decimal_required:{name}")
        if (
            self.lower_limit_price <= 0
            or self.upper_limit_price < self.lower_limit_price
            or self.tick_size <= 0
            or self.execution_price <= 0
        ):
            raise ValueError("invalid_price_snapshot")
        for name in ("available_liquidity", "current_position", "sellable_quantity"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"non_negative_integer_required:{name}")
        versions = tuple(sorted(self.rule_source_versions))
        if not versions:
            raise ValueError("rule_source_versions_required")
        object.__setattr__(self, "rule_source_versions", versions)


@dataclass(frozen=True)
class SimulationResult:
    status: str
    fills: tuple[Fill, ...]
    blockers: tuple[str, ...]


def simulate(
    intent: OrderIntent,
    *,
    preflight: MarketSemanticsPreflight,
    snapshot: SimulationSnapshot,
    board_lot_policy: BoardLotPolicy,
    fee_policy: FeePolicy,
    fill_id: str,
    received_at: datetime,
) -> SimulationResult:
    """Simulate at most one fill from explicitly injected, versioned state."""

    blockers = list(preflight.blockers)
    if snapshot.as_of < intent.created_at:
        blockers.append("snapshot_before_order")
    if snapshot.suspended:
        blockers.append("security_suspended")
    if not snapshot.accepts_orders:
        blockers.append("session_not_accepting_orders")
    if snapshot.phase not in {"opening_auction", "continuous", "closing_auction"}:
        blockers.append("session_phase_unknown")
    if intent.limit_price % snapshot.tick_size != 0:
        blockers.append("price_tick_misaligned")
    if intent.limit_price < snapshot.lower_limit_price:
        blockers.append("price_below_limit")
    if intent.limit_price > snapshot.upper_limit_price:
        blockers.append("price_above_limit")
    quantity_status = board_lot_policy.validate_quantity(
        side=intent.side,
        quantity=intent.quantity,
        current_position=snapshot.current_position,
    )
    if quantity_status != QUANTITY_VALID:
        blockers.append(quantity_status)
    if intent.side == "sell" and intent.quantity > snapshot.sellable_quantity:
        blockers.append("t_plus_one_sellability_blocked")

    executable = min(intent.quantity, snapshot.available_liquidity)
    if intent.time_in_force == "fok" and executable != intent.quantity:
        blockers.append("fok_not_fully_fillable")
    if executable == 0:
        blockers.append("liquidity_unavailable")
    notional = snapshot.execution_price * executable
    fees = fee_policy.charges_for(side=intent.side, notional=notional) if executable else ()
    if intent.side == "buy" and notional + sum(
        (amount for _, amount in fees), Decimal("0")
    ) > snapshot.available_cash:
        blockers.append("cash_insufficient")
    canonical = tuple(sorted(set(blockers)))
    if canonical:
        return SimulationResult("rejected", (), canonical)
    fill = Fill(
        fill_id=fill_id,
        order_id=intent.order_id,
        stable_security_id=intent.stable_security_id,
        side=intent.side,
        quantity=executable,
        price=snapshot.execution_price,
        fee_components=fees,
        occurred_at=snapshot.as_of,
        received_at=received_at,
        session_sequence=intent.session_sequence,
    )
    status = "filled" if executable == intent.quantity else "partially_filled"
    return SimulationResult(status, (fill,), ())
