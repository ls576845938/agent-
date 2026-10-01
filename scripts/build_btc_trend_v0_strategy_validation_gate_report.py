#!/usr/bin/env python3
"""Build BTC trend v0 strategy validation gate report.

This gate is intentionally separate from the paper runner readiness gate.
It evaluates whether the selected strategy has enough backtest evidence to
support a strategy-quality claim. It never unlocks live trading.
"""

from __future__ import annotations

import argparse
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
from scripts.build_btc_trend_v0_promotion_gate_report import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_PAPER_GATE,
)
from scripts.build_btc_trend_v0_robustness_report import (  # noqa: E402
    COST_BPS_GRID,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_FORMAL_REPORT,
    DEFAULT_OUTPUT as DEFAULT_ROBUSTNESS_REPORT,
    MA_FAST_GRID,
    MA_SLOW_GRID,
    MIN_LONG_HISTORY_ROWS,
    MOMENTUM_WINDOW_GRID,
    TARGET_VOL_GRID,
    VOL_WINDOW_GRID,
    _effective_exposure,
    _evaluate_exposure,
    _raw_signal,
)


SCHEMA_VERSION = "btc_trend_v0_strategy_validation_gate_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_v0_strategy_validation_gate_report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC-only 趋势 v0 策略验证门槛.md")
DEFAULT_SELECTED_CANDIDATE = "twelve_month_momentum_intended"
SYMBOL = "BTCUSDT"


