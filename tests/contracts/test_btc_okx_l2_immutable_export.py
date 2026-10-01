from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

import quant_crypto.data.immutable_okx_l2_export as l2_exporter
from quant_crypto.data.immutable_okx_l2_export import (
    ATTESTATION_NAME,
    L2ExportBlocked,
    L2SegmentSource,
    export_immutable_okx_l2,
)
from quant_crypto.data.dataready_consumer import _validate_l2_attestation


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "schemas/btc_okx_l2_dataready_attestation.schema.json"
HEAD = "b" * 40
VERSION = "btc-okx-l2-fixture-20260726-v1"
START = datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _book_row(
    *,
    capture_sequence: int,
    connection_sequence: int,
    action: str,
    seq_id: int,
    prev_seq_id: int,
    event_time: datetime,
    receive_delay_ms: int = 100,
    monotonic_ns: int | None = None,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    checksum: int = 0,
) -> dict[str, object]:
    payload = {
        "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
        "action": action,
        "data": [
            {
                "bids": bids
                if bids is not None
                else [["99.9", "1.0", "0", "1"], ["99.8", "2.0", "0", "1"]],
                "asks": asks
                if asks is not None
                else [["100.1", "1.0", "0", "1"], ["100.2", "2.0", "0", "1"]],
                "ts": str(int(event_time.timestamp() * 1000)),
                "seqId": seq_id,
                "prevSeqId": prev_seq_id,
                "checksum": checksum,
            }
        ],
    }
    receive_time = event_time + timedelta(milliseconds=receive_delay_ms)
    return {
        "capture_sequence": capture_sequence,
        "connection_sequence": connection_sequence,
        "local_receive_ts": receive_time.isoformat().replace("+00:00", "Z"),
        "monotonic_ns": (
            monotonic_ns
            if monotonic_ns is not None
            else int(receive_time.timestamp() * 1_000_000_000)
        ),
        "channel": "books",
        "instId": "BTC-USDT-SWAP",
        "action": action,
        "raw": json.dumps(payload, sort_keys=True),
    }


def _segment(
    root: Path,
    name: str,
    rows: list[dict[str, object]],
    *,
    manifest_overrides: dict[str, object] | None = None,
) -> L2SegmentSource:
    segment = root / name
    segment.mkdir(parents=True)
    raw_path = segment / "okx_public_ws_l2_raw_messages.jsonl"
    manifest_path = segment / "okx_public_ws_l2_raw_capture_manifest.json"
    raw_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    receive_times = [str(row["local_receive_ts"]) for row in rows]
    capture_start = min(receive_times)
    capture_end = max(receive_times)
    if capture_end == capture_start:
        capture_end = (
            datetime.fromisoformat(capture_start.replace("Z", "+00:00"))
            + timedelta(milliseconds=1)
        ).isoformat().replace("+00:00", "Z")
    duration = (
        datetime.fromisoformat(capture_end.replace("Z", "+00:00"))
        - datetime.fromisoformat(capture_start.replace("Z", "+00:00"))
    ).total_seconds()
    capture_started_monotonic_ns = min(
        int(row["monotonic_ns"]) for row in rows
    )
    capture_ended_monotonic_ns = (
        capture_started_monotonic_ns + int(duration * 1_000_000_000)
    )
    manifest = {
        "schema_version": "btc_okx_public_ws_l2_raw_capture_manifest_v1",
        "data_version": name,
        "capture_start": capture_start,
        "capture_end": capture_end,
        "capture_duration_seconds": duration,
        "capture_started_monotonic_ns": capture_started_monotonic_ns,
        "capture_ended_monotonic_ns": capture_ended_monotonic_ns,
        "public_ws_url": "wss://ws.okx.com:8443/ws/v5/public",
        "venue": "okx",
        "venue_symbol": "BTC-USDT-SWAP",
        "symbol": "BTCUSDT",
        "public_channels": ["books"],
        "public_ws_only": True,
        "api_key_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_calls_used": False,
        "clock_source": "system_utc_and_python_monotonic_ns",
        "checksum_or_sequence_policy": (
            "raw_ws_capture_before_order_book_replay_sequence_validation"
        ),
        "message_count": len(rows),
        "data_message_count": len(rows),
        "channel_counts": {"books": len(rows)},
        "connection_count": max(
            int(row["connection_sequence"]) for row in rows
        ),
        "forced_reconnect_count": 0,
        "error_count": 0,
        "gap_count": 0,
    }
    manifest.update(manifest_overrides or {})
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return L2SegmentSource(
        segment_dir=segment,
        expected_raw_sha256=_sha256(raw_path),
        expected_manifest_sha256=_sha256(manifest_path),
    )


