"""Point-in-time, effective-dated China security-status semantics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from quant_cn.data.contracts import (
    ensure_aware_timestamp,
    ensure_sha256_checksum,
    require_non_empty,
)


STATUS_ACTIVE = "active"
STATUS_RISK_WARNING = "risk_warning"
STATUS_SUSPENDED = "suspended"
STATUS_DELISTING_PERIOD = "delisting_period"
STATUS_DELISTED = "delisted"
STATUS_NOT_LISTED = "not_listed"
STATUS_UNKNOWN = "unknown"
KNOWN_SECURITY_STATUSES = frozenset(
    {
        STATUS_ACTIVE,
        STATUS_RISK_WARNING,
        STATUS_SUSPENDED,
        STATUS_DELISTING_PERIOD,
        STATUS_DELISTED,
        STATUS_NOT_LISTED,
        STATUS_UNKNOWN,
    }
)

STATUS_RESOLVED = "resolved"
STATUS_MISSING = "missing"
STATUS_NOT_AVAILABLE = "not_available"
STATUS_NOT_YET_EFFECTIVE = "not_yet_effective"
STATUS_EXPIRED = "expired"
STATUS_OVERLAP = "overlap"

SECURITY_STATUS_UNKNOWN = "security_status_unknown"
SECURITY_SUSPENDED = "security_suspended"
SECURITY_DELISTED = "security_delisted"
SECURITY_NOT_LISTED = "security_not_listed"
SECURITY_BUY_NOT_ALLOWED = "security_buy_not_allowed"
SECURITY_SELL_NOT_ALLOWED = "security_sell_not_allowed"


@dataclass(frozen=True)
class EffectiveSecurityStatus:
    stable_security_id: str
    status: str
    buy_allowed: bool
    sell_allowed: bool
    event_time: datetime
    effective_from: datetime
    effective_to: datetime | None
    available_time: datetime
    ingested_at: datetime
    processed_at: datetime
    source: str
    version: str
    checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "stable_security_id",
            require_non_empty(self.stable_security_id, "stable_security_id"),
        )
        normalized_status = require_non_empty(self.status, "status").lower()
        if normalized_status not in KNOWN_SECURITY_STATUSES:
            raise ValueError("security_status_unknown")
        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "source", require_non_empty(self.source, "source"))
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))
        if not isinstance(self.buy_allowed, bool) or not isinstance(
            self.sell_allowed,
            bool,
        ):
            raise TypeError("security_status_allow_flags_must_be_bool")
        if normalized_status in {
            STATUS_SUSPENDED,
            STATUS_DELISTED,
            STATUS_NOT_LISTED,
            STATUS_UNKNOWN,
        } and (self.buy_allowed or self.sell_allowed):
            raise ValueError("non_tradable_security_status_cannot_allow_trading")

        event = ensure_aware_timestamp(
            self.event_time,
            "security_status.event_time",
        )
        start = ensure_aware_timestamp(
            self.effective_from,
            "security_status.effective_from",
        )
        end = (
            ensure_aware_timestamp(
                self.effective_to,
                "security_status.effective_to",
            )
            if self.effective_to is not None
            else None
        )
        available = ensure_aware_timestamp(
            self.available_time,
            "security_status.available_time",
        )
        ingested = ensure_aware_timestamp(
            self.ingested_at,
            "security_status.ingested_at",
        )
        processed = ensure_aware_timestamp(
            self.processed_at,
            "security_status.processed_at",
        )
        if end is not None and end <= start:
            raise ValueError("security_status_effective_interval_invalid")
        if event > available:
            raise ValueError("security_status_event_time_after_available_time")
        if available > ingested:
            raise ValueError("security_status_available_time_after_ingested_at")
        if ingested > processed:
            raise ValueError("security_status_ingested_at_after_processed_at")

        object.__setattr__(self, "event_time", event)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_to", end)
        object.__setattr__(self, "available_time", available)
        object.__setattr__(self, "ingested_at", ingested)
        object.__setattr__(self, "processed_at", processed)
        object.__setattr__(
            self,
            "checksum",
            ensure_sha256_checksum(self.checksum, "security_status.checksum"),
        )

    def is_effective(self, as_of: datetime) -> bool:
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        return self.effective_from <= timestamp and (
            self.effective_to is None or timestamp < self.effective_to
        )

    def blockers_for(self, side: str) -> tuple[str, ...]:
        normalized_side = require_non_empty(side, "side").lower()
        status_blocker = {
            STATUS_UNKNOWN: SECURITY_STATUS_UNKNOWN,
            STATUS_SUSPENDED: SECURITY_SUSPENDED,
            STATUS_DELISTED: SECURITY_DELISTED,
            STATUS_NOT_LISTED: SECURITY_NOT_LISTED,
        }.get(self.status)
        blockers: list[str] = []
        if status_blocker is not None:
            blockers.append(status_blocker)
        if normalized_side == "buy":
            if not self.buy_allowed:
                blockers.append(SECURITY_BUY_NOT_ALLOWED)
        elif normalized_side == "sell":
            if not self.sell_allowed:
                blockers.append(SECURITY_SELL_NOT_ALLOWED)
        else:
            raise ValueError("side_unknown")
        return tuple(sorted(set(blockers)))


@dataclass(frozen=True)
class SecurityStatusResolution:
    status: str
    versions: tuple[str, ...] = ()
    record: EffectiveSecurityStatus | None = None


class SecurityStatusBook:
    """Resolve injected status history without current-state fallback."""

    def __init__(self, records: Iterable[EffectiveSecurityStatus]) -> None:
        self._records = tuple(records)
        if any(not isinstance(item, EffectiveSecurityStatus) for item in self._records):
            raise TypeError("security_status_record_type_invalid")

    @property
    def records(self) -> tuple[EffectiveSecurityStatus, ...]:
        return self._records

    def resolve(
        self,
        *,
        stable_security_id: str,
        as_of: datetime,
    ) -> SecurityStatusResolution:
        security_id = require_non_empty(stable_security_id, "stable_security_id")
        timestamp = ensure_aware_timestamp(as_of, "as_of")
        candidates = tuple(
            item for item in self._records if item.stable_security_id == security_id
        )
        if not candidates:
            return SecurityStatusResolution(STATUS_MISSING)
        visible = tuple(item for item in candidates if item.available_time <= timestamp)
        if not visible:
            return SecurityStatusResolution(STATUS_NOT_AVAILABLE)
        active = tuple(item for item in visible if item.is_effective(timestamp))
        visible_versions = tuple(sorted({item.version for item in visible}))
        if not active:
            if any(
                item.available_time > timestamp and item.is_effective(timestamp)
                for item in candidates
            ):
                return SecurityStatusResolution(STATUS_NOT_AVAILABLE)
            if all(
                item.effective_to is not None and item.effective_to <= timestamp
                for item in visible
            ):
                state = STATUS_EXPIRED
            elif all(item.effective_from > timestamp for item in visible):
                state = STATUS_NOT_YET_EFFECTIVE
            else:
                state = STATUS_MISSING
            return SecurityStatusResolution(state, visible_versions)
        active_versions = tuple(sorted({item.version for item in active}))
        if len(active) > 1:
            return SecurityStatusResolution(STATUS_OVERLAP, active_versions)
        return SecurityStatusResolution(
            STATUS_RESOLVED,
            (active[0].version,),
            active[0],
        )
