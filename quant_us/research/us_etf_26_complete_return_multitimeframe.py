"""Research-only application of the frozen TQQQ complete-return rule to 26 ETFs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant_us.research.tqqq_multitimeframe_walk_forward import (
    TIMEFRAME_MINUTES,
    _complete_sessions,
    _filter_sessions,
    _fixed_params,
    _fixed_signal,
    _prepare_market,
    _resample_rth,
)


BASE_COST_BPS = 10.0
COST_LEVELS_BPS = (0.0, 5.0, 10.0, 25.0, 50.0)
INITIAL_CAPITAL = 25_000.0
SYNTHETIC_MARGIN_MULTIPLIER = 3.0
MARGIN_INTEREST_ANNUAL = 0.06
MAINTENANCE_MARGIN_RATE = 0.25
REQUESTED_TIMEFRAMES = (
    "1min",
    "5min",
    "15min",
    "30min",
    "1H",
    "4H",
    "1D",
)
COMPLETE_RETURN_TIMEFRAME_MINUTES = {"1min": 1, **TIMEFRAME_MINUTES}


@dataclass(frozen=True)
class DangerSimulation:
    metrics: dict[str, Any]
    daily_returns: pd.Series


def run_symbol_complete_return_multitimeframe(
    *,
    path: str | Path,
    symbol: str,
    start: str | date,
    end: str | date,
    timeframes: Iterable[str] = REQUESTED_TIMEFRAMES,
) -> dict[str, Any]:
    normalized_symbol = str(symbol).strip().upper()
    minute = _load_minute_frame(
        Path(path),
        symbol=normalized_symbol,
        start=start,
        end=end,
    )
    complete_sessions = sorted(_complete_sessions(minute))
    if not complete_sessions:
        return {
            "symbol": normalized_symbol,
            "matrix_rows": [],
            "cost_stress_rows": [],
            "walk_forward_rows": [],
            "blockers": [f"{normalized_symbol.lower()}_complete_rth_sessions_missing"],
        }
    minute = _filter_sessions(minute, complete_sessions)
    matrix_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    for timeframe in timeframes:
        if timeframe not in COMPLETE_RETURN_TIMEFRAME_MINUTES:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        minutes = COMPLETE_RETURN_TIMEFRAME_MINUTES[timeframe]
        bars = _resample_rth(minute, minutes=minutes, symbol=normalized_symbol)
        market = _prepare_market(bars, bars)
        params = _fixed_params(minutes)
        market = market.join(_fixed_signal(market, params))
        if len(market) < int(params["entry_window"]) + 50:
            blockers.append(f"{normalized_symbol.lower()}_{timeframe}_insufficient_bars")
            continue
        one_x = _simulate_danger_reference(
            market,
            multiplier=1.0,
            cost_bps=BASE_COST_BPS,
            periods_per_year=252 * int(params["bars_per_session"]),
        )
        three_x = _simulate_danger_reference(
            market,
            multiplier=SYNTHETIC_MARGIN_MULTIPLIER,
            cost_bps=BASE_COST_BPS,
            periods_per_year=252 * int(params["bars_per_session"]),
        )
        matrix_rows.append(
            {
                "symbol": normalized_symbol,
                "timeframe": timeframe,
                "start": market.index.min().isoformat(),
                "end": market.index.max().isoformat(),
                "bar_count": int(len(market)),
                "complete_session_count": len(complete_sessions),
                "params": dict(params),
                **{f"one_x_{key}": value for key, value in one_x.metrics.items()},
                **{f"three_x_{key}": value for key, value in three_x.metrics.items()},
            }
        )
        for cost_bps in COST_LEVELS_BPS:
            simulation = _simulate_danger_reference(
                market,
                multiplier=SYNTHETIC_MARGIN_MULTIPLIER,
                cost_bps=cost_bps,
                periods_per_year=252 * int(params["bars_per_session"]),
            )
            cost_rows.append(
                {
                    "symbol": normalized_symbol,
                    "timeframe": timeframe,
                    "cost_bps": cost_bps,
                    **simulation.metrics,
                }
            )
        fold_rows.extend(
            _walk_forward_rows(
                symbol=normalized_symbol,
                timeframe=timeframe,
                daily_returns=three_x.daily_returns,
                periods_per_year=252 * int(params["bars_per_session"]),
            )
        )
    return {
        "symbol": normalized_symbol,
        "matrix_rows": matrix_rows,
        "cost_stress_rows": cost_rows,
        "walk_forward_rows": fold_rows,
        "blockers": blockers,
    }


def summarize_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if not row.get("three_x_portfolio_zero")]
    best_total = max(
        completed,
        key=lambda row: float(row.get("three_x_total_return_pct", -1e18)),
        default=None,
    )
    best_sharpe = max(
        completed,
        key=lambda row: float(row.get("three_x_sharpe", -1e18)),
        default=None,
    )
    return {
        "combination_count": len(rows),
        "surviving_combination_count": len(completed),
        "portfolio_zero_count": len(rows) - len(completed),
        "margin_call_combination_count": sum(
            int(row.get("three_x_margin_call_count", 0) or 0) > 0 for row in rows
        ),
        "best_surviving_by_total_return": _row_identity(best_total),
        "best_surviving_by_sharpe": _row_identity(best_sharpe),
        "ten_thousand_x_combination_count": sum(
            float(row.get("three_x_total_return_pct", 0.0) or 0.0) >= 999_900.0
            for row in completed
        ),
    }


def _load_minute_frame(
    path: Path,
    *,
    symbol: str,
    start: str | date,
    end: str | date,
) -> pd.DataFrame:
    start_date = date.fromisoformat(str(start)) if not isinstance(start, date) else start
    end_date = date.fromisoformat(str(end)) if not isinstance(end, date) else end
    start_local = pd.Timestamp(start_date)
    end_local = pd.Timestamp(end_date + timedelta(days=1))
    read_kwargs: dict[str, Any] = {
        "columns": ["datetime", "Open", "High", "Low", "Close", "Volume"]
    }
    datetime_type = pq.read_schema(path).field("datetime").type
    if pa.types.is_timestamp(datetime_type):
        read_kwargs["filters"] = [
            ("datetime", ">=", start_local),
            ("datetime", "<", end_local),
        ]
    frame = pd.read_parquet(path, **read_kwargs)
    timestamp = pd.to_datetime(frame["datetime"], errors="coerce")
    if timestamp.dt.tz is None:
        timestamp = timestamp.dt.tz_localize(
            "America/New_York", ambiguous="raise", nonexistent="raise"
        )
    else:
        timestamp = timestamp.dt.tz_convert("America/New_York")
    frame["datetime"] = timestamp.dt.tz_convert("UTC")
    frame["symbol"] = symbol
    return (
        frame.dropna(subset=["datetime", "Open", "High", "Low", "Close", "Volume"])
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
    )


def _simulate_danger_reference(
    market: pd.DataFrame,
    *,
    multiplier: float,
    cost_bps: float,
    periods_per_year: int,
) -> DangerSimulation:
    side = market["effective_signal"].to_numpy(dtype=float)
    returns = market["tqqq_open_to_next_open_return"].to_numpy(dtype=float)
    adverse = market["tqqq_adverse_open_low_or_gap_return"].to_numpy(dtype=float)
    turnover = np.abs(side - np.r_[0.0, side[:-1]]) * multiplier
    fee_rate = turnover * cost_bps / 10_000.0
    borrow_rate = max(0.0, multiplier - 1.0) * MARGIN_INTEREST_ANNUAL / periods_per_year
    margin_threshold = _margin_call_threshold(multiplier)
    wipeout_threshold = -1.0 / multiplier
    margin_hits = (
        (side > 0.0) & (adverse <= margin_threshold)
        if multiplier > 1.0
        else np.zeros(len(market), dtype=bool)
    )
    wipeout_hits = (side > 0.0) & (returns <= wipeout_threshold)
    terminal_hits = margin_hits | wipeout_hits
    terminal_index = int(np.flatnonzero(terminal_hits)[0]) if terminal_hits.any() else None
    factors = (1.0 - fee_rate) * np.where(
        side > 0.0,
        1.0 + multiplier * returns - borrow_rate,
        1.0,
    )
    factors = np.maximum(factors, 0.0)
    if terminal_index is not None:
        factors[terminal_index] = 0.0
        factors[terminal_index + 1 :] = 1.0
    equity = pd.Series(
        INITIAL_CAPITAL * np.cumprod(factors),
        index=market.index,
        dtype=float,
    )
    daily_returns = equity.pct_change(fill_method=None).fillna(0.0)
    metrics = _performance_metrics(
        daily_returns,
        periods_per_year=periods_per_year,
    )
    metrics.update(
        {
            "final_equity": _round(float(equity.iloc[-1]) if len(equity) else 0.0),
            "turnover": _round(float(turnover.sum())),
            "trade_count": int((turnover > 0.0).sum()),
            "exposure_ratio": _round(float((side > 0.0).mean()) if len(side) else 0.0),
            "cost_bps": float(cost_bps),
            "cost_drag_pct": _round(float(fee_rate.sum()) * 100.0),
            "margin_interest_annual": MARGIN_INTEREST_ANNUAL,
            "margin_call_threshold_pct": _round(margin_threshold * 100.0),
            "wipeout_threshold_pct": _round(wipeout_threshold * 100.0),
            "margin_call_count": int(margin_hits[terminal_index]) if terminal_index is not None else 0,
            "wipeout_count": int(wipeout_hits[terminal_index]) if terminal_index is not None else 0,
            "portfolio_zero": bool(terminal_index is not None),
            "terminal_timestamp": market.index[terminal_index].isoformat() if terminal_index is not None else None,
        }
    )
    return DangerSimulation(metrics=metrics, daily_returns=daily_returns)


def _walk_forward_rows(
    *,
    symbol: str,
    timeframe: str,
    daily_returns: pd.Series,
    periods_per_year: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    years = pd.DatetimeIndex(daily_returns.index).tz_convert("America/New_York").year
    for year in sorted({int(value) for value in years if int(value) >= 2020}):
        fold = daily_returns.loc[years == year]
        if len(fold) < 20:
            continue
        rows.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "test_year": year,
                "parameters_frozen": True,
                "training_selection_used": False,
                **_performance_metrics(fold, periods_per_year=periods_per_year),
            }
        )
    return rows


def _performance_metrics(
    returns: pd.Series,
    *,
    periods_per_year: int,
) -> dict[str, Any]:
    clean = returns.fillna(0.0)
    equity = (1.0 + clean).cumprod()
    total = float(equity.iloc[-1] - 1.0) if len(equity) else 0.0
    years = max(1.0 / periods_per_year, len(clean) / periods_per_year)
    annual = (1.0 + total) ** (1.0 / years) - 1.0 if total > -1.0 else -1.0
    volatility = float(clean.std(ddof=0) * math.sqrt(periods_per_year)) if len(clean) else 0.0
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series(dtype=float)
    return {
        "total_return_pct": _round(total * 100.0),
        "annual_return_pct": _round(annual * 100.0),
        "annual_vol_pct": _round(volatility * 100.0),
        "sharpe": _round(annual / volatility if volatility > 1e-12 else 0.0),
        "max_drawdown_abs_pct": _round(abs(float(drawdown.min())) * 100.0 if len(drawdown) else 0.0),
        "periods_per_year": int(periods_per_year),
    }


def _margin_call_threshold(multiplier: float) -> float:
    if multiplier <= 1.0:
        return -1.0
    return (
        MAINTENANCE_MARGIN_RATE * multiplier - 1.0
    ) / (multiplier * (1.0 - MAINTENANCE_MARGIN_RATE))


def _row_identity(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "total_return_pct": row["three_x_total_return_pct"],
        "annual_return_pct": row["three_x_annual_return_pct"],
        "sharpe": row["three_x_sharpe"],
        "max_drawdown_abs_pct": row["three_x_max_drawdown_abs_pct"],
    }


def _round(value: float | int | None, digits: int = 6) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), digits)