def _valid_rows(
    *,
    start: datetime = START,
    seq_start: int = 10,
) -> list[dict[str, object]]:
    return [
        _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=seq_start,
            prev_seq_id=-1,
            event_time=start,
        ),
        _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=seq_start + 1,
            prev_seq_id=seq_start,
            event_time=start + timedelta(seconds=1),
            bids=[["99.9", "1.5", "0", "1"]],
            asks=[["100.1", "1.5", "0", "1"]],
        ),
    ]


def _export(
    sources: tuple[L2SegmentSource, ...],
    output: Path,
    *,
    now: datetime | None = None,
    max_inter_message_gap_seconds: float = 5.0,
) -> dict[str, object]:
    return export_immutable_okx_l2(
        segments=sources,
        output_dir=output,
        dataset_version=VERSION,
        source_head=HEAD,
        now=now or START + timedelta(seconds=4),
        max_clock_lag_ms=5_000,
        freshness_sla_minutes=15,
        max_inter_message_gap_seconds=max_inter_message_gap_seconds,
    )


def test_valid_segments_export_deterministic_partitioned_replay(
    tmp_path: Path,
) -> None:
    first = _segment(tmp_path, "segment-a", _valid_rows())
    second = _segment(
        tmp_path,
        "segment-b",
        _valid_rows(
            start=START + timedelta(seconds=1),
            seq_start=12,
        ),
    )
    output = tmp_path / "exported"

    report = _export((first, second), output)

    assert report["status"] == "quality_checked"
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        attestation,
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )
    assert attestation["sequence_validation_status"] == "pass"
    assert attestation["sequence_gap_count"] == 0
    assert attestation["unrecovered_gap_count"] == 0
    assert attestation["segment_count"] == 2
    assert attestation["snapshot_count"] == 2
    assert attestation["update_count"] == 2
    assert attestation["resync_snapshot_count"] == 1
    assert attestation["two_sided_coverage_pct"] == 100.0
    assert attestation["history_window_days"] < 1.0
    assert attestation["observed_history_seconds"] == pytest.approx(2.0)
    assert attestation["gap_windows"] == []
    assert attestation["guardrails"]["network_collection_used"] is False
    assert attestation["readiness"]["promotion_evidence_ready"] is False
    assert {
        "btc_okx_l2_history_below_30_natural_days",
        "btc_execution_latency_model_missing",
        "btc_queue_model_missing",
    } <= set(attestation["promotion_blockers"])
    table_rows = []
    for item in attestation["files"]:
        path = output / item["path"]
        assert _sha256(path) == item["sha256"]
        table_rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
    assert len(table_rows) == 4
    assert all(row["best_bid"] < row["best_ask"] for row in table_rows)
    assert all(row["event_time"] <= row["available_time"] for row in table_rows)
    consumer_result = _validate_l2_attestation(
        attestation,
        manifest={
                "dataset_id": attestation["dataset_id"],
                "dataset_version": attestation["dataset_version"],
                "producer_commit": attestation["source_head"],
                "coverage": {
                "start": attestation["coverage_start"],
                "end": attestation["coverage_end"],
            },
            "files": attestation["files"],
        },
        now=START + timedelta(seconds=4),
        freshness_sla_hours=1.0,
        min_coverage_pct=100.0,
        max_clock_offset_ms=5_000.0,
        resolved_root=output,
    )
    assert consumer_result["status"] == "pass"
    assert consumer_result["blockers"] == []


