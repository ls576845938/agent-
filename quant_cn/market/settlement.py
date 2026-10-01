"""Immutable settlement inventory and fail-closed A-share sellability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from quant_cn.data.contracts import (
    ensure_aware_timestamp,
    ensure_sha256_checksum,
    require_non_empty,
)
from quant_cn.market.rules import SellabilityPolicy, SettlementPolicy


INVENTORY_RESOLVED = "resolved"
INVENTORY_MISSING = "missing"
INVENTORY_NOT_AVAILABLE = "not_available"
INVENTORY_AMBIGUOUS = "ambiguous"
INVENTORY_INCOMPLETE = "incomplete"
INVENTORY_SESSION_SEQUENCE_INVALID = "session_sequence_invalid"
INVENTORY_SESSION_SEQUENCE_VERSION_MISMATCH = "session_sequence_version_mismatch"
INVENTORY_POLICY_MISMATCH = "policy_mismatch"


def _integer(value: int, field_name: str, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"integer_minimum_required:{field_name}:{minimum}")
    return value


@dataclass(frozen=True)
class SettlementInventoryLot:
    lot_id: str
    stable_security_id: str
    quantity: int
    reserved_quantity: int
    acquired_session_sequence: int
    session_sequence_version: str
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    source: str
    version: str
    checksum: str

    def __post_init__(self) -> None:
        for field_name in (
            "lot_id",
            "stable_security_id",
            "session_sequence_version",
            "source",
            "version",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        quantity = _integer(self.quantity, "quantity", minimum=1)
        reserved = _integer(self.reserved_quantity, "reserved_quantity", minimum=0)
        if reserved > quantity:
            raise ValueError("inventory_reserved_quantity_exceeds_quantity")
        _integer(
            self.acquired_session_sequence,
            "acquired_session_sequence",
            minimum=0,
        )
        for field_name in (
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
                    f"inventory.{field_name}",
                ),
            )
        if self.event_time > self.available_time:
            raise ValueError("inventory_event_time_after_available_time")
        if self.available_time > self.ingested_at:
            raise ValueError("inventory_available_time_after_ingested_at")
        if self.ingested_at > self.processed_at:
            raise ValueError("inventory_ingested_at_after_processed_at")
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "inventory.checksum"),
        )


@dataclass(frozen=True)
class SettlementInventorySnapshot:
    snapshot_id: str
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    source: str
    version: str
    checksum: str
    complete: bool
    lots: tuple[SettlementInventoryLot, ...]

    def __post_init__(self) -> None:
        for field_name in ("snapshot_id", "source", "version"):
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
        ):
            object.__setattr__(
                self,
                field_name,
                ensure_aware_timestamp(
                    getattr(self, field_name),
                    f"inventory_snapshot.{field_name}",
                ),
            )
        if self.event_time > self.available_time:
            raise ValueError("inventory_snapshot_event_time_after_available_time")
        if self.available_time > self.ingested_at:
            raise ValueError("inventory_snapshot_available_time_after_ingested_at")
        if self.ingested_at > self.processed_at:
            raise ValueError("inventory_snapshot_ingested_at_after_processed_at")
        if not isinstance(self.complete, bool):
            raise TypeError("inventory_snapshot_complete_must_be_bool")
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "inventory_snapshot.checksum"),
        )
        lots = tuple(self.lots)
        if any(not isinstance(item, SettlementInventoryLot) for item in lots):
            raise TypeError("settlement_inventory_lot_type_invalid")
        if any(item.event_time > self.event_time for item in lots):
            raise ValueError("inventory_lot_event_after_snapshot")
        if any(item.available_time > self.available_time for item in lots):
            raise ValueError("inventory_lot_available_after_snapshot")
        if any(item.ingested_at > self.ingested_at for item in lots):
            raise ValueError("inventory_lot_ingested_after_snapshot")
        if any(item.processed_at > self.processed_at for item in lots):
            raise ValueError("inventory_lot_processed_after_snapshot")
        object.__setattr__(
            self,
            "lots",
            tuple(
                sorted(
                    lots,
                    key=lambda item: (
                        item.stable_security_id,
                        item.lot_id,
                        item.version,
                    ),
                )
            ),
        )

    def is_available(self, as_of: datetime) -> bool:
        return self.available_time <= ensure_aware_timestamp(as_of, "as_of")


@dataclass(frozen=True)
class SellableInventoryResolution:
    status: str
    snapshot_version: str | None = None
    total_quantity: int = 0
    reserved_quantity: int = 0
    sellable_quantity: int = 0
    versions: tuple[tuple[str, str], ...] = ()


class SettlementInventory:
    """Calculate sellability from one PIT-complete injected snapshot."""

    def __init__(self, snapshot: SettlementInventorySnapshot | None) -> None:
        if snapshot is not None and not isinstance(
            snapshot,
            SettlementInventorySnapshot,
        ):
            raise TypeError("settlement_inventory_snapshot_type_invalid")
        self._snapshot = snapshot

    @property
    def snapshot(self) -> SettlementInventorySnapshot | None:
        return self._snapshot

    def resolve(
        self,
        *,
        stable_security_id: str,
        as_of: datetime,
        current_session_sequence: int,
        current_session_sequence_version: str,
        sellability_policy: SellabilityPolicy,
        settlement_policy: SettlementPolicy,
    ) -> SellableInventoryResolution:
        security_id = require_non_empty(stable_security_id, "stable_security_id")
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        current_sequence = _integer(
            current_session_sequence,
            "current_session_sequence",
            minimum=0,
        )
        sequence_version = require_non_empty(
            current_session_sequence_version,
            "current_session_sequence_version",
        )
        if not isinstance(sellability_policy, SellabilityPolicy):
            raise TypeError("sellability_policy_type_invalid")
        if not isinstance(settlement_policy, SettlementPolicy):
            raise TypeError("settlement_policy_type_invalid")
        if (
            sellability_policy.sellable_after_sessions
            != settlement_policy.position_settlement_sessions
        ):
            return SellableInventoryResolution(INVENTORY_POLICY_MISMATCH)
        if self._snapshot is None:
            return SellableInventoryResolution(INVENTORY_MISSING)
        if not self._snapshot.is_available(timestamp):
            return SellableInventoryResolution(INVENTORY_NOT_AVAILABLE)
        snapshot_version = self._snapshot.version
        if not self._snapshot.complete:
            return SellableInventoryResolution(
                INVENTORY_INCOMPLETE,
                snapshot_version=snapshot_version,
            )
        visible = tuple(
            item
            for item in self._snapshot.lots
            if item.stable_security_id == security_id
            and item.available_time <= timestamp
        )
        if not visible:
            return SellableInventoryResolution(
                INVENTORY_RESOLVED,
                snapshot_version=snapshot_version,
            )
        identities = tuple(item.lot_id for item in visible)
        versions = tuple(sorted((item.lot_id, item.version) for item in visible))
        if len(identities) != len(set(identities)):
            return SellableInventoryResolution(
                INVENTORY_AMBIGUOUS,
                snapshot_version=snapshot_version,
                versions=versions,
            )
        if any(item.acquired_session_sequence > current_sequence for item in visible):
            return SellableInventoryResolution(
                INVENTORY_SESSION_SEQUENCE_INVALID,
                snapshot_version=snapshot_version,
                versions=versions,
            )
        if any(item.session_sequence_version != sequence_version for item in visible):
            return SellableInventoryResolution(
                INVENTORY_SESSION_SEQUENCE_VERSION_MISMATCH,
                snapshot_version=snapshot_version,
                versions=versions,
            )
        total = sum(item.quantity for item in visible)
        reserved = sum(item.reserved_quantity for item in visible)
        waiting_sessions = settlement_policy.position_settlement_sessions
        sellable = sum(
            item.quantity - item.reserved_quantity
            for item in visible
            if current_sequence - item.acquired_session_sequence >= waiting_sessions
        )
        return SellableInventoryResolution(
            INVENTORY_RESOLVED,
            snapshot_version=snapshot_version,
            total_quantity=total,
            reserved_quantity=reserved,
            sellable_quantity=sellable,
            versions=versions,
        )


def inventory_from_lots(
    *,
    snapshot_id: str,
    event_time: datetime,
    available_time: datetime,
    ingested_at: datetime,
    processed_at: datetime,
    source: str,
    version: str,
    checksum: str,
    complete: bool,
    lots: Iterable[SettlementInventoryLot],
) -> SettlementInventory:
    """Small constructor that preserves immutable tuple ordering."""

    return SettlementInventory(
        SettlementInventorySnapshot(
            snapshot_id=snapshot_id,
            event_time=event_time,
            available_time=available_time,
            ingested_at=ingested_at,
            processed_at=processed_at,
            source=source,
            version=version,
            checksum=checksum,
            complete=complete,
            lots=tuple(lots),
        )
    )
