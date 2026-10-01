"""PIT price-band evidence and fail-closed order-price validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quant_cn.data.contracts import (
    ensure_aware_timestamp,
    ensure_sha256_checksum,
    require_non_empty,
)
from quant_cn.market.rules import PriceLimitPolicy, TickSizePolicy


PRICE_VALID = "valid"
PRICE_SNAPSHOT_NOT_AVAILABLE = "market_snapshot_not_available"
PRICE_SNAPSHOT_NOT_EFFECTIVE = "market_snapshot_not_effective"
PRICE_SECURITY_MISMATCH = "market_snapshot_security_mismatch"
PRICE_CALENDAR_VERSION_MISMATCH = "calendar_version_mismatch"
PRICE_LIMIT_RULE_VERSION_MISMATCH = "price_limit_rule_version_mismatch"
TICK_RULE_VERSION_MISMATCH = "tick_size_rule_version_mismatch"
PRICE_LIMIT_POLICY_MISMATCH = "price_limit_policy_mismatch"
PRICE_TICK_MISALIGNED = "price_tick_misaligned"
PRICE_BELOW_LIMIT = "price_below_lower_limit"
PRICE_ABOVE_LIMIT = "price_above_upper_limit"
BUY_BLOCKED_AT_UPPER_LOCK = "buy_blocked_at_upper_lock"
SELL_BLOCKED_AT_LOWER_LOCK = "sell_blocked_at_lower_lock"


def _positive_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"decimal_required:{field_name}")
    if not value.is_finite() or value <= Decimal("0"):
        raise ValueError(f"positive_decimal_required:{field_name}")
    return value


@dataclass(frozen=True)
class PITPriceBandSnapshot:
    stable_security_id: str
    session_id: str
    calendar_version: str
    reference_price: Decimal
    last_price: Decimal
    lower_limit_price: Decimal | None
    upper_limit_price: Decimal | None
    lower_locked: bool
    upper_locked: bool
    price_limit_rule_version: str
    tick_size_rule_version: str
    valid_from: datetime
    valid_to: datetime
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    source: str
    version: str
    checksum: str

    def __post_init__(self) -> None:
        for field_name in (
            "stable_security_id",
            "session_id",
            "calendar_version",
            "price_limit_rule_version",
            "tick_size_rule_version",
            "source",
            "version",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "reference_price",
            _positive_decimal(self.reference_price, "reference_price"),
        )
        object.__setattr__(
            self,
            "last_price",
            _positive_decimal(self.last_price, "last_price"),
        )
        if (self.lower_limit_price is None) != (self.upper_limit_price is None):
            raise ValueError("price_band_bounds_incomplete")
        if self.lower_limit_price is not None and self.upper_limit_price is not None:
            lower = _positive_decimal(self.lower_limit_price, "lower_limit_price")
            upper = _positive_decimal(self.upper_limit_price, "upper_limit_price")
            if lower >= upper:
                raise ValueError("price_band_interval_invalid")
            if not lower <= self.last_price <= upper:
                raise ValueError("last_price_outside_price_band")
        if not isinstance(self.lower_locked, bool) or not isinstance(
            self.upper_locked,
            bool,
        ):
            raise TypeError("price_band_lock_flags_must_be_bool")
        if self.lower_locked and self.upper_locked:
            raise ValueError("price_band_cannot_lock_both_sides")
        if (self.lower_locked or self.upper_locked) and self.lower_limit_price is None:
            raise ValueError("price_band_lock_requires_bounds")
        for field_name in (
            "valid_from",
            "valid_to",
            "event_time",
            "available_time",
            "ingested_at",
            "processed_at",
        ):
            object.__setattr__(
                self,
                field_name,
                ensure_aware_timestamp(
                    getattr(self, field_name),
                    f"price_band.{field_name}",
                ),
            )
        if self.valid_to <= self.valid_from:
            raise ValueError("price_band_valid_interval_invalid")
        if self.event_time > self.available_time:
            raise ValueError("price_band_event_time_after_available_time")
        if self.available_time > self.ingested_at:
            raise ValueError("price_band_available_time_after_ingested_at")
        if self.ingested_at > self.processed_at:
            raise ValueError("price_band_ingested_at_after_processed_at")
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "price_band.checksum"),
        )

    def is_available(self, as_of: datetime) -> bool:
        return self.available_time <= ensure_aware_timestamp(as_of, "as_of")

    def is_effective(self, as_of: datetime) -> bool:
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        return self.valid_from <= timestamp < self.valid_to

    def validate_price(
        self,
        *,
        side: str,
        price: Decimal,
        as_of: datetime,
        stable_security_id: str,
        calendar_version: str,
        price_limit_rule_version: str,
        tick_size_rule_version: str,
        price_limit_policy: PriceLimitPolicy,
        tick_size_policy: TickSizePolicy,
    ) -> tuple[str, ...]:
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        normalized_side = require_non_empty(side, "side").lower()
        candidate = _positive_decimal(price, "price")
        if normalized_side not in {"buy", "sell"}:
            raise ValueError("side_unknown")
        blockers: list[str] = []
        if not self.is_available(timestamp):
            blockers.append(PRICE_SNAPSHOT_NOT_AVAILABLE)
        if not self.is_effective(timestamp):
            blockers.append(PRICE_SNAPSHOT_NOT_EFFECTIVE)
        if self.stable_security_id != require_non_empty(
            stable_security_id,
            "stable_security_id",
        ):
            blockers.append(PRICE_SECURITY_MISMATCH)
        if self.calendar_version != require_non_empty(
            calendar_version,
            "calendar_version",
        ):
            blockers.append(PRICE_CALENDAR_VERSION_MISMATCH)
        if self.price_limit_rule_version != require_non_empty(
            price_limit_rule_version,
            "price_limit_rule_version",
        ):
            blockers.append(PRICE_LIMIT_RULE_VERSION_MISMATCH)
        if self.tick_size_rule_version != require_non_empty(
            tick_size_rule_version,
            "tick_size_rule_version",
        ):
            blockers.append(TICK_RULE_VERSION_MISMATCH)
        if not isinstance(price_limit_policy, PriceLimitPolicy):
            raise TypeError("price_limit_policy_type_invalid")
        if not isinstance(tick_size_policy, TickSizePolicy):
            raise TypeError("tick_size_policy_type_invalid")
        has_bounds = self.lower_limit_price is not None
        if price_limit_policy.has_price_limit != has_bounds:
            blockers.append(PRICE_LIMIT_POLICY_MISMATCH)
        elif has_bounds:
            try:
                expected = price_limit_policy.expected_band(
                    reference_price=self.reference_price,
                    tick_size=tick_size_policy.tick_size,
                )
            except ValueError:
                blockers.append(PRICE_LIMIT_POLICY_MISMATCH)
            else:
                actual = (self.lower_limit_price, self.upper_limit_price)
                if actual != expected:
                    blockers.append(PRICE_LIMIT_POLICY_MISMATCH)
                if self.lower_limit_price is not None and candidate < self.lower_limit_price:
                    blockers.append(PRICE_BELOW_LIMIT)
                if self.upper_limit_price is not None and candidate > self.upper_limit_price:
                    blockers.append(PRICE_ABOVE_LIMIT)
        if not tick_size_policy.is_aligned(candidate):
            blockers.append(PRICE_TICK_MISALIGNED)
        if normalized_side == "buy" and self.upper_locked:
            blockers.append(BUY_BLOCKED_AT_UPPER_LOCK)
        if normalized_side == "sell" and self.lower_locked:
            blockers.append(SELL_BLOCKED_AT_LOWER_LOCK)
        return tuple(sorted(set(blockers))) if blockers else (PRICE_VALID,)
