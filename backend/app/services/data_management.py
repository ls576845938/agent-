from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import logger, settings
from backend.app.core.exceptions import DataNotAvailableError, DataSyncError
from quant_us.data.storage.data_manifest import DataManifest, DataManifestStore


SUPPORTED_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}
INTERVAL_MILLISECONDS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}
DEFAULT_EXCHANGE = "binance_spot"
EXCHANGE_ALIASES = {"binance": DEFAULT_EXCHANGE}
SUPPORTED_SYNC_EXCHANGES = {DEFAULT_EXCHANGE, "coinbase_spot", "kraken_spot"}
BTC_PERPETUAL_COVERAGE_EXCHANGES = {"", "binance_usdm", "binance_futures", "binance_perpetual"}
BTC_DATA_STATUS_REPORT = Path("artifacts/btc_data_status/latest/btc_data_status_report.json")
COINBASE_GRANULARITY_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 21600,
    "1d": 86400,
}
KRAKEN_INTERVAL_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def to_utc(value: datetime) -> datetime:
    timestamp = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def to_milliseconds(value: datetime) -> int:
    return int(to_utc(value).timestamp() * 1000)


def from_milliseconds(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc)


def normalize_interval(interval: str) -> str:
    if interval not in SUPPORTED_INTERVALS:
        raise DataNotAvailableError(f"Unsupported interval: {interval}")
    return interval


def normalize_exchange(exchange: str) -> str:
    value = exchange.strip().lower() if exchange else ""
    return EXCHANGE_ALIASES.get(value, exchange)


def _coinbase_product_id(symbol: str) -> str:
    value = symbol.upper().replace("_", "-").replace("/", "-")
    if value in {"BTCUSDT", "BTCUSD", "XBTUSD"}:
        return "BTC-USD"
    if "-" not in value and len(value) > 3:
        return f"{value[:-3]}-{value[-3:]}"
    return value


def _kraken_pair_id(symbol: str) -> str:
    value = symbol.upper().replace("_", "").replace("/", "").replace("-", "")
    if value in {"BTCUSD", "XBTUSD"}:
        return "XBTUSD"
    if value in {"BTCUSDT", "XBTUSDT"}:
        return "XBTUSDT"
    return value


def interval_to_milliseconds(interval: str) -> int:
    return INTERVAL_MILLISECONDS[normalize_interval(interval)]


def resolve_data_db_path(db_path: str = "") -> Path:
    target = db_path.strip() if db_path else settings.data_db_path
    if not target:
        target = str(settings.repo_root / "data" / "market_data.sqlite")
    return Path(target).expanduser().resolve()


@dataclass(frozen=True)
class KlineRecord:
    exchange: str
    symbol: str
    interval: str
    open_time_ms: int
    open_time: str
    close_time_ms: int
    close_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    taker_buy_base_volume: float
    taker_buy_quote_volume: float
    source: str = "binance_rest"


@dataclass(frozen=True)
class DataSyncSpec:
    symbol: str
    interval: str
    start: datetime
    end: datetime
    db_path: str = ""
    exchange: str = DEFAULT_EXCHANGE
    limit: int = 1000
    closed_only: bool = True


@dataclass(frozen=True)
class LatestUpdateSpec:
    symbol: str
    interval: str
    db_path: str = ""
    exchange: str = DEFAULT_EXCHANGE
    lookback_days: int = 30
    limit: int = 1000


@dataclass(frozen=True)
class CryptoResampleSpec:
    symbol: str = "BTCUSDT"
    target_interval: str = "1h"
    start: datetime | None = None
    end: datetime | None = None
    db_path: str = ""
    exchange: str = DEFAULT_EXCHANGE
    source_interval: str = "1m"
    persist_manifest: bool = True


@dataclass
class DataSyncResult:
    run_id: str
    status: str
    db_path: str
    exchange: str
    symbol: str
    interval: str
    start: datetime
    end: datetime
    rows_received: int = 0
    rows_written: int = 0
    requests: int = 0
    created_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


@dataclass
class CryptoResampleResult:
    status: str
    db_path: str
    exchange: str
    symbol: str
    source_interval: str
    target_interval: str
    start: datetime
    end: datetime
    source_rows: int
    expected_source_rows: int
    rows_written: int
    coverage_pct: float
    quality_score: float
    manifest_path: str = ""
    data_version: str = ""
    fingerprint: str = ""
    completed_at: datetime | None = None
    quality_summary: dict[str, int] | None = None


