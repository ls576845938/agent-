from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import settings
from backend.app.domain.models import BacktestArtifacts, StrategyDescriptor, TradeMarker
from backend.app.domain.risk import DrawdownCircuitBreaker, KellySizer, OrthogonalizationEngine, VolatilityScaler, clamp
from backend.app.domain.strategy_registry import strategy_registry
from backend.app.services.market_data import load_market_frame


@dataclass(frozen=True)
class SimulationConfig:
    mode: str
    source: str
    symbol: str
    interval: str
    start: datetime
    end: datetime
    capital: float
    commission_rate: float
    slippage: float
    leverage: float
    position_basis: str = "equity"
    db_path: str = ""
    volume_participation_cap_pct: float = 5.0
    rebalance_buffer_pct: float = 0.01
    min_holding_bars: int = 5
    cost_aware_filter: bool = True
    max_annual_turnover_pct: float = 5000.0


def _to_epoch(timestamp: pd.Timestamp) -> int:
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return int(timestamp.timestamp())


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    positive = {name: max(0.0, float(weight)) for name, weight in weights.items()}
    total = sum(positive.values())
    if total <= 0:
        return {name: 0.0 for name in positive}
    return {name: value / total for name, value in positive.items()}


def _compute_summary(equity: pd.Series, returns: pd.Series, periods_per_year: float, trade_count: int) -> dict[str, float | int]:
    if equity.empty:
        return {
            "total_return_pct": 0.0,
            "annual_return_pct": 0.0,
            "annual_volatility_pct": 0.0,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "calmar_ratio": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "trade_count": trade_count,
        }

    series = returns.fillna(0.0)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    annualized_return = 0.0
    if len(series) > 0 and equity.iloc[-1] > 0:
        annualized_return = (float(equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / max(1, len(series))) - 1.0)

    annual_vol = float(series.std(ddof=0)) * sqrt(periods_per_year) if len(series) > 1 else 0.0
    downside = series[series < 0]
    downside_vol = float(downside.std(ddof=0)) * sqrt(periods_per_year) if len(downside) > 1 else 0.0
    sharpe = float(series.mean() / series.std(ddof=0) * sqrt(periods_per_year)) if len(series) > 1 and float(series.std(ddof=0)) > 0 else 0.0
    sortino = float(series.mean() / downside.std(ddof=0) * sqrt(periods_per_year)) if len(downside) > 1 and float(downside.std(ddof=0)) > 0 else 0.0

    cumulative = equity / equity.iloc[0]
    drawdown = cumulative / cumulative.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = annualized_return / abs(max_drawdown) if max_drawdown < 0 else 0.0

    non_zero = series[series != 0]
    win_rate = float((non_zero > 0).mean()) if not non_zero.empty else 0.0
    gains = float(series[series > 0].sum())
    losses = float(-series[series < 0].sum())
    profit_factor = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)

    return {
        "total_return_pct": round(total_return * 100, 4),
        "annual_return_pct": round(annualized_return * 100, 4),
        "annual_volatility_pct": round(annual_vol * 100, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4),
        "calmar_ratio": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100, 4),
        "profit_factor": round(profit_factor, 4),
        "trade_count": trade_count,
    }


def _build_candle_payload(frame: pd.DataFrame) -> list[dict[str, float | int]]:
    return [
        {
            "time": _to_epoch(timestamp),
            "open": round(float(row["open"]), 6),
            "high": round(float(row["high"]), 6),
            "low": round(float(row["low"]), 6),
            "close": round(float(row["close"]), 6),
        }
        for timestamp, row in frame.iterrows()
    ]


def _build_series_payload(series: pd.Series) -> list[dict[str, float | int]]:
    return [{"time": _to_epoch(index), "value": round(float(value), 6)} for index, value in series.items()]


def _round(value: float | int | None, digits: int = 4) -> float:
    if value is None:
        return 0.0
    if not np.isfinite(float(value)):
        return 0.0
    return round(float(value), digits)


def _display_percent(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}%"


def _display_money(value: float, digits: int = 2) -> str:
    return f"${value:,.{digits}f}"


def _display_number(value: float | int, digits: int = 2) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{value:,.{digits}f}"


def _metric(
    label: str,
    value: float | int | str,
    display: str,
    tone: str = "neutral",
    description: str = "",
) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "display": display,
        "tone": tone,
        "description": description,
    }


def _compute_drawdown_periods(equity: pd.Series, limit: int = 5) -> list[dict[str, Any]]:
    if equity.empty:
        return []

    drawdown = equity / equity.cummax() - 1.0
    periods: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None

    for position, (timestamp, value) in enumerate(drawdown.items()):
        depth = float(value)
        if depth < 0 and active is None:
            peak_position = max(0, position - 1)
            active = {
                "start_time": _to_epoch(equity.index[peak_position]),
                "start_position": peak_position,
                "trough_time": _to_epoch(timestamp),
                "trough_position": position,
                "end_time": _to_epoch(timestamp),
                "end_position": position,
                "depth_pct": depth * 100,
                "recovered": False,
            }
            continue

        if active is None:
            continue

        active["end_time"] = _to_epoch(timestamp)
        active["end_position"] = position
        if depth < float(active["depth_pct"]) / 100:
            active["depth_pct"] = depth * 100
            active["trough_time"] = _to_epoch(timestamp)
            active["trough_position"] = position

        if depth >= 0:
            active["recovered"] = True
            periods.append(active)
            active = None

    if active is not None:
        periods.append(active)

    enriched: list[dict[str, Any]] = []
    for period in periods:
        start_position = int(period.pop("start_position"))
        trough_position = int(period.pop("trough_position"))
        end_position = int(period.pop("end_position"))
        enriched.append(
            {
                **period,
                "depth_pct": _round(period["depth_pct"], 4),
                "duration_bars": max(0, end_position - start_position),
                "recovery_bars": max(0, end_position - trough_position) if period["recovered"] else None,
            }
        )

    return sorted(enriched, key=lambda item: item["depth_pct"])[:limit]


def _compute_periodic_returns(equity: pd.Series, freq: str, limit: int = 18) -> list[dict[str, Any]]:
    if equity.empty:
        return []
    grouped = equity.groupby(pd.Grouper(freq=freq))
    rows: list[dict[str, Any]] = []
    for timestamp, values in grouped:
        clean = values.dropna()
        if clean.empty:
            continue
        period_return = float(clean.iloc[-1] / clean.iloc[0] - 1.0)
        rows.append(
            {
                "period": timestamp.strftime("%Y-%m" if freq == "ME" else "%Y"),
                "return_pct": _round(period_return * 100, 4),
            }
        )
    return rows[-limit:]


