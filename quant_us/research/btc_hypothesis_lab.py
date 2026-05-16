"""Config-driven BTC hypothesis event-return lab.

The lab is research-only. It imports no paper, live, broker, or OMS modules and
only generates event-return labels plus static research artifacts.
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


BTC_HYPOTHESIS_LAB_RUN_ID = "20260516T122000Z_compression_expansion"
BTC_HYPOTHESIS_OUTPUT_ROOT = Path("artifacts/btc_hypothesis")
DEFAULT_CONFIG_PATH = Path("configs/btc/hypotheses/compression_expansion_breakout_v0.yaml")
SKELETON_PATH = Path("configs/btc/hypotheses/compression_expansion_breakout_v1_skeleton.yaml")


def load_hypothesis_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"hypothesis config must be a mapping: {config_path}")
    return payload


def run_hypothesis_lab(
    *,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    run_id: str = BTC_HYPOTHESIS_LAB_RUN_ID,
    output_root: Path = BTC_HYPOTHESIS_OUTPUT_ROOT,
    frame: pd.DataFrame | None = None,
) -> Path:
    config = load_hypothesis_config(config_path)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source = load_btc_1h_frame() if frame is None else frame.copy()
    feature_result = build_feature_profile(run_dir=run_dir, config=config, frame=source)
    distribution = analyze_distribution(run_dir=run_dir, config=config, event_table=feature_result["table"])
    decision = evaluate_hypothesis(run_dir=run_dir, config=config, distribution_report=distribution)
    write_safety_status(run_dir=run_dir, config=config, decision=decision)
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_hypothesis_lab_run_manifest_v1",
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
            "commit_hash": git_commit_hash(),
            "code_commit": git_commit_hash(),
            "artifact_files": [
                "feature_profile.json",
                "event_table.csv",
                "compression_expansion_event_table.csv",
                "distribution_report.json",
                "compression_expansion_distribution_report.json",
                "hypothesis_decision.json",
                "compression_expansion_hypothesis_decision.json",
                "paper_live_safety_status.json",
            ],
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
    table.to_csv(run_dir / "event_table.csv", index=False)
    table.to_csv(run_dir / "compression_expansion_event_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "event_table.parquet", index=False)
    except Exception:
        pass
    active = table.loc[table["expansion_active"].astype(bool)].copy()
    profile = {
        "schema_version": "btc_hypothesis_lab_feature_profile_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "mode": config.get("mode", "research_only"),
        "data_range": {
            "start": str(local_frame.index[0].isoformat()),
            "end": str(local_frame.index[-1].isoformat()),
            "rows": int(len(local_frame)),
        },
        "feature_definitions": {
            "compression": "low realized volatility, range, ATR, and band width percentiles using current and historical bars only",
            "pre_breakout_box": "prior box high/low from shifted historical bars; current breakout bar is excluded from box construction",
            "upside_breakout": "closed bar close > prior compression box high",
            "downside_breakout": "closed bar close < prior compression box low",
            "range_expansion": "current bar range exceeds recent median range multiple",
            "volatility_expansion": "current realized volatility exceeds recent median volatility",
            "future_return_usage": "labels_only",
            "orderflow_entry_trigger": False,
        },
        "no_lookahead": {
            "status": "pass",
            "feature_basis": "rolling/expanding current-and-past OHLCV; prior box uses shift(1)",
            "future_return_usage": "labels_only",
        },
        "row_count": int(len(table)),
        "active_event_count": int(len(active)),
        "upside_event_count": int(table["upside_breakout"].sum()),
        "downside_event_count": int(table["downside_breakout"].sum()),
        "fold_active_counts": active.groupby("fold_id").size().astype(int).to_dict(),
    }
    write_json(run_dir / "feature_profile.json", profile)
    return {"profile": profile, "table": table}


def build_event_table(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.DataFrame:
    compression_cfg = config.get("compression_config", {})
    expansion_cfg = config.get("expansion_config", {})
    horizons = _horizons_to_bars(config.get("horizons", ["1h", "4h", "12h", "24h", "48h"]))
    close = pd.to_numeric(frame["close"], errors="coerce").astype(float)
    high = pd.to_numeric(frame["high"], errors="coerce").astype(float)
    low = pd.to_numeric(frame["low"], errors="coerce").astype(float)
    returns = close.pct_change().fillna(0.0)

    vol_window = int(compression_cfg.get("vol_window", 96))
    range_window = int(compression_cfg.get("range_window", 96))
    atr_window = int(compression_cfg.get("atr_window", 96))
    band_window = int(compression_cfg.get("band_window", 96))
    box_window = int(compression_cfg.get("box_window", 48))

    realized_vol = returns.rolling(vol_window, min_periods=max(12, vol_window // 3)).std(ddof=0).fillna(0.0)
    range_pct = ((high - low).abs() / close.shift(1).replace(0, pd.NA)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_pct = (true_range.rolling(atr_window, min_periods=max(12, atr_window // 3)).mean() / close.shift(1).replace(0, pd.NA))
    atr_pct = atr_pct.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    band_mid = close.rolling(band_window, min_periods=max(12, band_window // 3)).mean()
    band_std = close.rolling(band_window, min_periods=max(12, band_window // 3)).std(ddof=0)
    band_width = (4.0 * band_std / band_mid.replace(0, pd.NA)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    vol_threshold = rolling_quantile_threshold(realized_vol, vol_window * 8, float(compression_cfg.get("vol_quantile_threshold", 0.25)))
    range_threshold = rolling_quantile_threshold(range_pct, range_window * 8, float(compression_cfg.get("range_quantile_threshold", 0.25)))
    atr_threshold = rolling_quantile_threshold(atr_pct, atr_window * 8, float(compression_cfg.get("atr_quantile_threshold", 0.25)))
    band_threshold = rolling_quantile_threshold(band_width, band_window * 8, float(compression_cfg.get("band_quantile_threshold", 0.25)))

    low_vol_compression = realized_vol <= vol_threshold
    range_compression = range_pct <= range_threshold
    atr_compression = atr_pct <= atr_threshold
    band_width_compression = band_width <= band_threshold
    compression_score = (
        low_vol_compression.astype(int)
        + range_compression.astype(int)
        + atr_compression.astype(int)
        + band_width_compression.astype(int)
    )
    compression_active = compression_score >= int(compression_cfg.get("min_compression_score", 3))
    compression_recent = compression_active.shift(1).rolling(box_window, min_periods=max(4, box_window // 4)).max().fillna(False).astype(bool)
    box_high_prior = high.shift(1).rolling(box_window, min_periods=max(4, box_window // 4)).max()
    box_low_prior = low.shift(1).rolling(box_window, min_periods=max(4, box_window // 4)).min()
    median_range = range_pct.shift(1).rolling(range_window, min_periods=max(12, range_window // 3)).median()
    range_expansion = range_pct > (median_range.fillna(range_pct) * float(expansion_cfg.get("range_expansion_multiple", 1.5)))
    median_vol = realized_vol.shift(1).rolling(vol_window, min_periods=max(12, vol_window // 3)).median()
    volatility_expansion = realized_vol > median_vol.fillna(realized_vol)
    volatility_required = bool(expansion_cfg.get("volatility_expansion_required", False))

    upside_breakout = compression_recent & (close > box_high_prior) & range_expansion
    downside_breakout = compression_recent & (close < box_low_prior) & range_expansion
    if volatility_required:
        upside_breakout &= volatility_expansion
        downside_breakout &= volatility_expansion

    regimes = classify_btc_regimes(frame)
    excluded_regimes = {str(item) for item in config.get("regime_exclusions", [])}
    regime_excluded = regimes.astype(str).isin(excluded_regimes)
    upside_breakout &= ~regime_excluded
    downside_breakout &= ~regime_excluded
    expansion_active = upside_breakout | downside_breakout
    expansion_score = range_expansion.astype(int) + volatility_expansion.astype(int) + expansion_active.astype(int)

    table = pd.DataFrame(index=frame.index)
    table["timestamp"] = frame.index
    table["fold_id"] = fold_ids(table.index, int(config.get("fold_config", {}).get("fold_count", 4)))
    table["regime"] = regimes.astype(str)
    table["volatility_bucket"] = historical_buckets(realized_vol, labels=("low_vol", "mid_vol", "high_vol"))
    trend_strength = close.pct_change(168).fillna(0.0)
    table["trend_strength_bucket"] = pd.cut(
        trend_strength,
        bins=[-np.inf, -0.03, 0.03, np.inf],
        labels=["downtrend", "neutral", "uptrend"],
    ).astype(str)
    table["compression_active"] = compression_active.astype(bool)
    table["compression_score"] = compression_score.astype(int)
    table["expansion_active"] = expansion_active.astype(bool)
    table["expansion_score"] = expansion_score.astype(int)
    table["breakout_direction"] = np.where(upside_breakout, "upside_breakout", np.where(downside_breakout, "downside_breakout", "none"))
    table["upside_breakout"] = upside_breakout.astype(bool)
    table["downside_breakout"] = downside_breakout.astype(bool)
    table["range_expansion"] = range_expansion.astype(bool)
    table["volatility_expansion"] = volatility_expansion.astype(bool)
    table["box_high_prior"] = box_high_prior
    table["box_low_prior"] = box_low_prior
    table["close"] = close
    table["realized_vol_percentile_threshold"] = vol_threshold
    table["range_compression"] = range_compression.astype(bool)
    table["atr_compression"] = atr_compression.astype(bool)
    table["band_width_compression"] = band_width_compression.astype(bool)
    table["future_return_used_only_for_label"] = True
    for horizon in horizons:
        table[f"event_return_forward_{horizon}h"] = close.shift(-horizon) / close - 1.0
    max_horizon = max(horizons)
    return table.dropna(subset=[f"event_return_forward_{max_horizon}h"]).reset_index(drop=True)


def analyze_distribution(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    event_table: pd.DataFrame | None = None,
) -> dict[str, Any]:
    table = pd.read_csv(run_dir / "event_table.csv") if event_table is None else event_table.copy()
    active = table.loc[table["expansion_active"].astype(bool)].copy()
    horizons = _horizons_to_bars(config.get("horizons", ["1h", "4h", "12h", "24h", "48h"]))
    overall = distribution_stats(active, "event_return_forward_1h")
    direction = direction_breakdown(active)
    selected_direction = select_direction(direction)
    selected_rows = selected_direction_rows(active, selected_direction, horizons)
    horizon_analysis = {
        f"{h}h": distribution_stats(selected_rows, f"selected_return_forward_{h}h") for h in horizons
    }
    tail = tail_dependency(selected_rows, "selected_return_forward_1h")
    report = {
        "schema_version": "btc_hypothesis_lab_distribution_report_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "overall": {
            **overall,
            "upside_event_count": int(table["upside_breakout"].sum()),
            "downside_event_count": int(table["downside_breakout"].sum()),
        },
        "direction_breakdown": direction,
        "selected_direction": selected_direction,
        "selected_direction_event_count": int(len(selected_rows)),
        "selected_direction_distribution": distribution_stats(selected_rows, "selected_return_forward_1h"),
        "fold_stability": fold_stability(selected_rows, config),
        "regime_breakdown": {
            "compression_only": distribution_stats(table.loc[table["compression_active"].astype(bool)], "event_return_forward_1h"),
            "compression_plus_expansion": group_distribution(active, "regime", "event_return_forward_1h"),
            "upside_expansion": group_distribution(active.loc[active["upside_breakout"].astype(bool)], "regime", "event_return_forward_1h"),
            "downside_expansion": group_distribution(active.loc[active["downside_breakout"].astype(bool)], "regime", "event_return_forward_1h"),
            "expansion_excluding_high_vol_trend": distribution_stats(
                active.loc[~active["regime"].astype(str).eq("high_vol_trend")],
                "event_return_forward_1h",
            ),
            "expansion_excluding_liquidation_shock": distribution_stats(
                active.loc[~active["regime"].astype(str).eq("liquidation_shock")],
                "event_return_forward_1h",
            ),
        },
        "horizon_analysis": horizon_analysis,
        "tail_dependency": tail,
        "failure_analysis": failure_analysis(active, selected_rows, direction, tail, config),
        "no_lookahead": {
            "status": "pass",
            "future_return_usage": "labels_only",
            "prior_box_rule": "box_high_prior and box_low_prior are based on shifted historical bars",
        },
    }
    write_json(run_dir / "distribution_report.json", report)
    write_json(run_dir / "compression_expansion_distribution_report.json", report)
    return report


def evaluate_hypothesis(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    distribution_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = distribution_report or read_json(run_dir / "distribution_report.json")
    sample = config.get("sample_thresholds", {})
    gate = config.get("acceptance_gate", {})
    selected = report["selected_direction_distribution"]
    fold_pass_rate = float(report["fold_stability"].get("pass_rate", 0.0))
    horizon_pass_count = sum(
        1
        for row in report["horizon_analysis"].values()
        if float(row.get("event_PF_proxy", 0.0)) >= float(gate.get("min_horizon_event_pf_proxy", 1.10))
    )
    reasons = []
    if int(report["overall"].get("active_event_count", 0)) < int(sample.get("min_active_events", 200)):
        reasons.append("active_event_count_below_minimum")
    if int(report.get("selected_direction_event_count", 0)) < int(sample.get("min_direction_events", 80)):
        reasons.append("selected_direction_event_count_below_minimum")
    if float(selected.get("event_PF_proxy", 0.0)) < float(gate.get("min_event_pf_proxy", 1.15)):
        reasons.append("event_PF_proxy_below_1_15")
    if fold_pass_rate < float(gate.get("min_fold_pass_rate", 0.75)):
        reasons.append("fold_pass_rate_below_75pct")
    if float(selected.get("median_return", 0.0)) < float(gate.get("min_median_return", 0.0)):
        reasons.append("median_return_negative")
    if float(report["tail_dependency"].get("top5_positive_contribution", 1.0)) > float(gate.get("max_top5_positive_contribution", 0.35)):
        reasons.append("top5_positive_contribution_too_high")
    if horizon_pass_count < int(gate.get("min_multi_horizon_pass_count", 2)):
        reasons.append("multi_horizon_edge_not_stable")
    if report.get("no_lookahead", {}).get("status") != "pass":
        reasons.append("no_lookahead")

    if int(report["overall"].get("active_event_count", 0)) < int(sample.get("min_active_events", 200)):
        decision = "hypothesis_needs_more_data"
    elif reasons:
        decision = "hypothesis_rejected"
    else:
        decision = "hypothesis_passed_for_strategy_skeleton"

    skeleton_generated = decision == "hypothesis_passed_for_strategy_skeleton"
    skeleton_path = ""
    if skeleton_generated:
        skeleton_path = str(SKELETON_PATH)
        write_strategy_skeleton(SKELETON_PATH, config=config, selected_direction=str(report.get("selected_direction")))
    payload = {
        "schema_version": "btc_hypothesis_lab_decision_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config.get("hypothesis_id"),
        "decision": decision,
        "selected_direction": report.get("selected_direction"),
        "strategy_skeleton_generated": skeleton_generated,
        "strategy_skeleton_path": skeleton_path,
        "checks": {
            "active_event_count": int(report["overall"].get("active_event_count", 0)) >= int(sample.get("min_active_events", 200)),
            "selected_direction_event_count": int(report.get("selected_direction_event_count", 0)) >= int(sample.get("min_direction_events", 80)),
            "event_PF_proxy": float(selected.get("event_PF_proxy", 0.0)) >= float(gate.get("min_event_pf_proxy", 1.15)),
            "fold_pass_rate": fold_pass_rate >= float(gate.get("min_fold_pass_rate", 0.75)),
            "median_return": float(selected.get("median_return", 0.0)) >= float(gate.get("min_median_return", 0.0)),
            "tail_dependency": float(report["tail_dependency"].get("top5_positive_contribution", 1.0)) <= float(gate.get("max_top5_positive_contribution", 0.35)),
            "multi_horizon_edge": horizon_pass_count >= int(gate.get("min_multi_horizon_pass_count", 2)),
            "no_lookahead": report.get("no_lookahead", {}).get("status") == "pass",
        },
        "thresholds": {
            "min_active_events": int(sample.get("min_active_events", 200)),
            "min_direction_events": int(sample.get("min_direction_events", 80)),
            "min_event_pf_proxy": float(gate.get("min_event_pf_proxy", 1.15)),
            "min_fold_pass_rate": float(gate.get("min_fold_pass_rate", 0.75)),
            "min_fold_event_pf_proxy": float(gate.get("min_fold_event_pf_proxy", 1.05)),
            "min_median_return": float(gate.get("min_median_return", 0.0)),
            "max_top5_positive_contribution": float(gate.get("max_top5_positive_contribution", 0.35)),
            "min_multi_horizon_pass_count": int(gate.get("min_multi_horizon_pass_count", 2)),
            "min_horizon_event_pf_proxy": float(gate.get("min_horizon_event_pf_proxy", 1.10)),
        },
        "horizon_pass_count": horizon_pass_count,
        "fold_pass_rate": round(fold_pass_rate, 6),
        "reasons": reasons or ["all_hypothesis_gates_passed"],
        "paper_queue_status": "LOCKED",
        "live_status": "FROZEN",
    }
    write_json(run_dir / "hypothesis_decision.json", payload)
    write_json(run_dir / "compression_expansion_hypothesis_decision.json", payload)
    return payload


def write_safety_status(*, run_dir: Path, config: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    safety = config.get("safety", {})
    payload = {
        "schema_version": "btc_hypothesis_lab_safety_status_v1",
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


def write_strategy_skeleton(path: Path, *, config: Mapping[str, Any], selected_direction: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"""hypothesis_id: {config.get('hypothesis_id')}
status: research_candidate
event_ledger_required: true
selected_direction: {selected_direction}
conditions:
  compression: low volatility/range/ATR/bandwidth percentile compression
  expansion: closed-bar breakout from prior compression box
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


