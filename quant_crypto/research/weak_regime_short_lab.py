from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from quant_crypto.research.multi_timeframe_rule_lab import (
    BASE_COST_BPS,
    INITIAL_CAPITAL,
    aggregate_ohlcv_calendar,
    performance_metrics,
)
from quant_crypto.research.simple_trend_rule_lab import (
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    SYMBOL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)


SCHEMA_VERSION = "btc_weak_regime_short_lab_v1"
SOURCE_INTERVAL = "1h"
BASE_INTERVAL = "4h"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_weak_regime_short_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_weak_regime_short_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_weak_regime_short_lab_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_weak_regime_short_lab_summary_cn.md"

MIN_4H_BARS = 900
MIN_1D_BARS = 180
FUNDING_INTERVAL_HOURS = 8.0
BAR_HOURS = 4.0


@dataclass(frozen=True)
class WeakShortSpec:
    family_id: str
    variant_id: str
    label: str
    params: dict[str, Any]
    direction_policy: str
    instrument_assumption: str
    optimization_stage: str
    components: list[str]
    notes: list[str]

    @property
    def branch(self) -> str:
        if self.direction_policy in {"short_flat", "long_short"}:
            return "short_research"
        return "spot_defensive_research"

    @property
    def candidate_id(self) -> str:
        raw = {
            "family_id": self.family_id,
            "variant_id": self.variant_id,
            "params": self.params,
            "direction_policy": self.direction_policy,
            "instrument_assumption": self.instrument_assumption,
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return f"btc_weak_short_{self.variant_id}_{digest}"


@dataclass
class EvaluatedWeakShortRule:
    spec: WeakShortSpec
    raw_signal: pd.Series
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    trading_cost: pd.Series
    funding_pnl: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]


def build_btc_weak_regime_short_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_path = output_dir / DEFAULT_GRID_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    source_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)

    blockers: list[str] = []
    if len(bars_4h) < MIN_4H_BARS:
        blockers.append("btc_weak_regime_short_lab_insufficient_4h_bars")
    if len(bars_1d) < MIN_1D_BARS:
        blockers.append("btc_weak_regime_short_lab_insufficient_1d_bars")

    specs = weak_regime_short_specs()
    evaluated = [
        evaluate_weak_short_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
        )
        for spec in specs
    ]
    baselines = _baselines(bars_4h=bars_4h, initial_capital=initial_capital, cost_bps=base_cost_bps)
    rows = [
        _grid_row(
            item,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            base_cost_bps=base_cost_bps,
        )
        for item in evaluated
    ]
    ranked = sorted(rows, key=lambda row: (-float(row["score"]), str(row["candidate_id"])))
    short_rows = [row for row in ranked if row["branch"] == "short_research"]
    defensive_rows = [row for row in ranked if row["branch"] == "spot_defensive_research"]
    short_watchlist = _short_research_watchlist(short_rows)
    defensive_watchlist = _defensive_watchlist(defensive_rows)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_weak_regime_short_lab_research_only_no_paper_no_live",
        "scope": "btc_weak_regime_short_and_defensive_research_lab",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "symbol": SYMBOL,
            "exchange": EXCHANGE,
            "source_interval": SOURCE_INTERVAL,
            "base_decision_interval": BASE_INTERVAL,
            "market_1h_rows": int(len(source_1h)),
            "bar_4h_rows": int(len(bars_4h)),
            "bar_1d_rows": int(len(bars_1d)),
            "bar_1w_rows": int(len(bars_1w)),
            "bar_1mo_rows": int(len(bars_1mo)),
            "bar_4h_start": _ts(bars_4h.index.min()) if len(bars_4h) else None,
            "bar_4h_end": _ts(bars_4h.index.max()) if len(bars_4h) else None,
            "derived_timeframes_from_1h": ["4h", "1d", "1w", "1mo"],
            "market_completed_bar_rule": "1h completed bars are the only market source; 4h/1d/1w/1mo are derived from complete 1h chunks",
            "derivatives_available_time_rule": "derivatives features aligned by available_time <= 4h decision_time",
            "derivatives_visible_rows": int(derivatives_4h["funding_rate"].notna().sum()) if "funding_rate" in derivatives_4h else 0,
        },
        "validation_design": {
            "candidate_count": len(specs),
            "candidate_family_count": len({spec.family_id for spec in specs}),
            "weak_market_purpose": "test whether BTC weak regimes should use short research, long-short research, or spot cash defense",
            "execution_rule": "signals are computed at completed 4h decision closes; exposure is shifted to the next 4h bar",
            "short_policy": "short/long-short rows are research-only and can only enter short_research_watchlist",
            "spot_policy": "spot defensive rows may only enter defensive_research_watchlist; no paper queue write",
            "cost_model": {
                "base_cost_bps": float(base_cost_bps),
                "stress_cost_bps": _cost_stress_bps(base_cost_bps),
                "includes_taker_fee_and_slippage": True,
            },
            "funding_model": {
                "enabled_for_perp_research_rows": True,
                "formula": "funding_pnl = -exposure * funding_rate * (4h / 8h)",
                "research_approximation": True,
                "not_sufficient_for_live_or_paper": True,
            },
            "no_lookahead_policy": [
                "all price features use completed 1h bars",
                "all 4h decisions use exposure.shift(1)",
                "derivatives features require available_time <= decision_time",
                "rolling quantiles and z-scores use shifted historical windows",
            ],
        },
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "oms_access_allowed": False,
            "broker_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "short/long-short research requires separate perpetual evidence, liquidation buffer review, and paper gate before any promotion",
        },
        "baselines": baselines,
        "comparison_rows": ranked,
        "short_research_rows": short_rows,
        "spot_defensive_rows": defensive_rows,
        "short_research_watchlist": short_watchlist,
        "defensive_research_watchlist": defensive_watchlist,
        "blockers": blockers,
        "warnings": _warnings(ranked),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }
    _write_csv(grid_path, _grid_fieldnames(), ranked)
    _write_json(report_path, report)
    _write_text(markdown_path, render_weak_regime_short_lab_markdown(report))
    return report


