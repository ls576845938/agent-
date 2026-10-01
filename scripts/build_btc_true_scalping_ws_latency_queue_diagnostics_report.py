#!/usr/bin/env python3
"""Build public WS receive-latency and visible-queue proxy diagnostics for BTC research."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from scripts.fetch_btc_okx_public_ws_l2_raw_capture import RAW_WS_MANIFEST_FILE, RAW_WS_MESSAGES_FILE
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.fetch_btc_okx_public_ws_l2_raw_capture import RAW_WS_MANIFEST_FILE, RAW_WS_MESSAGES_FILE


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_WS_CAPTURE_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_okx_public_ws_l2_raw_capture_report.json")
DEFAULT_REPLAY_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_ws_order_book_replay_report.json")
REPORT_SCHEMA_VERSION = "btc_true_scalping_ws_latency_queue_diagnostics_report_v1"


def build_btc_true_scalping_ws_latency_queue_diagnostics_report(
    *,
    repo_root: Path | None = None,
    ws_capture_report_path: Path | None = None,
    replay_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    capture_file = _resolve(root, ws_capture_report_path or DEFAULT_WS_CAPTURE_REPORT)
    replay_file = _resolve(root, replay_report_path or DEFAULT_REPLAY_REPORT)
    capture = _read_json(capture_file)
    replay = _read_json(replay_file)
    selected_bundle_dir = str(capture.get("selected_bundle_dir") or "data/external/btc_perpetual/okx_swap/bundles/missing")
    bundle_dir = _resolve(root, Path(selected_bundle_dir))
    raw_path = bundle_dir / RAW_WS_MESSAGES_FILE
    manifest_path = bundle_dir / RAW_WS_MANIFEST_FILE
    raw_rows = _read_jsonl(raw_path)
    manifest = _read_json(manifest_path)

    receive_latency = _receive_latency_proxy(raw_rows)
    visible_queue = _visible_queue_proxy(raw_rows)
    validation = _validation(
        capture=capture,
        replay=replay,
        manifest=manifest,
        receive_latency=receive_latency,
        visible_queue=visible_queue,
    )
    blockers = _blockers(validation=validation)
    diagnostics_ready = bool(validation["proxy_diagnostics_ready"])
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_ws_receive_latency_visible_queue_proxy_no_candidate_no_paper_no_live",
        "status": "ws_latency_queue_proxy_ready_research_only_execution_latency_history_insufficient"
        if diagnostics_ready
        else "ws_latency_queue_proxy_missing_or_invalid_research_only",
        "decision": "continue_long_public_ws_l2_capture_and_keep_execution_latency_queue_unlocked_false",
        "next_required_action": "extend_public_ws_l2_capture_duration_then_separate_order_execution_latency_and_queue_position_evidence",
        "source_reports": {
            "ws_capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
            "ws_order_book_replay_report": _relpath(replay_file, root) if replay_file.exists() else None,
        },
        "source_files": {
            "raw_messages": {
                "path": _relpath(raw_path, root) if raw_path.exists() else None,
                "exists": raw_path.exists(),
                "row_count": len(raw_rows),
            },
            "raw_capture_manifest": {
                "path": _relpath(manifest_path, root) if manifest_path.exists() else None,
                "exists": manifest_path.exists(),
                "row_count": 1 if manifest else 0,
            },
        },
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "capture_summary": {
            "capture_duration_seconds": _float(manifest.get("capture_duration_seconds")) or 0.0,
            "event_ledger_history_days": (_float(manifest.get("capture_duration_seconds")) or 0.0) / 86_400.0,
            "message_count": int(manifest.get("message_count", len(raw_rows)) or len(raw_rows)),
            "data_message_count": int(manifest.get("data_message_count", 0) or 0),
            "connection_count": int(manifest.get("connection_count", 0) or 0) or (1 if raw_rows else 0),
            "forced_reconnect_count": int(manifest.get("forced_reconnect_count", 0) or 0),
        },
        "receive_latency_proxy": receive_latency,
        "visible_queue_proxy": visible_queue,
        "validation": validation,
        "blockers": blockers,
        "proxy_diagnostics_ready": diagnostics_ready,
        "contract_satisfied": False,
        "event_ledger_feature_validation_allowed": False,
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "true_scalping_allowed": False,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "guardrails": {
            "research_only": True,
            "production_ready": False,
            "paper_or_live_usable": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "broker_calls_allowed": False,
            "real_orders_created": False,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    }
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "btc_true_scalping_ws_latency_queue_diagnostics_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ws-capture-report-path", default=str(DEFAULT_WS_CAPTURE_REPORT))
    parser.add_argument("--replay-report-path", default=str(DEFAULT_REPLAY_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_ws_latency_queue_diagnostics_report(
        repo_root=Path(args.repo_root),
        ws_capture_report_path=Path(args.ws_capture_report_path),
        replay_report_path=Path(args.replay_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "ws_latency_queue_proxy_ready_research_only_execution_latency_history_insufficient",
        "ws_latency_queue_proxy_missing_or_invalid_research_only",
    }:
        raise SystemExit(2)


def _receive_latency_proxy(raw_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        row = _parse_raw(raw_row.get("raw"))
        channel = str(_mapping(row.get("arg")).get("channel", raw_row.get("channel", "")) or "")
        data = row.get("data")
        local_ms = _datetime_ms(raw_row.get("local_receive_ts"))
        if local_ms is None or not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, Mapping):
                continue
            exchange_ms = _int_or_none(item.get("ts"))
            if exchange_ms is None:
                continue
            delta_ms = local_ms - exchange_ms
            samples.append(
                {
                    "capture_sequence": _int(raw_row.get("capture_sequence")),
                    "connection_sequence": _int(raw_row.get("connection_sequence")),
                    "channel": channel,
                    "exchange_ts_ms": exchange_ms,
                    "receive_clock_delta_ms": delta_ms,
                }
            )
    deltas = [float(sample["receive_clock_delta_ms"]) for sample in samples]
    negative_count = sum(1 for value in deltas if value < 0)
    return {
        "proxy_id": "btc_okx_public_ws_receive_latency_proxy_v1",
        "proxy_scope": "public_ws_market_data_receive_clock_delta_not_order_execution_latency",
        "sample_count": len(samples),
        "book_sample_count": sum(1 for sample in samples if sample["channel"] == "books"),
        "trade_sample_count": sum(1 for sample in samples if sample["channel"] == "trades"),
        "negative_clock_delta_count": negative_count,
        "clock_precision_warning": negative_count > 0,
        "receive_clock_delta_ms": _stats(deltas),
        "sample_preview": samples[:20],
        "limitations": [
            "local_receive_ts_clock_delta_is_not_private_order_execution_latency",
            "second_precision_receive_timestamps_can_create_negative_clock_delta_samples",
            "network_path_is_public_market_data_not_authenticated_order_path",
        ],
    }


def _visible_queue_proxy(raw_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    bids: dict[float, dict[str, float]] = {}
    asks: dict[float, dict[str, float]] = {}
    samples: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        row = _parse_raw(raw_row.get("raw"))
        if str(_mapping(row.get("arg")).get("channel", "")) != "books":
            continue
        action = str(row.get("action", "") or "")
        data = row.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, Mapping):
                continue
            if action == "snapshot":
                bids = _levels_from_snapshot(item.get("bids"))
                asks = _levels_from_snapshot(item.get("asks"))
            else:
                _apply_updates(bids, item.get("bids"))
                _apply_updates(asks, item.get("asks"))
            best_bid = max(bids, default=None)
            best_ask = min(asks, default=None)
            spread_bps = _spread_bps(best_bid, best_ask)
            if best_bid is None or best_ask is None or spread_bps is None:
                continue
            bid_size = bids[best_bid]["size"]
            ask_size = asks[best_ask]["size"]
            bid_orders = bids[best_bid]["order_count"]
            ask_orders = asks[best_ask]["order_count"]
            samples.append(
                {
                    "capture_sequence": _int(raw_row.get("capture_sequence")),
                    "action": action,
                    "seq_id": _int_or_none(item.get("seqId")),
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_bps": spread_bps,
                    "best_bid_visible_queue_btc": bid_size,
                    "best_ask_visible_queue_btc": ask_size,
                    "best_bid_order_count": bid_orders,
                    "best_ask_order_count": ask_orders,
                    "top5_bid_visible_queue_btc": _top_size(bids, reverse=True, depth=5),
                    "top5_ask_visible_queue_btc": _top_size(asks, reverse=False, depth=5),
                }
            )
    bid_queue = [float(sample["best_bid_visible_queue_btc"]) for sample in samples]
    ask_queue = [float(sample["best_ask_visible_queue_btc"]) for sample in samples]
    spread_bps = [float(sample["spread_bps"]) for sample in samples]
    return {
        "proxy_id": "btc_okx_public_ws_visible_queue_proxy_v1",
        "proxy_scope": "visible_book_depth_proxy_not_exchange_order_queue_position",
        "sample_count": len(samples),
        "best_bid_visible_queue_btc": _stats(bid_queue),
        "best_ask_visible_queue_btc": _stats(ask_queue),
        "spread_bps": _stats(spread_bps),
        "maker_fill_assumption": "join_back_of_visible_best_level_queue_research_only",
        "taker_fill_assumption": "cross_spread_and_pay_cost_model_research_only",
        "sample_preview": samples[:20],
        "limitations": [
            "public_l2_depth_does_not_reveal_private_queue_position",
            "visible_size_can_cancel_before_fill",
            "proxy_cannot_estimate_order_priority_without_executions_or_private_order_ack_timestamps",
        ],
    }


def _validation(
    *,
    capture: Mapping[str, Any],
    replay: Mapping[str, Any],
    manifest: Mapping[str, Any],
    receive_latency: Mapping[str, Any],
    visible_queue: Mapping[str, Any],
) -> dict[str, Any]:
    duration_seconds = _float(manifest.get("capture_duration_seconds")) or 0.0
    public_boundary = bool(manifest.get("public_ws_only", False)) and not bool(
        manifest.get("private_endpoint_used", True)
    ) and not bool(manifest.get("order_endpoint_used", True)) and not bool(manifest.get("broker_calls_used", True))
    receive_ready = int(receive_latency.get("sample_count", 0) or 0) > 0
    queue_ready = int(visible_queue.get("sample_count", 0) or 0) > 0
    replay_ready = bool(replay.get("replay_sequence_ready", False)) and bool(
        _mapping(replay.get("validation")).get("sequence_integrity_policy_satisfied", False)
    )
    return {
        "raw_capture_ready": capture.get("status") == "verified_preflight",
        "replay_sequence_ready": replay_ready,
        "public_source_boundary_satisfied": public_boundary,
        "receive_latency_proxy_ready": receive_ready,
        "receive_latency_proxy_is_execution_latency": False,
        "visible_queue_proxy_ready": queue_ready,
        "visible_queue_proxy_is_exchange_queue_position": False,
        "minimum_research_capture_seconds_satisfied": duration_seconds >= 3600.0,
        "minimum_event_ledger_history_days_satisfied": duration_seconds / 86_400.0 >= 30.0,
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "proxy_diagnostics_ready": public_boundary and receive_ready and queue_ready and replay_ready,
    }


def _blockers(*, validation: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not bool(validation.get("raw_capture_ready", False)):
        blockers.append("btc_ws_latency_queue_raw_capture_not_verified_preflight")
    if not bool(validation.get("replay_sequence_ready", False)):
        blockers.append("btc_ws_latency_queue_order_book_replay_not_ready")
    if not bool(validation.get("public_source_boundary_satisfied", False)):
        blockers.append("btc_ws_latency_queue_public_source_boundary_not_verified")
    if not bool(validation.get("receive_latency_proxy_ready", False)):
        blockers.append("btc_ws_receive_latency_proxy_missing")
    if not bool(validation.get("visible_queue_proxy_ready", False)):
        blockers.append("btc_ws_visible_queue_proxy_missing")
    if not bool(validation.get("minimum_research_capture_seconds_satisfied", False)):
        blockers.append("btc_ws_latency_queue_research_capture_duration_below_contract")
    if not bool(validation.get("minimum_event_ledger_history_days_satisfied", False)):
        blockers.append("btc_ws_latency_queue_history_missing_for_event_ledger_window")
    if not bool(validation.get("execution_latency_model_ready", False)):
        blockers.append("btc_execution_latency_model_missing_ws_receive_latency_is_not_order_execution_latency")
    if not bool(validation.get("queue_model_ready", False)):
        blockers.append("btc_queue_model_missing_public_l2_visible_depth_is_not_exchange_queue_position")
    return _dedupe(blockers)


def _levels_from_snapshot(value: object) -> dict[float, dict[str, float]]:
    levels: dict[float, dict[str, float]] = {}
    for raw in value if isinstance(value, list) else []:
        parsed = _parse_level(raw)
        if parsed is None:
            continue
        price, size, order_count = parsed
        if size > 0:
            levels[price] = {"size": size, "order_count": order_count}
    return levels


def _apply_updates(levels: dict[float, dict[str, float]], value: object) -> None:
    for raw in value if isinstance(value, list) else []:
        parsed = _parse_level(raw)
        if parsed is None:
            continue
        price, size, order_count = parsed
        if size <= 0:
            levels.pop(price, None)
        else:
            levels[price] = {"size": size, "order_count": order_count}


def _parse_level(raw: object) -> tuple[float, float, float] | None:
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    price = _float(raw[0])
    size = _float(raw[1])
    order_count = _float(raw[3]) if len(raw) >= 4 else 0.0
    if price is None or size is None:
        return None
    return price, size, order_count or 0.0


def _top_size(levels: Mapping[float, Mapping[str, float]], *, reverse: bool, depth: int) -> float:
    return sum(float(levels[price]["size"]) for price in sorted(levels, reverse=reverse)[:depth])


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    midpoint = (best_bid + best_ask) / 2.0
    if midpoint <= 0 or best_ask <= best_bid:
        return None
    return (best_ask - best_bid) / midpoint * 10_000.0


def _stats(values: Iterable[float]) -> dict[str, float | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"min": None, "max": None, "mean": None, "median": None}
    return {"min": min(clean), "max": max(clean), "mean": statistics.mean(clean), "median": statistics.median(clean)}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                rows.append(dict(payload))
    return rows


def _parse_raw(value: object) -> dict[str, Any]:
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


def _datetime_ms(value: object) -> int | None:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(parsed.timestamp() * 1000)


def _int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError, IndexError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
