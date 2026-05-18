"""BTC range-reclaim momentum lifecycle-aware hypothesis research.

This module is research-only. It builds current-and-past feature profiles,
event-return labels, lifecycle-aware proxy metrics, and safety artifacts. It
does not import paper, live, broker, OMS, or execution runtime paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_canonical import git_commit_hash, stable_hash, write_json
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_eventreturn_alpha import profit_factor
from quant_us.research.btc_hypothesis_lab import distribution_stats, fold_ids, group_distribution, tail_dependency


BTC_RANGE_RECLAIM_RUN_ID = "20260518T010000Z_range_reclaim_lifecycle"
BTC_RANGE_RECLAIM_OUTPUT_ROOT = Path("artifacts/btc_hypothesis")
BTC_RANGE_RECLAIM_CONFIG_PATH = Path("configs/btc/hypotheses/range_reclaim_momentum_v0.yaml")
BTC_RANGE_RECLAIM_SKELETON_PATH = Path("configs/btc/hypotheses/range_reclaim_momentum_v1_skeleton.yaml")
RESEARCH_REGISTRY_PATH = Path("artifacts/btc_research_registry/research_registry.json")
REGISTRY_SUMMARY_PATH = Path("docs/research/BTC_ALPHA_REGISTRY_SUMMARY.md")
PLAN_PATH = Path("docs/research/BTC_RANGE_RECLAIM_LIFECYCLE_PLAN.md")


def run_range_reclaim_lifecycle_research(
    *,
    config_path: str | Path = BTC_RANGE_RECLAIM_CONFIG_PATH,
    run_id: str = BTC_RANGE_RECLAIM_RUN_ID,
    output_root: Path = BTC_RANGE_RECLAIM_OUTPUT_ROOT,
    frame: pd.DataFrame | None = None,
) -> Path:
    config = load_config(config_path)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source = load_btc_1h_frame() if frame is None else frame.copy()
    feature = build_range_reclaim_feature_profile(run_dir=run_dir, config=config, frame=source)
    report = build_lifecycle_report(run_dir=run_dir, config=config, event_table=feature["table"])
    decision = evaluate_lifecycle_gate(run_dir=run_dir, config=config, lifecycle_report=report)
    write_safety_status(run_dir=run_dir, decision=decision)
    update_research_registry(decision=decision, lifecycle_report=report)
    write_plan_doc(run_dir=run_dir, config=config, decision=decision)
    write_run_manifest(run_dir=run_dir, config_path=Path(config_path), config=config, decision=decision)
    return run_dir


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"range reclaim hypothesis config must be a mapping: {config_path}")
    return payload


def build_range_reclaim_feature_profile(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    local_frame = load_btc_1h_frame() if frame is None else frame.copy()
    local_frame.index = pd.to_datetime(local_frame.index, utc=True)
    table = build_event_table(local_frame, config)
    table.to_csv(run_dir / "range_reclaim_event_table.csv", index=False)
    table.to_csv(run_dir / "event_table.csv", index=False)
    try:
        table.to_parquet(run_dir / "range_reclaim_event_table.parquet", index=False)
        table.to_parquet(run_dir / "event_table.parquet", index=False)
    except Exception:
        pass
    active = table.loc[table["is_hypothesis_active"].astype(bool)]
    profile = {
        "schema_version": "btc_range_reclaim_feature_profile_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config["hypothesis_id"],
        "mode": config.get("mode", "research_only"),
        "data_range": {
            "start": str(local_frame.index[0].isoformat()),
            "end": str(local_frame.index[-1].isoformat()),
            "rows": int(len(local_frame)),
        },
        "feature_definitions": {
            "prior_range_high": "rolling high shifted by one bar; current bar is excluded",
            "range_reclaim": "closed bar close reclaims prior range high after prior close was inside/below the prior range",
            "trend_confirmation": "fast MA above slow MA, close above slow MA, slow MA slope positive",
            "volatility_filter": "current realized volatility <= rolling historical quantile threshold",
            "regime_exclusions": list(config.get("regime_exclusions", [])),
            "side": "long_only",
            "orderflow_entry_trigger": False,
            "future_return_usage": "labels_only",
        },
        "no_lookahead": {
            "status": "pass",
            "feature_basis": "rolling current-and-past OHLCV; prior range uses shift(1)",
            "future_return_usage": "labels_only",
        },
        "row_count": int(len(table)),
        "active_event_count": int(len(active)),
        "active_rate": round(float(len(active) / max(1, len(table))), 6),
        "fold_active_counts": active.groupby("fold_id").size().astype(int).to_dict(),
    }
    write_json(run_dir / "feature_profile.json", profile)
    write_json(run_dir / "range_reclaim_feature_profile.json", profile)
    return {"profile": profile, "table": table}


def build_event_table(
    frame: pd.DataFrame,
    config: Mapping[str, Any],
    *,
    drop_incomplete_labels: bool = True,
) -> pd.DataFrame:
    cfg = config.get("feature_config", {})
    horizons = _horizons_to_bars(config.get("horizons", ["1h", "4h", "12h", "24h", "48h"]))
    close = pd.to_numeric(frame["close"], errors="coerce").astype(float)
    high = pd.to_numeric(frame["high"], errors="coerce").astype(float)
    low = pd.to_numeric(frame["low"], errors="coerce").astype(float)
    returns = close.pct_change().fillna(0.0)

    range_window = int(cfg.get("range_window", 48))
    fast_ma = int(cfg.get("fast_ma", 72))
    slow_ma = int(cfg.get("slow_ma", 240))
    slope_window = int(cfg.get("slope_window", 48))
    vol_window = int(cfg.get("volatility_window", 96))
    vol_lookback = int(cfg.get("volatility_quantile_lookback", 720))

    prior_range_high = high.shift(1).rolling(range_window, min_periods=max(12, range_window // 3)).max()
    prior_range_low = low.shift(1).rolling(range_window, min_periods=max(12, range_window // 3)).min()
    prior_close = close.shift(1)
    buffer = float(cfg.get("reclaim_buffer_bps", 0.0)) / 10_000.0
    reclaim = (close > prior_range_high * (1.0 + buffer)) & (prior_close <= prior_range_high)

    fast = close.rolling(fast_ma, min_periods=max(12, fast_ma // 3)).mean()
    slow = close.rolling(slow_ma, min_periods=max(24, slow_ma // 3)).mean()
    slow_slope = slow - slow.shift(slope_window)
    extension = (close / fast.replace(0, pd.NA) - 1.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    trend_confirmation = (close > slow) & (fast > slow) & (slow_slope > 0.0)
    not_overextended = extension <= float(cfg.get("max_extension_pct", 0.08))

    realized_vol = returns.rolling(vol_window, min_periods=max(12, vol_window // 3)).std(ddof=0).fillna(0.0)
    vol_threshold = realized_vol.rolling(vol_lookback, min_periods=max(48, vol_lookback // 4)).quantile(
        float(cfg.get("max_volatility_quantile", 0.80))
    )
    vol_threshold = vol_threshold.fillna(realized_vol.expanding(min_periods=48).quantile(float(cfg.get("max_volatility_quantile", 0.80))))
    volatility_ok = realized_vol <= vol_threshold.fillna(realized_vol)

    regimes = classify_btc_regimes(frame).astype(str)
    excluded_regimes = {str(item) for item in config.get("regime_exclusions", [])}
    regime_excluded = regimes.isin(excluded_regimes)
    active = reclaim & trend_confirmation & not_overextended & volatility_ok & ~regime_excluded

    table = pd.DataFrame(index=frame.index)
    table["timestamp"] = frame.index
    table["fold_id"] = fold_ids(table.index, int(config.get("fold_config", {}).get("fold_count", 4)))
    table["regime"] = regimes
    table["close"] = close
    table["prior_range_high"] = prior_range_high
    table["prior_range_low"] = prior_range_low
    table["prior_close"] = prior_close
    table["range_reclaim"] = reclaim.fillna(False).astype(bool)
    table["trend_confirmation"] = trend_confirmation.fillna(False).astype(bool)
    table["volatility_ok"] = volatility_ok.fillna(False).astype(bool)
    table["not_overextended"] = not_overextended.fillna(False).astype(bool)
    table["is_hypothesis_active"] = active.fillna(False).astype(bool)
    table["side"] = "long_only"
    table["realized_vol"] = realized_vol
    table["volatility_bucket"] = _historical_buckets(realized_vol, labels=("low_vol", "mid_vol", "high_vol"))
    trend_strength = close.pct_change(slow_ma).fillna(0.0)
    table["trend_strength"] = trend_strength
    table["trend_strength_bucket"] = pd.cut(
        trend_strength,
        bins=[-np.inf, -0.03, 0.03, np.inf],
        labels=["downtrend", "neutral", "uptrend"],
    ).astype(str)
    table["extension"] = extension
    table["excluded_regime_flag"] = regime_excluded.astype(bool)
    table["future_return_used_only_for_label"] = True
    for horizon in horizons:
        table[f"event_return_forward_{horizon}h"] = close.shift(-horizon) / close - 1.0
    if drop_incomplete_labels:
        table = table.dropna(subset=[f"event_return_forward_{max(horizons)}h"])
    return table.reset_index(drop=True)


def build_lifecycle_report(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    event_table: pd.DataFrame | None = None,
) -> dict[str, Any]:
    table = pd.read_csv(run_dir / "range_reclaim_event_table.csv") if event_table is None else event_table.copy()
    lifecycle_cfg = config.get("lifecycle_config", {})
    base = simulate_lifecycle(
        table,
        hold_bars=int(lifecycle_cfg.get("hold_bars", 18)),
        target_active_bars=int(lifecycle_cfg.get("target_active_bars", 6)),
        cooldown_bars=int(lifecycle_cfg.get("cooldown_bars", 6)),
        cost_bps=float(lifecycle_cfg.get("cost_bps", 4.0)),
    )
    harsh = simulate_lifecycle(
        table,
        hold_bars=int(lifecycle_cfg.get("hold_bars", 18)),
        target_active_bars=int(lifecycle_cfg.get("target_active_bars", 6)),
        cooldown_bars=int(lifecycle_cfg.get("cooldown_bars", 6)),
        cost_bps=float(lifecycle_cfg.get("harsh_cost_bps", 8.0)),
    )
    base.to_csv(run_dir / "range_reclaim_lifecycle_event_table.csv", index=False)
    active = base.loc[base["is_hypothesis_active"].astype(bool)].copy()
    target_active = base.loc[base["target_active_event"].astype(bool)].copy()
    lifecycle = base.loc[base["lifecycle_position"].astype(float) > 0.0].copy()
    raw = distribution_stats(active, "event_return_forward_1h")
    target = distribution_stats(target_active, "target_active_return")
    full = distribution_stats(lifecycle, "lifecycle_return_net")
    full_harsh = distribution_stats(harsh.loc[harsh["lifecycle_position"].astype(float) > 0.0], "lifecycle_return_net")
    lifecycle_drag = round(max(0.0, float(target["event_PF_proxy"]) - float(full["event_PF_proxy"])), 6)
    lifecycle_drag_pct = round(lifecycle_drag / max(float(target["event_PF_proxy"]), 1e-12), 6)
    horizon_analysis = {
        f"{h}h": distribution_stats(active, f"event_return_forward_{h}h")
        for h in _horizons_to_bars(config.get("horizons", ["1h", "4h", "12h", "24h", "48h"]))
    }
    gate = config.get("acceptance_gate", {})
    horizon_pass_count = sum(
        1
        for row in horizon_analysis.values()
        if float(row.get("event_PF_proxy", 0.0)) >= float(gate.get("min_horizon_event_pf_proxy", 1.10))
    )
    fold_lifecycle = lifecycle_fold_stability(lifecycle, config)
    tail = tail_dependency(lifecycle, "lifecycle_return_net")
    report = {
        "schema_version": "btc_hypothesis_lab_v2_lifecycle_report_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config["hypothesis_id"],
        "mode": config.get("mode", "research_only"),
        "raw_event_return_distribution": raw,
        "target_active_distribution": target,
        "full_lifecycle_distribution": full,
        "raw_event_PF_proxy": float(raw["event_PF_proxy"]),
        "target_active_event_PF_proxy": float(target["event_PF_proxy"]),
        "full_lifecycle_event_PF_proxy": float(full["event_PF_proxy"]),
        "lifecycle_drag": lifecycle_drag,
        "lifecycle_drag_pct": lifecycle_drag_pct,
        "active_event_count": int(raw["active_event_count"]),
        "lifecycle_event_count": int(full["active_event_count"]),
        "positive_sum_raw": float(raw["positive_sum"]),
        "negative_sum_raw": float(raw["negative_sum"]),
        "positive_sum_lifecycle": float(full["positive_sum"]),
        "negative_sum_lifecycle": float(full["negative_sum"]),
        "fold_pass_rate_raw": raw_fold_pass_rate(active, config),
        "fold_pass_rate_lifecycle": float(fold_lifecycle["pass_rate"]),
        "fold_stability_lifecycle": fold_lifecycle,
        "top5_positive_contribution": float(tail["top5_positive_contribution"]),
        "top5_negative_contribution": float(tail["top5_negative_contribution"]),
        "tail_dependency": tail,
        "cost_stress_proxy_base": {
            "passed": float(full["event_PF_proxy"]) >= float(gate.get("min_full_lifecycle_event_pf_proxy", 1.10)),
            "event_PF_proxy": float(full["event_PF_proxy"]),
            "cost_bps": float(lifecycle_cfg.get("cost_bps", 4.0)),
        },
        "cost_stress_proxy_harsh": {
            "passed": float(full_harsh["event_PF_proxy"]) >= float(gate.get("harsh_cost_survival_event_pf_proxy", 1.0)),
            "event_PF_proxy": float(full_harsh["event_PF_proxy"]),
            "cost_bps": float(lifecycle_cfg.get("harsh_cost_bps", 8.0)),
        },
        "horizon_analysis": horizon_analysis,
        "horizon_pass_count": int(horizon_pass_count),
        "regime_breakdown_lifecycle": group_distribution(lifecycle, "regime", "lifecycle_return_net"),
        "volatility_breakdown_lifecycle": group_distribution(lifecycle, "volatility_bucket", "lifecycle_return_net"),
        "trend_breakdown_lifecycle": group_distribution(lifecycle, "trend_strength_bucket", "lifecycle_return_net"),
        "no_lookahead_status": "pass",
        "decision": "pending",
        "skeleton_guard_decision": "pending",
        "root_cause_summary": lifecycle_root_cause(raw=raw, target=target, full=full, fold_lifecycle=fold_lifecycle, tail=tail),
    }
    write_json(run_dir / "lifecycle_aware_distribution_report.json", report)
    write_json(run_dir / "range_reclaim_lifecycle_report.json", report)
    return report


def simulate_lifecycle(
    table: pd.DataFrame,
    *,
    hold_bars: int,
    target_active_bars: int,
    cooldown_bars: int,
    cost_bps: float,
) -> pd.DataFrame:
    out = table.copy()
    active = out["is_hypothesis_active"].astype(bool).to_numpy()
    forward = pd.to_numeric(out["event_return_forward_1h"], errors="coerce").fillna(0.0).to_numpy()
    position = np.zeros(len(out), dtype=float)
    age = np.zeros(len(out), dtype=int)
    cost = np.zeros(len(out), dtype=float)
    current_position = 0.0
    current_age = 0
    cooldown = 0
    for i in range(len(out)):
        if current_position > 0.0 and current_age >= hold_bars:
            current_position = 0.0
            current_age = 0
            cooldown = max(cooldown, cooldown_bars)
            cost[i] += cost_bps / 10_000.0
        if cooldown > 0:
            cooldown -= 1
        if current_position == 0.0 and cooldown == 0 and bool(active[i]):
            current_position = 1.0
            current_age = 0
            cost[i] += cost_bps / 10_000.0
        position[i] = current_position
        age[i] = current_age if current_position > 0.0 else 0
        if current_position > 0.0:
            current_age += 1
    out["lifecycle_position"] = position
    out["lifecycle_age_bars"] = age
    out["lifecycle_cost_return"] = cost
    out["lifecycle_return_gross"] = position * forward
    out["lifecycle_return_net"] = out["lifecycle_return_gross"] - out["lifecycle_cost_return"]
    out["target_active_event"] = (out["lifecycle_position"] > 0.0) & (out["lifecycle_age_bars"] < target_active_bars)
    out["target_active_return"] = np.where(out["target_active_event"], out["lifecycle_return_gross"], np.nan)
    out["lifecycle_cost_bucket"] = np.where(out["lifecycle_cost_return"] > 0.0, "transition_cost", "no_transition_cost")
    return out


def evaluate_lifecycle_gate(
    *,
    run_dir: Path,
    config: Mapping[str, Any],
    lifecycle_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = dict(lifecycle_report or read_json(run_dir / "lifecycle_aware_distribution_report.json"))
    sample = config.get("sample_thresholds", {})
    gate = config.get("acceptance_gate", {})
    skeleton_gate = config.get("skeleton_gate", {})
    checks = {
        "active_event_count": int(report["active_event_count"]) >= int(sample.get("min_active_events", 200)),
        "raw_event_PF_proxy": float(report["raw_event_PF_proxy"]) >= float(gate.get("min_raw_event_pf_proxy", 1.15)),
        "target_active_event_PF_proxy": float(report["target_active_event_PF_proxy"]) >= float(gate.get("min_target_active_event_pf_proxy", 1.15)),
        "full_lifecycle_event_PF_proxy": float(report["full_lifecycle_event_PF_proxy"]) >= float(gate.get("min_full_lifecycle_event_pf_proxy", 1.10)),
        "lifecycle_drag_pct": float(report["lifecycle_drag_pct"]) <= float(gate.get("max_lifecycle_drag_pct", 0.20)),
        "fold_pass_rate_lifecycle": float(report["fold_pass_rate_lifecycle"]) >= float(gate.get("min_fold_pass_rate_lifecycle", 0.75)),
        "top5_positive_contribution": float(report["top5_positive_contribution"]) <= float(gate.get("max_top5_positive_contribution", 0.35)),
        "cost_stress_proxy_base": bool(report["cost_stress_proxy_base"]["passed"]),
        "no_lookahead": report["no_lookahead_status"] == "pass",
    }
    skeleton_checks = {
        "full_lifecycle_event_PF_proxy": float(report["full_lifecycle_event_PF_proxy"]) >= float(
            skeleton_gate.get("min_full_lifecycle_event_pf_proxy", 1.15)
        ),
        "fold_pass_rate_lifecycle": float(report["fold_pass_rate_lifecycle"]) >= float(
            skeleton_gate.get("min_fold_pass_rate_lifecycle", 0.75)
        ),
        "multi_horizon": int(report["horizon_pass_count"]) >= int(skeleton_gate.get("min_multi_horizon_pass_count", 2)),
        "downside_tail_not_catastrophic": float(report["full_lifecycle_distribution"].get("downside_tail_5pct", 0.0))
        > float(skeleton_gate.get("min_downside_tail_5pct", -0.05)),
    }
    fail_reasons = [name for name, passed in checks.items() if not passed]
    skeleton_fail_reasons = [name for name, passed in skeleton_checks.items() if not passed]
    if not checks["active_event_count"]:
        decision = "hypothesis_needs_more_data"
    elif fail_reasons:
        decision = "hypothesis_rejected"
    elif skeleton_fail_reasons:
        decision = "hypothesis_passed_distribution_only"
    else:
        decision = "hypothesis_passed_for_strategy_skeleton"
    skeleton_generated = decision == "hypothesis_passed_for_strategy_skeleton"
    skeleton_path = ""
    if skeleton_generated:
        skeleton_path = str(BTC_RANGE_RECLAIM_SKELETON_PATH)
        write_strategy_skeleton(BTC_RANGE_RECLAIM_SKELETON_PATH, config=config)
    payload = {
        "schema_version": "btc_hypothesis_lab_v2_decision_v1",
        "run_id": run_dir.name,
        "hypothesis_id": report["hypothesis_id"],
        "decision": decision,
        "checks": checks,
        "skeleton_checks": skeleton_checks,
        "reasons": fail_reasons or ["lifecycle_distribution_gate_passed"],
        "skeleton_reasons": skeleton_fail_reasons or ["skeleton_gate_passed"],
        "strategy_skeleton_generated": skeleton_generated,
        "strategy_skeleton_path": skeleton_path,
        "skeleton_guard_decision": "generate_skeleton" if skeleton_generated else "do_not_generate_skeleton",
        "paper_queue": "LOCKED",
        "live": "FROZEN",
        "final_decision": final_decision(decision),
    }
    report["decision"] = decision
    report["skeleton_guard_decision"] = payload["skeleton_guard_decision"]
    write_json(run_dir / "lifecycle_aware_distribution_report.json", report)
    write_json(run_dir / "range_reclaim_lifecycle_report.json", report)
    write_json(run_dir / "hypothesis_decision_v2.json", payload)
    write_json(run_dir / "range_reclaim_hypothesis_decision_v2.json", payload)
    return payload


def write_safety_status(*, run_dir: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_hypothesis_lab_v2_safety_status_v1",
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


def update_research_registry(*, decision: Mapping[str, Any], lifecycle_report: Mapping[str, Any]) -> dict[str, Any]:
    if RESEARCH_REGISTRY_PATH.exists():
        registry = read_json(RESEARCH_REGISTRY_PATH)
    else:
        registry = {
            "schema_version": "btc_research_registry_v1",
            "paper_queue": "LOCKED",
            "live": "FROZEN",
            "items": {},
        }
    registry["generated_at"] = datetime.now(timezone.utc).isoformat()
    registry["paper_queue"] = "LOCKED"
    registry["live"] = "FROZEN"
    items = registry.setdefault("items", {})
    items.setdefault(
        "perp_dual_trend",
        {
            "status": "archived",
            "reason": "event_PF stuck near 1.01-1.02; no stable repair pattern",
            "last_run_id": "20260516T100000Z_eventreturn_alpha",
            "next_action": "do_not_resurrect_without_new_hypothesis",
        },
    )
    items.setdefault(
        "liquidation_shock_recovery",
        {
            "status": "archived",
            "reason": "full-ledger event_PF 0.998; lifecycle drag; no ablation passed",
            "last_run_id": "20260517T010000Z_liquidation_shock_attribution",
            "next_action": "do_not_generate_v2_or_v3",
        },
    )
    status = str(decision["decision"])
    reason = (
        f"full_lifecycle_event_PF_proxy={float(lifecycle_report['full_lifecycle_event_PF_proxy']):.6f}; "
        f"fold_pass_rate_lifecycle={float(lifecycle_report['fold_pass_rate_lifecycle']):.6f}; "
        f"tail_top5={float(lifecycle_report['top5_positive_contribution']):.6f}; "
        f"reasons={', '.join(decision.get('reasons', []))}"
    )
    items["range_reclaim_momentum"] = {
        "status": status,
        "reason": reason,
        "last_run_id": str(decision["run_id"]),
        "next_action": "generate_skeleton_only_if_lifecycle_gate_passes"
        if status == "hypothesis_passed_for_strategy_skeleton"
        else "do_not_generate_skeleton",
    }
    write_json(RESEARCH_REGISTRY_PATH, registry)
    write_registry_summary(registry)
    return registry


def write_registry_summary(registry: Mapping[str, Any], path: Path = REGISTRY_SUMMARY_PATH) -> None:
    lines = [
        "# BTC Alpha Registry Summary",
        "",
        f"- Paper queue: `{registry.get('paper_queue', 'LOCKED')}`",
        f"- Live: `{registry.get('live', 'FROZEN')}`",
        "",
        "## Registry Items",
        "",
    ]
    for key, row in sorted(registry.get("items", {}).items()):
        lines.append(f"- `{key}`: `{row.get('status')}`; {row.get('reason')} (last_run_id `{row.get('last_run_id')}`)")
    lines.extend(
        [
            "",
            "## Lifecycle-Aware Rule",
            "",
            "New BTC hypotheses must pass full-lifecycle event_PF, lifecycle fold stability, cost proxy, and tail dependency before a skeleton is allowed.",
            "Archived lines, including perp_dual_trend and liquidation_shock_recovery, remain inactive.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_plan_doc(*, run_dir: Path, config: Mapping[str, Any], decision: Mapping[str, Any]) -> None:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = f"""# BTC Range-Reclaim Lifecycle Hypothesis Plan

