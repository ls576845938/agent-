#!/usr/bin/env python3
"""Validate timestamp-aligned BTC L2 public capture files for research-only preflight."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture import (
        AGG_TRADES_ALIGNED_FILE,
        ALIGNMENT_MANIFEST_FILE,
        ORDER_BOOK_DEPTH_ALIGNED_FILE,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.fetch_btc_okx_timestamp_aligned_l2_public_capture import (
        AGG_TRADES_ALIGNED_FILE,
        ALIGNMENT_MANIFEST_FILE,
        ORDER_BOOK_DEPTH_ALIGNED_FILE,
    )


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_CONTRACT_REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_timestamp_aligned_l2_data_contract_report.json"
)
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_okx_timestamp_aligned_l2_capture_report.json")
REPORT_SCHEMA_VERSION = "btc_true_scalping_l2_aligned_capture_quality_report_v1"
TRADE_REQUIRED_FIELDS = [
    "capture_sequence",
    "exchange_ts",
    "exchange_ts_ms",
    "local_receive_ts",
    "monotonic_ns",
    "trade_id",
    "price",
    "size",
    "side",
]
BOOK_REQUIRED_FIELDS = [
    "capture_sequence",
    "exchange_ts",
    "exchange_ts_ms",
    "local_receive_ts",
    "monotonic_ns",
    "side",
    "level",
    "price",
    "size",
    "best_bid",
    "best_ask",
    "spread_bps",
    "bid_depth_notional",
    "ask_depth_notional",
]
MANIFEST_REQUIRED_FIELDS = [
    "data_version",
    "capture_start",
    "capture_end",
    "venue_symbol",
    "public_channels",
    "private_endpoint_used",
    "order_endpoint_used",
    "clock_source",
    "gap_count",
    "checksum_or_sequence_policy",
]


def build_btc_true_scalping_l2_aligned_capture_quality_report(
    *,
    repo_root: Path | None = None,
    contract_report_path: Path | None = None,
    capture_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    contract_file = _resolve(root, contract_report_path or DEFAULT_CONTRACT_REPORT)
    capture_file = _resolve(root, capture_report_path or DEFAULT_CAPTURE_REPORT)
    contract = _read_json(contract_file)
    capture = _read_json(capture_file)
    selected_bundle_dir = str(
        capture.get("selected_bundle_dir")
        or contract.get("selected_bundle_dir")
        or "data/external/btc_perpetual/okx_swap/bundles/missing"
    )
    bundle_dir = _resolve(root, Path(selected_bundle_dir))
    trade_path = bundle_dir / AGG_TRADES_ALIGNED_FILE
    book_path = bundle_dir / ORDER_BOOK_DEPTH_ALIGNED_FILE
    manifest_path = bundle_dir / ALIGNMENT_MANIFEST_FILE
    trade_rows, trade_fields = _read_csv_with_fields(trade_path)
    book_rows, book_fields = _read_csv_with_fields(book_path)
    manifest = _read_json(manifest_path)
    thresholds = _thresholds(contract)
    file_quality = {
        "agg_trades_aligned": _file_quality(trade_path, root, trade_rows, trade_fields, TRADE_REQUIRED_FIELDS),
        "order_book_depth_aligned": _file_quality(book_path, root, book_rows, book_fields, BOOK_REQUIRED_FIELDS),
        "l2_alignment_manifest": _manifest_quality(manifest_path, root, manifest),
    }
    alignment = _alignment_quality(trade_rows=trade_rows, book_rows=book_rows, manifest=manifest, thresholds=thresholds)
    validation = _validation(file_quality=file_quality, alignment=alignment, manifest=manifest, capture=capture)
    blockers = _blockers(
        contract=contract,
        capture=capture,
        file_quality=file_quality,
        alignment=alignment,
        validation=validation,
    )
    format_ready = bool(validation["format_contract_satisfied"])
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "venue_symbol": "BTC-USDT-SWAP",
        "scope": "research_only_l2_aligned_capture_quality_no_candidate_no_paper_no_live",
        "status": "aligned_l2_capture_format_verified_research_only_history_insufficient"
        if format_ready
        else "aligned_l2_capture_missing_or_invalid_research_only",
        "decision": "continue_public_l2_capture_until_research_and_event_history_thresholds_are_met",
        "next_required_action": "extend_timestamp_aligned_public_l2_capture_or_import_verified_archive",
        "source_reports": {
            "data_contract": _relpath(contract_file, root) if contract_file.exists() else None,
            "capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
        },
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "thresholds": thresholds,
        "source_files": file_quality,
        "alignment_quality": alignment,
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
    (output_dir / "btc_true_scalping_l2_aligned_capture_quality_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--contract-report-path", default=str(DEFAULT_CONTRACT_REPORT))
    parser.add_argument("--capture-report-path", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_l2_aligned_capture_quality_report(
        repo_root=Path(args.repo_root),
        contract_report_path=Path(args.contract_report_path),
        capture_report_path=Path(args.capture_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") not in {
        "aligned_l2_capture_format_verified_research_only_history_insufficient",
        "aligned_l2_capture_missing_or_invalid_research_only",
    }:
        raise SystemExit(2)


def _thresholds(contract: Mapping[str, Any]) -> dict[str, Any]:
    minimum = _mapping(contract.get("minimum_capture_contract"))
    return {
        "minimum_research_capture_seconds": int(minimum.get("minimum_research_capture_seconds", 3600) or 3600),
        "minimum_event_ledger_history_days": int(minimum.get("minimum_event_ledger_history_days", 30) or 30),
        "minimum_book_depth_levels": int(minimum.get("minimum_book_depth_levels", 50) or 50),
        "required_alignment_max_clock_skew_ms": int(minimum.get("required_alignment_max_clock_skew_ms", 250) or 250),
        "minimum_trade_rows": 1,
        "minimum_book_rows": 1,
    }


def _file_quality(
    path: Path,
    root: Path,
    rows: list[dict[str, str]],
    fields: list[str],
    required_fields: list[str],
) -> dict[str, Any]:
    missing_fields = [field for field in required_fields if field not in fields]
    return {
        "path": _relpath(path, root) if path.exists() else None,
        "exists": path.exists(),
        "row_count": len(rows),
        "required_fields_present": not missing_fields,
        "missing_fields": missing_fields,
    }


def _manifest_quality(path: Path, root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    missing_fields = [field for field in MANIFEST_REQUIRED_FIELDS if field not in manifest]
    public_channels = manifest.get("public_channels")
    return {
        "path": _relpath(path, root) if path.exists() else None,
        "exists": path.exists(),
        "row_count": 1 if manifest else 0,
        "required_fields_present": not missing_fields,
        "missing_fields": missing_fields,
        "public_data_only": bool(manifest.get("public_rest_only", False))
        and not bool(manifest.get("private_endpoint_used", True))
        and not bool(manifest.get("order_endpoint_used", True))
        and not bool(manifest.get("broker_calls_used", True)),
        "public_channel_count": len(public_channels) if isinstance(public_channels, list) else 0,
    }


def _alignment_quality(
    *,
    trade_rows: list[Mapping[str, str]],
    book_rows: list[Mapping[str, str]],
    manifest: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    trade_sequences = _sequence_set(trade_rows)
    book_sequences = _sequence_set(book_rows)
    common_sequences = sorted(trade_sequences & book_sequences)
    max_gap_ms = int(thresholds.get("required_alignment_max_clock_skew_ms", 250) or 250)
    sequence_receive_gaps = _sequence_receive_gaps_ms(trade_rows=trade_rows, book_rows=book_rows)
    aligned_sequence_count = sum(1 for gap in sequence_receive_gaps if gap["local_receive_gap_ms"] <= max_gap_ms)
    book_depth_levels = _max_book_level(book_rows)
    capture_duration_seconds = _float(manifest.get("capture_duration_seconds")) or 0.0
    event_ledger_history_days = capture_duration_seconds / 86_400.0
    return {
        "trade_row_count": len(trade_rows),
        "book_level_row_count": len(book_rows),
        "trade_sequence_count": len(trade_sequences),
        "book_sequence_count": len(book_sequences),
        "same_capture_sequence_count": len(common_sequences),
        "aligned_sequence_count": aligned_sequence_count,
        "sequence_receive_gaps_ms": sequence_receive_gaps[:20],
        "capture_duration_seconds": capture_duration_seconds,
        "event_ledger_history_days": event_ledger_history_days,
        "max_book_level": book_depth_levels,
        "spread_bps_observed": any(_float(row.get("spread_bps")) is not None for row in book_rows),
        "depth_notional_observed": any(
            _float(row.get("bid_depth_notional")) is not None and _float(row.get("ask_depth_notional")) is not None
            for row in book_rows
        ),
        "trade_aggressor_flow_observed": any(str(row.get("side", "")).lower() in {"buy", "sell"} for row in trade_rows),
        "minimum_research_capture_seconds_satisfied": capture_duration_seconds
        >= float(thresholds.get("minimum_research_capture_seconds", 3600)),
        "minimum_event_ledger_history_days_satisfied": event_ledger_history_days
        >= float(thresholds.get("minimum_event_ledger_history_days", 30)),
        "minimum_book_depth_levels_satisfied": book_depth_levels >= int(thresholds.get("minimum_book_depth_levels", 50)),
    }


def _validation(
    *,
    file_quality: Mapping[str, Any],
    alignment: Mapping[str, Any],
    manifest: Mapping[str, Any],
    capture: Mapping[str, Any],
) -> dict[str, Any]:
    files_ready = all(
        bool(_mapping(file_quality.get(name)).get("exists"))
        and bool(_mapping(file_quality.get(name)).get("required_fields_present"))
        and int(_mapping(file_quality.get(name)).get("row_count", 0) or 0) > 0
        for name in ("agg_trades_aligned", "order_book_depth_aligned", "l2_alignment_manifest")
    )
    public_boundary = (
        bool(_mapping(file_quality.get("l2_alignment_manifest")).get("public_data_only"))
        and not bool(capture.get("private_endpoint_used", False))
        and not bool(capture.get("order_endpoint_used", False))
    )
    same_window = int(alignment.get("aligned_sequence_count", 0) or 0) > 0
    replay_inputs = (
        bool(alignment.get("spread_bps_observed", False))
        and bool(alignment.get("depth_notional_observed", False))
        and bool(alignment.get("trade_aggressor_flow_observed", False))
    )
    return {
        "files_ready": files_ready,
        "public_source_boundary_satisfied": public_boundary,
        "same_window_trade_book_alignment_satisfied": same_window,
        "spread_slippage_queue_replay_inputs_partial": replay_inputs,
        "minimum_research_capture_seconds_satisfied": bool(
            alignment.get("minimum_research_capture_seconds_satisfied", False)
        ),
        "minimum_event_ledger_history_days_satisfied": bool(
            alignment.get("minimum_event_ledger_history_days_satisfied", False)
        ),
        "execution_latency_model_ready": False,
        "queue_model_ready": False,
        "format_contract_satisfied": files_ready and public_boundary and same_window and replay_inputs,
        "manifest_public_rest_only": bool(manifest.get("public_rest_only", False)),
        "capture_report_status": str(capture.get("status", "missing") or "missing"),
    }


def _blockers(
    *,
    contract: Mapping[str, Any],
    capture: Mapping[str, Any],
    file_quality: Mapping[str, Any],
    alignment: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if contract.get("status") != "timestamp_aligned_l2_capture_required_research_only":
        blockers.append("btc_timestamp_aligned_l2_data_contract_not_ready")
    if capture.get("status") not in {"verified_preflight", "dry_run"}:
        blockers.append("btc_okx_timestamp_aligned_l2_capture_report_not_ready")
    for name in ("agg_trades_aligned", "order_book_depth_aligned", "l2_alignment_manifest"):
        quality = _mapping(file_quality.get(name))
        if not bool(quality.get("exists", False)):
            blockers.append(f"btc_{name}_missing")
        if not bool(quality.get("required_fields_present", False)):
            blockers.append(f"btc_{name}_required_fields_missing")
        if int(quality.get("row_count", 0) or 0) <= 0:
            blockers.append(f"btc_{name}_empty")
    if not bool(validation.get("public_source_boundary_satisfied", False)):
        blockers.append("btc_aligned_l2_public_source_boundary_not_verified")
    if not bool(validation.get("same_window_trade_book_alignment_satisfied", False)):
        blockers.append("btc_same_window_public_trade_book_alignment_missing")
    if not bool(validation.get("spread_slippage_queue_replay_inputs_partial", False)):
        blockers.append("btc_spread_slippage_queue_replay_inputs_missing")
    if not bool(alignment.get("minimum_book_depth_levels_satisfied", False)):
        blockers.append("btc_aligned_l2_book_depth_below_contract")
    if not bool(validation.get("minimum_research_capture_seconds_satisfied", False)):
        blockers.append("btc_aligned_l2_research_capture_duration_below_contract")
    if not bool(validation.get("minimum_event_ledger_history_days_satisfied", False)):
        blockers.append("btc_timestamp_aligned_l2_history_missing_for_event_ledger_window")
    if not bool(validation.get("execution_latency_model_ready", False)):
        blockers.append("btc_execution_latency_model_missing_rest_latency_is_not_execution_latency")
    if not bool(validation.get("queue_model_ready", False)):
        blockers.append("btc_queue_model_missing_visible_depth_is_proxy_only")
    return _dedupe(blockers)


def _sequence_set(rows: Iterable[Mapping[str, str]]) -> set[int]:
    values = set()
    for row in rows:
        try:
            values.add(int(str(row.get("capture_sequence", ""))))
        except (TypeError, ValueError):
            continue
    return values


def _sequence_receive_gaps_ms(
    *,
    trade_rows: list[Mapping[str, str]],
    book_rows: list[Mapping[str, str]],
) -> list[dict[str, Any]]:
    trade_by_sequence = _first_local_receive_by_sequence(trade_rows)
    book_by_sequence = _first_local_receive_by_sequence(book_rows)
    out = []
    for sequence in sorted(set(trade_by_sequence) & set(book_by_sequence)):
        trade_ts = trade_by_sequence[sequence]
        book_ts = book_by_sequence[sequence]
        gap = abs((book_ts - trade_ts).total_seconds() * 1000.0)
        out.append({"capture_sequence": sequence, "local_receive_gap_ms": gap})
    return out


def _first_local_receive_by_sequence(rows: Iterable[Mapping[str, str]]) -> dict[int, datetime]:
    out: dict[int, datetime] = {}
    for row in rows:
        try:
            sequence = int(str(row.get("capture_sequence", "")))
        except (TypeError, ValueError):
            continue
        parsed = _parse_dt(row.get("local_receive_ts"))
        if parsed is None:
            continue
        if sequence not in out or parsed < out[sequence]:
            out[sequence] = parsed
    return out


def _max_book_level(rows: Iterable[Mapping[str, str]]) -> int:
    levels = []
    for row in rows:
        try:
            levels.append(int(float(str(row.get("level", "")))))
        except (TypeError, ValueError):
            continue
    return max(levels, default=0)


def _read_csv_with_fields(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader], list(reader.fieldnames or [])


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


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


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
