#!/usr/bin/env python3
"""Build research-only BTC scalping microstructure model evidence."""

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


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_readiness/latest")
DEFAULT_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
DEFAULT_CAPTURE_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_okx_microstructure_capture_report.json")
MODEL_SCHEMA_VERSION = "btc_true_scalping_microstructure_model_v1"
REPORT_SCHEMA_VERSION = "btc_true_scalping_microstructure_model_report_v1"
SYMBOL = "BTCUSDT"


def build_btc_true_scalping_microstructure_models(
    *,
    repo_root: Path | None = None,
    data_status_path: Path | None = None,
    capture_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    data_status = _read_json(_resolve(root, data_status_path or DEFAULT_DATA_STATUS))
    selected_provider = str(
        _mapping(data_status.get("perpetual_provider_verification")).get("selected_provider", "okx_swap")
        or "okx_swap"
    )
    selected_bundle_id = str(
        _mapping(data_status.get("perpetual_provider_verification")).get(
            "selected_bundle_id", "btc_okx_swap_btcusdt_history_365d_v1"
        )
        or "btc_okx_swap_btcusdt_history_365d_v1"
    )
    bundle_dir = root / "data" / "external" / "btc_perpetual" / selected_provider / "bundles" / selected_bundle_id
    agg_trades_path = bundle_dir / "agg_trades.csv"
    order_book_path = bundle_dir / "order_book_depth.csv"
    capture_path = _resolve(root, capture_report_path or DEFAULT_CAPTURE_REPORT)
    capture_report = _read_json(capture_path)
    book_rows = _read_csv(order_book_path)
    trade_rows = _read_csv(agg_trades_path)

    spread_model = _spread_model(
        generated_at=generated,
        root=root,
        source_path=order_book_path,
        rows=book_rows,
    )
    latency_model = _latency_model(
        generated_at=generated,
        root=root,
        source_path=capture_path,
        capture_report=capture_report,
    )
    queue_model = _queue_model(
        generated_at=generated,
        root=root,
        source_path=order_book_path,
        rows=book_rows,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    spread_path = output_dir / "spread_model.json"
    latency_path = output_dir / "latency_model.json"
    queue_path = output_dir / "queue_position_model.json"
    _write_json(spread_path, spread_model)
    _write_json(latency_path, latency_model)
    _write_json(queue_path, queue_model)

    models = {
        "spread_model": _model_summary(spread_model, spread_path, root),
        "latency_model": _model_summary(latency_model, latency_path, root),
        "queue_position_model": _model_summary(queue_model, queue_path, root),
    }
    blockers = _dedupe(
        [
            blocker
            for model in (spread_model, latency_model, queue_model)
            for blocker in _list_of_strings(model.get("blockers"))
        ]
    )
    all_pass = all(summary["status"] == "pass" for summary in models.values())
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": SYMBOL,
        "status": "pass" if all_pass else "fail",
        "decision": "models_ready_for_manual_review_research_only"
        if all_pass
        else "continue_microstructure_model_building",
        "selected_provider": selected_provider,
        "selected_bundle_id": selected_bundle_id,
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "source_files": {
            "agg_trades": _file_status(agg_trades_path, root, row_count=len(trade_rows)),
            "order_book_depth": _file_status(order_book_path, root, row_count=len(book_rows)),
            "capture_report": _file_status(capture_path, root, row_count=None),
        },
        "models": models,
        "blockers": blockers,
        "guardrails": {
            "research_only": True,
            "production_ready": False,
            "paper_or_live_usable": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "broker_calls_allowed": False,
        },
    }
    _write_json(output_dir / "btc_true_scalping_microstructure_model_report.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-status-path", default=str(DEFAULT_DATA_STATUS))
    parser.add_argument("--capture-report-path", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_microstructure_models(
        repo_root=Path(args.repo_root),
        data_status_path=Path(args.data_status_path),
        capture_report_path=Path(args.capture_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") != "pass":
        raise SystemExit(2)


def _spread_model(*, generated_at: str, root: Path, source_path: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    snapshots = _book_snapshots(rows)
    samples = []
    for ts, sides in sorted(snapshots.items()):
        bids = sides.get("bid", [])
        asks = sides.get("ask", [])
        if not bids or not asks:
            continue
        best_bid = max(bids, key=lambda item: item["price"])
        best_ask = min(asks, key=lambda item: item["price"])
        midpoint = (best_bid["price"] + best_ask["price"]) / 2.0
        spread = best_ask["price"] - best_bid["price"]
        if midpoint <= 0 or spread <= 0:
            continue
        samples.append(
            {
                "ts": ts,
                "best_bid": best_bid["price"],
                "best_ask": best_ask["price"],
                "midpoint": midpoint,
                "spread_abs": spread,
                "spread_bps": spread / midpoint * 10_000.0,
            }
        )
    blockers = [] if samples else ["btc_spread_model_no_valid_order_book_snapshots"]
    spread_bps = [float(item["spread_bps"]) for item in samples]
    latest = samples[-1] if samples else {}
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_id": "btc_okx_public_rest_spread_model_v1",
        "model_type": "spread_model",
        "generated_at": generated_at,
        "asset": "btc",
        "symbol": SYMBOL,
        "status": "pass" if not blockers else "fail",
        "evidence_grade": "public_rest_micro_sample_research_only",
        "source_file": _relpath(source_path, root) if source_path.exists() else None,
        "sample_count": len(samples),
        "latest_snapshot": latest,
        "spread_bps": _stats(spread_bps),
        "production_ready": False,
        "paper_or_live_usable": False,
        "blockers": blockers,
    }


def _latency_model(
    *,
    generated_at: str,
    root: Path,
    source_path: Path,
    capture_report: Mapping[str, Any],
) -> dict[str, Any]:
    samples = [
        {
            "endpoint": str(sample.get("endpoint", "")),
            "duration_ms": float(sample.get("duration_ms")),
        }
        for sample in _list_of_mappings(capture_report.get("latency_samples"))
        if sample.get("network_called") is True and _float(sample.get("duration_ms")) is not None
    ]
    durations = [sample["duration_ms"] for sample in samples]
    blockers = [] if durations else ["btc_latency_model_no_public_rest_latency_samples"]
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_id": "btc_okx_public_rest_latency_model_v1",
        "model_type": "latency_model",
        "generated_at": generated_at,
        "asset": "btc",
        "symbol": SYMBOL,
        "status": "pass" if not blockers else "fail",
        "evidence_grade": "public_rest_market_data_latency_research_only",
        "latency_scope": "public_rest_market_data_observation_not_order_latency",
        "source_file": _relpath(source_path, root) if source_path.exists() else None,
        "sample_count": len(durations),
        "duration_ms": _stats(durations),
        "samples": samples,
        "private_order_latency_verified": False,
        "production_ready": False,
        "paper_or_live_usable": False,
        "blockers": blockers,
    }


def _queue_model(*, generated_at: str, root: Path, source_path: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    snapshots = _book_snapshots(rows)
    samples = []
    for ts, sides in sorted(snapshots.items()):
        bids = sides.get("bid", [])
        asks = sides.get("ask", [])
        if not bids or not asks:
            continue
        best_bid = max(bids, key=lambda item: item["price"])
        best_ask = min(asks, key=lambda item: item["price"])
        samples.append(
            {
                "ts": ts,
                "best_bid_visible_size": best_bid["size"],
                "best_bid_order_count": best_bid["order_count"],
                "best_ask_visible_size": best_ask["size"],
                "best_ask_order_count": best_ask["order_count"],
            }
        )
    blockers = [] if samples else ["btc_queue_position_model_no_valid_order_book_snapshots"]
    bid_sizes = [float(item["best_bid_visible_size"]) for item in samples]
    ask_sizes = [float(item["best_ask_visible_size"]) for item in samples]
    return {
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_id": "btc_okx_public_rest_queue_position_model_v1",
        "model_type": "queue_position_model",
        "generated_at": generated_at,
        "asset": "btc",
        "symbol": SYMBOL,
        "status": "pass" if not blockers else "fail",
        "evidence_grade": "visible_book_depth_research_only",
        "source_file": _relpath(source_path, root) if source_path.exists() else None,
        "sample_count": len(samples),
        "queue_assumption": "conservative_join_back_of_visible_best_level_queue",
        "best_bid_visible_size": _stats(bid_sizes),
        "best_ask_visible_size": _stats(ask_sizes),
        "latest_snapshot": samples[-1] if samples else {},
        "production_ready": False,
        "paper_or_live_usable": False,
        "blockers": blockers,
    }


def _book_snapshots(rows: Iterable[Mapping[str, str]]) -> dict[str, dict[str, list[dict[str, float]]]]:
    snapshots: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(lambda: {"bid": [], "ask": []})
    for row in rows:
        side = str(row.get("side", "")).lower()
        ts = str(row.get("ts") or row.get("timestamp") or "")
        price = _float(row.get("price"))
        size = _float(row.get("size"))
        if side not in {"bid", "ask"} or not ts or price is None or size is None:
            continue
        order_count = _float(row.get("order_count")) or 0.0
        snapshots[ts][side].append({"price": price, "size": size, "order_count": order_count})
    return dict(snapshots)


def _model_summary(model: Mapping[str, Any], path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": _relpath(path, root),
        "schema_version": str(model.get("schema_version", "")),
        "status": str(model.get("status", "missing") or "missing"),
        "model_id": str(model.get("model_id", "")),
        "evidence_grade": str(model.get("evidence_grade", "")),
        "sample_count": int(model.get("sample_count", 0) or 0),
        "production_ready": bool(model.get("production_ready", False)),
        "paper_or_live_usable": bool(model.get("paper_or_live_usable", False)),
        "blockers": _list_of_strings(model.get("blockers")),
    }


def _file_status(path: Path, root: Path, *, row_count: int | None) -> dict[str, Any]:
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
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        return float(value)
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
