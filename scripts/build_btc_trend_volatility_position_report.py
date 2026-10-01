#!/usr/bin/env python3
"""Build BTC trend volatility-position sizing report.

The report keeps the existing trend signals unchanged and applies a
volatility-targeted exposure overlay:

    target_raw_exposure = raw_signal * target_vol / realized_vol
    effective_exposure = target_raw_exposure.shift(T+1)

It is research-only and never unlocks paper or live trading.
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
    DEFAULT_BUNDLE_DIR,
    MAX_EXPOSURE,
    MIN_DAILY_ROWS,
    SYMBOL,
    CandidateSpec,
    EvaluatedCandidate,
    _atr,
    _candidate_specs,
    _evaluate_spec,
    _float,
    _guardrails,
    _mapping,
    _performance,
    _raw_signal,
    _relpath,
    _resolve,
    _round,
    _timestamp_text,
)
from scripts.build_btc_trend_top_strategy_validation_report import (  # noqa: E402
    DEFAULT_OUTPUT as DEFAULT_TOP_VALIDATION_REPORT,
)


SCHEMA_VERSION = "btc_trend_volatility_position_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_volatility_position_report.json")
DEFAULT_GRID_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_volatility_position_grid.csv")
DEFAULT_LEDGER_OUTPUT = Path("artifacts/btc_trend_v0/latest/btc_trend_volatility_position_ledger.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 趋势波动率仓位报告.md")

VOL_WINDOWS = [14, 20, 30, 60]
TARGET_VOLS = [0.15, 0.20, 0.25, 0.35]


def build_btc_trend_volatility_position_report(
    *,
    repo_root: Path | None = None,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    top_validation_report: Path = DEFAULT_TOP_VALIDATION_REPORT,
    output: Path = DEFAULT_OUTPUT,
    grid_output: Path = DEFAULT_GRID_OUTPUT,
    ledger_output: Path = DEFAULT_LEDGER_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    initial_capital: float = 25_000.0,
    default_cost_bps: float = 5.0,
    default_delay_days: int = 1,
    minimum_daily_rows: int = MIN_DAILY_ROWS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    bundle_abs = _resolve(root, bundle_dir)
    top_abs = _resolve(root, top_validation_report)
    output_abs = _resolve(root, output)
    grid_abs = _resolve(root, grid_output)
    ledger_abs = _resolve(root, ledger_output)
    markdown_abs = _resolve(root, markdown_output)

    daily = _load_daily_bars(bundle_abs)
    top_report = _read_json(top_abs)
    blockers: list[str] = []
    if len(daily) < int(minimum_daily_rows):
        blockers.append("btc_trend_volatility_position_requires_minimum_daily_rows")
    if str(top_report.get("status", "")) != "top_strategy_validation_research_only":
        blockers.append("btc_trend_top_strategy_validation_report_missing_or_unexpected_status")

    specs_by_id = {spec.candidate_id: spec for spec in _candidate_specs()}
    selected_specs = _selected_specs(top_report=top_report, specs_by_id=specs_by_id)
    if not selected_specs:
        blockers.append("btc_trend_volatility_position_no_research_validated_candidates")

    if blockers:
        payload = _blocked_payload(
            generated=generated,
            root=root,
            bundle_abs=bundle_abs,
            top_abs=top_abs,
            grid_abs=grid_abs,
            ledger_abs=ledger_abs,
            daily=daily,
            blockers=blockers,
        )
        _write_csv(grid_abs, _grid_fieldnames(), [])
        _write_csv(ledger_abs, _ledger_fieldnames(), [])
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    close = daily["close"].astype(float)
    high = daily["high"].astype(float)
    low = daily["low"].astype(float)
    returns = close.pct_change().fillna(0.0)
    atr = _atr(high=high, low=low, close=close, window=20)

    baseline_candidates = [
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
    baseline_by_id = {candidate.spec.candidate_id: candidate for candidate in baseline_candidates}

    variants: list[dict[str, Any]] = []
    for spec in selected_specs:
        raw = _raw_signal(spec, close=close, high=high, low=low, returns=returns, atr=atr).fillna(0.0).clip(0.0, 1.0)
        for vol_window in VOL_WINDOWS:
            realized_vol = returns.rolling(int(vol_window)).std(ddof=0) * math.sqrt(365.0)
            for target_vol in TARGET_VOLS:
                variant = _evaluate_vol_variant(
                    spec=spec,
                    raw_signal=raw,
                    returns=returns,
                    realized_vol=realized_vol,
                    initial_capital=initial_capital,
                    cost_bps=default_cost_bps,
                    delay_days=default_delay_days,
                    vol_window=vol_window,
                    target_vol=target_vol,
                )
                variants.append(variant)

    grid_rows = [
        _grid_row(variant, baseline=baseline_by_id[str(variant["base_candidate_id"])])
        for variant in variants
    ]
    _write_csv(grid_abs, _grid_fieldnames(), grid_rows)

    selected_by_family = _select_family_variants(variants, baseline_by_id=baseline_by_id)
    ledger_rows = _ledger_rows(
        selected_variants=selected_by_family,
        close=close,
        returns=returns,
        cost_bps=default_cost_bps,
        delay_days=default_delay_days,
    )
    _write_csv(ledger_abs, _ledger_fieldnames(), ledger_rows)

    family_summaries = [
        _family_summary(
            spec=spec,
            baseline=baseline_by_id[spec.candidate_id],
            selected=selected_by_family[spec.family_id],
            variants=[variant for variant in variants if variant["family_id"] == spec.family_id],
        )
        for spec in selected_specs
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "volatility_position_research_only",
        "decision": "manual_review_required_before_any_paper_or_live_claim",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "top_validation_report": _relpath(top_abs, root),
        "data": _data_section(daily),
        "parameters": {
            "vol_windows": VOL_WINDOWS,
            "target_vols": TARGET_VOLS,
            "default_cost_bps": float(default_cost_bps),
            "default_delay_days": int(default_delay_days),
            "max_exposure": MAX_EXPOSURE,
            "rule": "raw_signal generated after T close; volatility-scaled exposure effective T+1",
        },
        "family_summaries": family_summaries,
        "grid_output": {"path": _relpath(grid_abs, root), "row_count": len(grid_rows)},
        "position_ledger": {
            "path": _relpath(ledger_abs, root),
            "row_count": len(ledger_rows),
            "complete": _ledger_complete(ledger_rows),
            "delay_rule": "signal and realized volatility are observed at T close; target exposure is effective T+1 or later",
        },
        "guardrails": {
            **_guardrails(),
            "this_report_does_not_unlock_paper_runner": True,
            "this_report_does_not_unlock_live_trading": True,
            "volatility_position_is_research_only": True,
        },
        "blockers": [],
        "recommendations": _recommendations(family_summaries),
    }
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _selected_specs(*, top_report: Mapping[str, Any], specs_by_id: Mapping[str, CandidateSpec]) -> list[CandidateSpec]:
    specs = []
    for row in top_report.get("candidate_summaries", []):
        item = _mapping(row)
        if str(item.get("validation_status", "")) != "research_validation_passed":
            continue
        spec = specs_by_id.get(str(item.get("candidate_id", "")))
        if spec is not None:
            specs.append(spec)
    return specs


def _evaluate_vol_variant(
    *,
    spec: CandidateSpec,
    raw_signal: pd.Series,
    returns: pd.Series,
    realized_vol: pd.Series,
    initial_capital: float,
    cost_bps: float,
    delay_days: int,
    vol_window: int,
    target_vol: float,
) -> dict[str, Any]:
    scalar = (float(target_vol) / realized_vol).replace([math.inf, -math.inf], 0.0).fillna(0.0)
    target_raw_exposure = (raw_signal * scalar).clip(0.0, MAX_EXPOSURE)
    exposure = target_raw_exposure.shift(int(delay_days)).fillna(0.0).clip(0.0, MAX_EXPOSURE)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = _performance(
        strategy_returns=strategy_returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
    )
    variant_id = f"{spec.candidate_id}_vol{int(float(target_vol) * 100)}_w{int(vol_window)}"
    return {
        "family_id": spec.family_id,
        "base_candidate_id": spec.candidate_id,
        "variant_id": variant_id,
        "base_params": spec.params,
        "vol_window": int(vol_window),
        "target_vol": float(target_vol),
        "raw_signal": raw_signal,
        "realized_vol": realized_vol,
        "target_raw_exposure": target_raw_exposure,
        "exposure": exposure,
        "turnover": turnover,
        "cost": cost,
        "strategy_returns": strategy_returns,
        "equity": equity,
        "metrics": metrics,
    }


def _select_family_variants(
    variants: list[Mapping[str, Any]],
    *,
    baseline_by_id: Mapping[str, EvaluatedCandidate],
) -> dict[str, Mapping[str, Any]]:
    selected = {}
    for family_id in sorted({str(row["family_id"]) for row in variants}):
        rows = [row for row in variants if str(row["family_id"]) == family_id]
        selected[family_id] = max(rows, key=lambda row: (_vol_score(row, baseline_by_id=baseline_by_id), str(row["variant_id"])))
    return selected


def _vol_score(row: Mapping[str, Any], *, baseline_by_id: Mapping[str, EvaluatedCandidate]) -> float:
    metrics = _mapping(row.get("metrics"))
    baseline = baseline_by_id[str(row["base_candidate_id"])].metrics
    sharpe = _float(metrics, "sharpe_ratio")
    annual_return = _float(metrics, "annual_return_pct")
    drawdown = _float(metrics, "max_drawdown_abs_pct")
    annual_vol = _float(metrics, "annual_volatility_pct")
    avg_exp = _float(metrics, "average_exposure")
    ret = _float(metrics, "total_return_pct")
    base_dd = _float(baseline, "max_drawdown_abs_pct")
    base_vol = _float(baseline, "annual_volatility_pct")
    low_exposure_penalty = 40.0 if avg_exp < 0.05 else 0.0
    negative_return_penalty = 60.0 if ret <= 0.0 else 0.0
    risk_reduction_bonus = max(0.0, base_dd - drawdown) * 0.35 + max(0.0, base_vol - annual_vol) * 0.25
    return round(annual_return + 12.0 * sharpe - 0.55 * drawdown - 0.15 * annual_vol + risk_reduction_bonus - low_exposure_penalty - negative_return_penalty, 6)


def _grid_row(row: Mapping[str, Any], *, baseline: EvaluatedCandidate) -> dict[str, Any]:
    metrics = _mapping(row.get("metrics"))
    base = baseline.metrics
    return {
        "family_id": row["family_id"],
        "base_candidate_id": row["base_candidate_id"],
        "variant_id": row["variant_id"],
        "vol_window": row["vol_window"],
        "target_vol": row["target_vol"],
        "score": _vol_score(row, baseline_by_id={baseline.spec.candidate_id: baseline}),
        "total_return_pct": metrics["total_return_pct"],
        "annual_return_pct": metrics["annual_return_pct"],
        "annual_volatility_pct": metrics["annual_volatility_pct"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
        "average_exposure": metrics["average_exposure"],
        "turnover": metrics["turnover"],
        "exposure_change_count": metrics["exposure_change_count"],
        "baseline_total_return_pct": base["total_return_pct"],
        "baseline_annual_volatility_pct": base["annual_volatility_pct"],
        "baseline_max_drawdown_abs_pct": base["max_drawdown_abs_pct"],
        "baseline_sharpe_ratio": base["sharpe_ratio"],
        "return_diff_vs_baseline_pct": _round(_float(metrics, "total_return_pct") - _float(base, "total_return_pct")),
        "volatility_reduction_vs_baseline_pct": _round(_float(base, "annual_volatility_pct") - _float(metrics, "annual_volatility_pct")),
        "drawdown_reduction_vs_baseline_pct": _round(_float(base, "max_drawdown_abs_pct") - _float(metrics, "max_drawdown_abs_pct")),
        "sharpe_diff_vs_baseline": _round(_float(metrics, "sharpe_ratio") - _float(base, "sharpe_ratio")),
    }


def _family_summary(
    *,
    spec: CandidateSpec,
    baseline: EvaluatedCandidate,
    selected: Mapping[str, Any],
    variants: list[Mapping[str, Any]],
) -> dict[str, Any]:
    selected_metrics = _mapping(selected.get("metrics"))
    baseline_metrics = baseline.metrics
    improved_sharpe = sum(1 for row in variants if _float(_mapping(row.get("metrics")), "sharpe_ratio") > _float(baseline_metrics, "sharpe_ratio"))
    lower_dd = sum(1 for row in variants if _float(_mapping(row.get("metrics")), "max_drawdown_abs_pct") < _float(baseline_metrics, "max_drawdown_abs_pct"))
    lower_vol = sum(1 for row in variants if _float(_mapping(row.get("metrics")), "annual_volatility_pct") < _float(baseline_metrics, "annual_volatility_pct"))
    return {
        "family_id": spec.family_id,
        "base_candidate_id": spec.candidate_id,
        "base_params": spec.params,
        "baseline_metrics": baseline_metrics,
        "variant_count": len(variants),
        "selected_variant": {
            "variant_id": selected["variant_id"],
            "vol_window": selected["vol_window"],
            "target_vol": selected["target_vol"],
            "score": _vol_score(selected, baseline_by_id={baseline.spec.candidate_id: baseline}),
            "metrics": selected_metrics,
            "return_diff_vs_baseline_pct": _round(_float(selected_metrics, "total_return_pct") - _float(baseline_metrics, "total_return_pct")),
            "volatility_reduction_vs_baseline_pct": _round(_float(baseline_metrics, "annual_volatility_pct") - _float(selected_metrics, "annual_volatility_pct")),
            "drawdown_reduction_vs_baseline_pct": _round(_float(baseline_metrics, "max_drawdown_abs_pct") - _float(selected_metrics, "max_drawdown_abs_pct")),
            "sharpe_diff_vs_baseline": _round(_float(selected_metrics, "sharpe_ratio") - _float(baseline_metrics, "sharpe_ratio")),
        },
        "improved_sharpe_share": _round(improved_sharpe / len(variants)) if variants else 0.0,
        "lower_drawdown_share": _round(lower_dd / len(variants)) if variants else 0.0,
        "lower_volatility_share": _round(lower_vol / len(variants)) if variants else 0.0,
    }


def _ledger_rows(
    *,
    selected_variants: Mapping[str, Mapping[str, Any]],
    close: pd.Series,
    returns: pd.Series,
    cost_bps: float,
    delay_days: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    index = list(close.index)
    for family_id, variant in selected_variants.items():
        raw_signal = variant["raw_signal"]
        realized_vol = variant["realized_vol"]
        target_raw = variant["target_raw_exposure"]
        exposure = variant["exposure"]
        turnover = variant["turnover"]
        strategy_returns = variant["strategy_returns"]
        equity = variant["equity"]
        for i, timestamp in enumerate(index):
            source_i = i - int(delay_days)
            source_ts = index[source_i] if source_i >= 0 else None
            rows.append(
                {
                    "timestamp": _timestamp_text(timestamp),
                    "family_id": family_id,
                    "base_candidate_id": variant["base_candidate_id"],
                    "variant_id": variant["variant_id"],
                    "vol_window": variant["vol_window"],
                    "target_vol": variant["target_vol"],
                    "close": _round(float(close.iloc[i])),
                    "daily_return": _round(float(returns.iloc[i]), 10),
                    "raw_signal": _round(float(raw_signal.iloc[source_i]), 10) if source_i >= 0 else 0.0,
                    "realized_vol": _round(float(realized_vol.iloc[source_i]), 10) if source_i >= 0 and not pd.isna(realized_vol.iloc[source_i]) else 0.0,
                    "target_raw_exposure": _round(float(target_raw.iloc[source_i]), 10) if source_i >= 0 else 0.0,
                    "signal_timestamp": _timestamp_text(source_ts) if source_ts is not None else "",
                    "effective_timestamp": _timestamp_text(timestamp),
                    "exposure": _round(float(exposure.iloc[i]), 10),
                    "turnover": _round(float(turnover.iloc[i]), 10),
                    "cost_bps": float(cost_bps),
                    "strategy_daily_return": _round(float(strategy_returns.iloc[i]), 10),
                    "equity": _round(float(equity.iloc[i])),
                    "reason": _ledger_reason(source_ts=source_ts, turnover=float(turnover.iloc[i]), exposure=float(exposure.iloc[i])),
                }
            )
    return rows


def _ledger_reason(*, source_ts: pd.Timestamp | None, turnover: float, exposure: float) -> str:
    if source_ts is None:
        return "warming_up_no_effective_signal"
    if turnover > 1e-12:
        return "volatility_target_exposure_changed"
    if exposure > 0.0:
        return "hold_volatility_target_exposure"
    return "flat_prior_effective_signal"


def _ledger_complete(rows: list[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    required = set(_ledger_fieldnames())
    return all(required.issubset(row.keys()) and str(row.get("reason", "")).strip() for row in rows)


def _blocked_payload(
    *,
    generated: str,
    root: Path,
    bundle_abs: Path,
    top_abs: Path,
    grid_abs: Path,
    ledger_abs: Path,
    daily: pd.DataFrame,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "volatility_position_blocked",
        "decision": "do_not_build_volatility_position_candidates",
        "asset": "btc",
        "symbol": SYMBOL,
        "bundle_dir": _relpath(bundle_abs, root),
        "top_validation_report": _relpath(top_abs, root),
        "data": _data_section(daily),
        "parameters": {"vol_windows": VOL_WINDOWS, "target_vols": TARGET_VOLS},
        "family_summaries": [],
        "grid_output": {"path": _relpath(grid_abs, root), "row_count": 0},
        "position_ledger": {"path": _relpath(ledger_abs, root), "row_count": 0, "complete": False},
        "guardrails": {**_guardrails(), "this_report_does_not_unlock_live_trading": True},
        "blockers": _dedupe(blockers),
        "recommendations": ["前置 top 策略验证或历史长度不足，不生成波动率仓位候选。"],
    }


def _data_section(daily: pd.DataFrame) -> dict[str, Any]:
    return {
        "daily_rows": int(len(daily)),
        "start": _timestamp_text(daily.index.min()) if len(daily) else "",
        "end": _timestamp_text(daily.index.max()) if len(daily) else "",
        "source": "OKX public local spot daily bundle",
    }


def _recommendations(family_summaries: list[Mapping[str, Any]]) -> list[str]:
    if not family_summaries:
        return ["没有可用波动率仓位候选。"]
    best = max(family_summaries, key=lambda row: _float(_mapping(_mapping(row).get("selected_variant")), "sharpe_diff_vs_baseline"))
    selected = _mapping(best.get("selected_variant"))
    return [
        "波动率仓位层已完成研究评估；它不改变趋势信号，只动态调整仓位。",
        f"Sharpe 改善最大的策略族是 `{best.get('family_id', '')}`，selected target_vol={selected.get('target_vol')}，vol_window={selected.get('vol_window')}。",
        "下一步应人工审阅收益牺牲是否可接受，再决定是否把某个波动率仓位版本加入 forward observation。",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    data = _mapping(payload.get("data"))
    lines = [
        "# BTC 趋势波动率仓位报告",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
    ]
    if payload.get("status") == "volatility_position_blocked":
        lines.append("波动率仓位研究被阻断。")
        lines.append("")
        for blocker in payload.get("blockers", []):
            lines.append(f"- `{blocker}`")
        lines.append("")
        return "\n".join(lines)
    lines += [
        "本报告对已通过 top 策略验证的 BTC 日线趋势候选增加波动率目标仓位层。",
        "规则：`target_raw_exposure = raw_signal * target_vol / realized_vol`，T+1 生效，最大仓位 100%。",
        "",
        "## 数据",
        "",
        "| 项目 | 数值 |",
        "| --- | ---: |",
        f"| 日线行数 | {data.get('daily_rows', 0)} |",
        f"| 开始 | {data.get('start', '')} |",
        f"| 结束 | {data.get('end', '')} |",
        "",
        "## 策略族对比",
        "",
        "| 策略族 | 原收益 | 原波动 | 原回撤 | 原Sharpe | 目标波动 | vol窗口 | 新收益 | 新波动 | 新回撤 | 新Sharpe | 收益差 | 波动下降 | 回撤下降 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("family_summaries", []):
        item = _mapping(row)
        base = _mapping(item.get("baseline_metrics"))
        selected = _mapping(item.get("selected_variant"))
        metrics = _mapping(selected.get("metrics"))
        lines.append(
            f"| {item.get('family_id', '')} | {base.get('total_return_pct', 0)}% | "
            f"{base.get('annual_volatility_pct', 0)}% | {base.get('max_drawdown_abs_pct', 0)}% | {base.get('sharpe_ratio', 0)} | "
            f"{selected.get('target_vol', 0)} | {selected.get('vol_window', 0)} | "
            f"{metrics.get('total_return_pct', 0)}% | {metrics.get('annual_volatility_pct', 0)}% | "
            f"{metrics.get('max_drawdown_abs_pct', 0)}% | {metrics.get('sharpe_ratio', 0)} | "
            f"{selected.get('return_diff_vs_baseline_pct', 0)}% | "
            f"{selected.get('volatility_reduction_vs_baseline_pct', 0)}% | "
            f"{selected.get('drawdown_reduction_vs_baseline_pct', 0)}% |"
        )
    lines += [
        "",
        "## 输出",
        "",
        f"- 参数网格：`{_mapping(payload.get('grid_output')).get('path', '')}`",
        f"- 仓位 ledger：`{_mapping(payload.get('position_ledger')).get('path', '')}`",
        "",
        "## 下一步",
        "",
    ]
    for note in payload.get("recommendations", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _grid_fieldnames() -> list[str]:
    return [
        "family_id",
        "base_candidate_id",
        "variant_id",
        "vol_window",
        "target_vol",
        "score",
        "total_return_pct",
        "annual_return_pct",
        "annual_volatility_pct",
        "sharpe_ratio",
        "max_drawdown_abs_pct",
        "average_exposure",
        "turnover",
        "exposure_change_count",
        "baseline_total_return_pct",
        "baseline_annual_volatility_pct",
        "baseline_max_drawdown_abs_pct",
        "baseline_sharpe_ratio",
        "return_diff_vs_baseline_pct",
        "volatility_reduction_vs_baseline_pct",
        "drawdown_reduction_vs_baseline_pct",
        "sharpe_diff_vs_baseline",
    ]


def _ledger_fieldnames() -> list[str]:
    return [
        "timestamp",
        "family_id",
        "base_candidate_id",
        "variant_id",
        "vol_window",
        "target_vol",
        "close",
        "daily_return",
        "raw_signal",
        "realized_vol",
        "target_raw_exposure",
        "signal_timestamp",
        "effective_timestamp",
        "exposure",
        "turnover",
        "cost_bps",
        "strategy_daily_return",
        "equity",
        "reason",
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
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC trend volatility-position sizing report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--top-validation-report", default=str(DEFAULT_TOP_VALIDATION_REPORT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--grid-output", default=str(DEFAULT_GRID_OUTPUT))
    parser.add_argument("--ledger-output", default=str(DEFAULT_LEDGER_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--initial-capital", type=float, default=25_000.0)
    parser.add_argument("--default-cost-bps", type=float, default=5.0)
    parser.add_argument("--default-delay-days", type=int, default=1)
    parser.add_argument("--minimum-daily-rows", type=int, default=MIN_DAILY_ROWS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_trend_volatility_position_report(
        repo_root=Path(args.repo_root),
        bundle_dir=Path(args.bundle_dir),
        top_validation_report=Path(args.top_validation_report),
        output=Path(args.output),
        grid_output=Path(args.grid_output),
        ledger_output=Path(args.ledger_output),
        markdown_output=Path(args.markdown_output),
        initial_capital=float(args.initial_capital),
        default_cost_bps=float(args.default_cost_bps),
        default_delay_days=int(args.default_delay_days),
        minimum_daily_rows=int(args.minimum_daily_rows),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
