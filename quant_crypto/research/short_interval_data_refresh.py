from __future__ import annotations

import csv
import io
import json
import sqlite3
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from quant_crypto.research.simple_trend_rule_lab import DEFAULT_MARKET_DB, EXCHANGE, SYMBOL


SCHEMA_VERSION = "btc_short_interval_data_refresh_v1"
DEFAULT_OUTPUT_DIR = Path("artifacts/btc_short_interval_data_refresh/latest")
DEFAULT_REPORT_PATH = DEFAULT_OUTPUT_DIR / "btc_short_interval_data_refresh_report.json"
DEFAULT_CSV_PATH = DEFAULT_OUTPUT_DIR / "btc_short_interval_coverage.csv"
DEFAULT_MARKDOWN_PATH = DEFAULT_OUTPUT_DIR / "btc_short_interval_data_refresh_summary_cn.md"
DEFAULT_1H_OUTPUT_DIR = Path("artifacts/btc_market_1h_data_refresh/latest")
DEFAULT_1H_REPORT_PATH = DEFAULT_1H_OUTPUT_DIR / "btc_market_1h_data_refresh_report.json"
DEFAULT_1H_CSV_PATH = DEFAULT_1H_OUTPUT_DIR / "btc_market_1h_coverage.csv"
DEFAULT_1H_MARKDOWN_PATH = DEFAULT_1H_OUTPUT_DIR / "btc_market_1h_data_refresh_summary_cn.md"

SPOT_KLINE_URL = "https://api.binance.com/api/v3/klines"
BINANCE_DATA_API_KLINE_URL = "https://data-api.binance.vision/api/v3/klines"
BINANCE_VISION_DAILY_URL_TEMPLATE = (
    "https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}/"
    "{symbol}-{interval}-{date}.zip"
)
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000}
RESAMPLED_INTERVALS = ("5m", "15m")


@dataclass(frozen=True)
class KlineRow:
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
    quote_volume: float = 0.0
    trade_count: int = 0
    taker_buy_base_volume: float = 0.0
    taker_buy_quote_volume: float = 0.0
    source: str = "binance_spot_public"


