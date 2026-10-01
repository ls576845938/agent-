"""Offline immutable OKX trades + ordered-L2 export for 10s research.

The raw capture is produced by the existing public-only collector.  Book
reconstruction remains owned by :mod:`immutable_okx_l2_export`; this module
adds strict trade normalization and a point-in-time backward book join.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from quant_crypto.data.immutable_okx_l2_export import (
    ATTESTATION_NAME as L2_ATTESTATION_NAME,
    L2ExportBlocked,
    L2SegmentSource,
    export_immutable_okx_l2,
)
from quant_crypto.data.okx_l2_capture_contract import (
    OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION,
    OKX_L2_INSTRUMENT_ID,
    OKX_L2_RAW_MANIFEST_FILE,
    OKX_L2_RAW_MESSAGES_FILE,
    OKX_L2_VENUE,
)
from tools.agent_governance.shared_data import aggregate_inventory_hash


DATASET_ID = "btc-okx-10s-microstructure-immutable-feed"
SCHEMA_VERSION = "btc_okx_10s_microstructure_immutable_feed_v1"
EXPORTER_VERSION = "btc_okx_10s_microstructure_immutable_export_v1"
ATTESTATION_NAME = "btc_okx_10s_microstructure_immutable_feed_attestation.json"
EXACT_CHANNELS = ("trades", "books")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class MicrostructureExportBlocked(RuntimeError):
    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(dict.fromkeys(str(item) for item in blockers if str(item)))
        super().__init__(";".join(self.blockers))


@dataclass(frozen=True)
class MicrostructureSegmentSource:
    segment_dir: Path
    expected_raw_sha256: str
    expected_manifest_sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _utc(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return None
    index = max(0, min(len(finite) - 1, math.ceil(len(finite) * fraction) - 1))
    return round(finite[index], 6)


def _load_segments(
    sources: Sequence[MicrostructureSegmentSource],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    blockers: list[str] = []
    trades: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    l2_sources: list[dict[str, Any]] = []
    seen_trade_ids: set[str] = set()
    last_capture = 0
    last_monotonic = 0
    last_receive: datetime | None = None
    last_trade_time: datetime | None = None
    for source in sources:
        segment = source.segment_dir.resolve()
        raw_path = segment / OKX_L2_RAW_MESSAGES_FILE
        manifest_path = segment / OKX_L2_RAW_MANIFEST_FILE
        if not raw_path.is_file() or not manifest_path.is_file():
            blockers.append(f"microstructure_segment_files_missing:{segment.name}")
            continue
        raw_hash = _sha256_file(raw_path)
        manifest_hash = _sha256_file(manifest_path)
        if raw_hash != source.expected_raw_sha256:
            blockers.append(f"microstructure_raw_sha256_mismatch:{segment.name}")
        if manifest_hash != source.expected_manifest_sha256:
            blockers.append(f"microstructure_manifest_sha256_mismatch:{segment.name}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            blockers.append(f"microstructure_manifest_unreadable:{segment.name}")
            continue
        if manifest.get("schema_version") != OKX_L2_CAPTURE_MANIFEST_SCHEMA_VERSION:
            blockers.append(f"microstructure_capture_schema_invalid:{segment.name}")
        if tuple(manifest.get("public_channels", [])) != EXACT_CHANNELS:
            blockers.append(f"microstructure_exact_channels_required:{segment.name}")
        for key in ("api_key_used", "private_endpoint_used", "order_endpoint_used", "broker_calls_used"):
            if manifest.get(key) is not False:
                blockers.append(f"microstructure_capture_safety_flag_invalid:{key}")
        row_count = 0
        channel_counts: dict[str, int] = {}
        with raw_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    envelope = json.loads(line)
                except (json.JSONDecodeError, AttributeError):
                    blockers.append(f"microstructure_envelope_json_invalid:{segment.name}:{line_number}")
                    continue
                row_count += 1
                capture_sequence = _integer(envelope.get("capture_sequence"))
                monotonic_ns = _integer(envelope.get("monotonic_ns"))
                connection_sequence = _integer(envelope.get("connection_sequence"))
                if capture_sequence is None or capture_sequence != last_capture + 1:
                    blockers.append("microstructure_capture_sequence_not_contiguous")
                if monotonic_ns is None or monotonic_ns <= last_monotonic:
                    blockers.append("microstructure_monotonic_ns_not_strict")
                if connection_sequence is None or connection_sequence <= 0:
                    blockers.append("microstructure_connection_sequence_invalid")
                receive_time = None
                try:
                    receive_time = _utc(envelope.get("local_receive_ts"))
                except (TypeError, ValueError):
                    blockers.append("microstructure_available_time_invalid")
                if receive_time is not None and last_receive is not None and receive_time < last_receive:
                    blockers.append("microstructure_available_time_rollback")
                if capture_sequence is not None:
                    last_capture = capture_sequence
                if monotonic_ns is not None:
                    last_monotonic = monotonic_ns
                if receive_time is not None:
                    last_receive = receive_time
                envelope_channel = str(envelope.get("channel", ""))
                if envelope_channel not in EXACT_CHANNELS:
                    continue
                try:
                    message = json.loads(str(envelope.get("raw", "")))
                except (json.JSONDecodeError, AttributeError):
                    blockers.append(f"microstructure_raw_json_invalid:{segment.name}:{line_number}")
                    continue
                arg = message.get("arg") if isinstance(message, Mapping) else None
                channel = str(arg.get("channel", "")) if isinstance(arg, Mapping) else ""
                data = message.get("data") if isinstance(message, Mapping) else None
                if channel != envelope_channel:
                    blockers.append("microstructure_envelope_payload_channel_mismatch")
                    continue
                if isinstance(data, list):
                    channel_counts[channel] = channel_counts.get(channel, 0) + 1
                if channel != "trades" or not isinstance(data, list):
                    continue
                if not isinstance(arg, Mapping) or arg.get("instId") != OKX_L2_INSTRUMENT_ID:
                    blockers.append("microstructure_trade_instrument_invalid")
                    continue
                for item_index, item in enumerate(data):
                    if not isinstance(item, Mapping):
                        blockers.append("microstructure_trade_row_invalid")
                        continue
                    trade_id = str(item.get("tradeId", ""))
                    if not trade_id:
                        blockers.append("microstructure_trade_id_missing")
                        continue
                    if trade_id in seen_trade_ids:
                        blockers.append("microstructure_duplicate_trade_id")
                        continue
                    seen_trade_ids.add(trade_id)
                    try:
                        event_time = datetime.fromtimestamp(int(str(item.get("ts"))) / 1000, tz=timezone.utc)
                        price = float(str(item.get("px")))
                        size = float(str(item.get("sz")))
                    except (TypeError, ValueError):
                        blockers.append("microstructure_trade_numeric_invalid")
                        continue
                    side = str(item.get("side", ""))
                    if side not in {"buy", "sell"} or price <= 0 or size <= 0:
                        blockers.append("microstructure_trade_semantics_invalid")
                        continue
                    if last_trade_time is not None and event_time < last_trade_time:
                        blockers.append("microstructure_trade_event_time_out_of_order")
                    last_trade_time = event_time
                    if receive_time is None or event_time > receive_time:
                        blockers.append("microstructure_trade_event_after_available_time")
                        continue
                    trades.append(
                        {
                            "venue": OKX_L2_VENUE,
                            "instrument_id": OKX_L2_INSTRUMENT_ID,
                            "channel": "trades",
                            "trade_id": trade_id,
                            "event_time": _utc_text(event_time),
                            "available_time": _utc_text(receive_time),
                            "ingested_at": _utc_text(receive_time),
                            "capture_sequence": capture_sequence,
                            "connection_sequence": connection_sequence,
                            "monotonic_ns": monotonic_ns,
                            "message_item_index": item_index,
                            "price": price,
                            "size": size,
                            "aggressor_side": side,
                            "source_payload_sha256": _stable_hash(message),
                        }
                    )
        if row_count != int(manifest.get("message_count", -1)):
            blockers.append(f"microstructure_manifest_message_count_mismatch:{segment.name}")
        expected_counts = manifest.get("channel_counts", {})
        for channel in EXACT_CHANNELS:
            if channel_counts.get(channel, 0) != int(expected_counts.get(channel, -1)):
                blockers.append(f"microstructure_manifest_channel_count_mismatch:{segment.name}:{channel}")
        source_rows.append(
            {
                "segment_name": segment.name,
                "raw_sha256": raw_hash,
                "manifest_sha256": manifest_hash,
                "message_count": row_count,
                "channel_counts": channel_counts,
            }
        )
        l2_sources.append(
            {
                "segment_dir": segment,
                "expected_raw_sha256": raw_hash,
                "expected_manifest_sha256": manifest_hash,
            }
        )
    if not sources:
        blockers.append("microstructure_source_segments_missing")
    if not trades:
        blockers.append("microstructure_trades_missing")
    if blockers:
        raise MicrostructureExportBlocked(blockers)
    return trades, source_rows, l2_sources


def _integer(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _jsonl_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    attestation = json.loads((root / L2_ATTESTATION_NAME).read_text(encoding="utf-8"))
    for item in attestation.get("files", []):
        path = root / str(item["path"])
        with path.open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return sorted(rows, key=lambda row: int(row["capture_sequence"]))


def _depth_vwap(levels: object, required_size: float) -> float | None:
    if not isinstance(levels, list) or required_size <= 0:
        return None
    remaining = required_size
    notional = 0.0
    filled = 0.0
    for raw in levels:
        try:
            price, available = float(raw[0]), float(raw[1])
        except (TypeError, ValueError, IndexError):
            continue
        take = min(remaining, max(0.0, available))
        notional += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    return notional / filled if filled > 0 and remaining <= 1e-12 else None


def _join_trades(
    trades: Sequence[Mapping[str, Any]],
    books: Sequence[Mapping[str, Any]],
    *,
    taker_fee_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    joined: list[dict[str, Any]] = []
    book_index = 0
    latest: Mapping[str, Any] | None = None
    receive_lags: list[float] = []
    alignments: list[float] = []
    cost_complete = 0
    for trade in trades:
        sequence = int(trade["capture_sequence"])
        available = _utc(trade["available_time"])
        while book_index < len(books):
            candidate = books[book_index]
            candidate_available = _utc(candidate["available_time"])
            if int(candidate["capture_sequence"]) > sequence or candidate_available > available:
                break
            latest = candidate
            book_index += 1
        row = dict(trade)
        event = _utc(trade["event_time"])
        receive_lags.append((available - event).total_seconds() * 1000.0)
        row.update(
            {
                "book_joined": False,
                "book_capture_sequence": None,
                "book_event_time": None,
                "book_available_time": None,
                "best_bid": None,
                "best_ask": None,
                "mid": None,
                "spread_bps": None,
                "depth_impact_bps": None,
                "taker_fee_bps": float(taker_fee_bps),
                "estimated_one_way_cost_bps": None,
            }
        )
        if latest is not None:
            book_available = _utc(latest["available_time"])
            best_bid, best_ask = float(latest["best_bid"]), float(latest["best_ask"])
            mid = (best_bid + best_ask) / 2.0
            side = str(trade["aggressor_side"])
            vwap = _depth_vwap(latest["asks"] if side == "buy" else latest["bids"], float(trade["size"]))
            impact = abs(vwap - mid) / mid * 10_000.0 if vwap is not None else None
            spread = (best_ask - best_bid) / mid * 10_000.0
            alignment = (available - book_available).total_seconds() * 1000.0
            if alignment < 0:
                raise MicrostructureExportBlocked(["microstructure_future_book_join_detected"])
            alignments.append(alignment)
            estimated_cost = taker_fee_bps + spread / 2.0 + impact if impact is not None else None
            if estimated_cost is not None:
                cost_complete += 1
            row.update(
                {
                    "book_joined": True,
                    "book_capture_sequence": int(latest["capture_sequence"]),
                    "book_event_time": latest["event_time"],
                    "book_available_time": latest["available_time"],
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid": mid,
                    "spread_bps": round(spread, 9),
                    "depth_impact_bps": round(impact, 9) if impact is not None else None,
                    "estimated_one_way_cost_bps": round(estimated_cost, 9) if estimated_cost is not None else None,
                }
            )
        joined.append(row)
    count = len(joined)
    return joined, {
        "trade_count": count,
        "joined_trade_count": sum(bool(row["book_joined"]) for row in joined),
        "cost_complete_trade_count": cost_complete,
        "joined_coverage_pct": round(100.0 * sum(bool(row["book_joined"]) for row in joined) / count, 9) if count else 0.0,
        "cost_sample_completeness_pct": round(100.0 * cost_complete / count, 9) if count else 0.0,
        "receive_lag_p99_ms": _percentile(receive_lags, 0.99),
        "trade_book_alignment_p99_ms": _percentile(alignments, 0.99),
    }


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _l2_validation_sources(
    sources: Sequence[MicrostructureSegmentSource],
    validation_root: Path,
) -> tuple[L2SegmentSource, ...]:
    """Make heartbeat-compatible input for the legacy L2 replay validator.

    The authoritative raw files are copied unchanged under ``raw/``.  The
    legacy validator expects every envelope ``raw`` value to contain JSON,
    while the collector intentionally records text ``pong`` heartbeat frames.
    Only those non-market frames are normalized to an empty JSON object in this
    disposable validation view; market-data bytes are never changed.
    """
    resolved: list[L2SegmentSource] = []
    for index, source in enumerate(sources, 1):
        segment = validation_root / f"segment-{index:08d}"
        segment.mkdir(parents=True, exist_ok=False)
        input_raw = source.segment_dir / OKX_L2_RAW_MESSAGES_FILE
        output_raw = segment / OKX_L2_RAW_MESSAGES_FILE
        with input_raw.open("r", encoding="utf-8") as reader, output_raw.open(
            "x", encoding="utf-8", newline="\n"
        ) as writer:
            for line in reader:
                envelope = json.loads(line)
                if str(envelope.get("channel", "")) not in EXACT_CHANNELS:
                    try:
                        json.loads(str(envelope.get("raw", "")))
                    except json.JSONDecodeError:
                        envelope["raw"] = "{}"
                writer.write(
                    json.dumps(
                        envelope,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    + "\n"
                )
            writer.flush()
            os.fsync(writer.fileno())
        manifest = json.loads(
            (source.segment_dir / OKX_L2_RAW_MANIFEST_FILE).read_text(
                encoding="utf-8"
            )
        )
        output_manifest = segment / OKX_L2_RAW_MANIFEST_FILE
        _write_json(output_manifest, manifest)
        resolved.append(
            L2SegmentSource(
                segment_dir=segment,
                expected_raw_sha256=_sha256_file(output_raw),
                expected_manifest_sha256=_sha256_file(output_manifest),
            )
        )
    return tuple(resolved)


def export_immutable_okx_10s_microstructure(
    *,
    segments: Iterable[MicrostructureSegmentSource],
    output_dir: Path,
    dataset_version: str,
    source_head: str,
    now: datetime,
    producer_role: str = "data_steward",
    taker_fee_bps: float = 5.0,
    l2_exporter: Callable[..., Mapping[str, Any]] = export_immutable_okx_l2,
) -> dict[str, Any]:
    sources = tuple(segments)
    destination = output_dir.resolve()
    blockers: list[str] = []
    if destination.exists():
        blockers.append("microstructure_output_directory_already_exists")
    if not SAFE_ID.fullmatch(dataset_version):
        blockers.append("microstructure_dataset_version_invalid")
    if not COMMIT.fullmatch(source_head):
        blockers.append("microstructure_source_head_invalid")
    if producer_role != "data_steward":
        blockers.append("microstructure_producer_role_invalid")
    if not math.isfinite(taker_fee_bps) or taker_fee_bps < 0:
        blockers.append("microstructure_taker_fee_invalid")
    if blockers:
        raise MicrostructureExportBlocked(blockers)
    trades, source_rows, l2_sources = _load_segments(sources)
    staging = destination.with_name(f".{destination.name}.staging-{uuid.uuid4().hex}")
    ordered_l2 = staging / "ordered-l2"
    try:
        staging.mkdir(parents=True, exist_ok=False)
        for index, source in enumerate(sources, 1):
            raw_target = staging / "raw" / f"segment-{index:08d}"
            raw_target.mkdir(parents=True, exist_ok=False)
            shutil.copy2(
                source.segment_dir / OKX_L2_RAW_MESSAGES_FILE,
                raw_target / OKX_L2_RAW_MESSAGES_FILE,
            )
            shutil.copy2(
                source.segment_dir / OKX_L2_RAW_MANIFEST_FILE,
                raw_target / OKX_L2_RAW_MANIFEST_FILE,
            )
            validation_root = staging / ".l2-validation-input"
            l2_report = l2_exporter(
                segments=_l2_validation_sources(sources, validation_root),
            output_dir=ordered_l2,
            dataset_version=f"{dataset_version}-ordered-l2",
            source_head=source_head,
            now=now,
            producer_role=producer_role,
            max_clock_lag_ms=5_000.0,
            freshness_sla_minutes=15.0,
                max_inter_message_gap_seconds=5.0,
            )
            shutil.rmtree(validation_root)
        books = _jsonl_rows(ordered_l2)
        joined, metrics = _join_trades(trades, books, taker_fee_bps=taker_fee_bps)
        dates: dict[str, list[dict[str, Any]]] = {}
        for row in joined:
            dates.setdefault(_utc(row["event_time"]).date().isoformat(), []).append(row)
        for date, rows in dates.items():
            _write_jsonl(
                staging / "normalized-trades" / f"venue={OKX_L2_VENUE}" / f"instrument_id={OKX_L2_INSTRUMENT_ID}" / f"date={date}" / "part-00000.jsonl",
                rows,
            )
        l2_attestation = json.loads((ordered_l2 / L2_ATTESTATION_NAME).read_text(encoding="utf-8"))
        event_start = min(_utc(row["event_time"]) for row in trades)
        event_end = max(_utc(row["event_time"]) for row in trades)
        attestation: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "exporter_version": EXPORTER_VERSION,
            "dataset_id": DATASET_ID,
            "dataset_version": dataset_version,
            "source_head": source_head,
            "generated_at": _utc_text(now),
            "venue": OKX_L2_VENUE,
            "instrument_id": OKX_L2_INSTRUMENT_ID,
            "public_channels": list(EXACT_CHANNELS),
            "same_connection_trade_ordered_l2": True,
            "event_time_field": "event_time",
            "available_time_field": "available_time",
            "ingested_at_field": "ingested_at",
            "coverage_start": _utc_text(event_start),
            "coverage_end": _utc_text(event_end),
            "source_segments": source_rows,
            "source_aggregate_sha256": _stable_hash(source_rows),
            "trade_count": metrics["trade_count"],
            "unique_trade_count": len({row["trade_id"] for row in trades}),
            "duplicate_trade_count": 0,
            "joined_trade_count": metrics["joined_trade_count"],
            "joined_coverage_pct": metrics["joined_coverage_pct"],
            "cost_complete_trade_count": metrics["cost_complete_trade_count"],
            "cost_sample_completeness_pct": metrics["cost_sample_completeness_pct"],
            "receive_lag_p99_ms": metrics["receive_lag_p99_ms"],
            "trade_book_alignment_p99_ms": metrics["trade_book_alignment_p99_ms"],
            "taker_fee_bps": float(taker_fee_bps),
            "fee_model": "explicit_conservative_public_research_assumption",
            "ordered_l2": {
                key: l2_attestation.get(key)
                for key in (
                    "sequence_gap_count", "duplicate_sequence_count", "out_of_order_sequence_count",
                    "unrecovered_gap_count", "snapshot_count", "update_count", "reconnect_count",
                    "resync_snapshot_count", "two_sided_coverage_pct", "max_clock_offset_ms",
                )
            },
            "l2_export_report_status": l2_report.get("status"),
            "readiness": {
                "quality_checked": True,
                "research_ready": False,
                "backtest_ready": False,
                "promotion_evidence_ready": False,
            },
            "guardrails": {
                "raw_frames_preserved": True,
                "future_book_join_used": False,
                "network_collection_used": False,
                "promotion_unlock_allowed": False,
                "paper_or_live_unlock_allowed": False,
                "private_endpoint_used": False,
                "order_endpoint_used": False,
                "broker_call_used": False,
                "real_order_submitted": False,
                "transfer_or_withdraw_used": False,
            },
        }
        _write_json(staging / ATTESTATION_NAME, attestation)
        files: list[dict[str, Any]] = []
        for path in sorted(staging.rglob("*"), key=lambda value: value.as_posix()):
            if path.is_file() and path.name != ATTESTATION_NAME:
                files.append({"path": path.relative_to(staging).as_posix(), "sha256": _sha256_file(path), "bytes": path.stat().st_size})
        attestation["files"] = files
        attestation["aggregate_payload_sha256"] = aggregate_inventory_hash(files)
        _write_json(staging / ATTESTATION_NAME, attestation)
        os.replace(staging, destination)
    except L2ExportBlocked as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise MicrostructureExportBlocked(exc.blockers) from exc
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
    return {
        "status": "quality_checked",
        "decision": "immutable_10s_microstructure_feed_ready_for_publication_review",
        "dataset_id": DATASET_ID,
        "dataset_version": dataset_version,
        "output_dir": str(destination),
        "attestation_path": str(destination / ATTESTATION_NAME),
        "coverage_start": attestation["coverage_start"],
        "coverage_end": attestation["coverage_end"],
        "trade_count": attestation["trade_count"],
        "joined_coverage_pct": attestation["joined_coverage_pct"],
        "readiness": attestation["readiness"],
        "guardrails": attestation["guardrails"],
    }


__all__ = [
    "ATTESTATION_NAME",
    "DATASET_ID",
    "EXACT_CHANNELS",
    "MicrostructureExportBlocked",
    "MicrostructureSegmentSource",
    "export_immutable_okx_10s_microstructure",
]
