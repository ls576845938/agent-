from __future__ import annotations

import csv
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.long_short_trend_following_lab import (
    BASE_INTERVAL,
    LongShortTrendSpec,
    aggregate_ohlcv_calendar,
    evaluate_long_short_trend_rule,
    long_short_trend_following_specs,
)
from quant_crypto.research.short_interval_data_refresh import (
    DEFAULT_REPORT_PATH as DEFAULT_DATA_REFRESH_REPORT_PATH,
    load_market_klines_frame,
)
from quant_crypto.research.simple_trend_rule_lab import (
    BASE_COST_BPS,
    DEFAULT_DERIVATIVES_ROWS,
    DEFAULT_MARKET_DB,
    EXCHANGE,
    INITIAL_CAPITAL,
    SYMBOL,
    aggregate_ohlcv,
    align_derivatives_to_index,
    load_market_1h,
)


SCHEMA_VERSION = "btc_small_account_high_yield_lab_v1"
DEFAULT_SOURCE_TOP5_REPORT = Path("artifacts/btc_long_short_top5_review/latest/btc_long_short_top5_review_report.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_small_account_high_yield_lab/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_lab_report.json"
DEFAULT_GRID_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_lab_grid.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_small_account_high_yield_lab_summary_cn.md"
DEFAULT_SAFETY_PATH = DEFAULT_OUTPUT_DIR / "paper_live_safety_status.json"

FIXED_LEVERAGES = (1.0, 1.5, 2.0, 3.0)
VOL_TARGETS = (60.0, 90.0, 120.0)
MAX_LEVERAGE = 3.0
MAX_ACCEPTABLE_DRAWDOWN_ABS_PCT = 40.0
HIGH_RISK_DRAWDOWN_ABS_PCT = 25.0
MIN_RESEARCH_ANNUAL_RETURN_PCT = 60.0
MIN_RESEARCH_PROFIT_FACTOR = 1.15
MIN_LIQUIDATION_BUFFER_BPS = 500.0


@dataclass(frozen=True)
class HighYieldVariant:
    bucket: str
    variant_id: str
    base_variant_id: str
    mode: str
    fixed_leverage: float | None
    target_volatility_pct: float | None
    max_leverage: float
    interval: str
    interval_hours: float
    signal_kind: str


@dataclass
class SimulatedCandidate:
    variant: HighYieldVariant
    exposure: pd.Series
    returns: pd.Series
    turnover: pd.Series
    cost: pd.Series
    funding_pnl: pd.Series
    equity: pd.Series
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]


