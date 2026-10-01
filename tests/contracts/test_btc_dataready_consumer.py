from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Overflow, localcontext
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

import quant_crypto.data.dataready_consumer as dataready_consumer_module
import scripts.build_btc_dataready_consumption_report as consumption_report_builder
from quant_crypto.adapters.btc_runtime_artifact_store import (
    ENVIRONMENT_VARIABLE,
    OWNER_MARKER_NAME,
    BTCRuntimeArtifactWriter,
    build_btc_runtime_artifact_owner_marker,
)
from quant_crypto.data.dataready_consumer import (
    KLINE_ATTESTATION_PATH,
    KLINE_MANIFEST_DATA_SCHEMA,
    L2_ATTESTATION_PATH,
    L2_DATASET_ID,
    L2_MANIFEST_DATA_SCHEMA,
    SNAPSHOT_DATASET_ID,
    _validate_kline_attestation,
    _validate_l2_payload_row,
    _validate_l2_attestation,
    _readiness_consistency_blockers,
    consume_btc_dataready,
)
from tools.agent_governance.shared_data import (
    MANIFEST_NAME,
    aggregate_inventory_hash,
    build_manifest,
    inventory_directory,
)


UTC = timezone.utc
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
COMMIT = "a" * 40
REPORT_SCHEMA = json.loads(
    Path("schemas/btc_dataready_consumption_report.schema.json").read_text(encoding="utf-8")
)
CURRENT_REPORT = Path(
    "docs/handoffs/BTC-V3-DATAREADY-CONSUMER-01-consumption-report.json"
)
L2_BLOCKED_MANIFEST_DATA_SCHEMA = "btc_okx_l2_blocked_attestation_v1"


def _runtime_pointer(*, published: bool = True) -> dict:
    return {
        "schema_version": "mutable_runtime_storage_pointer_v1",
        "storage_id": "btc-market-data",
        "owner_role": "data_steward",
        "writer_mode": "single_writer",
        "immutable_publication": {
            "dataset_id": SNAPSHOT_DATASET_ID,
            "status": "published" if published else "awaiting_data_steward_publication",
            "blockers": [] if published else [
                "immutable_snapshot_not_published",
                "data_steward_attestation_required",
            ],
        },
        "guardrails": {
            "runtime_database_is_promotion_evidence": False,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
        },
    }