@pytest.mark.parametrize(
    ("case", "expected_blocker"),
    [
        ("gap", "l2_sequence_gap"),
        ("duplicate", "l2_sequence_duplicate"),
        ("out_of_order", "l2_sequence_out_of_order"),
        ("one_sided", "l2_book_one_sided"),
        ("zero_liquidity", "l2_book_zero_liquidity"),
        ("clock", "l2_clock_lag_exceeds_limit"),
        ("checksum", "l2_checksum_mismatch"),
        ("reconnect", "l2_reconnect_requires_new_snapshot"),
        ("partition_boundary", "l2_segment_requires_initial_snapshot"),
    ],
)
def test_integrity_failures_block_without_publishable_directory(
    tmp_path: Path,
    case: str,
    expected_blocker: str,
) -> None:
    rows = _valid_rows()
    if case == "gap":
        rows[1] = _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=11,
            prev_seq_id=999,
            event_time=START + timedelta(seconds=1),
        )
    elif case == "duplicate":
        rows[1] = _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=10,
            prev_seq_id=10,
            event_time=START + timedelta(seconds=1),
        )
    elif case == "out_of_order":
        rows[1] = _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=9,
            prev_seq_id=10,
            event_time=START + timedelta(seconds=1),
        )
    elif case == "one_sided":
        rows[0] = _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
            asks=[],
        )
    elif case == "zero_liquidity":
        rows[0] = _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
            bids=[["99.9", "0", "0", "1"]],
            asks=[["100.1", "0", "0", "1"]],
        )
    elif case == "clock":
        rows[0] = _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
            receive_delay_ms=6_000,
        )
    elif case == "checksum":
        rows[0] = _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
            checksum=123,
        )
    elif case == "reconnect":
        rows[1] = _book_row(
            capture_sequence=2,
            connection_sequence=2,
            action="update",
            seq_id=11,
            prev_seq_id=10,
            event_time=START + timedelta(seconds=1),
        )
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides=(
            {
                "connection_count": 2,
                "forced_reconnect_count": 1,
                "gap_count": 1,
            }
            if case == "reconnect"
            else None
        ),
    )
    if case == "partition_boundary":
        second_rows = [
            _book_row(
                capture_sequence=1,
                connection_sequence=1,
                action="update",
                seq_id=21,
                prev_seq_id=20,
                event_time=START + timedelta(seconds=1),
            )
        ]
        sources = (source, _segment(tmp_path, "segment-b", second_rows))
    else:
        sources = (source,)
    output = tmp_path / "must-not-exist"

    with pytest.raises(L2ExportBlocked) as caught:
        _export(sources, output)

    assert expected_blocker in caught.value.blockers
    assert not output.exists()


def test_stale_or_hash_mismatched_source_fails_closed(tmp_path: Path) -> None:
    source = _segment(tmp_path, "segment-a", _valid_rows())
    output = tmp_path / "must-not-exist"

    with pytest.raises(L2ExportBlocked) as stale:
        _export((source,), output, now=START + timedelta(hours=1))
    assert "l2_common_end_freshness_sla_breached" in stale.value.blockers

    bad_hash = L2SegmentSource(
        segment_dir=source.segment_dir,
        expected_raw_sha256="0" * 64,
        expected_manifest_sha256=source.expected_manifest_sha256,
    )
    with pytest.raises(L2ExportBlocked) as mismatched:
        _export((bad_hash,), output)
    assert "l2_raw_sha256_mismatch:segment-a" in mismatched.value.blockers
    assert not output.exists()


