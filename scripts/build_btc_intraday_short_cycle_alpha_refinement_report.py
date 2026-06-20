#!/usr/bin/env python3
"""Build BTC intraday short-cycle alpha refinement report.

This report tests a small, fixed set of refined event definitions after the
initial probe found no net-positive distribution edge. It is research-only:
future returns are labels, not signal inputs, and no strategy candidate,
paper review, live unlock, or broker/order path is created.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
BTC_INTRADAY_PROBE = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_probe_report.json")
BTC_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
FORWARD_HORIZONS = {"30m": 6, "60m": 12, "120m": 24}
FOLD_COUNT = 6
MIN_TOTAL_EVENTS = 300
MIN_FOLD_EVENTS = 30
MIN_POSITIVE_FOLDS = 4
MIN_NET_MEAN_BPS = 0.0
MIN_NET_MEDIAN_BPS = -10.0
MIN_NET_POSITIVE_HIT_RATE = 0.45
FIFTEEN_MINUTES_MS = 15 * 60 * 1000


def build_btc_intraday_short_cycle_alpha_refinement_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    probe = _read_json(root / BTC_INTRADAY_PROBE)
    data_status = _read_json(root / BTC_DATA_STATUS)
    cost_model = _read_json(root / BTC_COST_MODEL)
    db_path = _resolve_data_path(root, data_status)
    taker_fee_bps = _taker_fee_bps(cost_model)
    round_trip_cost_bps = round(2.0 * taker_fee_bps, 6)
    data_ready = bool(probe.get("distribution_probe_completed", False)) and db_path.exists()
    variant_results: list[dict[str, Any]] = []
    if data_ready:
        rows_5m = _load_rows(db_path, interval="5m")
        rows_15m = _load_rows(db_path, interval="15m")
        variant_results = _evaluate_refinements(
            rows_5m=rows_5m,
            rows_15m=rows_15m,
            round_trip_cost_bps=round_trip_cost_bps,
        )

    robust_variants = [row for row in variant_results if row["robust_distribution_observed"]]
    best_variant = _best_variant(robust_variants or variant_results)
    status = _status(data_ready=data_ready, robust_variants=robust_variants)
    return {
        "schema_version": "btc_intraday_short_cycle_alpha_refinement_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_bounded_refinement_no_candidate_no_paper_no_live",
        "status": status,
        "decision": (
            "design_research_only_event_ledger_backtest_for_refined_alpha"
            if robust_variants
            else ("continue_event_definition_research_no_candidate" if data_ready else "repair_intraday_refinement_data")
        ),
        "next_required_action": (
            "build_event_ledger_backtest_for_best_refined_variant"
            if robust_variants
            else ("add_intraday_context_or_new_alpha_family_before_scalping" if data_ready else "repair_5m_15m_sqlite_data")
        ),
        "refinement_completed": data_ready,
        "robust_alpha_distribution_observed": bool(robust_variants),
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "source_intraday_short_cycle_alpha_probe": _maybe_path(root, BTC_INTRADAY_PROBE),
        "source_data_status": _maybe_path(root, BTC_DATA_STATUS),
        "source_cost_model": _maybe_path(root, BTC_COST_MODEL),
        "data_context": _data_context(root=root, db_path=db_path, data_status=data_status),
        "cost_context": {
            "cost_model_status": str(cost_model.get("status", "missing") or "missing"),
            "taker_fee_bps": taker_fee_bps,
            "round_trip_taker_cost_bps": round_trip_cost_bps,
            "cost_is_diagnostic_not_fill_ledger_pnl": True,
        },
        "refinement_parameters": {
            "variant_count": len(_variant_specs()),
            "fold_count": FOLD_COUNT,
            "min_total_events": MIN_TOTAL_EVENTS,
            "min_fold_events": MIN_FOLD_EVENTS,
            "min_positive_folds": MIN_POSITIVE_FOLDS,
            "min_net_mean_bps": MIN_NET_MEAN_BPS,
            "min_net_median_bps": MIN_NET_MEDIAN_BPS,
            "min_net_positive_hit_rate": MIN_NET_POSITIVE_HIT_RATE,
            "forward_return_horizons": list(FORWARD_HORIZONS),
            "lookahead_used_for_signal": False,
            "future_returns_used_only_as_labels": True,
            "bounded_search_only": True,
        },
        "variant_results": variant_results,
        "best_variant": best_variant,
        "acceptance_gates": {
            "event_ledger_backtest_required_before_candidate": True,
            "walk_forward_required_before_candidate": True,
            "regime_required_before_candidate": True,
            "cost_stress_required_before_candidate": True,
            "fill_ledger_pnl_required_before_paper": True,
            "manifest_required": True,
        },
        "guardrails": {
            "research_only": True,
            "broker_calls_allowed": False,
            "private_endpoints_allowed": False,
            "order_endpoints_allowed": False,
            "paper_or_live_unlock_allowed": False,
            "candidate_generation_allowed": False,
            "strategy_skeleton_generation_allowed": False,
            "true_scalping_allowed": False,
            "sub_minute_or_tick_scalping_allowed": False,
            "pnl_from_fill_ledger_required_for_promotion": True,
        },
        "interpretation": _interpretation(
            data_ready=data_ready,
            robust_variants=robust_variants,
            variant_results=variant_results,
        ),
        "blockers": _blockers(data_ready=data_ready, status=status),
    }


def write_btc_intraday_short_cycle_alpha_refinement_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_intraday_short_cycle_alpha_refinement_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_alpha_refinement_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_alpha_refinement_report(payload, Path(args.output_root)))


def _evaluate_refinements(
    *,
    rows_5m: list[dict[str, Any]],
    rows_15m: list[dict[str, Any]],
    round_trip_cost_bps: float,
) -> list[dict[str, Any]]:
    features = _features(rows_5m=rows_5m, rows_15m=rows_15m)
    return [
        _evaluate_variant(spec=spec, features=features, round_trip_cost_bps=round_trip_cost_bps)
        for spec in _variant_specs()
    ]


def _features(*, rows_5m: list[dict[str, Any]], rows_15m: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(row["close"]) for row in rows_5m]
    highs = [float(row["high"]) for row in rows_5m]
    lows = [float(row["low"]) for row in rows_5m]
    opens = [float(row["open"]) for row in rows_5m]
    volumes = [float(row["volume"]) for row in rows_5m]
    times = [int(row["open_time_ms"]) for row in rows_5m]
    windows = (6, 12, 24, 36, 48, 72, 144)
    previous_highs = {window: _rolling_extreme_previous(highs, window, maximum=True) for window in windows}
    previous_lows = {window: _rolling_extreme_previous(lows, window, maximum=False) for window in windows}
    volume_sums = _rolling_sums(volumes)
    avg_vol_72 = [_window_average(volume_sums, i - 72, i) for i in range(len(volumes))]
    trend_15m_map = _fifteen_minute_trend_map(rows_15m)
    trend_1h = []
    trend_2h = []
    trend_4h = []
    for ts in times:
        row = trend_15m_map.get(ts - (ts % FIFTEEN_MINUTES_MS), {})
        trend_1h.append(float(row.get("1h", 0.0)))
        trend_2h.append(float(row.get("2h", 0.0)))
        trend_4h.append(float(row.get("4h", 0.0)))
    prev_return_bps = [0.0, 0.0]
    for i in range(2, len(closes)):
        prev_return_bps.append(((closes[i - 1] / closes[i - 2]) - 1.0) * 10_000.0)
    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "opens": opens,
        "volumes": volumes,
        "previous_highs": previous_highs,
        "previous_lows": previous_lows,
        "avg_vol_72": avg_vol_72,
        "trend_1h": trend_1h,
        "trend_2h": trend_2h,
        "trend_4h": trend_4h,
        "prev_return_bps": prev_return_bps,
    }


def _variant_specs() -> list[dict[str, Any]]:
    return [
        {
            "variant_id": "momentum_breakout_24_vol2_4htrend50_v1",
            "family_id": "orderflow_confirmed_momentum_intraday_v0",
            "kind": "momentum",
            "lookback": 24,
            "volume_multiple": 2.0,
            "trend_key": "trend_4h",
            "trend_min": 0.005,
        },
        {
            "variant_id": "momentum_breakout_24_vol25_4htrend100_v1",
            "family_id": "orderflow_confirmed_momentum_intraday_v0",
            "kind": "momentum",
            "lookback": 24,
            "volume_multiple": 2.5,
            "trend_key": "trend_4h",
            "trend_min": 0.01,
        },
        {
            "variant_id": "momentum_breakout_48_vol15_2htrend25_v1",
            "family_id": "orderflow_confirmed_momentum_intraday_v0",
            "kind": "momentum",
            "lookback": 48,
            "volume_multiple": 1.5,
            "trend_key": "trend_2h",
            "trend_min": 0.0025,
        },
        {
            "variant_id": "compression_reclaim_12x72_ratio25_vol15_uptrend_v1",
            "family_id": "volatility_compression_reclaim_intraday_v0",
            "kind": "compression",
            "lookback": 12,
            "base_window": 72,
            "range_ratio_max": 0.25,
            "volume_multiple": 1.5,
            "trend_key": "trend_2h",
            "trend_min": 0.0025,
        },
        {
            "variant_id": "compression_reclaim_24x144_ratio35_vol2_uptrend_v1",
            "family_id": "volatility_compression_reclaim_intraday_v0",
            "kind": "compression",
            "lookback": 24,
            "base_window": 144,
            "range_ratio_max": 0.35,
            "volume_multiple": 2.0,
            "trend_key": "trend_4h",
            "trend_min": 0.005,
        },
        {
            "variant_id": "pullback_reclaim_12_dd50_4htrend50_v1",
            "family_id": "pullback_reclaim_intraday_v0",
            "kind": "pullback",
            "lookback": 12,
            "prior_high_window": 36,
            "pullback_depth_min": 0.005,
            "volume_multiple": 1.0,
            "trend_key": "trend_4h",
            "trend_min": 0.005,
        },
        {
            "variant_id": "pullback_reclaim_24_dd100_4htrend100_v1",
            "family_id": "pullback_reclaim_intraday_v0",
            "kind": "pullback",
            "lookback": 24,
            "prior_high_window": 48,
            "pullback_depth_min": 0.01,
            "volume_multiple": 1.25,
            "trend_key": "trend_4h",
            "trend_min": 0.01,
        },
        {
            "variant_id": "shock_reclaim_relaxed_35bps_vol15_v1",
            "family_id": "liquidation_exhaustion_reclaim_intraday_v0",
            "kind": "shock_reclaim",
            "shock_return_bps_max": -35.0,
            "volume_multiple": 1.5,
            "trend_key": "trend_2h",
            "trend_min": -0.01,
        },
    ]


def _evaluate_variant(
    *,
    spec: Mapping[str, Any],
    features: Mapping[str, Any],
    round_trip_cost_bps: float,
) -> dict[str, Any]:
    indexes = _event_indexes(spec=spec, features=features)
    closes = features["closes"]
    horizon_stats = {
        label: _horizon_stats(indexes=indexes, closes=closes, bars=bars, round_trip_cost_bps=round_trip_cost_bps)
        for label, bars in FORWARD_HORIZONS.items()
    }
    best_horizon, best_stats = _best_horizon(horizon_stats)
    event_count = len(indexes)
    robust = _robust_distribution(best_stats=best_stats, event_count=event_count)
    return {
        "variant_id": str(spec["variant_id"]),
        "family_id": str(spec["family_id"]),
        "status": (
            "robust_distribution_observed"
            if robust
            else ("sample_ready_no_robust_edge" if event_count >= MIN_TOTAL_EVENTS else "sample_too_sparse")
        ),
        "event_count": event_count,
        "best_horizon": best_horizon,
        "best_net_mean_bps": best_stats.get("mean_net_bps") if best_stats else None,
        "best_net_median_bps": best_stats.get("median_net_bps") if best_stats else None,
        "best_net_positive_hit_rate": best_stats.get("net_positive_hit_rate") if best_stats else None,
        "valid_fold_count": best_stats.get("valid_fold_count", 0) if best_stats else 0,
        "positive_net_fold_count": best_stats.get("positive_net_fold_count", 0) if best_stats else 0,
        "min_fold_event_count": best_stats.get("min_fold_event_count", 0) if best_stats else 0,
        "robust_distribution_observed": robust,
        "candidate_generation_allowed": False,
        "parameters": {key: value for key, value in spec.items() if key not in {"variant_id", "family_id"}},
        "horizon_stats": horizon_stats,
    }


def _event_indexes(*, spec: Mapping[str, Any], features: Mapping[str, Any]) -> list[int]:
    closes = features["closes"]
    highs = features["highs"]
    lows = features["lows"]
    opens = features["opens"]
    previous_highs = features["previous_highs"]
    previous_lows = features["previous_lows"]
    avg_vol_72 = features["avg_vol_72"]
    volumes = features["volumes"]
    trend = features[str(spec.get("trend_key", "trend_2h"))]
    kind = str(spec["kind"])
    indexes: list[int] = []
    start = 200
    stop = len(closes) - max(FORWARD_HORIZONS.values())
    for i in range(start, stop):
        avg_volume = avg_vol_72[i]
        if avg_volume <= 0:
            continue
        if trend[i] < float(spec.get("trend_min", 0.0)):
            continue
        if kind == "momentum":
            lookback = int(spec["lookback"])
            if closes[i] > previous_highs[lookback][i] and volumes[i] >= float(spec["volume_multiple"]) * avg_volume:
                indexes.append(i)
        elif kind == "compression":
            lookback = int(spec["lookback"])
            base = int(spec["base_window"])
            base_range = previous_highs[base][i] - previous_lows[base][i]
            lookback_range = previous_highs[lookback][i] - previous_lows[lookback][i]
            if (
                base_range > 0
                and lookback_range <= float(spec["range_ratio_max"]) * base_range
                and closes[i] > previous_highs[lookback][i]
                and volumes[i] >= float(spec["volume_multiple"]) * avg_volume
            ):
                indexes.append(i)
        elif kind == "pullback":
            lookback = int(spec["lookback"])
            prior_high_window = int(spec["prior_high_window"])
            prior_high = previous_highs[prior_high_window][i - lookback]
            pullback_low = previous_lows[lookback][i]
            pullback_depth = (prior_high - pullback_low) / prior_high if prior_high > 0 else 0.0
            if (
                pullback_depth >= float(spec["pullback_depth_min"])
                and closes[i] > previous_highs[lookback][i]
                and volumes[i] >= float(spec["volume_multiple"]) * avg_volume
            ):
                indexes.append(i)
        elif kind == "shock_reclaim":
            prev_return_bps = features["prev_return_bps"][i]
            if (
                prev_return_bps <= float(spec["shock_return_bps_max"])
                and volumes[i - 1] >= float(spec["volume_multiple"]) * avg_volume
                and closes[i] > max(opens[i], highs[i - 1])
            ):
                indexes.append(i)
    return indexes


def _horizon_stats(
    *,
    indexes: list[int],
    closes: list[float],
    bars: int,
    round_trip_cost_bps: float,
) -> dict[str, Any]:
    values = [((closes[i + bars] / closes[i]) - 1.0) * 10_000.0 for i in indexes if i + bars < len(closes)]
    net_values = [value - round_trip_cost_bps for value in values]
    if not net_values:
        return _empty_stats()
    fold_rows = []
    for fold_id in range(FOLD_COUNT):
        fold_values = [
            ((closes[i + bars] / closes[i]) - 1.0) * 10_000.0 - round_trip_cost_bps
            for i in indexes
            if i + bars < len(closes) and _fold_id(i, len(closes)) == fold_id
        ]
        fold_rows.append(
            {
                "fold_id": fold_id,
                "event_count": len(fold_values),
                "mean_net_bps": _round(sum(fold_values) / len(fold_values)) if fold_values else None,
                "net_positive_hit_rate": _round(sum(1 for value in fold_values if value > 0.0) / len(fold_values))
                if fold_values
                else None,
            }
        )
    valid_folds = [row for row in fold_rows if int(row["event_count"]) >= MIN_FOLD_EVENTS]
    positive_folds = [
        row for row in valid_folds if row["mean_net_bps"] is not None and float(row["mean_net_bps"]) > 0.0
    ]
    sorted_values = sorted(values)
    return {
        "event_count": len(net_values),
        "mean_gross_bps": _round(sum(values) / len(values)),
        "median_gross_bps": _round(median(values)),
        "p25_gross_bps": _round(_percentile(sorted_values, 0.25)),
        "p75_gross_bps": _round(_percentile(sorted_values, 0.75)),
        "mean_net_bps": _round(sum(net_values) / len(net_values)),
        "median_net_bps": _round(median(net_values)),
        "net_positive_hit_rate": _round(sum(1 for value in net_values if value > 0.0) / len(net_values)),
        "valid_fold_count": len(valid_folds),
        "positive_net_fold_count": len(positive_folds),
        "min_fold_event_count": min((int(row["event_count"]) for row in fold_rows), default=0),
        "folds": fold_rows,
    }


def _empty_stats() -> dict[str, Any]:
    return {
        "event_count": 0,
        "mean_gross_bps": None,
        "median_gross_bps": None,
        "p25_gross_bps": None,
        "p75_gross_bps": None,
        "mean_net_bps": None,
        "median_net_bps": None,
        "net_positive_hit_rate": None,
        "valid_fold_count": 0,
        "positive_net_fold_count": 0,
        "min_fold_event_count": 0,
        "folds": [],
    }


def _best_horizon(horizon_stats: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, Mapping[str, Any]]:
    candidates = [
        (label, stats)
        for label, stats in horizon_stats.items()
        if stats.get("mean_net_bps") is not None
    ]
    if not candidates:
        return None, {}
    return max(candidates, key=lambda item: float(item[1].get("mean_net_bps") or -999999.0))


def _robust_distribution(*, best_stats: Mapping[str, Any], event_count: int) -> bool:
    return bool(
        event_count >= MIN_TOTAL_EVENTS
        and best_stats.get("mean_net_bps") is not None
        and float(best_stats["mean_net_bps"]) > MIN_NET_MEAN_BPS
        and best_stats.get("median_net_bps") is not None
        and float(best_stats["median_net_bps"]) >= MIN_NET_MEDIAN_BPS
        and best_stats.get("net_positive_hit_rate") is not None
        and float(best_stats["net_positive_hit_rate"]) >= MIN_NET_POSITIVE_HIT_RATE
        and int(best_stats.get("valid_fold_count", 0) or 0) == FOLD_COUNT
        and int(best_stats.get("positive_net_fold_count", 0) or 0) >= MIN_POSITIVE_FOLDS
        and int(best_stats.get("min_fold_event_count", 0) or 0) >= MIN_FOLD_EVENTS
    )


def _best_variant(rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get("best_net_mean_bps") is not None]
    if not candidates:
        return None
    best = max(
        candidates,
        key=lambda row: (
            int(row.get("positive_net_fold_count", 0) or 0),
            float(row.get("best_net_mean_bps") or -999999.0),
            int(row.get("event_count", 0) or 0),
        ),
    )
    return {
        "variant_id": str(best.get("variant_id", "")),
        "family_id": str(best.get("family_id", "")),
        "status": str(best.get("status", "")),
        "event_count": int(best.get("event_count", 0) or 0),
        "best_horizon": best.get("best_horizon"),
        "best_net_mean_bps": best.get("best_net_mean_bps"),
        "positive_net_fold_count": int(best.get("positive_net_fold_count", 0) or 0),
        "candidate_generation_allowed": False,
    }


def _status(*, data_ready: bool, robust_variants: list[Mapping[str, Any]]) -> str:
    if not data_ready:
        return "refinement_data_blocked"
    if robust_variants:
        return "refinement_completed_event_ledger_backtest_ready_candidate_blocked"
    return "refinement_completed_no_robust_distribution_edge"


def _blockers(*, data_ready: bool, status: str) -> list[str]:
    blockers: list[str] = []
    if not data_ready:
        blockers.append("btc_intraday_refinement_data_not_ready")
    if status == "refinement_completed_no_robust_distribution_edge":
        blockers.append("btc_intraday_refinement_no_robust_net_positive_distribution_edge")
    blockers.append("btc_intraday_refinement_candidate_generation_blocked_until_event_ledger_backtest")
    blockers.append("btc_intraday_refinement_requires_walk_forward_regime_cost_stress")
    blockers.append("btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model")
    blockers.append("btc_intraday_refinement_paper_live_locked")
    return _dedupe(blockers)


def _interpretation(
    *,
    data_ready: bool,
    robust_variants: list[Mapping[str, Any]],
    variant_results: list[Mapping[str, Any]],
) -> list[str]:
    if not data_ready:
        return ["short-cycle alpha refinement could not run because probe/data prerequisites are missing"]
    if robust_variants:
        best = _best_variant(robust_variants)
        variant_id = best["variant_id"] if best else "unknown"
        return [
            f"{variant_id} passed the bounded distribution refinement screen after diagnostic taker cost",
            "this only authorizes research-only event-ledger backtest design; it does not authorize a candidate or trading path",
            "true scalping remains blocked until 1m/tick/orderbook/spread/latency/queue evidence exists",
        ]
    sample_ready = sum(1 for row in variant_results if int(row.get("event_count", 0) or 0) >= MIN_TOTAL_EVENTS)
    return [
        f"{sample_ready} refined variants had enough samples, but none met the net-positive fold-stability screen",
        "continue alpha research with additional public context or a materially different intraday family before scalping work",
        "candidate generation, paper review, live trading, and true scalping remain locked",
    ]


def _data_context(*, root: Path, db_path: Path, data_status: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "db_path": _relpath(db_path, root),
        "db_exists": db_path.exists(),
        "exchange": "binance_spot",
        "symbol": "BTCUSDT",
        "market_type": str(_mapping(data_status.get("instrument")).get("market_type", "missing")),
        "source_type": str(_mapping(data_status.get("metadata")).get("source_type", "missing")),
        "data_status": str(data_status.get("status", "missing") or "missing"),
        "data_status_blockers": _list_of_strings(data_status.get("blockers")),
    }


def _load_rows(db_path: Path, *, interval: str) -> list[dict[str, Any]]:
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT open_time_ms, open, high, low, close, volume
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ?
            ORDER BY open_time_ms ASC
            """,
            ("binance_spot", "BTCUSDT", interval),
        ).fetchall()
    return [dict(row) for row in rows]