def _kline_attestation(**overrides: object) -> dict:
    common_end = (NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    source_sha256 = "c" * 64
    inventory = []
    intervals = []
    files = []
    for interval, seconds in (("1m", 60), ("1h", 3_600)):
        coverage_start = (
            datetime.fromisoformat(common_end.replace("Z", "+00:00"))
            - timedelta(seconds=2 * seconds)
        ).isoformat().replace("+00:00", "Z")
        item = {
            "venue": "okx",
            "instrument_id": "BTC-USDT-SWAP",
            "interval": interval,
            "total_row_count": 4,
            "finalized_count": 3,
            "in_progress_count": 1,
            "coverage_start": coverage_start,
            "common_end": common_end,
            "freshness_age_hours": 1.0,
            "selection_status": "included_required",
            "selection_policy": "explicit_required_partitions_v1",
            "source_sha256": source_sha256,
        }
        item["partition_inventory_sha256"] = _canonical_sha256(item)
        inventory.append(item)
        intervals.append(
            {
                "venue": "okx",
                "instrument_id": "BTC-USDT-SWAP",
                "interval": interval,
                "coverage_start": coverage_start,
                "coverage_end": common_end,
                "coverage_pct": 100.0,
                "missing_count": 0,
                "duplicate_count": 0,
                "finalized_count": 3,
                "in_progress_count": 1,
                "in_progress_excluded": True,
                "common_end": common_end,
            }
        )
        files.append(
            {
                "path": (
                    "exchange=okx/symbol=BTC-USDT-SWAP/"
                    f"interval={interval}/part-00000.jsonl"
                ),
                "sha256": "d" * 64 if interval == "1m" else "e" * 64,
                "bytes": 100,
                "row_count": 3,
            }
        )
    payload = {
        "schema_version": "btc_kline_dataready_attestation_v1",
        "exporter_version": "btc_kline_immutable_export_v1",
        "producer_role": "data_steward",
        "dataset_id": SNAPSHOT_DATASET_ID,
        "dataset_version": "2026-07-24T110000Z",
        "source_head": COMMIT,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "timezone": "UTC",
        "event_time_field": "event_time",
        "available_time_field": "available_time",
        "finalized_field": "is_finalized",
        "source_time_semantics": "explicit_event_available_finalized_fields",
        "pit_available_time_enforced": True,
        "in_progress_excluded_from_consumption": True,
        "partition_selection": {
            "mode": "explicit_required_partitions",
            "policy_id": "explicit_required_partitions_v1",
            "required_partitions": [
                {
                    "venue": "okx",
                    "instrument_id": "BTC-USDT-SWAP",
                    "interval": "1m",
                },
                {
                    "venue": "okx",
                    "instrument_id": "BTC-USDT-SWAP",
                    "interval": "1h",
                },
            ],
            "included_partitions": [
                {
                    "venue": "okx",
                    "instrument_id": "BTC-USDT-SWAP",
                    "interval": "1m",
                },
                {
                    "venue": "okx",
                    "instrument_id": "BTC-USDT-SWAP",
                    "interval": "1h",
                },
            ],
            "excluded_partitions": [],
        },
        "source_partition_inventory": inventory,
        "source_partition_inventory_sha256": _canonical_sha256(inventory),
        "lineage": {
            "source_kind": "read_only_consistent_sqlite_snapshot",
            "source_file_name": "fixture.sqlite",
            "source_table": "market_klines",
            "source_sha256": source_sha256,
            "source_bytes": 1_024,
            "sqlite_integrity_check": "ok",
            "sqlite_open_mode": "mode=ro&immutable=1",
            "sort_order": [
                "exchange",
                "symbol",
                "interval",
                "event_time",
                "available_time",
            ],
            "explicit_time_derivation_used": False,
            "explicit_finalized_derivation_used": False,
            "source_event_time_field": "event_time",
            "source_available_time_field": "available_time",
            "source_finalized_policy": "explicit_is_finalized",
            "source_close_time_ms_field": None,
            "source_close_time_validation_policy": (
                "not_applicable_explicit_time_contract"
            ),
            "source_open_time_ms_field": None,
            "source_open_close_duration_policy": (
                "not_applicable_open_time_ms_missing"
            ),
        },
        "coverage_start": min(
            item["coverage_start"] for item in intervals
        ),
        "coverage_end": common_end,
        "common_end": common_end,
        "freshness_sla_hours": 1.0,
        "freshness_age_hours": 1.0,
        "intervals": intervals,
        "files": files,
        "aggregate_table_sha256": aggregate_inventory_hash(files),
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
    payload.update(overrides)
    return payload


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _l2_attestation(**overrides: object) -> dict:
    common_end = (NOW - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    coverage_start = (
        datetime.fromisoformat(common_end.replace("Z", "+00:00"))
        - timedelta(seconds=2)
    ).isoformat().replace("+00:00", "Z")
    span_seconds = (
        datetime.fromisoformat(common_end.replace("Z", "+00:00"))
        - datetime.fromisoformat(coverage_start.replace("Z", "+00:00"))
    ).total_seconds()
    payload = {
        "schema_version": "btc_okx_l2_dataready_attestation_v1",
        "exporter_version": "btc_okx_l2_immutable_export_v5",
        "producer_role": "data_steward",
        "dataset_id": L2_DATASET_ID,
        "dataset_version": "2026-07-24T115000Z",
        "source_head": COMMIT,
        "generated_at": NOW.isoformat().replace("+00:00", "Z"),
        "venue": "okx",
        "instrument_id": "BTC-USDT-SWAP",
        "channel": "books",
        "timezone": "UTC",
        "event_time_field": "event_time",
        "snapshot_time_field": "snapshot_time",
        "available_time_field": "available_time",
        "sequence_validation_status": "pass",
        "sequence_gap_count": 0,
        "duplicate_sequence_count": 0,
        "out_of_order_sequence_count": 0,
        "unrecovered_gap_count": 0,
        "checksum_observed_count": 3,
        "checksum_validated_count": 0,
        "checksum_policy": (
            "nonzero_crc32_validated_zero_accepted_after_okx_deprecation"
        ),
        "event_snapshot_time_order_valid": True,
        "two_sided_snapshot_count": 3,
        "two_sided_coverage_pct": 100.0,
        "clock_offset_attested": True,
        "max_clock_offset_ms": 120.0,
        "max_clock_lag_policy_ms": 5_000.0,
        "max_inter_message_gap_seconds": 5.0,
        "inter_message_gap_policy_id": "btc_okx_l2_inter_message_gap_v1",
        "approved_max_inter_message_gap_seconds": 5.0,
        "endpoint_anchor_tolerance_seconds": 0.1,
        "capture_duration_tolerance_seconds": 0.2,
        "observed_history_policy": (
            "sum_min_receive_monotonic_contiguous_deltas_excluding_"
            "reconnect_idle_and_unobserved_endpoint_gaps"
        ),
        "coverage_start": coverage_start,
        "coverage_end": common_end,
        "common_start": coverage_start,
        "common_end": common_end,
        "freshness_sla_minutes": 15.0,
        "freshness_age_minutes": 10.0,
        "observed_history_seconds": span_seconds,
        "history_window_days": span_seconds / 86_400.0,
        "coverage_span_days": span_seconds / 86_400.0,
        "segment_count": 1,
        "snapshot_count": 1,
        "update_count": 2,
        "book_record_count": 3,
        "reconnect_count": 0,
        "resync_snapshot_count": 0,
        "gap_windows": [],
        "source_segments": [
            {
                "segment_name": "segment-a",
                "data_version": "segment-a",
                "raw_sha256": "1" * 64,
                "manifest_sha256": "2" * 64,
                "raw_bytes": 100,
                "manifest_bytes": 100,
                "capture_start": coverage_start,
                "capture_end": common_end,
                "raw_first_receive_time": coverage_start,
                "raw_last_receive_time": common_end,
                "max_clock_offset_ms": 120.0,
                "capture_duration_seconds": span_seconds,
                "capture_started_monotonic_ns": 1_000_000_000,
                "capture_ended_monotonic_ns": (
                    1_000_000_000 + int(span_seconds * 1_000_000_000)
                ),
                "raw_receive_span_seconds": span_seconds,
                "raw_monotonic_span_seconds": span_seconds,
                "clock_span_drift_seconds": 0.0,
                "endpoint_gap_count": 0,
                "raw_row_count": 3,
                "books_row_count": 3,
                "manifest_connection_count": 1,
                "manifest_gap_count": 0,
                "observed_reconnect_count": 0,
                "snapshot_count": 1,
                "update_count": 2,
                "output_record_count": 3,
                "blockers": [],
            }
        ],
        "source_aggregate_sha256": "3" * 64,
        "files": [
            {
                "path": (
                    "venue=okx/instrument_id=BTC-USDT-SWAP/"
                    "date=2026-07-24/part-00000.jsonl"
                ),
                "sha256": "4" * 64,
                "bytes": 100,
                "row_count": 3,
            }
        ],
        "aggregate_table_sha256": "5" * 64,
        "quality_checked": True,
        "promotion_evidence_ready": False,
        "promotion_blockers": [
            "btc_okx_l2_history_below_30_natural_days",
            "btc_execution_latency_model_missing",
            "btc_queue_model_missing",
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
    payload.update(overrides)
    payload["source_aggregate_sha256"] = _canonical_sha256(
        [
            {
                "segment_name": item["segment_name"],
                "raw_sha256": item["raw_sha256"],
                "manifest_sha256": item["manifest_sha256"],
            }
            for item in payload["source_segments"]
        ]
    )
    payload["aggregate_table_sha256"] = aggregate_inventory_hash(
        payload["files"]
    )
    return payload


def _publish_fixture(
    shared_root: Path,
    *,
    dataset_id: str,
    dataset_version: str,
    attestation_name: str,
    attestation: dict,
) -> tuple[dict, Path]:
    target = shared_root / "datasets" / dataset_id / dataset_version
    target.mkdir(parents=True)
    for item in attestation["files"]:
        table_path = target / item["path"]
        table_path.parent.mkdir(parents=True, exist_ok=True)
        if dataset_id == L2_DATASET_ID:
            start = datetime.fromisoformat(
                attestation["common_start"].replace("Z", "+00:00")
            )
            content = "".join(
                json.dumps(
                    {
                        "action": "snapshot" if index == 0 else "update",
                        "asks": [["101", "1"]],
                        "available_time": (
                            start
                            + timedelta(seconds=index, milliseconds=120)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "best_ask": 101.0,
                        "best_bid": 99.0,
                        "bids": [["99", "1"]],
                        "capture_sequence": index + 1,
                        "channel": "books",
                        "checksum": 0,
                        "connection_sequence": 1,
                        "event_time": (start + timedelta(seconds=index))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "instrument_id": "BTC-USDT-SWAP",
                        "monotonic_ns": (index + 1) * 1_000_000_000,
                        "prev_seq_id": -1 if index == 0 else 9 + index,
                        "segment_name": "segment-a",
                        "seq_id": 10 + index,
                        "snapshot_time": (
                            start
                            + timedelta(seconds=index, milliseconds=120)
                        )
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "venue": "okx",
                    },
                    sort_keys=True,
                )
                + "\n"
                for index in range(int(item["row_count"]))
            )
        else:
            interval = item["path"].split("interval=", 1)[1].split("/", 1)[0]
            step = timedelta(
                seconds={"1m": 60, "1h": 3_600}[interval]
            )
            interval_item = next(
                (
                    row
                    for row in attestation["intervals"]
                    if row["interval"] == interval
                ),
                None,
            )
            start = (
                datetime.fromisoformat(
                    interval_item["coverage_start"].replace("Z", "+00:00")
                )
                if interval_item is not None
                else datetime.fromisoformat(
                    attestation["common_end"].replace("Z", "+00:00")
                )
                - (int(item["row_count"]) - 1) * step
            )
            content = "".join(
                json.dumps(
                    {
                        "event_time": (start + index * step)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "available_time": (start + index * step)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "is_finalized": True,
                        "exchange": "okx",
                        "symbol": "BTC-USDT-SWAP",
                        "interval": interval,
                        "open": 100.0,
                        "high": 102.0,
                        "low": 98.0,
                        "close": 101.0,
                        "volume": 1.0,
                        "data_version": dataset_version,
                    },
                    sort_keys=True,
                )
                + "\n"
                for index in range(int(item["row_count"]))
            )
        table_path.write_text(content, encoding="utf-8")
        item["sha256"] = hashlib.sha256(table_path.read_bytes()).hexdigest()
        item["bytes"] = table_path.stat().st_size
    attestation["aggregate_table_sha256"] = aggregate_inventory_hash(
        attestation["files"]
    )
    (target / attestation_name).write_text(
        json.dumps(attestation, sort_keys=True),
        encoding="utf-8",
    )
    files, aggregate_sha256, total_bytes = inventory_directory(target)
    manifest = build_manifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        readiness_class="quality_checked",
        quality_status="pass",
        files=files,
        aggregate_sha256=aggregate_sha256,
        total_bytes=total_bytes,
        producer_commit=COMMIT,
        schema_name=(
            KLINE_MANIFEST_DATA_SCHEMA
            if dataset_id == SNAPSHOT_DATASET_ID
            else L2_MANIFEST_DATA_SCHEMA
        ),
        coverage_start=str(attestation["coverage_start"]),
        coverage_end=str(attestation["coverage_end"]),
        published_at="2026-07-24T11:55:00Z",
    )
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return manifest, target


def _valid_inputs(shared_root: Path) -> tuple[dict, dict]:
    snapshot, _ = _publish_fixture(
        shared_root,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version="2026-07-24T110000Z",
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=_kline_attestation(),
    )
    l2, _ = _publish_fixture(
        shared_root,
        dataset_id=L2_DATASET_ID,
        dataset_version="2026-07-24T115000Z",
        attestation_name=L2_ATTESTATION_PATH,
        attestation=_l2_attestation(),
    )
    return snapshot, l2


def _consume(shared_root: Path, snapshot: dict | None, l2: dict | None, **overrides: object) -> dict:
    return consume_btc_dataready(
        runtime_pointer=overrides.pop("runtime_pointer", _runtime_pointer()),
        snapshot_manifest=snapshot,
        l2_manifest=l2,
        shared_root=shared_root,
        current_head="b" * 40,
        now=NOW,
        commit_exists=overrides.pop("commit_exists", lambda _: True),
        snapshot_manifest_source="HEAD:.agent/data_manifests/snapshot.json" if snapshot else "",
        l2_manifest_source="HEAD:.agent/data_manifests/l2.json" if l2 else "",
        **overrides,
    )


def _discovery_manifest(
    *,
    dataset_id: str = SNAPSHOT_DATASET_ID,
    dataset_version: str = "version-a",
    data_schema: str = KLINE_MANIFEST_DATA_SCHEMA,
    quality_status: str = "pass",
    blockers: tuple[str, ...] = (),
) -> dict:
    return build_manifest(
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        readiness_class="quality_checked",
        quality_status=quality_status,
        files=[
            {
                "path": "part-00000.jsonl",
                "sha256": "a" * 64,
                "bytes": 1,
            }
        ],
        aggregate_sha256="b" * 64,
        total_bytes=1,
        producer_commit=COMMIT,
        blockers=blockers,
        schema_name=data_schema,
        published_at="2026-07-24T11:55:00Z",
    )


def _patch_committed_manifest_tree(
    monkeypatch,
    payloads: dict[str, dict],
) -> None:
    monkeypatch.setattr(
        consumption_report_builder,
        "_git_text",
        lambda *_args: "\n".join(payloads),
    )
    monkeypatch.setattr(
        consumption_report_builder,
        "_load_committed_json",
        lambda _repo_root, _ref, path: payloads.get(path),
    )


def test_dataready_report_writer_uses_external_runtime_artifact_root(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source-worktree"
    source_root.mkdir()
    artifact_root = tmp_path / "runtime-artifacts"
    artifact_root.mkdir()
    repository_identity = "sha256:" + "a" * 64
    (artifact_root / OWNER_MARKER_NAME).write_text(
        json.dumps(build_btc_runtime_artifact_owner_marker(repository_identity)),
        encoding="utf-8",
    )
    writer = BTCRuntimeArtifactWriter.from_environment(
        source_repo_root=source_root,
        environment={ENVIRONMENT_VARIABLE: str(artifact_root)},
        repository_identity=repository_identity,
        worktree_roots=(source_root,),
    )
    report = {"status": "blocked", "promotion_evidence_ready": False}

    physical_path = consumption_report_builder.write_report(
        repo_root=source_root,
        logical_output=consumption_report_builder.DEFAULT_OUTPUT,
        report=report,
        artifact_writer=writer,
    )

    assert physical_path == (
        artifact_root
        / "btc_dataready_consumption/latest/btc_dataready_consumption_report.json"
    )
    assert json.loads(physical_path.read_text(encoding="utf-8")) == report
    assert not (source_root / "artifacts").exists()


def test_manifest_discovery_ignores_attestation_with_same_dataset_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    manifest_path = ".agent/data_manifests/btc/snapshot-version-a.json"
    attestation_path = (
        ".agent/data_manifests/btc/snapshot-version-a-attestation.json"
    )
    manifest = _discovery_manifest()
    _patch_committed_manifest_tree(
        monkeypatch,
        {
            manifest_path: manifest,
            attestation_path: {
                "schema_version": "btc_kline_dataready_attestation_v1",
                "dataset_id": SNAPSHOT_DATASET_ID,
                "dataset_version": "version-a",
            },
        },
    )

    payload, source, blocker = consumption_report_builder._discover_manifest(
        tmp_path,
        COMMIT,
        SNAPSHOT_DATASET_ID,
    )

    assert payload == manifest
    assert source == f"{COMMIT}:{manifest_path}"
    assert blocker == ""


def test_manifest_discovery_blocks_multiple_versions_without_selection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path_a = ".agent/data_manifests/btc/snapshot-version-a.json"
    path_b = ".agent/data_manifests/btc/snapshot-version-b.json"
    _patch_committed_manifest_tree(
        monkeypatch,
        {
            path_a: _discovery_manifest(dataset_version="version-a"),
            path_b: _discovery_manifest(dataset_version="version-b"),
        },
    )

    payload, source, blocker = consumption_report_builder._discover_manifest(
        tmp_path,
        COMMIT,
        SNAPSHOT_DATASET_ID,
    )

    assert payload is None
    assert source == ""
    assert blocker == (
        f"committed_manifest_selection_required:{SNAPSHOT_DATASET_ID}"
    )


def test_manifest_discovery_explicit_path_and_version_select_exact_commit_object(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path_a = ".agent/data_manifests/btc/snapshot-version-a.json"
    path_b = ".agent/data_manifests/btc/snapshot-version-b.json"
    manifest_a = _discovery_manifest(dataset_version="version-a")
    manifest_b = _discovery_manifest(dataset_version="version-b")
    _patch_committed_manifest_tree(
        monkeypatch,
        {path_a: manifest_a, path_b: manifest_b},
    )

    by_path, path_source, path_blocker = (
        consumption_report_builder._discover_manifest(
            tmp_path,
            COMMIT,
            SNAPSHOT_DATASET_ID,
            manifest_path=path_a,
            dataset_version="version-a",
        )
    )
    by_version, version_source, version_blocker = (
        consumption_report_builder._discover_manifest(
            tmp_path,
            COMMIT,
            SNAPSHOT_DATASET_ID,
            dataset_version="version-b",
        )
    )

    assert by_path == manifest_a
    assert path_source == f"{COMMIT}:{path_a}"
    assert path_blocker == ""
    assert by_version == manifest_b
    assert version_source == f"{COMMIT}:{path_b}"
    assert version_blocker == ""


def test_manifest_discovery_rejects_path_escape_and_explicit_wrong_schema(
    monkeypatch,
    tmp_path: Path,
) -> None:
    wrong_schema_path = (
        ".agent/data_manifests/btc/snapshot-wrong-schema.json"
    )
    _patch_committed_manifest_tree(
        monkeypatch,
        {
            wrong_schema_path: {
                **_discovery_manifest(),
                "schema_version": "btc_kline_dataready_attestation_v1",
            }
        },
    )

    escaped = consumption_report_builder._discover_manifest(
        tmp_path,
        COMMIT,
        SNAPSHOT_DATASET_ID,
        manifest_path="../outside.json",
    )
    wrong_schema = consumption_report_builder._discover_manifest(
        tmp_path,
        COMMIT,
        SNAPSHOT_DATASET_ID,
        manifest_path=wrong_schema_path,
    )

    assert escaped == (
        None,
        "",
        f"committed_manifest_path_invalid:{SNAPSHOT_DATASET_ID}",
    )
    assert wrong_schema == (
        None,
        "",
        f"committed_manifest_schema_invalid:{SNAPSHOT_DATASET_ID}",
    )


def test_manifest_discovery_allows_exact_blocked_l2_attestation_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = ".agent/data_manifests/btc/l2-blocked-version-a.json"
    manifest = _discovery_manifest(
        dataset_id=L2_DATASET_ID,
        data_schema=L2_BLOCKED_MANIFEST_DATA_SCHEMA,
        quality_status="blocked",
        blockers=("real_timestamp_aligned_l2_missing",),
    )
    _patch_committed_manifest_tree(monkeypatch, {path: manifest})

    payload, source, blocker = consumption_report_builder._discover_manifest(
        tmp_path,
        COMMIT,
        L2_DATASET_ID,
        manifest_path=path,
        dataset_version="version-a",
    )

    assert payload == manifest
    assert source == f"{COMMIT}:{path}"
    assert blocker == ""


def test_manifest_discovery_rejects_unknown_and_kline_blocked_l2_schema(
    monkeypatch,
    tmp_path: Path,
) -> None:
    blocked_l2 = _discovery_manifest(
        dataset_id=L2_DATASET_ID,
        data_schema=L2_BLOCKED_MANIFEST_DATA_SCHEMA,
        quality_status="blocked",
        blockers=("real_timestamp_aligned_l2_missing",),
    )
    payloads = {
        ".agent/data_manifests/btc/l2-unknown-schema.json": {
            **blocked_l2,
            "data_schema": "btc_okx_l2_unknown_attestation_v1",
        },
        ".agent/data_manifests/btc/kline-blocked-schema.json": {
            **blocked_l2,
            "dataset_id": SNAPSHOT_DATASET_ID,
            "storage_relative_path": (
                f"datasets/{SNAPSHOT_DATASET_ID}/version-a"
            ),
        },
    }
    _patch_committed_manifest_tree(monkeypatch, payloads)

    cases = (
        (".agent/data_manifests/btc/l2-unknown-schema.json", L2_DATASET_ID),
        (
            ".agent/data_manifests/btc/kline-blocked-schema.json",
            SNAPSHOT_DATASET_ID,
        ),
    )
    for path, dataset_id in cases:
        assert consumption_report_builder._discover_manifest(
            tmp_path,
            COMMIT,
            dataset_id,
            manifest_path=path,
            dataset_version="version-a",
        ) == (
            None,
            "",
            f"committed_manifest_schema_invalid:{dataset_id}",
        )


def test_manifest_discovery_rejects_blocked_l2_schema_without_blocked_quality(
    monkeypatch,
    tmp_path: Path,
) -> None:
    blocked_l2 = _discovery_manifest(
        dataset_id=L2_DATASET_ID,
        data_schema=L2_BLOCKED_MANIFEST_DATA_SCHEMA,
        quality_status="blocked",
        blockers=("real_timestamp_aligned_l2_missing",),
    )
    payloads = {
        ".agent/data_manifests/btc/l2-blocked-schema-pass.json": {
            **blocked_l2,
            "quality_status": "pass",
        },
        ".agent/data_manifests/btc/l2-blocked-schema-empty-blockers.json": {
            **blocked_l2,
            "blockers": [],
        },
    }
    _patch_committed_manifest_tree(monkeypatch, payloads)

    for path in payloads:
        assert consumption_report_builder._discover_manifest(
            tmp_path,
            COMMIT,
            L2_DATASET_ID,
            manifest_path=path,
            dataset_version="version-a",
        ) == (
            None,
            "",
            f"committed_manifest_schema_invalid:{L2_DATASET_ID}",
        )


def test_blocked_l2_manifest_reaches_core_fail_closed_without_payload_resolution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot, _ = _valid_inputs(tmp_path)
    blocked_l2 = _discovery_manifest(
        dataset_id=L2_DATASET_ID,
        data_schema=L2_BLOCKED_MANIFEST_DATA_SCHEMA,
        quality_status="blocked",
        blockers=(
            "real_timestamp_aligned_l2_missing",
            "l2_lt_30_natural_days",
        ),
    )
    original_resolver = dataready_consumer_module.resolve_manifest_payload

    def guarded_resolver(manifest, **kwargs):
        if manifest.get("data_schema") == L2_BLOCKED_MANIFEST_DATA_SCHEMA:
            raise AssertionError("blocked L2 payload must not be resolved")
        return original_resolver(manifest, **kwargs)

    monkeypatch.setattr(
        dataready_consumer_module,
        "resolve_manifest_payload",
        guarded_resolver,
    )

    report = _consume(tmp_path, snapshot, blocked_l2)

    assert report["status"] == "blocked"
    assert report["decision"] == "block_dataready_consumption_fail_closed"
    for blocker in (
        "manifest_data_schema_mismatch",
        "manifest_quality_status_not_pass",
        "real_timestamp_aligned_l2_missing",
        "l2_lt_30_natural_days",
    ):
        assert blocker in report["blockers"]
    assert len(report["blockers"]) == len(set(report["blockers"]))
    assert (
        report["manifest_checks"]["okx_timestamp_aligned_public_l2"]["status"]
        == "blocked"
    )
    assert report["readiness"] == {
        "quality_checked": False,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
    }
    assert report["guardrails"]["paper_or_live_unlock_allowed"] is False
    assert report["guardrails"]["private_endpoint_used"] is False
    assert report["guardrails"]["order_endpoint_used"] is False


def test_valid_immutable_manifests_are_quality_checked_but_not_promotion_evidence(
    tmp_path: Path,
) -> None:
    snapshot, l2 = _valid_inputs(tmp_path)

    report = _consume(tmp_path, snapshot, l2)

    Draft202012Validator(REPORT_SCHEMA).validate(report)
    assert report["status"] == "quality_checked"
    assert report["blockers"] == []
    assert report["readiness"] == {
        "quality_checked": True,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
    }
    assert report["guardrails"]["mutable_sqlite_consumed"] is False
    assert report["guardrails"]["paper_or_live_unlock_allowed"] is False


def test_current_head_report_is_schema_valid_and_fail_closed() -> None:
    report = json.loads(CURRENT_REPORT.read_text(encoding="utf-8"))

    Draft202012Validator(REPORT_SCHEMA).validate(report)
    assert report["status"] == "blocked"
    assert "immutable_snapshot_not_published" in report["blockers"]
    assert "data_steward_attestation_required" in report["blockers"]
    assert report["readiness"]["promotion_evidence_ready"] is False
    assert report["guardrails"]["mutable_sqlite_consumed"] is False


def test_missing_manifests_and_attestations_preserve_required_blockers(tmp_path: Path) -> None:
    report = _consume(
        tmp_path,
        None,
        None,
        runtime_pointer=_runtime_pointer(published=False),
    )

    assert report["status"] == "blocked"
    assert "immutable_snapshot_not_published" in report["blockers"]
    assert "data_steward_attestation_required" in report["blockers"]
    assert "okx_timestamp_aligned_l2_manifest_not_published" in report["blockers"]


def test_stale_kline_and_l2_common_ends_fail_closed(tmp_path: Path) -> None:
    stale = "2026-07-20T00:00:00Z"
    snapshot, _ = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version="2026-07-24T110000Z",
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=_kline_attestation(
            common_end=stale,
            coverage_end=stale,
            intervals=[
                {
                    **_kline_attestation()["intervals"][0],
                    "common_end": stale,
                }
            ],
        ),
    )
    l2, _ = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version="2026-07-24T115000Z",
        attestation_name=L2_ATTESTATION_PATH,
        attestation=_l2_attestation(common_end=stale, coverage_end=stale),
    )

    report = _consume(tmp_path, snapshot, l2)

    assert "kline_freshness_sla_breached" in report["blockers"]
    assert "l2_freshness_sla_breached" in report["blockers"]


def test_manifest_hash_mismatch_blocks_consumption(tmp_path: Path) -> None:
    snapshot, snapshot_root = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version="2026-07-24T110000Z",
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=_kline_attestation(),
    )
    l2, _ = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version="2026-07-24T115000Z",
        attestation_name=L2_ATTESTATION_PATH,
        attestation=_l2_attestation(),
    )
    table_path = next(
        item["path"]
        for item in snapshot["files"]
        if item["path"] != KLINE_ATTESTATION_PATH
    )
    table = snapshot_root / table_path
    original = table.read_bytes()
    table.write_bytes(
        (b"X" if original[:1] != b"X" else b"Y") + original[1:]
    )

    report = _consume(tmp_path, snapshot, l2)

    assert "manifest_hash_mismatch" in report["blockers"]
    assert any("shared_data_file_" in item for item in report["blockers"])


def test_manifest_schema_mismatch_blocks_before_physical_resolution(tmp_path: Path) -> None:
    snapshot, l2 = _valid_inputs(tmp_path)
    snapshot["schema_version"] = "wrong"

    report = _consume(tmp_path, snapshot, l2)

    assert "manifest_schema_mismatch" in report["blockers"]
    assert "shared_data_manifest_schema_version_invalid" in report["blockers"]


def test_partial_kline_and_two_sided_l2_coverage_block_consumption(tmp_path: Path) -> None:
    partial_intervals = [
        {
            **_kline_attestation()["intervals"][0],
            "coverage_pct": 95.0,
            "missing_count": 12,
        }
    ]
    snapshot, _ = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version="2026-07-24T110000Z",
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=_kline_attestation(intervals=partial_intervals),
    )
    l2, _ = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version="2026-07-24T115000Z",
        attestation_name=L2_ATTESTATION_PATH,
        attestation=_l2_attestation(two_sided_coverage_pct=94.0),
    )

    report = _consume(tmp_path, snapshot, l2)

    assert "kline_partial_coverage:1m" in report["blockers"]
    assert "kline_missing_rows:1m" in report["blockers"]
    assert "l2_partial_two_sided_coverage" in report["blockers"]


def test_kline_required_partition_declaration_must_match_intervals(
    tmp_path: Path,
) -> None:
    mismatched_selection = {
        **_kline_attestation()["partition_selection"],
        "required_partitions": [
            {
                "venue": "okx",
                "instrument_id": "BTC-USDT-SWAP",
                "interval": "1m",
            }
        ],
    }
    snapshot, _ = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version="2026-07-24T110000Z",
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=_kline_attestation(partition_selection=mismatched_selection),
    )
    l2, _ = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version="2026-07-24T115000Z",
        attestation_name=L2_ATTESTATION_PATH,
        attestation=_l2_attestation(),
    )

    report = _consume(tmp_path, snapshot, l2)

    assert "kline_required_partition_set_mismatch" in report["blockers"]


