#!/usr/bin/env python3
"""Run a research-only 1m proxy-feature redesign for BTC scalping hypotheses."""

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
DEFAULT_L2_FEATURE_DIAGNOSTICS = Path(
    "artifacts/btc_scalping_readiness/latest/btc_true_scalping_l2_feature_diagnostics_report.json"
)
DEFAULT_PREVIOUS_REDESIGN = Path(
    "artifacts/btc_scalping_event_ledger/latest/btc_true_scalping_event_definition_redesign_report.json"
)
DEFAULT_SPREAD_MODEL = Path("artifacts/btc_scalping_readiness/latest/spread_model.json")
DEFAULT_LATENCY_MODEL = Path("artifacts/btc_scalping_readiness/latest/latency_model.json")
DEFAULT_DB_PATH = Path("data/market_data.sqlite")
DEFAULT_MANIFEST_ROOT = Path("data/manifests")
SYMBOL = "BTCUSDT"
EXCHANGE = "binance_spot"
INTERVAL = "1m"
STRATEGY_ID = "btc_true_scalping_1m_proxy_feature_redesign_research_v0"


def build_btc_true_scalping_1m_proxy_feature_redesign_report(
    *,
    repo_root: Path | None = None,
    l2_feature_diagnostics_path: Path | None = None,
    previous_redesign_path: Path | None = None,
    spread_model_path: Path | None = None,
    latency_model_path: Path | None = None,
    db_path: Path | None = None,
    manifest_root: Path | None = None,
    output_root: Path | None = None,
    history_days: int = 365,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    output_dir = _resolve(root, output_root or DEFAULT_OUTPUT_ROOT)
    run_dir = output_dir / "proxy_feature_redesign_run"
    l2_feature_file = _resolve(root, l2_feature_diagnostics_path or DEFAULT_L2_FEATURE_DIAGNOSTICS)
    previous_file = _resolve(root, previous_redesign_path or DEFAULT_PREVIOUS_REDESIGN)
    spread_file = _resolve(root, spread_model_path or DEFAULT_SPREAD_MODEL)
    latency_file = _resolve(root, latency_model_path or DEFAULT_LATENCY_MODEL)
    sqlite_file = _resolve(root, db_path or DEFAULT_DB_PATH)
    manifest_dir = _resolve(root, manifest_root or DEFAULT_MANIFEST_ROOT)
    l2_features = _read_json(l2_feature_file)
    previous = _read_json(previous_file)
    spread_model = _read_json(spread_file)
    latency_model = _read_json(latency_file)
    blockers = _preflight_blockers(
        l2_features=l2_features,
        previous=previous,
        spread_model=spread_model,
        latency_model=latency_model,
        sqlite_file=sqlite_file,
    )
    if blockers:
        payload = _base_payload(
            generated=generated,
            root=root,
            status="proxy_feature_redesign_blocked",
            decision="repair_proxy_feature_redesign_preflight",
            next_required_action="repair_proxy_feature_redesign_preflight",
            blockers=blockers,
            source_reports={
                "l2_feature_diagnostics": l2_feature_file,
                "previous_event_definition_redesign": previous_file,
                "spread_model": spread_file,
                "latency_model": latency_file,
            },
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(output_dir / "btc_true_scalping_1m_proxy_feature_redesign_report.json", payload)
        return payload

    frame = _load_klines(sqlite_file, history_days=int(history_days))
    data = _proxy_features(frame)
    spread_bps = _nested_float(spread_model, ("spread_bps", "median"), default=0.0)
    latency_ms = _nested_float(latency_model, ("duration_ms", "median"), default=0.0)
    latency_penalty_bps = min(2.0, max(0.0, latency_ms / 1000.0))
    slippage_bps_each_side = max(0.01, spread_bps / 2.0) + latency_penalty_bps
    fee_bps_each_side = 5.0
    variants = _variant_specs()
    results: list[dict[str, Any]] = []
    best_result: dict[str, Any] | None = None
    best_events: list[dict[str, Any]] = []
    best_fills: list[dict[str, Any]] = []
    for spec in variants:
        events, fills = _simulate_proxy_variant(
            data=data,
            spec=spec,
            spread_bps=spread_bps,
            latency_ms=latency_ms,
            slippage_bps_each_side=slippage_bps_each_side,
            fee_bps_each_side=fee_bps_each_side,
        )
        metrics = _metrics(fills)
        wf = _walk_forward(events, fills, frame_len=len(data))
        gate = _gate(metrics, wf)
        row = {
            "variant_id": spec["variant_id"],
            "family": spec["family"],
            "side": spec["side"],
            "params": spec["params"],
            "params_hash": _sha256_json(spec["params"]),
            "metrics": metrics,
            "walk_forward": wf,
            "gate": gate,
            "blockers": _gate_blockers(gate),
        }
        results.append(row)
        if best_result is None or _rank(row) > _rank(best_result):
            best_result = row
            best_events = events
            best_fills = fills

    selected = best_result or {}
    passed = bool(_mapping(selected.get("gate")).get("passed", False))
    status = (
        "proxy_feature_redesign_found_research_gate_variant_candidate_still_locked"
        if passed
        else "proxy_feature_redesign_completed_no_viable_event"
    )
    decision = "manual_review_proxy_only_before_any_candidate_work" if passed else "reject_current_1m_proxy_feature_redesign_set"
    next_action = "manual_review_proxy_only_not_true_l2_scalping" if passed else "collect_timestamp_aligned_l2_history_before_true_scalping"
    run_dir.mkdir(parents=True, exist_ok=True)
    event_objects_path = run_dir / "best_variant_event_objects.csv"
    fill_ledger_path = run_dir / "best_variant_fill_ledger.csv"
    summary_path = run_dir / "variant_summary.csv"
    manifest_path = run_dir / "proxy_feature_redesign_manifest.json"
    _write_csv(event_objects_path, best_events)
    _write_csv(fill_ledger_path, best_fills)
    _write_csv(summary_path, [_summary_row(row) for row in results])
    data_version = _latest_1m_data_version(manifest_dir)
    manifest = {
        "schema_version": "btc_true_scalping_1m_proxy_feature_redesign_manifest_v1",
        "generated_at": generated,
        "strategy_id": STRATEGY_ID,
        "data_version": data_version,
        "strategy_version": f"{STRATEGY_ID}:proxy_feature_redesign_v1",
        "params": {
            "history_days": int(history_days),
            "variant_count": len(variants),
            "families": sorted({str(spec["family"]) for spec in variants}),
        },
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
        "not_true_l2_scalping": True,
    }
    _write_json(manifest_path, manifest)
    payload = _base_payload(
        generated=generated,
        root=root,
        status=status,
        decision=decision,
        next_required_action=next_action,
        blockers=_dedupe(
            ([] if passed else ["btc_true_scalping_proxy_redesign_no_variant_passed_research_gate"])
            + _list_of_strings(selected.get("blockers"))
            + [
                "btc_true_scalping_proxy_redesign_not_true_l2_scalping",
                "btc_true_scalping_proxy_redesign_candidate_generation_locked",
                "btc_true_scalping_proxy_redesign_paper_live_locked",
            ]
        ),
        source_reports={
            "l2_feature_diagnostics": l2_feature_file,
            "previous_event_definition_redesign": previous_file,
            "spread_model": spread_file,
            "latency_model": latency_file,
        },
    )
    payload.update(
        {
            "run_dir": _relpath(run_dir, root),
            "artifacts": {
                "best_variant_event_objects": _relpath(event_objects_path, root),
                "best_variant_fill_ledger": _relpath(fill_ledger_path, root),
                "variant_summary": _relpath(summary_path, root),
                "proxy_feature_redesign_manifest": _relpath(manifest_path, root),
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
            "variant_count": len(results),
            "top_variants": [_public_result(row) for row in sorted(results, key=_rank, reverse=True)[:10]],
            "best_variant": _public_result(selected),
            "manifest": manifest,
            "research_gate_passed": passed,
        }
    )
    _write_json(output_dir / "btc_true_scalping_1m_proxy_feature_redesign_report.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--l2-feature-diagnostics-path", default=str(DEFAULT_L2_FEATURE_DIAGNOSTICS))
    parser.add_argument("--previous-redesign-path", default=str(DEFAULT_PREVIOUS_REDESIGN))
    parser.add_argument("--spread-model-path", default=str(DEFAULT_SPREAD_MODEL))
    parser.add_argument("--latency-model-path", default=str(DEFAULT_LATENCY_MODEL))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--manifest-root", default=str(DEFAULT_MANIFEST_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--history-days", type=int, default=365)
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_true_scalping_1m_proxy_feature_redesign_report(
        repo_root=Path(args.repo_root),
        l2_feature_diagnostics_path=Path(args.l2_feature_diagnostics_path),
        previous_redesign_path=Path(args.previous_redesign_path),
        spread_model_path=Path(args.spread_model_path),
        latency_model_path=Path(args.latency_model_path),
        db_path=Path(args.db_path),
        manifest_root=Path(args.manifest_root),
        output_root=Path(args.output_root),
        history_days=args.history_days,
        generated_at=args.generated_at or None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def _base_payload(
    *,
    generated: str,
    root: Path,
    status: str,
    decision: str,
    next_required_action: str,
    blockers: list[str],
    source_reports: Mapping[str, Path],
) -> dict[str, Any]:
    return {
        "schema_version": "btc_true_scalping_1m_proxy_feature_redesign_report_v1",
        "generated_at": generated,
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": SYMBOL,
        "strategy_id": STRATEGY_ID,
        "scope": "research_only_1m_proxy_feature_redesign_no_true_l2_no_candidate_no_paper_no_live",
        "status": status,
        "decision": decision,
        "next_required_action": next_required_action,
        "source_reports": {name: _relpath(path, root) if path.exists() else None for name, path in source_reports.items()},
        "run_dir": None,
        "artifacts": {
            "best_variant_event_objects": None,
            "best_variant_fill_ledger": None,
            "variant_summary": None,
            "proxy_feature_redesign_manifest": None,
        },
        "data_context": {},
        "variant_count": 0,
        "top_variants": [],
        "best_variant": {},
        "manifest": {},
        "research_gate_passed": False,
        "not_true_l2_scalping": True,
        "event_ledger_feature_validation_allowed": False,
        "blockers": _dedupe(blockers),
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
            "completed_bar_features_only": True,
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "pnl_from_fill_ledger": True,
        },
    }


def _preflight_blockers(
    *,
    l2_features: Mapping[str, Any],
    previous: Mapping[str, Any],
    spread_model: Mapping[str, Any],
    latency_model: Mapping[str, Any],
    sqlite_file: Path,
) -> list[str]:
    blockers: list[str] = []
    if str(l2_features.get("status", "")) != "l2_feature_diagnostics_ready_research_only_backtest_blocked":
        blockers.append("btc_l2_feature_diagnostics_not_ready")
    if bool(l2_features.get("event_ledger_feature_validation_allowed", True)):
        blockers.append("btc_l2_feature_diagnostics_unexpectedly_allowed_backtest_join")
    if str(previous.get("status", "")) not in {
        "redesign_audit_completed_no_viable_scalping_event",
        "redesign_audit_found_research_gate_variant_candidate_still_locked",
    }:
        blockers.append("btc_previous_true_scalping_redesign_not_ready")
    if str(spread_model.get("status", "")) != "pass":
        blockers.append("btc_true_scalping_spread_model_not_pass")
    if str(latency_model.get("status", "")) != "pass":
        blockers.append("btc_true_scalping_latency_model_not_pass")
    if not sqlite_file.exists():
        blockers.append("btc_true_scalping_sqlite_market_data_missing")
    return blockers


def _variant_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    thresholds = [0.001, 0.0015, 0.0025, 0.004]
    volume_ratios = [1.2, 1.5]
    holds = [2, 3, 5]
    families = [
        ("long_wick_reclaim", "long"),
        ("short_wick_reject", "short"),
        ("long_absorption_reversal", "long"),
        ("short_absorption_reversal", "short"),
        ("long_compression_break", "long"),
        ("short_compression_break", "short"),
    ]
    for family, side in families:
        for threshold in thresholds:
            for volume_ratio in volume_ratios:
                for hold in holds:
                    params = {
                        "return_threshold": threshold,
                        "volume_ratio_threshold": volume_ratio,
                        "hold_minutes": hold,
                        "min_gap_bars": hold,
                        "close_location_threshold": 0.70,
                        "wick_fraction_threshold": 0.45,
                    }
                    specs.append(
                        {
                            "variant_id": f"{family}_thr{str(threshold).replace('.', 'p')}_vol{str(volume_ratio).replace('.', 'p')}_hold{hold}_v1",
                            "family": family,
                            "side": side,
                            "params": params,
                        }
                    )
    return specs


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
        return pd.read_sql_query(
            """
            SELECT open_time_ms, open_time, open, high, low, close, volume, trade_count
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ? AND open_time_ms >= ?
            ORDER BY open_time_ms
            """,
            connection,
            params=(EXCHANGE, SYMBOL, INTERVAL, start_ms),
        )


def _proxy_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["ret1"] = data["close"].pct_change()
    data["ret3"] = data["close"] / data["close"].shift(3) - 1.0
    data["ret5"] = data["close"] / data["close"].shift(5) - 1.0
    candle_range = (data["high"] - data["low"]).replace(0, math.nan)
    data["close_location"] = ((data["close"] - data["low"]) / candle_range).fillna(0.5)
    upper_body = data[["open", "close"]].max(axis=1)
    lower_body = data[["open", "close"]].min(axis=1)
    data["upper_wick_fraction"] = ((data["high"] - upper_body) / candle_range).fillna(0.0)
    data["lower_wick_fraction"] = ((lower_body - data["low"]) / candle_range).fillna(0.0)
    data["range_bps"] = ((data["high"] - data["low"]) / data["close"] * 10_000.0).fillna(0.0)
    data["volume_ratio"] = data["volume"] / data["volume"].rolling(60).median().shift(1)
    data["trade_count_ratio"] = data["trade_count"] / data["trade_count"].rolling(60).median().shift(1)
    data["compression_prior"] = data["range_bps"].rolling(10).mean().shift(1) < data["range_bps"].rolling(240).median().shift(1)
    return data


def _simulate_proxy_variant(
    *,
    data: pd.DataFrame,
    spec: Mapping[str, Any],
    spread_bps: float,
    latency_ms: float,
    slippage_bps_each_side: float,
    fee_bps_each_side: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    params = _mapping(spec.get("params"))
    threshold = float(params["return_threshold"])
    volume_threshold = float(params["volume_ratio_threshold"])
    hold = int(params["hold_minutes"])
    gap = int(params["min_gap_bars"])
    clv = float(params["close_location_threshold"])
    wick = float(params["wick_fraction_threshold"])
    family = str(spec["family"])
    side = str(spec["side"])
    volume_confirm = (data["volume_ratio"] >= volume_threshold) | (data["trade_count_ratio"] >= volume_threshold)
    if family == "long_wick_reclaim":
        signal = (data["ret3"] <= -threshold) & (data["close_location"] >= clv) & (data["lower_wick_fraction"] >= wick) & volume_confirm
    elif family == "short_wick_reject":
        signal = (data["ret3"] >= threshold) & (data["close_location"] <= 1.0 - clv) & (data["upper_wick_fraction"] >= wick) & volume_confirm
    elif family == "long_absorption_reversal":
        signal = (data["ret1"] <= -threshold) & (data["close_location"] >= clv) & (data["trade_count_ratio"] >= volume_threshold)
    elif family == "short_absorption_reversal":
        signal = (data["ret1"] >= threshold) & (data["close_location"] <= 1.0 - clv) & (data["trade_count_ratio"] >= volume_threshold)
    elif family == "long_compression_break":
        signal = data["compression_prior"] & (data["ret1"] >= threshold) & (data["close_location"] >= clv) & volume_confirm
    elif family == "short_compression_break":
        signal = data["compression_prior"] & (data["ret1"] <= -threshold) & (data["close_location"] <= 1.0 - clv) & volume_confirm
    else:
        signal = pd.Series(False, index=data.index)
    events: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    last_index = -10_000_000
    for raw_index in list(data.index[signal.fillna(False)]):
        signal_index = int(raw_index)
        if signal_index <= last_index + gap:
            continue
        entry_index = signal_index + 1
        exit_index = entry_index + hold
        if exit_index >= len(data):
            continue
        last_index = signal_index
        event_id = f"{spec['variant_id']}-{len(events) + 1:06d}"
        signal_row = data.iloc[signal_index]
        entry_row = data.iloc[entry_index]
        exit_row = data.iloc[exit_index]
        entry_reference = float(entry_row["open"])
        exit_reference = float(exit_row["open"])
        if side == "long":
            entry_fill = entry_reference * (1.0 + slippage_bps_each_side / 10_000.0)
            exit_fill = exit_reference * (1.0 - slippage_bps_each_side / 10_000.0)
            entry_cash = -(entry_fill + entry_fill * fee_bps_each_side / 10_000.0)
            exit_cash = exit_fill - exit_fill * fee_bps_each_side / 10_000.0
            entry_side, exit_side = "buy", "sell"
        else:
            entry_fill = entry_reference * (1.0 - slippage_bps_each_side / 10_000.0)
            exit_fill = exit_reference * (1.0 + slippage_bps_each_side / 10_000.0)
            entry_cash = entry_fill - entry_fill * fee_bps_each_side / 10_000.0
            exit_cash = -(exit_fill + exit_fill * fee_bps_each_side / 10_000.0)
            entry_side, exit_side = "sell_short", "buy_to_cover"
        order_intent_id = f"{event_id}-intent"
        fills.extend(
            [
                {
                    "fill_id": f"{event_id}-fill-entry",
                    "event_id": event_id,
                    "order_intent_id": order_intent_id,
                    "timestamp": str(entry_row["open_time"]),
                    "side": entry_side,
                    "quantity": 1.0,
                    "reference_price": entry_reference,
                    "fill_price": entry_fill,
                    "fee": abs(entry_fill * fee_bps_each_side / 10_000.0),
                    "cash_flow": entry_cash,
                    "simulated": True,
                },
                {
                    "fill_id": f"{event_id}-fill-exit",
                    "event_id": event_id,
                    "order_intent_id": order_intent_id,
                    "timestamp": str(exit_row["open_time"]),
                    "side": exit_side,
                    "quantity": 1.0,
                    "reference_price": exit_reference,
                    "fill_price": exit_fill,
                    "fee": abs(exit_fill * fee_bps_each_side / 10_000.0),
                    "cash_flow": exit_cash,
                    "simulated": True,
                },
            ]
        )
        events.append(
            {
                "event_id": event_id,
                "variant_id": spec["variant_id"],
                "family": family,
                "side": side,
                "signal_index": signal_index,
                "event_timestamp": str(signal_row["open_time"]),
                "entry_timestamp": str(entry_row["open_time"]),
                "exit_timestamp": str(exit_row["open_time"]),
                "order_intent_id": order_intent_id,
                "trigger_state": family,
                "context_state": "1m_completed_bar_proxy_not_true_l2_scalping",
                "return_1m": _float(signal_row.get("ret1")),
                "return_3m": _float(signal_row.get("ret3")),
                "close_location": _float(signal_row.get("close_location")),
                "lower_wick_fraction": _float(signal_row.get("lower_wick_fraction")),
                "upper_wick_fraction": _float(signal_row.get("upper_wick_fraction")),
                "volume_ratio": _float(signal_row.get("volume_ratio")),
                "trade_count_ratio": _float(signal_row.get("trade_count_ratio")),
                "spread_bps_at_decision": spread_bps,
                "latency_ms_assumption": latency_ms,
                "completed_bar_features_only": True,
                "label_horizon_seconds": hold * 60,
            }
        )
    return events, fills


def _metrics(fill_ledger: list[Mapping[str, Any]]) -> dict[str, Any]:
    if not fill_ledger:
        return _empty_metrics()
    by_event: dict[str, list[Mapping[str, Any]]] = {}
    for row in fill_ledger:
        by_event.setdefault(str(row["event_id"]), []).append(row)
    pnls = []
    returns = []
    for fills in by_event.values():
        pnl = sum(float(row["cash_flow"]) for row in fills)
        entry = fills[0]
        entry_notional = float(entry["fill_price"]) * float(entry["quantity"])
        pnls.append(pnl)
        returns.append(pnl / entry_notional * 10_000.0 if entry_notional else 0.0)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    return {
        "event_count": len(by_event),
        "trade_count": len(by_event),
        "fill_count": len(fill_ledger),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": sum(pnls),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "hit_rate": sum(1 for value in pnls if value > 0) / len(pnls) if pnls else 0.0,
        "mean_trade_return_bps": statistics.mean(returns) if returns else 0.0,
        "median_trade_return_bps": statistics.median(returns) if returns else 0.0,
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


def _walk_forward(events: list[Mapping[str, Any]], fills: list[Mapping[str, Any]], *, frame_len: int) -> dict[str, Any]:
    event_fold: dict[str, int] = {}
    for event in events:
        fold = min(5, int(int(event.get("signal_index", 0)) / max(1, frame_len) * 6))
        event_fold[str(event["event_id"])] = fold
    by_fold: list[list[Mapping[str, Any]]] = [[] for _ in range(6)]
    for fill in fills:
        by_fold[event_fold.get(str(fill["event_id"]), 0)].append(fill)
    rows = []
    pass_count = 0
    valid_count = 0
    for fold, fold_fills in enumerate(by_fold):
        metrics = _metrics(fold_fills)
        valid = int(metrics["trade_count"]) >= 20
        passed = valid and _float(metrics.get("profit_factor")) >= 1.05 and _float(metrics.get("mean_trade_return_bps")) > 0
        rows.append(
            {
                "fold": fold,
                "valid": valid,
                "passed": passed,
                "trade_count": metrics["trade_count"],
                "profit_factor": metrics["profit_factor"],
                "mean_trade_return_bps": metrics["mean_trade_return_bps"],
            }
        )
        valid_count += int(valid)
        pass_count += int(passed)
    return {
        "method": "six_chronological_folds",
        "fold_count": 6,
        "valid_fold_count": valid_count,
        "pass_count": pass_count,
        "pass_rate": pass_count / valid_count if valid_count else 0.0,
        "folds": rows,
    }


def _gate(metrics: Mapping[str, Any], walk_forward: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "minimum_trade_count": int(metrics.get("trade_count", 0) or 0) >= 100,
        "minimum_fill_count": int(metrics.get("fill_count", 0) or 0) >= 200,
        "profit_factor": _float(metrics.get("profit_factor")) >= 1.10,
        "hit_rate": _float(metrics.get("hit_rate")) >= 0.45,
        "mean_trade_return_bps": _float(metrics.get("mean_trade_return_bps")) > 0.0,
        "walk_forward_pass_rate": _float(walk_forward.get("pass_rate")) >= 0.60,
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
            "walk_forward_pass_rate": 0.60,
        },
    }


def _gate_blockers(gate: Mapping[str, Any]) -> list[str]:
    return [f"btc_true_scalping_proxy_redesign_gate_failed_{name}" for name, passed in _mapping(gate.get("checks")).items() if not passed]


def _rank(row: Mapping[str, Any]) -> tuple[float, float, float, float, int]:
    metrics = _mapping(row.get("metrics"))
    wf = _mapping(row.get("walk_forward"))
    gate = _mapping(row.get("gate"))
    return (
        1.0 if bool(gate.get("passed", False)) else 0.0,
        _float(wf.get("pass_rate")),
        _float(metrics.get("profit_factor")),
        _float(metrics.get("mean_trade_return_bps"), default=-9999.0),
        int(metrics.get("trade_count", 0) or 0),
    )


def _public_result(row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _mapping(row.get("metrics"))
    walk_forward = _mapping(row.get("walk_forward"))
    gate = _mapping(row.get("gate"))
    return {
        "variant_id": row.get("variant_id"),
        "family": row.get("family"),
        "side": row.get("side"),
        "params": row.get("params", {}),
        "params_hash": row.get("params_hash"),
        "metrics": metrics,
        "walk_forward": {
            "valid_fold_count": walk_forward.get("valid_fold_count", 0),
            "pass_count": walk_forward.get("pass_count", 0),
            "pass_rate": walk_forward.get("pass_rate", 0.0),
        },
        "gate": gate,
        "blockers": _list_of_strings(row.get("blockers")),
    }


def _summary_row(row: Mapping[str, Any]) -> dict[str, Any]:
    public = _public_result(row)
    metrics = _mapping(public.get("metrics"))
    wf = _mapping(public.get("walk_forward"))
    gate = _mapping(public.get("gate"))
    return {
        "variant_id": public["variant_id"],
        "family": public["family"],
        "side": public["side"],
        "trade_count": metrics.get("trade_count"),
        "fill_count": metrics.get("fill_count"),
        "profit_factor": metrics.get("profit_factor"),
        "hit_rate": metrics.get("hit_rate"),
        "mean_trade_return_bps": metrics.get("mean_trade_return_bps"),
        "median_trade_return_bps": metrics.get("median_trade_return_bps"),
        "walk_forward_pass_rate": wf.get("pass_rate"),
        "gate_passed": gate.get("passed"),
    }


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


def _list_of_strings(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


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
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


if __name__ == "__main__":
    main()
