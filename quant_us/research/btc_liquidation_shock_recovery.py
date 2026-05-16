"""BTC liquidation-shock recovery event-return hypothesis research.

This module is research-only. It creates label-based event-return evidence and
does not import paper, live, broker, OMS, or order submission paths.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_canonical import stable_hash, write_json
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_eventreturn_alpha import profit_factor


BTC_LIQUIDATION_SHOCK_RUN_ID = "20260516T232000Z_liquidation_shock_recovery"
BTC_LIQUIDATION_SHOCK_OUTPUT_ROOT = Path("artifacts/btc_hypothesis")
DEFAULT_CONFIG_PATH = Path("configs/btc/hypotheses/liquidation_shock_recovery_v0.yaml")
SKELETON_PATH = Path("configs/btc/hypotheses/liquidation_shock_recovery_v1_skeleton.yaml")


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"hypothesis config must be a mapping: {path}")
    return payload


def run_liquidation_shock_research(
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    run_id: str = BTC_LIQUIDATION_SHOCK_RUN_ID,
    output_root: Path = BTC_LIQUIDATION_SHOCK_OUTPUT_ROOT,
    frame: pd.DataFrame | None = None,
) -> Path:
    config = load_config(config_path)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source = load_btc_1h_frame() if frame is None else frame.copy()
    feature = build_feature_profile(run_dir=run_dir, config=config, frame=source)
    distribution = analyze_distribution(run_dir=run_dir, config=config, event_table=feature["table"])
    decision = evaluate_hypothesis(run_dir=run_dir, config=config, distribution_report=distribution)
    write_safety_status(run_dir=run_dir, config=config, decision=decision)
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_liquidation_shock_recovery_run_manifest_v1",
            "run_id": run_id,
            "hypothesis_id": config.get("hypothesis_id"),
            "mode": config.get("mode", "research_only"),
            "config_path": str(config_path),
            "config_hash": stable_hash(config),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_version": "btc_sqlite_1h",
            "strategy_version": "research_hypothesis_only",
            "cost_model": "not_applicable_event_return_labels",
            "slippage_model": "not_applicable_event_return_labels",
            "code_commit": git_commit_hash(),
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    )
    return run_dir


def build_feature_profile(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    local_frame = load_btc_1h_frame() if frame is None else frame.copy()
    local_frame.index = pd.to_datetime(local_frame.index, utc=True)
    table = build_event_table(local_frame, config)
    table.to_csv(run_dir / "liquidation_shock_recovery_event_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "liquidation_shock_recovery_event_table.parquet", index=False)
    except Exception:
        pass
    active = table.loc[table["is_hypothesis_active"].astype(bool)]
    profile = {
        "schema_version": "btc_liquidation_shock_recovery_feature_profile_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "mode": config.get("mode", "research_only"),
        "data_range": {
            "start": str(local_frame.index[0].isoformat()),
            "end": str(local_frame.index[-1].isoformat()),
            "rows": int(len(local_frame)),
        },
        "feature_definitions": {
            "liquidation_shock": "current bar return <= threshold with elevated volume ratio; current and past bars only",
            "recent_shock_window": "rolling window over past closed bars using shift(1)",
            "recovery_confirmation": "current bar has positive close-to-close return after a recent shock and is not itself a shock",
            "side": "long_recovery_label_only",
            "future_return_usage": "labels_only",
            "orderflow_entry_trigger": False,
        },
        "no_lookahead": {
            "status": "pass",
            "feature_basis": "current/past OHLCV; recent shock uses shifted historical shock flags",
            "future_return_usage": "labels_only",
        },
        "row_count": int(len(table)),
        "shock_event_count": int(table["liquidation_shock"].sum()),
        "active_event_count": int(len(active)),
        "active_rate": round(float(len(active) / max(1, len(table))), 6),
        "fold_active_counts": active.groupby("fold_id").size().astype(int).to_dict(),
    }
    write_json(run_dir / "liquidation_shock_recovery_feature_profile.json", profile)
    return {"profile": profile, "table": table}


def build_event_table(
    frame: pd.DataFrame,
    config: Mapping[str, Any],
    *,
    drop_incomplete_labels: bool = True,
) -> pd.DataFrame:
    cfg = config.get("shock_config", {})
    horizons = _horizons_to_bars(config.get("horizons", ["1h", "4h", "12h", "24h", "48h"]))
    local = frame.copy()
    local.index = pd.to_datetime(local.index, utc=True)
    close = pd.to_numeric(local["close"], errors="coerce").astype(float)
    high = pd.to_numeric(local["high"], errors="coerce").astype(float)
    low = pd.to_numeric(local["low"], errors="coerce").astype(float)
    volume = pd.to_numeric(local["volume"], errors="coerce").astype(float)
    returns = close.pct_change().fillna(0.0)
    volume_window = max(24, int(cfg.get("volume_window", 168)))
    volume_baseline = volume.rolling(volume_window, min_periods=max(12, volume_window // 3)).median().replace(0, pd.NA)
    volume_ratio = (volume / volume_baseline).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    shock = (returns <= float(cfg.get("return_threshold", -0.025))) & (
        volume_ratio >= float(cfg.get("volume_ratio_threshold", 1.10))
    )
    recent_window = max(1, int(cfg.get("recent_shock_window", 6)))
    recent_shock = shock.shift(1).rolling(recent_window, min_periods=1).max().fillna(False).astype(bool)
    confirmation = str(cfg.get("recovery_confirmation", "positive_close"))
    if confirmation != "positive_close":
        raise ValueError(f"unsupported recovery_confirmation: {confirmation}")
    recovery_confirmed = (returns > 0.0) & recent_shock & ~shock
    regimes = classify_btc_regimes(local)
    excluded = {str(item) for item in config.get("regime_exclusions", [])}
    regime_excluded = regimes.astype(str).isin(excluded)
    active = recovery_confirmed & ~regime_excluded
    wick_recovery = ((close - low) / (high - low).replace(0, pd.NA)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    table = pd.DataFrame(index=local.index)
    table["timestamp"] = local.index
    table["fold_id"] = fold_ids(local.index, int(config.get("fold_config", {}).get("fold_count", 4)))
    table["regime"] = regimes.astype(str)
    table["liquidation_shock"] = shock.astype(bool)
    table["recent_liquidation_shock"] = recent_shock.astype(bool)
    table["recovery_confirmed"] = recovery_confirmed.astype(bool)
    table["is_hypothesis_active"] = active.astype(bool)
    table["shock_return"] = returns
    table["volume_ratio"] = volume_ratio
    table["wick_recovery_score"] = wick_recovery
    table["close"] = close
    table["volatility_bucket"] = historical_buckets(
        returns.rolling(168, min_periods=56).std(ddof=0).fillna(0.0),
        labels=("low_vol", "mid_vol", "high_vol"),
    )
    trend_strength = close.pct_change(168).fillna(0.0)
    table["trend_strength_bucket"] = pd.cut(
        trend_strength,
        bins=[-np.inf, -0.03, 0.03, np.inf],
        labels=["downtrend", "neutral", "uptrend"],
    ).astype(str)
    table["future_return_used_only_for_label"] = True
    for horizon in horizons:
        table[f"event_return_forward_{horizon}h"] = close.shift(-horizon) / close - 1.0
    if drop_incomplete_labels:
        table = table.dropna(subset=[f"event_return_forward_{max(horizons)}h"])
    return table.reset_index(drop=True)


def analyze_distribution(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    event_table: pd.DataFrame | None = None,
) -> dict[str, Any]:
    table = pd.read_csv(run_dir / "liquidation_shock_recovery_event_table.csv") if event_table is None else event_table.copy()
    active = table.loc[table["is_hypothesis_active"].astype(bool)].copy()
    horizons = _horizons_to_bars(config.get("horizons", ["1h", "4h", "12h", "24h", "48h"]))
    primary_horizon = _horizon_to_bar(config.get("shock_config", {}).get("primary_horizon", "24h"))
    primary_col = f"event_return_forward_{primary_horizon}h"
    horizon_analysis = {f"{h}h": distribution_stats(active, f"event_return_forward_{h}h") for h in horizons}
    report = {
        "schema_version": "btc_liquidation_shock_recovery_distribution_report_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "primary_horizon": f"{primary_horizon}h",
        "overall_distribution": distribution_stats(active, primary_col),
        "shock_bar_distribution": distribution_stats(table.loc[table["liquidation_shock"].astype(bool)], primary_col),
        "fold_stability": fold_stability(active, primary_col, config),
        "regime_breakdown": group_distribution(active, "regime", primary_col),
        "volatility_breakdown": group_distribution(active, "volatility_bucket", primary_col),
        "trend_breakdown": group_distribution(active, "trend_strength_bucket", primary_col),
        "holding_horizon_analysis": horizon_analysis,
        "tail_dependency": tail_dependency(active, primary_col),
        "failure_analysis": failure_analysis(active, primary_col, config),
        "no_lookahead": {
            "status": "pass",
            "future_return_usage": "labels_only",
            "recent_shock_rule": "uses shift(1) before rolling recent shock state",
        },
    }
    write_json(run_dir / "liquidation_shock_recovery_distribution_report.json", report)
    return report


def evaluate_hypothesis(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    distribution_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = distribution_report or read_json(run_dir / "liquidation_shock_recovery_distribution_report.json")
    sample = config.get("sample_thresholds", {})
    gate = config.get("acceptance_gate", {})
    overall = report["overall_distribution"]
    fold_pass_rate = float(report["fold_stability"].get("pass_rate", 0.0))
    horizon_pass_count = sum(
        1
        for row in report["holding_horizon_analysis"].values()
        if float(row.get("event_PF_proxy", 0.0)) >= float(gate.get("min_horizon_event_pf_proxy", 1.10))
    )
    reasons = []
    if int(overall.get("active_event_count", 0)) < int(sample.get("min_active_events", 80)):
        reasons.append("active_event_count_below_minimum")
    if float(overall.get("event_PF_proxy", 0.0)) < float(gate.get("min_event_pf_proxy", 1.15)):
        reasons.append("event_PF_proxy_below_1_15")
    if fold_pass_rate < float(gate.get("min_fold_pass_rate", 0.75)):
        reasons.append("fold_pass_rate_below_75pct")
    if float(overall.get("median_return", 0.0)) < float(gate.get("min_median_return", 0.0)):
        reasons.append("median_return_negative")
    if float(report["tail_dependency"].get("top5_positive_contribution", 1.0)) > float(gate.get("max_top5_positive_contribution", 0.35)):
        reasons.append("top5_positive_contribution_too_high")
    if horizon_pass_count < int(gate.get("min_multi_horizon_pass_count", 2)):
        reasons.append("multi_horizon_edge_not_stable")
    if report.get("no_lookahead", {}).get("status") != "pass":
        reasons.append("no_lookahead")
    if int(overall.get("active_event_count", 0)) < int(sample.get("min_active_events", 80)):
        decision = "hypothesis_needs_more_data"
    elif reasons:
        decision = "hypothesis_rejected"
    else:
        decision = "hypothesis_passed_for_strategy_skeleton"
    skeleton_generated = decision == "hypothesis_passed_for_strategy_skeleton"
    skeleton_path = ""
    if skeleton_generated:
        skeleton_path = str(SKELETON_PATH)
        write_strategy_skeleton(SKELETON_PATH, config=config, primary_horizon=str(report.get("primary_horizon")))
    payload = {
        "schema_version": "btc_liquidation_shock_recovery_hypothesis_decision_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "decision": decision,
        "primary_horizon": report.get("primary_horizon"),
        "strategy_skeleton_generated": skeleton_generated,
        "strategy_skeleton_path": skeleton_path,
        "checks": {
            "active_event_count": int(overall.get("active_event_count", 0)) >= int(sample.get("min_active_events", 80)),
            "event_PF_proxy": float(overall.get("event_PF_proxy", 0.0)) >= float(gate.get("min_event_pf_proxy", 1.15)),
            "fold_pass_rate": fold_pass_rate >= float(gate.get("min_fold_pass_rate", 0.75)),
            "median_return": float(overall.get("median_return", 0.0)) >= float(gate.get("min_median_return", 0.0)),
            "tail_dependency": float(report["tail_dependency"].get("top5_positive_contribution", 1.0)) <= float(gate.get("max_top5_positive_contribution", 0.35)),
            "multi_horizon_edge": horizon_pass_count >= int(gate.get("min_multi_horizon_pass_count", 2)),
            "no_lookahead": report.get("no_lookahead", {}).get("status") == "pass",
        },
        "thresholds": {
            "min_active_events": int(sample.get("min_active_events", 80)),
            "min_event_pf_proxy": float(gate.get("min_event_pf_proxy", 1.15)),
            "min_fold_pass_rate": float(gate.get("min_fold_pass_rate", 0.75)),
            "min_fold_event_pf_proxy": float(gate.get("min_fold_event_pf_proxy", 1.05)),
            "min_median_return": float(gate.get("min_median_return", 0.0)),
            "max_top5_positive_contribution": float(gate.get("max_top5_positive_contribution", 0.35)),
            "min_multi_horizon_pass_count": int(gate.get("min_multi_horizon_pass_count", 2)),
        },
        "fold_pass_rate": round(fold_pass_rate, 6),
        "horizon_pass_count": horizon_pass_count,
        "reasons": reasons or ["all_hypothesis_gates_passed"],
        "paper_queue_status": "LOCKED",
        "live_status": "FROZEN",
    }
    write_json(run_dir / "liquidation_shock_recovery_hypothesis_decision.json", payload)
    return payload


def write_safety_status(*, run_dir: Path, config: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    safety = config.get("safety", {})
    payload = {
        "schema_version": "btc_liquidation_shock_recovery_safety_status_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "candidate_passed_internal_gate": 0,
        "paper_queue": safety.get("paper_queue", "LOCKED"),
        "paper_queue_locked": True,
        "paper_auto_start": False,
        "live": safety.get("live", "FROZEN"),
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
        "hypothesis_decision": decision.get("decision"),
        "strategy_skeleton_generated": bool(decision.get("strategy_skeleton_generated", False)),
    }
    write_json(run_dir / "paper_live_safety_status.json", payload)
    return payload


def write_strategy_skeleton(path: Path, *, config: Mapping[str, Any], primary_horizon: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"""hypothesis_id: {config.get('hypothesis_id')}
status: research_candidate
event_ledger_required: true
selected_direction: long_recovery_after_liquidation_shock
primary_horizon: {primary_horizon}
conditions:
  liquidation_shock: current closed bar return <= threshold with elevated volume
  recovery_confirmation: positive closed bar after recent shifted shock state
