from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
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

    timestamps = list(frame.index)
    close = frame["close"]
    equity = pd.Series(index=frame.index, dtype=float)
    portfolio_returns = pd.Series(index=frame.index, dtype=float)
    drawdown = pd.Series(index=frame.index, dtype=float)
    exposure = pd.Series(index=frame.index, dtype=float)
    net_units = pd.Series(index=frame.index, dtype=float)

    theoretical_returns: dict[str, pd.Series] = {}
    for strategy_id, signal in signals.items():
        shifted = signal.shift(1).fillna(0.0)
        theoretical_returns[strategy_id] = shifted * close.pct_change().fillna(0.0)

    current_equity = config.capital
    current_units = 0.0
    markers: list[TradeMarker] = []
    latest_weights = dict(normalized_weights)
    hwm = config.capital

    equity.iloc[0] = current_equity
    portfolio_returns.iloc[0] = 0.0
    drawdown.iloc[0] = 0.0
    exposure.iloc[0] = 0.0
    net_units.iloc[0] = 0.0

    for index in range(1, len(frame.index)):
        timestamp = timestamps[index]
        previous_timestamp = timestamps[index - 1]
        previous_close = float(close.iloc[index - 1])
        current_close = float(close.iloc[index])

        rolling_strategy_returns = pd.DataFrame(
            {name: series.iloc[:index] for name, series in theoretical_returns.items()}
        ).fillna(0.0)

        dynamic_weights: dict[str, float] = {}
        for strategy_id, base_weight in normalized_weights.items():
            multiplier = kelly.multiplier(rolling_strategy_returns.get(strategy_id, pd.Series(dtype=float)))
            dynamic_weights[strategy_id] = base_weight * multiplier

        adjusted_weights, diversity_scaler = orthogonalization.apply(dynamic_weights, rolling_strategy_returns)
        latest_weights = _normalize_weights(adjusted_weights)

        realized_returns = portfolio_returns.iloc[:index].fillna(0.0)
        volatility_multiplier = volatility_scaler.multiplier(realized_returns.tail(96), periods_per_year)
        breaker_multiplier = breaker.update(current_equity)
        leverage = config.leverage * volatility_multiplier * diversity_scaler * breaker_multiplier
        leverage = clamp(leverage, 0.1, 3.0)

        risk_budget = config.capital if config.position_basis == "capital" else current_equity
        total_exposure = risk_budget * leverage

        target_units = 0.0
        for strategy_id, weight in latest_weights.items():
            signal_value = float(signals[strategy_id].iloc[index - 1])
            notional = total_exposure * weight * signal_value
            target_units += notional / previous_close if previous_close > 0 else 0.0

        delta_units = target_units - current_units
        transaction_cost = abs(delta_units) * previous_close * config.commission_rate
        slippage_cost = abs(delta_units) * config.slippage
        pnl = current_units * (current_close - previous_close) - transaction_cost - slippage_cost
        current_equity = max(1.0, current_equity + pnl)
        current_units = target_units

        current_return = pnl / max(1.0, equity.iloc[index - 1])
        portfolio_returns.iloc[index] = current_return
        equity.iloc[index] = current_equity
        exposure.iloc[index] = abs(target_units * current_close)
        net_units.iloc[index] = current_units
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
    summary = _compute_summary(equity_filled, portfolio_returns.fillna(0.0), periods_per_year, trade_count=len(markers))
    chart = {
        "candles": _build_candle_payload(frame),
        "markers": [marker.__dict__ for marker in markers],
        "equity": _build_series_payload(equity_filled),
        "drawdown": _build_series_payload(drawdown.fillna(0.0) * 100.0),
        "exposure": _build_series_payload(exposure.fillna(0.0)),
        "net_units": _build_series_payload(net_units.fillna(0.0)),
    }

    strategy_details = _build_strategy_details(
        base_weights=normalized_weights,
        latest_weights=latest_weights,
        strategy_returns=theoretical_returns,
    )
    diagnostics = {
        "periods_per_year": periods_per_year,
        "data_source": config.source,
        "position_basis": config.position_basis,
        "latest_leverage": round(float(leverage), 6),
        "latest_weight_map": latest_weights,
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
        )
        frame = load_market_frame(
            source=config.source,
            symbol=config.symbol,
            interval=config.interval,
            start=config.start,
            end=config.end,
            db_path=config.db_path,
        )

        requested_weights = {
            item["strategy_id"]: float(item["weight"])
            for item in request.get("weights", [])
        }
        if not requested_weights:
            requested_weights = {
                descriptor.id: descriptor.default_weight
                for descriptor in strategy_registry.list_descriptors()
            }

        signals, _ = _prepare_strategy_pack(frame, list(requested_weights.keys()))
        result = _simulate(frame=frame, config=config, weights=requested_weights, signals=signals)
        result.diagnostics["requested_weight_map"] = requested_weights
        return result
