"""Pure, offline-only contracts for a future CN QMT adapter.

The module deliberately has no broker SDK, network, account, order, file, or
environment access.  It normalizes already-decoded fixture callbacks and
compares them with the offline OMS/ledger state introduced by G06.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from quant_cn.execution.models import OrderState
from quant_cn.ledger.reconciliation import ReconciliationResult


CONTRACT_VERSION = "cn_qmt_offline_adapter_contract_v1"
FIXTURE_SCHEMA_VERSION = "cn_qmt_offline_fixture_v1"
FIELD_MAPPING_VERSION = "cn_qmt_offline_field_mapping_v1"
STATUS_MAPPING_VERSION = "cn_qmt_offline_status_mapping_v1"

QMT_REQUIRED_BLOCKERS = (
    "cn_broker_capability_unproven",
    "cn_qmt_order_write_not_authorized",
    "cn_qmt_private_read_not_authorized",
    "cn_qmt_reconciliation_unproven",
    "cn_qmt_sdk_integration_not_authorized",
)

QMT_SAFETY_FLAGS: dict[str, bool] = {
    "broker": False,
    "demo": False,
    "live": False,
    "network": False,
    "oms": False,
    "order": False,
    "paper": False,
    "paper_queue": False,
    "private": False,
    "promotion": False,
    "real_order": False,
    "sdk": False,
    "withdraw": False,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CALLBACK_TYPES = frozenset({"order", "fill"})
_SOURCE_KINDS = frozenset({"synthetic_fixture", "recorded_fixture"})
_VALUE_KINDS = frozenset(
    {"decimal", "integer", "sha256", "side", "status", "text", "timestamp"}
)
_CANONICAL_STATUSES = frozenset(
    {
        "accepted",
        "cancel_requested",
        "cancelled",
        "expired",
        "filled",
        "partially_filled",
        "rejected",
    }
)
_FORBIDDEN_PAYLOAD_KEY_MARKERS = (
    "account",
    "api_key",
    "authorization",
    "credential",
    "password",
    "passphrase",
    "private",
    "secret",
    "token",
)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"qmt_field_missing:{field_name}")
    return value.strip()


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"qmt_datetime_required:{field_name}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"qmt_datetime_naive:{field_name}")
    return value.astimezone(timezone.utc)


def _sha256_text(value: object, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if _SHA256_RE.fullmatch(text) is None:
        raise ValueError(f"qmt_sha256_invalid:{field_name}")
    return text


def _canonical_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            item.name: _canonical_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _aware_utc(value, "canonical_datetime").isoformat().replace(
            "+00:00", "Z"
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("qmt_decimal_not_finite")
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("qmt_float_forbidden")
    raise TypeError(f"qmt_canonical_type_unsupported:{type(value).__name__}")


def canonical_qmt_json(value: Any) -> str:
    """Serialize contract material deterministically without accepting floats."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_qmt_sha256(value: Any) -> str:
    return sha256(canonical_qmt_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class QMTStructuredError:
    code: str
    category: str
    operation: str
    context_sha256: str
    retryable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        for name in ("code", "category", "operation"):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "context_sha256",
            _sha256_text(self.context_sha256, "context_sha256"),
        )


class QMTContractViolation(ValueError):
    """A fail-closed contract error that never embeds raw fixture material."""

    def __init__(self, error: QMTStructuredError) -> None:
        self.error = error
        super().__init__(error.code)


def _violation(
    code: str,
    *,
    category: str,
    operation: str,
    context: object,
) -> QMTContractViolation:
    return QMTContractViolation(
        QMTStructuredError(
            code=code,
            category=category,
            operation=operation,
            context_sha256=canonical_qmt_sha256(context),
        )
    )


@dataclass(frozen=True)
class QMTRuntimeCapability:
    name: str
    blocker: str
    enabled: bool = field(default=False, init=False)
    authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        object.__setattr__(
            self, "blocker", _required_text(self.blocker, "blocker")
        )


