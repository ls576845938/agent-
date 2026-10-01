"""Point-in-time input contracts for the China A-share domain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any


PIT_RECORD_NOT_AVAILABLE = "pit_record_not_available"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PITLookaheadError(ValueError):
    """Raised when a record is consumed before its visibility timestamp."""


def require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"non_empty_string_required:{field_name}")
    return value.strip()


def ensure_aware_timestamp(value: datetime, field_name: str) -> datetime:
    """Require an aware timestamp and normalize it to UTC."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timestamp_must_be_timezone_aware:{field_name}")
    return value.astimezone(timezone.utc)


def ensure_sha256_checksum(value: str, field_name: str = "checksum") -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"checksum_must_be_lowercase_sha256:{field_name}")
    return value


@dataclass(frozen=True)
class PITSecurityRecord:
    """Injected security state with explicit identity, lineage, and visibility."""

    stable_security_id: str
    venue: str
    instrument: str
    board: str
    security_type: str
    state: str
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
            "venue",
            "instrument",
            "board",
            "security_type",
            "state",
            "source",
            "version",
        ):
            normalized = require_non_empty(getattr(self, field_name), field_name)
            if field_name == "state":
                normalized = normalized.lower()
            object.__setattr__(self, field_name, normalized)

        for field_name in (
            "event_time",
            "available_time",
            "ingested_at",
            "processed_at",
        ):
            object.__setattr__(
                self,
                field_name,
                ensure_aware_timestamp(getattr(self, field_name), field_name),
            )

        object.__setattr__(self, "checksum", ensure_sha256_checksum(self.checksum))
        if self.event_time > self.available_time:
            raise ValueError("pit_event_time_after_available_time")
        if self.available_time > self.ingested_at:
            raise ValueError("pit_available_time_after_ingested_at")
        if self.ingested_at > self.processed_at:
            raise ValueError("pit_ingested_at_after_processed_at")

    def assert_available(self, as_of: datetime) -> None:
        decision_time = ensure_aware_timestamp(as_of, "as_of")
        if decision_time < self.available_time:
            raise PITLookaheadError(PIT_RECORD_NOT_AVAILABLE)

    def is_available(self, as_of: datetime) -> bool:
        try:
            self.assert_available(as_of)
        except PITLookaheadError:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "available_time": self.available_time.isoformat(),
            "board": self.board,
            "checksum": self.checksum,
            "event_time": self.event_time.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "instrument": self.instrument,
            "processed_at": self.processed_at.isoformat(),
            "security_type": self.security_type,
            "source": self.source,
            "stable_security_id": self.stable_security_id,
            "state": self.state,
            "venue": self.venue,
            "version": self.version,
        }