def build_btc_small_account_high_yield_lab(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    derivatives_rows_path: Path = DEFAULT_DERIVATIVES_ROWS,
    source_top5_report_path: Path = DEFAULT_SOURCE_TOP5_REPORT,
    data_refresh_report_path: Path = DEFAULT_DATA_REFRESH_REPORT_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    initial_capital: float = INITIAL_CAPITAL,
    base_cost_bps: float = BASE_COST_BPS,
    top_n: int = 5,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    grid_path = output_dir / DEFAULT_GRID_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name
    safety_path = output_dir / DEFAULT_SAFETY_PATH.name

    source_1h = load_market_1h(market_db_path)
    bars_4h = aggregate_ohlcv(source_1h, interval_hours=4)
    bars_1d = aggregate_ohlcv(source_1h, interval_hours=24)
    bars_1w = aggregate_ohlcv_calendar(source_1h, timeframe="1w")
    bars_1mo = aggregate_ohlcv_calendar(source_1h, timeframe="1mo")
    derivatives_4h = align_derivatives_to_index(derivatives_rows_path, bars_4h.index)
    top_specs = _top_donchian_specs(source_top5_report_path, top_n=top_n)
    data_refresh = _read_json(data_refresh_report_path) if data_refresh_report_path.exists() else {}
    intraday_enabled = _short_interval_ready(data_refresh)

    blockers: list[str] = []
    if not top_specs:
        blockers.append("btc_high_yield_missing_long_short_top5_specs")

    candidates: list[SimulatedCandidate] = []
    for spec in top_specs:
        base_item = evaluate_long_short_trend_rule(
            spec,
            bars_4h=bars_4h,
            bars_1d=bars_1d,
            bars_1w=bars_1w,
            bars_1mo=bars_1mo,
            derivatives_4h=derivatives_4h,
            initial_capital=initial_capital,
            cost_bps=base_cost_bps,
        )
        for variant in _donchian_variants(spec):
            candidates.append(
                _simulate_candidate(
                    variant,
                    base_signal=base_item.exposure,
                    bars=bars_4h,
                    derivatives=derivatives_4h,
                    initial_capital=initial_capital,
                    cost_bps=base_cost_bps,
                )
            )

    intraday_blockers: list[str] = []
    if intraday_enabled:
        bars_15m = load_market_klines_frame(market_db_path, interval="15m")
        derivatives_15m = align_derivatives_to_index(derivatives_rows_path, bars_15m.index)
        if len(bars_15m) < 500:
            intraday_blockers.append("btc_high_yield_15m_rows_too_short")
        else:
            for variant in _intraday_variants():
                signal = _intraday_signal(bars_15m, kind=variant.signal_kind)
                candidates.append(
                    _simulate_candidate(
                        variant,
                        base_signal=signal.shift(1).fillna(0.0),
                        bars=bars_15m,
                        derivatives=derivatives_15m,
                        initial_capital=initial_capital,
                        cost_bps=base_cost_bps,
                    )
                )
    else:
        intraday_blockers.append("btc_high_yield_short_interval_data_not_ready")

    rows = [_candidate_row(item) for item in candidates]
    rows = sorted(rows, key=lambda row: (-float(row["annual_return_pct"]), float(row["max_drawdown_abs_pct"]), row["variant_id"]))
    watchlist = [row for row in rows if row["retention_decision"] == "retain_high_yield_research_watchlist_only"]
    safety = _safety_status(watchlist=watchlist, blockers=blockers, intraday_blockers=intraday_blockers)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "complete_research_only",
        "decision": "btc_small_account_high_yield_lab_research_only_no_paper_no_live",
        "scope": "small_account_high_yield_research_only",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "derivatives_rows_path": _portable_path(derivatives_rows_path),
            "source_top5_report_path": _portable_path(source_top5_report_path),
            "data_refresh_report_path": _portable_path(data_refresh_report_path),
            "exchange": EXCHANGE,
            "symbol": SYMBOL,
            "base_interval": BASE_INTERVAL,
            "short_interval_status": data_refresh.get("status"),
            "intraday_15m_enabled": bool(intraday_enabled and not intraday_blockers),
        },
        "validation_design": {
            "goal": "high annualized return for small capital with explicit high-risk controls",
            "max_leverage": MAX_LEVERAGE,
            "fixed_leverages": list(FIXED_LEVERAGES),
            "volatility_targets_pct": list(VOL_TARGETS),
            "max_acceptable_drawdown_abs_pct": MAX_ACCEPTABLE_DRAWDOWN_ABS_PCT,
            "high_risk_drawdown_abs_pct": HIGH_RISK_DRAWDOWN_ABS_PCT,
            "shortlist_min_annual_return_pct": MIN_RESEARCH_ANNUAL_RETURN_PCT,
            "shortlist_min_profit_factor": MIN_RESEARCH_PROFIT_FACTOR,
            "min_liquidation_buffer_bps": MIN_LIQUIDATION_BUFFER_BPS,
            "funding_oi_long_short_usage": "risk_filter_only_never_standalone_direction",
            "paper_live_boundary": "research_only_watchlist_only",
        },
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "broker_access_allowed": False,
            "oms_access_allowed": False,
            "strategy_skeleton_generated": False,
            "reason": "high-yield variants are research-only stress tests; leverage results do not unlock paper or live",
        },
        "candidate_rows": rows,
        "high_yield_research_watchlist": watchlist,
        "summary": _summary(rows, watchlist),
        "short_interval_data_refresh": data_refresh,
        "intraday_blockers": intraday_blockers,
        "blockers": blockers,
        "warnings": _warnings(rows, intraday_blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "grid_csv": _portable_path(grid_path),
            "summary_cn": _portable_path(markdown_path),
            "paper_live_safety_status": _portable_path(safety_path),
        },
    }
    _write_json(report_path, report)
    _write_csv(grid_path, _grid_fieldnames(), rows)
    _write_text(markdown_path, render_btc_small_account_high_yield_markdown(report))
    _write_json(safety_path, safety)
    return report


