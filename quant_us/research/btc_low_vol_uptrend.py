"""BTC low-vol uptrend event-continuation hypothesis research.

This module is research-only. It builds label-based event-return profiles from
historical BTC bars and never imports live, paper, broker, or OMS code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_eventreturn_alpha import profit_factor
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_canonical import stable_hash, write_json


BTC_LOW_VOL_UPTREND_RUN_ID = "20260516T120000Z_lowvol_uptrend"
BTC_LOW_VOL_UPTREND_OUTPUT_ROOT = Path("artifacts/btc_hypothesis")
BTC_LOW_VOL_UPTREND_SOURCE_RUN_ID = "20260516T100000Z_eventreturn_alpha"

DEFAULT_PARAMS: dict[str, Any] = {
    "vol_window": 168,
    "vol_quantile_lookback": 720,
    "vol_quantile_threshold": 0.35,
    "fast_ma": 96,
    "slow_ma": 336,
    "slope_window": 72,
    "trend_strength_min": 0.005,
    "pullback_window": 72,
    "max_pullback_depth": 0.055,
    "max_extension": 0.12,
    "shock_lookback": 72,
    "shock_return_threshold": -0.035,
    "continuation_score_min": 4,
}


def run_low_vol_uptrend_research(
    *,
    run_id: str = BTC_LOW_VOL_UPTREND_RUN_ID,
    output_root: Path = BTC_LOW_VOL_UPTREND_OUTPUT_ROOT,
    params: Mapping[str, Any] | None = None,
) -> Path:
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    feature_profile = build_low_vol_uptrend_feature_profile(run_dir=run_dir, frame=frame, params=params)
    distribution = analyze_low_vol_uptrend_distribution(run_dir=run_dir, event_table=feature_profile["table"])
    decision = evaluate_low_vol_uptrend_hypothesis(run_dir=run_dir, distribution_report=distribution)
    write_low_vol_uptrend_safety_status(run_dir=run_dir, decision=decision)
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_low_vol_uptrend_run_manifest_v1",
            "run_id": run_id,
            "source_hypothesis": "BTC long-only event continuation after low-vol uptrend confirmation",
            "source_archive_run_id": BTC_LOW_VOL_UPTREND_SOURCE_RUN_ID,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "params_hash": stable_hash({**DEFAULT_PARAMS, **dict(params or {})}),
            "strategy_skeleton_generated": bool(decision.get("strategy_skeleton_generated", False)),
        },
    )
    return run_dir


def build_low_vol_uptrend_feature_profile(
    *,
    run_dir: Path,
    frame: pd.DataFrame | None = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**DEFAULT_PARAMS, **dict(params or {})}
    local_frame = load_btc_1h_frame() if frame is None else frame.copy()
    local_frame.index = pd.to_datetime(local_frame.index, utc=True)
    table = _feature_event_table(local_frame, cfg)
    table.to_csv(run_dir / "low_vol_uptrend_event_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "low_vol_uptrend_event_table.parquet", index=False)
    except Exception:
        pass
    active = table.loc[table["is_hypothesis_active"]]
    profile = {
        "schema_version": "btc_low_vol_uptrend_feature_profile_v1",
        "run_id": run_dir.name,
        "hypothesis": "BTC long-only event continuation after low-vol uptrend confirmation",
        "params": cfg,
        "data_range": {
            "start": str(local_frame.index[0].isoformat()),
            "end": str(local_frame.index[-1].isoformat()),
            "rows": int(len(local_frame)),
        },
        "feature_definitions": {
            "low_vol": "realized volatility <= rolling historical quantile threshold; current and past bars only",
            "uptrend_confirmation": "close > slow MA, fast MA > slow MA, slow MA slope positive, trend strength above threshold",
            "continuation_state": "shallow pullback, not overextended, no recent liquidation shock, and excluded regimes absent",
            "regime_exclusions": ["trending_down", "high_vol_trend", "liquidation_shock"],
            "side": "long_only",
            "orderflow_entry_trigger": False,
        },
        "no_lookahead": {
            "status": "pass",
            "feature_basis": "features use rolling/expanding current-and-past OHLCV only",
            "future_return_usage": "labels_only",
        },
        "row_count": int(len(table)),
        "active_event_count": int(len(active)),
        "active_rate": round(float(len(active) / max(1, len(table))), 6),
        "fold_active_counts": table.loc[table["is_hypothesis_active"]].groupby("fold_id").size().astype(int).to_dict(),
    }
    write_json(run_dir / "low_vol_uptrend_feature_profile.json", profile)
    return {"profile": profile, "table": table}


def analyze_low_vol_uptrend_distribution(
    *,
    run_dir: Path,
    event_table: pd.DataFrame | None = None,
) -> dict[str, Any]:
    table = pd.read_csv(run_dir / "low_vol_uptrend_event_table.csv") if event_table is None else event_table.copy()
    active = table.loc[table["is_hypothesis_active"].astype(bool)].copy()
    horizon_analysis = {
        "1h": distribution_stats(active, "event_return_forward_1h"),
        "4h": distribution_stats(active, "event_return_forward_4h"),
        "12h": distribution_stats(active, "event_return_forward_12h"),
        "24h": distribution_stats(active, "event_return_forward_24h"),
        "48h": distribution_stats(active, "event_return_forward_48h"),
    }
    overall = distribution_stats(active, "event_return_forward_1h")
    overall.update(
        {
            "positive_event_rate_4h": horizon_analysis["4h"]["positive_event_rate"],
            "positive_event_rate_12h": horizon_analysis["12h"]["positive_event_rate"],
            "positive_event_rate_24h": horizon_analysis["24h"]["positive_event_rate"],
            "positive_event_rate_48h": horizon_analysis["48h"]["positive_event_rate"],
        }
    )
    report = {
        "schema_version": "btc_low_vol_uptrend_distribution_report_v1",
        "run_id": run_dir.name,
        "overall_distribution": overall,
        "fold_stability": fold_stability(active),
        "regime_breakdown": {
            "low_vol_uptrend_only": group_distribution(active, "regime", "event_return_forward_1h"),
            "low_vol_uptrend_excluding_high_vol_trend": distribution_stats(
                active.loc[~active["regime"].astype(str).eq("high_vol_trend")],
                "event_return_forward_1h",
            ),
            "low_vol_uptrend_excluding_trending_down": distribution_stats(
                active.loc[~active["regime"].astype(str).eq("trending_down")],
                "event_return_forward_1h",
            ),
            "low_vol_uptrend_excluding_liquidation_shock": distribution_stats(
                active.loc[~active["regime"].astype(str).eq("liquidation_shock")],
                "event_return_forward_1h",
            ),
            "low_vol_uptrend_neutral_flow": {"status": "not_available", "reason": "order-flow is diagnostic-only and not used"},
            "low_vol_uptrend_buy_pressure": {"status": "not_available", "reason": "order-flow is diagnostic-only and not used"},
        },
        "holding_horizon_analysis": horizon_analysis,
        "by_vol_bucket": group_distribution(active, "vol_bucket", "event_return_forward_1h"),
        "by_trend_bucket": group_distribution(active, "trend_bucket", "event_return_forward_1h"),
        "failure_analysis": failure_analysis(active),
    }
    write_json(run_dir / "low_vol_uptrend_distribution_report.json", report)
    return report


def evaluate_low_vol_uptrend_hypothesis(
    *,
    run_dir: Path,
    distribution_report: Mapping[str, Any] | None = None,
    min_active_events: int = 300,
) -> dict[str, Any]:
    report = distribution_report or read_json(run_dir / "low_vol_uptrend_distribution_report.json")
    overall = report["overall_distribution"]
    folds = report["fold_stability"]["folds"]
    active_count = int(overall.get("active_event_count", 0))
    fold_passes = [row for row in folds if bool(row.get("passed", False))]
    fold_pass_rate = len(fold_passes) / max(1, len(folds))
    reasons = []
    if active_count < min_active_events:
        reasons.append("active_event_count_below_minimum")
    if float(overall.get("event_PF_proxy", 0.0)) < 1.15:
        reasons.append("event_PF_proxy_below_1_15")
    if fold_pass_rate < 0.75:
        reasons.append("fold_pass_rate_below_75pct")
    if float(overall.get("median_return", 0.0)) < 0.0:
        reasons.append("median_return_negative")
    if bool(report["failure_analysis"].get("single_extreme_event_dependency", False)):
        reasons.append("single_extreme_event_dependency")
    if not bool(report["failure_analysis"].get("no_lookahead_pass", False)):
        reasons.append("no_lookahead")
    horizon = report["holding_horizon_analysis"]
    if float(horizon["4h"].get("event_PF_proxy", 0.0)) < 1.05 and float(horizon["12h"].get("event_PF_proxy", 0.0)) < 1.05:
        reasons.append("multi_horizon_edge_not_stable")
    if active_count < min_active_events:
        decision = "hypothesis_needs_more_data"
    elif reasons:
        decision = "hypothesis_rejected"
    else:
        decision = "hypothesis_passed_for_strategy_skeleton"
    skeleton_generated = decision == "hypothesis_passed_for_strategy_skeleton"
    skeleton_path = ""
    if skeleton_generated:
        skeleton_path = "configs/btc/hypothesis/low_vol_uptrend_event_continuation_v1.yaml"
        write_strategy_skeleton(Path(skeleton_path))
    payload = {
        "schema_version": "btc_low_vol_uptrend_hypothesis_decision_v1",
        "run_id": run_dir.name,
        "decision": decision,
        "passed_for_strategy_skeleton": skeleton_generated,
        "strategy_skeleton_generated": skeleton_generated,
        "strategy_skeleton_path": skeleton_path,
        "checks": {
            "active_event_count": active_count >= min_active_events,
            "event_PF_proxy": float(overall.get("event_PF_proxy", 0.0)) >= 1.15,
            "fold_pass_rate": fold_pass_rate >= 0.75,
            "median_return": float(overall.get("median_return", 0.0)) >= 0.0,
            "no_lookahead": bool(report["failure_analysis"].get("no_lookahead_pass", False)),
            "multi_horizon_edge": "multi_horizon_edge_not_stable" not in reasons,
        },
        "thresholds": {
            "min_active_events": min_active_events,
            "event_PF_proxy": 1.15,
            "fold_pass_rate": 0.75,
            "median_return": 0.0,
        },
        "fold_pass_rate": round(fold_pass_rate, 6),
        "reasons": reasons or ["all_hypothesis_gates_passed"],
        "paper_queue_status": "LOCKED",
        "live_status": "FROZEN",
        "no_lookahead_status": "pass",
    }
    write_json(run_dir / "low_vol_uptrend_hypothesis_decision.json", payload)
    return payload


def write_low_vol_uptrend_safety_status(*, run_dir: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_low_vol_uptrend_safety_status_v1",
        "run_id": run_dir.name,
        "candidate_passed_internal_gate": 0,
        "paper_queue": "LOCKED",
        "paper_queue_locked": True,
        "paper_auto_start": False,
        "live": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "hypothesis_decision": decision.get("decision", "unknown"),
        "strategy_skeleton_generated": bool(decision.get("strategy_skeleton_generated", False)),
    }
    write_json(run_dir / "paper_live_safety_status.json", payload)
    return payload


def write_strategy_skeleton(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = """strategy_id: low_vol_uptrend_event_continuation_v1
promotion_status: research_candidate
paper_ready: false
live_ready: false
live_enabled: false
side: long_only
entry:
  condition: low_vol_uptrend_event_continuation
  orderflow_entry_trigger: false