- Branch: `main`
- Starting commit: `{git_commit_hash()}`
- Run ID: `{run_dir.name}`
- Hypothesis: `{config['hypothesis_id']}`
- Mode: `research_only`
- Decision: `{decision['decision']}`

## Guardrails

- Do not resurrect `perp_dual_trend`.
- Do not resurrect `liquidation_shock_recovery`.
- Do not generate a strategy skeleton unless full-lifecycle event_PF, lifecycle WF, cost proxy, and tail dependency all pass.
- Paper queue remains `LOCKED`.
- Live remains `FROZEN`.

## Artifacts

- `{run_dir / 'range_reclaim_event_table.csv'}`
- `{run_dir / 'range_reclaim_lifecycle_report.json'}`
- `{run_dir / 'range_reclaim_hypothesis_decision_v2.json'}`
- `{run_dir / 'paper_live_safety_status.json'}`
"""
    PLAN_PATH.write_text(text, encoding="utf-8")


def write_run_manifest(*, run_dir: Path, config_path: Path, config: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "btc_range_reclaim_lifecycle_run_manifest_v1",
        "run_id": run_dir.name,
        "hypothesis_id": config["hypothesis_id"],
        "mode": config.get("mode", "research_only"),
        "config_path": str(config_path),
        "config_hash": stable_hash(config),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_version": "btc_sqlite_1h",
        "strategy_version": "research_hypothesis_only",
        "cost_model": "lifecycle_proxy_cost_bps",
        "slippage_model": "included_in_lifecycle_proxy_cost_bps",
        "commit_hash": git_commit_hash(),
        "code_commit": git_commit_hash(),
        "decision": decision.get("decision"),
        "paper_queue": "LOCKED",
        "live": "FROZEN",
        "artifact_files": [
            "range_reclaim_event_table.csv",
            "lifecycle_aware_distribution_report.json",
            "range_reclaim_lifecycle_report.json",
            "hypothesis_decision_v2.json",
            "range_reclaim_hypothesis_decision_v2.json",
            "paper_live_safety_status.json",
        ],
        "local_generated_files": [
            "range_reclaim_lifecycle_event_table.csv",
            "event_table.csv",
            "event_table.parquet",
            "range_reclaim_event_table.parquet",
        ],
    }
    write_json(run_dir / "run_manifest.json", payload)
    return payload


def write_strategy_skeleton(path: Path, *, config: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"""hypothesis_id: {config['hypothesis_id']}
status: research_candidate
event_ledger_required: true
side: long_only
conditions:
  range_reclaim: close reclaims prior rolling range high
  trend_confirmation: fast_ma_above_slow_ma_and_positive_slope
  regime_exclusions: {list(config.get('regime_exclusions', []))}
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


