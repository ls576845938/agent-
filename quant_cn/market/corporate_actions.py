"""PIT corporate actions and side-effect-free effect projections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from quant_cn.data.contracts import (
    ensure_aware_timestamp,
    ensure_sha256_checksum,
    require_non_empty,
)


CASH_DIVIDEND = "cash_dividend"
BONUS_SHARE = "bonus_share"
SHARE_SPLIT = "share_split"
SHARE_CONSOLIDATION = "share_consolidation"
RIGHTS_ISSUE = "rights_issue"
CORPORATE_ACTION_TYPES = frozenset(
    {CASH_DIVIDEND, BONUS_SHARE, SHARE_SPLIT, SHARE_CONSOLIDATION, RIGHTS_ISSUE}
)

ACTION_RESOLVED = "resolved"
ACTION_MISSING = "missing"
ACTION_SNAPSHOT_NOT_AVAILABLE = "snapshot_not_available"
ACTION_NOT_AVAILABLE = "not_available"
ACTION_AMBIGUOUS = "ambiguous"
ACTION_SNAPSHOT_INCOMPLETE = "snapshot_incomplete"

EFFECT_PENDING = "pending"
EFFECT_EFFECTIVE = "effective"

FRACTIONAL_PRESERVE_DECIMAL = "preserve_decimal"
FRACTIONAL_ROUND_DOWN = "round_down"
FRACTIONAL_POLICIES = frozenset(
    {FRACTIONAL_PRESERVE_DECIMAL, FRACTIONAL_ROUND_DOWN}
)


def _decimal(value: Decimal, field_name: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"decimal_required:{field_name}")
    if not value.is_finite():
        raise ValueError(f"finite_decimal_required:{field_name}")
    if positive and value <= Decimal("0"):
        raise ValueError(f"positive_decimal_required:{field_name}")
    if not positive and value < Decimal("0"):
        raise ValueError(f"non_negative_decimal_required:{field_name}")
    return value


def _apply_fractional_policy(value: Decimal, policy: str | None) -> Decimal:
    if policy == FRACTIONAL_PRESERVE_DECIMAL:
        return value
    if policy == FRACTIONAL_ROUND_DOWN:
        return value.to_integral_value(rounding=ROUND_FLOOR)
    raise ValueError("corporate_action_fractional_policy_missing")


def _canonical_decimal(value: Decimal) -> str:
    return "0" if value == Decimal("0") else format(value.normalize(), "f")


@dataclass(frozen=True)
class PITCorporateAction:
    action_id: str
    stable_security_id: str
    action_type: str
    announce_time: datetime
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    record_time: datetime
    effective_time: datetime
    pay_time: datetime | None
    rights_expiry_time: datetime | None
    cash_per_share: Decimal | None
    share_ratio: Decimal | None
    share_multiplier: Decimal | None
    subscription_price: Decimal | None
    fractional_policy: str | None
    source: str
    source_version: str
    effective_rule_date: datetime
    version: str
    checksum: str

    def __post_init__(self) -> None:
        for field_name in (
            "action_id",
            "stable_security_id",
            "source",
            "source_version",
            "version",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        action_type = require_non_empty(self.action_type, "action_type").lower()
        if action_type not in CORPORATE_ACTION_TYPES:
            raise ValueError("corporate_action_type_unknown")
        object.__setattr__(self, "action_type", action_type)
        for field_name in (
            "announce_time",
            "available_time",
            "ingested_at",
            "processed_at",
            "record_time",
            "effective_time",
            "effective_rule_date",
        ):
            object.__setattr__(
                self,
                field_name,
                ensure_aware_timestamp(
                    getattr(self, field_name),
                    f"corporate_action.{field_name}",
                ),
            )
        for field_name in ("pay_time", "rights_expiry_time"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    ensure_aware_timestamp(
                        value,
                        f"corporate_action.{field_name}",
                    ),
                )
        if self.announce_time > self.available_time:
            raise ValueError("corporate_action_announce_time_after_available_time")
        if self.available_time > self.ingested_at:
            raise ValueError("corporate_action_available_time_after_ingested_at")
        if self.ingested_at > self.processed_at:
            raise ValueError("corporate_action_ingested_at_after_processed_at")
        if self.record_time > self.effective_time:
            raise ValueError("corporate_action_record_time_after_effective_time")
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "corporate_action.checksum"),
        )
        self._validate_terms()

    def _validate_fractional_policy(self) -> None:
        if self.fractional_policy is None:
            raise ValueError("corporate_action_fractional_policy_missing")
        policy = require_non_empty(
            self.fractional_policy,
            "fractional_policy",
        ).lower()
        if policy not in FRACTIONAL_POLICIES:
            raise ValueError("corporate_action_fractional_policy_unknown")
        object.__setattr__(self, "fractional_policy", policy)

    def _validate_terms(self) -> None:
        if self.action_type == CASH_DIVIDEND:
            if self.cash_per_share is None or self.pay_time is None:
                raise ValueError("corporate_action_cash_terms_missing")
            _decimal(self.cash_per_share, "cash_per_share")
            if self.pay_time < self.effective_time:
                raise ValueError("corporate_action_pay_time_before_effective_time")
            if any(
                value is not None
                for value in (
                    self.share_ratio,
                    self.share_multiplier,
                    self.subscription_price,
                    self.rights_expiry_time,
                    self.fractional_policy,
                )
            ):
                raise ValueError("corporate_action_terms_conflict:cash_dividend")
            return
        if self.action_type == BONUS_SHARE:
            if self.share_ratio is None:
                raise ValueError("corporate_action_share_ratio_missing")
            _decimal(self.share_ratio, "share_ratio", positive=True)
            self._validate_fractional_policy()
            conflicting = (
                self.cash_per_share,
                self.share_multiplier,
                self.subscription_price,
                self.pay_time,
                self.rights_expiry_time,
            )
        elif self.action_type in {SHARE_SPLIT, SHARE_CONSOLIDATION}:
            if self.share_multiplier is None:
                raise ValueError("corporate_action_share_multiplier_missing")
            multiplier = _decimal(
                self.share_multiplier,
                "share_multiplier",
                positive=True,
            )
            if self.action_type == SHARE_SPLIT and multiplier <= Decimal("1"):
                raise ValueError("share_split_multiplier_must_exceed_one")
            if (
                self.action_type == SHARE_CONSOLIDATION
                and multiplier >= Decimal("1")
            ):
                raise ValueError("share_consolidation_multiplier_must_be_below_one")
            self._validate_fractional_policy()
            conflicting = (
                self.cash_per_share,
                self.share_ratio,
                self.subscription_price,
                self.pay_time,
                self.rights_expiry_time,
            )
        else:
            if (
                self.share_ratio is None
                or self.subscription_price is None
                or self.rights_expiry_time is None
            ):
                raise ValueError("corporate_action_rights_terms_missing")
            _decimal(self.share_ratio, "share_ratio", positive=True)
            _decimal(self.subscription_price, "subscription_price")
            self._validate_fractional_policy()
            if self.rights_expiry_time < self.effective_time:
                raise ValueError("corporate_action_rights_expiry_before_effective_time")
            conflicting = (
                self.cash_per_share,
                self.share_multiplier,
                self.pay_time,
            )
        if any(value is not None for value in conflicting):
            raise ValueError(f"corporate_action_terms_conflict:{self.action_type}")


@dataclass(frozen=True)
class CorporateActionSnapshot:
    snapshot_id: str
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    source: str
    source_version: str
    effective_rule_date: datetime
    version: str
    checksum: str
    complete: bool
    actions: tuple[PITCorporateAction, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "snapshot_id",
            "source",
            "source_version",
            "version",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        for field_name in (
            "event_time",
            "available_time",
            "ingested_at",
            "processed_at",
            "effective_rule_date",
        ):
            object.__setattr__(
                self,
                field_name,
                ensure_aware_timestamp(
                    getattr(self, field_name),
                    f"action_snapshot.{field_name}",
                ),
            )
        if self.event_time > self.available_time:
            raise ValueError("corporate_action_snapshot_event_time_after_available_time")
        if self.available_time > self.ingested_at:
            raise ValueError("corporate_action_snapshot_available_time_after_ingested_at")
        if self.ingested_at > self.processed_at:
            raise ValueError("corporate_action_snapshot_ingested_at_after_processed_at")
        if not isinstance(self.complete, bool):
            raise TypeError("corporate_action_snapshot_complete_must_be_bool")
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "action_snapshot.checksum"),
        )
        actions = tuple(self.actions)
        if any(not isinstance(item, PITCorporateAction) for item in actions):
            raise TypeError("corporate_action_type_invalid")
        identities = tuple(
            (item.stable_security_id, item.action_id, item.version)
            for item in actions
        )
        if len(identities) != len(set(identities)):
            raise ValueError("corporate_action_duplicate_identity")
        object.__setattr__(
            self,
            "actions",
            tuple(
                sorted(
                    actions,
                    key=lambda item: (
                        item.stable_security_id,
                        item.action_id,
                        item.version,
                    ),
                )
            ),
        )

    def is_available(self, as_of: datetime) -> bool:
        return self.available_time <= ensure_aware_timestamp(as_of, "as_of")


@dataclass(frozen=True)
class CorporateActionResolution:
    status: str
    snapshot_version: str | None = None
    versions: tuple[str, ...] = ()
    action: PITCorporateAction | None = None


@dataclass(frozen=True)
class CorporateActionEffectProjection:
    status: str
    stable_security_id: str
    action_id: str | None
    action_type: str | None
    action_version: str | None
    snapshot_version: str | None
    effect_time: datetime | None
    cash_delta: Decimal
    position_delta: Decimal
    rights_quantity: Decimal
    subscription_cash_required: Decimal
    posting_key: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "action_version": self.action_version,
            "cash_delta": str(self.cash_delta),
            "effect_time": self.effect_time.isoformat() if self.effect_time else None,
            "position_delta": str(self.position_delta),
            "posting_key": self.posting_key,
            "rights_quantity": str(self.rights_quantity),
            "snapshot_version": self.snapshot_version,
            "stable_security_id": self.stable_security_id,
            "status": self.status,
            "subscription_cash_required": str(self.subscription_cash_required),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class CorporateActionBook:
    """Resolve only PIT-visible rows and never mutate portfolio or ledger state."""

    def __init__(self, snapshot: CorporateActionSnapshot | None) -> None:
        if snapshot is not None and not isinstance(snapshot, CorporateActionSnapshot):
            raise TypeError("corporate_action_snapshot_type_invalid")
        self._snapshot = snapshot

    def resolve(
        self,
        *,
        stable_security_id: str,
        action_id: str,
        as_of: datetime,
    ) -> CorporateActionResolution:
        security_id = require_non_empty(stable_security_id, "stable_security_id")
        requested_action_id = require_non_empty(action_id, "action_id")
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        if self._snapshot is None:
            return CorporateActionResolution(ACTION_MISSING)
        if not self._snapshot.is_available(timestamp):
            return CorporateActionResolution(ACTION_SNAPSHOT_NOT_AVAILABLE)
        if not self._snapshot.complete:
            return CorporateActionResolution(
                ACTION_SNAPSHOT_INCOMPLETE,
                snapshot_version=self._snapshot.version,
            )
        candidates = tuple(
            item
            for item in self._snapshot.actions
            if item.stable_security_id == security_id
            and item.action_id == requested_action_id
        )
        if not candidates:
            return CorporateActionResolution(
                ACTION_MISSING,
                snapshot_version=self._snapshot.version,
            )
        visible = tuple(
            item for item in candidates if item.available_time <= timestamp
        )
        if not visible:
            return CorporateActionResolution(
                ACTION_NOT_AVAILABLE,
                snapshot_version=self._snapshot.version,
            )
        versions = tuple(sorted({item.version for item in visible}))
        if len(visible) > 1:
            return CorporateActionResolution(
                ACTION_AMBIGUOUS,
                snapshot_version=self._snapshot.version,
                versions=versions,
            )
        return CorporateActionResolution(
            ACTION_RESOLVED,
            snapshot_version=self._snapshot.version,
            versions=(visible[0].version,),
            action=visible[0],
        )

    def project(
        self,
        *,
        stable_security_id: str,
        action_id: str,
        as_of: datetime,
        record_quantity: Decimal,
    ) -> CorporateActionEffectProjection:
        quantity = _decimal(record_quantity, "record_quantity")
        security_id = require_non_empty(stable_security_id, "stable_security_id")
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        resolution = self.resolve(
            stable_security_id=security_id,
            action_id=action_id,
            as_of=timestamp,
        )
        zero = Decimal("0")
        if resolution.status != ACTION_RESOLVED or resolution.action is None:
            return CorporateActionEffectProjection(
                resolution.status,
                security_id,
                None,
                None,
                None,
                resolution.snapshot_version,
                None,
                zero,
                zero,
                zero,
                zero,
                None,
            )
        action = resolution.action
        effect_time = (
            action.pay_time
            if action.action_type == CASH_DIVIDEND
            else action.effective_time
        )
        if effect_time is None:
            raise AssertionError("validated corporate action missing effect time")
        cash_delta = position_delta = rights_quantity = subscription_cash = zero
        state = EFFECT_PENDING
        if timestamp >= effect_time:
            state = EFFECT_EFFECTIVE
            if action.action_type == CASH_DIVIDEND:
                if action.cash_per_share is None:
                    raise AssertionError("validated cash dividend missing terms")
                cash_delta = quantity * action.cash_per_share
            elif action.action_type == BONUS_SHARE:
                if action.share_ratio is None:
                    raise AssertionError("validated bonus action missing ratio")
                position_delta = _apply_fractional_policy(
                    quantity * action.share_ratio,
                    action.fractional_policy,
                )
            elif action.action_type in {SHARE_SPLIT, SHARE_CONSOLIDATION}:
                if action.share_multiplier is None:
                    raise AssertionError("validated share action missing multiplier")
                new_quantity = _apply_fractional_policy(
                    quantity * action.share_multiplier,
                    action.fractional_policy,
                )
                position_delta = new_quantity - quantity
            else:
                if action.share_ratio is None or action.subscription_price is None:
                    raise AssertionError("validated rights action missing terms")
                rights_quantity = _apply_fractional_policy(
                    quantity * action.share_ratio,
                    action.fractional_policy,
                )
                subscription_cash = rights_quantity * action.subscription_price
        posting_key = None
        if state == EFFECT_EFFECTIVE:
            material = json.dumps(
                {
                    "action_checksum": action.checksum,
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "action_version": action.version,
                    "effect_time": effect_time.isoformat(),
                    "record_quantity": _canonical_decimal(quantity),
                    "stable_security_id": action.stable_security_id,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            posting_key = hashlib.sha256(material).hexdigest()
        return CorporateActionEffectProjection(
            state,
            action.stable_security_id,
            action.action_id,
            action.action_type,
            action.version,
            resolution.snapshot_version,
            effect_time,
            cash_delta,
            position_delta,
            rights_quantity,
            subscription_cash,
            posting_key,
        )
