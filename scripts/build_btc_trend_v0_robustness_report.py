#!/usr/bin/env python3
"""Build BTC trend v0 robustness report and position ledger."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_btc_only_trend_v0_report import _load_daily_bars  # noqa: E402


SCHEMA_VERSION = "btc_trend_v0_robustness_report_v1"
SYMBOL = "BTCUSDT"
DEFAULT_BUNDLE_DIR = Path("data/external/btc_spot/okx/bundles/btc_okx_spot_btcusdt_daily_5y_v1")
DEFAULT_FORMAL_REPORT = Path("artifacts/btc_trend_v0/latest/btc_only_trend_v0_formal_report.json")
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_robustness_report.json")
DEFAULT_LEDGER_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_position_ledger.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC-only 趋势 v0 稳健性审计.md")

FORMAL_STRATEGY_IDS = [
    "buy_hold_btc",
    "fixed_50pct_btc",
    "ma120_200_trend_intended",
    "ma120_200_trend_vol_target_intended",
    "twelve_month_momentum_intended",
]
CANDIDATE_IDS = [
    "ma120_200_trend_intended",
    "ma120_200_trend_vol_target_intended",
    "twelve_month_momentum_intended",
]
COST_BPS_GRID = [0.0, 5.0, 10.0, 25.0]
DELAY_DAYS_GRID = [1, 2, 3]
MA_FAST_GRID = [100, 120, 150]
MA_SLOW_GRID = [180, 200, 240]
MOMENTUM_WINDOW_GRID = [300, 365, 420]
VOL_WINDOW_GRID = [14, 20, 30]
TARGET_VOL_GRID = [0.15, 0.25, 0.35]
MIN_LONG_HISTORY_ROWS = 1095


def build_btc_trend_v0_robustness_report(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    formal_report: Path = DEFAULT_FORMAL_REPORT,
    output: Path = DEFAULT_OUTPUT,
    ledger_output: Path = DEFAULT_LEDGER_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    initial_capital: float = 25_000.0,
    default_cost_bps: float = 5.0,
    default_delay_days: int = 1,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    bundle_abs = _resolve(root, bundle_dir)
    output_abs = _resolve(root, output)
    ledger_abs = _resolve(root, ledger_output)
    markdown_abs = _resolve(root, markdown_output)
    formal_abs = _resolve(root, formal_report)
    daily = _load_daily_bars(bundle_abs)
    rows = int(len(daily))
    formal_payload = _read_json(formal_abs)

    parameters = {
        "minimum_daily_rows": MIN_LONG_HISTORY_ROWS,
        "default_cost_bps": float(default_cost_bps),
        "default_delay_days": int(default_delay_days),
        "cost_bps_grid": COST_BPS_GRID,
        "delay_days_grid": DELAY_DAYS_GRID,
        "ma_fast_grid": MA_FAST_GRID,
        "ma_slow_grid": MA_SLOW_GRID,
        "momentum_window_grid": MOMENTUM_WINDOW_GRID,
        "vol_window_grid": VOL_WINDOW_GRID,
        "target_vol_grid": TARGET_VOL_GRID,
    }
    if rows < MIN_LONG_HISTORY_ROWS:
        _write_csv(ledger_abs, _ledger_fieldnames(), [])
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated,
            "status": "insufficient_history",
            "asset": "btc",
            "symbol": SYMBOL,
            "bundle_dir": _relpath(bundle_abs, root),
            "formal_report": _relpath(formal_abs, root),
            "data": _data_section(daily),
            "parameters": parameters,
            "guardrails": _guardrails(),
            "formal_strategy_ids": FORMAL_STRATEGY_IDS,
            "proxy_strategy_ids_excluded_from_promotion": ["ma20_60_timing_proxy", "btc_trend_v0_proxy_vol_target"],
            "position_ledger": {"path": _relpath(ledger_abs, root), "row_count": 0, "complete": False},
            "candidate_ranking": [],
            "blockers": ["btc_trend_v0_robustness_requires_at_least_1095_daily_rows"],
        }
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    close = daily["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    benchmark_default = _evaluate_named_strategy(
        "buy_hold_btc",
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    default_results = [
        _evaluate_named_strategy(
            strategy_id,
            close=close,
            returns=returns,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for strategy_id in FORMAL_STRATEGY_IDS
    ]
    yearly_rows = _yearly_performance_rows(
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    cost_stress = _cost_stress_rows(
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        delay_days=default_delay_days,
    )
    delay_stress = _delay_stress_rows(
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
    )
    parameter_matrix = _parameter_matrix_rows(
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    ledger_rows = _position_ledger_rows(
        close=close,
        returns=returns,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    _write_csv(ledger_abs, _ledger_fieldnames(), ledger_rows)
    ranking = _candidate_ranking(
        default_results=default_results,
        yearly_rows=yearly_rows,
        cost_stress=cost_stress,
        buy_hold_metrics=_mapping(benchmark_default.get("metrics")),
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "research_only",
        "decision": "robustness_audit_complete_no_direct_promotion",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "formal_report": _relpath(formal_abs, root),
        "formal_report_status": str(formal_payload.get("status", "")) if formal_payload else "",
        "data": _data_section(daily),
        "parameters": parameters,
        "guardrails": _guardrails(),
        "formal_strategy_ids": FORMAL_STRATEGY_IDS,
        "candidate_strategy_ids": CANDIDATE_IDS,
        "proxy_strategy_ids_excluded_from_promotion": ["ma20_60_timing_proxy", "btc_trend_v0_proxy_vol_target"],
        "default_performance": default_results,
        "yearly_performance": yearly_rows,
        "cost_stress": cost_stress,
        "delay_stress": delay_stress,
        "parameter_matrix": parameter_matrix,
        "parameter_matrix_summary": _parameter_matrix_summary(parameter_matrix),
        "position_ledger": {
            "path": _relpath(ledger_abs, root),
            "row_count": len(ledger_rows),
            "complete": _ledger_complete(ledger_rows),
            "delay_rule": "signal generated at T is effective no earlier than T+1",
        },
        "candidate_ranking": ranking,
        "paper_candidate_ready": False,
        "promotion_allowed": False,
        "blockers": [],
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _evaluate_named_strategy(
    strategy_id: str,
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
    ma_fast: int = 120,
    ma_slow: int = 200,
    momentum_window: int = 365,
    vol_window: int = 20,
    target_vol: float = 0.25,
) -> dict[str, Any]:
    raw = _raw_signal(
        strategy_id,
        close=close,
        returns=returns,
        ma_fast=ma_fast,
        ma_slow=ma_slow,
        momentum_window=momentum_window,
        vol_window=vol_window,
        target_vol=target_vol,
    )
    exposure = _effective_exposure(raw, delay_days=delay_days)
    metrics = _evaluate_exposure(
        returns=returns,
        exposure=exposure,
        cost_bps=cost_bps,
        initial_capital=initial_capital,
    )
    return {
        "strategy_id": strategy_id,
        "label": _strategy_label(strategy_id),
        "status": "ready",
        "params": {
            "ma_fast": ma_fast if "ma120_200" in strategy_id else None,
            "ma_slow": ma_slow if "ma120_200" in strategy_id else None,
            "momentum_window": momentum_window if strategy_id == "twelve_month_momentum_intended" else None,
            "vol_window": vol_window if strategy_id == "ma120_200_trend_vol_target_intended" else None,
            "target_vol": target_vol if strategy_id == "ma120_200_trend_vol_target_intended" else None,
            "delay_days": delay_days,
            "cost_bps": cost_bps,
        },
        "metrics": metrics["metrics"],
        "exposure": metrics["exposure"],
    }


def _raw_signal(
    strategy_id: str,
    *,
    close: pd.Series,
    returns: pd.Series,
    ma_fast: int,
    ma_slow: int,
    momentum_window: int,
    vol_window: int,
    target_vol: float,
) -> pd.Series:
    if strategy_id == "buy_hold_btc":
        return pd.Series(1.0, index=close.index)
    if strategy_id == "fixed_50pct_btc":
        return pd.Series(0.5, index=close.index)
    if strategy_id == "ma120_200_trend_intended":
        return ((close.rolling(ma_fast).mean() > close.rolling(ma_slow).mean()) & (close > close.rolling(ma_slow).mean())).astype(float)
    if strategy_id == "ma120_200_trend_vol_target_intended":
        trend = ((close.rolling(ma_fast).mean() > close.rolling(ma_slow).mean()) & (close > close.rolling(ma_slow).mean())).astype(float)
        realized_vol = returns.rolling(vol_window).std(ddof=0) * math.sqrt(365.0)
        scalar = (target_vol / realized_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
        return (trend * scalar).clip(0.0, 1.0)
    if strategy_id == "twelve_month_momentum_intended":
        return (close.pct_change(momentum_window) > 0.0).astype(float)
    raise ValueError(f"Unsupported BTC trend v0 strategy_id: {strategy_id}")


def _effective_exposure(raw_signal: pd.Series, *, delay_days: int) -> pd.Series:
    return raw_signal.shift(int(delay_days)).fillna(0.0).clip(0.0, 1.0)


def _evaluate_exposure(
    *,
    returns: pd.Series,
    exposure: pd.Series,
    cost_bps: float,
    initial_capital: float,
) -> dict[str, Any]:
    exposure = exposure.reindex(returns.index).fillna(0.0).clip(0.0, 1.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    return {
        "returns": strategy_returns,
        "equity": equity,
        "turnover": turnover,
        "metrics": _performance(strategy_returns, equity),
        "exposure": {
            "average_exposure": round(float(exposure.mean()), 6) if len(exposure) else 0.0,
            "max_exposure": round(float(exposure.max()), 6) if len(exposure) else 0.0,
            "days_with_exposure": int((exposure > 0.0).sum()),
            "turnover": round(float(turnover.sum()), 6),
        },
    }


def _performance(returns: pd.Series, equity: pd.Series) -> dict[str, Any]:
    if returns.empty or equity.empty:
        return {
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_abs_pct": 0.0,
            "final_equity": 0.0,
        }
    first = float(equity.iloc[0])
    total_return = float(equity.iloc[-1] / first - 1.0) if first else 0.0
    days = max(1, int((equity.index.max() - equity.index.min()).days))
    annual_return = (1.0 + total_return) ** (365.0 / days) - 1.0 if total_return > -1.0 else -1.0
    std = float(returns.std(ddof=0))
    annual_vol = std * math.sqrt(365.0)
    sharpe = float(returns.mean() / std * math.sqrt(365.0)) if std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    return {
        "total_return_pct": round(total_return * 100.0, 6),
        "annual_return_pct": round(annual_return * 100.0, 6),
        "annual_volatility_pct": round(annual_vol * 100.0, 6),
        "sharpe_ratio": round(sharpe, 6),
        "max_drawdown_pct": round(max_drawdown * 100.0, 6),
        "max_drawdown_abs_pct": round(abs(max_drawdown) * 100.0, 6),
        "final_equity": round(float(equity.iloc[-1]), 6),
    }


def _yearly_performance_rows(
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    raw_by_strategy = {
        strategy_id: _raw_signal(
            strategy_id,
            close=close,
            returns=returns,
            ma_fast=120,
            ma_slow=200,
            momentum_window=365,
            vol_window=20,
            target_vol=0.25,
        )
        for strategy_id in FORMAL_STRATEGY_IDS
    }
    strategy_returns: dict[str, pd.Series] = {}
    for strategy_id, raw in raw_by_strategy.items():
        exposure = _effective_exposure(raw, delay_days=delay_days)
        result = _evaluate_exposure(
            returns=returns,
            exposure=exposure,
            cost_bps=cost_bps,
            initial_capital=initial_capital,
        )
        strategy_returns[strategy_id] = result["returns"]
    rows: list[dict[str, Any]] = []
    years = sorted(set(int(ts.year) for ts in returns.index))
    for year in years:
        mask = returns.index.year == year
        if int(mask.sum()) <= 0:
            continue
        buy_hold_metrics = _metrics_for_period(strategy_returns["buy_hold_btc"][mask], initial_capital)
        for strategy_id in FORMAL_STRATEGY_IDS:
            metrics = _metrics_for_period(strategy_returns[strategy_id][mask], initial_capital)
            acceptable = (
                strategy_id not in CANDIDATE_IDS
                or (
                    float(metrics["total_return_pct"]) >= -20.0
                    and float(metrics["max_drawdown_abs_pct"]) <= float(buy_hold_metrics["max_drawdown_abs_pct"]) + 1e-9
                )
            )
            rows.append(
                {
                    "year": int(year),
                    "segment": f"{year} partial" if int(mask.sum()) < 365 else str(year),
                    "strategy_id": strategy_id,
                    "day_count": int(mask.sum()),
                    "metrics": metrics,
                    "buy_hold_max_drawdown_abs_pct": buy_hold_metrics["max_drawdown_abs_pct"],
                    "acceptable": bool(acceptable),
                }
            )
    return rows


def _metrics_for_period(strategy_returns: pd.Series, initial_capital: float) -> dict[str, Any]:
    equity = float(initial_capital) * (1.0 + strategy_returns.fillna(0.0)).cumprod()
    return _performance(strategy_returns.fillna(0.0), equity)


def _cost_stress_rows(
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows = []
    for strategy_id in FORMAL_STRATEGY_IDS:
        for cost_bps in COST_BPS_GRID:
            evaluated = _evaluate_named_strategy(
                strategy_id,
                close=close,
                returns=returns,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            )
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "cost_bps": cost_bps,
                    "metrics": evaluated["metrics"],
                    "exposure": evaluated["exposure"],
                }
            )
    return rows


def _delay_stress_rows(
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
) -> list[dict[str, Any]]:
    rows = []
    for strategy_id in FORMAL_STRATEGY_IDS:
        for delay_days in DELAY_DAYS_GRID:
            evaluated = _evaluate_named_strategy(
                strategy_id,
                close=close,
                returns=returns,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            )
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "delay_days": delay_days,
                    "metrics": evaluated["metrics"],
                    "exposure": evaluated["exposure"],
                }
            )
    return rows


def _parameter_matrix_rows(
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows = []
    for fast in MA_FAST_GRID:
        for slow in MA_SLOW_GRID:
            if fast >= slow:
                continue
            evaluated = _evaluate_named_strategy(
                "ma120_200_trend_intended",
                close=close,
                returns=returns,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
                ma_fast=fast,
                ma_slow=slow,
            )
            rows.append(_parameter_row(evaluated, ma_fast=fast, ma_slow=slow))
            for vol_window in VOL_WINDOW_GRID:
                for target_vol in TARGET_VOL_GRID:
                    vol_eval = _evaluate_named_strategy(
                        "ma120_200_trend_vol_target_intended",
                        close=close,
                        returns=returns,
                        initial_capital=initial_capital,
                        cost_bps=cost_bps,
                        delay_days=delay_days,
                        ma_fast=fast,
                        ma_slow=slow,
                        vol_window=vol_window,
                        target_vol=target_vol,
                    )
                    rows.append(
                        _parameter_row(
                            vol_eval,
                            ma_fast=fast,
                            ma_slow=slow,
                            vol_window=vol_window,
                            target_vol=target_vol,
                        )
                    )
    for window in MOMENTUM_WINDOW_GRID:
        evaluated = _evaluate_named_strategy(
            "twelve_month_momentum_intended",
            close=close,
            returns=returns,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
            momentum_window=window,
        )
        rows.append(_parameter_row(evaluated, momentum_window=window))
    return rows


def _parameter_row(evaluated: Mapping[str, Any], **params: Any) -> dict[str, Any]:
    return {
        "strategy_id": evaluated.get("strategy_id", ""),
        "params": params,
        "is_default": _is_default_params(str(evaluated.get("strategy_id", "")), params),
        "metrics": _mapping(evaluated.get("metrics")),
        "exposure": _mapping(evaluated.get("exposure")),
    }


def _is_default_params(strategy_id: str, params: Mapping[str, Any]) -> bool:
    if strategy_id == "ma120_200_trend_intended":
        return int(params.get("ma_fast", 0)) == 120 and int(params.get("ma_slow", 0)) == 200
    if strategy_id == "ma120_200_trend_vol_target_intended":
        return (
            int(params.get("ma_fast", 0)) == 120
            and int(params.get("ma_slow", 0)) == 200
            and int(params.get("vol_window", 0)) == 20
            and abs(float(params.get("target_vol", 0.0)) - 0.25) < 1e-12
        )
    if strategy_id == "twelve_month_momentum_intended":
        return int(params.get("momentum_window", 0)) == 365
    return False


def _parameter_matrix_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_strategy: dict[str, dict[str, Any]] = {}
    for row in rows:
        strategy_id = str(row.get("strategy_id", ""))
        target = by_strategy.setdefault(strategy_id, {"row_count": 0, "default_present": False})
        target["row_count"] += 1
        target["default_present"] = bool(target["default_present"] or row.get("is_default", False))
    return by_strategy


def _position_ledger_rows(
    *,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_id in FORMAL_STRATEGY_IDS:
        raw = _raw_signal(
            strategy_id,
            close=close,
            returns=returns,
            ma_fast=120,
            ma_slow=200,
            momentum_window=365,
            vol_window=20,
            target_vol=0.25,
        )
        exposure = _effective_exposure(raw, delay_days=delay_days)
        evaluated = _evaluate_exposure(
            returns=returns,
            exposure=exposure,
            cost_bps=cost_bps,
            initial_capital=initial_capital,
        )
        turnover = evaluated["turnover"]
        strategy_returns = evaluated["returns"]
        equity = evaluated["equity"]
        index = list(close.index)
        for i, timestamp in enumerate(index):
            source_i = i - delay_days
            source_ts = index[source_i] if source_i >= 0 else None
            raw_value = float(raw.iloc[source_i]) if source_i >= 0 else 0.0
            current_exposure = float(exposure.iloc[i])
            current_turnover = float(turnover.iloc[i])
            rows.append(
                {
                    "timestamp": _timestamp_text(timestamp),
                    "strategy_id": strategy_id,
                    "close": _round_float(close.iloc[i]),
                    "daily_return": _round_float(returns.iloc[i]),
                    "raw_signal": round(raw_value, 10),
                    "signal_timestamp": _timestamp_text(source_ts) if source_ts is not None else "",
                    "effective_timestamp": _timestamp_text(timestamp),
                    "exposure": round(current_exposure, 10),
                    "turnover": round(current_turnover, 10),
                    "cost_bps": float(cost_bps),
                    "strategy_daily_return": round(float(strategy_returns.iloc[i]), 10),
                    "equity": round(float(equity.iloc[i]), 6),
                    "reason": _ledger_reason(source_ts=source_ts, turnover=current_turnover, exposure=current_exposure),
                }
            )
    return rows


def _ledger_reason(*, source_ts: pd.Timestamp | None, turnover: float, exposure: float) -> str:
    if source_ts is None:
        return "warming_up_no_effective_signal"
    if turnover > 1e-12:
        return "exposure_changed_from_prior_effective_signal"
    if exposure > 0.0:
        return "hold_prior_effective_signal"
    return "flat_prior_effective_signal"


def _ledger_complete(rows: list[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    required = set(_ledger_fieldnames())
    for row in rows:
        if required - set(row):
            return False
        if not str(row.get("reason", "")).strip():
            return False
        if float(row.get("exposure", 0.0) or 0.0) > 0.0 and not str(row.get("signal_timestamp", "")).strip():
            return False
    return True


def _candidate_ranking(
    *,
    default_results: list[Mapping[str, Any]],
    yearly_rows: list[Mapping[str, Any]],
    cost_stress: list[Mapping[str, Any]],
    buy_hold_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_default = {str(row.get("strategy_id", "")): _mapping(row) for row in default_results}
    by_cost = {
        (str(row.get("strategy_id", "")), float(row.get("cost_bps", 0.0))): _mapping(row)
        for row in cost_stress
    }
    ranked = []
    for strategy_id in CANDIDATE_IDS:
        default = _mapping(by_default.get(strategy_id))
        metrics = _mapping(default.get("metrics"))
        cost_10 = _mapping(_mapping(by_cost.get((strategy_id, 10.0))).get("metrics"))
        acceptable_segments = sum(
            1 for row in yearly_rows if str(row.get("strategy_id", "")) == strategy_id and bool(row.get("acceptable", False))
        )
        drawdown_reduction = float(buy_hold_metrics.get("max_drawdown_abs_pct", 0.0) or 0.0) - float(
            metrics.get("max_drawdown_abs_pct", 0.0) or 0.0
        )
        score = (
            acceptable_segments * 10.0
            + max(0.0, drawdown_reduction)
            + max(0.0, float(cost_10.get("total_return_pct", 0.0) or 0.0)) / 10.0
        )
        ranked.append(
            {
                "strategy_id": strategy_id,
                "rank_score": round(score, 6),
                "acceptable_year_segments": acceptable_segments,
                "default_total_return_pct": metrics.get("total_return_pct", 0.0),
                "default_max_drawdown_abs_pct": metrics.get("max_drawdown_abs_pct", 0.0),
                "cost_10bps_total_return_pct": cost_10.get("total_return_pct", 0.0),
                "drawdown_reduction_vs_buy_hold_pct": round(drawdown_reduction, 6),
                "paper_candidate_ready": False,
            }
        )
    return sorted(ranked, key=lambda row: (-float(row["rank_score"]), str(row["strategy_id"])))


def _data_section(daily: pd.DataFrame) -> dict[str, Any]:
    return {
        "daily_rows": int(len(daily)),
        "start": _timestamp_text(daily.index.min()) if len(daily) else "",
        "end": _timestamp_text(daily.index.max()) if len(daily) else "",
        "source": "OKX public local spot daily bundle",
    }


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_candidate_ready": False,
        "promotion_allowed_by_robustness_report": False,
        "broker_calls_allowed": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "live_order_allowed": False,
        "spot_or_low_leverage_first": True,
        "high_leverage_perpetual_not_allowed_for_v0": True,
        "all_exposures_use_t_plus_1_or_later_signal": True,
    }


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    ranking = [_mapping(row) for row in payload.get("candidate_ranking", []) if isinstance(row, Mapping)]
    lines = [
        "# BTC-only 趋势 v0 稳健性审计",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
    ]
    if payload.get("status") == "insufficient_history":
        lines += [
            f"当前日线行数 {data.get('daily_rows', 0)}，不足 1095 行，不能输出候选排名。",
            "",
            "## 阻断项",
            "",
        ]
        for blocker in payload.get("blockers", []):
            lines.append(f"- {blocker}")
        lines.append("")
        return "\n".join(lines)
    lines += [
        "本报告只做研究审计，不直接允许纸盘或实盘。所有仓位使用 T+1 或更晚信号生效，并写入 position ledger。",
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        "",
        "## 候选排名",
        "",
        "| 策略 | 分数 | 可接受年度段 | 默认收益 | 默认最大回撤 | 10bps收益 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in ranking:
        lines.append(
            f"| {row.get('strategy_id', '')} | {row.get('rank_score', 0)} | "
            f"{row.get('acceptable_year_segments', 0)} | {row.get('default_total_return_pct', 0)}% | "
            f"{row.get('default_max_drawdown_abs_pct', 0)}% | {row.get('cost_10bps_total_return_pct', 0)}% |"
        )
    lines += [
        "",
        "## 输出",
        "",
        f"- position ledger：`{_mapping(payload.get('position_ledger')).get('path', '')}`",
        "- promotion gate 需要单独读取本报告后判断，当前报告不直接晋级候选。",
        "",
    ]
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_csv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _ledger_fieldnames() -> list[str]:
    return [
        "timestamp",
        "strategy_id",
        "close",
        "daily_return",
        "raw_signal",
        "signal_timestamp",
        "effective_timestamp",
        "exposure",
        "turnover",
        "cost_bps",
        "strategy_daily_return",
        "equity",
        "reason",
    ]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _timestamp_text(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.isoformat().replace("+00:00", "Z")


def _round_float(value: object) -> float:
    try:
        return round(float(value), 10)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _strategy_label(strategy_id: str) -> str:
    return {
        "buy_hold_btc": "Buy and hold BTC",
        "fixed_50pct_btc": "Fixed 50% BTC exposure",
        "ma120_200_trend_intended": "MA120/200 daily trend timing",
        "ma120_200_trend_vol_target_intended": "MA120/200 trend + volatility-targeted exposure",
        "twelve_month_momentum_intended": "12-month BTC momentum timing",
    }.get(strategy_id, strategy_id)


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC trend v0 robustness report and position ledger.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--formal-report", default=str(DEFAULT_FORMAL_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--ledger-output", default=str(DEFAULT_LEDGER_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--default-cost-bps", type=float, default=5.0)
    parser.add_argument("--default-delay-days", type=int, default=1)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_v0_robustness_report(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        formal_report=Path(args.formal_report),
        output=Path(args.output),
        ledger_output=Path(args.ledger_output),
        markdown_output=Path(args.markdown_output),
        initial_capital=args.initial_capital,
        default_cost_bps=args.default_cost_bps,
        default_delay_days=args.default_delay_days,
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
