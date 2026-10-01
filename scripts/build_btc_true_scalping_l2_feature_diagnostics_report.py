#!/usr/bin/env python3
"""Build research-only diagnostics for BTC L2/tick microstructure features."""

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
DEFAULT_SAMPLE_QUALITY = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_sample_quality_report.json")
DEFAULT_CAPTURE_REPORT = Path(
    "artifacts/btc_scalping_readiness/latest/btc_okx_l2_microstructure_sample_capture_report.json"
)
DEFAULT_REDESIGN_REPORT = Path(
    "artifacts/btc_scalping_event_ledger/latest/btc_true_scalping_event_definition_redesign_report.json"
)
TRADE_SAMPLE_FILE = "agg_trades_samples.csv"
BOOK_SAMPLE_FILE = "order_book_depth_samples.csv"
REPORT_SCHEMA_VERSION = "btc_true_scalping_l2_feature_diagnostics_report_v1"


def build_btc_true_scalping_l2_feature_diagnostics_report(
    *,
    repo_root: Path | None = None,
    sample_quality_path: Path | None = None,
    capture_report_path: Path | None = None,
    redesign_report_path: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).isoformat()
    sample_quality_file = _resolve(root, sample_quality_path or DEFAULT_SAMPLE_QUALITY)
    capture_file = _resolve(root, capture_report_path or DEFAULT_CAPTURE_REPORT)
    redesign_file = _resolve(root, redesign_report_path or DEFAULT_REDESIGN_REPORT)
    sample_quality = _read_json(sample_quality_file)
    capture = _read_json(capture_file)
    redesign = _read_json(redesign_file)
    selected_bundle_dir = str(capture.get("selected_bundle_dir") or sample_quality.get("selected_bundle_dir") or "")
    bundle_dir = _resolve(root, Path(selected_bundle_dir)) if selected_bundle_dir else root / "missing"
    trade_path = bundle_dir / TRADE_SAMPLE_FILE
    book_path = bundle_dir / BOOK_SAMPLE_FILE
    trade_rows = _read_csv(trade_path)
    book_rows = _read_csv(book_path)
    book_feature_rows = _book_feature_rows(book_rows)
    trade_flow_rows = _trade_flow_rows(trade_rows)
    joined = _join_by_sample(book_feature_rows, trade_flow_rows)
    historical_alignment = _historical_alignment(
        sample_times=_sample_capture_times([*trade_rows, *book_rows]),
        redesign=redesign,
    )
    feature_diagnostics = _feature_diagnostics(book_feature_rows=book_feature_rows, trade_flow_rows=trade_flow_rows, joined=joined)
    feature_candidates = _feature_candidates(feature_diagnostics=feature_diagnostics, historical_alignment=historical_alignment)
    blockers = _blockers(
        sample_quality=sample_quality,
        book_feature_rows=book_feature_rows,
        trade_flow_rows=trade_flow_rows,
        historical_alignment=historical_alignment,
    )
    status = (
        "l2_feature_diagnostics_ready_research_only_backtest_blocked"
        if book_feature_rows and trade_flow_rows and sample_quality.get("status") == "public_l2_sample_evidence_ready_research_only"
        else "l2_feature_diagnostics_blocked_missing_sample_evidence"
    )
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_l2_feature_diagnostics_no_candidate_no_paper_no_live",
        "status": status,
        "decision": "collect_timestamp_aligned_l2_history_before_event_ledger_feature_validation",
        "next_required_action": "collect_timestamp_aligned_l2_tick_history_or_build_1m_only_feature_redesign",
        "source_reports": {
            "sample_quality": _relpath(sample_quality_file, root) if sample_quality_file.exists() else None,
            "capture_report": _relpath(capture_file, root) if capture_file.exists() else None,
            "event_definition_redesign": _relpath(redesign_file, root) if redesign_file.exists() else None,
        },
        "selected_bundle_dir": _relpath(bundle_dir, root),
        "source_files": {
            "agg_trades_samples": _file_status(trade_path, root, row_count=len(trade_rows)),
            "order_book_depth_samples": _file_status(book_path, root, row_count=len(book_rows)),
        },
        "historical_alignment": historical_alignment,
        "feature_diagnostics": feature_diagnostics,
        "feature_candidates": feature_candidates,
        "blockers": blockers,
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
    (output_dir / "btc_true_scalping_l2_feature_diagnostics_report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--sample-quality-path", default=str(DEFAULT_SAMPLE_QUALITY))
    parser.add_argument("--capture-report-path", default=str(DEFAULT_CAPTURE_REPORT))
    parser.add_argument("--redesign-report-path", default=str(DEFAULT_REDESIGN_REPORT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_l2_feature_diagnostics_report(
        repo_root=Path(args.repo_root),
        sample_quality_path=Path(args.sample_quality_path),
        capture_report_path=Path(args.capture_report_path),
        redesign_report_path=Path(args.redesign_report_path),
        output_root=Path(args.output_root),
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("status") != "l2_feature_diagnostics_ready_research_only_backtest_blocked":
        raise SystemExit(2)


def _book_feature_rows(rows: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    snapshots: dict[tuple[str, str], dict[str, list[dict[str, float]]]] = defaultdict(lambda: {"bid": [], "ask": []})
    captured_at_by_key: dict[tuple[str, str], str] = {}
    for row in rows:
        sample_index = str(row.get("sample_index", "") or "")
        ts = str(row.get("ts", "") or "")
        side = str(row.get("side", "") or "").lower()
        level = _int(row.get("level"))
        price = _float(row.get("price"))
        size = _float(row.get("size"))
        if not sample_index or not ts or side not in {"bid", "ask"} or level <= 0 or price is None or size is None:
            continue
        key = (sample_index, ts)
        captured_at_by_key[key] = str(row.get("sample_captured_at", "") or "")
        snapshots[key][side].append({"level": float(level), "price": price, "size": size})
    feature_rows: list[dict[str, Any]] = []
    for (sample_index, ts), sides in sorted(snapshots.items(), key=lambda item: (int(item[0][0]), int(item[0][1]))):
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
        top_bid_size = best_bid["size"]
        top_ask_size = best_ask["size"]
        microprice = _microprice(best_bid["price"], best_ask["price"], top_bid_size, top_ask_size)
        row = {
            "sample_index": sample_index,
            "book_ts": ts,
            "sample_captured_at": captured_at_by_key.get((sample_index, ts), ""),
            "best_bid": best_bid["price"],
            "best_ask": best_ask["price"],
            "midpoint": midpoint,
            "spread_bps": spread / midpoint * 10_000.0,
            "microprice_edge_bps": ((microprice - midpoint) / midpoint * 10_000.0) if microprice is not None else None,
            "max_book_level": int(max([item["level"] for item in bids + asks], default=0)),
        }
        for depth in (1, 5, 10, 50):
            bid_depth = sum(item["size"] for item in bids if item["level"] <= depth)
            ask_depth = sum(item["size"] for item in asks if item["level"] <= depth)
            row[f"bid_depth_top{depth}"] = bid_depth
            row[f"ask_depth_top{depth}"] = ask_depth
            row[f"depth_imbalance_top{depth}"] = _imbalance(bid_depth, ask_depth)
        feature_rows.append(row)
    return feature_rows


def _trade_flow_rows(rows: Iterable[Mapping[str, str]]) -> list[dict[str, Any]]:
    samples: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    captured_at: dict[str, str] = {}
    for row in rows:
        sample_index = str(row.get("sample_index", "") or "")
        if not sample_index:
            continue
        samples[sample_index].append(row)
        captured_at[sample_index] = str(row.get("sample_captured_at", "") or "")
    out: list[dict[str, Any]] = []
    for sample_index, sample_rows in sorted(samples.items(), key=lambda item: int(item[0])):
        buy_size = sum(_float(row.get("size")) or 0.0 for row in sample_rows if str(row.get("side", "")).lower() == "buy")
        sell_size = sum(_float(row.get("size")) or 0.0 for row in sample_rows if str(row.get("side", "")).lower() == "sell")
        buy_notional = sum((_float(row.get("price")) or 0.0) * (_float(row.get("size")) or 0.0) for row in sample_rows if str(row.get("side", "")).lower() == "buy")
        sell_notional = sum((_float(row.get("price")) or 0.0) * (_float(row.get("size")) or 0.0) for row in sample_rows if str(row.get("side", "")).lower() == "sell")
        timestamps = sorted(_int(row.get("ts")) for row in sample_rows if _int(row.get("ts")) > 0)
        out.append(
            {
                "sample_index": sample_index,
                "sample_captured_at": captured_at.get(sample_index, ""),
                "trade_count": len(sample_rows),
                "buy_trade_count": sum(1 for row in sample_rows if str(row.get("side", "")).lower() == "buy"),
                "sell_trade_count": sum(1 for row in sample_rows if str(row.get("side", "")).lower() == "sell"),
                "buy_size": buy_size,
                "sell_size": sell_size,
                "buy_notional": buy_notional,
                "sell_notional": sell_notional,
                "trade_size_imbalance": _imbalance(buy_size, sell_size),
                "trade_notional_imbalance": _imbalance(buy_notional, sell_notional),
                "first_trade_ts": timestamps[0] if timestamps else None,
                "last_trade_ts": timestamps[-1] if timestamps else None,
            }
        )
    return out


def _join_by_sample(book_feature_rows: list[Mapping[str, Any]], trade_flow_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    trade_by_sample = {str(row.get("sample_index", "")): row for row in trade_flow_rows}
    joined: list[dict[str, Any]] = []
    for book in book_feature_rows:
        sample_index = str(book.get("sample_index", ""))
        trade = trade_by_sample.get(sample_index, {})
        if not trade:
            continue
        joined.append(
            {
                "sample_index": sample_index,
                "spread_bps": book.get("spread_bps"),
                "microprice_edge_bps": book.get("microprice_edge_bps"),
                "depth_imbalance_top1": book.get("depth_imbalance_top1"),
                "depth_imbalance_top5": book.get("depth_imbalance_top5"),
                "depth_imbalance_top10": book.get("depth_imbalance_top10"),
                "depth_imbalance_top50": book.get("depth_imbalance_top50"),
                "trade_size_imbalance": trade.get("trade_size_imbalance"),
                "trade_notional_imbalance": trade.get("trade_notional_imbalance"),
            }
        )
    return joined


def _feature_diagnostics(
    *,
    book_feature_rows: list[Mapping[str, Any]],
    trade_flow_rows: list[Mapping[str, Any]],
    joined: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "book_snapshot_count": len(book_feature_rows),
        "trade_flow_sample_count": len(trade_flow_rows),
        "joined_sample_count": len(joined),
        "max_book_level": max([int(row.get("max_book_level", 0) or 0) for row in book_feature_rows], default=0),
        "spread_bps": _stats([row.get("spread_bps") for row in book_feature_rows]),
        "microprice_edge_bps": _stats([row.get("microprice_edge_bps") for row in book_feature_rows]),
        "depth_imbalance_top1": _stats([row.get("depth_imbalance_top1") for row in book_feature_rows]),
        "depth_imbalance_top5": _stats([row.get("depth_imbalance_top5") for row in book_feature_rows]),
        "depth_imbalance_top10": _stats([row.get("depth_imbalance_top10") for row in book_feature_rows]),
        "depth_imbalance_top50": _stats([row.get("depth_imbalance_top50") for row in book_feature_rows]),
        "trade_size_imbalance": _stats([row.get("trade_size_imbalance") for row in trade_flow_rows]),
        "trade_notional_imbalance": _stats([row.get("trade_notional_imbalance") for row in trade_flow_rows]),
        "book_trade_pressure_proxy": _stats(
            [
                _average_optional(row.get("depth_imbalance_top5"), row.get("trade_notional_imbalance"))
                for row in joined
            ]
        ),
    }


def _feature_candidates(
    *,
    feature_diagnostics: Mapping[str, Any],
    historical_alignment: Mapping[str, Any],
) -> list[dict[str, Any]]:
    usable = bool(historical_alignment.get("timestamp_aligned_l2_history_available", False))
    reason = "timestamp_aligned_l2_history_missing_for_backtest"
    candidates = [
        ("spread_filter_bps", "Filter entries when observed public top-of-book spread exceeds the calibrated sample band."),
        ("depth_imbalance_top5", "Require visible bid/ask depth pressure to agree with the proposed entry side."),
        ("microprice_edge_bps", "Use microprice displacement from midpoint as a short-horizon pressure proxy."),
        ("trade_flow_imbalance", "Use recent public trade aggressor imbalance as confirmation."),
        ("book_trade_pressure_proxy", "Combine depth imbalance and trade-flow imbalance into a conservative pressure score."),
    ]
    return [
        {
            "feature_id": feature_id,
            "diagnostic_status": "observed_in_bounded_sample" if feature_diagnostics else "missing",
            "description": description,
            "sample_observed": True,
            "event_ledger_backtest_usable": usable,
            "backtest_blocker": None if usable else reason,
        }
        for feature_id, description in candidates
    ]


def _historical_alignment(*, sample_times: list[datetime], redesign: Mapping[str, Any]) -> dict[str, Any]:
    data_context = _mapping(redesign.get("data_context"))
    backtest_start = _parse_dt(data_context.get("start"))
    backtest_end = _parse_dt(data_context.get("end"))
    sample_start = min(sample_times) if sample_times else None
    sample_end = max(sample_times) if sample_times else None
    overlaps = bool(sample_start and sample_end and backtest_start and backtest_end and sample_start <= backtest_end and sample_end >= backtest_start)
    return {
        "status": "not_timestamp_aligned_to_backtest",
        "sample_capture_start": _dt_text(sample_start),
        "sample_capture_end": _dt_text(sample_end),
        "backtest_start": _dt_text(backtest_start),
        "backtest_end": _dt_text(backtest_end),
        "overlaps_backtest_window": overlaps,
        "timestamp_aligned_l2_history_available": False,
        "causal_event_ledger_join_allowed": False,
        "reason": "bounded_public_rest_samples_are_current_observations_not_historical_l2_covering_the_backtest_window",
    }


def _blockers(
    *,
    sample_quality: Mapping[str, Any],
    book_feature_rows: list[Mapping[str, Any]],
    trade_flow_rows: list[Mapping[str, Any]],
    historical_alignment: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if sample_quality.get("status") != "public_l2_sample_evidence_ready_research_only":
        blockers.append("btc_l2_sample_quality_not_ready")
    if not book_feature_rows:
        blockers.append("btc_l2_feature_diagnostics_no_valid_book_snapshots")
    if not trade_flow_rows:
        blockers.append("btc_l2_feature_diagnostics_no_trade_flow_rows")
    blockers.append("btc_l2_features_bounded_sample_not_historical_l2")
    if not bool(historical_alignment.get("overlaps_backtest_window", False)):
        blockers.append("btc_l2_features_not_timestamp_aligned_to_historical_backtest")
    if not bool(historical_alignment.get("timestamp_aligned_l2_history_available", False)):
        blockers.append("btc_l2_feature_event_ledger_validation_blocked_without_timestamp_aligned_history")
    return _dedupe(blockers)


def _sample_capture_times(rows: Iterable[Mapping[str, str]]) -> list[datetime]:
    times = []
    for row in rows:
        parsed = _parse_dt(row.get("sample_captured_at"))
        if parsed is not None:
            times.append(parsed)
    return times


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
    return {"path": _relpath(path, root) if path.exists() else None, "exists": path.exists(), "row_count": row_count}


def _stats(values: Iterable[object]) -> dict[str, float | None]:
    parsed = [_float(value) for value in values]
    clean = [value for value in parsed if value is not None]
    if not clean:
        return {"min": None, "max": None, "mean": None, "median": None}
    return {"min": min(clean), "max": max(clean), "mean": statistics.mean(clean), "median": statistics.median(clean)}


def _microprice(best_bid: float, best_ask: float, bid_size: float, ask_size: float) -> float | None:
    total = bid_size + ask_size
    if total <= 0:
        return None
    return (best_ask * bid_size + best_bid * ask_size) / total


def _imbalance(left: float, right: float) -> float | None:
    total = left + right
    if total <= 0:
        return None
    return (left - right) / total


def _average_optional(left: object, right: object) -> float | None:
    parsed = [value for value in (_float(left), _float(right)) if value is not None]
    return statistics.mean(parsed) if parsed else None


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


def _dt_text(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


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