def build_btc_trend_v0_strategy_validation_gate_report(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    formal_report: Path = DEFAULT_FORMAL_REPORT,
    robustness_report: Path = DEFAULT_ROBUSTNESS_REPORT,
    paper_gate: Path = DEFAULT_PAPER_GATE,
    output: Path = DEFAULT_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    selected_candidate: str = DEFAULT_SELECTED_CANDIDATE,
    initial_capital: float = 25_000.0,
    cost_bps: float = 5.0,
    delay_days: int = 1,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    bundle_abs = _resolve(root, bundle_dir)
    formal_abs = _resolve(root, formal_report)
    robustness_abs = _resolve(root, robustness_report)
    paper_gate_abs = _resolve(root, paper_gate)
    output_abs = _resolve(root, output)
    markdown_abs = _resolve(root, markdown_output)

    formal = _read_json(formal_abs)
    robustness = _read_json(robustness_abs)
    paper = _read_json(paper_gate_abs)
    daily = _load_daily_bars(bundle_abs)
    row_count = int(len(daily))
    blockers: list[str] = []

    if row_count < MIN_LONG_HISTORY_ROWS:
        blockers.append("btc_trend_strategy_validation_daily_rows_below_1095")
    if str(formal.get("status", "")) != "research_ready":
        blockers.append("btc_trend_formal_backtest_not_research_ready")
    if str(robustness.get("status", "")) not in {"research_only", "insufficient_history"}:
        blockers.append("btc_trend_robustness_report_unexpected_status")

    for source_name, source in [("formal", formal), ("robustness", robustness), ("paper_gate", paper)]:
        guardrails = _mapping(source.get("guardrails"))
        if bool(guardrails.get("private_endpoint_used", False)):
            blockers.append(f"btc_trend_{source_name}_private_endpoint_used")
        if bool(guardrails.get("order_endpoint_used", False)):
            blockers.append(f"btc_trend_{source_name}_order_endpoint_used")
        if bool(guardrails.get("broker_calls_allowed", False)):
            blockers.append(f"btc_trend_{source_name}_broker_calls_allowed")

    if daily.empty:
        blockers.append("btc_trend_strategy_validation_daily_bundle_empty")
        close = pd.Series(dtype=float)
        returns = pd.Series(dtype=float)
    else:
        close = daily["close"].astype(float)
        returns = close.pct_change().fillna(0.0)

    selected_metrics = {}
    buy_hold_metrics = {}
    walk_forward = {"folds": [], "summary": _empty_walk_forward_summary()}
    regime = {"segments": [], "summary": _empty_regime_summary()}
    parameter_stability = {"rows": [], "summary": _empty_parameter_summary()}
    cost_stress = {"rows": [], "summary": _empty_cost_summary()}
    extreme_year = _empty_extreme_year_summary()

    if not blockers:
        selected_eval = _evaluate_variant(
            selected_candidate,
            close=close,
            returns=returns,
            params=_default_params(selected_candidate),
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        buy_hold_eval = _evaluate_variant(
            "buy_hold_btc",
            close=close,
            returns=returns,
            params=_default_params("buy_hold_btc"),
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        selected_metrics = _mapping(selected_eval.get("metrics"))
        buy_hold_metrics = _mapping(buy_hold_eval.get("metrics"))
        walk_forward = _walk_forward_validation(
            selected_candidate=selected_candidate,
            close=close,
            returns=returns,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        regime = _regime_validation(
            selected_candidate=selected_candidate,
            close=close,
            returns=returns,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        parameter_stability = _parameter_stability(
            selected_candidate=selected_candidate,
            close=close,
            returns=returns,
            buy_hold_metrics=buy_hold_metrics,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        cost_stress = _cost_stress_validation(
            selected_candidate=selected_candidate,
            close=close,
            returns=returns,
            buy_hold_metrics=buy_hold_metrics,
            initial_capital=initial_capital,
            delay_days=delay_days,
        )
        extreme_year = _extreme_year_contribution(_mapping(regime.get("summary")), regime.get("segments", []))

    checks = {
        "long_history": row_count >= MIN_LONG_HISTORY_ROWS,
        "formal_backtest_research_ready": str(formal.get("status", "")) == "research_ready",
        "walk_forward_enough_folds": int(_mapping(walk_forward.get("summary")).get("fold_count", 0)) >= 3,
        "walk_forward_acceptance": bool(_mapping(walk_forward.get("summary")).get("pass", False)),
        "regime_segment_acceptance": bool(_mapping(regime.get("summary")).get("pass", False)),
        "parameter_stability": bool(_mapping(parameter_stability.get("summary")).get("pass", False)),
        "cost_stress": bool(_mapping(cost_stress.get("summary")).get("pass", False)),
        "extreme_year_dependency": bool(extreme_year.get("pass", False)),
        "no_private_or_order_endpoint": not any(
            item.endswith("_private_endpoint_used") or item.endswith("_order_endpoint_used") for item in blockers
        ),
    }
    strategy_validation_passed = not blockers and all(checks.values())
    if blockers:
        status = "strategy_validation_rejected"
    elif strategy_validation_passed:
        status = "strategy_backtest_validated"
    else:
        status = "strategy_validation_research_only"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "gate_type": "strategy_backtest_validation_gate",
        "status": status,
        "decision": _decision_text(status),
        "asset": "btc",
        "symbol": SYMBOL,
        "selected_candidate": selected_candidate,
        "strategy_validation_passed": bool(strategy_validation_passed),
        "paper_runner_observation_allowed": bool(str(paper.get("status", "")) == "paper_candidate_ready"),
        "paper_gate_status": str(paper.get("status", "")),
        "paper_gate_type": str(paper.get("gate_type", "")),
        "paper_candidate_ready_is_strategy_validation": False,
        "formal_report": _relpath(formal_abs, root),
        "robustness_report": _relpath(robustness_abs, root),
        "paper_gate": _relpath(paper_gate_abs, root),
        "bundle_dir": _relpath(bundle_abs, root),
        "data": {
            "daily_rows": row_count,
            "start": _timestamp_text(daily.index.min()) if row_count else "",
            "end": _timestamp_text(daily.index.max()) if row_count else "",
            "source": "OKX public local spot daily bundle",
        },
        "parameters": {
            "selected_candidate": selected_candidate,
            "default_cost_bps": float(cost_bps),
            "default_delay_days": int(delay_days),
            "walk_forward_train_days": 1095,
            "walk_forward_test_days": 180,
            "walk_forward_step_days": 180,
            "cost_bps_grid": COST_BPS_GRID,
            "parameter_neighborhood": _strategy_param_variants(selected_candidate),
        },
        "selected_metrics": selected_metrics,
        "buy_hold_metrics": buy_hold_metrics,
        "checks": checks,
        "walk_forward": walk_forward,
        "regime_validation": regime,
        "parameter_stability": parameter_stability,
        "cost_stress": cost_stress,
        "extreme_year_contribution": extreme_year,
        "guardrails": {
            "this_gate_does_not_unlock_paper_runner": True,
            "this_gate_does_not_unlock_live_trading": True,
            "live_order_allowed": False,
            "broker_calls_allowed": False,
            "private_endpoint_used": False,
            "order_endpoint_used": False,
            "manual_review_required_before_any_live_use": True,
        },
        "blockers": _dedupe(blockers),
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _walk_forward_validation(
    *,
    selected_candidate: str,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
    train_days: int = 1095,
    test_days: int = 180,
    step_days: int = 180,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    variants = _strategy_param_variants(selected_candidate)
    n = int(len(close))
    fold_id = 1
    test_start = int(train_days)
    while test_start < n:
        test_end = min(test_start + int(test_days), n)
        if test_end - test_start < 90:
            break
        train_start = max(0, test_start - int(train_days))
        train_index = close.index[train_start:test_start]
        test_index = close.index[test_start:test_end]
        if len(train_index) < 365 or len(test_index) < 90:
            test_start += int(step_days)
            continue
        evaluated = []
        for params in variants:
            result = _evaluate_variant(
                selected_candidate,
                close=close,
                returns=returns,
                params=params,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            )
            exposure = result["exposure_series"]
            train_metrics = _metrics_for_period(
                returns=returns.loc[train_index],
                exposure=exposure.loc[train_index],
                initial_capital=initial_capital,
                cost_bps=cost_bps,
            )
            test_metrics = _metrics_for_period(
                returns=returns.loc[test_index],
                exposure=exposure.loc[test_index],
                initial_capital=initial_capital,
                cost_bps=cost_bps,
            )
            evaluated.append({"params": params, "train_metrics": train_metrics, "test_metrics": test_metrics})
        best_train = max(evaluated, key=lambda row: _score(_mapping(row.get("train_metrics"))))
        default_params = _default_params(selected_candidate)
        default_eval = next((row for row in evaluated if row.get("params") == default_params), evaluated[0])
        buy_hold = _evaluate_variant(
            "buy_hold_btc",
            close=close,
            returns=returns,
            params=_default_params("buy_hold_btc"),
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        buy_hold_test_metrics = _metrics_for_period(
            returns=returns.loc[test_index],
            exposure=buy_hold["exposure_series"].loc[test_index],
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        default_test = _mapping(default_eval.get("test_metrics"))
        acceptable = (
            _float_metric(default_test, "total_return_pct", 0.0) >= -20.0
            and _float_metric(default_test, "max_drawdown_abs_pct", 999.0)
            <= _float_metric(buy_hold_test_metrics, "max_drawdown_abs_pct", 0.0) + 5.0
        )
        rows.append(
            {
                "fold_id": fold_id,
                "train_start": _timestamp_text(train_index.min()),
                "train_end": _timestamp_text(train_index.max()),
                "test_start": _timestamp_text(test_index.min()),
                "test_end": _timestamp_text(test_index.max()),
                "train_selected_params": best_train.get("params", {}),
                "default_params": default_params,
                "default_test_metrics": default_test,
                "train_best_test_metrics": _mapping(best_train.get("test_metrics")),
                "buy_hold_test_metrics": buy_hold_test_metrics,
                "acceptable": bool(acceptable),
            }
        )
        fold_id += 1
        test_start += int(step_days)
    fold_count = len(rows)
    acceptable_count = sum(1 for row in rows if row.get("acceptable"))
    positive_count = sum(
        1 for row in rows if _float_metric(_mapping(row.get("default_test_metrics")), "total_return_pct", 0.0) > 0.0
    )
    summary = {
        "fold_count": fold_count,
        "acceptable_fold_count": acceptable_count,
        "positive_fold_count": positive_count,
        "minimum_required_folds": 3,
        "minimum_acceptable_folds": max(2, math.ceil(fold_count * 0.5)) if fold_count else 2,
        "pass": bool(fold_count >= 3 and acceptable_count >= max(2, math.ceil(fold_count * 0.5))),
    }
    return {"folds": rows, "summary": summary}


def _regime_validation(
    *,
    selected_candidate: str,
    close: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> dict[str, Any]:
    selected = _evaluate_variant(
        selected_candidate,
        close=close,
        returns=returns,
        params=_default_params(selected_candidate),
        initial_capital=initial_capital,
        cost_bps=cost_bps,
        delay_days=delay_days,
    )
    buy_hold = _evaluate_variant(
        "buy_hold_btc",
        close=close,
        returns=returns,
        params=_default_params("buy_hold_btc"),
        initial_capital=initial_capital,
        cost_bps=cost_bps,
        delay_days=delay_days,
    )
    selected_exposure = selected["exposure_series"]
    buy_hold_exposure = buy_hold["exposure_series"]
    rows = []
    for year in sorted({int(ts.year) for ts in returns.index}):
        mask = returns.index.year == year
        if int(mask.sum()) < 60:
            continue
        year_index = returns.index[mask]
        selected_metrics = _metrics_for_period(
            returns=returns.loc[year_index],
            exposure=selected_exposure.loc[year_index],
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        buy_hold_metrics = _metrics_for_period(
            returns=returns.loc[year_index],
            exposure=buy_hold_exposure.loc[year_index],
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        buy_hold_return = float(buy_hold_metrics.get("total_return_pct", 0.0) or 0.0)
        regime = "bull" if buy_hold_return >= 25.0 else ("bear" if buy_hold_return <= -20.0 else "sideways")
        acceptable = (
            _float_metric(selected_metrics, "total_return_pct", 0.0) >= -20.0
            and _float_metric(selected_metrics, "max_drawdown_abs_pct", 999.0)
            <= _float_metric(buy_hold_metrics, "max_drawdown_abs_pct", 0.0) + 5.0
        )
        rows.append(
            {
                "year": year,
                "segment": f"{year} partial" if int(mask.sum()) < 365 else str(year),
                "regime": regime,
                "day_count": int(mask.sum()),
                "selected_metrics": selected_metrics,
                "buy_hold_metrics": buy_hold_metrics,
                "acceptable": bool(acceptable),
            }
        )
    observed_regimes = sorted({str(row.get("regime")) for row in rows})
    acceptable_count = sum(1 for row in rows if row.get("acceptable"))
    summary = {
        "segment_count": len(rows),
        "observed_regimes": observed_regimes,
        "observed_regime_count": len(observed_regimes),
        "acceptable_segment_count": acceptable_count,
        "minimum_acceptable_segments": 4,
        "pass": bool(len(observed_regimes) >= 2 and acceptable_count >= 4),
    }
    return {"segments": rows, "summary": summary}


def _parameter_stability(
    *,
    selected_candidate: str,
    close: pd.Series,
    returns: pd.Series,
    buy_hold_metrics: Mapping[str, Any],
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> dict[str, Any]:
    rows = []
    for params in _strategy_param_variants(selected_candidate):
        result = _evaluate_variant(
            selected_candidate,
            close=close,
            returns=returns,
            params=params,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
            delay_days=delay_days,
        )
        metrics = _mapping(result.get("metrics"))
        rows.append(
            {
                "params": params,
                "is_default": params == _default_params(selected_candidate),
                "metrics": metrics,
                "positive_total_return": _float_metric(metrics, "total_return_pct", 0.0) > 0.0,
                "drawdown_below_buy_hold": _float_metric(metrics, "max_drawdown_abs_pct", 999.0)
                < _float_metric(buy_hold_metrics, "max_drawdown_abs_pct", 0.0),
            }
        )
    row_count = len(rows)
    positive_count = sum(1 for row in rows if row.get("positive_total_return"))
    drawdown_count = sum(1 for row in rows if row.get("drawdown_below_buy_hold"))
    default_present = any(row.get("is_default") for row in rows)
    summary = {
        "row_count": row_count,
        "default_present": default_present,
        "positive_total_return_share": round(positive_count / row_count, 6) if row_count else 0.0,
        "drawdown_below_buy_hold_share": round(drawdown_count / row_count, 6) if row_count else 0.0,
        "minimum_share_required": 0.67,
        "pass": bool(
            row_count >= len(_strategy_param_variants(selected_candidate))
            and default_present
            and row_count > 0
            and positive_count / row_count >= 0.67
            and drawdown_count / row_count >= 0.67
        ),
    }
    return {"rows": rows, "summary": summary}


def _cost_stress_validation(
    *,
    selected_candidate: str,
    close: pd.Series,
    returns: pd.Series,
    buy_hold_metrics: Mapping[str, Any],
    initial_capital: float,
    delay_days: int,
) -> dict[str, Any]:
    rows = []
    for cost_bps in COST_BPS_GRID:
        result = _evaluate_variant(
            selected_candidate,
            close=close,
            returns=returns,
            params=_default_params(selected_candidate),
            initial_capital=initial_capital,
            cost_bps=float(cost_bps),
            delay_days=delay_days,
        )
        rows.append({"cost_bps": float(cost_bps), "metrics": _mapping(result.get("metrics"))})
    by_cost = {float(row["cost_bps"]): _mapping(row.get("metrics")) for row in rows}
    cost_10 = _mapping(by_cost.get(10.0))
    cost_25 = _mapping(by_cost.get(25.0))
    summary = {
        "tested_cost_bps": sorted(by_cost),
        "cost_10bps_total_return_positive": _float_metric(cost_10, "total_return_pct", 0.0) > 0.0,
        "cost_25bps_total_return_positive": _float_metric(cost_25, "total_return_pct", 0.0) > 0.0,
        "cost_25bps_drawdown_below_buy_hold": _float_metric(cost_25, "max_drawdown_abs_pct", 999.0)
        < _float_metric(buy_hold_metrics, "max_drawdown_abs_pct", 0.0),
        "pass": bool(
            set(COST_BPS_GRID).issubset(set(by_cost))
            and _float_metric(cost_10, "total_return_pct", 0.0) > 0.0
            and _float_metric(cost_25, "total_return_pct", 0.0) > 0.0
            and _float_metric(cost_25, "max_drawdown_abs_pct", 999.0)
            < _float_metric(buy_hold_metrics, "max_drawdown_abs_pct", 0.0)
        ),
    }
    return {"rows": rows, "summary": summary}


def _extreme_year_contribution(regime_summary: Mapping[str, Any], segments: object) -> dict[str, Any]:
    rows = [_mapping(row) for row in segments if isinstance(row, Mapping)]
    selected_returns = [
        float(_mapping(row.get("selected_metrics")).get("total_return_pct", 0.0) or 0.0)
        for row in rows
    ]
    positives = [value for value in selected_returns if value > 0.0]
    positive_sum = sum(positives)
    top_positive_share = max(positives) / positive_sum if positive_sum > 0.0 else 1.0
    summary = {
        "positive_segment_count": len(positives),
        "top_positive_segment_share": round(top_positive_share, 6),
        "observed_regime_count": int(regime_summary.get("observed_regime_count", 0) or 0),
        "pass": bool(len(positives) >= 2 and top_positive_share <= 0.75),
    }
    return summary


def _evaluate_variant(
    strategy_id: str,
    *,
    close: pd.Series,
    returns: pd.Series,
    params: Mapping[str, Any],
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> dict[str, Any]:
    merged = _default_params(strategy_id)
    merged.update(dict(params))
    raw = _raw_signal(
        strategy_id,
        close=close,
        returns=returns,
        ma_fast=int(merged.get("ma_fast", 120)),
        ma_slow=int(merged.get("ma_slow", 200)),
        momentum_window=int(merged.get("momentum_window", 365)),
        vol_window=int(merged.get("vol_window", 20)),
        target_vol=float(merged.get("target_vol", 0.25)),
    )
    exposure = _effective_exposure(raw, delay_days=delay_days)
    result = _evaluate_exposure(
        returns=returns,
        exposure=exposure,
        cost_bps=cost_bps,
        initial_capital=initial_capital,
    )
    return {"metrics": _mapping(result.get("metrics")), "exposure": _mapping(result.get("exposure")), "exposure_series": exposure}


def _metrics_for_period(
    *,
    returns: pd.Series,
    exposure: pd.Series,
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    result = _evaluate_exposure(
        returns=returns.fillna(0.0),
        exposure=exposure.reindex(returns.index).fillna(0.0),
        cost_bps=cost_bps,
        initial_capital=initial_capital,
    )
    return _mapping(result.get("metrics"))


def _strategy_param_variants(strategy_id: str) -> list[dict[str, Any]]:
    if strategy_id == "twelve_month_momentum_intended":
        return [{"momentum_window": int(window)} for window in MOMENTUM_WINDOW_GRID]
    if strategy_id == "ma120_200_trend_intended":
        return [
            {"ma_fast": int(fast), "ma_slow": int(slow)}
            for fast in MA_FAST_GRID
            for slow in MA_SLOW_GRID
            if int(fast) < int(slow)
        ]
    if strategy_id == "ma120_200_trend_vol_target_intended":
        return [
            {
                "ma_fast": int(fast),
                "ma_slow": int(slow),
                "vol_window": int(vol_window),
                "target_vol": float(target_vol),
            }
            for fast in MA_FAST_GRID
            for slow in MA_SLOW_GRID
            if int(fast) < int(slow)
            for vol_window in VOL_WINDOW_GRID
            for target_vol in TARGET_VOL_GRID
        ]
    return [_default_params(strategy_id)]


def _default_params(strategy_id: str) -> dict[str, Any]:
    if strategy_id == "twelve_month_momentum_intended":
        return {"momentum_window": 365}
    if strategy_id == "ma120_200_trend_intended":
        return {"ma_fast": 120, "ma_slow": 200}
    if strategy_id == "ma120_200_trend_vol_target_intended":
        return {"ma_fast": 120, "ma_slow": 200, "vol_window": 20, "target_vol": 0.25}
    return {}


def _score(metrics: Mapping[str, Any]) -> float:
    total = float(metrics.get("total_return_pct", 0.0) or 0.0)
    drawdown = float(metrics.get("max_drawdown_abs_pct", 0.0) or 0.0)
    return total - drawdown


def _decision_text(status: str) -> str:
    if status == "strategy_backtest_validated":
        return "backtest_evidence_passed_internal_gate_manual_review_still_required"
    if status == "strategy_validation_rejected":
        return "backtest_evidence_rejected_or_incomplete"
    return "backtest_evidence_requires_more_research"


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    checks = _mapping(payload.get("checks"))
    wf = _mapping(_mapping(payload.get("walk_forward")).get("summary"))
    regime = _mapping(_mapping(payload.get("regime_validation")).get("summary"))
    parameter = _mapping(_mapping(payload.get("parameter_stability")).get("summary"))
    cost = _mapping(_mapping(payload.get("cost_stress")).get("summary"))
    extreme = _mapping(payload.get("extreme_year_contribution"))
    lines = [
        "# BTC-only 趋势 v0 策略验证门槛",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        f"候选策略：`{payload.get('selected_candidate', '')}`",
        "",
        "这个 gate 只判断回测证据质量，不允许纸盘或实盘。纸盘 runner 的准入仍由独立 paper operational readiness gate 控制。",
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        "",
        "## 检查结果",
        "",
        "| 检查 | 结果 |",
        "| --- | --- |",
    ]
    for key, value in checks.items():
        lines.append(f"| {key} | `{value}` |")
    lines += [
        "",
        "## 核心摘要",
        "",
        f"- Walk-forward：{wf.get('acceptable_fold_count', 0)} / {wf.get('fold_count', 0)} 个 fold 可接受。",
        f"- 牛熊震荡分段：{regime.get('acceptable_segment_count', 0)} / {regime.get('segment_count', 0)} 个年度段可接受。",
        f"- 参数稳定：正收益占比 {parameter.get('positive_total_return_share', 0)}，回撤低于买入持有占比 {parameter.get('drawdown_below_buy_hold_share', 0)}。",
        f"- 成本压力：10bps 正收益 `{cost.get('cost_10bps_total_return_positive', False)}`，25bps 正收益 `{cost.get('cost_25bps_total_return_positive', False)}`。",
        f"- 极端年份依赖：正收益段数量 {extreme.get('positive_segment_count', 0)}，最大正收益段贡献占比 {extreme.get('top_positive_segment_share', 0)}。",
        "",
        "## 限制",
        "",
        "- 通过本 gate 也不代表 live-ready。",
        "- 单资产 BTC 趋势仍有集中风险，不能当作多品种 CTA 分散化策略。",
        "- 纸盘 30 天只验证运行链路，不验证 alpha。",
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


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float_metric(metrics: Mapping[str, Any], key: str, default: float) -> float:
    try:
        return float(metrics.get(key, default))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


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


def _empty_walk_forward_summary() -> dict[str, Any]:
    return {
        "fold_count": 0,
        "acceptable_fold_count": 0,
        "positive_fold_count": 0,
        "minimum_required_folds": 3,
        "minimum_acceptable_folds": 2,
        "pass": False,
    }


def _empty_regime_summary() -> dict[str, Any]:
    return {
        "segment_count": 0,
        "observed_regimes": [],
        "observed_regime_count": 0,
        "acceptable_segment_count": 0,
        "minimum_acceptable_segments": 4,
        "pass": False,
    }


def _empty_parameter_summary() -> dict[str, Any]:
    return {
        "row_count": 0,
        "default_present": False,
        "positive_total_return_share": 0.0,
        "drawdown_below_buy_hold_share": 0.0,
        "minimum_share_required": 0.67,
        "pass": False,
    }


def _empty_cost_summary() -> dict[str, Any]:
    return {
        "tested_cost_bps": [],
        "cost_10bps_total_return_positive": False,
        "cost_25bps_total_return_positive": False,
        "cost_25bps_drawdown_below_buy_hold": False,
        "pass": False,
    }


def _empty_extreme_year_summary() -> dict[str, Any]:
    return {
        "positive_segment_count": 0,
        "top_positive_segment_share": 1.0,
        "observed_regime_count": 0,
        "pass": False,
    }


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC trend v0 strategy validation gate report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--formal-report", default=str(DEFAULT_FORMAL_REPORT))
    parser.add_argument("--robustness-report", default=str(DEFAULT_ROBUSTNESS_REPORT))
    parser.add_argument("--paper-gate", default=str(DEFAULT_PAPER_GATE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--selected-candidate", default=DEFAULT_SELECTED_CANDIDATE)
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--cost-bps", type=float, default=5.0)
    parser.add_argument("--delay-days", type=int, default=1)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_v0_strategy_validation_gate_report(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        formal_report=Path(args.formal_report),
        robustness_report=Path(args.robustness_report),
        paper_gate=Path(args.paper_gate),
        output=Path(args.output),
        markdown_output=Path(args.markdown_output),
        selected_candidate=args.selected_candidate,
        initial_capital=float(args.initial_capital),
        cost_bps=float(args.cost_bps),
        delay_days=int(args.delay_days),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
