from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence

from quant_shared.core.contracts import validate_contract_version
from quant_shared.core.identity import validate_id
from quant_shared.core.serialization import canonical_payload_hash
from quant_shared.core.time import ensure_utc


@dataclass(frozen=True)
class LedgerRecord:
    stream_id: str
    record_id: str
    sequence: int
    occurred_at_utc: datetime
    record_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    contract_version: str = "shared_ledger_record_v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "stream_id", validate_id(self.stream_id, field_name="stream_id"))
        object.__setattr__(self, "record_id", validate_id(self.record_id, field_name="record_id"))
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        object.__setattr__(self, "sequence", int(self.sequence))
        object.__setattr__(self, "occurred_at_utc", ensure_utc(self.occurred_at_utc))
        if not str(self.record_type).strip():
            raise ValueError("record_type is required")
        object.__setattr__(self, "payload", dict(self.payload))
        validate_contract_version(self.contract_version, "shared_ledger_record_v2")

    @property
    def fingerprint(self) -> str:
        return canonical_payload_hash(self)


@dataclass(frozen=True)
class LedgerAppendResult:
    status: str
    record_id: str
    fingerprint: str
    contract_version: str = "shared_ledger_append_result_v2"

    def __post_init__(self) -> None:
        if self.status not in {"appended", "duplicate", "conflict"}:
            raise ValueError("unsupported append status")
        validate_id(self.record_id, field_name="record_id")
        if len(self.fingerprint) != 64:
            raise ValueError("fingerprint must be sha256")
        validate_contract_version(self.contract_version, "shared_ledger_append_result_v2")


class LedgerStore(Protocol):
    def append(self, record: LedgerRecord) -> LedgerAppendResult: ...

    def read_stream(self, stream_id: str) -> Sequence[LedgerRecord]: ...

    def fingerprint(self, stream_id: str) -> str: ...


@dataclass(frozen=True)
class ReconciliationResult:
    reconciled: bool
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    mismatched: tuple[str, ...] = ()
    contract_version: str = "shared_reconciliation_result_v2"

    def __post_init__(self) -> None:
        if self.reconciled and (self.missing or self.unexpected or self.mismatched):
            raise ValueError("reconciled result cannot contain differences")
        validate_contract_version(self.contract_version, "shared_reconciliation_result_v2")


def reconcile_fingerprints(
    expected: Mapping[str, str],
    actual: Mapping[str, str],
) -> ReconciliationResult:
    expected_keys = set(expected)
    actual_keys = set(actual)
    missing = tuple(sorted(expected_keys - actual_keys))
    unexpected = tuple(sorted(actual_keys - expected_keys))
    mismatched = tuple(
        sorted(key for key in expected_keys & actual_keys if expected[key] != actual[key])
    )
    return ReconciliationResult(
        reconciled=not (missing or unexpected or mismatched),
        missing=missing,
        unexpected=unexpected,
        mismatched=mismatched,
    )