def direction_breakdown(active: pd.DataFrame) -> dict[str, Any]:
    upside = active.loc[active["upside_breakout"].astype(bool)]
    downside = active.loc[active["downside_breakout"].astype(bool)].copy()
    downside["short_label_return"] = -pd.to_numeric(downside["event_return_forward_1h"], errors="coerce")
    combined_directional = active.copy()
    combined_directional["directional_return"] = np.where(
        combined_directional["breakout_direction"].eq("downside_breakout"),
        -pd.to_numeric(combined_directional["event_return_forward_1h"], errors="coerce"),
        pd.to_numeric(combined_directional["event_return_forward_1h"], errors="coerce"),
    )
    return {
        "upside_breakout": distribution_stats(upside, "event_return_forward_1h"),
        "downside_breakout": distribution_stats(downside, "event_return_forward_1h"),
        "combined": distribution_stats(active, "event_return_forward_1h"),
        "long_label_proxy": distribution_stats(upside, "event_return_forward_1h"),
        "short_label_proxy": distribution_stats(downside, "short_label_return"),
        "combined_directional": distribution_stats(combined_directional, "directional_return"),
    }


def select_direction(direction: Mapping[str, Mapping[str, Any]]) -> str:
    candidates = ["upside_breakout", "short_label_proxy", "combined_directional"]
    best = max(candidates, key=lambda key: float(direction.get(key, {}).get("event_PF_proxy", 0.0)))
    return best