def weak_regime_short_specs() -> list[WeakShortSpec]:
    def spec(
        family_id: str,
        variant_id: str,
        label: str,
        params: dict[str, Any],
        *,
        direction_policy: str,
        instrument: str,
        stage: str,
        components: list[str],
        notes: list[str],
    ) -> WeakShortSpec:
        return WeakShortSpec(family_id, variant_id, label, params, direction_policy, instrument, stage, components, notes)

    return [
        spec(
            "bear_ema_short_flat",
            "bear_ema_short_flat_original",
            "Daily bear plus 4H EMA ribbon short/flat",
            {"signal_type": "bear_ema_short_flat", "use_funding_guard": False, "use_squeeze_guard": False, "use_oi_guard": False},
            direction_policy="short_flat",
            instrument="simulated_usdt_perpetual_research_only",
            stage="original",
            components=[],
            notes=["short only when daily and 4h trend are bearish"],
        ),
        spec(
            "bear_ema_short_flat",
            "bear_ema_short_flat_funding_squeeze_guard",
            "Bear EMA short/flat with funding and squeeze guards",
            {"signal_type": "bear_ema_short_flat", "use_funding_guard": True, "use_squeeze_guard": True, "use_oi_guard": False},
            direction_policy="short_flat",
            instrument="simulated_usdt_perpetual_research_only",
            stage="single_funding_squeeze_guard",
            components=["funding_guard", "long_short_squeeze_guard"],
            notes=["avoid shorting when funding is too negative or short side looks crowded"],
        ),
        spec(
            "donchian_breakdown_short",
            "donchian_breakdown_short_flat_original",
            "Daily bear plus 4H Donchian breakdown short/flat",
            {"signal_type": "donchian_breakdown_short", "entry_window": 72, "exit_window": 36, "use_funding_guard": False, "use_squeeze_guard": False, "use_oi_guard": False},
            direction_policy="short_flat",
            instrument="simulated_usdt_perpetual_research_only",
            stage="original",
            components=[],
            notes=["short 4h downside breakouts only in daily bear regime"],
        ),
        spec(
            "donchian_breakdown_short",
            "donchian_breakdown_short_risk_guard",
            "Donchian breakdown short/flat with funding, OI and squeeze guards",
            {"signal_type": "donchian_breakdown_short", "entry_window": 72, "exit_window": 36, "use_funding_guard": True, "use_squeeze_guard": True, "use_oi_guard": True},
            direction_policy="short_flat",
            instrument="simulated_usdt_perpetual_research_only",
            stage="combo_short_risk_guards",
            components=["funding_guard", "open_interest_acceleration_guard", "long_short_squeeze_guard"],
            notes=["avoid breakdown shorts when derivatives crowding is fragile"],
        ),
        spec(
            "long_short_ema_flip",
            "long_short_ema_flip_original",
            "Daily bull long and daily bear short EMA flip",
            {"signal_type": "long_short_ema_flip", "use_funding_guard": False, "use_squeeze_guard": False, "use_oi_guard": False},
            direction_policy="long_short",
            instrument="simulated_usdt_perpetual_research_only",
            stage="original",
            components=[],
            notes=["research-only long/short switching; never enters spot shortlist"],
        ),
        spec(
            "long_short_ema_flip",
            "long_short_ema_flip_risk_guard",
            "Long/short EMA flip with funding, OI and squeeze guards",
            {"signal_type": "long_short_ema_flip", "use_funding_guard": True, "use_squeeze_guard": True, "use_oi_guard": True},
            direction_policy="long_short",
            instrument="simulated_usdt_perpetual_research_only",
            stage="combo_long_short_risk_guards",
            components=["funding_guard", "open_interest_acceleration_guard", "long_short_squeeze_guard"],
            notes=["long-short switching with derivatives risk filters"],
        ),
        spec(
            "spot_defensive_cash",
            "spot_defensive_bear_cash_original",
            "Spot long/flat defensive cash in bear and high-volatility regimes",
            {"signal_type": "spot_defensive_cash", "use_high_vol_cash": True, "use_monthly_bear_cash": True},
            direction_policy="long_flat",
            instrument="spot_research_only",
            stage="defensive_baseline",
            components=["bear_cash", "high_volatility_cash", "monthly_bear_cash"],
            notes=["defensive spot benchmark; cannot profit from downside"],
        ),
    ]