def _compute_return_diagnostics(returns: pd.Series, periods_per_year: float) -> dict[str, Any]:
    series = returns.fillna(0.0)
    non_zero = series[series != 0.0]
    if series.empty:
        return {
            "best_period_pct": 0.0,
            "worst_period_pct": 0.0,
            "positive_period_pct": 0.0,
            "var_95_pct": 0.0,
            "cvar_95_pct": 0.0,
            "skew": 0.0,
            "kurtosis": 0.0,
            "rolling_window": 0,
            "rolling_sharpe_latest": 0.0,
            "rolling_sharpe_min": 0.0,
            "rolling_sharpe_max": 0.0,
        }

    var_95 = float(series.quantile(0.05))
    tail = series[series <= var_95]
    rolling_window = min(len(series), max(20, min(252, len(series) // 4 if len(series) >= 80 else len(series))))
    if rolling_window > 1:
        rolling_std = series.rolling(rolling_window).std(ddof=0)
        rolling_sharpe = series.rolling(rolling_window).mean() / rolling_std.replace(0.0, np.nan) * sqrt(periods_per_year)
        rolling_sharpe = rolling_sharpe.replace([np.inf, -np.inf], np.nan).dropna()
    else:
        rolling_sharpe = pd.Series(dtype=float)

    return {
        "best_period_pct": _round(float(series.max()) * 100, 4),
        "worst_period_pct": _round(float(series.min()) * 100, 4),
        "positive_period_pct": _round(float((non_zero > 0).mean()) * 100 if not non_zero.empty else 0.0, 4),
        "var_95_pct": _round(var_95 * 100, 4),
        "cvar_95_pct": _round(float(tail.mean()) * 100 if not tail.empty else 0.0, 4),
        "skew": _round(float(series.skew()) if len(series) > 2 else 0.0, 4),
        "kurtosis": _round(float(series.kurtosis()) if len(series) > 3 else 0.0, 4),
        "rolling_window": int(rolling_window),
        "rolling_sharpe_latest": _round(float(rolling_sharpe.iloc[-1]) if not rolling_sharpe.empty else 0.0, 4),
        "rolling_sharpe_min": _round(float(rolling_sharpe.min()) if not rolling_sharpe.empty else 0.0, 4),
        "rolling_sharpe_max": _round(float(rolling_sharpe.max()) if not rolling_sharpe.empty else 0.0, 4),
    }


def _compute_execution_diagnostics(
    *,
    equity: pd.Series,
    order_notional: pd.Series,
    commission_costs: pd.Series,
    slippage_costs: pd.Series,
    periods_per_year: float,
    volume_capped: pd.Series | None = None,
) -> dict[str, Any]:
    average_equity = float(equity.mean()) if not equity.empty else 0.0
    total_volume = float(order_notional.sum())
    total_fees = float(commission_costs.sum())
    total_slippage = float(slippage_costs.sum())
    total_cost = total_fees + total_slippage
    runtime_years = len(equity) / periods_per_year if periods_per_year > 0 else 0.0
    orders = int((order_notional > 0).sum())
    turnover = total_volume / average_equity if average_equity > 0 else 0.0
    annual_turnover = turnover / runtime_years if runtime_years > 0 else 0.0
    total_capped = float(volume_capped.sum()) if volume_capped is not None else 0.0
    capped_orders = int((volume_capped > 0).sum()) if volume_capped is not None else 0
    return {
        "orders": orders,
        "orders_per_day": _round(orders / max(1.0, len(equity) / max(1.0, periods_per_year / 365.0)), 4),
        "total_volume": _round(total_volume, 4),
        "total_fees": _round(total_fees, 4),
        "total_slippage": _round(total_slippage, 4),
        "total_cost": _round(total_cost, 4),
        "cost_drag_pct": _round(total_cost / float(equity.iloc[0]) * 100 if not equity.empty and equity.iloc[0] > 0 else 0.0, 4),
        "turnover_pct": _round(turnover * 100, 4),
        "annual_turnover_pct": _round(annual_turnover * 100, 4),
        "avg_order_value": _round(total_volume / max(1, orders), 4),
        "volume_capped_notional": _round(total_capped, 4),
        "volume_capped_orders": capped_orders,
        "volume_capped_pct": _round(total_capped / max(1e-9, total_volume + total_capped) * 100.0, 4) if (total_volume + total_capped) > 0 else 0.0,
    }


def _compute_exposure_diagnostics(equity: pd.Series, exposure: pd.Series, net_units: pd.Series) -> dict[str, Any]:
    if equity.empty:
        return {}
    exposure_pct = exposure.fillna(0.0) / equity.replace(0.0, np.nan)
    exposure_pct = exposure_pct.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    units = net_units.fillna(0.0)
    return {
        "avg_gross_exposure_pct": _round(float(exposure_pct.mean()) * 100, 4),
        "max_gross_exposure_pct": _round(float(exposure_pct.max()) * 100, 4),
        "time_in_market_pct": _round(float((units.abs() > 1e-12).mean()) * 100, 4),
        "long_time_pct": _round(float((units > 1e-12).mean()) * 100, 4),
        "short_time_pct": _round(float((units < -1e-12).mean()) * 100, 4),
        "flat_time_pct": _round(float((units.abs() <= 1e-12).mean()) * 100, 4),
    }


def _build_optimization_hints(
    summary: dict[str, float | int],
    return_stats: dict[str, Any],
    execution_stats: dict[str, Any],
    exposure_stats: dict[str, Any],
) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    if float(summary["max_drawdown_pct"]) < -12:
        hints.append({"severity": "high", "message": "最大回撤已经超过 12%，优先降低杠杆、单次目标仓位或增加回撤降仓规则。"})
    if float(summary["profit_factor"]) < 1.15:
        hints.append({"severity": "high", "message": "Profit Factor 偏低，策略边际不足，先检查入场过滤、止损/止盈和交易成本敏感性。"})
    if float(summary["sharpe_ratio"]) < 1.0:
        hints.append({"severity": "medium", "message": "夏普低于 1，收益波动质量一般，建议做参数稳定性和样本外切分。"})
    if float(execution_stats["cost_drag_pct"]) > max(0.5, abs(float(summary["total_return_pct"])) * 0.25):
        hints.append({"severity": "medium", "message": "交易费用和滑点吞噬较多收益，优先降低换手或放宽调仓阈值。"})
    if float(exposure_stats.get("time_in_market_pct", 0.0)) > 95:
        hints.append({"severity": "medium", "message": "几乎全程在场，策略可能更像方向暴露，建议和买入持有基准比较。"})
    if float(return_stats["cvar_95_pct"]) < float(return_stats["var_95_pct"]) * 1.8:
        hints.append({"severity": "low", "message": "尾部损失需要继续观察，可增加极端行情切片和压力测试。"})
    if not hints:
        hints.append({"severity": "low", "message": "核心统计未触发明显警报，下一步重点看样本外、参数扰动和数据源一致性。"})
    return hints


def _build_report_sections(
    *,
    summary: dict[str, float | int],
    return_stats: dict[str, Any],
    execution_stats: dict[str, Any],
    exposure_stats: dict[str, Any],
    monthly_returns: list[dict[str, Any]],
    drawdown_periods: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    best_month = max((item["return_pct"] for item in monthly_returns), default=0.0)
    worst_month = min((item["return_pct"] for item in monthly_returns), default=0.0)
    positive_month_pct = (
        sum(1 for item in monthly_returns if item["return_pct"] > 0) / len(monthly_returns) * 100
        if monthly_returns
        else 0.0
    )
    longest_drawdown = max((int(item["duration_bars"]) for item in drawdown_periods), default=0)

    return [
        {
            "priority": 1,
            "title": "生存性 / 风险底线",
            "subtitle": "先判断策略有没有资格进入 paper trading。",
            "metrics": [
                _metric("最大回撤", summary["max_drawdown_pct"], _display_percent(float(summary["max_drawdown_pct"])), "bad"),
                _metric("最长回撤", longest_drawdown, f"{longest_drawdown:,} bars", "neutral"),
                _metric("Recovery Factor", _round(float(summary["total_return_pct"]) / abs(float(summary["max_drawdown_pct"])) if float(summary["max_drawdown_pct"]) < 0 else 0.0), _display_number(_round(float(summary["total_return_pct"]) / abs(float(summary["max_drawdown_pct"])) if float(summary["max_drawdown_pct"]) < 0 else 0.0)), "neutral"),
                _metric("CVaR 95", return_stats["cvar_95_pct"], _display_percent(float(return_stats["cvar_95_pct"])), "bad"),
            ],
        },
        {
            "priority": 2,
            "title": "收益质量",
            "subtitle": "看收益是否来自稳定风险溢价，而不是单边行情偶然抬升。",
            "metrics": [
                _metric("CAGR", summary["annual_return_pct"], _display_percent(float(summary["annual_return_pct"])), "good" if float(summary["annual_return_pct"]) > 0 else "bad"),
                _metric("Sharpe", summary["sharpe_ratio"], _display_number(float(summary["sharpe_ratio"])), "good" if float(summary["sharpe_ratio"]) >= 1 else "neutral"),
                _metric("Sortino", summary["sortino_ratio"], _display_number(float(summary["sortino_ratio"])), "good" if float(summary["sortino_ratio"]) >= 1 else "neutral"),
                _metric("Calmar", summary["calmar_ratio"], _display_number(float(summary["calmar_ratio"])), "good" if float(summary["calmar_ratio"]) >= 1 else "neutral"),
            ],
        },
        {
            "priority": 3,
            "title": "交易边际",
            "subtitle": "判断每次交易是否有足够正期望。",
            "metrics": [
                _metric("Profit Factor", summary["profit_factor"], _display_number(float(summary["profit_factor"])), "good" if float(summary["profit_factor"]) >= 1.2 else "bad"),
                _metric("胜率", summary["win_rate_pct"], _display_percent(float(summary["win_rate_pct"])), "neutral"),
                _metric("正收益周期", return_stats["positive_period_pct"], _display_percent(float(return_stats["positive_period_pct"])), "neutral"),
                _metric("最差周期", return_stats["worst_period_pct"], _display_percent(float(return_stats["worst_period_pct"])), "bad"),
            ],
        },
        {
            "priority": 4,
            "title": "执行成本 / 换手",
            "subtitle": "检查回测收益是否会被真实交易成本吃掉。",
            "metrics": [
                _metric("成交额", execution_stats["total_volume"], _display_money(float(execution_stats["total_volume"])), "neutral"),
                _metric("总费用", execution_stats["total_cost"], _display_money(float(execution_stats["total_cost"])), "bad" if float(execution_stats["total_cost"]) > 0 else "neutral"),
                _metric("成本拖累", execution_stats["cost_drag_pct"], _display_percent(float(execution_stats["cost_drag_pct"])), "bad" if float(execution_stats["cost_drag_pct"]) > 1 else "neutral"),
                _metric("年化换手", execution_stats["annual_turnover_pct"], _display_percent(float(execution_stats["annual_turnover_pct"])), "neutral"),
            ],
        },
        {
            "priority": 5,
            "title": "仓位与敞口",
            "subtitle": "区分策略 alpha 和方向暴露。",
            "metrics": [
                _metric("平均敞口", exposure_stats.get("avg_gross_exposure_pct", 0.0), _display_percent(float(exposure_stats.get("avg_gross_exposure_pct", 0.0))), "neutral"),
                _metric("最大敞口", exposure_stats.get("max_gross_exposure_pct", 0.0), _display_percent(float(exposure_stats.get("max_gross_exposure_pct", 0.0))), "bad" if float(exposure_stats.get("max_gross_exposure_pct", 0.0)) > 200 else "neutral"),
                _metric("在场时间", exposure_stats.get("time_in_market_pct", 0.0), _display_percent(float(exposure_stats.get("time_in_market_pct", 0.0))), "neutral"),
                _metric("做空时间", exposure_stats.get("short_time_pct", 0.0), _display_percent(float(exposure_stats.get("short_time_pct", 0.0))), "neutral"),
            ],
        },
        {
            "priority": 6,
            "title": "时间稳定性",
            "subtitle": "观察收益是否集中在少数月份或少数波段。",
            "metrics": [
                _metric("最好月", best_month, _display_percent(float(best_month)), "good"),
                _metric("最差月", worst_month, _display_percent(float(worst_month)), "bad"),
                _metric("盈利月份", _round(positive_month_pct, 4), _display_percent(float(positive_month_pct)), "neutral"),
                _metric("滚动 Sharpe", return_stats["rolling_sharpe_latest"], _display_number(float(return_stats["rolling_sharpe_latest"])), "neutral"),
            ],
        },
    ]


def _build_strategy_details(
    base_weights: dict[str, float],
    latest_weights: dict[str, float],
    strategy_returns: dict[str, pd.Series],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for descriptor in strategy_registry.list_descriptors():
        returns = strategy_returns.get(descriptor.id, pd.Series(dtype=float)).fillna(0.0)
        cumulative = (1.0 + returns).cumprod()
        total_return_pct = (float(cumulative.iloc[-1] - 1.0) * 100) if not cumulative.empty else 0.0
        details.append(
            {
                "strategy_id": descriptor.id,
                "display_name": descriptor.display_name,
                "category": descriptor.category,
                "base_weight": round(float(base_weights.get(descriptor.id, 0.0)), 6),
                "latest_weight": round(float(latest_weights.get(descriptor.id, 0.0)), 6),
                "total_return_pct": round(total_return_pct, 4),
            }
        )
    return details


def _signal_trade_text(delta_units: float, target_units: float) -> tuple[str, str, str, str]:
    if delta_units > 0:
        return "belowBar", "#00C853", "arrowUp", f"Increase long {abs(delta_units):.4f} | Net {target_units:.4f}"
    return "aboveBar", "#D50000", "arrowDown", f"Increase short {abs(delta_units):.4f} | Net {target_units:.4f}"


def _prepare_strategy_pack(frame: pd.DataFrame, strategy_ids: list[str], params_map: dict[str, dict[str, float]] | None = None) -> tuple[dict[str, pd.Series], dict[str, StrategyDescriptor]]:
    packs: dict[str, pd.Series] = {}
    descriptors: dict[str, StrategyDescriptor] = {}
    for strategy_id in strategy_ids:
        strategy = strategy_registry.get(strategy_id)
        pack = strategy.generate(frame, params=(params_map or {}).get(strategy_id))
        signal = pack.signal.fillna(0.0).clip(-1.0, 1.0)
        packs[strategy_id] = signal
        descriptors[strategy_id] = strategy.descriptor
    return packs, descriptors


def _candidate_parameter_grid(strategy_id: str) -> list[dict[str, float]]:
    grids: dict[str, list[dict[str, float]]] = {
        "trend_macd": [
            {"fast_window": fast, "slow_window": slow, "signal_window": signal}
            for fast in [12, 20, 30]
            for slow in [48, 60, 96]
            for signal in [9, 12]
            if fast < slow
        ],
        "reversion_rsi": [
            {"rsi_window": rsi_window, "boll_window": boll_window, "boll_dev": boll_dev, "rsi_long": 30, "rsi_short": 70, "rsi_exit_low": 45, "rsi_exit_high": 55}
            for rsi_window in [10, 14, 21]
            for boll_window in [20, 30]
            for boll_dev in [1.8, 2.0, 2.4]
        ],
        "donchian_breakout": [{"channel_window": value} for value in [10, 20, 30, 55]],
        "volatility_squeeze": [
            {"boll_window": window, "boll_dev": dev, "width_threshold": threshold}
            for window in [20, 30]
            for dev in [1.8, 2.0, 2.4]
            for threshold in [0.03, 0.05, 0.08]
        ],
        "funding_sentiment": [
            {"momentum_short": short, "momentum_long": long, "divergence_threshold": threshold}
            for short in [6, 10, 14]
            for long in [48, 60, 96]
            for threshold in [0.015, 0.02, 0.03]
            if short < long
        ],
        "macro_trend": [
            {"short_ma": short, "medium_ma": medium, "long_ma": long}
            for short in [10, 20, 30]
            for medium in [50, 60, 90]
            for long in [120, 180]
            if short < medium < long
        ],
        "dynamic_grid": [
            {"center_window": window, "band_pct": band}
            for window in [30, 60, 96]
            for band in [0.01, 0.02, 0.035]
        ],
        "time_window": [{}],
        "trend_momentum": [
            {"lookback_bars": lb, "entry_threshold": et}
            for lb in [20, 40, 60]
            for et in [0.03, 0.05, 0.08, 0.12]
        ],
        "short_reversion": [
            {"window": w, "threshold": t}
            for w in [10, 20, 30]
            for t in [0.02, 0.03, 0.05]
        ],
        "factor_rank": [
            {"momentum_window": mw, "vol_window": vw}
            for mw in [20, 40, 60]
            for vw in [20, 40]
        ],
        "earnings_drift": [
            {"drift_window": w, "drift_threshold": t}
            for w in [5, 10, 20]
            for t in [0.01, 0.02, 0.04]
        ],
        "etf_rotation": [
            {"rotation_window": w, "momentum_threshold": t}
            for w in [20, 40, 60]
            for t in [0.02, 0.04, 0.06]
        ],
    }
    defaults = strategy_registry.get(strategy_id).descriptor.default_params
    candidates = [dict(defaults)]
    for params in grids.get(strategy_id, [dict(defaults)]):
        merged = {**defaults, **params}
        if merged not in candidates:
            candidates.append(merged)
    return candidates


def _split_train_validation(frame: pd.DataFrame, train_ratio: float = 0.65) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(frame) < 80:
        split = max(2, len(frame) // 2)
    else:
        split = max(40, min(len(frame) - 20, int(len(frame) * train_ratio)))
    train = frame.iloc[:split].copy()
    validation = frame.iloc[split:].copy()
    if len(train) < 2 or len(validation) < 2:
        raise ValueError("Not enough bars for train/validation optimization.")
    return train, validation


def _robust_optimization_score(train_summary: dict[str, float | int], validation_summary: dict[str, float | int]) -> float:
    validation_sharpe = float(validation_summary["sharpe_ratio"])
    validation_calmar = float(validation_summary["calmar_ratio"])
    validation_return = float(validation_summary["total_return_pct"])
    validation_drawdown = abs(float(validation_summary["max_drawdown_pct"]))
    validation_profit_factor = float(validation_summary["profit_factor"])
    train_sharpe = float(train_summary["sharpe_ratio"])
    overfit_gap = max(0.0, train_sharpe - validation_sharpe)
    return round(
        validation_sharpe
        + min(validation_calmar, 5.0) * 0.35
        + min(max(validation_return, -20.0), 50.0) / 50.0
        + min(validation_profit_factor, 3.0) * 0.25
        - validation_drawdown / 25.0
        - overfit_gap * 0.35,
        6,
    )


def _optimization_status(priority: int, selected_priority: int) -> str:
    if priority < selected_priority:
        return "completed"
    if priority == selected_priority:
        return "selected"
    if priority <= selected_priority + 1:
        return "next"
    return "later"


def _optimization_framework(selected_priority: int = 1) -> list[dict[str, Any]]:
    rows = [
        {
            "priority": 1,
            "title": "参数稳健性 + 样本外验证",
            "status": "selected",
            "reason": "当前系统已有回测报告，但还缺少防过拟合的参数筛选；这是进入 paper trading 前最重要的工程关口。",
        },
        {
            "priority": 2,
            "title": "交易成本压力测试",
            "status": "next",
            "reason": "对手续费、滑点、延迟和成交比例做压力测试，避免低频策略被真实执行吞噬。",
        },
        {
            "priority": 3,
            "title": "Walk-forward 与市场状态切片",
            "status": "next",
            "reason": "按牛熊、震荡、高波动、低波动切片验证策略稳定性。",
        },
        {
            "priority": 4,
            "title": "组合层相关性与资金分配",
            "status": "later",
            "reason": "在单策略样本外稳定后，再优化多策略权重、相关性惩罚和风险预算。",
        },
        {
            "priority": 5,
            "title": "数据质量与特征版本治理",
            "status": "later",
            "reason": "为后续机器学习和多数据源接入保留可复现的数据谱系。",
        },
    ]
    for row in rows:
        row["status"] = _optimization_status(int(row["priority"]), selected_priority)
    return rows


def _cost_stress_scenarios(max_scenarios: int) -> list[dict[str, Any]]:
    scenarios = [
        {"name": "base", "label": "当前成本", "commission_multiplier": 1.0, "slippage_multiplier": 1.0},
        {"name": "fees_2x", "label": "手续费 2x", "commission_multiplier": 2.0, "slippage_multiplier": 1.0},
        {"name": "slippage_2x", "label": "滑点 2x", "commission_multiplier": 1.0, "slippage_multiplier": 2.0},
        {"name": "costs_2x", "label": "手续费+滑点 2x", "commission_multiplier": 2.0, "slippage_multiplier": 2.0},
        {"name": "severe_3x", "label": "极端成本 3x", "commission_multiplier": 3.0, "slippage_multiplier": 3.0},
        {"name": "stress_5x", "label": "压力上限 5x", "commission_multiplier": 5.0, "slippage_multiplier": 5.0},
    ]
    return scenarios[: max(1, min(max_scenarios, len(scenarios)))]


def _cost_stress_survives(summary: dict[str, float | int]) -> bool:
    return (
        float(summary["total_return_pct"]) > 0
        and float(summary["profit_factor"]) >= 1.0
        and float(summary["sharpe_ratio"]) >= 0.5
        and float(summary["max_drawdown_pct"]) > -20.0
    )


def _build_cost_stress_recommendations(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["没有生成压力测试场景，请检查输入数据范围。"]
    baseline = rows[0]
    failed = [row for row in rows if not row["survives"]]
    recommendations: list[str] = []
    if not baseline["survives"]:
        recommendations.append("基础成本场景已经未通过，先暂停参数优化，优先降低换手、杠杆或调整策略信号。")
    elif not failed:
        recommendations.append("所有成本场景均通过，可以进入 walk-forward 与市场状态切片验证。")
    else:
        first_failed = failed[0]
        recommendations.append(f"{first_failed['label']} 起开始失效，下一步应优先降低换手和滑点敏感性。")
    worst_return = min(rows, key=lambda row: float(row["summary"]["total_return_pct"]))
    if float(worst_return["summary"]["total_return_pct"]) < -5:
        recommendations.append("极端成本下收益转负明显，paper trading 前需要加入最小调仓阈值或成交额上限。")
    worst_drawdown = min(rows, key=lambda row: float(row["summary"]["max_drawdown_pct"]))
    if float(worst_drawdown["summary"]["max_drawdown_pct"]) < -12:
        recommendations.append("压力场景回撤超过 12%，建议把回撤降仓规则纳入下一轮优化。")
    return recommendations


def _summary_quality_score(summary: dict[str, float | int]) -> float:
    sharpe = float(summary["sharpe_ratio"])
    calmar = float(summary["calmar_ratio"])
    total_return = float(summary["total_return_pct"])
    drawdown = abs(float(summary["max_drawdown_pct"]))
    profit_factor = float(summary["profit_factor"])
    trade_count = int(summary["trade_count"])
    activity_penalty = 0.35 if trade_count == 0 else 0.0
    return round(
        sharpe
        + min(calmar, 5.0) * 0.3
        + min(max(total_return, -20.0), 50.0) / 60.0
        + min(profit_factor, 3.0) * 0.2
        - drawdown / 30.0
        - activity_penalty,
        6,
    )


def _walk_forward_splits(frame: pd.DataFrame, max_windows: int) -> list[tuple[int, pd.DataFrame, pd.DataFrame]]:
    row_count = len(frame)
    if row_count < 50:
        raise ValueError("Not enough bars for walk-forward validation.")

    requested_windows = max(1, min(int(max_windows), 8))
    min_train_rows = max(20, row_count // 5)
    validation_rows = max(10, row_count // (requested_windows + 1))

    while requested_windows > 1 and row_count - validation_rows * requested_windows < min_train_rows:
        requested_windows -= 1
        validation_rows = max(10, row_count // (requested_windows + 1))

    splits: list[tuple[int, pd.DataFrame, pd.DataFrame]] = []
    for window_index in range(requested_windows):
        train_end = row_count - validation_rows * (requested_windows - window_index)
        validation_end = row_count - validation_rows * (requested_windows - window_index - 1)
        if window_index == requested_windows - 1:
            validation_end = row_count
        train = frame.iloc[:train_end].copy()
        validation = frame.iloc[train_end:validation_end].copy()
        if len(train) >= 2 and len(validation) >= 2:
            splits.append((window_index + 1, train, validation))

    if not splits:
        raise ValueError("Not enough bars for walk-forward validation.")
    return splits


def _walk_forward_survives(summary: dict[str, float | int]) -> bool:
    """A fold survives if equity/risk metrics pass. Zero-trade folds are acceptable
    for low-frequency strategies — they indicate no signal, not a broken strategy."""
    return (
        float(summary["total_return_pct"]) >= 0.0
        and float(summary["sharpe_ratio"]) >= 0.0
        and float(summary["max_drawdown_pct"]) > -18.0
    )


def _parameter_stability_pct(windows: list[dict[str, Any]]) -> float:
    if len(windows) <= 1:
        return 100.0
    fingerprints = {
        tuple(sorted((str(key), float(value)) for key, value in row["selected_params"].items()))
        for row in windows
    }
    instability = (len(fingerprints) - 1) / max(1, len(windows) - 1)
    return _round(max(0.0, 1.0 - instability) * 100.0, 4)


def _market_regime_masks(frame: pd.DataFrame) -> list[tuple[str, str, pd.Series]]:
    close = frame["close"].astype(float)
    returns = close.pct_change().fillna(0.0)
    window = max(5, min(96, len(frame) // 8))
    trend = close.pct_change(window).fillna(0.0)
    volatility = returns.rolling(window=window, min_periods=max(3, window // 3)).std(ddof=0)
    fallback_volatility = float(returns.std(ddof=0)) if len(returns) > 1 else 0.0
    volatility = volatility.fillna(fallback_volatility)
    volatility_median = float(volatility.median()) if not volatility.empty else 0.0
    return [
        ("uptrend", "上涨 / 趋势向上", trend > 0.0),
        ("downtrend", "下跌 / 趋势向下", trend <= 0.0),
        ("high_volatility", "高波动", volatility >= volatility_median),
        ("low_volatility", "低波动", volatility < volatility_median),
    ]


def _build_regime_slices(
    *,
    frame: pd.DataFrame,
    config: SimulationConfig,
    strategy_id: str,
    strategy_params: dict[str, float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    min_rows = max(20, int(len(frame) * 0.05))
    for name, label, mask in _market_regime_masks(frame):
        regime_frame = frame.loc[mask].copy()
        if len(regime_frame) < min_rows:
            continue
        signals, _ = _prepare_strategy_pack(regime_frame, [strategy_id], params_map={strategy_id: strategy_params})
        result = _simulate(frame=regime_frame, config=config, weights={strategy_id: 1.0}, signals=signals)
        rows.append(
            {
                "name": name,
                "label": label,
                "bar_count": len(regime_frame),
                "coverage_pct": _round(len(regime_frame) / len(frame) * 100.0, 4),
                "survives": _walk_forward_survives(result.summary),
                "summary": result.summary,
            }
        )
    return rows


def _build_walk_forward_recommendations(windows: list[dict[str, Any]], regimes: list[dict[str, Any]]) -> list[str]:
    if not windows:
        return ["没有生成 walk-forward 窗口，请扩大回测时间范围。"]

    pass_rate = sum(1 for row in windows if row["survives"]) / len(windows) * 100.0
    worst_window = min(windows, key=lambda row: float(row["validation"]["max_drawdown_pct"]))
    recommendations: list[str] = []
    if pass_rate < 60:
        recommendations.append("样本外通过率低于 60%，当前策略不应进入 paper trading，先收紧参数空间或增加市场状态过滤。")
    elif pass_rate < 100:
        recommendations.append("部分样本外窗口失效，下一轮优先检查失效窗口对应的市场状态和换手成本。")
    else:
        recommendations.append("所有 walk-forward 窗口通过，可以继续进入组合相关性和资金分配优化。")

    if float(worst_window["validation"]["max_drawdown_pct"]) < -12:
        recommendations.append("最差样本外窗口回撤超过 12%，建议把回撤降仓和最大日亏损规则提前纳入回测。")

    stability = _parameter_stability_pct(windows)
    if stability < 70:
        recommendations.append("不同窗口选出的参数差异较大，说明参数稳定性不足，应降低参数自由度或改用更宽的参数簇。")

    failed_regimes = [row["label"] for row in regimes if not row["survives"]]
    if failed_regimes:
        recommendations.append(f"市场状态切片中 {', '.join(failed_regimes[:3])} 未通过，实盘前应加入对应 regime filter 或降低仓位。")

    return recommendations


def _requested_portfolio_weights(request: dict[str, Any]) -> dict[str, float]:
    requested = {
        item["strategy_id"]: float(item["weight"])
        for item in request.get("weights", [])
        if float(item.get("weight", 0.0)) > 0
    }
    if requested:
        return requested
    return {
        descriptor.id: descriptor.default_weight
        for descriptor in strategy_registry.list_descriptors()
        if descriptor.default_weight > 0
    }


def _strategy_return_matrix(frame: pd.DataFrame, signals: dict[str, pd.Series]) -> pd.DataFrame:
    close_returns = frame["close"].pct_change().fillna(0.0)
    matrix = pd.DataFrame(
        {
            strategy_id: signal.shift(1).fillna(0.0) * close_returns
            for strategy_id, signal in signals.items()
        },
        index=frame.index,
    )
    return matrix.fillna(0.0)


def _correlation_payload(returns: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    strategy_ids = list(returns.columns)
    if not strategy_ids:
        return [], [], {}

    corr = returns.corr().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    for strategy_id in strategy_ids:
        corr.loc[strategy_id, strategy_id] = 1.0

    matrix: list[dict[str, Any]] = []
    avg_abs: dict[str, float] = {}
    for strategy_id in strategy_ids:
        peers = [other for other in strategy_ids if other != strategy_id]
        avg_abs[strategy_id] = _round(float(corr.loc[strategy_id, peers].abs().mean()) if peers else 0.0, 4)
        matrix.append(
            {
                "strategy_id": strategy_id,
                "avg_abs_correlation": avg_abs[strategy_id],
                "values": [
                    {"strategy_id": other, "correlation": _round(float(corr.loc[strategy_id, other]), 4)}
                    for other in strategy_ids
                ],
            }
        )

    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(strategy_ids):
        for right in strategy_ids[left_index + 1 :]:
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "correlation": _round(float(corr.loc[left, right]), 4),
                    "abs_correlation": _round(abs(float(corr.loc[left, right])), 4),
                }
            )
    pairs.sort(key=lambda row: float(row["abs_correlation"]), reverse=True)
    return matrix, pairs, avg_abs


def _cap_weight_map(weights: dict[str, float], max_single_weight: float) -> dict[str, float]:
    normalized = _normalize_weights(weights)
    if not normalized:
        return {}
    cap = max(float(max_single_weight), 1.0 / len(normalized))
    capped = {strategy_id: min(weight, cap) for strategy_id, weight in normalized.items()}
    for _ in range(12):
        total = sum(capped.values())
        deficit = 1.0 - total
        if abs(deficit) < 1e-9:
            break
        if deficit > 0:
            room = {strategy_id: max(0.0, cap - weight) for strategy_id, weight in capped.items()}
            room_total = sum(room.values())
            if room_total <= 1e-12:
                break
            for strategy_id, available in room.items():
                capped[strategy_id] += min(available, deficit * available / room_total)
        elif total > 0:
            capped = {strategy_id: weight / total for strategy_id, weight in capped.items()}
    return _normalize_weights(capped)


def _portfolio_quality_weights(
    *,
    summaries: dict[str, dict[str, float | int]],
    returns: pd.DataFrame,
    avg_abs_correlation: dict[str, float],
    correlation_penalty: float,
    max_single_weight: float,
    periods_per_year: float,
) -> dict[str, float]:
    raw_scores: dict[str, float] = {}
    for strategy_id, summary in summaries.items():
        series = returns.get(strategy_id, pd.Series(dtype=float)).fillna(0.0)
        annualized_vol_pct = float(series.std(ddof=0)) * sqrt(periods_per_year) * 100.0 if len(series) > 1 else 0.0
        quality = max(0.0, _summary_quality_score(summary))
        activity_penalty = 0.0 if int(summary["trade_count"]) > 0 else 0.9
        corr_penalty = max(0.08, 1.0 - min(0.95, avg_abs_correlation.get(strategy_id, 0.0)) * float(correlation_penalty))
        risk_denominator = max(5.0, annualized_vol_pct)
        raw_scores[strategy_id] = max(0.0, quality * corr_penalty * (1.0 - activity_penalty) / risk_denominator)

    if sum(raw_scores.values()) <= 0:
        raw_scores = {
            strategy_id: max(0.0, float(summary["profit_factor"]) - 0.9)
            for strategy_id, summary in summaries.items()
        }
    if sum(raw_scores.values()) <= 0:
        raw_scores = {strategy_id: 1.0 for strategy_id in summaries}
    return _cap_weight_map(raw_scores, max_single_weight=max_single_weight)


def _risk_budget_payload(
    weights: dict[str, float],
    returns: pd.DataFrame,
    avg_abs_correlation: dict[str, float],
    periods_per_year: float,
) -> list[dict[str, Any]]:
    weighted_risk: dict[str, float] = {}
    vols: dict[str, float] = {}
    for strategy_id, weight in weights.items():
        series = returns.get(strategy_id, pd.Series(dtype=float)).fillna(0.0)
        volatility = float(series.std(ddof=0)) * sqrt(periods_per_year) if len(series) > 1 else 0.0
        vols[strategy_id] = volatility
        weighted_risk[strategy_id] = max(0.0, weight * volatility)
    total_risk = sum(weighted_risk.values())
    if total_risk <= 0:
        total_risk = sum(weights.values()) or 1.0
        weighted_risk = dict(weights)

    return [
        {
            "strategy_id": strategy_id,
            "weight_pct": _round(weight * 100.0, 4),
            "risk_contribution_pct": _round(weighted_risk.get(strategy_id, 0.0) / total_risk * 100.0, 4),
            "standalone_volatility_pct": _round(vols.get(strategy_id, 0.0) * 100.0, 4),
            "avg_abs_correlation": _round(avg_abs_correlation.get(strategy_id, 0.0), 4),
        }
        for strategy_id, weight in sorted(weights.items(), key=lambda item: item[1], reverse=True)
    ]


def _portfolio_risk_overlay(summary: dict[str, float | int], cash_reserve_pct: float, max_single_weight: float) -> dict[str, Any]:
    max_drawdown = float(summary["max_drawdown_pct"])
    if max_drawdown <= -12.0:
        state = "stop_new_risk"
        gross_multiplier = 0.0
    elif max_drawdown <= -8.0:
        state = "halve_risk"
        gross_multiplier = 0.5
    elif max_drawdown <= -5.0:
        state = "reduce_risk"
        gross_multiplier = 0.75
    else:
        state = "normal"
        gross_multiplier = 1.0
    return {
        "state": state,
        "suggested_gross_multiplier": gross_multiplier,
        "cash_reserve_pct": _round(cash_reserve_pct, 4),
        "max_single_weight_pct": _round(max_single_weight * 100.0, 4),
        "drawdown_trigger_pct": max_drawdown,
    }


def _build_portfolio_recommendations(
    *,
    baseline: dict[str, float | int],
    optimized: dict[str, float | int],
    pairs: list[dict[str, Any]],
    risk_overlay: dict[str, Any],
) -> list[str]:
    recommendations: list[str] = []
    if float(optimized["sharpe_ratio"]) > float(baseline["sharpe_ratio"]) + 0.15:
        recommendations.append("建议用优化权重进入下一轮组合回测，风险调整后收益质量优于当前权重。")
    else:
        recommendations.append("优化权重相对当前权重提升有限，应优先检查策略相关性和单策略稳定性。")

    if pairs and float(pairs[0]["abs_correlation"]) > 0.75:
        recommendations.append(f"{pairs[0]['left']} 与 {pairs[0]['right']} 相关性偏高，实盘资金分配应避免同时满权重运行。")
    if risk_overlay["state"] != "normal":
        recommendations.append("组合回撤已触发风险降档，建议把该降仓规则同步到事件回测和 paper trading。")
    if float(optimized["profit_factor"]) < 1.1:
        recommendations.append("组合 Profit Factor 仍偏低，先不要扩大策略数量，应淘汰交易边际弱的策略。")
    if not recommendations:
        recommendations.append("组合层未触发明显风险警报，下一步可以进入数据质量与特征版本治理。")
    return recommendations


def _simulate(
    frame: pd.DataFrame,
    config: SimulationConfig,
    weights: dict[str, float],
    signals: dict[str, pd.Series],
) -> BacktestArtifacts:
    normalized_weights = _normalize_weights(weights)
    periods_per_year = settings.periods_per_year(config.interval)

    kelly = KellySizer()
    orthogonalization = OrthogonalizationEngine()
    volatility_scaler = VolatilityScaler()
    breaker = DrawdownCircuitBreaker(cooldown_bars=max(4, int(periods_per_year // 365)))

    # Rebalance frequency: recompute risk overlays every N bars instead of every bar.
    # 1h bars ≈ 6.5 bars/day, so 20 bars ≈ 3 trading days. Daily on 1d bars.
    _rebalance_every = max(1, int(periods_per_year // 252 * 20))

    timestamps = list(frame.index)
    close = frame["close"]
    n_bars = len(frame.index)
    equity = pd.Series(index=frame.index, dtype=float)
    portfolio_returns = pd.Series(index=frame.index, dtype=float)
    drawdown = pd.Series(index=frame.index, dtype=float)
    exposure = pd.Series(index=frame.index, dtype=float)
    net_units = pd.Series(index=frame.index, dtype=float)
    order_notional = pd.Series(index=frame.index, dtype=float)
    commission_costs = pd.Series(index=frame.index, dtype=float)
    slippage_costs = pd.Series(index=frame.index, dtype=float)
    leverage_series = pd.Series(index=frame.index, dtype=float)
    turnover_series = pd.Series(index=frame.index, dtype=float)
    volume_capped = pd.Series(index=frame.index, dtype=float)

    # Pre-build strategy returns matrix once; slice views are cheap.
    _close_ret = close.pct_change().fillna(0.0)
    strategy_return_cols: dict[str, pd.Series] = {}
    for strategy_id, signal in signals.items():
        strategy_return_cols[strategy_id] = (signal.shift(1).fillna(0.0) * _close_ret)
    _returns_df = pd.DataFrame(strategy_return_cols, index=frame.index).fillna(0.0)

    current_equity = config.capital
    current_units = 0.0
    markers: list[TradeMarker] = []
    latest_weights = dict(normalized_weights)
    hwm = config.capital

    # Turnover reduction state
    _last_trade_direction: float = 0.0  # +1 long, -1 short, 0 flat
    _bars_since_entry: int = 0
    _cumulative_turnover: float = 0.0

    equity.iloc[0] = current_equity
    portfolio_returns.iloc[0] = 0.0
    drawdown.iloc[0] = 0.0
    exposure.iloc[0] = 0.0
    net_units.iloc[0] = 0.0
    order_notional.iloc[0] = 0.0
    commission_costs.iloc[0] = 0.0
    slippage_costs.iloc[0] = 0.0
    leverage_series.iloc[0] = 0.0
    turnover_series.iloc[0] = 0.0
    volume_capped.iloc[0] = 0.0

    # Cached risk overlay outputs, recomputed every _rebalance_every bars.
    _cached_weights = dict(normalized_weights)
    _cached_leverage = config.leverage

    for index in range(1, n_bars):
        timestamp = timestamps[index]
        previous_close = float(close.iloc[index - 1])
        current_close = float(close.iloc[index])

        # --- Periodic risk overlay recomputation ---
        if (index - 1) % _rebalance_every == 0:
            window = _returns_df.iloc[:index]

            dynamic_weights: dict[str, float] = {}
            for strategy_id, base_weight in normalized_weights.items():
                col = window[strategy_id] if strategy_id in window.columns else pd.Series(dtype=float)
                dynamic_weights[strategy_id] = base_weight * kelly.multiplier(col)

            adjusted_weights, diversity_scaler = orthogonalization.apply(dynamic_weights, window)
            _cached_weights = _normalize_weights(adjusted_weights)

            realized = portfolio_returns.iloc[:index].fillna(0.0)
            vol_mult = volatility_scaler.multiplier(realized.tail(96), periods_per_year)
            breaker_mult = breaker.update(current_equity)
            _cached_leverage = config.leverage * vol_mult * diversity_scaler * breaker_mult
            _cached_leverage = clamp(_cached_leverage, 0.1, 3.0)

        latest_weights = _cached_weights
        leverage = _cached_leverage

        risk_budget = config.capital if config.position_basis == "capital" else current_equity
        total_exposure = risk_budget * leverage

        target_units = 0.0
        for strategy_id, weight in latest_weights.items():
            signal_value = float(signals[strategy_id].iloc[index - 1])
            notional = total_exposure * weight * signal_value
            target_units += notional / previous_close if previous_close > 0 else 0.0

        delta_units = target_units - current_units
        current_order_notional = abs(delta_units) * previous_close

        # --- Turnover reduction: rebalance buffer ---
        _max_position = total_exposure / previous_close if previous_close > 0 else 0.0
        if _max_position > 0 and abs(delta_units) / _max_position < config.rebalance_buffer_pct:
            delta_units = 0.0
            current_order_notional = 0.0

        # --- Turnover reduction: minimum holding period ---
        _new_direction = 1.0 if delta_units > 0 else (-1.0 if delta_units < 0 else 0.0)
        if _new_direction != 0 and _new_direction != _last_trade_direction and _bars_since_entry < config.min_holding_bars:
            delta_units = 0.0
            current_order_notional = 0.0
        else:
            _bars_since_entry += 1

        # --- Turnover reduction: cost-aware signal filter ---
        if config.cost_aware_filter and current_order_notional > 0:
            _estimated_cost = current_order_notional * config.commission_rate + abs(delta_units) * config.slippage
            _expected_return = abs(delta_units) * previous_close * 0.01  # 1% expected move proxy
            if _expected_return < _estimated_cost:
                delta_units = 0.0
                current_order_notional = 0.0

        # --- Turnover reduction: annual turnover guard ---
        if current_order_notional > 0:
            _annual_turnover_est = (_cumulative_turnover + current_order_notional) / max(1.0, current_equity) / (index / max(1, n_bars)) * periods_per_year
            if _annual_turnover_est > config.max_annual_turnover_pct / 100.0:
                delta_units = 0.0
                current_order_notional = 0.0

        bar_volume = float(frame["volume"].iloc[index - 1]) if "volume" in frame.columns else 0.0
        capped_notional = 0.0
        if bar_volume > 0 and config.volume_participation_cap_pct > 0:
            max_notional = bar_volume * previous_close * config.volume_participation_cap_pct / 100.0
            if current_order_notional > max_notional:
                capped_notional = current_order_notional - max_notional
                capped_ratio = max_notional / max(1e-9, current_order_notional)
                current_order_notional = max_notional
                delta_units *= capped_ratio

        transaction_cost = current_order_notional * config.commission_rate
        slippage_cost = abs(delta_units) * config.slippage
        pnl = current_units * (current_close - previous_close) - transaction_cost - slippage_cost
        current_equity = max(1.0, current_equity + pnl)
        current_units = target_units

        # Update turnover reduction state
        if abs(delta_units) > 1e-9:
            _last_trade_direction = _new_direction
            _bars_since_entry = 0
            _cumulative_turnover += current_order_notional

        current_return = pnl / max(1.0, equity.iloc[index - 1])
        portfolio_returns.iloc[index] = current_return
        equity.iloc[index] = current_equity
        exposure.iloc[index] = abs(target_units * current_close)
        net_units.iloc[index] = current_units
        order_notional.iloc[index] = current_order_notional
        volume_capped.iloc[index] = capped_notional
        commission_costs.iloc[index] = transaction_cost
        slippage_costs.iloc[index] = slippage_cost
        leverage_series.iloc[index] = leverage
        turnover_series.iloc[index] = current_order_notional / max(1.0, equity.iloc[index - 1])
        hwm = max(hwm, current_equity)
        drawdown.iloc[index] = current_equity / hwm - 1.0

        if abs(delta_units) > 1e-9:
            position, color, shape, text = _signal_trade_text(delta_units=delta_units, target_units=target_units)
            markers.append(
                TradeMarker(
                    time=_to_epoch(timestamp),
                    position=position,
                    color=color,
                    shape=shape,
                    text=text,
                )
            )

    equity_filled = equity.ffill()
    returns_filled = portfolio_returns.fillna(0.0)
    order_notional_filled = order_notional.fillna(0.0)
    commission_costs_filled = commission_costs.fillna(0.0)
    slippage_costs_filled = slippage_costs.fillna(0.0)
    exposure_filled = exposure.fillna(0.0)
    net_units_filled = net_units.fillna(0.0)
    summary = _compute_summary(equity_filled, portfolio_returns.fillna(0.0), periods_per_year, trade_count=len(markers))
    drawdown_periods = _compute_drawdown_periods(equity_filled)
    monthly_returns = _compute_periodic_returns(equity_filled, freq="ME")
    annual_returns = _compute_periodic_returns(equity_filled, freq="YE")
    return_stats = _compute_return_diagnostics(returns_filled, periods_per_year=periods_per_year)
    execution_stats = _compute_execution_diagnostics(
        equity=equity_filled,
        order_notional=order_notional_filled,
        commission_costs=commission_costs_filled,
        slippage_costs=slippage_costs_filled,
        periods_per_year=periods_per_year,
        volume_capped=volume_capped.fillna(0.0),
    )
    exposure_stats = _compute_exposure_diagnostics(equity_filled, exposure_filled, net_units_filled)
    report_sections = _build_report_sections(
        summary=summary,
        return_stats=return_stats,
        execution_stats=execution_stats,
        exposure_stats=exposure_stats,
        monthly_returns=monthly_returns,
        drawdown_periods=drawdown_periods,
    )
    optimization_hints = _build_optimization_hints(
        summary=summary,
        return_stats=return_stats,
        execution_stats=execution_stats,
        exposure_stats=exposure_stats,
    )
    chart = {
        "candles": _build_candle_payload(frame),
        "markers": [marker.__dict__ for marker in markers],
        "equity": _build_series_payload(equity_filled),
        "drawdown": _build_series_payload(drawdown.fillna(0.0) * 100.0),
        "exposure": _build_series_payload(exposure_filled),
        "net_units": _build_series_payload(net_units_filled),
        "turnover": _build_series_payload(turnover_series.fillna(0.0) * 100.0),
        "leverage": _build_series_payload(leverage_series.fillna(0.0)),
    }

    strategy_details = _build_strategy_details(
        base_weights=normalized_weights,
        latest_weights=latest_weights,
        strategy_returns=strategy_return_cols,
    )
    diagnostics = {
        "periods_per_year": periods_per_year,
        "data_source": config.source,
        "position_basis": config.position_basis,
        "latest_leverage": round(float(leverage), 6),
        "latest_weight_map": latest_weights,
        "start_equity": _round(float(equity_filled.iloc[0]), 4),
        "end_equity": _round(float(equity_filled.iloc[-1]), 4),
        "net_profit": _round(float(equity_filled.iloc[-1] - equity_filled.iloc[0]), 4),
        "report_sections": report_sections,
        "optimization_hints": optimization_hints,
        "drawdown_periods": drawdown_periods,
        "monthly_returns": monthly_returns,
        "annual_returns": annual_returns,
        "return_distribution": return_stats,
        "execution": execution_stats,
        "exposure": exposure_stats,
    }

    return BacktestArtifacts(
        mode=config.mode,
        summary=summary,
        chart=chart,
        strategy_details=strategy_details,
        latest_weights=[
            {
                "strategy_id": strategy_id,
                "display_name": strategy_registry.get(strategy_id).descriptor.display_name,
                "weight": round(float(weight), 6),
            }
            for strategy_id, weight in latest_weights.items()
            if weight > 0
        ],
        diagnostics=diagnostics,
    )


class ResearchBacktestService:
    def list_strategies(self) -> list[StrategyDescriptor]:
        return strategy_registry.list_descriptors()

    def run_single(self, request: dict[str, Any]) -> BacktestArtifacts:
        config = SimulationConfig(
            mode="single",
            source=request.get("source", settings.default_data_source),
            symbol=request.get("symbol", settings.default_symbol),
            interval=request.get("interval", settings.default_interval),
            start=request["start"],
            end=request["end"],
            capital=float(request.get("capital", settings.default_capital)),
            commission_rate=float(request.get("commission_rate", settings.default_commission_rate)),
            slippage=float(request.get("slippage", settings.default_slippage)),
            leverage=float(request.get("leverage", settings.default_leverage)),
            position_basis=str(request.get("position_basis", "equity")),
            db_path=str(request.get("data_db_path", "")),
            rebalance_buffer_pct=float(request.get("rebalance_buffer_pct", 0.01)),
            min_holding_bars=int(request.get("min_holding_bars", 5)),
            cost_aware_filter=bool(request.get("cost_aware_filter", True)),
            max_annual_turnover_pct=float(request.get("max_annual_turnover_pct", 5000.0)),
        )
        frame = load_market_frame(
            source=config.source,
            symbol=config.symbol,
            interval=config.interval,
            start=config.start,
            end=config.end,
            db_path=config.db_path,
        )
        strategy_id = request["strategy_id"]
        signals, _ = _prepare_strategy_pack(frame, [strategy_id], params_map={strategy_id: request.get("strategy_params", {})})
        result = _simulate(frame=frame, config=config, weights={strategy_id: 1.0}, signals=signals)
        result.diagnostics["selected_strategy"] = strategy_id
        return result

    def optimize_strategy(self, request: dict[str, Any]) -> dict[str, Any]:
        config = SimulationConfig(
            mode="optimization",
            source=request.get("source", settings.default_data_source),
            symbol=request.get("symbol", settings.default_symbol),
            interval=request.get("interval", settings.default_interval),
            start=request["start"],
            end=request["end"],
            capital=float(request.get("capital", settings.default_capital)),
            commission_rate=float(request.get("commission_rate", settings.default_commission_rate)),
            slippage=float(request.get("slippage", settings.default_slippage)),
            leverage=float(request.get("leverage", settings.default_leverage)),
            position_basis=str(request.get("position_basis", "equity")),
            db_path=str(request.get("data_db_path", "")),
        )
        strategy_id = request["strategy_id"]
        frame = load_market_frame(
            source=config.source,
            symbol=config.symbol,
            interval=config.interval,
            start=config.start,
            end=config.end,
            db_path=config.db_path,
        )
        train_frame, validation_frame = _split_train_validation(frame)
        candidates = _candidate_parameter_grid(strategy_id)
        max_candidates = max(1, min(int(request.get("max_candidates", 18)), 64))
        candidates = candidates[:max_candidates]

        rows: list[dict[str, Any]] = []
        for index, params in enumerate(candidates, start=1):
            train_signals, _ = _prepare_strategy_pack(train_frame, [strategy_id], params_map={strategy_id: params})
            validation_signals, _ = _prepare_strategy_pack(validation_frame, [strategy_id], params_map={strategy_id: params})
            train_result = _simulate(frame=train_frame, config=config, weights={strategy_id: 1.0}, signals=train_signals)
            validation_result = _simulate(frame=validation_frame, config=config, weights={strategy_id: 1.0}, signals=validation_signals)
            score = _robust_optimization_score(train_result.summary, validation_result.summary)
            rows.append(
                {
                    "rank": index,
                    "strategy_id": strategy_id,
                    "parameters": params,
                    "score": score,
                    "train": train_result.summary,
                    "validation": validation_result.summary,
                    "overfit_gap": round(float(train_result.summary["sharpe_ratio"]) - float(validation_result.summary["sharpe_ratio"]), 6),
                }
            )

        rows.sort(key=lambda item: item["score"], reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank

        default_params = dict(strategy_registry.get(strategy_id).descriptor.default_params)
        baseline = next((row for row in rows if row["parameters"] == default_params), None)
        if baseline is None and rows:
            baseline = rows[0]
        best = rows[0] if rows else None
        recommendations: list[str] = []
        if best and baseline:
            delta = float(best["score"]) - float(baseline["score"])
            if delta > 0.25:
                recommendations.append("优先用最优参数进入下一轮 walk-forward，当前候选明显优于默认参数。")
            else:
                recommendations.append("最优参数相对默认参数优势有限，说明默认参数尚可，下一步应做更长样本和压力测试。")
            if float(best["validation"]["max_drawdown_pct"]) < -10:
                recommendations.append("样本外回撤仍偏高，参数优化后还需要降低杠杆或增加回撤降仓规则。")
            if float(best["validation"]["profit_factor"]) < 1.15:
                recommendations.append("样本外 Profit Factor 仍不足，优化方向应从入场过滤转向交易边际和成本控制。")

        return {
            "status": "completed",
            "selected_priority": "参数稳健性 + 样本外验证",
            "framework": _optimization_framework(1),
            "split": {
                "train_start": _to_epoch(train_frame.index[0]),
                "train_end": _to_epoch(train_frame.index[-1]),
                "validation_start": _to_epoch(validation_frame.index[0]),
                "validation_end": _to_epoch(validation_frame.index[-1]),
                "train_rows": len(train_frame),
                "validation_rows": len(validation_frame),
            },
            "baseline": baseline,
            "best": best,
            "candidates": rows[:10],
            "recommendations": recommendations,
        }

    def run_cost_stress(self, request: dict[str, Any]) -> dict[str, Any]:
        config = SimulationConfig(
            mode="cost_stress",
            source=request.get("source", settings.default_data_source),
            symbol=request.get("symbol", settings.default_symbol),
            interval=request.get("interval", settings.default_interval),
            start=request["start"],
            end=request["end"],
            capital=float(request.get("capital", settings.default_capital)),
            commission_rate=float(request.get("commission_rate", settings.default_commission_rate)),
            slippage=float(request.get("slippage", settings.default_slippage)),
            leverage=float(request.get("leverage", settings.default_leverage)),
            position_basis=str(request.get("position_basis", "equity")),
            db_path=str(request.get("data_db_path", "")),
        )
        strategy_id = request["strategy_id"]
        strategy_params = request.get("strategy_params", {})
        frame = load_market_frame(
            source=config.source,
            symbol=config.symbol,
            interval=config.interval,
            start=config.start,
            end=config.end,
            db_path=config.db_path,
        )
        signals, _ = _prepare_strategy_pack(frame, [strategy_id], params_map={strategy_id: strategy_params})
        rows: list[dict[str, Any]] = []
        baseline_summary: dict[str, float | int] | None = None

        for scenario in _cost_stress_scenarios(int(request.get("max_scenarios", 5))):
            scenario_config = SimulationConfig(
                mode="cost_stress",
                source=config.source,
                symbol=config.symbol,
                interval=config.interval,
                start=config.start,
                end=config.end,
                capital=config.capital,
                commission_rate=config.commission_rate * float(scenario["commission_multiplier"]),
                slippage=config.slippage * float(scenario["slippage_multiplier"]),
                leverage=config.leverage,
                position_basis=config.position_basis,
                db_path=config.db_path,
            )
            result = _simulate(frame=frame, config=scenario_config, weights={strategy_id: 1.0}, signals=signals)
            summary = result.summary
            if baseline_summary is None:
                baseline_summary = summary
            survives = _cost_stress_survives(summary)
            rows.append(
                {
                    **scenario,
                    "commission_rate": round(scenario_config.commission_rate, 8),
                    "slippage": round(scenario_config.slippage, 6),
                    "survives": survives,
                    "summary": summary,
                    "execution": result.diagnostics.get("execution", {}),
                    "return_decay_pct": round(float(summary["total_return_pct"]) - float(baseline_summary["total_return_pct"]), 4),
                    "sharpe_decay": round(float(summary["sharpe_ratio"]) - float(baseline_summary["sharpe_ratio"]), 4),
                }
            )

        survival_rate = sum(1 for row in rows if row["survives"]) / max(1, len(rows)) * 100
        worst_case = min(rows, key=lambda row: float(row["summary"]["total_return_pct"])) if rows else None
        return {
            "status": "completed",
            "selected_priority": "交易成本压力测试",
            "framework": _optimization_framework(2),
            "strategy_id": strategy_id,
            "strategy_params": strategy_params,
            "baseline": rows[0] if rows else None,
            "scenarios": rows,
            "survival_rate_pct": round(survival_rate, 4),
            "worst_case": worst_case,
            "recommendations": _build_cost_stress_recommendations(rows),
        }

    def run_walk_forward(self, request: dict[str, Any]) -> dict[str, Any]:
        from quant_us.backtest.data_bridge import bars_from_dataframe
        from quant_us.backtest.unified_runner import UnifiedBacktestConfig
        from quant_us.backtest.walk_forward import WalkForwardConfig, run_walk_forward_unified
        from quant_us.core.enums import SignalDirection
        from quant_us.core.events import MarketEvent
        from quant_us.core.types import Signal
        from quant_us.strategies.base import Strategy, StrategyContext

        strategy_id = request["strategy_id"]
        requested_params = dict(request.get("strategy_params", {}) or {})
        requested_windows = int(request.get("windows", 4))
        symbols: list[str] = request.get("symbols", [])
        if not symbols:
            # Fall back to single-symbol mode
            single = request.get("symbol", settings.default_symbol)
            symbols = [single] if single else ["SPY"]

        strategy_base = strategy_registry.get(strategy_id)
        merged_params: dict[str, float] = {**strategy_base.descriptor.default_params, **requested_params}

        # Per-symbol walk-forward
        all_windows: list[dict[str, Any]] = []
        all_regimes: list[dict[str, Any]] = []
        symbol_results: dict[str, dict[str, Any]] = {}
        insufficient_symbols: list[str] = []

        for symbol in symbols:
            config = SimulationConfig(
                mode="walk_forward",
                source=request.get("source", settings.default_data_source),
                symbol=symbol,
                interval=request.get("interval", settings.default_interval),
                start=request["start"],
                end=request["end"],
                capital=float(request.get("capital", settings.default_capital)),
                commission_rate=float(request.get("commission_rate", settings.default_commission_rate)),
                slippage=float(request.get("slippage", settings.default_slippage)),
                leverage=float(request.get("leverage", settings.default_leverage)),
                position_basis=str(request.get("position_basis", "equity")),
                db_path=str(request.get("data_db_path", "")),
            )

            frame = load_market_frame(
                source=config.source, symbol=config.symbol,
                interval=config.interval, start=config.start, end=config.end,
                db_path=config.db_path,
            )

            if len(frame) < 50:
                insufficient_symbols.append(symbol)
                all_windows.append({
                    "fold": 0, "symbol": symbol, "bar_count": len(frame),
                    "survives": False, "status": "insufficient_data",
                    "note": f"Only {len(frame)} bars available, need at least 50 for walk-forward.",
                })
                continue

            bars = bars_from_dataframe(frame, source=config.source)
            signals, _ = _prepare_strategy_pack(frame, [strategy_id], params_map={strategy_id: merged_params})
            signal_series = signals[strategy_id]
            signal_lookup: dict = {
                ts.to_pydatetime(): float(value) for ts, value in signal_series.items()
            }

            _wf_strategy_id = strategy_id

            class _WfSignalStrategy(Strategy):
                version = "0.1.0"

                def on_bar(self, event: MarketEvent, context: StrategyContext):
                    sig = signal_lookup.get(event.timestamp_utc, 0.0)
                    if abs(sig) > 0:
                        direction = SignalDirection.LONG if sig > 0 else SignalDirection.SHORT
                        return [
                            Signal(
                                timestamp_utc=event.timestamp_utc,
                                strategy_id=_wf_strategy_id,
                                symbol=event.bar.symbol,
                                direction=direction,
                                strength=abs(sig),
                                horizon="1b",
                            )
                        ]
                    return []

            _WfSignalStrategy.strategy_id = f"wf_{_wf_strategy_id}"

            num_windows = max(1, min(requested_windows, 8))
            total_bars = len(bars)
            train_bars = max(20, int(total_bars * 0.65))
            remaining = total_bars - train_bars
            test_bars = max(10, remaining // num_windows)
            step_bars = test_bars

            wf_config = WalkForwardConfig(train_bars=train_bars, test_bars=test_bars, step_bars=step_bars)
            unified_config = UnifiedBacktestConfig(
                initial_cash=config.capital,
                commission_rate=config.commission_rate,
                slippage_bps=config.slippage,
                run_id=f"wf_{strategy_id}_{symbol}",
            )

            wf_results = run_walk_forward_unified(
                bars=bars,
                strategy_factory=lambda: _WfSignalStrategy(),
                wf_config=wf_config,
                unified_config=unified_config,
            )

            symbol_folds: list[dict[str, Any]] = []
            for fold, result in enumerate(wf_results, start=1):
                w = result.window
                val_summary = result.unified.summary
                survives = _walk_forward_survives(val_summary)
                symbol_folds.append({
                    "fold": fold,
                    "symbol": symbol,
                    "train_start": _to_epoch(pd.Timestamp(w.train_start)),
                    "train_end": _to_epoch(pd.Timestamp(w.train_end)),
                    "validation_start": _to_epoch(pd.Timestamp(w.test_start)),
                    "validation_end": _to_epoch(pd.Timestamp(w.test_end)),
                    "train_rows": 0,
                    "validation_rows": 0,
                    "selected_params": dict(merged_params),
                    "train_score": 0.0,
                    "train": {},
                    "validation": val_summary,
                    "survives": survives,
                    "equity_consistent": result.unified.equity_consistent,
                })
            all_windows.extend(symbol_folds)

            regimes = _build_regime_slices(
                frame=frame, config=config,
                strategy_id=strategy_id, strategy_params=merged_params,
            )
            all_regimes.extend(regimes)

            symbol_results[symbol] = {
                "folds": len(symbol_folds),
                "passes": sum(1 for f in symbol_folds if f["survives"]),
                "bar_count": len(frame),
            }

        # --- Aggregate multi-symbol results ---
        total_folds = len(all_windows)
        valid_folds = [w for w in all_windows if w.get("status") != "insufficient_data"]
        passing_folds = [w for w in valid_folds if w["survives"]]
        fold_pass_rate = (len(passing_folds) / max(1, len(valid_folds)) * 100.0) if valid_folds else 0.0

        # Build stability metrics
        validation_returns = [float(w["validation"]["total_return_pct"]) for w in valid_folds if "validation" in w]
        validation_sharpes = [float(w["validation"]["sharpe_ratio"]) for w in valid_folds if "validation" in w]
        validation_drawdowns = [float(w["validation"]["max_drawdown_pct"]) for w in valid_folds if "validation" in w]
        consistent_count = sum(1 for w in valid_folds if w.get("equity_consistent", False))

        symbols_covered = [s for s in symbols if s not in insufficient_symbols]
        regime_passes = sum(1 for r in all_regimes if r.get("survives", False))

        stability = {
            "total_folds": total_folds,
            "valid_folds": len(valid_folds),
            "passing_folds": len(passing_folds),
            "fold_pass_rate_pct": _round(fold_pass_rate, 4),
            "pass_rate_pct": _round(fold_pass_rate, 4),  # backward compat
            "window_count": len(valid_folds),             # backward compat
            "avg_oos_return_pct": _round(float(np.mean(validation_returns)) if validation_returns else 0.0, 4),
            "median_oos_sharpe": _round(float(np.median(validation_sharpes)) if validation_sharpes else 0.0, 4),
            "worst_oos_drawdown_pct": _round(min(validation_drawdowns) if validation_drawdowns else 0.0, 4),
            "parameter_stability_pct": 100.0,
            "regime_pass_rate_pct": _round(regime_passes / max(1, len(all_regimes)) * 100.0, 4),
            "ledger_equity_consistent_windows": consistent_count,
            "ledger_consistency_pct": _round(consistent_count / max(1, len(valid_folds)) * 100.0, 4),
            "symbol_count": len(symbols),
            "symbols_covered": len(symbols_covered),
            "symbols_insufficient": len(insufficient_symbols),
            "symbol_details": symbol_results,
        }

        # Determine insufficient-data WARN
        is_insufficient = len(insufficient_symbols) > 0 and len(valid_folds) == 0
        recommendations = _build_walk_forward_recommendations(valid_folds, all_regimes)
        if insufficient_symbols:
            recommendations.insert(0, f"数据不足: {', '.join(insufficient_symbols)} 少于 50 bar，无法做 walk-forward。")

        # --- Persist walk-forward manifest ---
        manifest_root = Path(request.get("data_root", "data")) / "reports" / "walk_forward"
        try:
            from quant_us.backtest.walk_forward import save_walk_forward_manifest
            from quant_us.backtest.walk_forward import WalkForwardAggregate

            wf_aggregate = WalkForwardAggregate(
                total_windows=total_folds,
                windows_consistent=consistent_count,
                oos_total_return_pct=float(stability.get("avg_oos_return_pct", 0.0)),
                oos_avg_sharpe=float(stability.get("median_oos_sharpe", 0.0)),
                oos_avg_max_dd=float(stability.get("worst_oos_drawdown_pct", 0.0)),
                oos_avg_turnover_pct=0.0,
                fold_pass_rate_pct=float(stability.get("fold_pass_rate_pct", 0.0)),
                symbol_coverage_pct=float(stability.get("symbols_covered", 0)) / max(1, len(symbols)) * 100.0,
                symbols_tested=list(symbols),
                insufficient_data=is_insufficient,
            )
            manifest_path = save_walk_forward_manifest(
                aggregate=wf_aggregate,
                manifest_dir=manifest_root,
                strategy_id=strategy_id,
                params=merged_params,
                data_version=str(request.get("data_version", "")),
            )
            stability["manifest_path"] = str(manifest_path)
        except Exception:
            pass

        return {
            "status": "insufficient_data" if is_insufficient else "completed",
            "selected_priority": "Walk-forward 与市场状态切片",
            "framework": _optimization_framework(3),
            "strategy_id": strategy_id,
            "strategy_params": merged_params,
            "symbols": symbols,
            "windows": all_windows,
            "regimes": all_regimes,
            "stability": stability,
            "recommendations": recommendations,
        }

    def optimize_portfolio(self, request: dict[str, Any]) -> dict[str, Any]:
        config = SimulationConfig(
            mode="portfolio_optimization",
            source=request.get("source", settings.default_data_source),
            symbol=request.get("symbol", settings.default_symbol),
            interval=request.get("interval", settings.default_interval),
            start=request["start"],
            end=request["end"],
            capital=float(request.get("capital", settings.default_capital)),
            commission_rate=float(request.get("commission_rate", settings.default_commission_rate)),
            slippage=float(request.get("slippage", settings.default_slippage)),
            leverage=float(request.get("leverage", settings.default_leverage)),
            position_basis=str(request.get("position_basis", "equity")),
            db_path=str(request.get("data_db_path", "")),
        )
        baseline_weights = _normalize_weights(_requested_portfolio_weights(request))
        if not baseline_weights:
            raise ValueError("At least one positive strategy weight is required for portfolio optimization.")

        max_single_weight = float(request.get("max_single_weight", 0.35))
        correlation_penalty = float(request.get("correlation_penalty", 0.75))
        cash_reserve_pct = float(request.get("cash_reserve_pct", 0.0))
        active_gross = max(0.05, 1.0 - cash_reserve_pct / 100.0)
        simulation_config = replace(config, leverage=config.leverage * active_gross)

        frame = load_market_frame(
            source=config.source,
            symbol=config.symbol,
            interval=config.interval,
            start=config.start,
            end=config.end,
            db_path=config.db_path,
        )
        strategy_ids = list(baseline_weights.keys())
        signals, _ = _prepare_strategy_pack(frame, strategy_ids)
        return_matrix = _strategy_return_matrix(frame, signals)
        correlation_matrix, correlation_pairs, avg_abs_correlation = _correlation_payload(return_matrix)
        periods_per_year = settings.periods_per_year(config.interval)

        standalone_summaries: dict[str, dict[str, float | int]] = {}
        standalone_rows: list[dict[str, Any]] = []
        for strategy_id in strategy_ids:
            standalone = _simulate(
                frame=frame,
                config=simulation_config,
                weights={strategy_id: 1.0},
                signals={strategy_id: signals[strategy_id]},
            )
            summary = standalone.summary
            standalone_summaries[strategy_id] = summary
            standalone_rows.append(
                {
                    "strategy_id": strategy_id,
                    "display_name": strategy_registry.get(strategy_id).descriptor.display_name,
                    "category": strategy_registry.get(strategy_id).descriptor.category,
                    "baseline_weight_pct": _round(baseline_weights.get(strategy_id, 0.0) * 100.0, 4),
                    "summary": summary,
                    "quality_score": _summary_quality_score(summary),
                    "avg_abs_correlation": avg_abs_correlation.get(strategy_id, 0.0),
                }
            )

        optimized_weights = _portfolio_quality_weights(
            summaries=standalone_summaries,
            returns=return_matrix,
            avg_abs_correlation=avg_abs_correlation,
            correlation_penalty=correlation_penalty,
            max_single_weight=max_single_weight,
            periods_per_year=periods_per_year,
        )
        baseline_result = _simulate(
            frame=frame,
            config=simulation_config,
            weights=baseline_weights,
            signals=signals,
        )
        optimized_result = _simulate(
            frame=frame,
            config=simulation_config,
            weights=optimized_weights,
            signals=signals,
        )
        risk_contributions = _risk_budget_payload(optimized_weights, return_matrix, avg_abs_correlation, periods_per_year)
        risk_overlay = _portfolio_risk_overlay(
            optimized_result.summary,
            cash_reserve_pct=cash_reserve_pct,
            max_single_weight=max_single_weight,
        )
        optimized_weight_rows = []
        for strategy_id, weight in sorted(optimized_weights.items(), key=lambda item: item[1], reverse=True):
            optimized_weight_rows.append(
                {
                    "strategy_id": strategy_id,
                    "display_name": strategy_registry.get(strategy_id).descriptor.display_name,
                    "weight": _round(weight, 6),
                    "weight_pct": _round(weight * 100.0, 4),
                    "baseline_weight_pct": _round(baseline_weights.get(strategy_id, 0.0) * 100.0, 4),
                }
            )
        for row in standalone_rows:
            strategy_id = row["strategy_id"]
            row["optimized_weight_pct"] = _round(optimized_weights.get(strategy_id, 0.0) * 100.0, 4)

        baseline_execution = baseline_result.diagnostics.get("execution", {})
        optimized_execution = optimized_result.diagnostics.get("execution", {})
        improvement = {
            "return_delta_pct": _round(float(optimized_result.summary["total_return_pct"]) - float(baseline_result.summary["total_return_pct"]), 4),
            "sharpe_delta": _round(float(optimized_result.summary["sharpe_ratio"]) - float(baseline_result.summary["sharpe_ratio"]), 4),
            "drawdown_delta_pct": _round(float(optimized_result.summary["max_drawdown_pct"]) - float(baseline_result.summary["max_drawdown_pct"]), 4),
            "cost_delta": _round(float(optimized_execution.get("total_cost", 0.0)) - float(baseline_execution.get("total_cost", 0.0)), 4),
        }

        return {
            "status": "completed",
            "selected_priority": "组合层相关性与资金分配",
            "framework": _optimization_framework(4),
            "baseline_weights": {key: _round(value, 6) for key, value in baseline_weights.items()},
            "optimized_weights": {key: _round(value, 6) for key, value in optimized_weights.items()},
            "optimized_weight_rows": optimized_weight_rows,
            "baseline_summary": baseline_result.summary,
            "optimized_summary": optimized_result.summary,
            "improvement": improvement,
            "strategy_allocations": standalone_rows,
            "correlation_matrix": correlation_matrix,
            "correlation_pairs": correlation_pairs[:10],
            "risk_budget": {
                "active_gross_pct": _round(active_gross * 100.0, 4),
                "cash_reserve_pct": _round(cash_reserve_pct, 4),
                "risk_contributions": risk_contributions,
                "max_pair_abs_correlation": correlation_pairs[0]["abs_correlation"] if correlation_pairs else 0.0,
            },
            "risk_overlay": risk_overlay,
            "recommendations": _build_portfolio_recommendations(
                baseline=baseline_result.summary,
                optimized=optimized_result.summary,
                pairs=correlation_pairs,
                risk_overlay=risk_overlay,
            ),
        }

    def run_portfolio(self, request: dict[str, Any]) -> BacktestArtifacts:
        config = SimulationConfig(
            mode="portfolio",
            source=request.get("source", settings.default_data_source),
            symbol=request.get("symbol", settings.default_symbol),
            interval=request.get("interval", settings.default_interval),
            start=request["start"],
            end=request["end"],
            capital=float(request.get("capital", settings.default_capital)),
            commission_rate=float(request.get("commission_rate", settings.default_commission_rate)),
            slippage=float(request.get("slippage", settings.default_slippage)),
            leverage=float(request.get("leverage", settings.default_leverage)),
            position_basis=str(request.get("position_basis", "equity")),
            db_path=str(request.get("data_db_path", "")),
            rebalance_buffer_pct=float(request.get("rebalance_buffer_pct", 0.01)),
            min_holding_bars=int(request.get("min_holding_bars", 5)),
            cost_aware_filter=bool(request.get("cost_aware_filter", True)),
            max_annual_turnover_pct=float(request.get("max_annual_turnover_pct", 5000.0)),
        )
        frame = load_market_frame(
            source=config.source,
            symbol=config.symbol,
            interval=config.interval,
            start=config.start,
            end=config.end,
            db_path=config.db_path,
        )

        requested_weights = _requested_portfolio_weights(request)

        signals, _ = _prepare_strategy_pack(frame, list(requested_weights.keys()))
        result = _simulate(frame=frame, config=config, weights=requested_weights, signals=signals)
        result.diagnostics["requested_weight_map"] = requested_weights
        return result

    def run_event_driven_cost_stress(
        self, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Run cost stress through the event-driven engine for realistic fill-level validation.

        This complements the vectorized cost stress by using the full order lifecycle:
        OMS -> risk check -> broker fill -> ledger. PnL is derived from fills, not signals.
        Delegates to cost_stress_scanner.run_cost_stress() for the per-scenario backtest loop.
        """
        from quant_us.backtest.cost_stress_scanner import run_cost_stress
        from quant_us.backtest.data_bridge import bars_from_dataframe
        from quant_us.backtest.engine import BacktestConfig
        from quant_us.strategies.momentum_strategy import MomentumStrategy

        strategy_id = str(request.get("strategy_id", "trend_momentum"))
        symbol = str(request.get("symbol", settings.default_symbol))
        interval = str(request.get("interval", settings.default_interval))
        initial_cash = float(request.get("capital", settings.default_capital))

        frame = load_market_frame(
            source=request.get("source", settings.default_data_source),
            symbol=symbol,
            interval=interval,
            start=request["start"],
            end=request["end"],
            db_path=str(request.get("data_db_path", "")),
        )

        bars = bars_from_dataframe(frame, source="event_driven_cost_stress")

        base_commission = float(request.get("commission_rate", settings.default_commission_rate))
        base_slippage = float(request.get("slippage", settings.default_slippage))

        base_config = BacktestConfig(
            initial_cash=initial_cash,
            commission_rate=base_commission,
            slippage_bps=base_slippage,
        )

        scenarios = _cost_stress_scenarios(int(request.get("max_scenarios", 5)))
        multipliers = [
            (float(s["commission_multiplier"]), float(s["slippage_multiplier"]), s["label"])
            for s in scenarios
        ]

        strategy = MomentumStrategy(
            strategy_id="trend_momentum",
            lookback_bars=int(request.get("lookback_bars", 20)),
            entry_threshold=float(request.get("entry_threshold", 0.03)),
            allow_short=False,
        )

        report = run_cost_stress(
            strategies=[strategy],
            bars=bars,
            base_config=base_config,
            multipliers=multipliers,
        )

        results: list[dict[str, Any]] = []
        baseline_summary: dict[str, float | int] | None = None

        for scenario_def, level in zip(scenarios, report.levels):
            summary = {
                "total_return_pct": level.total_return_pct,
                "sharpe_ratio": level.sharpe_ratio,
                "max_drawdown_pct": level.max_drawdown_pct,
                "trade_count": level.trade_count,
            }
            if baseline_summary is None:
                baseline_summary = summary

            survives = (
                level.total_return_pct > 0
                and level.sharpe_ratio >= 0.5
                and level.max_drawdown_pct > -20.0
            )

            results.append(
                {
                    **scenario_def,
                    "commission_rate": round(level.commission_rate, 8),
                    "slippage_bps": round(level.slippage_bps, 4),
                    "survives": survives,
                    "summary": summary,
                    "execution": {},
                    "fill_count": level.trade_count,
                    "order_count": level.trade_count,
                    "return_decay_pct": round(
                        level.total_return_pct - baseline_summary["total_return_pct"],
                        4,
                    ),
                    "sharpe_decay": round(level.sharpe_decay, 4),
                }
            )

        survival_rate = sum(1 for r in results if r["survives"]) / max(1, len(results)) * 100
        return {
            "status": "completed",
            "engine": "event_driven",
            "strategy_id": strategy_id,
            "symbol": symbol,
            "interval": interval,
            "scenarios": results,
            "survival_rate_pct": round(survival_rate, 4),
            "baseline_fill_count": results[0]["fill_count"] if results else 0,
            "engine_note": "PnL derived from fills, orders go through OMS -> risk -> broker -> ledger",
        }