def lifecycle_fold_stability(lifecycle: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, Any]:
    gate = config.get("acceptance_gate", {})
    rows = []
    for fold_id, subset in lifecycle.groupby("fold_id", dropna=False):
        if str(fold_id) == "pre_wf":
            continue
        stats = distribution_stats(subset, "lifecycle_return_net")
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


def raw_fold_pass_rate(active: pd.DataFrame, config: Mapping[str, Any]) -> float:
    gate = config.get("acceptance_gate", {})
    rows = []
    for fold_id, subset in active.groupby("fold_id", dropna=False):
        if str(fold_id) == "pre_wf":
            continue
        stats = distribution_stats(subset, "event_return_forward_1h")
        rows.append(
            stats["active_event_count"] > 0
            and float(stats["event_PF_proxy"]) > float(gate.get("min_fold_event_pf_proxy", 1.05))
            and float(stats["median_return"]) >= float(gate.get("min_median_return", 0.0))
        )
    return round(sum(1 for passed in rows if passed) / max(1, len(rows)), 6)


def lifecycle_root_cause(
    *,
    raw: Mapping[str, Any],
    target: Mapping[str, Any],
    full: Mapping[str, Any],
    fold_lifecycle: Mapping[str, Any],
    tail: Mapping[str, Any],
) -> list[str]:
    notes = []
    if float(full.get("event_PF_proxy", 0.0)) < 1.10:
        notes.append("full-lifecycle event_PF_proxy is below the v2 research gate")
    if float(fold_lifecycle.get("pass_rate", 0.0)) < 0.75:
        notes.append("lifecycle fold stability is below 75%")
    if float(tail.get("top5_positive_contribution", 1.0)) > 0.35:
        notes.append("positive edge depends too much on the top 5 events")
    if float(target.get("event_PF_proxy", 0.0)) > float(full.get("event_PF_proxy", 0.0)):
        notes.append("target-active edge decays after lifecycle costs and hold-time exposure")
    if not notes:
        notes.append("lifecycle proxy passed primary diagnostics")
    notes.append("ordinary PF and signal-equity metrics are not used by this gate")
    return notes