def evaluate_weak_short_rule(
    spec: WeakShortSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> EvaluatedWeakShortRule:
    close = bars_4h["close"].astype(float)
    raw = raw_weak_short_signal(spec, bars_4h=bars_4h, bars_1d=bars_1d, bars_1w=bars_1w, bars_1mo=bars_1mo, derivatives_4h=derivatives_4h)
    raw = raw.reindex(close.index).fillna(0.0).clip(-1.0, 1.0)
    exposure = raw.shift(1).fillna(0.0).clip(-1.0, 1.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    trading_cost = turnover * (float(cost_bps) / 10_000.0)
    funding_pnl = _funding_pnl(exposure, derivatives_4h) if "perpetual" in spec.instrument_assumption else pd.Series(0.0, index=close.index)
    returns = (exposure * close.pct_change().fillna(0.0) - trading_cost + funding_pnl).fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    metrics = performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=exposure,
        turnover=turnover,
        cost=trading_cost,
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )
    metrics["funding_return_pct"] = _round(float(funding_pnl.sum()) * 100.0)
    metrics["trading_cost_return_pct"] = _round(float(trading_cost.sum()) * -100.0)
    metrics["short_bar_count"] = int((exposure < 0.0).sum())
    metrics["long_bar_count"] = int((exposure > 0.0).sum())
    return EvaluatedWeakShortRule(spec, raw, exposure, returns, turnover, trading_cost, funding_pnl, equity, metrics)


def raw_weak_short_signal(
    spec: WeakShortSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
) -> pd.Series:
    signal_type = str(spec.params["signal_type"])
    if signal_type == "bear_ema_short_flat":
        return _signal_bear_ema_short_flat(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "donchian_breakdown_short":
        return _signal_donchian_breakdown_short(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "long_short_ema_flip":
        return _signal_long_short_ema_flip(bars_4h=bars_4h, bars_1d=bars_1d, derivatives_4h=derivatives_4h, params=spec.params)
    if signal_type == "spot_defensive_cash":
        return _signal_spot_defensive_cash(bars_4h=bars_4h, bars_1d=bars_1d, bars_1mo=bars_1mo, params=spec.params)
    raise ValueError(f"unsupported signal_type: {signal_type}")


def _signal_bear_ema_short_flat(*, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame, derivatives_4h: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    close = bars_4h["close"].astype(float)
    daily_bear = _timeframe_bear(bars_1d, close.index, fast=34, slow=144)
    entry = daily_bear & _ema_ribbon_bear(close)
    exit_signal = (~daily_bear) | (close > _ema(close, 50))
    short_ok = _short_risk_ok(derivatives_4h, close.index, params=params)
    return _stateful_short_flat(entry & short_ok, exit_signal | (~short_ok))


def _signal_donchian_breakdown_short(*, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame, derivatives_4h: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    close = bars_4h["close"].astype(float)
    low = bars_4h["low"].astype(float)
    high = bars_4h["high"].astype(float)
    daily_bear = _timeframe_bear(bars_1d, close.index, fast=34, slow=144)
    entry = daily_bear & (close < low.shift(1).rolling(int(params.get("entry_window", 72))).min())
    exit_signal = (~daily_bear) | (close > high.shift(1).rolling(int(params.get("exit_window", 36))).max())
    short_ok = _short_risk_ok(derivatives_4h, close.index, params=params)
    return _stateful_short_flat(entry & short_ok, exit_signal | (~short_ok))


def _signal_long_short_ema_flip(*, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame, derivatives_4h: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    close = bars_4h["close"].astype(float)
    daily_bull = _timeframe_bull(bars_1d, close.index, fast=50, slow=200)
    daily_bear = _timeframe_bear(bars_1d, close.index, fast=34, slow=144)
    long_entry = daily_bull & _ema_ribbon_long(close)
    long_exit = (~daily_bull) | (close < _ema(close, 100))
    short_ok = _short_risk_ok(derivatives_4h, close.index, params=params)
    short_entry = daily_bear & _ema_ribbon_bear(close) & short_ok
    short_exit = (~daily_bear) | (close > _ema(close, 50)) | (~short_ok)
    return _stateful_long_short(long_entry, long_exit, short_entry, short_exit)


def _signal_spot_defensive_cash(*, bars_4h: pd.DataFrame, bars_1d: pd.DataFrame, bars_1mo: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    close = bars_4h["close"].astype(float)
    daily_bull = _timeframe_bull(bars_1d, close.index, fast=50, slow=200)
    daily_bear = _timeframe_bear(bars_1d, close.index, fast=34, slow=144)
    entry = daily_bull & _ema_ribbon_long(close)
    exit_signal = daily_bear | (close < _ema(close, 100))
    if bool(params.get("use_high_vol_cash", False)):
        high_vol = ~_high_vol_ok(close, window=60)
        entry = entry & (~high_vol)
        exit_signal = exit_signal | high_vol
    if bool(params.get("use_monthly_bear_cash", False)):
        monthly_bear = _timeframe_bear(bars_1mo, close.index, fast=3, slow=10)
        entry = entry & (~monthly_bear)
        exit_signal = exit_signal | monthly_bear
    return _stateful_long_flat(entry, exit_signal)


def _grid_row(
    item: EvaluatedWeakShortRule,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    walk_forward = walk_forward_summary(item, initial_capital=initial_capital)
    annual = annual_summary(item, initial_capital=initial_capital)
    recent = recent_segment_summary(item, initial_capital=initial_capital)
    cost_stress = cost_stress_summary(
        item.spec,
        bars_4h=bars_4h,
        bars_1d=bars_1d,
        bars_1w=bars_1w,
        bars_1mo=bars_1mo,
        derivatives_4h=derivatives_4h,
        initial_capital=initial_capital,
        base_cost_bps=base_cost_bps,
    )
    squeeze = short_squeeze_and_liquidation_diagnostics(item, bars_4h=bars_4h)
    decision = _retention_decision(item, walk_forward=walk_forward, annual=annual, recent=recent, cost_stress=cost_stress, squeeze=squeeze)
    score = _score(item.metrics, walk_forward=walk_forward, annual=annual, recent=recent, cost_stress=cost_stress, squeeze=squeeze)
    return {
        "candidate_id": item.spec.candidate_id,
        "family_id": item.spec.family_id,
        "variant_id": item.spec.variant_id,
        "branch": item.spec.branch,
        "direction_policy": item.spec.direction_policy,
        "instrument_assumption": item.spec.instrument_assumption,
        "optimization_stage": item.spec.optimization_stage,
        "components": item.spec.components,
        "notes": item.spec.notes,
        "params": item.spec.params,
        "params_hash": hashlib.sha1(json.dumps(item.spec.params, sort_keys=True).encode("utf-8")).hexdigest()[:12],
        "label": item.spec.label,
        "total_return_pct": item.metrics["total_return_pct"],
        "annual_return_pct": item.metrics["annual_return_pct"],
        "max_drawdown_pct": item.metrics["max_drawdown_pct"],
        "max_drawdown_abs_pct": item.metrics["max_drawdown_abs_pct"],
        "profit_factor": item.metrics["profit_factor"],
        "sharpe_ratio": item.metrics["sharpe_ratio"],
        "average_exposure": item.metrics["average_exposure"],
        "average_net_exposure": item.metrics["average_net_exposure"],
        "short_bar_count": item.metrics["short_bar_count"],
        "long_bar_count": item.metrics["long_bar_count"],
        "turnover": item.metrics["turnover"],
        "fee_return_pct": item.metrics["fee_return_pct"],
        "funding_return_pct": item.metrics["funding_return_pct"],
        "walk_forward_pass_rate": walk_forward["pass_rate"],
        "annual_pass_rate": annual["pass_rate"],
        "recent_segment_passed": recent["passed"],
        "recent_segment_total_return_pct": recent["metrics"]["total_return_pct"],
        "cost_survival_rate": cost_stress["survival_rate"],
        "score": _round(score),
        "retention_decision": decision,
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
        "walk_forward": walk_forward,
        "annual": annual,
        "recent_segment": recent,
        "cost_stress": cost_stress,
        "short_squeeze_liquidation_diagnostics": squeeze,
    }


def cost_stress_summary(
    spec: WeakShortSpec,
    *,
    bars_4h: pd.DataFrame,
    bars_1d: pd.DataFrame,
    bars_1w: pd.DataFrame,
    bars_1mo: pd.DataFrame,
    derivatives_4h: pd.DataFrame,
    initial_capital: float,
    base_cost_bps: float,
) -> dict[str, Any]:
    if bars_1d.empty:
        bars_1d = _derive_1d_from_4h(bars_4h)
    scenarios = []
    for cost_bps in _cost_stress_bps(base_cost_bps):
        item = evaluate_weak_short_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=cost_bps,
        )
        survives = float(item.metrics["total_return_pct"]) > 0.0 and float(item.metrics["profit_factor"]) >= 1.0
        scenarios.append({"cost_bps": _round(cost_bps), "survives": bool(survives), "metrics": item.metrics})
    survival_count = sum(1 for row in scenarios if row["survives"])
    return {
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "survival_count": survival_count,
        "survival_rate": _round(survival_count / len(scenarios) if scenarios else 0.0),
        "base_survives": bool(scenarios[0]["survives"]) if scenarios else False,
        "cost_2x_survives": bool(scenarios[1]["survives"]) if len(scenarios) > 1 else False,
        "cost_5x_survives": bool(scenarios[2]["survives"]) if len(scenarios) > 2 else False,
    }


def walk_forward_summary(item: EvaluatedWeakShortRule, *, initial_capital: float, fold_count: int = 4) -> dict[str, Any]:
    chunks = _sequential_chunks(item.returns.index, fold_count)
    rows = []
    for idx, chunk in enumerate(chunks, 1):
        if len(chunk) < 20:
            continue
        metrics = _slice_metrics(item, chunk, initial_capital=initial_capital)
        rows.append({"fold": idx, "row_count": int(len(chunk)), "passed": _segment_passed(metrics), "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    return {"fold_count": len(rows), "pass_rate": _round(pass_rate), "folds": rows}


def annual_summary(item: EvaluatedWeakShortRule, *, initial_capital: float) -> dict[str, Any]:
    rows = []
    for year, index in item.returns.groupby(item.returns.index.year).groups.items():
        idx = pd.DatetimeIndex(index)
        if len(idx) < 20:
            continue
        metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
        rows.append({"year": int(year), "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics})
    pass_rate = sum(1 for row in rows if row["passed"]) / len(rows) if rows else 0.0
    positive = [max(0.0, float(row["metrics"]["total_return_pct"])) for row in rows]
    best_share = max(positive) / sum(positive) if sum(positive) > 0.0 else 0.0
    return {"segment_type": "calendar_year", "segment_count": len(rows), "pass_rate": _round(pass_rate), "best_positive_year_share": _round(best_share), "segments": rows}


def recent_segment_summary(item: EvaluatedWeakShortRule, *, initial_capital: float, days: int = 180) -> dict[str, Any]:
    if item.returns.empty:
        metrics = _empty_metrics(initial_capital)
        return {"segment": f"latest_{days}d", "row_count": 0, "passed": False, "metrics": metrics}
    start = item.returns.index.max() - pd.Timedelta(days=days)
    idx = item.returns.index[item.returns.index >= start]
    metrics = _slice_metrics(item, idx, initial_capital=initial_capital)
    return {"segment": f"latest_{days}d", "row_count": int(len(idx)), "passed": _segment_passed(metrics), "metrics": metrics}


def short_squeeze_and_liquidation_diagnostics(item: EvaluatedWeakShortRule, *, bars_4h: pd.DataFrame) -> dict[str, Any]:
    close = bars_4h["close"].astype(float)
    high = bars_4h["high"].astype(float)
    low = bars_4h["low"].astype(float)
    prev = close.shift(1).replace(0.0, math.nan)
    short_idx = item.exposure < 0.0
    long_idx = item.exposure > 0.0
    short_adverse = ((high / prev) - 1.0).where(short_idx).dropna()
    long_adverse = ((prev / low) - 1.0).where(long_idx).dropna()
    max_short = float(short_adverse.max()) if len(short_adverse) else 0.0
    max_long = float(long_adverse.max()) if len(long_adverse) else 0.0
    leverage_checks = []
    for lev in [1.0, 2.0, 3.0]:
        threshold = 0.80 / lev
        breach_count = int((short_adverse >= threshold).sum() + (long_adverse >= threshold).sum())
        leverage_checks.append({"leverage": lev, "adverse_move_threshold_pct": _round(threshold * 100.0), "breach_count": breach_count})
    return {
        "short_exposure_bars": int(short_idx.sum()),
        "long_exposure_bars": int(long_idx.sum()),
        "max_short_intrabar_adverse_pct": _round(max_short * 100.0),
        "max_long_intrabar_adverse_pct": _round(max_long * 100.0),
        "short_squeeze_bar_count_10pct": int((short_adverse >= 0.10).sum()),
        "short_squeeze_bar_count_15pct": int((short_adverse >= 0.15).sum()),
        "hypothetical_liquidation_checks": leverage_checks,
        "research_approximation": True,
    }


def _baselines(*, bars_4h: pd.DataFrame, initial_capital: float, cost_bps: float) -> dict[str, Any]:
    close = bars_4h["close"].astype(float)
    raw_buy_hold = pd.Series(1.0, index=close.index)
    raw_cash = pd.Series(0.0, index=close.index)
    return {
        "buy_hold_spot": _baseline_metrics(raw_buy_hold, close=close, initial_capital=initial_capital, cost_bps=cost_bps),
        "cash": _baseline_metrics(raw_cash, close=close, initial_capital=initial_capital, cost_bps=cost_bps),
    }


def _baseline_metrics(raw: pd.Series, *, close: pd.Series, initial_capital: float, cost_bps: float) -> dict[str, Any]:
    exposure = raw.shift(1).fillna(0.0)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    cost = turnover * (float(cost_bps) / 10_000.0)
    returns = (exposure * close.pct_change().fillna(0.0) - cost).fillna(0.0)
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    return performance_metrics(strategy_returns=returns, equity=equity, exposure=exposure, turnover=turnover, cost=cost, interval=BASE_INTERVAL, initial_capital=initial_capital)


def _funding_pnl(exposure: pd.Series, derivatives_4h: pd.DataFrame) -> pd.Series:
    funding = _numeric_col(derivatives_4h, "funding_rate", exposure.index).fillna(0.0)
    return (-exposure * funding * (BAR_HOURS / FUNDING_INTERVAL_HOURS)).fillna(0.0)


def _short_risk_ok(derivatives: pd.DataFrame, index: pd.DatetimeIndex, *, params: Mapping[str, Any]) -> pd.Series:
    ok = pd.Series(True, index=index)
    if bool(params.get("use_funding_guard", False)):
        funding = _numeric_col(derivatives, "funding_rate", index)
        floor = funding.rolling(180, min_periods=24).quantile(0.20).shift(1)
        ok = ok & ((funding >= floor) | floor.isna() | funding.isna())
    if bool(params.get("use_squeeze_guard", False)):
        long_short = _numeric_col(derivatives, "long_short_ratio", index)
        floor = long_short.rolling(180, min_periods=24).quantile(0.20).shift(1)
        ok = ok & ((long_short >= floor) | floor.isna() | long_short.isna())
    if bool(params.get("use_oi_guard", False)):
        oi = _numeric_col(derivatives, "open_interest_usd", index)
        oi_z = _rolling_z(oi.diff(), window=72)
        ok = ok & ((oi_z <= 2.0) | oi_z.isna())
    return ok.fillna(True).astype(bool)


def _retention_decision(
    item: EvaluatedWeakShortRule,
    *,
    walk_forward: Mapping[str, Any],
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    squeeze: Mapping[str, Any],
) -> str:
    metrics = item.metrics
    if float(metrics["total_return_pct"]) <= 0.0:
        return "reject_non_positive_total_return"
    if float(metrics["profit_factor"]) < 1.05:
        return "defer_profit_factor_too_thin"
    if float(metrics["max_drawdown_abs_pct"]) > 35.0:
        return "defer_drawdown_too_high"
    if float(walk_forward.get("pass_rate", 0.0)) < 0.50:
        return "defer_walk_forward_unstable"
    if not bool(recent.get("passed", False)):
        return "defer_recent_segment_failed"
    if float(annual.get("best_positive_year_share", 0.0)) > 0.70:
        return "defer_year_concentration_review"
    if float(cost_stress.get("survival_rate", 0.0)) < 0.50:
        return "defer_cost_stress_fragile"
    if float(squeeze.get("max_short_intrabar_adverse_pct", 0.0)) > 15.0:
        return "defer_short_squeeze_risk_review"
    return "research_watchlist_only_no_paper_no_live"


def _score(
    metrics: Mapping[str, Any],
    *,
    walk_forward: Mapping[str, Any],
    annual: Mapping[str, Any],
    recent: Mapping[str, Any],
    cost_stress: Mapping[str, Any],
    squeeze: Mapping[str, Any],
) -> float:
    score = float(metrics.get("total_return_pct", 0.0))
    score += 8.0 * float(metrics.get("profit_factor", 0.0))
    score += 12.0 * float(walk_forward.get("pass_rate", 0.0))
    score += 8.0 * float(annual.get("pass_rate", 0.0))
    score += 12.0 if bool(recent.get("passed", False)) else -12.0
    score += 8.0 * float(cost_stress.get("survival_rate", 0.0))
    score -= max(0.0, float(metrics.get("max_drawdown_abs_pct", 0.0)) - 25.0) * 1.2
    score -= max(0.0, float(annual.get("best_positive_year_share", 0.0)) - 0.60) * 25.0
    score -= max(0.0, float(squeeze.get("max_short_intrabar_adverse_pct", 0.0)) - 10.0) * 1.5
    return score


def _short_research_watchlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["retention_decision"] == "research_watchlist_only_no_paper_no_live"][:5]


def _defensive_watchlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["retention_decision"] == "research_watchlist_only_no_paper_no_live"][:3]


def _warnings(rows: list[dict[str, Any]]) -> list[str]:
    warnings = ["btc_weak_regime_short_lab_research_only_no_paper_no_live"]
    if any(row["direction_policy"] in {"short_flat", "long_short"} for row in rows):
        warnings.append("short_or_long_short_requires_perpetual_funding_liquidation_review_before_paper")
    if any(row["recent_segment_passed"] is False for row in rows):
        warnings.append("some_candidates_fail_recent_segment")
    if any(float(row["short_squeeze_liquidation_diagnostics"]["max_short_intrabar_adverse_pct"]) > 10.0 for row in rows):
        warnings.append("short_squeeze_adverse_move_review_required")
    return warnings


def render_weak_regime_short_lab_markdown(report: Mapping[str, Any]) -> str:
    gate = report["gate"]
    lines = [
        "# BTC 弱势/做空研究实验室",
        "",
        f"- 状态：`{report['status']}`",
        f"- 决策：`{report['decision']}`",
        f"- 候选数：`{report['validation_design']['candidate_count']}`",
        f"- 做空观察数：`{len(report['short_research_watchlist'])}`",
        f"- 现货防守观察数：`{len(report['defensive_research_watchlist'])}`",
        f"- 写 paper 队列：`{gate['paper_queue_write_allowed']}`",
        f"- 解锁 live：`{gate['live_unlock_allowed']}`",
        "",
        "## 排名前 10",
        "",
        "| 排名 | 候选 | 方向 | 收益 | 回撤 | PF | 最近分段 | 结论 |",
        "|---:|---|---|---:|---:|---:|---|---|",
    ]
    for idx, row in enumerate(list(report.get("comparison_rows", []))[:10], 1):
        lines.append(
            f"| {idx} | `{row['variant_id']}` | `{row['direction_policy']}` | {row['total_return_pct']} | "
            f"{row['max_drawdown_pct']} | {row['profit_factor']} | `{row['recent_segment_passed']}` | `{row['retention_decision']}` |"
        )
    lines.extend(
        [
            "",
            "## 复核边界",
            "",
            "- 本报告只研究弱势行情下做空/空仓是否值得继续，不写 paper 队列，不解锁 live。",
            "- 做空和 long/short 候选默认是假设 USDT 永续的模拟研究，funding 是近似摊销，不足以支持真实交易。",
            "- 任何做空候选进入 paper 前，必须补齐强平缓冲、funding 账本、交易所深度、强平/挤压归因和人工复核。",
        ]
    )
    return "\n".join(lines) + "\n"


def _slice_metrics(item: EvaluatedWeakShortRule, index: pd.DatetimeIndex, *, initial_capital: float) -> dict[str, Any]:
    returns = item.returns.loc[index]
    equity = float(initial_capital) * (1.0 + returns).cumprod()
    return performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=item.exposure.loc[index],
        turnover=item.turnover.loc[index],
        cost=item.trading_cost.loc[index],
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _segment_passed(metrics: Mapping[str, Any]) -> bool:
    return float(metrics.get("total_return_pct", 0.0)) > 0.0 and float(metrics.get("profit_factor", 0.0)) >= 1.0


def _sequential_chunks(index: pd.DatetimeIndex, count: int) -> list[pd.DatetimeIndex]:
    if len(index) == 0 or count <= 0:
        return []
    size = max(1, len(index) // count)
    chunks = []
    for start in range(0, len(index), size):
        chunk = index[start : start + size]
        if len(chunk):
            chunks.append(pd.DatetimeIndex(chunk))
        if len(chunks) == count:
            break
    return chunks


def _derive_1d_from_4h(bars_4h: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    frame = bars_4h.copy().sort_values("open_time")
    for start, chunk in frame.groupby(pd.Grouper(key="open_time", freq="24h")):
        if len(chunk) != 6:
            continue
        rows.append(
            {
                "open_time": start,
                "close_time": chunk.index.max(),
                "open": float(chunk["open"].iloc[0]),
                "high": float(chunk["high"].max()),
                "low": float(chunk["low"].min()),
                "close": float(chunk["close"].iloc[-1]),
                "volume": float(chunk["volume"].sum()),
            }
        )
    output = pd.DataFrame(rows)
    if output.empty:
        return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])
    output = output.set_index(pd.to_datetime(output["close_time"], utc=True))
    return output[["open_time", "open", "high", "low", "close", "volume"]].sort_index()


def _timeframe_bull(frame: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    return ((fast_ema > slow_ema) & (close > slow_ema)).reindex(index, method="ffill").fillna(False).astype(bool)


def _timeframe_bear(frame: pd.DataFrame, index: pd.DatetimeIndex, *, fast: int, slow: int) -> pd.Series:
    if frame.empty or "close" not in frame:
        return pd.Series(False, index=index)
    close = frame["close"].astype(float)
    fast_ema = _ema(close, fast)
    slow_ema = _ema(close, slow)
    return ((fast_ema < slow_ema) & (close < slow_ema)).reindex(index, method="ffill").fillna(False).astype(bool)


def _ema_ribbon_long(close: pd.Series) -> pd.Series:
    return (_ema(close, 21) > _ema(close, 50)) & (_ema(close, 50) > _ema(close, 100)) & (_ema(close, 100) > _ema(close, 200)) & (close > _ema(close, 200))


def _ema_ribbon_bear(close: pd.Series) -> pd.Series:
    return (_ema(close, 21) < _ema(close, 50)) & (_ema(close, 50) < _ema(close, 100)) & (_ema(close, 100) < _ema(close, 200)) & (close < _ema(close, 200))


def _high_vol_ok(close: pd.Series, *, window: int) -> pd.Series:
    vol = close.pct_change().rolling(window).std(ddof=0)
    cap = vol.rolling(window * 4, min_periods=window).quantile(0.85).shift(1)
    return ((vol <= cap) | cap.isna()).fillna(True).astype(bool)


def _stateful_long_flat(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    out: list[float] = []
    in_position = False
    for ent, ex in zip(entry.fillna(False).astype(bool), exit_signal.fillna(False).astype(bool)):
        if in_position and ex:
            in_position = False
        if not in_position and ent:
            in_position = True
        out.append(1.0 if in_position else 0.0)
    return pd.Series(out, index=entry.index)


def _stateful_short_flat(entry: pd.Series, exit_signal: pd.Series) -> pd.Series:
    return -1.0 * _stateful_long_flat(entry, exit_signal)


def _stateful_long_short(long_entry: pd.Series, long_exit: pd.Series, short_entry: pd.Series, short_exit: pd.Series) -> pd.Series:
    out: list[float] = []
    state = 0.0
    index = long_entry.index
    for le, lx, se, sx in zip(
        long_entry.reindex(index).fillna(False).astype(bool),
        long_exit.reindex(index).fillna(False).astype(bool),
        short_entry.reindex(index).fillna(False).astype(bool),
        short_exit.reindex(index).fillna(False).astype(bool),
    ):
        if state > 0.0 and lx:
            state = 0.0
        if state < 0.0 and sx:
            state = 0.0
        if state == 0.0:
            if le and not se:
                state = 1.0
            elif se and not le:
                state = -1.0
        out.append(state)
    return pd.Series(out, index=index)


def _numeric_col(frame: pd.DataFrame, column: str, index: pd.DatetimeIndex) -> pd.Series:
    if column not in frame:
        return pd.Series(math.nan, index=index)
    return pd.to_numeric(frame[column], errors="coerce").reindex(index)


def _rolling_z(values: pd.Series, *, window: int) -> pd.Series:
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=0)
    return (values - mean) / std.replace(0.0, math.nan)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


def _cost_stress_bps(base_cost_bps: float) -> list[float]:
    return [float(base_cost_bps), float(base_cost_bps) * 2.0, float(base_cost_bps) * 5.0]


def _empty_metrics(initial_capital: float) -> dict[str, Any]:
    return performance_metrics(
        strategy_returns=pd.Series(dtype=float),
        equity=pd.Series(dtype=float),
        exposure=pd.Series(dtype=float),
        turnover=pd.Series(dtype=float),
        cost=pd.Series(dtype=float),
        interval=BASE_INTERVAL,
        initial_capital=initial_capital,
    )


def _guardrails() -> dict[str, bool]:
    return {
        "broker_imported": False,
        "oms_imported": False,
        "paper_runtime_imported": False,
        "live_runtime_imported": False,
        "order_endpoint_used": False,
        "real_order_submitted": False,
        "paper_queue_written": False,
        "private_exchange_endpoint_used": False,
    }


def _grid_fieldnames() -> list[str]:
    return [
        "candidate_id",
        "family_id",
        "variant_id",
        "branch",
        "direction_policy",
        "instrument_assumption",
        "optimization_stage",
        "total_return_pct",
        "max_drawdown_pct",
        "profit_factor",
        "average_exposure",
        "average_net_exposure",
        "short_bar_count",
        "long_bar_count",
        "funding_return_pct",
        "walk_forward_pass_rate",
        "annual_pass_rate",
        "recent_segment_passed",
        "recent_segment_total_return_pct",
        "cost_survival_rate",
        "score",
        "retention_decision",
        "paper_queue_write_allowed",
        "live_unlock_allowed",
    ]


def _write_csv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path.cwd(), text=True).strip()
    except Exception:
        return "unknown"


def _ts(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _round(value: float, digits: int = 6) -> float:
    if not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)