@pytest.mark.parametrize(
    ("offset", "seq_start", "expected_blocker"),
    [
        (timedelta(days=31), 12, "l2_cross_segment_capture_gap"),
        (timedelta(milliseconds=500), 12, "l2_cross_segment_capture_overlap"),
        (timedelta(seconds=2), 12, "l2_cross_segment_capture_gap"),
        (timedelta(seconds=1), 5, "l2_cross_segment_sequence_not_contiguous"),
    ],
)
def test_cross_segment_gap_overlap_or_sequence_regression_blocks(
    tmp_path: Path,
    offset: timedelta,
    seq_start: int,
    expected_blocker: str,
) -> None:
    first = _segment(tmp_path, "segment-a", _valid_rows())
    second = _segment(
        tmp_path,
        "segment-b",
        _valid_rows(start=START + offset, seq_start=seq_start),
    )
    output = tmp_path / "must-not-exist"

    with pytest.raises(L2ExportBlocked) as caught:
        _export(
            (first, second),
            output,
            now=max(
                START + timedelta(seconds=4),
                START + offset + timedelta(seconds=2),
            ),
        )

    assert expected_blocker in caught.value.blockers
    assert not output.exists()


@pytest.mark.parametrize(
    ("case", "expected_blocker"),
    [
        ("connection", "l2_connection_sequence_rollback"),
        ("event", "l2_exchange_event_time_rollback"),
        ("receive", "l2_local_receive_time_rollback"),
    ],
)
def test_cross_row_connection_event_or_receive_rollback_blocks(
    tmp_path: Path,
    case: str,
    expected_blocker: str,
) -> None:
    rows = _valid_rows()
    if case == "connection":
        rows = [
            rows[0],
            _book_row(
                capture_sequence=2,
                connection_sequence=2,
                action="snapshot",
                seq_id=11,
                prev_seq_id=-1,
                event_time=START + timedelta(seconds=1),
            ),
            _book_row(
                capture_sequence=3,
                connection_sequence=1,
                action="snapshot",
                seq_id=12,
                prev_seq_id=-1,
                event_time=START + timedelta(seconds=2),
            ),
        ]
    elif case == "event":
        rows[1] = _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=11,
            prev_seq_id=10,
            event_time=START - timedelta(seconds=1),
            receive_delay_ms=2_100,
        )
    else:
        rows[1]["local_receive_ts"] = (
            START - timedelta(milliseconds=100)
        ).isoformat().replace("+00:00", "Z")
        rows[1]["monotonic_ns"] = (
            int(rows[0]["monotonic_ns"]) + 100_000_000
        )
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides=(
            {
                "connection_count": 2,
                "forced_reconnect_count": 1,
                "gap_count": 1,
            }
            if case == "connection"
            else None
        ),
    )

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert expected_blocker in caught.value.blockers


def test_manifest_gap_and_connection_counts_are_consumed(tmp_path: Path) -> None:
    source = _segment(
        tmp_path,
        "segment-a",
        _valid_rows(),
        manifest_overrides={"gap_count": 1, "connection_count": 2},
    )

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert "l2_manifest_connection_count_mismatch:segment-a" in caught.value.blockers
    assert "l2_manifest_gap_count_mismatch:segment-a" in caught.value.blockers


def test_recovered_reconnect_emits_measured_gap_and_reduces_coverage(
    tmp_path: Path,
) -> None:
    rows = [
        *_valid_rows(),
        _book_row(
            capture_sequence=3,
            connection_sequence=2,
            action="snapshot",
            seq_id=12,
            prev_seq_id=-1,
            event_time=START + timedelta(seconds=2),
        ),
        _book_row(
            capture_sequence=4,
            connection_sequence=2,
            action="update",
            seq_id=13,
            prev_seq_id=12,
            event_time=START + timedelta(seconds=3),
        ),
    ]
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides={
            "connection_count": 2,
            "forced_reconnect_count": 1,
            "gap_count": 1,
        },
    )
    output = tmp_path / "exported"

    report = _export((source,), output)

    assert report["status"] == "quality_checked"
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    jsonschema.validate(
        attestation,
        json.loads(SCHEMA.read_text(encoding="utf-8")),
    )
    assert attestation["unrecovered_gap_count"] == 0
    assert attestation["gap_windows"] == [
        {
            "segment_name": "segment-a",
            "from_connection_sequence": 1,
            "to_connection_sequence": 2,
            "gap_start": "2026-07-26T00:00:01.100Z",
            "gap_end": "2026-07-26T00:00:02.100Z",
            "duration_seconds": 1.0,
            "recovered": True,
        }
    ]
    assert attestation["observed_history_seconds"] == pytest.approx(2.0)
    assert attestation["two_sided_coverage_pct"] == pytest.approx(
        66.666666667
    )
    assert (
        "btc_okx_l2_two_sided_coverage_incomplete"
        in attestation["promotion_blockers"]
    )


