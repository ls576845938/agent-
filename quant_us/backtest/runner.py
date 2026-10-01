from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_us.backtest.configuration import config_to_metadata
from quant_us.backtest.engine import BacktestConfig, BacktestResult, EventDrivenBacktestEngine
from quant_us.backtest.features import feature_map_from_frame
from quant_us.core.types import Bar
from quant_us.data.cleaners.corporate_action_adjuster import CorporateAction, CorporateActionAdjuster
from quant_us.data.events import EarningsBlackoutFilter, EarningsEvent
from quant_us.data.pipeline import DataLakeConfig, DataLakeService
from quant_us.data.storage.feature_store import ParquetFeatureStore
from quant_us.strategies.base import Strategy
from quant_us.strategies.factory import build_strategy


def normalize_symbols(symbol: str | None = None, symbols: list[str] | None = None) -> list[str]:
    requested = symbols or ([symbol] if symbol else [])
    normalized: list[str] = []
    seen: set[str] = set()
    for item in requested:
        value = str(item).strip().upper()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    if not normalized:
        raise ValueError("At least one symbol is required")
    return normalized


def bars_from_frame(frame: pd.DataFrame) -> list[Bar]:
    if frame.empty:
        return []
    working = frame.copy()
    working["timestamp_utc"] = pd.to_datetime(working["timestamp_utc"], utc=True)
    bars: list[Bar] = []
    for row in working.sort_values("timestamp_utc").to_dict("records"):
        bars.append(
            Bar(
                timestamp_utc=row["timestamp_utc"].to_pydatetime() if hasattr(row["timestamp_utc"], "to_pydatetime") else row["timestamp_utc"],
                symbol=str(row["symbol"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                vwap=None if pd.isna(row.get("vwap")) else float(row.get("vwap")),
                trade_count=None if pd.isna(row.get("trade_count")) else int(row.get("trade_count")),
                source=str(row.get("source", "")),
                session=str(row.get("session", "")),
                adjusted=bool(row.get("adjusted_flag", False)),
            )
        )
    return bars


def strategy_from_id(strategy_id: str, parameters: dict[str, object] | None = None) -> Strategy:
    return build_strategy(strategy_id, parameters)


def feature_names_for_strategy(strategy_id: str, strategy_params: dict[str, object] | None, feature_names: list[str] | None) -> list[str]:
    if feature_names:
        return [str(item) for item in feature_names]
    params = strategy_params or {}
    if strategy_id == "factor_rank" and params.get("factor_name"):
        return [str(params["factor_name"])]
    return []


def run_event_backtest_from_lake(
    data_root: str,
    symbol: str | None,
    start: datetime,
    end: datetime,
    bar_size: str = "1d",
    vendor: str = "yfinance",
    asset_class: str = "equity",
    strategy_id: str = "trend_momentum",
    config: BacktestConfig | None = None,
    corporate_actions: list[CorporateAction] | None = None,
    earnings_events: list[EarningsEvent] | None = None,
    symbols: list[str] | None = None,
    strategy_params: dict[str, object] | None = None,
    feature_names: list[str] | None = None,
    feature_version: str = "v1",
    feature_universe: str = "default",
) -> BacktestResult:
    selected_symbols = normalize_symbols(symbol, symbols)
    data = DataLakeService(DataLakeConfig(data_root=Path(data_root)))
    frames: list[pd.DataFrame] = []
    loaded_symbols: list[str] = []
    missing_symbols: list[str] = []
    for item in selected_symbols:
        symbol_frame = data.read_cleaned_bars(symbol=item, start=start, end=end, bar_size=bar_size, vendor=vendor, asset_class=asset_class)
        if symbol_frame.empty:
            missing_symbols.append(item)
            continue
        frames.append(symbol_frame)
        loaded_symbols.append(item)
    frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    metadata: dict[str, object] = {
        "symbols": selected_symbols,
        "loaded_symbols": loaded_symbols,
        "missing_symbols": missing_symbols,
        "input_rows": int(len(frame)),
        "corporate_action_count": int(len(corporate_actions or [])),
        "earnings_event_count": int(len(earnings_events or [])),
        "earnings_blackout_removed_rows": 0,
        "strategy_params": strategy_params or {},
        "feature_names": feature_names_for_strategy(strategy_id, strategy_params, feature_names),
        "feature_version": feature_version,
        "feature_universe": feature_universe,
    }
    if config is not None:
        metadata["backtest_config"] = config_to_metadata(config)
    if corporate_actions:
        frame = CorporateActionAdjuster().adjust_bars(frame, corporate_actions)
    if earnings_events:
        filter_result = EarningsBlackoutFilter().filter_bars(frame, earnings_events)
        frame = filter_result.frame
        metadata["earnings_blackout_removed_rows"] = int(filter_result.removed_rows)
        metadata["earnings_blackout_symbols"] = filter_result.blocked_symbols
    metadata["processed_rows"] = int(len(frame))
    bars = bars_from_frame(frame)
    if not bars:
        raise ValueError(f"No cleaned bars found for {','.join(selected_symbols)} {bar_size} in {data_root}")
    selected_feature_names = feature_names_for_strategy(strategy_id, strategy_params, feature_names)
    feature_frame = load_feature_values(
        data_root=Path(data_root),
        feature_names=selected_feature_names,
        feature_version=feature_version,
        feature_universe=feature_universe,
        symbols=loaded_symbols,
        start=start,
        end=end,
    )
    metadata["feature_rows"] = int(len(feature_frame))
    engine = EventDrivenBacktestEngine(
        strategies=[strategy_from_id(strategy_id, strategy_params)],
        config=config,
        features_by_date=feature_map_from_frame(feature_frame),
    )
    return replace(engine.run(bars), metadata=metadata)


def load_feature_values(
    data_root: Path,
    feature_names: list[str],
    feature_version: str,
    feature_universe: str,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    if not feature_names:
        return pd.DataFrame()
    store = ParquetFeatureStore(data_root / "features")
    frames = []
    selected_symbols = {symbol.upper() for symbol in symbols}
    start_date = start.date()
    end_date = end.date()
    for factor_name in feature_names:
        frame = store.read_factor_values(factor_name=factor_name, version=feature_version)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        if "universe" in frame.columns:
            frame = frame[frame["universe"] == feature_universe]
        frame = frame[(frame["symbol"].isin(selected_symbols)) & (frame["date"] >= start_date) & (frame["date"] <= end_date)]
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