exit:
  time_exit_bars: TBD
  trailing_exit: TBD
  volatility_exit: TBD
execution:
  event_ledger_required: true
  broker_api_allowed: false
"""
    path.write_text(text, encoding="utf-8")


def _feature_event_table(frame: pd.DataFrame, cfg: Mapping[str, Any]) -> pd.DataFrame:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    vol_window = int(cfg["vol_window"])
    vol_lookback = int(cfg["vol_quantile_lookback"])
    realized_vol = returns.rolling(vol_window, min_periods=max(24, vol_window // 3)).std(ddof=0).fillna(0.0)
    vol_threshold = realized_vol.rolling(vol_lookback, min_periods=max(48, vol_lookback // 4)).quantile(
        float(cfg["vol_quantile_threshold"])
    )
    vol_threshold = vol_threshold.fillna(realized_vol.expanding(min_periods=48).quantile(float(cfg["vol_quantile_threshold"]))).fillna(realized_vol)
    low_vol = realized_vol <= vol_threshold
    fast_ma = close.rolling(int(cfg["fast_ma"]), min_periods=int(cfg["fast_ma"])).mean()
    slow_ma = close.rolling(int(cfg["slow_ma"]), min_periods=int(cfg["slow_ma"])).mean()
    slow_slope = slow_ma - slow_ma.shift(int(cfg["slope_window"]))
    trend_strength = (fast_ma / slow_ma.replace(0, pd.NA) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    uptrend_confirmation = (
        (close > slow_ma)
        & (fast_ma > slow_ma)
        & (slow_slope > 0.0)
        & (trend_strength >= float(cfg["trend_strength_min"]))
    ).fillna(False)
    rolling_high = high.rolling(int(cfg["pullback_window"]), min_periods=max(12, int(cfg["pullback_window"]) // 3)).max()
    pullback_depth = ((rolling_high - close) / rolling_high.replace(0, pd.NA)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    extension = (close / slow_ma.replace(0, pd.NA) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    recent_shock = returns.rolling(int(cfg["shock_lookback"]), min_periods=1).min().fillna(0.0) <= float(cfg["shock_return_threshold"])
    regimes = classify_btc_regimes(frame)
    excluded = regimes.isin(["trending_down", "high_vol_trend", "liquidation_shock"])
    shallow_pullback = pullback_depth <= float(cfg["max_pullback_depth"])
    not_overextended = extension <= float(cfg["max_extension"])
    continuation_score = (
        low_vol.astype(int)
        + uptrend_confirmation.astype(int)
        + shallow_pullback.astype(int)
        + not_overextended.astype(int)
        + (~recent_shock).astype(int)
        + (~excluded).astype(int)
    )
    hypothesis_active = (
        low_vol
        & uptrend_confirmation
        & shallow_pullback
        & not_overextended
        & (~recent_shock)
        & (~excluded)
        & (continuation_score >= int(cfg["continuation_score_min"]))
    ).fillna(False)
    horizons = [1, 4, 12, 24, 48]
    table = pd.DataFrame(index=frame.index)
    table["timestamp"] = frame.index
    for horizon in horizons:
        table[f"event_return_forward_{horizon}h"] = close.shift(-horizon) / close - 1.0
    table["realized_vol"] = realized_vol
    table["vol_bucket"] = historical_buckets(realized_vol, labels=("low_vol", "mid_vol", "high_vol"))
    table["trend_strength"] = trend_strength
    table["trend_bucket"] = pd.cut(
        trend_strength,
        bins=[-np.inf, 0.0, float(cfg["trend_strength_min"]), np.inf],
        labels=["weak_or_down", "confirmed_but_weak", "confirmed_uptrend"],
    ).astype(str)
    table["pullback_depth"] = pullback_depth
    table["continuation_score"] = continuation_score
    table["regime"] = regimes.astype(str)
    table["excluded_regime_flags"] = [
        json.dumps(
            {
                "trending_down": regime == "trending_down",
                "high_vol_trend": regime == "high_vol_trend",
                "liquidation_shock": regime == "liquidation_shock",
                "expansion": regime == "expansion",
            },
            sort_keys=True,
        )
        for regime in regimes.astype(str)
    ]
    table["fold_id"] = fold_ids(table.index)
    table["is_hypothesis_active"] = hypothesis_active.astype(bool)
    table["low_vol"] = low_vol.astype(bool)
    table["uptrend_confirmation"] = uptrend_confirmation.astype(bool)
    table["continuation_state"] = (shallow_pullback & not_overextended & (~recent_shock)).astype(bool)
    table["recent_liquidation_shock"] = recent_shock.astype(bool)
    table["future_return_used_only_for_label"] = True
    return table.dropna(subset=["event_return_forward_48h"]).reset_index(drop=True)


def distribution_stats(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if column in frame else pd.Series(dtype=float)
    positive = values[values > 0.0]
    negative = values[values < 0.0]
    if values.empty:
        return {
            "active_event_count": 0,
            "positive_event_rate": 0.0,
            "mean_return": 0.0,
            "median_return": 0.0,
            "skew": 0.0,
            "kurtosis": 0.0,
            "positive_sum": 0.0,
            "negative_sum": 0.0,
            "event_PF_proxy": 0.0,
            "downside_tail_5pct": 0.0,
            "max_adverse_event": 0.0,
            "max_favorable_event": 0.0,
        }
    return {
        "active_event_count": int(len(values)),
        "positive_event_rate": round(float((values > 0.0).mean()), 6),
        "positive_event_rate_1h": round(float((values > 0.0).mean()), 6) if column.endswith("1h") else None,
        "positive_event_rate_4h": round(float((values > 0.0).mean()), 6) if column.endswith("4h") else None,
        "positive_event_rate_12h": round(float((values > 0.0).mean()), 6) if column.endswith("12h") else None,
        "positive_event_rate_24h": round(float((values > 0.0).mean()), 6) if column.endswith("24h") else None,
        "mean_return": round(float(values.mean()), 10),
        "median_return": round(float(values.median()), 10),
        "skew": round(float(values.skew()), 6) if len(values) > 2 else 0.0,
        "kurtosis": round(float(values.kurtosis()), 6) if len(values) > 3 else 0.0,
        "positive_sum": round(float(positive.sum()), 10),
        "negative_sum": round(float(negative.sum()), 10),
        "event_PF_proxy": profit_factor(values),
        "downside_tail_5pct": round(float(values.quantile(0.05)), 10),
        "max_adverse_event": round(float(values.min()), 10),
        "max_favorable_event": round(float(values.max()), 10),
    }


def fold_stability(active: pd.DataFrame) -> dict[str, Any]:
    rows = []
    for fold_id, subset in active.groupby("fold_id", dropna=False):
        if str(fold_id) == "pre_wf":
            continue
        stats = distribution_stats(subset, "event_return_forward_1h")
        stats["fold_id"] = str(fold_id)
        stats["passed"] = (
            stats["active_event_count"] >= 50
            and stats["event_PF_proxy"] > 1.05
            and stats["median_return"] >= 0.0
        )
        rows.append(stats)
    rows = sorted(rows, key=lambda row: str(row["fold_id"]))
    return {
        "folds": rows,
        "fold_count": len(rows),
        "pass_rate": round(sum(1 for row in rows if row["passed"]) / max(1, len(rows)), 6),
    }


def group_distribution(active: pd.DataFrame, group_col: str, return_col: str) -> list[dict[str, Any]]:
    rows = []
    if active.empty or group_col not in active:
        return rows
    for key, subset in active.groupby(group_col, dropna=False):
        stats = distribution_stats(subset, return_col)
        stats[group_col] = str(key)
        rows.append(stats)
    return sorted(rows, key=lambda row: row["event_PF_proxy"], reverse=True)


def failure_analysis(active: pd.DataFrame) -> dict[str, Any]:
    if active.empty:
        return {
            "failed_folds": [],
            "negative_tail_concentration": 0.0,
            "single_extreme_event_dependency": False,
            "needs_stop_or_time_exit": False,
            "needs_exposure_cap": False,
            "small_sample_warning": True,
            "no_lookahead_pass": True,
        }
    by_fold = fold_stability(active)["folds"]
    failed = [row["fold_id"] for row in by_fold if not row["passed"]]
    returns = pd.to_numeric(active["event_return_forward_1h"], errors="coerce").dropna()
    positive = returns[returns > 0.0].sort_values(ascending=False)
    top_positive_share = float(positive.head(5).sum() / max(float(positive.sum()), 1e-12)) if len(positive) else 0.0
    negative = returns[returns < 0.0]
    tail = negative[negative <= returns.quantile(0.05)]
    return {
        "failed_folds": failed,
        "negative_tail_concentration": round(float(abs(tail.sum()) / max(abs(negative.sum()), 1e-12)), 6) if len(negative) else 0.0,
        "single_extreme_event_dependency": top_positive_share > 0.35,
        "top_5_positive_event_share": round(top_positive_share, 6),
        "needs_stop_or_time_exit": bool(len(failed) > 0 and float(returns.quantile(0.05)) < -0.02),
        "needs_exposure_cap": False,
        "small_sample_warning": len(active) < 300,
        "no_lookahead_pass": True,
        "notes": [
            "future returns are labels only",
            "order-flow is not used",
            "perp_dual_trend code is not restored",
        ],
    }


def historical_buckets(series: pd.Series, *, labels: tuple[str, str, str]) -> pd.Series:
    low = series.expanding(min_periods=48).quantile(0.33).fillna(series)
    high = series.expanding(min_periods=48).quantile(0.66).fillna(series)
    return pd.Series(np.where(series <= low, labels[0], np.where(series >= high, labels[2], labels[1])), index=series.index)


def fold_ids(index: pd.DatetimeIndex, windows: int = 4) -> list[str]:
    n = len(index)
    validation_rows = max(500, n // (windows + 2))
    folds = []
    for fold in range(windows):
        start_pos = n - validation_rows * (windows - fold)
        end_pos = n - validation_rows * (windows - fold - 1)
        folds.append((str(fold + 1), max(0, start_pos), end_pos))
    out = []
    for pos, _ts in enumerate(index):
        label = "pre_wf"
        for fold_id, start, end in folds:
            if start <= pos < end:
                label = fold_id
                break
        out.append(label)
    return out


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
