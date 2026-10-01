#!/usr/bin/env python3
"""Validate OKX public WebSocket raw L2/trade captures for BTC scalping research."""

from __future__ import annotations

import argparse
import json
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
REPORT_SCHEMA_VERSION = "btc_true_scalping_ws_l2_raw_capture_quality_report_v1"
REQUIRED_CHANNELS = ["trades", "books"]


def build_btc_true_scalping_ws_l2_raw_capture_quality_report(
    *,
    repo_root: Path | None = None,
    ws_capture_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    capture_file = _resolve(root, ws_capture_report_path or DEFAULT_WS_CAPTURE_REPORT)
    capture = _read_json(capture_file)
    selected_bundle_dir = str(capture.get("selected_bundle_dir") or "data/external/btc_perpetual/okx_swap/bundles/missing")
    bundle_dir = _resolve(root, Path(selected_bundle_dir))
    raw_path = bundle_dir / RAW_WS_MESSAGES_FILE
    manifest_path = bundle_dir / RAW_WS_MANIFEST_FILE
    raw_rows = _read_jsonl(raw_path)
    manifest = _read_json(manifest_path)
    thresholds = {
        "minimum_research_capture_seconds": 3600,
        "minimum_event_ledger_history_days": 30,
        "minimum_data_messages": 1,
        "required_channels": REQUIRED_CHANNELS,
    }
    source_files = {
        "raw_messages": _raw_file_quality(raw_path, root, raw_rows),
        "raw_capture_manifest": _manifest_quality(manifest_path, root, manifest),
    }
    capture_quality = _capture_quality(raw_rows=raw_rows, manifest=manifest, thresholds=thresholds)
    validation = _validation(capture=capture, manifest=manifest, source_files=source_files, capture_quality=capture_quality)
    blockers = _blockers(capture=capture, source_files=source_files, capture_quality=capture_quality, validation=validation)
    format_ready = bool(validation["format_contract_satisfied"])
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_ws_l2_raw_capture_quality_no_candidate_no_paper_no_live",
        "status": "ws_l2_raw_capture_format_verified_research_only_history_insufficient"
        if format_ready
        else "ws_l2_raw_capture_missing_or_invalid_research_only",
        "decision": "continue_public_ws_l2_capture_then_build_order_book_replay_and_resync_policy_before_true_scalping",
        "next_required_action": "extend_public_ws_l2_capture_and_build_replay_resync_queue_latency_reports",
        "source_reports": {
            "ws_capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
        },
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "thresholds": thresholds,
        "source_files": source_files,
        "capture_quality": capture_quality,
        "validation": validation,
        "blockers": blockers,
        "format_contract_satisfied": format_ready,
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
    (output_dir / "btc_true_scalping_ws_l2_raw_capture_quality_report.json").write_text(
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
    payload = build_btc_true_scalping_ws_l2_raw_capture_quality_report(
        repo_root=Path(args.repo_root),
        ws_capture_report_path=Path(args.ws_capture_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "ws_l2_raw_capture_format_verified_research_only_history_insufficient",
        "ws_l2_raw_capture_missing_or_invalid_research_only",
    }:
        raise SystemExit(2)


def _raw_file_quality(path: Path, root: Path, rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "path": _relpath(path, root) if path.exists() else None,
        "exists": path.exists(),
        "row_count": len(rows),
        "required_fields_present": all(
            all(field in row for field in ("capture_sequence", "local_receive_ts", "monotonic_ns", "channel", "raw"))
            for row in rows
        )
        if rows
        else False,
    }


def _manifest_quality(path: Path, root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    required = [
        "data_version",
        "capture_start",
        "capture_end",
        "capture_duration_seconds",
        "public_ws_url",
        "public_channels",
        "private_endpoint_used",
        "order_endpoint_used",
        "clock_source",
        "checksum_or_sequence_policy",
    ]
    missing = [field for field in required if field not in manifest]
    public_channels = manifest.get("public_channels")
    return {
        "path": _relpath(path, root) if path.exists() else None,
        "exists": path.exists(),
        "row_count": 1 if manifest else 0,
        "required_fields_present": not missing,
        "missing_fields": missing,
        "public_data_only": bool(manifest.get("public_ws_only", False))
        and not bool(manifest.get("private_endpoint_used", True))
        and not bool(manifest.get("order_endpoint_used", True))
        and not bool(manifest.get("broker_calls_used", True)),
        "public_channel_count": len(public_channels) if isinstance(public_channels, list) else 0,
    }


def _capture_quality(
    *,
    raw_rows: list[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    parsed_raw = [_parse_raw(row.get("raw")) for row in raw_rows]
    data_messages = [item for item in parsed_raw if isinstance(item.get("data"), list)]
    channels = [str(_mapping(item.get("arg")).get("channel", "")) for item in data_messages]
    channel_counts = {channel: channels.count(channel) for channel in sorted(set(channels)) if channel}
    capture_duration_seconds = _float(manifest.get("capture_duration_seconds")) or 0.0
    event_history_days = capture_duration_seconds / 86_400.0
    return {
        "message_count": len(raw_rows),
        "data_message_count": len(data_messages),
        "trade_message_count": channel_counts.get("trades", 0),
        "book_message_count": channel_counts.get("books", 0) + channel_counts.get("books5", 0),
        "channel_counts": channel_counts,
        "capture_duration_seconds": capture_duration_seconds,
        "event_ledger_history_days": event_history_days,
        "local_receive_timestamp_present": all(bool(row.get("local_receive_ts")) for row in raw_rows) if raw_rows else False,
        "monotonic_timestamp_present": all(_int(row.get("monotonic_ns")) > 0 for row in raw_rows) if raw_rows else False,
        "monotonic_order_pass": _monotonic_order_pass(raw_rows),
        "exchange_ts_observed": _exchange_ts_observed(data_messages),
        "sequence_or_checksum_observed": _sequence_or_checksum_observed(data_messages),
        "required_channels_observed": all(channel in channel_counts for channel in thresholds.get("required_channels", [])),
        "minimum_research_capture_seconds_satisfied": capture_duration_seconds
        >= float(thresholds.get("minimum_research_capture_seconds", 3600)),
        "minimum_event_ledger_history_days_satisfied": event_history_days
        >= float(thresholds.get("minimum_event_ledger_history_days", 30)),
    }


def _validation(
    *,
    capture: Mapping[str, Any],
    manifest: Mapping[str, Any],
    source_files: Mapping[str, Any],
    capture_quality: Mapping[str, Any],
) -> dict[str, Any]:
    raw_quality = _mapping(source_files.get("raw_messages"))
    manifest_quality = _mapping(source_files.get("raw_capture_manifest"))
    files_ready = (
        bool(raw_quality.get("exists"))
        and bool(raw_quality.get("required_fields_present"))
        and int(raw_quality.get("row_count", 0) or 0) > 0
        and bool(manifest_quality.get("exists"))
        and bool(manifest_quality.get("required_fields_present"))
    )
    public_boundary = (
        bool(manifest_quality.get("public_data_only"))
        and not bool(capture.get("private_endpoint_used", False))
        and not bool(capture.get("order_endpoint_used", False))
    )
    raw_timestamps = bool(capture_quality.get("local_receive_timestamp_present")) and bool(
        capture_quality.get("monotonic_timestamp_present")
    )
    required_channels = bool(capture_quality.get("required_channels_observed"))
    raw_l2_ready = (
        bool(capture_quality.get("exchange_ts_observed"))
        and bool(capture_quality.get("sequence_or_checksum_observed"))
        and required_channels
    )
    return {
        "files_ready": files_ready,
        "public_source_boundary_satisfied": public_boundary,
        "required_channels_observed": required_channels,
        "raw_message_timestamps_ready": raw_timestamps,
        "raw_l2_sequence_or_checksum_observed": bool(capture_quality.get("sequence_or_checksum_observed")),
        "raw_l2_capture_format_satisfied": raw_l2_ready,
        "minimum_research_capture_seconds_satisfied": bool(
            capture_quality.get("minimum_research_capture_seconds_satisfied")
        ),
        "minimum_event_ledger_history_days_satisfied": bool(
            capture_quality.get("minimum_event_ledger_history_days_satisfied")
        ),
        "order_book_replay_ready": False,
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "format_contract_satisfied": files_ready and public_boundary and raw_timestamps and raw_l2_ready,
        "capture_report_status": str(capture.get("status", "missing") or "missing"),
        "manifest_public_ws_only": bool(manifest.get("public_ws_only", False)),
    }


def _blockers(
    *,
    capture: Mapping[str, Any],
    source_files: Mapping[str, Any],
    capture_quality: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if capture.get("status") not in {"verified_preflight", "partial", "dry_run"}:
        blockers.append("btc_okx_public_ws_l2_raw_capture_report_not_ready")
    for name in ("raw_messages", "raw_capture_manifest"):
        quality = _mapping(source_files.get(name))
        if not bool(quality.get("exists", False)):
            blockers.append(f"btc_ws_l2_{name}_missing")
        if not bool(quality.get("required_fields_present", False)):
            blockers.append(f"btc_ws_l2_{name}_required_fields_missing")
        if int(quality.get("row_count", 0) or 0) <= 0:
            blockers.append(f"btc_ws_l2_{name}_empty")
    if not bool(validation.get("public_source_boundary_satisfied", False)):
        blockers.append("btc_ws_l2_public_source_boundary_not_verified")
    if not bool(validation.get("required_channels_observed", False)):
        blockers.append("btc_ws_l2_required_trades_and_books_channels_missing")
    if not bool(validation.get("raw_message_timestamps_ready", False)):
        blockers.append("btc_ws_l2_raw_message_timestamps_missing")
    if not bool(validation.get("raw_l2_sequence_or_checksum_observed", False)):
        blockers.append("btc_ws_l2_sequence_or_checksum_missing")
    if not bool(validation.get("minimum_research_capture_seconds_satisfied", False)):
        blockers.append("btc_ws_l2_research_capture_duration_below_contract")
    if not bool(validation.get("minimum_event_ledger_history_days_satisfied", False)):
        blockers.append("btc_ws_l2_history_missing_for_event_ledger_window")
    if not bool(validation.get("order_book_replay_ready", False)):
        blockers.append("btc_ws_l2_order_book_replay_not_validated")
    if not bool(validation.get("execution_latency_model_ready", False)):
        blockers.append("btc_execution_latency_model_missing_ws_receive_latency_is_not_execution_latency")
    if not bool(validation.get("queue_model_ready", False)):
        blockers.append("btc_queue_model_missing_raw_l2_requires_replay_before_queue_proxy")
    blockers.extend(str(item) for item in capture.get("blockers", []) if str(item))
    return _dedupe(blockers)


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
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
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


def _exchange_ts_observed(messages: Iterable[Mapping[str, Any]]) -> bool:
    for message in messages:
        for item in message.get("data", []):
            if isinstance(item, Mapping) and ("ts" in item or "tradeId" in item):
                return True
    return False


def _sequence_or_checksum_observed(messages: Iterable[Mapping[str, Any]]) -> bool:
    for message in messages:
        for item in message.get("data", []):
            if isinstance(item, Mapping) and any(key in item for key in ("seqId", "prevSeqId", "checksum")):
                return True
    return False


def _monotonic_order_pass(rows: Iterable[Mapping[str, Any]]) -> bool:
    values = [_int(row.get("monotonic_ns")) for row in rows]
    clean = [value for value in values if value > 0]
    return bool(clean) and clean == sorted(clean)


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


def _int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