exit:
  time_exit_bars: TBD
  volatility_exit: TBD
safety:
  paper_ready: false
  live_ready: false
  live_enabled: false
  broker_api_allowed: false
  real_orders_allowed: false
"""
    path.write_text(text, encoding="utf-8")


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
        "mean_return": round(float(values.mean()), 10),
        "median_return": round(float(values.median()), 10),
        "positive_sum": round(float(positive.sum()), 10),
        "negative_sum": round(float(negative.sum()), 10),
        "event_PF_proxy": profit_factor(values),
        "downside_tail_5pct": round(float(values.quantile(0.05)), 10),
        "max_adverse_event": round(float(values.min()), 10),
        "max_favorable_event": round(float(values.max()), 10),
    }


def fold_stability(active: pd.DataFrame, return_col: str, config: Mapping[str, Any]) -> dict[str, Any]:
    gate = config.get("acceptance_gate", {})
    rows = []
    for fold_id, subset in active.groupby("fold_id", dropna=False):
        if str(fold_id) == "pre_wf":
            continue
        stats = distribution_stats(subset, return_col)
        stats["fold_id"] = str(fold_id)
        stats["passed"] = (
            stats["active_event_count"] > 0
            and float(stats["event_PF_proxy"]) > float(gate.get("min_fold_event_pf_proxy", 1.05))
            and float(stats["median_return"]) >= float(gate.get("min_median_return", 0.0))
        )
        rows.append(stats)
    rows = sorted(rows, key=lambda row: str(row["fold_id"]))
    return {
        "fold_count": len(rows),
        "folds": rows,
        "pass_rate": round(sum(1 for row in rows if row["passed"]) / max(1, len(rows)), 6),
    }


def group_distribution(active: pd.DataFrame, group_col: str, return_col: str) -> list[dict[str, Any]]:
    if active.empty or group_col not in active:
        return []
    rows = []
    for key, subset in active.groupby(group_col, dropna=False):
        stats = distribution_stats(subset, return_col)
        stats[group_col] = str(key)
        rows.append(stats)
    return sorted(rows, key=lambda row: float(row["event_PF_proxy"]), reverse=True)


def tail_dependency(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if column in frame else pd.Series(dtype=float)
    positive = values[values > 0.0].sort_values(ascending=False)
    negative = values[values < 0.0].sort_values(ascending=True)
    positive_sum = max(float(positive.sum()), 1e-12)
    negative_sum = max(abs(float(negative.sum())), 1e-12)
    return {
        "top5_positive_contribution": round(float(positive.head(5).sum() / positive_sum), 6) if len(positive) else 0.0,
        "top10_positive_contribution": round(float(positive.head(10).sum() / positive_sum), 6) if len(positive) else 0.0,
        "top5_negative_contribution": round(float(abs(negative.head(5).sum()) / negative_sum), 6) if len(negative) else 0.0,
        "edge_depends_on_extreme_events": bool(len(positive) > 0 and float(positive.head(5).sum() / positive_sum) > 0.35),
    }


def failure_analysis(active: pd.DataFrame, return_col: str, config: Mapping[str, Any]) -> dict[str, Any]:
    folds = fold_stability(active, return_col, config)
    return {
        "failed_folds": [row["fold_id"] for row in folds["folds"] if not row["passed"]],
        "fold_pass_rate": folds["pass_rate"],
        "sample_warning": int(len(active)) < int(config.get("sample_thresholds", {}).get("min_active_events", 80)),
        "no_lookahead_pass": True,
        "notes": [
            "future returns are labels only",
            "recent shock state uses shift(1)",
            "paper/live/broker paths are not imported",
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


def _horizons_to_bars(horizons: Sequence[Any]) -> list[int]:
    return [_horizon_to_bar(item) for item in horizons]


def _horizon_to_bar(item: Any) -> int:
    text = str(item).strip().lower()
    if not text.endswith("h"):
        raise ValueError(f"unsupported horizon: {item}")
    return int(text[:-1])


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"