def qmt_runtime_capabilities() -> tuple[QMTRuntimeCapability, ...]:
    """Return only disabled runtime capabilities; fixture work grants none."""

    return (
        QMTRuntimeCapability(
            "broker_connection", "cn_broker_capability_unproven"
        ),
        QMTRuntimeCapability(
            "order_write", "cn_qmt_order_write_not_authorized"
        ),
        QMTRuntimeCapability(
            "private_read", "cn_qmt_private_read_not_authorized"
        ),
        QMTRuntimeCapability(
            "runtime_reconciliation", "cn_qmt_reconciliation_unproven"
        ),
        QMTRuntimeCapability(
            "sdk_integration", "cn_qmt_sdk_integration_not_authorized"
        ),
    )


@dataclass(frozen=True)
class QMTFieldMapping:
    callback_type: str
    external_field: str
    canonical_field: str
    value_kind: str
    required: bool
    mapping_version: str
    source_version: str
    effective_from: datetime
    available_at: datetime
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        callback_type = _required_text(
            self.callback_type, "callback_type"
        ).lower()
        if callback_type not in _CALLBACK_TYPES:
            raise ValueError("qmt_callback_type_unknown")
        object.__setattr__(self, "callback_type", callback_type)
        for name in (
            "external_field",
            "canonical_field",
            "mapping_version",
            "source_version",
        ):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        value_kind = _required_text(self.value_kind, "value_kind").lower()
        if value_kind not in _VALUE_KINDS:
            raise ValueError("qmt_value_kind_unknown")
        object.__setattr__(self, "value_kind", value_kind)
        if type(self.required) is not bool:
            raise TypeError("qmt_mapping_required_bool")
        effective_from = _aware_utc(self.effective_from, "effective_from")
        available_at = _aware_utc(self.available_at, "available_at")
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "available_at", available_at)
        if self.effective_to is not None:
            effective_to = _aware_utc(self.effective_to, "effective_to")
            if effective_to <= effective_from:
                raise ValueError("qmt_mapping_effective_window_invalid")
            object.__setattr__(self, "effective_to", effective_to)

    def visible_for(self, *, event_time: datetime, as_of: datetime) -> bool:
        event_time = _aware_utc(event_time, "event_time")
        as_of = _aware_utc(as_of, "as_of")
        return (
            self.available_at <= as_of
            and self.effective_from <= event_time
            and (self.effective_to is None or event_time < self.effective_to)
        )


@dataclass(frozen=True)
class QMTStatusMapping:
    external_status: str
    canonical_status: str
    mapping_version: str
    source_version: str
    effective_from: datetime
    available_at: datetime
    effective_to: datetime | None = None

    def __post_init__(self) -> None:
        for name in (
            "external_status",
            "mapping_version",
            "source_version",
        ):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        canonical_status = _required_text(
            self.canonical_status, "canonical_status"
        ).lower()
        if canonical_status not in _CANONICAL_STATUSES:
            raise ValueError("qmt_canonical_status_unknown")
        object.__setattr__(self, "canonical_status", canonical_status)
        effective_from = _aware_utc(self.effective_from, "effective_from")
        available_at = _aware_utc(self.available_at, "available_at")
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "available_at", available_at)
        if self.effective_to is not None:
            effective_to = _aware_utc(self.effective_to, "effective_to")
            if effective_to <= effective_from:
                raise ValueError("qmt_status_effective_window_invalid")
            object.__setattr__(self, "effective_to", effective_to)

    def visible_for(self, *, event_time: datetime, as_of: datetime) -> bool:
        event_time = _aware_utc(event_time, "event_time")
        as_of = _aware_utc(as_of, "as_of")
        return (
            self.available_at <= as_of
            and self.effective_from <= event_time
            and (self.effective_to is None or event_time < self.effective_to)
        )


