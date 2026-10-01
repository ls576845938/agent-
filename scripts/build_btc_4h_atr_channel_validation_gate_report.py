#!/usr/bin/env python3
"""Build the BTC 4H ATR-channel validation gate.

This gate is deliberately stricter than the intraday trend v1 research ranking
and deliberately weaker than any live-readiness gate. It validates the selected
4H ATR channel candidate with fixed parameters, walk-forward slices, calendar
regimes, parameter neighborhood checks, cost stress, and T+1 ledger evidence.
It never unlocks paper or live trading.
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

from scripts.build_btc_intraday_trend_v1_report import (  # noqa: E402
    DEFAULT_COST_BPS,
    DEFAULT_DB_PATH,
    DEFAULT_DELAY_BARS,
    DEFAULT_OUTPUT as DEFAULT_INTRADAY_REPORT,
    INITIAL_CAPITAL,
    CandidateSpec,
    _evaluate_spec,
    _load_sqlite_bars,
    _round,
)


SCHEMA_VERSION = "btc_4h_atr_channel_validation_gate_report_v1"
DEFAULT_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_4h_atr_channel_validation_gate_report.json")
DEFAULT_WALK_FORWARD_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_4h_atr_channel_walk_forward.csv")
DEFAULT_REGIME_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_4h_atr_channel_regime_segments.csv")
DEFAULT_PARAMETER_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_4h_atr_channel_parameter_stability.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 4H ATR 通道趋势验证门槛.md")
DEFAULT_LEDGER = Path("artifacts/btc_intraday_trend_v1/latest/btc_intraday_trend_v1_position_ledger.csv")

EXCHANGE = "binance_spot"
SYMBOL = "BTCUSDT"
INTERVAL = "4h"
FAMILY_ID = "it04_atr_channel_breakout"
VARIANT_ID = "it04_atr_channel_binary"
DEFAULT_PARAMS = {"signal_type": "atr_channel", "ma_window": 96, "atr_window": 20, "k": 1.5}
COST_BPS_GRID = [5.0, 10.0, 25.0, 50.0, 100.0]
PARAMETER_NEIGHBORHOOD = {
    "ma_window": [48, 96, 144],
    "atr_window": [14, 20, 30],
    "k": [1.0, 1.5, 2.0, 2.5],
}
MIN_4H_BARS = 900
MIN_WALK_FORWARD_FOLDS = 4
MIN_WALK_FORWARD_PASS_RATE = 0.50
MIN_PARAMETER_PASS_RATE = 0.50


def build_btc_4h_atr_channel_validation_gate_report(
    *,
    repo_root: Path | None = None,
    intraday_report: Path = DEFAULT_INTRADAY_REPORT,
    db_path: Path = DEFAULT_DB_PATH,
    ledger_path: Path = DEFAULT_LEDGER,
    output: Path = DEFAULT_OUTPUT,
    walk_forward_output: Path = DEFAULT_WALK_FORWARD_OUTPUT,
    regime_output: Path = DEFAULT_REGIME_OUTPUT,
    parameter_output: Path = DEFAULT_PARAMETER_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    generated = generated_at or _utc_z_now()
    intraday_abs = _resolve(root, intraday_report)
    db_abs = _resolve(root, db_path)
    ledger_abs = _resolve(root, ledger_path)
    output_abs = _resolve(root, output)
    walk_abs = _resolve(root, walk_forward_output)
    regime_abs = _resolve(root, regime_output)
    parameter_abs = _resolve(root, parameter_output)
    markdown_abs = _resolve(root, markdown_output)

    blockers: list[str] = []
    intraday = _read_json(intraday_abs)
    if not intraday:
        blockers.append("btc_4h_atr_intraday_research_report_missing")
    if intraday and str(intraday.get("status", "")) != "research_only_intraday_trend_v1_complete":
        blockers.append("btc_4h_atr_intraday_research_not_complete")

    guardrails = _guardrails()
    source_guardrails = _mapping(intraday.get("guardrails")) if intraday else {}
    for key in ("private_endpoint_used", "order_endpoint_used", "live_order_allowed", "real_order_submitted"):
        if bool(source_guardrails.get(key, False)):
            blockers.append(f"btc_4h_atr_source_{key}")

    spec = _default_spec()
    selected = _selected_4h_candidate(intraday)
    if not selected:
        blockers.append("btc_4h_atr_selected_candidate_missing")
    elif str(selected.get("candidate_id", "")) != spec.candidate_id:
        blockers.append("btc_4h_atr_selected_candidate_mismatch")

    frame = _load_sqlite_bars(db_abs, exchange=EXCHANGE, symbol=SYMBOL, interval=INTERVAL)
    if len(frame) < MIN_4H_BARS:
        blockers.append("btc_4h_atr_4h_history_below_minimum")

    walk_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    ledger_checks = _ledger_checks(ledger_abs, spec.candidate_id)
    if not ledger_checks["lookahead_pass"]:
        blockers.append("btc_4h_atr_position_ledger_lookahead_failed")
    if not ledger_checks["reason_pass"]:
        blockers.append("btc_4h_atr_position_ledger_reason_missing")

    selected_metrics: dict[str, Any] = {}
    buy_hold_metrics: dict[str, Any] = {}
    validation_checks: dict[str, bool] = {}
    if not blockers:
        frames = {INTERVAL: frame}
        selected_eval = _evaluate_spec(spec, frames=frames, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
        buy_hold = _evaluate_spec(_buy_hold_spec(), frames=frames, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
        selected_metrics = selected_eval.metrics
        buy_hold_metrics = buy_hold.metrics

        cost_rows = _cost_stress_rows(frame=frame, spec=spec)
        walk_rows = _walk_forward_rows(frame=frame, spec=spec)
        regime_rows = _regime_rows(frame=frame, spec=spec)
        parameter_rows = _parameter_rows(frame=frame)

        cost_25 = _row_for_cost(cost_rows, 25.0)
        cost_50 = _row_for_cost(cost_rows, 50.0)
        walk_pass_rate = _pass_rate(walk_rows)
        parameter_pass_rate = _pass_rate(parameter_rows)
        regime_acceptable_segments = sum(1 for row in regime_rows if row.get("acceptable"))
        validation_checks = {
            "selected_candidate_fixed": str(selected.get("candidate_id", "")) == spec.candidate_id,
            "four_hour_history_ready": len(frame) >= MIN_4H_BARS,
            "cost_25bps_positive": _metric(cost_25, "total_return_pct") > 0.0,
            "cost_25bps_drawdown_below_buy_hold": _metric(cost_25, "max_drawdown_abs_pct") < _metric({"metrics": buy_hold_metrics}, "max_drawdown_abs_pct"),
            "cost_50bps_positive": _metric(cost_50, "total_return_pct") > 0.0,
            "walk_forward_minimum_folds": len(walk_rows) >= MIN_WALK_FORWARD_FOLDS,
            "walk_forward_pass_rate": walk_pass_rate >= MIN_WALK_FORWARD_PASS_RATE,
            "regime_at_least_two_acceptable": regime_acceptable_segments >= 2,
            "parameter_default_present": any(bool(row.get("is_default")) for row in parameter_rows),
            "parameter_pass_rate": parameter_pass_rate >= MIN_PARAMETER_PASS_RATE,
            "ledger_t_plus_one_pass": bool(ledger_checks["lookahead_pass"]),
            "ledger_reason_pass": bool(ledger_checks["reason_pass"]),
            "no_private_or_order_endpoint": not any(bool(source_guardrails.get(key, False)) for key in ("private_endpoint_used", "order_endpoint_used", "live_order_allowed", "real_order_submitted")),
        }
        if not all(validation_checks.values()):
            blockers.extend([f"btc_4h_atr_validation_check_failed:{key}" for key, passed in validation_checks.items() if not passed])

    status = "blocked" if blockers else "research_validation_passed_manual_review_required"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "decision": "manual_review_required_no_paper_no_live" if status != "blocked" else "blocked_keep_research_only",
        "asset": "btc",
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "strategy_id": "btc_4h_atr_channel_breakout",
        "candidate_id": spec.candidate_id,
        "family_id": FAMILY_ID,
        "variant_id": VARIANT_ID,
        "params": dict(DEFAULT_PARAMS),
        "data": {
            "source": "local sqlite market_klines",
            "db_path": _relpath(db_abs, root),
            "rows": int(len(frame)),
            "start": _timestamp_text(frame.index.min()) if len(frame) else "",
            "end": _timestamp_text(frame.index.max()) if len(frame) else "",
            "minimum_rows": MIN_4H_BARS,
        },
        "selected_metrics": selected_metrics,
        "buy_hold_metrics": buy_hold_metrics,
        "validation_checks": validation_checks,
        "cost_stress": cost_rows,
        "walk_forward": {
            "path": _relpath(walk_abs, root),
            "row_count": len(walk_rows),
            "pass_rate": _pass_rate(walk_rows),
            "minimum_pass_rate": MIN_WALK_FORWARD_PASS_RATE,
        },
        "regime_segments": {
            "path": _relpath(regime_abs, root),
            "row_count": len(regime_rows),
            "acceptable_segments": sum(1 for row in regime_rows if row.get("acceptable")),
        },
        "parameter_stability": {
            "path": _relpath(parameter_abs, root),
            "row_count": len(parameter_rows),
            "pass_rate": _pass_rate(parameter_rows),
            "minimum_pass_rate": MIN_PARAMETER_PASS_RATE,
            "neighborhood": PARAMETER_NEIGHBORHOOD,
        },
        "position_ledger_checks": ledger_checks,
        "source_reports": {
            "intraday_trend_v1": _relpath(intraday_abs, root),
            "position_ledger": _relpath(ledger_abs, root),
        },
        "guardrails": guardrails,
        "blockers": _dedupe(blockers),
        "outputs": {
            "json": _relpath(output_abs, root),
            "markdown": _relpath(markdown_abs, root),
            "walk_forward_csv": _relpath(walk_abs, root),
            "regime_csv": _relpath(regime_abs, root),
            "parameter_csv": _relpath(parameter_abs, root),
        },
        "recommendations": [
            "4H ATR channel can remain a second research line if this report stays passed.",
            "Do not start a 4H paper runner until manual review accepts walk-forward, regimes, and parameter stability.",
            "This report does not unlock paper or live trading.",
        ],
    }
    _write_csv(walk_abs, _row_fieldnames(walk_rows), walk_rows)
    _write_csv(regime_abs, _row_fieldnames(regime_rows), regime_rows)
    _write_csv(parameter_abs, _row_fieldnames(parameter_rows), parameter_rows)
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload, walk_rows=walk_rows, regime_rows=regime_rows, parameter_rows=parameter_rows))
    return payload


def _cost_stress_rows(*, frame: pd.DataFrame, spec: CandidateSpec) -> list[dict[str, Any]]:
    rows = []
    frames = {INTERVAL: frame}
    for cost_bps in COST_BPS_GRID:
        evaluated = _evaluate_spec(spec, frames=frames, initial_capital=INITIAL_CAPITAL, cost_bps=cost_bps, delay_bars=DEFAULT_DELAY_BARS)
        rows.append(
            {
                "cost_bps": cost_bps,
                "shock_type": "base_cost" if cost_bps <= 25.0 else "higher_slippage_shock",
                **_flat_metrics(evaluated.metrics),
            }
        )
    return rows


def _walk_forward_rows(*, frame: pd.DataFrame, spec: CandidateSpec) -> list[dict[str, Any]]:
    rows = []
    chunks = _equal_chunks(frame, MIN_WALK_FORWARD_FOLDS)
    for index, fold in enumerate(chunks, start=1):
        if fold.empty:
            continue
        strategy = _evaluate_spec(spec, frames={INTERVAL: fold}, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
        buy_hold = _evaluate_spec(_buy_hold_spec(), frames={INTERVAL: fold}, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
        acceptable = _acceptable_segment(strategy.metrics, buy_hold.metrics, require_positive=True)
        rows.append(
            {
                "fold": index,
                "start": _timestamp_text(fold.index.min()),
                "end": _timestamp_text(fold.index.max()),
                "bar_count": int(len(fold)),
                "acceptable": acceptable,
                "buy_hold_total_return_pct": _round(_float_metric(buy_hold.metrics, "total_return_pct")),
                "buy_hold_max_drawdown_abs_pct": _round(_float_metric(buy_hold.metrics, "max_drawdown_abs_pct")),
                **_flat_metrics(strategy.metrics),
            }
        )
    return rows


def _regime_rows(*, frame: pd.DataFrame, spec: CandidateSpec) -> list[dict[str, Any]]:
    rows = []
    for year, fold in frame.groupby(frame.index.year):
        if fold.empty:
            continue
        strategy = _evaluate_spec(spec, frames={INTERVAL: fold}, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
        buy_hold = _evaluate_spec(_buy_hold_spec(), frames={INTERVAL: fold}, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
        acceptable = _acceptable_segment(strategy.metrics, buy_hold.metrics, require_positive=False)
        rows.append(
            {
                "segment": f"{year}" if len(fold) > 1000 else f"{year} partial",
                "year": int(year),
                "start": _timestamp_text(fold.index.min()),
                "end": _timestamp_text(fold.index.max()),
                "bar_count": int(len(fold)),
                "acceptable": acceptable,
                "buy_hold_total_return_pct": _round(_float_metric(buy_hold.metrics, "total_return_pct")),
                "buy_hold_max_drawdown_abs_pct": _round(_float_metric(buy_hold.metrics, "max_drawdown_abs_pct")),
                **_flat_metrics(strategy.metrics),
            }
        )
    return rows


def _parameter_rows(*, frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    buy_hold = _evaluate_spec(_buy_hold_spec(), frames={INTERVAL: frame}, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
    for ma_window in PARAMETER_NEIGHBORHOOD["ma_window"]:
        for atr_window in PARAMETER_NEIGHBORHOOD["atr_window"]:
            for k in PARAMETER_NEIGHBORHOOD["k"]:
                params = {"signal_type": "atr_channel", "ma_window": ma_window, "atr_window": atr_window, "k": k}
                spec = CandidateSpec(INTERVAL, FAMILY_ID, VARIANT_ID, "4h ATR channel breakout", params)
                evaluated = _evaluate_spec(spec, frames={INTERVAL: frame}, initial_capital=INITIAL_CAPITAL, cost_bps=DEFAULT_COST_BPS, delay_bars=DEFAULT_DELAY_BARS)
                acceptable = _acceptable_parameter(evaluated.metrics, buy_hold.metrics)
                rows.append(
                    {
                        "candidate_id": spec.candidate_id,
                        "ma_window": ma_window,
                        "atr_window": atr_window,
                        "k": k,
                        "is_default": params == DEFAULT_PARAMS,
                        "acceptable": acceptable,
                        "buy_hold_total_return_pct": _round(_float_metric(buy_hold.metrics, "total_return_pct")),
                        "buy_hold_max_drawdown_abs_pct": _round(_float_metric(buy_hold.metrics, "max_drawdown_abs_pct")),
                        **_flat_metrics(evaluated.metrics),
                    }
                )
    return rows


def _acceptable_segment(strategy: Mapping[str, Any], buy_hold: Mapping[str, Any], *, require_positive: bool) -> bool:
    total = _float_metric(strategy, "total_return_pct")
    drawdown = _float_metric(strategy, "max_drawdown_abs_pct")
    buy_hold_drawdown = _float_metric(buy_hold, "max_drawdown_abs_pct")
    return (total > 0.0 or not require_positive) and drawdown <= max(5.0, buy_hold_drawdown)


def _acceptable_parameter(strategy: Mapping[str, Any], buy_hold: Mapping[str, Any]) -> bool:
    return (
        _float_metric(strategy, "total_return_pct") > 0.0
        and _float_metric(strategy, "sharpe_ratio") > 0.25
        and _float_metric(strategy, "max_drawdown_abs_pct") <= max(40.0, _float_metric(buy_hold, "max_drawdown_abs_pct"))
    )


def _equal_chunks(frame: pd.DataFrame, count: int) -> list[pd.DataFrame]:
    if frame.empty:
        return []
    size = max(1, int(math.floor(len(frame) / count)))
    chunks = []
    for i in range(count):
        start = i * size
        end = (i + 1) * size if i < count - 1 else len(frame)
        chunks.append(frame.iloc[start:end].copy())
    return chunks


def _ledger_checks(path: Path, candidate_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "row_count": 0, "candidate_row_count": 0, "lookahead_pass": False, "reason_pass": False, "blockers": ["btc_4h_atr_position_ledger_missing"]}
    row_count = 0
    candidate_rows = 0
    lookahead_pass = True
    reason_pass = True
    change_count = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            if row.get("candidate_id") != candidate_id:
                continue
            candidate_rows += 1
            turnover = _safe_float(row.get("turnover"))
            if turnover > 0.0:
                change_count += 1
                if not row.get("reason"):
                    reason_pass = False
            signal_ts = str(row.get("signal_timestamp", ""))
            effective_ts = str(row.get("effective_timestamp", ""))
            if signal_ts and effective_ts and signal_ts >= effective_ts:
                lookahead_pass = False
    blockers = []
    if candidate_rows == 0:
        blockers.append("btc_4h_atr_position_ledger_candidate_missing")
        lookahead_pass = False
    if not reason_pass:
        blockers.append("btc_4h_atr_position_ledger_reason_missing")
    if not lookahead_pass:
        blockers.append("btc_4h_atr_position_ledger_lookahead_failed")
    return {
        "path": str(path),
        "row_count": row_count,
        "candidate_row_count": candidate_rows,
        "exposure_change_count": change_count,
        "lookahead_pass": lookahead_pass,
        "reason_pass": reason_pass,
        "blockers": blockers,
    }


def _selected_4h_candidate(report: Mapping[str, Any]) -> dict[str, Any]:
    for row in report.get("selected_candidates", []) if isinstance(report.get("selected_candidates"), list) else []:
        item = _mapping(row)
        if item.get("interval") == INTERVAL:
            return item
    return {}


def _default_spec() -> CandidateSpec:
    return CandidateSpec(INTERVAL, FAMILY_ID, VARIANT_ID, "4h ATR channel breakout", dict(DEFAULT_PARAMS))


def _buy_hold_spec() -> CandidateSpec:
    return CandidateSpec(INTERVAL, "baseline", "buy_hold_btc", "Buy and hold BTC on interval bars", {"signal_type": "buy_hold"})


def _row_for_cost(rows: list[Mapping[str, Any]], cost_bps: float) -> dict[str, Any]:
    return next((dict(row) for row in rows if float(row.get("cost_bps", -1.0)) == float(cost_bps)), {})


def _metric(row: Mapping[str, Any], key: str) -> float:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), Mapping) else row
    return _float_metric(_mapping(metrics), key)


def _flat_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    keys = [
        "total_return_pct",
        "annual_return_pct",
        "annual_volatility_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "max_drawdown_abs_pct",
        "average_exposure",
        "turnover",
        "exposure_change_count",
        "fee_return_pct",
    ]
    return {key: _round(_float_metric(metrics, key)) for key in keys}


def _pass_rate(rows: list[Mapping[str, Any]]) -> float:
    if not rows:
        return 0.0
    return _round(sum(1 for row in rows if bool(row.get("acceptable"))) / len(rows))


def _row_fieldnames(rows: list[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return []
    names: list[str] = []
    for row in rows:
        for key in row:
            if key not in names:
                names.append(key)
    return names


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "paper_runner_allowed": False,
        "live_order_allowed": False,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "manual_review_required": True,
        "does_not_unlock_daily_trend_mainline": True,
        "does_not_unlock_5m_hft": True,
    }


def _markdown(payload: Mapping[str, Any], *, walk_rows: list[Mapping[str, Any]], regime_rows: list[Mapping[str, Any]], parameter_rows: list[Mapping[str, Any]]) -> str:
    checks = _mapping(payload.get("validation_checks"))
    selected = _mapping(payload.get("selected_metrics"))
    lines = [
        "# BTC 4H ATR 通道趋势验证门槛",
        "",
        f"生成时间：`{payload.get('generated_at', '')}`",
        "",
        "## 结论",
        "",
        f"- 状态：`{payload.get('status', '')}`",
        f"- 决策：`{payload.get('decision', '')}`",
        f"- 候选：`{payload.get('candidate_id', '')}`",
        f"- 参数：`{json.dumps(payload.get('params', {}), ensure_ascii=False, sort_keys=True)}`",
        f"- 总收益：`{selected.get('total_return_pct', '')}%`",
        f"- 最大回撤：`{selected.get('max_drawdown_abs_pct', '')}%`",
        f"- Sharpe：`{selected.get('sharpe_ratio', '')}`",
        "",
        "本报告只验证 4H ATR channel 作为第二研究线，不解锁纸盘或实盘。",
        "",
        "## 门槛检查",
        "",
        "| 检查 | 结果 |",
        "| --- | --- |",
    ]
    for key, passed in checks.items():
        lines.append(f"| {key} | {'PASS' if passed else 'FAIL'} |")
    lines += [
        "",
        "## Walk-forward",
        "",
        "| Fold | 起始 | 结束 | 收益 | 回撤 | Sharpe | 结果 |",
        "| ---: | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in walk_rows:
        lines.append(f"| {row.get('fold')} | {row.get('start')} | {row.get('end')} | {row.get('total_return_pct')}% | {row.get('max_drawdown_abs_pct')}% | {row.get('sharpe_ratio')} | {'PASS' if row.get('acceptable') else 'FAIL'} |")
    lines += [
        "",
        "## 年度/行情分段",
        "",
        "| 分段 | Bar | 收益 | 回撤 | 买入持有回撤 | 结果 |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in regime_rows:
        lines.append(f"| {row.get('segment')} | {row.get('bar_count')} | {row.get('total_return_pct')}% | {row.get('max_drawdown_abs_pct')}% | {row.get('buy_hold_max_drawdown_abs_pct')}% | {'PASS' if row.get('acceptable') else 'FAIL'} |")
    lines += [
        "",
        "## 参数稳定性",
        "",
        f"- 参数邻域行数：`{len(parameter_rows)}`",
        f"- 通过率：`{_pass_rate(parameter_rows)}`",
        "- 只看稳定性，不用邻域结果替换默认参数。",
        "",
        "## 实盘边界",
        "",
        "- `live_order_allowed=false`",
        "- `paper_runner_allowed=false`",
        "- `private_endpoint_used=false`",
        "- `order_endpoint_used=false`",
        "- 仍需人工审阅后才允许进入任何纸盘设计。",
        "",
    ]
    blockers = payload.get("blockers", [])
    if blockers:
        lines += ["## 阻断项", ""]
        for blocker in blockers:
            lines.append(f"- `{blocker}`")
    return "\n".join(lines)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
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
        with tmp.open("w", encoding="utf-8", newline="") as handle:
            if fieldnames:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow({key: row.get(key, "") for key in fieldnames})
            else:
                handle.write("")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(content + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float_metric(metrics: Mapping[str, Any], key: str) -> float:
    return _safe_float(metrics.get(key))


def _safe_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _timestamp_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC 4H ATR channel validation gate report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--intraday-report", default=str(DEFAULT_INTRADAY_REPORT))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--ledger-path", default=str(DEFAULT_LEDGER))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--walk-forward-output", default=str(DEFAULT_WALK_FORWARD_OUTPUT))
    parser.add_argument("--regime-output", default=str(DEFAULT_REGIME_OUTPUT))
    parser.add_argument("--parameter-output", default=str(DEFAULT_PARAMETER_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_4h_atr_channel_validation_gate_report(
        repo_root=Path(args.repo_root),
        intraday_report=Path(args.intraday_report),
        db_path=Path(args.db_path),
        ledger_path=Path(args.ledger_path),
        output=Path(args.output),
        walk_forward_output=Path(args.walk_forward_output),
        regime_output=Path(args.regime_output),
        parameter_output=Path(args.parameter_output),
        markdown_output=Path(args.markdown_output),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    else:
        print(payload["status"])
    raise SystemExit(0 if payload.get("status") != "blocked" else 2)


if __name__ == "__main__":
    main()
