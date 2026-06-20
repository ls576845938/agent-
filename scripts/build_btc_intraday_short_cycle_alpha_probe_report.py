#!/usr/bin/env python3
"""Build a BTC intraday short-cycle alpha distribution probe report.

The probe is research-only. It labels 5m events with future return
distributions to decide whether a short-cycle alpha family deserves an
event-ledger backtest. It does not create strategy candidates, orders, paper
review, or live unlocks.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Mapping


DEFAULT_OUTPUT_ROOT = Path("artifacts/btc_candidate_gate/latest")
BTC_INTRADAY_PLAN = Path("artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_plan_report.json")
BTC_DATA_STATUS = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_COST_MODEL = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")
REQUIRED_INTERVALS = ("5m", "15m")
FORWARD_HORIZONS = {"30m": 6, "60m": 12, "120m": 24}
MIN_EVENT_COUNT_FOR_DISTRIBUTION = 300
MIN_ALPHA_NET_MEAN_BPS = 0.0
FIVE_MINUTES_MS = 5 * 60 * 1000
FIFTEEN_MINUTES_MS = 15 * 60 * 1000


def build_btc_intraday_short_cycle_alpha_probe_report(
    *,
    repo_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    plan = _read_json(root / BTC_INTRADAY_PLAN)
    data_status = _read_json(root / BTC_DATA_STATUS)
    cost_model = _read_json(root / BTC_COST_MODEL)
    db_path = _resolve_data_path(root, data_status)
    taker_fee_bps = _taker_fee_bps(cost_model)
    round_trip_cost_bps = round(2.0 * taker_fee_bps, 6)

    data_context = _data_context(root=root, data_status=data_status, db_path=db_path)
    data_ready = (
        bool(plan.get("intraday_research_distribution_allowed", False))
        and data_context["db_exists"]
        and all(row["row_count"] > 0 for row in data_context["intervals"].values())
    )
    family_rows: list[dict[str, Any]] = []
    if data_ready:
        rows_5m = _load_rows(db_path, exchange="binance_spot", symbol="BTCUSDT", interval="5m")
        rows_15m = _load_rows(db_path, exchange="binance_spot", symbol="BTCUSDT", interval="15m")
        family_rows = _probe_families(rows_5m=rows_5m, rows_15m=rows_15m, round_trip_cost_bps=round_trip_cost_bps)

    sample_ready_families = [
        row for row in family_rows if row["event_count"] >= MIN_EVENT_COUNT_FOR_DISTRIBUTION
    ]
    positive_net_families = [
        row
        for row in sample_ready_families
        if row["best_net_mean_bps"] is not None and row["best_net_mean_bps"] > MIN_ALPHA_NET_MEAN_BPS
    ]
    status = _status(data_ready=data_ready, positive_net_families=positive_net_families)
    blockers = _blockers(data_ready=data_ready, status=status, data_context=data_context)
    return {
        "schema_version": "btc_intraday_short_cycle_alpha_probe_report_v1",
        "generated_at": generated_at or _utc_z_now(),
        "commit": _git(["rev-parse", "--short", "HEAD"], cwd=root),
        "branch": _git(["branch", "--show-current"], cwd=root),
        "asset": "btc",
        "symbol": "BTCUSDT",
        "scope": "research_only_distribution_probe_no_candidate_no_paper_no_live",
        "status": status,
        "decision": (
            "run_event_ledger_backtest_for_best_short_cycle_family"
            if positive_net_families
            else ("continue_intraday_alpha_research" if data_ready else "repair_intraday_probe_data")
        ),
        "next_required_action": (
            "design_research_only_event_ledger_backtest_for_best_probe_family"
            if positive_net_families
            else ("refine_short_cycle_event_definitions_before_candidate" if data_ready else "repair_5m_15m_sqlite_data")
        ),
        "distribution_probe_completed": data_ready,
        "alpha_distribution_observed": bool(positive_net_families),
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "source_intraday_short_cycle_alpha_plan": _maybe_path(root, BTC_INTRADAY_PLAN),
        "source_data_status": _maybe_path(root, BTC_DATA_STATUS),
        "source_cost_model": _maybe_path(root, BTC_COST_MODEL),
        "data_context": data_context,
        "cost_context": {
            "cost_model_status": str(cost_model.get("status", "missing") or "missing"),
            "taker_fee_bps": taker_fee_bps,
            "round_trip_taker_cost_bps": round_trip_cost_bps,
            "cost_is_diagnostic_not_fill_ledger_pnl": True,
        },
        "probe_parameters": {
            "event_bar_interval": "5m",
            "context_interval": "15m",
            "forward_return_horizons": list(FORWARD_HORIZONS),
            "min_event_count_for_distribution": MIN_EVENT_COUNT_FOR_DISTRIBUTION,
            "min_alpha_net_mean_bps": MIN_ALPHA_NET_MEAN_BPS,
            "lookahead_used_for_signal": False,
            "future_returns_used_only_as_labels": True,
        },
        "family_results": family_rows,
        "best_family": _best_family(positive_net_families or sample_ready_families or family_rows),
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
            positive_net_families=positive_net_families,
            sample_ready_families=sample_ready_families,
        ),
        "blockers": blockers,
    }


def write_btc_intraday_short_cycle_alpha_probe_report(payload: Mapping[str, Any], output_root: Path) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    output = output_root / "btc_intraday_short_cycle_alpha_probe_report.json"
    output.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--generated-at", default="")
    args = parser.parse_args()
    payload = build_btc_intraday_short_cycle_alpha_probe_report(
        repo_root=Path(args.repo_root),
        generated_at=args.generated_at or None,
    )
    print(write_btc_intraday_short_cycle_alpha_probe_report(payload, Path(args.output_root)))


def _probe_families(
    *,
    rows_5m: list[dict[str, Any]],
    rows_15m: list[dict[str, Any]],
    round_trip_cost_bps: float,
) -> list[dict[str, Any]]:
    closes = [float(row["close"]) for row in rows_5m]
    highs = [float(row["high"]) for row in rows_5m]
    lows = [float(row["low"]) for row in rows_5m]
    opens = [float(row["open"]) for row in rows_5m]
    volumes = [float(row["volume"]) for row in rows_5m]
    times = [int(row["open_time_ms"]) for row in rows_5m]
    trend_15m = _fifteen_minute_trend_map(rows_15m)
    families: dict[str, list[int]] = {
        "volatility_compression_reclaim_intraday_v0": [],
        "liquidation_exhaustion_reclaim_intraday_v0": [],
        "orderflow_confirmed_momentum_intraday_v0": [],
    }
    volume_sums = _rolling_sums(volumes)
    for i in range(100, len(rows_5m) - max(FORWARD_HORIZONS.values())):
        avg_vol_72 = _window_average(volume_sums, i - 72, i)
        if avg_vol_72 <= 0:
            continue
        context_ts = times[i] - (times[i] % FIFTEEN_MINUTES_MS)
        context_trend = trend_15m.get(context_ts, 0.0)
        prev12_high = max(highs[i - 12 : i])
        prev12_low = min(lows[i - 12 : i])
        prev72_high = max(highs[i - 72 : i])
        prev72_low = min(lows[i - 72 : i])
        range12_pct = (prev12_high - prev12_low) / closes[i - 1]
        range72_pct = (prev72_high - prev72_low) / closes[i - 1]
        if (
            range72_pct > 0
            and range12_pct <= 0.35 * range72_pct
            and closes[i] > prev12_high
            and volumes[i] >= 1.15 * avg_vol_72
            and context_trend >= -0.0025
        ):
            families["volatility_compression_reclaim_intraday_v0"].append(i)

        prev_return_bps = ((closes[i - 1] / closes[i - 2]) - 1.0) * 10_000.0
        if (
            prev_return_bps <= -75.0
            and volumes[i - 1] >= 1.8 * avg_vol_72
            and closes[i] > max(opens[i], highs[i - 1])
            and context_trend >= -0.02
        ):
            families["liquidation_exhaustion_reclaim_intraday_v0"].append(i)

        prev24_high = max(highs[i - 24 : i])
        if (
            closes[i] > prev24_high
            and volumes[i] >= 1.5 * avg_vol_72
            and context_trend > 0
        ):
            families["orderflow_confirmed_momentum_intraday_v0"].append(i)

    rows = [
        _family_result(
            family_id=family_id,
            event_indexes=indexes,
            closes=closes,
            round_trip_cost_bps=round_trip_cost_bps,
        )
        for family_id, indexes in families.items()
    ]
    rows.append(
        {
            "family_id": "funding_premium_reversion_intraday_v0",
            "status": "context_blocked_missing_intraday_funding_premium",
            "event_count": 0,
            "distribution_sample_ready": False,
            "alpha_distribution_observed": False,
            "best_horizon": None,
            "best_net_mean_bps": None,
            "horizon_stats": {},
            "notes": [
                "funding/premium can be an intraday context overlay, but current 5m probe has no intraday funding/premium series"
            ],
        }
    )
    return rows


def _family_result(
    *,
    family_id: str,
    event_indexes: list[int],
    closes: list[float],
    round_trip_cost_bps: float,
) -> dict[str, Any]:
    horizon_stats: dict[str, dict[str, Any]] = {}
    best_horizon: str | None = None
    best_net_mean: float | None = None
    for label, bars in FORWARD_HORIZONS.items():
        values = [((closes[i + bars] / closes[i]) - 1.0) * 10_000.0 for i in event_indexes]
        stats = _return_stats(values, round_trip_cost_bps)
        horizon_stats[label] = stats
        net_mean = stats["mean_net_bps"]
        if net_mean is not None and (best_net_mean is None or net_mean > best_net_mean):
            best_net_mean = net_mean
            best_horizon = label
    sample_ready = len(event_indexes) >= MIN_EVENT_COUNT_FOR_DISTRIBUTION
    alpha_observed = bool(sample_ready and best_net_mean is not None and best_net_mean > MIN_ALPHA_NET_MEAN_BPS)
    return {
        "family_id": family_id,
        "status": (
            "distribution_edge_observed"
            if alpha_observed
            else ("distribution_sample_ready_no_net_edge" if sample_ready else "sample_too_sparse")
        ),
        "event_count": len(event_indexes),
        "distribution_sample_ready": sample_ready,
        "alpha_distribution_observed": alpha_observed,
        "best_horizon": best_horizon,
        "best_net_mean_bps": _round_or_none(best_net_mean),
        "horizon_stats": horizon_stats,
        "notes": [],
    }


def _return_stats(values: list[float], round_trip_cost_bps: float) -> dict[str, Any]:
    if not values:
        return {
            "mean_gross_bps": None,
            "median_gross_bps": None,
            "p25_gross_bps": None,
            "p75_gross_bps": None,
            "mean_net_bps": None,
            "median_net_bps": None,
            "gross_positive_hit_rate": None,
            "net_positive_hit_rate": None,
        }
    sorted_values = sorted(values)
    net_values = [value - round_trip_cost_bps for value in values]
    return {
        "mean_gross_bps": _round(sum(values) / len(values)),
        "median_gross_bps": _round(median(values)),
        "p25_gross_bps": _round(_percentile(sorted_values, 0.25)),
        "p75_gross_bps": _round(_percentile(sorted_values, 0.75)),
        "mean_net_bps": _round(sum(net_values) / len(net_values)),
        "median_net_bps": _round(median(net_values)),
        "gross_positive_hit_rate": _round(sum(1 for value in values if value > 0.0) / len(values)),
        "net_positive_hit_rate": _round(sum(1 for value in net_values if value > 0.0) / len(net_values)),
    }


def _fifteen_minute_trend_map(rows_15m: list[dict[str, Any]]) -> dict[int, float]:
    closes = [float(row["close"]) for row in rows_15m]
    times = [int(row["open_time_ms"]) for row in rows_15m]
    trend: dict[int, float] = {}
    for i in range(8, len(rows_15m)):
        trend[times[i]] = (closes[i] / closes[i - 8]) - 1.0
    return trend


def _data_context(*, root: Path, data_status: Mapping[str, Any], db_path: Path) -> dict[str, Any]:
    intervals = {}
    for interval in REQUIRED_INTERVALS:
        intervals[interval] = _sqlite_interval_status(db_path, interval)
    return {
        "db_path": _relpath(db_path, root),
        "db_exists": db_path.exists(),
        "exchange": "binance_spot",
        "symbol": "BTCUSDT",
        "market_type": str(_mapping(data_status.get("instrument")).get("market_type", "missing")),
        "source_type": str(_mapping(data_status.get("metadata")).get("source_type", "missing")),
        "intervals": intervals,
        "data_status": str(data_status.get("status", "missing") or "missing"),
        "data_status_blockers": _list_of_strings(data_status.get("blockers")),
    }


def _sqlite_interval_status(db_path: Path, interval: str) -> dict[str, Any]:
    if not db_path.exists():
        return {"row_count": 0, "sample_start": "", "sample_end": ""}
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT COUNT(*) AS row_count, MIN(open_time) AS sample_start, MAX(open_time) AS sample_end
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ?
            """,
            ("binance_spot", "BTCUSDT", interval),
        ).fetchone()
    return {
        "row_count": int(row["row_count"] or 0),
        "sample_start": str(row["sample_start"] or ""),
        "sample_end": str(row["sample_end"] or ""),
    }


