#!/usr/bin/env python3
"""Validate top BTC daily trend candidates after the all-strategy sweep.

This report is deliberately downstream of the broad parameter sweep. It takes
the top distinct strategy families from the all-strategy report and subjects
them to walk-forward selection, bull/bear/sideways segmentation, parameter
stability checks, cost stress, and extreme-year contribution analysis.

The output is research-only. It does not unlock paper trading or live trading.
"""

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
from scripts.build_btc_trend_all_strategy_backtest_report import (  # noqa: E402
    COST_BPS_GRID,
    DEFAULT_BUNDLE_DIR,
    DEFAULT_OUTPUT as DEFAULT_ALL_STRATEGY_REPORT,
    MIN_DAILY_ROWS,
    SYMBOL,
    CandidateSpec,
    EvaluatedCandidate,
    _atr,
    _baseline_specs,
    _candidate_specs,
    _evaluate_spec,
    _float,
    _guardrails,
    _mapping,
    _performance,
    _relpath,
    _resolve,
    _round,
    _score,
    _timestamp_text,
)


SCHEMA_VERSION = "btc_trend_top_strategy_validation_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_top_strategy_validation_report.json")
DEFAULT_WALK_FORWARD_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_top_strategy_walk_forward.csv")
DEFAULT_REGIME_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_top_strategy_regime_segments.csv")
DEFAULT_PARAMETER_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_top_strategy_parameter_stability.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势Top策略验证报告.md")

DEFAULT_TOP_FAMILY_COUNT = 5
DEFAULT_TRAIN_DAYS = 1095
DEFAULT_TEST_DAYS = 180
DEFAULT_STEP_DAYS = 180