@dataclass(frozen=True)
class QMTFixtureCallback:
    callback_id: str
    callback_type: str
    sequence: int
    occurred_at: datetime
    received_at: datetime
    source_kind: str
    source_version: str
    payload: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "callback_id", _required_text(self.callback_id, "callback_id")
        )
        callback_type = _required_text(
            self.callback_type, "callback_type"
        ).lower()
        if callback_type not in _CALLBACK_TYPES:
            raise ValueError("qmt_callback_type_unknown")
        object.__setattr__(self, "callback_type", callback_type)
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ValueError("qmt_callback_sequence_invalid")
        occurred_at = _aware_utc(self.occurred_at, "occurred_at")
        received_at = _aware_utc(self.received_at, "received_at")
        if received_at < occurred_at:
            raise ValueError("qmt_callback_received_before_occurred")
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "received_at", received_at)
        source_kind = _required_text(self.source_kind, "source_kind")
        if source_kind not in _SOURCE_KINDS:
            raise ValueError("qmt_fixture_source_kind_unknown")
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(
            self,
            "source_version",
            _required_text(self.source_version, "source_version"),
        )
        normalized: list[tuple[str, object]] = []
        for key, value in self.payload:
            key = _required_text(key, "payload_key")
            lowered = key.lower()
            if any(marker in lowered for marker in _FORBIDDEN_PAYLOAD_KEY_MARKERS):
                raise ValueError("qmt_fixture_sensitive_field_forbidden")
            _canonical_value(value)
            normalized.append((key, value))
        if len({key for key, _ in normalized}) != len(normalized):
            raise ValueError("qmt_fixture_payload_key_duplicate")
        object.__setattr__(self, "payload", tuple(sorted(normalized)))

    @classmethod
    def from_mapping(
        cls,
        *,
        callback_id: str,
        callback_type: str,
        sequence: int,
        occurred_at: datetime,
        received_at: datetime,
        source_kind: str,
        source_version: str,
        payload: Mapping[str, object],
    ) -> QMTFixtureCallback:
        if not isinstance(payload, Mapping):
            raise TypeError("qmt_fixture_payload_mapping_required")
        return cls(
            callback_id=callback_id,
            callback_type=callback_type,
            sequence=sequence,
            occurred_at=occurred_at,
            received_at=received_at,
            source_kind=source_kind,
            source_version=source_version,
            payload=tuple(payload.items()),
        )

    @property
    def fingerprint(self) -> str:
        return canonical_qmt_sha256(self)


@dataclass(frozen=True)
class QMTNormalizedCallback:
    callback_id: str
    callback_type: str
    sequence: int
    occurred_at: datetime
    received_at: datetime
    fields: tuple[tuple[str, object], ...]
    source_kind: str
    source_version: str

    @property
    def field_map(self) -> dict[str, object]:
        return dict(self.fields)

    @property
    def fingerprint(self) -> str:
        return canonical_qmt_sha256(self)


@dataclass(frozen=True)
class QMTNormalizedBatch:
    callbacks: tuple[QMTNormalizedCallback, ...]
    duplicate_count: int
    first_sequence: int
    last_sequence: int

    @property
    def fingerprint(self) -> str:
        return canonical_qmt_sha256(self)


def _parse_decimal(value: object, canonical_field: str) -> Decimal:
    if isinstance(value, float) or isinstance(value, bool):
        raise _violation(
            "qmt_decimal_invalid",
            category="mapping",
            operation="normalize_callback",
            context={"field": canonical_field, "type": type(value).__name__},
        )
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise _violation(
            "qmt_decimal_invalid",
            category="mapping",
            operation="normalize_callback",
            context={"field": canonical_field, "type": type(value).__name__},
        ) from None
    if not decimal_value.is_finite():
        raise _violation(
            "qmt_decimal_invalid",
            category="mapping",
            operation="normalize_callback",
            context={"field": canonical_field, "non_finite": True},
        )
    return decimal_value


def _parse_integer(value: object, canonical_field: str) -> int:
    if isinstance(value, bool):
        raise _violation(
            "qmt_integer_invalid",
            category="mapping",
            operation="normalize_callback",
            context={"field": canonical_field, "type": "bool"},
        )
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise _violation(
        "qmt_integer_invalid",
        category="mapping",
        operation="normalize_callback",
        context={"field": canonical_field, "type": type(value).__name__},
    )