def test_generic_policy_cannot_bypass_approved_binance_partition_contract() -> None:
    payload = _kline_attestation()
    required = []
    intervals = []
    inventory = []
    source_sha256 = payload["lineage"]["source_sha256"]
    common_end = payload["common_end"]
    for interval in ("1m", "5m", "15m", "1h"):
        partition = {
            "venue": "binance_spot",
            "instrument_id": "BTCUSDT",
            "interval": interval,
        }
        required.append(partition)
        intervals.append(
            {
                **payload["intervals"][0],
                **partition,
            }
        )
        inventory_item = {
            **partition,
            "total_row_count": 11,
            "finalized_count": 10,
            "in_progress_count": 1,
            "coverage_start": "2025-07-24T00:00:00Z",
            "common_end": common_end,
            "freshness_age_hours": 1.0,
            "selection_status": "included_required",
            "selection_policy": "explicit_required_partitions_v1",
            "source_sha256": source_sha256,
        }
        inventory_item["partition_inventory_sha256"] = _canonical_sha256(
            inventory_item
        )
        inventory.append(inventory_item)
    payload["partition_selection"] = {
        "mode": "explicit_required_partitions",
        "policy_id": "explicit_required_partitions_v1",
        "required_partitions": required,
        "included_partitions": required,
        "excluded_partitions": [],
    }
    payload["intervals"] = intervals
    payload["source_partition_inventory"] = inventory
    payload["source_partition_inventory_sha256"] = _canonical_sha256(inventory)

    result = _validate_kline_attestation(
        payload,
        manifest=None,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
    )

    assert result["status"] == "blocked"
    assert (
        "kline_approved_current_main_policy_required"
        in result["blockers"]
    )


