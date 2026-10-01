from __future__ import annotations

import hashlib
import json
import math
import zlib
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    SharedDataError,
    aggregate_inventory_hash,
    resolve_manifest_payload,
    validate_manifest,
)


REPORT_SCHEMA_VERSION = "btc_dataready_consumption_report_v1"
RUNTIME_POINTER_SCHEMA_VERSION = "mutable_runtime_storage_pointer_v1"
SNAPSHOT_DATASET_ID = "btc-market-data-sqlite-snapshot"
L2_DATASET_ID = "btc-okx-timestamp-aligned-public-l2-history"
KLINE_ATTESTATION_PATH = "btc_kline_dataready_attestation.json"
L2_ATTESTATION_PATH = "btc_okx_l2_dataready_attestation.json"
KLINE_ATTESTATION_SCHEMA_VERSION = "btc_kline_dataready_attestation_v1"
L2_ATTESTATION_SCHEMA_VERSION = "btc_okx_l2_dataready_attestation_v1"
KLINE_MANIFEST_DATA_SCHEMA = KLINE_ATTESTATION_SCHEMA_VERSION
L2_MANIFEST_DATA_SCHEMA = L2_ATTESTATION_SCHEMA_VERSION
L2_INTER_MESSAGE_GAP_POLICY_ID = "btc_okx_l2_inter_message_gap_v1"
L2_APPROVED_MAX_INTER_MESSAGE_GAP_SECONDS = 5.0
L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS = 0.1
L2_CAPTURE_DURATION_TOLERANCE_SECONDS = 0.2
L2_NUMERIC_TOLERANCE_SECONDS = 1e-6
L2_PERCENT_TOLERANCE = 1e-6
GOVERNED_MAX_FRESHNESS_SLA_HOURS = 48.0
GOVERNED_MIN_COVERAGE_PCT = 99.0
GOVERNED_MAX_L2_CLOCK_OFFSET_MS = 1_000.0
GOVERNED_PAYLOAD_MAX_ADJUSTED_MAGNITUDE = 18
GOVERNED_PAYLOAD_MIN_ADJUSTED_MAGNITUDE = -18
GOVERNED_PAYLOAD_MAX_DECIMAL_PLACES = 18
L2_OBSERVED_HISTORY_POLICY = (
    "sum_min_receive_monotonic_contiguous_deltas_excluding_"
    "reconnect_idle_and_unobserved_endpoint_gaps"
)
L2_ATTESTATION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "btc_okx_l2_dataready_attestation.schema.json"
)
KLINE_ATTESTATION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "schemas"
    / "btc_kline_dataready_attestation.schema.json"
)
APPROVED_CURRENT_MAIN_REQUIRED_PARTITIONS = {
    ("binance_spot", "BTCUSDT", "1m"),
    ("binance_spot", "BTCUSDT", "5m"),
    ("binance_spot", "BTCUSDT", "15m"),
    ("binance_spot", "BTCUSDT", "1h"),
}
REQUIRED_MISSING_BLOCKERS = [
    "immutable_snapshot_not_published",
    "data_steward_attestation_required",
]
READINESS_CLASS_RANK = {
    "quality_checked": 1,
    "research_ready": 2,
    "backtest_ready": 3,
    "promotion_evidence_ready": 4,
}


def _attestation_readiness_rank(attestation: object) -> int:
    if not isinstance(attestation, Mapping):
        return 0
    readiness = attestation.get("readiness")
    if not isinstance(readiness, Mapping):
        return 0
    ordered = (
        "quality_checked",
        "research_ready",
        "backtest_ready",
        "promotion_evidence_ready",
    )
    rank = 0
    seen_false = False
    for index, field in enumerate(ordered, start=1):
        value = readiness.get(field)
        if value is True:
            if seen_false:
                return -1
            rank = index
        elif value is False:
            seen_false = True
        else:
            return -1
    return rank


def _readiness_consistency_blockers(
    manifest: object,
    attestation: object,
    *,
    prefix: str,
) -> list[str]:
    if not isinstance(manifest, Mapping):
        return []
    manifest_rank = READINESS_CLASS_RANK.get(
        str(manifest.get("readiness_class", "")),
        0,
    )
    attestation_rank = _attestation_readiness_rank(attestation)
    if manifest_rank != attestation_rank:
        return [f"{prefix}_manifest_attestation_readiness_mismatch"]
    return []


def consume_btc_dataready(
    *,
    runtime_pointer: Mapping[str, Any] | None,
    snapshot_manifest: Mapping[str, Any] | None,
    l2_manifest: Mapping[str, Any] | None,
    shared_root: Path,
    current_head: str,
    now: datetime,
    commit_exists: Callable[[str], bool],
    snapshot_manifest_source: str = "",
    l2_manifest_source: str = "",
    freshness_sla_hours: float = 48.0,
    min_coverage_pct: float = 99.0,
    max_l2_clock_offset_ms: float = 1_000.0,
) -> dict[str, Any]:
    checked_at = _as_utc(now)
    (
        policy_blockers,
        effective_freshness_sla_hours,
        effective_min_coverage_pct,
        effective_max_l2_clock_offset_ms,
    ) = _validate_consumer_policy(
        freshness_sla_hours=freshness_sla_hours,
        min_coverage_pct=min_coverage_pct,
        max_l2_clock_offset_ms=max_l2_clock_offset_ms,
    )
    blockers: list[str] = list(policy_blockers)

    pointer_check = _validate_runtime_pointer(runtime_pointer)
    blockers.extend(pointer_check["blockers"])

    snapshot_check = _consume_manifest(
        manifest=snapshot_manifest,
        expected_dataset_id=SNAPSHOT_DATASET_ID,
        expected_attestation_path=KLINE_ATTESTATION_PATH,
        expected_data_schema=KLINE_MANIFEST_DATA_SCHEMA,
        shared_root=shared_root,
        commit_exists=commit_exists,
        manifest_source=snapshot_manifest_source,
    )
    blockers.extend(snapshot_check["blockers"])

    l2_check = _consume_manifest(
        manifest=l2_manifest,
        expected_dataset_id=L2_DATASET_ID,
        expected_attestation_path=L2_ATTESTATION_PATH,
        expected_data_schema=L2_MANIFEST_DATA_SCHEMA,
        shared_root=shared_root,
        commit_exists=commit_exists,
        manifest_source=l2_manifest_source,
    )
    blockers.extend(l2_check["blockers"])

    kline_check = _validate_kline_attestation(
        snapshot_check.get("attestation"),
        manifest=snapshot_manifest,
        now=checked_at,
        freshness_sla_hours=effective_freshness_sla_hours,
        min_coverage_pct=effective_min_coverage_pct,
        resolved_root=(
            Path(snapshot_check["resolved_path"])
            if snapshot_check.get("resolved_path")
            else None
        ),
        commit_exists=commit_exists,
        current_head=current_head,
    )
    blockers.extend(kline_check["blockers"])

    order_book_check = _validate_l2_attestation(
        l2_check.get("attestation"),
        manifest=l2_manifest,
        now=checked_at,
        freshness_sla_hours=effective_freshness_sla_hours,
        min_coverage_pct=effective_min_coverage_pct,
        max_clock_offset_ms=effective_max_l2_clock_offset_ms,
        resolved_root=(
            Path(l2_check["resolved_path"])
            if l2_check.get("resolved_path")
            else None
        ),
        commit_exists=commit_exists,
        current_head=current_head,
    )
    blockers.extend(order_book_check["blockers"])
    blockers.extend(
        _readiness_consistency_blockers(
            snapshot_manifest,
            snapshot_check.get("attestation"),
            prefix="kline",
        )
    )
    blockers.extend(
        _readiness_consistency_blockers(
            l2_manifest,
            l2_check.get("attestation"),
            prefix="l2",
        )
    )
    blockers = _dedupe(blockers)

    quality_checked = not blockers
    manifest_ranks = [
        READINESS_CLASS_RANK.get(str(item.get("readiness_class", "")), 0)
        for item in (snapshot_manifest, l2_manifest)
        if isinstance(item, Mapping)
    ]
    attestation_ranks = [
        _attestation_readiness_rank(item)
        for item in (
            snapshot_check.get("attestation"),
            l2_check.get("attestation"),
        )
    ]
    research_ready = (
        quality_checked
        and len(manifest_ranks) == 2
        and len(attestation_ranks) == 2
        and all(rank >= 2 for rank in manifest_ranks)
        and all(rank >= 2 for rank in attestation_ranks)
    )
    backtest_ready = (
        quality_checked
        and research_ready
        and all(rank >= 3 for rank in manifest_ranks)
        and all(rank >= 3 for rank in attestation_ranks)
    )

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": checked_at.isoformat().replace("+00:00", "Z"),
        "current_head": current_head,
        "status": "quality_checked" if quality_checked else "blocked",
        "decision": (
            "consume_immutable_data_read_only"
            if quality_checked
            else "block_dataready_consumption_fail_closed"
        ),
        "runtime_pointer": pointer_check,
        "expected_datasets": {
            "kline_snapshot": SNAPSHOT_DATASET_ID,
            "okx_timestamp_aligned_public_l2": L2_DATASET_ID,
        },
        "manifest_checks": {
            "kline_snapshot": _public_manifest_check(snapshot_check),
            "okx_timestamp_aligned_public_l2": _public_manifest_check(l2_check),
        },
        "data_checks": {
            "klines": kline_check,
            "okx_public_l2": order_book_check,
        },
        "readiness": {
            "quality_checked": quality_checked,
            "research_ready": research_ready,
            "backtest_ready": backtest_ready,
            "promotion_evidence_ready": False,
        },
        "promotion_blockers": [
            "dataready_manifest_is_not_current_head_promotion_evidence",
            "promotion_requires_strategy_risk_oms_fill_ledger_audit_gate_chain",
        ],
        "blockers": blockers,
        "next_action": (
            "consume immutable versions through the resolved read-only paths"
            if quality_checked
            else "data_steward must publish both immutable datasets and attestations, then integrate their manifests"
        ),
        "guardrails": {
            "mutable_sqlite_consumed": False,
            "network_collection_used": False,
            "shared_data_published_by_consumer": False,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "withdraw_allowed": False,
        },
    }


