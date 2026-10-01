"""Fail-closed export of a proven SQLite snapshot into immutable BTC K-line tables."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.agent_governance.shared_data import aggregate_inventory_hash


EXPORTER_VERSION = "btc_kline_immutable_export_v1"
ATTESTATION_SCHEMA_VERSION = "btc_kline_dataready_attestation_v1"
DATASET_ID = "btc-market-data-sqlite-snapshot"
ATTESTATION_NAME = "btc_kline_dataready_attestation.json"
APPROVED_CURRENT_MAIN_REQUIRED_PARTITIONS = (
    ("binance_spot", "BTCUSDT", "1m"),
    ("binance_spot", "BTCUSDT", "5m"),
    ("binance_spot", "BTCUSDT", "15m"),
    ("binance_spot", "BTCUSDT", "1h"),
)
SOURCE_TABLE = "market_klines"
BASE_REQUIRED_COLUMNS = (
    "exchange",
    "symbol",
    "interval",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
EXPLICIT_TIME_COLUMNS = ("event_time", "available_time", "is_finalized")
CLOSE_TIME_COLUMNS = ("close_time", "close_time_ms")
EXPLICIT_TIME_SEMANTICS = "explicit_event_available_finalized_fields"
DERIVED_CLOSE_TIME_SEMANTICS = "derived_from_close_time"
INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}
IMMUTABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PARTITION_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
CANONICAL_DECIMAL_PLACES = 18
_CANONICAL_DECIMAL_QUANTUM = Decimal("1e-18")


class KlineExportBlocked(RuntimeError):
    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(dict.fromkeys(str(item) for item in blockers if str(item)))
        super().__init__(";".join(self.blockers))


@dataclass
class _PartitionStats:
    exchange: str
    symbol: str
    interval: str
    finalized_count: int = 0
    in_progress_count: int = 0
    min_event_time: datetime | None = None
    max_event_time: datetime | None = None


def export_immutable_klines(
    *,
    source_sqlite: Path,
    expected_source_sha256: str,
    output_dir: Path,
    dataset_version: str,
    source_head: str,
    now: datetime,
    producer_role: str = "data_steward",
    freshness_sla_hours: float = 48.0,
    required_partitions: Iterable[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """Export finalized rows without mutating or publishing the source snapshot."""

    source = source_sqlite.resolve()
    destination = output_dir.resolve()
    checked_at = _as_utc(now)
    blockers = _preflight_blockers(
        source=source,
        destination=destination,
        expected_source_sha256=expected_source_sha256,
        dataset_version=dataset_version,
        source_head=source_head,
        producer_role=producer_role,
        freshness_sla_hours=freshness_sla_hours,
    )
    if blockers:
        raise KlineExportBlocked(blockers)

    source_stat = source.stat()
    source_hash_before = _sha256_file(source)
    if source_hash_before != expected_source_sha256:
        raise KlineExportBlocked(["source_sqlite_sha256_mismatch"])

    connection = sqlite3.connect(
        f"file:{source.as_posix()}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        connection.execute("PRAGMA query_only = ON")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise KlineExportBlocked([f"source_sqlite_integrity_failed:{integrity}"])
        columns = {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({SOURCE_TABLE})")
        }
        missing_columns = sorted(set(BASE_REQUIRED_COLUMNS) - columns)
        if missing_columns:
            raise KlineExportBlocked(
                [f"source_schema_required_column_missing:{name}" for name in missing_columns]
            )
        if set(EXPLICIT_TIME_COLUMNS) <= columns:
            source_time_semantics = EXPLICIT_TIME_SEMANTICS
        elif set(CLOSE_TIME_COLUMNS) <= columns:
            source_time_semantics = DERIVED_CLOSE_TIME_SEMANTICS
        else:
            raise KlineExportBlocked(["source_schema_supported_time_contract_missing"])
        source_partitions = _discover_partitions(connection)
        (
            partition_mode,
            selected_partitions,
            excluded_partitions,
            partition_policy_id,
            partition_blockers,
        ) = _select_partitions(
            source_partitions,
            required_partitions=required_partitions,
        )
        if partition_blockers:
            raise KlineExportBlocked(partition_blockers)
        source_partition_inventory = _source_partition_inventory(
            connection,
            source_partitions=source_partitions,
            selected_partitions=selected_partitions,
            now=checked_at,
            source_time_semantics=source_time_semantics,
            source_sha256=source_hash_before,
            selection_policy_id=partition_policy_id,
        )
        source_partition_inventory_sha256 = _json_sha256(
            source_partition_inventory
        )

        stats, validation_blockers = _scan_source(
            connection,
            now=checked_at,
            source_time_semantics=source_time_semantics,
            required_partitions=selected_partitions,
            source_has_open_time_ms="open_time_ms" in columns,
        )
        if validation_blockers:
            raise KlineExportBlocked(validation_blockers)
        duplicate_groups = _count_duplicate_groups(
            connection,
            partitions=selected_partitions,
            source_time_semantics=source_time_semantics,
            cutoff=checked_at,
        )
        if duplicate_groups:
            raise KlineExportBlocked(
                [f"source_finalized_duplicate_key_groups:{duplicate_groups}"]
            )

        common_end = min(
            item.max_event_time
            for item in stats.values()
            if item.max_event_time is not None
        )
        freshness_age_hours = (checked_at - common_end).total_seconds() / 3_600.0
        if freshness_age_hours < 0:
            raise KlineExportBlocked(["kline_common_end_in_future"])
        if freshness_age_hours > freshness_sla_hours:
            raise KlineExportBlocked(["kline_common_end_freshness_sla_breached"])

        interval_attestations = _quality_attestations(
            connection,
            stats=stats,
            common_end=common_end,
            source_time_semantics=source_time_semantics,
        )
        quality_blockers: list[str] = []
        for item in interval_attestations:
            key = f"{item['venue']}:{item['instrument_id']}:{item['interval']}"
            if item["missing_count"]:
                quality_blockers.append(f"kline_missing_rows:{key}")
            if item["duplicate_count"]:
                quality_blockers.append(f"kline_duplicate_rows:{key}")
            if item["finalized_count"] <= 0:
                quality_blockers.append(f"kline_finalized_rows_missing:{key}")
            if item["coverage_pct"] < 100.0:
                quality_blockers.append(f"kline_partial_coverage:{key}")
        if quality_blockers:
            raise KlineExportBlocked(quality_blockers)

        staging = destination.with_name(
            f".{destination.name}.staging-{uuid.uuid4().hex}"
        )
        staging.mkdir(parents=True, exist_ok=False)
        try:
            table_files = _write_partitioned_tables(
                connection,
                staging=staging,
                stats=stats,
                common_end=common_end,
                dataset_version=dataset_version,
                source_time_semantics=source_time_semantics,
            )
            source_hash_after = _sha256_file(source)
            source_stat_after = source.stat()
            if (
                source_hash_after != source_hash_before
                or source_stat_after.st_size != source_stat.st_size
                or source_stat_after.st_mtime_ns != source_stat.st_mtime_ns
            ):
                raise KlineExportBlocked(["source_sqlite_changed_during_export"])

            coverage_start = min(
                _parse_utc(str(item["coverage_start"]))
                for item in interval_attestations
            )
            table_aggregate_sha256 = aggregate_inventory_hash(table_files)
            attestation = {
                "schema_version": ATTESTATION_SCHEMA_VERSION,
                "exporter_version": EXPORTER_VERSION,
                "producer_role": producer_role,
                "dataset_id": DATASET_ID,
                "dataset_version": dataset_version,
                "source_head": source_head,
                "generated_at": _utc_text(checked_at),
                "timezone": "UTC",
                "event_time_field": "event_time",
                "available_time_field": "available_time",
                "finalized_field": "is_finalized",
                "source_time_semantics": source_time_semantics,
                "partition_selection": {
                    "mode": partition_mode,
                    "policy_id": partition_policy_id,
                    "required_partitions": [
                        _partition_record(key) for key in selected_partitions
                    ],
                    "included_partitions": [
                        _partition_record(key) for key in selected_partitions
                    ],
                    "excluded_partitions": excluded_partitions,
                },
                "source_partition_inventory": source_partition_inventory,
                "source_partition_inventory_sha256": (
                    source_partition_inventory_sha256
                ),
                "pit_available_time_enforced": True,
                "in_progress_excluded_from_consumption": True,
                "coverage_start": _utc_text(coverage_start),
                "coverage_end": _utc_text(common_end),
                "common_end": _utc_text(common_end),
                "freshness_sla_hours": float(freshness_sla_hours),
                "freshness_age_hours": round(freshness_age_hours, 6),
                "intervals": interval_attestations,
                "lineage": {
                    "source_kind": "read_only_consistent_sqlite_snapshot",
                    "source_file_name": source.name,
                    "source_table": SOURCE_TABLE,
                    "source_sha256": source_hash_before,
                    "source_bytes": source_stat.st_size,
                    "sqlite_integrity_check": integrity,
                    "sqlite_open_mode": "mode=ro&immutable=1",
                    "sort_order": [
                        "exchange",
                        "symbol",
                        "interval",
                        "event_time",
                        "available_time",
                    ],
                    "explicit_time_derivation_used": (
                        source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                    ),
                    "explicit_finalized_derivation_used": (
                        source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                    ),
                    "source_event_time_field": (
                        "close_time"
                        if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                        else "event_time"
                    ),
                    "source_available_time_field": (
                        "close_time"
                        if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                        else "available_time"
                    ),
                    "source_finalized_policy": (
                        "close_time_lte_generated_at"
                        if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                        else "explicit_is_finalized"
                    ),
                    "source_close_time_ms_field": (
                        "close_time_ms"
                        if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                        else None
                    ),
                    "source_close_time_validation_policy": (
                        "close_time_ms_equals_iso_epoch_ms_and_inclusive_interval_end"
                        if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                        else "not_applicable_explicit_time_contract"
                    ),
                    "source_open_time_ms_field": (
                        "open_time_ms"
                        if (
                            source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                            and "open_time_ms" in columns
                        )
                        else None
                    ),
                    "source_open_close_duration_policy": (
                        "open_aligned_close_minus_open_equals_interval_ms_minus_one"
                        if (
                            source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
                            and "open_time_ms" in columns
                        )
                        else "not_applicable_open_time_ms_missing"
                    ),
                },
                "files": table_files,
                "aggregate_table_sha256": table_aggregate_sha256,
                "quality_checked": True,
                "promotion_evidence_ready": False,
                "promotion_blockers": [
                    "btc_execution_latency_model_missing",
                    "btc_queue_model_missing",
                    "btc_kline_dataready_not_promotion_evidence",
                ],
                "readiness": {
                    "quality_checked": True,
                    "research_ready": False,
                    "backtest_ready": False,
                    "promotion_evidence_ready": False,
                },
                "guardrails": {
                    "source_sqlite_mutated": False,
                    "sqlite_payload_emitted": False,
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
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
    finally:
        connection.close()

    return {
        "status": "quality_checked",
        "decision": "immutable_kline_export_ready_for_data_steward_publication_review",
        "output_dir": str(destination),
        "attestation_path": str(destination / ATTESTATION_NAME),
        "dataset_id": DATASET_ID,
        "dataset_version": dataset_version,
        "source_sha256": source_hash_before,
        "table_file_count": len(table_files),
        "aggregate_table_sha256": table_aggregate_sha256,
        "common_end": _utc_text(common_end),
        "freshness_age_hours": round(freshness_age_hours, 6),
        "partition_selection": attestation["partition_selection"],
        "source_partition_inventory_sha256": (
            source_partition_inventory_sha256
        ),
        "readiness": {
            "quality_checked": True,
            "research_ready": False,
            "backtest_ready": False,
            "promotion_evidence_ready": False,
        },
        "guardrails": attestation["guardrails"],
    }


def blocked_export_report(
    *,
    blockers: Iterable[str],
    dataset_version: str,
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "decision": "block_immutable_kline_export_fail_closed",
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
            "source_sqlite_mutated": False,
            "sqlite_payload_emitted": False,
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
    source: Path,
    destination: Path,
    expected_source_sha256: str,
    dataset_version: str,
    source_head: str,
    producer_role: str,
    freshness_sla_hours: float,
) -> list[str]:
    blockers: list[str] = []
    if not source.is_file():
        blockers.append("source_sqlite_missing")
    if source.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
        blockers.append("source_sqlite_suffix_invalid")
    if source.with_name(f"{source.name}-wal").exists():
        blockers.append("source_sqlite_wal_present_snapshot_not_stable")
    if source.with_name(f"{source.name}-shm").exists():
        blockers.append("source_sqlite_shm_present_snapshot_not_stable")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_source_sha256):
        blockers.append("expected_source_sha256_invalid")
    if not IMMUTABLE_ID.fullmatch(dataset_version):
        blockers.append("dataset_version_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", source_head):
        blockers.append("source_head_invalid")
    if producer_role != "data_steward":
        blockers.append("attestation_producer_role_must_be_data_steward")
    if freshness_sla_hours <= 0:
        blockers.append("freshness_sla_hours_invalid")
    if destination.exists():
        blockers.append("output_directory_already_exists")
    if destination.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
        blockers.append("output_must_not_be_database_payload")
    return blockers


def _scan_source(
    connection: sqlite3.Connection,
    *,
    now: datetime,
    source_time_semantics: str,
    required_partitions: tuple[tuple[str, str, str], ...],
    source_has_open_time_ms: bool,
) -> tuple[dict[tuple[str, str, str], _PartitionStats], list[str]]:
    stats: dict[tuple[str, str, str], _PartitionStats] = {}
    blockers: list[str] = []
    event_time_column = _event_time_column(source_time_semantics)
    available_time_column = _available_time_column(source_time_semantics)
    finalized_column = (
        "is_finalized"
        if source_time_semantics == EXPLICIT_TIME_SEMANTICS
        else "NULL"
    )
    close_time_ms_column = (
        "close_time_ms"
        if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
        else "NULL"
    )
    open_time_ms_column = (
        "open_time_ms"
        if (
            source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS
            and source_has_open_time_ms
        )
        else "NULL"
    )
    partition_filter, partition_params = _partition_filter(required_partitions)
    query = f"""
        SELECT exchange, symbol, interval, {event_time_column}, {available_time_column},
               {finalized_column}, {close_time_ms_column}, {open_time_ms_column},
               open, high, low, close, volume
        FROM {SOURCE_TABLE}
        WHERE {partition_filter}
        ORDER BY exchange, symbol, interval, {event_time_column}, {available_time_column}
    """
    for index, row in enumerate(
        connection.execute(query, partition_params),
        start=1,
    ):
        exchange, symbol, interval = (str(row[0]), str(row[1]), str(row[2]))
        key = (exchange, symbol, interval)
        if not all(PARTITION_VALUE.fullmatch(value) for value in key):
            blockers.append(f"source_partition_value_invalid:{index}")
            continue
        if interval not in INTERVAL_SECONDS:
            blockers.append(f"source_interval_unsupported:{interval}")
            continue
        try:
            event_time = _parse_utc(str(row[3]))
            available_time = _parse_utc(str(row[4]))
        except ValueError as exc:
            blockers.append(f"source_timestamp_invalid:{index}:{exc}")
            continue
        if source_time_semantics == EXPLICIT_TIME_SEMANTICS:
            if available_time < event_time:
                blockers.append(f"source_available_time_before_event_time:{index}")
            if available_time > now:
                blockers.append(f"source_available_time_after_export_time:{index}")
            finalized = row[5]
            if finalized not in (0, 1, False, True):
                blockers.append(f"source_finalized_value_invalid:{index}")
                continue
        else:
            finalized = event_time <= now
            close_time_ms = _int_or_none(row[6])
            expected_close_time_ms = int(
                round(event_time.timestamp() * 1_000.0)
            )
            if close_time_ms != expected_close_time_ms:
                blockers.append(f"source_close_time_ms_mismatch:{index}")
            interval_ms = INTERVAL_SECONDS[interval] * 1_000
            if (
                close_time_ms is None
                or (close_time_ms + 1) % interval_ms != 0
            ):
                blockers.append(
                    f"source_close_time_interval_boundary_invalid:{index}"
                )
            open_time_ms = _int_or_none(row[7])
            if open_time_ms is not None:
                if open_time_ms % interval_ms != 0:
                    blockers.append(
                        f"source_open_time_interval_boundary_invalid:{index}"
                    )
                if (
                    close_time_ms is None
                    or close_time_ms - open_time_ms != interval_ms - 1
                ):
                    blockers.append(
                        f"source_open_close_duration_invalid:{index}"
                    )
        try:
            open_price, high, low, close, volume = (
                float(row[8]),
                float(row[9]),
                float(row[10]),
                float(row[11]),
                float(row[12]),
            )
        except (TypeError, ValueError):
            blockers.append(f"source_ohlcv_invalid:{index}")
            continue
        if (
            min(open_price, high, low, close) <= 0
            or volume < 0
            or high < max(open_price, low, close)
            or low > min(open_price, high, close)
        ):
            blockers.append(f"source_ohlcv_invalid:{index}")
        partition = stats.setdefault(
            key,
            _PartitionStats(exchange=exchange, symbol=symbol, interval=interval),
        )
        if bool(finalized):
            partition.finalized_count += 1
            partition.min_event_time = (
                event_time
                if partition.min_event_time is None
                else min(partition.min_event_time, event_time)
            )
            partition.max_event_time = (
                event_time
                if partition.max_event_time is None
                else max(partition.max_event_time, event_time)
            )
        else:
            partition.in_progress_count += 1
    if not stats:
        blockers.append("source_kline_partitions_missing")
    for key, item in stats.items():
        if item.finalized_count <= 0 or item.max_event_time is None:
            blockers.append(f"source_finalized_rows_missing:{':'.join(key)}")
    return stats, list(dict.fromkeys(blockers))


def _discover_partitions(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str], ...]:
    rows = connection.execute(
        f"""
        SELECT DISTINCT exchange, symbol, interval
        FROM {SOURCE_TABLE}
        ORDER BY exchange, symbol, interval
        """
    )
    partitions = tuple(
        (str(row[0]), str(row[1]), str(row[2]))
        for row in rows
    )
    if not partitions:
        raise KlineExportBlocked(["source_kline_partitions_missing"])
    blockers: list[str] = []
    for key in partitions:
        if not all(PARTITION_VALUE.fullmatch(value) for value in key):
            blockers.append(f"source_partition_value_invalid:{':'.join(key)}")
        if key[2] not in INTERVAL_SECONDS:
            blockers.append(f"source_interval_unsupported:{key[2]}")
    if blockers:
        raise KlineExportBlocked(blockers)
    return partitions


def _select_partitions(
    source_partitions: tuple[tuple[str, str, str], ...],
    *,
    required_partitions: Iterable[tuple[str, str, str]] | None,
) -> tuple[
    str,
    tuple[tuple[str, str, str], ...],
    list[dict[str, str]],
    str,
    list[str],
]:
    source_set = set(source_partitions)
    if required_partitions is None:
        return (
            "all_source_partitions",
            source_partitions,
            [],
            "all_source_partitions_strict_v1",
            [],
        )
    requested = tuple(
        tuple(str(value) for value in item)
        for item in required_partitions
    )
    blockers: list[str] = []
    if not requested:
        blockers.append("required_partition_set_empty")
    normalized: list[tuple[str, str, str]] = []
    for item in requested:
        if len(item) != 3:
            blockers.append("required_partition_selector_invalid")
            continue
        key = (item[0], item[1], item[2])
        if not all(PARTITION_VALUE.fullmatch(value) for value in key):
            blockers.append(f"required_partition_selector_invalid:{':'.join(key)}")
            continue
        if key[2] not in INTERVAL_SECONDS:
            blockers.append(f"required_partition_interval_unsupported:{key[2]}")
            continue
        normalized.append(key)
    if len(normalized) != len(set(normalized)):
        blockers.append("required_partition_selector_duplicate")
    selected = tuple(sorted(set(normalized)))
    for key in selected:
        if key not in source_set:
            blockers.append(f"required_partition_missing:{':'.join(key)}")
    is_current_main_source = any(
        key[0] == "binance_spot" and key[1] == "BTCUSDT"
        for key in source_partitions
    )
    if is_current_main_source:
        policy_id = "btc_v3_current_main_binance_spot_required_v1"
        if set(selected) != set(APPROVED_CURRENT_MAIN_REQUIRED_PARTITIONS):
            blockers.append(
                "approved_current_main_required_partition_set_mismatch"
            )
    else:
        policy_id = "explicit_required_partitions_v1"
    excluded = [
        {
            **_partition_record(key),
            "reason": "excluded_non_required",
        }
        for key in source_partitions
        if key not in set(selected)
    ]
    return (
        "explicit_required_partitions",
        selected,
        excluded,
        policy_id,
        list(dict.fromkeys(blockers)),
    )


def _partition_record(key: tuple[str, str, str]) -> dict[str, str]:
    return {
        "venue": key[0],
        "instrument_id": key[1],
        "interval": key[2],
    }


def _source_partition_inventory(
    connection: sqlite3.Connection,
    *,
    source_partitions: tuple[tuple[str, str, str], ...],
    selected_partitions: tuple[tuple[str, str, str], ...],
    now: datetime,
    source_time_semantics: str,
    source_sha256: str,
    selection_policy_id: str,
) -> list[dict[str, Any]]:
    selected = set(selected_partitions)
    cutoff = _utc_text(now)
    if source_time_semantics == EXPLICIT_TIME_SEMANTICS:
        finalized_condition = (
            "is_finalized = 1 AND julianday(available_time) <= julianday(?)"
        )
        event_time_column = "event_time"
    else:
        finalized_condition = "julianday(close_time) <= julianday(?)"
        event_time_column = "close_time"

    inventory: list[dict[str, Any]] = []
    for key in source_partitions:
        row = connection.execute(
            f"""
            SELECT
                COUNT(*),
                SUM(CASE WHEN {finalized_condition} THEN 1 ELSE 0 END),
                MIN(CASE WHEN {finalized_condition} THEN {event_time_column} END),
                MAX(CASE WHEN {finalized_condition} THEN {event_time_column} END)
            FROM {SOURCE_TABLE}
            WHERE exchange = ? AND symbol = ? AND interval = ?
            """,
            (cutoff, cutoff, cutoff, *key),
        ).fetchone()
        total_count = int(row[0] or 0)
        finalized_count = int(row[1] or 0)
        coverage_start = _parse_utc(str(row[2])) if row[2] is not None else None
        common_end = _parse_utc(str(row[3])) if row[3] is not None else None
        base_record: dict[str, Any] = {
            **_partition_record(key),
            "total_row_count": total_count,
            "finalized_count": finalized_count,
            "in_progress_count": total_count - finalized_count,
            "coverage_start": (
                _utc_text(coverage_start) if coverage_start is not None else None
            ),
            "common_end": (
                _utc_text(common_end) if common_end is not None else None
            ),
            "freshness_age_hours": (
                round((now - common_end).total_seconds() / 3_600.0, 6)
                if common_end is not None
                else None
            ),
            "selection_status": (
                "included_required" if key in selected else "excluded_non_required"
            ),
            "selection_policy": (
                selection_policy_id
            ),
            "source_sha256": source_sha256,
        }
        base_record["partition_inventory_sha256"] = _json_sha256(base_record)
        inventory.append(base_record)
    return inventory


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _partition_filter(
    partitions: tuple[tuple[str, str, str], ...],
) -> tuple[str, tuple[str, ...]]:
    if not partitions:
        return "0 = 1", ()
    clauses = [
        "(exchange = ? AND symbol = ? AND interval = ?)"
        for _ in partitions
    ]
    params = tuple(value for key in partitions for value in key)
    return f"({' OR '.join(clauses)})", params


def _count_duplicate_groups(
    connection: sqlite3.Connection,
    *,
    partitions: tuple[tuple[str, str, str], ...],
    source_time_semantics: str,
    cutoff: datetime,
) -> int:
    event_time_column = _event_time_column(source_time_semantics)
    finalized_filter, finalized_params = _finalized_filter(
        source_time_semantics,
        cutoff=cutoff,
    )
    count = 0
    for key in partitions:
        count += int(
            connection.execute(
                f"""
                SELECT COUNT(*) FROM (
                    SELECT {event_time_column}
                    FROM {SOURCE_TABLE}
                    WHERE exchange = ? AND symbol = ? AND interval = ?
                      AND {finalized_filter}
                    GROUP BY {event_time_column}
                    HAVING COUNT(*) > 1
                )
                """,
                (*key, *finalized_params),
            ).fetchone()[0]
        )
    return count


def _event_time_column(source_time_semantics: str) -> str:
    if source_time_semantics == EXPLICIT_TIME_SEMANTICS:
        return "event_time"
    if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS:
        return "close_time"
    raise ValueError(f"unsupported_source_time_semantics:{source_time_semantics}")


def _available_time_column(source_time_semantics: str) -> str:
    if source_time_semantics == EXPLICIT_TIME_SEMANTICS:
        return "available_time"
    if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS:
        return "close_time"
    raise ValueError(f"unsupported_source_time_semantics:{source_time_semantics}")


def _finalized_filter(
    source_time_semantics: str,
    *,
    cutoff: datetime,
) -> tuple[str, tuple[str, ...]]:
    cutoff_text = _utc_text(cutoff)
    if source_time_semantics == EXPLICIT_TIME_SEMANTICS:
        return "is_finalized = 1 AND event_time <= ?", (cutoff_text,)
    if source_time_semantics == DERIVED_CLOSE_TIME_SEMANTICS:
        return "julianday(close_time) <= julianday(?)", (cutoff_text,)
    raise ValueError(f"unsupported_source_time_semantics:{source_time_semantics}")


def _quality_attestations(
    connection: sqlite3.Connection,
    *,
    stats: Mapping[tuple[str, str, str], _PartitionStats],
    common_end: datetime,
    source_time_semantics: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    common_end_text = _utc_text(common_end)
    event_time_column = _event_time_column(source_time_semantics)
    finalized_filter, finalized_params = _finalized_filter(
        source_time_semantics,
        cutoff=common_end,
    )
    for key in sorted(stats):
        item = stats[key]
        first_row = connection.execute(
            f"""
            SELECT MIN({event_time_column})
            FROM {SOURCE_TABLE}
            WHERE exchange = ? AND symbol = ? AND interval = ?
              AND {finalized_filter}
            """,
            (*key, *finalized_params),
        ).fetchone()
        count_row = connection.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT {event_time_column})
            FROM {SOURCE_TABLE}
            WHERE exchange = ? AND symbol = ? AND interval = ?
              AND {finalized_filter}
            """,
            (*key, *finalized_params),
        ).fetchone()
        coverage_start = _parse_utc(str(first_row[0]))
        finalized_count = int(count_row[0])
        duplicate_count = finalized_count - int(count_row[1])
        expected_count = (
            int(
                (common_end - coverage_start).total_seconds()
                // INTERVAL_SECONDS[item.interval]
            )
            + 1
        )
        missing_count = max(0, expected_count - int(count_row[1]))
        coverage_pct = (
            round(100.0 * int(count_row[1]) / expected_count, 9)
            if expected_count > 0
            else 0.0
        )
        results.append(
            {
                "venue": item.exchange,
                "instrument_id": item.symbol,
                "interval": item.interval,
                "coverage_start": _utc_text(coverage_start),
                "coverage_end": common_end_text,
                "coverage_pct": coverage_pct,
                "missing_count": missing_count,
                "duplicate_count": duplicate_count,
                "finalized_count": finalized_count,
                "in_progress_count": item.in_progress_count,
                "in_progress_excluded": True,
                "common_end": common_end_text,
            }
        )
    return results