def test_l2_sequence_gap_time_and_clock_contracts_fail_closed(tmp_path: Path) -> None:
    snapshot, _ = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version="2026-07-24T110000Z",
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=_kline_attestation(),
    )
    l2, _ = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version="2026-07-24T115000Z",
        attestation_name=L2_ATTESTATION_PATH,
        attestation=_l2_attestation(
            sequence_validation_status="fail",
            sequence_gap_count=2,
            unrecovered_gap_count=1,
            event_snapshot_time_order_valid=False,
            max_clock_offset_ms=1_500.0,
            gap_windows=[{"recovered": False}],
        ),
    )

    report = _consume(tmp_path, snapshot, l2)

    assert "l2_sequence_validation_failed" in report["blockers"]
    assert "l2_sequence_gap_detected" in report["blockers"]
    assert "l2_unrecovered_gap_detected" in report["blockers"]
    assert "l2_event_snapshot_time_order_invalid" in report["blockers"]
    assert "l2_clock_offset_exceeds_limit" in report["blockers"]
    assert "l2_gap_window_unrecovered" in report["blockers"]


def test_l2_consumer_rejects_oversized_or_unknown_gap_policy() -> None:
    for overrides, expected_blocker in (
        (
            {"max_inter_message_gap_seconds": 31 * 86_400.0 + 1.0},
            "l2_max_inter_message_gap_exceeds_governed_ceiling",
        ),
        (
            {"inter_message_gap_policy_id": "caller-controlled"},
            "l2_inter_message_gap_policy_unknown",
        ),
        (
            {"approved_max_inter_message_gap_seconds": 31 * 86_400.0},
            "l2_inter_message_gap_ceiling_invalid",
        ),
    ):
        attestation = _l2_attestation(**overrides)
        result = _validate_direct_l2(attestation)

        assert result["status"] == "blocked"
        assert expected_blocker in result["blockers"]