def build_btc_short_interval_data_refresh(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    execute_network: bool = False,
    sleep_seconds: float = 0.05,
    fetch_limit: int = 1000,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_REPORT_PATH.name
    csv_path = output_dir / DEFAULT_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_MARKDOWN_PATH.name

    blockers: list[str] = []
    network = {
        "execute_network": bool(execute_network),
        "network_called": False,
        "public_endpoint_used": SPOT_KLINE_URL if execute_network else None,
        "fallback_endpoint_used": None,
        "row_sources": [],
        "rows_received": 0,
        "rows_written": 0,
        "errors": [],
    }
    if not market_db_path.exists():
        blockers.append("btc_market_db_missing")
        payload = _report_payload(
            generated=generated,
            market_db_path=market_db_path,
            output_paths=(report_path, csv_path, markdown_path),
            coverage=[],
            target={},
            network=network,
            resample={},
            blockers=blockers,
        )
        _write_outputs(payload, report_path, csv_path, markdown_path)
        return payload

    with sqlite3.connect(market_db_path) as conn:
        target = _target_from_latest_1h(conn)
        if not target:
            blockers.append("btc_latest_1h_missing")
            coverage = [_coverage(conn, interval) for interval in ("1m", "5m", "15m", "1h")]
            payload = _report_payload(
                generated=generated,
                market_db_path=market_db_path,
                output_paths=(report_path, csv_path, markdown_path),
                coverage=coverage,
                target=target,
                network=network,
                resample={},
                blockers=blockers,
            )
            _write_outputs(payload, report_path, csv_path, markdown_path)
            return payload

        before_coverage = [_coverage(conn, interval) for interval in ("1m", "5m", "15m")]
        before_1m = next(row for row in before_coverage if row["interval"] == "1m")
        target_1m_open_ms = int(target["target_last_open_time_ms_by_interval"]["1m"])
        fetch_start_ms = _next_fetch_start_ms(before_1m, target_1m_open_ms, interval="1m")
        before_blockers = _coverage_blockers(before_coverage, target)
        resample_needed = any(
            str(blocker).startswith("btc_5m") or str(blocker).startswith("btc_15m")
            for blocker in before_blockers
        )
        if fetch_start_ms is not None:
            if execute_network:
                try:
                    fetched = fetch_binance_spot_klines(
                        interval="1m",
                        start_time_ms=fetch_start_ms,
                        end_time_ms=target_1m_open_ms,
                        limit=fetch_limit,
                        sleep_seconds=sleep_seconds,
                    )
                    network["network_called"] = True
                    network["rows_received"] = len(fetched)
                    network["row_sources"] = sorted({row.source for row in fetched})
                    network["fallback_endpoint_used"] = _fallback_endpoint_used(network["row_sources"])
                    network["rows_written"] = upsert_market_klines(conn, fetched)
                except Exception as exc:  # pragma: no cover - network failure path is environment dependent
                    network["network_called"] = True
                    network["errors"].append({"error": type(exc).__name__, "message": str(exc)})
                    blockers.append("btc_1m_public_network_refresh_failed")
            else:
                blockers.append("btc_1m_refresh_required_execute_network_false")

        if fetch_start_ms is not None and (not execute_network or network["errors"]):
            resample_result = {
                "executed": False,
                "reason": "skipped_until_1m_refresh_complete",
                "blockers": ["btc_5m_15m_resample_skipped_until_1m_current"],
                "intervals": [],
            }
        elif not resample_needed:
            resample_result = {
                "executed": False,
                "reason": "short_intervals_already_current",
                "blockers": [],
                "intervals": [],
            }
        else:
            resample_result = resample_short_intervals_from_1m(
                conn,
                target_last_1h_close_time_ms=int(target["latest_1h_close_time_ms"]),
                start_open_time_ms=fetch_start_ms,
            )
        coverage = [_coverage(conn, interval) for interval in ("1m", "5m", "15m", "1h")]
        blockers.extend(_coverage_blockers(coverage, target))
        if resample_result.get("blockers"):
            blockers.extend(str(item) for item in resample_result["blockers"])

    payload = _report_payload(
        generated=generated,
        market_db_path=market_db_path,
        output_paths=(report_path, csv_path, markdown_path),
        coverage=coverage,
        target=target,
        network=network,
        resample=resample_result,
        blockers=sorted(set(blockers)),
    )
    _write_outputs(payload, report_path, csv_path, markdown_path)
    return payload


def build_btc_market_1h_data_refresh(
    *,
    market_db_path: Path = DEFAULT_MARKET_DB,
    output_dir: Path = DEFAULT_1H_OUTPUT_DIR,
    generated_at_utc: datetime | None = None,
    execute_network: bool = False,
    sleep_seconds: float = 0.05,
    fetch_limit: int = 1000,
) -> dict[str, Any]:
    generated = generated_at_utc or datetime.now(timezone.utc)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / DEFAULT_1H_REPORT_PATH.name
    csv_path = output_dir / DEFAULT_1H_CSV_PATH.name
    markdown_path = output_dir / DEFAULT_1H_MARKDOWN_PATH.name
    blockers: list[str] = []
    network = {
        "execute_network": bool(execute_network),
        "network_called": False,
        "public_endpoint_used": SPOT_KLINE_URL if execute_network else None,
        "fallback_endpoint_used": None,
        "row_sources": [],
        "rows_received": 0,
        "rows_written": 0,
        "errors": [],
    }
    if not market_db_path.exists():
        blockers.append("btc_market_db_missing")
        payload = _one_hour_report_payload(
            generated=generated,
            market_db_path=market_db_path,
            output_paths=(report_path, csv_path, markdown_path),
            coverage=[],
            target={},
            network=network,
            blockers=blockers,
        )
        _write_1h_outputs(payload, report_path, csv_path, markdown_path)
        return payload

    with sqlite3.connect(market_db_path) as conn:
        before = _coverage(conn, "1h")
        target = _target_latest_completed_1h(generated)
        fetch_start_ms = _next_fetch_start_ms(before, int(target["target_last_1h_open_time_ms"]), interval="1h")
        if fetch_start_ms is not None:
            if execute_network:
                try:
                    fetched = fetch_binance_spot_klines(
                        interval="1h",
                        start_time_ms=fetch_start_ms,
                        end_time_ms=int(target["target_last_1h_open_time_ms"]),
                        limit=fetch_limit,
                        sleep_seconds=sleep_seconds,
                    )
                    network["network_called"] = True
                    network["rows_received"] = len(fetched)
                    network["row_sources"] = sorted({row.source for row in fetched})
                    network["fallback_endpoint_used"] = _fallback_endpoint_used(network["row_sources"])
                    network["rows_written"] = upsert_market_klines(conn, fetched)
                except Exception as exc:  # pragma: no cover - network failure path is environment dependent
                    network["network_called"] = True
                    network["errors"].append({"error": type(exc).__name__, "message": str(exc)})
                    blockers.append("btc_1h_public_network_refresh_failed")
            else:
                blockers.append("btc_1h_refresh_required_execute_network_false")
        coverage = [_coverage(conn, "1h")]
        blockers.extend(_one_hour_coverage_blockers(coverage[0], target))

    payload = _one_hour_report_payload(
        generated=generated,
        market_db_path=market_db_path,
        output_paths=(report_path, csv_path, markdown_path),
        coverage=coverage,
        target=target,
        network=network,
        blockers=sorted(set(blockers)),
    )
    _write_1h_outputs(payload, report_path, csv_path, markdown_path)
    return payload


def load_market_klines_frame(
    db_path: Path,
    *,
    interval: str,
    exchange: str = EXCHANGE,
    symbol: str = SYMBOL,
) -> pd.DataFrame:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            select open_time, close_time, open_time_ms, close_time_ms, open, high, low, close, volume
            from market_klines
            where exchange = ?
              and upper(symbol) = ?
              and interval = ?
            order by open_time_ms
            """,
            [exchange, symbol, interval],
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["open_time", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(
        rows,
        columns=["open_time", "close_time", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"],
    )
    frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], utc=True)
    for col in ["open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna().sort_values("open_time_ms").drop_duplicates(subset=["open_time_ms"], keep="last")
    frame = frame.set_index(pd.DatetimeIndex(frame["close_time"]))
    return frame[["open_time", "open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume"]]


def fetch_binance_spot_klines(
    *,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    limit: int = 1000,
    sleep_seconds: float = 0.05,
) -> list[KlineRow]:
    if interval not in {"1m", "1h"}:
        raise ValueError("btc public spot refresh supports 1m and 1h rows; 5m/15m are resampled from complete 1m rows")
    try:
        return _fetch_binance_spot_klines_rest(
            interval=interval,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            sleep_seconds=sleep_seconds,
            endpoint=SPOT_KLINE_URL,
            source="binance_spot_public_rest_klines",
        )
    except Exception:
        try:
            return _fetch_binance_spot_klines_rest(
                interval=interval,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                limit=limit,
                sleep_seconds=sleep_seconds,
                endpoint=BINANCE_DATA_API_KLINE_URL,
                source="binance_vision_data_api_klines",
            )
        except Exception:
            return fetch_binance_vision_spot_klines(
                interval=interval,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                sleep_seconds=sleep_seconds,
            )


def _fetch_binance_spot_klines_rest(
    *,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    limit: int = 1000,
    sleep_seconds: float = 0.05,
    endpoint: str = SPOT_KLINE_URL,
    source: str = "binance_spot_public_rest_klines",
) -> list[KlineRow]:
    if interval not in {"1m", "1h"}:
        raise ValueError("btc public spot refresh supports 1m and 1h rows; 5m/15m are resampled from complete 1m rows")
    rows: list[KlineRow] = []
    cursor = int(start_time_ms)
    while cursor <= int(end_time_ms):
        params = {
            "symbol": SYMBOL,
            "interval": interval,
            "startTime": cursor,
            "endTime": int(end_time_ms),
            "limit": int(limit),
        }
        url = endpoint + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - public market-data endpoint only
            payload = json.loads(response.read().decode("utf-8"))
        if not payload:
            break
        batch = [replace(_parse_spot_kline(row, interval=interval), source=source) for row in payload]
        batch = [row for row in batch if row.open_time_ms <= int(end_time_ms)]
        rows.extend(batch)
        next_cursor = max(row.open_time_ms for row in batch) + INTERVAL_MS[interval]
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(float(sleep_seconds))
    deduped = {row.open_time_ms: row for row in rows}
    return [deduped[key] for key in sorted(deduped)]


def fetch_binance_vision_spot_klines(
    *,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    sleep_seconds: float = 0.05,
) -> list[KlineRow]:
    if interval not in {"1m", "1h"}:
        raise ValueError("btc public spot refresh supports 1m and 1h rows; 5m/15m are resampled from complete 1m rows")
    start_day = datetime.fromtimestamp(int(start_time_ms) / 1000, tz=timezone.utc).date()
    end_day = datetime.fromtimestamp(int(end_time_ms) / 1000, tz=timezone.utc).date()
    rows: list[KlineRow] = []
    day = start_day
    while day <= end_day:
        url = BINANCE_VISION_DAILY_URL_TEMPLATE.format(symbol=SYMBOL, interval=interval, date=day.isoformat())
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - public market-data endpoint only
                archive_bytes = response.read()
        except Exception:
            day += timedelta(days=1)
            continue
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            csv_name = next(name for name in archive.namelist() if name.endswith(".csv"))
            with archive.open(csv_name) as csv_file:
                text = io.TextIOWrapper(csv_file, encoding="utf-8")
                for raw in csv.reader(text):
                    if not raw or str(raw[0]).lower() == "open_time":
                        continue
                    parsed = replace(_parse_spot_kline(raw, interval=interval), source="binance_vision_spot_daily_zip")
                    if int(start_time_ms) <= parsed.open_time_ms <= int(end_time_ms):
                        rows.append(parsed)
        day += timedelta(days=1)
        time.sleep(float(sleep_seconds))
    deduped = {row.open_time_ms: row for row in rows}
    return [deduped[key] for key in sorted(deduped)]


def upsert_market_klines(conn: sqlite3.Connection, rows: Sequence[KlineRow]) -> int:
    if not rows:
        return 0
    columns = _table_columns(conn)
    insert_columns = [col for col in _kline_insert_columns() if col in columns]
    now = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        """
        delete from market_klines
        where exchange = ? and symbol = ? and interval = ? and open_time_ms = ?
        """,
        [(row.exchange, row.symbol, row.interval, row.open_time_ms) for row in rows],
    )
    values = []
    for row in rows:
        payload = _kline_payload(row, now=now)
        values.append([payload[col] for col in insert_columns])
    placeholders = ", ".join(["?"] * len(insert_columns))
    conn.executemany(
        f"insert into market_klines ({', '.join(insert_columns)}) values ({placeholders})",
        values,
    )
    conn.commit()
    return len(rows)


def resample_short_intervals_from_1m(
    conn: sqlite3.Connection,
    *,
    target_last_1h_close_time_ms: int,
    start_open_time_ms: int | None = None,
) -> dict[str, Any]:
    source_start_ms = None
    if start_open_time_ms is not None:
        source_start_ms = (int(start_open_time_ms) // INTERVAL_MS["15m"]) * INTERVAL_MS["15m"]
    target_last_1m_open_ms = int(target_last_1h_close_time_ms) - INTERVAL_MS["1m"] + 1
    one_minute = _load_interval_from_conn(
        conn,
        "1m",
        start_open_time_ms=source_start_ms,
        end_open_time_ms=target_last_1m_open_ms,
    )
    if one_minute.empty:
        return {"executed": False, "blockers": ["btc_1m_source_missing_for_resample"], "intervals": []}
    intervals = []
    blockers: list[str] = []
    for interval in RESAMPLED_INTERVALS:
        interval_rows = _resample_from_1m(
            one_minute,
            interval=interval,
            target_last_1h_close_time_ms=target_last_1h_close_time_ms,
            start_open_time_ms=start_open_time_ms,
        )
        if not interval_rows:
            blockers.append(f"btc_{interval}_resample_no_complete_rows")
            intervals.append({"interval": interval, "rows_written": 0})
            continue
        written = upsert_market_klines(conn, interval_rows)
        intervals.append(
            {
                "interval": interval,
                "rows_written": written,
                "start": interval_rows[0].open_time,
                "end": interval_rows[-1].close_time,
                "source": "resampled_from_complete_1m",
            }
        )
    return {"executed": True, "blockers": blockers, "intervals": intervals}


def _resample_from_1m(
    frame: pd.DataFrame,
    *,
    interval: str,
    target_last_1h_close_time_ms: int,
    start_open_time_ms: int | None = None,
) -> list[KlineRow]:
    minutes = int(INTERVAL_MS[interval] / 60_000)
    target_last_open_ms = int(target_last_1h_close_time_ms) - INTERVAL_MS[interval] + 1
    source = frame[frame["open_time_ms"] <= target_last_open_ms + INTERVAL_MS[interval] - 60_000].copy()
    if source.empty:
        return []
    source["bucket_ms"] = (source["open_time_ms"].astype("int64") // INTERVAL_MS[interval]) * INTERVAL_MS[interval]
    first_output_bucket_ms = None
    if start_open_time_ms is not None:
        first_output_bucket_ms = (int(start_open_time_ms) // INTERVAL_MS[interval]) * INTERVAL_MS[interval]
    rows: list[KlineRow] = []
    for bucket_ms, chunk in source.groupby("bucket_ms", sort=True):
        if first_output_bucket_ms is not None and int(bucket_ms) < int(first_output_bucket_ms):
            continue
        if len(chunk) != minutes:
            continue
        chunk = chunk.sort_values("open_time_ms")
        expected = list(range(int(bucket_ms), int(bucket_ms) + INTERVAL_MS[interval], 60_000))
        if [int(value) for value in chunk["open_time_ms"].tolist()] != expected:
            continue
        close_time_ms = int(bucket_ms) + INTERVAL_MS[interval] - 1
        if close_time_ms > int(target_last_1h_close_time_ms):
            continue
        rows.append(
            KlineRow(
                exchange=EXCHANGE,
                symbol=SYMBOL,
                interval=interval,
                open_time_ms=int(bucket_ms),
                open_time=_iso_from_ms(int(bucket_ms)),
                close_time_ms=close_time_ms,
                close_time=_iso_from_ms(close_time_ms),
                open=float(chunk["open"].iloc[0]),
                high=float(chunk["high"].max()),
                low=float(chunk["low"].min()),
                close=float(chunk["close"].iloc[-1]),
                volume=float(chunk["volume"].sum()),
                source="sqlite_resample_complete_1m",
            )
        )
    return rows


def _target_from_latest_1h(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        select open_time_ms, close_time_ms, close_time
        from market_klines
        where exchange = ? and upper(symbol) = ? and interval = '1h'
        order by close_time_ms desc
        limit 1
        """,
        [EXCHANGE, SYMBOL],
    ).fetchone()
    if not row:
        return {}
    close_time_ms = int(row[1])
    return {
        "latest_1h_open_time_ms": int(row[0]),
        "latest_1h_close_time_ms": close_time_ms,
        "latest_1h_close_time": row[2],
        "target_last_open_time_ms_by_interval": {
            interval: close_time_ms - INTERVAL_MS[interval] + 1 for interval in ("1m", "5m", "15m")
        },
        "target_rule": "short intervals must cover complete bars through the latest completed 1h close",
    }