class MarketDataRepository:
    def __init__(self, db_path: str = "") -> None:
        self.db_path = resolve_data_db_path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def ensure_schema(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_klines (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    open_time_ms INTEGER NOT NULL,
                    open_time TEXT NOT NULL,
                    close_time_ms INTEGER NOT NULL,
                    close_time TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL NOT NULL DEFAULT 0,
                    trade_count INTEGER NOT NULL DEFAULT 0,
                    taker_buy_base_volume REAL NOT NULL DEFAULT 0,
                    taker_buy_quote_volume REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'binance_rest',
                    ingested_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (exchange, symbol, interval, open_time_ms)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_klines_lookup
                ON market_klines (symbol, interval, open_time_ms)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS data_sync_runs (
                    run_id TEXT PRIMARY KEY,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rows_received INTEGER NOT NULL DEFAULT 0,
                    rows_written INTEGER NOT NULL DEFAULT 0,
                    requests INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.commit()

    def database_status(self) -> dict[str, Any]:
        exists = self.db_path.exists()
        initialized = False
        table_count = 0
        if exists:
            with self.connect() as connection:
                rows = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
                tables = {str(row["name"]) for row in rows}
                initialized = "market_klines" in tables
                table_count = len(tables)
        return {
            "db_path": str(self.db_path),
            "exists": exists,
            "initialized": initialized,
            "table_count": table_count,
        }

    def create_sync_run(self, spec: DataSyncSpec) -> DataSyncResult:
        self.ensure_schema()
        run_id = uuid.uuid4().hex
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO data_sync_runs (
                    run_id, exchange, symbol, interval, start_time, end_time,
                    status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    spec.exchange,
                    spec.symbol,
                    spec.interval,
                    to_utc(spec.start).isoformat(),
                    to_utc(spec.end).isoformat(),
                    "running",
                    now.isoformat(),
                ),
            )
            connection.commit()
        return DataSyncResult(
            run_id=run_id,
            status="running",
            db_path=str(self.db_path),
            exchange=spec.exchange,
            symbol=spec.symbol,
            interval=spec.interval,
            start=to_utc(spec.start),
            end=to_utc(spec.end),
            created_at=now,
        )

    def finish_sync_run(
        self,
        result: DataSyncResult,
        status: str,
        error: str | None = None,
    ) -> DataSyncResult:
        completed_at = utc_now()
        result.status = status
        result.completed_at = completed_at
        result.error = error
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE data_sync_runs
                SET status = ?, rows_received = ?, rows_written = ?,
                    requests = ?, error = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    result.rows_received,
                    result.rows_written,
                    result.requests,
                    error,
                    completed_at.isoformat(),
                    result.run_id,
                ),
            )
            connection.commit()
        return result

    def upsert_klines(self, records: list[KlineRecord]) -> int:
        if not records:
            return 0
        self.ensure_schema()
        now = utc_now().isoformat()
        rows = [
            (
                record.exchange,
                record.symbol,
                record.interval,
                record.open_time_ms,
                record.open_time,
                record.close_time_ms,
                record.close_time,
                record.open,
                record.high,
                record.low,
                record.close,
                record.volume,
                record.quote_volume,
                record.trade_count,
                record.taker_buy_base_volume,
                record.taker_buy_quote_volume,
                record.source,
                now,
                now,
            )
            for record in records
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO market_klines (
                    exchange, symbol, interval, open_time_ms, open_time,
                    close_time_ms, close_time, open, high, low, close,
                    volume, quote_volume, trade_count, taker_buy_base_volume,
                    taker_buy_quote_volume, source, ingested_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, symbol, interval, open_time_ms) DO UPDATE SET
                    close_time_ms = excluded.close_time_ms,
                    close_time = excluded.close_time,
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    quote_volume = excluded.quote_volume,
                    trade_count = excluded.trade_count,
                    taker_buy_base_volume = excluded.taker_buy_base_volume,
                    taker_buy_quote_volume = excluded.taker_buy_quote_volume,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            connection.commit()
        return len(records)

    def latest_open_time_ms(self, exchange: str, symbol: str, interval: str) -> int | None:
        self.ensure_schema()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(open_time_ms) AS latest_open_time_ms
                FROM market_klines
                WHERE exchange = ? AND symbol = ? AND interval = ?
                """,
                (exchange, symbol, interval),
            ).fetchone()
        value = row["latest_open_time_ms"] if row else None
        return int(value) if value is not None else None

    def interval_bounds(self, exchange: str, symbol: str, interval: str) -> dict[str, int] | None:
        self.ensure_schema()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    MIN(open_time_ms) AS start_ms,
                    MAX(open_time_ms) AS end_ms,
                    COUNT(*) AS row_count
                FROM market_klines
                WHERE exchange = ? AND symbol = ? AND interval = ?
                """,
                (exchange, symbol, interval),
            ).fetchone()
        if row is None or row["start_ms"] is None or row["end_ms"] is None:
            return None
        return {
            "start_ms": int(row["start_ms"]),
            "end_ms": int(row["end_ms"]),
            "row_count": int(row["row_count"]),
        }

    def load_klines(
        self,
        *,
        exchange: str,
        symbol: str,
        interval: str,
        start_open_time_ms: int,
        end_open_time_ms: int,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    exchange, symbol, interval, open_time_ms, open_time,
                    close_time_ms, close_time, open, high, low, close,
                    volume, quote_volume, trade_count, taker_buy_base_volume,
                    taker_buy_quote_volume, source
                FROM market_klines
                WHERE exchange = ? AND symbol = ? AND interval = ?
                  AND open_time_ms >= ? AND open_time_ms <= ?
                ORDER BY open_time_ms ASC
                """,
                (exchange, symbol, interval, start_open_time_ms, end_open_time_ms),
            ).fetchall()
        return [dict(row) for row in rows]

    def coverage(self, exchange: str = "", symbol: str = "", interval: str = "") -> list[dict[str, Any]]:
        self.ensure_schema()
        filters: list[str] = []
        params: list[Any] = []
        if exchange:
            filters.append("exchange = ?")
            params.append(exchange)
        if symbol:
            filters.append("symbol = ?")
            params.append(symbol)
        if interval:
            filters.append("interval = ?")
            params.append(interval)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = f"""
            SELECT
                exchange,
                symbol,
                interval,
                COUNT(*) AS rows,
                MIN(open_time_ms) AS start_ms,
                MAX(open_time_ms) AS end_ms,
                MAX(updated_at) AS updated_at
            FROM market_klines
            {where_clause}
            GROUP BY exchange, symbol, interval
            ORDER BY symbol ASC, interval ASC
        """
        with self.connect() as connection:
            result = connection.execute(query, params).fetchall()
        return [
            {
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "interval": row["interval"],
                "rows": int(row["rows"]),
                "start": from_milliseconds(int(row["start_ms"])).isoformat() if row["start_ms"] is not None else None,
                "end": from_milliseconds(int(row["end_ms"])).isoformat() if row["end_ms"] is not None else None,
                "updated_at": row["updated_at"],
            }
            for row in result
        ]

    def preview_klines(
        self,
        exchange: str = DEFAULT_EXCHANGE,
        symbol: str = "",
        interval: str = "",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        filters = ["exchange = ?"]
        params: list[Any] = [exchange]
        if symbol:
            filters.append("symbol = ?")
            params.append(symbol)
        if interval:
            filters.append("interval = ?")
            params.append(interval)
        if start is not None:
            filters.append("open_time_ms >= ?")
            params.append(to_milliseconds(start))
        if end is not None:
            filters.append("open_time_ms <= ?")
            params.append(to_milliseconds(end))
        params.append(max(1, min(int(limit), 1000)))
        query = f"""
            SELECT
                exchange, symbol, interval, open_time_ms, open_time,
                open, high, low, close, volume, quote_volume, trade_count
            FROM market_klines
            WHERE {' AND '.join(filters)}
            ORDER BY open_time_ms DESC
            LIMIT ?
        """
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "interval": row["interval"],
                "time": row["open_time"],
                "open_time_ms": int(row["open_time_ms"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "quote_volume": float(row["quote_volume"]),
                "trade_count": int(row["trade_count"]),
            }
            for row in rows
        ]

    def list_sync_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    run_id, exchange, symbol, interval, start_time, end_time,
                    status, rows_received, rows_written, requests, error,
                    created_at, completed_at
                FROM data_sync_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]


class BinanceKlineClient:
    def __init__(
        self,
        base_url: str | None = None,
        fallback_base_urls: list[str] | tuple[str, ...] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        primary_base_url = (base_url or settings.binance_base_url).rstrip("/")
        configured_fallbacks = settings.binance_fallback_base_urls if fallback_base_urls is None else fallback_base_urls
        base_urls = [primary_base_url]
        for candidate in configured_fallbacks:
            normalized = candidate.strip().rstrip("/")
            if normalized and normalized not in base_urls:
                base_urls.append(normalized)
        self.base_url = primary_base_url
        self.base_urls = tuple(base_urls)
        self.timeout_seconds = float(timeout_seconds or settings.http_timeout_seconds)

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> list[list[Any]]:
        normalize_interval(interval)
        query = urllib.parse.urlencode(
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": int(start_time_ms),
                "endTime": int(end_time_ms),
                "limit": max(1, min(int(limit), 1000)),
            }
        )
        errors: list[str] = []
        last_exception: Exception | None = None

        for index, base_url in enumerate(self.base_urls):
            url = f"{base_url}/api/v3/klines?{query}"
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "QuantStation-vNext/0.1"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = response.read().decode("utf-8")
                    data = json.loads(payload)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                errors.append(f"{base_url} HTTP {exc.code} {detail}")
                last_exception = exc
                if self._should_try_next_endpoint(exc.code, index):
                    logger.warning(
                        "Binance kline endpoint returned HTTP %s; trying fallback endpoint.",
                        exc.code,
                    )
                    continue
                break
            except urllib.error.URLError as exc:
                errors.append(f"{base_url} {exc.reason}")
                last_exception = exc
                if self._has_next_endpoint(index):
                    logger.warning("Binance kline endpoint failed; trying fallback endpoint: %s", exc.reason)
                    continue
                break
            except json.JSONDecodeError as exc:
                errors.append(f"{base_url} invalid JSON")
                last_exception = exc
                if self._has_next_endpoint(index):
                    logger.warning("Binance kline endpoint returned invalid JSON; trying fallback endpoint.")
                    continue
                break

            if isinstance(data, list):
                return data
            errors.append(f"{base_url} unexpected response {data}")
            if self._has_next_endpoint(index):
                logger.warning("Binance kline endpoint returned an unexpected response; trying fallback endpoint.")
                continue
            break

        tried = ", ".join(self.base_urls)
        message = f"Binance kline request failed after trying {tried}: {'; '.join(errors)}"
        if last_exception is not None:
            raise DataSyncError(message) from last_exception
        raise DataSyncError(message)

    def _has_next_endpoint(self, index: int) -> bool:
        return index + 1 < len(self.base_urls)

    def _should_try_next_endpoint(self, status_code: int, index: int) -> bool:
        retriable_statuses = {403, 418, 429, 451, 500, 502, 503, 504}
        return self._has_next_endpoint(index) and status_code in retriable_statuses


class CoinbaseKlineClient:
    def __init__(
        self,
        base_url: str = "https://api.exchange.coinbase.com",
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds or settings.http_timeout_seconds)

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 300,
    ) -> list[list[Any]]:
        granularity = COINBASE_GRANULARITY_SECONDS[normalize_interval(interval)]
        product_id = _coinbase_product_id(symbol)
        start = from_milliseconds(start_time_ms).isoformat().replace("+00:00", "Z")
        end = from_milliseconds(end_time_ms).isoformat().replace("+00:00", "Z")
        query = urllib.parse.urlencode({"granularity": granularity, "start": start, "end": end})
        url = f"{self.base_url}/products/{product_id}/candles?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "QuantStation-vNext/0.1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DataSyncError(f"Coinbase candle request failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DataSyncError(f"Coinbase candle request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise DataSyncError("Coinbase candle request returned invalid JSON") from exc

        if not isinstance(data, list):
            raise DataSyncError(f"Coinbase candle request returned unexpected payload: {data}")
        return sorted(data[: max(1, min(int(limit), 300))], key=lambda row: int(row[0]) if isinstance(row, list) and row else 0)


class KrakenKlineClient:
    def __init__(
        self,
        base_url: str = "https://api.kraken.com",
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds or settings.http_timeout_seconds)

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 720,
    ) -> list[list[Any]]:
        interval_minutes = KRAKEN_INTERVAL_MINUTES[normalize_interval(interval)]
        pair = _kraken_pair_id(symbol)
        query = urllib.parse.urlencode(
            {
                "pair": pair,
                "interval": interval_minutes,
                "since": int(start_time_ms // 1000),
            }
        )
        url = f"{self.base_url}/0/public/OHLC?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "QuantStation-vNext/0.1"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
                data = json.loads(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DataSyncError(f"Kraken OHLC request failed HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DataSyncError(f"Kraken OHLC request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise DataSyncError("Kraken OHLC request returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise DataSyncError(f"Kraken OHLC request returned unexpected payload: {data}")
        errors = data.get("error") or []
        if errors:
            raise DataSyncError(f"Kraken OHLC request returned errors: {errors}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise DataSyncError(f"Kraken OHLC request missing result: {data}")
        rows: list[Any] = []
        for key, value in result.items():
            if key == "last":
                continue
            if isinstance(value, list):
                rows = value
                break
        end_seconds = int(end_time_ms // 1000)
        filtered = [
            row
            for row in rows
            if isinstance(row, list) and row and int(row[0]) <= end_seconds
        ]
        return sorted(filtered[: max(1, min(int(limit), 720))], key=lambda row: int(row[0]))


class MarketDataService:
    def __init__(
        self,
        client: BinanceKlineClient | None = None,
        coinbase_client: CoinbaseKlineClient | None = None,
        kraken_client: KrakenKlineClient | None = None,
        repo_root: Path | str | None = None,
    ) -> None:
        self.client = client or BinanceKlineClient()
        self.coinbase_client = coinbase_client or CoinbaseKlineClient()
        self.kraken_client = kraken_client or KrakenKlineClient()
        self.repo_root = Path(repo_root) if repo_root is not None else settings.repo_root

    def repository(self, db_path: str = "") -> MarketDataRepository:
        return MarketDataRepository(db_path=db_path)

    def database_status(self, db_path: str = "") -> dict[str, Any]:
        repository = self.repository(db_path)
        repository.ensure_schema()
        status = repository.database_status()
        status["coverage"] = self.coverage(db_path=db_path) if status["initialized"] else []
        return status

    def coverage(self, db_path: str = "", exchange: str = "", symbol: str = "", interval: str = "") -> list[dict[str, Any]]:
        normalized_exchange = normalize_exchange(exchange)
        rows = self.repository(db_path).coverage(exchange=normalized_exchange, symbol=symbol, interval=interval)
        if rows:
            return rows
        return self._btc_artifact_coverage(exchange=normalized_exchange, symbol=symbol, interval=interval)

    def _btc_artifact_coverage(self, *, exchange: str = "", symbol: str = "", interval: str = "") -> list[dict[str, Any]]:
        normalized_symbol = symbol.upper().strip() if symbol else ""
        normalized_exchange = exchange.lower().strip() if exchange else ""
        if normalized_symbol and normalized_symbol != "BTCUSDT":
            return []
        if normalized_exchange not in BTC_PERPETUAL_COVERAGE_EXCHANGES:
            return []

        report_path = self.repo_root / BTC_DATA_STATUS_REPORT
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as exc:
            logger.warning("BTC data status report is not valid JSON: %s", exc)
            return []

        if str(payload.get("symbol", "BTCUSDT")).upper() != "BTCUSDT":
            return []
        coverage = payload.get("coverage")
        if not isinstance(coverage, dict):
            return []

        intervals = coverage.get("intervals_available") or []
        bar_counts = coverage.get("bar_count_by_interval") or {}
        if not isinstance(intervals, list) or not isinstance(bar_counts, dict):
            return []

        requested_interval = interval.strip() if interval else ""
        sample_start = coverage.get("sample_start")
        sample_end = coverage.get("sample_end")
        updated_at = payload.get("generated_at")
        rows: list[dict[str, Any]] = []
        for item in intervals:
            item_interval = str(item)
            if requested_interval and item_interval != requested_interval:
                continue
            row_count = bar_counts.get(item_interval)
            if not isinstance(row_count, (int, float)):
                continue
            rows.append(
                {
                    "exchange": "binance_usdm",
                    "symbol": "BTCUSDT",
                    "interval": item_interval,
                    "rows": int(row_count),
                    "start": sample_start,
                    "end": sample_end,
                    "updated_at": updated_at,
                }
            )
        return rows

    def preview_klines(
        self,
        db_path: str = "",
        exchange: str = DEFAULT_EXCHANGE,
        symbol: str = "",
        interval: str = "",
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.repository(db_path).preview_klines(
            exchange=normalize_exchange(exchange),
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            limit=limit,
        )

    def list_sync_runs(self, db_path: str = "", limit: int = 20) -> list[dict[str, Any]]:
        return self.repository(db_path).list_sync_runs(limit=limit)

    def resample_crypto_klines(self, spec: CryptoResampleSpec) -> CryptoResampleResult:
        symbol = spec.symbol.upper()
        exchange = normalize_exchange(spec.exchange or DEFAULT_EXCHANGE)
        if exchange not in SUPPORTED_SYNC_EXCHANGES:
            raise DataSyncError(f"Unsupported crypto data exchange for resampling: {exchange}")
        source_interval = normalize_interval(spec.source_interval)
        target_interval = normalize_interval(spec.target_interval)
        if source_interval != "1m":
            raise DataSyncError(f"Crypto resample only supports source_interval=1m, got {source_interval}.")
        if target_interval == source_interval:
            raise DataSyncError("Crypto resample target_interval must be larger than 1m.")

        repository = self.repository(spec.db_path)
        source_bounds = repository.interval_bounds(exchange=exchange, symbol=symbol, interval=source_interval)
        if source_bounds is None:
            raise DataSyncError(
                f"Source 1m klines not found for {exchange} {symbol}. "
                "Load Binance BTCUSDT 1m data into market_klines before resampling."
            )

        source_interval_ms = interval_to_milliseconds(source_interval)
        target_interval_ms = interval_to_milliseconds(target_interval)
        start_ms, end_ms = self._resolve_resample_bounds(
            spec=spec,
            source_bounds=source_bounds,
            target_interval_ms=target_interval_ms,
            source_interval_ms=source_interval_ms,
        )
        expected_target_rows = ((end_ms - start_ms) // target_interval_ms) + 1
        expected_source_rows = expected_target_rows * (target_interval_ms // source_interval_ms)
        source_end_open_time_ms = end_ms + target_interval_ms - source_interval_ms
        source_rows = repository.load_klines(
            exchange=exchange,
            symbol=symbol,
            interval=source_interval,
            start_open_time_ms=start_ms,
            end_open_time_ms=source_end_open_time_ms,
        )

        aggregated_records = self._aggregate_resampled_records(
            exchange=exchange,
            symbol=symbol,
            target_interval=target_interval,
            start_ms=start_ms,
            end_ms=end_ms,
            target_interval_ms=target_interval_ms,
            source_interval_ms=source_interval_ms,
            source_rows=source_rows,
        )
        if len(source_rows) != expected_source_rows:
            raise DataSyncError(
                f"Insufficient source 1m klines for {symbol} {target_interval}: "
                f"expected {expected_source_rows} rows from {from_milliseconds(start_ms).isoformat()} "
                f"to {from_milliseconds(source_end_open_time_ms).isoformat()}, found {len(source_rows)}."
            )

        rows_written = repository.upsert_klines(aggregated_records)
        fingerprint = self._fingerprint_records(aggregated_records)
        quality_summary = {
            "missing_bars": 0,
            "duplicate_bars": 0,
            "price_jump_bars": 0,
            "zero_volume_bars": 0,
            "corporate_action_flags": 0,
            "invalid_ohlc_rows": 0,
            "non_positive_price_rows": 0,
            "duplicate_timestamps_removed": 0,
            "cleaning_loss_rows": 0,
            "total_issue_count": 0,
        }
        completed_at = utc_now()
        result = CryptoResampleResult(
            status="completed",
            db_path=str(repository.db_path),
            exchange=exchange,
            symbol=symbol,
            source_interval=source_interval,
            target_interval=target_interval,
            start=from_milliseconds(start_ms),
            end=from_milliseconds(end_ms),
            source_rows=len(source_rows),
            expected_source_rows=expected_source_rows,
            rows_written=rows_written,
            coverage_pct=100.0,
            quality_score=100.0,
            fingerprint=fingerprint,
            completed_at=completed_at,
            quality_summary=quality_summary,
        )
        if spec.persist_manifest:
            manifest = self._build_resample_manifest(result=result)
            manifest_path = DataManifestStore(root=settings.repo_root / "data" / "manifests").write(manifest)
            result.data_version = manifest.data_version
            result.manifest_path = str(manifest_path)
        return result

    def sync_binance_klines(self, spec: DataSyncSpec) -> DataSyncResult:
        exchange = normalize_exchange(spec.exchange or DEFAULT_EXCHANGE)
        if exchange not in SUPPORTED_SYNC_EXCHANGES:
            raise DataSyncError(f"Unsupported crypto data exchange: {exchange}")
        spec = DataSyncSpec(
            symbol=spec.symbol.upper(),
            interval=normalize_interval(spec.interval),
            start=to_utc(spec.start),
            end=to_utc(spec.end),
            db_path=spec.db_path,
            exchange=exchange,
            limit=max(1, min(int(spec.limit), 1000)),
            closed_only=spec.closed_only,
        )
        start_ms = to_milliseconds(spec.start)
        end_ms = to_milliseconds(spec.end)
        interval_ms = interval_to_milliseconds(spec.interval)
        if spec.closed_only:
            end_ms = min(end_ms, self._latest_closed_open_time_ms(interval_ms))
        if end_ms < start_ms:
            raise DataSyncError("No closed kline exists in the requested time range.")
        if spec.exchange == "coinbase_spot":
            spec = DataSyncSpec(
                symbol=spec.symbol,
                interval=spec.interval,
                start=spec.start,
                end=from_milliseconds(end_ms),
                db_path=spec.db_path,
                exchange=spec.exchange,
                limit=min(spec.limit, 300),
                closed_only=spec.closed_only,
            )
            return self._sync_coinbase_klines(spec=spec, start_ms=start_ms, end_ms=end_ms, interval_ms=interval_ms)
        if spec.exchange == "kraken_spot":
            spec = DataSyncSpec(
                symbol=spec.symbol,
                interval=spec.interval,
                start=spec.start,
                end=from_milliseconds(end_ms),
                db_path=spec.db_path,
                exchange=spec.exchange,
                limit=min(spec.limit, 720),
                closed_only=spec.closed_only,
            )
            return self._sync_kraken_klines(spec=spec, start_ms=start_ms, end_ms=end_ms, interval_ms=interval_ms)
        spec = DataSyncSpec(
            symbol=spec.symbol,
            interval=spec.interval,
            start=spec.start,
            end=from_milliseconds(end_ms),
            db_path=spec.db_path,
            exchange=spec.exchange,
            limit=spec.limit,
            closed_only=spec.closed_only,
        )

        repository = self.repository(spec.db_path)
        result = repository.create_sync_run(spec)
        cursor = start_ms

        try:
            while cursor <= end_ms:
                raw_rows = self.client.fetch_klines(
                    symbol=spec.symbol,
                    interval=spec.interval,
                    start_time_ms=cursor,
                    end_time_ms=end_ms,
                    limit=spec.limit,
                )
                result.requests += 1
                if not raw_rows:
                    break

                records = [
                    self._parse_binance_kline(spec.exchange, spec.symbol, spec.interval, row)
                    for row in raw_rows
                ]
                records = [
                    record
                    for record in records
                    if start_ms <= record.open_time_ms <= end_ms
                ]
                if not records:
                    break

                result.rows_received += len(records)
                result.rows_written += repository.upsert_klines(records)
                last_open_time = records[-1].open_time_ms
                next_cursor = last_open_time + interval_ms
                if next_cursor <= cursor:
                    raise DataSyncError("Binance kline pagination did not advance.")
                cursor = next_cursor

                if len(raw_rows) < spec.limit:
                    break
                if settings.binance_request_sleep_seconds > 0:
                    time.sleep(settings.binance_request_sleep_seconds)

            return repository.finish_sync_run(result, status="completed")
        except Exception as exc:
            message = str(exc)
            repository.finish_sync_run(result, status="failed", error=message)
            if isinstance(exc, DataSyncError):
                raise
            raise DataSyncError(message) from exc

    def _sync_kraken_klines(
        self,
        *,
        spec: DataSyncSpec,
        start_ms: int,
        end_ms: int,
        interval_ms: int,
    ) -> DataSyncResult:
        repository = self.repository(spec.db_path)
        result = repository.create_sync_run(spec)
        cursor = start_ms
        request_limit = max(1, min(int(spec.limit), 720))

        try:
            while cursor <= end_ms:
                request_end = min(end_ms, cursor + (request_limit - 1) * interval_ms)
                raw_rows = self.kraken_client.fetch_klines(
                    symbol=spec.symbol,
                    interval=spec.interval,
                    start_time_ms=cursor,
                    end_time_ms=request_end,
                    limit=request_limit,
                )
                result.requests += 1
                if not raw_rows:
                    break

                records = [
                    self._parse_kraken_kline(spec.exchange, spec.symbol, spec.interval, row)
                    for row in raw_rows
                ]
                records = [
                    record
                    for record in records
                    if start_ms <= record.open_time_ms <= end_ms
                ]
                if not records:
                    break

                result.rows_received += len(records)
                result.rows_written += repository.upsert_klines(records)
                last_open_time = records[-1].open_time_ms
                next_cursor = last_open_time + interval_ms
                if next_cursor <= cursor:
                    raise DataSyncError("Kraken kline pagination did not advance.")
                cursor = next_cursor

            return repository.finish_sync_run(result, status="completed")
        except Exception as exc:
            message = str(exc)
            repository.finish_sync_run(result, status="failed", error=message)
            if isinstance(exc, DataSyncError):
                raise
            raise DataSyncError(message) from exc

    def _sync_coinbase_klines(
        self,
        *,
        spec: DataSyncSpec,
        start_ms: int,
        end_ms: int,
        interval_ms: int,
    ) -> DataSyncResult:
        repository = self.repository(spec.db_path)
        result = repository.create_sync_run(spec)
        cursor = start_ms
        request_limit = max(1, min(int(spec.limit), 300))

        try:
            while cursor <= end_ms:
                request_end = min(end_ms, cursor + (request_limit - 1) * interval_ms)
                raw_rows = self.coinbase_client.fetch_klines(
                    symbol=spec.symbol,
                    interval=spec.interval,
                    start_time_ms=cursor,
                    end_time_ms=request_end,
                    limit=request_limit,
                )
                result.requests += 1
                if not raw_rows:
                    break

                records = [
                    self._parse_coinbase_kline(spec.exchange, spec.symbol, spec.interval, row)
                    for row in raw_rows
                ]
                records = [
                    record
                    for record in records
                    if start_ms <= record.open_time_ms <= end_ms
                ]
                if not records:
                    break

                result.rows_received += len(records)
                result.rows_written += repository.upsert_klines(records)
                last_open_time = records[-1].open_time_ms
                next_cursor = last_open_time + interval_ms
                if next_cursor <= cursor:
                    raise DataSyncError("Coinbase kline pagination did not advance.")
                cursor = next_cursor

            return repository.finish_sync_run(result, status="completed")
        except Exception as exc:
            message = str(exc)
            repository.finish_sync_run(result, status="failed", error=message)
            if isinstance(exc, DataSyncError):
                raise
            raise DataSyncError(message) from exc

    def update_latest(self, spec: LatestUpdateSpec) -> DataSyncResult:
        interval = normalize_interval(spec.interval)
        symbol = spec.symbol.upper()
        exchange = normalize_exchange(spec.exchange or DEFAULT_EXCHANGE)
        if exchange not in SUPPORTED_SYNC_EXCHANGES:
            raise DataSyncError(f"Unsupported crypto data exchange: {exchange}")
        repository = self.repository(spec.db_path)
        latest = repository.latest_open_time_ms(exchange=exchange, symbol=symbol, interval=interval)
        interval_ms = interval_to_milliseconds(interval)
        end_ms = self._latest_closed_open_time_ms(interval_ms)

        if latest is None:
            lookback_days = max(1, int(spec.lookback_days or settings.data_default_backfill_days))
            start = utc_now() - timedelta(days=lookback_days)
        else:
            start = from_milliseconds(latest + interval_ms)
        end = from_milliseconds(end_ms)

        if to_milliseconds(start) > end_ms:
            sync_spec = DataSyncSpec(
                symbol=symbol,
                interval=interval,
                start=end,
                end=end,
                db_path=spec.db_path,
                exchange=exchange,
                limit=spec.limit,
                closed_only=True,
            )
            result = repository.create_sync_run(sync_spec)
            return repository.finish_sync_run(result, status="completed")

        return self.sync_binance_klines(
            DataSyncSpec(
                symbol=symbol,
                interval=interval,
                start=start,
                end=end,
                db_path=spec.db_path,
                exchange=exchange,
                limit=spec.limit,
                closed_only=True,
            )
        )

    def _latest_closed_open_time_ms(self, interval_ms: int) -> int:
        now_ms = int(utc_now().timestamp() * 1000)
        return (now_ms // interval_ms) * interval_ms - interval_ms

    def _resolve_resample_bounds(
        self,
        *,
        spec: CryptoResampleSpec,
        source_bounds: dict[str, int],
        target_interval_ms: int,
        source_interval_ms: int,
    ) -> tuple[int, int]:
        source_start_ms = int(source_bounds["start_ms"])
        source_end_ms = int(source_bounds["end_ms"])
        start_ms = source_start_ms if spec.start is None else to_milliseconds(to_utc(spec.start))
        end_ms = source_end_ms if spec.end is None else to_milliseconds(to_utc(spec.end))
        aligned_start_ms = ((start_ms + target_interval_ms - 1) // target_interval_ms) * target_interval_ms
        requested_end_ms = (end_ms // target_interval_ms) * target_interval_ms
        latest_complete_source_end_ms = source_end_ms - (target_interval_ms - source_interval_ms)
        aligned_end_ms = min(
            requested_end_ms,
            (latest_complete_source_end_ms // target_interval_ms) * target_interval_ms,
        )
        if aligned_start_ms > aligned_end_ms:
            raise DataSyncError(
                f"Requested range does not contain a full {spec.target_interval} bar after alignment: "
                f"start={from_milliseconds(start_ms).isoformat()} end={from_milliseconds(end_ms).isoformat()}."
            )
        return aligned_start_ms, aligned_end_ms

    def _aggregate_resampled_records(
        self,
        *,
        exchange: str,
        symbol: str,
        target_interval: str,
        start_ms: int,
        end_ms: int,
        target_interval_ms: int,
        source_interval_ms: int,
        source_rows: list[dict[str, Any]],
    ) -> list[KlineRecord]:
        if not source_rows:
            raise DataSyncError(
                f"Insufficient source 1m klines for {symbol} {target_interval}: no source rows found in the requested range."
            )

        records_by_open_time = {int(row["open_time_ms"]): row for row in source_rows}
        expected_group_size = target_interval_ms // source_interval_ms
        aggregated: list[KlineRecord] = []
        bucket_open_time_ms = start_ms
        while bucket_open_time_ms <= end_ms:
            bucket_rows: list[dict[str, Any]] = []
            missing_open_times: list[int] = []
            for offset in range(expected_group_size):
                minute_open_time_ms = bucket_open_time_ms + offset * source_interval_ms
                row = records_by_open_time.get(minute_open_time_ms)
                if row is None:
                    missing_open_times.append(minute_open_time_ms)
                    continue
                bucket_rows.append(row)
            if missing_open_times:
                first_missing = from_milliseconds(missing_open_times[0]).isoformat()
                raise DataSyncError(
                    f"Insufficient source 1m klines for {symbol} {target_interval} bucket "
                    f"{from_milliseconds(bucket_open_time_ms).isoformat()}: missing {len(missing_open_times)} "
                    f"source rows, first missing {first_missing}."
                )

            aggregated.append(
                KlineRecord(
                    exchange=exchange,
                    symbol=symbol,
                    interval=target_interval,
                    open_time_ms=bucket_open_time_ms,
                    open_time=from_milliseconds(bucket_open_time_ms).isoformat(),
                    close_time_ms=bucket_open_time_ms + target_interval_ms - 1,
                    close_time=from_milliseconds(bucket_open_time_ms + target_interval_ms - 1).isoformat(),
                    open=float(bucket_rows[0]["open"]),
                    high=max(float(row["high"]) for row in bucket_rows),
                    low=min(float(row["low"]) for row in bucket_rows),
                    close=float(bucket_rows[-1]["close"]),
                    volume=sum(float(row["volume"]) for row in bucket_rows),
                    quote_volume=sum(float(row["quote_volume"]) for row in bucket_rows),
                    trade_count=sum(int(row["trade_count"]) for row in bucket_rows),
                    taker_buy_base_volume=sum(float(row["taker_buy_base_volume"]) for row in bucket_rows),
                    taker_buy_quote_volume=sum(float(row["taker_buy_quote_volume"]) for row in bucket_rows),
                    source="sqlite_resample_1m",
                )
            )
            bucket_open_time_ms += target_interval_ms
        return aggregated

    def _fingerprint_records(self, records: list[KlineRecord]) -> str:
        payload = [
            {
                "exchange": record.exchange,
                "symbol": record.symbol,
                "interval": record.interval,
                "open_time_ms": record.open_time_ms,
                "close_time_ms": record.close_time_ms,
                "open": record.open,
                "high": record.high,
                "low": record.low,
                "close": record.close,
                "volume": record.volume,
                "quote_volume": record.quote_volume,
                "trade_count": record.trade_count,
                "taker_buy_base_volume": record.taker_buy_base_volume,
                "taker_buy_quote_volume": record.taker_buy_quote_volume,
            }
            for record in records
        ]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _build_resample_manifest(self, *, result: CryptoResampleResult) -> DataManifest:
        data_version = (
            f"qs-sqlite-{result.symbol}-{result.target_interval}-"
            f"{result.start.strftime('%Y%m%dT%H%M%S')}-{result.fingerprint[:12]}"
        )
        quality_summary = result.quality_summary or {}
        return DataManifest(
            data_version=data_version,
            source="sqlite",
            symbol=result.symbol,
            interval=result.target_interval,
            asset_class="crypto",
            timezone="UTC",
            adjustment="raw",
            adjustment_policy="raw",
            corporate_action_adjustment="raw",
            start=result.start.isoformat(),
            end=result.end.isoformat(),
            row_count=result.rows_written,
            expected_rows=result.rows_written,
            coverage_pct=result.coverage_pct,
            fingerprint=result.fingerprint,
            checksum=result.fingerprint,
            quality_score=result.quality_score,
            fields=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "quote_volume",
                "trade_count",
                "taker_buy_base_volume",
                "taker_buy_quote_volume",
            ],
            issues=[],
            cleaning={
                "duplicate_timestamps_removed": 0,
                "invalid_ohlc_removed": 0,
                "non_positive_prices_removed": 0,
                "cleaning_loss_rows": 0,
                "missing_bars": 0,
            },
            quality_summary=quality_summary,
            raw_path=f"sqlite://{result.db_path}#market_klines/{result.exchange}/{result.symbol}/{result.source_interval}",
            cleaned_path=f"sqlite://{result.db_path}#market_klines/{result.exchange}/{result.symbol}/{result.target_interval}",
            universe_id=f"{result.exchange}:{result.symbol}",
            universe_source="sqlite:market_klines",
            survivorship_bias_risk="clean",
        )

    def _parse_binance_kline(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        row: list[Any],
    ) -> KlineRecord:
        if len(row) < 6:
            raise DataSyncError(f"Invalid Binance kline row: {row}")
        open_time_ms = int(row[0])
        close_time_ms = int(row[6]) if len(row) > 6 else open_time_ms + interval_to_milliseconds(interval) - 1
        return KlineRecord(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            open_time_ms=open_time_ms,
            open_time=from_milliseconds(open_time_ms).isoformat(),
            close_time_ms=close_time_ms,
            close_time=from_milliseconds(close_time_ms).isoformat(),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=float(row[5]),
            quote_volume=float(row[7]) if len(row) > 7 else 0.0,
            trade_count=int(row[8]) if len(row) > 8 else 0,
            taker_buy_base_volume=float(row[9]) if len(row) > 9 else 0.0,
            taker_buy_quote_volume=float(row[10]) if len(row) > 10 else 0.0,
        )

    def _parse_coinbase_kline(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        row: list[Any],
    ) -> KlineRecord:
        if len(row) < 6:
            raise DataSyncError(f"Invalid Coinbase kline row: {row}")
        open_time_ms = int(row[0]) * 1000
        close_time_ms = open_time_ms + interval_to_milliseconds(interval) - 1
        close = float(row[4])
        volume = float(row[5])
        return KlineRecord(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            open_time_ms=open_time_ms,
            open_time=from_milliseconds(open_time_ms).isoformat(),
            close_time_ms=close_time_ms,
            close_time=from_milliseconds(close_time_ms).isoformat(),
            open=float(row[3]),
            high=float(row[2]),
            low=float(row[1]),
            close=close,
            volume=volume,
            quote_volume=close * volume,
            trade_count=0,
            taker_buy_base_volume=0.0,
            taker_buy_quote_volume=0.0,
            source="coinbase_exchange_rest",
        )

    def _parse_kraken_kline(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        row: list[Any],
    ) -> KlineRecord:
        if len(row) < 7:
            raise DataSyncError(f"Invalid Kraken OHLC row: {row}")
        open_time_ms = int(row[0]) * 1000
        close_time_ms = open_time_ms + interval_to_milliseconds(interval) - 1
        close = float(row[4])
        volume = float(row[6])
        return KlineRecord(
            exchange=exchange,
            symbol=symbol,
            interval=interval,
            open_time_ms=open_time_ms,
            open_time=from_milliseconds(open_time_ms).isoformat(),
            close_time_ms=close_time_ms,
            close_time=from_milliseconds(close_time_ms).isoformat(),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=close,
            volume=volume,
            quote_volume=close * volume,
            trade_count=int(row[7]) if len(row) > 7 else 0,
            taker_buy_base_volume=0.0,
            taker_buy_quote_volume=0.0,
            source="kraken_rest",
        )


class DataUpdateScheduler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._spec: LatestUpdateSpec | None = None
        self._interval_seconds = settings.data_update_interval_seconds
        self._run_immediately = True
        self._last_result: DataSyncResult | None = None
        self._last_error: str | None = None
        self._last_started_at: datetime | None = None
        self._next_run_at: datetime | None = None

    def start(
        self,
        service: MarketDataService,
        spec: LatestUpdateSpec,
        interval_seconds: int | None = None,
        run_immediately: bool = True,
    ) -> dict[str, Any]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._spec = spec
            self._interval_seconds = max(60, int(interval_seconds or settings.data_update_interval_seconds))
            self._run_immediately = run_immediately
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._loop,
                args=(service,),
                name="market-data-update-scheduler",
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._lock:
            if self._thread is not None and not self._thread.is_alive():
                self._thread = None
            return self.status()

    def status(self) -> dict[str, Any]:
        running = self._thread is not None and self._thread.is_alive()
        return {
            "running": running,
            "interval_seconds": self._interval_seconds,
            "symbol": self._spec.symbol if self._spec else "",
            "interval": self._spec.interval if self._spec else "",
            "db_path": resolve_data_db_path(self._spec.db_path).as_posix() if self._spec else resolve_data_db_path().as_posix(),
            "last_started_at": self._last_started_at.isoformat() if self._last_started_at else None,
            "next_run_at": self._next_run_at.isoformat() if self._next_run_at else None,
            "last_error": self._last_error,
            "last_result": self._serialize_result(self._last_result) if self._last_result else None,
        }

    def _loop(self, service: MarketDataService) -> None:
        if self._run_immediately:
            self._run_once(service)
        while not self._stop_event.is_set():
            with self._lock:
                self._next_run_at = utc_now() + timedelta(seconds=self._interval_seconds)
            if self._stop_event.wait(self._interval_seconds):
                break
            self._run_once(service)

    def _run_once(self, service: MarketDataService) -> None:
        spec = self._spec
        if spec is None:
            return
        with self._lock:
            self._last_started_at = utc_now()
            self._last_error = None
        try:
            result = service.update_latest(spec)
            with self._lock:
                self._last_result = result
        except Exception as exc:
            logger.exception("Scheduled market data update failed")
            with self._lock:
                self._last_error = str(exc)

    def _serialize_result(self, result: DataSyncResult | None) -> dict[str, Any] | None:
        if result is None:
            return None
        return {
            "run_id": result.run_id,
            "status": result.status,
            "db_path": result.db_path,
            "exchange": result.exchange,
            "symbol": result.symbol,
            "interval": result.interval,
            "start": result.start.isoformat(),
            "end": result.end.isoformat(),
            "rows_received": result.rows_received,
            "rows_written": result.rows_written,
            "requests": result.requests,
            "created_at": result.created_at.isoformat() if result.created_at else None,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            "error": result.error,
        }