def _load_rows(db_path: Path, *, exchange: str, symbol: str, interval: str) -> list[dict[str, Any]]:
    with sqlite3.connect(str(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT open_time_ms, open_time, open, high, low, close, volume
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ?
            ORDER BY open_time_ms ASC
            """,
            (exchange, symbol, interval),
        ).fetchall()
    return [dict(row) for row in rows]


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


def _best_family(rows: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in rows if row.get("best_net_mean_bps") is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda row: float(row.get("best_net_mean_bps") or -999999.0))
    return {
        "family_id": str(best.get("family_id", "")),
        "status": str(best.get("status", "")),
        "event_count": int(best.get("event_count", 0) or 0),
        "best_horizon": best.get("best_horizon"),
        "best_net_mean_bps": best.get("best_net_mean_bps"),
        "candidate_generation_allowed": False,
    }


def _status(*, data_ready: bool, positive_net_families: list[Mapping[str, Any]]) -> str:
    if not data_ready:
        return "probe_data_blocked"
    if positive_net_families:
        return "probe_completed_candidate_blocked"
    return "probe_completed_no_distribution_edge"


def _blockers(*, data_ready: bool, status: str, data_context: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not data_ready:
        blockers.append("btc_intraday_probe_data_not_ready")
    if not _mapping(data_context.get("intervals")).get("5m", {}).get("row_count"):
        blockers.append("btc_intraday_probe_5m_rows_missing")
    if not _mapping(data_context.get("intervals")).get("15m", {}).get("row_count"):
        blockers.append("btc_intraday_probe_15m_rows_missing")
    if status == "probe_completed_no_distribution_edge":
        blockers.append("btc_intraday_probe_no_net_positive_distribution_edge")
    blockers.append("btc_intraday_probe_candidate_generation_blocked_until_event_ledger_backtest")
    blockers.append("btc_intraday_probe_requires_walk_forward_regime_cost_stress")
    blockers.append("btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model")
    blockers.append("btc_intraday_probe_paper_live_locked")
    return _dedupe(blockers)


def _interpretation(
    *,
    data_ready: bool,
    positive_net_families: list[Mapping[str, Any]],
    sample_ready_families: list[Mapping[str, Any]],
) -> list[str]:
    if not data_ready:
        return ["intraday short-cycle probe could not run because 5m/15m SQLite evidence is unavailable"]
    if positive_net_families:
        best = _best_family(positive_net_families)
        family_id = best["family_id"] if best else "unknown"
        return [
            f"{family_id} has a net-positive forward-return distribution after diagnostic taker round-trip cost",
            "this is not a tradable result; the next step is a research-only event-ledger backtest with full costs",
            "candidate generation, paper review, live trading, and true scalping remain locked",
        ]
    if sample_ready_families:
        return [
            "short-cycle events have enough samples but no net-positive distribution edge after diagnostic taker cost",
            "refine event definitions or add missing public context before any event-ledger candidate work",
            "candidate generation, paper review, live trading, and true scalping remain locked",
        ]
    return [
        "short-cycle event definitions are too sparse for distribution conclusions",
        "broaden research-only event definitions before any event-ledger candidate work",
        "candidate generation, paper review, live trading, and true scalping remain locked",
    ]


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


def _round_or_none(value: float | None) -> float | None:
    return _round(value) if value is not None else None


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