def test_l2_consumer_accepts_stricter_governed_gap_policy() -> None:
    attestation = _l2_attestation(
        max_inter_message_gap_seconds=0.5,
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "pass"
    assert result["blockers"] == []


def _validate_direct_l2(
    attestation: dict,
    *,
    manifest_files: list[dict] | None = None,
) -> dict:
    return _validate_l2_attestation(
        attestation,
        manifest={
            "dataset_id": attestation["dataset_id"],
            "dataset_version": attestation["dataset_version"],
            "producer_commit": attestation["source_head"],
            "data_schema": L2_MANIFEST_DATA_SCHEMA,
            "coverage": {
                "start": attestation["coverage_start"],
                "end": attestation["coverage_end"],
            },
            "files": (
                list(attestation.get("files", []))
                if manifest_files is None
                else manifest_files
            ),
        },
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
    )


def _validate_direct_kline(
    attestation: dict,
    *,
    resolved_root: Path | None = None,
    manifest_files: list[dict] | None = None,
) -> dict:
    return _validate_kline_attestation(
        attestation,
        manifest={
            "dataset_id": attestation["dataset_id"],
            "dataset_version": attestation["dataset_version"],
            "producer_commit": attestation["source_head"],
            "data_schema": KLINE_MANIFEST_DATA_SCHEMA,
            "coverage": {
                "start": attestation["coverage_start"],
                "end": attestation["coverage_end"],
            },
            "files": (
                list(attestation.get("files", []))
                if manifest_files is None
                else manifest_files
            ),
        },
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=resolved_root,
    )


def test_l2_consumer_rejects_30_day_claim_over_29_day_raw_cap() -> None:
    attestation = _l2_attestation()
    common_end = datetime.fromisoformat(
        attestation["common_end"].replace("Z", "+00:00")
    )
    coverage_start = (
        common_end - timedelta(days=30)
    ).isoformat().replace("+00:00", "Z")
    claimed_seconds = 30 * 86_400.0
    raw_seconds = 29 * 86_400.0
    attestation.update(
        {
            "coverage_start": coverage_start,
            "observed_history_seconds": claimed_seconds,
            "history_window_days": 30.0,
            "coverage_span_days": 30.0,
        }
    )
    source = attestation["source_segments"][0]
    source.update(
        {
            "capture_start": coverage_start,
            "capture_duration_seconds": claimed_seconds,
            "capture_started_monotonic_ns": 1_000_000_000,
            "capture_ended_monotonic_ns": (
                1_000_000_000 + int(claimed_seconds * 1_000_000_000)
            ),
            "raw_receive_span_seconds": raw_seconds,
            "raw_monotonic_span_seconds": raw_seconds,
        }
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_observed_history_exceeds_conservative_source_cap" in result["blockers"]


def test_l2_consumer_rejects_multisegment_total_mismatch() -> None:
    attestation = _l2_attestation()
    second = dict(attestation["source_segments"][0])
    second["segment_name"] = "segment-b"
    second["capture_start"] = second["capture_end"]
    second["capture_end"] = (
        datetime.fromisoformat(second["capture_end"].replace("Z", "+00:00"))
        + timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    second["capture_duration_seconds"] = 1.0
    second["capture_started_monotonic_ns"] = 10_000_000_000
    second["capture_ended_monotonic_ns"] = 11_000_000_000
    second["raw_receive_span_seconds"] = 1.0
    second["raw_monotonic_span_seconds"] = 1.0
    attestation["source_segments"] = [
        attestation["source_segments"][0],
        second,
    ]
    attestation["segment_count"] = 2

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert (
        "l2_source_segment_output_record_count_total_mismatch"
        in result["blockers"]
    )


def test_l2_consumer_rejects_capture_duration_raw_endpoint_mismatch() -> None:
    attestation = _l2_attestation()
    source = attestation["source_segments"][0]
    source["raw_receive_span_seconds"] -= 1.0
    source["raw_monotonic_span_seconds"] -= 1.0

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_source_segment_endpoint_span_mismatch" in result["blockers"]


def test_l2_consumer_rejects_nonempty_segment_blockers() -> None:
    attestation = _l2_attestation()
    attestation["source_segments"][0]["blockers"] = [
        "producer_suppressed_failure"
    ]

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_source_segment_blockers_present" in result["blockers"]


def test_l2_consumer_rejects_gap_window_segment_total_mismatch() -> None:
    attestation = _l2_attestation(
        gap_windows=[
            {
                "segment_name": "segment-a",
                "from_connection_sequence": 1,
                "to_connection_sequence": 2,
                "gap_start": "2026-07-20T00:00:00Z",
                "gap_end": "2026-07-20T00:00:01Z",
                "duration_seconds": 1.0,
                "recovered": True,
            }
        ],
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_source_segment_gap_window_total_mismatch" in result["blockers"]


def test_l2_consumer_rejects_missing_or_nonfinite_cap_inputs() -> None:
    missing = _l2_attestation()
    missing["source_segments"][0].pop("raw_monotonic_span_seconds")
    missing_result = _validate_direct_l2(missing)
    assert "l2_source_segment_clock_span_invalid" in missing_result["blockers"]

    nonfinite_source = _l2_attestation()
    nonfinite_source["source_segments"][0][
        "raw_receive_span_seconds"
    ] = float("nan")
    nonfinite_source_result = _validate_direct_l2(nonfinite_source)
    assert (
        "l2_source_segment_clock_span_invalid"
        in nonfinite_source_result["blockers"]
    )

    nonfinite_total = _l2_attestation(
        observed_history_seconds=float("nan"),
    )
    nonfinite_total_result = _validate_direct_l2(nonfinite_total)
    assert "l2_observed_history_invalid" in nonfinite_total_result["blockers"]


def _set_l2_window(
    attestation: dict,
    *,
    coverage_start: datetime,
    coverage_end: datetime,
    common_start: datetime,
    common_end: datetime,
    endpoint_offset_ms: float = 0.0,
) -> None:
    coverage_start_text = coverage_start.isoformat().replace("+00:00", "Z")
    coverage_end_text = coverage_end.isoformat().replace("+00:00", "Z")
    common_start_text = common_start.isoformat().replace("+00:00", "Z")
    common_end_text = common_end.isoformat().replace("+00:00", "Z")
    span_seconds = (coverage_end - coverage_start).total_seconds()
    attestation.update(
        {
            "coverage_start": coverage_start_text,
            "coverage_end": coverage_end_text,
            "common_start": common_start_text,
            "common_end": common_end_text,
            "observed_history_seconds": span_seconds,
            "history_window_days": span_seconds / 86_400.0,
            "coverage_span_days": span_seconds / 86_400.0,
            "max_clock_offset_ms": endpoint_offset_ms,
            "freshness_age_minutes": (
                NOW - min(coverage_end, common_end)
            ).total_seconds()
            / 60.0,
        }
    )
    source = attestation["source_segments"][0]
    source.update(
        {
            "capture_start": coverage_start_text,
            "capture_end": coverage_end_text,
            "raw_first_receive_time": coverage_start_text,
            "raw_last_receive_time": coverage_end_text,
            "capture_duration_seconds": span_seconds,
            "capture_started_monotonic_ns": 1_000_000_000,
            "capture_ended_monotonic_ns": (
                1_000_000_000 + int(span_seconds * 1_000_000_000)
            ),
            "raw_receive_span_seconds": span_seconds,
            "raw_monotonic_span_seconds": span_seconds,
            "max_clock_offset_ms": endpoint_offset_ms,
        }
    )


def test_l2_consumer_uses_stale_coverage_endpoint_over_fresh_common_end() -> None:
    attestation = _l2_attestation()
    stale_end = NOW - timedelta(hours=72)
    stale_start = stale_end - timedelta(days=1)
    _set_l2_window(
        attestation,
        coverage_start=stale_start,
        coverage_end=stale_end,
        common_start=stale_start,
        common_end=NOW - timedelta(minutes=10),
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_freshness_sla_breached" in result["blockers"]
    assert "l2_common_end_after_receive_endpoint" in result["blockers"]


def test_l2_consumer_rejects_reverse_direction_end_offset() -> None:
    attestation = _l2_attestation()
    receive_end = NOW - timedelta(minutes=20)
    receive_start = receive_end - timedelta(days=1)
    _set_l2_window(
        attestation,
        coverage_start=receive_start,
        coverage_end=receive_end,
        common_start=receive_start,
        common_end=receive_end + timedelta(minutes=10),
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_common_end_after_receive_endpoint" in result["blockers"]


def test_l2_consumer_rejects_start_endpoint_offset() -> None:
    attestation = _l2_attestation()
    receive_end = NOW - timedelta(minutes=10)
    receive_start = receive_end - timedelta(days=1)
    _set_l2_window(
        attestation,
        coverage_start=receive_start,
        coverage_end=receive_end,
        common_start=receive_start + timedelta(minutes=10),
        common_end=receive_end,
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_common_start_after_receive_endpoint" in result["blockers"]


def test_l2_consumer_accepts_clock_lag_within_endpoint_bound() -> None:
    attestation = _l2_attestation()
    receive_end = NOW - timedelta(minutes=10)
    receive_start = receive_end - timedelta(days=1)
    lag = timedelta(milliseconds=120)
    _set_l2_window(
        attestation,
        coverage_start=receive_start,
        coverage_end=receive_end,
        common_start=receive_start - lag,
        common_end=receive_end - lag,
        endpoint_offset_ms=120.0,
    )

    result = _validate_direct_l2(attestation)

    assert result["status"] == "pass"
    assert result["blockers"] == []


def test_l2_consumer_rejects_missing_or_nonfinite_endpoint_clock_fields() -> None:
    missing = _l2_attestation()
    missing.pop("common_start")
    missing["source_segments"][0].pop("raw_last_receive_time")
    missing_result = _validate_direct_l2(missing)
    assert "l2_common_start_invalid" in missing_result["blockers"]
    assert "l2_source_segment_receive_endpoints_invalid" in missing_result["blockers"]

    nonfinite = _l2_attestation(max_clock_offset_ms=float("nan"))
    nonfinite["source_segments"][0]["max_clock_offset_ms"] = float("nan")
    nonfinite_result = _validate_direct_l2(nonfinite)
    assert "l2_clock_offset_exceeds_limit" in nonfinite_result["blockers"]
    assert "l2_source_segment_clock_offset_invalid" in nonfinite_result["blockers"]


def test_l2_consumer_full_schema_and_safety_contract_fail_closed() -> None:
    attestation = _l2_attestation()
    attestation["instrument_id"] = "ETH-USDT-SWAP"
    attestation["channel"] = "orders"
    attestation["quality_checked"] = False
    attestation["promotion_evidence_ready"] = True
    attestation["duplicate_sequence_count"] = 1
    attestation["readiness"]["research_ready"] = True
    attestation["guardrails"]["private_endpoint_used"] = True
    attestation["guardrails"]["order_endpoint_used"] = True
    attestation["guardrails"]["real_order_submitted"] = True
    attestation["unknown_contract_field"] = "must-block"

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_attestation_schema_invalid" in result["blockers"]
    assert "l2_instrument_must_be_btc_usdt_swap" in result["blockers"]
    assert "l2_channel_must_be_public_books" in result["blockers"]
    assert "l2_quality_checked_required" in result["blockers"]
    assert "l2_promotion_evidence_must_remain_false" in result["blockers"]
    assert "l2_duplicate_sequence_count_nonzero" in result["blockers"]
    assert "l2_readiness_must_remain_fail_closed" in result["blockers"]
    assert "l2_guardrail_not_false:private_endpoint_used" in result["blockers"]
    assert "l2_guardrail_not_false:order_endpoint_used" in result["blockers"]
    assert "l2_guardrail_not_false:real_order_submitted" in result["blockers"]


def test_l2_consumer_recomputes_row_side_of_two_sided_coverage() -> None:
    attestation = _l2_attestation()
    source = attestation["source_segments"][0]
    source["raw_row_count"] = 6
    source["books_row_count"] = 6

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_two_sided_coverage_derivation_mismatch" in result["blockers"]
    assert "l2_partial_two_sided_coverage" in result["blockers"]


def test_l2_consumer_recomputes_temporal_side_of_two_sided_coverage() -> None:
    attestation = _l2_attestation()
    half_span = attestation["observed_history_seconds"] / 2.0
    attestation["observed_history_seconds"] = half_span
    attestation["history_window_days"] = half_span / 86_400.0

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_two_sided_coverage_derivation_mismatch" in result["blockers"]
    assert "l2_partial_two_sided_coverage" in result["blockers"]


def test_l2_consumer_recovered_gap_reduces_temporal_coverage() -> None:
    attestation = _l2_attestation()
    source = attestation["source_segments"][0]
    coverage_start = datetime.fromisoformat(
        attestation["coverage_start"].replace("Z", "+00:00")
    )
    half_span = attestation["observed_history_seconds"] / 2.0
    gap_end = coverage_start + timedelta(seconds=half_span)
    attestation["gap_windows"] = [
        {
            "segment_name": "segment-a",
            "from_connection_sequence": 1,
            "to_connection_sequence": 2,
            "gap_start": attestation["coverage_start"],
            "gap_end": gap_end.isoformat().replace("+00:00", "Z"),
            "duration_seconds": half_span,
            "recovered": True,
        }
    ]
    attestation["observed_history_seconds"] = half_span
    attestation["history_window_days"] = half_span / 86_400.0
    attestation["snapshot_count"] = 2
    attestation["update_count"] = 1
    attestation["reconnect_count"] = 1
    attestation["resync_snapshot_count"] = 1
    source["snapshot_count"] = 2
    source["update_count"] = 1
    source["manifest_connection_count"] = 2
    source["manifest_gap_count"] = 1
    source["observed_reconnect_count"] = 1

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_gap_not_reflected_in_coverage" in result["blockers"]
    assert "l2_two_sided_coverage_derivation_mismatch" in result["blockers"]


def test_l2_consumer_binds_lineage_hashes_and_manifest_inventory() -> None:
    source_hash = _l2_attestation()
    source_hash["source_aggregate_sha256"] = "0" * 64
    source_result = _validate_direct_l2(source_hash)
    assert "l2_source_aggregate_sha256_mismatch" in source_result["blockers"]

    table_hash = _l2_attestation()
    table_hash["aggregate_table_sha256"] = "0" * 64
    table_result = _validate_direct_l2(table_hash)
    assert "l2_aggregate_table_sha256_mismatch" in table_result["blockers"]

    manifest_binding = _l2_attestation()
    manifest_result = _validate_direct_l2(
        manifest_binding,
        manifest_files=[
            {
                **manifest_binding["files"][0],
                "sha256": "0" * 64,
            }
        ],
    )
    assert (
        "l2_table_file_manifest_inventory_mismatch"
        in manifest_result["blockers"]
    )

    malformed = _l2_attestation()
    malformed["files"][0]["sha256"] = "é" * 64
    malformed_result = _validate_direct_l2(malformed)
    assert malformed_result["status"] == "blocked"
    assert "l2_table_file_invalid" in malformed_result["blockers"]


def test_l2_consumer_binds_checksum_resync_and_freshness_declarations() -> None:
    checksum = _l2_attestation(checksum_observed_count=2)
    checksum_result = _validate_direct_l2(checksum)
    assert (
        "l2_checksum_observed_book_total_mismatch"
        in checksum_result["blockers"]
    )

    invalid_validated = _l2_attestation(checksum_validated_count=4)
    validated_result = _validate_direct_l2(invalid_validated)
    assert "l2_checksum_validated_count_invalid" in validated_result["blockers"]

    resync = _l2_attestation(resync_snapshot_count=1)
    resync_result = _validate_direct_l2(resync)
    assert "l2_resync_snapshot_total_mismatch" in resync_result["blockers"]

    freshness = _l2_attestation(freshness_age_minutes=9.0)
    freshness_result = _validate_direct_l2(freshness)
    assert "l2_declared_freshness_age_mismatch" in freshness_result["blockers"]

    policy = _l2_attestation(freshness_sla_minutes=120.0)
    policy_result = _validate_direct_l2(policy)
    assert "l2_declared_freshness_sla_invalid" in policy_result["blockers"]


def test_l2_consumer_capture_duration_accepts_micro_overhead() -> None:
    attestation = _l2_attestation()
    source = attestation["source_segments"][0]
    source["capture_duration_seconds"] += 0.0001
    source["capture_ended_monotonic_ns"] += 100_000

    result = _validate_direct_l2(attestation)

    assert result["status"] == "pass"
    assert result["blockers"] == []


def test_l2_consumer_capture_duration_over_governed_bound_blocks() -> None:
    attestation = _l2_attestation()
    source = attestation["source_segments"][0]
    source["capture_duration_seconds"] += 0.201
    source["capture_ended_monotonic_ns"] += 201_000_000

    result = _validate_direct_l2(attestation)

    assert result["status"] == "blocked"
    assert "l2_source_segment_capture_duration_mismatch" in result["blockers"]


def test_public_consumer_rejects_nonfinite_bool_and_widened_policies(
    tmp_path: Path,
) -> None:
    snapshot, l2 = _valid_inputs(tmp_path)
    cases = [
        ({"freshness_sla_hours": float("nan")}, "consumer_freshness_policy_invalid_or_too_wide"),
        ({"freshness_sla_hours": float("inf")}, "consumer_freshness_policy_invalid_or_too_wide"),
        ({"freshness_sla_hours": True}, "consumer_freshness_policy_invalid_or_too_wide"),
        ({"freshness_sla_hours": 72.0}, "consumer_freshness_policy_invalid_or_too_wide"),
        ({"min_coverage_pct": float("nan")}, "consumer_coverage_policy_invalid_or_too_wide"),
        ({"min_coverage_pct": float("inf")}, "consumer_coverage_policy_invalid_or_too_wide"),
        ({"min_coverage_pct": False}, "consumer_coverage_policy_invalid_or_too_wide"),
        ({"min_coverage_pct": 50.0}, "consumer_coverage_policy_invalid_or_too_wide"),
        ({"max_l2_clock_offset_ms": float("nan")}, "consumer_clock_policy_invalid_or_too_wide"),
        ({"max_l2_clock_offset_ms": float("inf")}, "consumer_clock_policy_invalid_or_too_wide"),
        ({"max_l2_clock_offset_ms": True}, "consumer_clock_policy_invalid_or_too_wide"),
        ({"max_l2_clock_offset_ms": 2_000.0}, "consumer_clock_policy_invalid_or_too_wide"),
    ]
    for overrides, expected in cases:
        report = _consume(tmp_path, snapshot, l2, **overrides)
        assert report["status"] == "blocked"
        assert expected in report["blockers"]


def test_public_consumer_accepts_stricter_governed_policies(
    tmp_path: Path,
) -> None:
    snapshot, l2 = _valid_inputs(tmp_path)

    report = _consume(
        tmp_path,
        snapshot,
        l2,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_l2_clock_offset_ms=120.0,
    )

    assert report["status"] == "quality_checked"
    assert report["blockers"] == []


def test_kline_consumer_full_schema_safety_and_nonfinite_fail_closed() -> None:
    attestation = _kline_attestation()
    attestation["unknown_contract_field"] = True
    attestation["freshness_age_hours"] = float("nan")
    attestation["quality_checked"] = False
    attestation["promotion_evidence_ready"] = True
    attestation["readiness"]["research_ready"] = True
    attestation["guardrails"]["private_endpoint_used"] = True
    attestation["guardrails"]["order_endpoint_used"] = True
    attestation["guardrails"]["real_order_submitted"] = True
    attestation["lineage"]["explicit_time_derivation_used"] = True

    result = _validate_direct_kline(attestation)

    assert result["status"] == "blocked"
    assert "kline_attestation_schema_invalid" in result["blockers"]
    assert "kline_attestation_nonfinite" in result["blockers"]
    assert "kline_quality_checked_required" in result["blockers"]
    assert "kline_promotion_evidence_must_remain_false" in result["blockers"]
    assert "kline_readiness_must_remain_fail_closed" in result["blockers"]
    assert "kline_guardrail_not_false:private_endpoint_used" in result["blockers"]
    assert "kline_lineage_time_semantics_mismatch" in result["blockers"]


def test_kline_consumer_uses_stale_coverage_over_fresh_common_end() -> None:
    attestation = _kline_attestation()
    stale_end = NOW - timedelta(hours=72)
    attestation["coverage_end"] = stale_end.isoformat().replace("+00:00", "Z")

    result = _validate_direct_kline(attestation)

    assert result["status"] == "blocked"
    assert "kline_common_end_coverage_end_mismatch" in result["blockers"]
    assert "kline_freshness_sla_breached" in result["blockers"]


def test_kline_payload_cadence_and_actual_rows_are_streamed(
    tmp_path: Path,
) -> None:
    attestation = _kline_attestation()
    manifest, root = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version=attestation["dataset_version"],
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=attestation,
    )
    table = root / attestation["files"][0]["path"]
    rows = table.read_text(encoding="utf-8").splitlines()
    rows[1] = rows[0]
    table.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )

    assert result["status"] == "blocked"
    assert "kline_payload_cadence_gap_or_duplicate" in result["blockers"]


def test_kline_physical_rows_fail_closed_on_content_and_pit_defects(
    tmp_path: Path,
) -> None:
    attestation = _kline_attestation()
    manifest, root = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version=attestation["dataset_version"],
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=attestation,
    )
    table = root / attestation["files"][0]["path"]
    original_lines = table.read_text(encoding="utf-8").splitlines()
    original_row = json.loads(original_lines[0])

    cases = [
        (
            {key: value for key, value in original_row.items() if key != "volume"},
            "kline_payload_required_fields_missing",
        ),
        (
            {**original_row, "high": 90.0},
            "kline_payload_ohlc_relation_invalid",
        ),
        (
            {
                **original_row,
                "available_time": (
                    NOW + timedelta(seconds=1)
                ).isoformat().replace("+00:00", "Z"),
            },
            "kline_payload_pit_time_order_invalid",
        ),
        (
            {**original_row, "open": 10**400},
            "kline_payload_ohlcv_range_invalid",
        ),
        (
            {**original_row, "open": 1e-20},
            "kline_payload_ohlcv_range_invalid",
        ),
        (
            {**original_row, "open": True},
            "kline_payload_ohlcv_invalid",
        ),
    ]
    for mutated, expected in cases:
        lines = list(original_lines)
        lines[0] = json.dumps(mutated, sort_keys=True)
        table.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = _validate_kline_attestation(
            attestation,
            manifest=manifest,
            now=NOW,
            freshness_sla_hours=48.0,
            min_coverage_pct=99.0,
            resolved_root=root,
        )
        assert expected in result["blockers"]

    lines = list(original_lines)
    lines[0] = lines[0].replace('"volume": 1.0', '"volume": NaN')
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    nonfinite = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert "kline_payload_jsonl_unreadable" in nonfinite["blockers"]

    lines = list(original_lines)
    lines[0] = lines[0].replace('"open": 100.0', '"open": 1e400')
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    exponent = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert "kline_payload_ohlcv_invalid" in exponent["blockers"]

    lines = list(original_lines)
    lines[0] = lines[0].replace(
        '"open": 100.0',
        '"open": 0.00000000000000000001',
    )
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    decimal_range = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert (
        "kline_payload_ohlcv_range_invalid"
        in decimal_range["blockers"]
    )

    lines = list(original_lines)
    lines[0] = lines[0].replace(
        '"open": 100.0',
        '"open": 100.0000000000000000001',
    )
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    nineteen_places = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert (
        "kline_payload_ohlcv_range_invalid"
        in nineteen_places["blockers"]
    )

    lines = list(original_lines)
    lines[0] = lines[0].replace(
        '"open": 100.0',
        '"open": 100.000000000000000001',
    )
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    eighteen_places = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert "kline_payload_ohlcv_range_invalid" not in eighteen_places[
        "blockers"
    ]

    lines = list(original_lines)
    lines[0] = lines[0].replace(
        '"volume": 1.0',
        '"volume": 1.000000000000000001e0',
    )
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    scientific_boundary = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert "kline_payload_ohlcv_range_invalid" not in scientific_boundary[
        "blockers"
    ]

    lines = list(original_lines)
    lines[0] = lines[0].replace('"open": 100.0', '"open": 1e-400')
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    underflow = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert "kline_payload_ohlcv_range_invalid" in underflow["blockers"]

    for lexeme in (
        "1e999999999999999999",
        "1e-999999999999999999",
        "1" + "0" * 3999,
    ):
        lines = list(original_lines)
        lines[0] = lines[0].replace(
            '"open": 100.0',
            f'"open": {lexeme}',
        )
        table.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with localcontext() as context:
            context.Emax = 10
            context.Emin = -10
            context.traps[Overflow] = True
            extreme = _validate_kline_attestation(
                attestation,
                manifest=manifest,
                now=NOW,
                freshness_sla_hours=48.0,
                min_coverage_pct=99.0,
                resolved_root=root,
            )
        assert "kline_payload_ohlcv_range_invalid" in extreme["blockers"]

    with patch.object(
        dataready_consumer_module,
        "_validate_kline_payload_row",
        side_effect=Overflow("injected decimal validation trap"),
    ):
        fallback = _validate_kline_attestation(
            attestation,
            manifest=manifest,
            now=NOW,
            freshness_sla_hours=48.0,
            min_coverage_pct=99.0,
            resolved_root=root,
        )
    assert "kline_payload_validation_exception" in fallback["blockers"]


def test_l2_physical_replay_fails_closed_on_book_sequence_and_time_defects(
    tmp_path: Path,
) -> None:
    attestation = _l2_attestation()
    manifest, root = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version=attestation["dataset_version"],
        attestation_name=L2_ATTESTATION_PATH,
        attestation=attestation,
    )
    table = root / attestation["files"][0]["path"]
    original_lines = table.read_text(encoding="utf-8").splitlines()
    original_rows = [json.loads(line) for line in original_lines]
    future = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    cases = [
        (
            [
                {
                    key: value
                    for key, value in original_rows[0].items()
                    if key != "asks"
                },
                *original_rows[1:],
            ],
            "l2_payload_required_fields_missing",
        ),
        (
            [
                {
                    **original_rows[0],
                    "bids": [["102", "1"]],
                    "best_bid": 102.0,
                },
                *original_rows[1:],
            ],
            "l2_payload_book_crossed_or_locked",
        ),
        (
            [
                original_rows[0],
                {**original_rows[1], "prev_seq_id": 999},
                original_rows[2],
            ],
            "l2_payload_sequence_gap_or_order_invalid",
        ),
        (
            [
                original_rows[0],
                {**original_rows[1], "capture_sequence": 99},
                {**original_rows[2], "capture_sequence": 100},
            ],
            "l2_payload_capture_sequence_gap",
        ),
        (
            [
                {**original_rows[0], "capture_sequence": 99},
                {**original_rows[1], "capture_sequence": 100},
                {**original_rows[2], "capture_sequence": 101},
            ],
            "l2_payload_capture_sequence_must_start_at_one",
        ),
        (
            [
                {
                    **original_rows[0],
                    "available_time": future,
                    "snapshot_time": future,
                },
                *original_rows[1:],
            ],
            "l2_payload_pit_time_order_invalid",
        ),
        (
            [
                {**original_rows[0], "checksum": 1},
                *original_rows[1:],
            ],
            "l2_payload_checksum_mismatch",
        ),
    ]
    for mutated_rows, expected in cases:
        table.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in mutated_rows
            ),
            encoding="utf-8",
        )
        result = _validate_l2_attestation(
            attestation,
            manifest=manifest,
            now=NOW,
            freshness_sla_hours=1.0,
            min_coverage_pct=100.0,
            max_clock_offset_ms=1_000.0,
            resolved_root=root,
        )
        assert expected in result["blockers"]

    lines = list(original_lines)
    lines[0] = lines[0].replace('"best_bid": 99.0', '"best_bid": NaN')
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    nonfinite = _validate_l2_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        resolved_root=root,
    )
    assert "l2_payload_jsonl_unreadable" in nonfinite["blockers"]

    nineteen = "99.0000000000000000001"
    lines = [
        json.dumps(row, sort_keys=True)
        for row in original_rows
    ]
    lines[0] = lines[0].replace(
        '"best_bid": 99.0',
        f'"best_bid": {nineteen}',
    )
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    l2_numeric_nineteen = _validate_l2_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        resolved_root=root,
    )
    assert (
        "l2_payload_numeric_range_invalid"
        in l2_numeric_nineteen["blockers"]
    )

    rows = [dict(row) for row in original_rows]
    rows[0]["bids"] = [[nineteen, "1"]]
    lines = [
        json.dumps(row, sort_keys=True)
        for row in rows
    ]
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    l2_book_price_nineteen = _validate_l2_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        resolved_root=root,
    )
    assert "l2_payload_book_level_range_invalid" in l2_book_price_nineteen[
        "blockers"
    ]

    rows = [dict(row) for row in original_rows]
    rows[0]["bids"] = [["99", "1.0000000000000000001"]]
    table.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    l2_book_size_nineteen = _validate_l2_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        resolved_root=root,
    )
    assert "l2_payload_book_level_range_invalid" in l2_book_size_nineteen[
        "blockers"
    ]

    eighteen = "99.000000000000000001"
    rows = [dict(row) for row in original_rows]
    rows[0]["bids"] = [[eighteen, "1.000000000000000001"]]
    lines = [
        json.dumps(row, sort_keys=True)
        for row in rows
    ]
    lines[0] = lines[0].replace(
        '"best_bid": 99.0',
        f'"best_bid": {eighteen}',
    )
    table.write_text("\n".join(lines) + "\n", encoding="utf-8")
    l2_eighteen = _validate_l2_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        resolved_root=root,
    )
    assert "l2_payload_numeric_range_invalid" not in l2_eighteen[
        "blockers"
    ]
    assert "l2_payload_book_level_range_invalid" not in l2_eighteen[
        "blockers"
    ]

    for lexeme in (
        "1e999999999999999999",
        "1e-999999999999999999",
        "1" + "0" * 4999,
    ):
        rows = [dict(row) for row in original_rows]
        rows[0]["bids"] = [[lexeme, "1"]]
        table.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        with localcontext() as context:
            context.Emax = 10
            context.Emin = -10
            context.traps[Overflow] = True
            extreme = _validate_l2_attestation(
                attestation,
                manifest=manifest,
                now=NOW,
                freshness_sla_hours=1.0,
                min_coverage_pct=100.0,
                max_clock_offset_ms=1_000.0,
                resolved_root=root,
            )
        assert "l2_payload_book_level_range_invalid" in extreme[
            "blockers"
        ]

    reconnect_rows = [
        original_rows[0],
        {
            **original_rows[1],
            "action": "snapshot",
            "capture_sequence": 1,
            "connection_sequence": 2,
            "prev_seq_id": -1,
        },
        {
            **original_rows[2],
            "capture_sequence": 2,
            "connection_sequence": 2,
        },
    ]
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
    states: dict[str, dict] = {}
    last_seq_id = None
    reconnect_blockers: list[str] = []
    for row in reconnect_rows:
        row_blockers, last_seq_id = _validate_l2_payload_row(
            row,
            states=states,
            replay_counts=replay_counts,
            global_last_seq_id=last_seq_id,
            generated_at=NOW,
            checked_at=NOW,
        )
        reconnect_blockers.extend(row_blockers)
    assert not any(
        "capture_sequence" in blocker
        for blocker in reconnect_blockers
    )


