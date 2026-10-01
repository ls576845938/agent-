#!/usr/bin/env python3
"""Backfill IBKR 1-minute bars for supplemental US ETF research.

This importer is read-only broker market data plumbing. It writes raw IBKR bars
and a coverage report, but it does not mark the data as PIT-clean research input
and it does not use account, position, or order endpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fetch_us_equity_ibkr_historical_bars import (
    _bars_to_frame,
    _connect_readonly,
    _dedupe,
    _guardrails,
    _load_ibkr_runtime,
    _relpath,
    _resolve,
    _ts_str,
    _unique,
    _utc_now,
    _write_json,
)


SCHEMA_VERSION = "us_equity_ibkr_minute_backfill_report_v1"
DEFAULT_SYMBOLS = ("QQQ", "TQQQ")
DEFAULT_START_DATE = "2017-05-31"
DEFAULT_OUTPUT_ROOT = Path("data/external/us_equity_intraday/ibkr/interval=1m")
DEFAULT_REPORT = Path("artifacts/us_equity_data_status/latest/ibkr_minute_backfill_report.json")


class IbkrClient(Protocol):
    def connect(self, host: str, port: int, clientId: int, timeout: float, **kwargs: Any) -> Any: ...

    def disconnect(self) -> Any: ...

    def isConnected(self) -> bool: ...

    def qualifyContracts(self, contract: Any) -> list[Any]: ...

    def reqHistoricalData(
        self,
        contract: Any,
        endDateTime: str,
        durationStr: str,
        barSizeSetting: str,
        whatToShow: str,
        useRTH: bool,
        formatDate: int,
        keepUpToDate: bool,
    ) -> list[Any]: ...


def import_ibkr_minute_backfill(
    *,
    repo_root: Path,
    symbols: Iterable[str] = DEFAULT_SYMBOLS,
    start_date: str = DEFAULT_START_DATE,
    end_date: str | None = None,
    host: str = "127.0.0.1",
    port: int = 4002,
    client_id: int = 81,
    duration: str = "1 M",
    bar_size: str = "1 min",
    what_to_show: str = "TRADES",
    use_rth: bool = False,
    execute_network: bool = False,
    request_sleep_seconds: float = 1.0,
    request_timeout_seconds: float = 30.0,
    connect_timeout_seconds: float = 5.0,
    chunk_days: int = 0,
    max_new_chunks_per_run: int = 0,
    max_new_chunks_per_symbol: int = 0,
    skip_existing: bool = True,
    preserve_existing_kline_on_partial: bool = True,
    min_coverage_ratio: float = 0.80,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report_path: Path = DEFAULT_REPORT,
    generated_at: str | None = None,
    ib_client: IbkrClient | None = None,
    stock_factory: Any | None = None,
) -> dict[str, Any]:
    root = repo_root.resolve()
    generated = generated_at or _utc_now()
    effective_end_date = end_date or generated[:10]
    selected_symbols = tuple(_unique(symbols))
    chunks = _day_chunks(start_date, effective_end_date, int(chunk_days)) if int(chunk_days) > 0 else _month_chunks(start_date, effective_end_date)
    output_abs = _resolve(root, output_root)
    report_abs = _resolve(root, report_path)
    kline_root = output_abs / "kline"
    chunk_root = output_abs / "chunks"

    base_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated,
        "provider": "ibkr",
        "asset": "us_equity",
        "source_type": "broker_historical_market_data_backfill_raw",
        "symbols": list(selected_symbols),
        "symbol_count": len(selected_symbols),
        "host": host,
        "port": int(port),
        "client_id": int(client_id),
        "duration": duration,
        "bar_size": bar_size,
        "what_to_show": what_to_show,
        "use_rth": bool(use_rth),
        "requested_start_date": start_date,
        "requested_end_date": effective_end_date,
        "planned_chunk_count_per_symbol": len(chunks),
        "chunk_days": int(chunk_days),
        "max_new_chunks_per_run": int(max_new_chunks_per_run),
        "max_new_chunks_per_symbol": int(max_new_chunks_per_symbol),
        "request_timeout_seconds": float(request_timeout_seconds),
        "skip_existing": bool(skip_existing),
        "preserve_existing_kline_on_partial": bool(preserve_existing_kline_on_partial),
        "min_coverage_ratio": float(min_coverage_ratio),
        "readonly_connection_requested": True,
        "output_root": _relpath(output_abs, root),
        "kline_root": _relpath(kline_root, root),
        "chunk_root": _relpath(chunk_root, root),
        "report_path": _relpath(report_abs, root),
        "guardrails": _guardrails(),
        "data_limitations": _data_limitations(),
        "adjustment_controls": _adjustment_controls(),
    }

    if not execute_network:
        payload = {
            **base_payload,
            "status": "dry_run",
            "research_ready_status": "blocked",
            "network_called": False,
            "writes_performed": False,
            "attempted_new_chunk_count": 0,
            "symbol_reports": {},
            "raw_data_blockers": [],
            "research_blockers": ["ibkr_minute_backfill_not_executed"],
            "blockers": [],
        }
        _write_json(report_abs, payload)
        return payload

    try:
        ib, stock = _load_ibkr_runtime(ib_client=ib_client, stock_factory=stock_factory)
    except Exception as exc:  # noqa: BLE001
        payload = {
            **base_payload,
            "status": "blocked",
            "research_ready_status": "blocked",
            "network_called": False,
            "writes_performed": False,
            "attempted_new_chunk_count": 0,
            "symbol_reports": {},
            "raw_data_blockers": ["ibkr_python_runtime_missing"],
            "research_blockers": ["ibkr_python_runtime_missing"],
            "blockers": ["ibkr_python_runtime_missing"],
            "runtime_error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
        _write_json(report_abs, payload)
        return payload

    try:
        _connect_readonly(
            ib,
            host=host,
            port=int(port),
            client_id=int(client_id),
            timeout=float(connect_timeout_seconds),
        )
        if not ib.isConnected():
            raise ConnectionError("ibkr_not_connected_after_connect")
    except Exception as exc:  # noqa: BLE001
        payload = {
            **base_payload,
            "status": "blocked",
            "research_ready_status": "blocked",
            "network_called": False,
            "writes_performed": False,
            "attempted_new_chunk_count": 0,
            "symbol_reports": {},
            "raw_data_blockers": ["ibkr_tws_or_gateway_not_connected"],
            "research_blockers": ["ibkr_tws_or_gateway_not_connected"],
            "blockers": ["ibkr_tws_or_gateway_not_connected"],
            "connection_error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
        _write_json(report_abs, payload)
        return payload

    kline_root.mkdir(parents=True, exist_ok=True)
    chunk_root.mkdir(parents=True, exist_ok=True)
    _set_ibkr_request_timeout(ib, float(request_timeout_seconds))
    symbol_reports: dict[str, Any] = {}
    raw_blockers: list[str] = []
    research_blockers: list[str] = []
    attempted_new_chunk_count = 0
    writes_performed = False

    try:
        for symbol in selected_symbols:
            if int(max_new_chunks_per_symbol) > 0:
                symbol_attempted_so_far = 0
                symbol_max_new_chunks = int(max_new_chunks_per_symbol)
            else:
                symbol_attempted_so_far = attempted_new_chunk_count
                symbol_max_new_chunks = int(max_new_chunks_per_run)
            report, attempted, wrote = _fetch_symbol_backfill(
                ib=ib,
                stock_factory=stock,
                symbol=symbol,
                chunks=chunks,
                duration=duration,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
                request_sleep_seconds=request_sleep_seconds,
                chunk_days=int(chunk_days),
                max_new_chunks_per_run=symbol_max_new_chunks,
                attempted_so_far=symbol_attempted_so_far,
                skip_existing=skip_existing,
                preserve_existing_kline_on_partial=preserve_existing_kline_on_partial,
                min_coverage_ratio=min_coverage_ratio,
                kline_root=kline_root,
                chunk_root=chunk_root,
                root=root,
            )
            if int(max_new_chunks_per_symbol) > 0:
                attempted_new_chunk_count += attempted
            else:
                attempted_new_chunk_count = attempted
            writes_performed = writes_performed or wrote
            symbol_reports[symbol] = report
            raw_blockers.extend(str(item) for item in report.get("raw_data_blockers", []))
            research_blockers.extend(str(item) for item in report.get("research_blockers", []))
    finally:
        try:
            ib.disconnect()
        except Exception:  # noqa: BLE001
            pass

    raw_blockers = _dedupe(raw_blockers)
    research_blockers = _dedupe(research_blockers)
    available_symbols = [
        symbol
        for symbol, row in symbol_reports.items()
        if row.get("raw_data_status") == "available"
    ]
    status = "pass" if len(available_symbols) == len(selected_symbols) and not raw_blockers else "partial"
    payload = {
        **base_payload,
        "status": status,
        "research_ready_status": "pass" if not research_blockers and status == "pass" else "blocked",
        "network_called": attempted_new_chunk_count > 0,
        "writes_performed": bool(writes_performed),
        "attempted_new_chunk_count": int(attempted_new_chunk_count),
        "available_symbols": available_symbols,
        "missing_symbols": sorted(set(selected_symbols) - set(available_symbols)),
        "symbol_reports": symbol_reports,
        "summary": _summary(symbol_reports),
        "raw_data_blockers": raw_blockers,
        "research_blockers": research_blockers,
        "blockers": _dedupe(raw_blockers + research_blockers),
    }
    _write_json(report_abs, payload)
    return payload


def _fetch_symbol_backfill(
    *,
    ib: IbkrClient,
    stock_factory: Any,
    symbol: str,
    chunks: list[tuple[str, str]],
    duration: str,
    bar_size: str,
    what_to_show: str,
    use_rth: bool,
    request_sleep_seconds: float,
    chunk_days: int,
    max_new_chunks_per_run: int,
    attempted_so_far: int,
    skip_existing: bool,
    preserve_existing_kline_on_partial: bool,
    min_coverage_ratio: float,
    kline_root: Path,
    chunk_root: Path,
    root: Path,
) -> tuple[dict[str, Any], int, bool]:
    symbol = symbol.upper()
    kline_path = kline_root / f"{symbol}.parquet"
    symbol_chunk_root = chunk_root / symbol
    symbol_chunk_root.mkdir(parents=True, exist_ok=True)
    kline_exists_before = kline_path.exists()
    contract = stock_factory(symbol, "SMART", "USD")
    qualified = ib.qualifyContracts(contract)
    if qualified:
        contract = qualified[0]

    frames: list[pd.DataFrame] = []
    chunk_reports: list[dict[str, Any]] = []
    attempted = attempted_so_far
    wrote = False
    for chunk_index, (chunk_start, chunk_end) in enumerate(chunks):
        chunk_path = symbol_chunk_root / f"{chunk_start}_{chunk_end}.parquet"
        if skip_existing and chunk_path.exists():
            frame = _normalize_existing_frame(pd.read_parquet(chunk_path), symbol)
            if not frame.empty:
                frames.append(frame)
                chunk_reports.append(
                    {
                        "start": chunk_start,
                        "end": chunk_end,
                        "status": "skipped_existing_chunk",
                        "rows": int(len(frame)),
                        "path": _relpath(chunk_path, root),
                    }
                )
                continue
        if max_new_chunks_per_run > 0 and attempted >= max_new_chunks_per_run:
            chunk_reports.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "status": "deferred_run_limit",
                    "rows": 0,
                    "path": _relpath(chunk_path, root),
                }
            )
            continue
        if attempted > attempted_so_far or chunk_index > 0:
            time.sleep(max(0.0, float(request_sleep_seconds)))
        attempted += 1
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=_ibkr_end_datetime(chunk_end),
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=bool(use_rth),
                formatDate=2,
                keepUpToDate=False,
            )
            frame = _bars_to_frame(symbol, bars)
            frame = _filter_chunk(frame, chunk_start, chunk_end)
            frame = _normalize_existing_frame(frame, symbol)
            if frame.empty:
                chunk_reports.append(
                    {
                        "start": chunk_start,
                        "end": chunk_end,
                        "status": "empty",
                        "rows": 0,
                        "path": _relpath(chunk_path, root),
                        "ibkr_end_datetime": _ibkr_end_datetime(chunk_end),
                    }
                )
                continue
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(chunk_path, index=False)
            wrote = True
            frames.append(frame)
            chunk_reports.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "status": "available",
                    "rows": int(len(frame)),
                    "path": _relpath(chunk_path, root),
                    "ibkr_end_datetime": _ibkr_end_datetime(chunk_end),
                }
            )
        except Exception as exc:  # noqa: BLE001
            chunk_reports.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                    "ibkr_end_datetime": _ibkr_end_datetime(chunk_end),
                }
            )

    complete = bool(chunks) and all(
        str(item.get("status")) in {"available", "skipped_existing_chunk"}
        for item in chunk_reports
    )
    frame = _merge_frames(frames, symbol)
    raw_data_blockers: list[str] = []
    research_blockers: list[str] = []
    failed_count = sum(1 for item in chunk_reports if item.get("status") == "failed")
    empty_count = sum(1 for item in chunk_reports if item.get("status") in {"empty", "skipped_empty_existing_chunk_retry_required"})
    deferred_count = sum(1 for item in chunk_reports if str(item.get("status", "")).startswith("deferred"))
    if failed_count:
        raw_data_blockers.append(f"ibkr_{symbol.lower()}_minute_chunk_failed")
    if empty_count:
        raw_data_blockers.append(f"ibkr_{symbol.lower()}_minute_chunk_empty")
    if deferred_count:
        raw_data_blockers.append(f"ibkr_{symbol.lower()}_minute_backfill_deferred")
    if not complete:
        raw_data_blockers.append(f"ibkr_{symbol.lower()}_minute_backfill_incomplete")
    if frame.empty:
        raw_data_blockers.append(f"ibkr_{symbol.lower()}_minute_empty")

    quality = _quality_report(
        frame=frame,
        symbol=symbol,
        root=root,
        path=kline_path,
        requested_start_date=chunks[0][0] if chunks else "",
        requested_end_date=chunks[-1][1] if chunks else "",
        min_coverage_ratio=min_coverage_ratio,
    )
    raw_data_blockers.extend(str(item) for item in quality.get("raw_data_blockers", []))
    research_blockers.extend(raw_data_blockers)
    if not frame.empty:
        research_blockers.append(f"{symbol.lower()}_ibkr_minute_pit_adjustment_replay_required")

    if complete and not raw_data_blockers:
        frame.to_parquet(kline_path, index=False)
        wrote = True
        write_mode = "complete_backfill_promoted_to_main_kline"
        main_kline_write_suppressed = False
    elif preserve_existing_kline_on_partial and kline_exists_before:
        write_mode = "partial_chunks_not_promoted_existing_kline_retained"
        main_kline_write_suppressed = True
    else:
        write_mode = "partial_chunks_not_promoted_no_existing_kline"
        main_kline_write_suppressed = True

    report = {
        **quality,
        "raw_data_status": "available" if complete and not raw_data_blockers else "partial",
        "research_use_status": "blocked" if research_blockers else "pass",
        "chunk_reports": chunk_reports,
        "chunk_count": len(chunks),
        "available_chunk_count": sum(
            1 for item in chunk_reports if item.get("status") in {"available", "skipped_existing_chunk"}
        ),
        "failed_chunk_count": failed_count,
        "empty_chunk_count": empty_count,
        "deferred_chunk_count": deferred_count,
        "write_mode": write_mode,
        "main_kline_write_suppressed": main_kline_write_suppressed,
        "raw_data_blockers": _dedupe(raw_data_blockers),
        "research_blockers": _dedupe(research_blockers),
        "promotion_clean_allowed": False,
    }
    if kline_exists_before and main_kline_write_suppressed:
        report["retained_existing_main_kline_path"] = _relpath(kline_path, root)
    return report, attempted, wrote


def _quality_report(
    *,
    frame: pd.DataFrame,
    symbol: str,
    root: Path,
    path: Path,
    requested_start_date: str,
    requested_end_date: str,
    min_coverage_ratio: float,
) -> dict[str, Any]:
    if frame.empty:
        return {
            "path": _relpath(path, root),
            "rows": 0,
            "start": None,
            "end": None,
            "raw_data_blockers": [f"ibkr_{symbol.lower()}_minute_empty"],
            "coverage_check": _coverage_check(frame, requested_start_date, requested_end_date),
        }
    working = frame.copy()
    ohlc = working[["Open", "High", "Low", "Close"]].astype(float)
    non_positive = int((ohlc <= 0).any(axis=1).sum())
    invalid = int(
        (
            (ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1))
            | (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1))
        ).sum()
    )
    duplicates = int(working["datetime"].duplicated().sum())
    returns = _contiguous_minute_returns(working)
    max_abs_return = float(returns.abs().max()) if not returns.empty else 0.0
    coverage = _coverage_check(working, requested_start_date, requested_end_date)
    blockers: list[str] = []
    if non_positive:
        blockers.append(f"ibkr_{symbol.lower()}_minute_non_positive_ohlc")
    if invalid:
        blockers.append(f"ibkr_{symbol.lower()}_minute_invalid_ohlc")
    if duplicates:
        blockers.append(f"ibkr_{symbol.lower()}_minute_duplicate_timestamps")
    if float(coverage["coverage_ratio"]) < float(min_coverage_ratio):
        blockers.append(f"ibkr_{symbol.lower()}_minute_coverage_below_threshold")
    return {
        "path": _relpath(path, root),
        "rows": int(len(working)),
        "start": _ts_str(working["datetime"].min()),
        "end": _ts_str(working["datetime"].max()),
        "latest_close": _round(float(working["Close"].iloc[-1])),
        "duplicate_timestamps": duplicates,
        "invalid_ohlc_rows": invalid,
        "non_positive_ohlc_rows": non_positive,
        "max_abs_contiguous_1m_return": _round(max_abs_return),
        "coverage_check": coverage,
        "adjustment_policy": "ibkr_returned_values_no_pit_replay",
        "raw_data_blockers": blockers,
    }


def _normalize_existing_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty:
        return _empty_frame()
    working = frame.copy()
    if "datetime" not in working.columns:
        return _empty_frame()
    if "symbol" not in working.columns:
        working["symbol"] = symbol.upper()
    if "bar_start_utc" not in working.columns:
        working["bar_start_utc"] = working["datetime"]
    if "bar_end_utc" not in working.columns:
        working["bar_end_utc"] = pd.to_datetime(working["datetime"], utc=True) + pd.Timedelta(minutes=1)
    if "available_time" not in working.columns:
        working["available_time"] = working["bar_end_utc"]
    for column in ("datetime", "bar_start_utc", "bar_end_utc", "available_time"):
        working[column] = pd.to_datetime(working[column], utc=True)
    for column in ("Open", "High", "Low", "Close", "Volume"):
        working[column] = pd.to_numeric(working[column], errors="coerce")
    for raw_column, column in (
        ("RawOpen", "Open"),
        ("RawHigh", "High"),
        ("RawLow", "Low"),
        ("RawClose", "Close"),
    ):
        if raw_column not in working.columns:
            working[raw_column] = working[column]
    if "source" not in working.columns:
        working["source"] = "ibkr_historical_data"
    if "interval" not in working.columns:
        working["interval"] = "1m"
    working["data_version"] = "ibkr_historical_intraday_backfill_v1"
    working["adjustment_policy"] = "ibkr_returned_values_no_pit_replay"
    if "quality_flags" not in working.columns:
        working["quality_flags"] = ""
    repaired_high = working[["Open", "High", "Low", "Close"]].max(axis=1)
    repaired_low = working[["Open", "High", "Low", "Close"]].min(axis=1)
    working["High"] = repaired_high
    working["Low"] = repaired_low
    return (
        working.dropna(subset=["datetime", "Open", "High", "Low", "Close"])
        .sort_values("datetime")
        .drop_duplicates("datetime", keep="last")
        .reset_index(drop=True)
    )


def _filter_chunk(frame: pd.DataFrame, chunk_start: str, chunk_end: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    working = frame.copy()
    working["datetime"] = pd.to_datetime(working["datetime"], utc=True)
    start = pd.Timestamp(chunk_start, tz="UTC")
    end = pd.Timestamp(chunk_end, tz="UTC") + pd.Timedelta(days=1)
    return working[(working["datetime"] >= start) & (working["datetime"] < end)].reset_index(drop=True)


def _merge_frames(frames: Iterable[pd.DataFrame], symbol: str) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return _empty_frame()
    merged = pd.concat(non_empty, ignore_index=True)
    merged["symbol"] = symbol.upper()
    return merged.sort_values("datetime").drop_duplicates("datetime", keep="last").reset_index(drop=True)


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "datetime",
            "bar_start_utc",
            "bar_end_utc",
            "available_time",
            "symbol",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "RawOpen",
            "RawHigh",
            "RawLow",
            "RawClose",
            "source",
            "interval",
            "data_version",
            "adjustment_policy",
            "quality_flags",
        ]
    )


def _month_chunks(start_date: str, end_date: str) -> list[tuple[str, str]]:
    start = pd.Timestamp(date.fromisoformat(start_date))
    end = pd.Timestamp(date.fromisoformat(end_date))
    if start > end:
        return []
    chunks: list[tuple[str, str]] = []
    current = start
    while current <= end:
        chunk_end = min(current + pd.DateOffset(months=1) - pd.Timedelta(days=1), end)
        chunks.append((current.date().isoformat(), chunk_end.date().isoformat()))
        current = chunk_end + pd.Timedelta(days=1)
    return chunks


def _day_chunks(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    start = pd.Timestamp(date.fromisoformat(start_date))
    end = pd.Timestamp(date.fromisoformat(end_date))
    if start > end:
        return []
    chunks: list[tuple[str, str]] = []
    current = start
    step_days = max(1, int(chunk_days))
    while current <= end:
        chunk_end = min(current + pd.Timedelta(days=step_days - 1), end)
        chunks.append((current.date().isoformat(), chunk_end.date().isoformat()))
        current = chunk_end + pd.Timedelta(days=1)
    return chunks


def _ibkr_end_datetime(chunk_end: str) -> str:
    end = datetime.combine(date.fromisoformat(chunk_end), dt_time(23, 59, 59), tzinfo=timezone.utc)
    return end.strftime("%Y%m%d %H:%M:%S UTC")


def _coverage_check(frame: pd.DataFrame, requested_start_date: str, requested_end_date: str) -> dict[str, Any]:
    sessions = pd.bdate_range(start=requested_start_date, end=requested_end_date)
    conservative_expected_rows = int(len(sessions) * 250)
    actual_rows = int(len(frame))
    coverage_ratio = actual_rows / conservative_expected_rows if conservative_expected_rows else 0.0
    return {
        "requested_start_date": requested_start_date,
        "requested_end_date": requested_end_date,
        "conservative_expected_min_rows": conservative_expected_rows,
        "actual_rows": actual_rows,
        "coverage_ratio": _round(coverage_ratio),
        "note": "Conservative lower bound assumes 250 observed minute bars per US business day.",
    }


def _contiguous_minute_returns(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    working = frame.sort_values("datetime").copy()
    dt = pd.to_datetime(working["datetime"], utc=True)
    same_session = dt.dt.tz_convert("America/New_York").dt.date == dt.shift(1).dt.tz_convert("America/New_York").dt.date
    contiguous = dt.diff() <= pd.Timedelta(minutes=2)
    returns = working["Close"].astype(float).pct_change(fill_method=None)
    return returns.where(same_session & contiguous).dropna()


def _summary(symbol_reports: dict[str, Any]) -> dict[str, Any]:
    available = [row for row in symbol_reports.values() if row.get("raw_data_status") == "available"]
    rows = [int(row.get("rows", 0) or 0) for row in symbol_reports.values()]
    starts = [str(row.get("start")) for row in symbol_reports.values() if row.get("start")]
    ends = [str(row.get("end")) for row in symbol_reports.values() if row.get("end")]
    return {
        "available_symbol_count": len(available),
        "min_rows": min(rows) if rows else 0,
        "max_rows": max(rows) if rows else 0,
        "common_start_timestamp": max(starts) if starts else None,
        "common_end_timestamp": min(ends) if ends else None,
        "earliest_any_timestamp": min(starts) if starts else None,
        "latest_any_timestamp": max(ends) if ends else None,
    }


def _adjustment_controls() -> dict[str, Any]:
    return {
        "raw_intraday_retained": True,
        "front_adjusted_output_written": False,
        "back_adjusted_output_written": False,
        "back_adjusted_for_signal_use_allowed": False,
        "pit_adjustment_replay_required_before_research_use": True,
        "no_lookahead_rule": "Do not apply full-history future adjustment factors to historical minute signals.",
        "allowed_adjustment_rule": "Only ex-date-known split/dividend factors with available_time <= decision_time may be applied in a separate PIT factor replay table.",
    }


def _data_limitations() -> dict[str, Any]:
    return {
        "ibkr_role": "supplemental broker historical market data, not standalone production PIT master data",
        "minute_bars_are_raw": True,
        "point_in_time_adjustment_replay_included": False,
        "research_clean_approval_granted": False,
        "account_or_order_endpoint_used": False,
    }


def _set_ibkr_request_timeout(ib: IbkrClient, timeout_seconds: float) -> None:
    try:
        setattr(ib, "RequestTimeout", max(1.0, float(timeout_seconds)))
    except Exception:  # noqa: BLE001
        return None


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill IBKR raw 1-minute bars for supplemental US ETF research.")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4002)
    parser.add_argument("--client-id", type=int, default=81)
    parser.add_argument("--duration", default="1 M")
    parser.add_argument("--bar-size", default="1 min")
    parser.add_argument("--what-to-show", default="TRADES")
    parser.add_argument("--use-rth", action="store_true")
    parser.add_argument("--execute-network", action="store_true")
    parser.add_argument("--request-sleep-seconds", type=float, default=1.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--connect-timeout-seconds", type=float, default=5.0)
    parser.add_argument("--chunk-days", type=int, default=0)
    parser.add_argument("--max-new-chunks-per-run", type=int, default=0)
    parser.add_argument("--max-new-chunks-per-symbol", type=int, default=0)
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("--min-coverage-ratio", type=float, default=0.80)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    payload = import_ibkr_minute_backfill(
        repo_root=Path(args.repo_root),
        symbols=[item.strip() for item in args.symbols.split(",") if item.strip()],
        start_date=args.start_date,
        end_date=args.end_date,
        host=args.host,
        port=int(args.port),
        client_id=int(args.client_id),
        duration=args.duration,
        bar_size=args.bar_size,
        what_to_show=args.what_to_show,
        use_rth=bool(args.use_rth),
        execute_network=bool(args.execute_network),
        request_sleep_seconds=float(args.request_sleep_seconds),
        request_timeout_seconds=float(args.request_timeout_seconds),
        connect_timeout_seconds=float(args.connect_timeout_seconds),
        chunk_days=int(args.chunk_days),
        max_new_chunks_per_run=int(args.max_new_chunks_per_run),
        max_new_chunks_per_symbol=int(args.max_new_chunks_per_symbol),
        skip_existing=not bool(args.no_skip_existing),
        min_coverage_ratio=float(args.min_coverage_ratio),
        output_root=Path(args.output_root),
        report_path=Path(args.report),
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "research_ready_status": payload["research_ready_status"],
                "report": payload["report_path"],
                "attempted_new_chunk_count": payload.get("attempted_new_chunk_count", 0),
                "blockers": payload.get("blockers", []),
                "summary": payload.get("summary", {}),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
