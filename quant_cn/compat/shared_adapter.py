"""Fail-closed adapters from China-domain records to ``quant_shared`` v2.

The shared objects receive only asset-neutral identities, hashes, evidence
references, and lifecycle-independent state. China market semantics stay in
``quant_cn`` and are represented across this boundary by canonical hashes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from quant_shared import SHARED_PLATFORM_VERSION
from quant_shared.backtest import (
    BacktestEvidence,
    BacktestIdentity,
    validate_backtest_evidence,
)
from quant_shared.core import (
    StableIdentity,
    canonical_payload_hash,
    ensure_utc,
    isoformat_utc,
    validate_id,
)
from quant_shared.evidence import (
    EvidenceBundle,
    EvidenceReference,
    FreshnessAssessment,
    FreshnessSource,
    assess_freshness,
)
from quant_shared.ledger import (
    LedgerRecord,
    ReconciliationResult,
    reconcile_fingerprints,
)
from quant_shared.read_model import BlockerView, ReadModelSnapshot
from quant_shared.replay import (
    ReplayEvent,
    ReplayInput,
    ReplaySnapshot,
    validate_replay_input,
)


CN_SHARED_ADAPTER_VERSION = "cn_shared_platform_adapter_v1"
EXPECTED_SHARED_PLATFORM_VERSION = "shared_platform_v2"
CN_DOMAIN_ID = "cn_equity"

SAFETY_FLAGS: Mapping[str, bool] = MappingProxyType(
    {
        "promotion_eligible": False,
        "promotion_unlock_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "private_endpoint_allowed": False,
        "order_endpoint_allowed": False,
        "real_order_submitted": False,
    }
)

_IDENTITY_KINDS = frozenset(
    {
        "backtest",
        "evidence",
        "ledger",
        "read_model",
        "replay",
        "run",
        "security",
    }
)
_GENERIC_LEDGER_RECORD_TYPES = frozenset({"cash", "fill", "position", "reversal"})
_GENERIC_READ_MODEL_STATUSES = frozenset({"blocked", "degraded", "pass"})
_GENERIC_READ_MODEL_DECISIONS = frozenset(
    {"blocked", "quality_checked", "research_only"}
)


class SharedContractMismatch(RuntimeError):
    """Raised when the integrated shared contract cannot satisfy this adapter."""


def require_shared_platform_v2() -> str:
    if SHARED_PLATFORM_VERSION != EXPECTED_SHARED_PLATFORM_VERSION:
        raise SharedContractMismatch(
            "shared_platform_version_mismatch:"
            f"expected={EXPECTED_SHARED_PLATFORM_VERSION}:"
            f"actual={SHARED_PLATFORM_VERSION}"
        )
    return SHARED_PLATFORM_VERSION


def to_shared_utc(value: datetime, *, field_name: str = "timestamp") -> datetime:
    """Normalize aware timestamps while rejecting implicit timezone assumptions."""

    require_shared_platform_v2()
    if not isinstance(value, datetime):
        raise TypeError(f"datetime_required:{field_name}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"timezone_aware_timestamp_required:{field_name}")
    return ensure_utc(value)


def cn_identity(kind: str, value: str) -> StableIdentity:
    """Create a stable identity without placing CN enums in shared contracts."""

    require_shared_platform_v2()
    normalized_kind = validate_id(kind, field_name="identity_kind").lower()
    if normalized_kind not in _IDENTITY_KINDS:
        raise ValueError("cn_identity_kind_unknown")
    return StableIdentity(
        namespace=f"{CN_DOMAIN_ID}.{normalized_kind}",
        value=validate_id(value, field_name="identity_value"),
    )


def canonical_cn_payload_hash(payload: Mapping[str, Any]) -> str:
    """Hash domain payloads after deterministic Decimal and UTC adaptation."""

    require_shared_platform_v2()
    if not isinstance(payload, Mapping):
        raise TypeError("cn_payload_mapping_required")
    return canonical_payload_hash(_normalize_cn_value(payload))


def _normalize_cn_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("finite_decimal_required")
        return "0" if value == Decimal("0") else format(value.normalize(), "f")
    if isinstance(value, datetime):
        return isoformat_utc(to_shared_utc(value))
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_cn_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_normalize_cn_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"unsupported_cn_payload_value:{type(value).__name__}")


def build_evidence_reference(
    *,
    evidence_id: str,
    path: str,
    sha256: str,
    schema_version: str,
    generated_at: datetime,
    code_commit: str,
) -> EvidenceReference:
    require_shared_platform_v2()
    return EvidenceReference(
        evidence_id=cn_identity("evidence", evidence_id).qualified,
        path=path,
        sha256=sha256,
        schema_version=schema_version,
        generated_at_utc=to_shared_utc(
            generated_at,
            field_name="evidence.generated_at",
        ),
        code_commit=code_commit,
    )


def build_evidence_bundle(
    *,
    bundle_id: str,
    created_at: datetime,
    references: Sequence[EvidenceReference],
    data_version: str,
) -> EvidenceBundle:
    require_shared_platform_v2()
    if not str(data_version).strip():
        raise ValueError("data_version_required")
    return EvidenceBundle(
        bundle_id=cn_identity("evidence", bundle_id).qualified,
        created_at_utc=to_shared_utc(created_at, field_name="bundle.created_at"),
        references=tuple(references),
        metadata={
            "adapter_version": CN_SHARED_ADAPTER_VERSION,
            "data_version": str(data_version).strip(),
            "domain_id": CN_DOMAIN_ID,
        },
    )


def build_freshness_assessment(
    *,
    source_id: str,
    available: bool,
    generated_at: datetime | None,
    code_commit: str,
    dependency_generated_at: Sequence[datetime],
    current_head: str,
    evaluated_at: datetime,
    max_age: timedelta,
) -> FreshnessAssessment:
    require_shared_platform_v2()
    if not isinstance(available, bool):
        raise TypeError("freshness_available_must_be_bool")
    source = FreshnessSource(
        source_id=cn_identity("evidence", source_id).qualified,
        available=available,
        generated_at_utc=(
            to_shared_utc(generated_at, field_name="freshness.generated_at")
            if generated_at is not None
            else None
        ),
        code_commit=code_commit,
        dependency_generated_at_utc=tuple(
            to_shared_utc(item, field_name="freshness.dependency_generated_at")
            for item in dependency_generated_at
        ),
    )
    return assess_freshness(
        (source,),
        current_head=current_head,
        evaluated_at_utc=to_shared_utc(
            evaluated_at,
            field_name="freshness.evaluated_at",
        ),
        max_age=max_age,
    )


def build_ledger_record(
    *,
    stream_id: str,
    record_id: str,
    sequence: int,
    occurred_at: datetime,
    record_type: str,
    domain_record: Mapping[str, Any],
    evidence_ids: Sequence[str] = (),
) -> LedgerRecord:
    """Adapt a CN ledger row without exporting CN execution enums."""

    require_shared_platform_v2()
    normalized_type = str(record_type).strip().lower()
    if normalized_type not in _GENERIC_LEDGER_RECORD_TYPES:
        raise ValueError("shared_ledger_record_type_not_asset_neutral")
    return LedgerRecord(
        stream_id=cn_identity("ledger", stream_id).qualified,
        record_id=cn_identity("ledger", record_id).qualified,
        sequence=sequence,
        occurred_at_utc=to_shared_utc(
            occurred_at,
            field_name="ledger.occurred_at",
        ),
        record_type=normalized_type,
        payload={
            "adapter_version": CN_SHARED_ADAPTER_VERSION,
            "domain_id": CN_DOMAIN_ID,
            "domain_record_hash": canonical_cn_payload_hash(domain_record),
            "evidence_ids": tuple(
                cn_identity("evidence", item).qualified for item in evidence_ids
            ),
        },
    )


def reconcile_cn_ledger(
    expected_records: Sequence[LedgerRecord],
    actual_records: Sequence[LedgerRecord],
) -> ReconciliationResult:
    require_shared_platform_v2()
    expected = {item.record_id: item.fingerprint for item in expected_records}
    actual = {item.record_id: item.fingerprint for item in actual_records}
    if len(expected) != len(expected_records) or len(actual) != len(actual_records):
        raise ValueError("duplicate_ledger_record_id")
    return reconcile_fingerprints(expected, actual)


@dataclass(frozen=True)
class ReplaySnapshotAdapterInput:
    snapshot_id: str
    as_of: datetime
    data_version: str
    domain_payload: Mapping[str, Any]
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayEventAdapterInput:
    event_id: str
    occurred_at: datetime
    event_type: str
    domain_payload: Mapping[str, Any]
    evidence_ids: tuple[str, ...] = ()


def build_replay_input(
    *,
    replay_id: str,
    fixed_clock: datetime,
    random_seed: int,
    snapshots: Sequence[ReplaySnapshotAdapterInput],
    events: Sequence[ReplayEventAdapterInput],
    parameters: Mapping[str, Any],
) -> ReplayInput:
    """Build deterministic injected replay input with opaque domain payloads."""

    require_shared_platform_v2()
    shared_snapshots = tuple(
        ReplaySnapshot(
            snapshot_id=cn_identity("replay", item.snapshot_id).qualified,
            as_of_utc=to_shared_utc(item.as_of, field_name="replay.snapshot.as_of"),
            data_version=item.data_version,
            payload={
                "domain_payload_hash": canonical_cn_payload_hash(
                    item.domain_payload
                ),
                "evidence_ids": tuple(
                    cn_identity("evidence", value).qualified
                    for value in item.evidence_ids
                ),
            },
        )
        for item in snapshots
    )
    shared_events = tuple(
        ReplayEvent(
            event_id=cn_identity("replay", item.event_id).qualified,
            occurred_at_utc=to_shared_utc(
                item.occurred_at,
                field_name="replay.event.occurred_at",
            ),
            event_type=_asset_neutral_event_type(item.event_type),
            payload={
                "domain_payload_hash": canonical_cn_payload_hash(
                    item.domain_payload
                ),
                "evidence_ids": tuple(
                    cn_identity("evidence", value).qualified
                    for value in item.evidence_ids
                ),
            },
        )
        for item in events
    )
    replay_input = ReplayInput(
        replay_id=cn_identity("replay", replay_id).qualified,
        fixed_clock_utc=to_shared_utc(
            fixed_clock,
            field_name="replay.fixed_clock",
        ),
        random_seed=random_seed,
        snapshots=shared_snapshots,
        events=shared_events,
        parameters={
            "adapter_version": CN_SHARED_ADAPTER_VERSION,
            "domain_id": CN_DOMAIN_ID,
            "parameters_hash": canonical_cn_payload_hash(parameters),
        },
    )
    blockers = validate_replay_input(replay_input)
    if blockers:
        raise ValueError("replay_input_blocked:" + ",".join(blockers))
    return replay_input


def _asset_neutral_event_type(value: str) -> str:
    normalized = validate_id(value, field_name="event_type").lower()
    allowed = {"data", "fill", "order", "position", "risk", "signal", "target"}
    if normalized not in allowed:
        raise ValueError("shared_replay_event_type_not_asset_neutral")
    return normalized


def build_backtest_identity(
    *,
    run_id: str,
    strategy_version: str,
    data_version: str,
    parameters: Mapping[str, Any],
    code_commit: str,
) -> BacktestIdentity:
    require_shared_platform_v2()
    return BacktestIdentity(
        run_id=cn_identity("backtest", run_id).qualified,
        strategy_version=strategy_version,
        data_version=data_version,
        params_hash=canonical_cn_payload_hash(parameters),
        code_commit=code_commit,
    )


def build_backtest_evidence(
    *,
    cost_model: str,
    slippage_model: str,
    decision_time_rule: str,
    execution_time_rule: str,
    candidate_count: int,
    trial_count: int,
    walk_forward_valid: bool,
    no_lookahead_valid: bool,
    ledger_reconciled: bool,
    ledger_hash: str,
    replay_hash: str,
    current_head_match: bool,
    blockers: Sequence[str] = (),
) -> BacktestEvidence:
    require_shared_platform_v2()
    evidence = BacktestEvidence(
        cost_model=cost_model,
        slippage_model=slippage_model,
        decision_time_rule=decision_time_rule,
        execution_time_rule=execution_time_rule,
        candidate_count=candidate_count,
        trial_count=trial_count,
        walk_forward_valid=walk_forward_valid,
        no_lookahead_valid=no_lookahead_valid,
        ledger_reconciled=ledger_reconciled,
        pnl_source="ledger_derived",
        ledger_hash=ledger_hash,
        replay_hash=replay_hash,
        current_head_match=current_head_match,
        blockers=tuple(str(item) for item in blockers),
    )
    validation_blockers = validate_backtest_evidence(evidence)
    return (
        replace(evidence, blockers=validation_blockers)
        if evidence.blockers != validation_blockers
        else evidence
    )


def build_read_model_snapshot(
    *,
    snapshot_id: str,
    generated_at: datetime,
    code_commit: str,
    data_version: str,
    status: str,
    decision: str,
    freshness: FreshnessAssessment,
    blockers: Sequence[tuple[str, str, str, str]],
    evidence: Sequence[EvidenceReference],
    source_manifest_hash: str,
) -> ReadModelSnapshot:
    """Project a CN status into an asset-neutral, immutable read-model envelope."""

    require_shared_platform_v2()
    normalized_status = str(status).strip().lower()
    normalized_decision = str(decision).strip().lower()
    if normalized_status not in _GENERIC_READ_MODEL_STATUSES:
        raise ValueError("shared_read_model_status_not_asset_neutral")
    if normalized_decision not in _GENERIC_READ_MODEL_DECISIONS:
        raise ValueError("shared_read_model_decision_not_asset_neutral")
    if len(source_manifest_hash) != 64:
        raise ValueError("source_manifest_hash_must_be_sha256")
    blocker_views = tuple(
        BlockerView(
            code=validate_id(code, field_name="blocker.code"),
            owner=owner,
            next_action=next_action,
            detail=detail,
        )
        for code, owner, next_action, detail in blockers
    )
    return ReadModelSnapshot(
        snapshot_id=cn_identity("read_model", snapshot_id).qualified,
        domain_id=CN_DOMAIN_ID,
        generated_at_utc=to_shared_utc(
            generated_at,
            field_name="read_model.generated_at",
        ),
        code_commit=code_commit,
        data_version=data_version,
        status=normalized_status,
        decision=normalized_decision,
        freshness=freshness,
        blockers=blocker_views,
        evidence=tuple(evidence),
        metadata={
            "adapter_version": CN_SHARED_ADAPTER_VERSION,
            "source_manifest_hash": source_manifest_hash,
        },
    )
