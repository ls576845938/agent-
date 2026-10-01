"""Deterministic binding for injected synthetic or recorded QMT fixtures.

This module has no SDK discovery, import, connection, account, order, file, or
environment surface.  A recorded fixture is already-decoded, redacted input;
its presence is not evidence that any runtime capability is authorized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Sequence

from quant_cn.execution.models import OrderState
from quant_cn.execution.qmt_adapter_contract import (
    CONTRACT_VERSION,
    FIXTURE_SCHEMA_VERSION,
    QMT_REQUIRED_BLOCKERS,
    QMT_SAFETY_FLAGS,
    QMTContractViolation,
    QMTFieldMapping,
    QMTFixtureCallback,
    QMTNormalizedBatch,
    QMTOfflineAdapterContract,
    QMTReconciliationDecision,
    QMTRuntimeCapability,
    QMTStatusMapping,
    QMTStructuredError,
    canonical_qmt_sha256,
    normalize_qmt_callbacks,
    qmt_runtime_capabilities,
    reconcile_qmt_fixture,
)
from quant_cn.ledger.reconciliation import ReconciliationResult


BINDING_VERSION = "cn_qmt_sdk_fixture_binding_v1"
_SOURCE_KINDS = frozenset({"synthetic_fixture", "recorded_fixture"})
_RUNTIME_ACTION_NAMES = (
    "account_read",
    "broker_connected",
    "network_accessed",
    "order_cancelled",
    "order_submitted",
    "paper_queue_written",
    "private_accessed",
    "sdk_imported",
)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"qmt_fixture_field_missing:{field_name}")
    return value.strip()


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"qmt_fixture_datetime_required:{field_name}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"qmt_fixture_datetime_naive:{field_name}")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class QMTFixtureEnvelope:
    fixture_id: str
    source_kind: str
    source_version: str
    mapping_version: str
    available_at: datetime
    recorded_at: datetime
    first_sequence: int
    callbacks: tuple[QMTFixtureCallback, ...]
    payload_sha256: str
    redaction_attested: bool
    runtime_actions: tuple[tuple[str, bool], ...]
    schema_version: str = FIXTURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "fixture_id",
            "source_version",
            "mapping_version",
            "schema_version",
        ):
            object.__setattr__(
                self, name, _required_text(getattr(self, name), name)
            )
        source_kind = _required_text(self.source_kind, "source_kind")
        if source_kind not in _SOURCE_KINDS:
            raise ValueError("qmt_fixture_source_kind_unknown")
        object.__setattr__(self, "source_kind", source_kind)
        available_at = _aware_utc(self.available_at, "available_at")
        recorded_at = _aware_utc(self.recorded_at, "recorded_at")
        if available_at < recorded_at:
            raise ValueError("qmt_fixture_available_before_recorded")
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "recorded_at", recorded_at)
        if (
            not isinstance(self.first_sequence, int)
            or isinstance(self.first_sequence, bool)
            or self.first_sequence < 0
        ):
            raise ValueError("qmt_fixture_first_sequence_invalid")
        if type(self.redaction_attested) is not bool or not self.redaction_attested:
            raise ValueError("qmt_fixture_redaction_attestation_required")
        actions = tuple(sorted(self.runtime_actions))
        if tuple(name for name, _ in actions) != _RUNTIME_ACTION_NAMES:
            raise ValueError("qmt_fixture_runtime_action_set_invalid")
        if any(type(value) is not bool or value for _, value in actions):
            raise ValueError("qmt_fixture_runtime_action_attestation_invalid")
        object.__setattr__(self, "runtime_actions", actions)
        if not self.callbacks:
            raise ValueError("qmt_fixture_callbacks_required")
        for callback in self.callbacks:
            if callback.source_kind != self.source_kind:
                raise ValueError("qmt_fixture_callback_source_kind_mismatch")
            if callback.source_version != self.source_version:
                raise ValueError("qmt_fixture_callback_source_version_mismatch")
            if callback.received_at > available_at:
                raise ValueError("qmt_fixture_callback_after_available_time")
        if self.payload_sha256 != self.calculated_payload_sha256:
            raise ValueError("qmt_fixture_payload_hash_mismatch")

    @property
    def material(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "fixture_id": self.fixture_id,
            "source_kind": self.source_kind,
            "source_version": self.source_version,
            "mapping_version": self.mapping_version,
            "available_at": self.available_at,
            "recorded_at": self.recorded_at,
            "first_sequence": self.first_sequence,
            "callbacks": self.callbacks,
            "redaction_attested": self.redaction_attested,
            "runtime_actions": self.runtime_actions,
        }

    @property
    def calculated_payload_sha256(self) -> str:
        return canonical_qmt_sha256(self.material)

    @classmethod
    def create(
        cls,
        *,
        fixture_id: str,
        source_kind: str,
        source_version: str,
        mapping_version: str,
        available_at: datetime,
        recorded_at: datetime,
        first_sequence: int,
        callbacks: Sequence[QMTFixtureCallback],
        redaction_attested: bool = True,
        runtime_actions: Mapping[str, bool] | None = None,
    ) -> QMTFixtureEnvelope:
        actions = (
            {name: False for name in _RUNTIME_ACTION_NAMES}
            if runtime_actions is None
            else dict(runtime_actions)
        )
        material = {
            "schema_version": FIXTURE_SCHEMA_VERSION,
            "fixture_id": fixture_id,
            "source_kind": source_kind,
            "source_version": source_version,
            "mapping_version": mapping_version,
            "available_at": available_at,
            "recorded_at": recorded_at,
            "first_sequence": first_sequence,
            "callbacks": tuple(callbacks),
            "redaction_attested": redaction_attested,
            "runtime_actions": tuple(sorted(actions.items())),
        }
        return cls(
            fixture_id=fixture_id,
            source_kind=source_kind,
            source_version=source_version,
            mapping_version=mapping_version,
            available_at=available_at,
            recorded_at=recorded_at,
            first_sequence=first_sequence,
            callbacks=tuple(callbacks),
            payload_sha256=canonical_qmt_sha256(material),
            redaction_attested=redaction_attested,
            runtime_actions=tuple(sorted(actions.items())),
        )


@dataclass(frozen=True)
class QMTFixtureBindingDecision:
    fixture_id: str | None
    input_sha256: str
    fixture_eligible: bool
    runtime_eligible: bool
    gate_status: str
    normalized_batch: QMTNormalizedBatch | None
    errors: tuple[QMTStructuredError, ...]
    blockers: tuple[str, ...]
    safety_flags: tuple[tuple[str, bool], ...]

    @property
    def promotion_eligible(self) -> bool:
        return False


def _blocked(
    input_sha256: str,
    error: QMTStructuredError,
) -> QMTFixtureBindingDecision:
    return QMTFixtureBindingDecision(
        fixture_id=None,
        input_sha256=input_sha256,
        fixture_eligible=False,
        runtime_eligible=False,
        gate_status="blocked",
        normalized_batch=None,
        errors=(error,),
        blockers=tuple(sorted(set(QMT_REQUIRED_BLOCKERS + (error.code,)))),
        safety_flags=tuple(sorted(QMT_SAFETY_FLAGS.items())),
    )


def bind_qmt_fixture(
    fixture: QMTFixtureEnvelope,
    *,
    field_mappings: Sequence[QMTFieldMapping],
    status_mappings: Sequence[QMTStatusMapping],
    as_of: datetime,
) -> QMTFixtureBindingDecision:
    input_sha256 = fixture.payload_sha256
    try:
        as_of = _aware_utc(as_of, "as_of")
        if fixture.schema_version != FIXTURE_SCHEMA_VERSION:
            raise ValueError("qmt_fixture_schema_version_unknown")
        if fixture.available_at > as_of:
            raise ValueError("qmt_fixture_not_available")
        if any(callback.received_at > as_of for callback in fixture.callbacks):
            raise ValueError("qmt_fixture_callback_not_available")
        if fixture.calculated_payload_sha256 != fixture.payload_sha256:
            raise ValueError("qmt_fixture_payload_hash_mismatch")
        visible_field_versions = {
            item.mapping_version
            for item in field_mappings
            if item.available_at <= as_of
        }
        if fixture.mapping_version not in visible_field_versions:
            raise ValueError("qmt_fixture_field_mapping_version_missing")
        visible_status_versions = {
            item.mapping_version
            for item in status_mappings
            if item.available_at <= as_of
        }
        if visible_status_versions != {fixture.mapping_version}:
            raise ValueError("qmt_fixture_status_mapping_version_mismatch")
        batch = normalize_qmt_callbacks(
            fixture.callbacks,
            first_sequence=fixture.first_sequence,
            field_mappings=field_mappings,
            status_mappings=status_mappings,
            as_of=as_of,
        )
    except QMTContractViolation as error:
        return _blocked(input_sha256, error.error)
    except (TypeError, ValueError) as error:
        code = str(error)
        structured = QMTStructuredError(
            code=code,
            category="fixture_validation",
            operation="bind_fixture",
            context_sha256=canonical_qmt_sha256(
                {
                    "fixture_sha256": input_sha256,
                    "error_code": code,
                }
            ),
        )
        return _blocked(input_sha256, structured)
    return QMTFixtureBindingDecision(
        fixture_id=fixture.fixture_id,
        input_sha256=input_sha256,
        fixture_eligible=True,
        runtime_eligible=False,
        gate_status="blocked",
        normalized_batch=batch,
        errors=(),
        blockers=tuple(sorted(QMT_REQUIRED_BLOCKERS)),
        safety_flags=tuple(sorted(QMT_SAFETY_FLAGS.items())),
    )


class OfflineQMTFixtureAdapter(QMTOfflineAdapterContract):
    """Concrete pure adapter over injected fixture values only."""

    @property
    def contract_version(self) -> str:
        return CONTRACT_VERSION

    @property
    def safety_flags(self) -> Mapping[str, bool]:
        return dict(QMT_SAFETY_FLAGS)

    @property
    def runtime_capabilities(self) -> tuple[QMTRuntimeCapability, ...]:
        return qmt_runtime_capabilities()

    def bind_fixture(
        self,
        fixture: object,
        *,
        field_mappings: Sequence[QMTFieldMapping],
        status_mappings: Sequence[QMTStatusMapping],
        as_of: datetime,
    ) -> QMTFixtureBindingDecision:
        if not isinstance(fixture, QMTFixtureEnvelope):
            error = QMTStructuredError(
                code="qmt_fixture_envelope_required",
                category="fixture_validation",
                operation="bind_fixture",
                context_sha256=canonical_qmt_sha256(type(fixture).__name__),
            )
            return _blocked(canonical_qmt_sha256(type(fixture).__name__), error)
        return bind_qmt_fixture(
            fixture,
            field_mappings=field_mappings,
            status_mappings=status_mappings,
            as_of=as_of,
        )

    def reconcile_fixture(
        self,
        *,
        batch: QMTNormalizedBatch,
        orders: Sequence[OrderState],
        ledger_result: ReconciliationResult,
    ) -> QMTReconciliationDecision:
        return reconcile_qmt_fixture(
            batch=batch,
            orders=orders,
            ledger_result=ledger_result,
        )


def qmt_fixture_binding_summary() -> dict[str, object]:
    return {
        "schema_version": BINDING_VERSION,
        "fixture_schema_version": FIXTURE_SCHEMA_VERSION,
        "supported_source_kinds": sorted(_SOURCE_KINDS),
        "runtime_actions": {name: False for name in _RUNTIME_ACTION_NAMES},
        "required_blockers": list(QMT_REQUIRED_BLOCKERS),
        "safety_flags": dict(QMT_SAFETY_FLAGS),
        "fixture_only": True,
        "runtime_eligible": False,
        "promotion_eligible": False,
    }