def _parse_timestamp(value: object, canonical_field: str) -> datetime:
    if isinstance(value, datetime):
        try:
            return _aware_utc(value, canonical_field)
        except (TypeError, ValueError):
            pass
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return _aware_utc(parsed, canonical_field)
        except ValueError:
            pass
    raise _violation(
        "qmt_timestamp_invalid",
        category="mapping",
        operation="normalize_callback",
        context={"field": canonical_field, "type": type(value).__name__},
    )


def _resolve_status(
    value: object,
    *,
    event_time: datetime,
    as_of: datetime,
    status_mappings: Sequence[QMTStatusMapping],
) -> str:
    if not isinstance(value, str):
        raise _violation(
            "qmt_unknown_order_status",
            category="mapping",
            operation="resolve_status",
            context={"type": type(value).__name__},
        )
    matches = [
        item
        for item in status_mappings
        if item.external_status == value
        and item.visible_for(event_time=event_time, as_of=as_of)
    ]
    if not matches:
        raise _violation(
            "qmt_unknown_order_status",
            category="mapping",
            operation="resolve_status",
            context={"external_status_sha256": canonical_qmt_sha256(value)},
        )
    if len(matches) != 1:
        raise _violation(
            "qmt_status_mapping_ambiguous",
            category="mapping",
            operation="resolve_status",
            context={
                "external_status_sha256": canonical_qmt_sha256(value),
                "match_count": len(matches),
            },
        )
    return matches[0].canonical_status


def _transform_value(
    value: object,
    mapping: QMTFieldMapping,
    *,
    event_time: datetime,
    as_of: datetime,
    status_mappings: Sequence[QMTStatusMapping],
) -> object:
    if mapping.value_kind == "decimal":
        return _parse_decimal(value, mapping.canonical_field)
    if mapping.value_kind == "integer":
        return _parse_integer(value, mapping.canonical_field)
    if mapping.value_kind == "sha256":
        try:
            return _sha256_text(value, mapping.canonical_field)
        except (TypeError, ValueError):
            raise _violation(
                "qmt_identity_hash_invalid",
                category="mapping",
                operation="normalize_callback",
                context={"field": mapping.canonical_field},
            ) from None
    if mapping.value_kind == "side":
        if not isinstance(value, str) or value.lower() not in {"buy", "sell"}:
            raise _violation(
                "qmt_side_mapping_unknown",
                category="mapping",
                operation="normalize_callback",
                context={"field": mapping.canonical_field},
            )
        return value.lower()
    if mapping.value_kind == "status":
        return _resolve_status(
            value,
            event_time=event_time,
            as_of=as_of,
            status_mappings=status_mappings,
        )
    if mapping.value_kind == "text":
        try:
            return _required_text(value, mapping.canonical_field)
        except (TypeError, ValueError):
            raise _violation(
                "qmt_text_mapping_invalid",
                category="mapping",
                operation="normalize_callback",
                context={"field": mapping.canonical_field},
            ) from None
    if mapping.value_kind == "timestamp":
        return _parse_timestamp(value, mapping.canonical_field)
    raise AssertionError("unreachable_qmt_value_kind")


