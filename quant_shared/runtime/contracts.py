"""Asset-neutral Shared Platform V3 runtime contract.

V3 is an additive interface layer.  It describes the shape and provenance of
runtime observations, action decisions, immutable audit events, and read-model
envelopes without deciding what an asset-domain action means.  Asset domains
remain responsible for their own strategy, risk, execution, and broker rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from quant_shared.core.identity import validate_id
from quant_shared.core.time import ensure_utc, isoformat_utc


V3_CONTRACT_VERSION = "shared_platform_v3"
V3_CAPABILITIES = (
    "runtime_state",
    "action_authorization",
    "audit_event",
    "read_model_envelope",
)

_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_HEX40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _validate_code(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not _CODE_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name}_invalid:{normalized}")
    return normalized


def validate_reason_code(value: str) -> str:
    """Validate a stable, lowercase reason code at a domain-neutral boundary."""

    return _validate_code(value, field_name="reason_code")


def validate_blocker_code(value: str) -> str:
    """Validate a stable, lowercase blocker code at a domain-neutral boundary."""

    return _validate_code(value, field_name="blocker_code")


def _validate_sha(value: str, *, field_name: str) -> str:
    normalized = str(value).lower()
    if not _HEX64_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name}_must_be_sha256")
    return normalized


def _validate_commit(value: str, *, field_name: str = "current_head") -> str:
    normalized = str(value).lower()
    if not _HEX40_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name}_must_be_git_commit")
    return normalized


def _strict_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name}_must_be_bool")
    return value


def _unique_codes(values: Sequence[str], *, validator: object) -> tuple[str, ...]:
    result: list[str] = []
    validate = validator  # keep the selected validator explicit for auditability
    for value in values:
        normalized = validate(value)  # type: ignore[operator]
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


@dataclass(frozen=True)
class RuntimeStateEnvelopeV3:
    """Immutable transport-neutral observation of a runtime state."""

    runtime_id: str
    state: str
    active: bool
    opening_allowed: bool
    cancel_only: bool
    worker_alive: bool
    heartbeat_at_utc: datetime | None
    blocker_codes: Sequence[str] = ()
    contract_version: str = V3_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_id", validate_id(self.runtime_id, field_name="runtime_id"))
        object.__setattr__(self, "state", validate_id(self.state, field_name="state"))
        for field_name in ("active", "opening_allowed", "cancel_only", "worker_alive"):
            _strict_bool(getattr(self, field_name), field_name=field_name)
        if self.heartbeat_at_utc is not None:
            object.__setattr__(self, "heartbeat_at_utc", ensure_utc(self.heartbeat_at_utc))
        object.__setattr__(
            self,
            "blocker_codes",
            _unique_codes(self.blocker_codes, validator=validate_blocker_code),
        )
        if self.contract_version != V3_CONTRACT_VERSION:
            raise ValueError(f"contract_version must be {V3_CONTRACT_VERSION}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.contract_version,
            "runtime_id": self.runtime_id,
            "state": self.state,
            "active": self.active,
            "opening_allowed": self.opening_allowed,
            "cancel_only": self.cancel_only,
            "worker_alive": self.worker_alive,
            "heartbeat_at_utc": (
                isoformat_utc(self.heartbeat_at_utc)
                if self.heartbeat_at_utc is not None
                else None
            ),
            "blocker_codes": list(self.blocker_codes),
        }


@dataclass(frozen=True)
class ActionAuthorizationV3:
    """A domain-neutral decision record; it does not grant execution access."""

    action: str
    allowed: bool
    reason_code: str | None
    blocker_codes: Sequence[str]
    evaluated_at_utc: datetime
    contract_version: str = V3_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", validate_id(self.action, field_name="action"))
        _strict_bool(self.allowed, field_name="allowed")
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", validate_reason_code(self.reason_code))
        if not self.allowed and self.reason_code is None:
            raise ValueError("denied_action_requires_reason_code")
        object.__setattr__(
            self,
            "blocker_codes",
            _unique_codes(self.blocker_codes, validator=validate_blocker_code),
        )
        object.__setattr__(self, "evaluated_at_utc", ensure_utc(self.evaluated_at_utc))
        if self.contract_version != V3_CONTRACT_VERSION:
            raise ValueError(f"contract_version must be {V3_CONTRACT_VERSION}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.contract_version,
            "action": self.action,
            "allowed": self.allowed,
            "reason_code": self.reason_code,
            "blocker_codes": list(self.blocker_codes),
            "evaluated_at_utc": isoformat_utc(self.evaluated_at_utc),
        }


@dataclass(frozen=True)
class RuntimeAuditEventV3:
    """Append-only, hash-addressed audit event contract."""

    event_id: str
    runtime_id: str
    sequence: int
    event_type: str
    occurred_at_utc: datetime
    reason_code: str | None
    payload_hash: str
    previous_event_hash: str | None
    contract_version: str = V3_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", validate_id(self.event_id, field_name="event_id"))
        object.__setattr__(self, "runtime_id", validate_id(self.runtime_id, field_name="runtime_id"))
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence_must_be_non_negative_integer")
        object.__setattr__(self, "event_type", validate_id(self.event_type, field_name="event_type"))
        object.__setattr__(self, "occurred_at_utc", ensure_utc(self.occurred_at_utc))
        if self.reason_code is not None:
            object.__setattr__(self, "reason_code", validate_reason_code(self.reason_code))
        object.__setattr__(self, "payload_hash", _validate_sha(self.payload_hash, field_name="payload_hash"))
        if self.previous_event_hash is not None:
            object.__setattr__(
                self,
                "previous_event_hash",
                _validate_sha(self.previous_event_hash, field_name="previous_event_hash"),
            )
        if self.contract_version != V3_CONTRACT_VERSION:
            raise ValueError(f"contract_version must be {V3_CONTRACT_VERSION}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.contract_version,
            "event_id": self.event_id,
            "runtime_id": self.runtime_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "occurred_at_utc": isoformat_utc(self.occurred_at_utc),
            "reason_code": self.reason_code,
            "payload_hash": self.payload_hash,
            "previous_event_hash": self.previous_event_hash,
        }


@dataclass(frozen=True)
class ReadModelEnvelopeV3:
    """A derived read-model envelope with explicit state/action/audit inputs."""

    snapshot_id: str
    generated_at_utc: datetime
    current_head: str
    status: str
    decision: str
    runtime: RuntimeStateEnvelopeV3
    action: ActionAuthorizationV3
    audit_event: RuntimeAuditEventV3
    data_version: str
    contract_version: str = V3_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", validate_id(self.snapshot_id, field_name="snapshot_id"))
        object.__setattr__(self, "generated_at_utc", ensure_utc(self.generated_at_utc))
        object.__setattr__(self, "current_head", _validate_commit(self.current_head))
        for field_name in ("status", "decision", "data_version"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name}_required")
        if self.runtime.runtime_id != self.audit_event.runtime_id:
            raise ValueError("runtime_audit_identity_mismatch")
        if self.contract_version != V3_CONTRACT_VERSION:
            raise ValueError(f"contract_version must be {V3_CONTRACT_VERSION}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.contract_version,
            "snapshot_id": self.snapshot_id,
            "generated_at_utc": isoformat_utc(self.generated_at_utc),
            "current_head": self.current_head,
            "status": self.status,
            "decision": self.decision,
            "data_version": self.data_version,
            "runtime": self.runtime.to_dict(),
            "action": self.action.to_dict(),
            "audit_event": self.audit_event.to_dict(),
        }


__all__ = [
    "ActionAuthorizationV3",
    "ReadModelEnvelopeV3",
    "RuntimeAuditEventV3",
    "RuntimeStateEnvelopeV3",
    "V3_CAPABILITIES",
    "V3_CONTRACT_VERSION",
    "validate_blocker_code",
    "validate_reason_code",
]