def _coverage(conn: sqlite3.Connection, interval: str) -> dict[str, Any]:
    step = INTERVAL_MS[interval]
    row = conn.execute(
        """
        select count(*), min(open_time_ms), max(open_time_ms), min(close_time), max(close_time)
        from market_klines
        where exchange = ? and upper(symbol) = ? and interval = ?
        """,
        [EXCHANGE, SYMBOL, interval],
    ).fetchone()
    count = int(row[0] or 0)
    duplicate_count = 0
    gap_count = 0
    if count:
        duplicates = conn.execute(
            """
            select count(*) from (
              select open_time_ms, count(*) as n
              from market_klines
              where exchange = ? and upper(symbol) = ? and interval = ?
              group by open_time_ms
              having n > 1
            )
            """,
            [EXCHANGE, SYMBOL, interval],
        ).fetchone()
        duplicate_count = int(duplicates[0] or 0)
        try:
            gaps = conn.execute(
                """
                select count(*) from (
                  select open_time_ms - lag(open_time_ms) over (order by open_time_ms) as delta_ms
                  from market_klines
                  where exchange = ? and upper(symbol) = ? and interval = ?
                )
                where delta_ms is not null and delta_ms != ?
                """,
                [EXCHANGE, SYMBOL, interval, step],
            ).fetchone()
            gap_count = int(gaps[0] or 0)
        except sqlite3.OperationalError:
            times = [
                int(item[0])
                for item in conn.execute(
                    """
                    select open_time_ms
                    from market_klines
                    where exchange = ? and upper(symbol) = ? and interval = ?
                    order by open_time_ms
                    """,
                    [EXCHANGE, SYMBOL, interval],
                ).fetchall()
            ]
            gap_count = sum(1 for previous, current in zip(times, times[1:]) if current - previous != step)
    return {
        "exchange": EXCHANGE,
        "symbol": SYMBOL,
        "interval": interval,
        "row_count": count,
        "first_open_time_ms": int(row[1]) if row[1] is not None else None,
        "last_open_time_ms": int(row[2]) if row[2] is not None else None,
        "first_close_time": row[3],
        "last_close_time": row[4],
        "duplicate_open_time_count": duplicate_count,
        "gap_count": gap_count,
        "expected_step_ms": step,
    }