def _top_donchian_specs(source_path: Path, *, top_n: int) -> list[LongShortTrendSpec]:
    spec_by_variant = {spec.variant_id: spec for spec in long_short_trend_following_specs(run_profile="formal_narrow")}
    rows: list[Mapping[str, Any]] = []
    if source_path.exists():
        payload = _read_json(source_path)
        rows = payload.get("candidate_rows") or payload.get("long_short_research_watchlist") or []
    variants = [str(row.get("variant_id", "")) for row in rows if isinstance(row, Mapping)]
    specs = [spec_by_variant[variant] for variant in variants if variant in spec_by_variant]
    if specs:
        return specs[:top_n]
    fallback = [
        spec
        for spec in long_short_trend_following_specs(run_profile="formal_narrow")
        if spec.variant_id
        in {
            "formal_donchian_w240_d50_200_atr20_cd12_fail0_risknone",
            "formal_donchian_w240_d50_200_atr20_cd0_fail0_risknone",
            "formal_donchian_w240_d50_200_atr20_cd6_fail0_risknone",
        }
    ]
    return fallback[:top_n]


def _donchian_variants(spec: LongShortTrendSpec) -> list[HighYieldVariant]:
    variants = [
        HighYieldVariant(
            bucket="donchian_leverage_overlay",
            variant_id=f"hy_{spec.variant_id}_fixed_{str(lev).replace('.', 'p')}x",
            base_variant_id=spec.variant_id,
            mode="fixed_leverage",
            fixed_leverage=lev,
            target_volatility_pct=None,
            max_leverage=lev,
            interval="4h",
            interval_hours=4.0,
            signal_kind="donchian_top5_overlay",
        )
        for lev in FIXED_LEVERAGES
    ]
    variants.extend(
        HighYieldVariant(
            bucket="donchian_leverage_overlay",
            variant_id=f"hy_{spec.variant_id}_vol_target_{int(target)}",
            base_variant_id=spec.variant_id,
            mode="volatility_target",
            fixed_leverage=None,
            target_volatility_pct=target,
            max_leverage=MAX_LEVERAGE,
            interval="4h",
            interval_hours=4.0,
            signal_kind="donchian_top5_overlay",
        )
        for target in VOL_TARGETS
    )
    return variants


def _intraday_variants() -> list[HighYieldVariant]:
    variants: list[HighYieldVariant] = []
    for kind in ("15m_momentum_breakout", "15m_pullback_reentry"):
        for lev in (1.5, 2.0, 3.0):
            variants.append(
                HighYieldVariant(
                    bucket="intraday_15m",
                    variant_id=f"hy_{kind}_{str(lev).replace('.', 'p')}x",
                    base_variant_id=kind,
                    mode="fixed_leverage",
                    fixed_leverage=lev,
                    target_volatility_pct=None,
                    max_leverage=lev,
                    interval="15m",
                    interval_hours=0.25,
                    signal_kind=kind,
                )
            )
    return variants