def test_single_connection_31_day_idle_gap_cannot_claim_history(
    tmp_path: Path,
) -> None:
    rows = [
        _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
        ),
        _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=11,
            prev_seq_id=10,
            event_time=START + timedelta(days=31),
        ),
    ]
    source = _segment(tmp_path, "segment-a", rows)
    output = tmp_path / "must-not-exist"

    with pytest.raises(L2ExportBlocked) as caught:
        _export(
            (source,),
            output,
            now=START + timedelta(days=31, seconds=2),
        )

    assert "l2_inter_message_gap_exceeds_limit" in caught.value.blockers
    assert not output.exists()


def test_oversized_caller_gap_policy_cannot_bypass_31_day_idle_gap(
    tmp_path: Path,
) -> None:
    rows = [
        _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
        ),
        _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=11,
            prev_seq_id=10,
            event_time=START + timedelta(days=31),
        ),
    ]
    source = _segment(tmp_path, "segment-a", rows)

    with pytest.raises(L2ExportBlocked) as caught:
        _export(
            (source,),
            tmp_path / "must-not-exist",
            now=START + timedelta(days=31, seconds=2),
            max_inter_message_gap_seconds=31 * 86_400.0 + 1.0,
        )

    assert (
        "l2_max_inter_message_gap_exceeds_governed_ceiling"
        in caught.value.blockers
    )


def test_stricter_than_governed_gap_policy_is_accepted(
    tmp_path: Path,
) -> None:
    rows = [
        _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=10,
            prev_seq_id=-1,
            event_time=START,
        ),
        _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="update",
            seq_id=11,
            prev_seq_id=10,
            event_time=START + timedelta(milliseconds=250),
        ),
    ]
    source = _segment(tmp_path, "segment-a", rows)
    output = tmp_path / "exported"

    report = _export(
        (source,),
        output,
        max_inter_message_gap_seconds=0.5,
    )

    assert report["status"] == "quality_checked"
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    assert attestation["max_inter_message_gap_seconds"] == 0.5
    assert (
        attestation["approved_max_inter_message_gap_seconds"] == 5.0
    )
    assert (
        attestation["inter_message_gap_policy_id"]
        == "btc_okx_l2_inter_message_gap_v1"
    )


def test_manifest_duration_tail_inflation_blocks(
    tmp_path: Path,
) -> None:
    rows = _valid_rows()
    monotonic_start = int(rows[0]["monotonic_ns"])
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides={
            "capture_end": (
                START + timedelta(days=31, milliseconds=100)
            ).isoformat().replace("+00:00", "Z"),
            "capture_duration_seconds": 31 * 86_400.0,
            "capture_started_monotonic_ns": monotonic_start,
            "capture_ended_monotonic_ns": (
                monotonic_start + 31 * 86_400 * 1_000_000_000
            ),
        },
    )
    output = tmp_path / "must-not-exist"

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), output)

    assert "l2_manifest_receive_end_endpoint_unanchored" in caught.value.blockers
    assert (
        "l2_manifest_monotonic_end_endpoint_unanchored"
        in caught.value.blockers
    )
    assert not output.exists()


