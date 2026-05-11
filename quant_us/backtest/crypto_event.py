from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from quant_us.backtest.data_bridge import SignalReplayStrategy
from quant_us.backtest.engine import BacktestBroker
from quant_us.backtest.ledger_pnl import ledger_state_at_time
from quant_us.backtest.unified_runner import UnifiedBacktestConfig, UnifiedBacktestResult, UnifiedBacktestRunner
from quant_us.core.events import MarketEvent
from quant_us.data.storage.data_manifest import DataManifestStore
from quant_us.portfolio.allocation import AllocationConfig
from quant_us.portfolio.position_sizer import PositionSizerConfig
from quant_us.portfolio.rebalance import RebalanceConfig
from quant_us.risk.pre_trade import PreTradeRiskConfig


MarketFrameLoader = Callable[..., pd.DataFrame]
SignalProvider = Callable[[pd.DataFrame, str, dict[str, Any]], pd.Series]


@dataclass
class CryptoEventBacktestArtifacts:
    mode: str
    summary: dict[str, float | int]
    chart: dict[str, list[dict[str, float | int | str]]]
    strategy_details: list[dict[str, Any]]
    latest_weights: list[dict[str, float | str]]
    diagnostics: dict[str, Any]
    unified: UnifiedBacktestResult


def run_crypto_event_backtest(
    *,
    source: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    strategy_id: str,
    params: dict[str, Any] | None = None,
    capital: float = 100_000.0,
    cost: float | None = None,
    commission_rate: float | None = None,
    slippage: float | None = None,
    slippage_bps: float | None = None,
    sqlite_path: str = "",
    db_path: str = "",
    data_version: str = "",
    strategy_version: str = "",
    manifest_root: str | Path | None = None,
    signal_provider: SignalProvider | None = None,
    market_loader: MarketFrameLoader | None = None,
    market_events: list[MarketEvent] | None = None,
    target_weight: float = 0.90,
    min_cash_buffer_pct: float | None = None,
    min_trade_notional: float = 25.0,
    long_only: bool = True,
    broker_factory: Callable[[UnifiedBacktestConfig], BacktestBroker] | None = None,
    run_id: str = "",
) -> CryptoEventBacktestArtifacts:
    """Run a single-symbol crypto backtest through the event-driven ledger path.

    The default loader/provider are lazy imports of the backend service and
    registry so the existing API can add a thin wrapper without duplicating
    execution semantics. Tests and batch jobs can inject either dependency.
    """

    requested_params = dict(params or {})
    loader = market_loader or _default_market_loader
    if market_events is None:
        frame = loader(
            source=source,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            db_path=db_path or sqlite_path,
        )
    else:
        frame = _frame_from_market_events(market_events)

    frame = _normalize_market_frame(frame, symbol=symbol)
    provider = signal_provider or _default_registry_signal_provider
    signal = provider(frame, strategy_id, requested_params).reindex(frame.index).fillna(0.0).clip(-1.0, 1.0)

    initial_cash = float(capital)
    commission = float(commission_rate if commission_rate is not None else (cost if cost is not None else 0.0001))
    slip_bps = float(slippage_bps if slippage_bps is not None else (slippage if slippage is not None else 1.0))
    execution_settings = _crypto_execution_settings(
        target_weight=target_weight,
        min_cash_buffer_pct=min_cash_buffer_pct,
        min_trade_notional=min_trade_notional,
        long_only=long_only,
    )

    config = UnifiedBacktestConfig(
        initial_cash=initial_cash,
        commission_rate=commission,
        slippage_bps=slip_bps,
        run_id=run_id or f"crypto_ed_{strategy_id}_{symbol.upper()}",
    )
    config = _with_crypto_execution_config(
        config,
        execution_settings=execution_settings,
    )
    runner = UnifiedBacktestRunner(config=config, broker_factory=broker_factory)
    if manifest_root is not None:
        runner.manifest_store = DataManifestStore(manifest_root)

    effective_data_version = data_version or _data_version(source, symbol, interval, start, end)
    effective_strategy_version = strategy_version or f"{strategy_id}:signal_replay_v1"
    strategy = SignalReplayStrategy(
        strategy_id=strategy_id,
        signal=signal,
        horizon="crypto_event_replay",
        params=requested_params,
    )

    if market_events is None:
        unified = runner.run(
            strategies=[strategy],
            frame=frame,
            data_version=effective_data_version,
            strategy_version=effective_strategy_version,
        )
    else:
        unified = runner.run(
            strategies=[strategy],
            market_events_override=market_events,
            data_version=effective_data_version,
            strategy_version=effective_strategy_version,
        )

    ledger_rows = _ledger_timeline(unified, frame=frame, initial_cash=initial_cash)
    summary = _ledger_summary(
        ledger_rows["equity"],
        periods_per_year=_crypto_periods_per_year(interval),
        trade_count=len(unified.fills),
    )
    chart = _chart_payload(frame=frame, unified=unified, ledger_rows=ledger_rows)
    final_equity = float(ledger_rows["equity"].iloc[-1]) if not ledger_rows["equity"].empty else initial_cash
    final_position_value = float(ledger_rows["exposure"].iloc[-1]) if not ledger_rows["exposure"].empty else 0.0
    latest_weight = final_position_value / max(final_equity, 1.0)

    diagnostics: dict[str, Any] = {
        "engine": "event_driven",
        "asset_class": "crypto",
        "source": source,
        "symbol": symbol.upper(),
        "interval": interval,
        "strategy_id": strategy_id,
        "strategy_params": requested_params,
        "data_version": effective_data_version,
        "strategy_version": effective_strategy_version,
        "manifest_id": unified.manifest_id,
        "manifest_path": unified.manifest_path,
        "pnl_source": "ledger_fills",
        "execution_semantics": unified.event_driven.metadata.get("execution_semantics"),
        "connection_health": runner.connection_health(),
        "orders": len(unified.orders),
        "fills": len(unified.fills),
        "ledger_equity_consistent": unified.equity_consistent,
        "ledger_consistency_msg": unified.equity_consistency_msg,
        "ledger_final_equity": round(final_equity, 6),
        "ledger_total_fees": round(float(unified.ledger_curve.total_fees), 6),
        "ledger_curve_points": len(ledger_rows["equity"]),
        "run_id": unified.run_id,
        "execution_config": execution_settings,
        "event_counts": unified.evidence.get("events", {}),
        "risk": unified.evidence.get("risk", {}),
        "reconciliation": unified.evidence.get("reconciliation", {}).get("summary", {}),
    }

    return CryptoEventBacktestArtifacts(
        mode="crypto_event",
        summary=summary,
        chart=chart,
        strategy_details=[
            {
                "strategy_id": strategy_id,
                "version": effective_strategy_version,
                "params": requested_params,
                "signal_points": int(len(signal)),
            }
        ],
        latest_weights=[
            {
                "strategy_id": strategy_id,
                "display_name": strategy_id,
                "weight": round(float(latest_weight), 6),
            }
        ],
        diagnostics=diagnostics,
        unified=unified,
    )


