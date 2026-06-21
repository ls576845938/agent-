#!/usr/bin/env python3
"""Replay OKX public WS order book frames for BTC scalping research evidence."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
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
REPORT_SCHEMA_VERSION = "btc_true_scalping_ws_order_book_replay_report_v1"
OKX_CHECKSUM_DEPRECATION_POLICY = {
    "source_url": "https://www.okx.com/docs-v5/log_en/",
    "announced_date": "2026-06-09",
    "production_deprecation_date": "2026-06-23",
    "affected_channels": ["books", "books-l2-tbt", "books50-l2-tbt"],
    "post_deprecation_checksum_value": 0,
    "required_integrity_check": "seqId_prevSeqId_continuity",
}


def build_btc_true_scalping_ws_order_book_replay_report(
    *,
    repo_root: Path | None = None,
    ws_capture_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_now()
    capture_file = _resolve(root, ws_capture_report_path or DEFAULT_WS_CAPTURE_REPORT)
    capture = _read_json(capture_file)
    selected_bundle_dir = str(capture.get("selected_bundle_dir") or "data/external/btc_perpetual/okx_swap/bundles/missing")
    bundle_dir = _resolve(root, Path(selected_bundle_dir))
    raw_path = bundle_dir / RAW_WS_MESSAGES_FILE
    manifest_path = bundle_dir / RAW_WS_MANIFEST_FILE
    raw_rows = _read_jsonl(raw_path)
    manifest = _read_json(manifest_path)
    replay = _replay_order_book(raw_rows)
    replay["summary"].update(_transport_summary(manifest=manifest, replay_summary=_mapping(replay.get("summary"))))
    validation = _validation(capture=capture, manifest=manifest, replay=replay)
    blockers = _blockers(capture=capture, manifest=manifest, replay=replay, validation=validation)
    replay_sequence_ready = bool(validation["replay_sequence_ready"])
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_ws_order_book_replay_no_candidate_no_paper_no_live",
        "status": "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient"
        if replay_sequence_ready
        else "ws_order_book_replay_missing_or_invalid_research_only",
        "decision": "continue_public_ws_l2_capture_with_sequence_reconnect_latency_queue_validation_before_true_scalping",
        "next_required_action": "extend_public_ws_l2_capture_then_add_reconnect_resync_latency_and_queue_reports",
        "source_reports": {
            "ws_capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
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
        "okx_checksum_deprecation_policy": OKX_CHECKSUM_DEPRECATION_POLICY,
        "replay_summary": replay["summary"],
        "replay_metrics": replay["metrics"],
        "validation": validation,
        "blockers": blockers,
        "replay_sequence_ready": replay_sequence_ready,
        "independent_checksum_validated": False,
        "contract_satisfied": False,
        "event_ledger_feature_validation_allowed": False,
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
    (output_dir / "btc_true_scalping_ws_order_book_replay_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--ws-capture-report-path", default=str(DEFAULT_WS_CAPTURE_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_ws_order_book_replay_report(
        repo_root=Path(args.repo_root),
        ws_capture_report_path=Path(args.ws_capture_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "ws_order_book_replay_sequence_policy_verified_research_only_history_insufficient",
        "ws_order_book_replay_missing_or_invalid_research_only",
    }:
        raise SystemExit(2)


def _replay_order_book(raw_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    last_seq_id: int | None = None
    snapshot_count = 0
    update_count = 0
    applied_update_count = 0
    delete_count = 0
    sequence_gap_count = 0
    crossed_book_count = 0
    checksum_observed_count = 0
    seq_id_observed_count = 0
    prev_seq_id_observed_count = 0
    book_message_count = 0
    spread_bps_values: list[float] = []
    top1_imbalance_values: list[float] = []
    top5_imbalance_values: list[float] = []
    final_levels_by_step: list[dict[str, Any]] = []
    sequence_issues: list[dict[str, Any]] = []
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
            seq_id = _int_or_none(item.get("seqId"))
            prev_seq_id = _int_or_none(item.get("prevSeqId"))
            checksum = _int_or_none(item.get("checksum"))
            book_message_count += 1
            if checksum is not None:
                checksum_observed_count += 1
            if seq_id is not None:
                seq_id_observed_count += 1
            if prev_seq_id is not None:
                prev_seq_id_observed_count += 1
            if action == "snapshot":
                bids = _levels_from_snapshot(item.get("bids"))
                asks = _levels_from_snapshot(item.get("asks"))
                snapshot_count += 1
                last_seq_id = seq_id
            else:
                update_count += 1
                if last_seq_id is None:
                    sequence_gap_count += 1
                    sequence_issues.append(
                        {
                            "capture_sequence": _int(raw_row.get("capture_sequence")),
                            "issue": "update_before_snapshot",
                            "seq_id": seq_id,
                            "prev_seq_id": prev_seq_id,
                            "expected_prev_seq_id": None,
                        }
                    )
                    continue
                if prev_seq_id != last_seq_id:
                    sequence_gap_count += 1
                    sequence_issues.append(
                        {
                            "capture_sequence": _int(raw_row.get("capture_sequence")),
                            "issue": "prev_seq_id_mismatch",
                            "seq_id": seq_id,
                            "prev_seq_id": prev_seq_id,
                            "expected_prev_seq_id": last_seq_id,
                        }
                    )
                removed = _apply_updates(bids, item.get("bids"))
                removed += _apply_updates(asks, item.get("asks"))
                delete_count += removed
                applied_update_count += 1
                last_seq_id = seq_id
            best_bid = max(bids, default=None)
            best_ask = min(asks, default=None)
            spread_bps = _spread_bps(best_bid, best_ask)
            if best_bid is not None and best_ask is not None and best_bid >= best_ask:
                crossed_book_count += 1
            if spread_bps is not None:
                spread_bps_values.append(spread_bps)
            top1_imbalance = _top_depth_imbalance(bids, asks, depth=1)
            top5_imbalance = _top_depth_imbalance(bids, asks, depth=5)
            if top1_imbalance is not None:
                top1_imbalance_values.append(top1_imbalance)
            if top5_imbalance is not None:
                top5_imbalance_values.append(top5_imbalance)
            final_levels_by_step.append(
                {
                    "capture_sequence": _int(raw_row.get("capture_sequence")),
                    "action": action,
                    "seq_id": seq_id,
                    "prev_seq_id": prev_seq_id,
                    "checksum": checksum,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread_bps": spread_bps,
                    "bid_level_count": len(bids),
                    "ask_level_count": len(asks),
                }
            )
    summary = {
        "raw_message_count": len(raw_rows),
        "book_message_count": book_message_count,
        "snapshot_count": snapshot_count,
        "update_count": update_count,
        "applied_update_count": applied_update_count,
        "delete_count": delete_count,
        "final_bid_level_count": len(bids),
        "final_ask_level_count": len(asks),
        "sequence_continuity_pass": sequence_gap_count == 0 and snapshot_count > 0 and applied_update_count > 0,
        "sequence_gap_count": sequence_gap_count,
        "sequence_issues": sequence_issues[:20],
        "crossed_book_count": crossed_book_count,
        "checksum_observed_count": checksum_observed_count,
        "seq_id_observed_count": seq_id_observed_count,
        "prev_seq_id_observed_count": prev_seq_id_observed_count,
        "checksum_validation_status": "checksum_observed_deprecated_by_okx_sequence_policy_required"
        if checksum_observed_count
        else "checksum_absent_or_zero_sequence_policy_required",
        "final_best_bid": max(bids, default=None),
        "final_best_ask": min(asks, default=None),
        "replayed_steps_sample": final_levels_by_step[:20],
    }
    metrics = {
        "spread_bps": _stats(spread_bps_values),
        "top1_depth_imbalance": _stats(top1_imbalance_values),
        "top5_depth_imbalance": _stats(top5_imbalance_values),
        "final_bid_top5_notional": _top_notional(bids, reverse=True, depth=5),
        "final_ask_top5_notional": _top_notional(asks, reverse=False, depth=5),
    }
    return {"summary": summary, "metrics": metrics}


def _transport_summary(*, manifest: Mapping[str, Any], replay_summary: Mapping[str, Any]) -> dict[str, Any]:
    raw_message_count = int(replay_summary.get("raw_message_count", 0) or 0)
    connection_count = _int(manifest.get("connection_count")) or (1 if raw_message_count > 0 else 0)
    forced_reconnect_count = _int(manifest.get("forced_reconnect_count"))
    transport_gap_count = _int(manifest.get("gap_count"))
    return {
        "connection_count": connection_count,
        "forced_reconnect_after_messages": _int(manifest.get("forced_reconnect_after_messages")),
        "forced_reconnect_count": forced_reconnect_count,
        "transport_gap_count": transport_gap_count,
    }


def _validation(*, capture: Mapping[str, Any], manifest: Mapping[str, Any], replay: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(replay.get("summary"))
    metrics = _mapping(replay.get("metrics"))
    spread = _mapping(metrics.get("spread_bps"))
    duration_seconds = _float(manifest.get("capture_duration_seconds")) or 0.0
    sequence_integrity_policy_satisfied = (
        bool(summary.get("sequence_continuity_pass", False))
        and int(summary.get("seq_id_observed_count", 0) or 0) > 0
        and int(summary.get("prev_seq_id_observed_count", 0) or 0) > 0
    )
    return {
        "raw_capture_ready": capture.get("status") == "verified_preflight",
        "public_source_boundary_satisfied": bool(manifest.get("public_ws_only", False))
        and not bool(manifest.get("private_endpoint_used", True))
        and not bool(manifest.get("order_endpoint_used", True))
        and not bool(manifest.get("broker_calls_used", True)),
        "snapshot_observed": int(summary.get("snapshot_count", 0) or 0) > 0,
        "updates_observed": int(summary.get("applied_update_count", 0) or 0) > 0,
        "sequence_continuity_pass": bool(summary.get("sequence_continuity_pass", False)),
        "non_crossed_book_pass": int(summary.get("crossed_book_count", 0) or 0) == 0,
        "spread_observed": spread.get("mean") is not None,
        "checksum_observed": int(summary.get("checksum_observed_count", 0) or 0) > 0,
        "checksum_deprecation_policy_recorded": True,
        "sequence_integrity_policy_satisfied": sequence_integrity_policy_satisfied,
        "independent_checksum_validated": False,
        "minimum_research_capture_seconds_satisfied": duration_seconds >= 3600.0,
        "minimum_event_ledger_history_days_satisfied": duration_seconds / 86_400.0 >= 30.0,
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "replay_sequence_ready": capture.get("status") == "verified_preflight"
        and sequence_integrity_policy_satisfied
        and int(summary.get("crossed_book_count", 0) or 0) == 0
        and spread.get("mean") is not None,
    }


def _blockers(
    *,
    capture: Mapping[str, Any],
    manifest: Mapping[str, Any],
    replay: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if capture.get("status") != "verified_preflight":
        blockers.append("btc_ws_l2_raw_capture_not_verified_preflight")
    if not bool(validation.get("public_source_boundary_satisfied", False)):
        blockers.append("btc_ws_l2_replay_public_source_boundary_not_verified")
    if not bool(validation.get("snapshot_observed", False)):
        blockers.append("btc_ws_l2_replay_snapshot_missing")
    if not bool(validation.get("updates_observed", False)):
        blockers.append("btc_ws_l2_replay_updates_missing")
    if not bool(validation.get("sequence_continuity_pass", False)):
        blockers.append("btc_ws_l2_replay_sequence_continuity_failed")
    if not bool(validation.get("non_crossed_book_pass", False)):
        blockers.append("btc_ws_l2_replay_crossed_book_detected")
    if not bool(validation.get("spread_observed", False)):
        blockers.append("btc_ws_l2_replay_spread_missing")
    if not bool(validation.get("checksum_deprecation_policy_recorded", False)):
        blockers.append("btc_ws_l2_checksum_deprecation_policy_missing")
    if not bool(validation.get("sequence_integrity_policy_satisfied", False)):
        blockers.append("btc_ws_l2_sequence_integrity_policy_not_satisfied")
    if not bool(validation.get("minimum_research_capture_seconds_satisfied", False)):
        blockers.append("btc_ws_l2_replay_research_capture_duration_below_contract")
    if not bool(validation.get("minimum_event_ledger_history_days_satisfied", False)):
        blockers.append("btc_ws_l2_replay_history_missing_for_event_ledger_window")
    if not bool(validation.get("execution_latency_model_ready", False)):
        blockers.append("btc_execution_latency_model_missing_ws_replay_receive_latency_is_not_execution_latency")
    if not bool(validation.get("queue_model_ready", False)):
        blockers.append("btc_queue_model_missing_replay_depth_is_proxy_only")
    blockers.extend(str(item) for item in capture.get("blockers", []) if str(item))
    return _dedupe(blockers)


def _levels_from_snapshot(value: object) -> dict[float, float]:
    levels: dict[float, float] = {}
    for raw in value if isinstance(value, list) else []:
        price = _float(raw[0]) if isinstance(raw, list) and len(raw) >= 2 else None
        size = _float(raw[1]) if isinstance(raw, list) and len(raw) >= 2 else None
        if price is None or size is None or size <= 0:
            continue
        levels[price] = size
    return levels


def _apply_updates(levels: dict[float, float], value: object) -> int:
    removed = 0
    for raw in value if isinstance(value, list) else []:
        price = _float(raw[0]) if isinstance(raw, list) and len(raw) >= 2 else None
        size = _float(raw[1]) if isinstance(raw, list) and len(raw) >= 2 else None
        if price is None or size is None:
            continue
        if size <= 0:
            if price in levels:
                removed += 1
                levels.pop(price, None)
        else:
            levels[price] = size
    return removed


def _top_depth_imbalance(bids: Mapping[float, float], asks: Mapping[float, float], *, depth: int) -> float | None:
    bid_notional = _top_notional(bids, reverse=True, depth=depth)
    ask_notional = _top_notional(asks, reverse=False, depth=depth)
    total = bid_notional + ask_notional
    if total <= 0:
        return None
    return (bid_notional - ask_notional) / total


def _top_notional(levels: Mapping[float, float], *, reverse: bool, depth: int) -> float:
    prices = sorted(levels, reverse=reverse)[:depth]
    return sum(price * levels[price] for price in prices)


def _spread_bps(best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    midpoint = (best_bid + best_ask) / 2.0
    if midpoint <= 0 or best_ask <= best_bid:
        return None
    return (best_ask - best_bid) / midpoint * 10_000.0


def _stats(values: Iterable[float]) -> dict[str, float | None]:
    clean = [value for value in values if value is not None]
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


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


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