def _coverage_blockers(coverage: Sequence[Mapping[str, Any]], target: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    target_by_interval = target.get("target_last_open_time_ms_by_interval", {})
    for row in coverage:
        interval = str(row["interval"])
        if interval not in ("1m", "5m", "15m"):
            continue
        if int(row.get("row_count", 0) or 0) <= 0:
            blockers.append(f"btc_{interval}_missing")
        if int(row.get("duplicate_open_time_count", 0) or 0) > 0:
            blockers.append(f"btc_{interval}_duplicate_open_times")
        if int(row.get("gap_count", 0) or 0) > 0:
            blockers.append(f"btc_{interval}_has_gaps")
        target_open = target_by_interval.get(interval)
        last_open = row.get("last_open_time_ms")
        if target_open is not None and (last_open is None or int(last_open) < int(target_open)):
            blockers.append(f"btc_{interval}_coverage_stale_vs_latest_1h")
    return blockers


def _target_latest_completed_1h(generated: datetime) -> dict[str, Any]:
    safe = generated.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    target_open_ms = int(safe.timestamp() * 1000)
    return {
        "target_last_1h_open_time_ms": target_open_ms,
        "target_last_1h_close_time_ms": target_open_ms + INTERVAL_MS["1h"] - 1,
        "target_last_1h_close_time": _iso_from_ms(target_open_ms + INTERVAL_MS["1h"] - 1),
        "target_rule": "1h spot rows are refreshed only through the latest fully completed UTC hour",
    }


def _one_hour_coverage_blockers(coverage: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if int(coverage.get("row_count", 0) or 0) <= 0:
        blockers.append("btc_1h_missing")
    if int(coverage.get("duplicate_open_time_count", 0) or 0) > 0:
        blockers.append("btc_1h_duplicate_open_times")
    if int(coverage.get("gap_count", 0) or 0) > 0:
        blockers.append("btc_1h_has_gaps")
    target_open = target.get("target_last_1h_open_time_ms")
    last_open = coverage.get("last_open_time_ms")
    if target_open is not None and (last_open is None or int(last_open) < int(target_open)):
        blockers.append("btc_1h_coverage_stale_vs_latest_completed_hour")
    return blockers


def _fallback_endpoint_used(row_sources: Sequence[str]) -> str | None:
    endpoints = []
    if any("binance_vision_data_api" in source for source in row_sources):
        endpoints.append(BINANCE_DATA_API_KLINE_URL)
    if any("binance_vision_spot_daily_zip" in source for source in row_sources):
        endpoints.append(BINANCE_VISION_DAILY_URL_TEMPLATE)
    return ";".join(endpoints) if endpoints else None


def _next_fetch_start_ms(coverage: Mapping[str, Any], target_open_ms: int, *, interval: str) -> int | None:
    last_open = coverage.get("last_open_time_ms")
    step = INTERVAL_MS[interval]
    if last_open is None:
        return int(target_open_ms) - 24 * step + step
    next_open = int(last_open) + step
    return next_open if next_open <= int(target_open_ms) else None


def _load_interval_from_conn(
    conn: sqlite3.Connection,
    interval: str,
    *,
    start_open_time_ms: int | None = None,
    end_open_time_ms: int | None = None,
) -> pd.DataFrame:
    predicates = [
        "exchange = ?",
        "upper(symbol) = ?",
        "interval = ?",
    ]
    params: list[Any] = [EXCHANGE, SYMBOL, interval]
    if start_open_time_ms is not None:
        predicates.append("open_time_ms >= ?")
        params.append(int(start_open_time_ms))
    if end_open_time_ms is not None:
        predicates.append("open_time_ms <= ?")
        params.append(int(end_open_time_ms))
    rows = conn.execute(
        f"""
        select open_time_ms, open, high, low, close, volume
        from market_klines
        where {" and ".join(predicates)}
        order by open_time_ms
        """,
        params,
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["open_time_ms", "open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(rows, columns=["open_time_ms", "open", "high", "low", "close", "volume"])
    for col in frame.columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna().drop_duplicates(subset=["open_time_ms"], keep="last").sort_values("open_time_ms")


def _parse_spot_kline(row: Sequence[Any], *, interval: str) -> KlineRow:
    open_time_ms = _normalize_epoch_ms(row[0])
    close_time_ms = _normalize_epoch_ms(row[6])
    return KlineRow(
        exchange=EXCHANGE,
        symbol=SYMBOL,
        interval=interval,
        open_time_ms=open_time_ms,
        open_time=_iso_from_ms(open_time_ms),
        close_time_ms=close_time_ms,
        close_time=_iso_from_ms(close_time_ms),
        open=float(row[1]),
        high=float(row[2]),
        low=float(row[3]),
        close=float(row[4]),
        volume=float(row[5]),
        quote_volume=float(row[7]) if len(row) > 7 else 0.0,
        trade_count=int(row[8]) if len(row) > 8 else 0,
        taker_buy_base_volume=float(row[9]) if len(row) > 9 else 0.0,
        taker_buy_quote_volume=float(row[10]) if len(row) > 10 else 0.0,
        source="binance_spot_public_rest_klines",
    )


def _normalize_epoch_ms(value: Any) -> int:
    normalized = int(value)
    while abs(normalized) > 9_999_999_999_999:
        normalized //= 1000
    return normalized


def _kline_insert_columns() -> list[str]:
    return [
        "exchange",
        "symbol",
        "interval",
        "open_time_ms",
        "open_time",
        "close_time_ms",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
        "source",
        "ingested_at",
        "updated_at",
    ]


def _table_columns(conn: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in conn.execute("pragma table_info(market_klines)").fetchall()}


def _kline_payload(row: KlineRow, *, now: str) -> dict[str, Any]:
    return {
        "exchange": row.exchange,
        "symbol": row.symbol,
        "interval": row.interval,
        "open_time_ms": row.open_time_ms,
        "open_time": row.open_time,
        "close_time_ms": row.close_time_ms,
        "close_time": row.close_time,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
        "quote_volume": row.quote_volume,
        "trade_count": row.trade_count,
        "taker_buy_base_volume": row.taker_buy_base_volume,
        "taker_buy_quote_volume": row.taker_buy_quote_volume,
        "source": row.source,
        "ingested_at": now,
        "updated_at": now,
    }


def _report_payload(
    *,
    generated: datetime,
    market_db_path: Path,
    output_paths: tuple[Path, Path, Path],
    coverage: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    network: Mapping[str, Any],
    resample: Mapping[str, Any],
    blockers: Sequence[str],
) -> dict[str, Any]:
    report_path, csv_path, markdown_path = output_paths
    complete = not blockers
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "complete_research_only" if complete else "blocked_data_refresh_required",
        "decision": "btc_short_interval_data_refresh_research_only_no_paper_no_live",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "exchange": EXCHANGE,
            "symbol": SYMBOL,
            "source_table": "market_klines",
        },
        "target": dict(target),
        "coverage": list(coverage),
        "network": dict(network),
        "resample": dict(resample),
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "broker_access_allowed": False,
            "oms_access_allowed": False,
            "reason": "short interval data refresh is a research data-prep step only",
        },
        "blockers": list(blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "coverage_csv": _portable_path(csv_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }


def _one_hour_report_payload(
    *,
    generated: datetime,
    market_db_path: Path,
    output_paths: tuple[Path, Path, Path],
    coverage: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    network: Mapping[str, Any],
    blockers: Sequence[str],
) -> dict[str, Any]:
    report_path, csv_path, markdown_path = output_paths
    complete = not blockers
    return {
        "schema_version": "btc_market_1h_data_refresh_v1",
        "generated_at_utc": generated.astimezone(timezone.utc).isoformat(),
        "status": "complete_research_only" if complete else "blocked_data_refresh_required",
        "decision": "btc_market_1h_data_refresh_research_only_no_paper_no_live",
        "code_commit": _git_commit(),
        "input": {
            "market_db_path": _portable_path(market_db_path),
            "exchange": EXCHANGE,
            "symbol": SYMBOL,
            "source_table": "market_klines",
        },
        "target": dict(target),
        "coverage": list(coverage),
        "network": dict(network),
        "guardrails": _guardrails(),
        "gate": {
            "paper_queue_write_allowed": False,
            "paper_candidate_created": False,
            "live_unlock_allowed": False,
            "live_order_allowed": False,
            "broker_access_allowed": False,
            "oms_access_allowed": False,
            "reason": "1h market data refresh is a research data-prep step only",
        },
        "blockers": list(blockers),
        "outputs": {
            "json": _portable_path(report_path),
            "coverage_csv": _portable_path(csv_path),
            "summary_cn": _portable_path(markdown_path),
        },
    }


def render_btc_market_1h_data_refresh_markdown(report: Mapping[str, Any]) -> str:
    gate = report.get("gate", {})
    target = report.get("target", {})
    lines = [
        "# BTC 1H 行情数据刷新报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 目标最新完成 1H：`{target.get('target_last_1h_close_time')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 覆盖情况",
        "",
        "| 周期 | 行数 | 最早 | 最新 | 缺口 | 重复 |",
        "|---|---:|---|---|---:|---:|",
    ]
    for row in report.get("coverage", []):
        lines.append(
            f"| {row.get('interval')} | {row.get('row_count')} | {row.get('first_close_time')} | "
            f"{row.get('last_close_time')} | {row.get('gap_count')} | {row.get('duplicate_open_time_count')} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 本流程只使用 Binance 公开现货 K 线接口或 Binance Vision 免费归档补 1H 数据。",
            "- 只补到最新已完成 UTC 小时，不使用未完成尾部 K 线。",
            "- 本流程只准备 observe-only 研究数据，不创建策略、不写 paper 队列、不解锁 live。",
        ]
    )
    if report.get("blockers"):
        lines.extend(["", "## 阻塞项", ""])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def render_btc_short_interval_data_refresh_markdown(report: Mapping[str, Any]) -> str:
    gate = report.get("gate", {})
    lines = [
        "# BTC 短周期数据刷新报告",
        "",
        f"- 状态：`{report.get('status')}`",
        f"- 决策边界：`{report.get('decision')}`",
        f"- 写入 paper 队列：`{gate.get('paper_queue_write_allowed')}`",
        f"- 解锁 live：`{gate.get('live_unlock_allowed')}`",
        "",
        "## 覆盖情况",
        "",
        "| 周期 | 行数 | 最早 | 最新 | 缺口 | 重复 |",
        "|---|---:|---|---|---:|---:|",
    ]
    for row in report.get("coverage", []):
        lines.append(
            f"| {row.get('interval')} | {row.get('row_count')} | {row.get('first_close_time')} | "
            f"{row.get('last_close_time')} | {row.get('gap_count')} | {row.get('duplicate_open_time_count')} |"
        )
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- `5m/15m` 只允许由完整 `1m` 聚合生成，未完成尾部桶会被丢弃。",
            "- 本流程只准备研究数据，不创建策略、不写 paper 队列、不解锁 live。",
        ]
    )
    if report.get("blockers"):
        lines.extend(["", "## 阻塞项", ""])
        lines.extend(f"- `{item}`" for item in report.get("blockers", []))
    return "\n".join(lines) + "\n"


def _write_outputs(payload: Mapping[str, Any], report_path: Path, csv_path: Path, markdown_path: Path) -> None:
    _write_json(report_path, payload)
    _write_csv(csv_path, payload.get("coverage", []))
    _write_text(markdown_path, render_btc_short_interval_data_refresh_markdown(payload))


def _write_1h_outputs(payload: Mapping[str, Any], report_path: Path, csv_path: Path, markdown_path: Path) -> None:
    _write_json(report_path, payload)
    _write_csv(csv_path, payload.get("coverage", []))
    _write_text(markdown_path, render_btc_market_1h_data_refresh_markdown(payload))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "exchange",
        "symbol",
        "interval",
        "row_count",
        "first_open_time_ms",
        "last_open_time_ms",
        "first_close_time",
        "last_close_time",
        "duplicate_open_time_count",
        "gap_count",
        "expected_step_ms",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
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


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()


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