def test_l2_physical_time_endpoints_bind_attestation_with_tolerance(
    tmp_path: Path,
) -> None:
    attestation = _l2_attestation()
    manifest, root = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version=attestation["dataset_version"],
        attestation_name=L2_ATTESTATION_PATH,
        attestation=attestation,
    )
    table = root / attestation["files"][0]["path"]
    original_rows = [
        json.loads(line)
        for line in table.read_text(encoding="utf-8").splitlines()
    ]

    def shifted(
        rows: list[dict],
        *,
        indices: tuple[int, ...],
        seconds: float,
    ) -> list[dict]:
        result = [dict(row) for row in rows]
        for index in indices:
            for field in ("event_time", "snapshot_time", "available_time"):
                value = datetime.fromisoformat(
                    result[index][field].replace("Z", "+00:00")
                )
                result[index][field] = (
                    value + timedelta(seconds=seconds)
                ).isoformat().replace("+00:00", "Z")
            result[index]["monotonic_ns"] += int(seconds * 1_000_000_000)
        return result

    def validate(rows: list[dict]) -> dict:
        table.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        return _validate_l2_attestation(
            attestation,
            manifest=manifest,
            now=NOW,
            freshness_sla_hours=1.0,
            min_coverage_pct=100.0,
            max_clock_offset_ms=1_000.0,
            resolved_root=root,
        )

    assert validate(
        shifted(original_rows, indices=(0, 1, 2), seconds=0.05)
    )["status"] == "pass"
    assert validate(
        shifted(original_rows, indices=(1,), seconds=0.05)
    )["status"] == "pass"
    for rows in (
        shifted(original_rows, indices=(0, 1, 2), seconds=60.0),
        shifted(original_rows, indices=(0,), seconds=-60.0),
        shifted(original_rows, indices=(2,), seconds=60.0),
    ):
        result = validate(rows)
        assert result["status"] == "blocked"
        assert "l2_payload_endpoint_mismatch" in result["blockers"]


