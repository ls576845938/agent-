"""Read-only orchestration for resolving and assessing CN DataReady versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from quant_cn.compat import (
    build_evidence_reference,
    build_freshness_assessment,
    build_read_model_snapshot,
)
from quant_cn.data.read_model import (
    CN_DATAREADY_EVIDENCE_FILE,
    CNDataReadModel,
    assess_cn_dataready,
)
from quant_cn.operations.blockers import (
    CN_DATAREADY_HANDOFF_INVALID,
    CN_DATAREADY_HANDOFF_MISSING,
    CN_DATAREADY_MANIFEST_MISSING,
    CN_DATAREADY_MANIFEST_RESOLVE_FAILED,
    blocker,
)
from tools.agent_governance.shared_data import (
    SharedDataError,
    resolve_manifest_file,
)


@dataclass(frozen=True)
class CNDataReadModelConsumption:
    model: CNDataReadModel
    shared_snapshot: object | None
    handoff_event_id: str
    manifest_source: str
    resolved_path: str
    consumer_read_only: bool = True

    def __post_init__(self) -> None:
        if self.consumer_read_only is not True:
            raise ValueError("cn_data_consumer_must_be_read_only")


def consume_cn_dataready(
    *,
    manifest_path: Path | None,
    shared_root: Path,
    handoff_event_id: str,
    handoff_validated: bool,
    evaluated_at: datetime,
    current_head: str,
    manifest_reference: str = "",
    maximum_common_date_age_days: int = 5,
    minimum_security_count: int = 3,
    minimum_coverage_ratio: float = 0.95,
) -> CNDataReadModelConsumption:
    """Resolve immutable bytes through ``shared_data`` and never write them."""

    evaluated = _aware_utc(evaluated_at, "evaluated_at")
    event_id = str(handoff_event_id).strip()
    if not event_id:
        return _missing_consumption(
            blocker(CN_DATAREADY_HANDOFF_MISSING),
            event_id="",
        )
    if handoff_validated is not True:
        return _missing_consumption(
            blocker(CN_DATAREADY_HANDOFF_INVALID, detail=event_id),
            event_id=event_id,
        )
    if manifest_path is None:
        return _missing_consumption(
            blocker(CN_DATAREADY_MANIFEST_MISSING),
            event_id=event_id,
        )
    manifest = Path(manifest_path)
    if not manifest.is_file():
        return _missing_consumption(
            blocker(CN_DATAREADY_MANIFEST_MISSING, detail=str(manifest)),
            event_id=event_id,
            manifest_source=manifest_reference or str(manifest),
        )

    try:
        manifest_bytes_before = manifest.read_bytes()
        resolved = resolve_manifest_file(
            manifest,
            shared_root=Path(shared_root),
            verify_files=True,
        )
        manifest_bytes = manifest.read_bytes()
        if manifest_bytes != manifest_bytes_before:
            raise ValueError("cn_dataready_manifest_changed_during_resolution")
        manifest_payload = _read_json_bytes(
            manifest_bytes,
            "cn_dataready_manifest_not_object",
        )
        evidence_path = resolved / CN_DATAREADY_EVIDENCE_FILE
        evidence_bytes = evidence_path.read_bytes()
        expected_evidence = next(
            (
                item
                for item in manifest_payload.get("files", ())
                if item.get("path") == CN_DATAREADY_EVIDENCE_FILE
            ),
            None,
        )
        if expected_evidence is None:
            raise ValueError("cn_dataready_evidence_file_not_declared")
        if (
            len(evidence_bytes) != int(expected_evidence["bytes"])
            or hashlib.sha256(evidence_bytes).hexdigest()
            != expected_evidence["sha256"]
        ):
            raise ValueError("cn_dataready_evidence_changed_during_resolution")
        evidence_payload = _read_json_bytes(
            evidence_bytes,
            "cn_dataready_evidence_not_object",
        )
    except (OSError, SharedDataError, ValueError) as exc:
        return _missing_consumption(
            blocker(
                CN_DATAREADY_MANIFEST_RESOLVE_FAILED,
                detail=str(exc),
            ),
            event_id=event_id,
            manifest_source=manifest_reference or str(manifest),
        )

    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    shared_identity = f"dataready.{manifest_hash[:24]}"
    model = assess_cn_dataready(
        manifest=manifest_payload,
        evidence=evidence_payload,
        manifest_sha256=manifest_hash,
        evaluated_at=evaluated,
        maximum_common_date_age_days=maximum_common_date_age_days,
        minimum_security_count=minimum_security_count,
        minimum_coverage_ratio=minimum_coverage_ratio,
    )
    published_at = _parse_aware_timestamp(
        str(manifest_payload.get("published_at", "")),
        "manifest.published_at",
    )
    evidence_reference = build_evidence_reference(
        evidence_id=shared_identity,
        path=manifest_reference or manifest.name,
        sha256=manifest_hash,
        schema_version=str(manifest_payload.get("schema_version", "")),
        generated_at=published_at,
        code_commit=str(manifest_payload.get("producer_commit", "")),
    )
    freshness = build_freshness_assessment(
        source_id=shared_identity,
        available=True,
        generated_at=evaluated,
        code_commit="",
        dependency_generated_at=(),
        current_head=current_head,
        evaluated_at=evaluated,
        max_age=timedelta(seconds=1),
    )
    shared_snapshot = build_read_model_snapshot(
        snapshot_id=shared_identity,
        generated_at=evaluated,
        code_commit=current_head,
        data_version=model.dataset_version,
        status=model.status,
        decision=model.decision,
        freshness=freshness,
        blockers=tuple(
            (item.code, item.owner, item.next_action, item.detail)
            for item in model.blockers
        ),
        evidence=(evidence_reference,),
        source_manifest_hash=manifest_hash,
    )
    return CNDataReadModelConsumption(
        model=model,
        shared_snapshot=shared_snapshot,
        handoff_event_id=event_id,
        manifest_source=manifest_reference or str(manifest),
        resolved_path=str(resolved),
    )


def _missing_consumption(
    *blockers,
    event_id: str,
    manifest_source: str = "",
) -> CNDataReadModelConsumption:
    return CNDataReadModelConsumption(
        model=CNDataReadModel.missing(blockers),
        shared_snapshot=None,
        handoff_event_id=event_id,
        manifest_source=manifest_source,
        resolved_path="",
    )


def _read_json_bytes(raw: bytes, object_error: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("cn_dataready_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError(object_error)
    return payload


def _parse_aware_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"timestamp_invalid:{field_name}") from exc
    return _aware_utc(parsed, field_name)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"timestamp_must_be_timezone_aware:{field_name}")
    return value.astimezone(timezone.utc)