def normalize_qmt_callback(
    callback: QMTFixtureCallback,
    *,
    field_mappings: Sequence[QMTFieldMapping],
    status_mappings: Sequence[QMTStatusMapping],
    as_of: datetime,
) -> QMTNormalizedCallback:
    as_of = _aware_utc(as_of, "as_of")
    payload = dict(callback.payload)
    visible = [
        item
        for item in field_mappings
        if item.callback_type == callback.callback_type
        and item.visible_for(event_time=callback.occurred_at, as_of=as_of)
    ]
    by_external: dict[str, list[QMTFieldMapping]] = {}
    for item in visible:
        by_external.setdefault(item.external_field, []).append(item)
    unknown = sorted(set(payload) - set(by_external))
    if unknown:
        raise _violation(
            "qmt_unmapped_field",
            category="mapping",
            operation="normalize_callback",
            context={
                "callback_type": callback.callback_type,
                "field_hashes": tuple(canonical_qmt_sha256(item) for item in unknown),
            },
        )
    required_missing = sorted(
        item.external_field
        for item in visible
        if item.required and item.external_field not in payload
    )
    if required_missing:
        raise _violation(
            "qmt_required_field_missing",
            category="mapping",
            operation="normalize_callback",
            context={
                "callback_type": callback.callback_type,
                "field_hashes": tuple(
                    canonical_qmt_sha256(item) for item in required_missing
                ),
            },
        )
    canonical: list[tuple[str, object]] = []
    for external_field, value in payload.items():
        matches = by_external[external_field]
        if len(matches) != 1:
            raise _violation(
                "qmt_field_mapping_ambiguous",
                category="mapping",
                operation="normalize_callback",
                context={
                    "field_sha256": canonical_qmt_sha256(external_field),
                    "match_count": len(matches),
                },
            )
        item = matches[0]
        canonical.append(
            (
                item.canonical_field,
                _transform_value(
                    value,
                    item,
                    event_time=callback.occurred_at,
                    as_of=as_of,
                    status_mappings=status_mappings,
                ),
            )
        )
    if len({name for name, _ in canonical}) != len(canonical):
        raise _violation(
            "qmt_canonical_field_duplicate",
            category="mapping",
            operation="normalize_callback",
            context={"callback_type": callback.callback_type},
        )
    canonical_map = dict(canonical)
    if callback.callback_type == "order":
        ordered_quantity = canonical_map.get("ordered_quantity")
        filled_quantity = canonical_map.get("filled_quantity")
        if (
            not isinstance(ordered_quantity, int)
            or ordered_quantity <= 0
            or not isinstance(filled_quantity, int)
            or filled_quantity < 0
            or filled_quantity > ordered_quantity
        ):
            raise _violation(
                "qmt_order_quantity_state_invalid",
                category="validation",
                operation="normalize_callback",
                context={
                    "ordered_quantity": ordered_quantity,
                    "filled_quantity": filled_quantity,
                },
            )
    else:
        quantity = canonical_map.get("quantity")
        price = canonical_map.get("price")
        fee = canonical_map.get("fee")
        if (
            not isinstance(quantity, int)
            or quantity <= 0
            or not isinstance(price, Decimal)
            or price <= 0
            or not isinstance(fee, Decimal)
            or fee < 0
        ):
            raise _violation(
                "qmt_fill_economics_invalid",
                category="validation",
                operation="normalize_callback",
                context={
                    "quantity": quantity,
                    "price": price,
                    "fee": fee,
                },
            )
    return QMTNormalizedCallback(
        callback_id=callback.callback_id,
        callback_type=callback.callback_type,
        sequence=callback.sequence,
        occurred_at=callback.occurred_at,
        received_at=callback.received_at,
        fields=tuple(sorted(canonical)),
        source_kind=callback.source_kind,
        source_version=callback.source_version,
    )


def normalize_qmt_callbacks(
    callbacks: Sequence[QMTFixtureCallback],
    *,
    first_sequence: int,
    field_mappings: Sequence[QMTFieldMapping],
    status_mappings: Sequence[QMTStatusMapping],
    as_of: datetime,
) -> QMTNormalizedBatch:
    if (
        not isinstance(first_sequence, int)
        or isinstance(first_sequence, bool)
        or first_sequence < 0
    ):
        raise ValueError("qmt_first_sequence_invalid")
    unique: dict[str, QMTFixtureCallback] = {}
    duplicate_count = 0
    for callback in callbacks:
        prior = unique.get(callback.callback_id)
        if prior is None:
            unique[callback.callback_id] = callback
        elif prior.fingerprint == callback.fingerprint:
            duplicate_count += 1
        else:
            raise _violation(
                "qmt_duplicate_callback_conflict",
                category="idempotency",
                operation="normalize_callbacks",
                context={"callback_id_sha256": canonical_qmt_sha256(callback.callback_id)},
            )
    ordered = sorted(unique.values(), key=lambda item: (item.sequence, item.callback_id))
    sequences = [item.sequence for item in ordered]
    expected = list(range(first_sequence, first_sequence + len(ordered)))
    if sequences != expected:
        raise _violation(
            "qmt_callback_sequence_gap_or_conflict",
            category="ordering",
            operation="normalize_callbacks",
            context={"actual": sequences, "expected": expected},
        )
    normalized = tuple(
        normalize_qmt_callback(
            callback,
            field_mappings=field_mappings,
            status_mappings=status_mappings,
            as_of=as_of,
        )
        for callback in ordered
    )
    last_sequence = first_sequence - 1 if not normalized else normalized[-1].sequence
    return QMTNormalizedBatch(
        callbacks=normalized,
        duplicate_count=duplicate_count,
        first_sequence=first_sequence,
        last_sequence=last_sequence,
    )