def test_manifest_and_attestation_readiness_must_be_consistent(
    tmp_path: Path,
) -> None:
    snapshot, l2 = _valid_inputs(tmp_path)
    snapshot["readiness_class"] = "research_ready"

    report = _consume(tmp_path, snapshot, l2)

    assert report["status"] == "blocked"
    assert (
        "kline_manifest_attestation_readiness_mismatch"
        in report["blockers"]
    )
    assert report["readiness"] == {
        "quality_checked": False,
        "research_ready": False,
        "backtest_ready": False,
        "promotion_evidence_ready": False,
    }
    synthetic_attestation = {
        "readiness": {
            "quality_checked": True,
            "research_ready": True,
            "backtest_ready": True,
            "promotion_evidence_ready": False,
        }
    }
    assert _readiness_consistency_blockers(
        {"readiness_class": "quality_checked"},
        synthetic_attestation,
        prefix="synthetic",
    ) == ["synthetic_manifest_attestation_readiness_mismatch"]


def test_l2_consumer_rejects_virtual_row_count_and_extra_manifest_payload(
    tmp_path: Path,
) -> None:
    attestation = _l2_attestation()
    manifest, root = _publish_fixture(
        tmp_path,
        dataset_id=L2_DATASET_ID,
        dataset_version=attestation["dataset_version"],
        attestation_name=L2_ATTESTATION_PATH,
        attestation=attestation,
    )
    table = root / attestation["files"][0]["path"]
    table.write_text(
        '{"segment_name":"segment-a"}\n'
        '{"segment_name":"segment-a"}\n',
        encoding="utf-8",
    )

    result = _validate_l2_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        resolved_root=root,
    )
    assert "l2_payload_file_row_count_mismatch" in result["blockers"]
    assert "l2_payload_book_row_total_mismatch" in result["blockers"]
    assert "l2_payload_segment_row_total_mismatch" in result["blockers"]

    extra = _l2_attestation()
    manifest_files = [
        *extra["files"],
        {"path": "extra.jsonl", "sha256": "0" * 64, "bytes": 1},
    ]
    extra_result = _validate_direct_l2(
        extra,
        manifest_files=manifest_files,
    )
    assert (
        "l2_manifest_payload_inventory_mismatch"
        in extra_result["blockers"]
    )