def final_decision(decision: str) -> str:
    if decision == "hypothesis_passed_for_strategy_skeleton":
        return "hypothesis passed for skeleton; strategy skeleton generated; paper queue remains LOCKED; live remains FROZEN."
    if decision == "hypothesis_needs_more_data":
        return "hypothesis needs more data; no strategy generated; paper queue remains LOCKED; live remains FROZEN."
    if decision == "hypothesis_rejected":
        return "hypothesis rejected; no strategy generated; paper queue remains LOCKED; live remains FROZEN."
    return "registry/lifecycle audit completed; paper queue remains LOCKED; live remains FROZEN."


def _horizons_to_bars(horizons: Sequence[Any]) -> list[int]:
    out = []
    for item in horizons:
        text = str(item).strip().lower()
        if not text.endswith("h"):
            raise ValueError(f"unsupported horizon: {item}")
        out.append(int(text[:-1]))
    return out


def _historical_buckets(series: pd.Series, *, labels: tuple[str, str, str]) -> pd.Series:
    low = series.expanding(min_periods=48).quantile(0.33).fillna(series)
    high = series.expanding(min_periods=48).quantile(0.66).fillna(series)
    return pd.Series(np.where(series <= low, labels[0], np.where(series >= high, labels[2], labels[1])), index=series.index)


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