def _validate_runtime_pointer(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(payload, Mapping):
        return {
            "status": "missing",
            "dataset_id": SNAPSHOT_DATASET_ID,
            "publication_status": "",
            "blockers": [*REQUIRED_MISSING_BLOCKERS, "btc_runtime_storage_pointer_missing"],
        }
    if payload.get("schema_version") != RUNTIME_POINTER_SCHEMA_VERSION:
        blockers.append("btc_runtime_storage_pointer_schema_mismatch")
    if payload.get("owner_role") != "data_steward":
        blockers.append("btc_runtime_storage_pointer_owner_invalid")
    publication = payload.get("immutable_publication")
    if not isinstance(publication, Mapping):
        blockers.extend(REQUIRED_MISSING_BLOCKERS)
        publication = {}
    if publication.get("dataset_id") != SNAPSHOT_DATASET_ID:
        blockers.append("btc_runtime_storage_pointer_dataset_id_mismatch")
    if publication.get("status") != "published":
        blockers.extend(str(item) for item in publication.get("blockers", []) if str(item))
        blockers.extend(REQUIRED_MISSING_BLOCKERS)
    guardrails = payload.get("guardrails")
    if not isinstance(guardrails, Mapping):
        blockers.append("btc_runtime_storage_pointer_guardrails_missing")
    else:
        if guardrails.get("runtime_database_is_promotion_evidence") is not False:
            blockers.append("mutable_sqlite_must_not_be_promotion_evidence")
        for key in (
            "promotion_unlock_allowed",
            "paper_or_live_unlock_allowed",
            "private_endpoint_used",
            "order_endpoint_used",
        ):
            if guardrails.get(key) is not False:
                blockers.append(f"btc_runtime_storage_pointer_unsafe:{key}")
    blockers = _dedupe(blockers)
    return {
        "status": "pass" if not blockers else "blocked",
        "dataset_id": str(publication.get("dataset_id", SNAPSHOT_DATASET_ID)),
        "publication_status": str(publication.get("status", "")),
        "blockers": blockers,
    }


def _validate_consumer_policy(
    *,
    freshness_sla_hours: object,
    min_coverage_pct: object,
    max_l2_clock_offset_ms: object,
) -> tuple[list[str], float, float, float]:
    blockers: list[str] = []
    freshness = _strict_finite_number(freshness_sla_hours)
    coverage = _strict_finite_number(min_coverage_pct)
    clock = _strict_finite_number(max_l2_clock_offset_ms)
    if (
        freshness is None
        or freshness <= 0
        or freshness > GOVERNED_MAX_FRESHNESS_SLA_HOURS
    ):
        blockers.append("consumer_freshness_policy_invalid_or_too_wide")
        freshness = GOVERNED_MAX_FRESHNESS_SLA_HOURS
    if (
        coverage is None
        or coverage < GOVERNED_MIN_COVERAGE_PCT
        or coverage > 100.0
    ):
        blockers.append("consumer_coverage_policy_invalid_or_too_wide")
        coverage = 100.0
    if (
        clock is None
        or clock < 0
        or clock > GOVERNED_MAX_L2_CLOCK_OFFSET_MS
    ):
        blockers.append("consumer_clock_policy_invalid_or_too_wide")
        clock = 0.0
    return blockers, freshness, coverage, clock


def _strict_finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _consume_manifest(
    *,
    manifest: Mapping[str, Any] | None,
    expected_dataset_id: str,
    expected_attestation_path: str,
    expected_data_schema: str,
    shared_root: Path,
    commit_exists: Callable[[str], bool],
    manifest_source: str,
) -> dict[str, Any]:
    if not isinstance(manifest, Mapping):
        blockers = ["immutable_manifest_not_published", "data_steward_attestation_required"]
        if expected_dataset_id == SNAPSHOT_DATASET_ID:
            blockers.insert(0, "immutable_snapshot_not_published")
        else:
            blockers.insert(0, "okx_timestamp_aligned_l2_manifest_not_published")
        return {
            "status": "missing",
            "dataset_id": expected_dataset_id,
            "dataset_version": "",
            "manifest_source": manifest_source,
            "immutable_uri": "",
            "resolved_path": "",
            "blockers": blockers,
            "attestation": None,
        }

    blockers = list(validate_manifest(manifest))
    if blockers:
        blockers.insert(0, "manifest_schema_mismatch")
    if manifest.get("dataset_id") != expected_dataset_id:
        blockers.append("manifest_dataset_id_mismatch")
    if manifest.get("producer_role") != "data_steward":
        blockers.append("manifest_producer_must_be_data_steward")
    if manifest.get("data_schema") != expected_data_schema:
        blockers.append("manifest_data_schema_mismatch")
    producer_commit = str(manifest.get("producer_commit", ""))
    if not producer_commit or not commit_exists(producer_commit):
        blockers.append("manifest_producer_commit_unavailable")
    version = str(manifest.get("dataset_version", ""))
    if not _is_immutable_version(version):
        blockers.append("manifest_version_not_immutable")
    immutable_uri = str(manifest.get("storage_relative_path", ""))
    if immutable_uri != f"datasets/{expected_dataset_id}/{version}":
        blockers.append("manifest_immutable_uri_mismatch")
    if manifest.get("quality_status") != "pass":
        blockers.append("manifest_quality_status_not_pass")
        blockers.extend(str(item) for item in manifest.get("blockers", []) if str(item))

    attestation: Mapping[str, Any] | None = None
    resolved_path = ""
    if not blockers:
        try:
            resolved = resolve_manifest_payload(manifest, shared_root=shared_root, verify_files=True)
            resolved_path = str(resolved)
            attestation_file = next(
                (
                    item
                    for item in manifest.get("files", [])
                    if isinstance(item, Mapping) and item.get("path") == expected_attestation_path
                ),
                None,
            )
            if attestation_file is None:
                blockers.append("data_steward_attestation_required")
            else:
                attestation = _read_json_object(resolved / expected_attestation_path)
        except SharedDataError as exc:
            errors = str(exc).split(";")
            blockers.extend(errors)
            if any("hash_mismatch" in item for item in errors):
                blockers.append("manifest_hash_mismatch")
        except (OSError, ValueError, json.JSONDecodeError):
            blockers.append("data_steward_attestation_unreadable")

    blockers = _dedupe(blockers)
    return {
        "status": "pass" if not blockers else "blocked",
        "dataset_id": str(manifest.get("dataset_id", expected_dataset_id)),
        "dataset_version": version,
        "manifest_source": manifest_source,
        "immutable_uri": immutable_uri,
        "resolved_path": resolved_path,
        "aggregate_sha256": str(manifest.get("aggregate_sha256", "")),
        "producer_commit": producer_commit,
        "readiness_class": str(manifest.get("readiness_class", "")),
        "blockers": blockers,
        "attestation": attestation,
    }


def _validate_kline_attestation(
    attestation: Mapping[str, Any] | None,
    *,
    manifest: Mapping[str, Any] | None,
    now: datetime,
    freshness_sla_hours: float,
    min_coverage_pct: float,
    resolved_root: Path | None = None,
    commit_exists: Callable[[str], bool] = lambda _: True,
    current_head: str = "",
) -> dict[str, Any]:
    if not isinstance(attestation, Mapping):
        return {
            "status": "blocked",
            "common_end": "",
            "freshness_age_hours": None,
            "blockers": ["data_steward_attestation_required"],
        }
    blockers = _attestation_identity_blockers(
        attestation,
        manifest=manifest,
        expected_schema=KLINE_ATTESTATION_SCHEMA_VERSION,
    )
    blockers.extend(_kline_schema_blockers(attestation))
    blockers.extend(
        _attestation_source_head_blockers(
            attestation,
            manifest=manifest,
            commit_exists=commit_exists,
            current_head=current_head,
            prefix="kline",
        )
    )
    if attestation.get("timezone") != "UTC":
        blockers.append("kline_timezone_must_be_utc")
    if attestation.get("pit_available_time_enforced") is not True:
        blockers.append("kline_pit_available_time_not_enforced")
    if attestation.get("in_progress_excluded_from_consumption") is not True:
        blockers.append("kline_in_progress_rows_not_excluded")
    if attestation.get("event_time_field") != "event_time":
        blockers.append("kline_event_time_field_missing")
    if attestation.get("available_time_field") != "available_time":
        blockers.append("kline_available_time_field_missing")
    if attestation.get("finalized_field") != "is_finalized":
        blockers.append("kline_finalized_field_missing")
    if attestation.get("quality_checked") is not True:
        blockers.append("kline_quality_checked_required")
    if attestation.get("promotion_evidence_ready") is not False:
        blockers.append("kline_promotion_evidence_must_remain_false")
    readiness = attestation.get("readiness")
    if not isinstance(readiness, Mapping) or dict(readiness) != {
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
    }:
        blockers.append("kline_readiness_must_remain_fail_closed")
    promotion_blockers = attestation.get("promotion_blockers")
    if (
        not isinstance(promotion_blockers, list)
        or "btc_execution_latency_model_missing" not in promotion_blockers
        or "btc_queue_model_missing" not in promotion_blockers
    ):
        blockers.append("kline_required_promotion_blockers_missing")
    guardrails = attestation.get("guardrails")
    if not isinstance(guardrails, Mapping):
        blockers.append("kline_guardrails_invalid")
    else:
        for key in (
            "source_sqlite_mutated",
            "sqlite_payload_emitted",
            "network_collection_used",
            "shared_data_published",
            "promotion_unlock_allowed",
            "paper_or_live_unlock_allowed",
            "private_endpoint_used",
            "order_endpoint_used",
            "broker_call_used",
            "real_order_submitted",
        ):
            if guardrails.get(key) is not False:
                blockers.append(f"kline_guardrail_not_false:{key}")
    common_end = _parse_utc_timestamp(attestation.get("common_end"))
    if common_end is None:
        blockers.append("kline_common_end_invalid")
    coverage_start = _parse_utc_timestamp(attestation.get("coverage_start"))
    coverage_end = _parse_utc_timestamp(attestation.get("coverage_end"))
    if coverage_start is None or coverage_end is None or (
        coverage_start is not None and coverage_end is not None and coverage_start > coverage_end
    ):
        blockers.append("kline_coverage_window_invalid")
    if coverage_end is not None and common_end != coverage_end:
        blockers.append("kline_common_end_coverage_end_mismatch")
    if isinstance(manifest, Mapping):
        manifest_coverage = manifest.get("coverage")
        if not isinstance(manifest_coverage, Mapping) or (
            manifest_coverage.get("start") != attestation.get("coverage_start")
            or manifest_coverage.get("end") != attestation.get("coverage_end")
        ):
            blockers.append("kline_manifest_coverage_mismatch")
    effective_common_end = (
        min(common_end, coverage_end)
        if common_end is not None and coverage_end is not None
        else None
    )
    freshness_age = _age_hours(now, effective_common_end)
    if freshness_age is None or freshness_age < 0 or freshness_age > freshness_sla_hours:
        blockers.append("kline_freshness_sla_breached")
    declared_freshness_sla = _float_or_none(
        attestation.get("freshness_sla_hours")
    )
    declared_freshness_age = _float_or_none(
        attestation.get("freshness_age_hours")
    )
    generated_at = _parse_utc_timestamp(attestation.get("generated_at"))
    computed_declared_age = (
        _age_hours(generated_at, effective_common_end)
        if generated_at is not None
        else None
    )
    if (
        declared_freshness_sla is None
        or not math.isfinite(declared_freshness_sla)
        or declared_freshness_sla <= 0
        or declared_freshness_sla > freshness_sla_hours
        or declared_freshness_sla > GOVERNED_MAX_FRESHNESS_SLA_HOURS
    ):
        blockers.append("kline_declared_freshness_sla_invalid")
    if (
        declared_freshness_age is None
        or not math.isfinite(declared_freshness_age)
        or computed_declared_age is None
        or computed_declared_age < 0
        or abs(declared_freshness_age - computed_declared_age) > 1e-6
    ):
        blockers.append("kline_declared_freshness_age_mismatch")

    intervals = attestation.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        blockers.append("kline_interval_attestations_missing")
        intervals = []
    interval_partitions: list[tuple[str, str, str]] = []
    interval_coverage_starts: list[datetime] = []
    interval_finalized_total = 0
    interval_finalized_by_key: dict[tuple[str, str, str], int] = {}
    interval_window_by_key: dict[
        tuple[str, str, str],
        tuple[datetime, datetime],
    ] = {}
    for item in intervals:
        if not isinstance(item, Mapping):
            blockers.append("kline_interval_attestation_invalid")
            continue
        partition_key = _kline_partition_key(item)
        if partition_key is None:
            blockers.append("kline_interval_partition_invalid")
        else:
            interval_partitions.append(partition_key)
        interval = str(item.get("interval", "unknown"))
        coverage_pct = _float_or_none(item.get("coverage_pct"))
        if (
            coverage_pct is None
            or not math.isfinite(coverage_pct)
            or coverage_pct < min_coverage_pct
            or coverage_pct > 100.0
        ):
            blockers.append(f"kline_partial_coverage:{interval}")
        missing_count = _int_or_none(item.get("missing_count"))
        duplicate_count = _int_or_none(item.get("duplicate_count"))
        finalized_count = _int_or_none(item.get("finalized_count"))
        if missing_count != 0:
            blockers.append(f"kline_missing_rows:{interval}")
        if duplicate_count != 0:
            blockers.append(f"kline_duplicate_rows:{interval}")
        if finalized_count is None or finalized_count <= 0:
            blockers.append(f"kline_finalized_rows_missing:{interval}")
        else:
            interval_finalized_total += finalized_count
            if partition_key is not None:
                interval_finalized_by_key[partition_key] = finalized_count
        if item.get("in_progress_excluded") is not True:
            blockers.append(f"kline_in_progress_rows_not_excluded:{interval}")
        item_coverage_start = _parse_utc_timestamp(item.get("coverage_start"))
        item_coverage_end = _parse_utc_timestamp(item.get("coverage_end"))
        if item_coverage_start is None or item_coverage_end is None:
            blockers.append(f"kline_interval_window_invalid:{interval}")
        else:
            interval_coverage_starts.append(item_coverage_start)
            if partition_key is not None:
                interval_window_by_key[partition_key] = (
                    item_coverage_start,
                    item_coverage_end,
                )
            if item_coverage_end != common_end:
                blockers.append(f"kline_interval_coverage_end_mismatch:{interval}")
        item_common_end = _parse_utc_timestamp(item.get("common_end"))
        if common_end is None or item_common_end != common_end:
            blockers.append(f"kline_common_end_mismatch:{interval}")
    if (
        coverage_start is not None
        and interval_coverage_starts
        and coverage_start != min(interval_coverage_starts)
    ):
        blockers.append("kline_coverage_start_interval_mismatch")

    selection = attestation.get("partition_selection")
    selected_partition_set: set[tuple[str, str, str]] = set()
    excluded_partition_set: set[tuple[str, str, str]] = set()
    policy_id = ""
    if not isinstance(selection, Mapping):
        blockers.append("kline_partition_selection_missing")
    else:
        mode = str(selection.get("mode", ""))
        policy_id = str(selection.get("policy_id", ""))
        if mode not in {
            "all_source_partitions",
            "explicit_required_partitions",
        }:
            blockers.append("kline_partition_selection_mode_invalid")
        if policy_id not in {
            "all_source_partitions_strict_v1",
            "explicit_required_partitions_v1",
            "btc_v3_current_main_binance_spot_required_v1",
        }:
            blockers.append("kline_partition_selection_policy_invalid")
        required = selection.get("required_partitions")
        included = selection.get("included_partitions")
        excluded = selection.get("excluded_partitions")
        if (
            not isinstance(required, list)
            or not required
            or not isinstance(included, list)
            or not included
            or not isinstance(excluded, list)
        ):
            blockers.append("kline_partition_selection_invalid")
        else:
            required_keys = [_kline_partition_key(item) for item in required]
            included_keys = [_kline_partition_key(item) for item in included]
            excluded_keys = [_kline_partition_key(item) for item in excluded]
            if (
                any(key is None for key in required_keys)
                or any(key is None for key in included_keys)
                or any(key is None for key in excluded_keys)
                or any(
                    not isinstance(item, Mapping)
                    or item.get("reason") != "excluded_non_required"
                    for item in excluded
                )
            ):
                blockers.append("kline_partition_selection_invalid")
            else:
                required_set = set(required_keys)
                included_set = set(included_keys)
                excluded_set = set(excluded_keys)
                selected_partition_set = {
                    key for key in included_set if key is not None
                }
                excluded_partition_set = {
                    key for key in excluded_set if key is not None
                }
                interval_set = set(interval_partitions)
                if (
                    len(required_set) != len(required_keys)
                    or len(included_set) != len(included_keys)
                    or len(excluded_set) != len(excluded_keys)
                    or required_set != included_set
                    or required_set != interval_set
                    or included_set & excluded_set
                    or (
                        mode == "all_source_partitions"
                        and bool(excluded_set)
                    )
                ):
                    blockers.append("kline_required_partition_set_mismatch")
                contains_current_main_binance = any(
                    key is not None
                    and key[0] == "binance_spot"
                    and key[1] == "BTCUSDT"
                    for key in required_set | excluded_set
                )
                if contains_current_main_binance:
                    if (
                        policy_id
                        != "btc_v3_current_main_binance_spot_required_v1"
                    ):
                        blockers.append(
                            "kline_approved_current_main_policy_required"
                        )
                    if (
                        required_set
                        != APPROVED_CURRENT_MAIN_REQUIRED_PARTITIONS
                    ):
                        blockers.append(
                            "kline_approved_current_main_required_set_mismatch"
                        )

    lineage = attestation.get("lineage")
    source_time_semantics = attestation.get("source_time_semantics")
    if not isinstance(lineage, Mapping):
        blockers.append("kline_lineage_invalid")
    elif source_time_semantics == "explicit_event_available_finalized_fields":
        expected_lineage = {
            "explicit_time_derivation_used": False,
            "explicit_finalized_derivation_used": False,
            "source_event_time_field": "event_time",
            "source_available_time_field": "available_time",
            "source_finalized_policy": "explicit_is_finalized",
            "source_close_time_validation_policy": (
                "not_applicable_explicit_time_contract"
            ),
        }
        if any(lineage.get(key) != value for key, value in expected_lineage.items()):
            blockers.append("kline_lineage_time_semantics_mismatch")
    elif source_time_semantics == "derived_from_close_time":
        expected_lineage = {
            "explicit_time_derivation_used": True,
            "explicit_finalized_derivation_used": True,
            "source_event_time_field": "close_time",
            "source_available_time_field": "close_time",
            "source_finalized_policy": "close_time_lte_generated_at",
            "source_close_time_ms_field": "close_time_ms",
            "source_close_time_validation_policy": (
                "close_time_ms_equals_iso_epoch_ms_and_inclusive_interval_end"
            ),
        }
        if any(lineage.get(key) != value for key, value in expected_lineage.items()):
            blockers.append("kline_lineage_time_semantics_mismatch")
    else:
        blockers.append("kline_source_time_semantics_invalid")

    inventory = attestation.get("source_partition_inventory")
    inventory_hash = attestation.get("source_partition_inventory_sha256")
    if not isinstance(inventory, list) or not inventory:
        blockers.append("kline_source_partition_inventory_missing")
    elif not isinstance(inventory_hash, str):
        blockers.append("kline_source_partition_inventory_hash_invalid")
    else:
        expected_inventory_hash = _canonical_json_sha256(inventory)
        if inventory_hash != expected_inventory_hash:
            blockers.append("kline_source_partition_inventory_hash_mismatch")
        inventory_keys: list[tuple[str, str, str]] = []
        source_sha256 = (
            str(lineage.get("source_sha256", ""))
            if isinstance(lineage, Mapping)
            else ""
        )
        for item in inventory:
            key = _kline_partition_key(item)
            if key is None or not isinstance(item, Mapping):
                blockers.append("kline_source_partition_inventory_invalid")
                continue
            inventory_keys.append(key)
            item_without_hash = dict(item)
            item_hash = item_without_hash.pop("partition_inventory_sha256", None)
            if item_hash != _canonical_json_sha256(item_without_hash):
                blockers.append(
                    f"kline_partition_inventory_hash_mismatch:{':'.join(key)}"
                )
            total_count = _int_or_none(item.get("total_row_count"))
            finalized_count = _int_or_none(item.get("finalized_count"))
            in_progress_count = _int_or_none(item.get("in_progress_count"))
            if (
                total_count is None
                or finalized_count is None
                or in_progress_count is None
                or total_count <= 0
                or finalized_count < 0
                or in_progress_count < 0
                or finalized_count + in_progress_count != total_count
                or item.get("source_sha256") != source_sha256
            ):
                blockers.append(
                    f"kline_partition_inventory_counts_or_lineage_invalid:{':'.join(key)}"
                )
            inventory_start = _parse_utc_timestamp(item.get("coverage_start"))
            inventory_end = _parse_utc_timestamp(item.get("common_end"))
            inventory_freshness = _float_or_none(
                item.get("freshness_age_hours")
            )
            computed_inventory_freshness = (
                _age_hours(generated_at, inventory_end)
                if generated_at is not None
                else None
            )
            if (
                inventory_start is None
                or inventory_end is None
                or inventory_start > inventory_end
                or inventory_freshness is None
                or not math.isfinite(inventory_freshness)
                or computed_inventory_freshness is None
                or abs(
                    inventory_freshness - computed_inventory_freshness
                )
                > 1e-6
            ):
                blockers.append(
                    f"kline_partition_inventory_window_invalid:{':'.join(key)}"
                )
            if key in selected_partition_set:
                if (
                    item.get("selection_status") != "included_required"
                    or item.get("selection_policy") != policy_id
                ):
                    blockers.append(
                        f"kline_partition_inventory_policy_mismatch:{':'.join(key)}"
                    )
                if finalized_count != interval_finalized_by_key.get(key):
                    blockers.append(
                        f"kline_partition_inventory_interval_total_mismatch:{':'.join(key)}"
                    )
                if (
                    inventory_start,
                    inventory_end,
                ) != interval_window_by_key.get(key):
                    blockers.append(
                        f"kline_partition_inventory_interval_window_mismatch:{':'.join(key)}"
                    )
            elif key in excluded_partition_set:
                if (
                    item.get("selection_status") != "excluded_non_required"
                    or item.get("selection_policy") != policy_id
                ):
                    blockers.append(
                        f"kline_partition_inventory_policy_mismatch:{':'.join(key)}"
                    )
            else:
                blockers.append(
                    f"kline_partition_inventory_unclassified:{':'.join(key)}"
                )
        if (
            len(set(inventory_keys)) != len(inventory_keys)
            or set(inventory_keys)
            != selected_partition_set | excluded_partition_set
        ):
            blockers.append("kline_source_partition_inventory_set_mismatch")

    payload_check = _validate_immutable_table_payload(
        attestation,
        manifest=manifest,
        resolved_root=resolved_root,
        attestation_path=KLINE_ATTESTATION_PATH,
        kind="kline",
        checked_at=now,
    )
    blockers.extend(payload_check["blockers"])
    actual_row_count = payload_check["actual_row_count"]
    if actual_row_count is not None and actual_row_count != interval_finalized_total:
        blockers.append("kline_payload_interval_row_total_mismatch")

    blockers = _dedupe(blockers)
    return {
        "status": "pass" if not blockers else "blocked",
        "common_end": (
            effective_common_end.isoformat().replace("+00:00", "Z")
            if effective_common_end
            else ""
        ),
        "freshness_age_hours": round(freshness_age, 6) if freshness_age is not None else None,
        "interval_count": len(intervals),
        "blockers": blockers,
    }


def _kline_partition_key(value: Any) -> tuple[str, str, str] | None:
    if not isinstance(value, Mapping):
        return None
    key = (
        str(value.get("venue", "")),
        str(value.get("instrument_id", "")),
        str(value.get("interval", "")),
    )
    if not all(key):
        return None
    return key


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_l2_attestation(
    attestation: Mapping[str, Any] | None,
    *,
    manifest: Mapping[str, Any] | None,
    now: datetime,
    freshness_sla_hours: float,
    min_coverage_pct: float,
    max_clock_offset_ms: float,
    resolved_root: Path | None = None,
    commit_exists: Callable[[str], bool] = lambda _: True,
    current_head: str = "",
) -> dict[str, Any]:
    if not isinstance(attestation, Mapping):
        return {
            "status": "blocked",
            "common_end": "",
            "freshness_age_hours": None,
            "blockers": ["data_steward_attestation_required"],
        }
    blockers = _attestation_identity_blockers(
        attestation,
        manifest=manifest,
        expected_schema=L2_ATTESTATION_SCHEMA_VERSION,
    )
    blockers.extend(_l2_schema_blockers(attestation))
    blockers.extend(
        _attestation_source_head_blockers(
            attestation,
            manifest=manifest,
            commit_exists=commit_exists,
            current_head=current_head,
            prefix="l2",
        )
    )
    if attestation.get("venue") != "okx":
        blockers.append("l2_venue_must_be_okx")
    if attestation.get("instrument_id") != "BTC-USDT-SWAP":
        blockers.append("l2_instrument_must_be_btc_usdt_swap")
    if attestation.get("channel") != "books":
        blockers.append("l2_channel_must_be_public_books")
    if attestation.get("timezone") != "UTC":
        blockers.append("l2_timezone_must_be_utc")
    if attestation.get("event_time_field") != "event_time":
        blockers.append("l2_event_time_field_missing")
    if attestation.get("snapshot_time_field") != "snapshot_time":
        blockers.append("l2_snapshot_time_field_missing")
    if attestation.get("available_time_field") != "available_time":
        blockers.append("l2_available_time_field_missing")
    if attestation.get("sequence_validation_status") != "pass":
        blockers.append("l2_sequence_validation_failed")
    sequence_gap_count = _int_or_none(
        attestation.get("sequence_gap_count")
    )
    if sequence_gap_count is None or sequence_gap_count != 0:
        blockers.append("l2_sequence_gap_detected")
    unrecovered_gap_count = _int_or_none(
        attestation.get("unrecovered_gap_count")
    )
    if unrecovered_gap_count is None or unrecovered_gap_count != 0:
        blockers.append("l2_unrecovered_gap_detected")
    for field in (
        "duplicate_sequence_count",
        "out_of_order_sequence_count",
    ):
        if _int_or_none(attestation.get(field)) != 0:
            blockers.append(f"l2_{field}_nonzero")
    if (
        attestation.get("checksum_policy")
        != "nonzero_crc32_validated_zero_accepted_after_okx_deprecation"
    ):
        blockers.append("l2_checksum_policy_invalid")
    checksum_observed_count = _int_or_none(
        attestation.get("checksum_observed_count")
    )
    checksum_validated_count = _int_or_none(
        attestation.get("checksum_validated_count")
    )
    if checksum_observed_count is None or checksum_observed_count < 1:
        blockers.append("l2_checksum_observed_count_invalid")
    if (
        checksum_validated_count is None
        or checksum_validated_count < 0
        or checksum_observed_count is None
        or checksum_validated_count > checksum_observed_count
    ):
        blockers.append("l2_checksum_validated_count_invalid")
    if attestation.get("quality_checked") is not True:
        blockers.append("l2_quality_checked_required")
    if attestation.get("promotion_evidence_ready") is not False:
        blockers.append("l2_promotion_evidence_must_remain_false")
    readiness = attestation.get("readiness")
    if not isinstance(readiness, Mapping):
        blockers.append("l2_readiness_invalid")
    else:
        expected_readiness = {
            "quality_checked": True,
            "research_ready": False,
            "backtest_ready": False,
            "promotion_evidence_ready": False,
        }
        if dict(readiness) != expected_readiness:
            blockers.append("l2_readiness_must_remain_fail_closed")
    promotion_blockers = attestation.get("promotion_blockers")
    required_promotion_blockers = {
        "btc_execution_latency_model_missing",
        "btc_queue_model_missing",
    }
    if (
        not isinstance(promotion_blockers, list)
        or not required_promotion_blockers.issubset(
            {str(item) for item in promotion_blockers}
        )
    ):
        blockers.append("l2_required_promotion_blockers_missing")
    guardrails = attestation.get("guardrails")
    if not isinstance(guardrails, Mapping):
        blockers.append("l2_guardrails_invalid")
    else:
        for key in (
            "source_segments_mutated",
            "database_payload_emitted",
            "network_collection_used",
            "shared_data_published",
            "promotion_unlock_allowed",
            "paper_or_live_unlock_allowed",
            "private_endpoint_used",
            "order_endpoint_used",
            "broker_call_used",
            "real_order_submitted",
        ):
            if guardrails.get(key) is not False:
                blockers.append(f"l2_guardrail_not_false:{key}")
    if attestation.get("event_snapshot_time_order_valid") is not True:
        blockers.append("l2_event_snapshot_time_order_invalid")
    two_sided_coverage_pct = _float_or_none(
        attestation.get("two_sided_coverage_pct")
    )
    if (
        two_sided_coverage_pct is None
        or not math.isfinite(two_sided_coverage_pct)
        or two_sided_coverage_pct < min_coverage_pct
    ):
        blockers.append("l2_partial_two_sided_coverage")
    two_sided_snapshot_count = _int_or_none(
        attestation.get("two_sided_snapshot_count")
    )
    if (
        two_sided_snapshot_count is None
        or two_sided_snapshot_count <= 0
    ):
        blockers.append("l2_two_sided_snapshots_missing")
    observed_clock_offset_ms = _float_or_none(
        attestation.get("max_clock_offset_ms")
    )
    if (
        observed_clock_offset_ms is None
        or not math.isfinite(observed_clock_offset_ms)
        or abs(observed_clock_offset_ms) > max_clock_offset_ms
    ):
        blockers.append("l2_clock_offset_exceeds_limit")
    max_clock_lag_policy_ms = _float_or_none(
        attestation.get("max_clock_lag_policy_ms")
    )
    if (
        max_clock_lag_policy_ms is None
        or not math.isfinite(max_clock_lag_policy_ms)
        or max_clock_lag_policy_ms <= 0
    ):
        blockers.append("l2_clock_lag_policy_invalid")
    elif (
        observed_clock_offset_ms is not None
        and math.isfinite(observed_clock_offset_ms)
        and observed_clock_offset_ms > max_clock_lag_policy_ms
    ):
        blockers.append("l2_clock_offset_exceeds_attested_policy")
    if attestation.get("clock_offset_attested") is not True:
        blockers.append("l2_clock_offset_attestation_missing")
    max_inter_message_gap_seconds = _float_or_none(
        attestation.get("max_inter_message_gap_seconds")
    )
    if (
        max_inter_message_gap_seconds is None
        or not math.isfinite(max_inter_message_gap_seconds)
        or max_inter_message_gap_seconds <= 0
    ):
        blockers.append("l2_max_inter_message_gap_seconds_invalid")
    elif (
        max_inter_message_gap_seconds
        > L2_APPROVED_MAX_INTER_MESSAGE_GAP_SECONDS
    ):
        blockers.append(
            "l2_max_inter_message_gap_exceeds_governed_ceiling"
        )
    if (
        attestation.get("inter_message_gap_policy_id")
        != L2_INTER_MESSAGE_GAP_POLICY_ID
    ):
        blockers.append("l2_inter_message_gap_policy_unknown")
    if (
        _float_or_none(
            attestation.get("approved_max_inter_message_gap_seconds")
        )
        != L2_APPROVED_MAX_INTER_MESSAGE_GAP_SECONDS
    ):
        blockers.append("l2_inter_message_gap_ceiling_invalid")
    if (
        _float_or_none(
            attestation.get("endpoint_anchor_tolerance_seconds")
        )
        != L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS
    ):
        blockers.append("l2_endpoint_anchor_tolerance_invalid")
    if (
        _float_or_none(
            attestation.get("capture_duration_tolerance_seconds")
        )
        != L2_CAPTURE_DURATION_TOLERANCE_SECONDS
    ):
        blockers.append("l2_capture_duration_tolerance_invalid")
    if (
        attestation.get("observed_history_policy")
        != L2_OBSERVED_HISTORY_POLICY
    ):
        blockers.append("l2_observed_history_policy_invalid")
    common_start = _parse_utc_timestamp(attestation.get("common_start"))
    common_end = _parse_utc_timestamp(attestation.get("common_end"))
    if common_start is None:
        blockers.append("l2_common_start_invalid")
    if common_end is None:
        blockers.append("l2_common_end_invalid")
    if (
        common_start is not None
        and common_end is not None
        and common_start > common_end
    ):
        blockers.append("l2_common_window_invalid")
    coverage_start = _parse_utc_timestamp(attestation.get("coverage_start"))
    coverage_end = _parse_utc_timestamp(attestation.get("coverage_end"))
    if coverage_start is None or coverage_end is None or (
        coverage_start is not None and coverage_end is not None and coverage_start > coverage_end
    ):
        blockers.append("l2_coverage_window_invalid")
    observed_history_seconds = _float_or_none(
        attestation.get("observed_history_seconds")
    )
    history_window_days = _float_or_none(
        attestation.get("history_window_days")
    )
    coverage_span_days = _float_or_none(attestation.get("coverage_span_days"))
    expected_span_seconds = (
        (coverage_end - coverage_start).total_seconds()
        if coverage_start is not None and coverage_end is not None
        else None
    )
    if (
        observed_history_seconds is None
        or not math.isfinite(observed_history_seconds)
        or observed_history_seconds < 0
        or expected_span_seconds is None
        or observed_history_seconds > expected_span_seconds + 1e-6
    ):
        blockers.append("l2_observed_history_invalid")
    if (
        history_window_days is None
        or not math.isfinite(history_window_days)
        or observed_history_seconds is None
        or abs(history_window_days - observed_history_seconds / 86_400.0)
        > 1e-8
    ):
        blockers.append("l2_history_window_derivation_invalid")
    if (
        coverage_span_days is None
        or not math.isfinite(coverage_span_days)
        or expected_span_seconds is None
        or abs(coverage_span_days - expected_span_seconds / 86_400.0)
        > 1e-8
    ):
        blockers.append("l2_coverage_span_derivation_invalid")
    if isinstance(manifest, Mapping):
        manifest_coverage = manifest.get("coverage")
        if not isinstance(manifest_coverage, Mapping) or (
            manifest_coverage.get("start") != attestation.get("coverage_start")
            or manifest_coverage.get("end") != attestation.get("coverage_end")
        ):
            blockers.append("l2_manifest_coverage_mismatch")
    freshness_age: float | None = None
    gap_windows = attestation.get("gap_windows")
    recovered_gap_seconds = 0.0
    computed_unrecovered_gap_count = 0
    gap_count_by_segment: dict[str, int] = {}
    gap_seconds_by_segment: dict[str, float] = {}
    gap_ranges_by_segment: dict[
        str,
        list[tuple[datetime, datetime]],
    ] = {}
    if not isinstance(gap_windows, list):
        blockers.append("l2_gap_windows_invalid")
    else:
        for item in gap_windows:
            if not isinstance(item, Mapping) or item.get("recovered") is not True:
                blockers.append("l2_gap_window_unrecovered")
                computed_unrecovered_gap_count += 1
                continue
            segment_name = item.get("segment_name")
            if not isinstance(segment_name, str) or not segment_name:
                blockers.append("l2_gap_window_segment_invalid")
                continue
            from_connection_sequence = _int_or_none(
                item.get("from_connection_sequence")
            )
            to_connection_sequence = _int_or_none(
                item.get("to_connection_sequence")
            )
            if (
                from_connection_sequence is None
                or to_connection_sequence is None
                or from_connection_sequence < 1
                or to_connection_sequence
                != from_connection_sequence + 1
            ):
                blockers.append(
                    "l2_gap_window_connection_transition_invalid"
                )
            duration_seconds = _float_or_none(item.get("duration_seconds"))
            gap_start = _parse_utc_timestamp(item.get("gap_start"))
            gap_end = _parse_utc_timestamp(item.get("gap_end"))
            if (
                duration_seconds is None
                or not math.isfinite(duration_seconds)
                or duration_seconds < 0
            ):
                blockers.append("l2_gap_window_duration_invalid")
            else:
                recovered_gap_seconds += duration_seconds
                gap_count_by_segment[segment_name] = (
                    gap_count_by_segment.get(segment_name, 0) + 1
                )
                gap_seconds_by_segment[segment_name] = (
                    gap_seconds_by_segment.get(segment_name, 0.0)
                    + duration_seconds
                )
            if (
                gap_start is None
                or gap_end is None
                or gap_start > gap_end
            ):
                blockers.append("l2_gap_window_time_invalid")
            elif (
                duration_seconds is not None
                and math.isfinite(duration_seconds)
                and abs(
                    (gap_end - gap_start).total_seconds()
                    - duration_seconds
                )
                > L2_NUMERIC_TOLERANCE_SECONDS
            ):
                blockers.append("l2_gap_window_duration_mismatch")
            else:
                gap_ranges_by_segment.setdefault(
                    segment_name,
                    [],
                ).append((gap_start, gap_end))
        if unrecovered_gap_count != computed_unrecovered_gap_count:
            blockers.append("l2_unrecovered_gap_count_mismatch")
    if (
        recovered_gap_seconds > 0
        and two_sided_coverage_pct is not None
        and math.isfinite(two_sided_coverage_pct)
        and two_sided_coverage_pct >= 100.0
    ):
        blockers.append("l2_gap_not_reflected_in_coverage")

    source_segments = attestation.get("source_segments")
    conservative_source_cap_seconds = 0.0
    total_books_row_count = 0
    first_raw_receive_endpoint: datetime | None = None
    last_raw_receive_endpoint: datetime | None = None
    max_segment_clock_offset_ms = 0.0
    source_lineage: list[dict[str, str]] = []
    source_totals = {
        "snapshot_count": 0,
        "update_count": 0,
        "output_record_count": 0,
        "observed_reconnect_count": 0,
    }
    if not isinstance(source_segments, list) or not source_segments:
        blockers.append("l2_source_segments_missing")
    else:
        segment_count = _int_or_none(attestation.get("segment_count"))
        if segment_count is None or segment_count != len(source_segments):
            blockers.append("l2_source_segment_count_mismatch")
        previous_capture_end: datetime | None = None
        source_names: set[str] = set()
        for item in source_segments:
            if not isinstance(item, Mapping):
                blockers.append("l2_source_segment_invalid")
                continue
            segment_name = item.get("segment_name")
            if (
                not isinstance(segment_name, str)
                or not segment_name
                or segment_name in source_names
            ):
                blockers.append("l2_source_segment_name_invalid")
                continue
            source_names.add(segment_name)
            raw_sha256 = item.get("raw_sha256")
            manifest_sha256 = item.get("manifest_sha256")
            if not isinstance(raw_sha256, str) or not isinstance(
                manifest_sha256,
                str,
            ):
                blockers.append("l2_source_segment_lineage_invalid")
            else:
                source_lineage.append(
                    {
                        "segment_name": segment_name,
                        "raw_sha256": raw_sha256,
                        "manifest_sha256": manifest_sha256,
                    }
                )
            capture_start = _parse_utc_timestamp(item.get("capture_start"))
            capture_end = _parse_utc_timestamp(item.get("capture_end"))
            if (
                capture_start is None
                or capture_end is None
                or capture_start >= capture_end
            ):
                blockers.append("l2_source_segment_capture_window_invalid")
                continue
            raw_first_receive_time = _parse_utc_timestamp(
                item.get("raw_first_receive_time")
            )
            raw_last_receive_time = _parse_utc_timestamp(
                item.get("raw_last_receive_time")
            )
            if (
                raw_first_receive_time is None
                or raw_last_receive_time is None
                or raw_first_receive_time > raw_last_receive_time
            ):
                blockers.append(
                    "l2_source_segment_receive_endpoints_invalid"
                )
            else:
                if (
                    abs(
                        (
                            raw_first_receive_time - capture_start
                        ).total_seconds()
                    )
                    > L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS
                    + L2_NUMERIC_TOLERANCE_SECONDS
                    or abs(
                        (
                            capture_end - raw_last_receive_time
                        ).total_seconds()
                    )
                    > L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS
                    + L2_NUMERIC_TOLERANCE_SECONDS
                ):
                    blockers.append(
                        "l2_source_segment_receive_endpoint_anchor_mismatch"
                    )
                if first_raw_receive_endpoint is None:
                    first_raw_receive_endpoint = raw_first_receive_time
                last_raw_receive_endpoint = raw_last_receive_time
            segment_clock_offset_ms = _float_or_none(
                item.get("max_clock_offset_ms")
            )
            if (
                segment_clock_offset_ms is None
                or not math.isfinite(segment_clock_offset_ms)
                or segment_clock_offset_ms < 0
            ):
                blockers.append(
                    "l2_source_segment_clock_offset_invalid"
                )
            else:
                max_segment_clock_offset_ms = max(
                    max_segment_clock_offset_ms,
                    segment_clock_offset_ms,
                )
                if (
                    max_clock_lag_policy_ms is not None
                    and math.isfinite(max_clock_lag_policy_ms)
                    and segment_clock_offset_ms
                    > max_clock_lag_policy_ms
                ):
                    blockers.append(
                        "l2_source_segment_clock_offset_exceeds_policy"
                    )
            for gap_start, gap_end in gap_ranges_by_segment.get(
                segment_name,
                [],
            ):
                if (
                    gap_start < capture_start
                    or gap_end > capture_end
                ):
                    blockers.append(
                        "l2_gap_window_outside_segment_capture"
                    )
            capture_duration_seconds = _float_or_none(
                item.get("capture_duration_seconds")
            )
            monotonic_start = _int_or_none(
                item.get("capture_started_monotonic_ns")
            )
            monotonic_end = _int_or_none(
                item.get("capture_ended_monotonic_ns")
            )
            if (
                capture_duration_seconds is None
                or not math.isfinite(capture_duration_seconds)
                or capture_duration_seconds <= 0
                or monotonic_start is None
                or monotonic_end is None
                or monotonic_start <= 0
                or monotonic_end <= monotonic_start
            ):
                blockers.append(
                    "l2_source_segment_monotonic_window_invalid"
                )
            else:
                wall_duration_seconds = (
                    capture_end - capture_start
                ).total_seconds()
                monotonic_duration_seconds = (
                    monotonic_end - monotonic_start
                ) / 1_000_000_000.0
                if (
                    abs(capture_duration_seconds - wall_duration_seconds)
                    > L2_CAPTURE_DURATION_TOLERANCE_SECONDS
                    + L2_NUMERIC_TOLERANCE_SECONDS
                ):
                    blockers.append(
                        "l2_source_segment_capture_duration_mismatch"
                    )
                if (
                    abs(
                        capture_duration_seconds
                        - monotonic_duration_seconds
                    )
                    > L2_CAPTURE_DURATION_TOLERANCE_SECONDS
                    + L2_NUMERIC_TOLERANCE_SECONDS
                ):
                    blockers.append(
                        "l2_source_segment_monotonic_duration_mismatch"
                    )
            receive_span_seconds = _float_or_none(
                item.get("raw_receive_span_seconds")
            )
            monotonic_span_seconds = _float_or_none(
                item.get("raw_monotonic_span_seconds")
            )
            declared_drift_seconds = _float_or_none(
                item.get("clock_span_drift_seconds")
            )
            if (
                receive_span_seconds is None
                or monotonic_span_seconds is None
                or declared_drift_seconds is None
                or not math.isfinite(receive_span_seconds)
                or not math.isfinite(monotonic_span_seconds)
                or not math.isfinite(declared_drift_seconds)
                or receive_span_seconds < 0
                or monotonic_span_seconds < 0
            ):
                blockers.append("l2_source_segment_clock_span_invalid")
            else:
                computed_drift_seconds = abs(
                    receive_span_seconds - monotonic_span_seconds
                )
                if (
                    computed_drift_seconds
                    > L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS + 1e-9
                ):
                    blockers.append(
                        "l2_source_segment_clock_span_drift_exceeds_limit"
                    )
                if (
                    abs(computed_drift_seconds - declared_drift_seconds)
                    > 1e-9
                ):
                    blockers.append(
                        "l2_source_segment_clock_span_drift_mismatch"
                    )
                if (
                    capture_duration_seconds is not None
                    and math.isfinite(capture_duration_seconds)
                    and (
                        receive_span_seconds
                        > capture_duration_seconds
                        + L2_NUMERIC_TOLERANCE_SECONDS
                        or monotonic_span_seconds
                        > capture_duration_seconds
                        + L2_NUMERIC_TOLERANCE_SECONDS
                        or capture_duration_seconds
                        - min(
                            receive_span_seconds,
                            monotonic_span_seconds,
                        )
                        > L2_CAPTURE_DURATION_TOLERANCE_SECONDS
                        + L2_NUMERIC_TOLERANCE_SECONDS
                    )
                ):
                    blockers.append(
                        "l2_source_segment_endpoint_span_mismatch"
                    )
            endpoint_gap_count = _int_or_none(
                item.get("endpoint_gap_count")
            )
            if endpoint_gap_count != 0:
                blockers.append("l2_source_segment_endpoint_gap_detected")
            segment_blockers = item.get("blockers")
            if not isinstance(segment_blockers, list):
                blockers.append("l2_source_segment_blockers_invalid")
            elif segment_blockers:
                blockers.append("l2_source_segment_blockers_present")
            segment_counts: dict[str, int] = {}
            for field in source_totals:
                value = _int_or_none(item.get(field))
                if value is None or value < 0:
                    blockers.append(
                        f"l2_source_segment_{field}_invalid"
                    )
                else:
                    segment_counts[field] = value
                    source_totals[field] += value
            raw_row_count = _int_or_none(item.get("raw_row_count"))
            books_row_count = _int_or_none(item.get("books_row_count"))
            output_record_count = segment_counts.get(
                "output_record_count"
            )
            snapshot_count = segment_counts.get("snapshot_count")
            update_count = segment_counts.get("update_count")
            if (
                raw_row_count is None
                or books_row_count is None
                or output_record_count is None
                or raw_row_count < 1
                or books_row_count < 1
                or books_row_count > raw_row_count
                or output_record_count > books_row_count
            ):
                blockers.append("l2_source_segment_row_counts_invalid")
            elif books_row_count is not None:
                total_books_row_count += books_row_count
            if (
                snapshot_count is not None
                and update_count is not None
                and output_record_count is not None
                and snapshot_count + update_count != output_record_count
            ):
                blockers.append(
                    "l2_source_segment_replay_count_mismatch"
                )
            manifest_gap_count = _int_or_none(
                item.get("manifest_gap_count")
            )
            manifest_connection_count = _int_or_none(
                item.get("manifest_connection_count")
            )
            observed_reconnect_count = segment_counts.get(
                "observed_reconnect_count"
            )
            segment_gap_window_count = gap_count_by_segment.get(
                segment_name,
                0,
            )
            if (
                manifest_gap_count is None
                or observed_reconnect_count is None
                or manifest_gap_count != observed_reconnect_count
                or observed_reconnect_count != segment_gap_window_count
            ):
                blockers.append(
                    "l2_source_segment_gap_window_total_mismatch"
                )
            if (
                manifest_connection_count is None
                or manifest_gap_count is None
                or manifest_connection_count < 1
                or manifest_gap_count < 0
                or manifest_connection_count != manifest_gap_count + 1
            ):
                blockers.append(
                    "l2_source_segment_connection_count_mismatch"
                )
            if (
                receive_span_seconds is not None
                and monotonic_span_seconds is not None
                and math.isfinite(receive_span_seconds)
                and math.isfinite(monotonic_span_seconds)
            ):
                segment_gap_seconds = gap_seconds_by_segment.get(
                    segment_name,
                    0.0,
                )
                segment_raw_cap = min(
                    receive_span_seconds,
                    monotonic_span_seconds,
                )
                if (
                    segment_gap_seconds
                    > segment_raw_cap + L2_NUMERIC_TOLERANCE_SECONDS
                ):
                    blockers.append(
                        "l2_source_segment_gap_duration_exceeds_raw_span"
                    )
                conservative_source_cap_seconds += max(
                    0.0,
                    segment_raw_cap - segment_gap_seconds,
                )
            if previous_capture_end is not None:
                if capture_start < previous_capture_end:
                    blockers.append("l2_source_segment_capture_overlap")
                elif capture_start > previous_capture_end:
                    blockers.append("l2_source_segment_capture_gap")
            previous_capture_end = capture_end
        if set(gap_count_by_segment) - source_names:
            blockers.append("l2_gap_window_unknown_segment")
        if (
            coverage_start is not None
            and coverage_end is not None
            and source_segments
        ):
            first_segment = source_segments[0]
            last_segment = source_segments[-1]
            if (
                not isinstance(first_segment, Mapping)
                or not isinstance(last_segment, Mapping)
                or _parse_utc_timestamp(first_segment.get("capture_start"))
                != coverage_start
                or _parse_utc_timestamp(last_segment.get("capture_end"))
                != coverage_end
            ):
                blockers.append("l2_source_segment_coverage_total_mismatch")
        top_total_fields = {
            "snapshot_count": "snapshot_count",
            "update_count": "update_count",
            "output_record_count": "book_record_count",
            "observed_reconnect_count": "reconnect_count",
        }
        for source_field, top_field in top_total_fields.items():
            top_value = _int_or_none(attestation.get(top_field))
            if (
                top_value is None
                or top_value != source_totals[source_field]
            ):
                blockers.append(
                    f"l2_source_segment_{source_field}_total_mismatch"
                )
        if (
            _int_or_none(attestation.get("two_sided_snapshot_count"))
            != source_totals["output_record_count"]
        ):
            blockers.append("l2_two_sided_snapshot_total_mismatch")
        if len(gap_windows or []) != source_totals[
            "observed_reconnect_count"
        ]:
            blockers.append("l2_gap_window_reconnect_total_mismatch")
        if (
            attestation.get("source_aggregate_sha256")
            != _canonical_json_sha256(source_lineage)
        ):
            blockers.append("l2_source_aggregate_sha256_mismatch")
    book_record_count = _int_or_none(attestation.get("book_record_count"))
    if (
        checksum_observed_count is None
        or book_record_count is None
        or checksum_observed_count != book_record_count
    ):
        blockers.append("l2_checksum_observed_book_total_mismatch")
    resync_snapshot_count = _int_or_none(
        attestation.get("resync_snapshot_count")
    )
    snapshot_count = _int_or_none(attestation.get("snapshot_count"))
    if (
        resync_snapshot_count is None
        or snapshot_count is None
        or resync_snapshot_count != max(0, snapshot_count - 1)
    ):
        blockers.append("l2_resync_snapshot_total_mismatch")
    attestation_files = attestation.get("files")
    normalized_attestation_files: list[dict[str, Any]] = []
    if not isinstance(attestation_files, list) or not attestation_files:
        blockers.append("l2_table_files_invalid")
    else:
        seen_table_paths: set[str] = set()
        for item in attestation_files:
            if not isinstance(item, Mapping):
                blockers.append("l2_table_file_invalid")
                continue
            path = item.get("path")
            sha256 = item.get("sha256")
            byte_count = _int_or_none(item.get("bytes"))
            row_count = _int_or_none(item.get("row_count"))
            if (
                not isinstance(path, str)
                or not path
                or path in seen_table_paths
                or not _is_sha256_text(sha256)
                or byte_count is None
                or byte_count < 1
                or row_count is None
                or row_count < 1
            ):
                blockers.append("l2_table_file_invalid")
                continue
            seen_table_paths.add(path)
            normalized_attestation_files.append(
                {
                    "path": path,
                    "sha256": sha256,
                    "bytes": byte_count,
                    "row_count": row_count,
                }
            )
        if (
            attestation.get("aggregate_table_sha256")
            != aggregate_inventory_hash(normalized_attestation_files)
        ):
            blockers.append("l2_aggregate_table_sha256_mismatch")
        if isinstance(manifest, Mapping):
            manifest_files = manifest.get("files")
            if not isinstance(manifest_files, list):
                blockers.append("l2_manifest_files_missing")
            else:
                manifest_inventory = {
                    (
                        item.get("path"),
                        item.get("sha256"),
                        _int_or_none(item.get("bytes")),
                    )
                    for item in manifest_files
                    if isinstance(item, Mapping)
                }
                for item in normalized_attestation_files:
                    if (
                        item["path"],
                        item["sha256"],
                        item["bytes"],
                    ) not in manifest_inventory:
                        blockers.append(
                            "l2_table_file_manifest_inventory_mismatch"
                        )
    payload_check = _validate_immutable_table_payload(
        attestation,
        manifest=manifest,
        resolved_root=resolved_root,
        attestation_path=L2_ATTESTATION_PATH,
        kind="l2",
        checked_at=now,
    )
    blockers.extend(payload_check["blockers"])
    actual_row_count = payload_check["actual_row_count"]
    if actual_row_count is not None and actual_row_count != book_record_count:
        blockers.append("l2_payload_book_row_total_mismatch")
    actual_segment_counts = payload_check["segment_counts"]
    if actual_segment_counts is not None and isinstance(source_segments, list):
        declared_segment_counts = {
            str(item.get("segment_name")): _int_or_none(
                item.get("output_record_count")
            )
            for item in source_segments
            if isinstance(item, Mapping)
        }
        if actual_segment_counts != declared_segment_counts:
            blockers.append("l2_payload_segment_row_total_mismatch")
    replay_counts = payload_check["replay_counts"]
    if replay_counts is not None:
        for field in (
            "snapshot_count",
            "update_count",
            "checksum_observed_count",
            "checksum_validated_count",
            "two_sided_snapshot_count",
        ):
            if replay_counts[field] != _int_or_none(attestation.get(field)):
                blockers.append(f"l2_payload_{field}_mismatch")
        if replay_counts["reconnect_count"] != _int_or_none(
            attestation.get("reconnect_count")
        ):
            blockers.append("l2_payload_reconnect_count_mismatch")
        attested_clock_offset = _float_or_none(
            attestation.get("max_clock_offset_ms")
        )
        if (
            attested_clock_offset is None
            or not math.isfinite(attested_clock_offset)
            or abs(
                replay_counts["max_clock_offset_ms"]
                - attested_clock_offset
            )
            > L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_payload_max_clock_offset_mismatch")
        if isinstance(source_segments, list):
            declared_names: set[str] = set()
            for item in source_segments:
                if not isinstance(item, Mapping):
                    continue
                segment_name = item.get("segment_name")
                if not isinstance(segment_name, str) or not segment_name:
                    continue
                declared_names.add(segment_name)
                physical = replay_counts["segments"].get(segment_name)
                if physical is None:
                    blockers.append("l2_payload_source_segment_missing")
                    continue
                for field in (
                    "snapshot_count",
                    "update_count",
                    "output_record_count",
                ):
                    if physical[field] != _int_or_none(item.get(field)):
                        blockers.append(
                            f"l2_payload_segment_{field}_mismatch"
                        )
                if physical["reconnect_count"] != _int_or_none(
                    item.get("observed_reconnect_count")
                ):
                    blockers.append(
                        "l2_payload_segment_reconnect_count_mismatch"
                    )
                connection_count = _int_or_none(
                    item.get("manifest_connection_count")
                )
                if (
                    connection_count is None
                    or connection_count != physical["reconnect_count"] + 1
                ):
                    blockers.append(
                        "l2_payload_segment_connection_count_mismatch"
                    )
                segment_clock_offset_ms = _float_or_none(
                    item.get("max_clock_offset_ms")
                )
                if (
                    segment_clock_offset_ms is None
                    or not math.isfinite(segment_clock_offset_ms)
                    or abs(
                        physical["max_clock_offset_ms"]
                        - segment_clock_offset_ms
                    )
                    > L2_NUMERIC_TOLERANCE_SECONDS
                ):
                    blockers.append(
                        "l2_payload_segment_clock_offset_mismatch"
                    )
                    segment_clock_offset_ms = 0.0
                endpoint_tolerance_seconds = (
                    segment_clock_offset_ms / 1_000.0
                    + L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS
                )
                raw_first_receive = _parse_utc_timestamp(
                    item.get("raw_first_receive_time")
                )
                raw_last_receive = _parse_utc_timestamp(
                    item.get("raw_last_receive_time")
                )
                capture_start = _parse_utc_timestamp(
                    item.get("capture_start")
                )
                capture_end = _parse_utc_timestamp(
                    item.get("capture_end")
                )
                first_endpoint_values = (
                    physical["first_event_time"],
                    physical["first_snapshot_time"],
                    physical["first_available_time"],
                )
                last_endpoint_values = (
                    physical["last_event_time"],
                    physical["last_snapshot_time"],
                    physical["last_available_time"],
                )
                segment_endpoint_valid = all(
                    _timestamp_within_tolerance(
                        value,
                        raw_first_receive,
                        tolerance_seconds=endpoint_tolerance_seconds,
                    )
                    and _timestamp_within_tolerance(
                        value,
                        capture_start,
                        tolerance_seconds=endpoint_tolerance_seconds,
                    )
                    for value in first_endpoint_values
                ) and all(
                    _timestamp_within_tolerance(
                        value,
                        raw_last_receive,
                        tolerance_seconds=endpoint_tolerance_seconds,
                    )
                    and _timestamp_within_tolerance(
                        value,
                        capture_end,
                        tolerance_seconds=endpoint_tolerance_seconds,
                    )
                    for value in last_endpoint_values
                )
                if not _monotonic_within_tolerance(
                    physical["first_monotonic_ns"],
                    _int_or_none(
                        item.get("capture_started_monotonic_ns")
                    ),
                    tolerance_seconds=endpoint_tolerance_seconds,
                ):
                    segment_endpoint_valid = False
                if not _monotonic_within_tolerance(
                    physical["last_monotonic_ns"],
                    _int_or_none(
                        item.get("capture_ended_monotonic_ns")
                    ),
                    tolerance_seconds=endpoint_tolerance_seconds,
                ):
                    segment_endpoint_valid = False
                if not segment_endpoint_valid:
                    blockers.append("l2_payload_endpoint_mismatch")
            if set(replay_counts["segments"]) != declared_names:
                blockers.append("l2_payload_source_segment_set_mismatch")
            physical_segments = list(replay_counts["segments"].values())
            if physical_segments:
                first_events = [
                    item["first_event_time"]
                    for item in physical_segments
                    if item["first_event_time"] is not None
                ]
                last_events = [
                    item["last_event_time"]
                    for item in physical_segments
                    if item["last_event_time"] is not None
                ]
                first_available_values = [
                    item["first_available_time"]
                    for item in physical_segments
                    if item["first_available_time"] is not None
                ]
                last_available_values = [
                    item["last_available_time"]
                    for item in physical_segments
                    if item["last_available_time"] is not None
                ]
                if not all(
                    (
                        first_events,
                        last_events,
                        first_available_values,
                        last_available_values,
                    )
                ):
                    blockers.append("l2_payload_endpoint_mismatch")
                else:
                    first_event = min(first_events)
                    last_event = max(last_events)
                    first_available = min(first_available_values)
                    last_available = max(last_available_values)
                    global_endpoint_tolerance_seconds = (
                        replay_counts["max_clock_offset_ms"] / 1_000.0
                        + L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS
                    )
                    if not all(
                        (
                            _timestamp_within_tolerance(
                                first_event,
                                common_start,
                                tolerance_seconds=(
                                    global_endpoint_tolerance_seconds
                                ),
                            ),
                            _timestamp_within_tolerance(
                                last_event,
                                common_end,
                                tolerance_seconds=(
                                    global_endpoint_tolerance_seconds
                                ),
                            ),
                            _timestamp_within_tolerance(
                                first_available,
                                coverage_start,
                                tolerance_seconds=(
                                    global_endpoint_tolerance_seconds
                                ),
                            ),
                            _timestamp_within_tolerance(
                                last_available,
                                coverage_end,
                                tolerance_seconds=(
                                    global_endpoint_tolerance_seconds
                                ),
                            ),
                        )
                    ):
                        blockers.append("l2_payload_endpoint_mismatch")
    if (
        observed_clock_offset_ms is None
        or not math.isfinite(observed_clock_offset_ms)
    ):
        endpoint_clock_bound_seconds = None
    else:
        endpoint_clock_bound_seconds = (
            observed_clock_offset_ms / 1_000.0
            + L2_ENDPOINT_ANCHOR_TOLERANCE_SECONDS
        )
        if (
            abs(
                observed_clock_offset_ms
                - max_segment_clock_offset_ms
            )
            > L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_clock_offset_segment_total_mismatch")
    if (
        common_start is not None
        and common_end is not None
        and coverage_start is not None
        and coverage_end is not None
        and first_raw_receive_endpoint is not None
        and last_raw_receive_endpoint is not None
        and endpoint_clock_bound_seconds is not None
    ):
        start_offset_seconds = (
            first_raw_receive_endpoint - common_start
        ).total_seconds()
        end_offset_seconds = (
            last_raw_receive_endpoint - common_end
        ).total_seconds()
        if start_offset_seconds < -L2_NUMERIC_TOLERANCE_SECONDS:
            blockers.append("l2_common_start_after_receive_endpoint")
        elif (
            start_offset_seconds
            > endpoint_clock_bound_seconds
            + L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_common_start_receive_endpoint_mismatch")
        if end_offset_seconds < -L2_NUMERIC_TOLERANCE_SECONDS:
            blockers.append("l2_common_end_after_receive_endpoint")
        elif (
            end_offset_seconds
            > endpoint_clock_bound_seconds
            + L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_common_end_receive_endpoint_mismatch")
        if (
            abs(
                (coverage_start - common_start).total_seconds()
            )
            > endpoint_clock_bound_seconds
            + L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_common_start_coverage_start_mismatch")
        if (
            abs((coverage_end - common_end).total_seconds())
            > endpoint_clock_bound_seconds
            + L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_common_end_coverage_end_mismatch")
        if (
            abs(
                (common_end - common_start).total_seconds()
                - (
                    last_raw_receive_endpoint
                    - first_raw_receive_endpoint
                ).total_seconds()
            )
            > 2 * endpoint_clock_bound_seconds
            + L2_NUMERIC_TOLERANCE_SECONDS
        ):
            blockers.append("l2_common_receive_span_mismatch")
    effective_end_candidates = [
        value
        for value in (
            common_end,
            coverage_end,
            last_raw_receive_endpoint,
        )
        if value is not None
    ]
    effective_common_end = (
        min(effective_end_candidates)
        if len(effective_end_candidates) == 3
        else None
    )
    freshness_age = _age_hours(now, effective_common_end)
    if (
        freshness_age is None
        or freshness_age < 0
        or freshness_age > freshness_sla_hours
    ):
        blockers.append("l2_freshness_sla_breached")
    generated_at = _parse_utc_timestamp(attestation.get("generated_at"))
    declared_freshness_sla_minutes = _float_or_none(
        attestation.get("freshness_sla_minutes")
    )
    declared_freshness_age_minutes = _float_or_none(
        attestation.get("freshness_age_minutes")
    )
    attested_freshness_age_minutes = (
        (generated_at - effective_common_end).total_seconds() / 60.0
        if generated_at is not None and effective_common_end is not None
        else None
    )
    if (
        declared_freshness_sla_minutes is None
        or not math.isfinite(declared_freshness_sla_minutes)
        or declared_freshness_sla_minutes <= 0
        or declared_freshness_sla_minutes
        > freshness_sla_hours * 60.0
    ):
        blockers.append("l2_declared_freshness_sla_invalid")
    if (
        declared_freshness_age_minutes is None
        or not math.isfinite(declared_freshness_age_minutes)
        or declared_freshness_age_minutes < 0
        or attested_freshness_age_minutes is None
        or attested_freshness_age_minutes < 0
        or abs(
            declared_freshness_age_minutes
            - attested_freshness_age_minutes
        )
        > L2_NUMERIC_TOLERANCE_SECONDS / 60.0 + 1e-6
    ):
        blockers.append("l2_declared_freshness_age_mismatch")
    elif (
        declared_freshness_sla_minutes is not None
        and declared_freshness_age_minutes
        > declared_freshness_sla_minutes
    ):
        blockers.append("l2_declared_freshness_sla_breached")
    if (
        observed_history_seconds is not None
        and math.isfinite(observed_history_seconds)
        and observed_history_seconds
        > conservative_source_cap_seconds + L2_NUMERIC_TOLERANCE_SECONDS
    ):
        blockers.append(
            "l2_observed_history_exceeds_conservative_source_cap"
        )
    if (
        total_books_row_count <= 0
        or expected_span_seconds is None
        or expected_span_seconds <= 0
        or observed_history_seconds is None
        or not math.isfinite(observed_history_seconds)
    ):
        blockers.append("l2_two_sided_coverage_inputs_invalid")
        computed_two_sided_coverage_pct = None
    else:
        row_coverage_ratio = (
            source_totals["output_record_count"]
            / total_books_row_count
        )
        temporal_coverage_ratio = (
            observed_history_seconds / expected_span_seconds
        )
        computed_two_sided_coverage_pct = (
            min(1.0, row_coverage_ratio, temporal_coverage_ratio)
            * 100.0
        )
        if (
            two_sided_coverage_pct is None
            or not math.isfinite(two_sided_coverage_pct)
            or abs(
                two_sided_coverage_pct
                - computed_two_sided_coverage_pct
            )
            > L2_PERCENT_TOLERANCE
        ):
            blockers.append("l2_two_sided_coverage_derivation_mismatch")
        if (
            computed_two_sided_coverage_pct
            + L2_PERCENT_TOLERANCE
            < min_coverage_pct
        ):
            blockers.append("l2_partial_two_sided_coverage")

    blockers = _dedupe(blockers)
    return {
        "status": "pass" if not blockers else "blocked",
        "common_end": (
            effective_common_end.isoformat().replace("+00:00", "Z")
            if effective_common_end
            else ""
        ),
        "freshness_age_hours": round(freshness_age, 6) if freshness_age is not None else None,
        "two_sided_snapshot_count": two_sided_snapshot_count or 0,
        "two_sided_coverage_pct": (
            two_sided_coverage_pct
            if (
                two_sided_coverage_pct is not None
                and math.isfinite(two_sided_coverage_pct)
            )
            else 0.0
        ),
        "blockers": blockers,
    }


def _attestation_identity_blockers(
    attestation: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None,
    expected_schema: str,
) -> list[str]:
    blockers: list[str] = []
    if attestation.get("schema_version") != expected_schema:
        blockers.append("attestation_schema_mismatch")
    if attestation.get("producer_role") != "data_steward":
        blockers.append("attestation_producer_must_be_data_steward")
    if isinstance(manifest, Mapping):
        if attestation.get("dataset_id") != manifest.get("dataset_id"):
            blockers.append("attestation_dataset_id_mismatch")
        if attestation.get("dataset_version") != manifest.get("dataset_version"):
            blockers.append("attestation_dataset_version_mismatch")
    return blockers


def _attestation_source_head_blockers(
    attestation: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None,
    commit_exists: Callable[[str], bool],
    current_head: str,
    prefix: str,
) -> list[str]:
    blockers: list[str] = []
    source_head = attestation.get("source_head")
    if (
        not isinstance(source_head, str)
        or len(source_head) != 40
        or not _is_hex_text(source_head)
        or not commit_exists(source_head)
    ):
        blockers.append(f"{prefix}_source_head_unavailable")
    if (
        isinstance(manifest, Mapping)
        and source_head != manifest.get("producer_commit")
    ):
        blockers.append(f"{prefix}_source_head_manifest_commit_mismatch")
    if current_head and (
        len(current_head) != 40
        or not _is_hex_text(current_head)
        or not commit_exists(current_head)
    ):
        blockers.append(f"{prefix}_consumer_current_head_unavailable")
    return blockers


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"nonfinite_json_constant:{value}")


def _parse_json_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (DecimalException, OverflowError, TypeError, ValueError) as exc:
        raise ValueError("invalid_decimal_lexeme") from exc


def _strict_payload_decimal(
    value: object,
    *,
    allow_text: bool = False,
) -> tuple[Decimal | None, str]:
    if isinstance(value, bool) or not isinstance(
        value,
        (Decimal, int, float, str) if allow_text else (Decimal, int, float),
    ):
        return None, "invalid"
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (DecimalException, OverflowError, TypeError, ValueError):
        return None, "invalid"
    if not result.is_finite():
        return None, "invalid"
    try:
        _, digits, exponent = result.as_tuple()
        is_zero = all(digit == 0 for digit in digits)
        decimal_places = max(0, -exponent)
        adjusted_magnitude = len(digits) + exponent - 1
        exceeds_max_boundary = (
            adjusted_magnitude
            == GOVERNED_PAYLOAD_MAX_ADJUSTED_MAGNITUDE
            and (
                digits[0] > 1
                or any(digit != 0 for digit in digits[1:])
            )
        )
    except (DecimalException, OverflowError, TypeError, ValueError):
        return None, "invalid"
    if (
        decimal_places > GOVERNED_PAYLOAD_MAX_DECIMAL_PLACES
        or (
            not is_zero
            and (
                adjusted_magnitude
                > GOVERNED_PAYLOAD_MAX_ADJUSTED_MAGNITUDE
                or adjusted_magnitude
                < GOVERNED_PAYLOAD_MIN_ADJUSTED_MAGNITUDE
                or exceeds_max_boundary
            )
        )
    ):
        return None, "range"
    return result, ""


def _validate_kline_payload_row(
    row: Mapping[str, Any],
    *,
    expected_exchange: str,
    expected_symbol: str,
    expected_interval: str,
    expected_data_version: str,
    generated_at: datetime | None,
    checked_at: datetime,
) -> tuple[list[str], datetime | None]:
    blockers: list[str] = []
    required = {
        "available_time",
        "close",
        "data_version",
        "event_time",
        "exchange",
        "high",
        "interval",
        "is_finalized",
        "low",
        "open",
        "symbol",
        "volume",
    }
    if not required.issubset(row):
        blockers.append("kline_payload_required_fields_missing")
    if (
        row.get("exchange") != expected_exchange
        or row.get("symbol") != expected_symbol
        or row.get("interval") != expected_interval
        or row.get("data_version") != expected_data_version
    ):
        blockers.append("kline_payload_partition_identity_invalid")
    if row.get("is_finalized") is not True:
        blockers.append("kline_payload_not_finalized")

    event_time = _parse_utc_timestamp(row.get("event_time"))
    available_time = _parse_utc_timestamp(row.get("available_time"))
    if event_time is None or available_time is None:
        blockers.append("kline_payload_time_invalid")
    elif (
        event_time > available_time
        or generated_at is None
        or available_time > generated_at
        or generated_at > checked_at
    ):
        blockers.append("kline_payload_pit_time_order_invalid")

    parsed_values = {
        field: _strict_payload_decimal(row.get(field))
        for field in ("open", "high", "low", "close", "volume")
    }
    if any(reason == "range" for _, reason in parsed_values.values()):
        blockers.append("kline_payload_ohlcv_range_invalid")
    if any(value is None for value, _ in parsed_values.values()):
        blockers.append("kline_payload_ohlcv_invalid")
    else:
        open_price = parsed_values["open"][0]
        high = parsed_values["high"][0]
        low = parsed_values["low"][0]
        close = parsed_values["close"][0]
        volume = parsed_values["volume"][0]
        assert open_price is not None
        assert high is not None
        assert low is not None
        assert close is not None
        assert volume is not None
        if min(open_price, high, low, close) <= 0 or volume < 0:
            blockers.append("kline_payload_ohlcv_domain_invalid")
        if high < max(open_price, close, low) or low > min(
            open_price,
            close,
            high,
        ):
            blockers.append("kline_payload_ohlc_relation_invalid")
    return blockers, event_time


def _strict_int(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else None
    )


def _l2_levels(
    value: object,
    *,
    reverse: bool,
) -> tuple[list[tuple[str, str]], list[str]]:
    blockers: list[str] = []
    if not isinstance(value, list) or not value:
        return [], ["l2_payload_book_levels_invalid"]
    parsed: list[tuple[str, str]] = []
    numeric_prices: list[Decimal] = []
    seen_numeric_prices: set[Decimal] = set()
    for level in value:
        if (
            not isinstance(level, list)
            or len(level) != 2
            or not all(isinstance(item, str) and item for item in level)
        ):
            blockers.append("l2_payload_book_level_invalid")
            continue
        price_text, size_text = level
        price, price_reason = _strict_payload_decimal(
            price_text,
            allow_text=True,
        )
        size, size_reason = _strict_payload_decimal(
            size_text,
            allow_text=True,
        )
        if "range" in {price_reason, size_reason}:
            blockers.append("l2_payload_book_level_range_invalid")
        if price is None or size is None:
            blockers.append("l2_payload_book_level_invalid")
            continue
        if (
            price <= 0
            or size <= 0
            or price in seen_numeric_prices
        ):
            blockers.append("l2_payload_book_level_invalid")
            continue
        seen_numeric_prices.add(price)
        parsed.append((price_text, size_text))
        numeric_prices.append(price)
    if numeric_prices != sorted(numeric_prices, reverse=reverse):
        blockers.append("l2_payload_book_sort_invalid")
    return parsed, blockers


def _l2_checksum(
    bids: list[tuple[str, str]],
    asks: list[tuple[str, str]],
) -> int:
    parts: list[str] = []
    bid_rows = bids[:25]
    ask_rows = asks[:25]
    for index in range(max(len(bid_rows), len(ask_rows))):
        if index < len(bid_rows):
            parts.extend(bid_rows[index])
        if index < len(ask_rows):
            parts.extend(ask_rows[index])
    unsigned = zlib.crc32(":".join(parts).encode("utf-8"))
    return unsigned if unsigned < 2**31 else unsigned - 2**32


def _timestamp_within_tolerance(
    value: object,
    expected: object,
    *,
    tolerance_seconds: float,
) -> bool:
    return (
        isinstance(value, datetime)
        and isinstance(expected, datetime)
        and abs((value - expected).total_seconds()) <= tolerance_seconds
    )


def _monotonic_within_tolerance(
    value: object,
    expected: object,
    *,
    tolerance_seconds: float,
) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and isinstance(expected, int)
        and not isinstance(expected, bool)
        and abs(value - expected) / 1_000_000_000.0
        <= tolerance_seconds
    )


def _validate_l2_payload_row(
    row: Mapping[str, Any],
    *,
    states: dict[str, dict[str, Any]],
    replay_counts: dict[str, Any],
    global_last_seq_id: int | None,
    generated_at: datetime | None,
    checked_at: datetime,
) -> tuple[list[str], int | None]:
    blockers: list[str] = []
    required = {
        "action",
        "asks",
        "available_time",
        "best_ask",
        "best_bid",
        "bids",
        "capture_sequence",
        "channel",
        "checksum",
        "connection_sequence",
        "event_time",
        "instrument_id",
        "monotonic_ns",
        "prev_seq_id",
        "segment_name",
        "seq_id",
        "snapshot_time",
        "venue",
    }
    if not required.issubset(row):
        blockers.append("l2_payload_required_fields_missing")

    segment_name = row.get("segment_name")
    action = row.get("action")
    if not isinstance(segment_name, str) or not segment_name:
        blockers.append("l2_payload_segment_name_invalid")
        segment_name = ""
    if (
        row.get("venue") != "okx"
        or row.get("instrument_id") != "BTC-USDT-SWAP"
        or row.get("channel") != "books"
    ):
        blockers.append("l2_payload_identity_invalid")
    if action not in {"snapshot", "update"}:
        blockers.append("l2_payload_action_invalid")

    event_time = _parse_utc_timestamp(row.get("event_time"))
    snapshot_time = _parse_utc_timestamp(row.get("snapshot_time"))
    available_time = _parse_utc_timestamp(row.get("available_time"))
    if event_time is None or snapshot_time is None or available_time is None:
        blockers.append("l2_payload_time_invalid")
    else:
        if (
            event_time > snapshot_time
            or snapshot_time != available_time
            or generated_at is None
            or available_time > generated_at
            or generated_at > checked_at
        ):
            blockers.append("l2_payload_pit_time_order_invalid")
        replay_counts["max_clock_offset_ms"] = max(
            float(replay_counts.get("max_clock_offset_ms", 0.0)),
            abs((available_time - event_time).total_seconds() * 1_000.0),
        )

    capture_sequence = _strict_int(row.get("capture_sequence"))
    connection_sequence = _strict_int(row.get("connection_sequence"))
    monotonic_ns = _strict_int(row.get("monotonic_ns"))
    prev_seq_id = _strict_int(row.get("prev_seq_id"))
    seq_id = _strict_int(row.get("seq_id"))
    checksum = _strict_int(row.get("checksum"))
    if (
        capture_sequence is None
        or capture_sequence < 1
        or connection_sequence is None
        or connection_sequence < 1
        or monotonic_ns is None
        or monotonic_ns < 1
        or prev_seq_id is None
        or seq_id is None
        or checksum is None
    ):
        blockers.append("l2_payload_sequence_fields_invalid")

    bids, bid_blockers = _l2_levels(row.get("bids"), reverse=True)
    asks, ask_blockers = _l2_levels(row.get("asks"), reverse=False)
    blockers.extend(bid_blockers)
    blockers.extend(ask_blockers)
    if bids and asks:
        best_bid, best_bid_reason = _strict_payload_decimal(
            row.get("best_bid")
        )
        best_ask, best_ask_reason = _strict_payload_decimal(
            row.get("best_ask")
        )
        if "range" in {best_bid_reason, best_ask_reason}:
            blockers.append("l2_payload_numeric_range_invalid")
        top_bid, _ = _strict_payload_decimal(
            bids[0][0],
            allow_text=True,
        )
        top_ask, _ = _strict_payload_decimal(
            asks[0][0],
            allow_text=True,
        )
        if (
            best_bid is None
            or best_ask is None
            or top_bid is None
            or top_ask is None
            or best_bid != top_bid
            or best_ask != top_ask
        ):
            blockers.append("l2_payload_best_price_mismatch")
        if (
            top_bid is not None
            and top_ask is not None
            and top_bid >= top_ask
        ):
            blockers.append("l2_payload_book_crossed_or_locked")
        elif top_bid is not None and top_ask is not None:
            replay_counts["two_sided_snapshot_count"] += 1
        if checksum is not None:
            replay_counts["checksum_observed_count"] += 1
            if checksum != 0:
                if checksum != _l2_checksum(bids, asks):
                    blockers.append("l2_payload_checksum_mismatch")
                else:
                    replay_counts["checksum_validated_count"] += 1

    if action == "snapshot":
        replay_counts["snapshot_count"] += 1
    elif action == "update":
        replay_counts["update_count"] += 1
    segment_replay: dict[str, Any] | None = None
    if segment_name:
        segment_replay = replay_counts["segments"].setdefault(
            segment_name,
            {
                "snapshot_count": 0,
                "update_count": 0,
                "reconnect_count": 0,
                "output_record_count": 0,
                "first_event_time": event_time,
                "last_event_time": event_time,
                "first_snapshot_time": snapshot_time,
                "last_snapshot_time": snapshot_time,
                "first_available_time": available_time,
                "last_available_time": available_time,
                "first_monotonic_ns": monotonic_ns,
                "last_monotonic_ns": monotonic_ns,
                "max_clock_offset_ms": 0.0,
            },
        )
        segment_replay["output_record_count"] += 1
        if action == "snapshot":
            segment_replay["snapshot_count"] += 1
        elif action == "update":
            segment_replay["update_count"] += 1
        if event_time is not None:
            if segment_replay["first_event_time"] is None:
                segment_replay["first_event_time"] = event_time
            segment_replay["last_event_time"] = event_time
        if snapshot_time is not None:
            if segment_replay["first_snapshot_time"] is None:
                segment_replay["first_snapshot_time"] = snapshot_time
            segment_replay["last_snapshot_time"] = snapshot_time
        if available_time is not None:
            if segment_replay["first_available_time"] is None:
                segment_replay["first_available_time"] = available_time
            segment_replay["last_available_time"] = available_time
        if monotonic_ns is not None:
            if segment_replay["first_monotonic_ns"] is None:
                segment_replay["first_monotonic_ns"] = monotonic_ns
            segment_replay["last_monotonic_ns"] = monotonic_ns
        if event_time is not None and available_time is not None:
            segment_replay["max_clock_offset_ms"] = max(
                segment_replay["max_clock_offset_ms"],
                abs(
                    (available_time - event_time).total_seconds()
                    * 1_000.0
                ),
            )

    if (
        segment_name
        and capture_sequence is not None
        and connection_sequence is not None
        and monotonic_ns is not None
        and prev_seq_id is not None
        and seq_id is not None
        and action in {"snapshot", "update"}
    ):
        state = states.get(segment_name)
        if state is None:
            if capture_sequence != 1:
                blockers.append(
                    "l2_payload_capture_sequence_must_start_at_one"
                )
            if action != "snapshot":
                blockers.append("l2_payload_segment_requires_initial_snapshot")
            if prev_seq_id != -1:
                blockers.append("l2_payload_snapshot_prev_seq_invalid")
            if connection_sequence != 1:
                blockers.append("l2_payload_connection_must_start_at_one")
            if (
                global_last_seq_id is not None
                and seq_id != global_last_seq_id + 1
            ):
                blockers.append("l2_payload_cross_segment_sequence_gap")
            states[segment_name] = {
                "capture_sequence": capture_sequence,
                "connection_sequence": connection_sequence,
                "monotonic_ns": monotonic_ns,
                "seq_id": seq_id,
                "event_time": event_time,
                "snapshot_time": snapshot_time,
                "available_time": available_time,
            }
        else:
            expected_capture_sequence = state["capture_sequence"] + 1
            reconnect_reset = (
                connection_sequence == state["connection_sequence"] + 1
                and capture_sequence == 1
            )
            if (
                capture_sequence != expected_capture_sequence
                and not reconnect_reset
            ):
                blockers.append("l2_payload_capture_sequence_gap")
            if monotonic_ns <= state["monotonic_ns"]:
                blockers.append("l2_payload_monotonic_ns_not_strict")
            previous_available = state.get("available_time")
            previous_event = state.get("event_time")
            previous_snapshot = state.get("snapshot_time")
            if (
                event_time is not None
                and previous_event is not None
                and event_time < previous_event
            ):
                blockers.append("l2_payload_event_time_rollback")
            if (
                snapshot_time is not None
                and previous_snapshot is not None
                and snapshot_time < previous_snapshot
            ):
                blockers.append("l2_payload_snapshot_time_rollback")
            if (
                available_time is not None
                and previous_available is not None
                and available_time < previous_available
            ):
                blockers.append("l2_payload_available_time_rollback")
            previous_connection = state["connection_sequence"]
            if connection_sequence == previous_connection:
                if action != "update":
                    blockers.append(
                        "l2_payload_unjustified_same_connection_snapshot"
                    )
                if prev_seq_id != state["seq_id"] or seq_id <= state["seq_id"]:
                    blockers.append("l2_payload_sequence_gap_or_order_invalid")
            elif connection_sequence == previous_connection + 1:
                replay_counts["reconnect_count"] += 1
                assert segment_replay is not None
                segment_replay["reconnect_count"] += 1
                if action != "snapshot":
                    blockers.append("l2_payload_reconnect_requires_snapshot")
                if prev_seq_id != -1:
                    blockers.append("l2_payload_snapshot_prev_seq_invalid")
            else:
                blockers.append("l2_payload_connection_sequence_jump")
            state.update(
                {
                    "capture_sequence": capture_sequence,
                    "connection_sequence": connection_sequence,
                    "monotonic_ns": monotonic_ns,
                    "seq_id": seq_id,
                    "event_time": event_time,
                    "snapshot_time": snapshot_time,
                    "available_time": available_time,
                }
            )
        global_last_seq_id = seq_id
    return blockers, global_last_seq_id


def _validate_immutable_table_payload(
    attestation: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any] | None,
    resolved_root: Path | None,
    attestation_path: str,
    kind: str,
    checked_at: datetime,
) -> dict[str, Any]:
    blockers: list[str] = []
    files = attestation.get("files")
    normalized: list[dict[str, Any]] = []
    if not isinstance(files, list) or not files:
        return {
            "blockers": [f"{kind}_table_files_invalid"],
            "actual_row_count": None,
            "segment_counts": None,
            "replay_counts": None,
        }
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            blockers.append(f"{kind}_table_file_invalid")
            continue
        path = item.get("path")
        sha256 = item.get("sha256")
        byte_count = _int_or_none(item.get("bytes"))
        row_count = _int_or_none(item.get("row_count"))
        if (
            not isinstance(path, str)
            or not path
            or path in seen
            or not _is_sha256_text(sha256)
            or byte_count is None
            or byte_count < 1
            or row_count is None
            or row_count < 1
        ):
            blockers.append(f"{kind}_table_file_invalid")
            continue
        seen.add(path)
        normalized.append(
            {
                "path": path,
                "sha256": sha256,
                "bytes": byte_count,
                "row_count": row_count,
            }
        )
    if (
        attestation.get("aggregate_table_sha256")
        != aggregate_inventory_hash(normalized)
    ):
        blockers.append(f"{kind}_aggregate_table_sha256_mismatch")
    if isinstance(manifest, Mapping):
        manifest_files = manifest.get("files")
        if not isinstance(manifest_files, list):
            blockers.append(f"{kind}_manifest_files_missing")
        else:
            payload_inventory = {
                (
                    item.get("path"),
                    item.get("sha256"),
                    _int_or_none(item.get("bytes")),
                )
                for item in manifest_files
                if isinstance(item, Mapping)
                and item.get("path") not in {attestation_path, MANIFEST_NAME}
            }
            attested_inventory = {
                (item["path"], item["sha256"], item["bytes"])
                for item in normalized
            }
            if payload_inventory != attested_inventory:
                blockers.append(f"{kind}_manifest_payload_inventory_mismatch")
    actual_total: int | None = None
    segment_counts: dict[str, int] | None = None
    replay_counts: dict[str, int] | None = None
    if resolved_root is not None:
        actual_total = 0
        segment_counts = {}
        replay_counts = {
            "snapshot_count": 0,
            "update_count": 0,
            "reconnect_count": 0,
            "checksum_observed_count": 0,
            "checksum_validated_count": 0,
            "two_sided_snapshot_count": 0,
            "max_clock_offset_ms": 0.0,
            "segments": {},
        }
        l2_states: dict[str, dict[str, Any]] = {}
        global_last_seq_id: int | None = None
        generated_at = _parse_utc_timestamp(attestation.get("generated_at"))
        if generated_at is None or generated_at > checked_at:
            blockers.append(f"{kind}_payload_generated_at_invalid")
        interval_windows: dict[
            tuple[str, str, str],
            tuple[datetime, datetime],
        ] = {}
        for item in sorted(normalized, key=lambda value: value["path"]):
            path = resolved_root / item["path"]
            actual_file_count = 0
            first_event: datetime | None = None
            previous_event: datetime | None = None
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            blockers.append(f"{kind}_payload_blank_jsonl_row")
                            continue
                        row = json.loads(
                            line,
                            parse_float=_parse_json_decimal,
                            parse_int=int,
                            parse_constant=_reject_json_constant,
                        )
                        if not isinstance(row, Mapping):
                            blockers.append(f"{kind}_payload_row_invalid")
                            continue
                        actual_file_count += 1
                        actual_total += 1
                        if kind == "l2":
                            row_blockers, global_last_seq_id = (
                                _validate_l2_payload_row(
                                    row,
                                    states=l2_states,
                                    replay_counts=replay_counts,
                                    global_last_seq_id=global_last_seq_id,
                                    generated_at=generated_at,
                                    checked_at=checked_at,
                                )
                            )
                            blockers.extend(row_blockers)
                            segment_name = row.get("segment_name")
                            if not isinstance(segment_name, str) or not segment_name:
                                blockers.append("l2_payload_segment_name_invalid")
                            else:
                                segment_counts[segment_name] = (
                                    segment_counts.get(segment_name, 0) + 1
                                )
                        else:
                            expected_exchange = _partition_value(
                                item["path"],
                                "exchange",
                            )
                            expected_symbol = _partition_value(
                                item["path"],
                                "symbol",
                            )
                            expected_interval = _partition_value(
                                item["path"],
                                "interval",
                            )
                            if (
                                row.get("exchange") != expected_exchange
                                or row.get("symbol") != expected_symbol
                                or row.get("interval") != expected_interval
                            ):
                                blockers.append(
                                    "kline_payload_partition_identity_invalid"
                                )
                            row_blockers, event_time = (
                                _validate_kline_payload_row(
                                    row,
                                    expected_exchange=expected_exchange,
                                    expected_symbol=expected_symbol,
                                    expected_interval=expected_interval,
                                    expected_data_version=str(
                                        attestation.get("dataset_version", "")
                                    ),
                                    generated_at=generated_at,
                                    checked_at=checked_at,
                                )
                            )
                            blockers.extend(row_blockers)
                            if event_time is None:
                                continue
                            if first_event is None:
                                first_event = event_time
                            interval = expected_interval
                            interval_seconds = {
                                "1m": 60,
                                "5m": 300,
                                "15m": 900,
                                "1h": 3_600,
                                "4h": 14_400,
                                "1d": 86_400,
                            }.get(interval)
                            if interval_seconds is None:
                                blockers.append("kline_payload_interval_invalid")
                            else:
                                epoch_ms = int(event_time.timestamp() * 1_000)
                                derived = (
                                    attestation.get("source_time_semantics")
                                    == "derived_from_close_time"
                                )
                                aligned = (
                                    (epoch_ms + 1) % (interval_seconds * 1_000)
                                    == 0
                                    if derived
                                    else epoch_ms % (interval_seconds * 1_000)
                                    == 0
                                )
                                if not aligned:
                                    blockers.append("kline_payload_event_time_off_grid")
                                if previous_event is not None and (
                                    event_time - previous_event
                                ).total_seconds() != interval_seconds:
                                    blockers.append(
                                        "kline_payload_cadence_gap_or_duplicate"
                                    )
                            previous_event = event_time
                if actual_file_count != item["row_count"]:
                    blockers.append(f"{kind}_payload_file_row_count_mismatch")
                if kind == "kline" and first_event is not None and previous_event is not None:
                    key = (
                        _partition_value(item["path"], "exchange"),
                        _partition_value(item["path"], "symbol"),
                        _partition_value(item["path"], "interval"),
                    )
                    interval_windows[key] = (first_event, previous_event)
            except (OSError, UnicodeError, ValueError):
                blockers.append(f"{kind}_payload_jsonl_unreadable")
            except (DecimalException, ArithmeticError, TypeError):
                blockers.append(f"{kind}_payload_validation_exception")
        if kind == "kline":
            for item in attestation.get("intervals", []):
                if not isinstance(item, Mapping):
                    continue
                key = _kline_partition_key(item)
                if key is None or key not in interval_windows:
                    blockers.append("kline_payload_partition_missing")
                    continue
                actual_start, actual_end = interval_windows[key]
                if (
                    actual_start
                    != _parse_utc_timestamp(item.get("coverage_start"))
                    or actual_end
                    != _parse_utc_timestamp(item.get("coverage_end"))
                ):
                    blockers.append("kline_payload_partition_window_mismatch")
    return {
        "blockers": _dedupe(blockers),
        "actual_row_count": actual_total,
        "segment_counts": segment_counts,
        "replay_counts": replay_counts,
    }


def _partition_value(path: str, field: str) -> str:
    prefix = f"{field}="
    for part in Path(path).parts:
        if part.startswith(prefix):
            return part[len(prefix):]
    return ""


def _is_hex_text(value: str) -> bool:
    return all(character in "0123456789abcdef" for character in value)


@lru_cache(maxsize=1)
def _kline_attestation_validator() -> Draft202012Validator:
    schema = json.loads(
        KLINE_ATTESTATION_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _kline_schema_blockers(
    attestation: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    try:
        errors = sorted(
            _kline_attestation_validator().iter_errors(attestation),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [
            f"kline_attestation_schema_unavailable:{type(exc).__name__}"
        ]
    if errors:
        blockers.append("kline_attestation_schema_invalid")
        for error in errors[:20]:
            path = ".".join(str(part) for part in error.absolute_path)
            blockers.append(
                "kline_attestation_schema_violation:"
                f"{path or '$'}:{error.validator}"
            )
    if _contains_nonfinite(attestation):
        blockers.append("kline_attestation_nonfinite")
    return blockers


@lru_cache(maxsize=1)
def _l2_attestation_validator() -> Draft202012Validator:
    schema = json.loads(
        L2_ATTESTATION_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    return Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )


def _l2_schema_blockers(
    attestation: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    try:
        errors = sorted(
            _l2_attestation_validator().iter_errors(attestation),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"l2_attestation_schema_unavailable:{type(exc).__name__}"]
    if errors:
        blockers.append("l2_attestation_schema_invalid")
        for error in errors[:20]:
            path = ".".join(str(part) for part in error.absolute_path)
            blockers.append(
                "l2_attestation_schema_violation:"
                f"{path or '$'}:{error.validator}"
            )
    if _contains_nonfinite(attestation):
        blockers.append("l2_attestation_nonfinite")
    return blockers


def _contains_nonfinite(value: object) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_nonfinite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(item) for item in value)
    return False


def _public_manifest_check(check: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in check.items() if key != "attestation"}


def _read_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("attestation_not_object")
    return payload


def _is_immutable_version(value: str) -> bool:
    lowered = value.lower()
    return bool(value) and all(token not in lowered for token in ("latest", "current", "staging", "mutable"))


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _age_hours(now: datetime, value: datetime | None) -> float | None:
    if value is None:
        return None
    return (now - value).total_seconds() / 3_600.0


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item)))
