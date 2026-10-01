#!/usr/bin/env python3
"""Build BTC intraday trend v1 research backtest artifacts.

This branch is intentionally separate from the daily BTC trend forward
observation line and from the rejected 5m HFT candidate. It studies shorter
bar trend following only: 4h/1h primary, 15m/5m exploratory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SCHEMA_VERSION = "btc_intraday_trend_v1_report"
SYMBOL = "BTCUSDT"
EXCHANGE = "binance_spot"
DEFAULT_DB_PATH = Path("data/market_data.sqlite")
DEFAULT_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_intraday_trend_v1_report.json")
DEFAULT_GRID_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_intraday_trend_v1_grid.csv")
DEFAULT_LEDGER_OUTPUT = Path("artifacts/btc_intraday_trend_v1/latest/btc_intraday_trend_v1_position_ledger.csv")
DEFAULT_MARKDOWN_OUTPUT = Path("../学习资料/量化交易业务闭环/系统评估/BTC 小周期趋势 v1 回测报告.md")

INTERVALS = ["4h", "1h", "15m", "5m"]
PRIMARY_INTERVALS = ["4h", "1h"]
EXPLORATORY_INTERVALS = ["15m", "5m"]
MIN_BARS_BY_INTERVAL = {"4h": 900, "1h": 2_500, "15m": 5_000, "5m": 10_000}
BARS_PER_YEAR = {"4h": 6 * 365, "1h": 24 * 365, "15m": 96 * 365, "5m": 288 * 365}
COST_BPS_GRID = [5.0, 10.0, 25.0, 50.0, 100.0]
DEFAULT_COST_BPS = 10.0
DEFAULT_DELAY_BARS = 1
INITIAL_CAPITAL = 25_000.0
MAX_EXPOSURE = 1.0
MIN_MEANINGFUL_AVERAGE_EXPOSURE = 0.08

FAMILIES = [
    "it01_momentum",
    "it02_ma_trend",
    "it03_donchian_breakout",
    "it04_atr_channel_breakout",
    "it05_dual_timeframe_trend_filter",
    "it06_ma_vol_volume_filter",
]

BLOCKED_BOUNDARIES = [
    {
        "scope": "daily_trend_mainline",
        "status": "preserved",
        "reason": "btc_trend_raw_forward_observation remains the main line and is not modified by intraday trend v1",
    },
    {
        "scope": "rejected_5m_hft_candidate",
        "status": "frozen",
        "reason": "btc_pullback_reclaim_intraday_high_vol_non_expansion_trend_guard_v1 remains frozen and is not reused",
    },
    {
        "scope": "true_hft_or_microstructure_scalping",
        "status": "out_of_scope",
        "reason": "requires L2/order-book queue, latency, maker/taker execution and private connector validation",
    },
]


@dataclass(frozen=True)
class CandidateSpec:
    interval: str
    family_id: str
    variant_id: str
    label: str
    params: dict[str, Any]

    @property
    def candidate_id(self) -> str:
        raw = {"interval": self.interval, "family_id": self.family_id, "variant_id": self.variant_id, "params": self.params}
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"{self.interval}_{self.variant_id}_{digest}"


@dataclass
class EvaluatedCandidate:
    spec: CandidateSpec
    raw_signal: pd.Series
    exposure: pd.Series
    turnover: pd.Series
    cost: pd.Series
    strategy_returns: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_intraday_trend_v1_report(
    *,
    repo_root: Path | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    output: Path = DEFAULT_OUTPUT,
    grid_output: Path = DEFAULT_GRID_OUTPUT,
    ledger_output: Path = DEFAULT_LEDGER_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
    exchange: str = EXCHANGE,
    symbol: str = SYMBOL,
    intervals: list[str] | None = None,
    min_bars_by_interval: Mapping[str, int] | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    default_cost_bps: float = DEFAULT_COST_BPS,
    default_delay_bars: int = DEFAULT_DELAY_BARS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = (repo_root or Path.cwd()).resolve()
    db_abs = _resolve(root, db_path)
    output_abs = _resolve(root, output)
    grid_abs = _resolve(root, grid_output)
    ledger_abs = _resolve(root, ledger_output)
    markdown_abs = _resolve(root, markdown_output)
    generated = generated_at or _utc_z_now()
    selected_intervals = intervals or list(INTERVALS)
    min_bars = dict(MIN_BARS_BY_INTERVAL)
    if min_bars_by_interval:
        min_bars.update({str(k): int(v) for k, v in min_bars_by_interval.items()})

    frames = {interval: _load_sqlite_bars(db_abs, exchange=exchange, symbol=symbol, interval=interval) for interval in selected_intervals}
    data_section = _data_section(frames=frames, db_abs=db_abs, root=root, exchange=exchange, symbol=symbol)
    insufficient = [
        {"interval": interval, "rows": int(len(frame)), "minimum_rows": int(min_bars.get(interval, 0))}
        for interval, frame in frames.items()
        if int(len(frame)) < int(min_bars.get(interval, 0))
    ]
    primary_blockers = [row for row in insufficient if row["interval"] in PRIMARY_INTERVALS]
    if primary_blockers:
        payload = _blocked_payload(
            generated=generated,
            root=root,
            db_abs=db_abs,
            data_section=data_section,
            insufficient=insufficient,
            output_abs=output_abs,
            grid_abs=grid_abs,
            ledger_abs=ledger_abs,
        )
        _write_csv(grid_abs, _grid_fieldnames(), [])
        _write_csv(ledger_abs, _ledger_fieldnames(), [])
        _write_json(output_abs, payload)
        _write_text(markdown_abs, _markdown(payload))
        return payload

    all_candidates: list[EvaluatedCandidate] = []
    baselines_by_interval: dict[str, list[EvaluatedCandidate]] = {}
    buy_hold_by_interval: dict[str, Mapping[str, Any]] = {}
    for interval, frame in frames.items():
        if int(len(frame)) < int(min_bars.get(interval, 0)):
            continue
        interval_baselines = [
            _evaluate_spec(
                spec,
                frames=frames,
                initial_capital=initial_capital,
                cost_bps=default_cost_bps,
                delay_bars=default_delay_bars,
            )
            for spec in _baseline_specs(interval)
        ]
        baselines_by_interval[interval] = interval_baselines
        buy_hold_by_interval[interval] = interval_baselines[0].metrics
        all_candidates.extend(
            _evaluate_spec(
                spec,
                frames=frames,
                initial_capital=initial_capital,
                cost_bps=default_cost_bps,
                delay_bars=default_delay_bars,
            )
            for spec in _candidate_specs_for_interval(interval)
        )

    grid_rows = [_grid_row(candidate, buy_hold_metrics=buy_hold_by_interval[candidate.spec.interval]) for candidate in all_candidates]
    family_summaries = _family_summaries(all_candidates, buy_hold_by_interval=buy_hold_by_interval)
    overall_ranking = sorted(grid_rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    selected = _selected_by_interval(all_candidates, buy_hold_by_interval=buy_hold_by_interval)
    ledger_rows = _position_ledger_rows(selected_candidates=selected, cost_bps=default_cost_bps, delay_bars=default_delay_bars)
    cost_stress = _cost_stress(
        selected_candidates=selected,
        frames=frames,
        initial_capital=initial_capital,
        delay_bars=default_delay_bars,
    )
    interval_summaries = _interval_summaries(
        intervals=selected_intervals,
        frames=frames,
        candidates=all_candidates,
        selected=selected,
        buy_hold_by_interval=buy_hold_by_interval,
    )
    status = "research_only_intraday_trend_v1_complete"
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": status,
        "decision": "short_cycle_trend_research_complete_manual_review_required",
        "asset": "btc",
        "symbol": symbol,
        "exchange": exchange,
        "db_path": _relpath(db_abs, root),
        "branch_id": "btc_intraday_trend_v1",
        "data": data_section,
        "primary_intervals": PRIMARY_INTERVALS,
        "exploratory_intervals": EXPLORATORY_INTERVALS,
        "tested_intervals": [interval for interval in selected_intervals if int(len(frames.get(interval, []))) >= int(min_bars.get(interval, 0))],
        "families": FAMILIES,
        "parameters": {
            "default_cost_bps": float(default_cost_bps),
            "default_delay_bars": int(default_delay_bars),
            "cost_bps_grid": COST_BPS_GRID,
            "higher_slippage_shock_bps": [50.0, 100.0],
            "min_bars_by_interval": min_bars,
            "max_exposure": MAX_EXPOSURE,
            "minimum_meaningful_average_exposure": MIN_MEANINGFUL_AVERAGE_EXPOSURE,
            "execution_rule": "signal generated after bar T close; exposure effective at T+1 bar or later",
        },
        "guardrails": _guardrails(),
        "blocked_boundaries": BLOCKED_BOUNDARIES,
        "baseline_performance": [
            _result_row(candidate, buy_hold_metrics=buy_hold_by_interval[candidate.spec.interval])
            for candidates in baselines_by_interval.values()
            for candidate in candidates
        ],
        "interval_summaries": interval_summaries,
        "family_summaries": family_summaries,
        "overall_ranking": overall_ranking[:50],
        "selected_candidates": [
            _result_row(candidate, buy_hold_metrics=buy_hold_by_interval[candidate.spec.interval])
            for candidate in selected
        ],
        "cost_stress": cost_stress,
        "grid_output": {"path": _relpath(grid_abs, root), "row_count": len(grid_rows)},
        "position_ledger": {
            "path": _relpath(ledger_abs, root),
            "row_count": len(ledger_rows),
            "complete": _ledger_complete(ledger_rows),
            "scope": "selected_top_candidate_per_interval_only",
            "delay_rule": "signal generated after bar T close; exposure effective at T+1 bar or later",
        },
        "recommendations": _recommendations(selected, buy_hold_by_interval=buy_hold_by_interval),
        "blockers": [],
    }
    _write_csv(grid_abs, _grid_fieldnames(), grid_rows)
    _write_csv(ledger_abs, _ledger_fieldnames(), ledger_rows)
    _write_json(output_abs, payload)
    _write_text(markdown_abs, _markdown(payload))
    return payload


def _candidate_specs_for_interval(interval: str) -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []
    specs.extend(_momentum_specs(interval))
    specs.extend(_ma_specs(interval))
    specs.extend(_donchian_specs(interval))
    specs.extend(_atr_channel_specs(interval))
    specs.extend(_dual_timeframe_specs(interval))
    specs.extend(_vol_volume_filter_specs(interval))
    return specs


def _baseline_specs(interval: str) -> list[CandidateSpec]:
    return [
        CandidateSpec(interval, "baseline", "buy_hold_btc", "Buy and hold BTC on interval bars", {"signal_type": "buy_hold"}),
        CandidateSpec(interval, "baseline", "fixed_50pct_btc", "Fixed 50% BTC exposure", {"signal_type": "fixed_50pct"}),
    ]


def _momentum_specs(interval: str) -> list[CandidateSpec]:
    windows = {
        "4h": [42, 84, 168],
        "1h": [72, 168, 360],
        "15m": [96, 192, 384],
        "5m": [144, 288, 576],
    }.get(interval, [72, 168, 360])
    return [
        CandidateSpec(
            interval,
            "it01_momentum",
            "it01_momentum_binary",
            f"{interval} momentum binary trend",
            {"signal_type": "momentum", "momentum_window": window},
        )
        for window in windows
    ]


def _ma_specs(interval: str) -> list[CandidateSpec]:
    pairs = {
        "4h": [(12, 48), (24, 96), (48, 168)],
        "1h": [(24, 120), (48, 240), (96, 480)],
        "15m": [(48, 192), (96, 384), (192, 768)],
        "5m": [(72, 288), (144, 576), (288, 1152)],
    }.get(interval, [(24, 120), (48, 240)])
    return [
        CandidateSpec(
            interval,
            "it02_ma_trend",
            "it02_ma_binary",
            f"{interval} moving average trend",
            {"signal_type": "ma", "ma_fast": fast, "ma_slow": slow},
        )
        for fast, slow in pairs
    ]


def _donchian_specs(interval: str) -> list[CandidateSpec]:
    windows = {
        "4h": [(24, 12), (48, 24), (96, 48)],
        "1h": [(48, 24), (120, 48), (240, 96)],
        "15m": [(96, 48), (192, 96), (384, 192)],
        "5m": [(144, 72), (288, 144), (576, 288)],
    }.get(interval, [(48, 24), (120, 48)])
    return [
        CandidateSpec(
            interval,
            "it03_donchian_breakout",
            "it03_donchian_binary",
            f"{interval} Donchian breakout",
            {"signal_type": "donchian", "entry_window": entry, "exit_window": exit_window},
        )
        for entry, exit_window in windows
    ]


def _atr_channel_specs(interval: str) -> list[CandidateSpec]:
    ma_windows = {"4h": [48, 96], "1h": [120, 240], "15m": [192, 384], "5m": [288, 576]}.get(interval, [120, 240])
    specs = []
    for ma_window in ma_windows:
        for k in [1.5, 2.5]:
            specs.append(
                CandidateSpec(
                    interval,
                    "it04_atr_channel_breakout",
                    "it04_atr_channel_binary",
                    f"{interval} ATR channel breakout",
                    {"signal_type": "atr_channel", "ma_window": ma_window, "atr_window": 20, "k": k},
                )
            )
    return specs


def _dual_timeframe_specs(interval: str) -> list[CandidateSpec]:
    if interval == "1h":
        return [
            CandidateSpec(
                interval,
                "it05_dual_timeframe_trend_filter",
                "it05_1h_with_4h_filter",
                "1h trend with 4h trend filter",
                {"signal_type": "dual_timeframe", "lower_signal": "ma", "filter_interval": "4h", "ma_fast": 48, "ma_slow": 240, "filter_momentum_window": 42},
            )
        ]
    if interval == "15m":
        return [
            CandidateSpec(
                interval,
                "it05_dual_timeframe_trend_filter",
                "it05_15m_with_1h_filter",
                "15m trend with 1h trend filter",
                {"signal_type": "dual_timeframe", "lower_signal": "ma", "filter_interval": "1h", "ma_fast": 96, "ma_slow": 384, "filter_momentum_window": 72},
            )
        ]
    if interval == "5m":
        return [
            CandidateSpec(
                interval,
                "it05_dual_timeframe_trend_filter",
                "it05_5m_with_1h_filter",
                "5m trend with 1h trend filter",
                {"signal_type": "dual_timeframe", "lower_signal": "ma", "filter_interval": "1h", "ma_fast": 144, "ma_slow": 576, "filter_momentum_window": 72},
            )
        ]
    return []


def _vol_volume_filter_specs(interval: str) -> list[CandidateSpec]:
    pairs = {
        "4h": [(24, 96, 60)],
        "1h": [(48, 240, 168)],
        "15m": [(96, 384, 192)],
        "5m": [(144, 576, 288)],
    }.get(interval, [(48, 240, 168)])
    return [
        CandidateSpec(
            interval,
            "it06_ma_vol_volume_filter",
            "it06_ma_vol_volume_filter",
            f"{interval} MA trend with volatility and volume filter",
            {
                "signal_type": "ma_vol_volume_filter",
                "ma_fast": fast,
                "ma_slow": slow,
                "filter_window": filter_window,
                "min_vol_ratio": 0.75,
                "min_volume_ratio": 0.90,
            },
        )
        for fast, slow, filter_window in pairs
    ]


def _evaluate_spec(
    spec: CandidateSpec,
    *,
    frames: Mapping[str, pd.DataFrame],
    initial_capital: float,
    cost_bps: float,
    delay_bars: int,
) -> EvaluatedCandidate:
    frame = frames[spec.interval]
    close = frame["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    raw_signal = _raw_signal(spec, frames=frames).reindex(close.index).fillna(0.0).clip(0.0, MAX_EXPOSURE)
    exposure = raw_signal.shift(int(delay_bars)).fillna(0.0).clip(0.0, MAX_EXPOSURE)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    strategy_returns = (exposure * returns - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + strategy_returns).cumprod()
    metrics = _performance(
        interval=spec.interval,
        strategy_returns=strategy_returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=cost,
    )
    return EvaluatedCandidate(spec, raw_signal, exposure, turnover, cost, strategy_returns, equity, metrics)


def _raw_signal(spec: CandidateSpec, *, frames: Mapping[str, pd.DataFrame]) -> pd.Series:
    frame = frames[spec.interval]
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    returns = close.pct_change().fillna(0.0)
    params = spec.params
    signal_type = str(params.get("signal_type"))
    if signal_type == "buy_hold":
        return pd.Series(1.0, index=close.index)
    if signal_type == "fixed_50pct":
        return pd.Series(0.5, index=close.index)
    if signal_type == "momentum":
        return (close.pct_change(int(params["momentum_window"])) > 0.0).astype(float)
    if signal_type == "ma":
        return _ma_signal(close=close, fast=int(params["ma_fast"]), slow=int(params["ma_slow"]))
    if signal_type == "donchian":
        entry = high > high.shift(1).rolling(int(params["entry_window"])).max()
        exit_ = low < low.shift(1).rolling(int(params["exit_window"])).min()
        return _stateful_long_flat(entry=entry, exit_=exit_)
    if signal_type == "atr_channel":
        atr = _atr(high=high, low=low, close=close, window=int(params["atr_window"]))
        mid = close.rolling(int(params["ma_window"])).mean()
        upper = mid + float(params["k"]) * atr
        lower = mid - float(params["k"]) * atr
        return _stateful_long_flat(entry=close > upper, exit_=close < lower)
    if signal_type == "dual_timeframe":
        lower = _ma_signal(close=close, fast=int(params["ma_fast"]), slow=int(params["ma_slow"]))
        higher_interval = str(params["filter_interval"])
        higher = frames.get(higher_interval, pd.DataFrame())
        if higher.empty:
            return pd.Series(0.0, index=close.index)
        higher_close = higher["close"].astype(float)
        higher_raw = (higher_close.pct_change(int(params["filter_momentum_window"])) > 0.0).astype(float)
        higher_effective = higher_raw.shift(1).fillna(0.0)
        higher_on_lower = higher_effective.reindex(close.index, method="ffill").fillna(0.0)
        return (lower * higher_on_lower).clip(0.0, 1.0)
    if signal_type == "ma_vol_volume_filter":
        base = _ma_signal(close=close, fast=int(params["ma_fast"]), slow=int(params["ma_slow"]))
        window = int(params["filter_window"])
        realized = returns.rolling(window).std(ddof=0)
        vol_ratio = realized / realized.rolling(window).median().replace(0.0, math.nan)
        volume_ratio = volume / volume.rolling(window).median().replace(0.0, math.nan)
        filt = (vol_ratio >= float(params["min_vol_ratio"])) & (volume_ratio >= float(params["min_volume_ratio"]))
        return (base * filt.astype(float)).fillna(0.0)
    raise ValueError(f"Unsupported intraday trend signal_type: {signal_type}")


def _ma_signal(*, close: pd.Series, fast: int, slow: int) -> pd.Series:
    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    return ((fast_ma > slow_ma) & (close > slow_ma)).astype(float)


def _stateful_long_flat(*, entry: pd.Series, exit_: pd.Series) -> pd.Series:
    out = []
    in_pos = False
    for ent, ex in zip(entry.fillna(False).astype(bool), exit_.fillna(False).astype(bool)):
        if in_pos and ex:
            in_pos = False
        if not in_pos and ent:
            in_pos = True
        out.append(1.0 if in_pos else 0.0)
    return pd.Series(out, index=entry.index)


def _atr(*, high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def _performance(
    *,
    interval: str,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
) -> dict[str, Any]:
    if strategy_returns.empty or equity.empty:
        return _empty_metrics()
    first = float(equity.iloc[0])
    total_return = float(equity.iloc[-1] / first - 1.0) if first else 0.0
    elapsed_days = max(1.0, float((equity.index.max() - equity.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    std = float(strategy_returns.std(ddof=0))
    bars_per_year = float(BARS_PER_YEAR.get(interval, 365.0))
    annual_vol = std * math.sqrt(bars_per_year)
    downside = strategy_returns[strategy_returns < 0.0]
    downside_std = float(downside.std(ddof=0)) if len(downside) else 0.0
    downside_vol = downside_std * math.sqrt(bars_per_year)
    sharpe = float(strategy_returns.mean() / std * math.sqrt(bars_per_year)) if std > 0 else 0.0
    sortino = float(strategy_returns.mean() / downside_std * math.sqrt(bars_per_year)) if downside_std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    nonzero = strategy_returns[exposure > 0.0]
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_volatility_pct": _round(annual_vol * 100.0),
        "downside_volatility_pct": _round(downside_vol * 100.0),
        "sharpe_ratio": _round(sharpe),
        "sortino_ratio": _round(sortino),
        "calmar_ratio": _round(calmar),
        "max_drawdown_pct": _round(max_drawdown * 100.0),
        "max_drawdown_abs_pct": _round(abs(max_drawdown) * 100.0),
        "final_equity": _round(float(equity.iloc[-1])),
        "average_exposure": _round(float(exposure.mean())) if len(exposure) else 0.0,
        "max_exposure": _round(float(exposure.max())) if len(exposure) else 0.0,
        "bars_with_exposure": int((exposure > 0.0).sum()),
        "turnover": _round(float(turnover.sum())),
        "exposure_change_count": int((turnover > 1e-12).sum()),
        "fee_return_pct": _round(float(cost.sum()) * 100.0),
        "winning_exposed_bar_pct": _round(float((nonzero > 0.0).mean()) * 100.0) if len(nonzero) else 0.0,
    }


def _score(metrics: Mapping[str, Any], *, buy_hold_metrics: Mapping[str, Any]) -> float:
    annual_return = _float(metrics, "annual_return_pct")
    sharpe = _float(metrics, "sharpe_ratio")
    drawdown = _float(metrics, "max_drawdown_abs_pct")
    turnover = _float(metrics, "turnover")
    fee = _float(metrics, "fee_return_pct")
    average_exposure = _float(metrics, "average_exposure")
    total_return = _float(metrics, "total_return_pct")
    drawdown_reduction = _float(buy_hold_metrics, "max_drawdown_abs_pct") - drawdown
    low_exposure_penalty = 50.0 if average_exposure < MIN_MEANINGFUL_AVERAGE_EXPOSURE else 0.0
    low_return_penalty = 35.0 if total_return <= 0.0 else 0.0
    return round(
        annual_return
        + 8.0 * sharpe
        + 0.15 * drawdown_reduction
        - 0.40 * drawdown
        - 0.02 * turnover
        - 1.25 * fee
        - low_exposure_penalty
        - low_return_penalty,
        6,
    )


def _result_row(candidate: EvaluatedCandidate, *, buy_hold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    metrics = candidate.metrics
    return {
        "candidate_id": candidate.spec.candidate_id,
        "interval": candidate.spec.interval,
        "stage": _stage(candidate.spec.interval),
        "family_id": candidate.spec.family_id,
        "variant_id": candidate.spec.variant_id,
        "label": candidate.spec.label,
        "params": candidate.spec.params,
        "score": _score(metrics, buy_hold_metrics=buy_hold_metrics),
        "metrics": metrics,
        "drawdown_reduction_vs_buy_hold_pct": _round(_float(buy_hold_metrics, "max_drawdown_abs_pct") - _float(metrics, "max_drawdown_abs_pct")),
        "return_diff_vs_buy_hold_pct": _round(_float(metrics, "total_return_pct") - _float(buy_hold_metrics, "total_return_pct")),
    }


def _grid_row(candidate: EvaluatedCandidate, *, buy_hold_metrics: Mapping[str, Any]) -> dict[str, Any]:
    row = _result_row(candidate, buy_hold_metrics=buy_hold_metrics)
    metrics = _mapping(row.get("metrics"))
    return {
        "candidate_id": row["candidate_id"],
        "interval": row["interval"],
        "stage": row["stage"],
        "family_id": row["family_id"],
        "variant_id": row["variant_id"],
        "score": row["score"],
        "params_json": json.dumps(row["params"], sort_keys=True, ensure_ascii=False),
        "total_return_pct": metrics["total_return_pct"],
        "annual_return_pct": metrics["annual_return_pct"],
        "annual_volatility_pct": metrics["annual_volatility_pct"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "sortino_ratio": metrics["sortino_ratio"],
        "max_drawdown_abs_pct": metrics["max_drawdown_abs_pct"],
        "calmar_ratio": metrics["calmar_ratio"],
        "turnover": metrics["turnover"],
        "exposure_change_count": metrics["exposure_change_count"],
        "fee_return_pct": metrics["fee_return_pct"],
        "average_exposure": metrics["average_exposure"],
        "drawdown_reduction_vs_buy_hold_pct": row["drawdown_reduction_vs_buy_hold_pct"],
        "return_diff_vs_buy_hold_pct": row["return_diff_vs_buy_hold_pct"],
    }


def _family_summaries(candidates: list[EvaluatedCandidate], *, buy_hold_by_interval: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for interval in INTERVALS:
        for family in FAMILIES:
            family_candidates = [candidate for candidate in candidates if candidate.spec.interval == interval and candidate.spec.family_id == family]
            if not family_candidates:
                continue
            ranked = sorted(
                [_result_row(candidate, buy_hold_metrics=buy_hold_by_interval[interval]) for candidate in family_candidates],
                key=lambda row: (-float(row["score"]), str(row["candidate_id"])),
            )
            rows.append(
                {
                    "interval": interval,
                    "stage": _stage(interval),
                    "family_id": family,
                    "candidate_count": len(ranked),
                    "selected_candidate": ranked[0],
                    "positive_total_return_share": _round(sum(1 for row in ranked if _float(_mapping(row.get("metrics")), "total_return_pct") > 0.0) / len(ranked)),
                    "top_3": ranked[:3],
                }
            )
    return rows


def _selected_by_interval(candidates: list[EvaluatedCandidate], *, buy_hold_by_interval: Mapping[str, Mapping[str, Any]]) -> list[EvaluatedCandidate]:
    selected = []
    for interval in INTERVALS:
        interval_candidates = [candidate for candidate in candidates if candidate.spec.interval == interval]
        if not interval_candidates:
            continue
        ranked = sorted(
            interval_candidates,
            key=lambda candidate: (-_score(candidate.metrics, buy_hold_metrics=buy_hold_by_interval[interval]), candidate.spec.candidate_id),
        )
        selected.append(ranked[0])
    return selected


def _cost_stress(
    *,
    selected_candidates: list[EvaluatedCandidate],
    frames: Mapping[str, pd.DataFrame],
    initial_capital: float,
    delay_bars: int,
) -> list[dict[str, Any]]:
    rows = []
    for selected in selected_candidates:
        for cost_bps in COST_BPS_GRID:
            evaluated = _evaluate_spec(
                selected.spec,
                frames=frames,
                initial_capital=initial_capital,
                cost_bps=cost_bps,
                delay_bars=delay_bars,
            )
            rows.append(
                {
                    "interval": selected.spec.interval,
                    "stage": _stage(selected.spec.interval),
                    "family_id": selected.spec.family_id,
                    "candidate_id": selected.spec.candidate_id,
                    "cost_bps": cost_bps,
                    "shock_type": "base_cost" if cost_bps <= 25.0 else "higher_slippage_shock",
                    "metrics": evaluated.metrics,
                }
            )
    return rows


def _interval_summaries(
    *,
    intervals: list[str],
    frames: Mapping[str, pd.DataFrame],
    candidates: list[EvaluatedCandidate],
    selected: list[EvaluatedCandidate],
    buy_hold_by_interval: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for interval in intervals:
        frame = frames.get(interval, pd.DataFrame())
        interval_candidates = [candidate for candidate in candidates if candidate.spec.interval == interval]
        selected_candidate = next((candidate for candidate in selected if candidate.spec.interval == interval), None)
        rows.append(
            {
                "interval": interval,
                "stage": _stage(interval),
                "rows": int(len(frame)),
                "start": _timestamp_text(frame.index.min()) if len(frame) else "",
                "end": _timestamp_text(frame.index.max()) if len(frame) else "",
                "candidate_count": len(interval_candidates),
                "selected_candidate": _result_row(selected_candidate, buy_hold_metrics=buy_hold_by_interval[interval]) if selected_candidate is not None else {},
            }
        )
    return rows


def _position_ledger_rows(*, selected_candidates: list[EvaluatedCandidate], cost_bps: float, delay_bars: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in selected_candidates:
        index = list(candidate.equity.index)
        close = candidate.equity.index.to_series().map(lambda _: math.nan)
        # Close is recovered from returns/equity is not possible, so store effective price through raw frame metrics path below.
        del close
        for i, timestamp in enumerate(index):
            source_i = i - int(delay_bars)
            source_ts = index[source_i] if source_i >= 0 else None
            turnover = float(candidate.turnover.iloc[i])
            exposure = float(candidate.exposure.iloc[i])
            rows.append(
                {
                    "timestamp": _timestamp_text(timestamp),
                    "interval": candidate.spec.interval,
                    "candidate_id": candidate.spec.candidate_id,
                    "family_id": candidate.spec.family_id,
                    "variant_id": candidate.spec.variant_id,
                    "raw_signal": _round(float(candidate.raw_signal.iloc[source_i]) if source_i >= 0 else 0.0, 10),
                    "signal_timestamp": _timestamp_text(source_ts) if source_ts is not None else "",
                    "effective_timestamp": _timestamp_text(timestamp),
                    "exposure": _round(exposure, 10),
                    "turnover": _round(turnover, 10),
                    "cost_bps": float(cost_bps),
                    "strategy_bar_return": _round(float(candidate.strategy_returns.iloc[i]), 10),
                    "equity": _round(float(candidate.equity.iloc[i])),
                    "reason": _ledger_reason(source_ts=source_ts, turnover=turnover, exposure=exposure),
                    "params_json": json.dumps(candidate.spec.params, sort_keys=True, ensure_ascii=False),
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


def _load_sqlite_bars(db_path: Path, *, exchange: str, symbol: str, interval: str) -> pd.DataFrame:
    if not db_path.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    query = """
        select open_time, open_time_ms, open, high, low, close, volume, quote_volume, trade_count
        from market_klines
        where exchange = ? and symbol = ? and interval = ?
        order by open_time_ms
    """
    with sqlite3.connect(str(db_path)) as con:
        frame = pd.read_sql_query(query, con, params=(exchange, symbol, interval))
    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["open_time"], utc=True)
    frame = frame.drop_duplicates(subset=["timestamp"]).set_index("timestamp").sort_index()
    return frame[["open", "high", "low", "close", "volume", "quote_volume", "trade_count"]].astype(float)


def _data_section(*, frames: Mapping[str, pd.DataFrame], db_abs: Path, root: Path, exchange: str, symbol: str) -> dict[str, Any]:
    return {
        "source": "local sqlite market_klines",
        "db_path": _relpath(db_abs, root),
        "exchange": exchange,
        "symbol": symbol,
        "intervals": {
            interval: {
                "rows": int(len(frame)),
                "start": _timestamp_text(frame.index.min()) if len(frame) else "",
                "end": _timestamp_text(frame.index.max()) if len(frame) else "",
            }
            for interval, frame in frames.items()
        },
    }


def _blocked_payload(
    *,
    generated: str,
    root: Path,
    db_abs: Path,
    data_section: Mapping[str, Any],
    insufficient: list[dict[str, Any]],
    output_abs: Path,
    grid_abs: Path,
    ledger_abs: Path,
) -> dict[str, Any]:
    del output_abs
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "status": "blocked_insufficient_primary_history",
        "decision": "do_not_rank_intraday_trend_v1",
        "asset": "btc",
        "symbol": SYMBOL,
        "exchange": EXCHANGE,
        "db_path": _relpath(db_abs, root),
        "branch_id": "btc_intraday_trend_v1",
        "data": data_section,
        "primary_intervals": PRIMARY_INTERVALS,
        "exploratory_intervals": EXPLORATORY_INTERVALS,
        "tested_intervals": [],
        "families": FAMILIES,
        "parameters": {"cost_bps_grid": COST_BPS_GRID, "default_delay_bars": DEFAULT_DELAY_BARS},
        "guardrails": _guardrails(),
        "blocked_boundaries": BLOCKED_BOUNDARIES,
        "baseline_performance": [],
        "interval_summaries": [],
        "family_summaries": [],
        "overall_ranking": [],
        "selected_candidates": [],
        "cost_stress": [],
        "grid_output": {"path": _relpath(grid_abs, root), "row_count": 0},
        "position_ledger": {"path": _relpath(ledger_abs, root), "row_count": 0, "complete": False},
        "recommendations": ["4H/1H primary history is insufficient; do not rank short-cycle trend candidates."],
        "blockers": [f"btc_intraday_trend_v1_{row['interval']}_rows_below_minimum" for row in insufficient],
        "insufficient_intervals": insufficient,
    }


def _recommendations(selected: list[EvaluatedCandidate], *, buy_hold_by_interval: Mapping[str, Mapping[str, Any]]) -> list[str]:
    if not selected:
        return ["没有可排名候选。"]
    rows = [_result_row(candidate, buy_hold_metrics=buy_hold_by_interval[candidate.spec.interval]) for candidate in selected]
    rows = sorted(rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    top = rows[0]
    metrics = _mapping(top.get("metrics"))
    return [
        f"短周期趋势 v1 已完成；当前入选得分最高周期是 `{top.get('interval')}`，策略族 `{top.get('family_id')}`。",
        f"最高候选总收益 {metrics.get('total_return_pct', 0)}%，最大回撤 {metrics.get('max_drawdown_abs_pct', 0)}%，Sharpe {metrics.get('sharpe_ratio', 0)}。",
        "这仍是研究排序，不解锁纸盘或实盘；下一步应只对 4H/1H 的前几名做 walk-forward、分段和参数稳定性验证。",
        "15m/5m 仅为 exploratory scout，不能复用旧 5m HFT 冻结候选。",
    ]


def _markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# BTC 小周期趋势 v1 回测报告",
        "",
        f"生成时间：{payload.get('generated_at', '')}",
        "",
        "## 结论",
        "",
        f"状态：`{payload.get('status', '')}`",
        "",
    ]
    if payload.get("status") != "research_only_intraday_trend_v1_complete":
        lines += ["主周期历史不足，不输出候选排名。", ""]
        return "\n".join(lines)
    lines += [
        "本报告新增独立 `btc_intraday_trend_v1` 分支，研究 4H/1H/15m/5m 的小周期趋势，不属于真正 HFT。",
        "",
        "## 周期摘要",
        "",
        "| 周期 | 阶段 | Bar 数 | 候选数 | 入选策略族 | 总收益 | 最大回撤 | Sharpe |",
        "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in payload.get("interval_summaries", []):
        item = _mapping(row)
        selected = _mapping(item.get("selected_candidate"))
        metrics = _mapping(selected.get("metrics"))
        lines.append(
            f"| {item.get('interval', '')} | {item.get('stage', '')} | {item.get('rows', 0)} | {item.get('candidate_count', 0)} | "
            f"{selected.get('family_id', '')} | {metrics.get('total_return_pct', 0)}% | {metrics.get('max_drawdown_abs_pct', 0)}% | {metrics.get('sharpe_ratio', 0)} |"
        )
    lines += [
        "",
        "## 成本压力",
        "",
        "每个入选周期候选均测试 `5 / 10 / 25 / 50 / 100 bps` turnover cost，其中 `50 / 100 bps` 视作更高滑点冲击。",
        "",
        "## 边界",
        "",
        "- 保留当前日线趋势 forward observation 主线。",
        "- 不复用已冻结 5m 高频候选。",
        "- 不调用 private/order/live endpoint。",
        "",
    ]
    for rec in payload.get("recommendations", []):
        lines.append(f"- {rec}")
    return "\n".join(lines)


def _guardrails() -> dict[str, Any]:
    return {
        "research_only": True,
        "branch_separate_from_daily_trend_mainline": True,
        "old_5m_hft_candidate_reused": False,
        "true_hft_claimed": False,
        "paper_runner_allowed": False,
        "live_order_allowed": False,
        "broker_calls_used": False,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
    }


def _stage(interval: str) -> str:
    return "primary" if interval in PRIMARY_INTERVALS else "exploratory"


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "interval",
        "stage",
        "family_id",
        "variant_id",
        "score",
        "params_json",
        "total_return_pct",
        "annual_return_pct",
        "annual_volatility_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown_abs_pct",
        "calmar_ratio",
        "turnover",
        "exposure_change_count",
        "fee_return_pct",
        "average_exposure",
        "drawdown_reduction_vs_buy_hold_pct",
        "return_diff_vs_buy_hold_pct",
    ]


def _ledger_fieldnames() -> list[str]:
    return [
        "timestamp",
        "interval",
        "candidate_id",
        "family_id",
        "variant_id",
        "raw_signal",
        "signal_timestamp",
        "effective_timestamp",
        "exposure",
        "turnover",
        "cost_bps",
        "strategy_bar_return",
        "equity",
        "reason",
        "params_json",
    ]


def _ledger_complete(rows: list[Mapping[str, Any]]) -> bool:
    if not rows:
        return False
    required = set(_ledger_fieldnames())
    return all(required.issubset(row.keys()) and str(row.get("reason", "")).strip() for row in rows)


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_return_pct": 0.0,
        "annual_return_pct": 0.0,
        "annual_volatility_pct": 0.0,
        "downside_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "max_drawdown_abs_pct": 0.0,
        "final_equity": 0.0,
        "average_exposure": 0.0,
        "max_exposure": 0.0,
        "bars_with_exposure": 0,
        "turnover": 0.0,
        "exposure_change_count": 0,
        "fee_return_pct": 0.0,
        "winning_exposed_bar_pct": 0.0,
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else (root / path).resolve()


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(mapping: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(mapping.get(key, default))
    except (TypeError, ValueError):
        return default


def _round(value: float, digits: int = 6) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _timestamp_text(value: Any) -> str:
    if value is None or str(value) == "NaT":
        return ""
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _utc_z_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build BTC intraday trend v1 research report.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--grid-output", default=str(DEFAULT_GRID_OUTPUT))
    parser.add_argument("--ledger-output", default=str(DEFAULT_LEDGER_OUTPUT))
    parser.add_argument("--markdown-output", default=str(DEFAULT_MARKDOWN_OUTPUT))
    parser.add_argument("--exchange", default=EXCHANGE)
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--initial-capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--default-cost-bps", type=float, default=DEFAULT_COST_BPS)
    parser.add_argument("--default-delay-bars", type=int, default=DEFAULT_DELAY_BARS)
    parser.add_argument("--generated-at", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_btc_intraday_trend_v1_report(
        repo_root=Path(args.repo_root),
        db_path=Path(args.db_path),
        output=Path(args.output),
        grid_output=Path(args.grid_output),
        ledger_output=Path(args.ledger_output),
        markdown_output=Path(args.markdown_output),
        exchange=args.exchange,
        symbol=args.symbol,
        initial_capital=float(args.initial_capital),
        default_cost_bps=float(args.default_cost_bps),
        default_delay_bars=int(args.default_delay_bars),
        generated_at=args.generated_at or None,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(payload["status"])


if __name__ == "__main__":
    main()