def _with_crypto_execution_config(
    config: UnifiedBacktestConfig,
    *,
    execution_settings: dict[str, float | bool],
) -> UnifiedBacktestConfig:
    target_weight = float(execution_settings["target_weight"])
    risk_limit = float(execution_settings["risk_limit"])
    cash_reserve = float(execution_settings["cash_reserve_weight"])
    min_trade_notional = float(execution_settings["min_trade_notional"])
    long_only = bool(execution_settings["long_only"])
    config.sizing = PositionSizerConfig(
        default_strategy_weight=target_weight,
        max_symbol_weight=risk_limit,
        long_only=long_only,
    )
    config.allocation = AllocationConfig(
        max_symbol_weight=risk_limit,
        cash_reserve_weight=cash_reserve,
        max_gross_exposure=risk_limit,
    )
    config.rebalance = RebalanceConfig(min_trade_notional=min_trade_notional, min_weight_change=0.01)
    config.risk = PreTradeRiskConfig(
        max_symbol_weight=risk_limit,
        max_gross_exposure=risk_limit,
        max_order_notional_pct=min(1.0, risk_limit + 0.10),
        min_cash_buffer_pct=cash_reserve,
        long_only=long_only,
        skip_session_check=True,
    )
    return config


def _crypto_execution_settings(
    *,
    target_weight: float,
    min_cash_buffer_pct: float | None,
    min_trade_notional: float,
    long_only: bool,
) -> dict[str, float | bool]:
    effective_target_weight = max(0.0, min(float(target_weight), 0.98))
    implied_cash_buffer = max(0.02, 1.0 - effective_target_weight)
    requested_cash_buffer = 0.0 if min_cash_buffer_pct is None else float(min_cash_buffer_pct)
    cash_reserve = max(implied_cash_buffer, requested_cash_buffer)
    return {
        "target_weight": effective_target_weight,
        "risk_limit": max(effective_target_weight, 0.10),
        "cash_reserve_weight": cash_reserve,
        "min_cash_buffer_pct": cash_reserve,
        "min_trade_notional": max(0.0, float(min_trade_notional)),
        "long_only": bool(long_only),
    }


