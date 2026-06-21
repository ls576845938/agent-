"""Research-only BTC intraday short-cycle event-ledger backtest.

This module consumes the bounded refinement winner
``pullback_reclaim_24_dd100_4htrend100_v1`` and runs it through the canonical
event-driven fill/ledger path. It deliberately does not create a tradable
strategy skeleton, paper readiness, live readiness, or broker/order endpoints.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from backend.app.services.market_data import load_market_frame
from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_canonical import (
    build_canonical_report,
    build_trade_attribution,
    evaluate_canonical_gate,
    fills_to_trade_ledger,
    git_commit_hash,
    regime_report_from_trades,
    run_event_with_signal,
    stable_hash,
    summarize_trade_attribution,
    write_json,
)
from quant_us.research.btc_compression_expansion_validation import time_exit_long_only_signal


BTC_INTRADAY_EVENT_LEDGER_RUN_ID = "20260620T000000Z_pullback_reclaim_intraday_eventledger"
BTC_INTRADAY_REPAIRED_EVENT_LEDGER_RUN_ID = "20260620T000000Z_high_vol_non_expansion_repair_eventledger"
BTC_INTRADAY_DRIFT_GUARDED_EVENT_LEDGER_RUN_ID = "20260620T000000Z_high_vol_non_expansion_trend_guard_eventledger"
BTC_INTRADAY_EVENT_LEDGER_ROOT = Path("artifacts/btc_intraday_event_ledger")
BTC_INTRADAY_EVENT_LEDGER_LATEST = Path("artifacts/btc_candidate_gate/latest")
BTC_INTRADAY_REFINEMENT_REPORT = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_alpha_refinement_report.json"
)
BTC_INTRADAY_REPAIR_REPORT = Path(
    "artifacts/btc_candidate_gate/latest/btc_intraday_short_cycle_event_definition_repair_report.json"
)
BTC_DATA_STATUS_REPORT = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
BTC_COST_MODEL_REPORT = Path("artifacts/btc_cost_model/latest/btc_cost_model_report.json")

STRATEGY_ID = "btc_pullback_reclaim_intraday_v1"
REPAIRED_STRATEGY_ID = "btc_pullback_reclaim_intraday_high_vol_non_expansion_repair_v1"
DRIFT_GUARDED_STRATEGY_ID = "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1"
VARIANT_ID = "pullback_reclaim_24_dd100_4htrend100_v1"
REPAIRED_VARIANT_ID = "high_vol_non_expansion_repair_v1"
DRIFT_GUARDED_VARIANT_ID = "high_vol_non_expansion_trend_guard_repair_v1"
FAMILY_ID = "pullback_reclaim_intraday_v0"
INTERVAL = "5m"
CONTEXT_INTERVAL = "15m"
SYMBOL = "BTCUSDT"
EXCHANGE = "binance_spot"
DB_PATH = "data/market_data.sqlite"
LABEL_HORIZON = "60m"
BARS_PER_YEAR_5M = 365.0 * 24.0 * 12.0
EVENT_OBJECT_COLUMNS = [
    "event_id",
    "entry_timestamp",
    "trigger_state",
    "context_state",
    "label_horizon",
    "label_timestamp",
    "label_return_bps",
    "future_label_used_for_signal",
    "simulated_order_intent",
    "broker_or_private_endpoint_called",
]

DEFAULT_PARAMS: dict[str, Any] = {
    "variant_id": VARIANT_ID,
    "family_id": FAMILY_ID,
    "lookback": 24,
    "prior_high_window": 48,
    "pullback_depth_min": 0.01,
    "volume_multiple": 1.25,
    "trend_key": "trend_4h",
    "trend_min": 0.01,
    "time_exit_bars": 12,
    "cooldown_bars": 12,
    "signal_scale": 0.20,
    "label_horizon": LABEL_HORIZON,
    "label_horizon_bars": 12,
    "feature_interval": INTERVAL,
    "context_interval": CONTEXT_INTERVAL,
    "lookahead_used_for_signal": False,
}
REPAIRED_ENTRY_FILTER: dict[str, list[str]] = {
    "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
    "volatility_states": ["high_vol"],
}
DRIFT_GUARDED_ENTRY_FILTER: dict[str, Any] = {
    "allowed_regimes": ["high_vol_trend", "mean_reverting_chop", "trending_up"],
    "volatility_states": ["high_vol"],
    "min_trend_by_regime": {"high_vol_trend": 0.017},
}


def load_btc_intraday_frame(
    *,
    interval: str,
    db_path: str = DB_PATH,
    symbol: str = SYMBOL,
) -> pd.DataFrame:
    start, end = _sqlite_range(Path(db_path), interval=interval, symbol=symbol)
    return load_market_frame(
        source="sqlite",
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        db_path=db_path,
    )


def pullback_reclaim_intraday_signal(
    frame_5m: pd.DataFrame,
    context_15m: pd.DataFrame | None = None,
    params: Mapping[str, Any] | None = None,
) -> tuple[pd.Series, dict[str, pd.Series]]:
    cfg = {**DEFAULT_PARAMS, **dict(params or {})}
    frame = _normalize_frame(frame_5m)
    context = _normalize_frame(context_15m) if context_15m is not None else _resample_context_15m(frame)
    features = _pullback_features(frame, context)
    entries = _entry_mask(features, cfg)
    signal = time_exit_long_only_signal(
        entries=entries,
        time_exit_bars=int(cfg["time_exit_bars"]),
        cooldown_bars=int(cfg["cooldown_bars"]),
        signal_scale=float(cfg["signal_scale"]),
    )
    diagnostics: dict[str, pd.Series] = {
        "pullback_reclaim_entry": entries.astype(float),
        "prior_high": features["prior_high"],
        "pullback_low": features["pullback_low"],
        "pullback_depth": features["pullback_depth"],
        "volume_ratio": features["volume_ratio"],
        "trend_4h": features["trend_4h"],
        "trend_strength": features["trend_4h"],
        "momentum": frame["close"].astype(float).pct_change(12).fillna(0.0),
        "volatility": frame["close"].astype(float).pct_change().rolling(72, min_periods=24).std(ddof=0).fillna(0.0),
        "target_signal": signal,
        "raw_signal": signal,
    }
    for key, value in diagnostics.items():
        value.index = frame.index
        diagnostics[key] = value.reindex(frame.index).ffill().fillna(0.0)
    return signal.reindex(frame.index).fillna(0.0).clip(0.0, 1.0), diagnostics


def apply_repaired_entry_filter(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    diagnostics: Mapping[str, pd.Series],
    params: Mapping[str, Any],
    entry_filter: Mapping[str, Any],
) -> tuple[pd.Series, dict[str, pd.Series]]:
    local_frame = _normalize_frame(frame)
    index = pd.to_datetime(local_frame.index, utc=True)
    entries = _diagnostic_series(diagnostics, "pullback_reclaim_entry", index) > 0.0
    regimes = classify_btc_regimes(local_frame).reindex(index).fillna("unknown").astype(str)
    volatility = _diagnostic_series(diagnostics, "volatility", index)
    trend_strength = _diagnostic_series(diagnostics, "trend_strength", index)
    volatility_states = _past_volatility_states(volatility)
    allowed_regimes = set(_list_of_strings(entry_filter.get("allowed_regimes")))
    allowed_volatility_states = set(_list_of_strings(entry_filter.get("volatility_states")))
    min_trend_by_regime = _mapping(entry_filter.get("min_trend_by_regime"))
    filtered_entries = entries.copy()
    if allowed_regimes:
        filtered_entries &= regimes.isin(allowed_regimes)
    if allowed_volatility_states:
        filtered_entries &= volatility_states.isin(allowed_volatility_states)
    trend_guard_allowed = pd.Series(True, index=index, dtype=bool)
    for regime, min_trend in min_trend_by_regime.items():
        try:
            threshold = float(min_trend)
        except (TypeError, ValueError):
            continue
        regime_mask = regimes == str(regime)
        allowed = (~regime_mask) | (trend_strength >= threshold)
        trend_guard_allowed &= allowed
        filtered_entries &= allowed
    repaired_signal = time_exit_long_only_signal(
        entries=filtered_entries,
        time_exit_bars=int(params["time_exit_bars"]),
        cooldown_bars=int(params["cooldown_bars"]),
        signal_scale=float(params["signal_scale"]),
    ).reindex(index).fillna(0.0).clip(0.0, 1.0)
    repaired_diagnostics = dict(diagnostics)
    repaired_diagnostics["pullback_reclaim_entry"] = filtered_entries.astype(float)
    repaired_diagnostics["raw_signal"] = repaired_signal
    repaired_diagnostics["target_signal"] = repaired_signal
    repaired_diagnostics["entry_regime_allowed"] = regimes.isin(allowed_regimes).astype(float) if allowed_regimes else pd.Series(1.0, index=index)
    repaired_diagnostics["volatility_state_allowed"] = (
        volatility_states.isin(allowed_volatility_states).astype(float)
        if allowed_volatility_states
        else pd.Series(1.0, index=index)
    )
    repaired_diagnostics["regime_trend_guard_allowed"] = trend_guard_allowed.astype(float)
    return repaired_signal, repaired_diagnostics


def run_btc_intraday_short_cycle_event_ledger(
    *,
    run_id: str = BTC_INTRADAY_EVENT_LEDGER_RUN_ID,
    output_root: Path = BTC_INTRADAY_EVENT_LEDGER_ROOT,
    latest_root: Path = BTC_INTRADAY_EVENT_LEDGER_LATEST,
    repo_root: Path | None = None,
) -> Path:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    params = dict(DEFAULT_PARAMS)
    refinement = _read_json(root / BTC_INTRADAY_REFINEMENT_REPORT)
    data_status = _read_json(root / BTC_DATA_STATUS_REPORT)
    cost_model = _read_json(root / BTC_COST_MODEL_REPORT)
    frame = load_btc_intraday_frame(interval=INTERVAL, db_path=DB_PATH)
    context = load_btc_intraday_frame(interval=CONTEXT_INTERVAL, db_path=DB_PATH)
    signal, diagnostics = pullback_reclaim_intraday_signal(frame, context, params)
    event_objects = build_event_objects(frame=frame, diagnostics=diagnostics, params=params)
    event_objects_path = run_dir / "event_objects.csv"
    event_objects.to_csv(event_objects_path, index=False)
    start = frame.index[0].to_pydatetime()
    end = frame.index[-1].to_pydatetime()
    data_version = _data_version(frame)
    strategy_version = f"{STRATEGY_ID}:research_only_event_ledger_v1"
    event = _run_intraday_event(
        frame=frame,
        signal=signal,
        strategy_id=STRATEGY_ID,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        scenario_name="base_10bps_taker",
        commission_rate=0.0005,
        slippage_bps=0.0,
        data_version=data_version,
        strategy_version=strategy_version,
    )
    trades = ledger_segments_from_signal_intraday(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        frame=frame,
        signal=signal,
        manifest_path=Path(str(event["manifest_path"])),
    )
    trades.to_csv(run_dir / "trade_ledger.csv", index=False)
    fill_trades = fills_to_trade_ledger(
        event["fills"],
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        symbol=SYMBOL,
        slippage_bps=0.0,
    )
    fill_trades.to_csv(run_dir / "fill_trade_ledger_diagnostic.csv", index=False)
    attribution = build_trade_attribution(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        frame=frame,
        trades=trades,
        signal=signal,
        diagnostics=diagnostics,
    )
    attribution.to_csv(run_dir / "trade_attribution.csv", index=False)
    write_json(run_dir / "trade_attribution_summary.json", summarize_trade_attribution(attribution))
    cost_stress = intraday_cost_stress_for_signal(
        frame=frame,
        signal=signal,
        strategy_id=STRATEGY_ID,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        data_version=data_version,
        strategy_version=strategy_version,
    )
    walk_forward = rolling_intraday_walk_forward(
        frame=frame,
        context=context,
        params=params,
        run_dir=run_dir,
        data_version=data_version,
        strategy_version=strategy_version,
    )
    regime_report = regime_report_from_trades(frame, trades)
    tail_dependency = build_tail_dependency_report(trades=trades, event_objects=event_objects)
    write_json(run_dir / "tail_dependency_report.json", tail_dependency)
    report = build_canonical_report(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        strategy_version=strategy_version,
        params=params,
        frame=frame,
        signal=signal,
        diagnostics=diagnostics,
        event=event,
        trades=trades,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        regime_report=regime_report,
        config_hash=stable_hash({"params": params, "source_refinement": refinement.get("best_variant")}),
        data_version=data_version,
        timeframe=INTERVAL,
        cost_model_id="crypto_taker_10bps_round_trip_intraday_stress_v1",
        ledger_engine_version="quant_us.crypto_event.event_ledger_v1.5m_intraday",
        bars_per_year=BARS_PER_YEAR_5M,
    )
    gate = evaluate_canonical_gate(report)
    report["gate_decision"] = gate.to_dict()
    report["promotion_gate_status"] = gate.status
    report["fail_reasons"] = gate.fail_reasons
    write_json(run_dir / "canonical_backtest_report.json", report)
    write_json(run_dir / "cost_stress_report.json", cost_stress)
    write_json(run_dir / "walk_forward_report.json", walk_forward)
    write_json(run_dir / "regime_report.json", regime_report)
    promotion = _promotion_decision(gate.to_dict(), data_status=data_status, tail_dependency=tail_dependency)
    write_json(run_dir / "promotion_decision.json", promotion)
    safety = _paper_live_safety(run_id, gate.to_dict())
    write_json(run_dir / "paper_live_safety_status.json", safety)
    manifest = _run_manifest(
        run_id=run_id,
        report=report,
        params=params,
        data_version=data_version,
        strategy_version=strategy_version,
        cost_model=cost_model,
        run_dir=run_dir,
    )
    write_json(run_dir / "run_manifest.json", manifest)
    summary = build_intraday_short_cycle_event_ledger_report(
        run_id=run_id,
        run_dir=run_dir,
        canonical_report=report,
        event_objects=event_objects,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        regime_report=regime_report,
        tail_dependency=tail_dependency,
        promotion=promotion,
        safety=safety,
        manifest=manifest,
        refinement=refinement,
        data_status=data_status,
        cost_model=cost_model,
    )
    write_json(run_dir / "btc_intraday_short_cycle_event_ledger_report.json", summary)
    latest_root.mkdir(parents=True, exist_ok=True)
    write_json(latest_root / "btc_intraday_short_cycle_event_ledger_report.json", summary)
    return run_dir


def run_btc_intraday_short_cycle_repaired_event_ledger(
    *,
    run_id: str = BTC_INTRADAY_REPAIRED_EVENT_LEDGER_RUN_ID,
    output_root: Path = BTC_INTRADAY_EVENT_LEDGER_ROOT,
    latest_root: Path = BTC_INTRADAY_EVENT_LEDGER_LATEST,
    repo_root: Path | None = None,
    strategy_id: str = REPAIRED_STRATEGY_ID,
    variant_id: str = REPAIRED_VARIANT_ID,
    entry_filter: Mapping[str, Any] = REPAIRED_ENTRY_FILTER,
    report_filename: str = "btc_intraday_short_cycle_repaired_event_ledger_report.json",
    strategy_version_suffix: str = "research_only_event_ledger_repaired_v1",
) -> Path:
    root = (repo_root or Path.cwd()).resolve()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    params = {
        **DEFAULT_PARAMS,
        "variant_id": variant_id,
        "source_variant_id": VARIANT_ID,
        "entry_filter": dict(entry_filter),
        "source_event_definition_repair_report": str(BTC_INTRADAY_REPAIR_REPORT),
    }
    refinement = _read_json(root / BTC_INTRADAY_REFINEMENT_REPORT)
    repair = _read_json(root / BTC_INTRADAY_REPAIR_REPORT)
    data_status = _read_json(root / BTC_DATA_STATUS_REPORT)
    cost_model = _read_json(root / BTC_COST_MODEL_REPORT)
    frame = load_btc_intraday_frame(interval=INTERVAL, db_path=DB_PATH)
    context = load_btc_intraday_frame(interval=CONTEXT_INTERVAL, db_path=DB_PATH)
    base_signal, base_diagnostics = pullback_reclaim_intraday_signal(frame, context, params)
    signal, diagnostics = apply_repaired_entry_filter(
        frame=frame,
        signal=base_signal,
        diagnostics=base_diagnostics,
        params=params,
        entry_filter=entry_filter,
    )
    event_objects = build_event_objects(
        frame=frame,
        diagnostics=diagnostics,
        params=params,
        variant_id=variant_id,
    )
    event_objects_path = run_dir / "event_objects.csv"
    event_objects.to_csv(event_objects_path, index=False)
    start = frame.index[0].to_pydatetime()
    end = frame.index[-1].to_pydatetime()
    data_version = _data_version(frame)
    strategy_version = f"{strategy_id}:{strategy_version_suffix}"
    event = _run_intraday_event(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        scenario_name="base_10bps_taker",
        commission_rate=0.0005,
        slippage_bps=0.0,
        data_version=data_version,
        strategy_version=strategy_version,
    )
    trades = ledger_segments_from_signal_intraday(
        run_id=run_id,
        strategy_id=strategy_id,
        frame=frame,
        signal=signal,
        manifest_path=Path(str(event["manifest_path"])),
    )
    trades.to_csv(run_dir / "trade_ledger.csv", index=False)
    fill_trades = fills_to_trade_ledger(
        event["fills"],
        run_id=run_id,
        strategy_id=strategy_id,
        symbol=SYMBOL,
        slippage_bps=0.0,
    )
    fill_trades.to_csv(run_dir / "fill_trade_ledger_diagnostic.csv", index=False)
    attribution = build_trade_attribution(
        run_id=run_id,
        strategy_id=strategy_id,
        frame=frame,
        trades=trades,
        signal=signal,
        diagnostics=diagnostics,
    )
    attribution.to_csv(run_dir / "trade_attribution.csv", index=False)
    write_json(run_dir / "trade_attribution_summary.json", summarize_trade_attribution(attribution))
    cost_stress = intraday_cost_stress_for_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        data_version=data_version,
        strategy_version=strategy_version,
    )
    walk_forward = rolling_intraday_walk_forward(
        frame=frame,
        context=context,
        params=params,
        run_dir=run_dir,
        data_version=data_version,
        strategy_version=strategy_version,
        strategy_id=strategy_id,
        entry_filter=entry_filter,
    )
    regime_report = regime_report_from_trades(frame, trades)
    tail_dependency = build_tail_dependency_report(trades=trades, event_objects=event_objects)
    write_json(run_dir / "tail_dependency_report.json", tail_dependency)
    report = build_canonical_report(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        params=params,
        frame=frame,
        signal=signal,
        diagnostics=diagnostics,
        event=event,
        trades=trades,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        regime_report=regime_report,
        config_hash=stable_hash(
            {
                "params": params,
                "source_refinement": refinement.get("best_variant"),
                "source_repair": repair.get("best_repair_variant"),
            }
        ),
        data_version=data_version,
        timeframe=INTERVAL,
        cost_model_id="crypto_taker_10bps_round_trip_intraday_stress_v1",
        ledger_engine_version="quant_us.crypto_event.event_ledger_v1.5m_intraday",
        bars_per_year=BARS_PER_YEAR_5M,
    )
    gate = evaluate_canonical_gate(report)
    report["gate_decision"] = gate.to_dict()
    report["promotion_gate_status"] = gate.status
    report["fail_reasons"] = gate.fail_reasons
    write_json(run_dir / "canonical_backtest_report.json", report)
    write_json(run_dir / "cost_stress_report.json", cost_stress)
    write_json(run_dir / "walk_forward_report.json", walk_forward)
    write_json(run_dir / "regime_report.json", regime_report)
    promotion = _promotion_decision(gate.to_dict(), data_status=data_status, tail_dependency=tail_dependency)
    write_json(run_dir / "promotion_decision.json", promotion)
    safety = _paper_live_safety(run_id, gate.to_dict())
    write_json(run_dir / "paper_live_safety_status.json", safety)
    manifest = _run_manifest(
        run_id=run_id,
        report=report,
        params=params,
        data_version=data_version,
        strategy_version=strategy_version,
        cost_model=cost_model,
        run_dir=run_dir,
        strategy_id=strategy_id,
        variant_id=variant_id,
    )
    write_json(run_dir / "run_manifest.json", manifest)
    summary = build_intraday_short_cycle_event_ledger_report(
        run_id=run_id,
        run_dir=run_dir,
        canonical_report=report,
        event_objects=event_objects,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        regime_report=regime_report,
        tail_dependency=tail_dependency,
        promotion=promotion,
        safety=safety,
        manifest=manifest,
        refinement=refinement,
        data_status=data_status,
        cost_model=cost_model,
        strategy_id=strategy_id,
        variant_id=variant_id,
        family_id=FAMILY_ID,
        source_event_definition_repair_report=str(BTC_INTRADAY_REPAIR_REPORT),
        entry_filters=entry_filter,
    )
    write_json(run_dir / report_filename, summary)
    latest_root.mkdir(parents=True, exist_ok=True)
    write_json(latest_root / report_filename, summary)
    return run_dir


def run_btc_intraday_short_cycle_drift_guarded_event_ledger(
    *,
    run_id: str = BTC_INTRADAY_DRIFT_GUARDED_EVENT_LEDGER_RUN_ID,
    output_root: Path = BTC_INTRADAY_EVENT_LEDGER_ROOT,
    latest_root: Path = BTC_INTRADAY_EVENT_LEDGER_LATEST,
    repo_root: Path | None = None,
) -> Path:
    return run_btc_intraday_short_cycle_repaired_event_ledger(
        run_id=run_id,
        output_root=output_root,
        latest_root=latest_root,
        repo_root=repo_root,
        strategy_id=DRIFT_GUARDED_STRATEGY_ID,
        variant_id=DRIFT_GUARDED_VARIANT_ID,
        entry_filter=DRIFT_GUARDED_ENTRY_FILTER,
        report_filename="btc_intraday_short_cycle_drift_guarded_event_ledger_report.json",
        strategy_version_suffix="research_only_event_ledger_drift_guarded_v1",
    )


def build_intraday_short_cycle_event_ledger_report(
    *,
    run_id: str,
    run_dir: Path,
    canonical_report: Mapping[str, Any],
    event_objects: pd.DataFrame,
    cost_stress: Mapping[str, Any],
    walk_forward: Mapping[str, Any],
    regime_report: Mapping[str, Any],
    tail_dependency: Mapping[str, Any],
    promotion: Mapping[str, Any],
    safety: Mapping[str, Any],
    manifest: Mapping[str, Any],
    refinement: Mapping[str, Any],
    data_status: Mapping[str, Any],
    cost_model: Mapping[str, Any],
    strategy_id: str = STRATEGY_ID,
    variant_id: str = VARIANT_ID,
    family_id: str = FAMILY_ID,
    source_event_definition_repair_report: str | None = None,
    entry_filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gate = _mapping(canonical_report.get("gate_decision"))
    metrics = _mapping(canonical_report.get("metrics"))
    failed_metrics = [str(item) for item in gate.get("fail_reasons", [])]
    status = "event_ledger_completed_research_only"
    if bool(gate.get("passed", False)):
        status = "event_ledger_passed_internal_research_gate_candidate_still_locked"
    return {
        "schema_version": "btc_intraday_short_cycle_event_ledger_report_v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "run_id": run_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "family_id": family_id,
        "asset": "btc",
        "symbol": SYMBOL,
        "scope": "research_only_event_ledger_no_candidate_no_paper_no_live_no_true_scalping",
        "status": status,
        "decision": str(promotion.get("decision", "return_to_event_definition")),
        "next_required_action": str(promotion.get("next_required_action", "review_event_ledger_failures")),
        "event_ledger_completed": True,
        "candidate_generation_allowed": False,
        "strategy_skeleton_generation_allowed": False,
        "promotion_allowed": False,
        "paper_review_pending_allowed": False,
        "paper_or_live_unlock_allowed": False,
        "true_scalping_allowed": False,
        "source_refinement_report": str(BTC_INTRADAY_REFINEMENT_REPORT)
        if Path(BTC_INTRADAY_REFINEMENT_REPORT).exists()
        else None,
        "source_event_definition_repair_report": source_event_definition_repair_report,
        "run_dir": str(run_dir),
        "artifacts": {
            "canonical_backtest_report": str(run_dir / "canonical_backtest_report.json"),
            "event_objects": str(run_dir / "event_objects.csv"),
            "trade_ledger": str(run_dir / "trade_ledger.csv"),
            "cost_stress_report": str(run_dir / "cost_stress_report.json"),
            "walk_forward_report": str(run_dir / "walk_forward_report.json"),
            "regime_report": str(run_dir / "regime_report.json"),
            "tail_dependency_report": str(run_dir / "tail_dependency_report.json"),
            "promotion_decision": str(run_dir / "promotion_decision.json"),
            "run_manifest": str(run_dir / "run_manifest.json"),
        },
        "data_context": {
            "data_status": str(data_status.get("status", "missing") or "missing"),
            "data_blockers": _list_of_strings(data_status.get("blockers")),
            "data_version": canonical_report.get("data_version"),
            "timeframe": canonical_report.get("timeframe"),
            "context_timeframe": CONTEXT_INTERVAL,
            "data_range": canonical_report.get("data_range", {}),
        },
        "cost_context": {
            "cost_model_status": str(cost_model.get("status", "missing") or "missing"),
            "base_taker_round_trip_bps": 10.0,
            "stress_scenario_count": int(cost_stress.get("scenario_count", 0) or 0),
            "required_scenarios_present": bool(cost_stress.get("required_scenarios_present", False)),
        },
        "event_definition": {
            "entry_timestamp_field": "entry_timestamp",
            "trigger_state_field": "trigger_state",
            "context_state_field": "context_state",
            "label_horizon": LABEL_HORIZON,
            "event_count": int(len(event_objects)),
            "entry_filters": {
                "allowed_regimes": _list_of_strings(_mapping(entry_filters).get("allowed_regimes")),
                "volatility_states": _list_of_strings(_mapping(entry_filters).get("volatility_states")),
                "min_trend_by_regime": {
                    str(key): float(value)
                    for key, value in _mapping(_mapping(entry_filters).get("min_trend_by_regime")).items()
                },
            },
            "future_label_used_for_signal": False,
            "lookahead_used_for_signal": False,
            "simulated_order_intent_only": True,
        },
        "metrics": {
            "profit_factor": metrics.get("profit_factor"),
            "event_profit_factor": metrics.get("event_profit_factor"),
            "total_return_pct": metrics.get("total_return_pct"),
            "max_drawdown": metrics.get("max_drawdown"),
            "annual_turnover": metrics.get("annual_turnover"),
            "trade_count": metrics.get("trade_count"),
            "fill_count": metrics.get("fill_count"),
            "walk_forward_pass_rate": metrics.get("walk_forward_pass_rate"),
            "regime_pass_rate": metrics.get("regime_pass_rate"),
            "pbo": metrics.get("pbo"),
            "dsr": metrics.get("dsr"),
        },
        "gate": gate,
        "failed_metrics": failed_metrics,
        "cost_stress": {
            "survival_rate": cost_stress.get("survival_rate"),
            "base_passed": bool(_mapping(cost_stress.get("base")).get("passed", False)),
            "harsh_survives": bool(_mapping(cost_stress.get("harsh")).get("survives", False)),
            "scenarios": [
                {
                    "name": str(row.get("name", "")),
                    "passed": bool(row.get("passed", False)),
                    "survives": bool(row.get("survives", False)),
                }
                for row in cost_stress.get("scenarios", [])
                if isinstance(row, Mapping)
            ],
        },
        "walk_forward": {
            "method": walk_forward.get("method"),
            "fold_count": walk_forward.get("fold_count"),
            "pass_rate": walk_forward.get("pass_rate"),
        },
        "regime": {
            "pass_rate": regime_report.get("pass_rate"),
            "dragging_regimes": _list_of_strings(regime_report.get("dragging_regimes")),
        },
        "tail_dependency": tail_dependency,
        "promotion_gate": promotion,
        "safety": safety,
        "manifest": {
            "data_version": manifest.get("data_version"),
            "strategy_version": manifest.get("strategy_version"),
            "params_hash": manifest.get("params_hash"),
            "cost_model": manifest.get("cost_model"),
            "slippage_model": manifest.get("slippage_model"),
            "commit_hash": manifest.get("commit_hash"),
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
        "blockers": _event_ledger_blockers(
            gate=gate,
            data_status=data_status,
            cost_stress=cost_stress,
            tail_dependency=tail_dependency,
        ),
    }


def build_event_objects(
    *,
    frame: pd.DataFrame,
    diagnostics: Mapping[str, pd.Series],
    params: Mapping[str, Any],
    variant_id: str = VARIANT_ID,
) -> pd.DataFrame:
    index = pd.to_datetime(frame.index, utc=True)
    entries = _diagnostic_series(diagnostics, "pullback_reclaim_entry", index) > 0.0
    horizon_bars = int(params.get("label_horizon_bars", 12))
    close = frame["close"].astype(float).reindex(index)
    rows: list[dict[str, Any]] = []
    for event_no, ts in enumerate(index[entries], start=1):
        pos = int(index.get_loc(ts))
        label_pos = pos + horizon_bars
        label_return = None
        label_ts = None
        if label_pos < len(index):
            label_ts = index[label_pos].isoformat()
            label_return = ((float(close.iloc[label_pos]) / float(close.iloc[pos])) - 1.0) * 10_000.0
        trigger_state = {
            "pullback_depth": round(float(_diagnostic_series(diagnostics, "pullback_depth", index).iloc[pos]), 8),
            "volume_ratio": round(float(_diagnostic_series(diagnostics, "volume_ratio", index).iloc[pos]), 8),
            "prior_high": round(float(_diagnostic_series(diagnostics, "prior_high", index).iloc[pos]), 8),
            "pullback_low": round(float(_diagnostic_series(diagnostics, "pullback_low", index).iloc[pos]), 8),
        }
        context_state = {
            "trend_4h": round(float(_diagnostic_series(diagnostics, "trend_4h", index).iloc[pos]), 8),
            "context_interval": CONTEXT_INTERVAL,
            "feature_time": ts.isoformat(),
        }
        rows.append(
            {
                "event_id": f"{variant_id}_{event_no:05d}",
                "entry_timestamp": ts.isoformat(),
                "trigger_state": json.dumps(trigger_state, sort_keys=True),
                "context_state": json.dumps(context_state, sort_keys=True),
                "label_horizon": str(params.get("label_horizon", LABEL_HORIZON)),
                "label_timestamp": label_ts,
                "label_return_bps": round(float(label_return), 6) if label_return is not None else None,
                "future_label_used_for_signal": False,
                "simulated_order_intent": "long_target_position_replay",
                "broker_or_private_endpoint_called": False,
            }
        )
    return pd.DataFrame(rows, columns=EVENT_OBJECT_COLUMNS)


def ledger_segments_from_signal_intraday(
    *,
    run_id: str,
    strategy_id: str,
    frame: pd.DataFrame,
    signal: pd.Series,
    manifest_path: Path,
) -> pd.DataFrame:
    local_frame = _normalize_frame(frame)
    index = pd.to_datetime(local_frame.index, utc=True)
    aligned = signal.reindex(index).fillna(0.0).astype(float)
    active = aligned > 0.0
    equity = _ledger_equity_curve(manifest_path)
    rows: list[dict[str, Any]] = []
    in_segment = False
    entry_signal_pos = 0
    segment_no = 0
    for pos, ts in enumerate(index):
        is_active = bool(active.iloc[pos])
        if is_active and not in_segment:
            in_segment = True
            entry_signal_pos = pos
        elif in_segment and not is_active:
            segment_no += 1
            rows.append(
                _segment_row(
                    run_id=run_id,
                    strategy_id=strategy_id,
                    frame=local_frame,
                    index=index,
                    equity=equity,
                    segment_no=segment_no,
                    entry_signal_pos=entry_signal_pos,
                    exit_signal_pos=pos,
                    signal=aligned,
                )
            )
            in_segment = False
    if in_segment:
        segment_no += 1
        rows.append(
            _segment_row(
                run_id=run_id,
                strategy_id=strategy_id,
                frame=local_frame,
                index=index,
                equity=equity,
                segment_no=segment_no,
                entry_signal_pos=entry_signal_pos,
                exit_signal_pos=len(index) - 1,
                signal=aligned,
            )
        )
    return pd.DataFrame(rows)


def _segment_row(
    *,
    run_id: str,
    strategy_id: str,
    frame: pd.DataFrame,
    index: pd.DatetimeIndex,
    equity: pd.Series,
    segment_no: int,
    entry_signal_pos: int,
    exit_signal_pos: int,
    signal: pd.Series,
) -> dict[str, Any]:
    entry_fill_pos = min(entry_signal_pos + 1, len(index) - 1)
    exit_fill_pos = min(exit_signal_pos + 1, len(index) - 1)
    entry_ts = pd.Timestamp(index[entry_fill_pos])
    exit_ts = pd.Timestamp(index[exit_fill_pos])
    entry_equity = float(equity.reindex([entry_ts], method="ffill").iloc[0])
    exit_equity = float(equity.reindex([exit_ts], method="ffill").iloc[0])
    entry_price = float(frame.iloc[entry_fill_pos]["open"])
    exit_price = float(frame.iloc[exit_fill_pos]["open"])
    net_pnl = exit_equity - entry_equity
    holding_bars = max(0, int(exit_fill_pos - entry_fill_pos))
    holding_hours = holding_bars * 5.0 / 60.0
    return {
        "run_id": run_id,
        "strategy_id": strategy_id,
        "trade_id": f"{strategy_id}_segment_{segment_no:05d}",
        "symbol": SYMBOL,
        "side": "long",
        "entry_time": entry_ts.isoformat(),
        "exit_time": exit_ts.isoformat(),
        "entry_price": round(entry_price, 8),
        "exit_price": round(exit_price, 8),
        "size": round(float(signal.iloc[entry_signal_pos]), 8),
        "gross_pnl": round(net_pnl, 8),
        "net_pnl": round(net_pnl, 8),
        "fees": 0.0,
        "slippage": 0.0,
        "holding_bars": holding_bars,
        "holding_hours": round(holding_hours, 4),
        "attribution_source": "ledger_equity_snapshots",
    }


def _ledger_equity_curve(manifest_path: Path) -> pd.Series:
    manifest = _read_json(manifest_path)
    snapshots = (
        _mapping(_mapping(manifest.get("ledger_artifact")).get("reconciliation")).get("snapshots", [])
    )
    if not snapshots:
        snapshots = (
            _mapping(
                _mapping(_mapping(manifest.get("evidence")).get("ledger_artifact")).get("reconciliation")
            ).get("snapshots", [])
        )
    if not isinstance(snapshots, list) or not snapshots:
        raise ValueError(f"ledger equity snapshots missing from manifest: {manifest_path}")
    return pd.Series(
        [float(_mapping(row).get("ledger_equity", _mapping(row).get("snapshot_equity", 0.0))) for row in snapshots],
        index=pd.to_datetime([_mapping(row).get("timestamp_utc") for row in snapshots], utc=True),
        dtype=float,
    ).sort_index()


def intraday_cost_stress_for_signal(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: Mapping[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    data_version: str,
    strategy_version: str,
) -> dict[str, Any]:
    scenario_specs = [
        {
            "name": "base_10bps_taker_round_trip",
            "label": "10 bps taker round trip",
            "commission_rate": 0.0005,
            "slippage_bps": 0.0,
            "signal": signal,
            "required_type": "base_10bps",
        },
        {
            "name": "double_taker_20bps_round_trip",
            "label": "Double taker cost",
            "commission_rate": 0.0010,
            "slippage_bps": 0.0,
            "signal": signal,
            "required_type": "double_taker",
        },
        {
            "name": "conservative_slippage_5bps_each_fill",
            "label": "Conservative slippage",
            "commission_rate": 0.0005,
            "slippage_bps": 5.0,
            "signal": signal,
            "required_type": "conservative_slippage",
        },
        {
            "name": "missed_fill_every_fourth_entry",
            "label": "Deterministic missed fills",
            "commission_rate": 0.0005,
            "slippage_bps": 0.0,
            "signal": _drop_every_nth_segment(signal, n=4),
            "required_type": "missed_fill",
        },
        {
            "name": "delayed_entry_one_5m_bar",
            "label": "One-bar delayed entry and exit",
            "commission_rate": 0.0005,
            "slippage_bps": 0.0,
            "signal": signal.shift(1).fillna(0.0),
            "required_type": "delayed_entry",
        },
    ]
    rows: list[dict[str, Any]] = []
    for spec in scenario_specs:
        event = _run_intraday_event(
            frame=frame,
            signal=spec["signal"],
            strategy_id=strategy_id,
            params={**dict(params), "stress_scenario": spec["name"]},
            start=start,
            end=end,
            run_dir=run_dir,
            scenario_name=f"cost_{spec['name']}",
            commission_rate=float(spec["commission_rate"]),
            slippage_bps=float(spec["slippage_bps"]),
            data_version=data_version,
            strategy_version=strategy_version,
        )
        summary = event["summary"]
        survives = (
            float(summary.get("total_return_pct", 0.0)) > 0.0
            and float(summary.get("profit_factor", 0.0)) >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        rows.append(
            {
                "name": spec["name"],
                "label": spec["label"],
                "required_type": spec["required_type"],
                "passed": survives,
                "survives": survives,
                "summary": summary,
                "manifest_path": event["manifest_path"],
                "engine": "event_driven",
                "pnl_source": event["diagnostics"].get("pnl_source"),
                "ledger_equity_consistent": event["diagnostics"].get("ledger_equity_consistent"),
            }
        )
    required = {str(row["required_type"]) for row in scenario_specs}
    present = {str(row.get("required_type")) for row in rows}
    return {
        "scenario_count": len(rows),
        "required_scenarios": sorted(required),
        "required_scenarios_present": required.issubset(present),
        "survival_rate": round(sum(1 for row in rows if row["survives"]) / max(1, len(rows)), 6),
        "base": rows[0] if rows else {},
        "harsh": rows[2] if len(rows) >= 3 else (rows[-1] if rows else {}),
        "scenarios": rows,
    }


def rolling_intraday_walk_forward(
    *,
    frame: pd.DataFrame,
    context: pd.DataFrame,
    params: Mapping[str, Any],
    run_dir: Path,
    data_version: str,
    strategy_version: str,
    windows: int = 6,
    strategy_id: str = STRATEGY_ID,
    entry_filter: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = []
    n = len(frame)
    validation_rows = max(2_000, n // windows)
    for fold in range(windows):
        start_pos = fold * validation_rows
        end_pos = n if fold == windows - 1 else min(n, (fold + 1) * validation_rows)
        validation_frame = frame.iloc[start_pos:end_pos].copy()
        if len(validation_frame) < 500:
            continue
        validation_end = validation_frame.index[-1]
        context_frame = frame.loc[:validation_end].copy()
        context_15m = context.loc[:validation_end].copy()
        full_signal, diagnostics = pullback_reclaim_intraday_signal(context_frame, context_15m, params)
        if entry_filter:
            full_signal, _ = apply_repaired_entry_filter(
                frame=context_frame,
                signal=full_signal,
                diagnostics=diagnostics,
                params=params,
                entry_filter=entry_filter,
            )
        fold_signal = full_signal.reindex(validation_frame.index).fillna(0.0)
        event = _run_intraday_event(
            frame=validation_frame,
            signal=fold_signal,
            strategy_id=strategy_id,
            params={**dict(params), "walk_forward_fold": fold + 1},
            start=validation_frame.index[0].to_pydatetime(),
            end=validation_frame.index[-1].to_pydatetime(),
            run_dir=run_dir,
            scenario_name=f"wf{fold + 1}",
            commission_rate=0.0005,
            slippage_bps=0.0,
            data_version=data_version,
            strategy_version=strategy_version,
        )
        summary = event["summary"]
        passed = (
            float(summary.get("total_return_pct", 0.0)) >= 0.0
            and float(summary.get("profit_factor", 0.0)) >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        rows.append(
            {
                "fold": fold + 1,
                "validation_start": validation_frame.index[0].isoformat(),
                "validation_end": validation_frame.index[-1].isoformat(),
                "validation_rows": int(len(validation_frame)),
                "event_count": int((fold_signal.diff().fillna(fold_signal) > 0.0).sum()),
                "passed": passed,
                "summary": summary,
                "manifest_path": event["manifest_path"],
            }
        )
    pass_rate = sum(1 for row in rows if row["passed"]) / max(1, len(rows))
    return {
        "method": "rolling_event_ledger_fixed_params_intraday_5m",
        "windows": rows,
        "pass_rate": round(pass_rate, 6),
        "fold_count": len(rows),
    }


def build_tail_dependency_report(*, trades: pd.DataFrame, event_objects: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "schema_version": "btc_intraday_tail_dependency_v1",
            "status": "fail",
            "trade_count": 0,
            "event_count": int(len(event_objects)),
            "top_5_trade_net_pnl_share": None,
            "top_decile_net_pnl_share": None,
            "mean_median_gap_ratio": None,
            "right_tail_dependency_flag": True,
            "blockers": ["btc_intraday_tail_dependency_no_trades"],
        }
    pnl = trades["net_pnl"].astype(float)
    total_positive = float(pnl[pnl > 0].sum())
    sorted_pnl = pnl.sort_values(ascending=False)
    top_5 = float(sorted_pnl.head(5).sum())
    top_decile_count = max(1, int(np.ceil(len(sorted_pnl) * 0.10)))
    top_decile = float(sorted_pnl.head(top_decile_count).sum())
    mean = float(pnl.mean())
    median = float(pnl.median())
    share_5 = top_5 / total_positive if total_positive > 0 else 1.0
    share_decile = top_decile / total_positive if total_positive > 0 else 1.0
    gap_ratio = abs(mean - median) / max(abs(mean), 1e-12)
    right_tail_flag = bool(share_5 > 0.50 or share_decile > 0.75 or (mean > 0 and median < 0))
    blockers = ["btc_intraday_tail_dependency_right_tail_concentrated"] if right_tail_flag else []
    return {
        "schema_version": "btc_intraday_tail_dependency_v1",
        "status": "fail" if blockers else "pass",
        "trade_count": int(len(trades)),
        "event_count": int(len(event_objects)),
        "top_5_trade_net_pnl_share": round(share_5, 6),
        "top_decile_net_pnl_share": round(share_decile, 6),
        "mean_net_pnl": round(mean, 6),
        "median_net_pnl": round(median, 6),
        "mean_median_gap_ratio": round(gap_ratio, 6),
        "right_tail_dependency_flag": right_tail_flag,
        "blockers": blockers,
    }


def _run_intraday_event(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: Mapping[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    scenario_name: str,
    commission_rate: float,
    slippage_bps: float,
    data_version: str,
    strategy_version: str,
) -> dict[str, Any]:
    execution_frame = _execution_frame_from_signal(frame, signal)
    execution_signal = signal.reindex(execution_frame.index).fillna(0.0)
    event = run_event_with_signal(
        frame=execution_frame,
        signal=execution_signal,
        strategy_id=strategy_id,
        params=params,
        start=execution_frame.index[0].to_pydatetime(),
        end=execution_frame.index[-1].to_pydatetime(),
        run_dir=run_dir,
        scenario_name=scenario_name,
        commission_rate=commission_rate,
        slippage_bps=slippage_bps,
        target_weight=0.35,
        min_trade_notional=10.0,
        rebalance_buffer_pct=0.0,
        interval=INTERVAL,
        data_version=data_version,
        strategy_version=strategy_version,
    )
    event["execution_frame_bar_count"] = int(len(execution_frame))
    event["source_frame_bar_count"] = int(len(frame))
    event["execution_frame_mode"] = "signal_change_next_bar_sparse_ledger"
    event["diagnostics"]["execution_frame_bar_count"] = int(len(execution_frame))
    event["diagnostics"]["source_frame_bar_count"] = int(len(frame))
    event["diagnostics"]["execution_frame_mode"] = "signal_change_next_bar_sparse_ledger"
    return event


def _execution_frame_from_signal(frame: pd.DataFrame, signal: pd.Series) -> pd.DataFrame:
    local = _normalize_frame(frame)
    aligned = signal.reindex(local.index).fillna(0.0).astype(float)
    changes = aligned.diff().fillna(aligned).abs() > 1e-12
    positions: set[int] = {0, len(local) - 1}
    for pos in np.flatnonzero(changes.to_numpy()):
        positions.add(int(pos))
        if pos + 1 < len(local):
            positions.add(int(pos + 1))
    selected = sorted(pos for pos in positions if 0 <= pos < len(local))
    return local.iloc[selected].copy()


def _pullback_features(frame: pd.DataFrame, context: pd.DataFrame) -> dict[str, pd.Series]:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    lookback = int(DEFAULT_PARAMS["lookback"])
    prior_high_window = int(DEFAULT_PARAMS["prior_high_window"])
    previous_high_lookback = high.rolling(lookback, min_periods=lookback).max().shift(1)
    previous_low_lookback = low.rolling(lookback, min_periods=lookback).min().shift(1)
    previous_high_prior = high.rolling(prior_high_window, min_periods=prior_high_window).max().shift(1 + lookback)
    avg_volume_72 = volume.rolling(72, min_periods=72).mean().shift(1)
    trend_4h = context["close"].astype(float).pct_change(16).shift(1)
    trend_4h = trend_4h.reindex(frame.index, method="ffill").fillna(0.0)
    pullback_depth = ((previous_high_prior - previous_low_lookback) / previous_high_prior.replace(0, np.nan)).fillna(0.0)
    volume_ratio = (volume / avg_volume_72.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return {
        "close": close,
        "previous_high_lookback": previous_high_lookback,
        "prior_high": previous_high_prior.fillna(0.0),
        "pullback_low": previous_low_lookback.fillna(0.0),
        "pullback_depth": pullback_depth,
        "volume_ratio": volume_ratio,
        "trend_4h": trend_4h,
    }


def _entry_mask(features: Mapping[str, pd.Series], params: Mapping[str, Any]) -> pd.Series:
    entries = (
        (features["pullback_depth"] >= float(params["pullback_depth_min"]))
        & (features["close"] > features["previous_high_lookback"])
        & (features["volume_ratio"] >= float(params["volume_multiple"]))
        & (features["trend_4h"] >= float(params["trend_min"]))
    )
    return entries.fillna(False).astype(bool)


def _resample_context_15m(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": frame["open"].resample("15min").first(),
            "high": frame["high"].resample("15min").max(),
            "low": frame["low"].resample("15min").min(),
            "close": frame["close"].resample("15min").last(),
            "volume": frame["volume"].resample("15min").sum(),
        }
    ).dropna()


def _drop_every_nth_segment(signal: pd.Series, *, n: int) -> pd.Series:
    active = signal.fillna(0.0).astype(float) > 0.0
    output = signal.copy().fillna(0.0)
    in_segment = False
    segment_no = 0
    drop = False
    for ts, is_active in active.items():
        if is_active and not in_segment:
            in_segment = True
            segment_no += 1
            drop = segment_no % max(1, int(n)) == 0
        elif not is_active and in_segment:
            in_segment = False
            drop = False
        if drop:
            output.loc[ts] = 0.0
    return output


def _promotion_decision(
    gate: Mapping[str, Any],
    *,
    data_status: Mapping[str, Any],
    tail_dependency: Mapping[str, Any],
) -> dict[str, Any]:
    gate_passed = bool(gate.get("passed", False))
    tail_passed = str(tail_dependency.get("status", "")) == "pass"
    data_passed = str(data_status.get("status", "")) == "pass"
    if gate_passed and tail_passed and data_passed:
        decision = "continue_research"
        next_required_action = "manual_review_before_any_candidate_generation"
    elif not gate_passed:
        decision = "return_to_event_definition"
        next_required_action = "repair_intraday_event_definition_before_candidate"
    else:
        decision = "continue_research"
        next_required_action = "repair_data_regime_or_tail_dependency_before_candidate"
    return {
        "schema_version": "btc_intraday_short_cycle_promotion_decision_v1",
        "decision": decision,
        "next_required_action": next_required_action,
        "candidate_gate": gate,
        "candidate_generation_allowed": False,
        "paper_review": {
            "paper_review_queue_locked": True,
            "paper_review_pending": [],
            "paper_auto_start": False,
            "reason": "research_only_intraday_event_ledger_gate",
        },
        "paper_queue": "LOCKED",
        "live": "FROZEN",
        "live_frozen": True,
        "forbidden_states": ["paper_ready", "live_ready", "live_enabled"],
    }


def _paper_live_safety(run_id: str, gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_intraday_short_cycle_paper_live_safety_v1",
        "run_id": run_id,
        "candidate_passed_internal_gate": 1 if bool(gate.get("passed", False)) else 0,
        "paper_queue": "LOCKED",
        "paper_queue_locked": True,
        "paper_auto_start": False,
        "live": "FROZEN",
        "live_frozen": True,
        "real_broker_api_called": False,
        "real_orders_created": False,
    }


def _run_manifest(
    *,
    run_id: str,
    report: Mapping[str, Any],
    params: Mapping[str, Any],
    data_version: str,
    strategy_version: str,
    cost_model: Mapping[str, Any],
    run_dir: Path,
    strategy_id: str = STRATEGY_ID,
    variant_id: str = VARIANT_ID,
) -> dict[str, Any]:
    return {
        "schema_version": "btc_intraday_short_cycle_event_ledger_manifest_v1",
        "run_id": run_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "config_hash": stable_hash({"params": params}),
        "params_hash": stable_hash(params),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "data_version": data_version,
        "strategy_version": strategy_version,
        "params": dict(params),
        "cost_model": "base_taker_10bps_round_trip_with_stress_grid_v1",
        "source_cost_model_status": str(cost_model.get("status", "missing") or "missing"),
        "slippage_model": "base_0bps_stress_5bps_each_fill",
        "commit_hash": git_commit_hash(),
        "event_ledger_manifest_path": _mapping(report.get("event_ledger_status")).get("manifest_path", ""),
        "canonical_report": str(run_dir / "canonical_backtest_report.json"),
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }


def _event_ledger_blockers(
    *,
    gate: Mapping[str, Any],
    data_status: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    tail_dependency: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    blockers.extend(f"btc_intraday_event_ledger_gate_failed_{item}" for item in gate.get("fail_reasons", []))
    if str(data_status.get("status", "")) != "pass":
        blockers.extend(_list_of_strings(data_status.get("blockers")) or ["btc_intraday_data_status_not_pass"])
    if not bool(cost_stress.get("required_scenarios_present", False)):
        blockers.append("btc_intraday_cost_stress_required_scenarios_missing")
    blockers.extend(_list_of_strings(tail_dependency.get("blockers")))
    blockers.append("btc_intraday_event_ledger_candidate_generation_locked_pending_review")
    blockers.append("btc_true_scalping_blocked_until_1m_tick_orderbook_spread_latency_queue_model")
    blockers.append("btc_intraday_event_ledger_paper_live_locked")
    return _dedupe(blockers)


def _sqlite_range(db_path: Path, *, interval: str, symbol: str) -> tuple[datetime, datetime]:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database does not exist: {db_path}")
    with sqlite3.connect(str(db_path)) as connection:
        row = connection.execute(
            """
            SELECT MIN(open_time) AS start_time, MAX(open_time) AS end_time
            FROM market_klines
            WHERE exchange = ? AND symbol = ? AND interval = ?
            """,
            (EXCHANGE, symbol, interval),
        ).fetchone()
    if not row or not row[0] or not row[1]:
        raise ValueError(f"no BTC rows found for {symbol} {interval}")
    return (
        pd.Timestamp(row[0]).tz_convert("UTC").to_pydatetime(),
        pd.Timestamp(row[1]).tz_convert("UTC").to_pydatetime(),
    )


def _data_version(frame: pd.DataFrame) -> str:
    start = pd.Timestamp(frame.index[0]).isoformat()
    end = pd.Timestamp(frame.index[-1]).isoformat()
    return f"qs-sqlite-{SYMBOL}-{INTERVAL}-{len(frame)}-{stable_hash({'start': start, 'end': end})[:12]}"


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data.index = pd.to_datetime(data.index, utc=True)
    return data.sort_index()


def _diagnostic_series(diagnostics: Mapping[str, pd.Series], name: str, index: pd.DatetimeIndex) -> pd.Series:
    value = diagnostics.get(name)
    if value is None:
        return pd.Series(0.0, index=index, dtype=float)
    series = pd.to_numeric(value, errors="coerce")
    series.index = pd.to_datetime(series.index, utc=True)
    return series.reindex(index).ffill().fillna(0.0).astype(float)


def _past_volatility_states(volatility: pd.Series) -> pd.Series:
    series = pd.to_numeric(volatility, errors="coerce").fillna(0.0).astype(float)
    low = series.expanding(min_periods=1).quantile(0.33)
    high = series.expanding(min_periods=1).quantile(0.66)
    states = pd.Series("mid_vol", index=series.index, dtype="object")
    states.loc[series >= high] = "high_vol"
    states.loc[series <= low] = "low_vol"
    return states


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            out.append(value)
            seen.add(value)
    return out