@dataclass(frozen=True)
class QMTReconciliationDifference:
    code: str
    identity_sha256: str
    expected_sha256: str
    observed_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, "code"))
        for name in (
            "identity_sha256",
            "expected_sha256",
            "observed_sha256",
        ):
            object.__setattr__(
                self,
                name,
                _sha256_text(getattr(self, name), name),
            )


@dataclass(frozen=True)
class QMTReconciliationDecision:
    fixture_status: str
    gate_status: str
    differences: tuple[QMTReconciliationDifference, ...]
    blockers: tuple[str, ...]
    safety_flags: tuple[tuple[str, bool], ...]

    @property
    def fixture_reconciled(self) -> bool:
        return not self.differences

    @property
    def promotion_eligible(self) -> bool:
        return False


def _difference(
    code: str, identity: object, expected: object, observed: object
) -> QMTReconciliationDifference:
    return QMTReconciliationDifference(
        code=code,
        identity_sha256=canonical_qmt_sha256(identity),
        expected_sha256=canonical_qmt_sha256(expected),
        observed_sha256=canonical_qmt_sha256(observed),
    )


def reconcile_qmt_fixture(
    *,
    batch: QMTNormalizedBatch,
    orders: Sequence[OrderState],
    ledger_result: ReconciliationResult,
) -> QMTReconciliationDecision:
    """Compare fixture callbacks with offline G06 state without unlocking runtime."""

    differences: list[QMTReconciliationDifference] = []
    order_callbacks: dict[str, dict[str, object]] = {}
    fill_callbacks: dict[str, dict[str, object]] = {}
    for callback in batch.callbacks:
        values = callback.field_map
        if callback.callback_type == "order":
            identity = values.get("client_order_id")
            if not isinstance(identity, str):
                differences.append(
                    _difference(
                        "qmt_order_identity_missing",
                        callback.callback_id,
                        "client_order_id",
                        identity,
                    )
                )
                continue
            order_callbacks[identity] = values
        else:
            identity = values.get("fill_id")
            if not isinstance(identity, str):
                differences.append(
                    _difference(
                        "qmt_fill_identity_missing",
                        callback.callback_id,
                        "fill_id",
                        identity,
                    )
                )
                continue
            if identity in fill_callbacks:
                differences.append(
                    _difference(
                        "qmt_fill_identity_duplicate",
                        identity,
                        "unique",
                        "duplicate",
                    )
                )
            fill_callbacks[identity] = values

    expected_order_ids = {state.intent.client_order_id for state in orders}
    for state in orders:
        identity = state.intent.client_order_id
        observed = order_callbacks.get(identity)
        expected = {
            "stable_security_id": state.intent.stable_security_id,
            "status": state.status,
            "ordered_quantity": state.intent.quantity,
            "filled_quantity": state.filled_quantity,
        }
        if observed is None:
            differences.append(
                _difference("qmt_order_callback_missing", identity, expected, None)
            )
        else:
            projected = {
                "stable_security_id": observed.get("stable_security_id"),
                "status": observed.get("status"),
                "ordered_quantity": observed.get("ordered_quantity"),
                "filled_quantity": observed.get("filled_quantity"),
            }
            if projected != expected:
                differences.append(
                    _difference(
                        "qmt_order_reconciliation_mismatch",
                        identity,
                        expected,
                        projected,
                    )
                )
        for fill in state.fills:
            fill_observed = fill_callbacks.get(fill.fill_id)
            fill_expected = {
                "client_order_id": identity,
                "stable_security_id": fill.stable_security_id,
                "side": fill.side,
                "quantity": fill.quantity,
                "price": fill.price,
                "fee": fill.total_fee,
                "occurred_at": fill.occurred_at,
            }
            if fill_observed is None:
                differences.append(
                    _difference(
                        "qmt_fill_callback_missing",
                        fill.fill_id,
                        fill_expected,
                        None,
                    )
                )
            else:
                fill_projected = {
                    "client_order_id": fill_observed.get("client_order_id"),
                    "stable_security_id": fill_observed.get("stable_security_id"),
                    "side": fill_observed.get("side"),
                    "quantity": fill_observed.get("quantity"),
                    "price": fill_observed.get("price"),
                    "fee": fill_observed.get("fee"),
                    "occurred_at": fill_observed.get("occurred_at"),
                }
                if fill_projected != fill_expected:
                    differences.append(
                        _difference(
                            "qmt_fill_reconciliation_mismatch",
                            fill.fill_id,
                            fill_expected,
                            fill_projected,
                        )
                    )

    for identity in sorted(set(order_callbacks) - expected_order_ids):
        differences.append(
            _difference(
                "qmt_unmatched_order_callback",
                identity,
                None,
                order_callbacks[identity],
            )
        )
    expected_fill_ids = {
        fill.fill_id for state in orders for fill in state.fills
    }
    for identity in sorted(set(fill_callbacks) - expected_fill_ids):
        differences.append(
            _difference(
                "qmt_unmatched_fill_callback",
                identity,
                None,
                fill_callbacks[identity],
            )
        )
    if ledger_result.blocks_gate or ledger_result.status != "reconciled":
        differences.append(
            _difference(
                "qmt_offline_ledger_reconciliation_unresolved",
                "ledger",
                "reconciled",
                {
                    "status": ledger_result.status,
                    "blockers": ledger_result.blockers,
                },
            )
        )
    differences = sorted(
        differences, key=lambda item: (item.code, item.identity_sha256)
    )
    blockers = list(QMT_REQUIRED_BLOCKERS)
    if differences:
        blockers.append("qmt_fixture_reconciliation_difference")
    return QMTReconciliationDecision(
        fixture_status="reconciled" if not differences else "difference",
        gate_status="blocked",
        differences=tuple(differences),
        blockers=tuple(sorted(set(blockers))),
        safety_flags=tuple(sorted(QMT_SAFETY_FLAGS.items())),
    )