def _write_partitioned_tables(
    connection: sqlite3.Connection,
    *,
    staging: Path,
    stats: Mapping[tuple[str, str, str], _PartitionStats],
    common_end: datetime,
    dataset_version: str,
    source_time_semantics: str,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    event_time_column = _event_time_column(source_time_semantics)
    available_time_column = _available_time_column(source_time_semantics)
    finalized_filter, finalized_params = _finalized_filter(
        source_time_semantics,
        cutoff=common_end,
    )
    for key in sorted(stats):
        exchange, symbol, interval = key
        relative = (
            Path(f"exchange={exchange}")
            / f"symbol={symbol}"
            / f"interval={interval}"
            / "part-00000.jsonl"
        )
        path = staging / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        row_count = 0
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            rows = connection.execute(
                f"""
                SELECT {event_time_column}, {available_time_column},
                       open, high, low, close, volume
                FROM {SOURCE_TABLE}
                WHERE exchange = ? AND symbol = ? AND interval = ?
                  AND {finalized_filter}
                ORDER BY {event_time_column}, {available_time_column}
                """,
                (*key, *finalized_params),
            )
            for row in rows:
                numeric_values = {
                    "close": _canonical_numeric_text(row[5]),
                    "high": _canonical_numeric_text(row[3]),
                    "low": _canonical_numeric_text(row[4]),
                    "open": _canonical_numeric_text(row[2]),
                    "volume": _canonical_numeric_text(row[6]),
                }
                canonical_decimals = {
                    key: Decimal(value)
                    for key, value in numeric_values.items()
                }
                if (
                    min(
                        canonical_decimals["open"],
                        canonical_decimals["high"],
                        canonical_decimals["low"],
                        canonical_decimals["close"],
                    )
                    <= 0
                    or canonical_decimals["volume"] < 0
                    or canonical_decimals["high"]
                    < max(
                        canonical_decimals["open"],
                        canonical_decimals["low"],
                        canonical_decimals["close"],
                    )
                    or canonical_decimals["low"]
                    > min(
                        canonical_decimals["open"],
                        canonical_decimals["high"],
                        canonical_decimals["close"],
                    )
                ):
                    raise KlineExportBlocked(
                        ["export_canonical_ohlcv_relation_invalid"]
                    )
                payload = {
                    "available_time": _utc_text(_parse_utc(str(row[1]))),
                    "close": None,
                    "data_version": dataset_version,
                    "event_time": _utc_text(_parse_utc(str(row[0]))),
                    "exchange": exchange,
                    "high": None,
                    "interval": interval,
                    "is_finalized": True,
                    "low": None,
                    "open": None,
                    "symbol": symbol,
                    "volume": None,
                }
                handle.write(
                    _json_object_with_canonical_numbers(payload, numeric_values)
                    + "\n"
                )
                row_count += 1
            handle.flush()
            os.fsync(handle.fileno())
        files.append(
            {
                "path": relative.as_posix(),
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
                "row_count": row_count,
            }
        )
    return files


def _canonical_numeric_text(value: object) -> str:
    """Return a finite decimal18 JSON number without binary-float tails."""

    try:
        candidate = Decimal(str(value))
    except (DecimalException, TypeError, ValueError):
        raise KlineExportBlocked(["export_numeric_invalid"])
    if not candidate.is_finite():
        raise KlineExportBlocked(["export_numeric_not_finite"])
    if candidate == 0:
        return "0"
    try:
        raw_adjusted = candidate.adjusted()
    except (DecimalException, ValueError):
        raise KlineExportBlocked(["export_numeric_invalid"])
    if (
        raw_adjusted > CANONICAL_DECIMAL_PLACES
        or raw_adjusted < -CANONICAL_DECIMAL_PLACES
    ):
        raise KlineExportBlocked(["export_numeric_range_invalid"])
    digits = candidate.as_tuple().digits
    exponent = candidate.as_tuple().exponent
    with localcontext() as context:
        context.prec = max(
            50,
            len(digits) + abs(exponent) + CANONICAL_DECIMAL_PLACES + 4,
        )
        try:
            rounded = candidate.quantize(
                _CANONICAL_DECIMAL_QUANTUM,
                rounding=ROUND_HALF_EVEN,
            )
        except DecimalException:
            raise KlineExportBlocked(["export_numeric_precision_invalid"])
    if rounded == 0:
        raise KlineExportBlocked(["export_numeric_precision_underflow"])
    if (
        rounded.adjusted() < -CANONICAL_DECIMAL_PLACES
        or rounded.adjusted() > CANONICAL_DECIMAL_PLACES
        or abs(rounded) > Decimal("1e18")
    ):
        raise KlineExportBlocked(["export_numeric_range_invalid"])
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _json_object_with_canonical_numbers(
    payload: Mapping[str, Any],
    numeric_values: Mapping[str, str],
) -> str:
    fields: list[str] = []
    for key in sorted(payload):
        encoded_key = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
        if key in numeric_values:
            encoded_value = numeric_values[key]
        else:
            encoded_value = json.dumps(
                payload[key],
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        fields.append(f"{encoded_key}:{encoded_value}")
    return "{" + ",".join(fields) + "}"


def _parse_utc(value: str) -> datetime:
    if not UTC_TIMESTAMP.fullmatch(value) and not value.endswith("+00:00"):
        raise ValueError("utc_z_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("utc_z_required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("utc_z_required")
    return parsed.astimezone(timezone.utc)


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


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
