from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.app.core.config import logger, settings
from backend.app.core.exceptions import DataNotAvailableError
from backend.app.services.data_management import DEFAULT_EXCHANGE, interval_to_milliseconds, resolve_data_db_path, to_milliseconds
from quant_us.data.connectors.alpaca_data import AlpacaDataConnector
from quant_us.data.connectors.base import infer_single_symbol_lineage
from quant_us.data.connectors.yfinance_data import YFinanceDataConnector


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
    return data[["open", "high", "low", "close", "volume"]]


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
    # Try data lake (parquet store) for known vendors
    if source in ("yfinance", "alpaca"):
        try:
            from quant_us.data.storage.parquet_store import ParquetBarStore

            store = ParquetBarStore(root=Path("data") / "cleaned")
            frame = store.read_bars(
                vendor=source,
                asset_class="equity",
                bar_size=interval,
                symbol=symbol,
                start=start,
                end=end,
            )
            if not frame.empty:
                frame = frame.rename(columns={"timestamp_utc": "timestamp"})
                return _normalize_frame(frame)
        except DataNotAvailableError:
            raise
        except Exception as exc:
            raise DataNotAvailableError(f"Failed to load {source} data from parquet store: {exc}") from exc
        raise DataNotAvailableError(
            f"No {source} market data found for {symbol.upper()} {interval} in the requested range."
        )

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
        if not settings.allow_fixture_fallback:
            raise DataNotAvailableError(
                "No local market data found and fixture fallback is disabled. "
                "Use source='fixture' explicitly for tests, or set QS_ALLOW_FIXTURE_FALLBACK=true for local demos."
            )
        return load_fixture_frame(symbol=symbol, interval=interval, start=start, end=end)

    raise DataNotAvailableError(f"Unsupported market data source: {source}")


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _load_raw_sqlite_frame(
    db_path: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    target = _utc_timestamp(start)
    cutoff = _utc_timestamp(end)
    db_file = resolve_data_db_path(db_path)
    if not db_file.exists():
        raise DataNotAvailableError(f"SQLite database does not exist: {db_file}")

    with sqlite3.connect(str(db_file)) as connection:
        table_row = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'market_klines'"
        ).fetchone()
        if table_row:
            query = (
                "SELECT open_time AS timestamp, open_time_ms, open, high, low, close, volume "
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
    return frame


def _dataset_fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    data = frame.reset_index()[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True).astype("int64")
    hashed = pd.util.hash_pandas_object(data, index=False).values.tobytes()
    return hashlib.sha256(hashed).hexdigest()


def _quality_framework() -> list[dict[str, Any]]:
    titles = [
        ("参数稳健性 + 样本外验证", "completed"),
        ("交易成本压力测试", "completed"),
        ("Walk-forward 与市场状态切片", "completed"),
        ("组合层相关性与资金分配", "completed"),
        ("数据质量与特征版本治理", "selected"),
    ]
    reasons = [
        "已经具备基础样本外参数检验。",
        "已经具备手续费和滑点压力测试。",
        "已经具备时间窗口和市场状态切片验证。",
        "已经具备组合相关性和风险预算分析。",
        "当前阶段把数据质量、数据指纹和版本治理接入研究闭环，为后续 ML 特征库打基础。",
    ]
    return [
        {
            "priority": index + 1,
            "title": title,
            "status": status,
            "reason": reasons[index],
        }
        for index, (title, status) in enumerate(titles)
    ]


def _quality_issue(severity: str, code: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _quality_source_metadata(
    *,
    actual_source: str,
    symbol: str,
    interval: str,
    start: Any,
    end: Any,
    raw: pd.DataFrame | None = None,
    db_path: str = "",
) -> dict[str, Any]:
    metadata = {
        "timezone": "UTC",
        "adjustment_policy": "",
        "corporate_action_adjustment": "",
        "universe_id": "",
        "universe_source": "",
        "survivorship_bias_risk": "unknown",
        "raw_path": "",
        "cleaned_path": "",
        "source_lineage": "",
    }
    if actual_source == "yfinance":
        metadata.update(
            YFinanceDataConnector.quality_metadata(
                symbol=symbol,
                start=start,
                end=end,
                bar_size=interval,
                frame=raw,
            )
        )
        return metadata
    if actual_source == "alpaca":
        metadata.update(
            AlpacaDataConnector.quality_metadata(
                symbol=symbol,
                start=start,
                end=end,
                bar_size=interval,
                frame=raw,
            )
        )
        return metadata

    metadata.update(
        infer_single_symbol_lineage(
            source=actual_source,
            symbol=symbol,
            bar_size=interval,
            start=start,
            end=end,
        )
    )
    if actual_source == "sqlite":
        metadata["adjustment_policy"] = "raw"
        metadata["corporate_action_adjustment"] = "raw"
        metadata["raw_path"] = str(resolve_data_db_path(db_path))
        metadata["source_lineage"] = "sqlite:market_klines"
    elif actual_source == "fixture":
        metadata["adjustment_policy"] = "raw"
        metadata["corporate_action_adjustment"] = "raw"
        metadata["source_lineage"] = "fixture:synthetic"
    return metadata


def inspect_market_data_quality(
    *,
    source: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    db_path: str = "",
) -> dict[str, Any]:
    actual_source = source
    raw = pd.DataFrame()

    # Try data lake (parquet) for known vendors first
    if source in ("yfinance", "alpaca"):
        try:
            from quant_us.data.storage.parquet_store import ParquetBarStore

            store = ParquetBarStore(root=Path("data") / "cleaned")
            frame = store.read_bars(
                vendor=source,
                asset_class="equity",
                bar_size=interval,
                symbol=symbol,
                start=start,
                end=end,
            )
            if not frame.empty:
                raw = frame.rename(columns={"timestamp_utc": "timestamp"})
                raw["open_time_ms"] = pd.to_datetime(raw["timestamp"], utc=True).astype("int64") // 1_000_000
        except Exception:
            pass

    if raw.empty and source not in ("yfinance", "alpaca"):
        try:
            if source == "fixture":
                raw = load_fixture_frame(symbol=symbol, interval=interval, start=start, end=end).reset_index()
            elif source == "sqlite":
                raw = _load_raw_sqlite_frame(db_path=db_path, symbol=symbol, interval=interval, start=start, end=end)
                actual_source = "sqlite"
            elif source == "auto":
                try:
                    raw = _load_raw_sqlite_frame(db_path=db_path, symbol=symbol, interval=interval, start=start, end=end)
                    actual_source = "sqlite"
                except DataNotAvailableError:
                    if not settings.allow_fixture_fallback:
                        raise
                    raw = load_fixture_frame(symbol=symbol, interval=interval, start=start, end=end).reset_index()
                    actual_source = "fixture"
            else:
                raise DataNotAvailableError(f"Unsupported market data source: {source}")
        except DataNotAvailableError:
            raise

    raw_metadata = _quality_source_metadata(
        actual_source=actual_source,
        symbol=symbol.upper(),
        interval=interval,
        start=start,
        end=end,
        raw=raw if not raw.empty else None,
        db_path=db_path,
    )
    raw_rows = int(len(raw))
    issues: list[dict[str, str]] = []
    if raw.empty:
        result = {
            "status": "failed",
            "selected_priority": "数据质量与特征版本治理",
            "framework": _quality_framework(),
            "source": source,
            "actual_source": actual_source,
            "symbol": symbol.upper(),
            "interval": interval,
            "row_count": 0,
            "expected_rows": 0,
            "coverage_pct": 0.0,
            "missing_bars": 0,
            "duplicate_timestamps": 0,
            "cleaning_loss_rows": 0,
            "invalid_ohlc": 0,
            "non_positive_prices": 0,
            "non_positive_volume": 0,
            "large_price_jumps": 0,
            "volume_anomalies": 0,
            "max_gap_bars": 0,
            "max_price_jump_pct": 0.0,
            "quality_score": 0.0,
            "is_usable": False,
            "fingerprint": _dataset_fingerprint(pd.DataFrame()),
            "data_version": "qs-empty",
            "issues": [_quality_issue("high", "empty_dataset", "请求区间没有可用行情数据。")],
        }
        result.update(raw_metadata)
        return result

    raw = raw.copy()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        raw[column] = pd.to_numeric(raw[column], errors="coerce")

    duplicate_timestamps = int(raw.duplicated(subset=["timestamp"]).sum())
    non_positive_prices = int(((raw[["open", "high", "low", "close"]] <= 0) | raw[["open", "high", "low", "close"]].isna()).any(axis=1).sum())
    invalid_ohlc = int(
        (
            (raw["high"] < raw["low"])
            | (raw["high"] < raw[["open", "close"]].max(axis=1))
            | (raw["low"] > raw[["open", "close"]].min(axis=1))
        ).sum()
    )
    non_positive_volume = int(((raw["volume"] <= 0) | raw["volume"].isna()).sum())

    cleaned = _normalize_frame(raw[["timestamp", "open", "high", "low", "close", "volume"]])
    cleaning_loss_rows = raw_rows - int(len(cleaned))
    start_ts = _utc_timestamp(start)
    end_ts = _utc_timestamp(end)
    # Use business days for equity sources (skip weekends/holidays)
    freq = "1B" if actual_source in ("yfinance", "alpaca") and interval == "1d" else interval_to_frequency(interval)
    expected_index = pd.date_range(start=start_ts, end=end_ts, freq=freq, inclusive="both")
    expected_rows = int(len(expected_index))
    # For daily bars, compare date-only to ignore intraday timestamp differences
    if interval == "1d":
        cleaned_dates = cleaned.index.normalize() if not cleaned.empty else pd.DatetimeIndex([])
        missing_bars = int(expected_index.difference(cleaned_dates).size) if not cleaned.empty else expected_rows
    else:
        missing_bars = int(expected_index.difference(cleaned.index).size) if not cleaned.empty else expected_rows
    coverage_pct = round((1.0 - missing_bars / max(1, expected_rows)) * 100.0, 4)

    if len(cleaned) > 1:
        interval_ms = interval_to_milliseconds(interval)
        gaps = cleaned.index.to_series().diff().dropna().dt.total_seconds() * 1000
        max_gap_bars = int(max(0.0, float((gaps / interval_ms - 1).max())))
        abs_returns = cleaned["close"].pct_change().abs().replace([np.inf, -np.inf], np.nan).fillna(0.0)
        large_price_jumps = int((abs_returns > 0.20).sum())
        max_price_jump_pct = round(float(abs_returns.max()) * 100.0, 4)
        positive_volume = cleaned["volume"][cleaned["volume"] > 0]
        median_volume = float(positive_volume.median()) if not positive_volume.empty else 0.0
        volume_anomalies = int((cleaned["volume"] > median_volume * 20).sum()) if median_volume > 0 else 0
    else:
        max_gap_bars = 0
        large_price_jumps = 0
        max_price_jump_pct = 0.0
        volume_anomalies = 0

    if duplicate_timestamps:
        issues.append(_quality_issue("medium", "duplicate_timestamps", f"发现 {duplicate_timestamps} 条重复时间戳，清洗层会保留最后一条。"))
    if missing_bars:
        severity = "high" if coverage_pct < 95 else "medium"
        issues.append(_quality_issue(severity, "missing_bars", f"请求区间缺失 {missing_bars} 根 K 线，覆盖率 {coverage_pct:.2f}%。"))
    if invalid_ohlc:
        issues.append(_quality_issue("high", "invalid_ohlc", f"发现 {invalid_ohlc} 条 OHLC 结构异常。"))
    if non_positive_prices:
        issues.append(_quality_issue("high", "non_positive_prices", f"发现 {non_positive_prices} 条非正价格。"))
    if non_positive_volume:
        issues.append(_quality_issue("low", "non_positive_volume", f"发现 {non_positive_volume} 条非正成交量。"))
    if large_price_jumps:
        issues.append(_quality_issue("medium", "large_price_jumps", f"发现 {large_price_jumps} 次超过 20% 的单根收盘跳变。"))
    if volume_anomalies:
        issues.append(_quality_issue("low", "volume_anomalies", f"发现 {volume_anomalies} 条成交量超过中位数 20 倍。"))
    if cleaning_loss_rows:
        issues.append(_quality_issue("medium", "cleaning_loss", f"清洗后剔除 {cleaning_loss_rows} 行原始数据。"))
    if not issues:
        issues.append(_quality_issue("low", "clean", "未发现阻断级数据质量问题。"))

    missing_penalty = min(45.0, missing_bars / max(1, expected_rows) * 100.0)
    quality_score = 100.0
    quality_score -= missing_penalty
    quality_score -= min(20.0, invalid_ohlc * 5.0)
    quality_score -= min(20.0, non_positive_prices * 5.0)
    quality_score -= min(12.0, duplicate_timestamps * 2.0)
    quality_score -= min(10.0, large_price_jumps * 1.5)
    quality_score -= min(8.0, cleaning_loss_rows * 1.0)
    quality_score = round(max(0.0, quality_score), 4)
    fingerprint = _dataset_fingerprint(cleaned)
    blocking = invalid_ohlc > 0 or non_positive_prices > 0 or coverage_pct < 90 or cleaned.empty
    quality_metadata = _quality_source_metadata(
        actual_source=actual_source,
        symbol=symbol.upper(),
        interval=interval,
        start=cleaned.index[0] if not cleaned.empty else start,
        end=cleaned.index[-1] if not cleaned.empty else end,
        raw=raw,
        db_path=db_path,
    )

    result = {
        "status": "completed",
        "selected_priority": "数据质量与特征版本治理",
        "framework": _quality_framework(),
        "source": source,
        "actual_source": actual_source,
        "symbol": symbol.upper(),
        "interval": interval,
        "row_count": int(len(cleaned)),
        "raw_row_count": raw_rows,
        "expected_rows": expected_rows,
        "coverage_pct": coverage_pct,
        "missing_bars": missing_bars,
        "duplicate_timestamps": duplicate_timestamps,
        "cleaning_loss_rows": cleaning_loss_rows,
        "invalid_ohlc": invalid_ohlc,
        "non_positive_prices": non_positive_prices,
        "non_positive_volume": non_positive_volume,
        "large_price_jumps": large_price_jumps,
        "volume_anomalies": volume_anomalies,
        "max_gap_bars": max_gap_bars,
        "max_price_jump_pct": max_price_jump_pct,
        "first_timestamp": cleaned.index[0].isoformat() if not cleaned.empty else None,
        "last_timestamp": cleaned.index[-1].isoformat() if not cleaned.empty else None,
        "quality_score": quality_score,
        "is_usable": not blocking,
        "fingerprint": fingerprint,
        "data_version": f"qs-{actual_source}-{symbol.upper()}-{interval}-{fingerprint[:12]}",
        "issues": issues,
    }
    result.update(quality_metadata)
    return result