@runtime_checkable
class QMTOfflineAdapterContract(Protocol):
    """The only adapter surface allowed by G08: injected fixture operations."""

    @property
    def contract_version(self) -> str: ...

    @property
    def safety_flags(self) -> Mapping[str, bool]: ...

    @property
    def runtime_capabilities(self) -> tuple[QMTRuntimeCapability, ...]: ...

    def bind_fixture(
        self,
        fixture: object,
        *,
        field_mappings: Sequence[QMTFieldMapping],
        status_mappings: Sequence[QMTStatusMapping],
        as_of: datetime,
    ) -> object: ...

    def reconcile_fixture(
        self,
        *,
        batch: QMTNormalizedBatch,
        orders: Sequence[OrderState],
        ledger_result: ReconciliationResult,
    ) -> QMTReconciliationDecision: ...


def qmt_contract_summary() -> dict[str, object]:
    return {
        "schema_version": CONTRACT_VERSION,
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "field_mapping_version": FIELD_MAPPING_VERSION,
        "status_mapping_version": STATUS_MAPPING_VERSION,
        "required_blockers": list(QMT_REQUIRED_BLOCKERS),
        "runtime_capabilities": [
            {
                "name": item.name,
                "blocker": item.blocker,
                "enabled": item.enabled,
                "authorized": item.authorized,
            }
            for item in qmt_runtime_capabilities()
        ],
        "safety_flags": dict(QMT_SAFETY_FLAGS),
        "runtime_eligible": False,
        "promotion_eligible": False,
    }