def _simulate_candidate(
    variant: HighYieldVariant,
    *,
    base_signal: pd.Series,
    bars: pd.DataFrame,
    derivatives: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> SimulatedCandidate:
    simulation = _simulate_returns(
        variant,
        base_signal=base_signal,
        bars=bars,
        derivatives=derivatives,
        initial_capital=initial_capital,
        cost_bps=cost_bps,
    )
    return SimulatedCandidate(variant=variant, **simulation)


def _simulate_returns(
    variant: HighYieldVariant,
    *,
    base_signal: pd.Series,
    bars: pd.DataFrame,
    derivatives: pd.DataFrame,
    initial_capital: float,
    cost_bps: float,
) -> dict[str, Any]:
    close = bars["close"].astype(float)
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    index = close.index
    base = base_signal.reindex(index).fillna(0.0).clip(-1.0, 1.0)
    leverage = _leverage_series(variant, close=close)
    target = (base * leverage).clip(-variant.max_leverage, variant.max_leverage)
    target = _apply_crowding_filter(target, derivatives.reindex(index), variant=variant)
    target = _apply_high_vol_trend_boost(target, close=close, max_leverage=variant.max_leverage)

    close_returns = close.pct_change().fillna(0.0)
    funding = pd.to_numeric(derivatives.reindex(index).get("funding_rate", pd.Series(0.0, index=index)), errors="coerce").fillna(0.0)
    actual_exposure: list[float] = []
    returns: list[float] = []
    costs: list[float] = []
    funding_pnl: list[float] = []
    equity_values: list[float] = []

    previous_exposure = 0.0
    equity = float(initial_capital)
    peak = equity
    cooldown_until = -1
    derisk_until = -1
    drawdown_locked = False
    consecutive_loss_bars = 0
    forced_reduce_count = 0
    partial_take_profit_count = 0
    consecutive_loss_derisk_count = 0
    drawdown_stop_count = 0
    simulated_liquidation_count = 0
    min_liquidation_buffer_bps: float | None = None
    crowding_filter_bar_count = int((target.abs() < (base * leverage).abs().reindex(index).fillna(0.0) - 1e-12).sum())

    for pos, ts in enumerate(index):
        desired = float(target.iloc[pos])
        if drawdown_locked or pos < cooldown_until:
            desired = 0.0
        elif pos < derisk_until:
            desired *= 0.5
        turnover = abs(desired - previous_exposure)
        cost = turnover * (float(cost_bps) / 10_000.0)
        fund = -desired * float(funding.iloc[pos]) * (variant.interval_hours / 8.0)
        bar_return = desired * float(close_returns.iloc[pos]) - cost + fund

        if pos > 0 and abs(desired) > 1e-12:
            prev_close = float(close.iloc[pos - 1])
            if desired > 0.0:
                adverse = max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
                favorable = max(0.0, float(high.iloc[pos]) / prev_close - 1.0)
            else:
                adverse = max(0.0, float(high.iloc[pos]) / prev_close - 1.0)
                favorable = max(0.0, 1.0 - float(low.iloc[pos]) / prev_close)
            exposure_abs = abs(desired)
            liquidation_threshold = 0.80 / exposure_abs
            buffer_bps = max(0.0, (liquidation_threshold - adverse) * 10_000.0)
            min_liquidation_buffer_bps = buffer_bps if min_liquidation_buffer_bps is None else min(min_liquidation_buffer_bps, buffer_bps)
            fast_stop = max(0.015, min(0.06, 0.06 / exposure_abs))
            take_profit = max(0.03, min(0.10, 0.09 / exposure_abs))
            if adverse >= liquidation_threshold:
                simulated_liquidation_count += 1
                forced_reduce_count += 1
                bar_return = -0.80 - cost + fund
                cooldown_until = max(cooldown_until, pos + 12)
                desired = 0.0
            elif buffer_bps < MIN_LIQUIDATION_BUFFER_BPS:
                forced_reduce_count += 1
                desired *= 0.5
                cooldown_until = max(cooldown_until, pos + 6)
            elif adverse >= fast_stop:
                forced_reduce_count += 1
                bar_return = -exposure_abs * fast_stop - cost + fund
                cooldown_until = max(cooldown_until, pos + 6)
                desired = 0.0
            elif favorable >= take_profit:
                partial_take_profit_count += 1
                signed_take = math.copysign(take_profit, desired)
                bar_return = desired * (0.5 * signed_take + 0.5 * float(close_returns.iloc[pos])) - cost + fund
                derisk_until = max(derisk_until, pos + 2)

        equity *= 1.0 + bar_return
        peak = max(peak, equity)
        drawdown = equity / peak - 1.0 if peak > 0.0 else -1.0
        if drawdown <= -MAX_ACCEPTABLE_DRAWDOWN_ABS_PCT / 100.0 and not drawdown_locked:
            drawdown_locked = True
            drawdown_stop_count += 1
            cooldown_until = len(index) + 1
        if abs(desired) > 1e-12 and bar_return < 0.0:
            consecutive_loss_bars += 1
        elif bar_return > 0.0:
            consecutive_loss_bars = 0
        if consecutive_loss_bars >= 3:
            derisk_until = max(derisk_until, pos + 12)
            consecutive_loss_derisk_count += 1
            consecutive_loss_bars = 0

        actual_exposure.append(float(desired))
        returns.append(float(bar_return))
        costs.append(float(cost))
        funding_pnl.append(float(fund))
        equity_values.append(float(equity))
        previous_exposure = float(desired)

    exposure = pd.Series(actual_exposure, index=index, dtype=float)
    strategy_returns = pd.Series(returns, index=index, dtype=float)
    cost_series = pd.Series(costs, index=index, dtype=float)
    funding_series = pd.Series(funding_pnl, index=index, dtype=float)
    equity_series = pd.Series(equity_values, index=index, dtype=float)
    turnover = exposure.diff().abs().fillna(exposure.abs())
    metrics = _performance_metrics(
        strategy_returns=strategy_returns,
        equity=equity_series,
        exposure=exposure,
        turnover=turnover,
        cost=cost_series,
        interval=variant.interval,
        initial_capital=initial_capital,
    )
    metrics["funding_return_pct"] = _round(float(funding_series.sum()) * 100.0)
    metrics["trading_cost_return_pct"] = _round(float(cost_series.sum()) * -100.0)
    diagnostics = {
        "forced_risk_reduction_count": forced_reduce_count,
        "partial_take_profit_count": partial_take_profit_count,
        "consecutive_loss_derisk_count": consecutive_loss_derisk_count,
        "drawdown_stop_count": drawdown_stop_count,
        "simulated_liquidation_count": simulated_liquidation_count,
        "min_liquidation_buffer_bps": _round(min_liquidation_buffer_bps or 0.0),
        "crowding_filter_bar_count": crowding_filter_bar_count,
        "risk_research_approximation": True,
    }
    return {
        "exposure": exposure,
        "returns": strategy_returns,
        "turnover": turnover,
        "cost": cost_series,
        "funding_pnl": funding_series,
        "equity": equity_series,
        "metrics": metrics,
        "diagnostics": diagnostics,
    }


def _leverage_series(variant: HighYieldVariant, *, close: pd.Series) -> pd.Series:
    if variant.mode == "fixed_leverage":
        return pd.Series(float(variant.fixed_leverage or 1.0), index=close.index)
    returns = close.pct_change().fillna(0.0)
    bars_per_year = _bars_per_year(variant.interval)
    window = 42 if variant.interval == "4h" else 96
    realized = returns.rolling(window, min_periods=max(10, window // 3)).std(ddof=0).shift(1) * math.sqrt(bars_per_year)
    target = float(variant.target_volatility_pct or 60.0) / 100.0
    leverage = (target / realized.replace(0.0, math.nan)).replace([math.inf, -math.inf], math.nan).fillna(1.0)
    return leverage.clip(0.0, float(variant.max_leverage))


def _apply_crowding_filter(target: pd.Series, derivatives: pd.DataFrame, *, variant: HighYieldVariant) -> pd.Series:
    if derivatives.empty:
        return target
    funding = pd.to_numeric(derivatives.get("funding_rate", pd.Series(0.0, index=target.index)), errors="coerce").fillna(0.0)
    oi = pd.to_numeric(derivatives.get("open_interest_usd", pd.Series(math.nan, index=target.index)), errors="coerce")
    long_short = pd.to_numeric(derivatives.get("long_short_ratio", pd.Series(math.nan, index=target.index)), errors="coerce")
    oi_change = oi.pct_change()
    oi_mean = oi_change.rolling(60, min_periods=20).mean().shift(1)
    oi_std = oi_change.rolling(60, min_periods=20).std(ddof=0).shift(1)
    oi_z = ((oi_change - oi_mean) / oi_std.replace(0.0, math.nan)).fillna(0.0)
    long_crowded = (funding > 0.0003) | (oi_z > 2.5) | (long_short > 1.30)
    short_crowded = (funding < -0.0003) | (oi_z > 2.5) | (long_short < 0.75)
    output = target.copy()
    output.loc[(target > 0.0) & long_crowded] = 0.0
    output.loc[(target < 0.0) & short_crowded] = 0.0
    return output


def _apply_high_vol_trend_boost(target: pd.Series, *, close: pd.Series, max_leverage: float) -> pd.Series:
    returns = close.pct_change().fillna(0.0)
    realized = returns.rolling(6, min_periods=4).std(ddof=0)
    cap = realized.rolling(180, min_periods=60).quantile(0.85).shift(1)
    high_vol = (realized > cap) & cap.notna() & (target.abs() > 0.0)
    output = target.copy()
    output.loc[high_vol] = (output.loc[high_vol] * 1.15).clip(-float(max_leverage), float(max_leverage))
    return output


def _intraday_signal(bars_15m: pd.DataFrame, *, kind: str) -> pd.Series:
    close = bars_15m["close"].astype(float)
    high = bars_15m["high"].astype(float)
    low = bars_15m["low"].astype(float)
    ema_fast = close.ewm(span=96, adjust=False).mean()
    ema_slow = close.ewm(span=384, adjust=False).mean()
    trend_long = ema_fast > ema_slow
    trend_short = ema_fast < ema_slow
    signal = pd.Series(0.0, index=close.index)
    if kind == "15m_momentum_breakout":
        upper = high.rolling(96, min_periods=40).max().shift(1)
        lower = low.rolling(96, min_periods=40).min().shift(1)
        momentum = close.pct_change(16)
        signal.loc[(close > upper) & trend_long & (momentum > 0.006)] = 1.0
        signal.loc[(close < lower) & trend_short & (momentum < -0.006)] = -1.0
    elif kind == "15m_pullback_reentry":
        reentry_long = (low <= ema_fast * 1.002) & (close > ema_fast) & (close.pct_change(4) > 0.0)
        reentry_short = (high >= ema_fast * 0.998) & (close < ema_fast) & (close.pct_change(4) < 0.0)
        signal.loc[trend_long & reentry_long] = 1.0
        signal.loc[trend_short & reentry_short] = -1.0
    else:
        raise ValueError(f"unsupported intraday signal kind: {kind}")
    return signal


def _performance_metrics(
    *,
    strategy_returns: pd.Series,
    equity: pd.Series,
    exposure: pd.Series,
    turnover: pd.Series,
    cost: pd.Series,
    interval: str,
    initial_capital: float,
) -> dict[str, Any]:
    if strategy_returns.empty:
        return _empty_metrics(initial_capital)
    total_return = float(equity.iloc[-1] / float(initial_capital) - 1.0)
    elapsed_days = max(1.0, float((strategy_returns.index.max() - strategy_returns.index.min()).total_seconds()) / 86_400.0)
    annual_return = (1.0 + total_return) ** (365.0 / elapsed_days) - 1.0 if total_return > -1.0 else -1.0
    bars_per_year = _bars_per_year(interval)
    std = float(strategy_returns.std(ddof=0))
    downside = strategy_returns[strategy_returns < 0.0]
    downside_std = float(downside.std(ddof=0)) if len(downside) else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
    positive = float(strategy_returns[strategy_returns > 0.0].sum())
    negative = float(strategy_returns[strategy_returns < 0.0].sum())
    profit_factor = positive / abs(negative) if negative < 0.0 else (999.0 if positive > 0.0 else 0.0)
    return {
        "total_return_pct": _round(total_return * 100.0),
        "annual_return_pct": _round(annual_return * 100.0),
        "annual_volatility_pct": _round(std * math.sqrt(bars_per_year) * 100.0),
        "downside_volatility_pct": _round(downside_std * math.sqrt(bars_per_year) * 100.0),
        "sharpe_ratio": _round(float(strategy_returns.mean() / std * math.sqrt(bars_per_year)) if std > 0.0 else 0.0),
        "sortino_ratio": _round(float(strategy_returns.mean() / downside_std * math.sqrt(bars_per_year)) if downside_std > 0.0 else 0.0),
        "calmar_ratio": _round(float(annual_return / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0),
        "profit_factor": _round(profit_factor),
        "max_drawdown_pct": _round(max_drawdown * 100.0),
        "max_drawdown_abs_pct": _round(abs(max_drawdown) * 100.0),
        "final_equity": _round(float(equity.iloc[-1])),
        "average_exposure": _round(float(exposure.abs().mean())),
        "average_net_exposure": _round(float(exposure.mean())),
        "bars_with_exposure": int((exposure.abs() > 0.0).sum()),
        "long_bar_count": int((exposure > 0.0).sum()),
        "short_bar_count": int((exposure < 0.0).sum()),
        "turnover": _round(float(turnover.sum())),
        "exposure_change_count": int((turnover > 1e-12).sum()),
        "fee_return_pct": _round(float(cost.sum()) * -100.0),
    }


def _candidate_row(candidate: SimulatedCandidate) -> dict[str, Any]:
    cost_2x = _cost_2x_proxy(candidate)
    m = candidate.metrics
    d = candidate.diagnostics
    decision = _retention_decision(m, d, cost_2x)
    return {
        "bucket": candidate.variant.bucket,
        "variant_id": candidate.variant.variant_id,
        "base_variant_id": candidate.variant.base_variant_id,
        "mode": candidate.variant.mode,
        "fixed_leverage": candidate.variant.fixed_leverage,
        "target_volatility_pct": candidate.variant.target_volatility_pct,
        "max_leverage": candidate.variant.max_leverage,
        "interval": candidate.variant.interval,
        "signal_kind": candidate.variant.signal_kind,
        "total_return_pct": m["total_return_pct"],
        "annual_return_pct": m["annual_return_pct"],
        "max_drawdown_pct": m["max_drawdown_pct"],
        "max_drawdown_abs_pct": m["max_drawdown_abs_pct"],
        "calmar_ratio": m["calmar_ratio"],
        "profit_factor": m["profit_factor"],
        "average_exposure": m["average_exposure"],
        "turnover": m["turnover"],
        "cost_2x_total_return_pct": cost_2x["total_return_pct"],
        "cost_2x_profit_factor": cost_2x["profit_factor"],
        "simulated_liquidation_count": d["simulated_liquidation_count"],
        "min_liquidation_buffer_bps": d["min_liquidation_buffer_bps"],
        "forced_risk_reduction_count": d["forced_risk_reduction_count"],
        "partial_take_profit_count": d["partial_take_profit_count"],
        "consecutive_loss_derisk_count": d["consecutive_loss_derisk_count"],
        "drawdown_stop_count": d["drawdown_stop_count"],
        "crowding_filter_bar_count": d["crowding_filter_bar_count"],
        "high_risk_drawdown_band": bool(HIGH_RISK_DRAWDOWN_ABS_PCT <= float(m["max_drawdown_abs_pct"]) <= MAX_ACCEPTABLE_DRAWDOWN_ABS_PCT),
        "forward_30d_status": "pending_future_data",
        "forward_60d_status": "pending_future_data",
        "retention_decision": decision,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
    }


def _cost_2x_proxy(candidate: SimulatedCandidate) -> dict[str, Any]:
    returns = candidate.returns - candidate.cost
    equity = INITIAL_CAPITAL * (1.0 + returns).cumprod()
    return _performance_metrics(
        strategy_returns=returns,
        equity=equity,
        exposure=candidate.exposure,
        turnover=candidate.turnover,
        cost=candidate.cost * 2.0,
        interval=candidate.variant.interval,
        initial_capital=INITIAL_CAPITAL,
    )


def _retention_decision(metrics: Mapping[str, Any], diagnostics: Mapping[str, Any], cost_2x: Mapping[str, Any]) -> str:
    if float(metrics.get("annual_return_pct", 0.0)) < MIN_RESEARCH_ANNUAL_RETURN_PCT:
        return "reject_annual_return_below_high_yield_target"
    if float(metrics.get("max_drawdown_abs_pct", 999.0)) > MAX_ACCEPTABLE_DRAWDOWN_ABS_PCT:
        return "reject_drawdown_above_small_account_limit"
    if float(metrics.get("profit_factor", 0.0)) < MIN_RESEARCH_PROFIT_FACTOR:
        return "reject_profit_factor_below_1p15"
    if int(diagnostics.get("simulated_liquidation_count", 0)) > 0:
        return "reject_simulated_liquidation"
    if float(cost_2x.get("total_return_pct", 0.0)) <= 0.0:
        return "reject_cost_2x_non_positive"
    return "retain_high_yield_research_watchlist_only"


def _short_interval_ready(report: Mapping[str, Any]) -> bool:
    if report.get("status") != "complete_research_only":
        return False
    coverage = {str(row.get("interval")): row for row in report.get("coverage", []) if isinstance(row, Mapping)}
    return all(interval in coverage and int(coverage[interval].get("row_count", 0) or 0) > 0 for interval in ("1m", "5m", "15m"))


def _summary(rows: Sequence[Mapping[str, Any]], watchlist: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    best = rows[0] if rows else {}
    return {
        "candidate_count": len(rows),
        "watchlist_count": len(watchlist),
        "best_variant_id": best.get("variant_id"),
        "best_annual_return_pct": best.get("annual_return_pct", 0.0),
        "best_max_drawdown_abs_pct": best.get("max_drawdown_abs_pct", 0.0),
        "best_profit_factor": best.get("profit_factor", 0.0),
        "paper_queue_write_allowed": False,
        "live_unlock_allowed": False,
    }


def _warnings(rows: Sequence[Mapping[str, Any]], intraday_blockers: Sequence[str]) -> list[str]:
    warnings = ["btc_small_account_high_yield_research_only_no_paper_no_live"]
    if intraday_blockers:
        warnings.append("btc_high_yield_intraday_bucket_blocked_or_partial")
    if any(bool(row.get("high_risk_drawdown_band")) for row in rows):
        warnings.append("high_risk_drawdown_25_to_40_pct_present")
    if any(int(row.get("forced_risk_reduction_count", 0)) > 0 for row in rows):
        warnings.append("risk_reduction_controls_triggered")
    return warnings


def _safety_status(*, watchlist: Sequence[Mapping[str, Any]], blockers: Sequence[str], intraday_blockers: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": "btc_small_account_high_yield_safety_status_v1",
        "status": "research_only",
        "watchlist_count": len(watchlist),
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "blockers": list(blockers),
        "intraday_blockers": list(intraday_blockers),
        "reason": "small-account high-yield research can only produce a research watchlist",
    }


def render_btc_small_account_high_yield_markdown(report: Mapping[str, Any]) -> str:
    gate = report.get("gate", {})
    summary = report.get("summary", {})
    lines = [
        "# BTC 小资金高收益研究实验室",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 候选数：`{summary.get('candidate_count')}`",
        f"- 高收益研究短名单数：`{summary.get('watchlist_count')}`",
        f"- 最佳候选：`{summary.get('best_variant_id')}`",
        f"- 最佳年化：`{summary.get('best_annual_return_pct')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## Top 10",
        "",
        "| 排名 | 桶 | 候选 | 年化 | 回撤 | PF | 2x成本收益 | 强平次数 | 结论 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for rank, row in enumerate(report.get("candidate_rows", [])[:10], 1):
        lines.append(
            f"| {rank} | {row.get('bucket')} | `{row.get('variant_id')}` | {row.get('annual_return_pct')} | "
            f"{row.get('max_drawdown_pct')} | {row.get('profit_factor')} | {row.get('cost_2x_total_return_pct')} | "
            f"{row.get('simulated_liquidation_count')} | `{row.get('retention_decision')}` |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 本报告只做小资金高收益研究，不写 paper 队列，不解锁 live。",
            "- 杠杆、强平缓冲、funding 和短周期执行均为研究近似，不能当作实盘证据。",
        ]
    )
    if report.get("intraday_blockers"):
        lines.extend(["", "## Intraday 阻塞项", ""])
        lines.extend(f"- `{item}`" for item in report.get("intraday_blockers", []))
    return "\n".join(lines) + "\n"


def _grid_fieldnames() -> list[str]:
    return [
        "bucket",
        "variant_id",
        "base_variant_id",
        "mode",
        "fixed_leverage",
        "target_volatility_pct",
        "max_leverage",
        "interval",
        "signal_kind",
        "total_return_pct",
        "annual_return_pct",
        "max_drawdown_pct",
        "max_drawdown_abs_pct",
        "calmar_ratio",
        "profit_factor",
        "average_exposure",
        "turnover",
        "cost_2x_total_return_pct",
        "cost_2x_profit_factor",
        "simulated_liquidation_count",
        "min_liquidation_buffer_bps",
        "forced_risk_reduction_count",
        "partial_take_profit_count",
        "consecutive_loss_derisk_count",
        "drawdown_stop_count",
        "crowding_filter_bar_count",
        "high_risk_drawdown_band",
        "forward_30d_status",
        "forward_60d_status",
        "retention_decision",
        "paper_queue_write_allowed",
        "paper_candidate_created",
        "live_unlock_allowed",
    ]


def _read_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _guardrails() -> dict[str, bool]:
    return {
        "research_only": True,
        "private_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_access_allowed": False,
        "oms_access_allowed": False,
        "paper_queue_write_allowed": False,
        "paper_candidate_created": False,
        "live_unlock_allowed": False,
        "live_order_allowed": False,
        "real_order_submitted": False,
    }


def _empty_metrics(initial_capital: float) -> dict[str, Any]:
    return {
        "total_return_pct": 0.0,
        "annual_return_pct": 0.0,
        "annual_volatility_pct": 0.0,
        "downside_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "profit_factor": 0.0,
        "max_drawdown_pct": 0.0,
        "max_drawdown_abs_pct": 0.0,
        "final_equity": initial_capital,
        "average_exposure": 0.0,
        "average_net_exposure": 0.0,
        "bars_with_exposure": 0,
        "long_bar_count": 0,
        "short_bar_count": 0,
        "turnover": 0.0,
        "exposure_change_count": 0,
        "fee_return_pct": 0.0,
    }


def _bars_per_year(interval: str) -> float:
    if interval == "4h":
        return 6.0 * 365.0
    if interval == "15m":
        return 96.0 * 365.0
    return 365.0


def _round(value: float, digits: int = 6) -> float:
    if value is None or not math.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _portable_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path.cwd(), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"