def test_kline_consumer_rejects_virtual_rows_and_extra_manifest_payload(
    tmp_path: Path,
) -> None:
    attestation = _kline_attestation()
    manifest, root = _publish_fixture(
        tmp_path,
        dataset_id=SNAPSHOT_DATASET_ID,
        dataset_version=attestation["dataset_version"],
        attestation_name=KLINE_ATTESTATION_PATH,
        attestation=attestation,
    )
    table = root / attestation["files"][0]["path"]
    rows = table.read_text(encoding="utf-8").splitlines()
    table.write_text("\n".join(rows[:2]) + "\n", encoding="utf-8")

    result = _validate_kline_attestation(
        attestation,
        manifest=manifest,
        now=NOW,
        freshness_sla_hours=48.0,
        min_coverage_pct=99.0,
        resolved_root=root,
    )
    assert "kline_payload_file_row_count_mismatch" in result["blockers"]
    assert "kline_payload_interval_row_total_mismatch" in result["blockers"]

    extra = _kline_attestation()
    extra_result = _validate_direct_kline(
        extra,
        manifest_files=[
            *extra["files"],
            {"path": "extra.jsonl", "sha256": "0" * 64, "bytes": 1},
        ],
    )
    assert (
        "kline_manifest_payload_inventory_mismatch"
        in extra_result["blockers"]
    )


def test_attestation_source_head_binds_manifest_and_commit_existence() -> None:
    attestation = _l2_attestation()
    mismatch = _validate_l2_attestation(
        attestation,
        manifest={
            "dataset_id": attestation["dataset_id"],
            "dataset_version": attestation["dataset_version"],
            "producer_commit": "f" * 40,
            "files": attestation["files"],
            "coverage": {
                "start": attestation["coverage_start"],
                "end": attestation["coverage_end"],
            },
        },
        now=NOW,
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=1_000.0,
        commit_exists=lambda value: value != attestation["source_head"],
        current_head="b" * 40,
    )

    assert "l2_source_head_unavailable" in mismatch["blockers"]
    assert "l2_source_head_manifest_commit_mismatch" in mismatch["blockers"]
