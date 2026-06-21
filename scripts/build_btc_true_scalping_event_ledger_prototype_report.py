#!/usr/bin/env python3
"""Build a research-only BTC 1m true-scalping event-ledger prototype."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_scalping_event_ledger/latest")
DEFAULT_DESIGN_REPORT = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_research_design_report.json")
DEFAULT_READINESS = Path("artifacts/btc_scalping_readiness/latest/btc_true_scalping_microstructure_readiness_report.json")
DEFAULT_SPREAD_MODEL = Path("artifacts/btc_scalping_readiness/latest/spread_model.json")
DEFAULT_LATENCY_MODEL = Path("artifacts/btc_scalping_readiness/latest/latency_model.json")
DEFAULT_QUEUE_MODEL = Path("artifacts/btc_scalping_readiness/latest/queue_position_model.json")
DEFAULT_DB_PATH = Path("data/market_data.sqlite")
DEFAULT_MANIFEST_ROOT = Path("data/manifests")
SYMBOL = "BTCUSDT"
EXCHANGE = "binance_spot"
INTERVAL = "1m"
STRATEGY_ID = "btc_true_scalp_liquidity_reclaim_research_v0"
VARIANT_ID = "pullback_reclaim_1m_public_microstructure_proxy_v0"


def build_btc_true_scalping_event_ledger_prototype_report(
    *,
    repo_root: Path | None = None,
    design_report_path: Path | None = None,
    readiness_path: Path | None = None,
    spread_model_path: Path | None = None,
    latency_model_path: Path | None = None,
    queue_model_path: Path | None = None,
    db_path: Path | None = None,
    manifest_root: Path | None = None,
    output_root: Path | None = None,
    generated_at: str | None = None,
    history_days: int = 180,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    run_dir = output_dir / "prototype_run"
    design_file = _resolve(root, design_report_path or DEFAULT_DESIGN_REPORT)
    readiness_file = _resolve(root, readiness_path or DEFAULT_READINESS)
    spread_file = _resolve(root, spread_model_path or DEFAULT_SPREAD_MODEL)
    latency_file = _resolve(root, latency_model_path or DEFAULT_LATENCY_MODEL)
    queue_file = _resolve(root, queue_model_path or DEFAULT_QUEUE_MODEL)
    sqlite_file = _resolve(root, db_path or DEFAULT_DB_PATH)
    manifest_dir = _resolve(root, manifest_root or DEFAULT_MANIFEST_ROOT)
    design = _read_json(design_file)
    readiness = _read_json(readiness_file)
    spread_model = _read_json(spread_file)
    latency_model = _read_json(latency_file)
    queue_model = _read_json(queue_file)
    blockers = _preflight_blockers(
        design=design,
        readiness=readiness,
        spread_model=spread_model,
        latency_model=latency_model,
        queue_model=queue_model,
        sqlite_file=sqlite_file,
    )
    if blockers:
        return _blocked_report(
            generated_at=generated,
            root=root,
            output_dir=output_dir,
            source_reports={
                "research_design": design_file,
                "microstructure_readiness": readiness_file,
                "spread_model": spread_file,
                "latency_model": latency_file,
                "queue_position_model": queue_file,
            },
            blockers=blockers,
        )

    frame = _load_klines(sqlite_file, history_days=history_days)
    params = {
        "history_days": int(history_days),
        "pullback_return_3m_threshold": -0.003,
        "volume_median_window": 60,
        "volatility_window": 60,
        "volatility_median_window": 1440,
        "hold_minutes": 3,
        "min_gap_bars": 3,
    }
    spread_bps = _nested_float(spread_model, ("spread_bps", "median"), default=0.0)
    latency_ms = _nested_float(latency_model, ("duration_ms", "median"), default=0.0)
    latency_penalty_bps = min(2.0, max(0.0, latency_ms / 1000.0))
    slippage_bps_each_side = max(0.01, spread_bps / 2.0) + latency_penalty_bps
    fee_bps_each_side = 5.0
    event_objects, fill_ledger = _simulate_event_ledger(
        frame=frame,
        params=params,
        spread_bps=spread_bps,
        latency_ms=latency_ms,
        slippage_bps_each_side=slippage_bps_each_side,
        fee_bps_each_side=fee_bps_each_side,
        queue_assumption=str(queue_model.get("queue_assumption", "visible_book_depth_research_only")),
    )
    metrics = _metrics(fill_ledger)
    gate = _gate(metrics)
    status = "event_ledger_research_gate_passed_candidate_still_locked" if gate["passed"] else "event_ledger_research_gate_failed"
    blockers = _gate_blockers(gate)
    blockers.append("btc_true_scalping_event_ledger_candidate_generation_locked")
    blockers.append("btc_true_scalping_event_ledger_paper_live_locked")
    run_dir.mkdir(parents=True, exist_ok=True)
    event_objects_path = run_dir / "event_objects.csv"
    fill_ledger_path = run_dir / "fill_ledger.csv"
    manifest_path = run_dir / "run_manifest.json"
    _write_csv(event_objects_path, event_objects)
    _write_csv(fill_ledger_path, fill_ledger)
    data_version = _latest_1m_data_version(manifest_dir)
    manifest = {
        "schema_version": "btc_true_scalping_event_ledger_manifest_v1",
        "generated_at": generated,
        "run_id": "btc_true_scalping_event_ledger_prototype_v0",
        "strategy_id": STRATEGY_ID,
        "variant_id": VARIANT_ID,
        "data_version": data_version,
        "strategy_version": f"{STRATEGY_ID}:research_only_event_ledger_prototype_v0",
        "params": params,
        "params_hash": _sha256_json(params),
        "cost_model": {
            "name": "public_microstructure_proxy_taker_10bps_round_trip",
            "fee_bps_each_side": fee_bps_each_side,
            "spread_bps": spread_bps,
            "latency_penalty_bps_each_side": latency_penalty_bps,
        },
        "slippage_model": {
            "name": "spread_half_plus_public_rest_latency_penalty",
            "slippage_bps_each_side": slippage_bps_each_side,
        },
        "commit_hash": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }
    _write_json(manifest_path, manifest)
    payload = {
        "schema_version": "btc_true_scalping_event_ledger_prototype_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": STRATEGY_ID,
        "variant_id": VARIANT_ID,
        "scope": "research_only_1m_scalping_event_ledger_no_candidate_no_paper_no_live",
        "status": status,
        "decision": "reject_or_redesign_scalping_hypothesis" if not gate["passed"] else "manual_review_before_candidate_generation",
        "next_required_action": "redesign_true_scalping_event_definition_before_strategy_skeleton"
        if not gate["passed"]
        else "manual_review_before_any_candidate_generation",
        "source_reports": {
            "research_design": _relpath(design_file, root),
            "microstructure_readiness": _relpath(readiness_file, root),
            "spread_model": _relpath(spread_file, root),
            "latency_model": _relpath(latency_file, root),
            "queue_position_model": _relpath(queue_file, root),
        },
        "run_dir": _relpath(run_dir, root),
        "artifacts": {
            "event_objects": _relpath(event_objects_path, root),
            "fill_ledger": _relpath(fill_ledger_path, root),
            "run_manifest": _relpath(manifest_path, root),
        },
        "data_context": {
            "source": "sqlite_market_klines",
            "exchange": EXCHANGE,
            "interval": INTERVAL,
            "data_version": data_version,
            "history_days": int(history_days),
            "row_count": int(len(frame)),
            "start": str(frame["open_time"].iloc[0]) if not frame.empty else None,
            "end": str(frame["open_time"].iloc[-1]) if not frame.empty else None,
        },
        "event_definition": {
            "entry_timestamp_field": "entry_timestamp",
            "trigger_state_field": "trigger_state",
            "context_state_field": "context_state",
            "label_horizon_seconds": int(params["hold_minutes"] * 60),
            "event_count": len(event_objects),
            "simulated_order_intent_only": True,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
        },
        "metrics": metrics,
        "gate": gate,
        "blockers": _dedupe(blockers),
        "manifest": manifest,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "pnl_from_fill_ledger": True,
        },
    }
    _write_json(output_dir / "btc_true_scalping_event_ledger_prototype_report.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--design-report-path", default=str(DEFAULT_DESIGN_REPORT))
    parser.add_argument("--readiness-path", default=str(DEFAULT_READINESS))
    parser.add_argument("--spread-model-path", default=str(DEFAULT_SPREAD_MODEL))
    parser.add_argument("--latency-model-path", default=str(DEFAULT_LATENCY_MODEL))
    parser.add_argument("--queue-model-path", default=str(DEFAULT_QUEUE_MODEL))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--history-days", type=int, default=180)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_event_ledger_prototype_report(
        repo_root=Path(args.repo_root),
        design_report_path=Path(args.design_report_path),
        readiness_path=Path(args.readiness_path),
        spread_model_path=Path(args.spread_model_path),
        latency_model_path=Path(args.latency_model_path),
        queue_model_path=Path(args.queue_model_path),
        db_path=Path(args.db_path),
        manifest_root=Path(args.manifest_root),
        output_root=Path(args.output_root),
        history_days=args.history_days,
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def _preflight_blockers(
    *,
    design: Mapping[str, Any],
    readiness: Mapping[str, Any],
    spread_model: Mapping[str, Any],
    latency_model: Mapping[str, Any],
    queue_model: Mapping[str, Any],
    sqlite_file: Path,
) -> list[str]:
    blockers: list[str] = []
    if str(design.get("status", "")) != "research_only_scalping_design_ready_for_event_ledger_prototype":
        blockers.append("btc_true_scalping_design_not_ready")
    if not bool(design.get("research_only_event_ledger_prototype_allowed", False)):
        blockers.append("btc_true_scalping_event_ledger_prototype_not_allowed")
    if str(readiness.get("status", "")) != "microstructure_evidence_ready_research_only":
        blockers.append("btc_true_scalping_microstructure_readiness_not_passed")
    if str(spread_model.get("status", "")) != "pass":
        blockers.append("btc_true_scalping_spread_model_not_pass")
    if str(latency_model.get("status", "")) != "pass":
        blockers.append("btc_true_scalping_latency_model_not_pass")
    if str(queue_model.get("status", "")) != "pass":
        blockers.append("btc_true_scalping_queue_model_not_pass")
    if not sqlite_file.exists():
        blockers.append("btc_true_scalping_sqlite_market_data_missing")
    return blockers


def _blocked_report(
    *,
    generated_at: str,
    root: Path,
    output_dir: Path,
    source_reports: Mapping[str, Path],
    blockers: list[str],
) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_true_scalping_event_ledger_prototype_report_v1",
        "generated_at": generated_at,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": STRATEGY_ID,
        "variant_id": VARIANT_ID,
        "scope": "research_only_1m_scalping_event_ledger_no_candidate_no_paper_no_live",
        "status": "event_ledger_research_gate_blocked",
        "decision": "repair_preflight_before_scalping_event_ledger",
        "next_required_action": "repair_preflight_before_scalping_event_ledger",
        "source_reports": {
            name: _relpath(path, root) if path.exists() else None for name, path in source_reports.items()
        },
        "run_dir": None,
        "artifacts": {"event_objects": None, "fill_ledger": None, "run_manifest": None},
        "data_context": {"source": "sqlite_market_klines", "exchange": EXCHANGE, "interval": INTERVAL},
        "event_definition": {
            "entry_timestamp_field": "entry_timestamp",
            "trigger_state_field": "trigger_state",
            "context_state_field": "context_state",
            "label_horizon_seconds": 0,
            "event_count": 0,
            "simulated_order_intent_only": True,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
        },
        "metrics": _empty_metrics(),
        "gate": {"passed": False, "status": "candidate_gate_failed", "checks": {}, "thresholds": {}},
        "blockers": _dedupe(blockers),
        "manifest": {},
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "real_orders_created": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "pnl_from_fill_ledger": True,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "btc_true_scalping_event_ledger_prototype_report.json", payload)
    return payload


def _load_klines(db_path: Path, *, history_days: int) -> pd.DataFrame:
    with sqlite3.connect(str(db_path)) as connection:
        end_ms = connection.execute(
            """
            SELECT MAX(open_time_ms)
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ?
            """,
            (EXCHANGE, SYMBOL, INTERVAL),
        ).fetchone()[0]
        if end_ms is None:
            return pd.DataFrame()
        start_ms = int(end_ms) - int(history_days) * 86_400_000
        frame = pd.read_sql_query(
            """
            SELECT open_time_ms, open_time, open, high, low, close, volume, trade_count
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ? AND open_time_ms >= ?
            ORDER BY open_time_ms
            """,
            connection,
            params=(EXCHANGE, SYMBOL, INTERVAL, start_ms),
        )
    return frame


def _simulate_event_ledger(
    *,
    frame: pd.DataFrame,
    params: Mapping[str, Any],
    spread_bps: float,
    latency_ms: float,
    slippage_bps_each_side: float,
    fee_bps_each_side: float,
    queue_assumption: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if frame.empty:
        return [], []
    data = frame.copy()
    data["ret1"] = data["close"].pct_change()
    data["ret3"] = data["close"] / data["close"].shift(3) - 1.0
    vol60 = data["ret1"].rolling(int(params["volatility_window"])).std().shift(1)
    vol_median = vol60.rolling(int(params["volatility_median_window"])).median().shift(1)
    volume_median = data["volume"].rolling(int(params["volume_median_window"])).median().shift(1)
    signal = (
        (data["ret3"] <= float(params["pullback_return_3m_threshold"]))
        & (data["close"] > data["open"])
        & (data["volume"] > volume_median)
        & (vol60 > vol_median)
    )
    indices = list(data.index[signal])
    event_objects: list[dict[str, Any]] = []
    fill_ledger: list[dict[str, Any]] = []
    last_signal_index = -10_000
    hold_minutes = int(params["hold_minutes"])
    min_gap = int(params["min_gap_bars"])
    for signal_index in indices:
        if int(signal_index) <= last_signal_index + min_gap:
            continue
        entry_index = int(signal_index) + 1
        exit_index = entry_index + hold_minutes
        if exit_index >= len(data):
            continue
        last_signal_index = int(signal_index)
        event_id = f"btc-scalp-proto-{len(event_objects) + 1:06d}"
        order_intent_id = f"{event_id}-intent"
        signal_row = data.iloc[int(signal_index)]
        entry_row = data.iloc[entry_index]
        exit_row = data.iloc[exit_index]
        entry_reference = float(entry_row["open"])
        exit_reference = float(exit_row["open"])
        qty = 1.0
        entry_fill = entry_reference * (1.0 + slippage_bps_each_side / 10_000.0)
        exit_fill = exit_reference * (1.0 - slippage_bps_each_side / 10_000.0)
        entry_fee = entry_fill * qty * fee_bps_each_side / 10_000.0
        exit_fee = exit_fill * qty * fee_bps_each_side / 10_000.0
        fill_ledger.extend(
            [
                {
                    "fill_id": f"{event_id}-fill-entry",
                    "event_id": event_id,
                    "order_intent_id": order_intent_id,
                    "timestamp": str(entry_row["open_time"]),
                    "side": "buy",
                    "quantity": qty,
                    "reference_price": entry_reference,
                    "fill_price": entry_fill,
                    "fee": entry_fee,
                    "cash_flow": -(entry_fill * qty + entry_fee),
                    "liquidity": "simulated_conservative_taker",
                    "simulated": True,
                },
                {
                    "fill_id": f"{event_id}-fill-exit",
                    "event_id": event_id,
                    "order_intent_id": order_intent_id,
                    "timestamp": str(exit_row["open_time"]),
                    "side": "sell",
                    "quantity": qty,
                    "reference_price": exit_reference,
                    "fill_price": exit_fill,
                    "fee": exit_fee,
                    "cash_flow": exit_fill * qty - exit_fee,
                    "liquidity": "simulated_conservative_taker",
                    "simulated": True,
                },
            ]
        )
        event_objects.append(
            {
                "event_id": event_id,
                "event_timestamp": str(signal_row["open_time"]),
                "entry_timestamp": str(entry_row["open_time"]),
                "exit_timestamp": str(exit_row["open_time"]),
                "order_intent_id": order_intent_id,
                "trigger_state": "three_minute_pullback_reclaim_high_volume_high_volatility",
                "context_state": "coarse_intraday_drift_guard_context_reused",
                "return_3m": float(signal_row["ret3"]),
                "volume": float(signal_row["volume"]),
                "spread_bps_at_decision": spread_bps,
                "latency_ms_assumption": latency_ms,
                "queue_assumption": queue_assumption,
                "label_horizon_seconds": hold_minutes * 60,
            }
        )
    return event_objects, fill_ledger


def _metrics(fill_ledger: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not fill_ledger:
        return _empty_metrics()
    by_event: dict[str, list[Mapping[str, Any]]] = {}
    for row in fill_ledger:
        by_event.setdefault(str(row["event_id"]), []).append(row)
    trade_pnls = []
    trade_return_bps = []
    for fills in by_event.values():
        pnl = sum(float(row["cash_flow"]) for row in fills)
        entry = next(row for row in fills if row["side"] == "buy")
        entry_notional = float(entry["fill_price"]) * float(entry["quantity"])
        trade_pnls.append(pnl)
        trade_return_bps.append(pnl / entry_notional * 10_000.0 if entry_notional else 0.0)
    gross_profit = sum(value for value in trade_pnls if value > 0)
    gross_loss = -sum(value for value in trade_pnls if value < 0)
    return {
        "event_count": len(by_event),
        "trade_count": len(by_event),
        "fill_count": len(fill_ledger),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": sum(trade_pnls),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "hit_rate": sum(1 for value in trade_pnls if value > 0) / len(trade_pnls) if trade_pnls else 0.0,
        "mean_trade_return_bps": statistics.mean(trade_return_bps) if trade_return_bps else 0.0,
        "median_trade_return_bps": statistics.median(trade_return_bps) if trade_return_bps else 0.0,
        "pnl_from_fill_ledger": True,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "event_count": 0,
        "trade_count": 0,
        "fill_count": 0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "net_pnl": 0.0,
        "profit_factor": None,
        "hit_rate": 0.0,
        "mean_trade_return_bps": 0.0,
        "median_trade_return_bps": 0.0,
        "pnl_from_fill_ledger": True,
    }


def _gate(metrics: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "minimum_trade_count": int(metrics.get("trade_count", 0) or 0) >= 100,
        "minimum_fill_count": int(metrics.get("fill_count", 0) or 0) >= 200,
        "profit_factor": _float(metrics.get("profit_factor")) >= 1.10,
        "hit_rate": _float(metrics.get("hit_rate")) >= 0.45,
        "mean_trade_return_bps": _float(metrics.get("mean_trade_return_bps")) > 0.0,
        "pnl_from_fill_ledger": bool(metrics.get("pnl_from_fill_ledger", False)),
    }
    return {
        "passed": all(checks.values()),
        "status": "candidate_gate_passed" if all(checks.values()) else "candidate_gate_failed",
        "checks": checks,
        "thresholds": {
            "minimum_trade_count": 100,
            "minimum_fill_count": 200,
            "profit_factor": 1.10,
            "hit_rate": 0.45,
            "mean_trade_return_bps": 0.0,
        },
    }


def _gate_blockers(gate: Mapping[str, Any]) -> list[str]:
    return [f"btc_true_scalping_event_ledger_gate_failed_{name}" for name, passed in _mapping(gate.get("checks")).items() if not passed]


def _latest_1m_data_version(manifest_root: Path) -> str:
    candidates = []
    for path in sorted(manifest_root.glob("qs-sqlite-BTCUSDT-1m-*.json")):
        payload = _read_json(path)
        if str(payload.get("symbol", "")).upper() == SYMBOL and str(payload.get("interval", "")) == INTERVAL:
            candidates.append(str(payload.get("data_version", path.stem)))
    return candidates[-1] if candidates else "unknown"


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _nested_float(payload: Mapping[str, Any], keys: tuple[str, str], *, default: float) -> float:
    first = _mapping(payload.get(keys[0]))
    return _float(first.get(keys[1]), default=default)


def _float(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _sha256_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(dict(payload), sort_keys=True).encode("utf-8")).hexdigest()


def _git(args: list[str], *, cwd: Path) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:  # noqa: BLE001 - metadata only.
        return "unknown"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