@pytest.mark.parametrize(
    ("case", "expected_blocker"),
    [
        ("head", "l2_manifest_receive_start_endpoint_unanchored"),
        ("tail", "l2_manifest_receive_end_endpoint_unanchored"),
    ],
)
def test_unobserved_manifest_head_or_tail_is_unrecovered_gap(
    tmp_path: Path,
    case: str,
    expected_blocker: str,
) -> None:
    rows = _valid_rows()
    first_receive = datetime.fromisoformat(
        str(rows[0]["local_receive_ts"]).replace("Z", "+00:00")
    )
    last_receive = datetime.fromisoformat(
        str(rows[-1]["local_receive_ts"]).replace("Z", "+00:00")
    )
    first_monotonic = int(rows[0]["monotonic_ns"])
    last_monotonic = int(rows[-1]["monotonic_ns"])
    if case == "head":
        capture_start = first_receive - timedelta(days=1)
        capture_end = last_receive
        monotonic_start = first_monotonic - 86_400 * 1_000_000_000
        monotonic_end = last_monotonic
    else:
        capture_start = first_receive
        capture_end = last_receive + timedelta(days=1)
        monotonic_start = first_monotonic
        monotonic_end = last_monotonic + 86_400 * 1_000_000_000
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides={
            "capture_start": capture_start.isoformat().replace("+00:00", "Z"),
            "capture_end": capture_end.isoformat().replace("+00:00", "Z"),
            "capture_duration_seconds": (
                capture_end - capture_start
            ).total_seconds(),
            "capture_started_monotonic_ns": monotonic_start,
            "capture_ended_monotonic_ns": monotonic_end,
        },
    )

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert expected_blocker in caught.value.blockers


def test_30_day_monotonic_29_day_receipt_cumulative_drift_blocks() -> None:
    blockers = l2_exporter._cumulative_clock_span_blockers(
        receive_span_seconds=29 * 86_400.0,
        monotonic_span_seconds=30 * 86_400.0,
        segment_name="segment-a",
    )

    assert "l2_monotonic_receive_cumulative_drift_exceeds_limit:segment-a" in blockers
    assert l2_exporter._conservative_observed_delta_seconds(3.0, 3.1) == 3.0


def test_small_manifest_endpoint_tolerance_remains_valid(
    tmp_path: Path,
) -> None:
    rows = _valid_rows()
    first_receive = datetime.fromisoformat(
        str(rows[0]["local_receive_ts"]).replace("Z", "+00:00")
    )
    last_receive = datetime.fromisoformat(
        str(rows[-1]["local_receive_ts"]).replace("Z", "+00:00")
    )
    first_monotonic = int(rows[0]["monotonic_ns"])
    last_monotonic = int(rows[-1]["monotonic_ns"])
    tolerance = timedelta(milliseconds=50)
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides={
            "capture_start": (
                first_receive - tolerance
            ).isoformat().replace("+00:00", "Z"),
            "capture_end": (
                last_receive + tolerance
            ).isoformat().replace("+00:00", "Z"),
            "capture_duration_seconds": 1.1,
            "capture_started_monotonic_ns": (
                first_monotonic - 50_000_000
            ),
            "capture_ended_monotonic_ns": last_monotonic + 50_000_000,
        },
    )
    output = tmp_path / "exported"

    report = _export((source,), output)

    assert report["status"] == "quality_checked"
    attestation = json.loads(
        (output / ATTESTATION_NAME).read_text(encoding="utf-8")
    )
    assert attestation["observed_history_seconds"] == pytest.approx(1.0)


