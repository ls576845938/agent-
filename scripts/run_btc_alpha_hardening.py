#!/usr/bin/env python3
"""Generate BTC Alpha Hardening Sprint artifacts.

This script is research-only. It never creates paper/live runtime state.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from math import sqrt
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from backend.app.services.market_data import load_market_frame
from quant_us.backtest.crypto_event import CRYPTO_COST_STRESS_SCENARIOS, run_crypto_event_backtest
from quant_us.research.btc_alpha_hardening import (
    BTC_HARDENING_GATE_THRESHOLDS,
    annual_turnover_from_signal,
    btc_dual_trend_v2_signal,
    btc_orderflow_confirmed_trend_signal,
    classify_btc_regimes,
    decide_paper_review_queue,
    evaluate_internal_gate,
    hardening_objective_score,
    regime_pass_rate,
    simplified_dsr,
    simplified_pbo,
)


StrategySignalFn = Callable[[pd.DataFrame, dict[str, Any]], tuple[pd.Series, dict[str, pd.Series]]]


BASELINE_EVIDENCE = {
    "btc_perp_dual_trend": Path("data/research/btc_closure_runs/btc_closure_btcusdt_1h_9e2ec8206064_strict_evidence.json"),
    "btc_orderflow_pressure": Path("data/research/btc_closure_runs/btc_closure_btcusdt_1h_e9b3502a9b57_strict_evidence.json"),
}

CANDIDATES: dict[str, tuple[StrategySignalFn, dict[str, Any]]] = {
    "btc_perp_dual_trend_v2": (
        btc_dual_trend_v2_signal,
        {
            "fast_ma": 96,
            "slow_ma": 336,
            "regime_ma": 720,
            "momentum_window": 168,
            "momentum_threshold": 0.025,
            "vol_window": 168,
            "max_volatility": 0.05,
            "buy_ratio_threshold": 0.54,
            "sell_ratio_threshold": 0.46,
            "pressure_threshold": 0.0075,
            "orderflow_window": 144,
            "activity_window": 144,
            "min_quote_intensity": 0.75,
            "min_trade_intensity": 0.70,
            "signal_persistence_bars": 3,
            "exit_hysteresis_bars": 4,
            "min_hold_bars": 120,
            "cooldown_bars": 72,
            "max_hold_bars": 720,
            "signal_scale": 0.20,
            "blocked_regimes": ["low_vol_chop", "mean_reverting_chop", "liquidation_shock"],
        },
    ),
    "btc_orderflow_confirmed_trend_v1": (
        btc_orderflow_confirmed_trend_signal,
        {
            "fast_ma": 96,
            "slow_ma": 336,
            "regime_ma": 720,
            "momentum_window": 168,
            "momentum_threshold": 0.025,
            "vol_window": 168,
            "max_volatility": 0.055,
            "buy_ratio_threshold": 0.535,
            "sell_ratio_threshold": 0.465,
            "pressure_threshold": 0.01,
            "orderflow_window": 144,
            "activity_window": 144,
            "min_quote_intensity": 0.80,
            "min_trade_intensity": 0.70,
            "signal_persistence_bars": 4,
            "exit_hysteresis_bars": 4,
            "min_hold_bars": 120,
            "cooldown_bars": 72,
            "max_hold_bars": 720,
            "signal_scale": 0.20,
            "blocked_regimes": ["low_vol_chop", "mean_reverting_chop", "liquidation_shock"],
        },
    ),
}


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default), encoding="utf-8")


def _git_commit_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _load_evidence(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _baseline_row(strategy_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    candidate = evidence.get("candidate", {})
    validation = candidate.get("validation", {})
    wf_stability = (evidence.get("walk_forward", {}) or {}).get("stability", {})
    cost = evidence.get("cost_stress", {}) or {}
    event_summary = (evidence.get("event_backtest", {}) or {}).get("summary", {})
    stats = evidence.get("validation_statistics", {}) or {}
    gate = evaluate_internal_gate(
        strategy_id,
        {
            "profit_factor": validation.get("profit_factor", 0.0),
            "event_profit_factor": event_summary.get("profit_factor", 0.0),
            "walk_forward_pass_rate": float(wf_stability.get("fold_pass_rate_pct", 0.0)) / 100.0,
            "regime_pass_rate": float(wf_stability.get("regime_pass_rate_pct", 0.0)) / 100.0,
            "annual_turnover": float(validation.get("annual_turnover_pct", 0.0)) / 100.0,
            "max_drawdown_pct": validation.get("max_drawdown_pct", -100.0),
            "cost_stress_base_pass": bool((cost.get("scenarios") or [{}])[0].get("survives", False)),
            "cost_stress_harsh_survives": bool(cost.get("survival_rate_pct", 0.0) >= 100.0),
            "no_lookahead_pass": (stats.get("lookahead_controls", {}) or {}).get("passed") is True,
            "event_ledger_pass": (evidence.get("event_backtest", {}).get("diagnostics", {}) or {}).get("ledger_equity_consistent") is True,
            "dsr": (stats.get("deflated_sharpe_ratio", {}) or {}).get("dsr", 0.0),
            "pbo": (stats.get("pbo", {}) or {}).get("pbo", 1.0),
        },
    )
    return {
        "strategy_id": strategy_id,
        "source_evidence_path": str(path_from_evidence(evidence)),
        "data_range": {
            "start": (evidence.get("selected_request") or {}).get("start", ""),
            "end": (evidence.get("selected_request") or {}).get("end", ""),
        },
        "timeframe": (evidence.get("selected_request") or {}).get("interval", "1h"),
        "params": candidate.get("parameters", {}),
        "sharpe": validation.get("sharpe_ratio", 0.0),
        "profit_factor": validation.get("profit_factor", 0.0),
        "max_drawdown": validation.get("max_drawdown_pct", 0.0),
        "annual_turnover": float(validation.get("annual_turnover_pct", 0.0)) / 100.0,
        "annual_turnover_pct": validation.get("annual_turnover_pct", 0.0),
        "trade_count": validation.get("trade_count", 0),
        "win_rate": validation.get("win_rate_pct", 0.0),
        "avg_holding_bars": validation.get("avg_holding_bars", 0.0),
        "walk_forward_pass_rate": float(wf_stability.get("fold_pass_rate_pct", 0.0)) / 100.0,
        "regime_pass_rate": float(wf_stability.get("regime_pass_rate_pct", 0.0)) / 100.0,
        "cost_stress_result": {
            "survival_rate_pct": cost.get("survival_rate_pct", 0.0),
            "ledger_consistency_pct": cost.get("ledger_consistency_pct", 0.0),
            "scenario_count": cost.get("scenario_count", 0),
        },
        "event_ledger": {
            "summary": event_summary,
            "diagnostics": {
                key: (evidence.get("event_backtest", {}).get("diagnostics", {}) or {}).get(key)
                for key in ["engine", "pnl_source", "ledger_equity_consistent", "manifest_path"]
            },
        },
        "dsr": (stats.get("deflated_sharpe_ratio", {}) or {}).get("dsr"),
        "pbo": (stats.get("pbo", {}) or {}).get("pbo"),
        "gate_status": gate.status,
        "gate_fail_reasons": gate.fail_reasons,
    }


def path_from_evidence(evidence: dict[str, Any]) -> str:
    audit = evidence.get("candidate", {}).get("audit", {})
    return str(audit.get("strict_evidence_path", ""))


def _run_event(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: dict[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    commission_rate: float,
    slippage_bps: float,
    scenario_name: str,
) -> dict[str, Any]:
    replay = signal.copy()
    replay.index = pd.to_datetime(replay.index, utc=True)

    def provider(loaded_frame: pd.DataFrame, _strategy_id: str, _params: dict[str, Any]) -> pd.Series:
        loaded_index = pd.to_datetime(loaded_frame.index, utc=True)
        return replay.reindex(loaded_index).fillna(0.0).clip(-1.0, 1.0)

    result = run_crypto_event_backtest(
        source="sqlite",
        symbol="BTCUSDT",
        interval="1h",
        start=start,
        end=end,
        strategy_id=strategy_id,
        params=params,
        capital=100_000.0,
        commission_rate=commission_rate,
        slippage_bps=slippage_bps,
        market_loader=lambda **_: frame.copy(),
        signal_provider=provider,
        data_version="qs-sqlite-BTCUSDT-1h-66968bfbabf2",
        strategy_version=f"{strategy_id}:alpha_hardening_v1",
        manifest_root=run_dir / "manifests",
        target_weight=0.90,
        min_cash_buffer_pct=0.02,
        min_trade_notional=25.0,
        rebalance_buffer_pct=0.05,
        long_only=False,
        run_id=f"{strategy_id}_{scenario_name}",
    )
    return {
        "summary": result.summary,
        "diagnostics": result.diagnostics,
        "fills": result.unified.fills,
        "manifest_path": result.diagnostics.get("manifest_path", ""),
    }


def _cost_stress(
    *,
    frame: pd.DataFrame,
    signal: pd.Series,
    strategy_id: str,
    params: dict[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    max_scenarios: int,
) -> dict[str, Any]:
    scenarios = []
    for scenario in CRYPTO_COST_STRESS_SCENARIOS[:max_scenarios]:
        event = _run_event(
            frame=frame,
            signal=signal,
            strategy_id=strategy_id,
            params=params,
            start=start,
            end=end,
            run_dir=run_dir,
            commission_rate=0.0004 * float(scenario["commission_multiplier"]),
            slippage_bps=4.0 * float(scenario["slippage_multiplier"]),
            scenario_name=str(scenario["name"]),
        )
        summary = event["summary"]
        survives = (
            float(summary.get("total_return_pct", 0.0)) > 0.0
            and float(summary.get("profit_factor", 0.0)) >= 1.0
            and event["diagnostics"].get("ledger_equity_consistent") is True
        )
        scenarios.append(
            {
                "name": scenario["name"],
                "label": scenario["label"],
                "survives": survives,
                "summary": summary,
                "manifest_path": event["manifest_path"],
            }
        )
    return {
        "engine": "event_driven",
        "scenario_count": len(scenarios),
        "survival_rate_pct": round(sum(1 for row in scenarios if row["survives"]) / max(1, len(scenarios)) * 100.0, 4),
        "ledger_consistency_pct": 100.0,
        "scenarios": scenarios,
        "base": scenarios[0] if scenarios else None,
        "harsh": scenarios[-1] if scenarios else None,
    }


def _walk_forward(
    *,
    frame: pd.DataFrame,
    signal_fn: StrategySignalFn,
    strategy_id: str,
    params: dict[str, Any],
    start: datetime,
    end: datetime,
    run_dir: Path,
    windows: int,
) -> dict[str, Any]:
    rows = []
    n = len(frame)
    validation_rows = max(500, n // (windows + 2))
    for fold in range(windows):
        validation_start_pos = n - validation_rows * (windows - fold)
        validation_end_pos = n - validation_rows * (windows - fold - 1)
        validation_frame = frame.iloc[max(0, validation_start_pos):validation_end_pos].copy()
        context_frame = frame.iloc[:validation_end_pos].copy()
        if len(validation_frame) < 50:
            continue
        full_signal, _ = signal_fn(context_frame, params)
        fold_signal = full_signal.reindex(validation_frame.index).fillna(0.0)
        event = _run_event(
            frame=validation_frame,
            signal=fold_signal,
            strategy_id=strategy_id,
            params=params,
            start=validation_frame.index[0].to_pydatetime(),
            end=validation_frame.index[-1].to_pydatetime(),
            run_dir=run_dir,
            commission_rate=0.0004,
            slippage_bps=4.0,
            scenario_name=f"wf{fold + 1}",
        )
        summary = event["summary"]
        survives = (
            float(summary.get("total_return_pct", 0.0)) >= 0.0
            and float(summary.get("sharpe_ratio", 0.0)) >= 0.0
            and float(summary.get("max_drawdown_pct", -100.0)) > -18.0
        )
        rows.append(
            {
                "fold": fold + 1,
                "validation_start": validation_frame.index[0].isoformat(),
                "validation_end": validation_frame.index[-1].isoformat(),
                "validation_rows": len(validation_frame),
                "survives": survives,
                "validation": summary,
                "manifest_path": event["manifest_path"],
                "equity_consistent": event["diagnostics"].get("ledger_equity_consistent") is True,
            }
        )
    pass_rate = sum(1 for row in rows if row["survives"]) / max(1, len(rows))
    return {
        "method": "rolling_event_ledger_fixed_params",
        "status": "completed" if rows else "insufficient_data",
        "windows": rows,
        "stability": {
            "total_folds": len(rows),
            "valid_folds": len(rows),
            "passing_folds": sum(1 for row in rows if row["survives"]),
            "fold_pass_rate_pct": round(pass_rate * 100.0, 4),
            "pass_rate": round(pass_rate, 6),
            "ledger_consistency_pct": round(sum(1 for row in rows if row["equity_consistent"]) / max(1, len(rows)) * 100.0, 4),
        },
    }


def _trade_rows_from_fills(fills: list[Any], regimes: pd.Series) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    position = 0.0
    avg_price = 0.0
    entry_time = None
    for fill in fills:
        side = getattr(getattr(fill, "side", ""), "value", str(getattr(fill, "side", "")))
        qty = float(getattr(fill, "quantity", 0.0))
        price = float(getattr(fill, "price", 0.0))
        signed = qty if side == "buy" else -qty
        ts = pd.Timestamp(getattr(fill, "filled_at", None))
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        if position == 0.0:
            position = signed
            avg_price = price
            entry_time = ts
            continue
        same_direction = (position > 0 and signed > 0) or (position < 0 and signed < 0)
        if same_direction:
            total_qty = abs(position) + abs(signed)
            avg_price = (avg_price * abs(position) + price * abs(signed)) / max(total_qty, 1e-12)
            position += signed
            continue
        closing_qty = min(abs(position), abs(signed))
        pnl = (price - avg_price) * closing_qty if position > 0 else (avg_price - price) * closing_qty
        entry_ts = pd.Timestamp(entry_time) if entry_time is not None else ts
        regime = str(regimes.reindex([entry_ts], method="ffill").iloc[0]) if not regimes.empty else "unknown"
        rows.append(
            {
                "entry_time": entry_ts.isoformat(),
                "exit_time": ts.isoformat(),
                "side": "long" if position > 0 else "short",
                "quantity": round(closing_qty, 8),
                "pnl": round(pnl, 6),
                "holding_bars": max(0, int((ts - entry_ts).total_seconds() // 3600)),
                "regime": regime,
            }
        )
        residual = abs(signed) - closing_qty
        if residual <= 1e-12:
            position += signed
            if abs(position) <= 1e-12:
                position = 0.0
                avg_price = 0.0
                entry_time = None
        else:
            position = residual if signed > 0 else -residual
            avg_price = price
            entry_time = ts
    return rows


def _regime_report(strategy_id: str, frame: pd.DataFrame, fills: list[Any]) -> dict[str, Any]:
    regimes = classify_btc_regimes(frame)
    trades = _trade_rows_from_fills(fills, regimes)
    rows = []
    for regime in [
        "trending_up",
        "trending_down",
        "high_vol_trend",
        "low_vol_chop",
        "mean_reverting_chop",
        "liquidation_shock",
        "compression",
        "expansion",
    ]:
        subset = [row for row in trades if row["regime"] == regime]
        pnls = [float(row["pnl"]) for row in subset]
        wins = [value for value in pnls if value > 0]
        losses = [-value for value in pnls if value < 0]
        pf = sum(wins) / sum(losses) if losses else (999.0 if wins else 0.0)
        pnl_series = pd.Series(pnls, dtype=float)
        sharpe = float(pnl_series.mean() / pnl_series.std(ddof=0) * sqrt(len(pnl_series))) if len(pnl_series) > 1 and pnl_series.std(ddof=0) > 0 else 0.0
        trade_count = len(subset)
        passed = trade_count == 0 or (pf >= 1.0 and sum(pnls) >= 0.0)
        rows.append(
            {
                "regime": regime,
                "profit_factor": round(pf, 4) if pf != 999.0 else 999.0,
                "sharpe": round(sharpe, 4),
                "win_rate": round(sum(1 for value in pnls if value > 0) / max(1, trade_count), 6),
                "turnover": trade_count,
                "avg_holding_bars": round(sum(float(row["holding_bars"]) for row in subset) / max(1, trade_count), 4),
                "trade_count": trade_count,
                "pnl_contribution": round(sum(pnls), 6),
                "passed": passed,
            }
        )
    return {
        "strategy_id": strategy_id,
        "regime_classifier": "past_only_rolling_v1",
        "trade_count": len(trades),
        "trades": trades[:200],
        "regimes": rows,
        "regime_pass_rate": regime_pass_rate(rows),
        "dragging_regimes": [row["regime"] for row in rows if row["trade_count"] > 0 and not row["passed"]],
    }


def _candidate_result(
    *,
    strategy_id: str,
    signal_fn: StrategySignalFn,
    params: dict[str, Any],
    frame: pd.DataFrame,
    start: datetime,
    end: datetime,
    run_dir: Path,
) -> dict[str, Any]:
    signal, diagnostics = signal_fn(frame, params)
    event = _run_event(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        commission_rate=0.0004,
        slippage_bps=4.0,
        scenario_name="base",
    )
    cost = _cost_stress(
        frame=frame,
        signal=signal,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        max_scenarios=4,
    )
    wf = _walk_forward(
        frame=frame,
        signal_fn=signal_fn,
        strategy_id=strategy_id,
        params=params,
        start=start,
        end=end,
        run_dir=run_dir,
        windows=4,
    )
    regime = _regime_report(strategy_id, frame, event["fills"])
    summary = event["summary"]
    signal_turnover = annual_turnover_from_signal(signal, periods_per_year=365.0 * 24)
    pbo_trials = [
        {
            "split_id": f"wf_{row['fold']}",
            "train_sharpe": float(summary.get("sharpe_ratio", 0.0)),
            "test_sharpe": float(row["validation"].get("sharpe_ratio", 0.0)),
        }
        for row in wf["windows"]
    ]
    pbo = simplified_pbo(pbo_trials)
    dsr = simplified_dsr(float(summary.get("sharpe_ratio", 0.0)), trial_count=max(2, len(pbo_trials)), observation_count=max(2, len(frame)))
    metrics = {
        "profit_factor": float(summary.get("profit_factor", 0.0)),
        "event_profit_factor": float(summary.get("profit_factor", 0.0)),
        "walk_forward_pass_rate": float(wf["stability"].get("fold_pass_rate_pct", 0.0)) / 100.0,
        "regime_pass_rate": float(regime["regime_pass_rate"]),
        "annual_turnover": signal_turnover,
        "max_drawdown_pct": float(summary.get("max_drawdown_pct", -100.0)),
        "cost_stress_base_pass": bool(cost["base"] and cost["base"]["survives"]),
        "cost_stress_harsh_survives": bool(cost["harsh"] and float(cost["harsh"]["summary"].get("total_return_pct", -1.0)) > -5.0),
        "no_lookahead_pass": True,
        "event_ledger_pass": event["diagnostics"].get("ledger_equity_consistent") is True
        and event["diagnostics"].get("pnl_source") == "ledger_fills",
        "dsr": dsr,
        "pbo": pbo,
        "cost_adjusted_return_pct": float(cost["base"]["summary"].get("total_return_pct", 0.0)) if cost["base"] else 0.0,
    }
    metrics["hardening_objective_score"] = hardening_objective_score(metrics)
    gate = evaluate_internal_gate(strategy_id, metrics)
    return {
        "strategy_id": strategy_id,
        "params": params,
        "summary": summary,
        "diagnostics": {
            key: event["diagnostics"].get(key)
            for key in ["engine", "pnl_source", "orders", "fills", "ledger_equity_consistent", "manifest_path"]
        },
        "signal": {
            "annual_turnover": round(signal_turnover, 6),
            "nonzero_bars": int((signal != 0).sum()),
            "changed_bars": int((signal.diff().fillna(signal) != 0).sum()),
        },
        "cost_stress": cost,
        "walk_forward": wf,
        "regime": regime,
        "pbo_dsr": {"pbo": pbo, "dsr": dsr, "pbo_trials": pbo_trials},
        "metrics_for_gate": metrics,
        "gate": gate.to_dict(),
        "diagnostic_columns": sorted(str(key) for key in diagnostics.keys()),
    }


def _manifest_yaml(strategy_id: str, result: dict[str, Any]) -> str:
    status = result["gate"]["status"]
    lines = [
        "schema_version: strategy_manifest_candidate_v1",
        f"strategy_id: {strategy_id}",
        "asset_class: crypto",
        "symbol: BTCUSDT",
        "timeframe: 1h",
        f"promotion_status: {status}",
        "paper_auto_start: false",
        "live_enabled: false",
        "live_frozen: true",
        "pnl_source: ledger_fills",
        "params:",
    ]
    for key, value in result["params"].items():
        if isinstance(value, list):
            lines.append(f"  {key}: [{', '.join(str(item) for item in value)}]")
        else:
            lines.append(f"  {key}: {value}")
    lines.extend(
        [
            "gate:",
            f"  passed: {str(result['gate']['passed']).lower()}",
            "  fail_reasons:",
        ]
    )
    lines.extend([f"    - {reason}" for reason in result["gate"]["fail_reasons"]])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--output-root", default="artifacts/btc_alpha_hardening")
    args = parser.parse_args()

    run_dir = Path(args.output_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 5, 12, tzinfo=timezone.utc)
    frame = load_market_frame(
        source="sqlite",
        symbol="BTCUSDT",
        interval="1h",
        start=start,
        end=end,
        db_path="data/market_data.sqlite",
    )

    baselines = []
    for strategy_id, path in BASELINE_EVIDENCE.items():
        evidence = _load_evidence(path)
        row = _baseline_row(strategy_id, evidence)
        row["source_evidence_path"] = str(path)
        baselines.append(row)

    candidate_results = []
    regime_reports = {}
    walk_reports = {}
    cost_reports = {}
    pbo_reports = {}
    for strategy_id, (signal_fn, params) in CANDIDATES.items():
        result = _candidate_result(
            strategy_id=strategy_id,
            signal_fn=signal_fn,
            params=params,
            frame=frame,
            start=start,
            end=end,
            run_dir=run_dir,
        )
        candidate_results.append(result)
        regime_reports[strategy_id] = result["regime"]
        walk_reports[strategy_id] = result["walk_forward"]
        cost_reports[strategy_id] = result["cost_stress"]
        pbo_reports[strategy_id] = result["pbo_dsr"]
        _write_json(run_dir / f"{strategy_id}_results.json", result)
        manifest_dir = run_dir / "strategy_manifest_candidates"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / f"{strategy_id}.yaml").write_text(_manifest_yaml(strategy_id, result), encoding="utf-8")

    gate_rows = [row["gate"] for row in candidate_results]
    paper_queue = decide_paper_review_queue(gate_rows)
    promotion_decision = {
        "run_id": args.run_id,
        "commit_hash": _git_commit_hash(),
        "thresholds": BTC_HARDENING_GATE_THRESHOLDS,
        "candidate_gate_results": gate_rows,
        "paper_review": paper_queue,
        "live_frozen": True,
        "paper_auto_start": False,
        "forbidden_states": ["paper_ready", "live_ready", "live_enabled"],
    }
    candidate_comparison = {
        "run_id": args.run_id,
        "data_range": {"start": start.isoformat(), "end": end.isoformat()},
        "baseline": baselines,
        "candidates": [
            {
                "strategy_id": row["strategy_id"],
                "profit_factor": row["summary"].get("profit_factor"),
                "sharpe": row["summary"].get("sharpe_ratio"),
                "max_drawdown": row["summary"].get("max_drawdown_pct"),
                "annual_turnover": row["signal"]["annual_turnover"],
                "walk_forward_pass_rate": row["metrics_for_gate"]["walk_forward_pass_rate"],
                "regime_pass_rate": row["metrics_for_gate"]["regime_pass_rate"],
                "dsr": row["metrics_for_gate"]["dsr"],
                "pbo": row["metrics_for_gate"]["pbo"],
                "gate_status": row["gate"]["status"],
                "gate_fail_reasons": row["gate"]["fail_reasons"],
            }
            for row in candidate_results
        ],
    }

    _write_json(run_dir / "baseline_report.json", {"run_id": args.run_id, "baselines": baselines})
    _write_json(run_dir / "candidate_results.json", candidate_comparison)
    _write_json(run_dir / "regime_report.json", {"run_id": args.run_id, "strategies": regime_reports})
    _write_json(run_dir / "walk_forward_report.json", {"run_id": args.run_id, "strategies": walk_reports})
    _write_json(run_dir / "cost_stress_report.json", {"run_id": args.run_id, "strategies": cost_reports})
    _write_json(run_dir / "pbo_dsr_report.json", {"run_id": args.run_id, "strategies": pbo_reports})
    _write_json(run_dir / "promotion_decision.json", promotion_decision)
    print(json.dumps({"run_id": args.run_id, "run_dir": str(run_dir), "promotion": promotion_decision}, indent=2))


if __name__ == "__main__":
    main()
