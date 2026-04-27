from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime

import numpy as np
import pandas as pd

from backend.app.core.config import logger, settings
from backend.app.core.exceptions import DataNotAvailableError
from backend.app.services.data_management import DEFAULT_EXCHANGE, resolve_data_db_path, to_milliseconds


def interval_to_frequency(interval: str) -> str:
    mapping = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1D",
    }
    if interval not in mapping:
        raise DataNotAvailableError(f"Unsupported interval: {interval}")
    return mapping[interval]


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DataNotAvailableError(f"Missing required market columns: {missing}")

    data = frame.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    data = data[(data["open"] > 0) & (data["high"] > 0) & (data["low"] > 0) & (data["close"] > 0)]
    data = data[data["high"] >= data["low"]]
    data = data.set_index("timestamp")
    return data


def load_from_sqlite(
    db_path: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    target = pd.Timestamp(start)
    cutoff = pd.Timestamp(end)
    target = target.tz_localize("UTC") if target.tzinfo is None else target.tz_convert("UTC")
    cutoff = cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")

    db_file = resolve_data_db_path(db_path)
    if not db_file.exists():
        raise DataNotAvailableError(f"SQLite database does not exist: {db_file}")

    logger.info("Loading market data from SQLite: %s", db_file)

    with sqlite3.connect(str(db_file)) as connection:
        table_row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'market_klines'"
        ).fetchone()
        if table_row:
            query = (
                "SELECT open_time AS timestamp, open, high, low, close, volume "
                "FROM market_klines "
                "WHERE exchange = ? AND symbol = ? AND interval = ? "
                "AND open_time_ms >= ? AND open_time_ms <= ? "
                "ORDER BY open_time_ms ASC"
            )
            frame = pd.read_sql_query(
                query,
                connection,
                params=(
                    DEFAULT_EXCHANGE,
                    symbol.upper(),
                    interval,
                    to_milliseconds(target.to_pydatetime()),
                    to_milliseconds(cutoff.to_pydatetime()),
                ),
            )
        else:
            query = (
                "SELECT time AS timestamp, open, high, low, close, volume "
                "FROM btc_kline WHERE time >= ? AND time <= ? ORDER BY time ASC"
            )
            frame = pd.read_sql_query(
                query,
                connection,
                params=(target.strftime("%Y-%m-%d %H:%M:%S"), cutoff.strftime("%Y-%m-%d %H:%M:%S")),
            )

    data = _normalize_frame(frame)
    if data.empty:
        raise DataNotAvailableError("No market data found in the requested SQLite range.")
    return data


def load_fixture_frame(symbol: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    else:
        start_ts = start_ts.tz_convert("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    else:
        end_ts = end_ts.tz_convert("UTC")

    index = pd.date_range(start=start_ts, end=end_ts, freq=interval_to_frequency(interval), inclusive="both")
    if len(index) < 180:
        index = pd.date_range(end=end_ts, periods=240, freq=interval_to_frequency(interval))

    seed_material = f"{symbol}:{interval}:{index[0].isoformat()}:{index[-1].isoformat()}".encode("utf-8")
    seed = int(hashlib.sha256(seed_material).hexdigest()[:16], 16)
    rng = np.random.default_rng(seed)

    base_price = 25000.0
    trend = np.linspace(0, 1800, len(index))
    seasonal = np.sin(np.linspace(0, 24, len(index))) * 700
    noise = rng.normal(0, 65, len(index)).cumsum()
    close = base_price + trend + seasonal + noise
    open_price = np.concatenate(([close[0]], close[:-1]))
    spread = np.abs(rng.normal(35, 12, len(index))) + 10
    high = np.maximum(open_price, close) + spread
    low = np.minimum(open_price, close) - spread
    volume = np.abs(rng.normal(550, 120, len(index))) + 100

    frame = pd.DataFrame(
        {
            "timestamp": index,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    return _normalize_frame(frame)


def load_market_frame(
    source: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    db_path: str = "",
) -> pd.DataFrame:
    if source == "fixture":
        return load_fixture_frame(symbol=symbol, interval=interval, start=start, end=end)

    if source == "sqlite":
        return load_from_sqlite(db_path=db_path, symbol=symbol, interval=interval, start=start, end=end)

    if source == "auto":
        try:
            if settings.resolved_data_db_path is not None and settings.resolved_data_db_path.exists():
                return load_from_sqlite(db_path=db_path, symbol=symbol, interval=interval, start=start, end=end)
        except DataNotAvailableError:
            if not settings.allow_fixture_fallback:
                raise
        return load_fixture_frame(symbol=symbol, interval=interval, start=start, end=end)

    raise DataNotAvailableError(f"Unsupported market data source: {source}")