@pytest.mark.parametrize("overhead_microseconds", [10, 100])
def test_manifest_capture_duration_accepts_micro_overhead(
    tmp_path: Path,
    overhead_microseconds: int,
) -> None:
    rows = _valid_rows()
    base_duration_seconds = 1.0
    monotonic_start = int(rows[0]["monotonic_ns"])
    overhead_seconds = overhead_microseconds / 1_000_000.0
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides={
            "capture_duration_seconds": (
                base_duration_seconds + overhead_seconds
            ),
            "capture_started_monotonic_ns": monotonic_start,
            "capture_ended_monotonic_ns": (
                monotonic_start
                + int(
                    (
                        base_duration_seconds + overhead_seconds
                    )
                    * 1_000_000_000
                )
            ),
        },
    )

    report = _export((source,), tmp_path / "exported")

    assert report["status"] == "quality_checked"


def test_manifest_capture_duration_over_governed_bound_blocks(
    tmp_path: Path,
) -> None:
    rows = _valid_rows()
    monotonic_start = int(rows[0]["monotonic_ns"])
    source = _segment(
        tmp_path,
        "segment-a",
        rows,
        manifest_overrides={
            "capture_duration_seconds": 1.201,
            "capture_started_monotonic_ns": monotonic_start,
            "capture_ended_monotonic_ns": (
                monotonic_start + 1_201_000_000
            ),
        },
    )

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert (
        "l2_manifest_capture_duration_mismatch:segment-a"
        in caught.value.blockers
    )


def test_same_connection_second_snapshot_cannot_reset_sequence(
    tmp_path: Path,
) -> None:
    rows = [
        _book_row(
            capture_sequence=1,
            connection_sequence=1,
            action="snapshot",
            seq_id=11,
            prev_seq_id=-1,
            event_time=START,
        ),
        _book_row(
            capture_sequence=2,
            connection_sequence=1,
            action="snapshot",
            seq_id=999,
            prev_seq_id=-1,
            event_time=START + timedelta(seconds=1),
        ),
    ]
    source = _segment(tmp_path, "segment-a", rows)

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert (
        "l2_unjustified_same_connection_snapshot_reset"
        in caught.value.blockers
    )


def test_raw_capture_manifest_requires_zero_errors(
    tmp_path: Path,
) -> None:
    source = _segment(
        tmp_path,
        "segment-a",
        _valid_rows(),
        manifest_overrides={"error_count": 1},
    )

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert (
        "l2_manifest_capture_errors_present:segment-a"
        in caught.value.blockers
    )


def test_capture_sequence_jump_within_segment_blocks(tmp_path: Path) -> None:
    rows = _valid_rows()
    rows[1]["capture_sequence"] = 3
    source = _segment(tmp_path, "segment-a", rows)

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert "l2_capture_sequence_not_contiguous" in caught.value.blockers


@pytest.mark.parametrize(
    ("overrides", "expected_blocker"),
    [
        (
            {"capture_started_monotonic_ns": None},
            "l2_manifest_monotonic_window_invalid:segment-a",
        ),
        (
            {"capture_ended_monotonic_ns": 123},
            "l2_manifest_monotonic_window_invalid:segment-a",
        ),
    ],
)
def test_manifest_monotonic_window_missing_or_invalid_blocks(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_blocker: str,
) -> None:
    source = _segment(
        tmp_path,
        "segment-a",
        _valid_rows(),
        manifest_overrides=overrides,
    )

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert expected_blocker in caught.value.blockers


def test_row_monotonic_delta_must_match_local_receive_delta(
    tmp_path: Path,
) -> None:
    rows = _valid_rows()
    rows[1]["monotonic_ns"] = int(rows[0]["monotonic_ns"]) + 1_000
    source = _segment(tmp_path, "segment-a", rows)

    with pytest.raises(L2ExportBlocked) as caught:
        _export((source,), tmp_path / "must-not-exist")

    assert "l2_monotonic_receive_delta_mismatch" in caught.value.blockers


def test_exporter_uses_import_safe_capture_contract_module() -> None:
    source = (
        ROOT / "quant_crypto/data/immutable_okx_l2_export.py"
    ).read_text(encoding="utf-8")
    assert "scripts.fetch_btc_okx_public_ws_l2_raw_capture" not in source
    assert "quant_crypto.data.okx_l2_capture_contract" in source
