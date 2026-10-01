from __future__ import annotations

import csv
import bisect
import hashlib
import json
import math
import os
import subprocess
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.agent_governance.shared_data import (
    load_manifest_from_git,
    resolve_manifest_payload,
)


REPORT_SCHEMA_VERSION = "btc_10s_microstructure_data_contract_report_v1"
LOCK_SCHEMA_VERSION = "btc_10s_microstructure_data_contract_lock_v1"
ARTIFACT_MANIFEST_SCHEMA_VERSION = "btc_10s_microstructure_data_contract_artifact_manifest_v1"
HORIZONS = ("10s", "30s", "60s")
FAMILIES = (
    "trade_imbalance_continuation",
    "micro_breakout",
    "sweep_absorption_reversal",
    "liquidation_cascade_recovery",
    "maker_queue",
)


class ContractError(ValueError):
    pass


def _stable_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ContractError(f"json_object_required:{path.name}")
    return payload


def _git_blob(repo_root: Path, git_spec: str) -> bytes:
    return subprocess.run(
        ["git", "show", git_spec],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return None
    index = max(0, min(len(finite) - 1, math.ceil(percentile * len(finite)) - 1))
    return round(finite[index], 6)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _public_source(binding: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in binding.items() if not key.startswith("_")}


def resolve_source(
    *,
    repo_root: Path,
    shared_root: Path,
    manifest_git_spec: str,
    manifest_loader: Callable[..., Mapping[str, Any]] = load_manifest_from_git,
    manifest_resolver: Callable[..., Path] = resolve_manifest_payload,
    blob_reader: Callable[[Path, str], bytes] = _git_blob,
) -> dict[str, Any]:
    """Resolve one exact Git manifest and verify every immutable file.

    There is deliberately no SQLite, latest, staging, glob, or repo-artifact
    argument. A missing physical version is evidence, not a discovery request.
    """

    manifest_blob = blob_reader(repo_root, manifest_git_spec)
    manifest = dict(manifest_loader(repo_root, manifest_git_spec))
    binding: dict[str, Any] = {
        "manifest_git_spec": manifest_git_spec,
        "manifest_blob_sha256": _sha256_bytes(manifest_blob),
        "dataset_id": str(manifest.get("dataset_id", "")),
        "dataset_version": str(manifest.get("dataset_version", "")),
        "aggregate_sha256": str(manifest.get("aggregate_sha256", "")),
        "file_count": int(manifest.get("file_count", len(manifest.get("files", [])))),
        "total_bytes": int(manifest.get("total_bytes", 0)),
        "coverage": dict(manifest.get("coverage", {})),
        "resolution_status": "blocked",
        "physical_path": None,
        "full_file_hash_verified": False,
        "fallback_used": False,
        "blockers": [],
        "_manifest": manifest,
    }
    try:
        resolved = manifest_resolver(
            manifest,
            shared_root=shared_root,
            verify_files=True,
        )
    except Exception as exc:  # resolver normalizes concrete storage errors
        message = str(exc)
        if "physical_version_missing" in message:
            binding["resolution_status"] = "physical_version_missing"
            binding["blockers"] = ["physical_version_missing"]
        else:
            binding["resolution_status"] = "hash_or_manifest_verification_failed"
            binding["blockers"] = ["immutable_manifest_or_file_hash_verification_failed"]
        return binding
    binding["resolution_status"] = "resolved_verified"
    binding["full_file_hash_verified"] = True
    binding["_resolved_root"] = Path(resolved)
    return binding


def _inspect_rest_aligned(root: Path) -> dict[str, Any]:
    base = root / "rest/btc_okx_swap_btcusdt_20260727T075929750Z"
    trade_path = base / "agg_trades_aligned.csv"
    book_path = base / "order_book_depth_aligned.csv"
    alignment = _read_json(base / "l2_alignment_manifest.json")
    trade_rows = list(csv.DictReader(trade_path.open("r", encoding="utf-8", newline="")))
    book_rows = list(csv.DictReader(book_path.open("r", encoding="utf-8", newline="")))
    trade_ids = [row.get("trade_id", "") for row in trade_rows]
    unique_trade_ids = {value for value in trade_ids if value}
    capture_sequences = {row.get("capture_sequence", "") for row in book_rows}
    crossed = sum(
        1
        for row in book_rows
        if float(row.get("best_bid", 0) or 0) >= float(row.get("best_ask", 0) or 0)
    )
    one_sided = sum(
        1
        for row in book_rows
        if float(row.get("best_bid", 0) or 0) <= 0 or float(row.get("best_ask", 0) or 0) <= 0
    )
    lags: list[float] = []
    negative_lags = 0
    for row in trade_rows + book_rows:
        try:
            lag = (_parse_time(row["local_receive_ts"]) - _parse_time(row["exchange_ts"])).total_seconds() * 1000
        except (KeyError, TypeError, ValueError):
            continue
        if lag < 0:
            negative_lags += 1
        else:
            lags.append(lag)
    start = _parse_time(str(alignment["capture_start"]))
    end = _parse_time(str(alignment["capture_end"]))
    return {
        "source_kind": "rest_aligned_repeated_snapshots",
        "capture_span_seconds": round((end - start).total_seconds(), 6),
        "trade_rows": len(trade_rows),
        "unique_trade_ids": len(unique_trade_ids),
        "duplicate_trade_id_rows": len(trade_ids) - len(unique_trade_ids),
        "aggressor_side_rows": sum(row.get("side") in {"buy", "sell"} for row in trade_rows),
        "book_level_rows": len(book_rows),
        "book_snapshot_count": len(capture_sequences),
        "two_sided_bbo_rows": len(book_rows) - one_sided,
        "crossed_book_rows": crossed,
        "one_sided_book_rows": one_sided,
        "negative_receive_lag_rows": negative_lags,
        "receive_lag_p99_ms": _percentile(lags, 0.99),
        "exchange_sequence_available": False,
        "ordered_l2_updates": False,
        "trade_bbo_joined": True,
        "trade_ordered_l2_joined": False,
        "visible_depth_is_queue_position": False,
        "message_count": None,
    }


def _inspect_ws_zero(root: Path) -> dict[str, Any]:
    quality = _read_json(root / "quality/btc_okx_public_ws_l2_funding_quality_report.json")
    raw = root / "raw_ws/segment-01/okx_public_ws_l2_raw_messages.jsonl"
    return {
        "source_kind": "public_ws_capture_attempt",
        "message_count": int(quality.get("message_count", 0)),
        "raw_message_bytes": raw.stat().st_size,
        "trade_rows": 0,
        "book_snapshot_count": 0,
        "ordered_l2_updates": False,
        "trade_bbo_joined": False,
        "trade_ordered_l2_joined": False,
    }


def _inspect_real_l2(root: Path) -> dict[str, Any]:
    attestation = _read_json(root / "immutable-export/btc_okx_l2_dataready_attestation.json")
    payload = root / "immutable-export/venue=okx/instrument_id=BTC-USDT-SWAP/date=2026-07-28/part-00000.jsonl"
    rows: list[dict[str, Any]] = []
    with payload.open("r", encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    lags: list[float] = []
    crossed = 0
    one_sided = 0
    for row in rows:
        bids = row.get("bids", [])
        asks = row.get("asks", [])
        if not bids or not asks:
            one_sided += 1
        if bids and asks and float(bids[0][0]) >= float(asks[0][0]):
            crossed += 1
        try:
            lags.append((_parse_time(row["available_time"]) - _parse_time(row["event_time"])).total_seconds() * 1000)
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "source_kind": "ordered_public_ws_l2_short_fragment",
        "capture_span_seconds": float(attestation.get("source_segments", [{}])[0].get("capture_duration_seconds", 0)),
        "message_count": len(rows),
        "trade_rows": 0,
        "book_snapshot_count": int(attestation.get("snapshot_count", 0)),
        "book_update_count": int(attestation.get("update_count", 0)),
        "two_sided_coverage_pct": float(attestation.get("two_sided_coverage_pct", 0)),
        "crossed_book_rows": crossed,
        "one_sided_book_rows": one_sided,
        "duplicate_sequence_count": int(attestation.get("duplicate_sequence_count", 0)),
        "out_of_order_sequence_count": int(attestation.get("out_of_order_sequence_count", 0)),
        "unrecovered_sequence_gap_count": int(attestation.get("unrecovered_gap_count", 0)),
        "reconnect_count": int(attestation.get("reconnect_count", 0)),
        "resync_snapshot_count": int(attestation.get("resync_snapshot_count", 0)),
        "receive_lag_p99_ms": _percentile(lags, 0.99),
        "ordered_l2_updates": True,
        "recovery_events": True,
        "trade_bbo_joined": False,
        "trade_ordered_l2_joined": False,
    }


def _lag1_ess(values: Sequence[float]) -> float:
    count = len(values)
    if count <= 1:
        return float(count)
    mean = sum(values) / count
    denominator = sum((value - mean) ** 2 for value in values)
    if denominator <= 0:
        return float(count)
    numerator = sum(
        (left - mean) * (right - mean)
        for left, right in zip(values, values[1:], strict=False)
    )
    rho = max(-0.99, min(0.99, numerator / denominator))
    return round(max(1.0, min(float(count), count * (1.0 - rho) / (1.0 + rho))), 6)


def _tercile(value: float, values: Sequence[float]) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    low = ordered[max(0, math.ceil(len(ordered) / 3) - 1)]
    high = ordered[max(0, math.ceil(2 * len(ordered) / 3) - 1)]
    return 0 if value <= low else (1 if value <= high else 2)


def _segment_ess(rows: Sequence[Mapping[str, Any]]) -> float:
    by_segment: dict[str, list[float]] = {}
    for row in rows:
        by_segment.setdefault(str(row["segment_id"]), []).append(
            float(row["cost_adjusted_return"])
        )
    return round(sum(_lag1_ess(values) for values in by_segment.values()), 6)


def _feed_windows(rows: Sequence[Mapping[str, Any]], seconds: int) -> dict[str, Any]:
    joined = sorted(
        rows,
        key=lambda row: (
            _parse_time(str(row["event_time"])),
            int(row.get("capture_sequence", 0)),
        ),
    )
    if len(joined) < 2:
        return {"potential": 0, "windows": []}
    times = [_parse_time(str(row["event_time"])).timestamp() for row in joined]
    epochs = [str(row.get("connection_sequence", 0)) for row in joined]
    epoch_starts: dict[str, float] = {}
    epoch_order: list[str] = []
    for timestamp, epoch in zip(times, epochs, strict=True):
        if epoch not in epoch_starts:
            epoch_starts[epoch] = timestamp
            epoch_order.append(epoch)
    next_reconnect: dict[str, float] = {
        epoch: epoch_starts[epoch_order[index + 1]]
        for index, epoch in enumerate(epoch_order[:-1])
    }
    anchor = times[0]
    end = times[-1]
    windows: list[dict[str, Any]] = []
    potential = 0
    while anchor + seconds <= end:
        left_index = bisect.bisect_left(times, anchor)
        right_index = bisect.bisect_left(times, anchor + seconds)
        if left_index < len(joined) and right_index < len(joined):
            left, right = joined[left_index], joined[right_index]
            epoch = epochs[left_index]
            right_epoch = epochs[right_index]
            reconnect_at = next_reconnect.get(epoch)
            eligible = (
                epoch == right_epoch
                and times[left_index] >= epoch_starts[epoch] + 60.0
                and (
                    reconnect_at is None
                    or times[right_index] <= reconnect_at - 60.0
                )
            )
            if eligible:
                potential += 1
            complete = eligible and all(
                row.get(field) is not None
                for row in (left, right)
                for field in ("estimated_one_way_cost_bps", "mid")
            ) and bool(left.get("book_joined")) and bool(right.get("book_joined"))
            if complete:
                raw_return = math.log(float(right["mid"]) / float(left["mid"]))
                cost = (
                    float(left["estimated_one_way_cost_bps"])
                    + float(right["estimated_one_way_cost_bps"])
                ) / 10_000.0
                trailing_start = times[left_index] - 60.0
                trailing_prices = [
                    float(joined[index]["mid"])
                    for index in range(left_index + 1)
                    if epochs[index] == epoch
                    and times[index] >= trailing_start
                    and joined[index].get("mid") is not None
                ]
                log_returns = [
                    math.log(right_price / left_price)
                    for left_price, right_price in zip(
                        trailing_prices,
                        trailing_prices[1:],
                        strict=False,
                    )
                ]
                windows.append(
                    {
                        "start": _parse_time(str(left["event_time"])),
                        "connection_sequence": epoch,
                        "segment_id": epoch,
                        "cost_adjusted_return": raw_return - cost,
                        "decision_volatility": math.sqrt(
                            sum(value * value for value in log_returns)
                        ),
                        "decision_liquidity_cost_bps": float(
                            left["estimated_one_way_cost_bps"]
                        ),
                    }
                )
        anchor += seconds
    return {"potential": potential, "windows": windows}


def _pooled_regime_metrics(
    observations: Sequence[Mapping[str, Any]],
) -> tuple[list[float], bool]:
    volatility = [float(row["decision_volatility"]) for row in observations]
    liquidity = [float(row["decision_liquidity_cost_bps"]) for row in observations]
    cells: list[list[Mapping[str, Any]]] = [[] for _ in range(9)]
    for row in observations:
        cell = _tercile(float(row["decision_volatility"]), volatility) * 3 + _tercile(
            float(row["decision_liquidity_cost_bps"]), liquidity
        )
        cells[cell].append(row)
    return [
        _segment_ess(cell) if cell else 0.0
        for cell in cells
    ], all(bool(cell) for cell in cells)


def _inspect_microstructure_feed(
    root: Path,
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    attestation = _read_json(
        root / "immutable_export/btc_okx_10s_microstructure_immutable_feed_attestation.json"
    )
    paths = [
        root / str(item["path"])
        for item in manifest.get("files", [])
        if str(item.get("path", "")).startswith("immutable_export/normalized-trades/")
        and str(item.get("path", "")).endswith(".jsonl")
    ]
    rows: list[dict[str, Any]] = []
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    rows.sort(key=lambda row: (_parse_time(str(row["event_time"])), int(row["capture_sequence"])))
    book_paths = [
        root / str(item["path"])
        for item in manifest.get("files", [])
        if str(item.get("path", "")).startswith(
            "immutable_export/ordered-l2/"
        )
        and str(item.get("path", "")).endswith(".jsonl")
    ]
    book_row_count = 0
    crossed_book_count = 0
    one_sided_book_count = 0
    for path in book_paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                book = json.loads(line)
                book_row_count += 1
                bid = book.get("best_bid")
                ask = book.get("best_ask")
                if bid is None or ask is None:
                    one_sided_book_count += 1
                elif float(bid) >= float(ask):
                    crossed_book_count += 1
    window_results = {
        horizon: _feed_windows(rows, seconds)
        for horizon, seconds in (("10s", 10), ("30s", 30), ("60s", 60))
    }
    coverage_start = _parse_time(str(attestation["coverage_start"]))
    coverage_end = _parse_time(str(attestation["coverage_end"]))
    span = max(0.0, (coverage_end - coverage_start).total_seconds())
    information: dict[str, dict[str, Any]] = {}
    dataset_version = str(attestation.get("dataset_version") or attestation["coverage_start"])
    for horizon, _seconds in (("10s", 10), ("30s", 30), ("60s", 60)):
        horizon_windows = window_results[horizon]["windows"]
        potential = int(window_results[horizon]["potential"])
        for row in horizon_windows:
            row["segment_id"] = f"{dataset_version}:{row['segment_id']}"
        labels = [float(row["cost_adjusted_return"]) for row in horizon_windows]
        information[horizon] = {
            "potential_non_overlap_windows": potential,
            "eligible_labeled_windows": len(labels),
            "autocorrelation_adjusted_ess": _segment_ess(horizon_windows),
            "joined_coverage_pct": float(attestation.get("joined_coverage_pct", 0)),
            "future_label_availability_pct": round(100.0 * len(labels) / potential, 9) if potential else 0.0,
        }
    sixty = window_results["60s"]["windows"]
    buckets = [0] * 6
    weekdays = [0] * 7
    for row in sixty:
        start = row["start"]
        buckets[start.hour // 4] += 1
        weekdays[start.weekday()] += 1
    regime_cell_ess, regime_complete = _pooled_regime_metrics(sixty)
    ordered_l2 = dict(attestation.get("ordered_l2", {}))
    receive_lag = attestation.get("receive_lag_p99_ms")
    alignment = attestation.get("trade_book_alignment_p99_ms")
    trade_count = len(rows)
    contract_metrics = {
        "raw_counts": {
            "trade_rows": trade_count,
            "unique_trade_ids": len({str(row.get("trade_id", "")) for row in rows}),
            "duplicate_trade_id_rows": int(attestation.get("duplicate_trade_count", 0)),
            "ordered_l2_message_count": int(ordered_l2.get("snapshot_count", 0)) + int(ordered_l2.get("update_count", 0)),
            "ordered_l2_snapshot_count": int(ordered_l2.get("snapshot_count", 0)),
            "ordered_l2_update_count": int(ordered_l2.get("update_count", 0)),
        },
        "information_by_horizon": information,
        "utc_4h_bucket_independent_60s_windows": buckets,
        "weekday_independent_60s_windows": weekdays,
        "regime_cell_ess": regime_cell_ess,
        "_internal_regime_observations": [
            {key: value for key, value in row.items() if key != "start"}
            for row in sixty
        ],
        "quality": {
            "duplicate_count": int(attestation.get("duplicate_trade_count", 0)) + int(ordered_l2.get("duplicate_sequence_count", 0)),
            "out_of_order_count": int(ordered_l2.get("out_of_order_sequence_count", 0)),
            "unrecovered_sequence_gap_count": int(ordered_l2.get("unrecovered_gap_count", 0)),
            "crossed_book_count": crossed_book_count,
            "one_sided_book_count": one_sided_book_count,
            "reconnect_snapshot_reset_verified": int(ordered_l2.get("reconnect_count", 0)) == int(ordered_l2.get("resync_snapshot_count", -1)),
            "gap_resync_embargo_seconds": 60,
            "receive_lag_p99_ms": receive_lag,
            "trade_book_alignment_p99_ms": alignment,
        },
        "coverage": {
            "max_verified_capture_span_seconds": span,
            "ordered_l2_two_sided_coverage_pct": round(
                100.0 * (book_row_count - one_sided_book_count) / book_row_count,
                9,
            )
            if book_row_count
            else 0.0,
            "utc_hour_coverage_complete": all(value > 0 for value in buckets),
            "weekday_coverage_complete": all(value > 0 for value in weekdays),
            "volatility_liquidity_regime_coverage_complete": regime_complete,
        },
        "cost": {
            "sample_completeness_pct": float(attestation.get("cost_sample_completeness_pct", 0)),
            "spread_available": all(row.get("spread_bps") is not None for row in rows) if rows else False,
            "fee_available": all(row.get("taker_fee_bps") is not None for row in rows) if rows else False,
            "depth_impact_available": all(row.get("depth_impact_bps") is not None for row in rows) if rows else False,
            "stratified_stability_verified": regime_complete,
        },
        "reference_data": {
            "mark_price_present_but_not_10s_aligned": False,
            "index_price_10s_aligned": False,
            "funding_present_but_not_10s_aligned": False,
            "time_aligned_open_interest": False,
            "liquidation_events": False,
        },
        "fields": {
            "unique_tick_trade_ids": trade_count > 0 and int(attestation.get("duplicate_trade_count", -1)) == 0,
            "exchange_timestamps": trade_count > 0,
            "aggressor_side": trade_count > 0 and all(row.get("aggressor_side") in {"buy", "sell"} for row in rows),
            "two_sided_bbo": trade_count > 0 and all(row.get("best_bid") and row.get("best_ask") for row in rows),
            "l2_price_levels": int(ordered_l2.get("snapshot_count", 0)) > 0,
            "ordered_l2_updates": int(ordered_l2.get("update_count", 0)) > 0,
            "volume_depth_shock": trade_count > 0 and all(row.get("depth_impact_bps") is not None for row in rows),
            "recovery_events": int(ordered_l2.get("reconnect_count", 0)) == int(ordered_l2.get("resync_snapshot_count", -1)),
            "trade_bbo_joined": float(attestation.get("joined_coverage_pct", 0)) > 0,
            "trade_ordered_l2_joined": attestation.get("same_connection_trade_ordered_l2") is True and float(attestation.get("joined_coverage_pct", 0)) > 0,
            "time_aligned_open_interest": False,
            "liquidation_events": False,
        },
    }
    return {
        "source_kind": "immutable_same_connection_trades_ordered_l2",
        "capture_span_seconds": span,
        "coverage_start": attestation["coverage_start"],
        "coverage_end": attestation["coverage_end"],
        "trade_rows": trade_count,
        "trade_ordered_l2_joined": contract_metrics["fields"]["trade_ordered_l2_joined"],
        "contract_metrics": contract_metrics,
    }


def _combine_feed_contract_metrics(
    feeds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(feeds, key=lambda row: _parse_time(str(row["coverage_start"])))
    selected: list[Mapping[str, Any]] = []
    overlap_count = 0
    last_end: datetime | None = None
    for feed in ordered:
        start = _parse_time(str(feed["coverage_start"]))
        end = _parse_time(str(feed["coverage_end"]))
        if last_end is not None and start <= last_end:
            overlap_count += 1
            continue
        selected.append(feed)
        last_end = end
    metrics = [dict(feed["contract_metrics"]) for feed in selected]
    if not metrics:
        return {}
    first = json.loads(json.dumps(metrics[0]))
    if len(metrics) == 1 and overlap_count == 0:
        return first
    raw_keys = set().union(*(metric["raw_counts"].keys() for metric in metrics))
    first["raw_counts"] = {
        key: sum(int(metric["raw_counts"].get(key, 0)) for metric in metrics)
        for key in raw_keys
    }
    total_trades = max(1, int(first["raw_counts"].get("trade_rows", 0)))
    for horizon in HORIZONS:
        rows = [metric["information_by_horizon"][horizon] for metric in metrics]
        eligible = sum(int(row["eligible_labeled_windows"]) for row in rows)
        potential = sum(int(row.get("potential_non_overlap_windows", 0)) for row in rows)
        first["information_by_horizon"][horizon] = {
            "potential_non_overlap_windows": potential,
            "eligible_labeled_windows": eligible,
            "autocorrelation_adjusted_ess": round(
                min(
                    float(eligible),
                    sum(float(row["autocorrelation_adjusted_ess"]) for row in rows),
                ),
                6,
            ),
            "joined_coverage_pct": round(
                sum(
                    float(row["joined_coverage_pct"])
                    * int(metric["raw_counts"].get("trade_rows", 0))
                    for row, metric in zip(rows, metrics, strict=True)
                )
                / total_trades,
                9,
            ),
            "future_label_availability_pct": round(
                100.0 * eligible / potential, 9
            )
            if potential
            else 0.0,
        }
    first["utc_4h_bucket_independent_60s_windows"] = [
        sum(int(metric["utc_4h_bucket_independent_60s_windows"][index]) for metric in metrics)
        for index in range(6)
    ]
    first["weekday_independent_60s_windows"] = [
        sum(int(metric["weekday_independent_60s_windows"][index]) for metric in metrics)
        for index in range(7)
    ]
    pooled_observations = [
        observation
        for metric in metrics
        for observation in metric.get("_internal_regime_observations", [])
    ]
    regime_cell_ess, regime_complete = _pooled_regime_metrics(pooled_observations)
    first["regime_cell_ess"] = regime_cell_ess
    first["_internal_regime_observations"] = pooled_observations
    for key in (
        "duplicate_count",
        "out_of_order_count",
        "unrecovered_sequence_gap_count",
        "crossed_book_count",
        "one_sided_book_count",
    ):
        first["quality"][key] = sum(int(metric["quality"].get(key, 0)) for metric in metrics)
    first["quality"]["duplicate_count"] += overlap_count
    first["quality"]["reconnect_snapshot_reset_verified"] = all(
        metric["quality"].get("reconnect_snapshot_reset_verified") is True
        for metric in metrics
    )
    first["quality"]["gap_resync_embargo_seconds"] = min(
        int(metric["quality"].get("gap_resync_embargo_seconds", 0))
        for metric in metrics
    )
    for key in ("receive_lag_p99_ms", "trade_book_alignment_p99_ms"):
        values = [metric["quality"].get(key) for metric in metrics]
        first["quality"][key] = (
            max(float(value) for value in values if value is not None)
            if any(value is not None for value in values)
            else None
        )
    first["coverage"]["max_verified_capture_span_seconds"] = sum(
        float(feed.get("capture_span_seconds", 0)) for feed in selected
    )
    first["coverage"]["utc_hour_coverage_complete"] = all(
        value > 0 for value in first["utc_4h_bucket_independent_60s_windows"]
    )
    first["coverage"]["weekday_coverage_complete"] = all(
        value > 0 for value in first["weekday_independent_60s_windows"]
    )
    first["coverage"]["volatility_liquidity_regime_coverage_complete"] = regime_complete
    first["coverage"]["ordered_l2_two_sided_coverage_pct"] = min(
        float(metric["coverage"].get("ordered_l2_two_sided_coverage_pct", 0))
        for metric in metrics
    )
    first["cost"]["sample_completeness_pct"] = round(
        sum(
            float(metric["cost"].get("sample_completeness_pct", 0))
            * int(metric["raw_counts"].get("trade_rows", 0))
            for metric in metrics
        )
        / total_trades,
        9,
    )
    for key in ("spread_available", "fee_available", "depth_impact_available"):
        first["cost"][key] = all(metric["cost"].get(key) is True for metric in metrics)
    first["cost"]["stratified_stability_verified"] = regime_complete and all(
        metric["cost"].get("spread_available") is True
        and metric["cost"].get("fee_available") is True
        and metric["cost"].get("depth_impact_available") is True
        for metric in metrics
    )
    for key in first["fields"]:
        first["fields"][key] = all(metric["fields"].get(key) is True for metric in metrics)
    return first


def inspect_resolved_source(binding: Mapping[str, Any]) -> dict[str, Any]:
    result = _public_source(binding)
    root = binding.get("_resolved_root")
    if not isinstance(root, Path):
        result["measured"] = {}
        return result
    dataset_id = str(binding.get("dataset_id", ""))
    try:
        if dataset_id == "btc-okx-v3-immutable-public-market-evidence":
            measured = _inspect_rest_aligned(root)
        elif dataset_id == "btc-okx-public-ws-l2-funding-evidence":
            measured = _inspect_ws_zero(root)
        elif dataset_id == "btc-okx-real-l2-attestation":
            measured = _inspect_real_l2(root)
        elif dataset_id == "btc-okx-10s-microstructure-immutable-feed":
            measured = _inspect_microstructure_feed(
                root,
                dict(binding.get("_manifest", {})),
            )
        else:
            measured = {"source_kind": "verified_immutable_unparsed"}
    except (OSError, ValueError, KeyError, json.JSONDecodeError, csv.Error) as exc:
        result["resolution_status"] = "verified_payload_semantic_parse_failed"
        result["blockers"] = ["verified_payload_semantic_parse_failed"]
        measured = {"parse_error_type": type(exc).__name__}
    result["measured"] = measured
    return result


def derive_measured_metrics(source_evaluations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    measured = [dict(source.get("measured", {})) for source in source_evaluations]
    feeds = [
        row
        for row in measured
        if row.get("source_kind")
        == "immutable_same_connection_trades_ordered_l2"
        and isinstance(row.get("contract_metrics"), Mapping)
    ]
    if feeds:
        return _combine_feed_contract_metrics(feeds)
    rest = next((row for row in measured if row.get("source_kind") == "rest_aligned_repeated_snapshots"), {})
    real_l2 = next((row for row in measured if row.get("source_kind") == "ordered_public_ws_l2_short_fragment"), {})
    ws_zero = next((row for row in measured if row.get("source_kind") == "public_ws_capture_attempt"), {})
    raw_span = max(float(row.get("capture_span_seconds", 0) or 0) for row in measured) if measured else 0.0
    potential = {
        horizon: max(0, int(raw_span // seconds) - 1)
        for horizon, seconds in (("10s", 10), ("30s", 30), ("60s", 60))
    }
    information = {
        horizon: {
            "potential_non_overlap_windows": potential[horizon],
            "eligible_labeled_windows": 0,
            "autocorrelation_adjusted_ess": 0.0,
            "joined_coverage_pct": 0.0,
            "future_label_availability_pct": 0.0,
        }
        for horizon in HORIZONS
    }
    return {
        "raw_counts": {
            "trade_rows": int(rest.get("trade_rows", 0)),
            "unique_trade_ids": int(rest.get("unique_trade_ids", 0)),
            "duplicate_trade_id_rows": int(rest.get("duplicate_trade_id_rows", 0)),
            "rest_book_level_rows": int(rest.get("book_level_rows", 0)),
            "rest_book_snapshot_count": int(rest.get("book_snapshot_count", 0)),
            "ordered_l2_message_count": int(real_l2.get("message_count", 0)),
            "ordered_l2_snapshot_count": int(real_l2.get("book_snapshot_count", 0)),
            "ordered_l2_update_count": int(real_l2.get("book_update_count", 0)),
            "zero_message_ws_capture_count": int(ws_zero.get("message_count", 0)),
        },
        "information_by_horizon": information,
        "utc_4h_bucket_independent_60s_windows": [0, 0, 0, 0, 0, 0],
        "weekday_independent_60s_windows": [0, 0, 0, 0, 0, 0, 0],
        "regime_cell_ess": [0.0] * 9,
        "quality": {
            "duplicate_count": int(rest.get("duplicate_trade_id_rows", 0)),
            "out_of_order_count": int(real_l2.get("out_of_order_sequence_count", 0)),
            "unrecovered_sequence_gap_count": int(real_l2.get("unrecovered_sequence_gap_count", 0)),
            "crossed_book_count": int(rest.get("crossed_book_rows", 0)) + int(real_l2.get("crossed_book_rows", 0)),
            "one_sided_book_count": int(rest.get("one_sided_book_rows", 0)) + int(real_l2.get("one_sided_book_rows", 0)),
            "reconnect_snapshot_reset_verified": bool(real_l2.get("reconnect_count", 0)) and int(real_l2.get("reconnect_count", 0)) == int(real_l2.get("resync_snapshot_count", -1)),
            "gap_resync_embargo_seconds": 0,
            "receive_lag_p99_ms": real_l2.get("receive_lag_p99_ms"),
            "trade_book_alignment_p99_ms": None,
            "rest_negative_receive_lag_rows": int(rest.get("negative_receive_lag_rows", 0)),
        },
        "coverage": {
            "max_verified_capture_span_seconds": raw_span,
            "ordered_l2_two_sided_coverage_pct": float(real_l2.get("two_sided_coverage_pct", 0) or 0),
            "utc_hour_coverage_complete": False,
            "weekday_coverage_complete": False,
            "volatility_liquidity_regime_coverage_complete": False,
        },
        "cost": {
            "sample_completeness_pct": 0.0,
            "spread_available": bool(rest.get("book_level_rows", 0)),
            "fee_available": False,
            "depth_impact_available": bool(rest.get("book_level_rows", 0)),
            "stratified_stability_verified": False,
        },
        "reference_data": {
            "mark_price_present_but_not_10s_aligned": True,
            "index_price_10s_aligned": False,
            "funding_present_but_not_10s_aligned": True,
            "time_aligned_open_interest": False,
            "liquidation_events": False,
        },
        "fields": {
            "unique_tick_trade_ids": bool(rest.get("unique_trade_ids", 0)),
            "exchange_timestamps": bool(rest.get("trade_rows", 0)),
            "aggressor_side": int(rest.get("aggressor_side_rows", 0)) == int(rest.get("trade_rows", -1)),
            "two_sided_bbo": bool(rest.get("book_level_rows", 0)),
            "l2_price_levels": bool(real_l2.get("message_count", 0)),
            "ordered_l2_updates": bool(real_l2.get("ordered_l2_updates", False)),
            "volume_depth_shock": bool(rest.get("book_level_rows", 0)),
            "recovery_events": bool(real_l2.get("recovery_events", False)),
            "trade_bbo_joined": bool(rest.get("trade_bbo_joined", False)),
            "trade_ordered_l2_joined": False,
            "time_aligned_open_interest": False,
            "liquidation_events": False,
        },
    }


def _information_blockers(prereg: Mapping[str, Any], metrics: Mapping[str, Any], horizon: str) -> list[str]:
    thresholds = prereg["information_thresholds"]
    measured = metrics["information_by_horizon"][horizon]
    blockers: list[str] = []
    if int(measured.get("eligible_labeled_windows", 0)) < int(thresholds["eligible_labeled_windows_by_horizon"][horizon]):
        blockers.append("eligible_labeled_windows_below_required")
    if float(measured.get("autocorrelation_adjusted_ess", 0)) < float(thresholds["autocorrelation_adjusted_ess_by_horizon"][horizon]):
        blockers.append("autocorrelation_adjusted_ess_below_required")
    if float(measured.get("joined_coverage_pct", 0)) < float(thresholds["joined_coverage_pct"]):
        blockers.append("joined_coverage_below_required")
    if float(measured.get("future_label_availability_pct", 0)) < float(thresholds["future_label_availability_pct"]):
        blockers.append("future_label_availability_below_required")
    buckets = metrics.get("utc_4h_bucket_independent_60s_windows", [])
    if len(buckets) != int(thresholds["utc_4h_bucket_count"]) or any(int(value) < int(thresholds["min_independent_60s_windows_per_utc_4h_bucket"]) for value in buckets):
        blockers.append("utc_4h_bucket_information_below_required")
    regimes = metrics.get("regime_cell_ess", [])
    required_cells = math.prod(thresholds["volatility_liquidity_regime_grid"])
    if len(regimes) != required_cells or any(float(value) < float(thresholds["min_ess_per_applicable_regime_cell"]) for value in regimes):
        blockers.append("volatility_liquidity_regime_ess_below_required")
    return blockers


def _quality_blockers(prereg: Mapping[str, Any], metrics: Mapping[str, Any]) -> list[str]:
    thresholds = prereg["information_thresholds"]
    quality = metrics["quality"]
    blockers: list[str] = []
    for key in ("duplicate_count", "out_of_order_count", "unrecovered_sequence_gap_count", "crossed_book_count", "one_sided_book_count"):
        if int(quality.get(key, -1)) != int(thresholds[key]):
            blockers.append(f"{key}_not_zero")
    if quality.get("reconnect_snapshot_reset_verified") is not True:
        blockers.append("reconnect_snapshot_reset_unverified")
    if int(quality.get("gap_resync_embargo_seconds", 0)) < int(thresholds["gap_resync_embargo_seconds"]):
        blockers.append("gap_resync_embargo_below_required")
    receive_lag = quality.get("receive_lag_p99_ms")
    if receive_lag is None or float(receive_lag) > float(thresholds["receive_lag_p99_ms"]):
        blockers.append("receive_lag_p99_missing_or_above_required")
    alignment = quality.get("trade_book_alignment_p99_ms")
    if alignment is None or float(alignment) > float(thresholds["trade_book_alignment_p99_ms"]):
        blockers.append("trade_book_alignment_p99_missing_or_above_required")
    cost = metrics["cost"]
    if float(cost.get("sample_completeness_pct", 0)) < float(thresholds["cost_sample_completeness_pct"]):
        blockers.append("cost_sample_completeness_below_required")
    for key in ("spread_available", "fee_available", "depth_impact_available", "stratified_stability_verified"):
        if cost.get(key) is not True:
            blockers.append(f"cost_{key}_missing")
    return blockers


def evaluate_readiness(prereg: Mapping[str, Any], metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    requirements = prereg["family_requirements"]
    fields = metrics["fields"]
    rows: list[dict[str, Any]] = []
    for family in FAMILIES:
        for horizon in HORIZONS:
            if family == "maker_queue":
                rows.append({
                    "family": family,
                    "horizon": horizon,
                    "status": "not_applicable",
                    "execution_baseline": "taker_only",
                    "measured": dict(metrics["information_by_horizon"][horizon]),
                    "required": {
                        "scope": "out_of_scope",
                        "visible_depth_is_queue_position": False,
                    },
                    "capabilities": {"maker_queue": False},
                    "blockers": ["maker_queue_out_of_scope_taker_only_baseline"],
                })
                continue
            blockers = _information_blockers(prereg, metrics, horizon)
            blockers.extend(_quality_blockers(prereg, metrics))
            for field in requirements[family]:
                if fields.get(field) is not True:
                    blockers.append(f"{field}_missing")
            blockers = list(dict.fromkeys(blockers))
            if any(code in blockers for code in (
                "eligible_labeled_windows_below_required",
                "autocorrelation_adjusted_ess_below_required",
                "joined_coverage_below_required",
                "future_label_availability_below_required",
            )):
                blockers.insert(0, "blocked_insufficient_information")
            trade_imbalance = all(fields.get(key) is True for key in requirements["trade_imbalance_continuation"])
            ofi = trade_imbalance and all(fields.get(key) is True for key in requirements["order_flow_imbalance_capability"])
            rows.append({
                "family": family,
                "horizon": horizon,
                "status": "ready" if not blockers else "blocked",
                "execution_baseline": "taker_only",
                "measured": dict(metrics["information_by_horizon"][horizon]),
                "required": {
                    "eligible_labeled_windows": prereg["information_thresholds"]["eligible_labeled_windows_by_horizon"][horizon],
                    "autocorrelation_adjusted_ess": prereg["information_thresholds"]["autocorrelation_adjusted_ess_by_horizon"][horizon],
                    "fields": list(requirements[family]),
                },
                "capabilities": {
                    "trade_imbalance": trade_imbalance,
                    "order_flow_imbalance": ofi,
                },
                "blockers": blockers,
            })
    return rows


def build_contract_lock(
    *,
    prereg: Mapping[str, Any],
    source_head: str,
    source_evaluations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    lock: dict[str, Any] = {
        "schema_version": LOCK_SCHEMA_VERSION,
        "ticket_id": prereg["ticket_id"],
        "source_head": source_head,
        "prediction_target": prereg["prediction_target"],
        "execution_baseline": prereg["execution_baseline"],
        "prereg_semantic_sha256": _sha256_bytes(_stable_json(dict(prereg)).encode("utf-8")),
        "information_thresholds": dict(prereg["information_thresholds"]),
        "family_requirements": dict(prereg["family_requirements"]),
        "source_bindings": [
            {
                key: source.get(key)
                for key in (
                    "manifest_git_spec",
                    "manifest_blob_sha256",
                    "dataset_id",
                    "dataset_version",
                    "aggregate_sha256",
                    "resolution_status",
                    "full_file_hash_verified",
                    "fallback_used",
                )
            }
            for source in source_evaluations
        ],
        "holdout_or_model_results_read": False,
        "model_or_ga_run": False,
    }
    lock["semantic_sha256"] = _sha256_bytes(_stable_json(lock).encode("utf-8"))
    return lock


def _without_internal_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_internal_evidence(item)
            for key, item in value.items()
            if not str(key).startswith("_internal_")
        }
    if isinstance(value, list):
        return [_without_internal_evidence(item) for item in value]
    return value


def build_report(
    *,
    prereg: Mapping[str, Any],
    source_head: str,
    generated_at: str,
    source_evaluations: Sequence[Mapping[str, Any]],
    measured_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    matrix = evaluate_readiness(prereg, measured_metrics)
    verified_sources = sum(source.get("resolution_status") == "resolved_verified" for source in source_evaluations)
    ready = [row for row in matrix if row["status"] == "ready"]
    source_blockers = [
        f"{source.get('dataset_id') or 'unknown'}:{blocker}"
        for source in source_evaluations
        for blocker in source.get("blockers", [])
    ]
    blockers = list(dict.fromkeys([
        *(source_blockers or (["source_manifest_evidence_missing"] if not source_evaluations else [])),
        *([] if ready and verified_sources else ["blocked_insufficient_information"]),
        "promotion_execution_evidence_out_of_scope",
    ]))
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "ticket_id": prereg["ticket_id"],
        "source_head": source_head,
        "generated_at": generated_at,
        "decision": "research_admission_ready" if ready and verified_sources else "blocked_insufficient_information",
        "prediction_target": prereg["prediction_target"],
        "execution_baseline": "taker_only",
        "legacy_natural_day_gate_modified": False,
        "research_admission_uses_natural_days": False,
        "source_evaluations": _without_internal_evidence(list(source_evaluations)),
        "measured_metrics": _without_internal_evidence(dict(measured_metrics)),
        "readiness_matrix": matrix,
        "next_research_authorization": [
            {"family": row["family"], "horizon": row["horizon"]}
            for row in ready
        ],
        "blockers": blockers,
        "execution_evidence_blockers": [
            "venue_hosted_protective_stop_unproven",
            "mark_index_funding_runtime_parity_unproven",
            "queue_partial_fill_execution_unproven",
            "fill_position_cash_ledger_unproven",
            "adverse_selection_unproven",
            "current_head_promotion_artifact_missing",
        ],
        "guardrails": {
            "model_or_ga_run": False,
            "network_used": False,
            "mutable_fallback_used": False,
            "promotion_unlock_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "real_order_submitted": False,
            "transfer_or_withdraw_used": False,
        },
    }
    report["semantic_sha256"] = _sha256_bytes(_stable_json(report).encode("utf-8"))
    return report


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_immutable_artifact_bundle(
    *,
    report: Mapping[str, Any],
    lock: Mapping[str, Any],
    output: Path,
) -> dict[str, Any]:
    if output.exists():
        raise ContractError(f"artifact_output_already_exists:{output.name}")
    output.mkdir(parents=True, exist_ok=False)
    report_path = output / "btc_10s_microstructure_data_contract_report.json"
    lock_path = output / "btc_10s_microstructure_data_contract_lock.json"
    _write_json_atomic(report_path, report)
    _write_json_atomic(lock_path, lock)
    artifact_manifest: dict[str, Any] = {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "immutable_version": output.name,
        "files": [
            {"path": report_path.name, "sha256": _sha256_file(report_path), "bytes": report_path.stat().st_size},
            {"path": lock_path.name, "sha256": _sha256_file(lock_path), "bytes": lock_path.stat().st_size},
        ],
        "report_semantic_sha256": report["semantic_sha256"],
        "contract_lock_semantic_sha256": lock["semantic_sha256"],
        "guardrails": dict(report["guardrails"]),
    }
    artifact_manifest["aggregate_sha256"] = _sha256_bytes(_stable_json({"files": artifact_manifest["files"]}).encode("utf-8"))
    manifest_path = output / "artifact_manifest.json"
    _write_json_atomic(manifest_path, artifact_manifest)
    return {
        "status": "published_immutable_research_artifact",
        "immutable_version": output.name,
        "report_semantic_sha256": report["semantic_sha256"],
        "report_file_sha256": _sha256_file(report_path),
        "contract_lock_semantic_sha256": lock["semantic_sha256"],
        "contract_lock_file_sha256": _sha256_file(lock_path),
        "artifact_manifest_file_sha256": _sha256_file(manifest_path),
        "aggregate_sha256": artifact_manifest["aggregate_sha256"],
        "decision": report["decision"],
    }


def evaluate_manifest_specs(
    *,
    repo_root: Path,
    shared_root: Path,
    manifest_git_specs: Sequence[str],
) -> list[dict[str, Any]]:
    return [
        inspect_resolved_source(
            resolve_source(
                repo_root=repo_root,
                shared_root=shared_root,
                manifest_git_spec=spec,
            )
        )
        for spec in manifest_git_specs
    ]
