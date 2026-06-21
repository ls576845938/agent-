#!/usr/bin/env python3
"""Build a research-only quality report for bounded BTC public L2/tick samples."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from scripts.fetch_btc_okx_l2_microstructure_public_samples import BOOK_SAMPLE_FILE, TRADE_SAMPLE_FILE
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.fetch_btc_okx_l2_microstructure_public_samples import BOOK_SAMPLE_FILE, TRADE_SAMPLE_FILE


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_CAPTURE_REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json"
)
REPORT_SCHEMA_VERSION = "btc_true_scalping_l2_sample_quality_report_v1"


def build_btc_true_scalping_l2_sample_quality_report(
    *,
    repo_root: Path | None = None,
    capture_report_path: Path | None = None,
    output_root: Path | None = None,
    min_completed_samples: int = 3,
    min_valid_book_snapshots: int = 1,
    min_latency_samples: int = 2,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    capture_path = _resolve(root, capture_report_path or DEFAULT_CAPTURE_REPORT)
    capture = _read_json(capture_path)
    selected_bundle_dir = str(capture.get("selected_bundle_dir", "") or "")
    bundle_dir = _resolve(root, Path(selected_bundle_dir)) if selected_bundle_dir else root / "missing"
    trade_path = bundle_dir / TRADE_SAMPLE_FILE
    book_path = bundle_dir / BOOK_SAMPLE_FILE
    trade_rows = _read_csv(trade_path)
    book_rows = _read_csv(book_path)
    latency_samples = _latency_samples(capture.get("latency_samples"))
    book_metrics = _book_metrics(book_rows)
    sample_quality = {
        "requested_sample_count": _int(capture.get("requested_sample_count")),
        "completed_sample_count": _int(capture.get("completed_sample_count")),
        "trade_row_count": len(trade_rows),
        "book_level_row_count": len(book_rows),
        "trade_sample_count_with_rows": len(_unique_values(trade_rows, "sample_index")),
        "book_sample_count_with_rows": len(_unique_values(book_rows, "sample_index")),
        "unique_trade_timestamps": len(_unique_values(trade_rows, "ts")),
        "unique_book_timestamps": len(_unique_values(book_rows, "ts")),
        "valid_top_of_book_snapshot_count": book_metrics["valid_top_of_book_snapshot_count"],
        "max_book_level": book_metrics["max_book_level"],
        "book_side_counts": book_metrics["side_counts"],
        "spread_bps": _stats(book_metrics["spread_bps_values"]),
        "latency_sample_count": len(latency_samples),
        "latency_ms": _stats([float(sample["duration_ms"]) for sample in latency_samples]),
    }
    thresholds = {
        "min_completed_samples": max(1, int(min_completed_samples)),
        "min_valid_book_snapshots": max(1, int(min_valid_book_snapshots)),
        "min_latency_samples": max(1, int(min_latency_samples)),
    }
    blockers = _quality_blockers(
        capture=capture,
        sample_quality=sample_quality,
        thresholds=thresholds,
        trade_path=trade_path,
        book_path=book_path,
    )
    ready = not blockers
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_public_l2_tick_sample_quality_no_candidate_no_paper_no_live",
        "status": "public_l2_sample_evidence_ready_research_only"
        if ready
        else "public_l2_sample_evidence_partial_research_only",
        "decision": "use_l2_sample_for_microstructure_feature_diagnostics_only"
        if ready
        else "collect_deeper_public_l2_tick_samples_before_feature_diagnostics",
        "next_required_action": "design_new_microstructure_features_with_event_ledger_validation"
        if ready
        else "collect_deeper_public_l2_tick_samples",
        "source_capture_report": _relpath(capture_path, root) if capture_path.exists() else None,
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "source_files": {
            "agg_trades_samples": _file_status(trade_path, root, row_count=len(trade_rows)),
            "order_book_depth_samples": _file_status(book_path, root, row_count=len(book_rows)),
        },
        "capture_status": str(capture.get("status", "missing") or "missing"),
        "network_called": bool(capture.get("network_called", False)),
        "public_rest_only": bool(capture.get("public_rest_only", False)),
        "bounded_public_rest_sample_only": True,
        "sample_quality": sample_quality,
        "thresholds": thresholds,
        "blockers": blockers,
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
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    }
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "btc_true_scalping_l2_sample_quality_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--capture-report-path", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--min-completed-samples", type=int, default=3)
    parser.add_argument("--min-valid-book-snapshots", type=int, default=1)
    parser.add_argument("--min-latency-samples", type=int, default=2)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_l2_sample_quality_report(
        repo_root=Path(args.repo_root),
        capture_report_path=Path(args.capture_report_path),
        output_root=Path(args.output_root),
        min_completed_samples=args.min_completed_samples,
        min_valid_book_snapshots=args.min_valid_book_snapshots,
        min_latency_samples=args.min_latency_samples,
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") != "public_l2_sample_evidence_ready_research_only":
        raise SystemExit(2)


def _quality_blockers(
    *,
    capture: Mapping[str, Any],
    sample_quality: Mapping[str, Any],
    thresholds: Mapping[str, int],
    trade_path: Path,
    book_path: Path,
) -> list[str]:
    blockers: list[str] = []
    if capture.get("status") != "verified":
        blockers.append("btc_l2_sample_capture_report_not_verified")
    if not bool(capture.get("network_called", False)):
        blockers.append("btc_l2_sample_capture_network_not_called")
    if not bool(capture.get("public_rest_only", False)):
        blockers.append("btc_l2_sample_capture_not_public_rest_only")
    if bool(capture.get("private_endpoint_used", False)):
        blockers.append("btc_l2_sample_capture_private_endpoint_used")
    if bool(capture.get("order_endpoint_used", False)):
        blockers.append("btc_l2_sample_capture_order_endpoint_used")
    if not trade_path.exists():
        blockers.append("btc_l2_sample_agg_trades_file_missing")
    if not book_path.exists():
        blockers.append("btc_l2_sample_order_book_depth_file_missing")
    if int(sample_quality.get("completed_sample_count", 0) or 0) < thresholds["min_completed_samples"]:
        blockers.append("btc_l2_sample_completed_sample_count_below_threshold")
    if int(sample_quality.get("trade_row_count", 0) or 0) <= 0:
        blockers.append("btc_l2_sample_agg_trades_empty")
    if int(sample_quality.get("book_level_row_count", 0) or 0) <= 0:
        blockers.append("btc_l2_sample_order_book_depth_empty")
    if int(sample_quality.get("valid_top_of_book_snapshot_count", 0) or 0) < thresholds["min_valid_book_snapshots"]:
        blockers.append("btc_l2_sample_valid_top_of_book_snapshots_below_threshold")
    if int(sample_quality.get("latency_sample_count", 0) or 0) < thresholds["min_latency_samples"]:
        blockers.append("btc_l2_sample_latency_sample_count_below_threshold")
    blockers.extend(str(item) for item in capture.get("blockers", []) if str(item))
    return _dedupe(blockers)


def _book_metrics(rows: Iterable[Mapping[str, str]]) -> dict[str, Any]:
    snapshots: dict[str, dict[str, list[tuple[int, float]]]] = defaultdict(lambda: {"bid": [], "ask": []})
    side_counts = {"bid": 0, "ask": 0}
    max_book_level = 0
    for row in rows:
        ts = str(row.get("ts", "") or "")
        side = str(row.get("side", "") or "").lower()
        level = _int(row.get("level"))
        price = _float(row.get("price"))
        if not ts or side not in {"bid", "ask"} or level <= 0 or price is None:
            continue
        side_counts[side] += 1
        max_book_level = max(max_book_level, level)
        snapshots[ts][side].append((level, price))
    spread_bps_values: list[float] = []
    for sides in snapshots.values():
        bids = sides.get("bid", [])
        asks = sides.get("ask", [])
        if not bids or not asks:
            continue
        best_bid = max(price for _level, price in bids)
        best_ask = min(price for _level, price in asks)
        midpoint = (best_bid + best_ask) / 2.0
        spread = best_ask - best_bid
        if midpoint > 0 and spread > 0:
            spread_bps_values.append(spread / midpoint * 10_000.0)
    return {
        "valid_top_of_book_snapshot_count": len(spread_bps_values),
        "max_book_level": max_book_level,
        "side_counts": side_counts,
        "spread_bps_values": spread_bps_values,
    }


def _latency_samples(value: object) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return samples
    for item in value:
        if not isinstance(item, Mapping):
            continue
        duration = _float(item.get("duration_ms"))
        if item.get("network_called") is True and duration is not None:
            samples.append({"endpoint": str(item.get("endpoint", "")), "duration_ms": duration})
    return samples


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _file_status(path: Path, root: Path, *, row_count: int) -> dict[str, Any]:
    return {
        "path": _relpath(path, root) if path.exists() else None,
        "exists": path.exists(),
        "row_count": row_count,
    }


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
    }


def _unique_values(rows: Iterable[Mapping[str, str]], key: str) -> set[str]:
    return {str(row.get(key, "") or "") for row in rows if str(row.get(key, "") or "")}


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
        return int(str(value))
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
