"""BTC-owned adapters over the asset-neutral Shared Platform V2 contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence
from uuid import uuid4

from quant_shared.core import StableIdentity, canonical_payload_hash, ensure_utc
from quant_shared.evidence import EvidenceReference, FreshnessAssessment
from quant_shared.ledger import LedgerRecord
from quant_shared.read_model import BlockerView, ReadModelSnapshot
from quant_shared.replay import ReplayEvent, ReplayInput, ReplaySnapshot


BTC_SHARED_BOUNDARY_VERSION = "btc_shared_platform_adapter_v1"


def new_btc_id(prefix: str) -> str:
    """Create a BTC runtime id while enforcing the shared identity grammar."""

    identity = StableIdentity(namespace="btc", value=f"{prefix}_{uuid4().hex[:16]}")
    return identity.value


def build_btc_evidence_reference(
    *,
    evidence_id: str,
    path: str,
    sha256: str,
    schema_version: str,
    generated_at_utc: datetime,
    code_commit: str,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=evidence_id,
        path=path,
        sha256=sha256,
        schema_version=schema_version,
        generated_at_utc=generated_at_utc,
        code_commit=code_commit,
    )


def build_btc_ledger_record(
    *,
    stream_id: str,
    record_id: str,
    sequence: int,
    occurred_at_utc: datetime,
    record_type: str,
    payload: Mapping[str, Any],
) -> LedgerRecord:
    """Adapt a BTC-owned lifecycle record without moving its semantics shared."""

    return LedgerRecord(
        stream_id=stream_id,
        record_id=record_id,
        sequence=sequence,
        occurred_at_utc=occurred_at_utc,
        record_type=record_type,
        payload=dict(payload),
    )


def build_btc_replay_input(
    *,
    fixed_clock_utc: datetime,
    random_seed: int,
    strategy_version: str,
    params: Mapping[str, Any],
    data_snapshot: Mapping[str, Any],
    risk_config: Mapping[str, Any],
    current_position: Mapping[str, Any],
    historical_orders: Sequence[Mapping[str, Any]],
    historical_fills: Sequence[Mapping[str, Any]],
) -> ReplayInput:
    """Adapt explicitly injected BTC history into the deterministic replay contract."""

    fixed_clock = ensure_utc(fixed_clock_utc)
    snapshot_hash = canonical_payload_hash(dict(data_snapshot))
    data_version = str(data_snapshot.get("data_version") or f"btc-snapshot-{snapshot_hash[:16]}")
    snapshot = ReplaySnapshot(
        snapshot_id=f"btc-snapshot-{snapshot_hash[:24]}",
        as_of_utc=fixed_clock,
        data_version=data_version,
        payload=dict(data_snapshot),
    )
    events: list[ReplayEvent] = []
    for event_type, rows in (
        ("btc_order", historical_orders),
        ("btc_fill", historical_fills),
    ):
        for row in rows:
            payload = dict(row)
            event_hash = canonical_payload_hash({"event_type": event_type, "payload": payload})
            events.append(
                ReplayEvent(
                    event_id=f"{event_type}-{event_hash[:24]}",
                    occurred_at_utc=_event_time(payload, fallback=fixed_clock),
                    event_type=event_type,
                    payload=payload,
                )
            )
    events.sort(key=lambda value: (value.occurred_at_utc, value.event_id))
    replay_payload = {
        "strategy_version": strategy_version,
        "params": dict(params),
        "risk_config": dict(risk_config),
        "current_position": dict(current_position),
        "snapshot_hash": snapshot_hash,
    }
    replay_hash = canonical_payload_hash(replay_payload)
    return ReplayInput(
        replay_id=f"btc-replay-{replay_hash[:24]}",
        fixed_clock_utc=fixed_clock,
        random_seed=random_seed,
        snapshots=(snapshot,),
        events=tuple(events),
        parameters=replay_payload,
    )


def build_btc_read_model_snapshot(
    *,
    snapshot_id: str,
    generated_at_utc: datetime,
    code_commit: str,
    data_version: str,
    status: str,
    decision: str,
    freshness: FreshnessAssessment,
    blockers: Sequence[BlockerView] = (),
    evidence: Sequence[EvidenceReference] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ReadModelSnapshot:
    return ReadModelSnapshot(
        snapshot_id=snapshot_id,
        domain_id="btc",
        generated_at_utc=generated_at_utc,
        code_commit=code_commit,
        data_version=data_version,
        status=status,
        decision=decision,
        freshness=freshness,
        blockers=tuple(blockers),
        evidence=tuple(evidence),
        metadata={
            "btc_shared_boundary_version": BTC_SHARED_BOUNDARY_VERSION,
            **dict(metadata or {}),
        },
    )


def _event_time(payload: Mapping[str, Any], *, fallback: datetime) -> datetime:
    for field_name in ("occurred_at_utc", "timestamp_utc", "decision_time", "fill_time"):
        value = payload.get(field_name)
        if isinstance(value, datetime):
            return ensure_utc(value)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            try:
                return ensure_utc(datetime.fromisoformat(text))
            except ValueError:
                continue
    return fallback