def _default_market_loader(**kwargs: Any) -> pd.DataFrame:
    from backend.app.services.market_data import load_market_frame

    return load_market_frame(**kwargs)


def _default_registry_signal_provider(
    frame: pd.DataFrame,
    strategy_id: str,
    params: dict[str, Any],
) -> pd.Series:
    from backend.app.domain.strategy_registry import strategy_registry

    pack = strategy_registry.get(strategy_id).generate(frame, params=params)
    return pack.signal


def _normalize_market_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    data = frame.copy()
    if not isinstance(data.index, pd.DatetimeIndex):
        ts_col = "timestamp_utc" if "timestamp_utc" in data.columns else "timestamp"
        data[ts_col] = pd.to_datetime(data[ts_col], utc=True)
        data = data.set_index(ts_col)
    data.index = pd.to_datetime(data.index, utc=True)
    data = data.sort_index()
    if "symbol" not in data.columns:
        data["symbol"] = symbol.upper()
    else:
        data["symbol"] = data["symbol"].fillna(symbol).astype(str).str.upper()
    return data


def _frame_from_market_events(events: list[MarketEvent]) -> pd.DataFrame:
    rows = []
    for event in events:
        if event.bar is None:
            raise ValueError("MarketEvent.bar is required")
        bar = event.bar
        rows.append(
            {
                "timestamp": bar.timestamp_utc,
                "symbol": bar.symbol,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "vwap": bar.vwap,
                "trade_count": bar.trade_count,
            }
        )
    return pd.DataFrame(rows)


def _ledger_timeline(
    unified: UnifiedBacktestResult,
    *,
    frame: pd.DataFrame,
    initial_cash: float,
) -> dict[str, pd.Series]:
    equity: dict[pd.Timestamp, float] = {}
    exposure: dict[pd.Timestamp, float] = {}
    net_units: dict[pd.Timestamp, float] = {}

    for timestamp, row in frame.iterrows():
        ts = pd.Timestamp(timestamp).tz_convert("UTC").to_pydatetime()
        symbol = str(row.get("symbol", "")).upper()
        close = float(row["close"])
        positions, _cash, position_value, ledger_equity = ledger_state_at_time(
            fills=unified.fills,
            at_time=ts,
            initial_cash=initial_cash,
            market_prices={symbol: close},
        )
        idx = pd.Timestamp(ts)
        equity[idx] = float(ledger_equity)
        exposure[idx] = abs(float(position_value))
        net_units[idx] = float(positions.get(symbol, 0.0))

    return {
        "equity": pd.Series(equity).sort_index(),
        "exposure": pd.Series(exposure).sort_index(),
        "net_units": pd.Series(net_units).sort_index(),
    }


