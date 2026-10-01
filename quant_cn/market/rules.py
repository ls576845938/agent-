"""Effective-dated China-market rule contracts and deterministic resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Iterable

from quant_cn.data.contracts import (
    ensure_aware_timestamp,
    ensure_sha256_checksum,
    require_non_empty,
)


PRICE_LIMIT = "price_limit"
BOARD_LOT = "board_lot"
SELLABILITY = "sellability"
FEE_SCHEDULE = "fee_schedule"
TICK_SIZE = "tick_size"
ORDER_CONSTRAINTS = "order_constraints"
SETTLEMENT = "settlement"

RULE_KINDS = (PRICE_LIMIT, BOARD_LOT, SELLABILITY, FEE_SCHEDULE)
MARKET_SEMANTICS_RULE_KINDS = RULE_KINDS + (
    TICK_SIZE,
    ORDER_CONSTRAINTS,
    SETTLEMENT,
)

RULE_RESOLVED = "resolved"
RULE_MISSING = "missing"
RULE_NOT_AVAILABLE = "not_available"
RULE_NOT_YET_EFFECTIVE = "not_yet_effective"
RULE_EXPIRED = "expired"
RULE_OVERLAP = "overlap"
RULE_AMBIGUOUS = "ambiguous"
RULE_UNKNOWN = "unknown"

UNKNOWN_DIMENSION_TOKENS = frozenset({"unknown", "unset", "n/a", "na", "none"})
_ROUNDING_MODES = {
    "ceiling": ROUND_CEILING,
    "down": ROUND_DOWN,
    "floor": ROUND_FLOOR,
    "half_up": ROUND_HALF_UP,
}

PRICE_REQUIRED = "required"
PRICE_FORBIDDEN = "forbidden"
PRICE_OPTIONAL = "optional"
PRICE_REQUIREMENTS = frozenset({PRICE_REQUIRED, PRICE_FORBIDDEN, PRICE_OPTIONAL})

ODD_LOT_FORBIDDEN = "forbidden"
ODD_LOT_ANY = "any"
ODD_LOT_FULL_REMAINDER_ONLY = "full_remainder_only"
ODD_LOT_MODES = frozenset(
    {ODD_LOT_FORBIDDEN, ODD_LOT_ANY, ODD_LOT_FULL_REMAINDER_ONLY}
)
QUANTITY_VALID = "valid"
BUY_LOT_INVALID = "buy_lot_invalid"
SELL_LOT_INVALID = "sell_lot_invalid"
ODD_LOT_SELL_REQUIRES_FULL_REMAINDER = "odd_lot_sell_requires_full_remainder"
ODD_LOT_SELL_MODE_MISSING = "odd_lot_sell_mode_missing"


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"decimal_required:{field_name}")
    if not value.is_finite():
        raise ValueError(f"finite_decimal_required:{field_name}")
    return value


def _non_negative_integer(value: int, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"non_negative_integer_required:{field_name}")
    return value


@dataclass(frozen=True)
class MarketDimensions:
    venue: str
    board: str
    instrument: str
    security_type: str
    security_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("venue", "board", "instrument", "security_type"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        if self.security_id is not None:
            object.__setattr__(
                self,
                "security_id",
                require_non_empty(self.security_id, "security_id"),
            )

    def matches(self, requested: "MarketDimensions") -> bool:
        return (
            self.venue == requested.venue
            and self.board == requested.board
            and self.instrument == requested.instrument
            and self.security_type == requested.security_type
            and (self.security_id is None or self.security_id == requested.security_id)
        )

    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(
            field_name
            for field_name in ("venue", "board", "instrument", "security_type")
            if getattr(self, field_name).lower() in UNKNOWN_DIMENSION_TOKENS
        )


@dataclass(frozen=True)
class PriceLimitPolicy:
    has_price_limit: bool
    upper_ratio: Decimal | None
    lower_ratio: Decimal | None
    upper_rounding_mode: str | None = None
    lower_rounding_mode: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.has_price_limit, bool):
            raise TypeError("price_limit_flag_must_be_bool")
        if self.has_price_limit:
            if self.upper_ratio is None or self.lower_ratio is None:
                raise ValueError("price_limit_ratios_required")
            upper = _decimal(self.upper_ratio, "upper_ratio")
            lower = _decimal(self.lower_ratio, "lower_ratio")
            if upper < Decimal("0") or lower < Decimal("0"):
                raise ValueError("price_limit_ratio_must_be_non_negative")
            if lower >= Decimal("1"):
                raise ValueError("price_limit_lower_ratio_must_be_below_one")
            if (self.upper_rounding_mode is None) != (
                self.lower_rounding_mode is None
            ):
                raise ValueError("price_limit_rounding_policy_incomplete")
            for field_name in ("upper_rounding_mode", "lower_rounding_mode"):
                mode = getattr(self, field_name)
                if mode is not None:
                    normalized = require_non_empty(mode, field_name).lower()
                    if normalized not in _ROUNDING_MODES:
                        raise ValueError("price_limit_rounding_mode_unknown")
                    object.__setattr__(self, field_name, normalized)
        elif any(
            value is not None
            for value in (
                self.upper_ratio,
                self.lower_ratio,
                self.upper_rounding_mode,
                self.lower_rounding_mode,
            )
        ):
            raise ValueError("price_limit_terms_must_be_none_when_disabled")

    @property
    def has_explicit_rounding(self) -> bool:
        return (
            self.upper_rounding_mode is not None
            and self.lower_rounding_mode is not None
        )

    def expected_band(
        self,
        *,
        reference_price: Decimal,
        tick_size: Decimal,
    ) -> tuple[Decimal, Decimal]:
        if not self.has_price_limit:
            raise ValueError("price_limit_disabled")
        if not self.has_explicit_rounding:
            raise ValueError("price_limit_rounding_policy_missing")
        reference = _decimal(reference_price, "reference_price")
        tick = _decimal(tick_size, "tick_size")
        if reference <= Decimal("0"):
            raise ValueError("price_limit_reference_price_must_be_positive")
        if tick <= Decimal("0"):
            raise ValueError("price_limit_tick_size_must_be_positive")
        if self.upper_ratio is None or self.lower_ratio is None:
            raise AssertionError("validated_price_limit_missing_ratios")
        lower_raw = reference * (Decimal("1") - self.lower_ratio)
        upper_raw = reference * (Decimal("1") + self.upper_ratio)
        lower = (
            (lower_raw / tick).quantize(
                Decimal("1"),
                rounding=_ROUNDING_MODES[self.lower_rounding_mode],
            )
            * tick
        )
        upper = (
            (upper_raw / tick).quantize(
                Decimal("1"),
                rounding=_ROUNDING_MODES[self.upper_rounding_mode],
            )
            * tick
        )
        if lower <= Decimal("0") or upper <= lower:
            raise ValueError("price_limit_derived_band_invalid")
        return lower, upper


@dataclass(frozen=True)
class BoardLotPolicy:
    buy_lot_size: int
    sell_lot_size: int
    odd_lot_sell_allowed: bool
    odd_lot_sell_mode: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("buy_lot_size", "sell_lot_size"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"positive_integer_required:{field_name}")
        if not isinstance(self.odd_lot_sell_allowed, bool):
            raise TypeError("odd_lot_sell_allowed_must_be_bool")
        if self.odd_lot_sell_mode is None:
            return
        mode = require_non_empty(
            self.odd_lot_sell_mode,
            "odd_lot_sell_mode",
        ).lower()
        if mode not in ODD_LOT_MODES:
            raise ValueError("odd_lot_sell_mode_unknown")
        if self.odd_lot_sell_allowed != (mode != ODD_LOT_FORBIDDEN):
            raise ValueError("odd_lot_sell_mode_conflicts_with_flag")
        object.__setattr__(self, "odd_lot_sell_mode", mode)

    def validate_quantity(
        self,
        *,
        side: str,
        quantity: int,
        current_position: int | None = None,
    ) -> str:
        normalized_side = require_non_empty(side, "side").lower()
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
            raise ValueError("quantity_must_be_positive_integer")
        if normalized_side == "buy":
            return (
                QUANTITY_VALID
                if quantity % self.buy_lot_size == 0
                else BUY_LOT_INVALID
            )
        if normalized_side != "sell":
            raise ValueError("side_unknown")
        if quantity % self.sell_lot_size == 0:
            return QUANTITY_VALID
        if self.odd_lot_sell_mode is None:
            return ODD_LOT_SELL_MODE_MISSING
        if self.odd_lot_sell_mode == ODD_LOT_ANY:
            return QUANTITY_VALID
        if self.odd_lot_sell_mode == ODD_LOT_FORBIDDEN:
            return SELL_LOT_INVALID
        if (
            current_position is None
            or not isinstance(current_position, int)
            or isinstance(current_position, bool)
            or current_position < quantity
        ):
            return ODD_LOT_SELL_REQUIRES_FULL_REMAINDER
        return (
            QUANTITY_VALID
            if quantity == current_position
            else ODD_LOT_SELL_REQUIRES_FULL_REMAINDER
        )


@dataclass(frozen=True)
class SellabilityPolicy:
    sellable_after_sessions: int

    def __post_init__(self) -> None:
        value = self.sellable_after_sessions
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("sellable_after_sessions_must_be_non_negative_integer")


@dataclass(frozen=True)
class FeeComponent:
    name: str
    rate: Decimal
    minimum_amount: Decimal
    fixed_amount: Decimal
    rounding_quantum: Decimal | None = None
    rounding_mode: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "fee.name"))
        for field_name in ("rate", "minimum_amount", "fixed_amount"):
            value = _decimal(getattr(self, field_name), field_name)
            if value < Decimal("0"):
                raise ValueError(f"fee_value_must_be_non_negative:{field_name}")
        if (self.rounding_quantum is None) != (self.rounding_mode is None):
            raise ValueError("fee_rounding_policy_incomplete")
        if self.rounding_quantum is not None:
            quantum = _decimal(self.rounding_quantum, "rounding_quantum")
            if quantum <= Decimal("0"):
                raise ValueError("fee_rounding_quantum_must_be_positive")
            mode = require_non_empty(self.rounding_mode, "rounding_mode").lower()
            if mode not in _ROUNDING_MODES:
                raise ValueError("fee_rounding_mode_unknown")
            object.__setattr__(self, "rounding_mode", mode)

    def charge(self, notional: Decimal) -> Decimal:
        amount = _decimal(notional, "notional")
        if amount < Decimal("0"):
            raise ValueError("fee_notional_must_be_non_negative")
        if self.rounding_quantum is None or self.rounding_mode is None:
            raise ValueError("fee_rounding_policy_missing")
        charge = max(self.rate * amount, self.minimum_amount) + self.fixed_amount
        units = (charge / self.rounding_quantum).quantize(
            Decimal("1"),
            rounding=_ROUNDING_MODES[self.rounding_mode],
        )
        return units * self.rounding_quantum


@dataclass(frozen=True)
class FeePolicy:
    buy: tuple[FeeComponent, ...]
    sell: tuple[FeeComponent, ...]

    def __post_init__(self) -> None:
        buy = tuple(self.buy)
        sell = tuple(self.sell)
        if any(not isinstance(item, FeeComponent) for item in buy + sell):
            raise TypeError("fee_component_type_invalid")
        if not buy:
            raise ValueError("fee_policy_buy_must_be_non_empty")
        if not sell:
            raise ValueError("fee_policy_sell_must_be_non_empty")
        for side, components in (("buy", buy), ("sell", sell)):
            names = tuple(component.name for component in components)
            if len(names) != len(set(names)):
                raise ValueError(f"fee_component_name_duplicate:{side}")
        object.__setattr__(self, "buy", tuple(sorted(buy, key=lambda item: item.name)))
        object.__setattr__(self, "sell", tuple(sorted(sell, key=lambda item: item.name)))

    def components_for(self, side: str) -> tuple[FeeComponent, ...]:
        normalized = require_non_empty(side, "side").lower()
        if normalized == "buy":
            return self.buy
        if normalized == "sell":
            return self.sell
        raise ValueError("fee_side_unknown")

    def charges_for(
        self,
        *,
        side: str,
        notional: Decimal,
    ) -> tuple[tuple[str, Decimal], ...]:
        return tuple(
            (component.name, component.charge(notional))
            for component in self.components_for(side)
        )

    def total_charge(self, *, side: str, notional: Decimal) -> Decimal:
        return sum(
            (amount for _, amount in self.charges_for(side=side, notional=notional)),
            Decimal("0"),
        )


@dataclass(frozen=True)
class TickSizePolicy:
    tick_size: Decimal

    def __post_init__(self) -> None:
        tick = _decimal(self.tick_size, "tick_size")
        if tick <= Decimal("0"):
            raise ValueError("tick_size_must_be_positive")

    def is_aligned(self, price: Decimal) -> bool:
        candidate = _decimal(price, "price")
        return candidate > Decimal("0") and candidate % self.tick_size == Decimal("0")


@dataclass(frozen=True)
class AllowedOrderInstruction:
    order_type: str
    time_in_force: str
    price_requirement: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "order_type",
            require_non_empty(self.order_type, "order_type").lower(),
        )
        object.__setattr__(
            self,
            "time_in_force",
            require_non_empty(self.time_in_force, "time_in_force").lower(),
        )
        requirement = require_non_empty(
            self.price_requirement,
            "price_requirement",
        ).lower()
        if requirement not in PRICE_REQUIREMENTS:
            raise ValueError("order_price_requirement_unknown")
        object.__setattr__(self, "price_requirement", requirement)


@dataclass(frozen=True)
class PhaseOrderConstraint:
    phase: str
    instructions: tuple[AllowedOrderInstruction, ...]

    def __post_init__(self) -> None:
        phase = require_non_empty(self.phase, "phase").lower()
        instructions = tuple(self.instructions)
        if not instructions:
            raise ValueError("phase_order_instructions_must_be_non_empty")
        if any(not isinstance(item, AllowedOrderInstruction) for item in instructions):
            raise TypeError("allowed_order_instruction_type_invalid")
        identities = tuple(
            (item.order_type, item.time_in_force) for item in instructions
        )
        if len(identities) != len(set(identities)):
            raise ValueError("allowed_order_instruction_duplicate")
        object.__setattr__(self, "phase", phase)
        object.__setattr__(
            self,
            "instructions",
            tuple(
                sorted(
                    instructions,
                    key=lambda item: (item.order_type, item.time_in_force),
                )
            ),
        )

    def resolve(
        self,
        *,
        order_type: str,
        time_in_force: str,
    ) -> AllowedOrderInstruction | None:
        requested_type = require_non_empty(order_type, "order_type").lower()
        requested_tif = require_non_empty(time_in_force, "time_in_force").lower()
        return next(
            (
                item
                for item in self.instructions
                if item.order_type == requested_type
                and item.time_in_force == requested_tif
            ),
            None,
        )


@dataclass(frozen=True)
class OrderConstraintPolicy:
    phases: tuple[PhaseOrderConstraint, ...]

    def __post_init__(self) -> None:
        phases = tuple(self.phases)
        if not phases:
            raise ValueError("order_constraint_phases_must_be_non_empty")
        if any(not isinstance(item, PhaseOrderConstraint) for item in phases):
            raise TypeError("phase_order_constraint_type_invalid")
        names = tuple(item.phase for item in phases)
        if len(names) != len(set(names)):
            raise ValueError("phase_order_constraint_duplicate")
        object.__setattr__(
            self,
            "phases",
            tuple(sorted(phases, key=lambda item: item.phase)),
        )

    def for_phase(self, phase: str) -> PhaseOrderConstraint | None:
        normalized = require_non_empty(phase, "phase").lower()
        return next((item for item in self.phases if item.phase == normalized), None)


@dataclass(frozen=True)
class SettlementPolicy:
    position_settlement_sessions: int
    cash_settlement_sessions: int
    same_day_sell_allowed: bool

    def __post_init__(self) -> None:
        _non_negative_integer(
            self.position_settlement_sessions,
            "position_settlement_sessions",
        )
        _non_negative_integer(
            self.cash_settlement_sessions,
            "cash_settlement_sessions",
        )
        if not isinstance(self.same_day_sell_allowed, bool):
            raise TypeError("same_day_sell_allowed_must_be_bool")
        if self.same_day_sell_allowed != (self.position_settlement_sessions == 0):
            raise ValueError("settlement_same_day_sell_policy_inconsistent")


RulePayload = (
    PriceLimitPolicy
    | BoardLotPolicy
    | SellabilityPolicy
    | FeePolicy
    | TickSizePolicy
    | OrderConstraintPolicy
    | SettlementPolicy
)


@dataclass(frozen=True)
class EffectiveRule:
    rule_kind: str
    rule_version: str
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    dimensions: MarketDimensions
    payload: RulePayload
    source: str
    checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "rule_kind",
            require_non_empty(self.rule_kind, "rule_kind"),
        )
        object.__setattr__(
            self,
            "rule_version",
            require_non_empty(self.rule_version, "rule_version"),
        )
        object.__setattr__(self, "source", require_non_empty(self.source, "source"))
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "rule.checksum"),
        )

        start = ensure_aware_timestamp(self.effective_from, "effective_from")
        end = (
            ensure_aware_timestamp(self.effective_to, "effective_to")
            if self.effective_to is not None
            else None
        )
        available = ensure_aware_timestamp(self.available_time, "rule.available_time")
        ingested = ensure_aware_timestamp(self.ingested_at, "rule.ingested_at")
        processed = ensure_aware_timestamp(self.processed_at, "rule.processed_at")
        if end is not None and end <= start:
            raise ValueError("rule_effective_interval_invalid")
        if available > ingested:
            raise ValueError("rule_available_time_after_ingested_at")
        if ingested > processed:
            raise ValueError("rule_ingested_at_after_processed_at")
        if not isinstance(self.dimensions, MarketDimensions):
            raise TypeError("market_dimensions_type_invalid")

        expected_payload = {
            PRICE_LIMIT: PriceLimitPolicy,
            BOARD_LOT: BoardLotPolicy,
            SELLABILITY: SellabilityPolicy,
            FEE_SCHEDULE: FeePolicy,
            TICK_SIZE: TickSizePolicy,
            ORDER_CONSTRAINTS: OrderConstraintPolicy,
            SETTLEMENT: SettlementPolicy,
        }.get(self.rule_kind)
        if expected_payload is None:
            raise ValueError("rule_kind_unknown")
        if not isinstance(self.payload, expected_payload):
            raise TypeError(f"rule_payload_type_invalid:{self.rule_kind}")

        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_to", end)
        object.__setattr__(self, "available_time", available)
        object.__setattr__(self, "ingested_at", ingested)
        object.__setattr__(self, "processed_at", processed)

    def is_effective(self, as_of: datetime) -> bool:
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        return self.effective_from <= timestamp and (
            self.effective_to is None or timestamp < self.effective_to
        )


@dataclass(frozen=True)
class RuleResolution:
    rule_kind: str
    status: str
    versions: tuple[str, ...] = ()
    rule: EffectiveRule | None = None


class EffectiveRuleBook:
    """Resolve explicit rules without security or market-level defaults."""

    def __init__(self, rules: Iterable[EffectiveRule]) -> None:
        self._rules = tuple(rules)
        if any(not isinstance(rule, EffectiveRule) for rule in self._rules):
            raise TypeError("effective_rule_type_invalid")

    @property
    def rules(self) -> tuple[EffectiveRule, ...]:
        return self._rules

    def resolve(
        self,
        rule_kind: str,
        *,
        dimensions: MarketDimensions,
        as_of: datetime,
    ) -> RuleResolution:
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        if rule_kind not in MARKET_SEMANTICS_RULE_KINDS:
            return RuleResolution(rule_kind, RULE_UNKNOWN)

        candidates = tuple(
            rule
            for rule in self._rules
            if rule.rule_kind == rule_kind and rule.dimensions.matches(dimensions)
        )
        if not candidates:
            return RuleResolution(rule_kind, RULE_MISSING)

        visible = tuple(rule for rule in candidates if rule.available_time <= timestamp)
        if not visible:
            return RuleResolution(rule_kind, RULE_NOT_AVAILABLE)

        active = tuple(rule for rule in visible if rule.is_effective(timestamp))
        visible_versions = tuple(sorted({rule.rule_version for rule in visible}))
        if not active:
            if any(
                rule.available_time > timestamp and rule.is_effective(timestamp)
                for rule in candidates
            ):
                return RuleResolution(rule_kind, RULE_NOT_AVAILABLE)
            if all(
                rule.effective_to is not None and rule.effective_to <= timestamp
                for rule in visible
            ):
                status = RULE_EXPIRED
            elif all(rule.effective_from > timestamp for rule in visible):
                status = RULE_NOT_YET_EFFECTIVE
            else:
                status = RULE_MISSING
            return RuleResolution(rule_kind, status, visible_versions)

        grouped: dict[MarketDimensions, list[EffectiveRule]] = {}
        for rule in active:
            grouped.setdefault(rule.dimensions, []).append(rule)
        active_versions = tuple(sorted({rule.rule_version for rule in active}))
        if any(len(group) > 1 for group in grouped.values()):
            return RuleResolution(rule_kind, RULE_OVERLAP, active_versions)
        if len(active) > 1:
            return RuleResolution(rule_kind, RULE_AMBIGUOUS, active_versions)
        return RuleResolution(
            rule_kind,
            RULE_RESOLVED,
            (active[0].rule_version,),
            active[0],
        )
