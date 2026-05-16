"""Event-ledger validation for BTC compression-to-expansion skeleton.

This module promotes the research skeleton only into candidate validation. It
does not create paper/live readiness, call brokers, or generate real orders.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from quant_us.research.btc_canonical import (
    BTC_CANONICAL_GATE_THRESHOLDS,
    build_canonical_report,
    build_trade_attribution,
    cost_stress_for_signal,
    evaluate_canonical_gate,
    git_commit_hash,
    regime_report_from_trades,
    rolling_walk_forward_for_signal,
    stable_hash,
    summarize_trade_attribution,
    write_json,
)
from quant_us.research.btc_alpha_hardening import classify_btc_regimes
from quant_us.research.btc_eventpf_wf import load_btc_1h_frame
from quant_us.research.btc_hypothesis_lab import DEFAULT_CONFIG_PATH, build_event_table, load_hypothesis_config


BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID = "20260516T133000Z_compression_expansion_eventledger"
BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT = Path("artifacts/btc_candidate_validation")
DEFAULT_VALIDATION_CONFIG_PATH = Path("configs/btc/candidate_validation/compression_expansion_breakout_v1_event_ledger.yaml")
SOURCE_HYPOTHESIS_RUN_DIR = Path("artifacts/btc_hypothesis/20260516T122000Z_compression_expansion")


def load_validation_config(path: str | Path = DEFAULT_VALIDATION_CONFIG_PATH) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"validation config must be a mapping: {path}")
    return payload


def run_compression_expansion_event_ledger_validation(
    *,
    run_id: str = BTC_COMPRESSION_EXPANSION_VALIDATION_RUN_ID,
    config_path: str | Path = DEFAULT_VALIDATION_CONFIG_PATH,
    output_root: Path = BTC_COMPRESSION_EXPANSION_VALIDATION_ROOT,
) -> Path:
    config = load_validation_config(config_path)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    frame = load_btc_1h_frame()
    start = frame.index[0].to_pydatetime()
    end = frame.index[-1].to_pydatetime()
    strategy_id = str(config["strategy_id"])
    params = dict(config.get("params", {}))
    signal, diagnostics = compression_expansion_signal(frame, params)
    event = _run_event(frame=frame, signal=signal, strategy_id=strategy_id, params=params, start=start, end=end, run_dir=run_dir)
    trades = ledger_segments_from_signal(
        run_id=run_id,
        strategy_id=strategy_id,
        frame=frame,
        signal=signal,
        manifest_path=Path(str(event["manifest_path"])),
    )
    trade_ledger_path = run_dir / "trade_ledger.csv"
    trades.to_csv(trade_ledger_path, index=False)
    fill_trades = _fills_to_trade_ledger_diagnostic(event["fills"], run_id=run_id, strategy_id=strategy_id)
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
    cost_stress = cost_stress_for_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
    )
    walk_forward = rolling_walk_forward_for_signal(
        frame=frame,
        signal_builder=lambda local_frame, local_params: compression_expansion_signal(local_frame, local_params),
        strategy_id=strategy_id,
        params=params,
        run_dir=run_dir,
        windows=4,
    )
    regime_report = regime_report_from_trades(frame, trades)
    write_json(run_dir / "ledger_segment_regime_report.json", regime_report)
    report = build_canonical_report(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_version=f"{strategy_id}:event_ledger_candidate_validation_v1",
        params=params,
        frame=frame,
        signal=signal,
        diagnostics=diagnostics,
        event=event,
        trades=trades,
        cost_stress=cost_stress,
        walk_forward=walk_forward,
        regime_report=regime_report,
        config_hash=stable_hash(config),
    )
    gate = evaluate_canonical_gate(report)
    report["gate_decision"] = gate.to_dict()
    report["promotion_gate_status"] = gate.status
    report["fail_reasons"] = gate.fail_reasons
    write_json(run_dir / "canonical_backtest_report.json", report)
    write_json(run_dir / "gate_inputs.json", {"strategy_id": strategy_id, "report": report, "gate": gate.to_dict()})
    write_json(run_dir / "cost_stress_report.json", cost_stress)
    write_json(run_dir / "walk_forward_report.json", walk_forward)
    write_json(run_dir / "regime_report.json", regime_report)
    write_json(
        run_dir / "pbo_dsr_report.json",
        {
            "schema_version": "btc_candidate_pbo_dsr_report_v1",
            "strategy_id": strategy_id,
            "pbo": report["metrics"]["pbo"],
            "dsr": report["metrics"]["dsr"],
            "folds": walk_forward.get("windows", []),
            "warnings": _pbo_dsr_warnings(report["metrics"]),
        },
    )
    write_json(run_dir / "candidate_validation_result.json", _candidate_summary(report, gate.to_dict()))
    write_json(run_dir / "promotion_decision.json", _promotion_decision(run_id, gate.to_dict()))
    write_json(run_dir / "paper_live_safety_status.json", _paper_live_safety(run_id, gate.to_dict()))
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": "btc_compression_expansion_candidate_validation_manifest_v1",
            "run_id": run_id,
            "strategy_id": strategy_id,
            "source_hypothesis_run": str(SOURCE_HYPOTHESIS_RUN_DIR),
            "config_path": str(config_path),
            "config_hash": stable_hash(config),
            "code_commit": git_commit_hash(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_version": report["data_version"],
            "strategy_version": report["strategy_version"],
            "cost_model": report["cost_model_id"],
            "slippage_model": "crypto_slippage_4bps_base",
            "paper_queue": "LOCKED",
            "live": "FROZEN",
        },
    )
    return run_dir


def compression_expansion_signal(frame: pd.DataFrame, params: Mapping[str, Any] | None = None) -> tuple[pd.Series, dict[str, pd.Series]]:
    cfg = {
        "time_exit_bars": 48,
        "cooldown_bars": 12,
        "signal_scale": 0.20,
        "min_reentry_delay_bars": 12,
        **dict(params or {}),
    }
    hypothesis_config = load_hypothesis_config(DEFAULT_CONFIG_PATH)
    event_table = build_event_table(frame, hypothesis_config, drop_incomplete_labels=False)
    event_table["timestamp"] = pd.to_datetime(event_table["timestamp"], utc=True)
    index = pd.to_datetime(frame.index, utc=True)
    aligned = event_table.set_index("timestamp").reindex(index)
    entries = aligned["upside_breakout"].fillna(False).astype(bool)
    signal = time_exit_long_only_signal(
        entries=entries,
        time_exit_bars=int(cfg["time_exit_bars"]),
        cooldown_bars=max(int(cfg["cooldown_bars"]), int(cfg.get("min_reentry_delay_bars", 0))),
        signal_scale=float(cfg["signal_scale"]),
    )
    diagnostics = {
        "compression_score": pd.to_numeric(aligned["compression_score"], errors="coerce").fillna(0.0),
        "expansion_score": pd.to_numeric(aligned["expansion_score"], errors="coerce").fillna(0.0),
        "upside_breakout": entries.astype(float),
        "downside_breakout": aligned["downside_breakout"].fillna(False).astype(float),
        "range_expansion": aligned["range_expansion"].fillna(False).astype(float),
        "volatility_expansion": aligned["volatility_expansion"].fillna(False).astype(float),
        "target_signal": signal,
        "raw_signal": signal,
    }
    for key, value in diagnostics.items():
        value.index = index
        diagnostics[key] = value
    return signal.reindex(index).fillna(0.0).clip(0.0, 1.0), diagnostics


def time_exit_long_only_signal(
    *,
    entries: pd.Series,
    time_exit_bars: int,
    cooldown_bars: int,
    signal_scale: float,
) -> pd.Series:
    signal = pd.Series(0.0, index=entries.index, dtype=float)
    in_position = False
    bars_remaining = 0
    cooldown_remaining = 0
    scale = min(1.0, max(0.0, float(signal_scale)))
    for timestamp, entry in entries.fillna(False).astype(bool).items():
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
        if in_position:
            bars_remaining -= 1
            if bars_remaining <= 0:
                in_position = False
                cooldown_remaining = max(0, int(cooldown_bars))
        if not in_position and cooldown_remaining == 0 and bool(entry):
            in_position = True
            bars_remaining = max(1, int(time_exit_bars))
        signal.loc[timestamp] = scale if in_position else 0.0
    return signal


def ledger_segments_from_signal(
    *,
    run_id: str,
    strategy_id: str,
    frame: pd.DataFrame,
    signal: pd.Series,
    manifest_path: Path,
) -> pd.DataFrame:
    equity = _ledger_equity_curve(manifest_path)
    local_frame = frame.copy()
    local_frame.index = pd.to_datetime(local_frame.index, utc=True)
    aligned_signal = signal.reindex(local_frame.index).fillna(0.0).astype(float)
    active = aligned_signal > 0.0
    rows: list[dict[str, Any]] = []
    in_segment = False
    entry_ts: pd.Timestamp | None = None
    entry_equity = 0.0
    entry_price = 0.0
    entry_size = 0.0
    segment_no = 0
    for ts in local_frame.index:
        is_active = bool(active.loc[ts])
        if is_active and not in_segment:
            in_segment = True
            entry_ts = pd.Timestamp(ts)
            entry_equity = float(equity.reindex([entry_ts], method="ffill").iloc[0])
            entry_price = float(local_frame.loc[ts, "close"])
            entry_size = float(aligned_signal.loc[ts])
        elif in_segment and not is_active:
            exit_ts = pd.Timestamp(ts)
            exit_equity = float(equity.reindex([exit_ts], method="ffill").iloc[0])
            exit_price = float(local_frame.loc[ts, "close"])
            segment_no += 1
            holding_hours = max(0.0, (exit_ts - (entry_ts or exit_ts)).total_seconds() / 3600.0)
            net_pnl = exit_equity - entry_equity
            rows.append(
                {
                    "run_id": run_id,
                    "strategy_id": strategy_id,
                    "trade_id": f"{strategy_id}_segment_{segment_no:05d}",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_time": (entry_ts or exit_ts).isoformat(),
                    "exit_time": exit_ts.isoformat(),
                    "entry_price": round(entry_price, 8),
                    "exit_price": round(exit_price, 8),
                    "size": round(entry_size, 8),
                    "gross_pnl": round(net_pnl, 8),
                    "net_pnl": round(net_pnl, 8),
                    "fees": 0.0,
                    "slippage": 0.0,
                    "holding_bars": int(round(holding_hours)),
                    "holding_hours": round(holding_hours, 4),
                    "attribution_source": "ledger_equity_segments",
                }
            )
            in_segment = False
            entry_ts = None
    if in_segment and entry_ts is not None:
        exit_ts = pd.Timestamp(local_frame.index[-1])
        exit_equity = float(equity.reindex([exit_ts], method="ffill").iloc[0])
        exit_price = float(local_frame.iloc[-1]["close"])
        segment_no += 1
        holding_hours = max(0.0, (exit_ts - entry_ts).total_seconds() / 3600.0)
        net_pnl = exit_equity - entry_equity
        rows.append(
            {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "trade_id": f"{strategy_id}_segment_{segment_no:05d}",
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_time": entry_ts.isoformat(),
                "exit_time": exit_ts.isoformat(),
                "entry_price": round(entry_price, 8),
                "exit_price": round(exit_price, 8),
                "size": round(entry_size, 8),
                "gross_pnl": round(net_pnl, 8),
                "net_pnl": round(net_pnl, 8),
                "fees": 0.0,
                "slippage": 0.0,
                "holding_bars": int(round(holding_hours)),
                "holding_hours": round(holding_hours, 4),
                "attribution_source": "ledger_equity_segments",
            }
        )
    return pd.DataFrame(rows)


def _ledger_equity_curve(manifest_path: Path) -> pd.Series:
    manifest = read_json(manifest_path)
    snapshots = (
        manifest.get("ledger_artifact", {})
        .get("reconciliation", {})
        .get("snapshots", [])
    )
    if not snapshots:
        snapshots = (
            manifest.get("evidence", {})
            .get("ledger_artifact", {})
            .get("reconciliation", {})
            .get("snapshots", [])
        )
    equity = pd.Series(
        [float(row.get("ledger_equity", row.get("snapshot_equity", 0.0))) for row in snapshots],
        index=pd.to_datetime([row.get("timestamp_utc") for row in snapshots], utc=True),
        dtype=float,
    ).sort_index()
    if equity.empty:
        raise ValueError(f"ledger equity snapshots missing from manifest: {manifest_path}")
    return equity


def _fills_to_trade_ledger_diagnostic(fills: Any, *, run_id: str, strategy_id: str) -> pd.DataFrame:
    from quant_us.research.btc_canonical import fills_to_trade_ledger

    return fills_to_trade_ledger(fills, run_id=run_id, strategy_id=strategy_id)


def _run_event(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: Mapping[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
) -> dict[str, Any]:
    from quant_us.research.btc_canonical import run_event_with_signal

    return run_event_with_signal(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        scenario_name="base",
        commission_rate=0.0004,
        slippage_bps=4.0,
        target_weight=0.90,
    )


def _candidate_summary(report: Mapping[str, Any], gate: Mapping[str, Any]) -> dict[str, Any]:
    metrics = report["metrics"]
    return {
        "schema_version": "btc_compression_expansion_candidate_validation_result_v1",
        "run_id": report["run_id"],
        "strategy_id": report["strategy_id"],
        "status": gate["status"],
        "gate_passed": bool(gate["passed"]),
        "gate_fail_reasons": list(gate["fail_reasons"]),
        "metrics": {
            "profit_factor": metrics["profit_factor"],
            "event_profit_factor": metrics["event_profit_factor"],
            "sharpe": metrics["sharpe"],
            "max_drawdown": metrics["max_drawdown"],
            "annual_turnover": metrics["annual_turnover"],
            "walk_forward_pass_rate": metrics["walk_forward_pass_rate"],
            "regime_pass_rate": metrics["regime_pass_rate"],
            "pbo": metrics["pbo"],
            "dsr": metrics["dsr"],
            "trade_count": metrics["trade_count"],
            "fill_count": metrics["fill_count"],
        },
        "paper_queue": "LOCKED",
        "live": "FROZEN",
    }


def _promotion_decision(run_id: str, gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_candidate_validation_promotion_decision_v1",
        "run_id": run_id,
        "candidate_gate_results": [gate],
        "paper_review": {
            "paper_review_queue_locked": True,
            "paper_review_pending": [],
            "paper_auto_start": False,
            "reason": "event_ledger_candidate_validation_only_manual_next_sprint_required",
        },
        "candidate_passed_internal_gate_count": 1 if bool(gate.get("passed", False)) else 0,
        "max_state": str(gate.get("status", "candidate_gate_failed")),
        "live_frozen": True,
        "forbidden_states": ["live_enabled", "live_ready", "paper_ready"],
    }


def _paper_live_safety(run_id: str, gate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_candidate_validation_paper_live_safety_v1",
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


def _pbo_dsr_warnings(metrics: Mapping[str, Any]) -> list[str]:
    warnings = []
    if float(metrics.get("pbo", 1.0)) > BTC_CANONICAL_GATE_THRESHOLDS["pbo"]:
        warnings.append("pbo_above_threshold")
    if float(metrics.get("dsr", 0.0)) < BTC_CANONICAL_GATE_THRESHOLDS["dsr"]:
        warnings.append("dsr_below_threshold")
    return warnings


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_event_ledger_attribution(
    *,
    run_dir: Path,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    report = read_json(run_dir / "canonical_backtest_report.json")
    validation = read_json(run_dir / "candidate_validation_result.json")
    walk_forward = read_json(run_dir / "walk_forward_report.json")
    regime_report = read_json(run_dir / "regime_report.json")
    pbo_dsr = read_json(run_dir / "pbo_dsr_report.json")
    safety = read_json(run_dir / "paper_live_safety_status.json")
    trades = pd.read_csv(run_dir / "trade_ledger.csv")
    local_frame = load_btc_1h_frame() if frame is None else frame.copy()
    local_frame.index = pd.to_datetime(local_frame.index, utc=True)
    equity = _ledger_equity_curve(Path(report["event_ledger_status"]["manifest_path"]))
    table = _event_return_table(
        frame=local_frame,
        equity=equity,
        trades=trades,
        walk_forward=walk_forward,
    )
    table_path = run_dir / "event_ledger_attribution_table.csv"
    table.to_csv(table_path, index=False)
    active = table.loc[table["active_exposure"].astype(bool)].copy()
    failed_folds = [row for row in walk_forward.get("windows", []) if not bool(row.get("passed", False))]
    payload = {
        "schema_version": "btc_compression_expansion_event_ledger_attribution_v1",
        "run_id": report["run_id"],
        "strategy_id": report["strategy_id"],
        "source": "event_ledger_equity_snapshots",
        "event_ledger_attribution_table": str(table_path),
        "ordinary_pf": report["metrics"]["profit_factor"],
        "event_pf": report["metrics"]["event_profit_factor"],
        "gate_status": validation["status"],
        "gate_fail_reasons": validation["gate_fail_reasons"],
        "paper_queue": safety["paper_queue"],
        "live": safety["live"],
        "overall_event_distribution": _event_stats(table, "event_return"),
        "active_exposure_distribution": _event_stats(active, "event_return"),
        "by_fold": _group_event_stats(active, "fold_id"),
        "by_regime": _group_event_stats(active, "regime"),
        "by_regime_fold": _worst_group_event_stats(active, ["fold_id", "regime"], limit=12),
        "by_segment_age_bucket": _group_event_stats(active, "segment_age_bucket"),
        "failed_fold_autopsy": _failed_fold_autopsy(table, failed_folds),
        "trade_segment_attribution": {
            "trade_count": int(len(trades)),
            "top_loss_segments": trades.sort_values("net_pnl", ascending=True).head(10).to_dict(orient="records"),
            "top_profit_segments": trades.sort_values("net_pnl", ascending=False).head(10).to_dict(orient="records"),
            "regime_report": regime_report,
        },
        "pbo_dsr": {
            "pbo": pbo_dsr.get("pbo"),
            "dsr": pbo_dsr.get("dsr"),
            "warnings": pbo_dsr.get("warnings", []),
        },
        "root_cause_summary": _root_cause_summary(report, walk_forward, regime_report),
        "recommended_next_actions": [
            "Do not create paper_review_pending until event_PF, walk_forward, and regime gates pass together.",
            "Keep long-only upside breakout, but test regime keep-outs for trending_down, high_vol_trend, mean_reverting_chop, compression, and expansion.",
            "Autopsy fold 3 and fold 4 before changing parameters; both are event-ledger failures, not cost failures.",
            "Use event_PF and ledger equity snapshots as gate evidence; ordinary PF remains diagnostic.",
        ],
    }
    write_json(run_dir / "event_ledger_attribution_report.json", payload)
    write_json(run_dir / "fold_regime_diagnostics_cleanup.json", _fold_regime_cleanup(payload))
    return payload


def _event_return_table(
    *,
    frame: pd.DataFrame,
    equity: pd.Series,
    trades: pd.DataFrame,
    walk_forward: Mapping[str, Any],
) -> pd.DataFrame:
    index = pd.to_datetime(frame.index, utc=True)
    aligned_equity = equity.reindex(index).ffill().bfill()
    regimes = classify_btc_regimes(frame).reindex(index).ffill().fillna("unknown")
    returns = frame["close"].astype(float).pct_change().fillna(0.0)
    volatility = returns.rolling(168, min_periods=24).std(ddof=0).fillna(0.0)
    trend = frame["close"].astype(float).pct_change(168).fillna(0.0)
    exposure = pd.Series(0.0, index=index, dtype=float)
    segment_ids = pd.Series("", index=index, dtype=object)
    segment_age = pd.Series(0, index=index, dtype=int)
    for _, trade in trades.iterrows():
        entry = pd.Timestamp(trade["entry_time"])
        exit_ts = pd.Timestamp(trade["exit_time"])
        entry = entry.tz_localize("UTC") if entry.tzinfo is None else entry.tz_convert("UTC")
        exit_ts = exit_ts.tz_localize("UTC") if exit_ts.tzinfo is None else exit_ts.tz_convert("UTC")
        mask = (index >= entry) & (index < exit_ts)
        exposure.loc[mask] = float(trade.get("size", 0.0))
        segment_ids.loc[mask] = str(trade.get("trade_id", ""))
        segment_age.loc[mask] = range(int(mask.sum()))
    table = pd.DataFrame(
        {
            "timestamp": index,
            "equity_before": aligned_equity.shift(1).fillna(aligned_equity.iloc[0]).values,
            "equity_after": aligned_equity.values,
            "event_return": aligned_equity.pct_change().fillna(0.0).values,
            "signed_event_pnl": aligned_equity.diff().fillna(0.0).values,
            "active_exposure": (exposure > 0.0).values,
            "exposure": exposure.values,
            "segment_id": segment_ids.values,
            "segment_age_bars": segment_age.values,
            "segment_age_bucket": [_age_bucket(int(value)) for value in segment_age.values],
            "fold_id": _fold_ids_from_report(index, walk_forward),
            "regime": regimes.astype(str).values,
            "volatility_bucket": _historical_bucket(volatility, labels=("low_vol", "mid_vol", "high_vol")).values,
            "trend_strength_bucket": pd.cut(
                trend,
                bins=[-float("inf"), -0.03, 0.03, float("inf")],
                labels=["downtrend", "neutral", "uptrend"],
            ).astype(str).values,
        }
    )
    table["is_positive_event"] = table["event_return"] > 0.0
    table["is_negative_event"] = table["event_return"] < 0.0
    return table


def _event_stats(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna() if column in frame else pd.Series(dtype=float)
    positive = values[values > 0.0]
    negative = values[values < 0.0]
    if values.empty:
        return {
            "event_count": 0,
            "positive_event_rate": 0.0,
            "positive_sum": 0.0,
            "negative_sum": 0.0,
            "event_pf": 0.0,
            "mean_return": 0.0,
            "median_return": 0.0,
            "downside_tail_5pct": 0.0,
            "max_adverse_event": 0.0,
            "max_favorable_event": 0.0,
        }
    negative_abs = abs(float(negative.sum()))
    event_pf = float(positive.sum()) / negative_abs if negative_abs > 0 else (999.0 if float(positive.sum()) > 0 else 0.0)
    return {
        "event_count": int(len(values)),
        "positive_event_rate": round(float((values > 0.0).mean()), 6),
        "positive_sum": round(float(positive.sum()), 10),
        "negative_sum": round(float(negative.sum()), 10),
        "event_pf": round(event_pf, 6),
        "mean_return": round(float(values.mean()), 10),
        "median_return": round(float(values.median()), 10),
        "downside_tail_5pct": round(float(values.quantile(0.05)), 10),
        "max_adverse_event": round(float(values.min()), 10),
        "max_favorable_event": round(float(values.max()), 10),
    }


def _group_event_stats(frame: pd.DataFrame, group_col: str) -> list[dict[str, Any]]:
    rows = []
    if frame.empty:
        return rows
    for key, subset in frame.groupby(group_col, dropna=False):
        stats = _event_stats(subset, "event_return")
        stats[group_col] = str(key)
        rows.append(stats)
    return sorted(rows, key=lambda row: row["event_pf"])


def _worst_group_event_stats(frame: pd.DataFrame, group_cols: list[str], *, limit: int) -> list[dict[str, Any]]:
    rows = []
    if frame.empty:
        return rows
    for keys, subset in frame.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        stats = _event_stats(subset, "event_return")
        for column, key in zip(group_cols, keys):
            stats[column] = str(key)
        rows.append(stats)
    return sorted(rows, key=lambda row: row["event_pf"])[:limit]


def _failed_fold_autopsy(table: pd.DataFrame, failed_folds: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for fold in failed_folds:
        fold_id = str(fold.get("fold"))
        subset = table.loc[(table["fold_id"].astype(str) == fold_id) & table["active_exposure"].astype(bool)]
        by_regime = _group_event_stats(subset, "regime")
        negative_events = subset.sort_values("event_return", ascending=True).head(10)
        rows.append(
            {
                "fold_id": fold_id,
                "validation_start": fold.get("validation_start"),
                "validation_end": fold.get("validation_end"),
                "event_summary": fold.get("summary", {}),
                "active_event_distribution": _event_stats(subset, "event_return"),
                "worst_regimes": by_regime[:5],
                "largest_negative_events": negative_events[
                    ["timestamp", "event_return", "signed_event_pnl", "regime", "segment_id", "segment_age_bucket"]
                ].to_dict(orient="records"),
                "recommended_action": "block_or_reduce_regime_exposure_before_parameter_search",
            }
        )
    return rows


def _root_cause_summary(report: Mapping[str, Any], walk_forward: Mapping[str, Any], regime_report: Mapping[str, Any]) -> list[str]:
    metrics = report["metrics"]
    failed_folds = [str(row.get("fold")) for row in walk_forward.get("windows", []) if not bool(row.get("passed", False))]
    dragging = list(regime_report.get("dragging_regimes", []))
    return [
        f"ordinary PF {float(metrics['profit_factor']):.4f} passes, but event_PF {float(metrics['event_profit_factor']):.4f} fails the 1.15 gate.",
        f"walk-forward pass rate is {float(metrics['walk_forward_pass_rate']):.2f}; failed folds are {', '.join(failed_folds) if failed_folds else 'none'}.",
        f"regime pass rate is {float(metrics['regime_pass_rate']):.4f}; dragging regimes are {', '.join(dragging) if dragging else 'none'}.",
        "cost stress passes base and harsh scenarios, so the blocker is alpha stability rather than transaction cost survival.",
    ]


def _fold_regime_cleanup(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "btc_fold_regime_diagnostics_cleanup_v1",
        "run_id": report["run_id"],
        "strategy_id": report["strategy_id"],
        "failed_folds": [row["fold_id"] for row in report["failed_fold_autopsy"]],
        "worst_regime_fold_pairs": report["by_regime_fold"][:8],
        "dragging_regimes": report["trade_segment_attribution"]["regime_report"].get("dragging_regimes", []),
        "cleanup_actions": [
            "Use ledger equity segments for trade/regime diagnostics.",
            "Keep fill aggregation as diagnostic only for this candidate.",
            "Do not promote based on ordinary PF while event_PF is below threshold.",
            "Require fold/regime gates before paper_review_pending.",
        ],
    }


def _fold_ids_from_report(index: pd.DatetimeIndex, walk_forward: Mapping[str, Any]) -> list[str]:
    labels = ["pre_wf"] * len(index)
    for window in walk_forward.get("windows", []):
        start = pd.Timestamp(window.get("validation_start"))
        end = pd.Timestamp(window.get("validation_end"))
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        fold_id = str(window.get("fold"))
        mask = (index >= start) & (index <= end)
        for pos in mask.nonzero()[0]:
            labels[pos] = fold_id
    return labels


def _historical_bucket(series: pd.Series, *, labels: tuple[str, str, str]) -> pd.Series:
    low = series.expanding(min_periods=48).quantile(0.33).fillna(series)
    high = series.expanding(min_periods=48).quantile(0.66).fillna(series)
    return pd.Series(
        ["low_vol" if value <= lo else "high_vol" if value >= hi else "mid_vol" for value, lo, hi in zip(series, low, high)],
        index=series.index,
    ).replace({"low_vol": labels[0], "mid_vol": labels[1], "high_vol": labels[2]})


def _age_bucket(age: int) -> str:
    if age <= 6:
        return "0_6h"
    if age <= 12:
        return "7_12h"
    if age <= 24:
        return "13_24h"
    if age <= 36:
        return "25_36h"
    return "37_48h"