def _ledger_summary(
    equity: pd.Series,
    *,
    periods_per_year: float,
    trade_count: int,
) -> dict[str, float | int]:
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

    returns = equity.pct_change().fillna(0.0)
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if equity.iloc[0] else 0.0
    annual_return = (
        float(equity.iloc[-1] / equity.iloc[0]) ** (periods_per_year / max(1, len(equity))) - 1.0
        if equity.iloc[0] > 0
        else 0.0
    )
    std = float(returns.std(ddof=0))
    annual_volatility = std * sqrt(periods_per_year)
    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=0))
    sharpe = float(returns.mean() / std * sqrt(periods_per_year)) if std > 0 else 0.0
    sortino = float(returns.mean() / downside_std * sqrt(periods_per_year)) if downside_std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
    calmar = float(annual_return / abs(max_drawdown)) if max_drawdown < 0 else 0.0
    active = returns[returns != 0.0]
    win_rate = float((active > 0).mean()) if not active.empty else 0.0
    gains = float(returns[returns > 0].sum())
    losses = abs(float(returns[returns < 0].sum()))
    profit_factor = gains / losses if losses > 0 else (999.0 if gains > 0 else 0.0)
    return {
        "total_return_pct": round(total_return * 100.0, 4),
        "annual_return_pct": round(annual_return * 100.0, 4),
        "annual_volatility_pct": round(annual_volatility * 100.0, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "calmar_ratio": round(calmar, 4),
        "win_rate_pct": round(win_rate * 100.0, 4),
        "profit_factor": round(profit_factor, 4) if np.isfinite(profit_factor) else 0.0,
        "trade_count": trade_count,
    }


def _chart_payload(
    *,
    frame: pd.DataFrame,
    unified: UnifiedBacktestResult,
    ledger_rows: dict[str, pd.Series],
) -> dict[str, list[dict[str, float | int | str]]]:
    equity = ledger_rows["equity"]
    drawdown = (equity / equity.cummax() - 1.0).fillna(0.0) * 100.0 if not equity.empty else equity
    return {
        "candles": [
            {
                "time": _to_epoch(timestamp),
                "open": round(float(row["open"]), 6),
                "high": round(float(row["high"]), 6),
                "low": round(float(row["low"]), 6),
                "close": round(float(row["close"]), 6),
            }
            for timestamp, row in frame.iterrows()
        ],
        "markers": [
            {
                "time": _to_epoch(fill.filled_at),
                "position": "belowBar" if fill.side.value == "buy" else "aboveBar",
                "color": "#00C853" if fill.side.value == "buy" else "#D50000",
                "shape": "arrowUp" if fill.side.value == "buy" else "arrowDown",
                "text": f"{fill.side.value.upper()} {fill.quantity:.8f} @ {fill.price:.2f}",
            }
            for fill in unified.fills
        ],
        "equity": _series_payload(equity),
        "drawdown": _series_payload(drawdown),
        "exposure": _series_payload(ledger_rows["exposure"]),
        "net_units": _series_payload(ledger_rows["net_units"]),
    }


def _series_payload(series: pd.Series) -> list[dict[str, float | int]]:
    return [
        {"time": _to_epoch(timestamp), "value": round(float(value), 6)}
        for timestamp, value in series.items()
    ]


def _to_epoch(timestamp: datetime | pd.Timestamp) -> int:
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.timestamp())


def _data_version(source: str, symbol: str, interval: str, start: datetime, end: datetime) -> str:
    start_s = pd.Timestamp(start).tz_convert("UTC").isoformat() if pd.Timestamp(start).tzinfo else pd.Timestamp(start).tz_localize("UTC").isoformat()
    end_s = pd.Timestamp(end).tz_convert("UTC").isoformat() if pd.Timestamp(end).tzinfo else pd.Timestamp(end).tz_localize("UTC").isoformat()
    return f"crypto:{source}:{symbol.upper()}:{interval}:{start_s}:{end_s}"


def _crypto_periods_per_year(interval: str) -> float:
    normalized = interval.strip().lower()
    if normalized.endswith("min"):
        minutes = float(normalized[:-3] or 1)
        return 365.0 * 24.0 * 60.0 / minutes
    unit = normalized[-1:]
    amount_text = normalized[:-1] or "1"
    try:
        amount = float(amount_text)
    except ValueError:
        amount = 1.0
    if unit == "m":
        return 365.0 * 24.0 * 60.0 / amount
    if unit == "h":
        return 365.0 * 24.0 / amount
    if unit == "d":
        return 365.0 / amount
    return 365.0