def _rolling_extreme_previous(values: list[float], window: int, *, maximum: bool) -> list[float]:
    out: list[float] = []
    indexes: deque[int] = deque()
    for i, value in enumerate(values):
        while indexes and indexes[0] < i - window:
            indexes.popleft()
        out.append(values[indexes[0]] if indexes else value)
        while indexes and ((values[indexes[-1]] <= value) if maximum else (values[indexes[-1]] >= value)):
            indexes.pop()
        indexes.append(i)
    return out


def _rolling_sums(values: list[float]) -> list[float]:
    out = [0.0]
    total = 0.0
    for value in values:
        total += value
        out.append(total)
    return out


def _window_average(prefix_sums: list[float], start: int, end: int) -> float:
    if start < 0 or end <= start:
        return 0.0
    return (prefix_sums[end] - prefix_sums[start]) / (end - start)


def _fifteen_minute_trend_map(rows_15m: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    closes = [float(row["close"]) for row in rows_15m]
    times = [int(row["open_time_ms"]) for row in rows_15m]
    trend: dict[int, dict[str, float]] = {}
    for i in range(16, len(rows_15m)):
        trend[times[i]] = {
            "1h": (closes[i] / closes[i - 4]) - 1.0,
            "2h": (closes[i] / closes[i - 8]) - 1.0,
            "4h": (closes[i] / closes[i - 16]) - 1.0,
        }
    return trend


def _fold_id(index: int, row_count: int) -> int:
    return min(FOLD_COUNT - 1, index * FOLD_COUNT // row_count)


def _resolve_data_path(root: Path, data_status: Mapping[str, Any]) -> Path:
    data_quality = _mapping(data_status.get("data_quality"))
    sqlite = _mapping(data_status.get("sqlite"))
    value = data_quality.get("sqlite_path") or data_quality.get("data_path") or sqlite.get("db_path") or "data/market_data.sqlite"
    path = Path(str(value))
    return path if path.is_absolute() else root / path


def _taker_fee_bps(cost_model: Mapping[str, Any]) -> float:
    fee_model = _mapping(cost_model.get("fee_model"))
    fee_tier = _mapping(cost_model.get("fee_tier"))
    value = cost_model.get("taker_fee_bps", fee_tier.get("taker_fee_bps", fee_model.get("taker_fee_bps", 5.0)))
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 5.0


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    index = (len(sorted_values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    return round(float(value), 6)


def _maybe_path(root: Path, path: Path) -> str | None:
    full = root / path
    return _relpath(full, root) if full.exists() else None


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
