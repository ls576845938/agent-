"""Offline fail-closed export of OKX public WS L2 capture segments."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, TextIO
import uuid

from quant_crypto.data.okx_l2_capture_contract import (
    OKX_L2_BOOKS_CHANNEL,
    OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
    OKX_L2_INSTRUMENT_ID,
    OKX_L2_RAW_MANIFEST_FILE,
    OKX_L2_RAW_MESSAGES_FILE,
    OKX_L2_VENUE,
)
from tools.agent_governance.shared_data import aggregate_inventory_hash


EXPORTER_VERSION = "btc_okx_l2_immutable_export_v5"
ATTESTATION_SCHEMA_VERSION = "btc_okx_l2_dataready_attestation_v1"
DATASET_ID = "btc-okx-timestamp-aligned-public-l2-history"
ATTESTATION_NAME = "btc_okx_l2_dataready_attestation.json"
VENUE = OKX_L2_VENUE
INSTRUMENT_ID = OKX_L2_INSTRUMENT_ID
CHANNEL = OKX_L2_BOOKS_CHANNEL
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MONOTONIC_DELTA_TOLERANCE_SECONDS = 0.1
ENDPOINT_ANCHOR_TOLERANCE_SECONDS = 0.1
CAPTURE_DURATION_TOLERANCE_SECONDS = 0.2
INTER_MESSAGE_GAP_POLICY_ID = "btc_okx_l2_inter_message_gap_v1"
APPROVED_MAX_INTER_MESSAGE_GAP_SECONDS = 5.0


class L2ExportBlocked(RuntimeError):
    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(dict.fromkeys(str(item) for item in blockers if str(item)))
        super().__init__(";".join(self.blockers))


@dataclass(frozen=True)
class L2SegmentSource:
    segment_dir: Path
    expected_raw_sha256: str
    expected_manifest_sha256: str


@dataclass
class _ReplayState:
    bids: dict[str, str]
    asks: dict[str, str]
    last_seq_id: int | None = None
    active: bool = False
    last_connection_sequence: int | None = None
    last_capture_sequence: int = 0
    last_monotonic_ns: int = 0
    last_event_time: datetime | None = None
    last_receive_time: datetime | None = None


def export_immutable_okx_l2(
    *,
    segments: Iterable[L2SegmentSource],
    output_dir: Path,
    dataset_version: str,
    source_head: str,
    now: datetime,
    producer_role: str = "data_steward",
    max_clock_lag_ms: float = 5_000.0,
    freshness_sla_minutes: float = 15.0,
    max_inter_message_gap_seconds: float = 5.0,
) -> dict[str, Any]:
    """Validate and export already-landed public WS segments without collection."""

    checked_at = _as_utc(now)
    sources = tuple(segments)
    destination = output_dir.resolve()
    blockers = _preflight_blockers(
        sources=sources,
        destination=destination,
        dataset_version=dataset_version,
        source_head=source_head,
        producer_role=producer_role,
        max_clock_lag_ms=max_clock_lag_ms,
        freshness_sla_minutes=freshness_sla_minutes,
        max_inter_message_gap_seconds=max_inter_message_gap_seconds,
    )
    if blockers:
        raise L2ExportBlocked(blockers)

    source_records, source_blockers = _load_source_records(sources)
    if source_blockers:
        raise L2ExportBlocked(source_blockers)

    staging = destination.with_name(f".{destination.name}.staging-{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    handles: dict[Path, TextIO] = {}
    output_paths: set[Path] = set()
    output_row_counts: dict[Path, int] = {}
    validation_blockers: list[str] = []
    coverage_start: datetime | None = None
    common_end: datetime | None = None
    max_observed_clock_lag_ms = 0.0
    snapshot_count = 0
    update_count = 0
    book_record_count = 0
    reconnect_count = 0
    resync_snapshot_count = 0
    checksum_observed_count = 0
    checksum_validated_count = 0
    sequence_gap_count = 0
    duplicate_count = 0
    out_of_order_count = 0
    segment_summaries: list[dict[str, Any]] = []
    seen_snapshot = False
    gap_windows: list[dict[str, Any]] = []
    unrecovered_gap_count = 0
    global_last_seq_id: int | None = None
    global_last_event_time: datetime | None = None
    global_last_receive_time: datetime | None = None
    capture_coverage_start = source_records[0]["capture_start"]
    capture_coverage_end = source_records[-1]["capture_end"]
    observed_history_seconds = 0.0
    total_books_row_count = sum(
        int(item["books_row_count"]) for item in source_records
    )

    try:
        for segment_index, source_record in enumerate(source_records):
            state = _ReplayState(bids={}, asks={})
            segment_snapshot_count = 0
            segment_update_count = 0
            segment_record_count = 0
            segment_reconnect_count = 0
            segment_max_clock_offset_ms = 0.0
            segment_first_sequence_checked = False
            segment_blockers: list[str] = []
            segment_blockers.extend(
                source_record["cumulative_clock_blockers"]
            )
            for endpoint_gap in source_record["endpoint_gaps"]:
                gap_windows.append(
                    {
                        "segment_name": source_record["segment_name"],
                        "from_connection_sequence": 1,
                        "to_connection_sequence": 1,
                        "gap_start": _utc_text(endpoint_gap["gap_start"]),
                        "gap_end": _utc_text(endpoint_gap["gap_end"]),
                        "duration_seconds": round(
                            endpoint_gap["duration_seconds"],
                            6,
                        ),
                        "recovered": False,
                        "gap_type": endpoint_gap["gap_type"],
                    }
                )
                unrecovered_gap_count += 1
                segment_blockers.append(endpoint_gap["blocker"])
            raw_path = Path(source_record["raw_path"])
            for line_number, raw_row in _iter_jsonl(raw_path):
                row_blockers, parsed = _parse_capture_row(
                    raw_row,
                    state=state,
                    segment_name=str(source_record["segment_name"]),
                    line_number=line_number,
                )
                segment_blockers.extend(row_blockers)
                if parsed is None:
                    continue
                action = parsed["action"]
                connection_sequence = parsed["connection_sequence"]
                is_reconnect = (
                    state.last_connection_sequence is not None
                    and connection_sequence != state.last_connection_sequence
                )
                if (
                    is_reconnect
                ):
                    reconnect_count += 1
                    segment_reconnect_count += 1
                    previous_receive_time = parsed["previous_receive_time"]
                    receive_time = parsed["receive_time"]
                    recovered = action == "snapshot"
                    gap_duration_seconds = (
                        max(
                            0.0,
                            (receive_time - previous_receive_time).total_seconds(),
                        )
                        if previous_receive_time is not None
                        else 0.0
                    )
                    gap_windows.append(
                        {
                            "segment_name": source_record["segment_name"],
                            "from_connection_sequence": (
                                state.last_connection_sequence
                            ),
                            "to_connection_sequence": connection_sequence,
                            "gap_start": (
                                _utc_text(previous_receive_time)
                                if previous_receive_time is not None
                                else _utc_text(receive_time)
                            ),
                            "gap_end": _utc_text(receive_time),
                            "duration_seconds": round(
                                gap_duration_seconds,
                                6,
                            ),
                            "recovered": recovered,
                        }
                    )
                    state.active = False
                    state.last_seq_id = None
                    state.bids.clear()
                    state.asks.clear()
                    if not recovered:
                        unrecovered_gap_count += 1
                        segment_blockers.append("l2_reconnect_requires_new_snapshot")
                state.last_connection_sequence = connection_sequence
                if not state.active and action != "snapshot":
                    segment_blockers.append(
                        "l2_segment_requires_initial_snapshot"
                        if segment_record_count == 0
                        else "l2_update_requires_new_snapshot"
                    )
                    continue

                item = parsed["item"]
                seq_id = _int_or_none(item.get("seqId"))
                prev_seq_id = _int_or_none(item.get("prevSeqId"))
                checksum = _int_or_none(item.get("checksum"))
                if seq_id is None or prev_seq_id is None:
                    segment_blockers.append("l2_sequence_fields_missing")
                    state.active = False
                    continue
                if checksum is None:
                    segment_blockers.append("l2_checksum_missing")
                    state.active = False
                    continue
                checksum_observed_count += 1

                event_time = _exchange_event_time(item.get("ts"))
                receive_time = parsed["receive_time"]
                if event_time is None:
                    segment_blockers.append("l2_exchange_event_time_invalid")
                    state.active = False
                    continue
                previous_event_time = state.last_event_time
                previous_receive_time = parsed["previous_receive_time"]
                previous_monotonic_ns = parsed["previous_monotonic_ns"]
                if (
                    not is_reconnect
                    and previous_event_time is not None
                    and previous_receive_time is not None
                    and previous_monotonic_ns is not None
                ):
                    event_gap_seconds = (
                        event_time - previous_event_time
                    ).total_seconds()
                    receive_gap_seconds = (
                        receive_time - previous_receive_time
                    ).total_seconds()
                    monotonic_gap_seconds = (
                        parsed["monotonic_ns"] - previous_monotonic_ns
                    ) / 1_000_000_000.0
                    if (
                        abs(monotonic_gap_seconds - receive_gap_seconds)
                        > MONOTONIC_DELTA_TOLERANCE_SECONDS + 1e-9
                    ):
                        segment_blockers.append(
                            "l2_monotonic_receive_delta_mismatch"
                        )
                    idle_gap_seconds = max(
                        event_gap_seconds,
                        receive_gap_seconds,
                        monotonic_gap_seconds,
                    )
                    if idle_gap_seconds > max_inter_message_gap_seconds:
                        gap_windows.append(
                            {
                                "segment_name": source_record["segment_name"],
                                "from_connection_sequence": connection_sequence,
                                "to_connection_sequence": connection_sequence,
                                "gap_start": _utc_text(previous_receive_time),
                                "gap_end": _utc_text(receive_time),
                                "duration_seconds": round(
                                    idle_gap_seconds,
                                    6,
                                ),
                                "recovered": False,
                                "gap_type": "inter_message_idle",
                            }
                        )
                        unrecovered_gap_count += 1
                        segment_blockers.append(
                            "l2_inter_message_gap_exceeds_limit"
                        )
                        _quarantine(state)
                        continue
                    observed_history_seconds += (
                        _conservative_observed_delta_seconds(
                            receive_gap_seconds,
                            monotonic_gap_seconds,
                        )
                    )
                if (
                    state.last_event_time is not None
                    and event_time < state.last_event_time
                ):
                    segment_blockers.append("l2_exchange_event_time_rollback")
                    _quarantine(state)
                    continue
                state.last_event_time = (
                    event_time
                    if state.last_event_time is None
                    else max(state.last_event_time, event_time)
                )
                if not segment_first_sequence_checked:
                    if segment_index > 0:
                        if (
                            global_last_seq_id is None
                            or seq_id != global_last_seq_id + 1
                        ):
                            segment_blockers.append(
                                "l2_cross_segment_sequence_not_contiguous"
                            )
                        if (
                            global_last_event_time is not None
                            and event_time < global_last_event_time
                        ):
                            segment_blockers.append(
                                "l2_cross_segment_event_time_rollback"
                            )
                        if (
                            global_last_receive_time is not None
                            and receive_time < global_last_receive_time
                        ):
                            segment_blockers.append(
                                "l2_cross_segment_receive_time_rollback"
                            )
                    segment_first_sequence_checked = True
                if receive_time > checked_at:
                    segment_blockers.append("l2_available_time_after_export_time")
                clock_lag_ms = (receive_time - event_time).total_seconds() * 1_000.0
                if clock_lag_ms < 0:
                    segment_blockers.append("l2_event_after_local_receipt")
                if clock_lag_ms > max_clock_lag_ms:
                    segment_blockers.append("l2_clock_lag_exceeds_limit")
                max_observed_clock_lag_ms = max(
                    max_observed_clock_lag_ms,
                    abs(clock_lag_ms),
                )
                segment_max_clock_offset_ms = max(
                    segment_max_clock_offset_ms,
                    abs(clock_lag_ms),
                )

                if action == "snapshot":
                    if segment_snapshot_count > 0 and not is_reconnect:
                        segment_blockers.append(
                            "l2_unjustified_same_connection_snapshot_reset"
                        )
                        _quarantine(state)
                        continue
                    bids, bid_issues = _snapshot_levels(item.get("bids"))
                    asks, ask_issues = _snapshot_levels(item.get("asks"))
                    segment_blockers.extend(bid_issues)
                    segment_blockers.extend(ask_issues)
                    state.bids = bids
                    state.asks = asks
                    state.last_seq_id = seq_id
                    state.active = True
                    snapshot_count += 1
                    segment_snapshot_count += 1
                    if seen_snapshot:
                        resync_snapshot_count += 1
                    seen_snapshot = True
                elif action == "update":
                    assert state.last_seq_id is not None
                    if seq_id == state.last_seq_id:
                        duplicate_count += 1
                        segment_blockers.append("l2_sequence_duplicate")
                        _quarantine(state)
                        continue
                    if seq_id < state.last_seq_id:
                        out_of_order_count += 1
                        segment_blockers.append("l2_sequence_out_of_order")
                        _quarantine(state)
                        continue
                    if prev_seq_id != state.last_seq_id:
                        sequence_gap_count += 1
                        segment_blockers.append("l2_sequence_gap")
                        _quarantine(state)
                        continue
                    segment_blockers.extend(_apply_level_updates(state.bids, item.get("bids")))
                    segment_blockers.extend(_apply_level_updates(state.asks, item.get("asks")))
                    state.last_seq_id = seq_id
                    update_count += 1
                    segment_update_count += 1
                else:
                    segment_blockers.append("l2_book_action_invalid")
                    _quarantine(state)
                    continue

                book_blockers = _book_integrity_blockers(state.bids, state.asks)
                segment_blockers.extend(book_blockers)
                if checksum != 0:
                    expected_checksum = _okx_checksum(state.bids, state.asks)
                    if checksum != expected_checksum:
                        segment_blockers.append("l2_checksum_mismatch")
                    else:
                        checksum_validated_count += 1
                if book_blockers or clock_lag_ms < 0 or clock_lag_ms > max_clock_lag_ms:
                    _quarantine(state)
                    continue
                if "l2_checksum_mismatch" in segment_blockers:
                    _quarantine(state)
                    continue

                record = _output_record(
                    segment_name=str(source_record["segment_name"]),
                    parsed=parsed,
                    item=item,
                    event_time=event_time,
                    receive_time=receive_time,
                    state=state,
                )
                relative = (
                    Path(f"venue={VENUE}")
                    / f"instrument_id={INSTRUMENT_ID}"
                    / f"date={event_time.date().isoformat()}"
                    / "part-00000.jsonl"
                )
                path = staging / relative
                if path not in handles:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handles[path] = path.open("a", encoding="utf-8", newline="\n")
                    output_paths.add(path)
                handles[path].write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )
                output_row_counts[path] = output_row_counts.get(path, 0) + 1
                coverage_start = (
                    event_time
                    if coverage_start is None
                    else min(coverage_start, event_time)
                )
                common_end = (
                    event_time
                    if common_end is None
                    else max(common_end, event_time)
                )
                book_record_count += 1
                segment_record_count += 1
                global_last_seq_id = seq_id
                global_last_event_time = event_time
                global_last_receive_time = receive_time

            if segment_reconnect_count != source_record["manifest_gap_count"]:
                segment_blockers.append(
                    "l2_manifest_gap_count_mismatch:"
                    f"{source_record['segment_name']}"
                )
            validation_blockers.extend(segment_blockers)
            segment_summaries.append(
                {
                    "segment_name": source_record["segment_name"],
                    "data_version": source_record["data_version"],
                    "raw_sha256": source_record["raw_sha256"],
                    "manifest_sha256": source_record["manifest_sha256"],
                    "raw_bytes": source_record["raw_bytes"],
                    "manifest_bytes": source_record["manifest_bytes"],
                    "raw_row_count": source_record["raw_row_count"],
                    "books_row_count": source_record["books_row_count"],
                    "capture_start": _utc_text(source_record["capture_start"]),
                    "capture_end": _utc_text(source_record["capture_end"]),
                    "raw_first_receive_time": _utc_text(
                        source_record["first_receive_time"]
                    ),
                    "raw_last_receive_time": _utc_text(
                        source_record["last_receive_time"]
                    ),
                    "max_clock_offset_ms": round(
                        segment_max_clock_offset_ms,
                        6,
                    ),
                    "capture_duration_seconds": source_record[
                        "capture_duration_seconds"
                    ],
                    "capture_started_monotonic_ns": source_record[
                        "capture_started_monotonic_ns"
                    ],
                    "capture_ended_monotonic_ns": source_record[
                        "capture_ended_monotonic_ns"
                    ],
                    "raw_receive_span_seconds": source_record[
                        "raw_receive_span_seconds"
                    ],
                    "raw_monotonic_span_seconds": source_record[
                        "raw_monotonic_span_seconds"
                    ],
                    "clock_span_drift_seconds": source_record[
                        "clock_span_drift_seconds"
                    ],
                    "endpoint_gap_count": len(
                        source_record["endpoint_gaps"]
                    ),
                    "manifest_connection_count": source_record[
                        "manifest_connection_count"
                    ],
                    "manifest_gap_count": source_record["manifest_gap_count"],
                    "observed_reconnect_count": segment_reconnect_count,
                    "snapshot_count": segment_snapshot_count,
                    "update_count": segment_update_count,
                    "output_record_count": segment_record_count,
                    "blockers": list(dict.fromkeys(segment_blockers)),
                }
            )

        for handle in handles.values():
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
        handles.clear()

        if not book_record_count:
            validation_blockers.append("l2_replayed_book_records_missing")
        if snapshot_count <= 0:
            validation_blockers.append("l2_snapshot_missing")
        if update_count <= 0:
            validation_blockers.append("l2_update_missing")
        if coverage_start is None or common_end is None:
            validation_blockers.append("l2_coverage_window_missing")
        validation_blockers.extend(_source_stability_blockers(source_records))
        if validation_blockers:
            raise L2ExportBlocked(validation_blockers)

        assert coverage_start is not None
        assert common_end is not None
        freshness_age_minutes = (
            checked_at - common_end
        ).total_seconds() / 60.0
        if freshness_age_minutes < 0:
            raise L2ExportBlocked(["l2_common_end_in_future"])
        if freshness_age_minutes > freshness_sla_minutes:
            raise L2ExportBlocked(["l2_common_end_freshness_sla_breached"])

        files = [
            {
                "path": path.relative_to(staging).as_posix(),
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
                "row_count": output_row_counts[path],
            }
            for path in sorted(output_paths)
        ]
        aggregate_sha256 = aggregate_inventory_hash(files)
        coverage_span_seconds = (
            capture_coverage_end - capture_coverage_start
        ).total_seconds()
        history_window_days = observed_history_seconds / 86_400.0
        row_coverage_ratio = (
            book_record_count / total_books_row_count
            if total_books_row_count > 0
            else 0.0
        )
        temporal_coverage_ratio = (
            observed_history_seconds / coverage_span_seconds
            if coverage_span_seconds > 0
            else 0.0
        )
        two_sided_coverage_pct = round(
            min(1.0, row_coverage_ratio, temporal_coverage_ratio) * 100.0,
            9,
        )
        promotion_blockers = [
            "btc_okx_l2_history_below_30_natural_days"
            if history_window_days < 30.0
            else "",
            "btc_execution_latency_model_missing",
            "btc_queue_model_missing",
            "btc_okx_l2_natural_execution_observation_missing",
            (
                "btc_okx_l2_two_sided_coverage_incomplete"
                if two_sided_coverage_pct < 100.0
                else ""
            ),
        ]
        attestation = {
            "schema_version": ATTESTATION_SCHEMA_VERSION,
            "exporter_version": EXPORTER_VERSION,
            "producer_role": producer_role,
            "dataset_id": DATASET_ID,
            "dataset_version": dataset_version,
            "source_head": source_head,
            "generated_at": _utc_text(checked_at),
            "timezone": "UTC",
            "venue": VENUE,
            "instrument_id": INSTRUMENT_ID,
            "channel": CHANNEL,
            "event_time_field": "event_time",
            "snapshot_time_field": "snapshot_time",
            "available_time_field": "available_time",
            "sequence_validation_status": "pass",
            "sequence_gap_count": sequence_gap_count,
            "duplicate_sequence_count": duplicate_count,
            "out_of_order_sequence_count": out_of_order_count,
            "unrecovered_gap_count": unrecovered_gap_count,
            "checksum_observed_count": checksum_observed_count,
            "checksum_validated_count": checksum_validated_count,
            "checksum_policy": (
                "nonzero_crc32_validated_zero_accepted_after_okx_deprecation"
            ),
            "event_snapshot_time_order_valid": True,
            "two_sided_snapshot_count": book_record_count,
            "two_sided_coverage_pct": two_sided_coverage_pct,
            "clock_offset_attested": True,
            "max_clock_offset_ms": round(max_observed_clock_lag_ms, 6),
            "max_clock_lag_policy_ms": float(max_clock_lag_ms),
            "max_inter_message_gap_seconds": float(
                max_inter_message_gap_seconds
            ),
            "inter_message_gap_policy_id": INTER_MESSAGE_GAP_POLICY_ID,
            "approved_max_inter_message_gap_seconds": (
                APPROVED_MAX_INTER_MESSAGE_GAP_SECONDS
            ),
            "endpoint_anchor_tolerance_seconds": (
                ENDPOINT_ANCHOR_TOLERANCE_SECONDS
            ),
            "capture_duration_tolerance_seconds": (
                CAPTURE_DURATION_TOLERANCE_SECONDS
            ),
            "observed_history_policy": (
                "sum_min_receive_monotonic_contiguous_deltas_excluding_"
                "reconnect_idle_and_unobserved_endpoint_gaps"
            ),
            "coverage_start": _utc_text(capture_coverage_start),
            "coverage_end": _utc_text(capture_coverage_end),
            "common_start": _utc_text(coverage_start),
            "common_end": _utc_text(common_end),
            "freshness_sla_minutes": float(freshness_sla_minutes),
            "freshness_age_minutes": round(freshness_age_minutes, 6),
            "history_window_days": round(history_window_days, 9),
            "observed_history_seconds": round(
                observed_history_seconds,
                6,
            ),
            "coverage_span_days": round(
                coverage_span_seconds / 86_400.0,
                9,
            ),
            "segment_count": len(source_records),
            "snapshot_count": snapshot_count,
            "update_count": update_count,
            "book_record_count": book_record_count,
            "reconnect_count": reconnect_count,
            "resync_snapshot_count": resync_snapshot_count,
            "gap_windows": gap_windows,
            "source_segments": segment_summaries,
            "source_aggregate_sha256": _stable_hash(
                [
                    {
                        "segment_name": item["segment_name"],
                        "raw_sha256": item["raw_sha256"],
                        "manifest_sha256": item["manifest_sha256"],
                    }
                    for item in segment_summaries
                ]
            ),
            "files": files,
            "aggregate_table_sha256": aggregate_sha256,
            "quality_checked": True,
            "promotion_evidence_ready": False,
            "promotion_blockers": [
                item for item in promotion_blockers if item
            ],
            "readiness": {
                "quality_checked": True,
                "research_ready": False,
                "backtest_ready": False,
                "promotion_evidence_ready": False,
            },
            "guardrails": {
                "source_segments_mutated": False,
                "database_payload_emitted": False,
                "network_collection_used": False,
                "shared_data_published": False,
                "promotion_unlock_allowed": False,
                "paper_or_live_unlock_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "broker_call_used": False,
                "real_order_submitted": False,
            },
        }
        _write_json(staging / ATTESTATION_NAME, attestation)
        os.replace(staging, destination)
    except Exception:
        for handle in handles.values():
            handle.close()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "status": "quality_checked",
        "decision": "immutable_okx_l2_export_ready_for_data_steward_publication_review",
        "output_dir": str(destination),
        "attestation_path": str(destination / ATTESTATION_NAME),
        "dataset_id": DATASET_ID,
        "dataset_version": dataset_version,
        "segment_count": len(source_records),
        "book_record_count": book_record_count,
        "common_end": _utc_text(common_end),
        "readiness": attestation["readiness"],
        "guardrails": attestation["guardrails"],
        "promotion_blockers": attestation["promotion_blockers"],
    }


def blocked_export_report(
    *,
    blockers: Iterable[str],
    dataset_version: str,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "decision": "block_immutable_okx_l2_export_fail_closed",
        "dataset_id": DATASET_ID,
        "dataset_version": dataset_version,
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
        "readiness": {
            "quality_checked": False,
            "research_ready": False,
            "backtest_ready": False,
            "promotion_evidence_ready": False,
        },
        "guardrails": {
            "source_segments_mutated": False,
            "database_payload_emitted": False,
            "network_collection_used": False,
            "shared_data_published": False,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_call_used": False,
            "real_order_submitted": False,
        },
    }


def _preflight_blockers(
    *,
    sources: tuple[L2SegmentSource, ...],
    destination: Path,
    dataset_version: str,
    source_head: str,
    producer_role: str,
    max_clock_lag_ms: float,
    freshness_sla_minutes: float,
    max_inter_message_gap_seconds: float,
) -> list[str]:
    blockers: list[str] = []
    if not sources:
        blockers.append("l2_source_segments_missing")
    resolved = [item.segment_dir.resolve() for item in sources]
    if len(resolved) != len(set(resolved)):
        blockers.append("l2_source_segment_duplicate")
    for item in sources:
        if not item.segment_dir.is_dir():
            blockers.append(f"l2_source_segment_missing:{item.segment_dir.name}")
        if not HASH_PATTERN.fullmatch(item.expected_raw_sha256):
            blockers.append(f"l2_expected_raw_sha256_invalid:{item.segment_dir.name}")
        if not HASH_PATTERN.fullmatch(item.expected_manifest_sha256):
            blockers.append(
                f"l2_expected_manifest_sha256_invalid:{item.segment_dir.name}"
            )
    if destination.exists():
        blockers.append("l2_output_directory_already_exists")
    if destination.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        blockers.append("l2_output_must_not_be_database_payload")
    if not SAFE_ID.fullmatch(dataset_version):
        blockers.append("l2_dataset_version_invalid")
    if not COMMIT_PATTERN.fullmatch(source_head):
        blockers.append("l2_source_head_invalid")
    if producer_role != "data_steward":
        blockers.append("l2_attestation_producer_role_must_be_data_steward")
    if max_clock_lag_ms <= 0:
        blockers.append("l2_max_clock_lag_ms_invalid")
    if freshness_sla_minutes <= 0:
        blockers.append("l2_freshness_sla_minutes_invalid")
    if (
        not math.isfinite(max_inter_message_gap_seconds)
        or max_inter_message_gap_seconds <= 0
    ):
        blockers.append("l2_max_inter_message_gap_seconds_invalid")
    elif (
        max_inter_message_gap_seconds
        > APPROVED_MAX_INTER_MESSAGE_GAP_SECONDS
    ):
        blockers.append(
            "l2_max_inter_message_gap_exceeds_governed_ceiling"
        )
    return blockers


def _load_source_records(
    sources: tuple[L2SegmentSource, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    blockers: list[str] = []
    for source in sources:
        segment_dir = source.segment_dir.resolve()
        segment_name = segment_dir.name
        if not SAFE_ID.fullmatch(segment_name):
            blockers.append(f"l2_segment_name_invalid:{segment_name}")
            continue
        raw_path = segment_dir / OKX_L2_RAW_MESSAGES_FILE
        manifest_path = segment_dir / OKX_L2_RAW_MANIFEST_FILE
        if not raw_path.is_file():
            blockers.append(f"l2_raw_messages_missing:{segment_name}")
            continue
        if not manifest_path.is_file():
            blockers.append(f"l2_raw_manifest_missing:{segment_name}")
            continue
        raw_stat = raw_path.stat()
        manifest_stat = manifest_path.stat()
        raw_hash = _sha256_file(raw_path)
        manifest_hash = _sha256_file(manifest_path)
        if raw_hash != source.expected_raw_sha256:
            blockers.append(f"l2_raw_sha256_mismatch:{segment_name}")
        if manifest_hash != source.expected_manifest_sha256:
            blockers.append(f"l2_manifest_sha256_mismatch:{segment_name}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blockers.append(f"l2_raw_manifest_unreadable:{segment_name}")
            continue
        if not isinstance(manifest, Mapping):
            blockers.append(f"l2_raw_manifest_not_object:{segment_name}")
            continue
        blockers.extend(_manifest_blockers(manifest, segment_name=segment_name))
        raw_facts = _raw_capture_facts(raw_path)
        row_count = int(raw_facts["row_count"])
        if row_count <= 0:
            blockers.append(f"l2_raw_messages_empty:{segment_name}")
        if int(manifest.get("message_count", -1)) != row_count:
            blockers.append(f"l2_manifest_message_count_mismatch:{segment_name}")
        manifest_connection_count = _int_or_none(manifest.get("connection_count"))
        manifest_gap_count = _int_or_none(manifest.get("gap_count"))
        if manifest_connection_count != raw_facts["connection_count"]:
            blockers.append(
                f"l2_manifest_connection_count_mismatch:{segment_name}"
            )
        if manifest_gap_count != raw_facts["connection_transition_count"]:
            blockers.append(f"l2_manifest_gap_count_mismatch:{segment_name}")
        if raw_facts["connection_sequence_rollback"]:
            blockers.append("l2_connection_sequence_rollback")
        channel_counts = manifest.get("channel_counts")
        manifest_books_count = (
            _int_or_none(channel_counts.get(CHANNEL))
            if isinstance(channel_counts, Mapping)
            else None
        )
        if manifest_books_count != raw_facts["books_row_count"]:
            blockers.append(
                f"l2_manifest_books_count_mismatch:{segment_name}"
            )
        if _int_or_none(manifest.get("data_message_count")) != raw_facts[
            "data_row_count"
        ]:
            blockers.append(
                f"l2_manifest_data_message_count_mismatch:{segment_name}"
            )
        try:
            capture_start = _parse_utc(str(manifest.get("capture_start", "")))
            capture_end = _parse_utc(str(manifest.get("capture_end", "")))
        except ValueError:
            continue
        first_receive_time = raw_facts["first_receive_time"]
        last_receive_time = raw_facts["last_receive_time"]
        if (
            raw_facts["min_receive_time"] is not None
            and (
                raw_facts["min_receive_time"] < capture_start
                or raw_facts["max_receive_time"] is None
                or raw_facts["max_receive_time"] > capture_end
            )
        ):
            blockers.append(
                f"l2_manifest_capture_window_mismatch:{segment_name}"
            )
        manifest_monotonic_start = _int_or_none(
            manifest.get("capture_started_monotonic_ns")
        )
        manifest_monotonic_end = _int_or_none(
            manifest.get("capture_ended_monotonic_ns")
        )
        if raw_facts["monotonic_missing_count"] > 0:
            blockers.append(f"l2_raw_monotonic_ns_missing:{segment_name}")
        if (
            manifest_monotonic_start is not None
            and manifest_monotonic_end is not None
            and (
                raw_facts["min_monotonic_ns"] is None
                or raw_facts["max_monotonic_ns"] is None
                or raw_facts["min_monotonic_ns"] < manifest_monotonic_start
                or raw_facts["max_monotonic_ns"] > manifest_monotonic_end
            )
        ):
            blockers.append(
                f"l2_manifest_monotonic_window_mismatch:{segment_name}"
            )
        endpoint_gaps: list[dict[str, Any]] = []
        raw_first_monotonic = raw_facts["first_monotonic_ns"]
        raw_last_monotonic = raw_facts["last_monotonic_ns"]
        if (
            first_receive_time is not None
            and last_receive_time is not None
            and manifest_monotonic_start is not None
            and manifest_monotonic_end is not None
            and raw_first_monotonic is not None
            and raw_last_monotonic is not None
        ):
            receive_head_gap = (
                first_receive_time - capture_start
            ).total_seconds()
            receive_tail_gap = (
                capture_end - last_receive_time
            ).total_seconds()
            monotonic_head_gap = (
                raw_first_monotonic - manifest_monotonic_start
            ) / 1_000_000_000.0
            monotonic_tail_gap = (
                manifest_monotonic_end - raw_last_monotonic
            ) / 1_000_000_000.0
            endpoint_specs = (
                (
                    receive_head_gap,
                    "l2_manifest_receive_start_endpoint_unanchored",
                    "receive_head",
                    capture_start,
                    first_receive_time,
                ),
                (
                    receive_tail_gap,
                    "l2_manifest_receive_end_endpoint_unanchored",
                    "receive_tail",
                    last_receive_time,
                    capture_end,
                ),
                (
                    monotonic_head_gap,
                    "l2_manifest_monotonic_start_endpoint_unanchored",
                    "monotonic_head",
                    capture_start,
                    capture_start + timedelta(seconds=monotonic_head_gap),
                ),
                (
                    monotonic_tail_gap,
                    "l2_manifest_monotonic_end_endpoint_unanchored",
                    "monotonic_tail",
                    capture_end - timedelta(seconds=monotonic_tail_gap),
                    capture_end,
                ),
            )
            for (
                gap_seconds,
                blocker,
                gap_type,
                gap_start,
                gap_end,
            ) in endpoint_specs:
                if (
                    gap_seconds
                    > ENDPOINT_ANCHOR_TOLERANCE_SECONDS + 1e-9
                ):
                    endpoint_gaps.append(
                        {
                            "duration_seconds": gap_seconds,
                            "blocker": blocker,
                            "gap_type": gap_type,
                            "gap_start": gap_start,
                            "gap_end": gap_end,
                        }
                    )
        receive_span_seconds = (
            (last_receive_time - first_receive_time).total_seconds()
            if first_receive_time is not None
            and last_receive_time is not None
            else -1.0
        )
        monotonic_span_seconds = (
            (raw_last_monotonic - raw_first_monotonic)
            / 1_000_000_000.0
            if raw_first_monotonic is not None
            and raw_last_monotonic is not None
            else -1.0
        )
        cumulative_clock_blockers = _cumulative_clock_span_blockers(
            receive_span_seconds=receive_span_seconds,
            monotonic_span_seconds=monotonic_span_seconds,
            segment_name=segment_name,
        )
        records.append(
            {
                "segment_name": segment_name,
                "segment_dir": str(segment_dir),
                "raw_path": str(raw_path),
                "manifest_path": str(manifest_path),
                "data_version": str(manifest.get("data_version", "")),
                "raw_sha256": raw_hash,
                "manifest_sha256": manifest_hash,
                "raw_bytes": raw_stat.st_size,
                "manifest_bytes": manifest_stat.st_size,
                "raw_mtime_ns": raw_stat.st_mtime_ns,
                "manifest_mtime_ns": manifest_stat.st_mtime_ns,
                "raw_row_count": row_count,
                "books_row_count": raw_facts["books_row_count"],
                "capture_start": capture_start,
                "capture_end": capture_end,
                "capture_duration_seconds": float(
                    manifest.get("capture_duration_seconds", 0.0)
                ),
                "manifest_connection_count": manifest_connection_count,
                "manifest_gap_count": manifest_gap_count,
                "capture_started_monotonic_ns": manifest_monotonic_start,
                "capture_ended_monotonic_ns": manifest_monotonic_end,
                "raw_receive_span_seconds": receive_span_seconds,
                "raw_monotonic_span_seconds": monotonic_span_seconds,
                "clock_span_drift_seconds": abs(
                    round(
                        receive_span_seconds - monotonic_span_seconds,
                        9,
                    )
                ),
                "endpoint_gaps": endpoint_gaps,
                "cumulative_clock_blockers": cumulative_clock_blockers,
                "first_receive_time": first_receive_time,
                "last_receive_time": last_receive_time,
            }
        )
    for previous, current in zip(records, records[1:], strict=False):
        previous_end = previous["capture_end"]
        current_start = current["capture_start"]
        if current_start < previous_end:
            blockers.append("l2_cross_segment_capture_overlap")
        elif current_start > previous_end:
            blockers.append("l2_cross_segment_capture_gap")
    return records, list(dict.fromkeys(blockers))


def _manifest_blockers(
    manifest: Mapping[str, Any],
    *,
    segment_name: str,
) -> list[str]:
    blockers: list[str] = []
    if manifest.get("schema_version") != OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION:
        blockers.append(f"l2_manifest_schema_version_invalid:{segment_name}")
    if manifest.get("public_ws_only") is not True:
        blockers.append(f"l2_manifest_not_public_only:{segment_name}")
    for field in (
        "api_key_used",
        "private_endpoint_used",
        "order_endpoint_used",
        "broker_calls_used",
    ):
        if manifest.get(field) is not False:
            blockers.append(f"l2_manifest_safety_flag_invalid:{segment_name}:{field}")
    channels = manifest.get("public_channels")
    if not isinstance(channels, list) or CHANNEL not in channels:
        blockers.append(f"l2_manifest_books_channel_missing:{segment_name}")
    if manifest.get("venue") != VENUE:
        blockers.append(f"l2_manifest_venue_invalid:{segment_name}")
    if manifest.get("venue_symbol") != INSTRUMENT_ID:
        blockers.append(f"l2_manifest_instrument_invalid:{segment_name}")
    if not str(manifest.get("data_version", "")):
        blockers.append(f"l2_manifest_data_version_missing:{segment_name}")
    try:
        capture_start = _parse_utc(str(manifest.get("capture_start", "")))
        capture_end = _parse_utc(str(manifest.get("capture_end", "")))
    except ValueError:
        blockers.append(f"l2_manifest_capture_window_invalid:{segment_name}")
    else:
        if capture_end <= capture_start:
            blockers.append(f"l2_manifest_capture_window_invalid:{segment_name}")
        duration = _float_or_none(manifest.get("capture_duration_seconds"))
        wall_duration = (capture_end - capture_start).total_seconds()
        if (
            duration is None
            or duration <= 0
            or abs(duration - wall_duration)
            > CAPTURE_DURATION_TOLERANCE_SECONDS
        ):
            blockers.append(
                f"l2_manifest_capture_duration_mismatch:{segment_name}"
            )
        monotonic_start = _int_or_none(
            manifest.get("capture_started_monotonic_ns")
        )
        monotonic_end = _int_or_none(
            manifest.get("capture_ended_monotonic_ns")
        )
        if (
            monotonic_start is None
            or monotonic_end is None
            or monotonic_start <= 0
            or monotonic_end <= monotonic_start
        ):
            blockers.append(
                f"l2_manifest_monotonic_window_invalid:{segment_name}"
            )
        elif (
            duration is None
            or abs(
                duration
                - (monotonic_end - monotonic_start) / 1_000_000_000.0
            )
            > CAPTURE_DURATION_TOLERANCE_SECONDS
        ):
            blockers.append(
                f"l2_manifest_monotonic_duration_mismatch:{segment_name}"
            )
    connection_count = _int_or_none(manifest.get("connection_count"))
    gap_count = _int_or_none(manifest.get("gap_count"))
    forced_reconnect_count = _int_or_none(
        manifest.get("forced_reconnect_count")
    )
    error_count = _int_or_none(manifest.get("error_count"))
    if connection_count is None or connection_count <= 0:
        blockers.append(f"l2_manifest_connection_count_invalid:{segment_name}")
    if gap_count is None or gap_count < 0:
        blockers.append(f"l2_manifest_gap_count_invalid:{segment_name}")
    if forced_reconnect_count is None or forced_reconnect_count < 0:
        blockers.append(
            f"l2_manifest_forced_reconnect_count_invalid:{segment_name}"
        )
    if error_count != 0:
        blockers.append(f"l2_manifest_capture_errors_present:{segment_name}")
    if (
        gap_count is not None
        and forced_reconnect_count is not None
        and gap_count != forced_reconnect_count
    ):
        blockers.append(f"l2_manifest_gap_count_mismatch:{segment_name}")
    if (
        connection_count is not None
        and gap_count is not None
        and connection_count != gap_count + 1
    ):
        blockers.append(
            f"l2_manifest_connection_gap_contract_invalid:{segment_name}"
        )
    return blockers


def _raw_capture_facts(path: Path) -> dict[str, Any]:
    row_count = 0
    books_row_count = 0
    data_row_count = 0
    connection_sequences: list[int] = []
    receive_times: list[datetime] = []
    monotonic_values: list[int] = []
    first_receive_time: datetime | None = None
    last_receive_time: datetime | None = None
    first_monotonic_ns: int | None = None
    last_monotonic_ns: int | None = None
    monotonic_missing_count = 0
    for _, row in _iter_jsonl(path):
        row_count += 1
        try:
            raw_message = json.loads(str(row.get("raw", "")))
        except json.JSONDecodeError:
            raw_message = None
        if isinstance(raw_message, Mapping):
            raw_arg = raw_message.get("arg")
            raw_data = raw_message.get("data")
            if isinstance(raw_data, list):
                data_row_count += 1
            if (
                isinstance(raw_arg, Mapping)
                and raw_arg.get("channel") == CHANNEL
                and isinstance(raw_data, list)
            ):
                books_row_count += 1
        connection_sequence = _int_or_none(row.get("connection_sequence"))
        if connection_sequence is not None:
            connection_sequences.append(connection_sequence)
        monotonic_ns = _int_or_none(row.get("monotonic_ns"))
        if monotonic_ns is None:
            monotonic_missing_count += 1
        else:
            monotonic_values.append(monotonic_ns)
            if first_monotonic_ns is None:
                first_monotonic_ns = monotonic_ns
            last_monotonic_ns = monotonic_ns
        try:
            receive_time = _parse_utc(str(row.get("local_receive_ts", "")))
            receive_times.append(receive_time)
            if first_receive_time is None:
                first_receive_time = receive_time
            last_receive_time = receive_time
        except ValueError:
            continue
    unique_connections = sorted(set(connection_sequences))
    connection_count = max(unique_connections, default=0)
    transition_count = sum(
        1
        for previous, current in zip(
            connection_sequences,
            connection_sequences[1:],
            strict=False,
        )
        if current != previous
    )
    connection_sequence_rollback = any(
        current < previous
        for previous, current in zip(
            connection_sequences,
            connection_sequences[1:],
            strict=False,
        )
    )
    return {
        "row_count": row_count,
        "books_row_count": books_row_count,
        "data_row_count": data_row_count,
        "connection_count": connection_count,
        "connection_transition_count": transition_count,
        "connection_sequence_rollback": connection_sequence_rollback,
        "min_monotonic_ns": min(monotonic_values) if monotonic_values else None,
        "max_monotonic_ns": max(monotonic_values) if monotonic_values else None,
        "first_monotonic_ns": first_monotonic_ns,
        "last_monotonic_ns": last_monotonic_ns,
        "monotonic_missing_count": monotonic_missing_count,
        "min_receive_time": min(receive_times) if receive_times else None,
        "max_receive_time": max(receive_times) if receive_times else None,
        "first_receive_time": first_receive_time,
        "last_receive_time": last_receive_time,
    }


def _cumulative_clock_span_blockers(
    *,
    receive_span_seconds: float,
    monotonic_span_seconds: float,
    segment_name: str,
) -> list[str]:
    if receive_span_seconds < 0 or monotonic_span_seconds < 0:
        return [f"l2_clock_span_invalid:{segment_name}"]
    if (
        abs(monotonic_span_seconds - receive_span_seconds)
        > MONOTONIC_DELTA_TOLERANCE_SECONDS + 1e-9
    ):
        return [
            "l2_monotonic_receive_cumulative_drift_exceeds_limit:"
            f"{segment_name}"
        ]
    return []


def _conservative_observed_delta_seconds(
    receive_gap_seconds: float,
    monotonic_gap_seconds: float,
) -> float:
    return max(0.0, min(receive_gap_seconds, monotonic_gap_seconds))


def _parse_capture_row(
    raw_row: Mapping[str, Any],
    *,
    state: _ReplayState,
    segment_name: str,
    line_number: int,
) -> tuple[list[str], dict[str, Any] | None]:
    blockers: list[str] = []
    capture_sequence = _int_or_none(raw_row.get("capture_sequence"))
    monotonic_ns = _int_or_none(raw_row.get("monotonic_ns"))
    previous_monotonic_ns = state.last_monotonic_ns or None
    connection_sequence = _int_or_none(raw_row.get("connection_sequence"))
    if (
        capture_sequence is None
        or capture_sequence != state.last_capture_sequence + 1
    ):
        blockers.append("l2_capture_sequence_not_contiguous")
    if monotonic_ns is None or monotonic_ns <= state.last_monotonic_ns:
        blockers.append(f"l2_monotonic_ns_not_strict:{segment_name}:{line_number}")
    if connection_sequence is None or connection_sequence <= 0:
        blockers.append(f"l2_connection_sequence_invalid:{segment_name}:{line_number}")
    elif state.last_connection_sequence is None and connection_sequence != 1:
        blockers.append(
            f"l2_connection_sequence_must_start_at_one:{segment_name}:{line_number}"
        )
    elif (
        state.last_connection_sequence is not None
        and connection_sequence < state.last_connection_sequence
    ):
        blockers.append("l2_connection_sequence_rollback")
    elif (
        state.last_connection_sequence is not None
        and connection_sequence > state.last_connection_sequence + 1
    ):
        blockers.append(
            f"l2_connection_sequence_jump:{segment_name}:{line_number}"
        )
    if capture_sequence is not None:
        state.last_capture_sequence = max(state.last_capture_sequence, capture_sequence)
    if monotonic_ns is not None:
        state.last_monotonic_ns = max(state.last_monotonic_ns, monotonic_ns)
    local_receive_ts = str(raw_row.get("local_receive_ts", ""))
    previous_receive_time = state.last_receive_time
    try:
        receive_time = _parse_utc(local_receive_ts)
    except ValueError:
        blockers.append(f"l2_local_receive_time_invalid:{segment_name}:{line_number}")
        receive_time = None
    if (
        receive_time is not None
        and state.last_receive_time is not None
        and receive_time < state.last_receive_time
    ):
        blockers.append("l2_local_receive_time_rollback")
    if receive_time is not None:
        state.last_receive_time = (
            receive_time
            if state.last_receive_time is None
            else max(state.last_receive_time, receive_time)
        )
    try:
        message = json.loads(str(raw_row.get("raw", "")))
    except json.JSONDecodeError:
        blockers.append(f"l2_raw_message_invalid_json:{segment_name}:{line_number}")
        return blockers, None
    if not isinstance(message, Mapping):
        blockers.append(f"l2_raw_message_not_object:{segment_name}:{line_number}")
        return blockers, None
    arg = message.get("arg")
    if not isinstance(arg, Mapping) or arg.get("channel") != CHANNEL:
        return blockers, None
    if arg.get("instId") != INSTRUMENT_ID:
        blockers.append(f"l2_raw_message_instrument_invalid:{segment_name}:{line_number}")
    action = str(message.get("action", ""))
    data = message.get("data")
    event = str(message.get("event", ""))
    if event and not isinstance(data, list):
        if event == "error":
            blockers.append(
                f"l2_raw_message_error_event:{segment_name}:{line_number}"
            )
        return blockers, None
    if action not in {"snapshot", "update"}:
        blockers.append(f"l2_book_action_invalid:{segment_name}:{line_number}")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
        blockers.append(f"l2_book_data_shape_invalid:{segment_name}:{line_number}")
        return blockers, None
    if blockers:
        return blockers, None
    return blockers, {
        "capture_sequence": capture_sequence,
        "connection_sequence": connection_sequence,
        "local_receive_ts": local_receive_ts,
        "receive_time": receive_time,
        "previous_receive_time": previous_receive_time,
        "monotonic_ns": monotonic_ns,
        "previous_monotonic_ns": previous_monotonic_ns,
        "action": action,
        "item": data[0],
    }


def _snapshot_levels(
    value: object,
) -> tuple[dict[str, str], list[str]]:
    levels: dict[str, str] = {}
    blockers: list[str] = []
    if not isinstance(value, list):
        return levels, ["l2_book_levels_invalid"]
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            blockers.append("l2_book_level_invalid")
            continue
        price, size = str(raw[0]), str(raw[1])
        price_decimal = _decimal(price)
        size_decimal = _decimal(size)
        if price_decimal is None or price_decimal <= 0:
            blockers.append("l2_book_price_invalid")
            continue
        if size_decimal is None or size_decimal < 0:
            blockers.append("l2_book_size_invalid")
            continue
        if size_decimal > 0:
            levels[price] = size
    return levels, blockers


def _apply_level_updates(
    levels: dict[str, str],
    value: object,
) -> list[str]:
    blockers: list[str] = []
    if not isinstance(value, list):
        return ["l2_book_levels_invalid"]
    for raw in value:
        if not isinstance(raw, list) or len(raw) < 2:
            blockers.append("l2_book_level_invalid")
            continue
        price, size = str(raw[0]), str(raw[1])
        price_decimal = _decimal(price)
        size_decimal = _decimal(size)
        if price_decimal is None or price_decimal <= 0:
            blockers.append("l2_book_price_invalid")
            continue
        if size_decimal is None or size_decimal < 0:
            blockers.append("l2_book_size_invalid")
            continue
        if size_decimal == 0:
            levels.pop(price, None)
        else:
            levels[price] = size
    return blockers


def _book_integrity_blockers(
    bids: Mapping[str, str],
    asks: Mapping[str, str],
) -> list[str]:
    blockers: list[str] = []
    if not bids and not asks:
        blockers.append("l2_book_zero_liquidity")
    if not bids or not asks:
        blockers.append("l2_book_one_sided")
        return blockers
    best_bid = max((_decimal(value) for value in bids), default=None)
    best_ask = min((_decimal(value) for value in asks), default=None)
    if best_bid is None or best_ask is None or best_bid >= best_ask:
        blockers.append("l2_book_crossed_or_locked")
    return blockers


def _okx_checksum(
    bids: Mapping[str, str],
    asks: Mapping[str, str],
) -> int:
    bid_rows = sorted(
        bids.items(),
        key=lambda item: _decimal(item[0]) or Decimal(0),
        reverse=True,
    )[:25]
    ask_rows = sorted(
        asks.items(),
        key=lambda item: _decimal(item[0]) or Decimal(0),
    )[:25]
    parts: list[str] = []
    for index in range(max(len(bid_rows), len(ask_rows))):
        if index < len(bid_rows):
            parts.extend(bid_rows[index])
        if index < len(ask_rows):
            parts.extend(ask_rows[index])
    unsigned = zlib.crc32(":".join(parts).encode("utf-8"))
    return unsigned if unsigned < 2**31 else unsigned - 2**32


def _output_record(
    *,
    segment_name: str,
    parsed: Mapping[str, Any],
    item: Mapping[str, Any],
    event_time: datetime,
    receive_time: datetime,
    state: _ReplayState,
) -> dict[str, Any]:
    bids = _sorted_levels(state.bids, reverse=True)
    asks = _sorted_levels(state.asks, reverse=False)
    return {
        "action": parsed["action"],
        "asks": asks,
        "available_time": _utc_text(receive_time),
        "best_ask": float(asks[0][0]),
        "best_bid": float(bids[0][0]),
        "bids": bids,
        "capture_sequence": parsed["capture_sequence"],
        "channel": CHANNEL,
        "checksum": int(item["checksum"]),
        "connection_sequence": parsed["connection_sequence"],
        "event_time": _utc_text(event_time),
        "instrument_id": INSTRUMENT_ID,
        "monotonic_ns": parsed["monotonic_ns"],
        "prev_seq_id": int(item["prevSeqId"]),
        "segment_name": segment_name,
        "seq_id": int(item["seqId"]),
        "snapshot_time": _utc_text(receive_time),
        "venue": VENUE,
    }


def _sorted_levels(
    levels: Mapping[str, str],
    *,
    reverse: bool,
) -> list[list[str]]:
    return [
        [price, size]
        for price, size in sorted(
            levels.items(),
            key=lambda item: _decimal(item[0]) or Decimal(0),
            reverse=reverse,
        )
    ]


def _quarantine(state: _ReplayState) -> None:
    state.active = False
    state.last_seq_id = None
    state.bids.clear()
    state.asks.clear()


def _source_stability_blockers(
    records: Iterable[Mapping[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    for item in records:
        segment_name = str(item["segment_name"])
        for prefix in ("raw", "manifest"):
            path = Path(str(item[f"{prefix}_path"]))
            stat = path.stat()
            if (
                stat.st_size != int(item[f"{prefix}_bytes"])
                or stat.st_mtime_ns != int(item[f"{prefix}_mtime_ns"])
                or _sha256_file(path) != str(item[f"{prefix}_sha256"])
            ):
                blockers.append(
                    f"l2_source_changed_during_export:{segment_name}:{prefix}"
                )
    return blockers


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise L2ExportBlocked(
                    [f"l2_raw_jsonl_invalid:{path.parent.name}:{line_number}"]
                ) from exc
            if not isinstance(payload, Mapping):
                raise L2ExportBlocked(
                    [f"l2_raw_jsonl_row_not_object:{path.parent.name}:{line_number}"]
                )
            yield line_number, dict(payload)


def _exchange_event_time(value: object) -> datetime | None:
    try:
        milliseconds = int(str(value))
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1_000.0, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("utc_timestamp_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("utc_timestamp_invalid")
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return (
        _as_utc(value)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