def build_btc_trend_top_strategy_validation_report(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    all_strategy_report: Path = DEFAULT_ALL_STRATEGY_REPORT,
    output: Path = DEFAULT_OUTPUT,
    walk_forward_output: Path = DEFAULT_WALK_FORWARD_OUTPUT,
    regime_output: Path = DEFAULT_REGIME_OUTPUT,
    parameter_output: Path = DEFAULT_PARAMETER_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    initial_capital: float = 25_000.0,
    default_cost_bps: float = 5.0,
    default_delay_days: int = 1,
    top_family_count: int = DEFAULT_TOP_FAMILY_COUNT,
    minimum_daily_rows: int = MIN_DAILY_ROWS,
    walk_forward_train_days: int = DEFAULT_TRAIN_DAYS,
    walk_forward_test_days: int = DEFAULT_TEST_DAYS,
    walk_forward_step_days: int = DEFAULT_STEP_DAYS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    bundle_abs = _resolve(root, bundle_dir)
    all_report_abs = _resolve(root, all_strategy_report)
    output_abs = _resolve(root, output)
    wf_abs = _resolve(root, walk_forward_output)
    regime_abs = _resolve(root, regime_output)
    parameter_abs = _resolve(root, parameter_output)
    markdown_abs = _resolve(root, markdown_output)

    blockers: list[str] = []
    daily = _load_daily_bars(bundle_abs)
    if int(len(daily)) < int(minimum_daily_rows):
        blockers.append("btc_trend_top_strategy_validation_requires_minimum_daily_rows")
    all_report = _read_json(all_report_abs)
    if str(all_report.get("status", "")) != "research_only_all_backtest_complete":
        blockers.append("btc_trend_all_strategy_report_not_complete")

    specs_by_id = {spec.candidate_id: spec for spec in _candidate_specs()}
    selected_specs = _selected_top_family_specs(
        all_report=all_report,
        specs_by_id=specs_by_id,
        top_family_count=int(top_family_count),
    )
    if not selected_specs:
        blockers.append("btc_trend_top_strategy_no_selected_specs")

    if blockers:
        payload = _blocked_payload(
            generated=generated,
            root=root,
            bundle_abs=bundle_abs,
            all_report_abs=all_report_abs,
            wf_abs=wf_abs,
            regime_abs=regime_abs,
            parameter_abs=parameter_abs,
            daily=daily,
            top_family_count=top_family_count,
            minimum_daily_rows=minimum_daily_rows,
            blockers=blockers,
        )
        _write_csv(wf_abs, _walk_forward_fieldnames(), [])
        _write_csv(regime_abs, _regime_fieldnames(), [])
        _write_csv(parameter_abs, _parameter_fieldnames(), [])
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    close = daily["close"].astype(float)
    high = daily["high"].astype(float)
    low = daily["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    atr = _atr(high=high, low=low, close=close, window=20)
    baselines = [
        _evaluate_spec(
            spec,
            close=close,
            high=high,
            low=low,
            returns=returns,
            atr=atr,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for spec in _baseline_specs()
    ]
    buy_hold = baselines[0]
    buy_hold_metrics = buy_hold.metrics

    selected_candidates = [
        _evaluate_spec(
            spec,
            close=close,
            high=high,
            low=low,
            returns=returns,
            atr=atr,
            initial_capital=initial_capital,
            cost_bps=default_cost_bps,
            delay_days=default_delay_days,
        )
        for spec in selected_specs
    ]

    wf = _walk_forward_validation(
        selected_specs=selected_specs,
        all_specs=_candidate_specs(),
        buy_hold=buy_hold,
        close=close,
        high=high,
        low=low,
        returns=returns,
        atr=atr,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
        train_days=walk_forward_train_days,
        test_days=walk_forward_test_days,
        step_days=walk_forward_step_days,
    )
    regimes = _regime_validation(
        selected_candidates=selected_candidates,
        buy_hold=buy_hold,
        returns=returns,
        initial_capital=initial_capital,
    )
    parameters = _parameter_stability(
        selected_specs=selected_specs,
        all_specs=_candidate_specs(),
        buy_hold_metrics=buy_hold_metrics,
        close=close,
        high=high,
        low=low,
        returns=returns,
        atr=atr,
        initial_capital=initial_capital,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    cost_stress = _cost_stress(
        selected_specs=selected_specs,
        buy_hold_metrics=buy_hold_metrics,
        close=close,
        high=high,
        low=low,
        returns=returns,
        atr=atr,
        initial_capital=initial_capital,
        delay_days=default_delay_days,
    )
    extreme_year = _extreme_year_contribution(regimes["segments"])

    candidate_summaries = _candidate_summaries(
        selected_candidates=selected_candidates,
        buy_hold_metrics=buy_hold_metrics,
        wf_summary=_mapping(wf.get("summary")),
        regime_summary=_mapping(regimes.get("summary")),
        parameter_summary=_mapping(parameters.get("summary")),
        cost_summary=_mapping(cost_stress.get("summary")),
        extreme_summary=_mapping(extreme_year.get("summary")),
    )

    wf_rows = _walk_forward_rows(wf["folds"])
    regime_rows = _regime_rows(regimes["segments"])
    parameter_rows = _parameter_rows(parameters["rows"])
    _write_csv(wf_abs, _walk_forward_fieldnames(), wf_rows)
    _write_csv(regime_abs, _regime_fieldnames(), regime_rows)
    _write_csv(parameter_abs, _parameter_fieldnames(), parameter_rows)

    any_validated = any(row["validation_status"] == "research_validation_passed" for row in candidate_summaries)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "top_strategy_validation_research_only",
        "decision": "manual_review_required_before_any_paper_or_live_claim",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "all_strategy_report": _relpath(all_report_abs, root),
        "data": _data_section(daily),
        "parameters": {
            "top_family_count": int(top_family_count),
            "minimum_daily_rows": int(minimum_daily_rows),
            "default_cost_bps": float(default_cost_bps),
            "default_delay_days": int(default_delay_days),
            "walk_forward_train_days": int(walk_forward_train_days),
            "walk_forward_test_days": int(walk_forward_test_days),
            "walk_forward_step_days": int(walk_forward_step_days),
            "cost_bps_grid": COST_BPS_GRID,
        },
        "selected_families": [
            {
                "rank": i + 1,
                "family_id": spec.family_id,
                "candidate_id": spec.candidate_id,
                "variant_id": spec.variant_id,
                "params": spec.params,
            }
            for i, spec in enumerate(selected_specs)
        ],
        "buy_hold_metrics": buy_hold_metrics,
        "candidate_summaries": candidate_summaries,
        "walk_forward": wf,
        "regime_validation": regimes,
        "parameter_stability": parameters,
        "cost_stress": cost_stress,
        "extreme_year_contribution": extreme_year,
        "outputs": {
            "walk_forward_csv": _relpath(wf_abs, root),
            "regime_csv": _relpath(regime_abs, root),
            "parameter_stability_csv": _relpath(parameter_abs, root),
        },
        "guardrails": {
            **_guardrails(),
            "this_report_does_not_unlock_paper_runner": True,
            "this_report_does_not_unlock_live_trading": True,
            "strategy_validation_report_is_not_execution_permission": True,
        },
        "research_validation_any_candidate_passed": bool(any_validated),
        "blockers": [],
        "recommendations": _recommendations(candidate_summaries),
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _selected_top_family_specs(
    *,
    all_report: Mapping[str, Any],
    specs_by_id: Mapping[str, CandidateSpec],
    top_family_count: int,
) -> list[CandidateSpec]:
    summaries = [_mapping(row) for row in all_report.get("family_summaries", []) if isinstance(row, Mapping)]
    ranked = sorted(
        summaries,
        key=lambda row: (
            -float(_mapping(row.get("selected_candidate")).get("score", -999999.0) or -999999.0),
            str(row.get("family_id", "")),
        ),
    )
    selected: list[CandidateSpec] = []
    seen: set[str] = set()
    for summary in ranked:
        family_id = str(summary.get("family_id", ""))
        if not family_id or family_id in seen:
            continue
        candidate_id = str(_mapping(summary.get("selected_candidate")).get("candidate_id", ""))
        spec = specs_by_id.get(candidate_id)
        if spec is None:
            continue
        selected.append(spec)
        seen.add(family_id)
        if len(selected) >= int(top_family_count):
            break
    return selected


def _walk_forward_validation(
    *,
    selected_specs: list[CandidateSpec],
    all_specs: list[CandidateSpec],
    buy_hold: EvaluatedCandidate,
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
    train_days: int,
    test_days: int,
    step_days: int,
) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    selected_family_ids = [spec.family_id for spec in selected_specs]
    n = int(len(close))
    fold_id = 1
    test_start = int(train_days)
    while test_start < n:
        test_end = min(test_start + int(test_days), n)
        if test_end - test_start < max(60, min(90, int(test_days) // 2)):
            break
        train_start = max(0, test_start - int(train_days))
        train_index = close.index[train_start:test_start]
        test_index = close.index[test_start:test_end]
        if len(train_index) < 120 or len(test_index) < 60:
            test_start += int(step_days)
            continue
        baseline_train = _period_metrics(buy_hold, train_index, initial_capital=initial_capital)
        baseline_test = _period_metrics(buy_hold, test_index, initial_capital=initial_capital)
        family_rows = []
        for family_id in selected_family_ids:
            family_specs = [spec for spec in all_specs if spec.family_id == family_id]
            train_rank = []
            evaluated_by_id: dict[str, EvaluatedCandidate] = {}
            for spec in family_specs:
                candidate = _evaluate_spec(
                    spec,
                    close=close,
                    high=high,
                    low=low,
                    returns=returns,
                    atr=atr,
                    initial_capital=initial_capital,
                    cost_bps=cost_bps,
                    delay_days=delay_days,
                )
                evaluated_by_id[spec.candidate_id] = candidate
                train_metrics = _period_metrics(candidate, train_index, initial_capital=initial_capital)
                train_rank.append(
                    {
                        "candidate_id": spec.candidate_id,
                        "variant_id": spec.variant_id,
                        "params": spec.params,
                        "score": _score(train_metrics, buy_hold_metrics=baseline_train),
                        "metrics": train_metrics,
                    }
                )
            if not train_rank:
                continue
            selected_train = max(train_rank, key=lambda row: (float(row["score"]), str(row["candidate_id"])))
            test_candidate = evaluated_by_id[str(selected_train["candidate_id"])]
            test_metrics = _period_metrics(test_candidate, test_index, initial_capital=initial_capital)
            full_sample_spec = next(spec for spec in selected_specs if spec.family_id == family_id)
            full_sample_candidate = evaluated_by_id[full_sample_spec.candidate_id]
            full_sample_test_metrics = _period_metrics(full_sample_candidate, test_index, initial_capital=initial_capital)
            acceptable = (
                _float(test_metrics, "total_return_pct") >= -25.0
                and _float(test_metrics, "max_drawdown_abs_pct")
                <= _float(baseline_test, "max_drawdown_abs_pct") + 5.0
                and _float(test_metrics, "average_exposure") >= 0.05
            )
            family_rows.append(
                {
                    "family_id": family_id,
                    "train_selected_candidate_id": selected_train["candidate_id"],
                    "train_selected_variant_id": selected_train["variant_id"],
                    "train_selected_params": selected_train["params"],
                    "train_selected_score": selected_train["score"],
                    "train_metrics": selected_train["metrics"],
                    "train_selected_test_metrics": test_metrics,
                    "full_sample_candidate_id": full_sample_spec.candidate_id,
                    "full_sample_params": full_sample_spec.params,
                    "full_sample_test_metrics": full_sample_test_metrics,
                    "buy_hold_test_metrics": baseline_test,
                    "acceptable": bool(acceptable),
                }
            )
        folds.append(
            {
                "fold_id": fold_id,
                "train_start": _timestamp_text(train_index.min()),
                "train_end": _timestamp_text(train_index.max()),
                "test_start": _timestamp_text(test_index.min()),
                "test_end": _timestamp_text(test_index.max()),
                "families": family_rows,
            }
        )
        fold_id += 1
        test_start += int(step_days)
    family_summary: dict[str, dict[str, Any]] = {}
    for family_id in selected_family_ids:
        rows = [row for fold in folds for row in fold["families"] if row["family_id"] == family_id]
        acceptable_count = sum(1 for row in rows if row.get("acceptable"))
        positive_count = sum(
            1 for row in rows if _float(_mapping(row.get("train_selected_test_metrics")), "total_return_pct") > 0.0
        )
        minimum_acceptable = max(2, math.ceil(len(rows) * 0.5)) if rows else 2
        minimum_positive = max(2, math.ceil(len(rows) * 0.5)) if rows else 2
        family_summary[family_id] = {
            "fold_count": len(rows),
            "acceptable_fold_count": acceptable_count,
            "positive_fold_count": positive_count,
            "minimum_acceptable_folds": minimum_acceptable,
            "minimum_positive_folds": minimum_positive,
            "pass": bool(
                len(rows) >= 3
                and acceptable_count >= minimum_acceptable
                and positive_count >= minimum_positive
            ),
        }
    return {
        "folds": folds,
        "summary": {
            "fold_count": len(folds),
            "family_summary": family_summary,
            "all_selected_families_have_walk_forward": all(row["fold_count"] >= 3 for row in family_summary.values())
            if family_summary
            else False,
        },
    }


def _regime_validation(
    *,
    selected_candidates: list[EvaluatedCandidate],
    buy_hold: EvaluatedCandidate,
    returns: pd.Series,
    initial_capital: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    years = sorted({int(ts.year) for ts in returns.index})
    for year in years:
        index = returns.index[returns.index.year == year]
        if len(index) < 60:
            continue
        buy_hold_metrics = _period_metrics(buy_hold, index, initial_capital=initial_capital)
        regime = _regime_label(buy_hold_metrics)
        for candidate in selected_candidates:
            metrics = _period_metrics(candidate, index, initial_capital=initial_capital)
            acceptable = (
                _float(metrics, "total_return_pct") >= -25.0
                and _float(metrics, "max_drawdown_abs_pct")
                <= _float(buy_hold_metrics, "max_drawdown_abs_pct") + 5.0
            )
            rows.append(
                {
                    "year": year,
                    "segment": f"{year} partial" if len(index) < 365 else str(year),
                    "day_count": int(len(index)),
                    "regime": regime,
                    "family_id": candidate.spec.family_id,
                    "candidate_id": candidate.spec.candidate_id,
                    "params": candidate.spec.params,
                    "metrics": metrics,
                    "buy_hold_metrics": buy_hold_metrics,
                    "acceptable": bool(acceptable),
                }
            )
    summary: dict[str, Any] = {}
    for candidate in selected_candidates:
        family_rows = [row for row in rows if row["candidate_id"] == candidate.spec.candidate_id]
        regimes = sorted({str(row.get("regime")) for row in family_rows})
        acceptable_count = sum(1 for row in family_rows if row.get("acceptable"))
        regime_counts = {
            regime: {
                "segment_count": sum(1 for row in family_rows if row.get("regime") == regime),
                "acceptable_count": sum(1 for row in family_rows if row.get("regime") == regime and row.get("acceptable")),
            }
            for regime in regimes
        }
        summary[candidate.spec.family_id] = {
            "candidate_id": candidate.spec.candidate_id,
            "segment_count": len(family_rows),
            "observed_regimes": regimes,
            "observed_regime_count": len(regimes),
            "acceptable_segment_count": acceptable_count,
            "minimum_acceptable_segments": 4,
            "regime_counts": regime_counts,
            "pass": bool(len(regimes) >= 2 and acceptable_count >= 4),
        }
    return {"segments": rows, "summary": summary}


def _parameter_stability(
    *,
    selected_specs: list[CandidateSpec],
    all_specs: list[CandidateSpec],
    buy_hold_metrics: Mapping[str, Any],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    selected_by_family = {spec.family_id: spec for spec in selected_specs}
    for family_id, selected_spec in selected_by_family.items():
        family_specs = [spec for spec in all_specs if spec.family_id == family_id]
        family_rows = []
        for spec in family_specs:
            candidate = _evaluate_spec(
                spec,
                close=close,
                high=high,
                low=low,
                returns=returns,
                atr=atr,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_days=delay_days,
            )
            metrics = candidate.metrics
            score = _score(metrics, buy_hold_metrics=buy_hold_metrics)
            row = {
                "family_id": family_id,
                "candidate_id": spec.candidate_id,
                "variant_id": spec.variant_id,
                "params": spec.params,
                "is_selected": spec.candidate_id == selected_spec.candidate_id,
                "score": score,
                "metrics": metrics,
                "positive_total_return": _float(metrics, "total_return_pct") > 0.0,
                "drawdown_below_buy_hold": _float(metrics, "max_drawdown_abs_pct")
                < _float(buy_hold_metrics, "max_drawdown_abs_pct"),
                "meaningful_exposure": _float(metrics, "average_exposure") >= 0.10
                and _float(metrics, "total_return_pct") >= 5.0,
            }
            rows.append(row)
            family_rows.append(row)
        ranked = sorted(family_rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
        selected_rank = next((i + 1 for i, row in enumerate(ranked) if row["candidate_id"] == selected_spec.candidate_id), 0)
        row_count = len(family_rows)
        positive_count = sum(1 for row in family_rows if row["positive_total_return"])
        dd_count = sum(1 for row in family_rows if row["drawdown_below_buy_hold"])
        meaningful_count = sum(1 for row in family_rows if row["meaningful_exposure"])
        selected_percentile = 1.0 - ((selected_rank - 1) / max(1, row_count - 1)) if selected_rank else 0.0
        summary[family_id] = {
            "candidate_id": selected_spec.candidate_id,
            "row_count": row_count,
            "selected_rank": selected_rank,
            "selected_score_percentile": _round(selected_percentile),
            "positive_total_return_share": _round(positive_count / row_count) if row_count else 0.0,
            "drawdown_below_buy_hold_share": _round(dd_count / row_count) if row_count else 0.0,
            "meaningful_candidate_share": _round(meaningful_count / row_count) if row_count else 0.0,
            "pass": bool(
                row_count > 0
                and selected_rank > 0
                and selected_percentile >= 0.75
                and positive_count / row_count >= 0.50
                and meaningful_count / row_count >= 0.25
            ),
        }
    return {"rows": rows, "summary": summary}


def _cost_stress(
    *,
    selected_specs: list[CandidateSpec],
    buy_hold_metrics: Mapping[str, Any],
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    returns: pd.Series,
    atr: pd.Series,
    initial_capital: float,
    delay_days: int,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    for spec in selected_specs:
        family_rows = []
        for cost_bps in COST_BPS_GRID:
            candidate = _evaluate_spec(
                spec,
                close=close,
                high=high,
                low=low,
                returns=returns,
                atr=atr,
                initial_capital=initial_capital,
                cost_bps=float(cost_bps),
                delay_days=delay_days,
            )
            row = {
                "family_id": spec.family_id,
                "candidate_id": spec.candidate_id,
                "cost_bps": float(cost_bps),
                "metrics": candidate.metrics,
            }
            rows.append(row)
            family_rows.append(row)
        by_cost = {float(row["cost_bps"]): _mapping(row.get("metrics")) for row in family_rows}
        cost_10 = _mapping(by_cost.get(10.0))
        cost_25 = _mapping(by_cost.get(25.0))
        summary[spec.family_id] = {
            "candidate_id": spec.candidate_id,
            "tested_cost_bps": sorted(by_cost),
            "cost_10bps_total_return_positive": _float(cost_10, "total_return_pct") > 0.0,
            "cost_25bps_total_return_positive": _float(cost_25, "total_return_pct") > 0.0,
            "cost_25bps_drawdown_below_buy_hold": _float(cost_25, "max_drawdown_abs_pct")
            < _float(buy_hold_metrics, "max_drawdown_abs_pct"),
            "pass": bool(
                set(COST_BPS_GRID).issubset(set(by_cost))
                and _float(cost_10, "total_return_pct") > 0.0
                and _float(cost_25, "total_return_pct") > 0.0
                and _float(cost_25, "max_drawdown_abs_pct") < _float(buy_hold_metrics, "max_drawdown_abs_pct")
            ),
        }
    return {"rows": rows, "summary": summary}


def _extreme_year_contribution(regime_segments: list[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    by_family: dict[str, list[Mapping[str, Any]]] = {}
    for row in regime_segments:
        by_family.setdefault(str(row.get("family_id", "")), []).append(row)
    for family_id, rows in by_family.items():
        year_returns = [
            {
                "year": int(row.get("year", 0) or 0),
                "segment": str(row.get("segment", "")),
                "regime": str(row.get("regime", "")),
                "total_return_pct": _float(_mapping(row.get("metrics")), "total_return_pct"),
            }
            for row in rows
        ]
        positives = [row for row in year_returns if float(row["total_return_pct"]) > 0.0]
        positive_sum = sum(float(row["total_return_pct"]) for row in positives)
        top_positive = max(positives, key=lambda row: float(row["total_return_pct"])) if positives else {}
        top_share = float(top_positive.get("total_return_pct", 0.0) or 0.0) / positive_sum if positive_sum > 0.0 else 1.0
        worst = min(year_returns, key=lambda row: float(row["total_return_pct"])) if year_returns else {}
        best = max(year_returns, key=lambda row: float(row["total_return_pct"])) if year_returns else {}
        summary[family_id] = {
            "positive_year_count": len(positives),
            "positive_return_sum_pct": _round(positive_sum),
            "top_positive_year": top_positive,
            "top_positive_year_share": _round(top_share),
            "best_year": best,
            "worst_year": worst,
            "single_year_dependency_warning": bool(len(positives) < 2 or top_share > 0.75),
            "pass": bool(len(positives) >= 2 and top_share <= 0.75),
        }
    return {"summary": summary}


def _candidate_summaries(
    *,
    selected_candidates: list[EvaluatedCandidate],
    buy_hold_metrics: Mapping[str, Any],
    wf_summary: Mapping[str, Any],
    regime_summary: Mapping[str, Any],
    parameter_summary: Mapping[str, Any],
    cost_summary: Mapping[str, Any],
    extreme_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    wf_family = _mapping(wf_summary.get("family_summary"))
    for i, candidate in enumerate(
        sorted(
            selected_candidates,
            key=lambda item: -_score(item.metrics, buy_hold_metrics=buy_hold_metrics),
        ),
        start=1,
    ):
        family_id = candidate.spec.family_id
        checks = {
            "walk_forward": bool(_mapping(wf_family.get(family_id)).get("pass", False)),
            "regime_validation": bool(_mapping(regime_summary.get(family_id)).get("pass", False)),
            "parameter_stability": bool(_mapping(parameter_summary.get(family_id)).get("pass", False)),
            "cost_stress": bool(_mapping(cost_summary.get(family_id)).get("pass", False)),
            "extreme_year_contribution": bool(_mapping(extreme_summary.get(family_id)).get("pass", False)),
        }
        passed = all(checks.values())
        rows.append(
            {
                "rank": i,
                "family_id": family_id,
                "candidate_id": candidate.spec.candidate_id,
                "variant_id": candidate.spec.variant_id,
                "params": candidate.spec.params,
                "score": _score(candidate.metrics, buy_hold_metrics=buy_hold_metrics),
                "metrics": candidate.metrics,
                "checks": checks,
                "validation_status": "research_validation_passed" if passed else "research_validation_not_passed",
            }
        )
    return rows


def _period_metrics(candidate: EvaluatedCandidate, index: pd.Index, *, initial_capital: float) -> dict[str, Any]:
    strategy_returns = candidate.strategy_returns.loc[index].fillna(0.0)
    exposure = candidate.exposure.loc[index].fillna(0.0)
    turnover = candidate.turnover.loc[index].fillna(0.0)
    cost = candidate.cost.loc[index].fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    return _performance(strategy_returns=strategy_returns, equity=equity, exposure=exposure, turnover=turnover, cost=cost)


def _regime_label(buy_hold_metrics: Mapping[str, Any]) -> str:
    total_return = _float(buy_hold_metrics, "total_return_pct")
    max_drawdown = _float(buy_hold_metrics, "max_drawdown_abs_pct")
    if total_return >= 25.0:
        return "bull"
    if total_return <= -20.0 or max_drawdown >= 35.0:
        return "bear"
    return "sideways"


def _walk_forward_rows(folds: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for fold in folds:
        for item in fold.get("families", []):
            row = _mapping(item)
            test_metrics = _mapping(row.get("train_selected_test_metrics"))
            baseline = _mapping(row.get("buy_hold_test_metrics"))
            rows.append(
                {
                    "fold_id": fold.get("fold_id", ""),
                    "family_id": row.get("family_id", ""),
                    "train_start": fold.get("train_start", ""),
                    "train_end": fold.get("train_end", ""),
                    "test_start": fold.get("test_start", ""),
                    "test_end": fold.get("test_end", ""),
                    "train_selected_candidate_id": row.get("train_selected_candidate_id", ""),
                    "train_selected_params_json": json.dumps(row.get("train_selected_params", {}), sort_keys=True, ensure_ascii=False),
                    "train_selected_score": row.get("train_selected_score", 0),
                    "test_total_return_pct": test_metrics.get("total_return_pct", 0),
                    "test_max_drawdown_abs_pct": test_metrics.get("max_drawdown_abs_pct", 0),
                    "test_sharpe_ratio": test_metrics.get("sharpe_ratio", 0),
                    "buy_hold_test_total_return_pct": baseline.get("total_return_pct", 0),
                    "buy_hold_test_max_drawdown_abs_pct": baseline.get("max_drawdown_abs_pct", 0),
                    "acceptable": row.get("acceptable", False),
                }
            )
    return rows


def _regime_rows(segments: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in segments:
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        baseline = _mapping(item.get("buy_hold_metrics"))
        rows.append(
            {
                "year": item.get("year", ""),
                "segment": item.get("segment", ""),
                "regime": item.get("regime", ""),
                "day_count": item.get("day_count", 0),
                "family_id": item.get("family_id", ""),
                "candidate_id": item.get("candidate_id", ""),
                "total_return_pct": metrics.get("total_return_pct", 0),
                "max_drawdown_abs_pct": metrics.get("max_drawdown_abs_pct", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "buy_hold_total_return_pct": baseline.get("total_return_pct", 0),
                "buy_hold_max_drawdown_abs_pct": baseline.get("max_drawdown_abs_pct", 0),
                "acceptable": item.get("acceptable", False),
            }
        )
    return rows


def _parameter_rows(parameter_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in parameter_rows:
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        rows.append(
            {
                "family_id": item.get("family_id", ""),
                "candidate_id": item.get("candidate_id", ""),
                "variant_id": item.get("variant_id", ""),
                "is_selected": item.get("is_selected", False),
                "score": item.get("score", 0),
                "params_json": json.dumps(item.get("params", {}), sort_keys=True, ensure_ascii=False),
                "total_return_pct": metrics.get("total_return_pct", 0),
                "max_drawdown_abs_pct": metrics.get("max_drawdown_abs_pct", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "average_exposure": metrics.get("average_exposure", 0),
                "exposure_change_count": metrics.get("exposure_change_count", 0),
                "positive_total_return": item.get("positive_total_return", False),
                "drawdown_below_buy_hold": item.get("drawdown_below_buy_hold", False),
                "meaningful_exposure": item.get("meaningful_exposure", False),
            }
        )
    return rows


def _blocked_payload(
    *,
    generated: str,
    root: Path,
    bundle_abs: Path,
    all_report_abs: Path,
    wf_abs: Path,
    regime_abs: Path,
    parameter_abs: Path,
    daily: pd.DataFrame,
    top_family_count: int,
    minimum_daily_rows: int,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "top_strategy_validation_blocked",
        "decision": "do_not_validate_top_strategies",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "all_strategy_report": _relpath(all_report_abs, root),
        "data": _data_section(daily),
        "parameters": {
            "top_family_count": int(top_family_count),
            "minimum_daily_rows": int(minimum_daily_rows),
        },
        "selected_families": [],
        "candidate_summaries": [],
        "walk_forward": {"folds": [], "summary": {"fold_count": 0, "family_summary": {}}},
        "regime_validation": {"segments": [], "summary": {}},
        "parameter_stability": {"rows": [], "summary": {}},
        "cost_stress": {"rows": [], "summary": {}},
        "extreme_year_contribution": {"summary": {}},
        "outputs": {
            "walk_forward_csv": _relpath(wf_abs, root),
            "regime_csv": _relpath(regime_abs, root),
            "parameter_stability_csv": _relpath(parameter_abs, root),
        },
        "guardrails": {
            **_guardrails(),
            "this_report_does_not_unlock_paper_runner": True,
            "this_report_does_not_unlock_live_trading": True,
            "strategy_validation_report_is_not_execution_permission": True,
        },
        "research_validation_any_candidate_passed": False,
        "blockers": _dedupe(blockers),
        "recommendations": ["前置数据或全集回测报告不足，不做 top 策略验证。"],
    }


def _data_section(daily: pd.DataFrame) -> dict[str, Any]:
    return {
        "daily_rows": int(len(daily)),
        "start": _timestamp_text(daily.index.min()) if len(daily) else "",
        "end": _timestamp_text(daily.index.max()) if len(daily) else "",
        "source": "OKX public local spot daily bundle",
    }


def _recommendations(candidate_summaries: list[Mapping[str, Any]]) -> list[str]:
    if not candidate_summaries:
        return ["没有可验证候选。"]
    passed = [row for row in candidate_summaries if row.get("validation_status") == "research_validation_passed"]
    notes = [
        "本报告只说明 top 策略是否通过下一层研究验证，不解锁纸盘或实盘。",
        "低换手、高排名候选需要人工重点审阅是否过度依赖少数 BTC 大趋势年份。",
    ]
    if passed:
        notes.append("存在通过研究验证的候选，可进入更细的人工审阅和前向观察设计。")
    else:
        notes.append("当前 top 候选没有全部通过验证项，应继续保持 research-only。")
    return notes


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    lines = [
        "# BTC 趋势Top策略验证报告",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
    ]
    if payload.get("status") == "top_strategy_validation_blocked":
        lines += [
            "验证被阻断。",
            "",
            "阻断项：",
        ]
        for blocker in payload.get("blockers", []):
            lines.append(f"- `{blocker}`")
        lines.append("")
        return "\n".join(lines)
    lines += [
        "本报告对全集回测排名靠前的不同策略族做 walk-forward、牛熊震荡分段、参数稳定性、成本压力和极端年份贡献拆解。",
        "它只支持研究判断，不解锁纸盘或实盘。",
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        "",
        "## 候选验证摘要",
        "",
        "| 排名 | 策略族 | 候选 | 状态 | 总收益 | 最大回撤 | Sharpe | WF | 分段 | 参数稳定 | 成本 | 极端年份 |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("candidate_summaries", []):
        item = _mapping(row)
        metrics = _mapping(item.get("metrics"))
        checks = _mapping(item.get("checks"))
        lines.append(
            f"| {item.get('rank', '')} | {item.get('family_id', '')} | `{item.get('candidate_id', '')}` | "
            f"`{item.get('validation_status', '')}` | {metrics.get('total_return_pct', 0)}% | "
            f"{metrics.get('max_drawdown_abs_pct', 0)}% | {metrics.get('sharpe_ratio', 0)} | "
            f"{checks.get('walk_forward', False)} | {checks.get('regime_validation', False)} | "
            f"{checks.get('parameter_stability', False)} | {checks.get('cost_stress', False)} | "
            f"{checks.get('extreme_year_contribution', False)} |"
        )
    lines += [
        "",
        "## Walk-forward 摘要",
        "",
        "| 策略族 | fold数 | 可接受fold | 正收益fold | 通过 |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    wf_family = _mapping(_mapping(payload.get("walk_forward")).get("summary")).get("family_summary", {})
    for family_id, summary in _mapping(wf_family).items():
        item = _mapping(summary)
        lines.append(
            f"| {family_id} | {item.get('fold_count', 0)} | {item.get('acceptable_fold_count', 0)} | "
            f"{item.get('positive_fold_count', 0)} | {item.get('pass', False)} |"
        )
    lines += [
        "",
        "## 参数稳定性摘要",
        "",
        "| 策略族 | 参数数 | 入选排名 | 入选分位 | 正收益占比 | 有效仓位占比 | 通过 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for family_id, summary in _mapping(_mapping(payload.get("parameter_stability")).get("summary")).items():
        item = _mapping(summary)
        lines.append(
            f"| {family_id} | {item.get('row_count', 0)} | {item.get('selected_rank', 0)} | "
            f"{item.get('selected_score_percentile', 0)} | {item.get('positive_total_return_share', 0)} | "
            f"{item.get('meaningful_candidate_share', 0)} | {item.get('pass', False)} |"
        )
    lines += [
        "",
        "## 极端年份贡献",
        "",
        "| 策略族 | 正收益年份数 | 最大正贡献年份占比 | 最好年份 | 最差年份 | 通过 |",
        "| --- | ---: | ---: | --- | --- | --- |",
    ]
    for family_id, summary in _mapping(_mapping(payload.get("extreme_year_contribution")).get("summary")).items():
        item = _mapping(summary)
        best = _mapping(item.get("best_year"))
        worst = _mapping(item.get("worst_year"))
        lines.append(
            f"| {family_id} | {item.get('positive_year_count', 0)} | {item.get('top_positive_year_share', 0)} | "
            f"{best.get('year', '')}: {best.get('total_return_pct', 0)}% | "
            f"{worst.get('year', '')}: {worst.get('total_return_pct', 0)}% | {item.get('pass', False)} |"
        )
    lines += [
        "",
        "## 输出",
        "",
        f"- walk-forward：`{_mapping(payload.get('outputs')).get('walk_forward_csv', '')}`",
        f"- 行情分段：`{_mapping(payload.get('outputs')).get('regime_csv', '')}`",
        f"- 参数稳定性：`{_mapping(payload.get('outputs')).get('parameter_stability_csv', '')}`",
        "",
        "## 下一步",
        "",
    ]
    for note in payload.get("recommendations", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _walk_forward_fieldnames() -> list[str]:
    return [
        "fold_id",
        "family_id",
        "train_start",
        "train_end",
        "test_start",
        "test_end",
        "train_selected_candidate_id",
        "train_selected_params_json",
        "train_selected_score",
        "test_total_return_pct",
        "test_max_drawdown_abs_pct",
        "test_sharpe_ratio",
        "buy_hold_test_total_return_pct",
        "buy_hold_test_max_drawdown_abs_pct",
        "acceptable",
    ]


def _regime_fieldnames() -> list[str]:
    return [
        "year",
        "segment",
        "regime",
        "day_count",
        "family_id",
        "candidate_id",
        "total_return_pct",
        "max_drawdown_abs_pct",
        "sharpe_ratio",
        "buy_hold_total_return_pct",
        "buy_hold_max_drawdown_abs_pct",
        "acceptable",
    ]


def _parameter_fieldnames() -> list[str]:
    return [
        "family_id",
        "candidate_id",
        "variant_id",
        "is_selected",
        "score",
        "params_json",
        "total_return_pct",
        "max_drawdown_abs_pct",
        "sharpe_ratio",
        "average_exposure",
        "exposure_change_count",
        "positive_total_return",
        "drawdown_below_buy_hold",
        "meaningful_exposure",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC top trend strategy validation report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--all-strategy-report", default=str(DEFAULT_ALL_STRATEGY_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--walk-forward-output", default=str(DEFAULT_WALK_FORWARD_OUTPUT))
    parser.add_argument("--regime-output", default=str(DEFAULT_REGIME_OUTPUT))
    parser.add_argument("--parameter-output", default=str(DEFAULT_PARAMETER_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--default-cost-bps", type=float, default=5.0)
    parser.add_argument("--default-delay-days", type=int, default=1)
    parser.add_argument("--top-family-count", type=int, default=DEFAULT_TOP_FAMILY_COUNT)
    parser.add_argument("--minimum-daily-rows", type=int, default=MIN_DAILY_ROWS)
    parser.add_argument("--walk-forward-train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    parser.add_argument("--walk-forward-test-days", type=int, default=DEFAULT_TEST_DAYS)
    parser.add_argument("--walk-forward-step-days", type=int, default=DEFAULT_STEP_DAYS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_top_strategy_validation_report(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        all_strategy_report=Path(args.all_strategy_report),
        output=Path(args.output),
        walk_forward_output=Path(args.walk_forward_output),
        regime_output=Path(args.regime_output),
        parameter_output=Path(args.parameter_output),
        markdown_output=Path(args.markdown_output),
        initial_capital=float(args.initial_capital),
        default_cost_bps=float(args.default_cost_bps),
        default_delay_days=int(args.default_delay_days),
        top_family_count=int(args.top_family_count),
        minimum_daily_rows=int(args.minimum_daily_rows),
        walk_forward_train_days=int(args.walk_forward_train_days),
        walk_forward_test_days=int(args.walk_forward_test_days),
        walk_forward_step_days=int(args.walk_forward_step_days),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