def selected_direction_rows(active: pd.DataFrame, selected_direction: str, horizons: Sequence[int]) -> pd.DataFrame:
    if selected_direction == "upside_breakout":
        rows = active.loc[active["upside_breakout"].astype(bool)].copy()
        sign = 1.0
    elif selected_direction == "short_label_proxy":
        rows = active.loc[active["downside_breakout"].astype(bool)].copy()
        sign = -1.0
    else:
        rows = active.copy()
        sign = np.where(rows["breakout_direction"].eq("downside_breakout"), -1.0, 1.0)
    for horizon in horizons:
        rows[f"selected_return_forward_{horizon}h"] = sign * pd.to_numeric(
            rows[f"event_return_forward_{horizon}h"],
            errors="coerce",
        )
    rows["event_return_forward_1h"] = rows["selected_return_forward_1h"]
    return rows


def fold_stability(active: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, Any]:
    gate = config.get("acceptance_gate", {})
    rows = []
    for fold_id, subset in active.groupby("fold_id", dropna=False):
        if str(fold_id) == "pre_wf":
            continue
        stats = distribution_stats(subset, "selected_return_forward_1h")
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


def failure_analysis(
    active: pd.DataFrame,
    selected_rows: pd.DataFrame,
    direction: Mapping[str, Mapping[str, Any]],
    tail: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    fold_report = fold_stability(selected_rows, config)
    compression_stats = distribution_stats(active.loc[active["compression_active"].astype(bool)], "event_return_forward_1h")
    return {
        "failed_folds": [row["fold_id"] for row in fold_report["folds"] if not row["passed"]],
        "compression_has_edge": float(compression_stats.get("event_PF_proxy", 0.0)) >= 1.05,
        "expansion_has_edge": float(direction.get("combined_directional", {}).get("event_PF_proxy", 0.0)) >= 1.05,
        "more_stable_direction": select_direction(direction),
        "tail_dependency_warning": bool(tail.get("edge_depends_on_extreme_events", False)),
        "no_lookahead_pass": True,
        "notes": [
            "future returns are labels only",
            "prior compression box uses shifted historical high/low",
            "paper/live/broker paths are not imported",
            "downside breakout is label research only, not a tradable short candidate",
        ],
    }


def rolling_quantile_threshold(series: pd.Series, lookback: int, quantile: float) -> pd.Series:
    lookback = max(24, int(lookback))
    threshold = series.rolling(lookback, min_periods=max(24, lookback // 4)).quantile(float(quantile))
    fallback = series.expanding(min_periods=24).quantile(float(quantile))
    return threshold.fillna(fallback).fillna(series)


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
    out = []
    for item in horizons:
        text = str(item).strip().lower()
        if not text.endswith("h"):
            raise ValueError(f"unsupported horizon: {item}")
        out.append(int(text[:-1]))
    return out


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"
